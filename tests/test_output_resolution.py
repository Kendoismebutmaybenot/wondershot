"""Exercise the host and menu's docked output sizes without a game dump: output_res as a size, the numbers saved before, a size
of the player's own, the Aspect ratio row's shapes and what the menu saves. The screen's display modes are none here, so the
menu offers the sizes it offered before them (vk_menu.cpp outputs): 0 the game's own, 1 1920x1080, 2 2560x1440, 3 3840x2160,
4 5120x1440, 5 5120x2880, 6 the player's own."""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from menu_model_fixture import menu_text, output_engine  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

# (env_on, the switches' rule, before the code cut out of the sources: gpu/vk/compat/longshot_env.h)
ENV_ON_H = str(Path(__file__).resolve().parents[1] / "gpu" / "vk" / "compat" / "longshot_env.h")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()

    host = (ROOT / "host/nn_applet.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    upscaler = (ROOT / "gpu" / "vk" / "menu" / "upscaler.cpp").read_text(encoding="utf-8")   # (tx_resolution: the module's)
    fixture = r'''
#define _CRT_SECURE_NO_WARNINGS
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>

using DWORD = unsigned long;
constexpr int MAX_PATH = 260;
DWORD hos_game_path_a(char *path, int size) { return snprintf(path, size, "./longshot.exe"); }
const char *hos_options_file() { return "./longshot_options.ini"; }   // (host/options_path.c: the user folder's)
void hos_log(const char *, ...) {}
// (the main screen at boot, for an options file with no output_res=: none known here, so the game's 2560x1440)
constexpr int SM_CXSCREEN = 0, SM_CYSCREEN = 1;
int GetSystemMetrics(int) { return 0; }
volatile uint64_t hos_wide_out = 0;   // (host/hos_main.c: the widescreen picture, 0 = none; nn_applet.c reads it)
struct { int handheld, output_res, ultrawide; } opts;
#include "host/hos_wide_size.h"
// (the main screen tx_output_res shapes its sizes for: none unless a check sets one)
static uint32_t screen_w = 0, screen_h = 0;
bool screen_size(uint32_t* w, uint32_t* h) { return screen_w ? (*w = screen_w, *h = screen_h, true) : false; }
// (the host's screen, whose shape ultrawide=1 gives a 16:9 size: the same one unless a check sets another)
static uint32_t host_w = 0, host_h = 0;
bool host_screen_size(uint32_t* w, uint32_t* h) {
    return host_w ? (*w = host_w, *h = host_h, true) : screen_size(w, h);
}
namespace mkwvk {
int up_now = 0;   // (the Upscaler shown: 0 the game's own, 1 DLSS, 2 DLAA)
int upscaler() { return up_now; }
}
#include "gpu/vk/upscaler_rows.h"
#include "gpu/vk/display_modes.h"
using namespace mkwvk;
namespace ur = upscaler_rows;
// (the screen's display modes: none, so the sizes offered before them)
std::vector<display_modes::Size> screen_modes() { return {}; }
''' + host[host.index("int hos_ini_option(const char *key, int otherwise);"):host.index("/* Private tier spike:")] + \
        output_engine(ROOT, "/// The Output resolution: the game's own reduced size") + \
        upscaler[upscaler.index("const char* tx_resolution(int v) {"):upscaler.index("\n}\n", upscaler.index("const char* tx_resolution(int v) {")) + 3] + r'''
int main(int argc, char **argv) {
    assert(argc == 7);
    const int mode = atoi(argv[1]), pool = atoi(argv[5]);   // (mode: the menu's choice, 6 the player's own size)
    const unsigned w = atoi(argv[2]), h = atoi(argv[3]);
    assert(output_mode() == (mode != 0));
    assert(hos_output_size(0) == w && hos_output_size(1) == h);
    assert(hos_rt_pool_size(305ull << 20) == ((uint64_t)pool << 20));   // (512 MB at least, 900 MB at most above 4K: nn_applet.c)
    // (the menu reads the same text: the ini's, or HOS_OUTPUT_RES over it)
    const char* e = getenv("HOS_OUTPUT_RES");
    char text[80] = "";
    if (!e && !ini_text("output_res", text, sizeof text)) {   // (none chosen: the default, as vk_menu.cpp menu_init takes it)
        uint32_t dw = 0, dh = 0;
        hos_output_default(0, 0, &dw, &dh);
        snprintf(text, sizeof text, "%ux%u", dw, dh);
    }
    opts.handheld = handheld();
    opts.output_res = opts.handheld ? 0 : parse_output(e ? e : text);
    if (!opts.handheld) assert(opts.output_res == mode);
    assert(custom_index() == 6);
    assert(output_choice(-1) == 0 && output_choice(5) == 5 && output_choice(7) == 0);
    assert(output_choice(6) == (custom_output.w ? 6 : 0));
    // (each shape's sizes from smallest to largest, by width then height; 16:9: 1920x1080, 2048x1152, 2560x1440, 3840x2160,
    // 5120x2880; 32:9: 5120x1440 alone; the player's own in its place among its shape's. Each step goes to the next of its
    // shape, and stops at the ends)
    const auto in_order = [](const std::string& shape) {
        std::vector<int> order;
        for (int id : {1, 0, 2, 3, 4, 5, 6})
            if (output_choice(id) == id && display_modes::ratio_name(size_of(output_at(id))) == shape) order.push_back(id);
        std::sort(order.begin(), order.end(), [](int a, int b) {
            const Out x = output_at(a), y = output_at(b);
            return x.w != y.w ? x.w < y.w : x.h < y.h;
        });
        return order;
    };
    for (const auto& shape : output_shapes()) {
        opts.ultrawide = aspect_index(shape.name);
        const std::vector<int> order = in_order(shape.name);
        const int n = (int)order.size();
        assert(n >= 1);
        for (int i = 0; i < n; i++) {
            assert(step_output_choice(order[i], -1) == order[i ? i - 1 : 0]);
            assert(step_output_choice(order[i], 1) == order[i + 1 < n ? i + 1 : i]);
        }
    }
    if (!custom_output.w) {
        opts.ultrawide = aspect_index("16:9");
        assert(step_output_choice(2, 1) == 3 && step_output_choice(3, 1) == 5 && step_output_choice(5, 1) == 5);   // (4K, 5K)
        opts.ultrawide = aspect_index("32:9");
        assert(step_output_choice(4, 1) == 4 && step_output_choice(4, -1) == 4);   // (5120x1440: 32:9, a shape of its own)
        // (the Aspect ratio row: 16:9 and 32:9; choosing a shape takes the size chosen when it has it, else the screen's own
        // size, else the largest)
        const std::vector<display_modes::Shape> shapes = output_shapes();
        assert(shapes.size() == 2 && shapes[0].name == "16:9" && shapes[1].name == "32:9");
        assert(output_shape_of(0) == 0 && output_shape_of(1) == 0 && output_shape_of(4) == 1 && output_shape_of(5) == 0);
        assert((aspect_window_value() < 0 ? aspect_last() == 1 : aspect_last() == 2 && aspect_shape(2) == "Window") && aspect_shape(0) == "16:9" && aspect_shape(1) == "32:9");
        assert(aspect_of_choice(1, 1) == 0 && aspect_for_choice(4) == 1);
        const int was = opts.output_res, was_aspect = opts.ultrawide;
        opts.output_res = 4;
        screen_w = 2560, screen_h = 1440;
        assert(strcmp(tx_ultrawide(0), "16:9 (monitor's)") == 0);
        assert(output_for_aspect(0) == 2 && output_for_aspect(1) == 4);
        screen_w = 5120, screen_h = 1440;
        assert(strcmp(tx_ultrawide(1), "32:9 (monitor's)") == 0);
        opts.ultrawide = aspect_index("16:9");
        assert(aspect_of_choice(1, 1) == 0 && step_output_choice(1, 1) == 0);
        assert(strcmp(tx_output_res(2), "2560x1440") == 0);
        const int new_modes = custom_index() + 1;
        output_extras.insert(output_extras.end(), {{3440, 1440}, {1600, 1200}});
        assert(last_choice() == new_modes + 1 && output_choice_of(3440, 1440) == new_modes);
        assert((aspect_window_value() < 0 ? aspect_last() == 3 : aspect_last() == 4 && aspect_shape(4) == "Window") && aspect_shape(0) == "4:3" && aspect_shape(2) == "21:9" && aspect_shape(3) == "32:9");
        assert(output_for_aspect(0) == new_modes + 1 && output_for_aspect(2) == new_modes);
        // A stale ultrawide resolution or startup ID cannot leak into the 16:9 list.
        const int flat = aspect_index("16:9");
        opts.ultrawide = flat;
        for (int wide : {4, new_modes})
            for (int dir : {-1, 1})
                assert(output_shape_of(step_output_choice(wide, dir)) == flat);
        aspect_started = flat;
        output_started = new_modes;
        assert(output_shape_of(output_for_aspect(flat)) == flat);
        aspect_started = -1;
        output_started = 0;
        assert(aspect_of_choice(new_modes, 0) == 2 && aspect_of_choice(new_modes + 1, 0) == 0);
        output_extras.clear();
        screen_w = screen_h = host_w = host_h = 0;
        opts.output_res = was, opts.ultrawide = was_aspect;
    } else {
        const int index = output_shape_of(6);
        const std::string shape = display_modes::ratio_name(size_of(custom_output));
        if (shape == "16:9" || hos_wonder_native_aspect(custom_output.w, custom_output.h))
            assert(index >= 0 && output_shapes()[index].name == shape);
        else assert(std::none_of(output_shapes().begin(), output_shapes().end(),
                                 [&](const auto& entry) { return entry.name == shape; }));
    }
    assert(strcmp(tx_output_res(opts.output_res), argv[4]) == 0);
    // (what the menu saves: the size, which both sides read back as the same choice)
    const Out o = output_at(opts.output_res);
    char saved[32];
    snprintf(saved, sizeof saved, "%ux%u", o.w, o.h);
    assert(strcmp(saved, argv[6]) == 0);
    uint32_t sw = 0, sh = 0;
    assert(hos_output_parse(saved, &sw, &sh) == (opts.output_res != 0));
    if (opts.output_res) assert(sw == o.w && sh == o.h);
    assert(parse_output(saved) == opts.output_res);
    unsigned scene_w, scene_h;
    game_size(1.0f, scene_w, scene_h);
    unsigned fitted_w = mode ? w : 2048, fitted_h = mode ? h : 1152;
    hos_wonder_wide_fit(&fitted_w, &fitted_h);
    assert(hos_wonder_frame_size(0) == (mode ? w : 2048));
    assert(hos_wonder_frame_size(1) == (mode ? h : 1152));
    assert(scene_w == (opts.handheld ? 1536 : fitted_w));
    assert(scene_h == (opts.handheld ? 864 : fitted_h));
    if (mode == 1) assert(strcmp(tx_resolution(2), "75% (1440x810)") == 0);
    if (mode == 1) {   // (DLSS at 1080p: its modes' render sizes, each a twelfth of the output, exact; DLAA the full size)
        up_now = ur::DLSS;
        // (each stop with its render size)
        assert(strcmp(tx_resolution(3), "Quality 67% (1280x720)") == 0 &&
               strcmp(tx_resolution(6), "Ultra Performance 33% (640x360)") == 0);
        assert(strcmp(tx_resolution(9), "92% (1760x990)") == 0 && strcmp(tx_resolution(7), "Performance 50% (960x540)") == 0);
        const unsigned want[][3] = {{3, 1280, 720}, {5, 1120, 630}, {4, 960, 540}, {6, 640, 360}};
        for (const auto& m : want) {
            game_size(ur::percent(m[0]) / 100.0f, scene_w, scene_h);
            assert(scene_w == m[1] && scene_h == m[2] && scene_w * 1080 == scene_h * 1920);
        }
        up_now = ur::DLAA;
        assert(strcmp(tx_resolution(1), "Native (DLAA, 1920x1080)") == 0);
        up_now = ur::GAME;
    }
    if (custom_output.w == 1360 && custom_output.h == 768) {   // (a 1366x768 screen: 1360x768, each side down to 8, is its own)
        screen_w = 1366, screen_h = 768;
        assert(strcmp(tx_output_res(6), "1360x768 (native)") == 0);
        screen_w = screen_h = 0;
    }
}
'''
    # (saved, handheld, HOS_OUTPUT_RES, the menu's choice, the size, its label, the pool for 305 MB, what the menu saves)
    cases = (
        ("0", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (the numbers saved before)
        ("1", 0, None, 2, 2560, 1440, "2560x1440", 512, "2560x1440"),
        ("2", 0, None, 3, 3840, 2160, "3840x2160", 687, "3840x2160"),
        ("3", 0, None, 1, 1920, 1080, "1920x1080", 512, "1920x1080"),
        ("4", 0, None, 4, 5120, 1440, "5120x1440", 610, "5120x1440"),
        ("5", 0, None, 5, 5120, 2880, "3840x2160", 900, "5120x2880"),   # (Wonder startup-pool cap)
        ("6", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        ("1", 0, "3", 1, 1920, 1080, "1920x1080", 512, "1920x1080"),
        ("3", 1, "3", 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (handheld: the game's own)
        ("4", 1, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        ("2048x1152", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (sizes)
        ("1920x1080", 0, None, 1, 1920, 1080, "1920x1080", 512, "1920x1080"),
        ("3840x2160", 0, None, 3, 3840, 2160, "3840x2160", 687, "3840x2160"),
        ("5120X1440", 0, None, 4, 5120, 1440, "5120x1440", 610, "5120x1440"),
        ("5120x2880", 0, None, 5, 5120, 2880, "3840x2160", 900, "5120x2880"),
        ("3440x1440", 0, None, 6, 3440, 1440, "3440x1440", 512, "3440x1440"),   # (the player's own)
        ("1366x768", 0, None, 6, 1360, 768, "1360x768", 512, "1360x768"),   # (a multiple of 8, rounded down)
        ("5120x2160", 0, None, 6, 5120, 2160, "4416x1864", 900, "5120x2160"),   # (between the two 5120s)
        ("0", 0, "5120x2880", 5, 5120, 2880, "3840x2160", 900, "5120x2880"),
        ("2560x1080", 0, None, 6, 2560, 1080, "2560x1080", 512, "2560x1080"),   # (2560 wide, not 1440 high)
        ("2560x1600", 0, None, 6, 2560, 1600, "2560x1600", 512, "2560x1600"),
        ("320x200", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (out of range: the game's own)
        ("9999x9999", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        ("7680x4320", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (more than 5120x2880's pixels)
        ("6144x2560", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        ("640x4320", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (narrower than 5:4)
        ("5760x1080", 0, None, 6, 5760, 1080, "5760x1080", 515, "5760x1080"),
        ("7680x1440", 0, None, 6, 7680, 1440, "6528x1224", 900, "7680x1440"),   # (Wonder startup-pool cap)
        ("7688x1440", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (wider than 48:9)
        ("3840 x 2160", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (not a size)
        ("abc", 0, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        ("5120x2880", 1, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),
        (None, 0, None, 2, 2560, 1440, "2560x1440", 512, "2560x1440"),   # (none chosen, a new install: the game's 2560x1440)
        (None, 1, None, 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (handheld: its own, as before)
        (None, 0, "2048x1152", 0, 2560, 1440, "2048x1152 (reduced)", 512, "2048x1152"),   # (the reduced size, asked for)
    )
    # (none chosen, a new install: the game's 2560x1440, or the screen's own size where that has fewer pixels, host and menu alike)
    for need, where, text in (("hos_output_default(", "host/nn_applet.c output_mode", host[host.index("static int output_mode(void)"):]),
                              ("hos_output_default(", "vk_menu.cpp menu_init", menu[menu.index("void menu_init() {"):])):
        if need not in text[:text.index("\n}\n")]:
            raise SystemExit(where + ": an Output resolution none chose does not follow hos_output_default")
    init = menu[menu.index("void menu_init() {"):]
    if not init.index("hos_output_default(") < init.index("restart_init();"):
        raise SystemExit("menu_init: the screen's size is taken after restart_init: the first close would ask to restart")
    rule = r'''
#include <cassert>
#include <cstdio>
#include "host/hos_wide_size.h"
int main() {
    uint32_t w = 1, h = 1;
    const auto is = [&](uint32_t sw, uint32_t sh, uint32_t ew, uint32_t eh) {
        hos_output_default(sw, sh, &w, &h);
        return w == ew && h == eh;
    };
    assert(is(1280, 800, 1280, 800));     // (a Steam Deck)
    assert(is(1920, 1080, 1920, 1080));   // (1080p: fewer pixels than 2560x1440)
    assert(is(1366, 768, 1360, 768));     // (a multiple of 8)
    assert(is(1920, 1200, 1920, 1200));   // (16:10 at 1200)
    assert(is(2560, 1080, 2560, 1080));   // (21:9 at 1080: fewer pixels still)
    assert(is(2048, 1152, 2048, 1152));   // (which both sides read as the game's own reduced size: output_mode, output_choice_of)
    assert(is(2560, 1440, 2560, 1440));   // (the game's picture)
    assert(is(3840, 2160, 2560, 1440));   // (larger: the game's picture, not the screen's)
    assert(is(3440, 1440, 2560, 1440));   // (21:9 at 1440: more pixels; the Aspect ratio widens the game's)
    assert(is(0, 0, 2560, 1440));         // (not known)
    assert(is(800, 1280, 2560, 1440));    // (portrait: no size the game takes)
    std::printf("the Output resolution none chose: the game's 2560x1440, the screen's below it\n");
}
'''
    with tempfile.TemporaryDirectory(prefix="output-default-") as tmp:
        source, exe = Path(tmp) / "rule.cpp", Path(tmp) / "rule.exe"
        source.write_text(rule, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-include", ENV_ON_H, "-I", str(ROOT), str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    with tempfile.TemporaryDirectory(prefix="output-resolution-") as tmp:
        work = Path(tmp)
        source, exe = work / "fixture.cpp", work / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-include", ENV_ON_H, "-I", str(ROOT), str(source), "-o", str(exe)], check=True)
        for saved, handheld, override, mode, w, h, label, pool, writes in cases:
            (work / "longshot_options.ini").write_text(   # (saved None: no output_res= line, a new install)
                ("" if saved is None else f"output_res={saved}\n") + f"handheld_profile={handheld}\n", encoding="ascii")
            env = os.environ.copy()
            for key in ("HOS_OUTPUT_RES", "HOS_HANDHELD", "HOS_RT_POOL_MB"):
                env.pop(key, None)
            if override is not None:
                env["HOS_OUTPUT_RES"] = override
            subprocess.run([str(exe), str(mode), str(w), str(h), label, str(pool), writes], cwd=work, env=env, check=True)
    print("PASS: output sizes and the numbers saved before, sizes of the player's own, menu order, what the menu saves, 1080p "
          "override, handheld, render-target budgets and DLSS sizes at 1080p")


if __name__ == "__main__":
    main()
