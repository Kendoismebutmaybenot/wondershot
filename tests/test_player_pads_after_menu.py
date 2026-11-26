"""Players 2 to 4 leave the game alone while the Insert menu is open (host/nn_hid.c, player_menu_gate).

Every player but the keyboard's reads its own pad in npad_states. That path used to give the game its buttons and sticks
with the Insert menu open, so steering the menu with such a pad also played the game: with the Controls page's Keyboard
and mouse row on player 2, the first pad (player 1) was one. Now those pads are the menu's while it is open, and after
it closed each input it had waits until it is let go, as the keyboard's player's pad does (tests/test_pads_after_menu.py).
Production's bound_pad_buttons_p, role_table and player_menu_gate are compiled with a fake menu; no device is read, and
npad_states must pass every such player's read through the gate.

python -I -B tests/test_player_pads_after_menu.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PRELUDE = r"""#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef long LONG;
typedef int SRWLOCK;
static void AcquireSRWLockShared(SRWLOCK *p) { (void)p; }
static void ReleaseSRWLockShared(SRWLOCK *p) { (void)p; }
static SRWLOCK pad_bind_lock;
static int menu_open;
int rx_option(int id, int otherwise) { return id == 1 ? menu_open : otherwise; }
"""

MAIN = r"""
#define PAD(p) (1ULL << HOS_PAD_##p)
#define SW(b) (1ULL << HOS_SW_##b)
/* one read of player pl's npad, as npad_states makes it: the pad through that player's controls, then the gate */
static uint64_t game(int pl, uint64_t raw, int32_t stick[4], int32_t x) {
    uint64_t buttons = bound_pad_buttons_p(role_table(pl), raw);
    memset(stick, 0, 4 * sizeof *stick);
    stick[0] = x;
    player_menu_gate(pl, raw, &buttons, stick);
    return buttons;
}

int main(void) {
    for (int p = 0; p < 3; p++)
        for (int i = 0; i < HOS_SW_N; i++) pad_bind_p[p][i][0] = pad_default[i], pad_bind_p[p][i][1] = -1;
    kb_player = 1;   /* (the keyboard on player 2: player 1's pad comes through here, as in the report) */
    int32_t s[4];
    CHECK(game(0, PAD(SOUTH), s, 0) == SW(B));   /* (by position: the bottom face button is the Switch's B) */
    CHECK(game(0, 0, s, 0) == 0);

    /* The menu open: nothing reaches the game, buttons or sticks */
    menu_open = 1;
    CHECK(game(0, PAD(SOUTH), s, 30000) == 0 && s[0] == 0);
    CHECK(game(0, PAD(DOWN) | PAD(EAST), s, -30000) == 0 && s[0] == 0);

    /* Closed with East (A) still down: it waits until let go; the sticks count at once */
    menu_open = 0;
    CHECK(game(0, PAD(EAST), s, 30000) == 0 && s[0] == 30000);
    CHECK(game(0, PAD(EAST), s, 0) == 0);
    CHECK(game(0, PAD(EAST) | PAD(SOUTH), s, 0) == SW(B));   /* another button counts with it still down */
    CHECK(game(0, 0, s, 0) == 0);
    CHECK(game(0, PAD(EAST), s, 0) == SW(A));   /* pressed again: the game's */

    /* The menu closed by a press no read saw while it was open: it waits too */
    menu_open = 1; CHECK(game(0, 0, s, 0) == 0);
    menu_open = 0; CHECK(game(0, PAD(EAST), s, 0) == 0);
    CHECK(game(0, 0, s, 0) == 0);
    CHECK(game(0, PAD(EAST), s, 0) == SW(A));

    /* Each player waits on its own: player 3's held button does not hold player 1's */
    menu_open = 1;
    CHECK(game(2, PAD(NORTH), s, 0) == 0 && game(0, 0, s, 0) == 0);
    menu_open = 0;
    CHECK(game(2, PAD(NORTH), s, 0) == 0 && game(0, 0, s, 0) == 0);   /* (each one's first read after the close) */
    CHECK(game(2, PAD(NORTH), s, 0) == 0);
    CHECK(game(0, PAD(NORTH), s, 0) == SW(X));
    CHECK(game(2, 0, s, 0) == 0 && game(2, PAD(NORTH), s, 0) == SW(X));
    puts("PASS: players 2 to 4 give the game nothing while the Insert menu is open, and wait input by input after it");
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")

    # npad_states passes every player's read but the keyboard's through the gate, after the background check
    npad = block(hid, "static void npad_states(")
    players = block(npad, "if (id <= 3 && id != (uint32_t)kb_player)")
    read = players.find("player_read((int)id, &raw, &pb, ps)")
    gate = players.find("player_menu_gate((int)id, raw, &pb, ps)")
    if read < 0 or gate < read or gate > players.index("for (int i = 0; i < count; i++)"):
        raise SystemExit("FAIL: npad_states' players 2 to 4 do not pass through player_menu_gate before their states")

    code = "\n".join((
        block(api, "enum { HOS_SW_A") + ";", block(api, "enum { HOS_PAD_SOUTH") + ";",
        PRELUDE,
        block(hid, "static const signed char pad_default[HOS_SW_N] =") + ";",
        re.search(r"^static int pad_bind_p\[3\]\[HOS_SW_N\]\[2\];$", hid, re.M).group(0),
        re.search(r"^static volatile LONG kb_player;$", hid, re.M).group(0),
        re.search(r"^static int role_table\(int player\).*$", hid, re.M).group(0),
        block(hid, "static uint64_t bound_pad_buttons_p("),
        re.search(r"^static uint64_t player_after_menu\[4\];$", hid, re.M).group(0),
        re.search(r"^static int player_menu_was\[4\];$", hid, re.M).group(0),
        block(hid, "static void player_menu_gate("),
        MAIN))
    with tempfile.TemporaryDirectory(prefix="wondershot-player-pads-after-menu-") as tmp:
        src = Path(tmp) / "t.c"
        src.write_text(code, encoding="utf-8")
        exe = Path(tmp) / "t.exe"
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-o", str(exe), str(src)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        if r.returncode:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
