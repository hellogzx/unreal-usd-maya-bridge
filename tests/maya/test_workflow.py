"""Portable UI, Phong, camera, rollback and isolated-reader acceptance.

Run only through a fresh Maya standalone process, never in an artist session.
USD_BRIDGE_PROJECT_ROOT allows the same test to verify an extracted release.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import hashlib
import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(
    os.environ.get("USD_BRIDGE_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()
OUTPUT = Path(os.environ.get("USD_BRIDGE_TEST_OUTPUT", ROOT / ".test-results/maya"))
RUNTIME = OUTPUT / "workflow" / uuid4().hex[:8]
sys.path.insert(0, str(ROOT))


def run():
    import maya.cmds as cmds
    from usd_scene_tool import __version__, core, native_import, show, simple_pbr

    core.environment()
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
    from PySide2 import QtWidgets

    RUNTIME.mkdir(parents=True, exist_ok=True)
    output = OUTPUT / "workflow.json"
    output.write_text('{"passed":false}', encoding="utf-8")
    cmds.currentUnit(linear="cm")
    cmds.upAxis(axis="y")
    artist = cmds.polyCube(name="ArtistKeep")[0]
    baseline = core._uuids()
    source = ROOT / "usd_learning/05_pbr_separate_textures.usda"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    maps = {
        "diffuseColor": ROOT / "usd_learning/textures/pbr_basecolor.png",
        "metallic": ROOT / "usd_learning/textures/pbr_metallic.png",
        "roughness": ROOT / "usd_learning/textures/pbr_roughness.png",
        "normal": ROOT / "usd_learning/textures/pbr_normal.png",
    }
    window = simple_pbr.Window()
    window.show()
    assert not window.options.isVisible() and not window.import_button.isEnabled()
    window.sample_button.click()
    assert window.inspection and window.target.count() == 2
    assert window.target_row.isVisible()
    for mode, node_type in (("pbr", "standardSurface"), ("phong_preview", "phong")):
        window.material_mode.setCurrentIndex(window.material_mode.findData(mode))
        window.import_button.click()
        result = window.result
        assert result and result["mode"] == mode, window.details.toPlainText()
        assert result["native_mesh_paths"] == 2 and len(result["materials"]) == 2
        assert len(result["textures"]) == 8
        assert all(set(item["channel_textures"]) == set(maps) for item in result["materials"])
        for item in result["materials"]:
            assert cmds.nodeType(item["node"]) == node_type
            assert cmds.listConnections(
                item["node"] + ".normalCamera", source=True, destination=False
            )
        # Publish screenshots with a relative display path, without machine identifiers.
        screenshot_name = "simple-pbr.png" if mode == "pbr" else "phong-preview.png"
        if (ROOT / "docs/images").is_dir() and not os.environ.get("USD_BRIDGE_NO_SCREENSHOTS"):
            window.path.blockSignals(True)
            window.path.setText("usd_learning/05_pbr_separate_textures.usda")
            window.path.blockSignals(False)
            QtWidgets.QApplication.processEvents()
            assert window.grab().save(str(ROOT / "docs/images" / screenshot_name))
        if mode == "phong_preview":
            material = result["materials"][0]
            node = material["node"]
            rough = material["channel_textures"]["roughness"]["node"]
            metal = material["channel_textures"]["metallic"]["node"]
            enabled = cmds.undoInfo(query=True, state=True)
            cmds.undoInfo(stateWithoutFlush=False)
            try:
                for value, expected in ((0, 1000), (0.2, 48), (0.8, 2), (1, 2)):
                    cmds.setAttr(rough + ".colorGain", 0, 0, 0, type="double3")
                    cmds.setAttr(rough + ".colorOffset", value, value, value, type="double3")
                    assert abs(cmds.getAttr(node + ".cosinePower") - expected) < 1e-3
                for value in (0, 1):
                    cmds.setAttr(metal + ".colorGain", 0, 0, 0, type="double3")
                    cmds.setAttr(metal + ".colorOffset", value, value, value, type="double3")
                    assert abs(cmds.getAttr(node + ".diffuse") - (1 - value)) < 1e-5
                    expected = cmds.getAttr(node + ".color")[0] if value else [0.04] * 3
                    actual = cmds.getAttr(node + ".specularColor")[0]
                    assert all(abs(a - b) < 1e-5 for a, b in zip(actual, expected))
            finally:
                cmds.undoInfo(stateWithoutFlush=enabled)
        cmds.undo()
        assert core._uuids() == baseline
        cmds.redo()
        assert all(cmds.ls(item["uuid"]) for item in result["materials"])
        cmds.undo()
        assert core._uuids() == baseline

    # File-picker input and all four manual maps are scoped to one material.
    window.material_mode.setCurrentIndex(window.material_mode.findData("pbr"))
    window.path.setText(str(source))
    assert window.inspect()
    window.target.setCurrentIndex(1)
    target = window.target.currentData()
    with patch.object(
        QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(maps["normal"]), "")
    ):
        window.channel_buttons["diffuseColor"].click()
    for role in ("metallic", "roughness", "normal"):
        window.channel_fields[role].setText(str(maps[role]))
    window.import_button.click()
    manual = window.result
    assert manual and set(manual["material_overrides"]) == {target}, window.details.toPlainText()
    for item in manual["materials"]:
        path = item["channel_textures"]["diffuseColor"]["source_path"]
        assert Path(path).name == (
            "pbr_normal.png" if item["usd_material"] == target else "pbr_basecolor.png"
        )
    cmds.undo()
    assert core._uuids() == baseline

    # Repair one missing source image without masking unrelated missing files.
    broken = RUNTIME / "missing_color.usda"
    Usd.Stage.Open(str(source)).Flatten().Export(str(broken))
    stage = Usd.Stage.Open(str(broken))
    material = UsdShade.Material(stage.GetPrimAtPath(target))
    surface = material.ComputeSurfaceSource()[0]
    texture = UsdShade.Shader(surface.GetInput("diffuseColor").GetConnectedSource()[0].GetPrim())
    texture.GetInput("file").Set(Sdf.AssetPath("missing_color.png"))
    stage.GetRootLayer().Save()
    window.path.setText(str(broken))
    assert window.inspect()
    window.target.setCurrentIndex(window.target.findData(target))
    window.channel_fields["diffuseColor"].setText(str(maps["diffuseColor"]))
    window.import_button.click()
    assert (
        window.result and window.result["source"] == broken.as_posix()
    ), window.details.toPlainText()
    cmds.undo()
    assert core._uuids() == baseline

    # Geometry without a binding can receive maps, but absent UVs cannot.
    naked = RUNTIME / "unbound.usda"
    Usd.Stage.Open(str(ROOT / "usd_learning/01_material_binding.usda")).Flatten().Export(str(naked))
    stage = Usd.Stage.Open(str(naked))
    stage.GetPrimAtPath("/Demo/Card").RemoveProperty("material:binding")
    stage.RemovePrim("/Demo/Looks")
    stage.GetRootLayer().Save()
    window.path.setText(str(naked))
    assert window.inspect() and window.target.currentData() == "__unbound__"
    for role, path in maps.items():
        window.channel_fields[role].setText(str(path))
    window.import_button.click()
    assert window.result and len(window.result["materials"]) == 1, window.details.toPlainText()
    cmds.undo()
    assert core._uuids() == baseline
    window.channel_fields["normal"].setText(str(RUNTIME / "absent.png"))
    window.import_button.click()
    assert "找不到" in window.details.toPlainText() and core._uuids() == baseline
    window.channel_fields["normal"].setText(str(maps["normal"]))
    stage.GetPrimAtPath("/Demo/Card").RemoveProperty("primvars:st")
    stage.GetRootLayer().Save()
    window.import_button.click()
    assert "st UV" in window.details.toPlainText() and core._uuids() == baseline

    # A synthetic camera scene replaces all private historical export fixtures.
    camera_scene = RUNTIME / "cameras.usda"
    Usd.Stage.Open(str(source)).Flatten().Export(str(camera_scene))
    stage = Usd.Stage.Open(str(camera_scene))
    for index in range(2):
        camera = UsdGeom.Camera.Define(stage, "/PBR_Demo/Camera" + str(index))
        camera.CreateFocalLengthAttr(35 + index * 15)
        camera.CreateHorizontalApertureAttr(36)
        camera.CreateVerticalApertureAttr(20.25)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 100000))
        camera.AddTranslateOp().Set(Gf.Vec3d(index * 100, 200, 600))
    stage.GetRootLayer().Save()

    def empty_import(**kwargs):
        return [cmds.createNode("transform", name="EmptyReaderHierarchy", parent=kwargs["parent"])]

    for mode in ("pbr", "phong_preview", "phong"):
        sample = ROOT / "usd_learning/02_texture_binding.usda" if mode == "phong" else camera_scene
        with patch.object(cmds, "mayaUSDImport", side_effect=empty_import):
            recovered = core.load_file(
                sample, mode, texture_output_directory=str(RUNTIME / "channels")
            )
        assert recovered["native_compatibility"]
        assert recovered["native_mesh_paths"] == (1 if mode == "phong" else 2)
        assert recovered["native_cameras"] == (0 if mode == "phong" else 2)
        assert not cmds.ls("*:EmptyReaderHierarchy") and not cmds.ls("*:_USDNativeTransfer")
        cmds.undo()
        assert core._uuids() == baseline
        cmds.redo()
        assert all(cmds.ls(item["uuid"]) for item in recovered["materials"])
        cmds.undo()
        assert core._uuids() == baseline
    with (
        patch.object(cmds, "mayaUSDImport", side_effect=empty_import),
        patch.object(
            native_import.subprocess, "run", side_effect=OSError("Injected worker failure")
        ),
    ):
        try:
            core.load_file(source, "pbr", texture_output_directory=str(RUNTIME / "channels"))
            raise AssertionError("Expected worker failure")
        except core.ToolError as error:
            assert "Injected worker failure" in str(error)
    assert core._uuids() == baseline
    window.advanced_button.click()
    from usd_scene_tool import ui

    assert ui._WINDOW and ui._WINDOW.isVisible()
    ui._WINDOW.close()
    window.close()
    public = show()
    assert show() is public and isinstance(public, simple_pbr.Window)
    launcher = runpy.run_path(str(ROOT / "launch_usd_pbr_simple.py"))
    assert launcher["onMayaDroppedPythonFile"]() is public
    public.close()

    # Save/reopen is separate from Undo tests: saving may add its own history.
    saved = core.load_file(
        camera_scene, "phong_preview", texture_output_directory=str(RUNTIME / "channels")
    )
    cmds.file(rename=str(RUNTIME / "roundtrip.ma"))
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(str(RUNTIME / "roundtrip.ma"), open=True, force=True)
    assert cmds.objExists(artist) and all(cmds.ls(item["uuid"]) for item in saved["materials"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    result = {
        "passed": True,
        "version": __version__,
        "environment": core.environment(),
        "test_mode": "dedicated actual Maya standalone, Qt offscreen",
        "checks": {
            name: True
            for name in (
                "simple_ui",
                "standard_surface",
                "phong",
                "phong_endpoint_values",
                "manual_four_maps",
                "per_material_overrides",
                "missing_image_repair",
                "unbound_geometry",
                "missing_uv_rejected",
                "compatibility_all_native_modes",
                "compatibility_real_process",
                "worker_failure_rollback",
                "camera_transfer",
                "undo_redo",
                "save_reopen",
                "source_unchanged",
                "artist_nodes_preserved",
            )
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in ("usd_scene_tool", "ue_maya_bridge")
            for path in (ROOT / folder).glob("*.py")
        },
    }
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("MAYA_WORKFLOW_PASS")


if __name__ == "__main__":
    from PySide2 import QtGui, QtWidgets

    APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for font in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"):
        QtGui.QFontDatabase.addApplicationFont(font)
    import maya.standalone

    maya.standalone.initialize(name="python")
    try:
        run()
    finally:
        maya.standalone.uninitialize()
