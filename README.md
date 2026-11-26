# Wondershot

> **Alpha.** Get **WondershotBuilder** from [Releases](https://github.com/Kendoismebutmaybenot/wondershot/releases), unzip it
> anywhere, run `WondershotBuilder.exe`, point it at your own game dump (a folder with `exefs` and `romfs`, or the game's `.nup`),
> press Build, then Play. The first build fetches the compiler and libraries once (about 230 MB, each checked against
> `tools.lock`), recompiles the game on your PC and sets the folder up; it takes a while and wants a fair amount of RAM. When a
> newer Wondershot release is out, the builder says so and Update downloads it and rebuilds only what changed. Your game's files can
> stay where they are (the game folder links to them) or be copied into the game folder, which then stands alone; the builder asks. The app is
> `builder/WondershotBuilder` (WPF, .NET 8); `scripts/wonder_builder_package.py` makes its folder and zip.

By default, the Builder reuses `build-workspace` inside the Wondershot install folder, alongside `wonder.exe`. Clear
**Store the build workspace in the install folder** to use `%LOCALAPPDATA%\WondershotBuilder\work`.
If you use linked game files with a `.nup`, keep the workspace's `dump` folder in place so the installed game can read its assets.

When **Update Builder app** appears, it downloads the new Builder, installs it in a sibling `WondershotBuilder-updates` folder and
opens it. The previous Builder stays available. **Update Wondershot** rebuilds the playable game.

Wondershot is a static recompilation of **Super Mario Bros. Wonder – Switch 2 Edition** for PC, built on
[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) by MagicBeanDev. It statically recompiles the game's own code
for the PC, so you need your own legally dumped copy of the game. **No game files are included here, and none ever will be.**

## What it does so far

- Runs the Switch 2 Edition, including the **Meetup in Bellabel Park** add-on content (from your own dump)
- **Frame rate cap** above 60 (120 tested) with the game running at the right speed (real-time step)
- **RenoDX-style HDR**: real highlights above paper white, Highlights / Highlight start, scene grading (Exposure, Contrast,
  Shadows, Saturation, Highlight saturation) and SDR gamma, all live in the Insert menu. Menus stay SDR. Ported from the
  author's HDR for the Switch 1 recomp SuperWonders
- Music and sound effects everywhere, hub worlds included, and movie audio
- Players 2-4, per-player controls, controller and keyboard assignment, per-player motion controls
- Button prompts that follow the controller in use (a stand-in for the system button font)
- The Poplin house dialogue and the Bellabel Park event softlocks above 60 fps fixed
- A Mario-themed Insert menu that uses the game's own font
- DualSense HD haptics (over a cable) through [RenHDrum](https://github.com/trzz1214/RenHDrum) (MIT or Apache-2.0), built from its source in `third_party/renhdrum` and shipped in the builder
- A builder app that makes the game folder from your dump, HDR shaders included, with a **Game settings** button that starts the game with its Insert menu already open

## Known issues

- Not tested on many PCs: expect rough edges
- For gameplay issues, attach `logs/wondershot.log` from the game folder after reproducing the problem.

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

## AI assistance

AI was used to assist in writing code for this project. All of it was reviewed and tested by the author.
