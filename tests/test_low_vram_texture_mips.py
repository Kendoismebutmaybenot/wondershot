"""Exercise Low-end mode and texture mip limits without launching the game."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default=os.environ.get("CXX", "clang++"))
    p.add_argument("--headers", default=os.environ.get("LONGSHOT_VULKAN_HEADERS"))
    p.add_argument("--sanitize", default="")
    a = p.parse_args()
    source = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8-sig")
    mip = block(source, "{   // huge textures leave out their top levels:")
    policy = block(source, "bool low_vram_texture_mips() {")
    helpers = "\n".join(block(source, marker) for marker in (
        "bool is_bc(VkFormat f)", "bool is_astc(VkFormat f)", "uint64_t texture_level_units("))
    fixture = r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vulkan/vulkan.h>
#define _Static_assert static_assert
#include "gpu/render/rx_nvn.h"
#include "gpu/vk/compat/longshot_env.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL:%d %s\n",__LINE__,#x); std::exit(1); } } while(0)
struct Texture {
    uint32_t width, height, depth = 1, levels, layers = 1, skip = 0;
    bool sparse = false;
    VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
    VkImageType type = VK_IMAGE_TYPE_2D;
};
struct { bool sparse_images = false; VkPhysicalDevice physical{}; } dev;
struct { int low_end_mode = 0; } opts;
void logf(const char*, ...) {}
@HELPERS@
extern "C" VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceSparseImageFormatProperties(
        VkPhysicalDevice, VkFormat, VkImageType, VkSampleCountFlagBits, VkImageUsageFlags, VkImageTiling,
        uint32_t* n, VkSparseImageFormatProperties*) { *n = 0; }
@POLICY@
void trim(Texture& x, const nvn_tex* t, bool astc = true, bool depth = false,
          int bpb = 4, int bw = 1, int bh = 1) {
    const nvn_texdesc& d = t->d;
    @MIP@
}
void check_image(const Texture& x, int skip, int width, int levels) {
    CHECK(x.skip == (uint32_t)skip);
    CHECK(x.width == (uint32_t)width && x.height == (uint32_t)width);
    CHECK(x.levels == (uint32_t)levels);
}
int main(int argc, char** argv) {
    CHECK(argc == 9);
    opts.low_end_mode = std::atoi(argv[1]);
    nvn_tex t{}; t.d.samples = 1;
    Texture single{3072,3072,1,12}; trim(single,&t);
    check_image(single,std::atoi(argv[2]),std::atoi(argv[3]),std::atoi(argv[4]));
    Texture array{1365,1365,1,11,90}; trim(array,&t);
    check_image(array,std::atoi(argv[5]),std::atoi(argv[6]),std::atoi(argv[7]));
    CHECK(array.layers == 90);
    Texture ui{512,512,1,10}; trim(ui,&t); check_image(ui,0,512,10);
    Texture last_mip{3072,3072,1,1}; trim(last_mip,&t); check_image(last_mip,0,3072,1);
    Texture target{4096,4096,1,13}; trim(target,&t,false); check_image(target,0,4096,13);
    Texture depth{12288,12288,1,1}; trim(depth,&t,false,true,2); check_image(depth,0,12288,1);
    // Changing the menu during a session must leave the renderer's current limits in force.
    opts.low_end_mode = !opts.low_end_mode;
    Texture next{3072,3072,1,12}; trim(next,&t);
    check_image(next,std::atoi(argv[2]),std::atoi(argv[3]),std::atoi(argv[4]));
    std::printf("PASS %s\n",argv[8]);
}
'''.replace("@HELPERS@", helpers).replace("@POLICY@", policy).replace("@MIP@", mip)
    original = (0, 3072, 12, 0, 1365, 11)
    reduced = (2, 768, 10, 1, 682, 10)
    cases = [
        ("off", 0, {}, original),
        ("on", 1, {}, reduced),
        ("dimension-override", 1, {"RX_VK_TEX_MAX_DIM": "2048"}, (1, 1536, 11, 0, 1365, 11)),
        ("threshold-override", 1, {"RX_VK_TEX_SKIP_MB": "64"}, (0, 3072, 12, 1, 682, 10)),
        ("aggressive-overrides", 1, {"RX_VK_TEX_MAX_DIM": "512", "RX_VK_TEX_SKIP_MB": "2"},
         (3, 384, 9, 2, 341, 9)),
        ("threshold-with-mode-off", 0, {"RX_VK_TEX_SKIP_MB": "2"}, (1, 1536, 11, 0, 1365, 11)),
        ("environment-on-with-mode-off", 0, {"RX_VK_LOW_VRAM_MIPS": "on"}, original),
    ]
    for value in ("0", "off", "false", "no", "OFF", "FaLsE", " no \t", ""):
        cases.append(("disabled-" + repr(value), 1, {"RX_VK_LOW_VRAM_MIPS": value}, original))
    with tempfile.TemporaryDirectory(prefix="low-vram-mips-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture.exe" if os.name == "nt" else "fixture")
        cpp.write_text(fixture, encoding="utf-8")
        cmd = [a.cxx, "-std=c++20", "-O2", "-I", str(ROOT)]
        if a.headers:
            cmd += ["-I", a.headers]
        if a.sanitize:
            cmd += ["-fsanitize=" + a.sanitize, "-fno-omit-frame-pointer"]
        subprocess.run(cmd + [str(cpp), "-o", str(exe)], check=True)
        failed = []
        for name, mode, overrides, expected in cases:
            env = os.environ.copy()
            for key in ("RX_VK_LOW_VRAM_MIPS", "RX_VK_TEX_MAX_DIM", "RX_VK_TEX_MAX_MB", "RX_VK_TEX_SKIP_MB"):
                env.pop(key, None)
            env.update(overrides)
            args = [mode, *expected, name]
            if subprocess.run([str(exe), *map(str, args)], env=env).returncode:
                failed.append(name)
    if failed:
        sys.exit("FAIL %d of %d mip-policy configurations: %s" % (len(failed), len(cases), ", ".join(failed)))
    print("PASS %d mip-policy configurations" % len(cases))


if __name__ == "__main__":
    main()
