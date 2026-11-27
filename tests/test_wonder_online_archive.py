"""The online source/tool extractor must not write outside its build directory."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('wonder_online', Path(__file__).resolve().parents[1] / 'nx2/wonder_online.py')
online = importlib.util.module_from_spec(spec)
spec.loader.exec_module(online)


class ArchiveTests(unittest.TestCase):
    def test_parent_path_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../outside.txt', 'bad')
            with self.assertRaises(ValueError):
                online.unpack(archive, root / 'output')
            self.assertFalse((root / 'outside.txt').exists())

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                info = zipfile.ZipInfo('link')
                info.external_attr = 0o120777 << 16
                output.writestr(info, '../outside')
            with self.assertRaises(ValueError):
                online.unpack(archive, root / 'output')


if __name__ == '__main__':
    unittest.main()
