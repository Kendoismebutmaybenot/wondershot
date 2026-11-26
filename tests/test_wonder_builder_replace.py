"""In-place Builder updates preserve the launch path and recover from copy failures."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('builder_update', Path(__file__).resolve().parents[1] / 'nx2/builder_update.py')
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)

OLD, NEW = 'v0.1.1-alpha.33', 'v0.1.1-alpha.34'


class BuilderReplaceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.base / 'WondershotBuilder-updates' / 'download'
        self.target = self.base / 'My Builder'
        for app, tag in ((self.source, NEW), (self.target, OLD)):
            for name in ('WondershotBuilder.exe', 'WondershotBuilder.dll', 'WondershotBuilder.runtimeconfig.json',
                         'tools/python/python.exe', 'tools/nx2/make_wonder.py', 'tools/nx2/builder_update.py'):
                file = app / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(tag + ':' + name, encoding='utf-8')
            (app / 'builder_version.txt').write_text(tag, encoding='utf-8')
            (app / 'tools/version.txt').write_text(tag, encoding='utf-8')
        for name in ('logs/build.log', 'tools/llvm-mingw/cache', 'build-workspace/dump/keep', 'settings.json'):
            file = self.target / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('keep me', encoding='utf-8')

    def contents(self):
        return {file.relative_to(self.target).as_posix(): file.read_bytes()
                for file in self.target.rglob('*') if file.is_file()}

    def test_update_replaces_original_and_preserves_user_files(self):
        before = self.contents()
        exe = updater.replace_files(self.source, self.target)
        self.assertEqual(exe, self.target / 'WondershotBuilder.exe')
        self.assertEqual(updater.wonder.builder_release(str(self.target)), NEW)
        for file in self.source.rglob('*'):
            if file.is_file():
                self.assertEqual((self.target / file.relative_to(self.source)).read_bytes(), file.read_bytes())
        for name, data in before.items():
            if not (self.source / name).exists():
                self.assertEqual((self.target / name).read_bytes(), data)
        self.assertEqual(list(self.target.glob('.builder-update-*')), [])

    def test_mid_update_failure_restores_original_files_and_version(self):
        before = self.contents()
        replace = os.replace
        count = 0

        def fail_once(source, dest):
            nonlocal count
            count += 1
            if count == 4:
                raise PermissionError('fixture: locked destination')
            return replace(source, dest)

        with patch.object(updater.os, 'replace', side_effect=fail_once), self.assertRaises(PermissionError):
            updater.replace_files(self.source, self.target)
        self.assertEqual(self.contents(), before)
        self.assertEqual(list(self.target.glob('.builder-update-*')), [])

    def test_incomplete_download_does_not_change_install(self):
        before = self.contents()
        (self.source / 'WondershotBuilder.dll').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            updater.replace_files(self.source, self.target)
        self.assertEqual(self.contents(), before)

    def test_downgrade_and_overlapping_folders_are_rejected(self):
        before = self.contents()
        (self.target / 'builder_version.txt').write_text('v0.1.1-alpha.35', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'newer'):
            updater.replace_files(self.source, self.target)
        for target in (self.source, self.source / 'nested'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'separate'):
                updater.replace_files(self.source, target)
        self.assertEqual((self.target / 'WondershotBuilder.exe').read_bytes(), before['WondershotBuilder.exe'])

    @unittest.skipUnless(os.name == 'nt', 'Windows process handles')
    def test_waits_for_specific_process_to_exit(self):
        with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.2)']) as child:
            updater.wait_for_exit(child.pid)
            self.assertIsNotNone(child.poll())
        with self.assertRaises(ValueError):
            updater.wait_for_exit(os.getpid())


if __name__ == '__main__':
    unittest.main(verbosity=2)
