"""HDR keeps its startup rendering mode while the saved menu choice awaits a restart."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
menu = (root / 'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
main = (root / 'gpu/vk/vk_main.cpp').read_text(encoding='utf-8')
replay = (root / 'gpu/vk/vk_replay.cpp').read_text(encoding='utf-8')
assert 'hdr_at_start = opts.hdr;' in menu
assert menu.index('hdr_at_start = opts.hdr;') < menu.index('restart_init();', menu.index('hdr_at_start = opts.hdr;'))
assert not re.search(r'opts\.hdr\b', main + replay), 'A renderer path still uses the pending menu choice'
functions = '\n'.join(re.search(r'^' + re.escape(prefix) + r'.*$', menu, re.M).group(0) for prefix in
                      ('int menu_hdr_running()', 'bool scene_tonemap_on()', 'bool wonder_hdr_on()', 'bool menu_hdr_on()'))
program = r"""
#include <cassert>
struct { int hdr, hdr_tonemap; } opts;
struct { bool hdr; } dev;
static int hdr_at_start;
FUNCTIONS
int main() {
  for (int start : {0, 2}) {
    opts.hdr = start; hdr_at_start = opts.hdr; dev.hdr = true; opts.hdr_tonemap = 1;
    int changed = start ? 0 : 2;
    opts.hdr = changed;
    assert(menu_hdr_running() == start && menu_hdr_on() == (changed != 0));
    assert(wonder_hdr_on() == (start == 2));
    assert(scene_tonemap_on() == (start == 2));
    opts.hdr = start;
    assert(menu_hdr_running() == start && menu_hdr_on() == (start != 0));
    opts.hdr = changed; hdr_at_start = opts.hdr; // next launch
    assert(menu_hdr_running() == changed && wonder_hdr_on() == (changed == 2));
  }
}
""".replace('#include <cassert>', '#include <cassert>\n#include <initializer_list>').replace('FUNCTIONS', functions)
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp)/'test.cpp'; exe = Path(tmp)/'test.exe'
    source.write_text(program, encoding='utf-8')
    subprocess.run([os.environ.get('CXX', 'clang++'), '-std=c++20', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: HDR remains in its startup mode until restart, in both directions')
