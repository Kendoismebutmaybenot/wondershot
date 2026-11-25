"""Exercise the packaged Wondershot Builder update without GitHub or game files."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location("make_wonder", Path(__file__).resolve().parents[1] / "nx2" / "make_wonder.py")
wonder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wonder)
OLD, NEW = "v0.1.1-alpha.14", "v0.1.1-alpha.15"


def package():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in ("WondershotBuilder.exe", "WondershotBuilder.dll", "WondershotBuilder.runtimeconfig.json",
                     "tools/python/python.exe", "tools/nx2/make_wonder.py"):
            archive.writestr("Builder/" + name, "fixture")
        for stamp in ("builder_version.txt", "tools/version.txt"):
            archive.writestr("Builder/" + stamp, NEW + "\n")
    return output.getvalue()


def release(payload):
    name = "WondershotBuilder-%s.zip" % NEW
    return {"tag_name": NEW, "zipball_url": "https://api.github.com/repos/%s/zipball/%s" % (wonder.REPO, NEW),
            "assets": [{"name": name, "state": "uploaded", "size": len(payload),
                        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                        "browser_download_url": "https://github.com/%s/releases/download/%s/%s" % (wonder.REPO, NEW, name)}]}


class Download(io.BytesIO):
    def geturl(self):
        return "https://release-assets.githubusercontent.com/fixture"


class BuilderUpdateTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.app = self.base / "Current Builder"
        self.tools = self.app / "tools"
        self.tools.mkdir(parents=True)
        (self.app / "WondershotBuilder.exe").write_bytes(b"old Builder")
        (self.app / "builder_version.txt").write_text(OLD, encoding="utf-8")
        (self.tools / "version.txt").write_text(NEW, encoding="utf-8")

    def test_update_is_available_when_only_game_sources_are_current(self):
        with patch.object(wonder, "github_json", return_value=[release(package())]), contextlib.redirect_stdout(io.StringIO()) as out:
            wonder.check_update(str(self.tools))
        self.assertEqual(out.getvalue().splitlines(), ["@@builder-update " + NEW, "@@update current " + NEW])

    def test_verified_package_is_installed_alongside_previous_builder(self):
        payload = package()
        with (patch.object(wonder, "github_json", return_value=release(payload)),
              patch.object(wonder.urllib.request, "urlopen", return_value=Download(payload)),
              contextlib.redirect_stdout(io.StringIO()) as out):
            wonder.install_builder(str(self.tools), NEW)
        prefix = "@@builder-ready "
        self.assertTrue(out.getvalue().startswith(prefix))
        installed = Path(out.getvalue()[len(prefix):].strip())
        self.assertEqual(installed.read_bytes(), b"fixture")
        self.assertEqual(installed.parent.parent, self.base / "WondershotBuilder-updates")
        self.assertEqual(wonder.builder_release(installed.parent), NEW)
        self.assertEqual((self.app / "WondershotBuilder.exe").read_bytes(), b"old Builder")
        self.assertEqual(list(installed.parent.parent.iterdir()), [installed.parent])

    def test_checksum_failure_keeps_previous_builder(self):
        payload = package()
        damaged = bytes([payload[0] ^ 1]) + payload[1:]
        with (patch.object(wonder, "github_json", return_value=release(payload)),
              patch.object(wonder.urllib.request, "urlopen", return_value=Download(damaged)),
              self.assertRaisesRegex(ValueError, "SHA-256")):
            wonder.install_builder(str(self.tools), NEW)
        self.assertEqual((self.app / "WondershotBuilder.exe").read_bytes(), b"old Builder")
        self.assertEqual(list((self.base / "WondershotBuilder-updates").iterdir()), [])

    def test_archive_rejects_a_path_outside_staging(self):
        zip_path = self.base / "malformed.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("Builder/../outside", b"fixture")
        with self.assertRaisesRegex(ValueError, "invalid file path"):
            wonder.extract_builder(zip_path, self.base / "staging")
        self.assertFalse((self.base / "outside").exists())


if __name__ == "__main__":
    unittest.main()
