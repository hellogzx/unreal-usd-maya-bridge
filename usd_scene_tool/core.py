"""Read-only USD inspection and additive Maya operations. No scene resets."""

import json
import math
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

SUFFIXES = {".usd", ".usda", ".usdc"}


class ToolError(RuntimeError):
    pass


def _maya_path(filename):
    """Maya 2023 command flags can lose Unicode on non-Chinese Windows locales."""
    path = str(Path(filename).resolve())
    if path.isascii():
        return Path(path).as_posix()
    import os

    if os.name == "nt":
        import ctypes

        function = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        function.restype = ctypes.c_uint
        buffer = ctypes.create_unicode_buffer(32768)
        size = function(path, buffer, len(buffer))
        if 0 < size < len(buffer) and buffer.value.isascii():
            # Windows aliases use uppercase .USD; the old USD registry's
            # extension lookup is case-sensitive even on Windows.
            short = Path(buffer.value)
            return short.with_suffix(short.suffix.lower()).as_posix()
    raise ToolError(
        "Maya 2023 无法安全传递此中文/非 ASCII 路径。请把完整 USD 包或工具移至英文目录后重试。"
    )


def environment():
    import maya.cmds as cmds

    version = cmds.about(version=True)
    if not str(version).startswith("2023"):
        raise ToolError("第一版仅验收 Maya 2023，当前版本为 " + str(version))
    if not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaUsdPlugin", quiet=True)
    # Loading the Maya USD plugin also establishes its bundled USD SDK paths.
    import mayaUsd.lib  # noqa: F401
    from pxr import Usd

    return {
        "maya": str(version),
        "maya_usd": cmds.pluginInfo("mayaUsdPlugin", query=True, version=True),
        "usd_sdk": list(Usd.GetVersion()),
    }


def _value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "path"):
        return value.path
    try:
        return [_value(v) for v in value]
    except TypeError:
        return str(value)


def inspect_file(filename):
    env = environment()
    from pxr import Usd, UsdGeom, UsdShade, UsdUtils

    path = Path(filename).expanduser().resolve()
    if path.suffix.lower() not in SUFFIXES:
        raise ToolError("请选择 .usd、.usda 或 .usdc 文件。")
    if not path.is_file():
        raise ToolError("找不到 USD 文件：" + str(path))
    try:
        stage = Usd.Stage.Open(str(path))
    except Exception as exc:
        raise ToolError("USD 文件无法解析：" + str(exc)) from exc
    if not stage:
        raise ToolError("无法打开 USD Stage。")
    report = dict(
        env,
        path=str(path),
        up_axis=str(UsdGeom.GetStageUpAxis(stage)),
        meters_per_unit=UsdGeom.GetStageMetersPerUnit(stage),
        meshes=0,
        instances=0,
        face_subsets=0,
        primitives=0,
        materials=[],
        cameras=[],
        camera_count=0,
        missing_assets=[],
        warnings=[],
        errors=[],
        native_errors=[],
        layers=[],
    )
    if hasattr(stage, "GetCompositionErrors"):
        report["errors"].extend(str(error) for error in stage.GetCompositionErrors())
    try:
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(path))
        report["layers"] = sorted(set(str(layer.realPath or layer.identifier) for layer in layers))
        for asset in sorted(set(str(p) for p in unresolved)):
            if Path(asset).suffix.lower() in SUFFIXES:
                report["errors"].append("缺失 USD 依赖：" + asset)
            else:
                report["missing_assets"].append(asset)
        if report["missing_assets"]:
            report["warnings"].append(
                "缺失或无法解析的贴图/资产：{} 项。".format(len(report["missing_assets"]))
            )
    except Exception as exc:
        report["errors"].append("无法完成依赖检查：" + str(exc))

    # Version one is deliberately limited to the unit/axis combination verified
    # against this installation. Neither path changes Maya's global units.
    if report["up_axis"] != "Y" or not math.isclose(report["meters_per_unit"], 0.01, abs_tol=1e-9):
        report["errors"].append(
            "第一版要求 USD 为 Y-up、厘米（metersPerUnit=0.01）。请先在源端转换。"
        )

    bound_materials = set()
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        report["primitives"] += 1
        prim_type = str(prim.GetTypeName())
        if prim_type and prim_type not in {
            "Mesh",
            "Xform",
            "Scope",
            "Material",
            "Shader",
            "NodeGraph",
            "GeomSubset",
            "Camera",
        }:
            report["native_errors"].append(
                "原生模式尚未支持对象类型 {}：{}".format(prim_type, prim.GetPath())
            )
        if not hasattr(stage, "GetCompositionErrors") and not prim.IsInstanceProxy():
            report["errors"].extend(str(error) for error in prim.GetPrimIndex().localErrors)
        if prim.IsInstance():
            report["instances"] += 1
        if prim.IsA(UsdGeom.Mesh):
            report["meshes"] += 1
            mesh = UsdGeom.Mesh(prim)
            if mesh.GetPointsAttr().ValueMightBeTimeVarying():
                report["native_errors"].append(
                    "第一版仅导入静态网格，检测到动画：" + str(prim.GetPath())
                )
            bindings = [UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]]
            subsets = UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets()
            report["face_subsets"] += len(subsets)
            for subset in subsets:
                bindings.append(UsdShade.MaterialBindingAPI(subset).ComputeBoundMaterial()[0])
            for material in bindings:
                if material:
                    bound_materials.add(str(material.GetPath()))
        # Transform animation is excluded too: importing a static snapshot must
        # not masquerade as transferring animation.
        for attr in prim.GetAttributes():
            if str(attr.GetName()).startswith("xformOp:") and attr.ValueMightBeTimeVarying():
                report["native_errors"].append("检测到变换动画：" + str(prim.GetPath()))
                break
    geometry_errors = list(report["native_errors"])
    # Instance-proxy materials must be checked too: their bound paths are in the
    # instance namespace. Plain stage.Traverse() silently omits those materials.
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdShade.Material):
            continue
        material = UsdShade.Material(prim)
        shader, _, _ = material.ComputeSurfaceSource()
        item = {
            "path": str(prim.GetPath()),
            "bound": str(prim.GetPath()) in bound_materials,
            "shader_id": "",
            "inputs": {},
            "issues": [],
            "shader_name": "",
        }
        if shader:
            item["shader_id"] = str(shader.GetIdAttr().Get() or "")
            item["shader_name"] = shader.GetPrim().GetName()
            for inp in shader.GetInputs():
                if inp.GetAttr().HasAuthoredValueOpinion() or inp.HasConnectedSource():
                    item["inputs"][str(inp.GetBaseName())] = {
                        "value": _value(inp.Get()),
                        "connected": bool(inp.HasConnectedSource()),
                    }
            if item["shader_id"] != "UsdPreviewSurface":
                item["issues"].append("未支持的 shader：" + item["shader_id"])
            allowed = {"diffuseColor", "roughness", "metallic"}
            for name, data in item["inputs"].items():
                if name == "opacity":
                    item["issues"].append("显式 opacity：当前旧版插件转换 Phong 存在类型错误。")
                elif name not in allowed:
                    item["issues"].append("尚未验收的材质输入：" + name)
                elif name != "diffuseColor" and data["connected"]:
                    item["issues"].append("尚未支持的参数贴图连接：" + name)
                elif name == "metallic" and data["value"] not in (None, 0, 0.0):
                    item["issues"].append("第一版 Phong 路线仅支持非金属材质。")
            for child in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
                if child.IsA(UsdShade.Shader):
                    node = UsdShade.Shader(child)
                    node_id = str(node.GetIdAttr().Get() or "")
                    if node_id not in {
                        "UsdPreviewSurface",
                        "UsdUVTexture",
                        "UsdPrimvarReader_float2",
                    }:
                        item["issues"].append("未支持的网络节点：" + node_id)
        else:
            item["issues"].append("没有可识别的通用 surface 输出，可能需要专用渲染后端。")
        report["materials"].append(item)
        if item["bound"]:
            report["native_errors"].extend(item["path"] + "：" + issue for issue in item["issues"])
    from .pbr import inspect as inspect_pbr

    plans, bindings, pbr_errors, pbr_warnings = inspect_pbr(stage, bound_materials)
    report.update(
        pbr_materials=plans, pbr_bindings=bindings, pbr_errors=geometry_errors + pbr_errors
    )
    report["pbr_warnings"] = pbr_warnings
    from ue_maya_bridge.usd_cameras import read_cameras

    report["cameras"], camera_issues, report["camera_count"] = read_cameras(stage)
    for issue in camera_issues:
        message = "摄影机 {}：{}".format(issue["prim"], issue["reason"])
        report["native_errors"].append(message)
        report["pbr_errors"].append(message)
        report["warnings"].append(message + "；Stage 路线仅保留 USD，不创建此摄影机副本。")
    if not report["meshes"] and not report["camera_count"]:
        report["errors"].append(
            "没有找到已加载的 Mesh 或 Camera，不支持空场景或仅含曲线、程序化几何的文件。"
        )
    if report["meshes"] and not bound_materials:
        report["warnings"].append("模型没有 USD 材质绑定；原生模式将创建默认灰色材质。")
    if report["face_subsets"]:
        report["warnings"].append("检测到面材质子集，导入后请检查逐面分配。")
    report["native_errors"] = list(dict.fromkeys(report["native_errors"]))
    from ue_maya_bridge.usd_package import inspect_package

    source = inspect_package(path, report["layers"])
    if source["status"] == "verified" and source["placement_count"] != report["meshes"]:
        source["status"] = "invalid"
        source["errors"].append("来源报告摆放数与实际 USD 网格路径数不同。")
    if source["status"] == "verified" and source.get("camera_count", 0) != report["camera_count"]:
        source["status"] = "invalid"
        source["errors"].append("来源报告摄影机数量与 USD 不同。")
    if source["status"] == "verified":
        source_cameras = {item["prim"]: item for item in source.get("cameras", [])}
        for camera in report["cameras"]:
            authored = source_cameras.get(camera["prim"])
            if not authored:
                continue
            if any(
                abs(camera[key] - authored[key]) > max(1e-4, abs(authored[key]) * 1e-6)
                for key in (
                    "focal_length_mm",
                    "aperture_width_mm",
                    "aperture_height_mm",
                    "horizontal_offset_mm",
                    "vertical_offset_mm",
                )
            ):
                source["status"] = "invalid"
                source["errors"].append("摄影机来源参数与 USD 不同：" + camera["prim"])
            camera.update(
                label=authored["label"],
                camera_type=authored["camera_type"],
                frame_hint=authored["frame_hint"],
                warnings=authored.get("warnings", []),
                focal_source=authored.get("focal_source", "unknown"),
            )
            report["warnings"].extend(authored.get("warnings", []))
    report["ue_source"] = source
    report["errors"].extend("UE 交付包：" + message for message in source["errors"])
    report["warnings"].extend(source["warnings"])
    report["errors"] = list(dict.fromkeys(report["errors"]))
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    return report


def _scene_nodes():
    from maya.api import OpenMaya as om

    iterator = om.MItDependencyNodes()
    while not iterator.isDone():
        obj = iterator.thisNode()
        fn = om.MFnDependencyNode(obj)
        if obj.hasFn(om.MFn.kDagNode):
            name = om.MFnDagNode(obj).fullPathName()
        else:
            name = ":" + fn.name().lstrip(":")
        yield name, fn.uuid().asString()
        iterator.next()


def _uuids():
    # Maya 2023 ls(uuid=True) with no explicit objects returns names, not UUIDs.
    return {uid for _, uid in _scene_nodes()}


def _created(before):
    return [(node, uid) for node, uid in _scene_nodes() if uid not in before]


@contextmanager
def _transaction(mode):
    import maya.cmds as cmds

    if (
        cmds.currentUnit(query=True, linear=True) != "cm"
        or cmds.upAxis(query=True, axis=True) != "y"
    ):
        raise ToolError("第一版要求 Maya 场景为厘米、Y-up。工具不会自动修改当前场景设置。")
    old_namespace = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    old_selection = cmds.ls(selection=True, long=True) or []
    before = _uuids()
    namespace = "USDTool_" + uuid4().hex[:10]
    try:
        cmds.namespace(add=namespace, parent=":")
        cmds.namespace(setNamespace=":" + namespace)
        root = cmds.createNode("transform", name="USD_Import")
        data = {"namespace": namespace, "root": root, "before": before}
        yield data
    except Exception as exc:
        cmds.namespace(setNamespace=old_namespace)
        failures = []
        # Delete only UUIDs created by this operation. This also covers importer
        # nodes that a third-party importer puts outside the current namespace.
        new_nodes = _created(before)
        for _, uid in reversed(new_nodes):
            nodes = cmds.ls(uid, long=True) or []
            if nodes:
                try:
                    cmds.delete(nodes[0])
                except Exception as cleanup_error:
                    failures.append(str(cleanup_error))
        if cmds.namespace(exists=":" + namespace):
            try:
                cmds.namespace(removeNamespace=":" + namespace)
            except Exception as cleanup_error:
                failures.append(str(cleanup_error))
        if failures:
            raise ToolError(
                "载入失败，部分新增节点未能清理：{}；原错误：{}".format("; ".join(failures), exc)
            ) from exc
        raise
    finally:
        cmds.namespace(setNamespace=old_namespace)
        existing = [n for n in old_selection if cmds.objExists(n)]
        if existing:
            cmds.select(existing, replace=True)
        else:
            cmds.select(clear=True)


def _load_file_impl(
    filename,
    mode="phong",
    allow_missing_textures=False,
    flip_normal_y=False,
    texture_output_directory="",
    material_overrides=None,
):
    """Always inspect again so changed source files cannot bypass validation."""
    if mode not in {"phong", "pbr", "stage", "phong_preview"}:
        raise ToolError("未知载入方式。")
    if type(flip_normal_y) is not bool:
        raise ToolError("法线翻转设置必须为布尔值。")
    if not isinstance(texture_output_directory, str):
        raise ToolError("拆分贴图输出目录必须为路径字符串。")
    report = inspect_file(filename)
    problems = list(report["errors"])
    if mode == "phong":
        problems += report["native_errors"]
    elif mode in ("pbr", "phong_preview"):
        problems += report["pbr_errors"]
    using_manual = mode in ("pbr", "phong_preview") and bool(material_overrides)
    if report["missing_assets"] and not allow_missing_textures and not using_manual:
        problems.append("存在缺失贴图/资产。修复路径，或明确勾选允许缺失贴图后再载入。")
    if problems:
        raise ToolError("\n".join(problems[:15]))
    prepared_plans = []
    separated_textures = []
    if mode in ("pbr", "phong_preview"):
        from .texture_channels import prepare
        from .pbr import apply_overrides

        effective_plans = apply_overrides(report, material_overrides)
        if using_manual:
            missing = [
                v["texture"]["path"]
                for p in effective_plans
                for v in p["inputs"].values()
                if "texture" in v and not Path(v["texture"]["path"]).is_file()
            ]
            if missing:
                raise ToolError("仍有未替换的缺失贴图：" + "\n".join(missing))
        prepared_plans, separated_textures = prepare(
            effective_plans, report["path"], texture_output_directory
        )
        if using_manual and report["missing_assets"]:
            report["warnings"].append(
                "原 USD 含缺失资产；本次材质已使用有效的手动／原材质贴图重建，源文件未改写。"
            )
    import maya.cmds as cmds

    with _transaction(mode) as op:
        root = op["root"]
        source = _maya_path(report["path"])
        warnings = list(report["warnings"])
        pbr_materials = []
        preview_materials = []
        pbr_textures = []
        native_compatibility = False
        if mode in ("pbr", "phong_preview"):
            warnings += report["pbr_warnings"]
        if mode == "phong_preview":
            warnings.append(
                "Phong 为预览近似：Roughness 转 Cosine Power，Metallic 近似控制漫反射／高光；不等同于 PBR 渲染。"
            )
        if mode == "stage":
            import mayaUsd.lib

            proxy = cmds.createNode("mayaUsdProxyShape", name="USD_StageShape", parent=root)
            cmds.setAttr(proxy + ".filePath", source, type="string")
            cmds.connectAttr("time1.outTime", proxy + ".time", force=True)
            stage = mayaUsd.lib.GetPrim(proxy).GetStage()
            if not stage or not stage.GetPseudoRoot().GetChildren():
                raise ToolError("Maya USD 未成功创建 Stage。")
        else:
            cmds.mayaUSDImport(
                file=source,
                parent=root,
                primPath="/",
                readAnimData=False,
                shadingMode=(
                    [("none", "")]
                    if mode in ("pbr", "phong_preview")
                    else [("useRegistry", "UsdPreviewSurface")]
                ),
                preferredMaterial="phong",
                importInstances=True,
            )
            meshes = cmds.ls(root, dag=True, type="mesh", long=True, allPaths=True) or []
            if not meshes and report["meshes"]:
                from .native_import import recover

                warnings.append(recover(report, op, mode))
                native_compatibility = True
                meshes = cmds.ls(root, dag=True, type="mesh", long=True, allPaths=True) or []
            if len(meshes) != report["meshes"]:
                raise ToolError(
                    "原生网格摆放数与 USD 不一致（{} / {}），已撤销本次导入。".format(
                        len(meshes), report["meshes"]
                    )
                )
            # Assets without authored materials still get a useful Phong result.
            unassigned = []
            from maya.api import OpenMaya as om

            for mesh in meshes:
                selection = om.MSelectionList()
                selection.add(mesh)
                dag = selection.getDagPath(0)
                sets, _ = om.MFnMesh(dag).getConnectedShaders(dag.instanceNumber())
                groups = [om.MFnDependencyNode(node).name() for node in sets]
                if not groups or groups == ["initialShadingGroup"]:
                    unassigned.append(mesh)
            if mode in ("pbr", "phong_preview"):
                from .pbr import materialize as materialize_pbr

                built, pbr_textures = materialize_pbr(
                    report,
                    root,
                    op["namespace"],
                    flip_normal_y,
                    plans=prepared_plans,
                    **({"target": "phong"} if mode == "phong_preview" else {}),
                )
                if mode == "pbr":
                    pbr_materials = built
                else:
                    preview_materials = built
            elif unassigned:
                gray = cmds.shadingNode("phong", asShader=True, name="DefaultGray")
                sg = cmds.sets(
                    renderable=True, noSurfaceShader=True, empty=True, name="DefaultGraySG"
                )
                cmds.setAttr(gray + ".color", 0.5, 0.5, 0.5, type="double3")
                cmds.connectAttr(gray + ".outColor", sg + ".surfaceShader")
                for mesh in unassigned:
                    cmds.sets(mesh, edit=True, forceElement=sg)
                warnings.append("{} 个无材质网格已分配默认灰色 Phong。".format(len(unassigned)))
        from .cameras import materialize

        imported_cameras = materialize(report, root, op["namespace"], mode)
        for name, value in (("usdSourceFile", source), ("usdLoadMode", mode)):
            cmds.addAttr(root, longName=name, dataType="string")
            cmds.setAttr(root + "." + name, value, type="string")
        new = _created(op["before"])
        phongs = []
        textures = []
        for name, uid in new:
            node_type = cmds.nodeType(name)
            if node_type == "phong":
                details = next((m for m in preview_materials if m["uuid"] == uid), {})
                phongs.append(
                    dict(
                        details,
                        node=name,
                        uuid=uid,
                        color=cmds.getAttr(name + ".color")[0],
                        cosine_power=cmds.getAttr(name + ".cosinePower"),
                    )
                )
            elif node_type == "file":
                details = next((t for t in pbr_textures if t["uuid"] == uid), {})
                textures.append(
                    dict(
                        details,
                        node=name,
                        path=cmds.getAttr(name + ".fileTextureName"),
                        color_space=cmds.getAttr(name + ".colorSpace"),
                    )
                )
        native_meshes = (
            cmds.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []
        )
        unique_mesh_ids = {cmds.ls(mesh, uuid=True)[0] for mesh in native_meshes}
        result = {
            "mode": mode,
            "source": Path(report["path"]).as_posix(),
            "maya_source": source,
            "root": (cmds.ls(root, long=True) or [root])[0],
            "root_uuid": cmds.ls(root, uuid=True)[0],
            "namespace": op["namespace"],
            "native_meshes": len(unique_mesh_ids),
            "phongs": phongs,
            "textures": textures,
            "materials": phongs + pbr_materials,
            "pbr_materials": pbr_materials,
            "flip_normal_y": flip_normal_y,
            "separated_textures": separated_textures,
            "material_overrides": material_overrides or {},
            "native_compatibility": native_compatibility,
            "native_mesh_paths": len(
                cmds.ls(root, dag=True, type="mesh", long=True, allPaths=True) or []
            ),
            "cameras": imported_cameras,
            "native_cameras": len(imported_cameras),
            "created_nodes": len(new),
            "warnings": list(dict.fromkeys(warnings)),
            "inspection": report,
        }
        if mode == "phong":
            bound = sum(1 for m in report["materials"] if m["bound"])
            if bound and not phongs:
                raise ToolError("USD 有材质绑定，但未创建 Phong；请检查材质支持。")
        return result


def load_file(
    filename,
    mode="phong",
    allow_missing_textures=False,
    flip_normal_y=False,
    texture_output_directory="",
    material_overrides=None,
):
    """Execute through a Python MPxCommand for complete undo/redo.

    Maya USD 0.16's importer does not undo all generated shading nodes. The
    wrapper owns exactly the new dependency nodes and restores them on redo.
    """
    environment()
    import maya.cmds as cmds

    if not cmds.undoInfo(query=True, state=True):
        raise ToolError("请先在 Maya 中启用 Undo，再使用载入功能。")
    plugin = Path(__file__).with_name("usd_scene_tool_undo.py")
    plugin_path = _maya_path(plugin)
    if not cmds.pluginInfo(plugin_path, query=True, loaded=True):
        cmds.loadPlugin(plugin_path, quiet=True)
    request = json.dumps(
        {
            "filename": str(filename),
            "mode": mode,
            "allow_missing_textures": bool(allow_missing_textures),
            "flip_normal_y": flip_normal_y,
            "texture_output_directory": texture_output_directory,
            "material_overrides": material_overrides,
        }
    )
    try:
        raw = cmds.usdSceneToolLoad(request)
        if isinstance(raw, (list, tuple)) and len(raw) == 1:
            raw = raw[0]
        return json.loads(raw)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc


def select_result(result, materials=False):
    import maya.cmds as cmds

    ids = (
        [p["uuid"] for p in result.get("materials", result.get("phongs", []))]
        if materials
        else [result["root_uuid"]]
    )
    nodes = []
    for uid in ids:
        nodes.extend(cmds.ls(uid, long=True) or [])
    if not nodes:
        raise ToolError("找不到本次载入的对象，可能已经撤销或删除。")
    cmds.select(nodes, replace=True)
    return nodes


def save_report(filename, data):
    Path(filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
