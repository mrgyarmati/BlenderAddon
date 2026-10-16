import math
import os
import shutil
import tempfile
import unittest

from tests.unit import factories  # noqa: F401
from unreal_exporter.domain import unreal_math as U
from unreal_exporter.services.logging import ExportLog


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


class UnrealMathTests(unittest.TestCase):
    """Expected values come from UE 5.6.1 / 5.8.3 imports of probe FBX files."""

    def test_location_mirrors_y_and_scales(self):
        self.assertEqual(U.location_to_unreal((2.0, 3.0, 4.0), 100.0), (200.0, -300.0, 400.0))
        self.assertEqual(U.location_to_unreal((0.25, 0.5, 1.0), 100.0), (25.0, -50.0, 100.0))

    def test_identity(self):
        self.assertEqual(U.rotation_to_unreal_rotator(rot_z(0)), (0.0, 0.0, 0.0))

    def test_yaw_sign_is_mirrored(self):
        self.assertEqual(U.rotation_to_unreal_rotator(rot_z(90)), (0.0, 0.0, -90.0))

    def test_pitch_and_roll(self):
        roll, pitch, yaw = U.rotation_to_unreal_rotator(rot_x(90))
        self.assertAlmostEqual(roll, 90.0, places=4)
        roll, pitch, yaw = U.rotation_to_unreal_rotator(rot_y(90))
        self.assertAlmostEqual(pitch, -90.0, places=4)

    def test_probe_socket_quirk_matches_ue(self):
        """UE showed an empty with Blender rotation R as convert(R @ RotX(-90))."""
        observed = {  # Blender rotation -> UE (roll, pitch, yaw) printed by UE
            "identity": (rot_z(0), (-90.0, 0.0, 0.0)),
            "z90": (rot_z(90), (-90.0, 0.0, -90.0)),
            "x90": (rot_x(90), (0.0, 0.0, 0.0)),
            "y90": (rot_y(90), (0.0, -90.0, -90.0)),
        }
        for label, (blender_rot, ue_rotator) in observed.items():
            predicted = U.rotation_to_unreal_matrix(matmul(blender_rot, rot_x(-90)))
            self.assertTrue(U.matrices_close(predicted, U.rotator_to_matrix(*ue_rotator)), label)

    def test_rotator_matrix_round_trip(self):
        for rotator in ((10.0, 20.0, 30.0), (-45.0, 5.0, 170.0), (0.0, 89.0, 0.0)):
            m = U.rotator_to_matrix(*rotator)
            back = U.quaternion_to_rotator(U.matrix_to_quaternion(m))
            self.assertTrue(U.matrices_close(m, U.rotator_to_matrix(*back)), rotator)

    def test_decompose(self):
        m4 = ((0.0, -2.0, 0.0, 1.0), (2.0, 0.0, 0.0, 2.0), (0.0, 0.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0))
        loc, rot, scale = U.decompose(m4)
        self.assertEqual(loc, (1.0, 2.0, 3.0))
        self.assertEqual(scale, (2.0, 2.0, 2.0))
        self.assertTrue(U.matrices_close(rot, rot_z(90)))


class ExportLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uex_log_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_paths_are_redacted(self):
        log = ExportLog("E:\\Exports", clock=iter(range(100)).__next__)
        log.info("write", "wrote E:\\Exports\\Props\\SM_A.fbx from C:\\Users\\me\\secret.blend", path="E:\\Exports\\x.fbx")
        rec = log.records[0]
        self.assertIn("Props/SM_A.fbx", rec["message"])
        self.assertNotIn("C:\\Users", rec["message"])
        self.assertIn("<outside export root>/secret.blend", rec["message"])
        self.assertEqual(rec["path"], "x.fbx")

    def test_debug_keeps_paths(self):
        log = ExportLog("/data/out", debug=True)
        log.info("write", "wrote /home/me/x.fbx")
        self.assertIn("/home/me/x.fbx", log.records[0]["message"])

    def test_write_files(self):
        log = ExportLog("/data/out")
        log.warning("w", "careful", asset="SM_A")
        text_path = os.path.join(self.tmp, "log.txt")
        json_path = os.path.join(self.tmp, "log.jsonl")
        log.write(text_path, json_path)
        with open(json_path, encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().strip().splitlines()), 1)
        with open(text_path, encoding="utf-8") as handle:
            self.assertIn("WARNING", handle.read())


if __name__ == "__main__":
    unittest.main()
