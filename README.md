# Wondershot

> **Work in progress.** Wondershot runs, and there is a builder app: point it at your own game dump (or its `.nup`), press Build, then
> Play. It fetches the compiler and libraries it needs once (about 230 MB, each checked against `tools.lock`), recompiles the game on
> your PC and sets the folder up. When a newer Wondershot release is out, the builder says so and Update downloads it and rebuilds
> only what changed. The app is `builder/WondershotBuilder` (WPF, .NET 8); `scripts/wonder_builder_package.py` makes its folder.

Wondershot is a static recompilation of **Super Mario Bros. Wonder – Nintendo Switch 2 Edition** for PC, built on
[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) by MagicBeanDev. It statically recompiles the game's own code
for the PC, so you need your own legally dumped copy of the game. **No game files are included here, and none ever will be.**

## What it does so far

- Runs the Switch 2 Edition, including the **Meetup in Bellabel Park** add-on content (from your own dump)
- **Frame rate cap** above 60 (120 tested) with the game running at the right speed (real-time step)
- **RenoDX-style HDR**: real highlights above paper white, Highlights / Highlight start, scene grading (Exposure, Contrast,
  Shadows, Saturation, Highlight saturation) and SDR gamma, all live in the Insert menu. Menus stay SDR. Ported from the
  author's HDR for the Switch 1 recomp SuperWonders
- In-level music and sound effects, movie audio
- The Poplin house dialogue softlock above 60 fps fixed
- A Mario-themed Insert menu that uses the game's own font

## Known issues

- Button prompts show as `?` (the system button font isn't there yet: a stand-in is planned)
- No builder yet (see above)
- Not tested on many PCs: expect rough edges

## HDR shaders

The HDR replaces two of the game's shaders at run time. They're made on your PC from your own game by
`scripts/renodx_wonder_sw2.py` (from shaders the game dumps with `RX_VK_DUMP_FRAG`), written to `shader_overrides/hdr/` next
to the game, and never committed. The builder does this as its last step: it opens the new game once by itself until the title
has drawn both shaders, edits them, and deletes the dumps. The tools for it come without the Vulkan SDK: glslang's own Windows
release, and SPIRV-Cross compiled from its sources with the builder's compiler (both checked by SHA-256). If the step can't
finish, the game still plays, without its HDR highlights; building again retries it (`nx2/make_wonder.py --hdr-only --out <folder>`
does only this step).

## Credits

- **[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot)** by MagicBeanDev: the recompiler, runtime and renderer this is
  built on. Their original README is in [docs/LONGSHOT_README.md](docs/LONGSHOT_README.md)
- The projects Longshot credits in turn (see its README and `third_party/`)
- HDR approach after [RenoDX](https://github.com/clshortfuse/renodx)

## Legal

Not affiliated with or endorsed by Nintendo. Super Mario Bros. Wonder is a trademark of Nintendo. This repository holds no
Nintendo code or assets. Licensed under the GNU GPL v3, as Longshot is (see [LICENSE](LICENSE)).
