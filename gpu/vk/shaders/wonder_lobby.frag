#version 450

layout(push_constant) uniform Push { vec4 size; } pc;
layout(location = 0) out vec4 o;

void main() {
    // Anchor the repeat in the centre and size it by height so tiles stay square.
    vec2 p = (gl_FragCoord.xy - pc.size.xy * 0.5) * (7.0 / pc.size.y);
    vec2 cell = floor(p);
    float tones = mod(cell.x + cell.y, 2.0);
    vec2 detail = floor(fract(p) * 8.0);
    float smallChecks = mod(detail.x + detail.y, 2.0);
    float corner = step(4.0, detail.x) * step(4.0, detail.y);
    vec3 base = vec3(0.021, 0.027, 0.020);
    o = vec4(base * (1.0 + 0.18 * tones + 0.08 * corner * smallChecks), 1.0);
}
