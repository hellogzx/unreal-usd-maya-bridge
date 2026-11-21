"""Drop this file in Maya to open the simple USD -> PBR importer."""

import sys
from pathlib import Path


def launch():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from usd_scene_tool.simple_pbr import show

    return show()


def onMayaDroppedPythonFile(*args):
    return launch()


if __name__ == "__main__":
    launch()
