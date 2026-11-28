#ifndef HOS_POSIX_SIGNAL_CONTEXT_H
#define HOS_POSIX_SIGNAL_CONTEXT_H

#include <stdint.h>
#include <ucontext.h>

static inline uintptr_t signal_pc(const ucontext_t *uc) {
#if defined(__aarch64__)
    return uc->uc_mcontext.pc;
#else
    return uc->uc_mcontext.gregs[REG_RIP];
#endif
}

#endif
