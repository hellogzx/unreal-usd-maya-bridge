"""Drop on Maya to create/update one shelf button and open the tool.

No Maya.env, startup scripts, system plugin files or existing shelf tabs changed.
The tool stays in its extracted folder; keep that folder in place.
"""

import sys
from pathlib import Path

SHELF = "USDSceneTool"
BUTTON = "USDSceneToolLaunchButton"


def install(open_window=True):
    import maya.cmds as cmds
    import maya.mel as mel

    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    shelf_parent = mel.eval("$tmpUsdShelf = $gShelfTopLevel;")
    if not cmds.shelfLayout(SHELF, exists=True):
        cmds.shelfLayout(SHELF, parent=shelf_parent)
    children = cmds.shelfLayout(SHELF, query=True, childArray=True) or []
    for child in children:
        if cmds.shelfButton(child, query=True, annotation=True) == "USD Scene and Material Tool":
            cmds.deleteUI(child)
    command = (
        "import sys\n"
        "p = {!r}\n"
        "if p not in sys.path: sys.path.insert(0, p)\n"
        "import usd_scene_tool\n"
        "usd_scene_tool.show()\n"
    ).format(str(root))
    cmds.shelfButton(
        BUTTON,
        parent=SHELF,
        label="USD",
        image="commandButton.png",
        imageOverlayLabel="USD",
        annotation="USD Scene and Material Tool",
        sourceType="python",
        command=command,
    )
    cmds.shelfTabLayout(shelf_parent, edit=True, selectTab=SHELF)
    shelves = Path(cmds.internalVar(userShelfDir=True))
    shelves.mkdir(parents=True, exist_ok=True)
    cmds.saveShelf(SHELF, str(shelves / ("shelf_" + SHELF)))
    if open_window:
        import usd_scene_tool

        return usd_scene_tool.show()
    return SHELF


def onMayaDroppedPythonFile(*args):
    try:
        return install()
    except Exception as exc:
        # Keep the tool usable if a customized Maya shelf layout prevents setup.
        import maya.cmds as cmds

        root = str(Path(__file__).resolve().parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        import usd_scene_tool

        window = usd_scene_tool.show()
        cmds.warning("USD 工具窗口已打开，但 Shelf 安装未完成：" + str(exc))
        return window


if __name__ == "__main__":
    onMayaDroppedPythonFile()
