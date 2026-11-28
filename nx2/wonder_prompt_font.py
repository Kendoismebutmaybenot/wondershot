"""(Wondershot) The button prompts' font: a stand-in for the Switch's system extension font (nn::pl built-in font type 5,
nintendo_ext_003), which Wonder draws every button icon in a text from. host/nn_applet.c serves it for that type and
host/prompts.c (the Wonder part) points each icon at the controller in use, as Longshot does with OoT's own icon font.

    wonder_prompt_font.py --out <game folder>/prompts/wonder_ext.ttf [--base HOST.ttf] [--preview PNG]

The icons are drawn here (SuperWonders' tools/fonts/make_button_font.py, MIT, below); only the letters cut out of them come from
the host font (--base, default Windows' Segoe UI Bold on this PC). The output therefore holds that font's letter outlines: it is
made on the player's PC, into the game folder, and never committed or shipped.

The cmap, as host/prompts.c reads it (Longshot's layout, nx2/prompt_assets.py):
  - each face's icon of each pad input at PAD_BASE + FACE_CODES x HOS_PROMPT_* + HOS_PAD_* (the keyboard face: the Switch's);
  - each key's icon at KEY_BASE + its Windows key code (the keyboard face points the buttons at the first key bound);
  - each code point Wonder's texts use (WONDER below) in a format 4 segment of its own, by idDelta alone: host/prompts.c points
    it at the face's icon of the pad input bound to its Switch button. Built pointing at the Switch face's default icons.

What each code point is was read from the system font (on this PC only, never kept): E0E0.. the filled A B X Y L R ZL ZR SL SR,
E0EA the four face buttons, E0EB..E0EE the d-pad's up down left right, E0EF E0F0 Plus Minus, E0AB..E0AE the face button at the
right, bottom, top, left (A B X Y on a Switch), E0A0.. the same outlined, E090..E097 arrows (right left up down, then the
diagonals), E100 a stick, E101 E102 the L and R sticks.
"""
# ---- SuperWonders' icon drawing (tools/fonts/make_button_font.py), with the home, keys and face-buttons icons added here:
# MIT License
#
# Copyright (c) 2026 BelmanteGu
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
import argparse
import io
import math
import os
import struct
import sys

PAD_BASE = 0xF700   # (host/prompts.c)
FACE_CODES = 32
FACES = ["switch", "xbox", "ps4", "ps5", "steamdeck", "keyboard"]   # (HOS_PROMPT_*)
KEY_BASE = PAD_BASE + FACE_CODES * len(FACES)
# HOS_PAD_* (gpu/vk/vk_api.h), up to the triggers
PADS = ["south", "east", "west", "north", "back", "guide", "start", "lstick", "rstick", "lshoulder", "rshoulder", "up", "down", "left",
        "right", "ltrigger", "rtrigger"]
SW = ["a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus", "minus", "left", "up", "right", "down"]   # (HOS_SW_*)
# longshot's default pad input for each Switch button (host/nn_hid.c, host/prompts.c switch_pad): the icon built in
DEFAULT = ["east", "south", "north", "west", "lstick", "rstick", "lshoulder", "rshoulder", "ltrigger", "rtrigger", "start", "back",
           "left", "up", "right", "down"]

# Wonder's code points that follow the controller: code -> ("sw", Switch button) its pad input's icon, or ("pad", pad input) the
# face's icon of that input whatever it is bound to (the sticks: moving them is not a binding). host/prompts.c wonder_code[]
WONDER = {
    0xE0E0: ("sw", "a"), 0xE0E1: ("sw", "b"), 0xE0E2: ("sw", "x"), 0xE0E3: ("sw", "y"), 0xE0E4: ("sw", "l"), 0xE0E5: ("sw", "r"),
    0xE0E6: ("sw", "zl"), 0xE0E7: ("sw", "zr"), 0xE0EF: ("sw", "plus"), 0xE0F0: ("sw", "minus"),
    0xE0EB: ("sw", "up"), 0xE0EC: ("sw", "down"), 0xE0ED: ("sw", "left"), 0xE0EE: ("sw", "right"),
    0xE0AB: ("sw", "a"), 0xE0AC: ("sw", "b"), 0xE0AD: ("sw", "x"), 0xE0AE: ("sw", "y"),
    0xE0A0: ("sw", "a"), 0xE0A1: ("sw", "b"), 0xE0A2: ("sw", "x"), 0xE0A3: ("sw", "y"), 0xE0A4: ("sw", "l"), 0xE0A5: ("sw", "r"),
    0xE0A6: ("sw", "zl"), 0xE0A7: ("sw", "zr"), 0xE0B3: ("sw", "plus"), 0xE0B4: ("sw", "minus"),
    0xE0AF: ("sw", "up"), 0xE0B0: ("sw", "down"), 0xE0B1: ("sw", "left"), 0xE0B2: ("sw", "right"),
    0xE0F1: ("sw", "plus"), 0xE0F2: ("sw", "minus"),
    0xE101: ("pad", "lstick"), 0xE102: ("pad", "rstick"), 0xE0C1: ("pad", "lstick"), 0xE0C2: ("pad", "rstick"),
}
# the ones the same for every controller: code -> (kind, argument)
STATIC = {
    0xE0E8: ("rail", "SL"), 0xE0E9: ("rail", "SR"), 0xE0A8: ("rail", "SL"), 0xE0A9: ("rail", "SR"),
    0xE0EA: ("diamond", None), 0xE0AA: ("diamond", None), 0xE100: ("stick", ""), 0xE0C0: ("stick", ""),
    0xE090: ("arrow", 0), 0xE091: ("arrow", 180), 0xE092: ("arrow", 90), 0xE093: ("arrow", 270),
    0xE094: ("arrow", 45), 0xE095: ("arrow", 315), 0xE096: ("arrow", 225), 0xE097: ("arrow", 135),
    0xE0F4: ("home", None), 0xE0B9: ("home", None), 0xE145: ("triangle", 180), 0xE146: ("triangle", 0),
}

_DPAD = [("dpad", "up"), ("dpad", "down"), ("dpad", "left"), ("dpad", "right")]


def _face(south, east, west, north, back, start, ls, rs, lb, rb, lt, rt):
    """a face's icons in PADS order"""
    return [south, east, west, north, back, ("home", None), start, ls, rs, lb, rb] + _DPAD + [lt, rt]


_SWITCH = _face(("circle_letter", "B"), ("circle_letter", "A"), ("circle_letter", "Y"), ("circle_letter", "X"),
                ("circle_sign", "-"), ("circle_sign", "+"), ("stick", "L"), ("stick", "R"), ("shoulder", "L"), ("shoulder", "R"),
                ("trigger", "ZL"), ("trigger", "ZR"))
_XBOX = _face(("circle_letter", "A"), ("circle_letter", "B"), ("circle_letter", "X"), ("circle_letter", "Y"), ("xbox_view", ""),
              ("xbox_menu", ""), ("stick", "L"), ("stick", "R"), ("shoulder", "LB"), ("shoulder", "RB"), ("trigger", "LT"),
              ("trigger", "RT"))
_PS = lambda back: _face(("ps_face", "cross"), ("ps_face", "circle"), ("ps_face", "square"), ("ps_face", "triangle"),
                         ("ps_menu", back), ("ps_menu", "options"), ("stick", "L3"), ("stick", "R3"), ("shoulder", "L1"),
                         ("shoulder", "R1"), ("trigger", "L2"), ("trigger", "R2"))
_DECK = _face(("circle_letter", "A"), ("circle_letter", "B"), ("circle_letter", "X"), ("circle_letter", "Y"), ("xbox_view", ""),
              ("xbox_menu", ""), ("stick", "L3"), ("stick", "R3"), ("shoulder", "L1"), ("shoulder", "R1"), ("trigger", "L2"),
              ("trigger", "R2"))
FACE_ICONS = {"switch": _SWITCH, "xbox": _XBOX, "ps4": _PS("create"), "ps5": _PS("create"), "steamdeck": _DECK,
              "keyboard": _SWITCH}

# the keys' labels by Windows key code (an arrow key: its arrow)
KEYS = {0x01: "M1", 0x02: "M2", 0x04: "M3", 0x05: "M4", 0x06: "M5", 0x08: "Bksp", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
        0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x14: "Caps", 0x1B: "Esc", 0x20: "Space", 0x21: "PgUp", 0x22: "PgDn",
        0x23: "End", 0x24: "Home", 0x25: 180, 0x26: 90, 0x27: 0, 0x28: 270, 0x2C: "PrtSc", 0x2D: "Ins", 0x2E: "Del",
        0x5B: "Win", 0x5C: "Win", 0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/", 0x90: "NumLk", 0x91: "ScrLk",
        0xA0: "Shift", 0xA1: "Shift", 0xA2: "Ctrl", 0xA3: "Ctrl", 0xA4: "Alt", 0xA5: "Alt", 0xBA: ";", 0xBB: "=", 0xBC: ",",
        0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
KEYS.update({0x30 + i: str(i) for i in range(10)})
KEYS.update({0x60 + i: f"Num{i}" for i in range(10)})
KEYS.update({0x41 + i: chr(0x41 + i) for i in range(26)})
KEYS.update({0x70 + i: f"F{i + 1}" for i in range(12)})

K = 0.5522847498  # cubic Bezier circle constant


class Builder:
    def __init__(self, font):
        from fontTools.pens.boundsPen import BoundsPen
        self.BoundsPen = BoundsPen
        self.font = font
        self.upm = font["head"].unitsPerEm
        self.cmap = font.getBestCmap()
        self.gs = font.getGlyphSet()
        cap = self._bounds(self.cmap[ord("H")])
        self.cap = cap[3] if cap else 0.716 * self.upm
        # icon box: a bit taller than the capitals, dipping slightly below the baseline
        pad = 0.06 * self.upm
        self.bottom = -pad
        self.top = self.cap + pad
        self.size = self.top - self.bottom
        self.cy = (self.top + self.bottom) / 2
        self.side = 0.07 * self.upm  # side bearing

    def _bounds(self, gname):
        bp = self.BoundsPen(self.gs)
        self.gs[gname].draw(bp)
        return bp.bounds

    # --- primitive shapes (drawn clockwise = filled in TrueType; hole=True cuts one out) ---

    def circle(self, pen, cx, cy, r, hole=False):
        from fontTools.pens.reverseContourPen import ReverseContourPen
        if hole:
            pen = ReverseContourPen(pen)
        k = K * r
        pen.moveTo((cx + r, cy))
        pen.curveTo((cx + r, cy - k), (cx + k, cy - r), (cx, cy - r))
        pen.curveTo((cx - k, cy - r), (cx - r, cy - k), (cx - r, cy))
        pen.curveTo((cx - r, cy + k), (cx - k, cy + r), (cx, cy + r))
        pen.curveTo((cx + k, cy + r), (cx + r, cy + k), (cx + r, cy))
        pen.closePath()

    def rrect(self, pen, x0, y0, x1, y1, r, hole=False):
        from fontTools.pens.reverseContourPen import ReverseContourPen
        if hole:
            pen = ReverseContourPen(pen)
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        k = K * r
        pen.moveTo((x0, y0 + r))
        pen.lineTo((x0, y1 - r))
        pen.curveTo((x0, y1 - r + k), (x0 + r - k, y1), (x0 + r, y1))
        pen.lineTo((x1 - r, y1))
        pen.curveTo((x1 - r + k, y1), (x1, y1 - r + k), (x1, y1 - r))
        pen.lineTo((x1, y0 + r))
        pen.curveTo((x1, y0 + r - k), (x1 - r + k, y0), (x1 - r, y0))
        pen.lineTo((x0 + r, y0))
        pen.curveTo((x0 + r - k, y0), (x0, y0 + r - k), (x0, y0 + r))
        pen.closePath()

    def poly(self, pen, pts, hole=False):
        """pts go clockwise (filled); hole=True cuts them out instead."""
        from fontTools.pens.reverseContourPen import ReverseContourPen
        if hole:
            pen = ReverseContourPen(pen)
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()

    def text(self, pen, s, cx, cy, cap_h, hole=True):
        """Draw the host font's outlines for s, centred on (cx, cy), scaled so capitals are cap_h tall."""
        from fontTools.pens.reverseContourPen import ReverseContourPen
        from fontTools.pens.transformPen import TransformPen
        scale = cap_h / self.cap
        track = -0.02 * self.upm
        names = [self.cmap[ord(ch)] for ch in s]
        widths = [self.font["hmtx"][n][0] for n in names]
        total = sum(widths) + track * (len(s) - 1)
        x = -total / 2
        for n, w in zip(names, widths):
            t = (scale, 0, 0, scale, cx + x * scale, cy - self.cap * scale / 2)
            target = ReverseContourPen(pen) if hole else pen
            self.gs[n].draw(TransformPen(target, t))
            x += w + track

    def text_width(self, s, cap_h):
        scale = cap_h / self.cap
        return scale * (sum(self.font["hmtx"][self.cmap[ord(ch)]][0] for ch in s) - 0.02 * self.upm * (len(s) - 1))

    # --- icons ---

    def build(self, kind, arg):
        """Returns (TTGlyph, advance)."""
        from fontTools.pens.cu2quPen import Cu2QuPen
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        tt = TTGlyphPen(None)
        pen = Cu2QuPen(tt, max_err=1.0, reverse_direction=False)
        S, cy, side = self.size, self.cy, self.side
        if kind == "circle_letter":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            self.text(pen, arg, cx, cy, 0.58 * S)
            adv = 2 * r + 2 * side
        elif kind == "circle_sign":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            a, t = 0.30 * S, 0.075 * S  # half arm length, half thickness
            if arg == "+":
                pts = [(cx - t, cy + a), (cx + t, cy + a), (cx + t, cy + t), (cx + a, cy + t), (cx + a, cy - t),
                       (cx + t, cy - t), (cx + t, cy - a), (cx - t, cy - a), (cx - t, cy - t), (cx - a, cy - t),
                       (cx - a, cy + t), (cx - t, cy + t)]
            else:
                pts = [(cx - a, cy + t), (cx + a, cy + t), (cx + a, cy - t), (cx - a, cy - t)]
            self.poly(pen, pts, hole=True)
            adv = 2 * r + 2 * side
        elif kind in ("shoulder", "trigger", "rail"):
            h = {"shoulder": 0.78, "trigger": 0.78, "rail": 0.62}[kind] * S
            cap_h = 0.50 * S if kind != "rail" else 0.40 * S
            tw = self.text_width(arg, cap_h)
            w = max(tw + 0.42 * S, {"shoulder": 1.2, "trigger": 1.45, "rail": 1.2}[kind] * S)
            x0, y0 = side, cy - h / 2
            x1, y1 = side + w, cy + h / 2
            if kind == "shoulder":
                self.rrect(pen, x0, y0, x1, y1, 0.34 * h)
            elif kind == "trigger":
                self.rrect(pen, x0, y0, x1, y1, 0.18 * h)
            else:
                self.rrect(pen, x0, y0, x1, y1, 0.5 * h)
            self.text(pen, arg, (x0 + x1) / 2, cy, cap_h)
            adv = w + 2 * side
        elif kind == "dpad":
            cx = side + S / 2
            a = S / 2           # arm reach
            t = 0.18 * S        # half arm width
            ring = 0.07 * S     # outline thickness

            def cross(a, t):
                return [(cx - t, cy + a), (cx + t, cy + a), (cx + t, cy + t), (cx + a, cy + t), (cx + a, cy - t),
                        (cx + t, cy - t), (cx + t, cy - a), (cx - t, cy - a), (cx - t, cy - t), (cx - a, cy - t),
                        (cx - a, cy + t), (cx - t, cy + t)]

            self.poly(pen, cross(a, t))
            if arg != "all":
                self.poly(pen, cross(a - ring, t - ring), hole=True)
                ang = {"right": 0, "up": 90, "left": 180, "down": 270}[arg]
                arm = [(t * 0.3, t - ring), (a - ring, t - ring), (a - ring, -(t - ring)), (t * 0.3, -(t - ring))]
                self.poly(pen, self._rot(arm, ang, cx, cy))
            else:
                self.circle(pen, cx, cy, 0.09 * S, hole=True)
            adv = S + 2 * side
        elif kind == "stick":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            self.circle(pen, cx, cy, r - 0.08 * S, hole=True)
            ri = 0.33 * S
            self.circle(pen, cx, cy, ri)
            if arg:
                self.text(pen, arg, cx, cy, (0.28 if len(arg) >= 2 else 0.36) * S)
            adv = 2 * r + 2 * side
        elif kind == "ps_face":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            if arg == "cross":
                a, t = 0.28 * S, 0.068 * S
                pts = [(-t, a), (t, a), (t, t), (a, t), (a, -t), (t, -t),
                       (t, -a), (-t, -a), (-t, -t), (-a, -t), (-a, t), (-t, t)]
                self.poly(pen, self._rot(pts, 45, cx, cy), hole=True)
            elif arg == "circle":
                self.circle(pen, cx, cy, 0.29 * S, hole=True)
                self.circle(pen, cx, cy, 0.18 * S, hole=False)
            elif arg == "square":
                def sq(d):
                    return [(cx - d, cy + d), (cx + d, cy + d), (cx + d, cy - d), (cx - d, cy - d)]
                self.poly(pen, sq(0.25 * S), hole=True)
                self.poly(pen, sq(0.15 * S), hole=False)
            elif arg == "triangle":
                tc_y = cy - 0.04 * S
                s32 = math.sqrt(3.0) / 2.0

                def tri(rad):
                    return [(cx, tc_y + rad), (cx + rad * s32, tc_y - 0.5 * rad), (cx - rad * s32, tc_y - 0.5 * rad)]
                self.poly(pen, tri(0.31 * S), hole=True)
                self.poly(pen, tri(0.16 * S), hole=False)
            else:
                raise ValueError(arg)
            adv = 2 * r + 2 * side
        elif kind == "xbox_menu":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            for dy in (0.16 * S, 0.0, -0.16 * S):
                self.rrect(pen, cx - 0.24 * S, cy + dy - 0.042 * S,
                           cx + 0.24 * S, cy + dy + 0.042 * S, 0.042 * S, hole=True)
            adv = 2 * r + 2 * side
        elif kind == "xbox_view":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            st, gap = 0.06 * S, 0.03 * S
            bx0, by0, bx1, by1 = cx - 0.25 * S, cy - 0.06 * S, cx + 0.06 * S, cy + 0.25 * S
            fx0, fy0, fx1, fy1 = cx - 0.06 * S, cy - 0.25 * S, cx + 0.25 * S, cy + 0.06 * S

            def rect_cw(x0, y0, x1, y1):
                return [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
            self.poly(pen, rect_cw(fx0, fy0, fx1, fy1), hole=True)
            self.poly(pen, rect_cw(fx0 + st, fy0 + st, fx1 - st, fy1 - st), hole=False)
            back_l = [
                (bx0, by0), (bx0, by1), (bx1, by1), (bx1, fy1 + gap),
                (bx1 - st, fy1 + gap), (bx1 - st, by1 - st), (bx0 + st, by1 - st),
                (bx0 + st, by0 + st), (fx0 - gap, by0 + st), (fx0 - gap, by0),
            ]
            self.poly(pen, back_l, hole=True)
            adv = 2 * r + 2 * side
        elif kind == "ps_menu":
            w, h = 0.92 * S, 0.64 * S
            x0, y0, x1, y1 = side, cy - h / 2, side + w, cy + h / 2
            cx = side + w / 2
            self.rrect(pen, x0, y0, x1, y1, h / 2)
            if arg == "options":
                for dy in (0.13 * S, 0.0, -0.13 * S):
                    self.rrect(pen, cx - 0.21 * S, cy + dy - 0.036 * S,
                               cx + 0.21 * S, cy + dy + 0.036 * S, 0.036 * S, hole=True)
            elif arg == "create":
                d0, d1, t = 0.11 * S, 0.29 * S, 0.032 * S
                ray = [(d0, t), (d1, t), (d1, -t), (d0, -t)]
                for ang in (56, 90, 124):
                    self.poly(pen, self._rot(ray, ang, cx, cy - 0.14 * S), hole=True)
            else:
                raise ValueError(arg)
            adv = w + 2 * side
        elif kind == "arrow":
            L = 0.80 * S
            cx = side + L / 2
            hl, hw, sw = 0.45 * L, 0.42 * L, 0.13 * L  # head length, head half width, shaft half width
            pts = [(-L / 2, sw), (L / 2 - hl, sw), (L / 2 - hl, hw), (L / 2, 0), (L / 2 - hl, -hw),
                   (L / 2 - hl, -sw), (-L / 2, -sw)]
            self.poly(pen, self._rot(pts, arg, cx, cy))
            adv = L + 2 * side
        elif kind == "triangle":
            L = 0.45 * S
            cx = side + L / 2
            pts = [(-L / 2, 0.55 * L), (L / 2, 0), (-L / 2, -0.55 * L)]  # clockwise, pointing right
            self.poly(pen, self._rot(pts, arg, cx, cy))
            adv = L + 2 * side
        # ---- (Wondershot) added to SuperWonders' set
        elif kind == "home":
            r = S / 2
            cx = side + r
            self.circle(pen, cx, cy, r)
            w, roof, body = 0.22 * S, 0.24 * S, 0.17 * S   # the house cut out: a roof over a box
            base = cy - 0.20 * S
            self.poly(pen, [(cx - w, base), (cx - w, base + body), (cx - w - 0.06 * S, base + body), (cx, base + body + roof),
                            (cx + w + 0.06 * S, base + body), (cx + w, base + body), (cx + w, base)], hole=True)
            adv = 2 * r + 2 * side
        elif kind == "diamond":
            cx = side + S / 2
            d, r = 0.32 * S, 0.17 * S   # the four face buttons
            for dx, dy in ((0, d), (d, 0), (0, -d), (-d, 0)):
                self.circle(pen, cx + dx, cy + dy, r)
            adv = S + 2 * side
        elif kind == "key":
            h = 0.84 * S
            if isinstance(arg, int):   # an arrow key: its arrow cut out
                w = h
            else:
                cap_h = (0.50 if len(arg) <= 2 else 0.36) * S
                w = max(self.text_width(arg, cap_h) + 0.36 * S, h)
            x0, y0, x1, y1 = side, cy - h / 2, side + w, cy + h / 2
            self.rrect(pen, x0, y0, x1, y1, 0.2 * h)
            cx = (x0 + x1) / 2
            if isinstance(arg, int):
                L = 0.55 * h
                hl, hw, sw = 0.45 * L, 0.42 * L, 0.13 * L
                pts = [(-L / 2, sw), (L / 2 - hl, sw), (L / 2 - hl, hw), (L / 2, 0), (L / 2 - hl, -hw),
                       (L / 2 - hl, -sw), (-L / 2, -sw)]
                self.poly(pen, self._rot(pts, arg, cx, cy), hole=True)
            else:
                self.text(pen, arg, cx, cy, cap_h)
            adv = w + 2 * side
        else:
            raise ValueError(kind)
        return tt.glyph(), int(round(adv))

    @staticmethod
    def _rot(pts, deg, cx, cy):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]
# ---- (end of SuperWonders' code)


def cmap4(mapping, single):
    """a cmap table of one format 4 subtable (Unicode BMP, platforms 0 and 3) from {code: glyph id}: runs of codes with
    consecutive glyphs share a segment, each code of `single` has one of its own; every segment by idDelta alone (as
    nx2/prompt_assets.py cmap4: host/prompts.c points a single one at another glyph through its idDelta)"""
    segs = []
    for c in sorted(mapping):
        g = mapping[c]
        if segs and c not in single and segs[-1][1] == c - 1 and segs[-1][1] not in single and (segs[-1][2] + c) & 0xFFFF == g:
            segs[-1][1] = c
        else:
            segs.append([c, c, (g - c) & 0xFFFF])
    segs.append([0xFFFF, 0xFFFF, 1])
    n = len(segs)
    search = 2 * (1 << (n.bit_length() - 1))
    sub = struct.pack(">HHHHHHH", 4, 16 + 8 * n, 0, 2 * n, search, (search // 2).bit_length() - 1, 2 * n - search)
    sub += b"".join(struct.pack(">H", s[1]) for s in segs) + b"\0\0"
    sub += b"".join(struct.pack(">H", s[0]) for s in segs)
    sub += b"".join(struct.pack(">H", s[2]) for s in segs)
    sub += b"\0\0" * n
    return struct.pack(">HHHHIHHI", 0, 2, 0, 3, 20, 3, 1, 20) + sub


def build(base_path):
    """the font's bytes"""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables.DefaultTable import DefaultTable

    font = TTFont(base_path, recalcTimestamp=False)
    if "glyf" not in font:
        sys.exit("base font must have TrueType (glyf) outlines")
    b = Builder(font)
    order = list(font.getGlyphOrder())
    hmtx = font["hmtx"]
    made = {}   # (kind, arg) -> glyph name: one glyph per icon, shared by every code showing it

    def glyph(kind, arg):
        key = (kind, arg)
        if key not in made:
            name = f"wsi{len(made):03d}"
            g, adv = b.build(kind, arg)
            order.append(name)
            font["glyf"][name] = g
            g.recalcBounds(font["glyf"])
            hmtx[name] = (adv, getattr(g, "xMin", 0))
            made[key] = name
        return made[key]

    placed = {}   # code -> glyph name
    for f, face in enumerate(FACES):
        for i, icon in enumerate(FACE_ICONS[face]):
            placed[PAD_BASE + FACE_CODES * f + i] = glyph(*icon)
    for code, label in KEYS.items():
        placed[KEY_BASE + code] = glyph("key", label)
    for code, (how, what) in WONDER.items():   # (the Switch face's default icons, as built)
        pad = DEFAULT[SW.index(what)] if how == "sw" else what
        placed[code] = placed[PAD_BASE + PADS.index(pad)]
    for code, icon in STATIC.items():
        placed[code] = glyph(*icon)
    font.setGlyphOrder(order)
    font["glyf"].glyphOrder = order
    font["maxp"].numGlyphs = len(order)
    if "post" in font:   # (format 2: the names written again from the glyph order, ours included)
        font["post"].formatType = 2.0
        font["post"].extraNames = []
        font["post"].mapping = {}
    for tag in ("hdmx", "LTSH", "DSIG", "VDMX"):
        if tag in font:
            del font[tag]
    raw = io.BytesIO()
    font.save(raw)

    # just the icons (and .notdef, space): the host font's own letters are not kept as glyphs
    opts = subset.Options()
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.name_IDs = ["*"]
    opts.layout_features = []
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "kern", "morx", "feat", "prop", "BASE", "JSTF", "MATH", "STAT", "fvar", "gvar"]
    sub = subset.Subsetter(opts)
    small = TTFont(io.BytesIO(raw.getvalue()), recalcTimestamp=False)
    sub.populate(glyphs=sorted(set(placed.values()) | {"space"}))
    sub.subset(small)
    gid = {n: i for i, n in enumerate(small.getGlyphOrder())}
    mapping = {0x20: gid["space"]}
    mapping.update({c: gid[n] for c, n in placed.items()})
    t = DefaultTable("cmap")
    t.data = cmap4(mapping, set(WONDER))
    small["cmap"] = t
    # Rename the font on every platform; keep copyright and license records intact.
    names = small["name"]
    identity = {1: "Wondershot Prompts", 2: "Regular", 3: "Wondershot Prompts",
                4: "Wondershot Prompts", 6: "WondershotPrompts", 16: "Wondershot Prompts", 17: "Regular",
                18: "Wondershot Prompts", 20: "WondershotPrompts", 21: "Wondershot Prompts", 22: "Regular",
                25: "WondershotPrompts"}
    for record in names.names:
        if record.nameID in identity:
            record.string = identity[record.nameID].encode(record.getEncoding())
    for name_id in (1, 2, 3, 4, 6):
        names.setName(identity[name_id], name_id, 3, 1, 0x409)
    out = io.BytesIO()
    small.save(out)
    return out.getvalue(), placed


def preview(path, png):
    from PIL import Image, ImageDraw, ImageFont
    big = ImageFont.truetype(path, 56)
    lab = ImageFont.truetype(path, 18) if False else ImageFont.load_default()
    rows = [("Wonder", sorted(WONDER) + sorted(STATIC))] + [(face, [PAD_BASE + FACE_CODES * f + i for i in range(len(PADS))])
                                                           for f, face in enumerate(FACES[:5])]
    rows.append(("keys", [KEY_BASE + c for c in (0x41, 0x57, 0x20, 0x10, 0x0D, 0x26, 0x01, 0x70, 0x09, 0x1B)]))
    cw, ch, per = 64, 80, 40
    lines = sum((len(r[1]) + per - 1) // per for r in rows)
    img = Image.new("RGB", (100 + per * cw, lines * ch + 10), "white")
    d = ImageDraw.Draw(img)
    y = 5
    for title, codes in rows:
        for k in range(0, len(codes), per):
            d.text((5, y + 30), title, font=lab, fill="red")
            for i, c in enumerate(codes[k:k + per]):
                d.text((100 + i * cw, y), chr(c), font=big, fill="black")
            y += ch
    img.save(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="the font to write (the game folder's prompts/wonder_ext.ttf)")
    ap.add_argument("--base", default=r"C:\Windows\Fonts\segoeuib.ttf", help="host TrueType font for the icons' letters")
    ap.add_argument("--preview", help="also draw every icon into this PNG (Pillow)")
    a = ap.parse_args()
    data, placed = build(a.base)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(data)
    print(f"wrote {a.out}: {len(set(placed.values()))} icons, {len(placed)} code points, {len(data)} bytes")
    if a.preview:
        preview(a.out, a.preview)


if __name__ == "__main__":
    main()
