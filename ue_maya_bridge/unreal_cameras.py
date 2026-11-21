"""Export evaluated static CameraActor/CineCameraActor pinhole snapshots."""

import hashlib
import math

from .camera_math import frame_hint, validate_camera

CAMERA_TYPES = {"CameraComponent", "CineCameraComponent"}


def inspect_cameras(actors, unreal, enabled=True):
    from pxr import Tf

    cameras, skipped = [], []
    for actor in dict.fromkeys(actors):
        for component in actor.get_components_by_class(unreal.SceneComponent):
            if component.get_class().get_name() not in CAMERA_TYPES:
                continue
            try:
                if not enabled:
                    raise ValueError("本次未启用静态摄影机导出。")
                if not isinstance(actor, unreal.CameraActor):
                    raise ValueError("首版只支持 CameraActor / CineCameraActor 内的摄影机组件。")
                view = component.get_camera_view(0.0)
                if view.projection_mode != unreal.CameraProjectionMode.PERSPECTIVE:
                    raise ValueError("首版仅支持透视摄影机，正交摄影机已跳过。")
                if not 0.01 < float(view.fov) < 179:
                    raise ValueError("摄影机视角超出静态针孔快照支持范围。")
                focal = (
                    float(component.get_editor_property("current_focal_length"))
                    if component.get_class().get_name() == "CineCameraComponent"
                    else 36.0 / (2 * math.tan(math.radians(view.fov) / 2))
                )
                aperture_w = 2 * focal * math.tan(math.radians(view.fov) / 2)
                aperture_h = aperture_w / float(view.aspect_ratio)
                offset = view.off_center_projection_offset
                right = unreal.MathLibrary.get_right_vector(view.rotation)
                up = unreal.MathLibrary.get_up_vector(view.rotation)
                forward = unreal.MathLibrary.get_forward_vector(view.rotation)
                rows = [
                    [float(v.x), float(v.z), float(v.y), 0.0] for v in (right, up, forward * -1.0)
                ]
                rows += [
                    [float(view.location.x), float(view.location.z), float(view.location.y), 1.0]
                ]
                identity = component.get_path_name()
                suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
                prim = "/UE_Previs/Cameras/{}_{}".format(
                    Tf.MakeValidIdentifier(actor.get_actor_label()), suffix
                )
                near = float(view.perspective_near_clip_plane)
                if near <= 0:
                    # For UE's reversed-Z infinite-far perspective matrix the
                    # translation-row Z is the actual resolved near plane.
                    # This also respects runtime near-plane overrides.
                    projection = unreal.GameplayStatics.get_view_projection_matrix(view)[1]
                    near = float(projection.get_origin().z)
                warnings = []
                if not component.get_editor_property("constrain_aspect_ratio"):
                    warnings.append("UE 未锁定宽高比；匹配以记录的摄影机目标画幅为准。")
                data = {
                    "id": identity,
                    "actor": actor.get_path_name(),
                    "component": identity,
                    "label": actor.get_actor_label(),
                    "camera_type": component.get_class().get_name(),
                    "prim": prim,
                    "matrix": rows,
                    "focal_length_mm": focal,
                    "aperture_width_mm": aperture_w,
                    "aperture_height_mm": aperture_h,
                    "horizontal_offset_mm": float(offset.x) * aperture_w / 2,
                    "vertical_offset_mm": float(offset.y) * aperture_h / 2,
                    "aspect_ratio": float(view.aspect_ratio),
                    "near_clip_cm": max(0.001, near),
                    "far_clip_cm": 1e9,
                    "frame_hint": frame_hint(float(view.aspect_ratio)),
                    "snapshot": True,
                    "warnings": warnings,
                    "focal_source": (
                        "authored"
                        if component.get_class().get_name() == "CineCameraComponent"
                        else "derived_from_horizontal_fov"
                    ),
                }
                if data["focal_source"] == "authored":
                    filmback = component.get_editor_property("filmback")
                    data["original_filmback_mm"] = [
                        float(filmback.sensor_width),
                        float(filmback.sensor_height),
                    ]
                    if (
                        abs(filmback.sensor_width - aperture_w) > 1e-4
                        or abs(filmback.sensor_height - aperture_h) > 1e-4
                    ):
                        warnings.append("裁切／挤压／Overscan 已等效进有效画幅；不传递景深和畸变。")
                else:
                    warnings.append(
                        "普通 CameraActor 使用 36 mm 虚拟画幅宽度换算焦距，不代表原始物理传感器。"
                    )
                validate_camera(data, require_source=True)
                cameras.append(data)
            except (ValueError, RuntimeError, ZeroDivisionError) as error:
                skipped.append(
                    {
                        "actor": actor.get_path_name(),
                        "label": actor.get_actor_label(),
                        "component": component.get_path_name(),
                        "instance_index": None,
                        "type": component.get_class().get_name(),
                        "reasons": [str(error)],
                    }
                )
    return cameras, skipped


def write_cameras(stage, cameras):
    from pxr import UsdGeom, Gf

    if cameras:
        UsdGeom.Scope.Define(stage, "/UE_Previs/Cameras")
    for item in cameras:
        camera = UsdGeom.Camera.Define(stage, item["prim"])
        camera.AddTransformOp().Set(Gf.Matrix4d(*[v for row in item["matrix"] for v in row]))
        camera.CreateProjectionAttr(UsdGeom.Tokens.perspective)
        for key, method in (
            ("focal_length_mm", "CreateFocalLengthAttr"),
            ("aperture_width_mm", "CreateHorizontalApertureAttr"),
            ("aperture_height_mm", "CreateVerticalApertureAttr"),
            ("horizontal_offset_mm", "CreateHorizontalApertureOffsetAttr"),
            ("vertical_offset_mm", "CreateVerticalApertureOffsetAttr"),
        ):
            getattr(camera, method)(item[key])
        camera.CreateClippingRangeAttr(Gf.Vec2f(item["near_clip_cm"], item["far_clip_cm"]))
        camera.CreateFStopAttr(0.0)
        camera.GetPrim().SetCustomDataByKey("ueActorPath", item["actor"])
        camera.GetPrim().SetCustomDataByKey("ueCameraComponent", item["component"])
        camera.GetPrim().SetCustomDataByKey("ueStaticSnapshot", True)
