# Wondershot

> **Alpha.** Get **WondershotBuilder** from [Releases](https://github.com/Kendoismebutmaybenot/wondershot/releases), unzip it
> anywhere, run `WondershotBuilder.exe`, point it at your own game dump (a folder with `exefs` and `romfs`, or the game's `.nup`),
> press Build, then Play. The first build fetches the compiler and libraries once (about 280 MB, each checked against
> `tools.lock`), recompiles the game on your PC and sets the folder up; it takes a while and wants a fair amount of RAM. When a
> newer Wondershot release is out, the builder says so and Update downloads it and rebuilds only what changed. Your game's files can
> stay where they are (the game folder links to them) or be copied into the game folder, which then stands alone; the builder asks. The app is
> `builder/WondershotBuilder` (WPF, .NET 8); `scripts/wonder_builder_package.py` makes its folder and zip.

<a name="online-play"></a>

> **Online play.** Online play is experimental and uses Bellabel Park's existing Local Wireless Game Rooms. This is native game networking: each PC runs its own game. No screen streaming, Nintendo account, Cloudflare account or port forwarding is required.
>
> 1. Update with WondershotBuilder and rebuild the game. Both players need compatible game data, including the Bellabel Park add-on.
> 2. Open **Insert → Online**, enable Online multiplayer and set an **Online name**. Use a nickname: it is shown to other players in the room list and game.
> 3. Leave **Connection → Private relay** selected to keep IP addresses hidden from peers. For a potential latency improvement, both players can choose **Direct preferred** before entering a room. It tries direct P2P and falls back to TURN; direct peers can learn each other's IP addresses. Connection status reports the selected route. A direct connection does not guarantee lower latency on every network.
> 4. In the game, select **Play via Local Wireless**. The host creates a room and can set an optional four-digit invite code on the room creation screen. A PC text-entry dialog replaces the Switch keyboard; enter the invite code using number keys and press Enter. The guest selects the room from the game's room list and enters the same invite code if prompted.
> 5. Leave the room normally before changing connection settings. The settings apply to the next room. Names and a randomly generated network identity are saved in `user/online/profile.json`. Renaming preserves the identity and existing saves. Do not share that file or copy it between players.
>
> Gameplay uses encrypted WebRTC data channels, through Cloudflare TURN in Private relay mode or directly when available in Direct preferred mode. Cloudflare handles room discovery and connection setup. Permanent service credentials stay on the server. Clients receive temporary session and TURN credentials automatically.
>
> If a connection drops, try joining again or create a new room.
>
> TURN and direct gameplay have been tested using two instances on one PC, including different frame-rate caps. Native transport tests cover admission rejection and a replacement guest joining the same host room. The game’s numeric invite-code entry, rejection of a wrong PIN, successful entry with the correct PIN, and concurrent rooms were also confirmed in the actual game. Gameplay across separate internet connections and different router/NAT combinations still needs broader testing. Each room currently supports one host and one guest. Local multiplayer support does not mean four networked PCs are supported.
>
> If reporting a problem, include the Wondershot version, the selected connection mode and the relevant connection-status/error lines from `logs/wondershot.log`. Logs and copied bug reports automatically hide your home folder, account name in paths, IP addresses and labelled online names and credentials. Share the log, rather than profiles or other user files.

By default, the Builder reuses `build-workspace` inside the Wondershot install folder, alongside `wonder.exe`. Clear
**Store the build workspace in the install folder** to use `%LOCALAPPDATA%\WondershotBuilder\work`.
If you use linked game files with a `.nup`, keep the workspace's `dump` folder in place so the installed game can read its assets.

When **Update Builder app** appears, it downloads the new Builder and replaces the installed Builder in place.
**Update Wondershot** rebuilds the playable game.

Wondershot is a static recompilation of **Super Mario Bros. Wonder - Switch 2 Edition** for PC, built on
[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) by MagicBeanDev. It statically recompiles the game's own code
for the PC, so you need your own legally dumped copy of the game. **No game files are included here, and none ever will be.**

## What it does so far

- Runs the Switch 2 Edition, including the **Meetup in Bellabel Park** add-on content (from your own dump)
- **Frame rate cap** above 60 (120 tested) with the game running at the right speed (real-time step)
- **RenoDX-style HDR**: real highlights above paper white, Highlights / Highlight start, scene grading (Exposure, Contrast,
  Shadows, Saturation, Highlight saturation) and SDR gamma, all live in the Insert menu. Menus stay SDR. Ported from my
 HDR for the Switch 1 recomp SuperWonders
- Music and sound effects everywhere, hub worlds included, and movie audio
- Experimental **online play in Bellabel Park**, with a room list, optional invite code, saved names and random player identities. Private relay is the default; direct P2P with TURN fallback is available. See [Online play](#online-play).
- Players 2-4 locally, per-player controls, controller and keyboard assignment, per-player motion controls
- Button prompts that follow the controller in use (a stand-in for the system button font)
- The Poplin house dialogue and the Bellabel Park event softlocks above 60 fps fixed
- The Wonder flight into space and the camera following the fall back down work above 60 fps (240 fps cap tested)
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

- **[SuperWonders](https://github.com/vfjoo888/SuperWonders)** by vfjoo888: the Switch 1 high-FPS camera, keep-jump and [Dolphin Kick counter corrections](https://github.com/vfjoo888/SuperWonders/commit/da6861d1b181f95135df37be2641d2e9539d37c1) adapted for the Switch 2 Edition
- **[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot)** by MagicBeanDev: the recompiler, runtime and renderer this is
  built on. Their original README is in [docs/LONGSHOT_README.md](docs/LONGSHOT_README.md)
- The projects Longshot credits in turn (see its README and `third_party/`)
- HDR approach after [RenoDX](https://github.com/clshortfuse/renodx)

## Legal

Not affiliated with or endorsed by Nintendo. Super Mario Bros. Wonder is a trademark of Nintendo. This repository holds no
Nintendo code or assets. Licensed under the GNU GPL v3, as Longshot is (see [LICENSE](LICENSE)).

## AI assistance

AI was used to assist in writing code for this project. All of it was reviewed and tested by the author.
