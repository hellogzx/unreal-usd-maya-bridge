"""Host-independent scene package validation. No executable data in manifests."""

import hashlib
import json
import math
from pathlib import Path

FORMAT = "ue-maya-static-scene"
VERSION = 1


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_vector(value, count):
    return (
        isinstance(value, list)
        and len(value) == count
        and all(type(item) in (int, float) and math.isfinite(item) for item in value)
    )


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("This is not a UE-to-Maya scene package.")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise ValueError("Unsupported package version.")
    if data.get("placement") != "native_scene_fbx":
        raise ValueError("Unsupported placement convention; do not reapply audit transforms.")
    payload = data.get("payload", {})
    if not isinstance(payload, dict) or payload.get("file") != "scene.fbx":
        raise ValueError("The payload must be the local scene.fbx file.")
    digest = payload.get("sha256", "")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("Invalid FBX checksum.")
    if type(payload.get("bytes")) is not int or payload["bytes"] <= 0:
        raise ValueError("Invalid FBX size.")
    actors = data.get("actors")
    if not isinstance(actors, list) or not actors:
        raise ValueError("The package has no actors.")
    ids = set()
    for actor in actors:
        if not isinstance(actor, dict) or not isinstance(actor.get("id"), str):
            raise ValueError("Invalid actor entry.")
        if actor["id"] in ids:
            raise ValueError("Duplicate actor ID.")
        ids.add(actor["id"])
        components = actor.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError("An actor has no mesh components.")
        for component in components:
            if not isinstance(component, dict):
                raise ValueError("Invalid component entry.")
            transform = component.get("world_transform", {})
            if not isinstance(transform, dict) or not all(
                (
                    _finite_vector(transform.get("translation_cm"), 3),
                    _finite_vector(transform.get("rotation_xyzw"), 4),
                    _finite_vector(transform.get("scale"), 3),
                )
            ):
                raise ValueError("Invalid or non-finite component transform.")
    return data


def load_package(path):
    """Validate metadata and content before starting any Maya scene mutation."""
    path = Path(path).expanduser().resolve()
    manifest = path / "manifest.json" if path.is_dir() else path
    if manifest.name != "manifest.json":
        raise ValueError("Choose a package folder or its manifest.json.")
    if manifest.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Manifest exceeds the 16 MiB prototype limit.")
    with manifest.open("r", encoding="utf-8") as stream:
        data = validate_manifest(json.load(stream))
    fbx = manifest.parent / "scene.fbx"
    if fbx.is_symlink() or fbx.resolve().parent != manifest.parent:
        raise ValueError("FBX must be a regular file inside the package.")
    if not fbx.is_file() or fbx.stat().st_size != data["payload"]["bytes"]:
        raise ValueError("FBX is missing or its size does not match the manifest.")
    if sha256_file(fbx) != data["payload"]["sha256"]:
        raise ValueError("FBX checksum does not match; export a fresh package.")
    return manifest, fbx, data
