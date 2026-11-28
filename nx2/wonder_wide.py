"""Switch 2 Wonder's startup display and scene sizes."""

BUILD_ID = "ec47e6f8846d2a7b6892e2682845c7255f7117ae"
SIZE = "extern uint64_t hos_wonder_wide_size; const uint64_t wide = hos_wonder_wide_size;"
SITES = (
    # Gameplay orthographic span before constructing top/bottom and left/right.
    (0x8043CD40, 0x1E210801, "extern void hos_wonder_tall_span(Ctx *); hos_wonder_tall_span(c);"),
    # The framework's startup arguments, before the constructor copies them.
    (0x80B6A528, 0xD102A3A1, "extern void hos_wonder_wide_display(Ctx *, uint64_t); "
     "hos_wonder_wide_display(c, c->x[1]);"),
    # Full-size color target, before its descriptor and storage are made.
    (0x8068FD3C, 0x52810E04, SIZE +
     " if (wide) { c->x[3] = (uint32_t)wide; c->x[4] = wide >> 32; }"),
    # The graphics configuration's display size and its half-size scene base.
    (0x8088D29C, 0xF2C10E08, SIZE + " if (wide) c->x[8] = wide;"),
    (0x8088D2A8, 0xF2C08708, SIZE +
     " if (wide) c->x[8] = ((wide >> 33) << 32) | ((uint32_t)wide / 2);"),
)


def install(lifter, image, build_id):
    if build_id != BUILD_ID or any(image.word(pc) != expected for pc, expected, _ in SITES):
        return
    for pc, _, code in SITES:
        lifter.after[pc] = "{ " + code + " }"
