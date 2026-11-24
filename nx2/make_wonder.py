"""Wondershot: a game folder from the player's own copy of Super Mario Bros. Wonder - Nintendo Switch 2 Edition. What the builder app
(builder/WondershotBuilder) runs:

    python -I nx2/make_wonder.py --check --game <.nup or folder>
    python -I nx2/make_wonder.py --game <.nup or folder> --out <folder> [--work <folder>] [--tools <folder>] [--jobs <n>]
    python -I nx2/make_wonder.py --check-update                      (is there a newer Wondershot release on GitHub?)
    ... --update-to <tag> --update-url <url>                         (with a build: the release's sources first, then what changed)
    python -I nx2/make_wonder.py --hdr-only --out <folder>            (only the HDR shaders, for a folder built already)

--game is the game's .nup, or a folder holding its exefs/ and romfs/ (and dlc/romfs, with the Rosalina and Bellabel Park
content, when the player has it). The folder is read in place; nothing of it is copied into the repository, and no game data ever
comes with the tools. The folder made holds wonder.exe and all it needs: started with a double click.

The steps are the ones the author ran by hand: the build tools (tools.lock: the compiler, the libraries), the game's files, the
translation of its code (nx2/lift.py), the compile (nx2/build.py), and the game folder put together. Lines the app reads, each on its
own line of stdout:

    @@stage <id> <text>      a step begins: tools, dump, lift, compile, assemble, hdr, finish
    @@progress <0..1>        how far the whole build is
    @@eta <seconds>          the compile's time left
    @@check <ok|bad> <text>  (--check) the answer
    @@update <available|current|dev|unknown> <tag> <url>   (--check-update) the answer
    @@done <folder>          finished
    @@error <text>           stopped
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = [sys.executable, "-I", "-u", "-X", "utf8"]
EXE, VK = "wonder.exe", "wonder_vk.dll"
# (the build the patches were made from: the Switch 2 Edition's main module. The hooks are keyed to its addresses)
SUPPORTED_BUILD = "ec47e6f8"

# the share of the whole build each step is, for the bar
SPAN = {"update": (0.00, 0.03), "tools": (0.03, 0.07), "dump": (0.07, 0.13), "lift": (0.13, 0.30), "compile": (0.30, 0.94),
        "assemble": (0.94, 0.955), "hdr": (0.955, 0.995)}
LIFT_STEPS = 7   # (nx2/lift.py's "lift: <step> in <s>" lines)


def say(*words):
    print(" ".join(str(w) for w in words), flush=True)


def fail(text):
    say("@@error", text)
    sys.exit(1)


def stage(name, text):
    say("@@stage", name, text)
    say("@@progress", "%.4f" % SPAN[name][0] if name in SPAN else "1")


def progress(name, fraction):
    lo, hi = SPAN[name]
    say("@@progress", "%.4f" % (lo + (hi - lo) * max(0.0, min(1.0, fraction))))


def run(cmd, env=None, on_line=None, cwd=ROOT):
    """A child process whose lines come to on_line (and to the log); raises SystemExit with its tail when it fails"""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tail = []
    for line in p.stdout:
        line = line.rstrip("\r\n")
        if line.startswith("@@"):
            if on_line:
                on_line(line)
            continue
        say(line)
        tail = (tail + [line])[-12:]
        if on_line:
            on_line(line)
    if p.wait() != 0:
        fail("%s stopped (exit code %d). The last lines:\n%s" % (os.path.basename(next((c for c in cmd if c.endswith(".py")), cmd[0])),
                                                                 p.returncode, "\n".join(tail)))


# ---- the game ----
def read_head(path, n=0x60):
    with open(path, "rb") as f:
        return f.read(n)


def module_id(main):
    head = read_head(main)
    if head[:4] != b"NSO0":
        return None
    return head[0x40:0x60].hex()


def dump_folders(game):
    """(exefs, romfs, dlc romfs or None) of a folder dump; None for each that is not there"""
    exefs, romfs = os.path.join(game, "exefs"), os.path.join(game, "romfs")
    dlc = os.path.join(game, "dlc", "romfs")
    return (exefs if os.path.isdir(exefs) else None, romfs if os.path.isdir(romfs) else None, dlc if os.path.isdir(dlc) else None)


def check(game, work, tools):
    """@@check ok|bad: is this the game, and a version the tools can read"""
    if os.path.isdir(game):
        exefs, romfs, dlc = dump_folders(game)
        if not exefs or not romfs:
            say("@@check", "bad", "This folder has no exefs and romfs folders. Choose the one with the game's files in it, or its .nup file.")
            return
        main = os.path.join(exefs, "main")
        if not os.path.exists(main):
            say("@@check", "bad", "There is no exefs\\main in this folder: it isn't a game dump.")
            return
        bid = module_id(main)
        if bid is None:
            say("@@check", "bad", "exefs\\main isn't a game executable the tools can read (it may be compressed: use the game's .nup instead).")
            return
        if not bid.startswith(SUPPORTED_BUILD):
            say("@@check", "bad", "This is build %s. Wondershot is made for build %s of the Switch 2 Edition." % (bid[:8], SUPPORTED_BUILD))
            return
        extra = " With the Rosalina and Bellabel Park content." if dlc else " Without the Rosalina and Bellabel Park content (no dlc\\romfs)."
        say("@@check", "ok", "Super Mario Bros. Wonder – Nintendo Switch 2 Edition, build %s.%s" % (bid[:8], extra))
        return
    if not os.path.isfile(game) or not game.lower().endswith(".nup"):
        say("@@check", "bad", "Choose a folder with your game's exefs and romfs, or the game's .nup file.")
        return
    sys.path.insert(0, HERE)
    import nup as _nup
    try:
        n = _nup.Nup(game)
    except (OSError, ValueError, SystemExit, IndexError) as error:
        say("@@check", "bad", "This .nup could not be read (%s)." % (str(error) or type(error).__name__))
        return
    try:
        ids = ["%016x" % t["id"] for t in n.titles]
        ok = any(i.startswith("0400") or i.startswith("0100") for i in ids) and any(i[:13] == "010015100b514" or i[:13] == "040015100b514" for i in ids)
    finally:
        n.f.close()
    if ok:
        say("@@check", "ok", "Super Mario Bros. Wonder – Nintendo Switch 2 Edition (.nup, %d title%s)." % (len(ids), "" if len(ids) == 1 else "s"))
    else:
        say("@@check", "bad", "This .nup isn't Super Mario Bros. Wonder – Nintendo Switch 2 Edition (it holds %s)." % ", ".join(ids))


# ---- releases of the port (github.com/Kendoismebutmaybenot/wondershot) ----
REPO = "Kendoismebutmaybenot/wondershot"
# what a release replaces under the tools folder: the sources the build reads. third_party merges (its prebuilt files from tools.lock
# live in the same folders); the rest is swapped whole, the old one put back when the new one cannot be copied
UPDATE_DIRS = ("gpu", "host", "nx2", "scripts", "third_party", "assets/profiles", "assets/pipeline_states", "builder/setup")
UPDATE_FILES = ("tools.lock", "requirements.txt", "LICENSE", "README.md")
UPDATE_HOSTS = ("api.github.com", "github.com", "codeload.github.com")
UPDATE_MAX = 600 << 20   # (a release's sources are tens of MB: more than this is not one)


def installed_version(tools):
    """The release these tools are (tools/version.txt, written by the package and by an update); "dev" from a checkout"""
    try:
        with open(os.path.join(tools, "version.txt"), encoding="utf-8") as f:
            return f.readline().strip() or "dev"
    except OSError:
        return "dev"


def version_key(tag):
    """(numbers, final) of v1.2.3 or 1.2.3-rc1: a release candidate comes before its release"""
    m = re.match(r"v?(\d+(?:\.\d+)*)(.*)$", tag.strip())
    if not m:
        return None
    return (tuple(int(n) for n in m.group(1).split(".")), 0 if m.group(2).lstrip("-+.").strip() else 1)


def newer(tag, have):
    a, b = version_key(tag), version_key(have)
    if a is None:
        return False
    return b is None or a > b


def github_json(url):
    import json
    req = urllib.request.Request(url, headers={"User-Agent": "WondershotBuilder", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def check_update(tools):
    """@@update available <tag> <sources url> | current <tag> | dev | unknown <why>: a newer release of the port than this one?"""
    have = installed_version(tools)
    if have == "dev":
        say("@@update", "dev")
        return
    try:
        release = github_json("https://api.github.com/repos/%s/releases/latest" % REPO)
    except urllib.error.HTTPError as error:
        if error.code == 404:   # (no release yet)
            say("@@update", "current", have)
        else:
            say("@@update", "unknown", "GitHub said %d" % error.code)
        return
    except (OSError, ValueError) as error:
        say("@@update", "unknown", str(error).replace("\n", " "))
        return
    tag = str(release.get("tag_name", ""))
    url = str(release.get("zipball_url", ""))
    if tag and url and newer(tag, have):
        say("@@update", "available", tag, url)
    else:
        say("@@update", "current", have)


def apply_update(tools, tag, url):
    """The release's sources over the tools folder's (the compiler and libraries stay), then its tag as the version"""
    from urllib.parse import urlparse
    host = urlparse(url)
    if host.scheme != "https" or host.hostname not in UPDATE_HOSTS or REPO.lower() not in url.lower():
        fail("The update's address is not a Wondershot release on GitHub.")
    stage("update", "Downloading Wondershot %s" % tag)
    tmp = os.path.join(tools, ".update")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    archive = os.path.join(tmp, "release.zip")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WondershotBuilder"})
        got = 0
        with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > UPDATE_MAX:
                    fail("The download is larger than a Wondershot release can be.")
                f.write(chunk)
                if total:
                    progress("update", 0.8 * got / total)
    except OSError as error:
        fail("Wondershot %s could not be downloaded (%s). Check the internet connection and try again." % (tag, error))
    new = os.path.join(tmp, "new")
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        top = names[0].split("/")[0] + "/" if names else ""
        for name in names:
            rel = name[len(top):] if name.startswith(top) else ""
            parts = rel.split("/")
            if not rel or rel.endswith("/") or ".." in parts or os.path.isabs(rel) or ":" in rel:
                continue   # (nothing outside the folder it unpacks into)
            if not (any(rel == d or rel.startswith(d + "/") for d in UPDATE_DIRS) or rel in UPDATE_FILES):
                continue
            target = os.path.join(new, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    progress("update", 0.9)
    if not os.path.isfile(os.path.join(new, "nx2", "make_wonder.py")):
        shutil.rmtree(tmp, ignore_errors=True)
        fail("That release has no nx2/make_wonder.py: it is not a release this builder can build.")
    for rel in UPDATE_DIRS:
        src, dst = os.path.join(new, *rel.split("/")), os.path.join(tools, *rel.split("/"))
        if not os.path.isdir(src):
            continue
        if rel == "third_party":
            shutil.copytree(src, dst, dirs_exist_ok=True)
            continue
        old = dst + ".old"
        shutil.rmtree(old, ignore_errors=True)
        had = os.path.isdir(dst)
        if had:
            os.rename(dst, old)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)
        except OSError as error:
            shutil.rmtree(dst, ignore_errors=True)
            if had:
                os.rename(old, dst)
            fail("The update could not be put in place (%s). Nothing was changed." % error)
        shutil.rmtree(old, ignore_errors=True)
    for f in UPDATE_FILES:
        if os.path.isfile(os.path.join(new, f)):
            shutil.copyfile(os.path.join(new, f), os.path.join(tools, f))
    with open(os.path.join(tools, "version.txt"), "w", encoding="utf-8") as f:
        f.write(tag + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    progress("update", 1.0)
    say("Wondershot %s's sources are in place" % tag)


# ---- the build tools (tools.lock) ----
def lock_tools(system="windows-x64"):
    """[(name, sha256, size, dest folder name, prefix, [urls])] of tools.lock for this system"""
    out = []
    with open(os.path.join(ROOT, "tools.lock"), encoding="utf-8") as f:
        for line in f:
            w = line.split()
            if len(w) >= 9 and w[0] == "tool" and w[3] == system:
                dest = w[6].replace("\\", "/").split("/tools/", 1)[-1] if "/tools/" in w[6] else w[6]
                out.append((w[1], w[4], int(w[5]), dest, w[7], w[8:]))
    return out


def download(urls, sha, size, target, progress_cb):
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WondershotBuilder"})
            h, got = hashlib.sha256(), 0
            with urllib.request.urlopen(req, timeout=60) as r, open(target, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    progress_cb(got / size if size else 0)
            if h.hexdigest() == sha and got == size:
                return
            last = "the file from %s was not the one expected" % url.split("/")[2]
        except OSError as error:
            last = "%s: %s" % (url.split("/")[2], error)
    fail("A build tool could not be downloaded (%s). Check the internet connection and try again." % last)


# (a file each tool has once it is there: third_party's folder is also the sources' own, so the folder alone says nothing)
MARKERS = {"llvm-mingw": os.path.join("bin", "clang.exe"), "cpm": "", "third_party": os.path.join("sdl2", "SDL3.dll")}


def ensure_tools(tools):
    """The build tools in `tools` (python is the builder's own: not fetched here when it runs the script already)"""
    os.makedirs(tools, exist_ok=True)
    needed = [t for t in lock_tools() if t[0] != "python" and t[3] in MARKERS]
    todo = [t for t in needed if not os.path.exists(os.path.join(tools, t[3], MARKERS[t[3]]))]
    total = sum(t[2] for t in todo) or 1
    done = 0
    for name, sha, size, dest, prefix, urls in todo:
        say("fetching %s %s (%d MB)" % (name, dest, size // 1000000))
        zpath = os.path.join(tools, dest + ".download.zip")
        base = done
        download(urls, sha, size, zpath, lambda f: progress("tools", (base + f * size) / total))
        part = os.path.join(tools, dest + ".part")
        shutil.rmtree(part, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(part)
        src = part if prefix == "-" else os.path.join(part, prefix)
        if dest == "third_party":   # (beside the sources of the same folder: merged, nothing of them replaced)
            shutil.copytree(src, os.path.join(tools, dest), dirs_exist_ok=True)
        else:
            shutil.rmtree(os.path.join(tools, dest), ignore_errors=True)
            shutil.move(src, os.path.join(tools, dest))
        shutil.rmtree(part, ignore_errors=True)
        os.remove(zpath)
        done += size
        progress("tools", done / total)
    for need, marker in MARKERS.items():
        if not os.path.exists(os.path.join(tools, need, marker)):
            fail("The build tool %s is missing from %s." % (need, tools))


# ---- the build ----
def tool_env(tools, work, exefs, romfs):
    env = dict(os.environ)
    env.update({
        "LONGSHOT_MINGW": os.path.join(tools, "llvm-mingw"),
        "RX_CPM": os.path.join(tools, "cpm"),
        "OOT_EXEFS": exefs,
        "OOT_ROMFS": romfs,
        "OOT_WORK": work,
    })
    if os.path.isdir(os.path.join(tools, "wgpu-native")):
        env["WGPU_NATIVE"] = os.path.join(tools, "wgpu-native")
    ngx = os.path.join(tools, "ngx")
    if os.path.isdir(ngx):
        env["LONGSHOT_NGX_SDK"] = ngx
    env.pop("EMSDK", None)   # (Windows takes the compiler from llvm-mingw: nothing of an emsdk)
    return env


def extract_nup(game, dump):
    """The newest title of a .nup into dump (exefs, romfs), as nx2/nup.py --extract does it"""
    stage("dump", "Reading your game's files")
    last = [0.0]

    def on_line(line):
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        if m:
            progress("dump", float(m.group(1)) / 100)

    run(PY + [os.path.join(HERE, "nup.py"), game, "--extract", dump], on_line=on_line)


GAME_PATH = [""]   # (the --game the build was started with: written into the folder's wondershot_version.txt)


def build(game, out, work, tools, jobs, update=None):
    t0 = time.time()
    GAME_PATH[0] = game
    if update:
        apply_update(tools, *update)
    stage("tools", "Getting the build tools")
    ensure_tools(tools)
    progress("tools", 1.0)

    if os.path.isdir(game):
        exefs, romfs, dlc = dump_folders(game)
        if not exefs or not romfs:
            fail("The folder %s has no exefs and romfs folders." % game)
        stage("dump", "Reading your game's files")
    else:
        dump = os.path.join(work, "dump")
        if not os.path.isdir(os.path.join(dump, "exefs", "main")) and not os.path.exists(os.path.join(dump, "exefs", "main")):
            shutil.rmtree(dump, ignore_errors=True)
            os.makedirs(dump, exist_ok=True)
            extract_nup(game, dump)
        exefs, romfs, dlc = dump_folders(dump)
        if not exefs or not romfs:
            fail("The .nup held no exefs and romfs: is it the game's base package?")
    check_modules(exefs)
    bid = module_id(os.path.join(exefs, "main")) or ""
    if not bid.startswith(SUPPORTED_BUILD):
        fail("This is build %s of the game. Wondershot is made for build %s." % (bid[:8], SUPPORTED_BUILD))
    progress("dump", 1.0)

    env = tool_env(tools, work, exefs, romfs)
    os.makedirs(work, exist_ok=True)

    # the translation of the game's code
    stage("lift", "Translating the game's code")
    steps = [0]

    def lift_line(line):
        if re.match(r"lift: .+ in [\d.]+s \(", line):
            steps[0] += 1
            progress("lift", steps[0] / LIFT_STEPS)

    run(PY + [os.path.join(HERE, "lift.py"), "--exefs", exefs, "--work", work, "--standalone", "--write"], env=env, on_line=lift_line)
    progress("lift", 1.0)

    # the compile
    stage("compile", "Compiling the game for your PC")
    plan = [0, 0]   # (files to build, built so far)

    def build_line(line):
        if line.startswith("@@plan "):
            plan[0] = int(line.split()[1])
        elif line.startswith("@@file "):
            plan[1] += 1
            if plan[0]:
                progress("compile", plan[1] / plan[0])
        elif line.startswith("@@eta "):
            say(line)

    run(PY + [os.path.join(HERE, "build.py"), "--standalone", "--jobs", str(jobs)], env=env, on_line=build_line)
    progress("compile", 1.0)

    # the folder
    stage("assemble", "Putting your game folder together")
    assemble(out, work, tools, dlc, romfs, exefs)
    make_hdr(out, tools)
    stage("finish", "All set")
    say("@@progress", "1")
    say("built in %.0f minutes" % ((time.time() - t0) / 60))
    say("@@done", out)


def check_modules(exefs):
    """Every module of the exefs is one the tools can read, said here and not as a Python error from the translator"""
    for name in os.listdir(exefs):
        if name == "main.npdm" or name.endswith((".part", ".plain")):
            continue
        head = read_head(os.path.join(exefs, name), 16)
        if head[:4] != b"NSO0":
            fail("The file %s in this dump is not a game module (it starts %s). Try the game's .nup, or another dump of the game." %
                 (name, head.hex()))


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def junction(link, target):
    """A directory junction (no administrator needed): the game folder reads the player's dump where it is"""
    if os.path.lexists(link):
        if os.path.islink(link) or os.path.isjunction(link):
            os.rmdir(link)   # (a junction of an earlier build: only the link goes, never what it points at)
        else:
            return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def assemble(out, work, tools, dlc, romfs, exefs):
    os.makedirs(out, exist_ok=True)
    build_dir = os.path.join(work, "sa", "build")
    image = os.path.join(work, "sa", "image", "image.bin")
    for name, src in ((EXE, os.path.join(build_dir, EXE)), (VK, os.path.join(build_dir, VK)), ("image.bin", image)):
        if not os.path.isfile(src):
            fail("The build did not make %s." % name)
        shutil.copy2(src, os.path.join(out, name))
    third = os.path.join(tools, "third_party")
    for sub, names in (("sdl2", ("SDL2.dll", "SDL3.dll")),):
        for n in names:
            p = os.path.join(third, sub, n)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(out, n))
    for n in ("renhdrum.dll",):   # (optional: RenHDrum's DualSense and Xbox haptics. Without it every pad keeps its plain motors)
        for d in (build_dir, os.path.join(ROOT, "third_party", "renhdrum"), os.path.join(tools, "third_party", "renhdrum")):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(out, n))
                break
    # the game's files, read where they are
    for name, target in (("romfs", romfs), ("dlc", dlc)):
        if target is None:
            continue
        link = os.path.join(out, name)
        if not junction(link, target):
            fail("%s could not be linked to %s. Is %s already something else?" % (link, target, link))
    # the button icons' font, drawn here (nx2/wonder_prompt_font.py) from Windows' own Segoe UI for the letters
    prompts = os.path.join(out, "prompts")
    os.makedirs(prompts, exist_ok=True)
    r = subprocess.run(PY + [os.path.join(HERE, "wonder_prompt_font.py"), "--out", os.path.join(prompts, "wonder_ext.ttf")],
                       capture_output=True, text=True, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        say("the button icons' font could not be made (%s): the game shows ? for its buttons" % (r.stderr.strip().splitlines() or ["?"])[-1])
    for folder in ("cache", "logs", "user", "shader_overrides"):
        os.makedirs(os.path.join(out, folder), exist_ok=True)
    # what the builder app reads to say this folder is Wondershot, which release built it, and which game to build again from
    with open(os.path.join(out, "wondershot_version.txt"), "w", encoding="utf-8") as f:
        f.write("version=%s\nbuilt=%s\ngame=%s\n" % (installed_version(tools), time.strftime("%Y-%m-%d %H:%M"), GAME_PATH[0]))


# ---- HDR: the game's tone mapper and final copy, edited on the player's PC (scripts/renodx_wonder_sw2.py) ----
# The two fragment programs the HDR replaces. Their SPIR-V is the game's own (translated by the renderer), so it is made here,
# from the player's game: the folder's wonder.exe runs once with RX_VK_DUMP_FRAG (vk_shader.cpp frag_override) until the
# title has drawn both, the script edits them into shader_overrides/hdr/, and the dumps are deleted. Nothing of it is shipped.
HDR_PROGRAMS = ("9c39b1dd1e1bad88", "b7914ae65792d0c8")   # (the tone mapper, the final copy: both drawn on the title)
HDR_WAIT = 240   # (seconds the game may take to draw both: the first start translates every shader it meets)
# The shader tools the edit needs, instead of the Vulkan SDK: glslang's own Windows release, and SPIRV-Cross (no Windows
# release of its own) compiled here from its sources with llvm-mingw. (name, sha256, size, urls), each checked as tools.lock's
GLSLANG = ("glslang 16.6.0", "82bf434e69b9bb4829de7e2b4bc2c5e7a7861e53d66cf75e5cc70f5f694a8d9b", 13734779,
           ["https://github.com/KhronosGroup/glslang/releases/download/16.6.0/glslang-16.6.0-windows-x86_64-release.zip"])
SPIRV_CROSS = ("SPIRV-Cross vulkan-sdk-1.4.341.0", "da2a75f72140caf4cccd6370cb6b25d09004f8cd2e6cda1abdfc4b2011f387a0", 4363752,
               ["https://github.com/KhronosGroup/SPIRV-Cross/archive/refs/tags/vulkan-sdk-1.4.341.0.zip"])
SPIRV_CROSS_SOURCES = ("main", "spirv_cfg", "spirv_cpp", "spirv_cross", "spirv_cross_parsed_ir", "spirv_cross_util", "spirv_glsl",
                       "spirv_hlsl", "spirv_msl", "spirv_parser", "spirv_reflect")


class HdrSkipped(Exception):
    pass


def ensure_shader_tools(tools):
    """tools/shader-tools with glslang.exe and spirv-cross.exe (fetched and made once)"""
    d = os.path.join(tools, "shader-tools")
    os.makedirs(d, exist_ok=True)
    glslang, cross = os.path.join(d, "glslang.exe"), os.path.join(d, "spirv-cross.exe")
    if not os.path.isfile(glslang):
        say("fetching %s" % GLSLANG[0])
        z = os.path.join(d, "glslang.download.zip")
        download(GLSLANG[3], GLSLANG[1], GLSLANG[2], z, lambda f: progress("hdr", 0.15 * f))
        with zipfile.ZipFile(z) as zz, open(glslang + ".part", "wb") as f:
            f.write(zz.read("bin/glslang.exe"))
        os.replace(glslang + ".part", glslang)
        os.remove(z)
    if not os.path.isfile(cross):
        say("fetching and compiling %s" % SPIRV_CROSS[0])
        z = os.path.join(d, "spirv-cross.download.zip")
        download(SPIRV_CROSS[3], SPIRV_CROSS[1], SPIRV_CROSS[2], z, lambda f: progress("hdr", 0.15 + 0.05 * f))
        src = os.path.join(d, "spirv-cross-src")
        shutil.rmtree(src, ignore_errors=True)
        with zipfile.ZipFile(z) as zz:
            zz.extractall(src)
        os.remove(z)
        top = os.path.join(src, os.listdir(src)[0])
        for lic in ("LICENSE", "LICENSES"):
            p = os.path.join(top, lic)
            if os.path.isfile(p):
                shutil.copyfile(p, os.path.join(d, "SPIRV-Cross-" + lic + ".txt"))
        cxx = os.path.join(tools, "llvm-mingw", "bin", "clang++.exe")
        r = subprocess.run([cxx, "-std=c++17", "-O1", "-static", "-o", cross + ".part"]
                           + [os.path.join(top, n + ".cpp") for n in SPIRV_CROSS_SOURCES],
                           capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        shutil.rmtree(src, ignore_errors=True)
        if r.returncode != 0:
            raise HdrSkipped("SPIRV-Cross did not compile: %s" % (r.stderr.strip().splitlines() or ["?"])[-1])
        os.replace(cross + ".part", cross)
    progress("hdr", 0.25)
    return d


def dump_hdr_programs(out):
    """The game's two programs' SPIR-V, from one run of the folder's wonder.exe: {key: path}"""
    for k in HDR_PROGRAMS:
        p = os.path.join(out, k + ".frag.spv")
        if os.path.exists(p):
            os.remove(p)
    # (a folder played before has its programs in cache/, and a program read from there is not translated, so not dumped: the
    # cache waits beside the folder for the run, and comes back after it)
    cache, aside = os.path.join(out, "cache"), os.path.join(out, "cache.hdr-aside")
    moved = os.path.isdir(cache) and any(n != "prompts" for n in os.listdir(cache))
    if moved:
        shutil.rmtree(aside, ignore_errors=True)
        os.rename(cache, aside)
        os.makedirs(cache)
    env = dict(os.environ)
    env["RX_VK_DUMP_FRAG"] = ",".join(HDR_PROGRAMS)
    log = os.path.join(out, "logs", "hdr_dump.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    try:
        with open(log, "w", encoding="utf-8", errors="replace") as lf:
            p = subprocess.Popen([os.path.join(out, EXE)], cwd=out, env=env, stdout=lf, stderr=subprocess.STDOUT)
            t0 = time.time()
            try:
                while True:
                    got = [k for k in HDR_PROGRAMS if os.path.isfile(os.path.join(out, k + ".frag.spv"))]
                    progress("hdr", 0.25 + 0.6 * min(1.0, (len(got) + (time.time() - t0) / HDR_WAIT) / (len(HDR_PROGRAMS) + 1)))
                    if len(got) == len(HDR_PROGRAMS):
                        time.sleep(1)   # (the second file's last words written)
                        break
                    if p.poll() is not None:
                        raise HdrSkipped("the game closed before it drew its title (exit code %s; logs\\hdr_dump.log)" % p.returncode)
                    if time.time() - t0 > HDR_WAIT:
                        raise HdrSkipped("the game did not draw its title within %d s (logs\\hdr_dump.log)" % HDR_WAIT)
                    time.sleep(0.5)
            finally:
                if p.poll() is None:   # (this run only: its own process tree, by its id)
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    p.wait(30)
    finally:
        if moved:
            time.sleep(1)
            shutil.rmtree(cache, ignore_errors=True)
            os.rename(aside, cache)
    return {k: os.path.join(out, k + ".frag.spv") for k in HDR_PROGRAMS}


def make_hdr(out, tools):
    """shader_overrides/hdr/ for the folder; a failure leaves the game as it is (HDR off works, HDR on is the game's own SDR)"""
    stage("hdr", "Making the HDR shaders (the game opens for a moment)")
    dumps = {}
    try:
        shader_tools = ensure_shader_tools(tools)
        dumps = dump_hdr_programs(out)
        env = dict(os.environ)
        env["RENODX_TOOLS"] = shader_tools
        r = subprocess.run(PY + [os.path.join(ROOT, "scripts", "renodx_wonder_sw2.py"), "--dump", dumps[HDR_PROGRAMS[0]],
                                 "--copy-dump", dumps[HDR_PROGRAMS[1]], "--game", out],
                           cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (r.stdout + r.stderr).splitlines():
            say(line)
        if r.returncode != 0:
            raise HdrSkipped("the HDR edit stopped: %s" % ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1])
        say("HDR shaders made: shader_overrides\\hdr")
    except HdrSkipped as why:
        say("the HDR shaders could not be made (%s): the game plays, without its HDR highlights. Build again to retry." % why)
    finally:
        for p in dumps.values():   # (the game's own code: not left lying in the folder)
            if os.path.exists(p):
                os.remove(p)
    progress("hdr", 1.0)


def default_tools():
    """The tools beside this script's package, or the builder's own folder in the player's profile"""
    own = os.path.join(ROOT, "python")
    if os.path.isdir(own):
        return ROOT
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WondershotBuilder", "tools")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game")
    ap.add_argument("--out")
    ap.add_argument("--work")
    ap.add_argument("--tools")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--check-update", action="store_true")
    ap.add_argument("--hdr-only", action="store_true", help="only make shader_overrides/hdr for the --out folder (built already)")
    ap.add_argument("--update-to")
    ap.add_argument("--update-url")
    a = ap.parse_args()
    tools = a.tools or os.environ.get("WONDERSHOT_TOOLS") or default_tools()
    work = a.work or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WondershotBuilder", "work")
    if a.check_update:
        check_update(tools)
        return 0
    if a.hdr_only:
        if not a.out or not os.path.isfile(os.path.join(a.out, EXE)):
            fail("--hdr-only needs --out: a folder Wondershot was built into.")
        make_hdr(os.path.abspath(a.out), os.path.abspath(tools))
        return 0
    if not a.game:
        fail("--game is missing.")
    game = os.path.abspath(a.game)
    if a.check:
        check(game, work, tools)
        return 0
    if not a.out:
        fail("--out is missing.")
    jobs = a.jobs or max(1, (os.cpu_count() or 4) - 1)
    update = (a.update_to, a.update_url) if a.update_to and a.update_url else None
    build(game, os.path.abspath(a.out), os.path.abspath(work), os.path.abspath(tools), jobs, update)
    return 0


if __name__ == "__main__":
    sys.exit(main())
