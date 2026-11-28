"""Moving a Builder/source checkout must not poison the shared online build cache."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wonder_online', Path(__file__).resolve().parents[1] / 'nx2/wonder_online.py')
online = importlib.util.module_from_spec(spec)
spec.loader.exec_module(online)


class CacheTests(unittest.TestCase):
    def test_dirty_manifest_retries_only_once(self):
        dirty = (1, online._DIRTY_MANIFEST + '100 tries, perhaps system time is not set')
        with patch.object(online, '_cmake_run', side_effect=[(0, ''), dirty, (0, ''), dirty]) as run:
            with self.assertRaisesRegex(online.OnlineBuildError, 'still dirty after 100 tries'):
                online._build_runtime(['cmake', '-S', 'source'], ['cmake', '--build', 'online'], [], {})
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['cmake', '-S', 'source'], ['cmake', '--build', 'online'],
            ['cmake', '--fresh', '-DCMAKE_SUPPRESS_REGENERATION=ON', '-S', 'source'],
            ['cmake', '--build', 'online'],
        ])

    def test_other_build_errors_are_preserved_without_retry(self):
        with patch.object(online, '_cmake_run', side_effect=[(0, ''), (1, 'error: compiler failed')]) as run:
            with self.assertRaisesRegex(online.OnlineBuildError, 'error: compiler failed'):
                online._build_runtime(['cmake', '-S', 'source'], ['cmake', '--build', 'online'], [], {})
        self.assertEqual(run.call_count, 2)

    @unittest.skipUnless(os.environ.get('WONDER_TEST_CMAKE'), 'set WONDER_TEST_CMAKE for CMake literal test')
    def test_cmake_literal_preserves_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            script, output = base / 'check.cmake', base / 'result.txt'
            paths = ['C:/Games/Wonder – édition/clang.exe', 'C:/a ]=] ]] ${NAME};/clang.exe']
            script.write_text(''.join('file(APPEND ' + online.cmake_literal(output.as_posix()) + ' ' +
                                      online.cmake_literal(path + "\n") + ')\n' for path in paths), encoding='utf-8')
            result = subprocess.run([os.environ['WONDER_TEST_CMAKE'], '-P', str(script)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(output.read_text(encoding='utf-8').splitlines(), paths)

    def test_source_location(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            source = build / 'Builder tools' / 'host'
            self.assertEqual(online.cmake_source_args(build, source), [])
            cache = build / 'CMakeCache.txt'
            cache.write_text('CMAKE_HOME_DIRECTORY:INTERNAL=' + str(source) + '\n', encoding='utf-8')
            self.assertEqual(online.cmake_source_args(build, source), [])
            self.assertEqual(online.cmake_source_args(build, build / 'moved source'), ['--fresh'])
            cache.write_text('# interrupted cache\n', encoding='utf-8')
            self.assertEqual(online.cmake_source_args(build, source), ['--fresh'])

    @unittest.skipUnless(os.environ.get('WONDER_TEST_CMAKE'), 'set WONDER_TEST_CMAKE for the real configure test')
    def test_real_source_move(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second, build = base/'old checkout', base/'new Builder', base/'build'
            cmake = os.environ['WONDER_TEST_CMAKE']
            project = 'cmake_minimum_required(VERSION 3.24)\nproject(CacheMove NONE)\nfile(WRITE "${CMAKE_BINARY_DIR}/configured.txt" "${CMAKE_CURRENT_SOURCE_DIR}")\n'
            for source in (first, second):
                source.mkdir()
                (source/'CMakeLists.txt').write_text(project, encoding='utf-8')
            def configure(source, extra=()):
                return subprocess.run([cmake, *extra, '-S', str(source), '-B', str(build)], capture_output=True)
            self.assertEqual(configure(first).returncode, 0)
            self.assertNotEqual(configure(second).returncode, 0)  # reproduces the reported update failure
            result = configure(second, online.cmake_source_args(build, second))
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual((build/'configured.txt').read_text(), second.as_posix())
            self.assertEqual(online.cmake_source_args(build, second), [])


if __name__ == '__main__':
    unittest.main()
