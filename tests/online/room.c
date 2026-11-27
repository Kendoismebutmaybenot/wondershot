#include <assert.h>
#include "hos.h"
#define HOS_H
#include "../../host/nn_wonder_ldn.c"

void imp__ZN2nn2os17CreateSystemEventEPNS0_15SystemEventTypeENS0_14EventClearModeEb(Ctx *c) { RET(0); }
void hos_system_event_signal(uint64_t key) { (void)key; }
void hos_sleep_ns(int64_t ns) { Sleep((DWORD)(ns / 1000000)); }
int hos_vcore_away(void) { return 0; }
void hos_vcore_back(void) {}
void f_83e23480(Ctx *c) { (void)c; assert(!"Unexpected real SDK call"); }

static unsigned bind_test_socket(void) {
    Ctx c = {{2, 2, 17}};
    imp__ZN2nn6socket6SocketEiii(&c);
    unsigned fd = (unsigned)c.x[0];
    unsigned char addr[16] = {16, 2, 0x45, 0x23};
    c = (Ctx){{fd, (uintptr_t)addr, sizeof addr}};
    imp__ZN2nn6socket4BindEiPK8sockaddrj(&c);
    assert(!c.x[0]);
    return fd;
}
static void send_test(unsigned fd, unsigned node, const char *message) {
    unsigned char addr[16] = {16, 2, 0x45, 0x23, 169, 254, 114};
    addr[7] = (unsigned char)(node + 1);
    Ctx c = {{fd, (uintptr_t)message, strlen(message), 0, (uintptr_t)addr, sizeof addr}};
    imp__ZN2nn6socket6SendToEiPKvmiPK8sockaddrj(&c);
    assert(c.x[0] == strlen(message));
}
static void receive_test(unsigned fd, unsigned node, const char *message) {
    for (int i = 0; i < 10000; ++i) {
        char payload[32] = {0};
        unsigned char addr[16] = {0};
        uint32_t addr_size = sizeof addr;
        Ctx c = {{fd, (uintptr_t)payload, sizeof payload, 0, (uintptr_t)addr, (uintptr_t)&addr_size}};
        imp__ZN2nn6socket8RecvFromEiPvmiP8sockaddrPj(&c);
        if (c.x[0] == UINT64_MAX) continue;
        assert(c.x[0] == strlen(message) && !strcmp(payload, message));
        assert(addr_size == 16 && addr[0] == 16 && addr[1] == 2 && addr[7] == node + 1);
        return;
    }
    assert(!"No packet received");
}

int main(int argc, char **argv) {
    Ctx c = {0};
    assert(argc == 2 && hos_wonder_ldn_enabled());
    hos_wonder_discovery_socket_init(&c);
    assert(!c.x[0]);
    imp__ZN2nn6socket13IsInitializedEv(&c);
    assert(c.x[0] == 1);
    imp__ZN2nn3ldn10InitializeEv(&c);
    assert(!c.x[0]);
    if (!strcmp(argv[1], "host")) {
        unsigned char cfg[32] = {0}, security[68] = {0}, user[48] = "Test host";
        if (getenv("WONDER_CHECK_PASSWORD")) { security[0]=1; security[2]=4; memcpy(security+4,"1234",4); }
        cfg[0] = 42; cfg[0x12] = 8;
        imp__ZN2nn3ldn15OpenAccessPointEv(&c);
        c = (Ctx){{(uintptr_t)"Wonder", 6}};
        imp__ZN2nn3ldn16SetAdvertiseDataEPKvm(&c);
        assert(!c.x[0]);
        c = (Ctx){{(uintptr_t)cfg, (uintptr_t)security, (uintptr_t)user}};
        imp__ZN2nn3ldn13CreateNetworkERKNS0_13NetworkConfigERKNS0_14SecurityConfigERKNS0_10UserConfigE(&c);
        assert(!c.x[0]);
        unsigned fd = bind_test_socket();
        unsigned char empty[1] = {0};
        c = (Ctx){{fd, (uintptr_t)empty, sizeof empty}};
        imp__ZN2nn6socket8RecvFromEiPvmiP8sockaddrPj(&c);
        assert(c.x[0] == UINT64_MAX);
        imp__ZN2nn6socket12GetLastErrnoEv(&c);
        assert(c.x[0] == 11);
        puts("ready");
        fflush(stdout);
        receive_test(fd, 1, "from guest");
        send_test(fd, 1, "from host");
        if (getenv("WONDER_REPEAT_GUEST")) { receive_test(fd, 1, "from guest"); send_test(fd, 1, "from host"); }
        (void)getchar();
        imp__ZN2nn3ldn14DestroyNetworkEv(&c);
        assert(!c.x[0]);
    } else {
        unsigned char filter[0x60] = {0}, info[INFO_SIZE] = {0};
        uint32_t count = 0;
        filter[0] = 42; filter[0x5c] = 1;
        imp__ZN2nn3ldn11OpenStationEv(&c);
        c = (Ctx){{(uintptr_t)info, (uintptr_t)&count, 1, (uintptr_t)filter}};
        imp__ZN2nn3ldn4ScanEPNS0_11NetworkInfoEPiiRKNS0_10ScanFilterEi(&c);
        assert(!c.x[0]);
        if (!strcmp(argv[1], "guest")) {
            assert(count == 1 && info[0x67] == 1 && info[AD_SIZE] == 6);
            assert(!memcmp(info + AD_DATA, "Wonder", 6));
            filter[0] = 43;
            c.x[0] = (uintptr_t)info;
            imp__ZN2nn3ldn4ScanEPNS0_11NetworkInfoEPiiRKNS0_10ScanFilterEi(&c);
            assert(!c.x[0] && count == 0);
            unsigned char security[68] = {0}, user[48] = "Test guest";
            if (getenv("WONDER_CHECK_PASSWORD")) {
                security[0]=1; security[2]=4; memcpy(security+4,"1234",4);
                security[4] ^= 1;
                c = (Ctx){{(uintptr_t)info, (uintptr_t)security, (uintptr_t)user}};
                imp__ZN2nn3ldn7ConnectERKNS0_11NetworkInfoERKNS0_14SecurityConfigERKNS0_10UserConfigEiNS0_13ConnectOptionE(&c);
                assert(c.x[0] != 0); security[4] ^= 1;
            }
            c = (Ctx){{(uintptr_t)info, (uintptr_t)security, (uintptr_t)user}};
            imp__ZN2nn3ldn7ConnectERKNS0_11NetworkInfoERKNS0_14SecurityConfigERKNS0_10UserConfigEiNS0_13ConnectOptionE(&c);
            assert(!c.x[0]);
            imp__ZN2nn3ldn8GetStateEv(&c);
            assert(c.x[0] == CONNECTED);
            c.x[0] = (uintptr_t)info;
            imp__ZN2nn3ldn14GetNetworkInfoEPNS0_11NetworkInfoE(&c);
            assert(!c.x[0] && info[0x67] == 2 && info[0xb3] == 1);
#ifdef WONDER_WITH_ONLINE
            if (online_mode) {
                ULONGLONG started = GetTickCount64();
                for (int i = 0; i < 1000; ++i) {
                    c.x[0] = (uintptr_t)info;
                    imp__ZN2nn3ldn14GetNetworkInfoEPNS0_11NetworkInfoE(&c);
                    assert(!c.x[0]);
                }
                assert(GetTickCount64() - started < 200);
            }
#endif
            unsigned char parameter[32];
            c.x[0] = (uintptr_t)parameter;
            imp__ZN2nn3ldn20GetSecurityParameterEPNS0_17SecurityParameterE(&c);
            assert(!c.x[0] && !memcmp(parameter, info + 0x50, 16) &&
                   !memcmp(parameter + 16, info + 0x10, 16));
            unsigned fd = bind_test_socket();
#ifdef WONDER_WITH_ONLINE
            for (int i = 0; online_mode && !wonder_online_ready() && i < 300; ++i) Sleep(100);
            assert(!online_mode || wonder_online_ready());
#endif
            send_test(fd, 0, "from guest");
            receive_test(fd, 0, "from host");
            imp__ZN2nn3ldn10DisconnectEv(&c);
            assert(!c.x[0]);
        } else {
            assert(count == 0);
        }
    }
    imp__ZN2nn3ldn8FinalizeEv(&c);
    return 0;
}
