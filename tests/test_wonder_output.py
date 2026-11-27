"""Exercise Wonder's real host framebuffer setup without game data or a GPU."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    host = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    setup = host[host.index("static void wonder_wide_init("):host.index("int hos_camera_trace_enabled(")]
    fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "host/hos_wide_size.h"
#define IMAGE_BASE 0
#define SM_CXSCREEN 0
#define SM_CYSCREEN 1
static uint8_t memory[0x2c71b14 + 4];
static uint8_t *A64_MEM = memory;
static uint64_t hos_wonder_wide_size, hos_wide_out;
static float hos_wide_ratio, hos_aspect_ratio;
static int handheld, follow, sw, sh;
int hos_output_handheld(void) { return handheld; }
int hos_ini_option(const char *key, int fallback) { (void)key; (void)fallback; return follow; }
void hos_monitor_prepare(void) {}
int hos_monitor_screen_size(int *w, int *h) { *w = sw; *h = sh; return sw && sh; }
int GetSystemMetrics(int which) { return which ? sh : sw; }
#define hos_log(...) ((void)0)
''' + setup + r'''
static void check(unsigned w, unsigned h, int monitor, unsigned mw, unsigned mh, unsigned ew, unsigned eh) {
    uint32_t original = 0x3fe38e3b;
    memcpy(memory + 0x2c71b14, &original, 4);
    hos_wonder_wide_size = hos_wide_out = 0;
    follow = monitor; sw = (int)mw; sh = (int)mh;
    wonder_wide_init(sizeof memory, w, h);
    assert((uint32_t)hos_wonder_wide_size == ew);
    assert((hos_wonder_wide_size >> 32) == eh);
    assert(hos_wide_out == hos_wonder_wide_size);
    assert(!hos_wonder_wide_size || (hos_aspect_ratio == hos_wide_ratio && fabs(hos_wide_ratio - (double)ew / eh) < 0.00001));
    assert(hos_wonder_wide_size == 0 || (uint64_t)ew * eh <= 3840ULL * 2160);
}
int main(void) {
    check(1920, 1080, 0, 5120, 2160, 1920, 1080);
    check(2560, 1440, 0, 5120, 2160, 2560, 1440);
    check(3840, 2160, 0, 5120, 2160, 3840, 2160);
    check(2560, 1440, 1, 3440, 1440, 3440, 1440);
    check(1920, 1080, 1, 5120, 2160, 2560, 1080);
    check(3440, 1440, 0, 1920, 1080, 3440, 1440);
    check(5120, 2160, 0, 5120, 2160, 4416, 1864);
    check(5120, 2880, 0, 5120, 2880, 3840, 2160);
    check(2560, 1440, 1, 0, 0, 2560, 1440);
    check(0, 0, 1, 3440, 1440, 0, 0);
    handheld = 1;
    check(2560, 1440, 1, 3440, 1440, 0, 0);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="wonder-output-") as directory:
        source, exe = Path(directory)/"test.c", Path(directory)/"test.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(exe), "-lm"], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: native Wonder docked output, monitor aspect, explicit sizes, pool cap and handheld isolation")


if __name__ == "__main__":
    main()
