// (private live-size spike) Wonder's menu plan: a pure function of the window's size in pixels. The game lays its menus out
// on a 1920 x 1080 unit canvas; the renderer fits that canvas, centred, in the window (vk_draw.cpp wonder_ui_scale). The
// plan says where the chrome goes in the window around it:
//   - the header group (its bar with the title) docks to the window's top edge, the footer group (its bar with the button
//     prompts) to the bottom edge; the prompts also dock to the right edge. Groups move whole.
//   - when two fitted pause canvases fit vertically, put controls above course details; otherwise retain the source split.
// At 16:9 every offset is 0 and the pause screen does not split: identity.
// The renderer calls it (vk_draw.cpp); the offline render calls the same header (nx2/wonder_plan_render.cpp).
#pragma once
#include <algorithm>

namespace wonder_plan {

constexpr float kLayoutW = 1920.0f, kLayoutH = 1080.0f;   // (the game's layout canvas, units)
constexpr float kPausePanelUnits = 668.0f;   // (the pause screen's left panel: the game's quad, 668 x 1080 units from the left edge)
constexpr float kPausePanelShare = 0.6f;     // (the panel's largest share of the window's width)
constexpr float kPauseSplitUnits = kPausePanelUnits - kLayoutW / 2;   // (-292: the panel's right edge, layout x)

struct Plan {
    float k = 1;           // pixels per layout unit, the fitted canvas's
    float ex = 0, ey = 0;  // pixels of window past the fitted canvas, each side
    float header_dy = 0;   // the header group's move, pixels (up: negative)
    float footer_dy = 0;   // the footer group's (down)
    float prompts_dx = 0;  // the footer's prompts' (right)
    float map_hud_x = 0, map_hud_y = 0; // top-left origin for the whole map counter group at fitted scale
    bool pause_stack = false;
    float pause_k = 1;          // control scale, at least the fitted scale
    float pause_top = 0;        // controls and their backdrop share the same origin
    float pause_detail_top = 0; // details keep the fitted scale
};

inline Plan plan(float w, float h) {
    Plan p;
    p.k = std::min(w / kLayoutW, h / kLayoutH);
    p.ex = 0.5f * (w - kLayoutW * p.k);
    p.ey = 0.5f * (h - kLayoutH * p.k);
    p.header_dy = -p.ey;
    p.footer_dy = p.ey;
    p.prompts_dx = p.ex;
    p.pause_top = p.pause_detail_top = p.ey;
    p.pause_k = p.k;
    const float fitted_h = kLayoutH * p.k;
    const float room = h - fitted_h;
    p.pause_stack = room >= fitted_h;
    if (p.pause_stack) {
        const float width_cap = kPausePanelShare * w / kPausePanelUnits;
        p.pause_k = std::min(width_cap, room / kLayoutH);
        p.pause_top = 0.5f * (room - kLayoutH * p.pause_k);
        p.pause_detail_top = room;
    }
    return p;
}

// Visible footprint of the full world-map course card, including its rotating title,
// preview, difficulty and badges (from the native quad and sampled asset bounds).
constexpr float kMapCardHalfW = 240.0f, kMapCardHalfH = 170.0f;
constexpr float kMapCardMaxWidth = 0.35f;
struct Card { float k, x, y; };
inline Card map_card(float w, float h, Plan p, float cx, float cy) {
    const float k = std::min(p.k, w * kMapCardMaxWidth / (2.0f * kMapCardHalfW));
    const float anchor_x = 0.5f * w + cx * p.k;
    const float anchor_y = 0.5f * h - cy * p.k;
    const float x = std::clamp(anchor_x, kMapCardHalfW * k, w - kMapCardHalfW * k);
    const float y = std::clamp(anchor_y, kMapCardHalfH * k, h - kMapCardHalfH * k);
    return {k, x - (cx + kLayoutW / 2.0f) * k, y - (kLayoutH / 2.0f - cy) * k};
}

}  // namespace wonder_plan
