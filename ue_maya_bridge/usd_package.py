"""Read-only validation of the optional UE USD source report, without host APIs."""

import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath

from .package import sha256_file
from .usd_options import normalize_options, choose_geometry
from .camera_math import validate_camera

FORMAT = "ue-maya-usd-previs"
VERSION = 4


def inspect_package(scene, resolved_layers=None):
    scene = Path(scene).expanduser().resolve()
    report = {"status": "missing", "errors": [], "warnings": [], "manifest": None}
    manifest = scene.parent / "usd_manifest.json"
    # Other USD files remain independent of a neighbouring UE package report.
    if scene.name != "scene.usda" or not manifest.exists():
        return report
    report["manifest"] = str(manifest)
    report["status"] = "invalid"
    try:
        if manifest.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("来源报告超过 16 MiB 限制。")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise ValueError("无法识别 UE 来源报告格式。")
        if type(data.get("version")) is not int or data["version"] not in (1, 2, 3, VERSION):
            raise ValueError("不支持此来源报告版本。")
        if any(
            not isinstance(data.get(key, "未知"), str)
            for key in ("engine_version", "created_utc", "geometry_source")
        ):
            raise ValueError("来源报告的版本、时间或几何说明无效。")
        if data.get("root_layer") != "scene.usda":
            raise ValueError("来源报告的根 USD 路径不匹配。")
        if (scene.parent / "EXPORT_FAILED.txt").exists():
            raise ValueError("此目录标记为导出失败，请重新导出。")
        files = data.get("files")
        actors, assets, skipped = data.get("actors"), data.get("assets"), data.get("skipped")
        if not isinstance(files, dict) or "scene.usda" not in files or not files:
            raise ValueError("来源报告缺少根文件校验。")
        if (
            not isinstance(actors, list)
            or not actors
            or not isinstance(assets, dict)
            or (not assets and data["version"] < 4)
            or not isinstance(skipped, list)
        ):
            raise ValueError("来源报告的对象、资源或跳过清单不完整。")
        actor_ids = set()
        for actor in actors:
            if not isinstance(actor, dict) or not all(
                isinstance(actor.get(key), str) and actor[key] for key in ("actor", "label")
            ):
                raise ValueError("来源报告含无效对象。")
            if actor["actor"] in actor_ids:
                raise ValueError("来源报告含重复 Actor。")
            actor_ids.add(actor["actor"])
        placements = data.get("placements") if data["version"] >= 2 else actors
        if not isinstance(placements, list) or (not placements and data["version"] < 4):
            raise ValueError("来源报告缺少摆放记录。")
        placement_ids, prim_ids, component_ids = set(), set(), set()
        for item in placements:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) and item[key]
                for key in ("actor", "label", "mesh", "prim")
            ):
                raise ValueError("来源报告含无效摆放。")
            identity = item.get("id") if data["version"] >= 2 else item["actor"]
            if (
                not isinstance(identity, str)
                or not identity
                or identity in placement_ids
                or item["prim"] in prim_ids
                or item["mesh"] not in assets
                or item["actor"] not in actor_ids
            ):
                raise ValueError("来源报告含重复摆放或缺失的 Actor / 资源。")
            if data["version"] >= 2:
                if not isinstance(item.get("component"), str) or not item["component"]:
                    raise ValueError("摆放记录缺少组件路径。")
                index = item.get("instance_index")
                if index is not None and (type(index) is not int or index < 0):
                    raise ValueError("摆放记录实例索引无效。")
                component_ids.add(item["component"])
                matrix = item.get("matrix")
                if (
                    not isinstance(matrix, list)
                    or len(matrix) != 4
                    or any(
                        not isinstance(row, list)
                        or len(row) != 4
                        or any(
                            type(value) not in (int, float) or not math.isfinite(value)
                            for value in row
                        )
                        for row in matrix
                    )
                ):
                    raise ValueError("摆放记录缺少有效的世界矩阵。")
            placement_ids.add(identity)
            prim_ids.add(item["prim"])
        for item in skipped:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("reasons"), list)
                or not all(isinstance(s, str) for s in item["reasons"])
            ):
                raise ValueError("来源报告含无效跳过记录。")
        checked = set()
        for name, checksum in files.items():
            if not isinstance(name, str) or "\\" in name or ":" in name:
                raise ValueError("来源报告含无效文件路径。")
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix not in (".usd", ".usda", ".usdc")
            ):
                raise ValueError("来源报告中的 USD 必须位于交付包内。")
            path = (scene.parent / name).resolve()
            try:
                path.relative_to(scene.parent)
            except ValueError:
                raise ValueError("来源报告路径超出交付包。")
            if (
                not isinstance(checksum, str)
                or len(checksum) != 64
                or any(c not in "0123456789abcdef" for c in checksum)
            ):
                raise ValueError("无效文件校验值：" + name)
            if not path.is_file() or sha256_file(path) != checksum:
                raise ValueError("USD 文件缺失或与导出记录不同：" + name)
            checked.add(path)
        for asset in assets.values():
            if not isinstance(asset, dict) or asset.get("file") not in files:
                raise ValueError("来源报告的资源未列入文件校验。")
        if resolved_layers is not None:
            for layer in resolved_layers:
                if Path(layer).resolve() not in checked:
                    raise ValueError("USD 引用了未列入交付包校验的依赖层：" + layer)
        scope = data.get("scope", {})
        if not isinstance(scope, dict) or scope.get("mode", "explicit") not in (
            "selection",
            "loaded",
            "explicit",
        ):
            raise ValueError("来源报告含不支持的导出范围。")
        statistics = data.get("statistics", {})
        if not isinstance(statistics, dict):
            raise ValueError("来源报告几何统计无效。")
        if data["version"] >= 2:
            if any(
                type(statistics.get(key)) is not int or statistics[key] < 0
                for key in ("unique_triangles", "placed_triangles", "unique_vertices")
            ):
                raise ValueError("来源报告三角面或顶点统计无效。")
            asset_stats = statistics.get("assets")
            if not isinstance(asset_stats, dict) or set(asset_stats) != set(assets):
                raise ValueError("来源报告资源统计与资源清单不同。")
            placement_counts = Counter(p["mesh"] for p in placements)
            for key, item in asset_stats.items():
                if not isinstance(item, dict) or any(
                    type(item.get(field)) is not int or item[field] < 0
                    for field in ("triangles", "vertices", "lod_count", "placements", "lod_index")
                ):
                    raise ValueError("来源报告含无效的资源几何统计。")
                if item["placements"] != placement_counts[key]:
                    raise ValueError("资源摆放统计与清单不同。")
            if statistics["unique_triangles"] != sum(
                item["triangles"] for item in asset_stats.values()
            ) or statistics["placed_triangles"] != sum(
                item["triangles"] * item["placements"] for item in asset_stats.values()
            ):
                raise ValueError("来源报告三角面总数与资源统计不同。")
        options = None
        if data["version"] >= 3:
            if "options" not in data:
                raise ValueError("来源报告缺少精度设置。")
            options = normalize_options(data["options"])
            if data["version"] == 3:
                options["include_cameras"] = False
            for key, stat in statistics["assets"].items():
                choice = stat.get("geometry_choice")
                if not isinstance(choice, dict) or type(choice.get("nanite")) is not bool:
                    raise ValueError("来源报告缺少实际几何选择。")
                expected = choose_geometry(stat["lod_count"], choice["nanite"], options)
                if (
                    choice != expected
                    or stat["lod_index"] != choice["effective_lod"]
                    or assets[key].get("geometry_choice") != choice
                ):
                    raise ValueError("来源报告精度选择与设置不同。")
                filename = assets[key]["file"]
                if Path(filename).suffix != "." + options["asset_format"]:
                    raise ValueError("资源后缀与选择的格式不同。")
                if options["asset_format"] == "usdc":
                    with (scene.parent / filename).open("rb") as stream:
                        header = stream.read(16)
                    if (
                        len(header) != 16
                        or header[:8] != b"PXR-USDC"
                        or tuple(header[8:11]) > (0, 8, 0)
                    ):
                        raise ValueError("USDC 编码或 Crate 版本不在本机 Maya 2023 验收范围。")
            for placement in placements:
                if (
                    placement.get("geometry_choice")
                    != statistics["assets"][placement["mesh"]]["geometry_choice"]
                ):
                    raise ValueError("摆放的精度记录与资源不同。")
            metrics = data.get("metrics")
            if not isinstance(metrics, dict) or any(
                type(metrics.get(key)) is not int or metrics[key] < 0
                for key in ("usd_bytes", "geometry_bytes")
            ):
                raise ValueError("来源报告文件体积统计无效。")
            seconds = metrics.get("usd_export_seconds")
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError("来源报告导出耗时无效。")
        cameras = data.get("cameras", []) if data["version"] >= 4 else []
        if not isinstance(cameras, list):
            raise ValueError("摄影机来源清单无效。")
        camera_ids, camera_paths = set(), set()
        for camera in cameras:
            validate_camera(camera, require_source=True)
            if (
                camera["actor"] not in actor_ids
                or camera["id"] in camera_ids
                or camera["prim"] in camera_paths
                or camera["prim"] in prim_ids
            ):
                raise ValueError("摄影机来源存在重复或缺失 Actor。")
            camera_ids.add(camera["id"])
            camera_paths.add(camera["prim"])
        if data["version"] >= 4 and (not placements and not cameras):
            raise ValueError("交付包没有模型或摄影机。")
        if cameras and not options.get("include_cameras"):
            raise ValueError("摄影机清单与导出设置不同。")
        report.update(
            status="verified",
            engine_version=data.get("engine_version", "未知"),
            created_utc=data.get("created_utc", "未知"),
            scope=scope,
            actor_count=len(actors),
            placement_count=len(placements),
            component_count=len(component_ids),
            instance_count=sum(p.get("instance_index") is not None for p in placements),
            asset_count=len(assets),
            skipped_count=len(skipped),
            statistics=statistics,
            options=options,
            metrics=data.get("metrics", {}),
            cameras=cameras,
            camera_count=len(cameras),
            skipped=skipped,
            actors=actors,
            placements=placements,
            geometry_source=data.get("geometry_source", "未知"),
        )
        if skipped:
            report["warnings"].append(
                "UE 导出为部分完成，共 {} 个跳过项（可能为 Actor、组件或实例）。".format(
                    len(skipped)
                )
            )
        if options:
            proxy = sum(
                s["placements"]
                for s in statistics["assets"].values()
                if s["geometry_choice"]["nanite"]
            )
            fallback = sum(
                s["geometry_choice"]["lod_fallback"] for s in statistics["assets"].values()
            )
            if proxy:
                report["warnings"].append(
                    "{} 次摆放使用 Nanite 渲染代理，外形近似；未导出 Nanite 完整源网格。".format(
                        proxy
                    )
                )
            if fallback:
                report["warnings"].append("{} 份资源因缺少所选 LOD 退回 LOD0。".format(fallback))
        if scope.get("mode") == "loaded":
            report["warnings"].append(
                "导出仅覆盖当时已加载的 Actor，不保证包含未加载区块或数据层。"
            )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report["errors"].append(str(exc))
    return report
