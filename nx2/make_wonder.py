"""Wondershot: a game folder from the player's own copy of Super Mario Bros. Wonder - Nintendo Switch 2 Edition. What the builder app
(builder/WondershotBuilder) runs:

    python -I nx2/make_wonder.py --check --game <.nup or folder>
    python -I nx2/make_wonder.py --game <.nup or folder> --out <folder> [--work <folder>] [--tools <folder>] [--jobs <n>]
                                 [--game-files link|copy]
    python -I nx2/make_wonder.py --check-update                      (is there a newer Wondershot release on GitHub?)
    python -I nx2/make_wonder.py --update-builder <tag>              (install and report the new Builder app's path)
    ... --update-to <tag> --update-url <url>                         (with a build: the release's sources first, then what changed)
    python -I nx2/make_wonder.py --hdr-only --out <folder>            (only the HDR shaders, for a folder built already)

--game is the game's .nup, or a folder holding its exefs/ and romfs/ (and dlc/romfs, with the Rosalina and Bellabel Park
content, when the player has it). The folder is read in place; nothing of it is copied into the repository, and no game data ever
comes with the tools. The folder made holds wonder.exe and all it needs: started with a double click.

The steps are the ones the author ran by hand: the build tools (tools.lock: the compiler, the libraries), the game's files, the
translation of its code (nx2/lift.py), the compile (nx2/build.py), and the game folder put together. Lines the app reads, each on its
own line of stdout:

    @@stage <id> <text>      a step begins: tools, dump, lift, compile, files (copy mode), layer (an add-on put over
                             the romfs), assemble, hdr, finish
    @@progress <0..1>        how far the whole build is
    @@eta <seconds>          the compile's time left
    @@check <ok|bad> <text>  (--check) the answer
    @@update <available|current|dev|unknown> <tag> <url>   (--check-update) the answer
    @@builder-update <tag>  (--check-update) a newer Builder app is available
    @@builder-ready <exe>   (--update-builder) the new Builder app
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
import tempfile
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
SPAN = {"update": (0.00, 0.03), "tools": (0.03, 0.07), "dump": (0.07, 0.13), "lift": (0.13, 0.30), "compile": (0.30, 0.90),
        "files": (0.90, 0.92), "layer": (0.92, 0.94), "assemble": (0.94, 0.955), "hdr": (0.955, 0.995)}
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
    reason = ''
    for line in p.stdout:
        line = line.rstrip("\r\n")
        if line.startswith("@@"):
            if line.startswith("@@error "):
                reason = line[len("@@error "):].strip() or reason
            if on_line:
                on_line(line)
            continue
        say(line)
        tail = (tail + [line])[-12:]
        if on_line:
            on_line(line)
    if p.wait() != 0:
        if reason:
            fail(reason)
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


HEAP_DEFS = ("Product.Nin_Ounce_NVN2.HeapDef.byml.zs", "Default.Nin_Ounce_NVN2.HeapDef.byml.zs")


def has_heap_def(romfs):
    """The game needs its Switch 2 heap sizes to finish starting."""
    heap_dir = os.path.join(romfs, "System", "HeapSize")
    return any(os.path.isfile(lp(os.path.join(heap_dir, name))) for name in HEAP_DEFS)


def needs_layering(romfs, dlc):
    """A dump unpacked title by title: romfs is the Switch 1 game's, and the Switch 2 Edition's own files (its heap definition,
    the Nin_Ounce_NVN2 assets, newer copies of many others) are in the add-on 010015100B515001, which says so with
    System/AocUpgradeVersion.txt. A .nup's romfs has the add-on over the game's files already; for this layout the build puts it
    over them in the game folder (layer_romfs). The player's dump is never written."""
    return (bool(dlc) and not has_heap_def(romfs) and has_heap_def(dlc)
            and os.path.isfile(lp(os.path.join(dlc, "System", "AocUpgradeVersion.txt"))))


def romfs_boot_error(romfs, dlc=None):
    if has_heap_def(romfs) or needs_layering(romfs, dlc):
        return None
    return ("This RomFS is missing the Switch 2 heap definition (System/HeapSize/%s or %s). "
            "Wondershot cannot start without it. Select a complete Switch 2 Edition dump or its .nup." % HEAP_DEFS)


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
        error = romfs_boot_error(romfs, dlc)
        if error:
            say("@@check", "bad", error)
            return
        extra = " With the Rosalina and Bellabel Park content." if dlc else " Without the Rosalina and Bellabel Park content (no dlc\\romfs)."
        if needs_layering(romfs, dlc):
            extra += " The Switch 2 Edition's files are in the add-on: the build puts them over the romfs in the game folder."
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
        # (the Switch 2 Edition's program is 040015100b514001. A package with only 010015100b514000 is the Switch 1 game, which
        # circulates under the Switch 2 Edition's name)
        ok = any(i[:13] == "040015100b514" for i in ids)
        switch1 = any(i[:13] == "010015100b514" and i[13:] == "000" for i in ids)
    finally:
        n.f.close()
    if not ok and switch1:
        say("@@check", "bad", "This .nup is the Nintendo Switch 1 version of Super Mario Bros. Wonder (title 010015100B514000), "
            "whatever its file name says. Wondershot is made from the Nintendo Switch 2 Edition, whose own package has the title "
            "040015100B514001. A Switch 1 package cannot be used.")
        return
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
UPDATE_MAX = 600 << 20   # cap downloads for both source archives and Builder packages
BUILDER_TAG = re.compile(r"v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.?\d+)?")


def read_version(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip() or "dev"
    except OSError:
        return "dev"


def installed_version(tools):
    return read_version(os.path.join(tools, "version.txt"))


PRE_STAGES = ("alpha", "beta", "rc")   # (a pre-release's kinds, in order: v1.0.0-alpha2 < -beta1 < -rc1 < v1.0.0)


def version_key(tag):
    """(numbers, final, stage, its number) of v1.2.3, v1.2.3-alpha2 or 1.2.3-rc1: pre-releases come before their release, in
    PRE_STAGES order, then by their number"""
    m = re.match(r"v?(\d+(?:\.\d+)*)(.*)$", tag.strip())
    if not m:
        return None
    numbers = tuple(int(n) for n in m.group(1).split("."))
    pre = m.group(2).lstrip("-+.").strip().lower()
    if not pre:
        return (numbers, 1, 0, 0)
    pm = re.match(r"([a-z]*)\.?(\d*)", pre)
    stage = PRE_STAGES.index(pm.group(1)) if pm.group(1) in PRE_STAGES else 0
    return (numbers, 0, stage, int(pm.group(2) or 0))


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


def builder_release(app):
    if not os.path.isfile(os.path.join(app, "WondershotBuilder.exe")):
        return "dev"
    return read_version(os.path.join(app, "builder_version.txt"))


def builder_asset(release):
    tag = release.get("tag_name", "")
    if release.get("draft") or not isinstance(tag, str) or not BUILDER_TAG.fullmatch(tag):
        return None
    name = "WondershotBuilder-%s.zip" % tag
    url = "https://github.com/%s/releases/download/%s/%s" % (REPO, tag, name)
    for asset in release.get("assets", []):
        digest, size = asset.get("digest") or "", asset.get("size")
        if (asset.get("name") == name and asset.get("state") == "uploaded" and asset.get("browser_download_url") == url
                and isinstance(digest, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
                and type(size) is int and 0 < size <= UPDATE_MAX):
            return url, digest[7:], size
    return None


def check_update(tools):
    """@@update available <tag> <sources url> | current <tag> | dev | unknown <why>: a newer release of the port than this one?"""
    have = installed_version(tools)
    app_version = builder_release(os.path.dirname(tools))
    if have == app_version == "dev":
        say("@@update", "dev")
        return
    try:
        # (every release, pre-releases too: GitHub's /releases/latest leaves those out, and the alphas are pre-releases)
        releases = github_json("https://api.github.com/repos/%s/releases?per_page=30" % REPO)
    except urllib.error.HTTPError as error:
        if error.code == 404:   # (no such repository yet)
            say("@@update", "current", have)
        else:
            say("@@update", "unknown", "GitHub said %d" % error.code)
        return
    except (OSError, ValueError) as error:
        say("@@update", "unknown", str(error).replace("\n", " "))
        return
    tag, url, app_tag = "", "", ""
    for release in releases if isinstance(releases, list) else []:
        t, u = str(release.get("tag_name", "")), str(release.get("zipball_url", ""))
        if release.get("draft") or not t or version_key(t) is None:
            continue
        if u and (not tag or newer(t, tag)):
            tag, url = t, u
        if app_version != "dev" and newer(t, app_tag or app_version) and builder_asset(release):
            app_tag = t
    if app_tag:
        say("@@builder-update", app_tag)
    if have == "dev":
        say("@@update", "dev")
    elif tag and url and newer(tag, have):
        say("@@update", "available", tag, url)
    else:
        say("@@update", "current", have)


def extract_builder(archive, dest):
    """Unpack the package's single top folder into an empty staging directory."""
    import ntpath
    import stat

    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if not entries or sum(e.file_size for e in entries) > 2 * UPDATE_MAX:
            raise ValueError("The Builder ZIP is empty or expands beyond the update size limit.")
        root = entries[0].filename.split("/")[0]
        for entry in entries:
            parts = entry.filename.rstrip("/").split("/")
            if (parts[0] != root or any(not p or p in (".", "..") or "\\" in p or ntpath.isreserved(p) for p in parts)
                    or stat.S_ISLNK(entry.external_attr >> 16) or (len(parts) == 1 and not entry.is_dir())):
                raise ValueError("The Builder ZIP has an invalid file path.")
            target = os.path.join(dest, *parts[1:])
            if entry.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with package.open(entry) as source, open(target, "xb") as output:
                    shutil.copyfileobj(source, output)


def install_builder(tools, tag):
    from tempfile import TemporaryDirectory
    from urllib.parse import urlparse

    app = os.path.dirname(tools)
    have = builder_release(app)
    if have == "dev" or not BUILDER_TAG.fullmatch(tag) or not newer(tag, have):
        raise ValueError("This is not a newer packaged Wondershot Builder release.")
    release = github_json("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, tag))
    asset = builder_asset(release) if release.get("tag_name") == tag else None
    if asset is None:
        raise ValueError("GitHub has no verified Builder ZIP for %s." % tag)
    url, expected_hash, size = asset
    root = os.path.dirname(app)
    if os.path.basename(root) != "WondershotBuilder-updates":
        root = os.path.join(root, "WondershotBuilder-updates")
    os.makedirs(root, exist_ok=True)
    with TemporaryDirectory(prefix="download-", dir=root) as temp:
        archive = os.path.join(temp, "builder.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "WondershotBuilder"})
        digest, got = hashlib.sha256(), 0
        with urllib.request.urlopen(req, timeout=60) as response, open(archive, "wb") as output:
            address = urlparse(response.geturl())
            if address.scheme != "https" or address.hostname not in ("github.com", "release-assets.githubusercontent.com",
                                                                       "objects.githubusercontent.com"):
                raise ValueError("The Builder ZIP download left GitHub.")
            while chunk := response.read(1 << 20):
                got += len(chunk)
                if got > size:
                    raise ValueError("The Builder ZIP is larger than GitHub reported.")
                digest.update(chunk)
                output.write(chunk)
        if got != size or digest.hexdigest() != expected_hash:
            raise ValueError("The Builder ZIP did not match GitHub's SHA-256 and size.")
        staged = os.path.join(temp, "unpacked")
        extract_builder(archive, staged)
        needed = ("WondershotBuilder.dll", "WondershotBuilder.runtimeconfig.json", "tools/python/python.exe", "tools/nx2/make_wonder.py")
        if (builder_release(staged) != tag or installed_version(os.path.join(staged, "tools")) != tag
                or not all(os.path.isfile(os.path.join(staged, p)) for p in needed)):
            raise ValueError("The ZIP does not contain a complete Builder for %s." % tag)
        dest = os.path.join(root, "%s-%s" % (tag, os.path.basename(temp).removeprefix("download-")))
        os.rename(staged, dest)
    say("@@builder-ready", os.path.join(dest, "WondershotBuilder.exe"))


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
    raise OSError("A build tool could not be downloaded (%s). Check the internet connection and try again." % last)


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
        try:
            download(urls, sha, size, zpath, lambda f: progress("tools", (base + f * size) / total))
        except OSError as error:
            fail(str(error))
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


def build(game, out, work, tools, jobs, update=None, files="link"):
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
    error = romfs_boot_error(romfs, dlc)
    if error:
        fail(error)
    layered = needs_layering(romfs, dlc)
    if layered:
        say("the romfs has no Switch 2 heap definition and the add-on has the Switch 2 Edition's files: they go over it")
    progress("dump", 1.0)
    pairs = [(src, os.path.join(out, name)) for name, src in (("romfs", romfs), ("dlc", dlc))
             if src and not (layered and name == "romfs")]
    if files == "copy" or layered:
        check_space(out, pairs if files == "copy" else [],
                    layer_space(os.path.join(out, "romfs"), romfs, dlc, files) if layered else 0)

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
    if files == "copy":
        stage("files", "Copying your game's files into the folder")
        copy_game_files(out, pairs)
    if layered:
        stage("layer", "Putting the Switch 2 Edition's files over your romfs")
        layer_romfs(os.path.join(out, "romfs"), romfs, dlc, link=files != "copy")
    assemble(out, work, tools, dlc, romfs, exefs, files, layered)
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


def lp(path):
    """A path Windows takes beyond 260 characters (the game's romfs has long ones)"""
    path = os.path.abspath(path)
    return path if path.startswith("\\\\?\\") or len(path) < 240 else "\\\\?\\" + path


def is_link(path):
    return os.path.islink(path) or os.path.isjunction(path)


def copy_plan(src, dst):
    """[(source file, its copy, size)] still to copy from src into dst: a file there of the same size and not older is kept, so
    a build again copies what changed (and a stopped copy goes on where it was)"""
    todo = []
    linked = is_link(dst)   # (a junction of an earlier build reads the dump itself: nothing is there yet, all is to be copied)
    for base, _, names in os.walk(lp(src)):
        rel = os.path.relpath(base, lp(src))
        for n in names:
            f = os.path.join(base, n)
            t = os.path.join(lp(dst), n if rel == "." else os.path.join(rel, n))
            try:
                st = os.stat(f)
                if not linked and os.path.isfile(t) and os.stat(t).st_size == st.st_size and os.stat(t).st_mtime >= st.st_mtime - 2:
                    continue
                todo.append((f, t, st.st_size))
            except OSError:
                todo.append((f, t, 0))
    return todo


def existing_parent(path):
    """path, or the nearest folder above it that is there"""
    path = os.path.abspath(path)
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def free_bytes(path):
    """The free space of the drive path is (or would be) on"""
    return shutil.disk_usage(existing_parent(path)).free


def layer_plan(base, addon):
    """{place in the romfs: source file} of base with the add-on over it: where both have a file, the add-on's copy is the one"""
    plan = {}
    for root in (base, addon):
        top = lp(root)
        for folder, _, names in os.walk(top):
            rel = os.path.relpath(folder, top)
            for n in names:
                plan[n if rel == "." else os.path.join(rel, n)] = os.path.join(folder, n)
    return plan


def can_hard_link(dst, *sources):
    try:
        dev = os.stat(existing_parent(dst)).st_dev
        return all(os.stat(src).st_dev == dev for src in sources)
    except OSError:
        return False


def layer_space(dst, base, addon, files):
    """Bytes layer_romfs may write: none when it hard-links (link mode, the dump on the game folder's drive)"""
    if files != "copy" and can_hard_link(dst, base, addon):
        return 0
    total = 0
    for src in layer_plan(base, addon).values():
        try:
            total += os.stat(src).st_size
        except OSError:
            pass
    return total


def layer_romfs(dst, base, addon, link=True):
    """The game folder's romfs as a real folder: base (the Switch 1 game's romfs) with the add-on's files over it, as a .nup's
    romfs is. link: each file a hard link to the dump's own (no space, read in place), copied when it cannot be (another drive);
    otherwise copied. A file already there and the same is kept, so a build again only does what changed; files an earlier
    build left that are no longer in it go. Nothing of the dump is written: a link is only removed, never written through."""
    if os.path.lexists(dst) and is_link(dst):
        os.rmdir(dst)   # (a junction of an earlier build: only the link goes)
    plan = layer_plan(base, addon)
    top = lp(dst)
    os.makedirs(top, exist_ok=True)
    for folder, _, names in os.walk(top):
        rel = os.path.relpath(folder, top)
        for n in names:
            if (n if rel == "." else os.path.join(rel, n)) not in plan:
                os.remove(os.path.join(folder, n))
    stats = {rel: os.stat(src) for rel, src in plan.items()}
    total = sum(st.st_size for st in stats.values()) or 1
    done = last = linked = copied = 0
    for rel, src in plan.items():
        t = os.path.join(top, rel)
        st = stats[rel]
        try:
            ts = os.stat(t)
        except OSError:
            ts = None
        if ts is None or not (os.path.samestat(st, ts) or (ts.st_size == st.st_size and ts.st_mtime >= st.st_mtime - 2)):
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if ts is not None:
                os.remove(t)
            try:
                if not link:
                    raise OSError("copy mode")
                os.link(src, t)
                linked += 1
            except OSError:
                shutil.copyfile(src, t + ".part")
                os.replace(t + ".part", t)
                try:
                    shutil.copystat(src, t)
                except OSError:
                    pass
                copied += 1
        done += st.st_size
        if done - last >= (256 << 20) or done == total:
            last = done
            progress("layer", done / total)
    say("romfs: %d files, the add-on's over the game's (%d linked, %d copied, the rest kept)" % (len(plan), linked, copied))
    progress("layer", 1.0)


def check_space(out, pairs, extra=0):
    """Stops before the long steps when copying the game's files would not fit: [(source, its place in the folder)], and extra
    bytes more (the romfs layer_romfs makes)"""
    need = extra + sum(size for src, dst in pairs for _, _, size in copy_plan(src, dst))
    free = free_bytes(out)
    if need + (1 << 30) > free:
        fail("Copying your game's files into %s needs about %.1f GB, and %.1f GB are free on that drive. Choose a folder on "
             "a drive with room, or keep the files where they are." % (out, need / 1e9, free / 1e9))
    say("copying the game's files will take about %.1f GB" % (need / 1e9))


def copy_game_files(out, pairs):
    """romfs and dlc as real folders in the game folder (a junction of an earlier build goes first: only the link, never what
    it points at), copied from where the dump is. Big files go through a .part file, so a stop leaves none half made"""
    for src, dst in pairs:
        if os.path.lexists(dst) and is_link(dst):
            os.rmdir(dst)
        os.makedirs(lp(dst), exist_ok=True)
        for base, _, names in os.walk(lp(dst)):   # (a copy stopped before: its half-made files go)
            for n in names:
                if n.endswith(".part"):
                    os.remove(os.path.join(base, n))
    plan = [(pair, item) for pair in pairs for item in copy_plan(*pair)]
    total = sum(item[2] for _, item in plan) or 1
    done, last = 0, 0
    for _, (f, t, size) in plan:
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copyfile(f, t + ".part")
        os.replace(t + ".part", t)
        try:
            shutil.copystat(f, t)
        except OSError:
            pass
        done += size
        if done - last >= (64 << 20) or done == total:
            last = done
            progress("files", done / total)
            say("copied %.1f of %.1f GB" % (done / 1e9, total / 1e9))
    progress("files", 1.0)


def junction(link, target):
    """A directory junction (no administrator needed): the game folder reads the player's dump where it is"""
    if os.path.lexists(link):
        if os.path.islink(link) or os.path.isjunction(link):
            os.rmdir(link)   # (a junction of an earlier build: only the link goes, never what it points at)
        else:
            return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, text=True,
                       encoding="oem", errors="replace",   # (mklink speaks the console's OEM code page, not UTF-8)
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def assemble(out, work, tools, dlc, romfs, exefs, files="link", layered=False):
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
    for n in ("renhdrum.dll",):   # (optional: RenHDrum's DualSense haptics. Without it every pad keeps its plain motors)
        for d in (build_dir, os.path.join(ROOT, "third_party", "renhdrum"), os.path.join(tools, "third_party", "renhdrum")):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(out, n))
                break
    # the game's files: read where they are (a junction), or already copied into the folder (files == "copy")
    stamp = os.path.join(out, "wondershot_version.txt")
    copied_before = layered_before = False
    try:
        with open(stamp, encoding="utf-8") as f:
            words = f.read().split()
            copied_before, layered_before = "files=copy" in words, "romfs=layered" in words
    except OSError:
        pass
    for name, target in (("romfs", romfs), ("dlc", dlc)):
        if files == "copy" or (layered and name == "romfs"):   # (the layered romfs is a real folder made by layer_romfs)
            continue
        link = os.path.join(out, name)
        ours = copied_before or (layered_before and name == "romfs")
        if ours and os.path.isdir(link) and not is_link(link):   # (our own copy of an earlier build: now to be linked)
            say("the copy of the game's %s is removed: the folder reads your dump in place now" % name)
            shutil.rmtree(lp(link))
        if target is None:
            continue
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
        f.write("version=%s\nbuilt=%s\ngame=%s\nfiles=%s\n" % (installed_version(tools), time.strftime("%Y-%m-%d %H:%M"), GAME_PATH[0], files))
        if layered:
            f.write("romfs=layered\n")


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
        sources = [name + ".cpp" for name in SPIRV_CROSS_SOURCES]
        licenses = ("LICENSE", "LICENSES")
        with tempfile.TemporaryDirectory(prefix="sc-", dir=d) as src:
            # Only extract the CLI sources and their headers. The archive's
            # versioned folder and nested test fixtures can exceed MAX_PATH.
            with zipfile.ZipFile(z) as archive:
                for member in archive.infolist():
                    parts = member.filename.split("/")
                    if len(parts) != 2 or member.is_dir():
                        continue
                    name = parts[1]
                    if name not in sources and name not in licenses and not name.endswith((".h", ".hpp")):
                        continue
                    with archive.open(member) as packed, open(lp(os.path.join(src, name)), "wb") as unpacked:
                        shutil.copyfileobj(packed, unpacked)
            os.remove(z)
            cxx = os.path.abspath(os.path.join(tools, "llvm-mingw", "bin", "clang++.exe"))
            r = subprocess.run([cxx, "-std=c++17", "-O1", "-static", "-o", "spirv-cross.exe"] + sources,
                               cwd=src, capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                raise HdrSkipped("SPIRV-Cross did not compile: %s" % (r.stderr.strip().splitlines() or ["?"])[-1])
            for lic in licenses:
                p = os.path.join(src, lic)
                if os.path.isfile(lp(p)):
                    shutil.copyfile(lp(p), lp(os.path.join(d, "SPIRV-Cross-" + lic + ".txt")))
            os.replace(lp(os.path.join(src, "spirv-cross.exe")), lp(cross))
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
    env["HOS_WONDER_HDR_BUILD"] = "1"
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
    except (HdrSkipped, OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as why:
        say("@@warn", "The game build is complete. The HDR shaders could not be made (%s). Press Build again to retry." % why)
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
    ap.add_argument("--update-builder")
    ap.add_argument("--game-files", choices=("link", "copy"), default="link",
                    help="link: the game folder reads the dump where it is; copy: romfs and dlc are copied into the folder")
    ap.add_argument("--hdr-only", action="store_true", help="only make shader_overrides/hdr for the --out folder (built already)")
    ap.add_argument("--update-to")
    ap.add_argument("--update-url")
    a = ap.parse_args()
    tools = a.tools or os.environ.get("WONDERSHOT_TOOLS") or default_tools()
    work = a.work or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WondershotBuilder", "work")
    if a.check_update:
        check_update(tools)
        return 0
    if a.update_builder:
        try:
            install_builder(os.path.abspath(tools), a.update_builder)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            fail("The Builder update could not be installed: %s" % error)
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
    build(game, os.path.abspath(a.out), os.path.abspath(work), os.path.abspath(tools), jobs, update, a.game_files)
    return 0


def guarded():
    """main(), with a crash said as an @@error: its traceback is in the log, and the app shows its last lines, not a bare exit code"""
    try:
        return main()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as error:   # noqa: BLE001 (anything: the player gets the words, the log gets the traceback)
        import traceback
        text = traceback.format_exc()
        print(text, file=sys.stderr, flush=True)
        hint = " The PC ran out of memory: close other programs and build again." if isinstance(error, MemoryError) else ""
        say("@@error", "The build hit an unexpected problem: %s: %s.%s The last lines of the log:\n%s"
            % (type(error).__name__, error, hint, "\n".join(text.strip().splitlines()[-8:])))
        return 1


if __name__ == "__main__":
    sys.exit(guarded())
