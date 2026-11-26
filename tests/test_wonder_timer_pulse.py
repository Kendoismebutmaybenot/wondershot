"""The linked-enemy delay must survive a fractional deadline crossing."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nx2'))
import oot_patches as P

PREAMBLE = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef struct {uint64_t x[32],vreg[32][2];int c,z;} Ctx;
static uint32_t recomp_load32(Ctx*c,uint64_t p){uint32_t v;memcpy(&v,(void*)p,4);return v;}
static int keep(float before,float now,float limit){
 uint8_t timer[64]={0};Ctx ctx={0},*c=&ctx;
 ctx.x[19]=(uint64_t)timer;memcpy(timer+0x24,&before,4);memcpy(&ctx.vreg[1][0],&limit,4);
 ctx.c=now>=limit;ctx.z=now==limit;
'''
AFTER = r'''
 return 0;
L_817fce2c: return 1;
}
static int run(int fps,int delay,int jitter,int corrected){
 float timer=0,held=0;int window=0;
 for(int frame=0;frame<fps*4;frame++){
  float step=60.0f/fps;if(jitter)step*=frame%3==0?1.013f:.993f;
  int pulse=frame==0;
  if(pulse||window){
   float before=timer;timer+=step;
   int remains=corrected?keep(before,timer,(float)delay):timer<=delay;
   if(remains)window=1;else {timer=0;window=pulse;}
  }
  held=window?held+step:0;
  if(held>=delay)return 1;
 }
 return 0;
}
int main(void){
 int rates[]={60,75,120,240},delays[]={30,60,90,120};
 assert(!run(75,60,0,0));assert(!run(240,60,1,0));
 for(int r=0;r<4;r++)for(int d=0;d<4;d++)for(int j=0;j<2;j++)assert(run(rates[r],delays[d],j,1));
 /* Integer steps preserve the existing 60 Hz pulse length, including zero. */
 for(int limit=-1;limit<120;limit++)for(int n=0;n<125;n++)assert(keep(n,n+1,limit)==(n+1<=limit));
 assert(keep(59.9f,60.15f,60));
 assert(!keep(60.15f,60.4f,60));
 assert(keep(60,60,60)); /* pause exactly at the deadline */
 assert(!keep(60.1f,60.1f,60));
 puts("PASS: original blockage reproduced; linked delays fire at 60/75/120/240 FPS with jitter; 60 Hz boundaries and pause preserved");
}
'''


class TimerPulseTests(unittest.TestCase):
    def test_linked_delay(self):
        cc = os.environ.get('WONDER_TEST_CC') or shutil.which('clang') or shutil.which('gcc')
        if not cc:
            self.skipTest('Set WONDER_TEST_CC to a C compiler')
        with tempfile.TemporaryDirectory(prefix='wonder-pulse-') as tmp:
            src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test.exe'
            src.write_text(PREAMBLE + P.WONDER_PULSE_CROSSING + AFTER, encoding='utf-8')
            build = subprocess.run([cc, '-std=c11', '-O2', str(src), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout, end='')

    def test_checked_scoped_and_idempotent(self):
        body = P.WONDER_PULSE_HEAD + 'f_801ff3d0(c);\n' + P.WONDER_PULSE_BRANCH + '\n}\n'
        tail = '\nvoid f_other(Ctx *c) {}\n'
        out = P.patch_wonder_timer_pulse(body + tail)
        self.assertFalse(any(line.startswith("}") for line in P.WONDER_PULSE_CROSSING.splitlines()))
        self.assertTrue(out.endswith(tail))
        self.assertIn(P.WONDER_PULSE_CROSSING, out)
        self.assertEqual(P.patch_wonder_timer_pulse(out), out)
        self.assertEqual(P.patch_wonder_timer_pulse(tail), tail)
        with self.assertRaises(RuntimeError):
            P.patch_wonder_timer_pulse(body.replace('f_801ff3d0', 'f_changed'))
        self.assertIn(P.WONDER_PULSE_CROSSING, P.patch_file(body, 'test.c')[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
