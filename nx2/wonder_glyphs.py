"""Wonder's font frame and the iType map_char result, independent of display hooks."""

from wonder_wide import BUILD_ID

SITES = (
    (0x80089574, 0x3940F408, "hos_wonder_glyph_frame"),  # ldrb w8, [x0, #0x3d]
    (0x840BC324, 0x2A1703E0, "hos_wonder_glyph_result"),  # mov w0, w23
)


def install(lifter, image, build_id):
    if build_id != BUILD_ID:
        return
    for pc, expected, _ in SITES:
        found = image.word(pc)
        if found != expected:
            raise SystemExit(f"Wonder glyph hook {pc:#x}: expected {expected:08x}, found {found:08x}")
    for pc, _, hook in SITES:
        lifter.after[pc] = "{ extern void %s(Ctx *); %s(c); }" % (hook, hook)
