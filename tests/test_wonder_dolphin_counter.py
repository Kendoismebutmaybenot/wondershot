"""Player counter timing used by Dolphin Kick's attack window; no game code."""
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

BODY = (P.WONDER_PLAYER_COUNTER_HEAD + '''
    c->x[19]=c->x[0];
    c->x[9]=recomp_load32(c,c->x[19] + 2204);
''' + P.WONDER_PLAYER_COUNTER_OLD + '''
    c->x[9]+=c->x[8];
    recomp_store32_sp(c,c->x[19] + 2204,c->x[9]);
    c->x[8]+=recomp_load32(c,c->x[19] + 2208);
    recomp_store32_sp(c,c->x[19] + 2208,c->x[8]);
    if(c->x[1]&1) recomp_store32_sp(c,c->x[19] + 2204,0);
    if(c->x[1]&2) recomp_store32_sp(c,c->x[19] + 2208,0);
}
''')
PREAMBLE = r'''
#include "frame_whole.h"
#include <stdio.h>
#include <assert.h>
#include <math.h>
#define A64_NOESC
typedef struct {uint64_t x[32],vreg[32][2];} Ctx;
static FrameWhole clock_state;
static int carry=1;
uint32_t hos_frame_whole(uint64_t at,uint32_t bits){return frame_whole(&clock_state,at,bits,carry);}
static uint32_t recomp_load32(Ctx*c,uint64_t p){uint32_t v;memcpy(&v,(void*)p,4);return v;}
static void recomp_store32_sp(Ctx*c,uint64_t p,uint64_t v){uint32_t b=v;memcpy((void*)p,&b,4);}
'''
MAIN = r'''
static void tick(Ctx*c,uint8_t*pc,float step,int reset){
 uint32_t bits;memcpy(&bits,&step,4);c->vreg[0][0]=bits;c->x[0]=(uint64_t)pc;c->x[1]=reset;f_802ecb20(c);
}
static uint32_t count(Ctx*c,uint8_t*pc,int offset){return recomp_load32(c,(uint64_t)pc+offset);}
int main(void){
 Ctx c={0};_Alignas(16) uint8_t players[4][2304]={0};int rates[]={60,75,120,144,240};
 for(int r=0;r<5;r++){
  memset(&clock_state,0,sizeof clock_state);memset(players,0,sizeof players);int active=0;
  carry=rates[r]!=60;
  for(int frame=0;frame<rates[r];frame++){
   tick(&c,players[0],60.0f/rates[r],0);
   uint32_t a=count(&c,players[0],2204),b=count(&c,players[0],2208);assert(a==b);
   if(a>=8&&a<=18)active++;
  }
  uint32_t frames=count(&c,players[0],2204);assert(frames>=59&&frames<=60);assert(active>0);
  printf("%d FPS: %u game ticks per second; attack window reached\n",rates[r],frames);
 }
 /* Independent player accumulators, followed by each native counter's own reset. */
 memset(&clock_state,0,sizeof clock_state);memset(players,0,sizeof players);carry=1;
 for(int i=0;i<4;i++){tick(&c,players[0],.25f,0);tick(&c,players[1],.5f,0);}
 assert(count(&c,players[0],2204)==1&&count(&c,players[1],2204)==2);
 tick(&c,players[0],1,1);assert(count(&c,players[0],2204)==0&&count(&c,players[0],2208)==2);
 tick(&c,players[0],1,2);assert(count(&c,players[0],2204)==1&&count(&c,players[0],2208)==0);
 tick(&c,players[0],0,0);assert(count(&c,players[0],2204)==1&&count(&c,players[0],2208)==0);
 /* Fractional game-time scaling and variable frame times keep progressing. */
 memset(&clock_state,0,sizeof clock_state);memset(players,0,sizeof players);
 for(int i=0;i<240;i++)tick(&c,players[0],.125f,0);
 assert(count(&c,players[0],2204)==30);
 for(int i=0;i<240;i++)tick(&c,players[1],i%2?.24f:.26f,0);
 assert(count(&c,players[1],2204)>=59&&count(&c,players[1],2204)<=60);
 carry=0;tick(&c,players[2],1,0);assert(count(&c,players[2],2204)==1);
 puts("PASS: both counters, four-rate timing, independent players, resets, pause and time scaling");
}
'''


class DolphinCounterTests(unittest.TestCase):
    def test_fractional_player_ticks(self):
        cc = os.environ.get('WONDER_TEST_CC') or shutil.which('clang') or shutil.which('gcc')
        if not cc:
            self.skipTest('Set WONDER_TEST_CC to a C compiler')
        patched = P.patch_wonder_player_counter('#include "a64.h"\n' + BODY)
        source = patched.replace('#include "a64.h"\n', PREAMBLE) + MAIN
        with tempfile.TemporaryDirectory(prefix='wonder-dolphin-') as tmp:
            src, exe = Path(tmp) / 'test.c', Path(tmp) / 'test.exe'
            src.write_text(source, encoding='utf-8')
            build = subprocess.run([cc, '-std=c11', '-O2', '-I', str(ROOT / 'host'), str(src), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout, end='')

    def test_patch_is_scoped_checked_and_idempotent(self):
        before = '#include "a64.h"\n' + BODY
        tail = '\nvoid f_other(Ctx *c) {}\n'
        out = P.patch_wonder_player_counter(before + tail)
        self.assertIn(P.WHOLE_DECL, out)
        self.assertIn(P.WONDER_PLAYER_COUNTER_NEW, out)
        self.assertTrue(out.endswith(tail))
        self.assertEqual(P.patch_wonder_player_counter(out), out)
        self.assertEqual(P.patch_wonder_player_counter(tail), tail)
        with self.assertRaises(RuntimeError):
            P.patch_wonder_player_counter(before.replace('+ 2208,', '+ 2212,'))
        self.assertIn(P.WONDER_PLAYER_COUNTER_NEW, P.patch_file(before, 'test.c')[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
