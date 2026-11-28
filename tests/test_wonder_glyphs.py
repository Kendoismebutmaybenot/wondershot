"""Game-free: guarded Wonder hook installation and pinned snapshots of remapped prompt glyphs."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import wonder_glyphs  # noqa: E402


def check_hooks():
    words = {0x80089574: 0x3940F408, 0x840BC324: 0x2A1703E0}
    build_id = "ec47e6f8846d2a7b6892e2682845c7255f7117ae"
    for wrong_pc in words:
        lifter = SimpleNamespace(after={})
        bad = dict(words)
        bad[wrong_pc] ^= 1
        wonder_glyphs.install(lifter, SimpleNamespace(word=bad.__getitem__), "other-build")
        assert not lifter.after
        try:
            wonder_glyphs.install(lifter, SimpleNamespace(word=bad.__getitem__), build_id)
        except SystemExit as exc:
            assert hex(wrong_pc) in str(exc)
        else:
            raise AssertionError("installed hooks for mismatched instruction")
        assert not lifter.after
    wonder_glyphs.install(lifter, SimpleNamespace(word=words.__getitem__), build_id)
    assert lifter.after.keys() == words.keys()
    assert "hos_wonder_glyph_frame(c);" in lifter.after[0x80089574]
    assert "hos_wonder_glyph_result(c);" in lifter.after[0x840BC324]


FIXTURE = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <pthread.h>
#include "host/wonder_glyphs.h"

static pthread_rwlock_t lock = PTHREAD_RWLOCK_INITIALIZER;
static WonderGlyphs slots[2], *active;

static void *read_snapshots(void *unused) {
    (void)unused;
    for (int i = 0; i < 30000; i++) {
        assert(!pthread_rwlock_rdlock(&lock));
        const WonderGlyphs *map = wonder_glyphs_load(&active);
        const unsigned first = wonder_glyph_id(map, 0x1234, 0xe090, 42);
        assert(first != 0 && first != 42);
        assert(wonder_glyph_id(map, 0x1234, 0xe102, 42) == first + 0x72);
        assert(wonder_glyph_id(map, 0x1235, 0xe090, 42) == 42);
        assert(wonder_glyph_id(map, 0x1234, 0xe08f, 42) == 42);
        assert(wonder_glyph_id(map, 0x1234, 0xe103, 42) == 42);
        assert(wonder_glyph_id(map, 0x1234, 0x1e090, 42) == 42);
        assert(!pthread_rwlock_unlock(&lock));
    }
    return 0;
}

static void publish(unsigned generation) {
    assert(!pthread_rwlock_wrlock(&lock));
    WonderGlyphs *const next = &slots[wonder_glyphs_load(&active) == &slots[0]];
    next->font = 0x1234;
    for (unsigned i = 0; i <= 0x72; i++) next->glyph[i] = generation + i;
    wonder_glyphs_publish(&active, next);
    assert(wonder_glyphs_load(&active) == next);
    assert(!pthread_rwlock_unlock(&lock));
}

int main(void) {
    assert(wonder_glyph_id(wonder_glyphs_load(&active), 0x1234, 0xe090, 42) == 42);
    assert(wonder_glyph_id(&(WonderGlyphs){ .font = 0x1234 }, 0x1234, 0xe090, 42) == 42);
    publish(1);
    pthread_t readers[2];
    for (int i = 0; i < 2; i++) assert(!pthread_create(&readers[i], 0, read_snapshots, 0));
    for (unsigned i = 0; i < 2000; i++) publish(100 + i);
    for (int i = 0; i < 2; i++) assert(!pthread_join(readers[i], 0));
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    check_hooks()
    with tempfile.TemporaryDirectory(prefix="wonder-glyphs-") as directory:
        source = Path(directory) / "fixture.c"
        exe = source.with_suffix("")
        source.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread", "-I", str(ROOT),
                        str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: Wonder hook words, sfnt identity, prompt range and complete snapshot swaps")


if __name__ == "__main__":
    main()
