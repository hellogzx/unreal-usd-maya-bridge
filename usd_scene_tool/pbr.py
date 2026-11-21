"""Restricted, explicit UsdPreviewSurface metal/rough -> Maya Standard Surface.

No Arnold dependency. Only reachable static texture networks are interpreted;
unsupported semantics fail preflight rather than silently losing a channel.
"""

import json
import math
import copy
from pathlib import Path


def _value(inp, default):
    if not inp:
        return default
    if inp.HasConnectedSource():
        raise ValueError("此参数不支持连接：" + str(inp.GetFullName()))
    if inp.GetAttr().ValueMightBeTimeVarying():
        raise ValueError("PBR 首版不支持动画参数：" + str(inp.GetFullName()))
    value = inp.Get()
    return default if value is None else value


def _numbers(value, count):
    result = [float(v) for v in value]
    if len(result) != count or not all(math.isfinite(v) for v in result):
        raise ValueError("材质参数必须为有限数值。")
    return result


def _texture(inp, usage):
    from pxr import UsdShade, Sdf, Usd

    source, output, kind = inp.GetConnectedSource()
    if str(kind) != "Output":
        raise ValueError("贴图必须连接到 Shader 输出。")
    shader = UsdShade.Shader(source.GetPrim())
    if not shader or shader.GetIdAttr().Get() != "UsdUVTexture":
        raise ValueError("只支持直接连接的 UsdUVTexture：" + str(inp.GetFullName()))
    channel = str(output)
    if channel not in (("rgb",) if usage in ("diffuseColor", "normal") else ("r", "g", "b", "a")):
        raise ValueError("贴图输出通道不匹配：{} → {}".format(channel, usage))
    allowed = {"file", "st", "sourceColorSpace", "wrapS", "wrapT", "scale", "bias", "fallback"}
    for item in shader.GetInputs():
        if str(item.GetBaseName()) not in allowed:
            raise ValueError("不支持的纹理参数：" + str(item.GetFullName()))
        if item.GetAttr().ValueMightBeTimeVarying():
            raise ValueError("不支持动画纹理。")
    asset = _value(shader.GetInput("file"), None)
    if asset is None or not asset.path or "<UDIM>" in asset.path or "%" in asset.path:
        raise ValueError("首版需要单张静态贴图，不支持 UDIM／序列。")
    filename = asset.resolvedPath
    if not filename:
        stack = shader.GetInput("file").GetAttr().GetPropertyStack(Usd.TimeCode.Default())
        filename = (
            Sdf.ComputeAssetPathRelativeToLayer(stack[0].layer, asset.path) if stack else asset.path
        )
    if usage in ("roughness", "metallic") and Path(filename).suffix.lower() not in (
        ".png",
        ".jpg",
        ".jpeg",
    ):
        raise ValueError("独立标量通道拆分目前需要 PNG／JPEG 数据图：" + str(filename))
    st = shader.GetInput("st")
    if not st or not st.HasConnectedSource():
        raise ValueError("贴图需要连接 st UV Reader。")
    reader, reader_output, reader_kind = st.GetConnectedSource()
    reader = UsdShade.Shader(reader.GetPrim())
    if (
        not reader
        or reader.GetIdAttr().Get() != "UsdPrimvarReader_float2"
        or str(reader_output) != "result"
        or str(reader_kind) != "Output"
        or str(_value(reader.GetInput("varname"), "st")) != "st"
    ):
        raise ValueError("首版仅支持直接读取 st UV；不支持 UV 变换或其他 UV 集。")
    color_space = str(_value(shader.GetInput("sourceColorSpace"), "auto"))
    if color_space not in ("auto", "sRGB", "raw"):
        raise ValueError("不支持的贴图颜色空间：" + color_space)
    if usage != "diffuseColor" and color_space == "sRGB":
        raise ValueError("Roughness／Metallic／Normal 贴图必须使用 raw 或 auto 数据颜色空间。")
    scale = _numbers(_value(shader.GetInput("scale"), (1, 1, 1, 1)), 4)
    bias = _numbers(_value(shader.GetInput("bias"), (0, 0, 0, 0)), 4)
    fallback = _numbers(_value(shader.GetInput("fallback"), (0, 0, 0, 1)), 4)
    wraps = [str(_value(shader.GetInput(k), "useMetadata")) for k in ("wrapS", "wrapT")]
    warnings = []
    if any(w not in ("repeat", "useMetadata") for w in wraps):
        raise ValueError("PBR 首版只支持 repeat 纹理边界；clamp／black／mirror 需先在源端处理。")
    if "useMetadata" in wraps:
        warnings.append("纹理 useMetadata 边界按 repeat 处理：" + str(shader.GetPath()))
    if color_space == "auto":
        warnings.append(
            "auto 颜色空间按用途解释：颜色 sRGB，参数／法线 Raw：" + str(shader.GetPath())
        )
    flip = False
    if usage == "normal":
        # bump2d tangent-space mode performs the unsigned -> signed decode.
        # Strip the equivalent USD decode, retaining an authored Y inversion.
        if scale[:3] == [2.0, 2.0, 2.0] and bias[:3] == [-1.0, -1.0, -1.0]:
            pass
        elif scale[:3] == [2.0, -2.0, 2.0] and bias[:3] == [-1.0, 1.0, -1.0]:
            flip = True
        else:
            raise ValueError(
                "法线贴图需在 USD 中使用 scale=(2,2,2,1)、bias=(-1,-1,-1,0) 解码；也支持绿色翻转解码。"
            )
        scale = [1, 1, 1, 1]
        bias = [0, 0, 0, 0]
    return {
        "path": Path(filename).as_posix(),
        "channel": channel,
        "usage": usage,
        "color_space": "sRGB" if usage == "diffuseColor" and color_space != "raw" else "Raw",
        "scale": scale,
        "bias": bias,
        "fallback": fallback,
        "wrap": [w != "clamp" for w in wraps],
        "flip_green": flip,
        "warnings": warnings,
    }


def inspect(stage, bound_materials):
    from pxr import Usd, UsdGeom, UsdShade

    plans = []
    issues = []
    warnings = []
    for path in sorted(bound_materials):
        try:
            material = UsdShade.Material(stage.GetPrimAtPath(path))
            shader, _, _ = material.ComputeSurfaceSource()
            if not shader or shader.GetIdAttr().Get() != "UsdPreviewSurface":
                raise ValueError("需要通用 UsdPreviewSurface 材质输出。")
            plan = {"path": path, "name": material.GetPrim().GetName(), "inputs": {}}
            neutral = {
                "useSpecularWorkflow": 0,
                "opacity": 1,
                "opacityThreshold": 0,
                "emissiveColor": (0, 0, 0),
                "displacement": 0,
                "occlusion": 1,
            }
            allowed = {"diffuseColor", "roughness", "metallic", "normal", "ior"} | set(neutral)
            for inp in shader.GetInputs():
                name = str(inp.GetBaseName())
                if name not in allowed:
                    raise ValueError("PBR 首版不支持输入：" + name)
                if inp.GetAttr().ValueMightBeTimeVarying():
                    raise ValueError("不支持动画材质输入：" + name)
                if name in neutral:
                    value = _value(inp, neutral[name])
                    value = list(value) if name == "emissiveColor" else value
                    default = list(neutral[name]) if name == "emissiveColor" else neutral[name]
                    if value != default:
                        raise ValueError("尚未支持的非默认输入：" + name)
            for name, default in (
                ("diffuseColor", (0.18, 0.18, 0.18)),
                ("roughness", 0.5),
                ("metallic", 0.0),
                ("normal", (0, 0, 1)),
                ("ior", 1.5),
            ):
                inp = shader.GetInput(name)
                if inp and inp.HasConnectedSource():
                    if name == "ior":
                        raise ValueError("不支持 IOR 贴图。")
                    data = _texture(inp, name)
                    warnings.extend(data["warnings"])
                    plan["inputs"][name] = {"texture": data}
                else:
                    value = _value(inp, default)
                    if name in ("diffuseColor", "normal"):
                        value = _numbers(value, 3)
                        if name == "normal" and value != [0, 0, 1]:
                            raise ValueError("尚不支持非默认常量法线。")
                    else:
                        value = float(value)
                        if (
                            not math.isfinite(value)
                            or (name == "ior" and not 1 <= value <= 3)
                            or (name != "ior" and not 0 <= value <= 1)
                        ):
                            raise ValueError("材质参数范围无效：" + name)
                    plan["inputs"][name] = {"value": value}
            plans.append(plan)
        except (ValueError, TypeError, RuntimeError) as error:
            issues.append(path + "：" + str(error))
    bindings = []
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        api = UsdShade.MaterialBindingAPI(prim)
        material = api.ComputeBoundMaterial()[0]
        binding = {
            "prim": str(prim.GetPath()),
            "material": str(material.GetPath()) if material else None,
            "subsets": [],
            "face_count": len(mesh.GetFaceVertexCountsAttr().Get() or []),
        }
        occupied = set()
        used = {binding["material"]}
        for subset in api.GetMaterialBindSubsets():
            mat = UsdShade.MaterialBindingAPI(subset).ComputeBoundMaterial()[0]
            indices = list(subset.GetIndicesAttr().Get() or [])
            if (
                str(subset.GetElementTypeAttr().Get()) != "face"
                or len(indices) != len(set(indices))
                or occupied.intersection(indices)
                or any(i < 0 or i >= binding["face_count"] for i in indices)
            ):
                issues.append(str(subset.GetPath()) + "：无效或重叠的面材质子集。")
            if subset.GetIndicesAttr().ValueMightBeTimeVarying():
                issues.append(str(subset.GetPath()) + "：不支持动画面材质子集。")
            occupied.update(indices)
            path = str(mat.GetPath()) if mat else None
            binding["subsets"].append({"material": path, "faces": indices})
            used.add(path)
        textured = any(
            p["path"] in used and any("texture" in v for v in p["inputs"].values()) for p in plans
        )
        if textured and not UsdGeom.PrimvarsAPI(prim).GetPrimvar("st").HasValue():
            issues.append(str(prim.GetPath()) + "：贴图材质缺少 st UV。")
        bindings.append(binding)
    return plans, bindings, list(dict.fromkeys(issues)), list(dict.fromkeys(warnings))


def apply_overrides(report, overrides):
    """Replace explicitly chosen channel images for one identified USD material."""
    from .core import ToolError
    from pxr import Usd, UsdGeom

    plans = copy.deepcopy(report["pbr_materials"])
    if overrides is None:
        return plans
    if not isinstance(overrides, dict):
        raise ToolError("手动贴图设置必须按材质记录。")
    if not overrides:
        return plans
    unbound = any(
        b["material"] is None or any(s["material"] is None for s in b["subsets"])
        for b in report["pbr_bindings"]
    )
    by_path = {p["path"]: p for p in plans}
    stage = None
    for target, channels in overrides.items():
        if not isinstance(channels, dict) or any(
            k not in ("diffuseColor", "roughness", "metallic", "normal") for k in channels
        ):
            raise ToolError("手动贴图只支持 Base Color、Metallic、Roughness、Normal。")
        key = None if target == "__unbound__" else target
        if key is None and unbound:
            plan = {
                "path": None,
                "name": "Default",
                "inputs": {
                    "diffuseColor": {"value": [0.5, 0.5, 0.5]},
                    "roughness": {"value": 0.5},
                    "metallic": {"value": 0},
                    "normal": {"value": [0, 0, 1]},
                    "ior": {"value": 1.5},
                },
            }
            plans.append(plan)
            by_path[None] = plan
        if key not in by_path:
            raise ToolError("找不到手动贴图对应的材质，请重新选择 USD：" + str(target))
        for usage, filename in channels.items():
            if not isinstance(filename, str) or not filename.strip():
                raise ToolError("请选择有效的手动贴图路径。")
            path = Path(filename).expanduser()
            if not path.is_absolute():
                path = Path(report["path"]).parent / path
            path = path.resolve()
            if not path.is_file():
                raise ToolError("找不到 " + usage + " 贴图：" + str(path))
            if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                raise ToolError("简易手动贴图当前支持 PNG／JPEG。")
            from PySide2.QtGui import QImage

            if QImage(str(path)).isNull():
                raise ToolError("无法读取 " + usage + " 贴图：" + str(path))
            by_path[key]["inputs"][usage] = {
                "texture": {
                    "path": path.as_posix(),
                    "channel": "rgb" if usage in ("diffuseColor", "normal") else "r",
                    "usage": usage,
                    "color_space": "sRGB" if usage == "diffuseColor" else "Raw",
                    "scale": [1, 1, 1, 1],
                    "bias": [0, 0, 0, 0],
                    "fallback": [0, 0, 0, 1],
                    "wrap": [True, True],
                    "flip_green": False,
                    "warnings": [],
                }
            }
        if channels:
            stage = stage or Usd.Stage.Open(report["path"])
            for binding in report["pbr_bindings"]:
                used = {binding["material"]} | {s["material"] for s in binding["subsets"]}
                if (
                    key in used
                    and not UsdGeom.PrimvarsAPI(stage.GetPrimAtPath(binding["prim"]))
                    .GetPrimvar("st")
                    .HasValue()
                ):
                    raise ToolError("手动贴图对应模型缺少 st UV：" + binding["prim"])
    return plans


def materialize(report, root, namespace, flip_normal_y=False, plans=None, target="standardSurface"):
    import maya.cmds as cmds
    from maya.api import OpenMaya as om
    from .core import ToolError, _maya_path

    if target not in ("standardSurface", "phong"):
        raise ToolError("未知目标材质：" + str(target))
    root = cmds.ls(root, long=True)[0]
    groups = {}
    materials = []
    textures = []
    cache = {}

    def texture(data):
        effective = dict(data)
        if data["usage"] == "normal":
            flip = bool(data["flip_green"]) ^ bool(flip_normal_y)
            effective["scale"] = [1, -1 if flip else 1, 1, 1]
            effective["bias"] = [0, 1 if flip else 0, 0, 0]
        key = json.dumps(
            {k: v for k, v in effective.items() if k not in ("channel", "warnings")}, sort_keys=True
        )
        if key not in cache:
            label = {
                "diffuseColor": "BaseColor",
                "roughness": "Roughness",
                "metallic": "Metallic",
                "normal": "Normal",
            }[data["usage"]]
            node = cmds.shadingNode(
                "file", asTexture=True, name=plan["name"] + "_" + label + "_File"
            )
            place = cmds.shadingNode("place2dTexture", asUtility=True, name="PBR_UV")
            for attr in (
                "coverage",
                "translateFrame",
                "rotateFrame",
                "mirrorU",
                "mirrorV",
                "stagger",
                "wrapU",
                "wrapV",
                "repeatUV",
                "offset",
                "rotateUV",
                "noiseUV",
                "vertexUvOne",
                "vertexUvTwo",
                "vertexUvThree",
                "vertexCameraOne",
            ):
                cmds.connectAttr(place + "." + attr, node + "." + attr)
            cmds.connectAttr(place + ".outUV", node + ".uvCoord")
            cmds.connectAttr(place + ".outUvFilterSize", node + ".uvFilterSize")
            cmds.setAttr(place + ".wrapU", data["wrap"][0])
            cmds.setAttr(place + ".wrapV", data["wrap"][1])
            path = _maya_path(data["path"]) if Path(data["path"]).is_file() else data["path"]
            cmds.setAttr(node + ".fileTextureName", path, type="string")
            cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)
            cmds.setAttr(node + ".colorSpace", data["color_space"], type="string")
            cmds.setAttr(node + ".alphaIsLuminance", False)
            cmds.setAttr(node + ".colorGain", *effective["scale"][:3], type="double3")
            cmds.setAttr(node + ".colorOffset", *effective["bias"][:3], type="double3")
            cmds.setAttr(node + ".alphaGain", effective["scale"][3])
            cmds.setAttr(node + ".alphaOffset", effective["bias"][3])
            cmds.setAttr(node + ".defaultColor", *data["fallback"][:3], type="double3")
            cache[key] = node
            textures.append(
                {
                    "node": node,
                    "uuid": cmds.ls(node, uuid=True)[0],
                    "path": path,
                    "color_space": data["color_space"],
                    "usage": data["usage"],
                    "source_path": data.get("source_path", data["path"]),
                    "source_channel": data.get("source_channel", data["channel"]),
                }
            )
        return cache[key]

    plans = list(report["pbr_materials"] if plans is None else plans)
    if not any(p["path"] is None for p in plans):
        plans.append(
            {
                "path": None,
                "name": "DefaultGray",
                "inputs": {
                    "diffuseColor": {"value": [0.5, 0.5, 0.5]},
                    "metallic": {"value": 0},
                    "roughness": {"value": 0.5},
                    "normal": {"value": [0, 0, 1]},
                    "ior": {"value": 1.5},
                },
            }
        )
    used = {b["material"] for b in report["pbr_bindings"]} | {
        s["material"] for b in report["pbr_bindings"] for s in b["subsets"]
    }
    for plan in plans:
        if plan["path"] not in used:
            continue
        # Every material channel gets a separately named file node.
        cache.clear()
        if target == "phong":
            from .phong import build

            node, group, files = build(plan, texture)
            groups[plan["path"]] = group
            materials.append(
                {
                    "node": node,
                    "uuid": cmds.ls(node, uuid=True)[0],
                    "usd_material": plan["path"],
                    "type": "phong",
                    "channel_textures": {
                        role: next(t for t in textures if t["node"] == file)
                        for role, file in files.items()
                    },
                }
            )
            continue
        node = cmds.shadingNode("standardSurface", asShader=True, name=plan["name"] + "_PBR")
        group = cmds.sets(
            renderable=True, noSurfaceShader=True, empty=True, name=plan["name"] + "_PBR_SG"
        )
        cmds.connectAttr(node + ".outColor", group + ".surfaceShader")
        cmds.setAttr(node + ".base", 1)
        groups[plan["path"]] = group
        channel_textures = {}
        for channel, attribute in (
            ("diffuseColor", "baseColor"),
            ("roughness", "specularRoughness"),
            ("metallic", "metalness"),
            ("ior", "specularIOR"),
            ("normal", "normalCamera"),
        ):
            source = plan["inputs"][channel]
            if "texture" not in source:
                if channel == "normal":
                    continue
                value = source["value"]
                if isinstance(value, list):
                    cmds.setAttr(node + "." + attribute, *value, type="double3")
                else:
                    cmds.setAttr(node + "." + attribute, value)
                continue
            data = source["texture"]
            file = texture(data)
            channel_textures[channel] = next(t for t in textures if t["node"] == file)
            if channel == "normal":
                bump = cmds.shadingNode("bump2d", asUtility=True, name=plan["name"] + "_Normal")
                cmds.setAttr(bump + ".bumpInterp", 1)
                cmds.connectAttr(file + ".outAlpha", bump + ".bumpValue")
                cmds.connectAttr(bump + ".outNormal", node + "." + attribute)
            else:
                output = (
                    "outColor"
                    if data["channel"] == "rgb"
                    else (
                        "outAlpha"
                        if data["channel"] == "a"
                        else "outColor" + data["channel"].upper()
                    )
                )
                cmds.connectAttr(file + "." + output, node + "." + attribute)
        materials.append(
            {
                "node": node,
                "uuid": cmds.ls(node, uuid=True)[0],
                "usd_material": plan["path"],
                "type": "standardSurface",
                "channel_textures": channel_textures,
            }
        )
    for binding in report["pbr_bindings"]:
        transform = (
            root
            + "|"
            + "|".join(namespace + ":" + part for part in binding["prim"].strip("/").split("/"))
        )
        shapes = (
            cmds.listRelatives(
                transform, shapes=True, noIntermediate=True, fullPath=True, type="mesh"
            )
            or []
        )
        if len(shapes) != 1:
            raise ToolError("无法唯一匹配 USD 网格以分配材质：" + binding["prim"])
        shape = shapes[0]
        cmds.sets(shape, edit=True, forceElement=groups[binding["material"]])
        expected = [groups[binding["material"]]] * binding["face_count"]
        for subset in binding["subsets"]:
            if subset["faces"]:
                cmds.sets(
                    [shape + ".f[{}]".format(i) for i in subset["faces"]],
                    edit=True,
                    forceElement=groups[subset["material"]],
                )
            for face in subset["faces"]:
                expected[face] = groups[subset["material"]]
        selection = om.MSelectionList()
        selection.add(shape)
        dag = selection.getDagPath(0)
        sets, indices = om.MFnMesh(dag).getConnectedShaders(dag.instanceNumber())
        names = [om.MFnDependencyNode(s).name() for s in sets]
        if len(indices) != len(expected) or any(
            i < 0 or names[i].lstrip(":") != expected[f].lstrip(":") for f, i in enumerate(indices)
        ):
            raise ToolError("PBR 面材质分配校验失败：" + binding["prim"])
    # Evaluate newly-created file nodes once. In Maya 2023 an immediate VP2
    # frame can otherwise see an uninitialized scalar texture as fully metallic.
    for item in textures:
        if Path(item["path"]).is_file():
            try:
                cmds.colorAtPoint(item["node"], output="RGB", u=0.5, v=0.5)
            except RuntimeError as error:
                report["warnings"].append(
                    "贴图预读未完成，请检查视口和文件格式：{}；{}".format(item["path"], error)
                )
    return materials, textures
