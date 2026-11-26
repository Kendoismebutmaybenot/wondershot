"""High-FPS vertical camera and keep-jump regressions. All fixtures are synthetic; no game data.

python -I -B tests/test_wonder_vertical_camera.py --cc <C compiler>
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "tests")]
import oot_patches
from srccut import block

RUN_ALL_ARGS = ["--cc", "gcc"]

PREAMBLE = r"""
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <assert.h>
typedef struct { uint64_t x[32]; } Ctx;
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
#define AcquireSRWLockExclusive(x) ((void)0)
#define ReleaseSRWLockExclusive(x) ((void)0)
#define hos_log(...) ((void)0)
static uint32_t hos_frame_seconds_bits;
static uint32_t recomp_load32(Ctx*c,uint64_t a){uint32_t v;memcpy(&v,(void*)a,4);return v;}
static uint64_t recomp_load64(Ctx*c,uint64_t a){uint64_t v;memcpy(&v,(void*)a,8);return v;}
static uint8_t recomp_load8(Ctx*c,uint64_t a){return *(uint8_t*)a;}
static void recomp_store32_sp(Ctx*c,uint64_t a,uint32_t v){memcpy((void*)a,&v,4);}
static void recomp_store8_sp(Ctx*c,uint64_t a,uint8_t v){*(uint8_t*)a=v;}
static void ptr(void*a,void*b){memcpy(a,&b,8);}
static void integer(void*a,uint32_t v){memcpy(a,&v,4);}
static void number(void*a,float v){memcpy(a,&v,4);}


#include <math.h>
"""

CAMERA_CASES = r"""int main(void){
 Ctx c={0};uint8_t node[1024]={0},pcam[512]={0};uint64_t n=(uint64_t)node,p=(uint64_t)pcam;
 float before=100.0f,speed=0.0f;uint32_t ybits,sbits;memcpy(&ybits,&before,4);memcpy(&sbits,&speed,4);
 const float rates[]={240,144,120,90};
 for(int j=0;j<4;j++){
  float r=60.0f/rates[j];float native=1.5f*r*(1.0f-powf(.5f,r));
  for(int dir=-1;dir<=1;dir+=2){
   number(node+0x104,r);number(node+0xac,dir*1.5f*r);number(node+0xf4,0);
   number(pcam+0x2c,before+dir*native);number(pcam+0x38,120.0f+dir*native);
   hos_wonder_camera_scroll_after(&c,n,p,ybits,sbits);
   float dy=wonder_camera_load_float(&c,p+0x2c)-before;
   assert(fabsf(dy*rates[j]-dir*45.0f)<0.002f);
   assert(fabsf(wonder_camera_load_float(&c,p+0x38)-(120.0f+dir*.75f*r))<.0001f);
  }
 }
 for(int gate=1;gate<3;gate++){
  number(node+0x104,gate==1?1.0f:.25f);number(node+0xac,gate==2?0.0f:.375f);
  number(node+0xf4,0);number(pcam+0x2c,100.03f);number(pcam+0x38,120.03f);
  hos_wonder_camera_scroll_after(&c,n,p,ybits,sbits);
  assert(wonder_camera_load_float(&c,p+0x2c)==100.03f);
 }
 assert(fabsf(wonder_camera_scroll_delta(100.0f,.25f)-.1875f)<.00001f);
 puts("PASS: saturated vertical tracking is 45 units/sec at 90/120/144/240 FPS in both directions; target stays aligned; 60-FPS/unsaturated movement unchanged; descending correction continues after the float ends");
}
"""

FLOAT_CASES = r"""int main(void) {
 uint8_t node[256]={0},link[16]={0},actor[1024]={0},impl[4096]={0},pc[8192]={0};
 uint8_t comps[512]={0},bb[1024]={0},flags[16]={0};uint32_t ints[16]={0};Ctx c={0};
 ptr(node+8,link);ptr(link+8,actor);ptr(actor+0x1f0,impl);ptr(actor+0x1f8,bb);
 ptr(impl+0x210,comps);integer(impl+0x208,0x25);ptr(comps+0x120,pc);
 integer(bb+0x198,16);ptr(bb+0x1a0,flags);integer(bb+0xa8,16);ptr(bb+0xb0,ints);
 integer(pc+0x31c,1);integer(pc+0x2ac,2);integer(pc+0x320,3);integer(pc+0x380,4);integer(node+0x64,5);
 flags[2]=flags[3]=1;ints[4]=1;ints[5]=6;node[0x18]=2;
 number(&hos_frame_seconds_bits,1.0f/240.0f);number(impl+0x32c,30.0f);
 uint64_t n=(uint64_t)node;
 hos_wonder_float_gravity(&c,n,0);assert(!flags[1]); /* no previous float: cannot initiate one */
 flags[1]=1;hos_wonder_float_gravity(&c,n,1);
 for(int reason=-1;reason<9;reason++){
  flags[1]=0;flags[2]=flags[3]=1;ints[4]=1;ints[5]=6;node[0x18]=2;
  number(impl+0x32c,30.0f);number(&hos_frame_seconds_bits,1.0f/240.0f);
  if(reason==0)flags[2]=0;if(reason==1)flags[3]=0;if(reason==2)ints[4]=0;
  if(reason==3)ints[5]=0;if(reason==4)number(impl+0x32c,-1.0f);
  if(reason==5)number(&hos_frame_seconds_bits,1.0f/60.0f);
  if(reason==6)node[0x18]=0;if(reason==7)number(impl+0x32c,50.0f);
  if(reason==8)integer(pc+0x31c,0xffffffff);
  hos_wonder_float_gravity(&c,n,0);
  assert(flags[1]==(reason==-1));
  assert(wonder_camera_load_float(&c,(uint64_t)(impl+0x32c))==(reason==-1?39.1f:reason==4?-1.0f:reason==7?50.0f:30.0f));
 }
 integer(pc+0x31c,1);flags[1]=0;hos_wonder_float_gravity(&c,n,1);
 flags[2]=flags[3]=1;ints[4]=1;ints[5]=6;node[0x18]=2;number(impl+0x32c,30.0f);
 hos_wonder_float_gravity(&c,n,0);assert(!flags[1]);
 puts("PASS: active float restored; inactive float, wrong area/mode/gravity, falling, 60 FPS, inactive node, fast rise and invalid key unchanged");
}
"""

def check_patches():
    for head, patch, calls in (
        (oot_patches.WONDER_SCROLL_HEAD, oot_patches.patch_wonder_camera_follow,
         ("hos_wonder_camera_scroll_owner(c,", "hos_wonder_camera_scroll_after(c,")),
        (oot_patches.WONDER_FLOAT_HEAD, oot_patches.patch_wonder_float,
         ("hos_wonder_float_gravity(c, node, 0);", "hos_wonder_float_gravity(c, node, 1);")),
    ):
        fixture = '#include "a64.h"\n' + head + '    f_8043d320(c);\n    return;\n}\n'
        out = patch(fixture)
        assert all(out.count(call) == 1 for call in calls), "missing or duplicate hook"
        assert patch(out) == out, "patch is not idempotent"
        assert patch('#include "a64.h"\n') == '#include "a64.h"\n', "unrelated file changed"
        assert out.index(calls[0]) < out.index(calls[1]), "hook order changed"
    print("PASS: camera and float wrappers are ordered, unique and idempotent")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    check_patches()
    source = (ROOT / "host/nn_vi.c").read_text(encoding="utf-8")
    common = block(source, "static float wonder_camera_load_float(")
    camera = common + "\n" + block(source, "static float wonder_camera_scroll_delta(")
    camera += "\n" + block(source, "void hos_wonder_camera_scroll_after(")
    begin = source.index("static SRWLOCK wonder_float_lock")
    end = source.index("volatile uint64_t hos_wonder_step_probe", begin)
    gravity = common + "\n" + source[begin:end]
    with tempfile.TemporaryDirectory(prefix="wonder-vertical-") as directory:
        for name, functions, cases in (("camera", camera, CAMERA_CASES), ("float", gravity, FLOAT_CASES)):
            src = Path(directory) / (name + ".c")
            exe = Path(directory) / (name + ".exe")
            src.write_text(PREAMBLE + functions + "\n" + cases, encoding="utf-8")
            subprocess.run([args.cc, str(src), "-o", str(exe), "-lm"], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
