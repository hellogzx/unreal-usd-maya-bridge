"""Validate malformed, relocated and edited delivery packages without a DCC."""

import json
import tempfile
import unittest
from pathlib import Path

from ue_maya_bridge.package import sha256_file
from ue_maya_bridge.usd_package import inspect_package


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = self.root / "scene.usda"
        self.scene.write_text("#usda 1.0\n", encoding="utf-8")
        self.data = {
            "format": "ue-maya-usd-previs",
            "version": 1,
            "root_layer": "scene.usda",
            "actors": [{"actor": "A", "label": "A", "mesh": "M", "prim": "/A"}],
            "assets": {"M": {"file": "scene.usda"}},
            "skipped": [],
            "files": {"scene.usda": sha256_file(self.scene)},
        }
        self.write()

    def write(self):
        (self.root / "usd_manifest.json").write_text(json.dumps(self.data), encoding="utf-8")

    def test_legacy_and_ordinary_files(self):
        self.assertEqual(inspect_package(self.scene)["status"], "verified")
        self.assertEqual(inspect_package(self.root / "another.usda")["status"], "missing")
        (self.root / "usd_manifest.json").unlink()
        self.assertEqual(inspect_package(self.scene)["status"], "missing")

    def test_edited_content_and_failure_marker(self):
        self.scene.write_text("#usda 1.0\n# changed", encoding="utf-8")
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        self.data["files"]["scene.usda"] = sha256_file(self.scene)
        self.write()
        (self.root / "EXPORT_FAILED.txt").write_text("failure")
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")

    def test_path_escape_and_unlisted_dependency(self):
        self.data["files"]["../outside.usda"] = "0" * 64
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        del self.data["files"]["../outside.usda"]
        self.write()
        self.assertEqual(
            inspect_package(self.scene, [str(self.root / "unlisted.usda")])["status"], "invalid"
        )

    def test_bad_json_schema_and_version(self):
        (self.root / "usd_manifest.json").write_text("{")
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        for bad in (
            [],
            {"version": 99},
            dict(self.data, version=True),
            dict(self.data, actors=[None]),
            dict(self.data, files=[]),
        ):
            self.data = bad
            self.write()
            self.assertEqual(inspect_package(self.scene)["status"], "invalid")

    def test_v2_multiple_placements_and_statistics(self):
        self.data.update(
            version=2,
            actors=[{"actor": "A", "label": "A"}],
            placements=[
                {
                    "id": "C#0",
                    "actor": "A",
                    "label": "A",
                    "component": "C",
                    "instance_index": 0,
                    "mesh": "M",
                    "prim": "/A/Instance0",
                    "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                }
            ],
            statistics={
                "unique_triangles": 12,
                "placed_triangles": 12,
                "unique_vertices": 24,
                "assets": {
                    "M": {
                        "triangles": 12,
                        "vertices": 24,
                        "lod_count": 1,
                        "lod_index": 0,
                        "placements": 1,
                    }
                },
            },
        )
        self.write()
        result = inspect_package(self.scene)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["instance_count"], 1)
        self.data["placements"].append(dict(self.data["placements"][0]))
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        self.data["placements"].pop()
        self.data["statistics"]["placed_triangles"] = 13
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")

    def test_v4_camera_only_and_invalid_ownership(self):
        from ue_maya_bridge.camera_math import frame_hint

        camera = {
            "id": "C",
            "actor": "A",
            "component": "C",
            "label": "Camera",
            "camera_type": "CameraComponent",
            "prim": "/Cameras/C",
            "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "focal_length_mm": 35,
            "aperture_width_mm": 36,
            "aperture_height_mm": 20.25,
            "horizontal_offset_mm": 0,
            "vertical_offset_mm": 0,
            "aspect_ratio": 16 / 9,
            "near_clip_cm": 10,
            "far_clip_cm": 100000,
            "frame_hint": frame_hint(16 / 9),
        }
        self.data.update(
            version=4,
            actors=[{"actor": "A", "label": "A"}],
            assets={},
            placements=[],
            cameras=[camera],
            options={"include_cameras": True},
            statistics={
                "unique_triangles": 0,
                "placed_triangles": 0,
                "unique_vertices": 0,
                "assets": {},
            },
            metrics={
                "usd_bytes": self.scene.stat().st_size,
                "geometry_bytes": 0,
                "usd_export_seconds": 0.1,
            },
        )
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "verified")
        camera["actor"] = "Missing"
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        camera["actor"] = "A"
        self.data["options"]["include_cameras"] = False
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        self.data["cameras"] = []
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")

    def test_v3_proxy_lod_provenance_and_invalid_metadata(self):
        from ue_maya_bridge.usd_options import choose_geometry

        options = {
            "nanite_mode": "proxy",
            "lod_index": 1,
            "missing_lod": "lod0",
            "asset_format": "usda",
        }
        choice = choose_geometry(1, True, options)
        placement = {
            "id": "C#0",
            "actor": "A",
            "label": "A",
            "component": "C",
            "instance_index": 0,
            "mesh": "M",
            "prim": "/A/P",
            "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "geometry_choice": dict(choice),
        }
        self.data.update(
            version=3,
            options=options,
            actors=[{"actor": "A", "label": "A"}],
            placements=[placement],
            assets={"M": {"file": "scene.usda", "geometry_choice": dict(choice)}},
            statistics={
                "unique_triangles": 12,
                "placed_triangles": 12,
                "unique_vertices": 24,
                "assets": {
                    "M": {
                        "triangles": 12,
                        "vertices": 24,
                        "lod_count": 1,
                        "lod_index": 0,
                        "placements": 1,
                        "geometry_choice": dict(choice),
                    }
                },
            },
            metrics={
                "usd_bytes": self.scene.stat().st_size,
                "geometry_bytes": self.scene.stat().st_size,
                "usd_export_seconds": 0.1,
            },
        )
        self.write()
        result = inspect_package(self.scene)
        self.assertEqual(result["status"], "verified", result)
        self.assertTrue(any("Nanite" in warning for warning in result["warnings"]))
        self.data["placements"][0]["geometry_choice"]["approximate"] = False
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")
        self.data["placements"][0]["geometry_choice"] = dict(choice)
        self.data["options"]["nanite_mode"] = "source"
        self.write()
        self.assertEqual(inspect_package(self.scene)["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
