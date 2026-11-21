"""Lossless channel extraction using Maya's bundled Qt image reader.

No color transform or gain/bias is baked. Generated files are persistent assets:
Undo removes scene nodes only, so Redo can keep using the same images.
"""

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ALGORITHM = "raw-channel-png-v1"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def extract_channel(source, channel, usage, directory):
    """Write one grayscale PNG, preserving 8-bit or 16-bit integer samples."""
    from PySide2.QtGui import QImage

    source = Path(source).resolve()
    directory = Path(directory).resolve()
    if channel not in ("r", "g", "b", "a") or usage not in ("roughness", "metallic"):
        raise ValueError("无效的标量贴图拆分请求。")
    if not source.is_file():
        raise ValueError("独立通道拆分需要存在的源贴图：" + str(source))
    if source.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("独立通道拆分目前支持 PNG／JPEG；请先将数据贴图转成 PNG：" + str(source))
    source_hash = digest(source)
    identity = hashlib.sha256(
        (ALGORITHM + source_hash + channel + usage).encode("ascii")
    ).hexdigest()[:24]
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", source.stem)[:60] or "Texture"
    destination = directory / (stem + "_" + usage + "_" + identity + ".png")
    metadata = destination.with_suffix(".json")
    if destination.is_file() and metadata.is_file():
        try:
            cached = json.loads(metadata.read_text(encoding="utf-8"))
            if (
                cached.get("algorithm") == ALGORITHM
                and cached.get("source_sha256") == source_hash
                and cached.get("source_channel") == channel
                and cached.get("usage") == usage
                and cached.get("output_sha256") == digest(destination)
            ):
                return dict(cached, source=str(source), path=str(destination), reused=True)
        except (ValueError, OSError):
            pass
    image = QImage(str(source))
    if image.isNull():
        raise ValueError("Qt 无法读取源贴图：" + str(source))
    high_precision = image.format() in (
        QImage.Format_Grayscale16,
        QImage.Format_RGBX64,
        QImage.Format_RGBA64,
        QImage.Format_RGBA64_Premultiplied,
    )
    bits = 16 if high_precision else 8
    image = image.convertToFormat(
        QImage.Format_RGBA64 if high_precision else QImage.Format_RGBA8888
    )
    output = QImage(
        image.width(),
        image.height(),
        QImage.Format_Grayscale16 if high_precision else QImage.Format_Grayscale8,
    )
    if image.isNull() or output.isNull():
        raise ValueError("无法分配贴图拆分图像。")
    output.fill(0)
    source_pixels = image.constBits()
    output_pixels = output.bits()
    component = ("r", "g", "b", "a").index(channel)
    for row in range(image.height()):
        start = row * image.bytesPerLine()
        line = source_pixels[start : start + image.width() * (8 if high_precision else 4)]
        values = (
            line.cast("H")[component::4].tobytes()
            if high_precision
            else line[component::4].tobytes()
        )
        out_start = row * output.bytesPerLine()
        output_pixels[out_start : out_start + len(values)] = values
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".channel_", suffix=".png", dir=str(directory))
        os.close(fd)
        try:
            if not output.save(temporary, "PNG"):
                raise ValueError("无法写入独立通道 PNG。")
            result = {
                "algorithm": ALGORITHM,
                "source": str(source),
                "source_sha256": source_hash,
                "source_channel": channel,
                "usage": usage,
                "path": str(destination),
                "width": image.width(),
                "height": image.height(),
                "bits": bits,
                "output_sha256": digest(temporary),
            }
            os.replace(temporary, str(destination))
        finally:
            if os.path.isfile(temporary):
                os.unlink(temporary)
        fd, temporary = tempfile.mkstemp(prefix=".channel_", suffix=".json", dir=str(directory))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, str(metadata))
        finally:
            if os.path.isfile(temporary):
                os.unlink(temporary)
    except OSError as error:
        raise ValueError(
            "无法写入拆分贴图目录，请在工具中选择可写的输出目录：{}；{}".format(directory, error)
        ) from error
    return dict(result, reused=False)


def prepare(plans, scene, output_directory=""):
    """Return independent descriptors without changing source USD or its plans."""
    scene = Path(scene).resolve()
    directory = (
        Path(output_directory).expanduser()
        if output_directory
        else scene.parent / "Maya_PBR_Textures"
    )
    if not directory.is_absolute():
        directory = scene.parent / directory
    effective = copy.deepcopy(plans)
    extractions = []
    for plan in effective:
        for usage in ("roughness", "metallic"):
            data = plan["inputs"][usage].get("texture")
            if data is None:
                continue
            record = extract_channel(data["path"], data["channel"], usage, directory)
            extractions.append(record)
            component = ("r", "g", "b", "a").index(data["channel"])
            scale, bias, fallback = (
                data["scale"][component],
                data["bias"][component],
                data["fallback"][component],
            )
            data.update(
                source_path=data["path"],
                source_channel=data["channel"],
                path=Path(record["path"]).as_posix(),
                channel="r",
                scale=[scale, scale, scale, 1],
                bias=[bias, bias, bias, 0],
                fallback=[fallback, fallback, fallback, 1],
            )
    return effective, extractions
