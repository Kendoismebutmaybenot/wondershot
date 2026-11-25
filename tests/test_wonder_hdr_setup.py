"""Exercise the optional Wondershot HDR build on Windows-style install paths."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location("make_wonder", Path(__file__).resolve().parents[1] / "nx2" / "make_wonder.py")
wonder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wonder)


class HdrSetupTests(unittest.TestCase):
    def test_spirv_cross_stages_only_the_files_needed_for_the_cli(self):
        tools = Path(self.enterContext(tempfile.TemporaryDirectory())) / "tools"
        cache = tools / "shader-tools"
        cache.mkdir(parents=True)
        (cache / "glslang.exe").touch()
        sources = {name + ".cpp" for name in wonder.SPIRV_CROSS_SOURCES}
        required = sources | {"spirv_cross.hpp", "LICENSE"}

        def download(urls, checksum, size, target, progress):
            with zipfile.ZipFile(target, "w") as archive:
                for name in required:
                    archive.writestr("SPIRV-Cross-vulkan-sdk-tag/" + name, name)
                archive.writestr("SPIRV-Cross-vulkan-sdk-tag/reference/opt/shaders-msl/" + "x" * 170 + ".comp", "fixture")

        def compile_cli(args, *, cwd, **kwargs):
            staging = Path(cwd)
            self.assertTrue(staging.name.startswith("sc-"))
            self.assertEqual({p.name for p in staging.iterdir()}, required)
            self.assertEqual(set(args[6:]), sources)
            (staging / "spirv-cross.exe").write_bytes(b"compiled CLI")
            return subprocess.CompletedProcess(args, 0)

        with (patch.object(wonder, "download", side_effect=download),
              patch.object(wonder.subprocess, "run", side_effect=compile_cli),
              contextlib.redirect_stdout(io.StringIO())):
            wonder.ensure_shader_tools(str(tools))

        self.assertEqual((cache / "spirv-cross.exe").read_bytes(), b"compiled CLI")
        self.assertEqual((cache / "SPIRV-Cross-LICENSE.txt").read_text(), "LICENSE")
        self.assertFalse(list(cache.glob("sc-*")))

    def test_hdr_tool_setup_failure_is_a_warning(self):
        for error in (FileNotFoundError("path too long"), zipfile.BadZipFile("unreadable archive")):
            with (self.subTest(error=error),
                  patch.object(wonder, "ensure_shader_tools", side_effect=error),
                  patch.object(wonder, "dump_hdr_programs") as dump,
                  contextlib.redirect_stdout(io.StringIO()) as output):
                wonder.make_hdr("installed-game", "tools")
                dump.assert_not_called()
                self.assertIn("@@warn The game build is complete.", output.getvalue())
                self.assertNotIn("@@error", output.getvalue())


if __name__ == "__main__":
    unittest.main()
