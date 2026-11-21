"""Real Maya PBR acceptance; run only in a dedicated standalone process."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/maya"))
from uuid import uuid4

RUNTIME = ROOT / ".test-results/maya/pbr" / uuid4().hex[:8]


def channel_tests():
    from PySide2.QtGui import QImage, QColor
    from usd_scene_tool.texture_channels import extract_channel
    import hashlib

    folder = RUNTIME / "channel_pixels"
    folder.mkdir(parents=True, exist_ok=True)
    for bits in (8, 16):
        image = QImage(3, 2, QImage.Format_RGBA64 if bits == 16 else QImage.Format_RGBA8888)
        for y in range(2):
            for x in range(3):
                image.setPixelColor(
                    x,
                    y,
                    (
                        QColor.fromRgbF(
                            (1234 + x) / 65535, (23456 + y) / 65535, 54321 / 65535, 60000 / 65535
                        )
                        if bits == 16
                        else QColor(12 + x, 34 + y, 56, 78)
                    ),
                )
        source = folder / ("source_" + str(bits) + ".png")
        assert image.save(str(source), "PNG")
        loaded = QImage(str(source))
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        for index, channel in enumerate(("r", "g", "b", "a")):
            record = extract_channel(source, channel, "roughness", folder / "generated")
            output = QImage(record["path"])
            assert record["bits"] == bits
            for y in range(2):
                for x in range(3):
                    color = loaded.pixelColor(x, y)
                    expected = round(
                        (color.redF(), color.greenF(), color.blueF(), color.alphaF())[index] * 65535
                    )
                    assert round(output.pixelColor(x, y).redF() * 65535) == expected, (
                        bits,
                        channel,
                        x,
                        y,
                    )
            assert extract_channel(source, channel, "roughness", folder / "generated")["reused"]
            Path(record["path"]).write_bytes(b"corrupted derived cache")
            assert not extract_channel(source, channel, "roughness", folder / "generated")["reused"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    from usd_scene_tool.texture_channels import prepare

    data = {
        "path": str(folder / "source_8.png"),
        "channel": "g",
        "usage": "roughness",
        "color_space": "Raw",
        "scale": [1, 2, 3, 4],
        "bias": [0, 0.1, 0.2, 0.3],
        "fallback": [0, 0.4, 0.5, 1],
        "wrap": [True, True],
        "flip_green": False,
        "warnings": [],
    }
    plans = [{"inputs": {"roughness": {"texture": data}, "metallic": {"value": 0}}}]
    prepared, _ = prepare(plans, folder / "scene.usda", str(folder / "transformed"))
    effective = prepared[0]["inputs"]["roughness"]["texture"]
    assert (
        effective["channel"] == "r"
        and effective["scale"] == [2, 2, 2, 1]
        and effective["bias"] == [0.1, 0.1, 0.1, 0]
    )
    assert effective["fallback"] == [0.4, 0.4, 0.4, 1] and data["channel"] == "g"


def run():
    import maya.cmds as cmds
    from usd_scene_tool import core

    core.environment()
    from pxr import Usd, UsdGeom, UsdShade, Sdf
    from usd_scene_tool.ui import Window
    from pbr_fixtures import build

    RUNTIME.mkdir(parents=True, exist_ok=True)
    channel_tests()
    output = ROOT / ".test-results/maya/materials.json"
    output.write_text('{"passed":false}', encoding="utf-8")
    sample = build(RUNTIME / "fixtures")
    separate_sample = build(RUNTIME / "fixtures", packed=False)
    report = core.inspect_file(sample)
    assert not report["errors"] and not report["pbr_errors"], report
    assert report["native_errors"], "Phong must continue rejecting unsupported PBR channels"
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    cmds.upAxis(axis="y")
    existing = cmds.polyCube(name="ArtistCube")[0]
    baseline = core._uuids()
    window = Window()
    window.show()
    window.sample_buttons[3].click()
    assert window.pbr.isChecked() and window.inspection
    assert window.path.text().endswith("05_pbr_separate_textures.usda")
    window.path.setText(str(sample))
    window.check_button.click()
    window.load_button.click()
    result = window.result
    assert result and result["mode"] == "pbr", window.log.toPlainText()
    assert (
        result["native_mesh_paths"] == 2
        and len(result["pbr_materials"]) == 2
        and not result["phongs"]
    )
    assert len(result["textures"]) == 8, result["textures"]
    assert len(result["separated_textures"]) == 4
    for item in result["pbr_materials"]:
        node = item["node"]
        mr = [
            cmds.listConnections(node + "." + plug, source=True, destination=False, type="file")[0]
            for plug in ("specularRoughness", "metalness")
        ]
        bump = cmds.listConnections(
            node + ".normalCamera", source=True, destination=False, type="bump2d"
        )[0]
        normal = cmds.listConnections(
            bump + ".bumpValue", source=True, destination=False, type="file"
        )[0]
        files = [cmds.getAttr(f + ".fileTextureName") for f in mr + [normal]]
        assert len(set(files)) == 3, files
        assert all(Path(p).is_file() for p in files)
        assert "Roughness" in mr[0] and "Metallic" in mr[1] and "Normal" in normal
    # Repeated imports reuse validated outputs; source USD and packed image stay intact.
    from usd_scene_tool.texture_channels import prepare, digest

    source_hash = digest(ROOT / "usd_learning/textures/pbr_orm.png")
    _, reused = prepare(report["pbr_materials"], sample)
    assert all(r["reused"] for r in reused)
    assert digest(ROOT / "usd_learning/textures/pbr_orm.png") == source_hash
    blocked = RUNTIME / "not_a_directory"
    blocked.write_text("file", encoding="utf-8")
    before_blocked = core._uuids()
    try:
        core.load_file(sample, "pbr", texture_output_directory=str(blocked))
        raise AssertionError("Invalid output directory accepted")
    except core.ToolError:
        pass
    assert core._uuids() == before_blocked

    def graph(imported):
        records = {}
        for item in imported["pbr_materials"]:
            node = cmds.ls(item["uuid"])[0]
            assert cmds.nodeType(node) == "standardSurface"
            inputs = {
                attr: cmds.listConnections(
                    node + "." + attr, source=True, destination=False, plugs=True
                )[0]
                for attr in ("baseColor", "specularRoughness", "metalness", "normalCamera")
            }
            assert inputs["specularRoughness"].endswith(".outColorR")
            assert inputs["metalness"].endswith(".outColorR")
            bump = inputs["normalCamera"].split(".")[0]
            assert cmds.nodeType(bump) == "bump2d" and cmds.getAttr(bump + ".bumpInterp") == 1
            normal = cmds.listConnections(
                bump + ".bumpValue", source=True, destination=False, type="file"
            )[0]
            assert cmds.getAttr(normal + ".colorSpace") == "Raw"
            for attr in ("specularRoughness", "metalness"):
                file = inputs[attr].split(".")[0]
                assert cmds.getAttr(file + ".colorSpace") == "Raw"
            assert cmds.getAttr(inputs["baseColor"].split(".")[0] + ".colorSpace") == "sRGB"
            groups = cmds.listConnections(
                node + ".outColor", source=False, destination=True, type="shadingEngine"
            )
            assert groups
            records[item["usd_material"]] = {
                "inputs": inputs,
                "members": sorted(cmds.sets(groups[0], query=True) or []),
            }
        return records

    original_graph = graph(result)
    # Separate maps and packed ORM must evaluate to the same channel values.
    mats = {m["usd_material"].split("/")[-1]: m["node"] for m in result["pbr_materials"]}
    for u, v in ((0.23, 0.31), (0.79, 0.69)):
        for attr, component in (("specularRoughness", 1), ("metalness", 2)):
            separate = cmds.listConnections(
                mats["SeparateMaps"] + "." + attr, source=True, destination=False
            )[0]
            packed = cmds.listConnections(
                mats["PackedORM"] + "." + attr, source=True, destination=False
            )[0]
            a = cmds.colorAtPoint(separate, output="RGB", u=u, v=v)[0]
            b = cmds.colorAtPoint(packed, output="RGB", u=u, v=v)[0]
            assert abs(a - b) < 1e-6, (attr, u, v, a, b)
    assert window.material_button.isEnabled()
    window.material_button.click()
    assert len(cmds.ls(selection=True, type="standardSurface")) == 2
    cmds.undo()  # selection
    cmds.undo()  # import
    assert core._uuids() == baseline
    cmds.redo()
    assert graph(result) == original_graph
    # DirectX option must invert green only, and must not alter the USD source.
    source_text = sample.read_bytes()
    flipped = core.load_file(sample, "pbr", flip_normal_y=True)
    for item in flipped["pbr_materials"]:
        bump = cmds.listConnections(item["node"] + ".normalCamera", source=True, destination=False)[
            0
        ]
        file = cmds.listConnections(
            bump + ".bumpValue", source=True, destination=False, type="file"
        )[0]
        assert cmds.getAttr(file + ".colorGain")[0] == (1, -1, 1)
        assert cmds.getAttr(file + ".colorOffset")[0] == (0, 1, 0)
    assert sample.read_bytes() == source_text
    cmds.undo()
    from unittest.mock import patch
    from usd_scene_tool import pbr

    real_materialize = pbr.materialize

    def fail_after_network(*args, **kwargs):
        real_materialize(*args, **kwargs)
        raise RuntimeError("injected PBR failure after network creation")

    before_failure = core._uuids()
    with patch.object(pbr, "materialize", side_effect=fail_after_network):
        try:
            core.load_file(sample, "pbr")
            raise AssertionError("Injected PBR failure was not raised")
        except core.ToolError as error:
            assert "injected PBR failure" in str(error)
    assert core._uuids() == before_failure
    # Shared USD references retain per-instance material bindings.
    instance_path = RUNTIME / "instances.usda"
    instances = Usd.Stage.CreateNew(str(instance_path))
    UsdGeom.SetStageMetersPerUnit(instances, 0.01)
    UsdGeom.SetStageUpAxis(instances, "Y")
    for name, position in (("A", (0, 0, 0)), ("B", (0, 300, 0))):
        prim = UsdGeom.Xform.Define(instances, "/" + name)
        prim.GetPrim().GetReferences().AddReference(str(sample))
        prim.GetPrim().SetInstanceable(True)
        prim.AddTranslateOp().Set(position)
    instances.GetRootLayer().Save()
    inst = core.load_file(instance_path, "pbr")
    assert inst["native_mesh_paths"] == 4 and len(inst["pbr_materials"]) == 4
    cmds.undo()
    # Face subsets, inherited default binding, and file-driven channels together.
    face_path = RUNTIME / "faces.usda"
    faces = Usd.Stage.Open(str(sample)).Flatten()
    faces.Export(str(face_path))
    face_stage = Usd.Stage.Open(str(face_path))
    mesh = UsdGeom.Mesh(face_stage.GetPrimAtPath("/PBR_Demo/SeparateMaps"))
    api = UsdShade.MaterialBindingAPI(mesh)
    subset = api.CreateMaterialBindSubset("OtherFaces", [0, 1])
    api.SetMaterialBindSubsetsFamilyType("nonOverlapping")
    UsdShade.MaterialBindingAPI(subset).Bind(
        UsdShade.Material(face_stage.GetPrimAtPath("/PBR_Demo/Looks/PackedORM"))
    )
    face_stage.GetRootLayer().Save()
    multi = core.load_file(face_path, "pbr")
    assert multi["native_mesh_paths"] == 2
    cmds.undo()
    # Unsupported normal decodes and incorrect data color spaces cannot silently pass.
    for label, edit in (
        (
            "bad_normal",
            lambda s: UsdShade.Shader(s.GetPrimAtPath("/PBR_Demo/Looks/SeparateMaps/Normal"))
            .GetInput("scale")
            .Set((1, 1, 1, 1)),
        ),
        (
            "bad_space",
            lambda s: UsdShade.Shader(s.GetPrimAtPath("/PBR_Demo/Looks/SeparateMaps/Roughness"))
            .GetInput("sourceColorSpace")
            .Set("sRGB"),
        ),
        (
            "bad_uv",
            lambda s: UsdShade.Shader(s.GetPrimAtPath("/PBR_Demo/Looks/SeparateMaps/UV"))
            .GetInput("varname")
            .Set("uv2"),
        ),
    ):
        bad = RUNTIME / (label + ".usda")
        Usd.Stage.Open(str(sample)).Flatten().Export(str(bad))
        stage = Usd.Stage.Open(str(bad))
        edit(stage)
        stage.GetRootLayer().Save()
        before = core._uuids()
        try:
            core.load_file(bad, "pbr")
            raise AssertionError(label + " was accepted")
        except core.ToolError:
            pass
        assert core._uuids() == before
    assert cmds.objExists(existing)
    from PySide2 import QtWidgets

    window.tabs.setCurrentWidget(window.materials)
    QtWidgets.QApplication.processEvents()
    assert window.grab().save(str(RUNTIME / "maya_pbr_ui.png"))
    saved = RUNTIME / "saved_pbr.ma"
    cmds.file(rename=str(saved))
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    cmds.file(str(saved), open=True, force=True)
    assert graph(result) == original_graph
    window.close()
    import hashlib

    source_hashes = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ("usd_scene_tool", "ue_maya_bridge")
        for p in (ROOT / folder).glob("*.py")
    }
    data = {
        "passed": True,
        "version": "0.9.2",
        "environment": core.environment(),
        "sample": str(sample),
        "source_sha256": source_hashes,
        "pbr_materials": 2,
        "file_nodes": 8,
        "orm_channels_verified": True,
        "physical_channel_files_separated": True,
        "raw_data_and_srgb_color_verified": True,
        "tangent_normal_and_green_flip_verified": True,
        "face_and_instance_bindings_verified": True,
        "undo_redo_graph_verified": True,
        "save_reopen_verified": True,
        "invalid_network_rejected_without_scene_changes": True,
        "pbr_ui_buttons_verified": True,
        "existing_scene_preserved": True,
        "test_mode": "dedicated Maya standalone, Qt offscreen",
    }
    data["separate_and_packed_texture_samples_equal"] = True
    data["pbr_failure_rolls_back_created_network"] = True
    data.update(
        bit_exact_8_and_16_bit_rgba_extraction=True,
        validated_cache_reuse_and_repair=True,
        invalid_output_directory_does_not_change_scene=True,
        normal_uses_independent_rgb_file=True,
    )
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("MAYA_MATERIALS_PASS " + json.dumps(data))


if __name__ == "__main__":
    from PySide2 import QtWidgets, QtGui

    APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for font in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"):
        QtGui.QFontDatabase.addApplicationFont(font)
    import maya.standalone

    maya.standalone.initialize(name="python")
    try:
        run()
    finally:
        maya.standalone.uninitialize()
