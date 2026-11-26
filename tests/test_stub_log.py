"""An SDK call the host does not implement shows in wondershot.log: host/hos_svc.c's a64_unimplemented, with no game.

The generated import stubs (gen/a64_stubs.c) call a64_unimplemented, which answers 0. The runtime's own fallback logged the
first call to stderr, which a Windows launch never shows: every nn::audio Delay call was such a stub, and the one that
answered "not removable" forever left Swamp Pipe Crawl's course clear on a grey screen with nothing in the log (issue #7).
The host's version logs the first call of each stub through hos_log, by a readable name, and still answers 0.

python -I -B tests/test_stub_log.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t x[32]; } Ctx;
static char logged[8][512];
static int lines;
static void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    if (lines < 8) vsnprintf(logged[lines++], sizeof logged[0], fmt, a);
    va_end(a);
}
#include "stub.inc"
static int failed;
static void expect(int ok, const char *what) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", what); failed = 1; }
}
static void name_is(const char *sym, const char *want) {
    char out[160];
    hos_stub_name(sym, out, sizeof out);
    if (strcmp(out, want)) { fprintf(stderr, "FAIL: name of %s: \"%s\", expected \"%s\"\n", sym, out, want); failed = 1; }
}
int main(void) {
    static const char *sym = "_ZN2nn5audio9AddReverbEPNS0_19AudioRendererConfigEPNS0_10ReverbTypeEPvmPNS0_10SubMixTypeEi";
    static int seen;
    Ctx c = {{0}};
    c.x[0] = 1234;
    c.x[30] = 0x82379a80;
    a64_unimplemented(&c, sym, &seen);
    expect(c.x[0] == 0, "a stub answers 0");
    expect(lines == 1, "the first call is logged");
    expect(lines && strstr(logged[0], "nn::audio::AddReverb") != NULL, "the log names the function readably");
    expect(lines && strstr(logged[0], "0x82379a80") != NULL, "the log has the game's caller");
    expect(lines && strstr(logged[0], sym) != NULL, "the log has the mangled symbol");
    c.x[0] = 99;
    a64_unimplemented(&c, sym, &seen);
    expect(c.x[0] == 0, "a later call still answers 0");
    expect(lines == 1, "a later call of the same stub is not logged again");
    static int other_seen;
    a64_unimplemented(&c, "_ZN2nn5audio16IsDelayRemovableEPKNS0_9DelayTypeE", &other_seen);
    expect(lines == 2 && strstr(logged[1], "nn::audio::IsDelayRemovable") != NULL, "another stub's first call is logged");
    name_is("_ZNK2nn3hid12NpadStyleSetE", "nn::hid::NpadStyleSet");
    name_is("glGetString", "glGetString");
    name_is("_ZN99tooshort", "_ZN99tooshort");
    char tiny[8];
    hos_stub_name(sym, tiny, sizeof tiny);
    expect(strlen(tiny) < sizeof tiny, "a small buffer is not overrun");
    return failed;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    source = (ROOT / 'host/hos_svc.c').read_text(encoding='utf-8')
    if 'void a64_unimplemented(Ctx *c' not in source:
        sys.exit("FAIL: host/hos_svc.c has no a64_unimplemented: the runtime's fallback logs stubs to stderr, which a Windows "
                 "launch never shows, so an unimplemented SDK call that hangs the game leaves nothing in wondershot.log")
    stub = block(source, 'void hos_stub_name(') + '\n' + block(source, 'void a64_unimplemented(Ctx *c')
    with tempfile.TemporaryDirectory(prefix='stub-log-') as tmp:
        directory = Path(tmp)
        (directory / 'stub.inc').write_text(stub, encoding='utf-8')
        test = directory / 'stub_test.c'
        test.write_text(HARNESS, encoding='utf-8')
        exe = directory / 'stub_test.exe'
        subprocess.run([args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-I' + str(directory), str(test), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
