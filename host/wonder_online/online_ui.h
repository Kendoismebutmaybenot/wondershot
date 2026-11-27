#ifndef WONDER_ONLINE_UI_H
#define WONDER_ONLINE_UI_H
#include <stdint.h>
enum { WONDER_UI_GET, WONDER_UI_NAME, WONDER_UI_ENABLE, WONDER_UI_PRIVACY };
typedef struct WonderOnlineView {
    char name[33];
    char status[160];
    int enabled, privacy;
} WonderOnlineView;
#ifdef __cplusplus
extern "C" {
#endif
const uint64_t *wonder_profile_uid(void);
const uint64_t *wonder_profile_save_uid(void);
void wonder_profile_name(char *, unsigned);
int wonder_profile_enabled(void);
int wonder_profile_privacy(void);
int wonder_profile_available(void);
int wonder_profile_set_name(const char *);
int wonder_profile_set_enabled(int);
int wonder_profile_set_privacy(int);
void wonder_profile_fingerprint(char *, unsigned);
int wonder_online_auto(void);
uint32_t wonder_online_identity(void);
int wonder_online_prepare_host(const void *);
int wonder_online_prepare_join(const void *, const void *);
int wonder_online_scan(void *, unsigned);
int wonder_online_copy_code(char *, unsigned);
void wonder_online_disconnect(void);
#ifdef __cplusplus
}
#endif
#endif
