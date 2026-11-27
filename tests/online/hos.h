#pragma once
#include <stdint.h>
#include <stdio.h>
typedef struct { uint64_t x[8]; } Ctx;
void hos_sleep_ns(int64_t ns);
int hos_vcore_away(void);
void hos_vcore_back(void);
#define HLE(sym) void imp_##sym(Ctx *c)
#define ARG(n) c->x[n]
#define RET(value) (c->x[0] = (value))
#define GP(addr) ((void *)(uintptr_t)(addr))
#define G32(addr) (*(uint32_t *)GP(addr))
#define hos_log(...) ((void)0)

#define G64(addr) (*(uint64_t *)GP(addr))
