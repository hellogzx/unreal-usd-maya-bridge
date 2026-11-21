"""Build reproducible, explicit-allowlist ZIPs without machine-local reports."""

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SHARED = (
    "__init__",
    "camera_math",
    "package",
    "usd_cameras",
    "usd_options",
    "usd_package",
    "usd_scene",
    "versions",
)
UNREAL = ("unreal_cameras", "unreal_ui", "unreal_usd")


def version():
    module = ast.parse((ROOT / "usd_scene_tool/__init__.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("Missing receiver version")


def validate(directory):
    if directory is None:
        return {"status": "not-run-for-this-build"}
    reports = {}
    expected = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("usd_scene_tool", "ue_maya_bridge")
        for path in (ROOT / folder).glob("*.py")
    }
    for name in ("materials", "workflow"):
        report = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
        if not report.get("passed") or report.get("version") != version():
            raise RuntimeError("Maya acceptance did not pass: " + name)
        if report.get("source_sha256") != expected:
            raise RuntimeError("Maya acceptance is stale: " + name)
        # Publish environment and acceptance flags, never absolute sample paths.
        reports[name] = {
            key: value
            for key, value in report.items()
            if isinstance(value, bool) or key in ("version", "environment", "test_mode", "checks")
        }
    return {"status": "passed-for-current-source", "reports": reports}


def payload(workflow):
    paths = list((ROOT / "usd_scene_tool").glob("*.py"))
    paths += [
        ROOT / "ue_maya_bridge" / (name + ".py") for name in SHARED + (UNREAL if workflow else ())
    ]
    paths += [
        ROOT / name
        for name in (
            "launch_usd_pbr_simple.py",
            "launch_usd_tool.py",
            "install_usd_tool.py",
            "README.md",
            "README_EN.md",
            "LICENSE",
            "CHANGELOG.md",
            "THIRD_PARTY_NOTICES.md",
        )
    ]
    if workflow:
        paths.append(ROOT / "launch_unreal_usd.py")
    paths += [path for path in (ROOT / "docs").rglob("*") if path.is_file()]
    paths += list((ROOT / "usd_learning").glob("*.usda"))
    paths += list((ROOT / "usd_learning").glob("*.md"))
    paths += list((ROOT / "usd_learning/textures").glob("*.png"))
    return sorted(set(paths))


def build(validation_directory=None):
    from check_repository import check

    check()
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_*.py"],
        cwd=str(ROOT),
        check=True,
    )
    validation = validate(validation_directory)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archives = []
    for workflow, prefix, stem in (
        (False, "USDStandardSurfaceSimple", "usd_maya_material_simple"),
        (True, "UEUSDMayaWorkflow", "ue_usd_maya_workflow"),
    ):
        paths = payload(workflow)
        content = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        metadata = {
            "version": version(),
            "unreal_exporter_version": "0.5.0",
            "includes_unreal_exporter": workflow,
            "maya_validation": validation,
            "source_sha256": {
                name: hashlib.sha256(data).hexdigest() for name, data in content.items()
            },
            "limitations": [
                "Maya 2023 / Windows is the tested runtime; other hosts are not certified.",
                "Static UsdPreviewSurface metal/rough with st UV and repeat only.",
                "Phong uses preview approximations, not equivalent PBR shading.",
                "Isolated native recovery may expand shared instances.",
                "No external photographic assets or host SDK binaries are included.",
            ],
        }
        content["VERIFICATION.json"] = json.dumps(metadata, ensure_ascii=False, indent=2).encode(
            "utf-8"
        )
        archive = output / (stem + "_v" + version() + ".zip")
        with ZipFile(archive, "w", ZIP_DEFLATED) as target:
            for name, data in sorted(content.items()):
                item = ZipInfo(prefix + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
                item.compress_type = ZIP_DEFLATED
                item.external_attr = 0o644 << 16
                target.writestr(item, data)
        with ZipFile(archive) as target:
            if target.testzip() is not None:
                raise RuntimeError("Corrupt release ZIP")
        archives.append(
            {"name": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        )
        print(archive.name)
    (output / "SHA256SUMS.txt").write_text(
        "".join(item["sha256"] + "  " + item["name"] + "\n" for item in archives), encoding="utf-8"
    )
    return archives


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-dir", type=Path, help="Current-source Maya acceptance report directory"
    )
    arguments = parser.parse_args()
    build(arguments.validation_dir)
