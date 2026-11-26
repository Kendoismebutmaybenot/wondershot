"""The Delay effect in host/nn_audio.c, with no game or audio device: its Add/Enable/Removable/Remove cycle and its echo.

Swamp Pipe Crawl's Wonder adds a delay effect (delay_wonder_dokanmorimori). When the course ends, the game disables it and
waits in a job, sleeping, until IsDelayRemovable says yes, then Remove hands back the work buffer to free. The build
stubbed every Delay call (a64_unimplemented answers 0), so IsDelayRemovable never said yes: the job never ended, the main
thread waited on it and the course-clear screen stayed grey (issue #7). The echo is checked with a click: the echoes come
one delay time apart, each the feedback gain of the one before, and a full channel spread moves each one to the other side.

python -I -B tests/test_audio_delay.py [--cc gcc] [--source host/nn_audio.c]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
HLE_START = "/* ---- Delay: AddDelay("
HLE_END = "/* ---- I3DL2 reverb: AddI3dl2Reverb("
DSP_START = "/* ---- Delay DSP ("
DSP_END = "static void effects_frame("

HARNESS = r'''#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { uint64_t x[8]; float vreg[8][4]; } Ctx;
#define HLE(name) void name(Ctx *c)
#define ARG(n) c->x[n]
#define RET(v) (c->x[0] = (uint64_t)(v))
#define GP(a) ((void *)(uintptr_t)(a))
#define AUT(...) ((void)0)
#define FRAME 240
#define RATE 48000
#define MAX_CH 8
#define MAX_BUF 24
#define MAX_EFFECTS 16
typedef struct { int buffers; float buf[MAX_BUF][FRAME]; } Mix;
static uint64_t effect_order;
static void au_lock(void) {}
static void au_unlock(void) {}
static int env_on(const char *name) { (void)name; return 0; }
static int mix_index(uint64_t obj) { return obj ? 0 : -1; }
static float farg(Ctx *c, int n) { return c->vreg[n][0]; }
#include "dsp.inc"
#include "hle.inc"
#define ADD _ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi
#define REMOVE _ZN2nn5audio11RemoveDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPNS0_10SubMixTypeE
#define REMOVABLE _ZN2nn5audio16IsDelayRemovableEPKNS0_9DelayTypeE
#define ENABLED _ZN2nn5audio14IsDelayEnabledEPKNS0_9DelayTypeE
#define SET_ENABLED _ZN2nn5audio15SetDelayEnabledEPNS0_9DelayTypeEb
#define GET_TIME _ZN2nn5audio12GetDelayTimeEPKNS0_9DelayTypeE
#define SET_TIME _ZN2nn5audio12SetDelayTimeEPNS0_9DelayTypeENS_8TimeSpanE
#define SET_IO _ZN2nn5audio19SetDelayInputOutputEPNS0_9DelayTypeEPKaS4_i
#define SET_FEEDBACK _ZN2nn5audio20SetDelayFeedbackGainEPNS0_9DelayTypeEf
#define SET_DRY _ZN2nn5audio15SetDelayDryGainEPNS0_9DelayTypeEf
#define SET_IN _ZN2nn5audio14SetDelayInGainEPNS0_9DelayTypeEf
#define SET_SPREAD _ZN2nn5audio21SetDelayChannelSpreadEPNS0_9DelayTypeEf
static int failed;
static void expect(const char *what, uint64_t got, uint64_t want) {
    if (got != want) {
        fprintf(stderr, "FAIL: %s: %llu, expected %llu\n", what, (unsigned long long)got, (unsigned long long)want);
        failed = 1;
    }
}
static void near(const char *what, float got, float want) {
    if (fabsf(got - want) > 1e-4f) {
        fprintf(stderr, "FAIL: %s: %.5f, expected %.5f\n", what, got, want);
        failed = 1;
    }
}
static void set_float(void (*fn)(Ctx *), uint64_t delay, float v) {
    Ctx c = {{delay}};
    c.vreg[0][0] = v;
    fn(&c);
}
/* a click on channel `side`, then `frames` frames: the left and right outputs, sample by sample */
static void run(uint64_t delay, int side, int frames, float *left, float *right) {
    static Mix mix = {2};
    Delay *d = delay_of(delay);
    for (int f = 0; f < frames; f++) {
        memset(mix.buf, 0, sizeof mix.buf);
        if (f == 0) mix.buf[side][0] = 1.0f;
        delay_frame(d, &mix);
        memcpy(left + f * FRAME, mix.buf[0], sizeof mix.buf[0]);
        memcpy(right + f * FRAME, mix.buf[1], sizeof mix.buf[1]);
    }
}
int main(void) {
    const uint64_t delay = 0x1078b260c0, buffer = 0x1078b27000, max_time = 4000000000ull, mix = 0x1078a6d0e0;
    Ctx c = {{0, delay, buffer, 0x10000, mix, max_time, 2}};
    ADD(&c);
    expect("AddDelay result", c.x[0], 0);
    c = (Ctx){{delay}};
    ENABLED(&c);
    expect("enabled after Add", c.x[0], 1);
    c = (Ctx){{delay}};
    GET_TIME(&c);
    expect("delay time after Add", c.x[0], max_time);
    c = (Ctx){{delay, 9000000000ull}};
    SET_TIME(&c);
    c = (Ctx){{delay}};
    GET_TIME(&c);
    expect("delay time held to the maximum Add gave", c.x[0], max_time);

    /* the SDK's AddDelay defaults: input gain and feedback 0, so a click passes dry with no echo */
    const int8_t io[2] = {0, 1};
    c = (Ctx){{delay, (uintptr_t)io, (uintptr_t)io, 2}};
    SET_IO(&c);
    c = (Ctx){{delay, 10000000}};
    SET_TIME(&c);
    static float left[12 * FRAME], right[12 * FRAME];
    run(delay, 0, 4, left, right);
    near("defaults: the click passes dry", left[0], 1.0f);
    near("defaults: no echo", left[480] + left[960], 0.0f);

    /* the echo: 10 ms apart (480 samples), output gain 1 (the SDK's), dry 0.5, feedback 0.5 */
    set_float(SET_IN, delay, 1.0f);
    set_float(SET_DRY, delay, 0.5f);
    set_float(SET_FEEDBACK, delay, 0.5f);
    set_float(SET_SPREAD, delay, 0.0f);
    run(delay, 0, 12, left, right);
    near("the click, dry", left[0], 0.5f);
    near("silence before the first echo", left[479], 0.0f);
    near("first echo at 10 ms, at the output gain", left[480], 1.0f);
    near("second echo, fed back", left[960], 0.5f);
    near("third echo", left[1440], 0.25f);
    near("no spread: nothing on the other side", right[480] + right[960], 0.0f);

    /* a full spread: each echo crosses to the other side */
    c = (Ctx){{0, delay + 0x2000, buffer, 0x10000, mix, max_time, 2}};
    ADD(&c);
    c = (Ctx){{delay + 0x2000, (uintptr_t)io, (uintptr_t)io, 2}};
    SET_IO(&c);
    c = (Ctx){{delay + 0x2000, 10000000}};
    SET_TIME(&c);
    set_float(SET_IN, delay + 0x2000, 1.0f);
    set_float(SET_DRY, delay + 0x2000, 0.5f);
    set_float(SET_FEEDBACK, delay + 0x2000, 0.5f);
    set_float(SET_SPREAD, delay + 0x2000, 1.0f);
    run(delay + 0x2000, 0, 12, left, right);
    near("spread: first echo on the click's side", left[480], 1.0f);
    near("spread: second echo crossed over", right[960], 0.5f);
    near("spread: none left on the click's side", left[960], 0.0f);
    near("spread: third echo back again", left[1440], 0.25f);
    /* a full low-pass amount: the line keeps 5 % of what goes in (its pole 0.95) */
    set_float(_ZN2nn5audio21SetDelayLowPassAmountEPNS0_9DelayTypeEf, delay + 0x2000, 1.0f);
    set_float(SET_SPREAD, delay + 0x2000, 0.0f);
    set_float(SET_FEEDBACK, delay + 0x2000, 0.0f);
    run(delay + 0x2000, 0, 12, left, right);
    run(delay + 0x2000, 0, 3, left, right);
    near("low-pass: the first echo is 5 % of the click", left[480], 0.05f);
    c = (Ctx){{delay + 0x2000, 0}};
    SET_ENABLED(&c);
    c = (Ctx){{0, delay + 0x2000, mix}};
    REMOVE(&c);

    /* disabled: the mix is left as it came */
    c = (Ctx){{delay, 0}};
    SET_ENABLED(&c);
    run(delay, 0, 1, left, right);
    near("disabled: dry click passes untouched", left[0], 1.0f);

    c = (Ctx){{delay}};
    REMOVABLE(&c);
    expect("removable once disabled (the course end waits on this)", c.x[0], 1);
    c = (Ctx){{0, delay, mix}};
    REMOVE(&c);
    expect("RemoveDelay hands back the work buffer", c.x[0], buffer);
    c = (Ctx){{delay}};
    REMOVABLE(&c);
    expect("removable after Remove", c.x[0], 1);
    /* the slots are free again: later courses add their own */
    for (int i = 0; i < 40; i++) {
        c = (Ctx){{0, delay + 0x1000, buffer, 0x10000, mix, max_time, 2}};
        ADD(&c);
        expect("AddDelay of a later course", c.x[0], 0);
        c = (Ctx){{delay + 0x1000, 0}};
        SET_ENABLED(&c);
        c = (Ctx){{0, delay + 0x1000, mix}};
        REMOVE(&c);
        expect("buffer of a re-added delay", c.x[0], buffer);
    }
    return failed;
}
'''


def section(source, start, end):
    at = source.index(start)
    return source[at:source.index(end, at)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--source', type=Path, default=ROOT / 'host/nn_audio.c')
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    if 'HLE(_ZN2nn5audio16IsDelayRemovableEPKNS0_9DelayTypeE)' not in source:
        sys.exit("FAIL: host/nn_audio.c does not implement nn::audio::IsDelayRemovable: the build stubs it to answer 0, "
                 "and a course that added a delay effect (Swamp Pipe Crawl) waits forever when it ends")
    if DSP_START not in source:
        sys.exit("FAIL: host/nn_audio.c has no delay DSP: the course's echo is not mixed")
    with tempfile.TemporaryDirectory(prefix='audio-delay-') as tmp:
        directory = Path(tmp)
        (directory / 'dsp.inc').write_text(section(source, DSP_START, DSP_END), encoding='utf-8')
        (directory / 'hle.inc').write_text(section(source, HLE_START, HLE_END), encoding='utf-8')
        test = directory / 'delay_test.c'
        test.write_text(HARNESS, encoding='utf-8')
        exe = directory / 'delay_test.exe'
        subprocess.run([args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-missing-field-initializers', '-I' + str(directory), str(test), '-o', str(exe), '-lm'], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
