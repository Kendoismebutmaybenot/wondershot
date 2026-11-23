// The Insert menu's HDR rows (#1633): the Graphics tab's HDR section, after Screen. (Wonder build) Longshot's Expanded / Native /
// tone mapper rows are replaced by the RenoDX-style HDR ported from SuperWonders (PR #116): HDR On is stored as 2 (Native) so
// the host and present plumbing keyed on it stay as they are; the game's tone mapper 9c39b1dd1e1bad88 is replaced from
// shader_overrides/hdr/ (tools/renodx_wonder_sw2.py) and the present pass (hdr_encode.comp mode 2) maps its extended picture. Their keys in
// longshot_options.ini are as they were in vk_menu.cpp's table (tests/test_menu_ini_keys.py keeps them).
#include "menu_module.h"

#include <cstdio>
#include <string>

namespace mkwvk {

const char* tx_hdr(int v) { return v ? "On" : "Off"; }

namespace {
// (as a printf format: the translations match a value's text against it)
std::string nits(int v) {
    char b[24];
    snprintf(b, sizeof b, "%d nits", v);
    return b;
}
} // namespace

MENU_MODULE(hdr) {
    const auto on = [] { return opts.hdr != 0; };
    menu::tab("graphics")
        .heading("hdr", "HDR", menu::after("screen"))
        .row({.key = "hdr", .label = "HDR",
              .help = "HDR10 out on an HDR display (Windows: Use HDR on in the display settings): the game's highlights past "
                      "its SDR white, RenoDX style. Turning it on or off applies after a restart.",
              .value = &opts.hdr, .lo = 0, .hi = 2, .preset_exempt = true, .text = [](int v) { return std::string(tx_hdr(v)); },
              .step_fn = [](int v, int) { return v ? 0 : 2; }})
        .row({.key = "hdr_paper_white", .label = "HDR paper white",
              .help = "How bright the picture's white (and the UI) is. Around 200 for a normal room; higher in a bright one.",
              .value = &opts.hdr_white, .lo = 80, .hi = 400, .step = 10, .preset_exempt = true, .shown = on, .text = nits})
        .row({.key = "hdr_peak_brightness", .label = "HDR peak brightness",
              .help = "The brightest highlights: set it to your display's peak brightness.",
              .value = &opts.hdr_peak, .lo = 400, .hi = 4000, .step = 100, .preset_exempt = true, .shown = on, .text = nits})
        .row({.key = "hdr_highlights", .label = "Highlights",
              .help = "How much brighter than paper white the scene's highlights get. 0% the SDR picture.",
              .value = &opts.hdr_highlights, .lo = 0, .hi = 500, .step = 10, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_highlight_start", .label = "Highlight start",
              .help = "Where the highlights start to rise, in percent of the SDR white point: lower starts them earlier.",
              .value = &opts.hdr_highlight_start, .lo = 50, .hi = 150, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_sdr_gamma", .label = "SDR gamma",
              .help = "How the game's picture under paper white is decoded: 2.2 as most PC monitors show SDR (the default), 2.4 "
                      "darker, sRGB the piecewise curve.",
              .value = &opts.hdr_sdr_gamma, .lo = 0, .hi = 2, .choices = {"sRGB", "2.2", "2.4"}, .preset_exempt = true,
              .shown = on})
        .row({.key = "hdr_exposure", .label = "Exposure",
              .help = "The scene's brightness before the game's tone curve.",
              .value = &opts.hdr_exposure, .lo = 25, .hi = 400, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_contrast", .label = "Contrast",
              .help = "The scene's contrast around mid grey.",
              .value = &opts.hdr_contrast, .lo = 50, .hi = 200, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_shadows", .label = "Shadows",
              .help = "Above 100% lifts the shadows, below lowers them; mid grey and above stay.",
              .value = &opts.hdr_shadows, .lo = 0, .hi = 200, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_saturation", .label = "Saturation",
              .help = "The scene's colourfulness (OKLab chroma).",
              .value = &opts.hdr_saturation, .lo = 0, .hi = 200, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent})
        .row({.key = "hdr_highlight_saturation", .label = "Highlight saturation",
              .help = "The colourfulness of the bright parts alone.",
              .value = &opts.hdr_highlight_saturation, .lo = 0, .hi = 300, .step = 5, .preset_exempt = true, .shown = on,
              .text = menu_text::percent});
}

} // namespace mkwvk
