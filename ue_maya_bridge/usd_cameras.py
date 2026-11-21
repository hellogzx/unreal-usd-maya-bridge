"""Read standard USD perspective cameras with either host's bundled SDK."""

from .camera_math import frame_hint, validate_camera


def read_cameras(stage):
    from pxr import Usd, UsdGeom

    valid, issues, count = [], [], 0
    cache = UsdGeom.XformCache()
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Camera):
            continue
        count += 1
        try:
            if prim.IsInstanceProxy() or prim.IsInstance():
                raise ValueError("首版不创建实例化摄影机副本")
            camera = UsdGeom.Camera(prim)
            if camera.GetProjectionAttr().Get() != UsdGeom.Tokens.perspective:
                raise ValueError("首版不创建正交摄影机副本")
            if any(attr.ValueMightBeTimeVarying() for attr in prim.GetAttributes()):
                raise ValueError("检测到摄影机参数动画")
            ancestor = prim
            while ancestor and not ancestor.IsPseudoRoot():
                if any(
                    str(a.GetName()).startswith("xformOp:") and a.ValueMightBeTimeVarying()
                    for a in ancestor.GetAttributes()
                ):
                    raise ValueError("检测到摄影机或父级变换动画")
                ancestor = ancestor.GetParent()
            width, height = float(camera.GetHorizontalApertureAttr().Get()), float(
                camera.GetVerticalApertureAttr().Get()
            )
            clip = camera.GetClippingRangeAttr().Get()
            data = {
                "prim": str(prim.GetPath()),
                "label": prim.GetName(),
                "camera_type": "UsdCamera",
                "matrix": [list(row) for row in cache.GetLocalToWorldTransform(prim)],
                "focal_length_mm": float(camera.GetFocalLengthAttr().Get()),
                "aperture_width_mm": width,
                "aperture_height_mm": height,
                "horizontal_offset_mm": float(camera.GetHorizontalApertureOffsetAttr().Get()),
                "vertical_offset_mm": float(camera.GetVerticalApertureOffsetAttr().Get()),
                "aspect_ratio": width / height,
                "near_clip_cm": float(clip[0]),
                "far_clip_cm": float(clip[1]),
                "frame_hint": frame_hint(width / height),
                "warnings": [],
            }
            validate_camera(data)
            valid.append(data)
        except (ValueError, RuntimeError, ZeroDivisionError) as error:
            issues.append({"prim": str(prim.GetPath()), "reason": str(error)})
    return valid, issues, count
