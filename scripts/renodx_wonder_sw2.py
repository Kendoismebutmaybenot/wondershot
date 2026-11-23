#!/usr/bin/env python3
"""(Wonder build) RenoDX-style HDR for Mario Wonder (Switch 2 Edition): the SuperWonders HDR (tools/renodx_wonder.py, PR #116)
on the Longshot Wonder renderer.

The game's tone mapper, fragment program 9c39b1dd1e1bad88, adds the bloom to the scene (x = scene * c3[12] + bloom) and maps
each channel with a two-piece rational curve, y = (a*x + b) / (c*x + d), the upper piece (x >= c3[24]) from c3[20..23]. That
curve reaches 1.0 (SDR white) at x1 = (d - b) / (a - c); the game's window texture clipped everything brighter. This copy:
  - grades the scene value first (hdr_grade: exposure, contrast, shadows, saturation, highlight saturation, after RenoDX's
    colorgrade.hlsl), from push constants the renderer writes live (vk_draw.cpp, offset 64: the mesh fallback's words);
    exposure 0 means grading off, the scene untouched;
  - keeps y wherever it is at most 1.0 and writes 1 + 0.25 * (min(x / x1, 48) - 1) above it (hdr_extend).
The scene buffer is float (B10G11R11), the window textures are R11G11B10F with HDR on (host/nvn_native.c), the final copy has
no saturate, and the present pass (gpu/vk/shaders/hdr_encode.comp mode 2) maps the result to paper white / highlights / peak.

    python -I scripts/renodx_wonder_sw2.py --dump <9c39b1dd1e1bad88.frag.spv> --game "C:/Games/Wonder Switch 2"
writes <game>/shader_overrides/hdr/9c39b1dd1e1bad88.frag.spv. The dump comes from the game itself:
RX_VK_DUMP_FRAG=9c39b1dd1e1bad88 (vk_shader.cpp frag_override). Needs spirv-cross and glslc (Vulkan SDK). The game's code
and anything made from it stay on the player's PC: never commit the dump or the output.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROGRAM = "9c39b1dd1e1bad88"
COPY = "b7914ae65792d0c8"   # the final copy, scene buffer -> window texture

# The final copy, made to keep the title's menus SDR: on the Title stage (push flag gameplay 0) it clamps at SDR white, since
# the game's menu art has values past 1.0 (its own HDR mode) that the 8-bit window clipped. Nothing is decoded: the scene
# buffer is linear and the copy writes through an sRGB view, so the float window is linear, as SW1's was.
COPY_DECODE = """
layout(push_constant) uniform HdrPush
{
    layout(offset = 84) float gameplay;  // 0 on the title's menus: kept SDR, as SW1's (their art goes past 1.0 here)
} hdr_pc;
vec3 hdr_decode(vec3 c)
{
    if (!(hdr_pc.gameplay > 0.5))
    {
        c = min(c, vec3(1.0));
    }
    return c;  // (no decode: the scene buffer is linear and the copy writes the window through an sRGB view, as in SW1; a
               // decode here linearised it twice, the oversaturated look SW1 also had)
}
"""


def tool(name):
    for d in filter(None, [os.environ.get("VULKAN_SDK"), "C:/VulkanSDK/1.4.363.0"]):
        for sub in ("Bin", "bin"):
            p = os.path.join(d, sub, name + (".exe" if os.name == "nt" else ""))
            if os.path.isfile(p):
                return p
    p = shutil.which(name)
    if not p:
        sys.exit(f"{name} not found: install the Vulkan SDK (or set VULKAN_SDK)")
    return p


HEADER = """
// ---- HDR (scripts/renodx_wonder_sw2.py) ----
layout(push_constant) uniform HdrPush
{
    layout(offset = 64) float exposure;  // 0: grading off
    float contrast;
    float shadows_exp;  // 2 - Shadows: below 1 lifts, above 1 lowers
    float saturation;
    float highlight_saturation;
    float gameplay;  // 0 on the title's menus (SDR): the final copy clamps at SDR white
} hdr_pc;
const float HDR_SCALE = %(scale)s;  // encoded units per multiple of the white point (hdr_encode.comp kWonderEncodeScale)
const float HDR_XMAX = %(xmax)s;    // brightest scene value kept, in multiples of the white point
float hdr_extend(float y, float x)
{
    if (!(y > 1.0))
    {
        return y;
    }
    float a = uintBitsToFloat(c3.data[20u]), c = uintBitsToFloat(c3.data[21u]);
    float b = uintBitsToFloat(c3.data[22u]), d = uintBitsToFloat(c3.data[23u]);
    float slope = a - c;
    if (!(slope > 1e-6))
    {
        return 1.0;
    }
    float x1 = (d - b) / slope;
    if (!(x1 > 0.0))
    {
        return 1.0;
    }
    return 1.0 + HDR_SCALE * (min(x / x1, HDR_XMAX) - 1.0);
}
vec3 hdr_oklab(vec3 c)
{
    vec3 lms = vec3(0.4122214708 * c.r + 0.5363325363 * c.g + 0.0514459929 * c.b,
                    0.2119034982 * c.r + 0.6806995451 * c.g + 0.1073969566 * c.b,
                    0.0883024619 * c.r + 0.2817188376 * c.g + 0.6299787005 * c.b);
    lms = pow(max(lms, vec3(0.0)), vec3(1.0 / 3.0));
    return vec3(0.2104542553 * lms.x + 0.7936177850 * lms.y - 0.0040720468 * lms.z,
                1.9779984951 * lms.x - 2.4285922050 * lms.y + 0.4505937099 * lms.z,
                0.0259040371 * lms.x + 0.7827717662 * lms.y - 0.8086757660 * lms.z);
}
vec3 hdr_unoklab(vec3 l)
{
    vec3 lms = vec3(l.x + 0.3963377774 * l.y + 0.2158037573 * l.z,
                    l.x - 0.1055613458 * l.y - 0.0638541728 * l.z,
                    l.x - 0.0894841775 * l.y - 1.2914855480 * l.z);
    lms = lms * lms * lms;
    return vec3(4.0767416621 * lms.x - 3.3077115913 * lms.y + 0.2309699292 * lms.z,
                -1.2684380046 * lms.x + 2.6097574011 * lms.y - 0.3413193965 * lms.z,
                -0.0041960863 * lms.x - 0.7034186147 * lms.y + 1.7076147010 * lms.z);
}
vec3 hdr_grade(vec3 x)
{
    if (!(hdr_pc.exposure > 0.0))
    {
        return x;
    }
    const float MID = 0.18;
    x = max(x, vec3(0.0)) * hdr_pc.exposure;
    float y = dot(x, vec3(0.2126, 0.7152, 0.0722));
    if (y > 1e-6)
    {
        float yc = MID * pow(y / MID, hdr_pc.contrast);
        float ys = mix(yc, MID * pow(yc / MID, hdr_pc.shadows_exp), 1.0 - smoothstep(0.0, 0.5, yc));
        x *= ys / y;
    }
    if (hdr_pc.saturation != 1.0 || hdr_pc.highlight_saturation != 1.0)
    {
        float yn = dot(x, vec3(0.2126, 0.7152, 0.0722));
        vec3 lab = hdr_oklab(x);
        lab.yz *= hdr_pc.saturation * mix(1.0, hdr_pc.highlight_saturation, smoothstep(0.35, 1.5, yn));
        x = max(hdr_unoklab(lab), vec3(0.0));
    }
    return x;
}
"""


def fail(why):
    sys.exit(f"{why}: has the game's shader changed? (expected program {PROGRAM})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True, help=f"the game's {PROGRAM}.frag.spv (RX_VK_DUMP_FRAG)")
    ap.add_argument("--game", required=True, help="the game folder (beside wonder.exe)")
    ap.add_argument("--scale", default="0.25")
    ap.add_argument("--xmax", default="48.0")
    ap.add_argument("--copy-dump", help=f"the game's {COPY}.frag.spv: also write the decoding final copy")
    ap.add_argument("--keep-glsl", help="also write the patched GLSL here (game-derived: keep it off the repository)")
    a = ap.parse_args()
    glsl = subprocess.run([tool("spirv-cross"), "--vulkan-semantics", a.dump], check=True, capture_output=True,
                          text=True).stdout
    lines = glsl.split("\n")
    # The three scene values: those compared with the curve's threshold, c3[24].
    scene = re.findall(r"bool _\d+ = !\((_\d+) < c3_1\.data\[24u\]\);", glsl)
    if len(scene) != 3:
        fail(f"{len(scene)} threshold compares")
    decl = {}
    for i, l in enumerate(lines):
        m = re.match(r"^(\s*)(?:precise )?float (_\d+) = (.+);$", l)
        if m and m.group(2) in scene:
            decl[m.group(2)] = i
    if len(decl) != 3:
        fail("scene value declarations not found")
    first, last = min(decl.values()), max(decl.values())
    # Between the first and the last scene value: float declarations (their inputs) and the threshold bools. The floats go
    # first, so all three scene values exist before any is used, then they are graded as one vec3.
    block = lines[first:last + 1]
    floats = [l for l in block if re.match(r"^\s*(?:precise )?float _\d+ = ", l)]
    bools = [l for l in block if re.match(r"^\s*bool _\d+ = ", l)]
    if len(floats) + len(bools) != len(block):
        fail("unexpected statements between the scene values")
    bool_names = {re.match(r"^\s*bool (_\d+)", l).group(1) for l in bools}
    for l in floats:
        if any(re.search(rf"\b{b}\b", l) for b in bool_names):
            fail("a scene input reads a threshold result")
    ind = re.match(r"^(\s*)", block[0]).group(1)
    out = []
    for l in floats:
        m = re.match(r"^(\s*)(?:precise )?float (_\d+) = (.+);$", l)
        if m.group(2) in scene:
            out.append(f"{m.group(1)}precise float {m.group(2)}_raw = {m.group(3)};")
        else:
            out.append(l)
    out.append(f"{ind}vec3 hdr_graded = hdr_grade(vec3({scene[0]}_raw, {scene[1]}_raw, {scene[2]}_raw));")
    out += [f"{ind}float {s} = hdr_graded.{c};" for s, c in zip(scene, "xyz")]
    out += bools
    lines[first:last + 1] = out
    glsl = "\n".join(lines)
    # The curve's three results: y = fma(x, a, b) * (1.0 / fma(x, c, d)), the pieces chosen by the threshold bools.
    curve = re.compile(r"^(\s*)precise float (_\d+) = (fma\((_\d+), uintBitsToFloat\(_\d+ \? c3\.data\[20u\].*);$", re.M)
    found = list(curve.finditer(glsl))
    if sorted(m.group(4) for m in found) != sorted(scene):
        fail(f"{len(found)} curve results")
    for m in reversed(found):
        glsl = (glsl[:m.start()] + f"{m.group(1)}float {m.group(2)} = hdr_extend({m.group(3)}, {m.group(4)});"
                + glsl[m.end():])
    glsl = glsl.replace("void main()", HEADER % dict(scale=a.scale, xmax=a.xmax) + "\nvoid main()", 1)
    if a.keep_glsl:
        with open(a.keep_glsl, "w") as f:
            f.write(glsl)
    out_dir = os.path.join(a.game, "shader_overrides", "hdr")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, PROGRAM + ".frag.spv")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, PROGRAM + ".frag"), "w") as f:
            f.write(glsl)
        subprocess.run([tool("glslc"), "-fshader-stage=frag", "--target-env=vulkan1.2", "-O", PROGRAM + ".frag",
                        "-o", os.path.abspath(dst)], check=True, cwd=tmp)
    print(f"wrote {dst} (scale {a.scale}, xmax {a.xmax})")
    if a.copy_dump:
        copy_override(a.copy_dump, out_dir)


def copy_override(dump, out_dir):
    glsl = subprocess.run([tool("spirv-cross"), "--vulkan-semantics", dump], check=True, capture_output=True,
                          text=True).stdout
    reads = list(re.finditer(r"^(\s*)vec4 (_\d+) = texture\([^;]+\);$", glsl, re.M))
    if len(reads) != 1:
        sys.exit(f"the final copy has {len(reads)} texture reads: has the game's shader changed? (expected program {COPY})")
    m = reads[0]
    glsl = glsl[:m.end()] + "\n" + f"{m.group(1)}{m.group(2)}.xyz = hdr_decode({m.group(2)}.xyz);" + glsl[m.end():]
    glsl = glsl.replace("void main()", COPY_DECODE + "\nvoid main()", 1)
    dst = os.path.join(out_dir, COPY + ".frag.spv")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, COPY + ".frag"), "w") as f:
            f.write(glsl)
        subprocess.run([tool("glslc"), "-fshader-stage=frag", "--target-env=vulkan1.2", "-O", COPY + ".frag",
                        "-o", os.path.abspath(dst)], check=True, cwd=tmp)
    print(f"wrote {dst} (the final copy: title menus clamped to SDR)")


if __name__ == "__main__":
    main()
