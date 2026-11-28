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
    # Private tier spike, instruction sites scoped to the checked main build ID.
    for pc in (0x801DB790, 0x801DB860, 0x801DB894, 0x801DB950,
               0x803877F0, 0x8033AE20, 0x8033AF54, 0x8033B064,
               0x80B84D20, 0x8068FCC0, 0x8088C840):
        lifter.after[pc] = ("{ extern void hos_tier_probe_site(Ctx *, unsigned); "
                            f"hos_tier_probe_site(c, {pc:#x}u); }}")
    # Private live-size spike: the game's render-size routine.
    for pc, fn in ((0x801AC368, "hos_wonder_live_force"), (0x801AC67C, "hos_wonder_live_size")):
        lifter.after[pc] = "{ extern void %s(Ctx *); %s(c); }" % (fn, fn)
    # Private live-size spike: the window textures follow the drawable through the game's own window rebuild,
    # and the camera's projection holds its 16:9 view inside the larger one. Instruction words checked; any mismatch leaves all out.
    GROW = (
        (0x8033AE78, 0x39432268, "{ extern void hos_wonder_window_present(Ctx *); hos_wonder_window_present(c); }"),
        (0x8033B1B8, 0x3903227F, "{ extern void hos_wonder_window_rebuilt(Ctx *); hos_wonder_window_rebuilt(c); }"),
        # The camera keeps its 16:9 view; the projection shows the rest around it (host/hos_main.c hos_wonder_cam_view).
        (0x8043E238, 0xD10163A1, "{ extern void hos_wonder_cam_bounds(Ctx *); hos_wonder_cam_bounds(c); }"),
        (0x8043CD50, 0x1E248802, "{ extern void hos_wonder_cam_view(Ctx *); hos_wonder_cam_view(c); }"),
    )
    if all(image.word(pc) == expected for pc, expected, _ in GROW):
        for pc, _, code in GROW:
            lifter.after[pc] = code
    # Private live-size spike: the scene arena sized from need at its creation (host/hos_main.c). Instruction words checked; any mismatch leaves both out.
    ARENA = (
        (0x8098A5A4, 0xAA0003F3, "{ extern void hos_wonder_arena_size(Ctx *); hos_wonder_arena_size(c); }"),
        (0x804F43A4, 0xF85E03A8, "{ extern void hos_wonder_arena_virtual(Ctx *); hos_wonder_arena_virtual(c); }"),
        (0x8098A690, 0xF9552A69, "{ extern void hos_wonder_arena_made(Ctx *); hos_wonder_arena_made(c); }"),
    )
    if all(image.word(pc) == expected for pc, expected, _ in ARENA):
        for pc, _, code in ARENA:
            lifter.after[pc] = code

    # Track the map camera's instance and refresh it before copying to the render view.
    MAP_LIVE = ((0x8085782C, 0xBD00B268, "hos_wonder_map_perspective_created"),
                (0x803FE37C, 0x3909A668, "hos_wonder_map_live_aspect"))
    if all(image.word(pc) == word for pc, word, _ in MAP_LIVE):
        for pc, _, fn in MAP_LIVE:
            lifter.after[pc] = f"{{ extern void {fn}(Ctx *); {fn}(c); }}"
