"""Run through Unreal: Tools > Execute Python Script. No project edits."""

import sys
from pathlib import Path


def launch():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from ue_maya_bridge.unreal_usd import install_menu
    from ue_maya_bridge.unreal_ui import show

    install_menu()
    return show()


if __name__ == "__main__":
    launch()
