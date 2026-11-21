"""Run integration tests only in separate Maya processes with isolated profiles."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(executable):
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise ValueError("Supply a valid Maya 2023 mayapy path with --mayapy")
    output = ROOT / ".test-results/maya"
    output.mkdir(parents=True, exist_ok=True)
    for name, filename in (("materials", "test_materials.py"), ("workflow", "test_workflow.py")):
        profile = output / ("profile_" + name + "_" + uuid4().hex[:8])
        profile.mkdir()
        report = output / (name + ".json")
        report.write_text('{"passed": false}', encoding="utf-8")
        environment = dict(os.environ)
        environment.update(
            MAYA_APP_DIR=str(profile),
            MAYA_SKIP_USERSETUP_PY="1",
            QT_QPA_PLATFORM="offscreen",
            PYTHONIOENCODING="utf-8",
        )
        with (output / (name + ".log")).open("wb") as log:
            process = subprocess.run(
                [str(executable), "-u", str(ROOT / "tests/maya" / filename)],
                cwd=str(ROOT),
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=240,
            )
        if process.returncode or not json.loads(report.read_text(encoding="utf-8")).get("passed"):
            raise RuntimeError(
                "Maya {} tests failed; inspect .test-results/maya/{}.log".format(name, name)
            )
        print("Maya {} tests passed.".format(name))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mayapy", default=shutil.which("mayapy"))
    args = parser.parse_args()
    if not args.mayapy:
        parser.error("Maya is not on PATH; provide --mayapy")
    run(args.mayapy)
