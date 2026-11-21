"""UE 5.8.4 -> Maya 2023 previs: static geometry + world placement, no shaders."""

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .package import sha256_file
from .versions import require_unreal_version
from .usd_scene import inspect_stage
from .usd_options import normalize_options, choose_geometry
from .unreal_cameras import CAMERA_TYPES, inspect_cameras, write_cameras


def _vector(vector):
    # Same basis as UE's native USD writer for a Y-up, centimeter stage.
    return (float(vector.x), float(vector.z), float(vector.y))


def _world_matrix(transform, unreal):
    """Sample transformed basis vectors; retain scale/mirroring, avoid Euler angles."""
    from pxr import Gf

    origin = _vector(transform.transform_location(unreal.Vector(0, 0, 0)))
    rows = []
    for basis in ((1, 0, 0), (0, 0, 1), (0, 1, 0)):
        position = _vector(transform.transform_location(unreal.Vector(*basis)))
        rows.append(tuple(position[i] - origin[i] for i in range(3)) + (0.0,))
    rows.append(origin + (1.0,))
    if not all(math.isfinite(value) for row in rows for value in row):
        raise ValueError("Non-finite world transform.")
    return Gf.Matrix4d(*[value for row in rows for value in row])


COMPONENT_TYPES = {
    "StaticMeshComponent",
    "InstancedStaticMeshComponent",
    "HierarchicalInstancedStaticMeshComponent",
}


def _inspect(actors, unreal, options=None):
    """Snapshot existing components only: never rerun a construction script."""
    from pxr import Gf

    accepted, skipped = [], []
    options = normalize_options(options)
    choices = {}

    def skip(actor, reason, component=None, instance=None):
        skipped.append(
            {
                "actor": actor.get_path_name(),
                "label": actor.get_actor_label(),
                "component": component.get_path_name() if component else None,
                "instance_index": instance,
                "type": (
                    component.get_class().get_name() if component else actor.get_class().get_name()
                ),
                "reasons": [reason],
            }
        )

    for actor in dict.fromkeys(actors):
        skipped_before = len(skipped)
        foliage_type = getattr(unreal, "InstancedFoliageActor", None)
        if foliage_type and isinstance(actor, foliage_type):
            skip(actor, "植被系统尚未验收，不能当作普通 HISM 导出")
            continue
        camera_actor = isinstance(actor, unreal.CameraActor)
        if actor.get_editor_property("hidden") and not camera_actor:
            skip(actor, "Actor 设置为 Hidden In Game")
            continue
        components = list(actor.get_components_by_class(unreal.SceneComponent))
        found_mesh = False
        for component in components:
            kind = component.get_class().get_name()
            if kind in CAMERA_TYPES:
                found_mesh = True  # Camera diagnostics are collected separately.
                continue
            if camera_actor and component.get_editor_property("is_editor_only"):
                continue
            if kind not in COMPONENT_TYPES:
                # SceneComponent is a non-rendering hierarchy node. Other
                # component types are reported rather than silently omitted.
                if kind != "SceneComponent" and not component.get_editor_property("is_editor_only"):
                    skip(actor, "未支持此组件类型：" + kind, component)
                continue
            found_mesh = True
            mesh = component.get_editor_property("static_mesh")
            reason = None
            if actor.get_editor_property("hidden"):
                reason = "Actor 设置为 Hidden In Game"
            elif mesh is None:
                reason = "组件未指定网格"
            elif component.get_editor_property(
                "hidden_in_game"
            ) or not component.get_editor_property("visible"):
                reason = "组件隐藏或不可见"
            elif component.get_editor_property("is_editor_only"):
                reason = "仅编辑器组件"
            if reason:
                skip(actor, reason, component)
                continue
            try:
                source = mesh.get_path_name()
                if source not in choices:
                    choices[source] = choose_geometry(
                        mesh.get_num_lods(),
                        bool(
                            mesh.get_editor_property("nanite_settings").get_editor_property(
                                "enabled"
                            )
                        ),
                        options,
                    )
                choice = choices[source]
                if mesh.get_num_triangles(choice["effective_lod"]) <= 0:
                    raise ValueError("选中的 LOD 没有可导出的三角面。")
                forced_lod = int(component.get_editor_property("forced_lod_model"))
                world = _world_matrix(component.get_world_transform(), unreal)
                instanced = kind != "StaticMeshComponent"
                count = component.get_instance_count() if instanced else 1
                if not count:
                    skip(actor, "实例组件没有实例", component)
                for index in range(count):
                    instance = index if instanced else None
                    try:
                        matrix = world
                        if instanced:
                            local = component.get_instance_transform(index, world_space=False)
                            if local is None:
                                raise ValueError("无法读取实例变换")
                            # Compose full matrices, retaining shear introduced
                            # by a rotated instance under nonuniform scale.
                            matrix = _world_matrix(local, unreal) * world
                        determinant = matrix.GetDeterminant()
                        if not math.isfinite(determinant) or abs(determinant) < 1e-12:
                            raise ValueError("零缩放、近奇异或非有限变换")
                        accepted.append(
                            {
                                "actor": actor,
                                "component": component,
                                "mesh": mesh,
                                "instance_index": instance,
                                "matrix": Gf.Matrix4d(matrix),
                                "type": kind,
                                "geometry_choice": dict(choice),
                                "component_forced_lod": forced_lod,
                            }
                        )
                    except (ValueError, RuntimeError) as error:
                        skip(actor, str(error), component, instance)
            except (ValueError, RuntimeError) as error:
                skip(actor, str(error), component)
        if not found_mesh and len(skipped) == skipped_before:
            skip(actor, "没有可导出的静态网格组件")
    return accepted, skipped


def _placement_info(item):
    actor, component, mesh = item["actor"], item["component"], item["mesh"]
    index = item["instance_index"]
    identity = component.get_path_name() + ("#" + str(index) if index is not None else "")
    return {
        "id": identity,
        "actor": actor.get_path_name(),
        "label": actor.get_actor_label(),
        "component": component.get_path_name(),
        "component_name": component.get_name(),
        "type": item["type"],
        "instance_index": index,
        "mesh": mesh.get_path_name(),
        "geometry_choice": dict(item["geometry_choice"]),
        "component_forced_lod": item["component_forced_lod"],
    }


def _statistics(accepted):
    assets = {}
    for item in accepted:
        mesh = item["mesh"]
        source = mesh.get_path_name()
        if source not in assets:
            choice = item["geometry_choice"]
            lod = choice["effective_lod"]
            assets[source] = {
                "triangles": mesh.get_num_triangles(lod),
                "vertices": mesh.get_num_vertices(lod),
                "lod_count": mesh.get_num_lods(),
                "lod_index": lod,
                "placements": 0,
                "geometry_source": choice["geometry_source"],
                "geometry_choice": dict(choice),
            }
        assets[source]["placements"] += 1
    return {
        "unique_triangles": sum(a["triangles"] for a in assets.values()),
        "placed_triangles": sum(a["triangles"] * a["placements"] for a in assets.values()),
        "unique_vertices": sum(a["vertices"] for a in assets.values()),
        "assets": assets,
        "proxy_assets": sum(a["geometry_choice"]["nanite"] for a in assets.values()),
        "proxy_placements": sum(
            a["placements"] for a in assets.values() if a["geometry_choice"]["nanite"]
        ),
        "lod_fallback_assets": sum(a["geometry_choice"]["lod_fallback"] for a in assets.values()),
    }


def inspect_selected(options=None):
    return inspect_scope("selection", options)


def _ready():
    import unreal

    require_unreal_version(unreal.SystemLibrary.get_engine_version())
    try:
        from pxr import Usd

        unreal.StaticMeshExporterUsd
    except (ImportError, AttributeError) as error:
        raise RuntimeError(
            "请启用 USD Importer 和 Python Editor Script Plugin，然后重启 Unreal。"
        ) from error
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError("请先停止 Play / Simulate，再检查或导出。")


def collect_actors(scope="selection"):
    import unreal

    _ready()
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if scope == "selection":
        return list(subsystem.get_selected_level_actors())
    if scope == "loaded":
        return list(subsystem.get_all_level_actors())
    raise ValueError("未知导出范围：" + str(scope))


def inspect_scope(scope="selection", options=None):
    import unreal

    actors = collect_actors(scope)
    options = normalize_options(options)
    accepted, skipped = _inspect(actors, unreal, options)
    cameras, camera_skips = inspect_cameras(actors, unreal, options["include_cameras"])
    skipped += camera_skips
    stats = _statistics(accepted)
    return {
        "scope": scope,
        "options": options,
        "scanned": len(actors),
        "accepted_count": len(accepted),
        "actor_count": len(
            {i["actor"].get_path_name() for i in accepted} | {c["actor"] for c in cameras}
        ),
        "component_count": len({i["component"].get_path_name() for i in accepted}),
        "instance_count": sum(i["instance_index"] is not None for i in accepted),
        "asset_count": len(stats["assets"]),
        "statistics": stats,
        "accepted": [_placement_info(item) for item in accepted],
        "cameras": cameras,
        "camera_count": len(cameras),
        "skipped": skipped,
    }


def locate_item(item):
    """Explicit user operation: select the owner and frame this component/instance."""
    import unreal

    _ready()
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = next(
        (a for a in subsystem.get_all_level_actors() if a.get_path_name() == item.get("actor")),
        None,
    )
    if actor is None:
        raise ValueError("源 Actor 已删除或未加载，请重新检查。")
    component = next(
        (
            c
            for c in actor.get_components_by_class(unreal.SceneComponent)
            if c.get_path_name() == item.get("component")
        ),
        None,
    )
    index = item.get("instance_index")
    if item.get("component") and component is None:
        raise ValueError("源组件已变化，请重新检查。")
    origin, extent = actor.get_actor_bounds(False)
    if component is not None:
        world = component.get_world_transform()
        if index is not None:
            if index < 0 or index >= component.get_instance_count():
                raise ValueError("实例索引已变化，请重新检查。")
            local = component.get_instance_transform(index, world_space=False)
            origin = world.transform_location(local.translation)
            # A conservative framing size; selection remains the owner Actor.
            extent = unreal.Vector(150, 150, 150)
        else:
            origin = world.translation
    subsystem.set_selected_level_actors([actor])
    distance = max(300.0, extent.length() * 3.0)
    location = origin + unreal.Vector(-distance, -distance, distance * 0.6)
    rotation = unreal.MathLibrary.find_look_at_rotation(location, origin)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        location, rotation
    )
    return {
        "actor": actor.get_path_name(),
        "component": component.get_path_name() if component else None,
        "instance_index": index,
        "target": [origin.x, origin.y, origin.z],
    }


def _export_mesh(mesh, path, unreal, use_source_data=False, lod_index=0):
    """Use native geometry conversion, then strip UE shading and absolute asset IDs."""
    from pxr import Usd, UsdGeom, UsdShade, Sdf

    options = unreal.StaticMeshExporterUSDOptions()
    settings = options.get_editor_property("stage_options")
    settings.set_editor_property("up_axis", unreal.UsdUpAxis.Y_AXIS)
    settings.set_editor_property("meters_per_unit", 0.01)
    options.set_editor_property("stage_options", settings)
    settings = options.get_editor_property("mesh_asset_options")
    for key, value in {
        "bake_materials": False,
        "use_payload": False,
        "lowest_mesh_lod": lod_index,
        "highest_mesh_lod": lod_index,
        "export_static_mesh_source_data": bool(use_source_data),
    }.items():
        settings.set_editor_property(key, value)
    options.set_editor_property("mesh_asset_options", settings)
    task = unreal.AssetExportTask()
    for key, value in {
        "object": mesh,
        "filename": str(path),
        "options": options,
        "exporter": unreal.StaticMeshExporterUsd(),
        "automated": True,
        "prompt": False,
        "replace_identical": False,
    }.items():
        task.set_editor_property(key, value)
    success = unreal.Exporter.run_asset_export_task(task)
    if not success or task.errors or not path.is_file():
        raise RuntimeError(
            "USD mesh export failed for {}: {}".format(mesh.get_path_name(), list(task.errors))
        )
    stage = Usd.Stage.Open(str(path))
    if stage is None or not stage.GetDefaultPrim():
        raise RuntimeError("USD mesh asset has no default prim: " + str(path))
    remove = []
    for prim in stage.Traverse():
        prim.ClearMetadata("assetInfo")
        if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
            remove.append(str(prim.GetPath()))
        for prop in list(prim.GetProperties()):
            if prop.GetName().startswith("material:binding"):
                prim.RemoveProperty(prop.GetName())
        if prim.IsA(UsdGeom.Mesh):
            UsdGeom.Mesh(prim).CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    for prim_path in sorted(remove, key=len, reverse=True):
        stage.RemovePrim(prim_path)
    # Put the native writer's default prim under an asset Xform. Referencing
    # that shared Xform directly at an instance root gives one USD prototype
    # per asset, and works with Maya USD 0.16's instance importer.
    original = stage.GetDefaultPrim().GetPath()
    wrapper_path = "/UE_MeshAsset"
    while stage.GetPrimAtPath(wrapper_path):
        wrapper_path += "_Root"
    wrapper = UsdGeom.Xform.Define(stage, wrapper_path).GetPrim()
    if not Sdf.CopySpec(
        stage.GetRootLayer(), original, stage.GetRootLayer(), wrapper.GetPath().AppendChild("Mesh")
    ):
        raise RuntimeError("无法创建兼容 Maya 的网格资源根。")
    stage.SetDefaultPrim(wrapper)
    stage.RemovePrim(original)
    stage.GetRootLayer().Save()
    if path.suffix == ".usdc":
        with path.open("rb") as stream:
            header = stream.read(16)
        if header[:8] != b"PXR-USDC" or tuple(header[8:11]) > (0, 8, 0):
            raise RuntimeError("USDC 编码或 Crate 版本不在 Maya 2023 验收范围内，请改用 USDA。")
    return inspect_stage(path)


def export_actors(actors, output_parent=None, scope="explicit", progress=None, options=None):
    """Export an explicit actor list without changing selection or source data."""
    import unreal

    started = time.perf_counter()
    options = normalize_options(options)
    _ready()
    try:
        from pxr import Usd, UsdGeom, Tf

        exporter_type = unreal.StaticMeshExporterUsd
    except (ImportError, AttributeError) as error:
        raise RuntimeError(
            "Enable USD Importer and Python Editor Script Plugin, then restart UE."
        ) from error
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    if editor.get_game_world() is not None:
        raise RuntimeError("Stop Play/Simulate before exporting.")
    actors = list(dict.fromkeys(actors))
    if scope not in ("explicit", "selection", "loaded"):
        raise ValueError("未知导出范围。")
    accepted, skipped = _inspect(actors, unreal, options)
    cameras, camera_skips = inspect_cameras(actors, unreal, options["include_cameras"])
    skipped += camera_skips
    if not accepted and not cameras:
        raise ValueError(
            "没有可导出的静态组件、实例或摄影机。" + json.dumps(skipped[:20], ensure_ascii=False)
        )
    if output_parent is None:
        output_parent = (
            Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()))
            / "UEToMayaUSD"
        )
    package = Path(output_parent).expanduser().resolve() / (
        "previs_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
    )
    (package / "Assets").mkdir(parents=True, exist_ok=False)
    statistics = _statistics(accepted)
    total = len(statistics["assets"]) + len(accepted) + 3
    completed = 0

    def advance(message):
        nonlocal completed
        completed += 1
        if progress:
            progress(completed, total, message)

    try:
        stage = Usd.Stage.CreateNew(str(package / "scene.usda"))
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        root = UsdGeom.Xform.Define(stage, "/UE_Previs").GetPrim()
        stage.SetDefaultPrim(root)
        assets, records, actor_records = {}, [], {}
        for item in accepted:
            actor, component, mesh = item["actor"], item["component"], item["mesh"]
            source = mesh.get_path_name()
            if source not in assets:
                choice = item["geometry_choice"]
                suffix = hashlib.sha256(
                    (source + json.dumps(choice, sort_keys=True)).encode("utf-8")
                ).hexdigest()[:12]
                relative = "Assets/{}_LOD{}_{}.{}".format(
                    Tf.MakeValidIdentifier(mesh.get_name()),
                    choice["effective_lod"],
                    suffix,
                    options["asset_format"],
                )
                asset_started = time.perf_counter()
                geometry_info = _export_mesh(
                    mesh, package / relative, unreal, lod_index=choice["effective_lod"]
                )
                actual_triangles = sum(m["triangles"] for m in geometry_info["meshes"])
                if actual_triangles != statistics["assets"][source]["triangles"]:
                    raise RuntimeError(
                        "导出实际三角面与选定渲染 LOD 不同：{} ({} / {})".format(
                            source, actual_triangles, statistics["assets"][source]["triangles"]
                        )
                    )
                assets[source] = {
                    "file": relative,
                    "geometry": geometry_info,
                    "geometry_choice": dict(choice),
                    "statistics": statistics["assets"][source],
                    "bytes": (package / relative).stat().st_size,
                    "export_seconds": time.perf_counter() - asset_started,
                }
                advance("已导出资源：" + mesh.get_name())
            actor_id = actor.get_path_name()
            info = _placement_info(item)
            suffix = hashlib.sha256(info["id"].encode("utf-8")).hexdigest()[:12]
            prim_path = "/UE_Previs/{}_{}_{}".format(
                Tf.MakeValidIdentifier(actor.get_actor_label()),
                Tf.MakeValidIdentifier(component.get_name()),
                suffix,
            )
            actor_prim = UsdGeom.Xform.Define(stage, prim_path)
            actor_prim.AddTransformOp().Set(item["matrix"])
            actor_prim.GetPrim().SetCustomDataByKey("ueActorPath", actor_id)
            actor_prim.GetPrim().SetCustomDataByKey("ueComponentPath", component.get_path_name())
            if item["instance_index"] is not None:
                actor_prim.GetPrim().SetCustomDataByKey("ueInstanceIndex", item["instance_index"])
            # Old Maya USD cannot reliably import an instanceable Mesh root.
            # Use an Xform instance root containing the referenced mesh.
            geometry = UsdGeom.Xform.Define(stage, prim_path + "/Geometry").GetPrim()
            geometry.GetReferences().AddReference(assets[source]["file"])
            if item["instance_index"] is not None:
                geometry.SetInstanceable(True)
            info.update(prim=prim_path, matrix=[list(row) for row in item["matrix"]])
            records.append(info)
            actor_records[actor_id] = {
                "actor": actor_id,
                "label": actor.get_actor_label(),
                "parent_actor": (
                    actor.get_attach_parent_actor().get_path_name()
                    if actor.get_attach_parent_actor()
                    else None
                ),
            }
            advance("已写入摆放：" + actor.get_actor_label())
        write_cameras(stage, cameras)
        for camera in cameras:
            actor_records.setdefault(
                camera["actor"],
                {"actor": camera["actor"], "label": camera["label"], "parent_actor": None},
            )
        advance("已写入 {} 个静态摄影机快照".format(len(cameras)))
        stage.GetRootLayer().Save()
        inspection = (
            inspect_stage(package / "scene.usda")
            if accepted
            else {"up_axis": "Y", "meters_per_unit": 0.01, "meshes": []}
        )
        if len(inspection["meshes"]) != len(accepted):
            raise RuntimeError("USD mesh count does not match the accepted actor count.")
        advance("场景几何和引用检查通过")
        files = {
            path.relative_to(package).as_posix(): sha256_file(path)
            for path in package.rglob("*")
            if path.suffix in (".usd", ".usda", ".usdc")
        }
        report = {
            "format": "ue-maya-usd-previs",
            "version": 4,
            "tool_version": "0.5.0",
            "options": options,
            "engine_version": unreal.SystemLibrary.get_engine_version(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "scope": {
                "mode": scope,
                "scanned_count": len(actors),
                "loaded_only": scope == "loaded",
                "note": (
                    "Only currently loaded actors; unloaded cells/data layers are not included"
                    if scope == "loaded"
                    else "Explicit actors only; no automatic descendant expansion"
                ),
            },
            "root_layer": "scene.usda",
            "actors": list(actor_records.values()),
            "placements": records,
            "cameras": cameras,
            "statistics": statistics,
            "skipped": skipped,
            "assets": assets,
            "files": files,
            "inspection": inspection,
            "geometry_source": "selected render LOD; Nanite assets use approximate render proxies only; no source-data export",
            "metrics": {
                "usd_bytes": sum((package / name).stat().st_size for name in files),
                "geometry_bytes": sum(a["bytes"] for a in assets.values()),
                "usd_export_seconds": time.perf_counter() - started,
                "timing_scope": "inspection, USD geometry/layout and file hashing; before JSON report write",
            },
            "placement": "world transforms; flat actor layout; Y-up centimeters",
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
            raise ValueError("来源报告超过 16 MiB 支持范围，请缩小导出范围或分批导出。")
        (package / "usd_manifest.json").write_text(payload, encoding="utf-8")
        advance("交付包完成")
    except Exception as error:
        (package / "EXPORT_FAILED.txt").write_text(str(error), encoding="utf-8")
        raise RuntimeError("USD 导出未完成，诊断目录：{}\n{}".format(package, error)) from error
    for skipped_actor in skipped:
        unreal.log_warning(
            "Skipped {}: {}".format(skipped_actor["label"], "; ".join(skipped_actor["reasons"]))
        )
    unreal.log(
        "USD previs: {} actors, {} placements, {} assets -> {}".format(
            len(actor_records), len(records), len(assets), package / "scene.usda"
        )
    )
    return str(package)


def export_selected(output_parent=None, options=None):
    return export_scope("selection", output_parent, options=options)


def export_scope(scope="selection", output_parent=None, progress=None, options=None):
    return export_actors(collect_actors(scope), output_parent, scope, progress, options)


def install_menu():
    import unreal

    menus = unreal.ToolMenus.get()
    menu = menus.extend_menu("LevelEditor.MainMenu.Tools")
    menu.add_section("UEToMayaUSD", "UE to Maya - USD Previs")
    entry = unreal.ToolMenuEntry(name="UEToMayaUSD.Export", type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label("UE → Maya USD · 导出面板")
    entry.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        "",
        "from ue_maya_bridge.unreal_ui import show; show()",
    )
    menu.add_menu_entry("UEToMayaUSD", entry)
    menus.refresh_all_widgets()
