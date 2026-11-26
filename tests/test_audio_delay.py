"""The Delay effect's Add/Enable/Removable/Remove cycle, from host/nn_audio.c, with no game or audio device.

Swamp Pipe Crawl's Wonder adds a delay effect (delay_wonder_dokanmorimori). When the course ends, the game disables it
and waits in a job, sleeping, until IsDelayRemovable says yes, then Remove hands back the work buffer to free. The
build stubbed every Delay call (a64_unimplemented answers 0), so IsDelayRemovable never said yes: the job never ended,
the main thread waited on it and the course-clear screen stayed grey (issue #7).

python -I -B tests/test_audio_delay.py [--cc gcc] [--source host/nn_audio.c]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
START = "/* ---- Delay:"
END = "/* ---- I3DL2 reverb: AddI3dl2Reverb("
TRACKER = "#define FX_TRACK 16"

HARNESS = r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint64_t x[8]; } Ctx;
#define HLE(name) void name(Ctx *c)
#define ARG(n) c->x[n]
#define RET(v) (c->x[0] = (uint64_t)(v))
#define AUT(...) ((void)0)
static void au_lock(void) {}
static void au_unlock(void) {}
#include "tracker.inc"
#include "delay.inc"
#define ADD _ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi
#define REMOVE _ZN2nn5audio11RemoveDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPNS0_10SubMixTypeE
#define REMOVABLE _ZN2nn5audio16IsDelayRemovableEPKNS0_9DelayTypeE
#define ENABLED _ZN2nn5audio14IsDelayEnabledEPKNS0_9DelayTypeE
#define SET_ENABLED _ZN2nn5audio15SetDelayEnabledEPNS0_9DelayTypeEb
#define GET_TIME _ZN2nn5audio12GetDelayTimeEPKNS0_9DelayTypeE
#define SET_TIME _ZN2nn5audio12SetDelayTimeEPNS0_9DelayTypeENS_8TimeSpanE
static int failed;
static void expect(const char *what, uint64_t got, uint64_t want) {
    if (got != want) {
        fprintf(stderr, "FAIL: %s: %llu, expected %llu\n", what, (unsigned long long)got, (unsigned long long)want);
        failed = 1;
    }
}
int main(void) {
    const uint64_t delay = 0x1078b260c0, buffer = 0x1078b27000, max_time = 4000000000ull;
    Ctx c = {{0, delay, buffer, 0x10000, 0x1078a6d0e0, max_time, 2}};
    ADD(&c);
    expect("AddDelay result", c.x[0], 0);
    c = (Ctx){{delay}};
    ENABLED(&c);
    expect("enabled after Add", c.x[0], 1);
    c = (Ctx){{delay}};
    GET_TIME(&c);
    expect("delay time after Add", c.x[0], max_time);
    c = (Ctx){{delay, 250000000}};
    SET_TIME(&c);
    c = (Ctx){{delay}};
    GET_TIME(&c);
    expect("delay time after SetDelayTime", c.x[0], 250000000);
    c = (Ctx){{delay}};
    REMOVABLE(&c);
    expect("removable while enabled", c.x[0], 0);
    c = (Ctx){{delay, 0}};
    SET_ENABLED(&c);
    c = (Ctx){{delay}};
    REMOVABLE(&c);
    expect("removable once disabled (the course end waits on this)", c.x[0], 1);
    c = (Ctx){{0, delay, 0x1078a6d0e0}};
    REMOVE(&c);
    expect("RemoveDelay hands back the work buffer", c.x[0], buffer);
    c = (Ctx){{delay}};
    REMOVABLE(&c);
    expect("removable after Remove", c.x[0], 1);
    /* the slot is free again: a later course can add its own */
    for (int i = 0; i < 40; i++) {
        c = (Ctx){{0, delay + 0x1000, buffer, 0x10000, 0x1078a6d0e0, max_time, 2}};
        ADD(&c);
        c = (Ctx){{delay + 0x1000, 0}};
        SET_ENABLED(&c);
        c = (Ctx){{0, delay + 0x1000, 0x1078a6d0e0}};
        REMOVE(&c);
        expect("buffer of a re-added delay", c.x[0], buffer);
    }
    return failed;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--source', type=Path, default=ROOT / 'host/nn_audio.c')
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    if START not in source or 'HLE(_ZN2nn5audio16IsDelayRemovableEPKNS0_9DelayTypeE)' not in source:
        sys.exit("FAIL: host/nn_audio.c does not implement nn::audio::IsDelayRemovable: the build stubs it to answer 0, "
                 "and a course that added a delay effect (Swamp Pipe Crawl) waits forever when it ends")
    tracker = source[source.index(TRACKER):source.index('HLE(', source.index(TRACKER))]
    delay = source[source.index(START):source.index(END, source.index(START))]
    with tempfile.TemporaryDirectory(prefix='audio-delay-') as tmp:
        directory = Path(tmp)
        (directory / 'tracker.inc').write_text(tracker, encoding='utf-8')
        (directory / 'delay.inc').write_text(delay, encoding='utf-8')
        test = directory / 'delay_test.c'
        test.write_text(HARNESS, encoding='utf-8')
        exe = directory / 'delay_test.exe'
        subprocess.run([args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-I' + str(directory), str(test), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
