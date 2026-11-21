"""Run in Maya, or drop this file onto Maya's viewport."""

import sys
from pathlib import Path


def launch():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    import usd_scene_tool

    return usd_scene_tool.show()


def onMayaDroppedPythonFile(*args):
    return launch()


if __name__ == "__main__":
    launch()
