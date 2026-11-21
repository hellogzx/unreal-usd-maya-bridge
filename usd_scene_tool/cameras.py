"""Native static camera companions and explicit viewport/frame operations."""

from .core import ToolError


def _camera_node(record):
    import maya.cmds as cmds

    nodes = cmds.ls(record.get("uuid", ""), long=True, type="camera") or []
    if len(nodes) != 1:
        raise ToolError("摄影机已撤销、删除或发生变化，请重新载入。")
    return nodes[0]


def materialize(report, root, namespace, mode):
    import maya.cmds as cmds

    root = cmds.ls(root, long=True)[0]
    records = []
    group = None
    for item in report["cameras"]:
        if mode in ("phong", "pbr", "phong_preview"):
            transform = (
                root
                + "|"
                + "|".join(namespace + ":" + part for part in item["prim"].strip("/").split("/"))
            )
            if not cmds.objExists(transform):
                candidates = [
                    p
                    for p in (
                        cmds.ls(
                            ":" + namespace + ":" + item["prim"].split("/")[-1],
                            long=True,
                            type="transform",
                        )
                        or []
                    )
                    if p.startswith(root + "|")
                ]
                if len(candidates) == 1:
                    transform = candidates[0]
            shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
            if len(shapes) != 1:
                raise ToolError("原生导入遗漏或重命名摄影机：" + item["prim"])
            shape = shapes[0]
        else:
            if group is None:
                group = cmds.createNode("transform", name="USD_Cameras", parent=root)
            transform = cmds.createNode("transform", name=item["prim"].split("/")[-1], parent=group)
            shape = cmds.createNode(
                "camera", name=item["prim"].split("/")[-1] + "Shape", parent=transform
            )
        cmds.xform(transform, matrix=[v for row in item["matrix"] for v in row], worldSpace=True)
        values = {
            "focalLength": item["focal_length_mm"],
            "horizontalFilmAperture": item["aperture_width_mm"] / 25.4,
            "verticalFilmAperture": item["aperture_height_mm"] / 25.4,
            "horizontalFilmOffset": item["horizontal_offset_mm"] / 25.4,
            "verticalFilmOffset": item["vertical_offset_mm"] / 25.4,
            "nearClipPlane": item["near_clip_cm"],
            "farClipPlane": item["far_clip_cm"],
            "filmFit": 1,
            "filmFitOffset": 0,
            "lensSqueezeRatio": 1,
            "cameraScale": 1,
            "overscan": 1,
            "preScale": 1,
            "postScale": 1,
            "depthOfField": False,
            "renderable": False,
            "displayResolution": True,
            "displayGateMask": True,
        }
        for name, value in values.items():
            cmds.setAttr(shape + "." + name, value)
        for name, value in values.items():
            if name in (
                "focalLength",
                "horizontalFilmAperture",
                "verticalFilmAperture",
                "horizontalFilmOffset",
                "verticalFilmOffset",
            ) and abs(cmds.getAttr(shape + "." + name) - value) > max(1e-6, abs(value) * 1e-6):
                raise ToolError("摄影机参数超出 Maya 可表示范围：" + name)
        cmds.addAttr(transform, longName="usdCameraPrim", dataType="string")
        cmds.setAttr(transform + ".usdCameraPrim", item["prim"], type="string")
        record = dict(
            item,
            uuid=cmds.ls(shape, uuid=True)[0],
            transform_uuid=cmds.ls(transform, uuid=True)[0],
            node=(cmds.ls(shape, long=True) or [shape])[0],
        )
        records.append(record)
    return records


def select_camera(record):
    import maya.cmds as cmds

    shape = _camera_node(record)
    parent = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    cmds.select(parent, replace=True)
    return parent


def view_camera(record):
    import maya.cmds as cmds

    shape = _camera_node(record)
    focused = cmds.getPanel(withFocus=True)
    if focused and cmds.getPanel(typeOf=focused) == "modelPanel":
        panel = focused
    else:
        panels = [
            p
            for p in (cmds.getPanel(visiblePanels=True) or [])
            if cmds.getPanel(typeOf=p) == "modelPanel"
        ]
        if not panels:
            raise ToolError("请先打开一个 Maya 模型视口。")
        panel = panels[0]
    cmds.lookThru(panel, shape)
    return panel


def match_frame(record):
    import maya.cmds as cmds

    _camera_node(record)
    hint = record["frame_hint"]
    plugs = [
        "defaultResolution." + name
        for name in ("width", "height", "pixelAspect", "deviceAspectRatio", "lockDeviceAspectRatio")
    ]
    if any(not cmds.getAttr(plug, settable=True) for plug in plugs):
        raise ToolError("当前输出设置存在锁定或连接，未应用画幅。")
    before = {plug: cmds.getAttr(plug) for plug in plugs}
    cmds.undoInfo(openChunk=True, chunkName="USD Match Camera Frame")
    try:
        cmds.setAttr("defaultResolution.lockDeviceAspectRatio", False)
        cmds.setAttr("defaultResolution.width", hint["width"])
        cmds.setAttr("defaultResolution.height", hint["height"])
        cmds.setAttr("defaultResolution.pixelAspect", 1.0)
        cmds.setAttr("defaultResolution.deviceAspectRatio", hint["width"] / hint["height"])
        cmds.setAttr(
            "defaultResolution.lockDeviceAspectRatio",
            before["defaultResolution.lockDeviceAspectRatio"],
        )
    except Exception:
        for plug, value in before.items():
            cmds.setAttr(plug, value)
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
    return dict(hint)
