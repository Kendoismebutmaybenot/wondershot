"""A dump unpacked title by title: the Switch 2 Edition's files are in the add-on, and the build puts them over the romfs."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("make_wonder", Path(__file__).resolve().parents[1] / "nx2" / "make_wonder.py")
wonder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wonder)

HEAP = "System/HeapSize/Product.Nin_Ounce_NVN2.HeapDef.byml.zs"


def write(root, rel, data):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


class RomfsLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.base, self.addon, self.dst = self.tmp / "romfs", self.tmp / "dlc" / "romfs", self.tmp / "game" / "romfs"
        write(self.base, "Pack/Shared.pack.zs", b"switch 1")
        write(self.base, "Stage/Only1.byml.zs", b"base only")
        write(self.addon, HEAP, b"heap")
        write(self.addon, "System/AocUpgradeVersion.txt", b"3")
        write(self.addon, "Pack/Shared.pack.zs", b"switch 2 copy")
        self.quiet = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_layout_is_recognised_and_not_an_error(self):
        self.assertTrue(wonder.needs_layering(str(self.base), str(self.addon)))
        self.assertIsNone(wonder.romfs_boot_error(str(self.base), str(self.addon)))
        self.assertIsNotNone(wonder.romfs_boot_error(str(self.base)))

    def test_no_layering_without_the_upgrade_marker_or_with_a_complete_romfs(self):
        (self.addon / "System" / "AocUpgradeVersion.txt").unlink()
        self.assertFalse(wonder.needs_layering(str(self.base), str(self.addon)))
        self.assertIsNotNone(wonder.romfs_boot_error(str(self.base), str(self.addon)))
        write(self.addon, "System/AocUpgradeVersion.txt", b"3")
        write(self.base, HEAP, b"heap")
        self.assertFalse(wonder.needs_layering(str(self.base), str(self.addon)))

    def test_addon_wins_and_the_dump_is_untouched(self):
        for link in (True, False):
            with self.subTest(link=link):
                wonder.layer_romfs(str(self.dst), str(self.base), str(self.addon), link=link)
                self.assertEqual((self.dst / "Pack/Shared.pack.zs").read_bytes(), b"switch 2 copy")
                self.assertEqual((self.dst / "Stage/Only1.byml.zs").read_bytes(), b"base only")
                self.assertTrue((self.dst / HEAP).is_file())
                self.assertEqual((self.base / "Pack/Shared.pack.zs").read_bytes(), b"switch 1")
                self.assertEqual(os.path.samefile(self.dst / HEAP, self.addon / HEAP), link)
                if link:
                    import shutil
                    shutil.rmtree(self.dst)

    def test_again_keeps_files_and_drops_leftovers(self):
        wonder.layer_romfs(str(self.dst), str(self.base), str(self.addon), link=False)
        write(self.dst, "Old/Leftover.bin", b"x")
        before = (self.dst / "Stage/Only1.byml.zs").stat().st_mtime_ns
        wonder.layer_romfs(str(self.dst), str(self.base), str(self.addon), link=False)
        self.assertFalse((self.dst / "Old/Leftover.bin").exists())
        self.assertEqual((self.dst / "Stage/Only1.byml.zs").stat().st_mtime_ns, before)

    def test_space_is_zero_when_hard_linking_on_one_drive(self):
        self.assertEqual(wonder.layer_space(str(self.dst), str(self.base), str(self.addon), "link"), 0)
        self.assertEqual(wonder.layer_space(str(self.dst), str(self.base), str(self.addon), "copy"),
                         len(b"switch 2 copy") + len(b"base only") + len(b"heap") + len(b"3"))


if __name__ == "__main__":
    unittest.main()
