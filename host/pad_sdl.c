/* Game controllers through SDL (host/hos_sdl.c: SDL3, else SDL2, third_party/sdl2/SDL2.dll; zlib license, loaded at
   run time): DualSense, DualShock 4, Switch Pro, Xbox and most other pads, over USB or Bluetooth. XInput alone sees
   only Xbox-style pads.

   A thread of its own (on Linux the window's, which runs SDL there too) opens every controller SDL knows (and ones
   plugged in later), polls them every 4 ms and keeps
   the merged state; nn_hid.c ORs it into the input with XInput, keyboard and mouse. Without SDL nothing
   changes. HOS_NO_SDL=1 leaves SDL out. The inputs go by position (HOS_PAD_*: the bottom face button
   first, cross on a DualSense, A on an Xbox pad); nn_hid.c's controls make them the Switch's buttons.

   (longshot) Motion: with the Insert menu's Motion controls on (the default), the open pad with a gyroscope and an
   accelerometer (Switch Pro and pads in Switch mode, DualSense, DualShock 4, others) that was used last has them read
   each poll and turned into the six-axis state OoT aims with (host/hos_motion.h), which nn_hid.c's
   GetSixAxisSensorStates gives the game; Motion sensitivity X/Y and Invert motion X/Y apply there. Off, or with no such pad, the game sees the pad
   lying still, as before. */
#include "hos.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hos_sdl.h"
#include "hd_rumble.h"
#include "vibration.h"
#include "rumble_renhdrum.h"
#include "hos_motion.h"
#include "steam_pads.h"
#include "../gpu/vk/vk_api.h"   /* (HOS_PAD_*) */
#ifndef LONGSHOT_ENV_H   /* (env_on: the switches' one rule) */
#include "../gpu/vk/compat/longshot_env.h"
#endif

void hos_host_thread_register_self(const char *name);   /* hos_prof.c */

/* (BTN_A ... BTN_RIGHT are HOS_PAD_SOUTH ... HOS_PAD_RIGHT) */
enum { BTN_A, BTN_B, BTN_X, BTN_Y, BTN_BACK, BTN_GUIDE, BTN_START, BTN_LSTICK, BTN_RSTICK, BTN_LSHOULDER, BTN_RSHOULDER,
       BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_MISC1, BTN_RPADDLE1, BTN_LPADDLE1, BTN_RPADDLE2, BTN_LPADDLE2,
       BTN_TOUCHPAD = 20, BTN_N = 21 };
enum { AX_LX, AX_LY, AX_RX, AX_RY, AX_LT, AX_RT };

#define MAX_PADS 8
/* (motion: whether it has the sensors, whether they are on, when to try again after they would not turn on; used_ns:
   its last button or stick change; serial: which opening this is, so a pad reconnecting into the slot is a new one;
   bias: its gyroscope's learned resting rate, kept while another pad has motion) */
static struct {
    void *gc;
    int32_t id;
    uint16_t rumble_lo, rumble_hi;
    int64_t rumble_ns;
    uint8_t hd, hd_kind, hd_ever;   /* HD rumble (hd_rumble.h): HD_RUMBLE_UNKNOWN / ON / OFF, the pad's kind, sent once */
    /* (longshot) what plays its vibration (host/vibration.h: -1 not chosen yet), the kind of pad and its transport for
       that; a backend that would not open, and when to try it again; an Xbox pad's four motors as last sent */
    int8_t vib, vib_kind, wireless, vib_failed;
    int64_t vib_retry_ns, four_ns;
    uint16_t four[4];
    uint8_t hd_sent[HD_RUMBLE_PACKET_SIZE];
    int64_t hd_ns;
    int motion, motion_on;
    int64_t motion_retry_ns, used_ns;
    uint64_t input_sig;
    unsigned rested;   /* (longshot) the sticks' axes seen at rest since it was opened, a bit each: only those steer */
    signed char held[4];   /* (the way each axis was last held, -1, 0 or 1: one held the other way has passed its rest) */
    uint32_t serial;
    float bias[3], bias_t;
    int has_bias;
    uint16_t vendor;      /* (longshot) its USB vendor and product, and its Steam Input handle: not 0 for a Steam stand-in pad */
    uint16_t product;     /* (longshot) its USB product id (host/vibration.h: a Steam Controller (2026); the Deck's built-in controls, host/steam_pads.h) */
    uint64_t steam;
    int8_t player;        /* (Wondershot) its player, 0..3, the lowest free while it is open; -1 none (a motion-only pad) */
    int motion_only;      /* (host/steam_pads.h) a real Valve pad while a Steam stand-in pad is open: motion, no input */
} pads[MAX_PADS];
static uint32_t pads_opened;
static SRWLOCK state_lock = SRWLOCK_INIT;
static uint64_t state_buttons;
static int32_t state_stick[4];
static int state_count;
static uint64_t state_pl_buttons[4];   /* (Wondershot) each player's pad: buttons (1 << HOS_PAD_*), sticks, whether there is one */
static int32_t state_pl_stick[4][4];
static int state_pl_on[4];
static int state_deck_builtin;   /* (longshot) the Deck's built-in controls gave gameplay input in that poll */
static char state_name[128];   /* the first controller's name (host/prompts.c: the button prompts' Auto) */
static int state_type, state_sdl;   /* and its SDL type (the loaded SDL's numbers, 0 unknown), and that SDL (3, 2; 0 none) */
/* (the Insert menu's Rumble strength row, changed: a short rumble at the new strength, so the player feels what the row
   does, and that the controller rumbles at all) until when, hos_now_ns */
static int64_t rumble_test_until;
void hos_sdl_rumble_test(void) { __atomic_store_n(&rumble_test_until, hos_now_ns() + 400000000LL, __ATOMIC_RELAXED); }
/* The game's vibration values per player and side, for SDL motors and HD rumble. */
typedef struct {
    float hd[2][4];
    uint16_t motors[2][2];
} PadRumble;
static SRWLOCK rumble_lock = SRWLOCK_INIT;
static PadRumble rumble[VIB_PLAYERS];

/* (motion) the pad read and its filter (the polling thread's own), then what the game is handed (under state_lock): the
   last HOS_MOTION_HISTORY readings, newest at motion_hist[motion_head]; gyro_status for the menu */
/* (Wondershot) one of these for each player: the pad that is player p's gives player p's sensors, as the game asks for them by its
   npad (host/nn_hid.c: the handle says which) */
typedef struct {
    HosMotion motion;
    int64_t ns, reading_ns, log_ns, readings, start_ns;
    int warned;
    int pad;   /* (the pad read into the filter, -1 none) */
    uint32_t serial;
    HosMotionSample hist[HOS_MOTION_HISTORY];
    int head, count, live;
    float last_a[3], last_g[3];
    int64_t same_since, rearm_ns;
} MotionSlot;
static MotionSlot mot[4];
static volatile LONG gyro_status;   /* 0 no controller, 1 controllers but none with a gyro, 2 one with a gyro */

void hos_filter_stick(int16_t x, int16_t y, int zone, int32_t out[2]);   /* nn_hid.c */

/* SDL's controller support started; 0 when it could not be */
static int pads_start(void) {
    /* poll in the background, whatever window is in front (nn_hid.c decides when input counts) */
    hos_sdl_hint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1");
    /* (SDL2: PlayStation pads' rumble asked for; SDL3 turns it on when a rumble is first sent) */
    hos_sdl_hint("SDL_JOYSTICK_HIDAPI_PS5_RUMBLE", "1");
    hos_sdl_hint("SDL_JOYSTICK_HIDAPI_PS4_RUMBLE", "1");
    /* (the map below is by position; SDL2 reports Nintendo pads by their labels unless told not to, which put a Switch Pro
       Controller's A, on the right, at the bottom button's place: A acted as B and X as Y: SkyboundTotk issue 12. SDL3's
       are by position always) */
    hos_sdl_hint("SDL_GAMECONTROLLER_USE_BUTTON_LABELS", "0");
    /* (with no window nothing reads SDL's quit event: SDL's own SIGINT/SIGTERM handlers turned a timeout's or a service
       manager's SIGTERM into that event, and the run went on until SIGKILL. Without them the signals end it as usual) */
    if (env_on("HOS_HEADLESS")) hos_sdl_hint("SDL_NO_SIGNAL_HANDLERS", "1");
    /* (longshot) Valve's own pads taken out of the ignore list Steam sets for the games it starts, so that their motion
       sensors are read (host/steam_pads.h). Only with an SDL that tells Steam's stand-in pads apart: without
       that, a real pad and its stand-in would both play. A list emptied or unset in Steam's launch options is left as
       it is */
    {
        const char *list = getenv("SDL_GAMECONTROLLER_IGNORE_DEVICES");
        char kept[4096];
        if (list && *list && hos_sdl_knows_steam_pads() && steam_pads_without_valve(list, kept, sizeof kept) > 0 &&
            hos_sdl_hint_override("SDL_GAMECONTROLLER_IGNORE_DEVICES", kept))
            hos_log("hid: Valve's controllers (not the Steam Deck's) taken out of Steam's ignore list, for their motion sensors");
    }
    if (!hos_sdl_init(HOS_SDL_GAMEPAD)) {
        hos_log("hid: SDL could not start its controller support: %s", hos_sdl_error());
        return 0;
    }
    hos_log("hid: SDL controller support ready (DualSense, DualShock 4, Switch Pro, Xbox and others)");
    return 1;
}

/* SDL_GameControllerRumble runs only for the duration it is given, then stops, and a repeat of the same numbers was
   skipped. A rumble the game holds, and one that was already playing when this controller opened, never reached it. */
static int rumble_due(unsigned lo, unsigned hi, unsigned sent_lo, unsigned sent_hi, long long now, long long sent_ns) {
    if (lo != sent_lo || hi != sent_hi) return 1;
    if ((lo || hi) && now - sent_ns >= 500000000LL) return 1;   /* (half of the 1 s effect, so it does not lapse) */
    return 0;
}

/* The Insert menu's Rumble strength (percent; 0 Off) on the motors' 0..65535, heavy and light together: up to 100 each
   motor is scaled on its own (100 sends them as they are); above, when the stronger would pass the motor's top, both
   are scaled by the same factor so that it just reaches it, keeping the balance between the motors that the frequency
   split chose. Off stops a rumble that is playing (the poll sends the change). */
static void rumble_strength(unsigned heavy, unsigned light, int percent, uint16_t out[2]) {
    if (percent <= 0) {
        out[0] = out[1] = 0;
        return;
    }
    unsigned long long h = (unsigned long long)heavy * (unsigned)percent / 100u;
    unsigned long long l = (unsigned long long)light * (unsigned)percent / 100u;
    if (h > 0xFFFFu || l > 0xFFFFu) {   /* (from the motors' own values: the same factor for both, the stronger at the top) */
        const unsigned long long top = heavy > light ? heavy : light;
        h = heavy * 0xFFFFull / top;
        l = light * 0xFFFFull / top;
    }
    out[0] = (uint16_t)h;
    out[1] = (uint16_t)l;
}

static void rumble_motors(const PadRumble *sample, int testing, int strength, uint16_t motors[2]) {
    uint16_t merged[2];
    for (int m = 0; m < 2; m++)
        merged[m] = sample->motors[0][m] > sample->motors[1][m] ? sample->motors[0][m] : sample->motors[1][m];
    rumble_strength(testing ? 0xC000 : merged[0], testing ? 0xC000 : merged[1], strength, motors);
}

/* A pad SDL just opened: HD rumble when it is a Switch Pro Controller or a Joy-Con and the SDL has the effect call
   (HOS_HD_RUMBLE=0: never); whether SDL's driver takes it shows with the first packet. */
static void hd_open(int i, void *gc) {
    static int env_off = -1;
    if (env_off < 0) {
        const char *e = getenv("HOS_HD_RUMBLE");
        env_off = e && !strcmp(e, "0");
    }
    pads[i].hd_kind = (uint8_t)hd_rumble_kind(hos_sdl_load(), hos_sdl_pad_type(gc));
    pads[i].hd = (uint8_t)hd_rumble_start(pads[i].hd_kind, hos_sdl_pad_has_effect(), env_off);
    pads[i].hd_ever = 0;
    pads[i].hd_ns = 0;
    const uint8_t n[4] = {0x00, 0x01, 0x40, 0x40};
    hd_rumble_packet(HD_RUMBLE_PRO, n, n, pads[i].hd_sent);
}

/* A pad's HD rumble, each poll: its packet when due (hd_rumble_due). 1 when the pad plays HD rumble (the motor rumble
   is not sent to it); 0 when it does not, or SDL just refused it (then it gets the motor rumble from now on). side:
   the left side's bytes, the right's, and both merged (for a single Joy-Con, which has only one). */
static int hd_poll(int i, const uint8_t side[3][4], long long now) {
    if (pads[i].hd == HD_RUMBLE_OFF) return 0;
    uint8_t packet[HD_RUMBLE_PACKET_SIZE];
    const int single = pads[i].hd_kind == HD_RUMBLE_JOYCON_LEFT || pads[i].hd_kind == HD_RUMBLE_JOYCON_RIGHT;
    hd_rumble_packet(pads[i].hd_kind, single ? side[2] : side[0], single ? side[2] : side[1], packet);
    if (!hd_rumble_due(packet, pads[i].hd_sent, pads[i].hd_ever, now, pads[i].hd_ns)) return 1;
    const int was = pads[i].hd;
    pads[i].hd = (uint8_t)hd_rumble_after_send(hos_sdl_pad_effect(pads[i].gc, packet, sizeof packet));
    if (pads[i].hd == HD_RUMBLE_OFF) {   /* (refused: HD rumble off for this pad until it is closed and opened again.
                                           SDL3 queues the write, so false means the driver does not support the effect,
                                           not a write that failed once) */
        hos_log("hid: \"%s\" did not take HD rumble (%s): its rumble goes to its motors", hos_sdl_pad_name(pads[i].gc),
                hos_sdl_error());
        pads[i].rumble_lo = pads[i].rumble_hi = 0;   /* (the motor path sends what is playing at once) */
        pads[i].rumble_ns = 0;
        return 0;
    }
    if (was == HD_RUMBLE_UNKNOWN) hos_log("hid: HD rumble on \"%s\"", hos_sdl_pad_name(pads[i].gc));
    memcpy(pads[i].hd_sent, packet, sizeof packet);
    pads[i].hd_ns = now;
    pads[i].hd_ever = 1;
    return 1;
}

/* (motion) the sensors on while Motion controls is on (HOS_OPT_GYRO, on without the menu), off otherwise; the pad with
   them that was used last read into the filter. count: the pads open */
static void motion_player(int64_t now, int player, int want, int debug);
static void motion_poll(int64_t now, int count) {
    int rx_option(int id, int otherwise);
    static int debug = -1;   /* (HOS_MOTION_DEBUG, read once) */
    if (debug < 0) debug = env_on("HOS_MOTION_DEBUG");
    const int want = rx_option(HOS_OPT_GYRO, 1) != 0;
    int any = 0;
    for (int i = 0; i < MAX_PADS; i++) {
        if (!pads[i].gc || !pads[i].motion) continue;
        any = 1;
        if (pads[i].motion_on != want && now >= pads[i].motion_retry_ns) {
            const int ok = hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_ACCEL, want) &
                           hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_GYRO, want);
            if (want && !ok) {   /* (both off again, and another try in two seconds: a pad over Bluetooth may still be
                                     starting) */
                hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_ACCEL, 0);
                hos_sdl_pad_sensor_enable(pads[i].gc, HOS_SDL_SENSOR_GYRO, 0);
                pads[i].motion_on = 0;
                if (!pads[i].motion_retry_ns)
                    hos_log("hid: \"%s\": its motion sensors could not be turned on yet, trying again",
                            hos_sdl_pad_name(pads[i].gc));
                pads[i].motion_retry_ns = now + 2000000000LL;
            } else {
                pads[i].motion_on = want;
                pads[i].motion_retry_ns = 0;
            }
        }
    }
    InterlockedExchange(&gyro_status, any ? 2 : count ? 1 : 0);
    for (int pl = 0; pl < 4; pl++) motion_player(now, pl, want, debug);
}

/* the sensors of player `player`: the pad that is theirs, read into their own filter. A real Valve pad beside its Steam stand-in
   (motion only: no buttons, no player) belongs to the stand-in's player */
static void motion_player(int64_t now, int player, int want, int debug) {
    MotionSlot *m = &mot[player];
    static int init;
    if (!init) {
        init = 1;
        for (int k = 0; k < 4; k++) mot[k].pad = -1;
    }
    int pick = -1, stand_in_player = 0;
    for (int i = 0; i < MAX_PADS; i++)
        if (pads[i].gc && pads[i].steam && !pads[i].motion_only && pads[i].player >= 0) stand_in_player = pads[i].player;
    for (int i = 0; i < MAX_PADS; i++) {
        if (!pads[i].gc || !pads[i].motion || !pads[i].motion_on || !want) continue;
        const int owner = pads[i].motion_only ? stand_in_player : pads[i].player;
        if (owner == player) pick = i;
    }
    float a[3], g[3];
    const int read = pick >= 0 && hos_sdl_pad_sensor(pads[pick].gc, HOS_SDL_SENSOR_ACCEL, a, 3) &&
                     hos_sdl_pad_sensor(pads[pick].gc, HOS_SDL_SENSOR_GYRO, g, 3);
    /* (a gyroscope reading the very same values for over a second has stopped when its accelerometer does too: a real
       accelerometer always moves a little, while a gyroscope may read exactly 0 at rest, as a Steam Deck's in its dock
       does. Seen with a Steam Controller under Steam after Alt+Tab, when Steam's layout switch left its sensors off while
       SDL still had them on. Off and on again, as the menu's Motion controls row does, brings it back) */
    {
        if (read && !memcmp(g, m->last_g, sizeof g) && !memcmp(a, m->last_a, sizeof a)) {
            if (!m->same_since) m->same_since = now;
            else if (now - m->same_since > 1200000000LL && now >= m->rearm_ns) {
                hos_sdl_pad_sensor_enable(pads[pick].gc, HOS_SDL_SENSOR_ACCEL, 0);
                hos_sdl_pad_sensor_enable(pads[pick].gc, HOS_SDL_SENSOR_GYRO, 0);
                pads[pick].motion_on = 0;   /* (turned on again by the loop above on the next poll) */
                hos_log("hid: \"%s\": its gyroscope and accelerometer stopped changing: motion sensors turned off "
                        "and on again", hos_sdl_pad_name(pads[pick].gc));
                m->same_since = 0, m->rearm_ns = now + 3000000000LL;
            }
        } else {
            if (read) memcpy(m->last_a, a, sizeof a), memcpy(m->last_g, g, sizeof g);
            m->same_since = 0;
        }
    }
    /* (the pad that had motion keeps what its filter learned of its gyroscope's bias, for when it has motion again) */
    if (m->pad >= 0 && (!read || pick != m->pad) && pads[m->pad].gc && pads[m->pad].serial == m->serial &&
        m->motion.learned_t > 0) {
        memcpy(pads[m->pad].bias, m->motion.bias, sizeof m->motion.bias);
        pads[m->pad].bias_t = m->motion.learned_t, pads[m->pad].has_bias = 1;
    }
    if (!read) {
        m->pad = -1;
        AcquireSRWLockExclusive(&state_lock);
        m->live = 0, m->count = 0;
        ReleaseSRWLockExclusive(&state_lock);
        return;
    }
    int fresh = 0;
    if (pick != m->pad || pads[pick].serial != m->serial) {   /* (another pad, or one reconnected: a fresh filter) */
        hos_motion_reset(&m->motion);
        if (pads[pick].has_bias)
            memcpy(m->motion.bias, pads[pick].bias, sizeof m->motion.bias), m->motion.learned_t = pads[pick].bias_t;
        m->pad = pick, m->serial = pads[pick].serial, m->ns = now;
        fresh = 1;
        m->start_ns = now, m->warned = 0;
        hos_log("hid: player %d's motion controls from \"%s\"", player + 1, hos_sdl_pad_name(pads[pick].gc));
    }
    /* the filter runs outside the lock (the game's input calls take it); a repeat of the last reading is no reading */
    const int64_t dt_ns = now - m->ns;
    m->ns = now;
    {   /* (the Motion deadzone row: the console's tight, standard and loose zero-drift thresholds, turns a second) */
        static const float zone[3] = {HOS_MOTION_THRESHOLD_TIGHT, HOS_MOTION_THRESHOLD, HOS_MOTION_THRESHOLD_LOOSE};
        const int z = rx_option(HOS_OPT_GYRO_DEADZONE, 1);
        m->motion.threshold = zone[z < 0 ? 0 : z > 2 ? 2 : z];
    }
    if (!hos_motion_update(&m->motion, a, g, (float)(dt_ns / 1e9), rx_option(HOS_OPT_GYRO_SENS_X, 100) / 100.0f,
                           rx_option(HOS_OPT_GYRO_SENS_Y, 100) / 100.0f, rx_option(HOS_OPT_GYRO_INV_X, 0),
                           rx_option(HOS_OPT_GYRO_INV_Y, 0)) && !fresh)
        return;
    if (!m->warned && m->motion.learned_t <= 0 && now - m->start_ns > 30000000000LL) {
        m->warned = 1;   /* (a pad noisier than the stillness test allows: its drift is never taken off) */
        hos_log("hid: motion: \"%s\" has not been set down yet, so its gyroscope's drift is not learned: set it on a "
                "table for a second (if it is on a table and this stays, its sensor may be noisier than the stillness "
                "test allows)", hos_sdl_pad_name(pads[pick].gc));
    }
    if (debug && now >= m->log_ns) {   /* (twice a second: what the game gets) */
        m->log_ns = now + 500000000LL;
        hos_log("hid: motion: accel (%+.2f, %+.2f, %+.2f) G, gyro (%+.3f, %+.3f, %+.3f) turns/s, direction rows "
                "(%+.2f %+.2f %+.2f / %+.2f %+.2f %+.2f / %+.2f %+.2f %+.2f), bias (%+.4f, %+.4f, %+.4f)", m->motion.out.accel[0],
                m->motion.out.accel[1], m->motion.out.accel[2], m->motion.out.gyro[0], m->motion.out.gyro[1], m->motion.out.gyro[2],
                m->motion.out.direction[0], m->motion.out.direction[1], m->motion.out.direction[2], m->motion.out.direction[3],
                m->motion.out.direction[4], m->motion.out.direction[5], m->motion.out.direction[6], m->motion.out.direction[7],
                m->motion.out.direction[8], m->motion.bias[0], m->motion.bias[1], m->motion.bias[2]);
    }
    HosMotionSample r;
    r.st = m->motion.out;
    r.n = ++m->readings;
    /* (the time since the reading before, capped as the filter caps it: a stalled pad's next reading is no jump) */
    r.dt_ns = fresh ? 5000000 : now - m->reading_ns;
    if (r.dt_ns > (int64_t)(HOS_MOTION_DT_MAX * 1e9)) r.dt_ns = (int64_t)(HOS_MOTION_DT_MAX * 1e9);
    m->reading_ns = now;
    AcquireSRWLockExclusive(&state_lock);
    m->head = (m->head + 1) % HOS_MOTION_HISTORY;
    m->hist[m->head] = r;
    if (fresh) m->count = 0;
    if (m->count < HOS_MOTION_HISTORY) m->count++;
    m->live = 1;
    ReleaseSRWLockExclusive(&state_lock);
}

/* (longshot) a motion-only pad's own presses (host/steam_pads.h): they are not the game's input, but they still mark it
   the pad used last, which motion_poll reads motion from */
static void motion_only_used(int i, int64_t now) {
    int rx_option(int id, int otherwise);
    const int z = rx_option(11, 0);   /* (the menu's Stick dead zone) */
    uint64_t sig = 0;
    for (int k = BTN_A; k <= BTN_RIGHT; k++)
        if (hos_sdl_pad_button(pads[i].gc, k)) sig |= 1ULL << k;
    int32_t v[4];
    hos_filter_stick(hos_sdl_pad_axis(pads[i].gc, AX_LX), hos_sdl_pad_axis(pads[i].gc, AX_LY), z, v);
    hos_filter_stick(hos_sdl_pad_axis(pads[i].gc, AX_RX), hos_sdl_pad_axis(pads[i].gc, AX_RY), z, v + 2);
    for (int k = 0; k < 4; k++) sig |= (uint64_t)(v[k] > 0 ? 1 : v[k] < 0 ? 2 : 0) << (32 + 2 * k);
    if (sig != pads[i].input_sig) pads[i].input_sig = sig, pads[i].used_ns = now;
}

/* ---- (longshot) what plays each pad's vibration (host/vibration.h); RenHDrum's backends are host/rumble_renhdrum.c ---- */
static int vib_force = -1;   /* HOS_RUMBLE_BACKEND, read once */
static int usb_found;        /* a DualSense's four-channel sound card was there at the last look */
static int64_t usb_next_look;
/* RenHDrum for a pad of this kind: loaded (once) only for a pad it would play */
static int vib_rh_for(int kind) {
    if (vib_force == VIB_FORCE_HD || vib_force == VIB_FORCE_MOTORS || kind == VIB_PAD_OTHER) return 0;
    return rh_load();
}
/* what played pad i lets go of it, and its motors are stopped (whatever plays next sends what is playing) */
static void vib_leave(int i, int64_t now) {
    (void)now;
    void *gc = pads[i].gc;
    switch (pads[i].vib) {
    case VIB_RH_DS_USB: rh_usb_close(); break;
    case VIB_RH_DS_BT: rh_bt_close(); break;
    case VIB_RH_XBOX:
        rh_pad_close(gc);
        hos_sdl_pad_rumble_triggers(gc, 0, 0, 0);
        break;
    case VIB_RH_SWITCH: rh_pad_close(gc); break;
    case VIB_RH_STEAM: rh_steam_close(); break;
    default: break;
    }
    if (pads[i].vib >= 0) hos_sdl_pad_rumble(gc, 0, 0, 0);
    pads[i].rumble_lo = pads[i].rumble_hi = 0, pads[i].rumble_ns = 0;
    pads[i].hd_ever = 0;
    memset(pads[i].four, 0, sizeof pads[i].four), pads[i].four_ns = 0;
    pads[i].vib = -1;
}
static void vib_choose(int i, int mode, int64_t now) {
    void *gc = pads[i].gc;
    const int kind = pads[i].vib_kind;
    /* (one that stopped playing: let go, and chosen again below) */
    if (pads[i].vib == VIB_RH_DS_USB && !rh_usb_alive()) {
        hos_log("vibration: the DualSense's sound card went away: its motors until it is back");
        vib_leave(i, now);
        usb_found = 0, usb_next_look = now + 2000000000LL;
    } else if (pads[i].vib == VIB_RH_DS_BT && !rh_bt_alive()) {
        vib_leave(i, now);
        pads[i].vib_failed = VIB_RH_DS_BT, pads[i].vib_retry_ns = now + 30000000000LL;
    } else if (pads[i].vib == VIB_RH_STEAM && !rh_steam_alive()) {
        vib_leave(i, now);
        pads[i].vib_failed = VIB_RH_STEAM, pads[i].vib_retry_ns = now + 30000000000LL;
    }
    const int rh = vib_rh_for(kind);
    int ds_usb = 0, ds_hid = 0;
    if (rh && kind == VIB_PAD_DUALSENSE && mode == VIB_MODE_AUTO) {
        void *owner = rh_usb_owner();
        if (owner == gc) ds_usb = 1;
        else if (!owner && pads[i].wireless != 1) {
            if (now >= usb_next_look) usb_found = rh_usb_find(), usb_next_look = now + 2000000000LL;
            ds_usb = usb_found;
        }
        owner = rh_bt_owner();
        ds_hid = owner == gc || (!owner && hos_sdl_hid_can() && *hos_sdl_pad_path(gc));
    } else if (rh && kind == VIB_PAD_STEAM && mode == VIB_MODE_AUTO) {   /* (its grips: its HID device, one pad at a time) */
        void *owner = rh_steam_owner();
        ds_hid = owner == gc || (!owner && hos_sdl_hid_can() && *hos_sdl_pad_path(gc));
    }
    const int hd = pads[i].hd_kind != HD_RUMBLE_NONE && pads[i].hd != HD_RUMBLE_OFF;
    int want = vibration_pick(mode, vib_force, kind, pads[i].wireless, hd, rh, ds_usb, ds_hid);
    /* (a Joy-Con alone: our HD rumble merges both sides into it, RenHDrum's engine plays its own side's only. Testers'
       =renhdrum still gets RenHDrum's) */
    const int single = pads[i].hd_kind == HD_RUMBLE_JOYCON_LEFT || pads[i].hd_kind == HD_RUMBLE_JOYCON_RIGHT;
    if (want == VIB_RH_SWITCH && single && vib_force != VIB_FORCE_RENHDRUM) want = hd ? VIB_HD : VIB_MOTORS;
    if (want == pads[i].vib_failed && now < pads[i].vib_retry_ns) want = VIB_MOTORS;   /* (it would not open: not yet) */
    if (want == pads[i].vib) return;
    vib_leave(i, now);
    int ok = 1;
    if (want == VIB_RH_DS_USB) ok = rh_usb_open(gc);
    else if (want == VIB_RH_DS_BT) ok = rh_bt_open(gc, hos_sdl_pad_path(gc));
    else if (want == VIB_RH_STEAM) ok = rh_steam_open(gc, hos_sdl_pad_path(gc), pads[i].product == VIB_STEAM_CABLE);
    else if (want == VIB_RH_XBOX || want == VIB_RH_SWITCH)
        ok = rh_pad_open(gc, want, pads[i].wireless == 1, pads[i].hd_kind == HD_RUMBLE_PRO);
    if (!ok) {
        pads[i].vib_failed = (int8_t)want, pads[i].vib_retry_ns = now + 5000000000LL;
        want = VIB_MOTORS;
    }
    if (want != VIB_MOTORS || pads[i].vib_kind != VIB_PAD_OTHER)
        hos_log("vibration: \"%s\": %s", hos_sdl_pad_name(gc),
                want == VIB_NONE ? "off" : want == VIB_MOTORS ? "its motors" : want == VIB_HD ? "its own HD rumble" :
                want == VIB_RH_DS_USB ? "fine haptics on its cable (RenHDrum)" :
                want == VIB_RH_DS_BT ? "fine haptics over Bluetooth (RenHDrum)" :
                want == VIB_RH_XBOX ? "four motors (RenHDrum)" :
                want == VIB_RH_STEAM ? "its grips (RenHDrum, experimental)" : "HD rumble (RenHDrum)");
    pads[i].vib = (int8_t)want;
}
/* an Xbox pad's four motors (RenHDrum): sent when RenHDrum says, and again every half second while they turn, as the
   motor rumble is (SDL's rumble lasts the time it is given) */
static void four_poll(int i, int64_t now) {
    uint16_t m[4];
    int due = rh_xbox_poll(pads[i].gc, now, m);
    if (!due) {
        if (!(pads[i].four[0] | pads[i].four[1] | pads[i].four[2] | pads[i].four[3]) || now - pads[i].four_ns < 500000000LL)
            return;
        memcpy(m, pads[i].four, sizeof m);
    }
    const int on = m[0] || m[1] || m[2] || m[3];
    hos_sdl_pad_rumble(pads[i].gc, m[0], m[1], on ? 1000 : 0);
    hos_sdl_pad_rumble_triggers(pads[i].gc, m[2], m[3], on ? 1000 : 0);
    memcpy(pads[i].four, m, sizeof m), pads[i].four_ns = now;
}

/* one poll: controllers plugged in or gone (each second), then every open one's buttons, sticks and rumble */
/* (Wondershot) which pad is which player. A player can be given a pad by name (the Controls page's Controller row: kept in
   longshot_options.ini as player_pad<N>=<name>); a player without one is Auto: the pads nobody asked for take the lowest players
   no name holds, in the order they connected, and keep their number while they are open */
static SRWLOCK want_lock = SRWLOCK_INIT;
static char want_name[4][128];
void hos_sdl_player_pad(int player, const char *name) {
    if (player < 0 || player > 3) return;
    AcquireSRWLockExclusive(&want_lock);
    snprintf(want_name[player], sizeof want_name[player], "%s", name ? name : "");
    ReleaseSRWLockExclusive(&want_lock);
}
int hos_sdl_player_wanted(int player, char *out, size_t cap) {
    if (player < 0 || player > 3 || !cap) return 0;
    AcquireSRWLockShared(&want_lock);
    snprintf(out, cap, "%s", want_name[player]);
    ReleaseSRWLockShared(&want_lock);
    return out[0] != 0;
}
/* the pads in the order they connected (serial): i-th of them, its name and player (-1 none yet); 0 past the last */
int hos_sdl_pad_info(int i, char *name, size_t cap, int *player) {
    AcquireSRWLockShared(&state_lock);
    int order[MAX_PADS], n = 0;
    for (int k = 0; k < MAX_PADS; k++)
        if (pads[k].gc && !pads[k].motion_only) order[n++] = k;
    for (int a = 1; a < n; a++)   /* (insertion sort by serial) */
        for (int b = a; b > 0 && pads[order[b]].serial < pads[order[b - 1]].serial; b--) {
            const int t = order[b]; order[b] = order[b - 1]; order[b - 1] = t;
        }
    int ok = 0;
    if (i >= 0 && i < n) {
        const char *nm = hos_sdl_pad_name(pads[order[i]].gc);
        snprintf(name, cap, "%s", nm ? nm : "");
        if (player) *player = pads[order[i]].player;
        ok = 1;
    }
    ReleaseSRWLockShared(&state_lock);
    return ok;
}
static void assign_players(void) {
    int order[MAX_PADS], n = 0;
    for (int k = 0; k < MAX_PADS; k++)
        if (pads[k].gc && !pads[k].motion_only) order[n++] = k;
        else pads[k].player = -1;
    for (int a = 1; a < n; a++)
        for (int b = a; b > 0 && pads[order[b]].serial < pads[order[b - 1]].serial; b--) {
            const int t = order[b]; order[b] = order[b - 1]; order[b - 1] = t;
        }
    int was[MAX_PADS], taken = 0, named = 0;
    for (int k = 0; k < MAX_PADS; k++) was[k] = pads[k].player, pads[k].player = -1;
    char want[4][128];
    AcquireSRWLockShared(&want_lock);
    memcpy(want, want_name, sizeof want);
    ReleaseSRWLockShared(&want_lock);
    for (int p = 0; p < 4; p++) {   /* (a player a name holds: the pad of that name that was already it, else the first) */
        if (!want[p][0]) continue;
        named |= 1 << p;
        int pick = -1;
        for (int j = 0; j < n && pick < 0; j++) {
            const int k = order[j];
            const char *nm = hos_sdl_pad_name(pads[k].gc);
            if (pads[k].player < 0 && nm && !strcmp(nm, want[p]) && was[k] == p) pick = k;
        }
        for (int j = 0; j < n && pick < 0; j++) {
            const int k = order[j];
            const char *nm = hos_sdl_pad_name(pads[k].gc);
            if (pads[k].player < 0 && nm && !strcmp(nm, want[p])) pick = k;
        }
        if (pick >= 0) pads[pick].player = (int8_t)p, taken |= 1 << p;
    }
    for (int j = 0; j < n; j++) {   /* (the rest keep their number when nothing holds it, else take the lowest free) */
        const int k = order[j];
        if (pads[k].player >= 0) continue;
        if (was[k] >= 0 && !((taken | named) >> was[k] & 1)) pads[k].player = (int8_t)was[k], taken |= 1 << was[k];
    }
    for (int j = 0; j < n; j++) {
        const int k = order[j];
        if (pads[k].player >= 0) continue;
        for (int p = 0; p < 4; p++)
            if (!((taken | named) >> p & 1)) { pads[k].player = (int8_t)p; taken |= 1 << p; break; }
    }
    for (int k = 0; k < MAX_PADS; k++)
        if (pads[k].gc && pads[k].player != was[k] && pads[k].player >= 0)
            hos_log("hid: \"%s\" is player %d", hos_sdl_pad_name(pads[k].gc), pads[k].player + 1);
}

static void pads_poll(void) {
    static int64_t next_scan = 0;
    if (vib_force < 0) vib_force = vibration_force(getenv("HOS_RUMBLE_BACKEND"));
    hos_sdl_pads_update();
        const int64_t now = hos_now_ns();
        if (now >= next_scan) {   /* new controllers (and ones that went away) */
            next_scan = now + 1000000000LL;
            for (int i = 0; i < MAX_PADS; i++)
                if (pads[i].gc && !hos_sdl_pad_connected(pads[i].gc)) {
                    hos_log("hid: controller \"%s\" disconnected (SDL)", hos_sdl_pad_name(pads[i].gc));
                    vib_leave(i, now);   /* (longshot) what played its vibration lets go of it first */
                    hos_sdl_pad_close(pads[i].gc);
                    pads[i].gc = NULL;
                    pads[i].player = -1;
                    pads[i].rumble_lo = pads[i].rumble_hi = 0;
                    pads[i].rumble_ns = 0;
                    pads[i].motion = pads[i].motion_on = 0;
                }
            int32_t ids[32];
            int opens[32];
            const int nj = hos_sdl_pads_list(ids, opens, 32);
            for (int j = 0; j < nj; j++) {
                const int32_t id = ids[j];
                int have = 0, slot = -1;
                for (int i = 0; i < MAX_PADS; i++) {
                    if (pads[i].gc && pads[i].id == id) have = 1;
                    if (!pads[i].gc && slot < 0) slot = i;
                }
                if (have || slot < 0) continue;
                void *gc = hos_sdl_pad_open(opens[j]);
                if (!gc) continue;
                pads[slot].gc = gc;
                pads[slot].id = hos_sdl_pad_id(gc);
                pads[slot].rumble_lo = pads[slot].rumble_hi = 0;
                pads[slot].rumble_ns = 0;
                hd_open(slot, gc);
                /* (longshot) what plays its vibration is chosen by the poll below (host/vibration.h) */
                pads[slot].vib = -1, pads[slot].vib_failed = -1, pads[slot].vib_retry_ns = 0;
                pads[slot].product = hos_sdl_pad_product(gc);
                pads[slot].vib_kind = (int8_t)vibration_pad_kind(hos_sdl_load(), hos_sdl_pad_type(gc), hos_sdl_pad_name(gc),
                                                                 hos_sdl_pad_vendor(gc), pads[slot].product);
                pads[slot].wireless = (int8_t)hos_sdl_pad_wireless(gc);
                pads[slot].motion = hos_sdl_pad_has_sensor(gc, HOS_SDL_SENSOR_GYRO) && hos_sdl_pad_has_sensor(gc, HOS_SDL_SENSOR_ACCEL);
                pads[slot].motion_on = 0;
                pads[slot].motion_retry_ns = 0;
                pads[slot].used_ns = now, pads[slot].input_sig = 0;   /* (just connected: the one about to be used) */
                pads[slot].rested = 0;
                memset(pads[slot].held, 0, sizeof pads[slot].held);
                pads[slot].serial = ++pads_opened;
                pads[slot].has_bias = 0;
                pads[slot].vendor = hos_sdl_pad_vendor(gc);
                pads[slot].product = hos_sdl_pad_product(gc);
                pads[slot].steam = hos_sdl_pad_steam_handle(gc);
                pads[slot].motion_only = 0;   /* (the poll below decides, and says so) */
                pads[slot].player = -1;   /* (given below, once it is known not to be motion-only) */
                hos_sdl_pad_log_connection(gc, pads[slot].motion, pads[slot].steam != 0);
            }
        }
        assign_players();
        void *player_pads[VIB_PLAYERS] = {0};
        uint32_t serial[VIB_PLAYERS] = {0};
        static uint32_t rumble_serial[VIB_PLAYERS];
        for (int i = 0; i < MAX_PADS; i++) {
            const int player = pads[i].player;
            if (pads[i].gc && player >= 0) {
                player_pads[player] = pads[i].gc;
                serial[player] = pads[i].serial;
            }
        }
        PadRumble samples[VIB_PLAYERS + 1] = {0};   /* extra entry for an unassigned pad */
        unsigned changed = 0;
        AcquireSRWLockExclusive(&rumble_lock);
        for (int p = 0; p < VIB_PLAYERS; p++) {
            if (serial[p] != rumble_serial[p]) {
                changed |= 1u << p;
                rumble_serial[p] = serial[p];
                memset(&rumble[p], 0, sizeof rumble[p]);
            }
            samples[p] = rumble[p];
        }
        if (changed) rh_route_players(player_pads, changed);
        ReleaseSRWLockExclusive(&rumble_lock);
        uint64_t b = 0;
        int32_t s[4] = {0};
        int count = 0;
        int rx_option(int id, int otherwise);
        /* (longshot) the Controls page's Vibration (Auto, Basic, Off) and Vibration strength (percent of the game's, every
           backend's: host/vibration.h). An options file's Rumble strength of 0 is Off */
        int strength = rx_option(9, 100);
        int mode = rx_option(HOS_OPT_VIBRATION, VIB_MODE_AUTO);
        if (mode < VIB_MODE_AUTO || mode > VIB_MODE_OFF) mode = VIB_MODE_AUTO;
        if (strength <= 0) mode = VIB_MODE_OFF, strength = 100;
        /* (Test vibration, or a strength just changed: three quarters of the motors, as the game's is scaled) */
        const int testing = now < __atomic_load_n(&rumble_test_until, __ATOMIC_RELAXED);
        /* (RenHDrum's backends: the test, a side gone quiet, the strength, and the Controls page's DualSense HD Haptics) */
        rh_tick(now, testing, strength, rx_option(HOS_OPT_DS_HD_HAPTICS, 1) != 0);
        int stand_in = 0;   /* (longshot) a Steam stand-in pad open (host/steam_pads.h) */
        int64_t status_used = -1;   /* (longshot) the Controls page's vibration line: the pad used last */
        int status_pad = -1;
        int deck_builtin = 0;   /* (longshot) the Deck's built-in controls give gameplay input: its mouse must not */
        uint64_t pl_buttons[4] = {0};   /* (Wondershot) each player's own pad, beside the merged state */
        int32_t pl_stick[4][4] = {{0}};
        int pl_on[4] = {0};
        for (int i = 0; i < MAX_PADS; i++) stand_in |= pads[i].gc && pads[i].steam;
        for (int i = 0; i < MAX_PADS; i++) {
            void *gc = pads[i].gc;
            if (!gc) continue;
            /* (longshot) a real Valve pad beside its Steam stand-in: its motion is read (motion_poll), its buttons and
               sticks come through the stand-in as the player's Steam layout maps them, so they are not merged twice,
               and its rumble goes through Steam too. Its own presses still mark it the pad used last, for motion */
            const int motion_only = steam_pads_motion_only(pads[i].vendor, pads[i].steam, stand_in);
            if (motion_only != pads[i].motion_only) {
                pads[i].motion_only = motion_only;
                /* (its rumble goes through Steam's stand-in now: what played it here lets go, or it would play twice) */
                if (motion_only && pads[i].vib >= 0) vib_leave(i, now);
                /* (a real Valve pad this SDL opens with no gyroscope: an SDL with no driver for it, so the loosened
                   list gives no motion, said once so the player sees why) */
                if (motion_only && !pads[i].motion)
                    hos_log("hid: \"%s\": no motion sensors through this SDL, so Motion controls can't read it; "
                            "its buttons come through Steam Input's pad", hos_sdl_pad_name(gc));
                else
                    hos_log(motion_only ? "hid: \"%s\": motion only, its buttons come through Steam Input's pad"
                                        : "hid: \"%s\": its buttons count again (no Steam Input pad is open)",
                            hos_sdl_pad_name(gc));
            }
            if (motion_only) {
                motion_only_used(i, now);
                continue;
            }
            if (steam_pads_deck_builtin(pads[i].vendor, pads[i].product, pads[i].steam)) deck_builtin = 1;
            count++;
            uint64_t sig = 0;
            for (int k = BTN_A; k <= BTN_RIGHT; k++)   /* (SDL3's gamepad buttons are in SDL2's order) */
                if (hos_sdl_pad_button(gc, k)) sig |= 1ULL << k;
            /* The paddle buttons follow MISC1 in SDL, and the triggers in HOS_PAD_*. */
            for (int k = BTN_RPADDLE1; k <= BTN_LPADDLE2; k++)
                if (hos_sdl_pad_button(gc, k)) sig |= 1ULL << (HOS_PAD_RPADDLE1 + k - BTN_RPADDLE1);
            uint64_t mine = sig;   /* (this pad's buttons: into the merged state and its player's) */
            /* (longshot) a DualShock 4's or DualSense's touchpad click: it opens the Insert menu as F1 does (vk_menu.cpp).
               SDL numbers it 20, past the buttons above; an SDL without it answers 0 */
            if (hos_sdl_pad_button(gc, BTN_TOUCHPAD)) mine |= 1ULL << HOS_PAD_TOUCHPAD;
            if (hos_sdl_pad_axis(gc, AX_LT) > 8000) mine |= 1ULL << HOS_PAD_LTRIGGER;
            if (hos_sdl_pad_axis(gc, AX_RT) > 8000) mine |= 1ULL << HOS_PAD_RTRIGGER;
            b |= mine;
            const int inv_x = rx_option(16, 0);
            const int inv_y = rx_option(17, 0);
            const int z = rx_option(11, 0);   /* (the menu's Stick dead zone) */
            int32_t v[4];
            hos_filter_stick(hos_sdl_pad_axis(gc, AX_LX), hos_sdl_pad_axis(gc, AX_LY), z, v);
            hos_filter_stick(hos_sdl_pad_axis(gc, AX_RX), hos_sdl_pad_axis(gc, AX_RY), z, v + 2);
            v[1] = -v[1];   /* SDL's Y axes point down */
            v[3] = -v[3];
            /* (longshot) An axis steers once it has been seen at rest (inside the dead zone) since the pad was opened. The sticks are
               the strongest of all the pads', so a device whose axis reads held for good (a mapping that puts a trigger or an
               unused axis on a stick, a second virtual pad) would turn the camera or walk Link in circles on its own, with the
               player's pad at rest. A real stick rests at the start. */
            /* (a worn stick resting just past a small dead zone counts once it is pushed the other way: it went past its rest) */
            /* Rest is judged per axis, as before the circle: a phantom axis held past the dead zone keeps its partner
               outside the circle, and the partner must still rest at its own center. */
            for (int k = 0; k < 4; k++) {
                int32_t alone[2];
                hos_filter_stick((int16_t)v[k], 0, z, alone);
                const signed char way = (signed char)(alone[0] > 0 ? 1 : alone[0] < 0 ? -1 : 0);
                if (!way || (pads[i].held[k] && way != pads[i].held[k])) pads[i].rested |= 1u << k;
                pads[i].held[k] = way;
                if (!(pads[i].rested >> k & 1)) v[k] = 0;
            }
            /* An axis held back above no longer counts toward its stick's circle, so its partner's drift stays inside
               the dead zone. Values are already clamped and the circle keeps them, so this changes nothing otherwise. */
            hos_filter_stick((int16_t)v[0], (int16_t)v[1], z, v);
            hos_filter_stick((int16_t)v[2], (int16_t)v[3], z, v + 2);
            /* Camera inversion changes output, not whether the physical stick crossed its rest position. Otherwise
               toggling the setting admits a held phantom axis, which stays admitted after the setting is restored. */
            if (inv_x) v[2] = -v[2];
            if (inv_y) v[3] = -v[3];
            for (int k = 0; k < 4; k++)
                if ((v[k] < 0 ? -v[k] : v[k]) > (s[k] < 0 ? -s[k] : s[k])) s[k] = v[k];
            if (pads[i].player >= 0) {
                pl_on[pads[i].player] = 1;
                pl_buttons[pads[i].player] = mine;
                memcpy(pl_stick[pads[i].player], v, sizeof v);
            }
            {   /* (motion: the pad last used; a stick counts by which way it is pushed, not by how far) */
                for (int k = 0; k < 4; k++) sig |= (uint64_t)(v[k] > 0 ? 1 : v[k] < 0 ? 2 : 0) << (32 + 2 * k);
                if (sig != pads[i].input_sig) pads[i].input_sig = sig, pads[i].used_ns = now;
            }
            /* (longshot) what plays its vibration: chosen again each poll (host/vibration.h), then played */
            vib_choose(i, mode, now);
            if (pads[i].used_ns >= status_used) status_used = pads[i].used_ns, status_pad = i;
            if (pads[i].vib == VIB_NONE) continue;
            const int player = pads[i].player;
            const PadRumble *sample = &samples[player >= 0 ? player : VIB_PLAYERS];
            if (pads[i].vib == VIB_HD) {
                uint8_t side[3][4];
                float hv[2][4], felt[3][4];
                memcpy(hv, sample->hd, sizeof hv);
                if (testing) {
                    for (int s = 0; s < 2; s++) {
                        hv[s][0] = hv[s][2] = 0.5f;
                        if (hv[s][1] <= 0.0f) hv[s][1] = 160.0f;
                        if (hv[s][3] <= 0.0f) hv[s][3] = 320.0f;
                    }
                }
                hd_rumble_felt(hv[0], felt[0]);
                hd_rumble_felt(hv[1], felt[1]);
                hd_rumble_encode(felt[0], strength, side[0]);
                hd_rumble_encode(felt[1], strength, side[1]);
                hd_rumble_merge(felt[0], felt[1], felt[2]);   /* a single Joy-Con */
                hd_rumble_encode(felt[2], strength, side[2]);
                if (hd_poll(i, side, now)) continue;   /* (refused: its motors, and chosen again) */
            }
            if (pads[i].vib == VIB_RH_DS_USB || pads[i].vib == VIB_RH_DS_BT) {   /* (their own threads play) */
                /* (HD Haptics' triggers: how far each is pulled, 0 to 255, and whether another button is held) */
                const int lt = hos_sdl_pad_axis(gc, AX_LT), rt = hos_sdl_pad_axis(gc, AX_RT);
                rh_ds_triggers(gc, now, lt > 0 ? lt * 255 / 32767 : 0, rt > 0 ? rt * 255 / 32767 : 0,
                               (sig & 0xFFFFFFFFULL) != 0);
                continue;
            }
            if (pads[i].vib == VIB_RH_STEAM) continue;   /* (its own thread plays) */
            if (pads[i].vib == VIB_RH_XBOX) {
                four_poll(i, now);
                continue;
            }
            if (pads[i].vib == VIB_RH_SWITCH) {
                uint8_t packet[HD_RUMBLE_PACKET_SIZE];
                if (rh_switch_poll(gc, now, packet)) hos_sdl_pad_effect(gc, packet, sizeof packet);
                continue;
            }
            uint16_t motors[2];
            rumble_motors(sample, testing, strength, motors);
            const uint16_t lo = motors[0], hi = motors[1];
            if (rumble_due(lo, hi, pads[i].rumble_lo, pads[i].rumble_hi, now, pads[i].rumble_ns)) {
                hos_sdl_pad_rumble(gc, lo, hi, lo || hi ? 1000 : 0);
                pads[i].rumble_lo = lo;
                pads[i].rumble_hi = hi;
                pads[i].rumble_ns = now;
            }
        }
        {   /* (longshot) the Controls page's vibration line: what plays the pad used last (host/vibration.h) */
            void rx_option_set(int id, int value);
            int st = vibration_status(VIB_PAD_OTHER, VIB_SAY_NO_PAD);
            if (status_pad >= 0) {
                const int k = pads[status_pad].vib_kind;
                st = vibration_status(k, vibration_say(pads[status_pad].vib, k, pads[status_pad].wireless, vib_rh_for(k),
                                                       mode));
            }
            rx_option_set(HOS_OPT_VIBRATION_STATUS, st);
        }
        motion_poll(now, count);
        AcquireSRWLockExclusive(&state_lock);
        state_buttons = b;
        memcpy(state_pl_buttons, pl_buttons, sizeof pl_buttons);
        memcpy(state_pl_stick, pl_stick, sizeof pl_stick);
        memcpy(state_pl_on, pl_on, sizeof pl_on);
        memcpy(state_stick, s, sizeof s);
        state_count = count;
        state_deck_builtin = deck_builtin;
        state_name[0] = 0;
        state_type = state_sdl = 0;
        for (int i = 0; i < MAX_PADS; i++)
            if (pads[i].gc && !pads[i].motion_only) {   /* (the stand-in's name, not its motion-only pad's) */
                const char *name = hos_sdl_pad_name(pads[i].gc);
                snprintf(state_name, sizeof state_name, "%s", name ? name : "");
                static int sdl;   /* (loaded already: a pad is open; the same SDL the whole run) */
                if (!sdl) sdl = hos_sdl_load();
                /* (read each time, as the name: Steam Input's stand-in learns the pad behind it after it opens, and can
                   change to another. A stand-in for a Nintendo pad says no type: Steam can swap its buttons to the letters
                   printed on them, so its name's face, as before) */
                const int type = hos_sdl_pad_type(pads[i].gc);
                state_type = pads[i].steam && hd_rumble_kind(sdl, type) != HD_RUMBLE_NONE ? 0 : type;
                state_sdl = sdl;
                break;
            }
        ReleaseSRWLockExclusive(&state_lock);
}

static DWORD WINAPI pad_main(void *arg) {
    (void)arg;
    hos_host_thread_register_self("gamepads (SDL)");
    if (!pads_start()) return 0;
    for (;;) {
        pads_poll();
        Sleep(4);
    }
}
#ifndef _WIN32
int hos_display_owns_sdl(void);   /* host/posix/display_sdl.c */
/* (linux) SDL also runs the window (host/posix/display_sdl.c), and its event queue is not for two threads. Polled
   from the window's thread, between its events. Two threads pumping it corrupted the heap once a controller was
   attached. */
static volatile LONG pads_loaded;
void hos_sdl_pads_pump(void) {
    static int state;   /* 0 not started, 1 polling, -1 not available */
    if (!state && pads_loaded) state = pads_start() ? 1 : -1;
    if (state > 0) pads_poll();
}
#endif

/* The controllers' merged state (nn_hid.c): ORs their inputs in (1 << HOS_PAD_*), keeps the larger stick
   deflections; returns how many controllers SDL has open. Starts the SDL thread on the first call. When
   deck_builtin_input is not NULL it is set to whether the Deck's built-in controls gave gameplay input in that same
   poll (host/steam_pads.h): read under this lock, so it and the buttons describe one poll. */
int hos_sdl_pads(uint64_t *buttons, int32_t stick[4], int *deck_builtin_input) {
    static volatile LONG started;
    if (deck_builtin_input) *deck_builtin_input = 0;
    if (!started && !InterlockedExchange(&started, 1)) {
        if (env_on("HOS_NO_SDL")) return 0;
        if (!hos_sdl_load()) {
            hos_log("hid: no SDL beside the exe or on the system: only XInput controllers (Xbox pads) work");
            return 0;
        }
#ifdef _WIN32
        CreateThread(NULL, 0, pad_main, NULL, 0, NULL);
        {   /* (longshot) the Switch 2 Pro Controller over USB, which Windows and this SDL have no driver for: host/pad_switch2.c */
            void hos_switch2_start(void);
            hos_switch2_start();
        }
#else
        if (hos_display_owns_sdl())
            InterlockedExchange(&pads_loaded, 1);   /* (the window's thread polls: hos_sdl_pads_pump) */
        else
            CreateThread(NULL, 0, pad_main, NULL, 0, NULL);   /* (no window: nothing else pumps SDL) */
#endif
    }
    AcquireSRWLockShared(&state_lock);
    const int n = state_count;
    *buttons |= state_buttons;
    for (int k = 0; k < 4; k++)
        if ((state_stick[k] < 0 ? -state_stick[k] : state_stick[k]) > (stick[k] < 0 ? -stick[k] : stick[k]))
            stick[k] = state_stick[k];
    if (deck_builtin_input) *deck_builtin_input = state_deck_builtin;
    ReleaseSRWLockShared(&state_lock);
    return n;
}

/* (Wondershot) one player's own pad (0..3: the first pad opened is player 1, the next player 2, a pad that goes away frees its
   number), not merged with the others': 1 with a pad there. nn_hid.c: each player's npad. Needs hos_sdl_pads to have started SDL */
int hos_sdl_pads_player(int player, uint64_t *buttons, int32_t stick[4]) {
    if (player < 0 || player > 3) return 0;
    AcquireSRWLockShared(&state_lock);
    const int on = state_pl_on[player];
    if (on) {
        *buttons |= state_pl_buttons[player];
        for (int k = 0; k < 4; k++)
            if ((state_pl_stick[player][k] < 0 ? -state_pl_stick[player][k] : state_pl_stick[player][k]) >
                (stick[k] < 0 ? -stick[k] : stick[k])) stick[k] = state_pl_stick[player][k];
    }
    ReleaseSRWLockShared(&state_lock);
    return on;
}

/* (motion) the latest readings for nn_hid.c's GetSixAxisSensorStates, newest first: up to max, how many there are; 0
   when there are none (Motion controls off, or no pad with a gyroscope) */
int hos_sdl_motion_history(int player, HosMotionSample *out, int max) {
    if (player < 0 || player > 3) return 0;
    const MotionSlot *m = &mot[player];
    AcquireSRWLockShared(&state_lock);
    const int n = !m->live ? 0 : m->count < max ? m->count : max;
    for (int i = 0; i < n; i++) out[i] = m->hist[(m->head - i + HOS_MOTION_HISTORY) % HOS_MOTION_HISTORY];
    ReleaseSRWLockShared(&state_lock);
    return n;
}
/* (the Insert menu's Motion controls row) 0 no controller, 1 controllers with no gyroscope, 2 one with a gyroscope */
int hos_sdl_gyro_status(void) { return (int)gyro_status; }
/* The first open controller's name into out ("" with none), its SDL type into *type (0 with none, or unknown) and that SDL
   into *sdl (3, 2; 0 with none), each when not NULL */
void hos_sdl_pad_first(char *out, size_t cap, int *type, int *sdl) {
    AcquireSRWLockShared(&state_lock);
    snprintf(out, cap, "%s", state_name);
    if (type) *type = state_type;
    if (sdl) *sdl = state_sdl;
    ReleaseSRWLockShared(&state_lock);
}

/* Both forms of one actuator's sample, published together by the game's vibration thread. */
void hos_sdl_rumble(int player, int side, const float value[4], const float motors[2]) {
    AcquireSRWLockExclusive(&rumble_lock);
    PadRumble *sample = &rumble[player];
    memcpy(sample->hd[side], value, sizeof sample->hd[side]);
    for (int m = 0; m < 2; m++)
        sample->motors[side][m] = (uint16_t)(motors[m] * 65535.0f);
    rh_push(player, side, value);
    ReleaseSRWLockExclusive(&rumble_lock);
}

/* (longshot) the game is over: RenHDrum's backends stop and let go of the pads (host/rumble_renhdrum.c); hos_main.c calls
   it once nnMain has returned */
void hos_sdl_vibration_shutdown(void) { rh_shutdown(); }
