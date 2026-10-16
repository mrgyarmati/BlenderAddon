import unittest

from tests.unit import factories  # noqa: F401  (sets sys.path)
from unreal_exporter import constants as C
from unreal_exporter.domain import naming


class SanitizeTests(unittest.TestCase):
    def test_plain_name_unchanged(self):
        result = naming.sanitize_name("SM_Crate_01")
        self.assertEqual(result.value, "SM_Crate_01")
        self.assertFalse(result.changed)
        self.assertTrue(result.valid)

    def test_spaces_dots_and_symbols_become_single_underscores(self):
        self.assertEqual(naming.sanitize_name("My Crate.001 (old)").value, "My_Crate_001_old")
        self.assertEqual(naming.sanitize_name("a--b//c").value, "a_b_c")

    def test_accents_fold_to_ascii(self):
        self.assertEqual(naming.sanitize_name("Café_Tablé").value, "Cafe_Table")

    def test_non_latin_only_name_is_invalid(self):
        result = naming.sanitize_name("日本語")
        self.assertEqual(result.value, "")
        self.assertFalse(result.valid)

    def test_mixed_unicode_keeps_ascii_part(self):
        self.assertEqual(naming.sanitize_name("Crate_箱_02").value, "Crate_02")

    def test_reserved_none_is_invalid(self):
        self.assertFalse(naming.sanitize_name("None").valid)

    def test_long_names_truncate_with_stable_hash(self):
        long_a = "Asset_" + "x" * 100 + "_A"
        long_b = "Asset_" + "x" * 100 + "_B"
        a1 = naming.sanitize_name(long_a, 32).value
        a2 = naming.sanitize_name(long_a, 32).value
        b = naming.sanitize_name(long_b, 32).value
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        self.assertLessEqual(len(a1), 32)

    def test_prefix_not_duplicated(self):
        self.assertEqual(naming.apply_prefix("Crate", "SM_"), "SM_Crate")
        self.assertEqual(naming.apply_prefix("SM_Crate", "SM_"), "SM_Crate")
        self.assertEqual(naming.apply_prefix("sm_crate", "SM_"), "sm_crate")


class HelperNamingTests(unittest.TestCase):
    def test_collision_names_round_trip(self):
        name = naming.collision_object_name(C.SHAPE_CONVEX, "SM_Crate", 3)
        self.assertEqual(name, "UCX_SM_Crate_03")
        self.assertEqual(naming.parse_collision_name(name), (C.SHAPE_CONVEX, "SM_Crate", 3))

    def test_collision_prefixes(self):
        self.assertEqual(naming.parse_collision_name("UBX_Box_00")[0], C.SHAPE_BOX)
        self.assertEqual(naming.parse_collision_name("USP_Ball")[0], C.SHAPE_SPHERE)
        self.assertEqual(naming.parse_collision_name("UCP_Pill_01")[0], C.SHAPE_CAPSULE)
        self.assertIsNone(naming.parse_collision_name("UCX_"))
        self.assertIsNone(naming.parse_collision_name("SM_Crate"))

    def test_collision_owner_matching_is_exact(self):
        self.assertTrue(naming.collision_matches_owner("UCX_SM_Crate_00", "SM_Crate"))
        self.assertTrue(naming.collision_matches_owner("UCX_SM_Crate", "SM_Crate"))
        self.assertFalse(naming.collision_matches_owner("UCX_SM_Crat_00", "SM_Crate"))
        self.assertFalse(naming.collision_matches_owner("UCX_SM_Crate2_00", "SM_Crate"))
        # Owners whose own name ends in digits.
        self.assertTrue(naming.collision_matches_owner("UCX_Rock_01_00", "Rock_01"))
        self.assertTrue(naming.collision_matches_owner("UCX_Rock_01", "Rock_01"))

    def test_socket_names_use_longest_owner(self):
        owners = ["SM_Crate", "SM_Crate_Big"]
        self.assertEqual(naming.parse_socket_name("SOCKET_SM_Crate_Big_Handle", owners), ("SM_Crate_Big", "Handle"))
        self.assertEqual(naming.parse_socket_name("SOCKET_SM_Crate_Handle", owners), ("SM_Crate", "Handle"))
        self.assertEqual(naming.parse_socket_name("SOCKET_Handle", owners), ("", "Handle"))
        self.assertIsNone(naming.parse_socket_name("Handle", owners))

    def test_lod_names(self):
        self.assertEqual(naming.lod_object_name("SM_Crate", 2), "SM_Crate_LOD2")
        self.assertEqual(naming.parse_lod_name("SM_Crate_LOD12"), ("SM_Crate", 12))
        self.assertIsNone(naming.parse_lod_name("SM_Crate_LODX"))
        self.assertEqual(naming.asset_base_name("SM_Crate_LOD0"), "SM_Crate")
        self.assertEqual(naming.asset_base_name("SM_Crate_LOD1"), "SM_Crate_LOD1")

    def test_unique_socket_name(self):
        self.assertEqual(naming.unique_socket_name({"Grip", "Grip_1"}, "Grip"), "Grip_2")


class UnrealPathTests(unittest.TestCase):
    def test_build_path(self):
        self.assertEqual(naming.build_unreal_path("/Game/Exports", "Props/Kitchen", "SM_Pot"),
                         "/Game/Exports/Props/Kitchen/SM_Pot")
        self.assertEqual(naming.build_unreal_path("/Game/Exports/", "", "SM_Pot"), "/Game/Exports/SM_Pot")
        self.assertEqual(naming.build_unreal_path("Game\\Exports", "", "SM_Pot"), "/Game/Exports/SM_Pot")

    def test_root_validation(self):
        self.assertEqual(naming.validate_unreal_root("/Game/BlenderExports"), [])
        self.assertTrue(naming.validate_unreal_root("/Engine/Stuff"))
        self.assertTrue(naming.validate_unreal_root("/Game/Bad Folder"))
        self.assertTrue(naming.validate_unreal_root(""))

    def test_folder_sanitization_drops_traversal(self):
        self.assertEqual(naming.sanitize_folder("../Props/./Kitchen Stuff/"), "Props/Kitchen_Stuff")
        self.assertEqual(naming.sanitize_folder("..\\..\\x"), "x")

    def test_file_relpath(self):
        self.assertEqual(naming.file_relpath("Props", "SM_Pot"), "Props/SM_Pot.fbx")
        self.assertEqual(naming.file_relpath("", "SM_Pot"), "SM_Pot.fbx")


class FilesystemPathTests(unittest.TestCase):
    def test_safe_join_posix(self):
        self.assertEqual(naming.safe_join("/data/export", "Props/SM_Pot.fbx"), "/data/export/Props/SM_Pot.fbx")
        for bad in ("../x.fbx", "/etc/passwd", "a/../../x", "", "a//b.fbx"):
            with self.assertRaises(naming.PathEscapeError):
                naming.safe_join("/data/export", bad)

    def test_safe_join_windows(self):
        self.assertEqual(naming.safe_join("E:\\Exports", "Props/SM_Pot.fbx"), "E:\\Exports\\Props\\SM_Pot.fbx")
        with self.assertRaises(naming.PathEscapeError):
            naming.safe_join("E:\\Exports", "C:/Windows/x.fbx")

    def test_is_within(self):
        self.assertTrue(naming.is_within("/data/export", "/data/export/a/b"))
        self.assertTrue(naming.is_within("/data/export", "/data/export"))
        self.assertFalse(naming.is_within("/data/export", "/data/exported/a"))
        self.assertTrue(naming.is_within("E:\\Exports", "e:\\exports\\Props"))
        self.assertFalse(naming.is_within("E:\\Exports", "/data/export"))

    def test_redact_path(self):
        self.assertEqual(naming.redact_path("/data/export/Props/a.fbx", "/data/export"), "Props/a.fbx")
        self.assertEqual(naming.redact_path("E:\\Exports\\Props\\a.fbx", "E:\\Exports"), "Props/a.fbx")
        self.assertEqual(naming.redact_path("/home/me/secret/a.fbx", "/data/export"), "<outside export root>/a.fbx")
        self.assertEqual(naming.redact_path("/home/me/a.fbx", "/data/export", debug=True), "/home/me/a.fbx")


if __name__ == "__main__":
    unittest.main()
