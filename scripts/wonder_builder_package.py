"""The Wondershot Builder's folder and zip: the app (builder/WondershotBuilder) with the sources its build reads under tools\\ and the
Python that runs them. No game data is involved. Python's standard library only.

    python -I scripts/wonder_builder_package.py <out folder> --publish <dotnet publish folder> [--zip <file>] [--version <x.y.z>] [--renhdrum <dll>]

The publish folder is `dotnet publish builder/WondershotBuilder -c Release` (self-contained: the player installs nothing). The folder
made is WondershotBuilder.exe, its files, and tools\\ with the gpu, host, nx2, scripts, third_party and assets the build needs,
tools.lock, and tools\\python (tools.lock's own, fetched and checked here). The compiler and libraries (llvm-mingw, cpm, the
prebuilt third-party files: about 230 MB) are not in it: nx2/make_wonder.py fetches them on the player's PC the first time it builds,
each checked against tools.lock's SHA-256.
"""
import argparse
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # (python -I leaves the script's folder off the path)
import tools  # noqa: E402
from helpers import ROOT  # noqa: E402

# (what the player's build reads, as in a checkout: nx2/build.py and nx2/lift.py reach gpu, host, third_party and assets by their
# place beside nx2; builder/setup/wonder.ico is the exe's icon)
SOURCES = ("gpu", "host", "nx2", "scripts", "third_party", "assets/profiles", "assets/pipeline_states", "builder/setup")
FILES = ("tools.lock", "requirements.txt", "LICENSE", "README.md")
SKIP_DIRS = {"__pycache__", ".git", "target", "work", "build", "tests", ".venv", "node_modules"}
SKIP_SUFFIX = (".pyc", ".pyo", ".obj", ".o", ".pdb", ".ilk", ".exe", ".dll", ".so")
# (built on the player's PC by third_party/a64-kit/lift/build_emit.py the first time the lift runs: a checkout's copy stays out)
SKIP_NAMES = {"a64emit.dll", "a64emit.dll.sha1"}


def copy_tree(src, dst):
    count = 0
    for d, dirs, names in os.walk(src):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        rel = os.path.relpath(d, src)
        for n in names:
            if n.endswith(SKIP_SUFFIX) or n in SKIP_NAMES:
                continue
            target = os.path.join(dst, rel, n) if rel != "." else os.path.join(dst, n)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(d, n), target)
            count += 1
    return count


def package(a):
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(a.publish, out)
    dest = os.path.join(out, "tools")
    total = 0
    for rel in SOURCES:
        src = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isdir(src):
            print("error: %s is not in this checkout" % rel, file=sys.stderr)
            return 1
        total += copy_tree(src, os.path.join(dest, *rel.split("/")))
    for f in FILES:
        if os.path.isfile(os.path.join(ROOT, f)):
            shutil.copyfile(os.path.join(ROOT, f), os.path.join(dest, f))
    # (the Python that runs the build: tools.lock's, its size and SHA-256 checked)
    stage = os.path.join(out, ".stage")
    os.makedirs(stage)
    tools.install(stage, [tools.named(tools.load(), "python")])
    shutil.move(os.path.join(stage, "LongshotBuilder", "tools", "python"), os.path.join(dest, "python"))
    shutil.rmtree(stage)
    dll = getattr(a, "renhdrum", None)
    if dll:   # (scripts/renhdrum.py build: where nx2/make_wonder.py's assemble looks, so the player's game folder gets it)
        import renhdrum
        with open(dll, "rb") as f:
            bad = renhdrum.problems(f.read(), "windows")   # (a Linux library under the name: a "Bad Image" box on Windows)
        if bad:
            print("error: %s: %s" % (dll, "; ".join(bad)), file=sys.stderr)
            return 1
        os.makedirs(os.path.join(dest, "third_party", "renhdrum"), exist_ok=True)
        shutil.copyfile(dll, os.path.join(dest, "third_party", "renhdrum", "renhdrum.dll"))
    for stamp in (os.path.join(dest, "version.txt"), os.path.join(out, "builder_version.txt")):
        with open(stamp, "w", encoding="utf-8", newline="\n") as f:
            f.write((a.version or "dev") + "\n")
    print("package folder: %s (%d source files)" % (out, total))
    if a.zip:
        make_zip(out, a.zip)
    return 0


def make_zip(folder, path):
    root = os.path.basename(folder.rstrip("\\/"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for d, _, names in os.walk(folder):
            for n in sorted(names):
                full = os.path.join(d, n)
                z.write(full, os.path.join(root, os.path.relpath(full, folder)))
    print("%s: %d MB" % (path, os.path.getsize(path) >> 20))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    p.add_argument("--publish", required=True)
    p.add_argument("--zip")
    p.add_argument("--version")
    p.add_argument("--renhdrum", help="renhdrum.dll (scripts/renhdrum.py build): RenHDrum's DualSense haptics, in the package")
    return package(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
