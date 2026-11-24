# Contributing to Wondershot

Wondershot is a static recompilation of **Super Mario Bros. Wonder – Nintendo Switch 2 Edition** for PC: the game's AArch64
code is lifted to C, the Horizon OS and NVN2 are implemented natively, and the GPU work is replayed on Vulkan. No emulator is
involved, and the game is built on your PC from your own copy.

It lives on GitHub, [Kendoismebutmaybenot/wondershot](https://github.com/Kendoismebutmaybenot/wondershot), and is built on
[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) by MagicBeanDev. Most of the code and the developer docs
(`docs/dev/`) are Longshot's. Where they talk about Longshot's forge, job queue, team chat, CircleCI or Test Farm, they do not
apply here; this page and [AGENTS.md](AGENTS.md) win.

## The rule with no exceptions

**No game files, keys, or anything made from them leave your PC.** The repository does not contain the game and never will.
That includes:

- the `.nup`, `romfs`, `exefs`, `dlc`, `.nso`, `.nca`, `.nsp`, `.xci` or `.nsz`/`.xcz` files, and any title keys;
- `work/` and everything in it (the extracted dump, `image.bin`, the lifted C, test builds), and the Builder's work folder
  (`%LOCALAPPDATA%\WondershotBuilder`);
- `wonder.exe`, `wonder_vk.dll` and other build output, the game folder's `cache/`, run profiles (perf or Tracy captures)
  and frame dumps;
- the game's shaders and anything made from them: `*.frag.spv` dumps and the HDR overrides in `shader_overrides/` (the
  Builder makes them on each player's PC);
- saves (`user/`), `wonder_options.ini` and `language.txt`. The one exception is scrubbed saves under `assets/saves/`
  ([the rules](assets/saves/README.md)).

Don't ask in an issue, a pull request or anywhere else where to get the game, how to decrypt it, or for someone else's files.
A screenshot, a video and the game's log are fine and often necessary: the log holds no game data. `.gitignore` covers most
of this, but check `git status` before you commit. If you aren't sure whether a file is game data, leave it out.

## The other non-negotiables

- **`main` takes reviewed pull requests**, from a branch on your fork, one topic each.
- **A change the game runs is tested in the game on your PC before its pull request opens.** Say what you ran and what you
  saw. A fix comes with a game-free test where one is possible.
- **A performance change shows its measured gain** against `main`.
- **Vendor SDKs are never committed, bundled or uploaded**: NVIDIA's DLSS SDK, AMD's FSR runtime, Intel's `libxess.dll`.
- **Only code you can license under the GPL** ([Licensing](#licensing)).
- **AI-assisted changes are welcome**, as the project itself uses them (see the README). Read and test every line you send.

## Get started

- **To play it**, you don't need any of this: get **WondershotBuilder** from
  [Releases](https://github.com/Kendoismebutmaybenot/wondershot/releases), run it, point it at your own dump and press Build.
- **To work on it**, clone the repository. `nx2/make_wonder.py` is what the Builder runs: it fetches the compiler and libraries
  once, lifts and compiles the game from your dump into a game folder. The first build is long and wants plenty of RAM; after
  it, a change to one source file rebuilds in a minute or two. [AGENTS.md](AGENTS.md) has the layout, how to rebuild and test
  a change, and how a release is made.
- **For how the recompiler, the host and the renderer work**, read Longshot's developer docs in [docs/dev](docs/dev/README.md)
  (and its original README, [docs/LONGSHOT_README.md](docs/LONGSHOT_README.md)).

## Ways to help

| | What |
|---|---|
| **Test on other hardware** | The port is tested on NVIDIA cards. Reports from AMD and Intel cards, other drivers and other Windows versions help even when everything works. |
| **Play further** | Reaching new worlds, courses, cutscenes, menus and items finds problems nobody has seen. |
| **Report what is broken** | Open an [issue](https://github.com/Kendoismebutmaybenot/wondershot/issues): the version, your hardware, where you were, and the game's log. |
| **Send a fix** | Branch, fix, test, open a pull request from your fork. Small, focused changes are the easiest to review. |
| **Improve the docs** | The README and the docs are part of the project. |

## Before you open an issue or a pull request

- Try the latest release (or current `main`) first: it has every fix so far.
- Search the [open issues](https://github.com/Kendoismebutmaybenot/wondershot/issues). If yours is there, add your details
  instead of opening another.
- English, please. One topic per issue or pull request.
- Say which version you ran: the game folder the Builder made has `wondershot_version.txt` with the release it was built from.
- For a graphics or performance problem, test without ReShade, shader-cache tools, overlays and frame-generation injectors:
  they change what the renderer does.
- A black window with sound is usually the renderer failing to start. Include the log lines starting with `vk:` around
  `swapchain`.

## CI

There is no CI on this repository yet. Run the game-free tests for the area you touched (`python -I -B tests/<name>.py`, or
`tests/run_all.py` for all of them) and say in the pull request what you ran.

## Licensing

Wondershot is free software under the [GNU General Public License, version 3](LICENSE), as Longshot is. By submitting a change
you license it under those terms, so only send code you can license that way: nothing from a project with an incompatible
license, and no decompiled game code or anything generated from the dump.

How the game or the console behaves (a function's name and arguments, a result code, the order of calls) is a fact and not
code, and the host's replacements for the console's functions are written from such facts; describe them in your own words and
cite a public source when there is one.

The third-party parts (under `third_party/` and `gpu/vk/eden/`, among others) keep their own notices: preserve them, and don't
relicense their code. NVIDIA's DLSS SDK is not one of them: it is never in the repository. Nor is Intel's `libxess.dll`.

## Where to talk

- **Issues and pull requests** on [GitHub](https://github.com/Kendoismebutmaybenot/wondershot).
- **Agents** read [AGENTS.md](AGENTS.md) on top of this page.
- **Questions about Longshot itself** (the recompiler, the renderer's general behaviour) belong with
  [its project](https://git.magicbean.dev/MagicBeanDev/Longshot).

Thanks for testing, reporting and sending fixes.
