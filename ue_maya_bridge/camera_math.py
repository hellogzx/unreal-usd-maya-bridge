"""Host-independent static pinhole camera validation and frame suggestions."""

import math
from fractions import Fraction


def frame_hint(aspect):
    if not math.isfinite(aspect) or not 0.1 <= aspect <= 10:
        raise ValueError("摄影机画幅比例超出 0.1–10 支持范围。")
    for ratio, width, height in (
        (16 / 9, 1920, 1080),
        (2.39, 2390, 1000),
        (9 / 16, 1080, 1920),
        (1.5, 1920, 1280),
    ):
        if abs(aspect - ratio) < 1e-5:
            return {"width": width, "height": height, "pixel_aspect": 1.0}
    fraction = Fraction(aspect).limit_denominator(1000)
    numerator, denominator = fraction.numerator, fraction.denominator
    scale = max(1, min(round(1920 / numerator), 16384 // max(numerator, denominator)))
    return {"width": numerator * scale, "height": denominator * scale, "pixel_aspect": 1.0}


def validate_camera(data, require_source=False):
    if not isinstance(data, dict):
        raise ValueError("无效的摄影机记录。")
    for name in ("prim", "label"):
        if not isinstance(data.get(name), str) or not data[name]:
            raise ValueError("摄影机缺少名称或 USD 路径。")
    if require_source and any(
        not isinstance(data.get(key), str) or not data[key]
        for key in ("id", "actor", "component", "camera_type")
    ):
        raise ValueError("摄影机缺少源对象标识。")
    for key in (
        "focal_length_mm",
        "aperture_width_mm",
        "aperture_height_mm",
        "aspect_ratio",
        "near_clip_cm",
        "far_clip_cm",
    ):
        value = data.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("摄影机参数无效：" + key)
    for key in ("horizontal_offset_mm", "vertical_offset_mm"):
        value = data.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("摄影机偏移无效：" + key)
    if data["far_clip_cm"] <= data["near_clip_cm"]:
        raise ValueError("摄影机裁切范围无效。")
    if abs(data["aperture_width_mm"] / data["aperture_height_mm"] - data["aspect_ratio"]) > 1e-5:
        raise ValueError("摄影机有效画幅与比例不同。")
    matrix = data.get("matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 4
        or any(
            not isinstance(row, list)
            or len(row) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
            for row in matrix
        )
    ):
        raise ValueError("摄影机世界矩阵无效。")
    for i in range(3):
        for j in range(3):
            dot = sum(matrix[i][k] * matrix[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > 1e-5:
                raise ValueError("摄影机世界矩阵含缩放或剪切，首版只支持刚体摄影机。")
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    if (
        determinant < 0
        or any(abs(matrix[i][3]) > 1e-8 for i in range(3))
        or abs(matrix[3][3] - 1) > 1e-8
    ):
        raise ValueError("摄影机矩阵不是有效的右手刚体变换。")
    hint = data.get("frame_hint")
    if (
        not isinstance(hint, dict)
        or any(
            type(hint.get(key)) is not int or not 1 <= hint[key] <= 16384
            for key in ("width", "height")
        )
        or hint.get("pixel_aspect") != 1.0
    ):
        raise ValueError("摄影机建议输出画幅无效。")
    if abs(hint["width"] / hint["height"] - data["aspect_ratio"]) > 1e-5:
        raise ValueError("建议输出尺寸与摄影机比例不同。")
    return data
