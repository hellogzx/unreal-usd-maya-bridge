"""Export quality policy, shared by UE, Maya report validation and tests."""

DEFAULTS = {
    "nanite_mode": "skip",
    "lod_index": 0,
    "missing_lod": "skip",
    "asset_format": "usdc",
    "include_cameras": True,
}


def normalize_options(options=None):
    if options is not None and not isinstance(options, dict):
        raise ValueError("导出设置必须为字典。")
    options = {} if options is None else dict(options)
    unknown = set(options) - set(DEFAULTS)
    if unknown:
        raise ValueError("未知导出设置：" + ", ".join(sorted(map(str, unknown))))
    result = dict(DEFAULTS, **options)
    if result["nanite_mode"] not in ("skip", "proxy"):
        raise ValueError("Nanite 只支持跳过或渲染代理，不提供源网格高精度保证。")
    if type(result["lod_index"]) is not int or not 0 <= result["lod_index"] <= 7:
        raise ValueError("LOD 必须是 0 到 7 的整数。")
    if result["missing_lod"] not in ("skip", "lod0"):
        raise ValueError("LOD 缺失策略只支持跳过或退回 LOD0。")
    if result["asset_format"] not in ("usda", "usdc"):
        raise ValueError("几何资源格式只支持 USDA 或 USDC。")
    if type(result["include_cameras"]) is not bool:
        raise ValueError("包含摄影机必须为布尔值。")
    return result


def choose_geometry(lod_count, nanite, options=None):
    options = normalize_options(options)
    if type(lod_count) is not int or lod_count < 1 or type(nanite) is not bool:
        raise ValueError("没有可读取的渲染 LOD 数据。")
    if nanite and options["nanite_mode"] == "skip":
        raise ValueError("Nanite 已按当前设置跳过；可选择快速代理（近似外形）。")
    requested = options["lod_index"]
    effective = requested
    fallback = requested >= lod_count
    if fallback:
        if options["missing_lod"] == "skip":
            raise ValueError(
                "请求 LOD{}，资源仅有 {} 个 LOD，按设置跳过。".format(requested, lod_count)
            )
        effective = 0
    return {
        "requested_lod": requested,
        "effective_lod": effective,
        "lod_fallback": fallback,
        "nanite": nanite,
        "geometry_source": "nanite_render_proxy" if nanite else "render_lod",
        "approximate": nanite,
        "asset_format": options["asset_format"],
    }


def choice_label(choice):
    text = "Nanite 渲染代理（近似）" if choice["nanite"] else "渲染网格"
    text += " · LOD{}".format(choice["effective_lod"])
    if choice["lod_fallback"]:
        text += "（从 LOD{} 回退）".format(choice["requested_lod"])
    return text + " · " + choice["asset_format"].upper()
