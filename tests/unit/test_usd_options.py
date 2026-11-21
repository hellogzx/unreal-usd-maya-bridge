"""Quality-policy boundary tests without a host application."""

import unittest
from ue_maya_bridge.usd_options import normalize_options, choose_geometry


class OptionsTests(unittest.TestCase):
    def test_default_conservative_nanite_and_binary(self):
        self.assertEqual(normalize_options()["asset_format"], "usdc")
        with self.assertRaises(ValueError):
            choose_geometry(1, True)

    def test_nanite_is_always_marked_approximate(self):
        result = choose_geometry(1, True, {"nanite_mode": "proxy"})
        self.assertTrue(result["approximate"])
        self.assertEqual(result["geometry_source"], "nanite_render_proxy")

    def test_exact_lod_and_explicit_fallback(self):
        self.assertEqual(choose_geometry(3, False, {"lod_index": 2})["effective_lod"], 2)
        with self.assertRaises(ValueError):
            choose_geometry(1, False, {"lod_index": 2})
        result = choose_geometry(1, False, {"lod_index": 2, "missing_lod": "lod0"})
        self.assertEqual(result["effective_lod"], 0)
        self.assertTrue(result["lod_fallback"])

    def test_invalid_source_mode_and_lod_types(self):
        for options in (
            {"nanite_mode": "source"},
            {"lod_index": True},
            {"lod_index": -1},
            {"lod_index": 8},
            {"lod_index": 1.5},
            {"asset_format": "fbx"},
            {"bake_materials": True},
        ):
            with self.assertRaises(ValueError):
                normalize_options(options)


if __name__ == "__main__":
    unittest.main()
