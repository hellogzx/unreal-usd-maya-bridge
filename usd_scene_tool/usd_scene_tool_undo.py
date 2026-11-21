"""Python Maya plugin: undo all nodes from an additive USD load as one action."""

import json
from maya.api import OpenMaya as om


def maya_useNewAPI():
    pass


class LoadCommand(om.MPxCommand):
    NAME = "usdSceneToolLoad"

    def __init__(self):
        super().__init__()
        self.modifier = None
        self.objects = []

    @staticmethod
    def creator():
        return LoadCommand()

    def isUndoable(self):
        return True

    def doIt(self, args):
        from maya import cmds
        from usd_scene_tool import core

        request = json.loads(args.asString(0))
        before = core._uuids()
        undo_enabled = cmds.undoInfo(query=True, state=True)
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            result = core._load_file_impl(**request)
            iterator = om.MItDependencyNodes()
            while not iterator.isDone():
                obj = iterator.thisNode()
                if om.MFnDependencyNode(obj).uuid().asString() not in before:
                    self.objects.append(om.MObjectHandle(obj))
                iterator.next()
            self.setResult(json.dumps(result, ensure_ascii=True))
        finally:
            cmds.undoInfo(stateWithoutFlush=undo_enabled)

    def undoIt(self):
        # A DAG modifier can handle both DAG and ordinary dependency nodes.
        # Queue only top-level new DAG nodes; their children delete recursively.
        self.modifier = om.MDagModifier()
        new_ids = {h.hashCode() for h in self.objects if h.isValid() and h.isAlive()}
        for handle in self.objects:
            if not handle.isValid() or not handle.isAlive():
                continue
            obj = handle.object()
            if obj.hasFn(om.MFn.kDagNode):
                dag = om.MFnDagNode(obj)
                if any(
                    om.MObjectHandle(dag.parent(i)).hashCode() in new_ids
                    for i in range(dag.parentCount())
                ):
                    continue
            self.modifier.deleteNode(obj)
        self.modifier.doIt()

    def redoIt(self):
        if self.modifier is not None:
            self.modifier.undoIt()


def initializePlugin(plugin):
    om.MFnPlugin(plugin, "USD Scene Material Tool", "0.9.2", "Any").registerCommand(
        LoadCommand.NAME, LoadCommand.creator
    )


def uninitializePlugin(plugin):
    om.MFnPlugin(plugin).deregisterCommand(LoadCommand.NAME)
