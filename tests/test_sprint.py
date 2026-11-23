"""Sprint (host/nn_hid.c, the Controls page's line, the Controls tab's Sprint row, gpu/vk/menu/sprint.cpp): a control past the Switch's buttons with
keys and gamepad inputs that, while the left stick is pushed, holds A, the game's own run. Off by default.

The bindings: host/nn_hid.c's binding table is compiled alone (C), as tests/test_bound_keys.py does, and linked with the
Sprint module's apply_sprint_layout cut out of gpu/vk/menu/sprint.cpp (C++), against a fake longshot_options.ini for each case. A new
install's defaults are the ones from before Sprint (Shift B, the left stick's press LS) and give Sprint nothing; the row
turned on gives it Shift and the press (B to V, LS keeping its other input) and turned off puts them back; a player who
rebound B, Shift or the press, or whose V is taken, or who bound Sprint, keeps theirs. The sources are checked for the
rest: read_input reads Sprint's key and gamepad input (and a test run's SPRINT, which never reaches the game), npad_states hands sprint_step the stick only with the row on, the
module's row is on the Controls tab and lays the controls out as it changes, the Controls page has Sprint's line, writes
its pad_ line and lays them out again as it resets.
sprint_step is compiled alone: A only while steered and the key or the gamepad input held (let go, the plain run again),
hos_sprint_press_mask A's bit while it is Sprint's A (not the player's own), the
player's own A mid-sprint a gap and then a press of theirs (a tap shorter than the gap too). nx2/oot_patches.py patch_sprint_press runs on synthetic matcher input: the mask goes
between the pair that makes "pressed" and its store, in the two controllers' updates only, once.

Physical review: compare ae8e78b0910d with the updated head using an Xbox controller and keyboard on Windows and a
controller on Linux or Steam Deck. With Sprint Off and On, release Sprint while steering and press A during Sprint;
capture menu screenshots before and after. Report the Linux build, applicable Tier 1 coverage, lint and CI, and name
any suite failures also present on the baseline. This fixture does not exercise physical L3 or either platform's input.
python -I -B tests/test_sprint.py   (needs a C and a C++ compiler)
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_command import compiler_command, windows_arguments  # noqa: E402
import test_bound_keys  # noqa: E402  (its PRELUDE and the helpers that cut code out of a source)




MAIN = r"""
void sprint_layout(int on);   /* (the Sprint module's apply_sprint_layout, layout.cpp) */
int sprint_moved_while_on(void);   /* (layout.cpp: bindings it moved while the input could see Sprint on) */
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s line %d: %s\n", which, __LINE__, #c); fails++; } } while (0)
#define KEY(b) hos_binding(HOS_BIND_KEY, b, 0)
#define KEY2(b) hos_binding(HOS_BIND_KEY, b, 1)
#define PAD(b) hos_binding(HOS_BIND_PAD, b, 0)
#define PAD2(b) hos_binding(HOS_BIND_PAD, b, 1)
#define S HOS_KEY_SPRINT
int main(int argc, char **argv) {
    (void)argc;
    const char *which = argv[1];
    binds_load();
    if (!strcmp(which, "new")) {
        /* the defaults are those from before Sprint: it has nothing */
        CHECK(KEY(S) == 0 && KEY2(S) == 0 && PAD(S) == -1 && PAD2(S) == -1);
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
        CHECK(hos_binding(HOS_BIND_SPRINT_ON, 0, 0) == 0);   /* (no sprint= line: off) */
        sprint_layout(1);
        CHECK(KEY(S) == VK_SHIFT && PAD(S) == HOS_PAD_LSTICK);
        CHECK(KEY(HOS_SW_B) == 'V' && PAD(HOS_SW_B) == HOS_PAD_SOUTH);
        CHECK(PAD(HOS_SW_LS) == -1 && PAD2(HOS_SW_LS) == -1 && KEY(HOS_SW_LS) == VK_CONTROL);
        CHECK(hos_binding(HOS_BIND_SPRINT_ON, 0, 0) == 1);   /* (on, the layout whole) */
        sprint_layout(1);   /* (on again: nothing moves) */
        CHECK(KEY(S) == VK_SHIFT && KEY(HOS_SW_B) == 'V' && PAD(S) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == -1);
        sprint_layout(0);
        CHECK(hos_binding(HOS_BIND_SPRINT_ON, 0, 0) == 0);
        CHECK(KEY(S) == 0 && KEY2(S) == 0 && PAD(S) == -1 && PAD2(S) == -1);
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
        CHECK(!KEY2(HOS_SW_B));   /* (V gone with it) */
        /* a gamepad input bound to Sprint trades places with the Switch button that had it */
        sprint_layout(1);
        hos_bind(HOS_BIND_PAD, S, 0, HOS_PAD_SOUTH);
        CHECK(PAD(S) == HOS_PAD_SOUTH && PAD(HOS_SW_B) == HOS_PAD_LSTICK);
        hos_bind(HOS_BIND_KEY, S, 1, 'E');   /* a key bound to Sprint is taken from the button that had it */
        CHECK(KEY2(S) == 'E' && KEY(HOS_SW_A) == 0);
        hos_bind(HOS_BIND_PAD, HOS_KEY_MOVE_UP, 0, HOS_PAD_NORTH);   /* no gamepad input for a keys-only control */
        CHECK(PAD(HOS_KEY_MOVE_UP) == -1 && PAD(HOS_SW_X) == HOS_PAD_NORTH);
        hos_bind(HOS_BIND_KEY, -1, 0, 0);   /* Reset to defaults: Sprint's go (the menu then lays them out again) */
        CHECK(KEY(S) == 0 && PAD(S) == -1 && KEY(HOS_SW_B) == VK_SHIFT && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "ls-two")) {   /* LS has a second gamepad input: it keeps it */
        sprint_layout(1);
        CHECK(PAD(S) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == HOS_PAD_RPADDLE1 && PAD2(HOS_SW_LS) == -1);
        sprint_layout(0);
        CHECK(PAD(S) == -1 && PAD(HOS_SW_LS) == HOS_PAD_LSTICK && PAD2(HOS_SW_LS) == HOS_PAD_RPADDLE1);
    } else if (!strcmp(which, "rebound")) {   /* B on the B key, Shift on X, LS on the right stick's press: all kept */
        sprint_layout(1);
        CHECK(KEY(HOS_SW_B) == 'B' && KEY(HOS_SW_X) == VK_SHIFT && KEY(S) == 0);
        CHECK(PAD(HOS_SW_LS) == HOS_PAD_RSTICK && PAD(HOS_SW_RS) == HOS_PAD_LSTICK && PAD(S) == -1);
        sprint_layout(0);
        CHECK(KEY(HOS_SW_B) == 'B' && KEY(HOS_SW_X) == VK_SHIFT && PAD(HOS_SW_RS) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "v-taken")) {   /* V already Y's: B keeps Shift, Sprint gets no key, the press still */
        sprint_layout(1);
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && KEY2(HOS_SW_Y) == 'V' && KEY(S) == 0);
        CHECK(PAD(S) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == -1);
        sprint_layout(0);
        CHECK(KEY(HOS_SW_B) == VK_SHIFT && KEY2(HOS_SW_Y) == 'V' && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "own")) {   /* Sprint bound by the player: the row leaves everything as it is */
        CHECK(KEY(S) == 'G' && PAD(S) == HOS_PAD_LPADDLE1);
        sprint_layout(1);
        CHECK(KEY(S) == 'G' && PAD(S) == HOS_PAD_LPADDLE1 && KEY(HOS_SW_B) == VK_SHIFT && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
        sprint_layout(0);
        CHECK(KEY(S) == 'G' && PAD(S) == HOS_PAD_LPADDLE1 && KEY(HOS_SW_B) == VK_SHIFT && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "save-auto") || !strcmp(which, "save-user")) {
        sprint_layout(1);
        if (!strcmp(which, "save-user")) {
            /* Same-value rebinds transfer ownership to the player, then survive a restart. */
            hos_bind(HOS_BIND_KEY, S, 0, VK_SHIFT);
            hos_bind(HOS_BIND_PAD, S, 0, HOS_PAD_LSTICK);
        }
        FILE *out = fopen("longshot_options.ini", "w");
        CHECK(out != NULL);
        if (!out) return 1;
        fprintf(out, "sprint_auto_bind=%d\nkey_b=%d,0\nkey_sprint=%d,0\npad_ls=%d,%d\npad_sprint=%d\n",
                hos_binding(HOS_BIND_SPRINT_AUTO, 0, 0), KEY(HOS_SW_B), KEY(S), PAD(HOS_SW_LS), PAD2(HOS_SW_LS), PAD(S));
        fclose(out);
    } else if (!strcmp(which, "restore-auto")) {
        sprint_layout(0);
        CHECK(KEY(S) == 0 && KEY(HOS_SW_B) == VK_SHIFT);
        CHECK(PAD(S) == -1 && PAD(HOS_SW_LS) == HOS_PAD_LSTICK && PAD2(HOS_SW_LS) == HOS_PAD_RPADDLE1);
    } else if (!strcmp(which, "restore-user")) {
        sprint_layout(0);
        CHECK(KEY(S) == VK_SHIFT && KEY(HOS_SW_B) == 'V');
        CHECK(PAD(S) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == HOS_PAD_RPADDLE1 && PAD2(HOS_SW_LS) == -1);
    } else if (!strcmp(which, "rebind-source")) {
        sprint_layout(1);
        hos_bind(HOS_BIND_KEY, HOS_SW_B, 0, 'V');   /* the player now owns V on B */
        hos_bind(HOS_BIND_PAD, HOS_SW_LS, 0, HOS_PAD_RPADDLE1);
        sprint_layout(0);
        CHECK(KEY(S) == 0 && KEY(HOS_SW_B) == 'V');
        CHECK(PAD(S) == HOS_PAD_LSTICK && PAD(HOS_SW_LS) == HOS_PAD_RPADDLE1);
    } else if (!strcmp(which, "rebound-sprint")) {
        /* Sprint's key rebound by the player after the row moved Shift: theirs stays, and B, which they left alone, goes
           back to Shift, now free */
        sprint_layout(1);
        hos_bind(HOS_BIND_KEY, S, 0, 'G');
        sprint_layout(0);
        CHECK(KEY(S) == 'G' && KEY(HOS_SW_B) == VK_SHIFT);
        CHECK(PAD(S) == -1 && PAD(HOS_SW_LS) == HOS_PAD_LSTICK);
    } else if (!strcmp(which, "shift-taken")) {
        /* Sprint rebound to G, then Shift given to X by the player: B stays on V rather than take Shift from X */
        sprint_layout(1);
        hos_bind(HOS_BIND_KEY, S, 0, 'G');
        hos_bind(HOS_BIND_KEY, HOS_SW_X, 1, VK_SHIFT);
        sprint_layout(0);
        CHECK(KEY(S) == 'G' && KEY(HOS_SW_B) == 'V' && KEY2(HOS_SW_X) == VK_SHIFT);
    } else if (!strcmp(which, "saved-positive") || !strcmp(which, "saved-negative")) {
        CHECK(hos_binding(HOS_BIND_SPRINT_ON, 0, 0) == !strcmp(which, "saved-positive"));
        CHECK(KEY(S) == 'G');
    } else if (!strcmp(which, "own-defaults")) {
        sprint_layout(1);
        sprint_layout(0);
        CHECK(KEY(S) == VK_SHIFT && PAD(S) == HOS_PAD_LSTICK);
    } else {
        CHECK(!"no such case");
    }
    CHECK(sprint_moved_while_on() == 0);   /* (every layout move was inside the update) */
    if (!fails) printf("PASS %s\n", which);
    return fails != 0;
}
"""

# (the Sprint module's layout, cut out of gpu/vk/menu/sprint.cpp, with the host table above as its MkwVkHost)
LAYOUT = r"""
#include "vk_api.h"
extern "C" int hos_binding(int set, int button, int slot);
extern "C" void hos_bind(int set, int button, int slot, int code);
/* Every binding the layout moves must be inside the update. */
static int moved_while_on;
static bool updating;
static void bind_checked(int set, int button, int slot, int code) {
    if (set == HOS_BIND_SPRINT_BEGIN) updating = true;
    if ((set == HOS_BIND_KEY || set == HOS_BIND_PAD) && !updating) moved_while_on++;
    hos_bind(set, button, slot, code);
    if (set == HOS_BIND_SPRINT_ON) updating = false;
}
extern "C" int sprint_moved_while_on(void) { return moved_while_on; }
struct Host { int version; int (*binding)(int, int, int); void (*bind)(int, int, int, int); } host_value{39, hos_binding, bind_checked},
    *host = &host_value;
static bool can_bind() { return true; }
%s
extern "C" void sprint_layout(int on) { apply_sprint_layout(on != 0); }
"""

CASES = {
    "own-defaults": "key_sprint=16,0\npad_sprint=7\n",
    "new": None,
    "saved-positive": "sprint=2\nkey_sprint=71,0\n",
    "saved-negative": "sprint=-1\nkey_sprint=71,0\n",
    "ls-two": "pad_ls=7,17\n",
    "rebind-source": "pad_ls=7,17\n",
    "rebound": "key_b=66,0\nkey_x=16,0\npad_ls=8\npad_rs=7\n",
    "v-taken": "key_b=16,0\nkey_y=1,86\n",
    "own": "key_sprint=71,0\npad_sprint=18\n",
    "rebound-sprint": None,
    "shift-taken": None,
}

class SprintTests(unittest.TestCase):
    def test_windows_compiler_arguments(self):
        self.assertEqual(windows_arguments(r'clang -I"C:\Program Files\SDK"'),
                         ["clang", r"-IC:\Program Files\SDK"])
        self.assertEqual(windows_arguments(r'"C:\Program Files\LLVM\clang.exe" -DNAME="a b"'),
                         [r"C:\Program Files\LLVM\clang.exe", "-DNAME=a b"])
        self.assertEqual(windows_arguments(r'clang "C:\dir\\" "a\"b"'),
                         ["clang", "C:\\dir\\", 'a"b'])

    def test_sources(self):
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        read = test_bound_keys.block(hid, "static void read_input(")
        self.assertIn("bound_down(HOS_KEY_SPRINT, captured)", read, "read_input does not read Sprint's keys")
        self.assertEqual(read.count("sprint_now = pad_sprint_down();"), 2,
                         "read_input does not read Sprint's gamepad input, in front and behind another window")
        npad = test_bound_keys.block(hid, "static void npad_states(")
        enabled = "sprint_frame = (int)__atomic_load_n(&sprint_on, __ATOMIC_ACQUIRE);"
        self.assertLess(read.index("binds_load();"), read.index("AcquireSRWLockShared(&input_bind_lock);"))
        self.assertLess(read.index("AcquireSRWLockShared(&input_bind_lock);"), read.index(enabled))
        self.assertLess(read.index(enabled), read.index("bound_down(HOS_KEY_SPRINT, captured)"))
        self.assertLess(read.index("ReleaseSRWLockShared(&input_bind_lock);"), read.index("hos_oot_autoload_input();"))
        self.assertLess(read.index("input_pads[i][k] = pad_bind[i][k]"), read.index("ReleaseSRWLockShared(&input_bind_lock);"))
        self.assertLess(npad.index("read_input(&buttons, &taps, stick);"), npad.index("const int sprint_enabled = sprint_frame;"))
        self.assertIn("const int physical_sprint = sprint_enabled ? sprint_now : 0;",
                      npad, "Sprint runs without the Controls tab's Sprint row on")
        self.assertIn("sprint_step(&buttons, sprint_held, steered, menu_open || hos_oc_wait == 1, hos_now_ns(),", npad,
                      "npad_states does not give Sprint the buttons as the game will get them")
        self.assertLess(npad.index("const int steered ="), npad.index("sprint_step("),
                        "Sprint must see the stick before it lets it go")
        # (a script's or the bridge's SPRINT: Sprint's key for a test run, never a button the game or the cheats see)
        self.assertIn('{"SPRINT", B_SPRINT}', test_bound_keys.block(hid, "static int parse_presses(const char *s, int64_t base_ms, int live) {"),
                      "HOS_INPUT_SCRIPT has no SPRINT")
        control = (ROOT / "host" / "control.c").read_text(encoding="utf-8")
        self.assertIn('{"SPRINT", 48, 0, 0}', control, "the control bridge has no SPRINT")
        self.assertIn("enum { B_SPRINT = 48 };", hid, "the bridge's SPRINT bit is not nn_hid.c's")
        self.assertIn("& ~(pad_after_menu | hud_pad_mask());", test_bound_keys.block(hid, "static int pad_sprint_down("),
                      "Sprint's gamepad input fires with the HUD shortcut's, which owns its inputs")
        took = npad.index("const int synthetic_sprint = buttons >> B_SPRINT & 1;")
        self.assertLess(npad.index("read_input(&buttons, &taps, stick);"), took)
        self.assertLess(took, npad.index("buttons &= ~(1ULL << B_SPRINT);"))
        self.assertLess(npad.index("buttons &= ~(1ULL << B_SPRINT);"), npad.index("hos_hid_buttons = buttons;"),
                        "SPRINT reaches the game's buttons or the cheats")
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        module = (ROOT / "gpu" / "vk" / "menu" / "sprint.cpp").read_text(encoding="utf-8")
        row = test_bound_keys.block(module, "MENU_MODULE(sprint)")
        self.assertIn('menu::tab("controls")', row, "the Sprint row is not on the Controls tab")
        self.assertIn('.key = "sprint"', row, "the Sprint row does not save as sprint=")
        self.assertIn("changes your controls", row, "the Sprint row does not warn that it changes the controls")
        self.assertNotIn('"Sprint", &opts.sprint', menu, "the Sprint row is in vk_menu.cpp's table, not its module")
        self.assertIn("int sprint = 0;", (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8"),
                      "Sprint is not off by default")
        self.assertIn(".on_change = MENU_HOOK(sprint_chosen)", row, "turning the row on or off does not lay out the controls")
        self.assertIn("void sprint_chosen(int v) { apply_sprint_layout(v != 0); }", module,
                      "the row's on_change does not lay out the controls")
        self.assertIn("if (opts.sprint) apply_sprint_layout(true);", menu, "Reset to defaults leaves Sprint with nothing")
        replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
        self.assertIn("if (id == HOS_OPT_SPRINT) return opts.sprint;", replay, "the host cannot see the Sprint row")
        names = test_bound_keys.block(hid, "static const char *const bind_names[HOS_KEY_N]")
        menu_names = test_bound_keys.block(menu, "const char* const bind_names[HOS_KEY_N]")
        self.assertEqual(re.findall(r'"(\w+)"', names), re.findall(r'"(\w+)"', menu_names),
                         "the menu writes other names than host/nn_hid.c reads")
        self.assertEqual(re.findall(r'"(\w+)"', names)[-1], "sprint", "Sprint's lines are not pad_sprint and key_sprint")
        self.assertIn('{HOS_KEY_SPRINT, "Sprint"}', menu, "the Controls page has no Sprint row")
        self.assertIn("i == HOS_KEY_SPRINT) {\n                const int alternate", menu, "the menu does not write pad_sprint")
        api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
        self.assertIn("HOS_KEY_TOGGLE_HUD, HOS_KEY_SPRINT, HOS_KEY_N };", api,
                      "Sprint is not the control after the HUD shortcut")

    def test_bindings(self):
        cc = compiler_command("CC", "gcc", "clang")
        cxx = compiler_command("CXX", "g++", "clang++")
        if not cc or not cxx or not cc[0] or not cxx[0]:
            self.skipTest("no C and C++ compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        code = test_bound_keys.between(hid, "static const char *const bind_names[HOS_KEY_N]", "void hos_bind(int set, int button, int slot, int code) {")
        code = code.replace("GetModuleFileNameA(NULL,", "GetModuleFileNameA(0,")
        module = (ROOT / "gpu" / "vk" / "menu" / "sprint.cpp").read_text(encoding="utf-8")
        layout = test_bound_keys.block(module, "void apply_sprint_layout(")
        include = ["-I", str(ROOT / "gpu" / "vk"), "-I", str(ROOT / "gpu")]
        with tempfile.TemporaryDirectory(prefix="longshot-sprint-") as tmp:
            tmp = Path(tmp)
            prelude = test_bound_keys.PRELUDE
            start = prelude.index("static const char *hos_options_file(void)")
            end = prelude.index("static int held[256];", start)
            prelude = prelude[:start] + 'static const char *hos_options_file(void) { return "longshot_options.ini"; }\n' + prelude[end:]
            (tmp / "t.c").write_text(prelude + code + MAIN, encoding="utf-8")
            (tmp / "layout.cpp").write_text(LAYOUT % layout, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            for command in ([*cc, "-std=gnu11", "-Wall", "-Wno-unused-function", *include, "-c", str(tmp / "t.c"),
                             "-o", str(tmp / "t.o")],
                            [*cxx, "-std=c++17", "-Wall", "-Wextra", *include, "-c", str(tmp / "layout.cpp"),
                             "-o", str(tmp / "layout.o")],
                            [*cxx, str(tmp / "t.o"), str(tmp / "layout.o"), "-o", str(binary)]):
                build = subprocess.run(command, text=True, capture_output=True)
                self.assertEqual(build.returncode, 0, build.stderr)
            for name, ini in CASES.items():
                with self.subTest(case=name):
                    folder = tmp / name
                    folder.mkdir()
                    if ini is not None:
                        (folder / "longshot_options.ini").write_text(ini, encoding="utf-8")
                    run = subprocess.run([str(binary), name], cwd=folder, text=True, capture_output=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            for case in ("auto", "user"):
                with self.subTest(restart=case):
                    folder = tmp / case
                    folder.mkdir()
                    (folder / "longshot_options.ini").write_text(CASES["ls-two"], encoding="utf-8")
                    for action in ("save", "restore"):
                        run = subprocess.run([str(binary), f"{action}-{case}"], cwd=folder,
                                             text=True, capture_output=True, timeout=30)
                        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


STEP_MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
enum { B_A = 0 };
volatile uint32_t hos_sprint_press_mask;
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
static uint64_t b;
static void step_a(int held, int steered, int menu, int64_t ms, int own_a) {
    b = own_a ? 1 : 0;
    sprint_step(&b, held, steered, menu, ms * 1000000, 0);
}
static void step(int held, int steered, int menu, int64_t ms) { step_a(held, steered, menu, ms, 0); }
#define RUNS (b & 1)
#define MASK hos_sprint_press_mask
int main(void) {
    /* the key: A while held and steered, the stick as it is; the press mask A's bit while it is Sprint's A */
    step(SPRINT_KEY, 0, 0, 0);       CHECK(!RUNS && !MASK);   /* standing: nothing */
    step(SPRINT_KEY, 1, 0, 1000);    CHECK(RUNS && MASK == 1);
    step(SPRINT_KEY, 1, 0, 1100);    CHECK(RUNS && MASK == 1);
    /* the player's own A going down mid-sprint: A let go for the gap, then held as their press (the mask 0) */
    step_a(SPRINT_KEY, 1, 0, 1150, 1);   CHECK(!RUNS && MASK == 0);   /* the gap: A up */
    step_a(SPRINT_KEY, 1, 0, 1180, 1);   CHECK(!RUNS && MASK == 0);
    step_a(SPRINT_KEY, 1, 0, 1201, 1);   CHECK(RUNS && MASK == 0);    /* A down again: a press, theirs */
    step(SPRINT_KEY, 1, 0, 1230);        CHECK(RUNS && MASK == 0);    /* theirs up: still owed for the gap */
    step(SPRINT_KEY, 1, 0, 1260);        CHECK(RUNS && MASK == 1);    /* Sprint's own A again: no press */
    /* a tap shorter than the gap: the press still comes */
    step_a(SPRINT_KEY, 1, 0, 1300, 1);   CHECK(!RUNS);
    step(SPRINT_KEY, 1, 0, 1320);        CHECK(!RUNS);
    step(SPRINT_KEY, 1, 0, 1360);        CHECK(RUNS && MASK == 0);
    step(SPRINT_KEY, 1, 0, 1420);        CHECK(RUNS && MASK == 1);

    step(0, 1, 0, 1450);             CHECK(!RUNS && !MASK);   /* let go: walks */
    /* their A down before Sprint starts: theirs, no gap */
    step_a(0, 1, 0, 1460, 1);        CHECK(RUNS && !MASK);    /* (the player's own A: not Sprint's) */
    step_a(SPRINT_KEY, 1, 0, 1470, 1);   CHECK(RUNS && MASK == 0);
    step(0, 1, 0, 1480);
    step(SPRINT_KEY, 1, 1, 1500);    CHECK(!RUNS && !MASK);   /* not with the menu open */
    /* Releasing Sprint and tapping A in the same sample still creates the gap and delivers the tap. */
    step(SPRINT_PAD, 1, 0, 1510);         CHECK(RUNS && MASK == 1);
    step_a(0, 1, 0, 1520, 1);           CHECK(!RUNS && !MASK);
    step(0, 1, 0, 1530);                 CHECK(!RUNS && !MASK);
    step(0, 1, 0, 1571);                 CHECK(RUNS && !MASK);
    step(0, 1, 0, 1600);
    /* a tap remains owed when Sprint is released or movement stops during the gap */
    step(SPRINT_KEY, 1, 0, 1650);
    step_a(SPRINT_KEY, 1, 0, 1660, 1); CHECK(!RUNS);
    step(0, 1, 0, 1680);               CHECK(!RUNS && !MASK);
    step(0, 1, 0, 1800);               CHECK(RUNS && !MASK); /* even after a long frame */
    step(0, 1, 0, 1860);               CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 1870);
    step_a(SPRINT_KEY, 1, 0, 1880, 1); CHECK(!RUNS);
    step(SPRINT_KEY, 0, 0, 1900);      CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 0, 0, 1940);      CHECK(RUNS && !MASK);
    step(0, 0, 0, 1990);               CHECK(!RUNS && !MASK);
    /* a long interval between reads still delivers the tap while Sprint remains held */
    step(SPRINT_KEY, 1, 0, 1991);
    step_a(SPRINT_KEY, 1, 0, 1992, 1); CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 2192);      CHECK(RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 2252);      CHECK(RUNS && MASK == 1);
    step(0, 0, 0, 2260);
    /* the gamepad input: only while held, as the key */
    step(SPRINT_PAD, 1, 0, 2300);    CHECK(RUNS && MASK == 1);
    step(SPRINT_PAD, 1, 0, 2350);    CHECK(RUNS && MASK == 1);   /* held: runs */
    step(0, 1, 0, 2400);             CHECK(!RUNS && !MASK);    /* let go while moving: back to the plain run */
    step(0, 1, 0, 2500);             CHECK(!RUNS);             /* (and stays so) */
    step(SPRINT_PAD, 0, 0, 2600);    CHECK(!RUNS && !MASK);    /* held standing: nothing */
    step(SPRINT_PAD, 1, 0, 2700);    CHECK(RUNS && MASK == 1);   /* still held, moving again: runs, no new press needed */
    step(0, 0, 0, 2800);             CHECK(!RUNS && !MASK);    /* stopped and let go: off */
    /* A second tap during the first tap's owed interval needs its own gap. */
    step(SPRINT_KEY, 1, 0, 2900);        CHECK(RUNS && MASK == 1);
    step_a(SPRINT_KEY, 1, 0, 2910, 1);  CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 2920);      CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 2961);      CHECK(RUNS && !MASK);
    step_a(SPRINT_KEY, 1, 0, 2970, 1); CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 2980);      CHECK(!RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 3021);      CHECK(RUNS && !MASK);
    step(SPRINT_KEY, 1, 0, 3072);      CHECK(RUNS && MASK == 1);
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


TOGGLE_MAIN = r"""
#include <stdio.h>
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void) {
    /* Toggle off: held as it is */
    CHECK(sprint_toggle_step(SPRINT_PAD, 0, 0) == SPRINT_PAD);
    CHECK(sprint_toggle_step(0, 0, 0) == 0);
    /* Toggle on: a press starts it, it stays on let go, the next press ends it */
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 0) == SPRINT_KEY);
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 0) == SPRINT_KEY);   /* (still the same press) */
    CHECK(sprint_toggle_step(0, 1, 0) == SPRINT_KEY);            /* let go: still on */
    CHECK(sprint_toggle_step(SPRINT_KEY, 1, 0) == 0);            /* the next press: off */
    CHECK(sprint_toggle_step(0, 1, 0) == 0);
    /* a reset ends it, and the press held across it does not start it again */
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 0) == SPRINT_KEY);
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 1) == 0);
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 0) == 0);
    CHECK(sprint_toggle_step(0, 1, 0) == 0);
    CHECK(sprint_toggle_step(SPRINT_PAD, 1, 0) == SPRINT_KEY);   /* a new press: on */
    /* the Toggle turned off: held again at once, nothing latched */
    CHECK(sprint_toggle_step(0, 0, 0) == 0);
    CHECK(sprint_toggle_step(0, 1, 0) == 0);
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


class SprintToggleTests(unittest.TestCase):
    """host/nn_hid.c sprint_toggle_step alone: the Controls page's Toggle for Sprint"""

    def test_toggle(self):
        compiler = compiler_command("CC", "gcc", "clang")
        if not compiler[0]:
            self.skipTest("no C compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        code = (test_bound_keys.block(hid, "enum { SPRINT_KEY") + ";\n" +
                test_bound_keys.block(hid, "static int sprint_toggle_step("))
        with tempfile.TemporaryDirectory(prefix="longshot-sprint-toggle-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(code + "\n#define sprint_toggle_step(a,b,c) sprint_toggle_step(a,b,c,0)\n" + TOGGLE_MAIN, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run(compiler + ["-std=gnu11", "-Wall", "-Werror", str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_wiring(self):
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        npad = test_bound_keys.block(hid, "static void npad_states(")
        self.assertIn("const int sprint_toggle = sprint_enabled && sprint_toggle_frame;", npad)
        self.assertIn("sprint_toggle_step(physical_sprint, sprint_toggle, sprint_reset, suppressed)", npad,
                      "npad_states does not give Sprint's held through its Toggle")
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn("|| button == HOS_KEY_SPRINT;", test_bound_keys.block(menu, "bool has_toggle(int button) {"),
                      "the Controls page has no Toggle for Sprint")
        self.assertIn('if (i < HOS_SW_N || i == HOS_KEY_SPRINT) fprintf(f, "toggle_%s=%d\\n"', menu,
                      "the menu does not save toggle_sprint")
        replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
        self.assertIn("host->binding(HOS_BIND_SPRINT_TOGGLE, 0, 0)", replay,
                      "the host cannot see Sprint's Toggle")


class SprintStepTests(unittest.TestCase):
    def test_step(self):
        compiler = compiler_command("CC", "gcc", "clang")
        if not compiler or not compiler[0]:
            self.skipTest("no C compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        gap = re.search(r"^#define SPRINT_ROLL_GAP_MS [^\n]*", hid, re.M).group(0)
        code = (test_bound_keys.block(hid, "enum { SPRINT_KEY") + ";\n" + gap + "\n" +
                test_bound_keys.block(hid, "static void sprint_step("))
        head, body = STEP_MAIN.split("static int fails;", 1)
        with tempfile.TemporaryDirectory(prefix="longshot-sprint-step-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(head + code + "\nstatic int fails;" + body, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([*compiler, "-std=gnu11", "-Wall", "-Werror", str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class SprintPressPatchTests(unittest.TestCase):
    """Exercise the matcher with independently authored synthetic functions."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "nx2"))
        import oot_patches
        self.p = oot_patches
        pair = lambda reg: (
            '    { uint64_t _r = (c->x[8] & ~((uint64_t)(uint32_t)(((uint32_t)(c->x[%d])) << 0))); _r &= 0xFFFFFFFFULL; c->x[9] = _r; }\n'
            '    { uint64_t _r = (c->x[%d] & ~((uint64_t)(uint32_t)(((uint32_t)(c->x[8])) << 0))); _r &= 0xFFFFFFFFULL; c->x[8] = _r; }\n' % (reg, reg))
        self.heads = ('void f_8038a220(Ctx *__restrict A64_NOESC c) {',
                      'void f_834a3680(Ctx *__restrict A64_NOESC c) {')
        self.sample = ('#include "a64.h"\n' + self.heads[0] + '\n    synthetic_before();\n' + pair(28) +
                       '    synthetic_store();\n}\n' + self.heads[1] + '\n' + pair(21) +
                       '    synthetic_store();\n}\nvoid f_80000000(Ctx *c) {\n' + pair(28) + '}\n')

    def test_patch(self):
        out, n = self.p.patch_sprint_press(self.sample)
        self.assertEqual(n, 2)
        self.assertEqual(out.count(self.p.SPRINT_MASK), 2, "the mask is not in both controllers' update")
        self.assertEqual(out.count(self.p.SPRINT_DECL), 1)
        for head in self.heads:
            body = out[out.index(head):]
            body = body[:body.index("\n}\n")]
            self.assertLess(body.index("c->x[9] = _r; }"), body.index(self.p.SPRINT_MASK), "the mask before pressed is made")
            self.assertLess(body.index(self.p.SPRINT_MASK), body.index("synthetic_store"), "the mask after the store")
        other = out[out.index("void f_80000000"):]
        self.assertNotIn("hos_sprint_press_mask", other, "a function that is not the controllers' update was patched")
        again, n2 = self.p.patch_sprint_press(out)
        self.assertEqual((again, n2), (out, 2), "a second run changes the code")

    def test_drifted(self):
        """an anchor that is not there leaves the code as it was, and the count says so (report() warns)"""
        drifted = self.sample.replace("c->x[28]", "c->x[27]")
        out, n = self.p.patch_sprint_press(drifted)
        self.assertEqual(n, 1)
        self.assertNotIn(self.p.SPRINT_MASK, out[out.index(self.heads[0]):out.index(self.heads[1])])
        self.assertEqual(self.p.patch_sprint_press("#include \"a64.h\"\n"), ("#include \"a64.h\"\n", 0))

    def test_body_ends_at_its_brace(self):
        """f_8038a220 without its pair, followed by a function that is not a `void f_` with one: that pair is not
        counted as f_8038a220's (the body ends at its own closing brace), and is left alone"""
        lines = self.sample.split("\n")
        start = lines.index("void f_8038a220(Ctx *__restrict A64_NOESC c) {")
        pair, store = lines[start + 2:start + 4], lines[start + 4]
        helper = ["static void helper(Ctx *__restrict A64_NOESC c) {"] + pair + [store, "}"]
        text = "\n".join(lines[:start + 2] + [store, "}"] + helper + lines[start + 6:])
        self.assertIn("static void helper", text)
        out, n = self.p.patch_sprint_press(text)
        self.assertEqual(n, 1, "the pair in the function after f_8038a220 was counted as its own")
        self.assertNotIn(self.p.SPRINT_MASK, out[out.index("static void helper"):out.index("void f_834a3680")])

    def test_host_side(self):
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        self.assertIn("volatile uint32_t hos_sprint_press_mask;", hid, "the host has no press mask for the patch")
        patches = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
        self.assertIn('counts["sprint press"] += n', patches, "patch_file does not run the patch")
        self.assertIn('total["sprint press"] != len(SPRINT_HEADS)', patches, "report() does not warn when it is missing")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
