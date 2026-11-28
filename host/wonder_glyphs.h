#ifndef HOS_WONDER_GLYPHS_H
#define HOS_WONDER_GLYPHS_H
#include <stdint.h>

enum { WONDER_GLYPH_FIRST = 0xe090, WONDER_GLYPH_LAST = 0xe102 };
typedef struct {
    uint64_t font;
    uint16_t glyph[WONDER_GLYPH_LAST - WONDER_GLYPH_FIRST + 1];
} WonderGlyphs;

static inline int wonder_glyph_code(uint32_t code) {
    return code >= WONDER_GLYPH_FIRST && code <= WONDER_GLYPH_LAST;
}

static inline uint16_t wonder_glyph_id(const WonderGlyphs *map, uint64_t font, uint32_t code, uint16_t original) {
    if (!map || map->font != font || !wonder_glyph_code(code)) return original;
    const uint16_t id = map->glyph[code - WONDER_GLYPH_FIRST];
    return id ? id : original;
}

/* Readers that dereference the result hold the shared lock; the publisher holds it exclusively while reusing a slot. */
static inline WonderGlyphs *wonder_glyphs_load(WonderGlyphs *const *active) {
    return __atomic_load_n(active, __ATOMIC_ACQUIRE);
}
static inline void wonder_glyphs_publish(WonderGlyphs **active, WonderGlyphs *next) {
    __atomic_store_n(active, next, __ATOMIC_RELEASE);
}
#endif
