/* (Wonder, Switch 2 Edition) imports Longshot's other games never called, which the generated stubs answered with x0 = 0
   and nothing written: an out parameter the game then read was whatever its stack held, a float result whatever v0 held.
   Each answer here is the offline, no-device one: no network, no friends, no mouse or keyboard, no software keyboard. */
#include "hos.h"
#include <string.h>

/* A failed Result: module | description << 9 (the description only has to be nonzero for the game to take the no path). */
#define FAIL(module, desc) ((uint64_t)(module) | ((uint64_t)(desc) << 9))

static void ret_float(Ctx *c, float f) {
    memset(&c->vreg[0], 0, sizeof c->vreg[0]);
    memcpy(&c->vreg[0], &f, 4);
}

/* ---- nn::hid: Switch 2 mouse (Nmouse, JCMS = Joy-Con mouse sensor), keyboard, vibration ------------------------- */
/* GetKeyboardState(KeyboardState*): sampling number, modifiers, attributes, 256 key bits; 48 bytes, no keys down. */
HLE(_ZN2nn3hid16GetKeyboardStateEPNS0_13KeyboardStateE) { memset(GP(ARG(0)), 0, 48); }
/* GetNmouseStates(int* count, NmouseState*, int, NmouseHandle): none. */
HLE(_ZN2nn3hid15GetNmouseStatesEPiPNS0_11NmouseStateEiNS0_12NmouseHandleE) { if (ARG(0)) G32(ARG(0)) = 0; }
/* GetNmouseTypeSet(BitFlagSet<32>*, NmouseHandle): no type. */
HLE(_ZN2nn3hid16GetNmouseTypeSetEPNS_4util10BitFlagSetILi32ENS0_10NmouseTypeEEENS0_12NmouseHandleE) { G32(ARG(0)) = 0; }
/* IsVibrationPermitted() -> bool: yes (the stub's false turned rumble off). */
HLE(_ZN2nn3hid20IsVibrationPermittedEv) { RET(1); }

/* ---- nn::nifm: no network --------------------------------------------------------------------------------------- */
HLE(_ZN2nn4nifm10InitializeEv) { RET(0); }
HLE(_ZN2nn4nifm18IsNetworkAvailableEv) { RET(0); }
/* GetCurrentIpConfigInfo(in_addr* x5) -> Result: zeros, and a failure (nifm module 110). */
HLE(_ZN2nn4nifm22GetCurrentIpConfigInfoEP7in_addrS2_S2_S2_S2_) {
    for (int i = 0; i < 5; i++)
        if (ARG(i)) G32(ARG(i)) = 0;
    RET(FAIL(110, 300));
}
HLE(_ZN2nn4nifm22GetCurrentProxySettingEPNS0_12ProxySettingE) { RET(FAIL(110, 300)); }
HLE(_ZN2nn4nifm31HandleNetworkRequestErrorResultEv) { RET(FAIL(110, 300)); }

/* ---- nn::friends: none, the list never available (module 121) ------------------------------------------------------ */
HLE(_ZN2nn7friends10InitializeEv) {}
HLE(_ZN2nn7friends27CheckFriendListAvailabilityEPbRKNS_7account3UidE) {
    *(uint8_t *)GP(ARG(0)) = 0;
    RET(0);
}
HLE(_ZN2nn7friends13GetFriendListEPiPNS0_6FriendERKNS_7account3UidEiiRKNS0_12FriendFilterE) {
    if (ARG(0)) G32(ARG(0)) = 0;
    RET(0);
}
HLE(_ZN2nn7friends25EnsureFriendListAvailableEPNS0_12AsyncContextERKNS_7account3UidE) { RET(FAIL(121, 1)); }
/* GetPlayHistoryRegistrationKey(PlayHistoryRegistrationKey*, Uid const&, bool): zeroed (0x40 bytes) and a failure. */
HLE(_ZN2nn7friends29GetPlayHistoryRegistrationKeyEPNS0_26PlayHistoryRegistrationKeyERKNS_7account3UidEb) {
    memset(GP(ARG(0)), 0, 0x40);
    RET(FAIL(121, 1));
}

/* ---- nn::swkbd: work-buffer sizes (PC text entry is in nn_swkbd.c) --------------------- */
HLE(_ZN2nn5swkbd25GetRequiredWorkBufferSizeEb) { RET(0xd000); }
HLE(_ZN2nn5swkbd27GetRequiredStringBufferSizeEv) { RET(0x7d4); }
HLE(_ZN2nn5swkbd34GetRequiredTextCheckWorkBufferSizeEv) { RET(0x7d4); }


/* ---- nn::audio: the two float getters (their answer is in v0) ---------------------------------------------------- */
HLE(_ZN2nn5audio26GetAudioDeviceOutputVolumeEPKNS0_15AudioDeviceNameE) { ret_float(c, 1.0f); }
HLE(_ZN2nn5audio34GetAudioRendererVoiceDropParameterENS0_19AudioRendererHandleE) { ret_float(c, 1.0f); }
/* GetDefaultVirtualOutputDevice(AudioDeviceName*): char[256]. */
HLE(_ZN2nn5audio29GetDefaultVirtualOutputDeviceEPNS0_15AudioDeviceNameE) {
    memset(GP(ARG(0)), 0, 256);
    memcpy(GP(ARG(0)), "MainAudioOut", 12);
}
