"""Regression tests for elapsed-time held-condition waits; contains no game code."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nx2'))
import oot_patches as P

import os
import shutil
CC = os.environ.get('WONDER_TEST_CC') or shutil.which('clang') or shutil.which('gcc')
FIXTURE = r'''
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <assert.h>
#include <stdio.h>
#define A64_NOESC
typedef struct { uint64_t x[32], vreg[32][2]; } Ctx;
static float step;
static uint32_t recomp_load32(Ctx*c,uint64_t p){uint32_t v;memcpy(&v,(void*)p,4);return v;}
static uint64_t recomp_load64(Ctx*c,uint64_t p){uint64_t v;memcpy(&v,(void*)p,8);return v;}
static uint8_t recomp_load8(Ctx*c,uint64_t p){return *(uint8_t*)p;}
static void recomp_store32(Ctx*c,uint64_t p,uint32_t v){memcpy((void*)p,&v,4);}
static void f_801ff4a0(Ctx*c){uint32_t v;memcpy(&v,&step,4);c->vreg[0][0]=v;c->x[0]=123;c->x[30]=456;}
/* Independent model of the existing query contract, including its integer slot. */
static void wonder_held_original(Ctx*c){
 uint64_t n=c->x[0];
 uint32_t v=recomp_load8(c,recomp_load64(c,n+0x28))?recomp_load32(c,n+0x20)+1:0;
 recomp_store32(c,n+0x20,v);
 int32_t limit=(int32_t)recomp_load32(c,recomp_load64(c,n+0x30)&~3ULL);
 *(uint32_t*)(recomp_load64(c,n+0x38)&~3ULL)=(int32_t)v>=limit;
 recomp_store32(c,n+0x18,0x80000000u|(recomp_load32(c,n+0x18)&0x3fffffffu));
}
'''
MAIN = r'''
typedef struct { _Alignas(16) uint8_t node[64]; uint32_t held,limit,result; } Wait;
static void init(Wait*w,int32_t limit){
 memset(w,0,sizeof *w);w->held=1;w->limit=limit;
 uint64_t p=(uint64_t)&w->held;memcpy(w->node+0x28,&p,8);
 p=(uint64_t)&w->limit;memcpy(w->node+0x30,&p,8);
 p=(uint64_t)&w->result;memcpy(w->node+0x38,&p,8);
}
static void tick(Ctx*c,Wait*w){c->x[0]=(uint64_t)w->node;c->x[30]=99;f_817a75b0(c);assert(c->x[30]==99);}
int main(void){
 Ctx c={0};Wait a,b;
 int rates[]={60,75,120,144,240};int limits[]={1,7,60,600};
 for(int r=0;r<5;r++)for(int l=0;l<4;l++)for(int slow=1;slow<=2;slow++){
  init(&a,limits[l]);step=60.0f/rates[r]/slow;int frame=0;
  int expected=(int)ceil((double)limits[l]*rates[r]*slow/60.0-1e-9);
  do{tick(&c,&a);frame++;assert(frame<=expected+1);}while(!a.result);
  if(frame!=expected){fprintf(stderr,"Mismatch rate=%d limit=%d slow=%d got=%d expected=%d\n",rates[r],limits[l],slow,frame,expected);return 1;}
  assert(recomp_load32(&c,(uint64_t)a.node+0x18)==0x80000000u);
  if(l==2&&slow==1)printf("%d FPS: 60 ticks finish in %.6f seconds\n",rates[r],frame/(double)rates[r]);
 }
 /* Reset drops the fraction; independent instances and reused memory start clean. */
 init(&a,1);init(&b,1);step=.25f;tick(&c,&a);tick(&c,&b);
 a.held=0;tick(&c,&a);assert(!a.result&&recomp_load32(&c,(uint64_t)a.node+0x20)==0);
 a.held=1;for(int i=0;i<3;i++)tick(&c,&a);assert(!a.result);
 tick(&c,&a);assert(a.result&&!b.result);
 for(int i=0;i<3;i++)tick(&c,&b);assert(b.result);
 init(&a,1);tick(&c,&a);assert(!a.result);
 /* Paused time and a cap change retain elapsed time rather than rendering count. */
 init(&a,2);step=.5f;tick(&c,&a);step=0;for(int i=0;i<50;i++)tick(&c,&a);assert(!a.result);
 step=1.5f;tick(&c,&a);assert(a.result);
 init(&a,1);step=NAN;tick(&c,&a);assert(!a.result);step=-1;tick(&c,&a);assert(!a.result);
 init(&a,2000001);float long_count=2000000;memcpy(a.node+0x20,&long_count,4);
 step=0;tick(&c,&a);assert(!a.result);
 init(&a,0);step=.25f;tick(&c,&a);assert(a.result);
 init(&a,-1);tick(&c,&a);assert(a.result);
 puts("PASS: fractional waits, reset, independence, pause, cap changes and time scaling");
}
'''


class HeldFramesTests(unittest.TestCase):
    def test_timing_and_lifecycle(self):
        if not CC:
            self.skipTest('Set WONDER_TEST_CC to a C compiler')
        with tempfile.TemporaryDirectory(prefix='wonder-held-test-') as tmp:
            source = Path(tmp) / 'test.c'
            binary = Path(tmp) / 'test.exe'
            source.write_text(FIXTURE + P.WONDER_HELD_WRAPPER + MAIN, encoding='utf-8')
            build = subprocess.run([CC, '-std=c11', '-O2', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout, end='')

    def test_patch_is_scoped_idempotent_and_checked(self):
        body = P.WONDER_HELD_HEAD + '    recomp_store32(c,c->x[0] + 32,c->x[8]);\n    f_808995a0(c);\n}\n'
        tail = '\nvoid f_other(Ctx *c) {}\n'
        patched = P.patch_wonder_held_frames(body + tail)
        self.assertIn(P.WONDER_HELD_WRAPPER, patched)
        self.assertTrue(patched.endswith(tail))
        self.assertEqual(P.patch_wonder_held_frames(patched), patched)
        self.assertEqual(P.patch_wonder_held_frames(tail), tail)
        with self.assertRaises(RuntimeError):
            P.patch_wonder_held_frames(body.replace('+ 32', '+ 36'))
        self.assertIn(P.WONDER_HELD_WRAPPER, P.patch_file(body, 'test.c')[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
