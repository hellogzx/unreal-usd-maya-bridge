"""Static camera boundary tests, independent of either application's SDK."""

import copy
import unittest
from ue_maya_bridge.camera_math import frame_hint, validate_camera


class CameraMathTests(unittest.TestCase):
    def camera(self):
        return {
            "prim": "/C",
            "label": "C",
            "focal_length_mm": 35.0,
            "aperture_width_mm": 36.0,
            "aperture_height_mm": 20.25,
            "horizontal_offset_mm": 0.0,
            "vertical_offset_mm": 0.0,
            "aspect_ratio": 16 / 9,
            "near_clip_cm": 10.0,
            "far_clip_cm": 1e9,
            "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "frame_hint": frame_hint(16 / 9),
        }

    def test_common_frames(self):
        self.assertEqual(frame_hint(16 / 9)["width"], 1920)
        self.assertEqual(frame_hint(2.39)["height"], 1000)
        self.assertEqual(frame_hint(9 / 16)["width"], 1080)
        validate_camera(self.camera())

    def test_invalid_lens_and_clipping(self):
        for key, value in (
            ("focal_length_mm", 0),
            ("aperture_height_mm", float("nan")),
            ("far_clip_cm", 1),
        ):
            data = self.camera()
            data[key] = value
            with self.assertRaises(ValueError):
                validate_camera(data)

    def test_scaled_and_mirrored_camera_rejected(self):
        for value in (-1, 2):
            data = self.camera()
            data["matrix"][0][0] = value
            with self.assertRaises(ValueError):
                validate_camera(data)

    def test_frame_mismatch_and_missing_source(self):
        data = self.camera()
        data["frame_hint"]["height"] = 1000
        with self.assertRaises(ValueError):
            validate_camera(data)
        with self.assertRaises(ValueError):
            validate_camera(self.camera(), require_source=True)


if __name__ == "__main__":
    unittest.main()
