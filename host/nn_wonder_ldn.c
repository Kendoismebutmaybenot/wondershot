/* Two-player Local Wireless SDK adapter. Layout and state references:
   Recompia runtime/src/services/ldn_types.h (6c3ed6dc, GPL-3.0-or-later),
   with its cited Ryujinx and Switchbrew LDN references.
   Wondershot calls the SDK functions directly, rather than sending IPC commands.
   One host and one station. Online gameplay uses encrypted WebRTC data channels;
   loopback UDP remains available to the isolated transport tests. */
#include "hos.h"
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#ifdef WONDER_WITH_ONLINE
#include "wonder_online/online_ui.h"
#endif
#endif

enum { LDN_DISABLED = 203 | (16 << 9), LDN_STATE = 203 | (32 << 9),
       LDN_MISSING = 203 | (65 << 9), LDN_ARGUMENT = 203 | (96 << 9) };
enum { NONE, INITIALIZED, ACCESS_POINT, HOSTING, STATION, CONNECTED };
enum { INFO_SIZE = 0x480, AD_SIZE = 0x26a, AD_DATA = 0x26c, AD_MAX = 384 };

int hos_wonder_ldn_enabled(void) {
#ifdef _WIN32
    return 1; /* SDK replacement stays active even when online is disabled in the menu. */
#else
    return 0;
#endif
}

#ifdef _WIN32
enum { PEERS = 2, QUEUE_SIZE = 64, DATA_SIZE = 2048, FD_COUNT = 16, FD_BASE = 3 };
#define VIRTUAL_IP(node) (0xa9fe7201u + (unsigned)(node))

typedef struct { uint16_t guest_port, host_port; } Endpoint;
typedef struct {
    DWORD owner, station;
    unsigned char info[INFO_SIZE];
    Endpoint endpoints[PEERS][FD_COUNT];
} Room;

typedef struct {
    int open;
    uint16_t port;
    SOCKET socket;
    uint32_t sequence;
    ULONGLONG keepalive;
} LocalSocket;
static SRWLOCK state_lock = SRWLOCK_INIT;
static SOCKET registry_socket = INVALID_SOCKET;
static Room *room;
static unsigned state;
static uint64_t event;
static unsigned char pending_advertise[AD_MAX];
static unsigned pending_size;
static LocalSocket sockets[FD_COUNT];
static _Thread_local unsigned socket_error;
static volatile LONG socket_initialized;

static int relay_mode;
static int online_mode;
static DWORD online_identity;
#ifdef WONDER_WITH_ONLINE
uint32_t wonder_online_start(const char *, const char *, const char *);
int wonder_online_acquire(void *, unsigned);
int wonder_online_commit(const void *, unsigned);
int wonder_online_read(void *, unsigned);
int wonder_online_send(const void *, unsigned);
int wonder_online_receive(void *, unsigned, uint16_t);
int wonder_online_ready(void);
int wonder_online_route(void);
void wonder_online_set_logger(void (*)(const char *));
static void online_log(const char *message) { hos_log("wonder-online: %s", message); }
#endif
static struct sockaddr_in relay_address;
static unsigned char relay_key[32], relay_token[16];
static BCRYPT_ALG_HANDLE relay_sha, relay_hmac;
static NTSTATUS relay_hash(BCRYPT_ALG_HANDLE algorithm, PUCHAR key, ULONG key_size,
                           PUCHAR data, ULONG size, PUCHAR output, ULONG output_size) {
    BCRYPT_HASH_HANDLE hash = NULL;
    NTSTATUS status = BCryptCreateHash(algorithm, &hash, NULL, 0, key, key_size, 0);
    if (status >= 0) status = BCryptHashData(hash, data, size, 0);
    if (status >= 0) status = BCryptFinishHash(hash, output, output_size, 0);
    if (hash) BCryptDestroyHash(hash);
    return status;
}
static DWORD owner_identity(void) {
    DWORD identity;
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto()) return wonder_online_identity();
#endif
    if (online_mode) return online_identity;
    if (!relay_mode) return GetCurrentProcessId();
    memcpy(&identity, relay_token, 4);
    return identity;
}
static int relay_setup(void) {
    const char *address = getenv("WONDER_RELAY");
#ifdef WONDER_WITH_ONLINE
    const char *online_url = getenv("WONDER_ONLINE_URL");
    if (online_url && *online_url) address = "127.0.0.1:1";
    if (wonder_online_auto()) address = "127.0.0.1:1";
#endif
    if (!address || !*address) return 1;
    const char *code = getenv("WONDER_ROOM_CODE");
#ifdef WONDER_WITH_ONLINE
    if (wonder_online_auto()) {
        if (!wonder_profile_enabled()) return 0;
        code = "00000000000000000000000000000000";
    }
#endif
    if (!code || strlen(code) < 8 || strlen(code) > 64 || strlen(address) > 240) return 0;
    char host[256], port[8];
    const char *colon = strrchr(address, ':');
    if (!colon || colon == address || strlen(colon + 1) >= sizeof port) return 0;
    memcpy(host, address, colon - address); host[colon - address] = 0;
    strcpy(port, colon + 1);
    struct addrinfo hints = {0}, *result = NULL;
    hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, port, &hints, &result)) return 0;
    memcpy(&relay_address, result->ai_addr, sizeof relay_address);
    freeaddrinfo(result);
    if (BCryptOpenAlgorithmProvider(&relay_sha, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0 ||
        BCryptOpenAlgorithmProvider(&relay_hmac, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG) < 0 ||
        relay_hash(relay_sha, NULL, 0, (PUCHAR)code, (ULONG)strlen(code), relay_key, 32) < 0 ||
        BCryptGenRandom(NULL, relay_token, 16, BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0) return 0;
    if (!memcmp(relay_token, "\0\0\0\0", 4)) relay_token[0] = 1;
    relay_mode = 1;
#ifdef WONDER_WITH_ONLINE
    if (wonder_online_auto()) {
        online_mode = 1; wonder_online_set_logger(online_log);
        return 1;
    }
    if (online_url && *online_url) {
        const char *token = getenv("WONDER_ONLINE_TOKEN");
        if (!token || !*token) return 0;
        wonder_online_set_logger(online_log);
        online_identity = wonder_online_start(online_url, code, token);
        if (!online_identity) return 0;
        online_mode = 1;
        hos_log("wonder-ldn: encrypted WebRTC transport initialized");
        return 1;
    }
#endif
    hos_log("wonder-ldn: legacy relay transport initialized");
    return 1;
}
#ifdef WONDER_WITH_ONLINE
static int refresh_online_room_key(void) {
    char code[33];
    return wonder_online_copy_code(code, sizeof code) &&
        relay_hash(relay_sha, NULL, 0, (PUCHAR)code, 32, relay_key, 32) >= 0;
}
#endif
void imp__ZN2nn2os17CreateSystemEventEPNS0_15SystemEventTypeENS0_14EventClearModeEb(Ctx *);
void hos_system_event_signal(uint64_t);

/* The game's room task initializes BSD before touching LDN. This prototype
   supplies a Winsock-backed Local Wireless transport for its datagram calls. */
void f_83e23480(Ctx *);
void hos_wonder_discovery_socket_init(Ctx *c) {
    if (!hos_wonder_ldn_enabled()) {
        f_83e23480(c);
        return;
    }

    if (!socket_initialized) {
        WSADATA data;
        if (WSAStartup(MAKEWORD(2, 2), &data) || !relay_setup()) { RET(LDN_DISABLED); return; }
    }
    InterlockedExchange(&socket_initialized, 1);
    hos_log("wonder-ldn: room task initialized local test sockets");
    RET(0);
}

static void put(void *base, size_t offset, uint64_t value, size_t width) {
    memcpy((unsigned char *)base + offset, &value, width);
}
static unsigned get32(const void *base, size_t offset) {
    unsigned value;
    memcpy(&value, (const unsigned char *)base + offset, sizeof value);
    return value;
}
static uint16_t get16(const void *base, size_t offset) {
    uint16_t value;
    memcpy(&value, (const unsigned char *)base + offset, sizeof value);
    return value;
}
static uint16_t swap16(uint16_t value) {
    return (uint16_t)((value >> 8) | (value << 8));
}
static uint32_t swap32(uint32_t value) {
    return ((uint32_t)swap16((uint16_t)value) << 16) | swap16((uint16_t)(value >> 16));
}
static void clear_station(void) {
    room->station = 0;
    room->info[0x67] = 1;
    memset(room->info + 0xa8, 0, 64);
    memset(room->endpoints[1], 0, sizeof room->endpoints[1]);
}
static int exited(DWORD pid) {
    if (relay_mode || !pid || pid == GetCurrentProcessId()) return 0;
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) return GetLastError() == ERROR_INVALID_PARAMETER;
    int result = WaitForSingleObject(process, 0) == WAIT_OBJECT_0;
    CloseHandle(process);
    return result;
}

_Static_assert(sizeof(Room) == 1288, "Room registry wire size");
static int transfer(SOCKET socket, void *buffer, unsigned size, int sending) {
    unsigned offset = 0;
    while (offset < size) {
        int count = sending ? send(socket, (const char *)buffer + offset, size - offset, 0) :
                              recv(socket, (char *)buffer + offset, size - offset, 0);
        if (count <= 0) return 0;
        offset += (unsigned)count;
    }
    return 1;
}
static int open_room(void) {
    if (!room) room = calloc(1, sizeof(Room));
    return room != NULL;
}
static int lock_room(void) {
    if (!room) return 0;
#ifdef WONDER_WITH_ONLINE
    if (online_mode) return wonder_online_acquire(room, sizeof(Room));
#endif
    registry_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (registry_socket == INVALID_SOCKET) return 0;
    DWORD timeout = 1000;
    int enabled = 1;
    setsockopt(registry_socket, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof timeout);
    setsockopt(registry_socket, SOL_SOCKET, SO_SNDTIMEO, (const char *)&timeout, sizeof timeout);
    setsockopt(registry_socket, IPPROTO_TCP, TCP_NODELAY, (const char *)&enabled, sizeof enabled);
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(47680);
    if (relay_mode) address = relay_address;
    if (connect(registry_socket, (const struct sockaddr *)&address, sizeof address) ||

        !transfer(registry_socket, relay_mode ? "WLR4" : "WLR3", 4, 1) ||
        (relay_mode && (!transfer(registry_socket, relay_key, 32, 1) ||
                        !transfer(registry_socket, relay_token, 16, 1))) ||
        !transfer(registry_socket, room, sizeof(Room), 0)) {
        closesocket(registry_socket);
        registry_socket = INVALID_SOCKET;
        return 0;
    }
    if (exited(room->owner)) room->owner = 0;
    if (room->station && (!room->owner || exited(room->station))) clear_station();
    return 1;
}
static void unlock_room(void) {
#ifdef WONDER_WITH_ONLINE
    if (online_mode) {
        if (!wonder_online_commit(room, sizeof(Room))) hos_log("wonder-ldn: online room transaction failed");
        return;
    }
#endif
    if (registry_socket == INVALID_SOCKET) return;
    char reply[2];
    if (!transfer(registry_socket, room, sizeof(Room), 1) ||
        !transfer(registry_socket, reply, sizeof reply, 0) || memcmp(reply, "OK", 2))
        hos_log("wonder-ldn: room registry transaction failed");
    closesocket(registry_socket);
    registry_socket = INVALID_SOCKET;
}
static void transition(unsigned next) {
    state = next;
    hos_log("wonder-ldn: state %u", next);
    if (event) hos_system_event_signal(event);
}
static int lock_room_read(void) {
#ifdef WONDER_WITH_ONLINE
    if (online_mode) return room && wonder_online_read(room, sizeof(Room));
#endif
    return lock_room();
}
static void unlock_room_read(void) {
    if (!online_mode) unlock_room();
}
static unsigned close_host(unsigned next) {
    if (state == HOSTING || state == CONNECTED) {
        if (lock_room()) {
            if (room->owner == owner_identity()) {
                room->owner = 0;
                clear_station();
            } else if (room->station == owner_identity()) {
                clear_station();
            }
            unlock_room();
        } else if (!online_mode) return LDN_DISABLED;
    }
    pending_size = 0;
    transition(next);
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto()) wonder_online_disconnect();
#endif
    return 0;
}
static unsigned create_room(Ctx *c, int private_room) {
    if (state != ACCESS_POINT) return LDN_STATE;
    if (!ARG(0) || !ARG(1) || !ARG(2) || (private_room && !ARG(3))) return LDN_ARGUMENT;
    const unsigned char *cfg = GP(ARG(0)), *security = GP(ARG(1));
    const unsigned char *user = GP(ARG(private_room ? 3 : 2));
    if (!cfg[0x12] || cfg[0x12] > 8) return LDN_ARGUMENT;
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto() && (!wonder_online_prepare_host(security) || !refresh_online_room_key())) return LDN_DISABLED;
#endif
    if (!lock_room()) return LDN_DISABLED;
    if (room->owner) {
        unlock_room();
        return LDN_STATE;
    }
    unsigned char *info = room->info;
    memset(info, 0, INFO_SIZE);
    DWORD pid = owner_identity();
    memcpy(info, cfg, 16);
    if (private_room) {
        const unsigned char *parameter = GP(ARG(2));
        memcpy(info + 0x10, parameter + 16, 16);
        memcpy(info + 0x50, parameter, 16);
    } else {
        put(info, 0x10, GetTickCount64(), 8);
        put(info, 0x18, pid, 4);
        memcpy(info + 0x50, info + 0x10, 16);
    }
    put(info, 0x478, ((uint64_t)pid << 32) | (uint32_t)GetTickCount64(), 8);
    put(info, 0x20, ((uint64_t)pid << 8) | 2, 6);
    info[0x26] = 8;
    memcpy(info + 0x27, "WonderPC", 8);
    memcpy(info + 0x48, cfg + 0x10, 2);
    if (!info[0x48] && !info[0x49]) info[0x48] = 6;
    info[0x4a] = 3;
    info[0x4b] = 2;
    memcpy(info + 0x60, security, 2);
    info[0x66] = cfg[0x12];
    info[0x67] = 1;
    put(info, 0x68, VIRTUAL_IP(0), 4);
    memcpy(info + 0x6c, info + 0x20, 6);
    info[0x73] = 1;
    memcpy(info + 0x74, user, 32);
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto()) wonder_profile_name((char *)info + 0x74, 33);
#endif
    memcpy(info + 0x96, cfg + 0x14, 2);
    put(info, AD_SIZE, pending_size, 2);
    memcpy(info + AD_DATA, pending_advertise, pending_size);
    room->station = 0;
    memset(room->endpoints, 0, sizeof room->endpoints);
    room->owner = pid;
    unlock_room();
    transition(HOSTING);
    hos_log("wonder-ldn: advertised %s room (capacity %u)", private_room ? "private" : "public", cfg[0x12]);
    return 0;
}
static int matches(const unsigned char *info, const unsigned char *filter) {
    unsigned flags = get32(filter, 0x5c);
    return (!(flags & 1) || !memcmp(info, filter, 8)) &&
           (!(flags & 2) || !memcmp(info + 0x10, filter + 0x10, 16)) &&
           (!(flags & 4) || (get32(filter, 0x20) & info[0x4b])) &&
           (!(flags & 8) || !memcmp(info + 0x20, filter + 0x24, 6)) &&
           (!(flags & 16) || (filter[0x2a] == info[0x26] &&
                              !memcmp(info + 0x27, filter + 0x2b, info[0x26]))) &&
           (!(flags & 32) || !memcmp(info + 0xa, filter + 0xa, 2));
}
static unsigned scan(Ctx *c) {
    if (!ARG(1)) return LDN_ARGUMENT;
    G32(ARG(1)) = 0;
    if (state < ACCESS_POINT) return LDN_STATE;
    if (!ARG(0) || !ARG(3) || (int32_t)ARG(2) < 1) return LDN_ARGUMENT;
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto()) {
        unsigned char found[16][INFO_SIZE];
        int count = wonder_online_scan(found, 16);
        if (count < 0) return LDN_DISABLED;
        unsigned written = 0;
        for (int i = 0; i < count && written < (unsigned)ARG(2); ++i) {
            if (!matches(found[i], GP(ARG(3)))) continue;
            memcpy((unsigned char *)GP(ARG(0)) + written++ * INFO_SIZE, found[i], INFO_SIZE);
        }
        G32(ARG(1)) = written;
        hos_log("wonder-ldn: internet scan returned %u rooms", written);
        return 0;
    }
#endif
    if (!lock_room()) return LDN_DISABLED;
    if (room->owner && room->owner != owner_identity() && matches(room->info, GP(ARG(3)))) {
        memcpy(GP(ARG(0)), room->info, INFO_SIZE);
        G32(ARG(1)) = 1;
        static DWORD logged_owner;
        if (logged_owner != room->owner) {
            logged_owner = room->owner;
            hos_log("wonder-ldn: scan returned a room from the other process");
        }
    }
    unlock_room();
    return 0;
}

static unsigned join_room(Ctx *c, int private_room) {
    if (state != STATION) return LDN_STATE;
    if (!ARG(0) || !ARG(1) || !ARG(2) || (private_room && !ARG(3))) return LDN_ARGUMENT;
    const unsigned char *target = GP(ARG(0));
#ifdef WONDER_WITH_ONLINE
    if (online_mode && wonder_online_auto() && (!wonder_online_prepare_join(target, GP(ARG(1))) || !refresh_online_room_key())) return LDN_MISSING;
#endif
    const unsigned char *user = GP(ARG(private_room ? 3 : 2));
    unsigned version = (unsigned)ARG(private_room ? 4 : 3);
    const unsigned char *session = private_room ? (const unsigned char *)GP(ARG(2)) + 16 : target + 16;
    if (!lock_room()) return LDN_DISABLED;
    unsigned result = LDN_MISSING;
    if (room->owner && room->owner != owner_identity() &&
        !memcmp(room->info, target, 8) && !memcmp(room->info + 16, session, 16)) {
        if (room->station || room->info[0x66] < 2) {
            result = 203 | (144 << 9);
        } else if (version != get16(room->info, 0x96)) {
            result = 203 | ((version < get16(room->info, 0x96) ? 113 : 114) << 9);
        } else {
            unsigned char *node = room->info + 0xa8;
            DWORD pid = owner_identity();
            clear_station();
            room->station = pid;
            room->info[0x67] = 2;
            put(node, 0, VIRTUAL_IP(1), 4);
            put(node, 4, ((uint64_t)pid << 8) | 2, 6);
            node[10] = 1;
            node[11] = 1;
            memcpy(node + 12, user, 32);
#ifdef WONDER_WITH_ONLINE
            if (online_mode && wonder_online_auto()) wonder_profile_name((char *)node + 12, 33);
#endif
            put(node, 0x2e, version, 2);
            result = 0;
        }
    }
    unlock_room();
    if (!result) transition(CONNECTED);
    hos_log("wonder-ldn: join result %#x", result);
    return result;
}

static int own_node(void) {
    DWORD pid = owner_identity();
    if (state == HOSTING && room->owner == pid) return 0;
    if (state == CONNECTED && room->station == pid) return 1;
    return -1;
}
static LocalSocket *fd_at(uint64_t fd) {
    return fd >= FD_BASE && fd < FD_BASE + FD_COUNT && sockets[fd - FD_BASE].open ?
           &sockets[fd - FD_BASE] : NULL;
}
static uint64_t sock_fail(unsigned error) {
    socket_error = error;
    /* SendTo and RecvFrom return a signed 64-bit count. */
    return UINT64_MAX;
}
static uint64_t open_socket(unsigned family, unsigned type, unsigned protocol) {
    if (family != 2 || (type & 0xf) != 2 || (protocol != 0 && protocol != 17))
        return sock_fail(93);
    for (unsigned i = 0; i < FD_COUNT; ++i) {
        if (sockets[i].open) continue;

        SOCKET handle = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (handle == INVALID_SOCKET) return sock_fail(24);
        u_long nonblocking = 1;
        if (ioctlsocket(handle, FIONBIO, &nonblocking)) {
            closesocket(handle);
            return sock_fail(22);
        }
        sockets[i] = (LocalSocket){.open = 1, .socket = handle};
        hos_log("wonder-ldn: created local datagram socket %u", i + FD_BASE);
        return i + FD_BASE;
    }
    return sock_fail(24);
}


enum { RELAY_HEADER = 96 };
static uint64_t sock_fail(unsigned error);
static int relay_send(LocalSocket *fd, int peer, uint16_t port, const void *data, unsigned size) {
    if (!room) return 0;
    int node = own_node();
    unsigned char wire[RELAY_HEADER + DATA_SIZE] = {'W', 'L', 'D', '4'};
    memcpy(wire + 4, relay_key, 32);
    memcpy(wire + 36, room->info + 16, 16);
    if (node < 0) return 0;
    if (online_mode && !size) return 1;
#ifdef WONDER_WITH_ONLINE
    static int logged_route;
    if (online_mode && wonder_online_ready() && !logged_route) {
        logged_route = wonder_online_route();
        hos_log("wonder-ldn: encrypted WebRTC channel uses %s", logged_route == 2 ? "Cloudflare TURN" : logged_route == 1 ? "direct P2P" : "an encrypted route being identified");
    }
#endif
    wire[52] = (unsigned char)node;
    wire[53] = (unsigned char)peer;
    put(wire, 54, fd->port, 2);
    put(wire, 56, port, 2);
    put(wire, 58, htons((uint16_t)size), 2);
    put(wire, 60, htonl(++fd->sequence), 4);
    if (size) memcpy(wire + RELAY_HEADER, data, size);
    unsigned char mac[32];
    if (relay_hash(relay_hmac, online_mode ? relay_key : relay_token, online_mode ? 32 : 16, wire, RELAY_HEADER + size, mac, 32) < 0) return 0;
    memcpy(wire + 64, mac, 32);
#ifdef WONDER_WITH_ONLINE
    if (online_mode) {
        if (!wonder_online_ready()) return 1; /* UDP may drop before the peer connects. */
        return wonder_online_send(wire, RELAY_HEADER + size);
    }
#endif
    return sendto(fd->socket, (const char *)wire, RELAY_HEADER + size, 0,
                  (const struct sockaddr *)&relay_address, sizeof relay_address) != SOCKET_ERROR;
}
static uint64_t bind_socket(Ctx *c) {
    LocalSocket *fd = fd_at(ARG(0));
    if (!fd) return sock_fail(9);
    if (!ARG(1) || ARG(2) < 8 || fd->port) return sock_fail(22);
    const unsigned char *addr = GP(ARG(1));
    uint16_t port = get16(addr, 2);
    if (!port || (addr[1] != 2 && get16(addr, 0) != 2)) return sock_fail(22);
    struct sockaddr_in local = {0};
    local.sin_family = AF_INET;
    local.sin_addr.s_addr = htonl(relay_mode ? INADDR_ANY : INADDR_LOOPBACK);
    if (bind(fd->socket, (struct sockaddr *)&local, sizeof local)) return sock_fail(98);
    int length = sizeof local;
    if (getsockname(fd->socket, (struct sockaddr *)&local, &length)) return sock_fail(22);
    if (!lock_room()) return sock_fail(11);
    int node = own_node();
    if (node < 0) { unlock_room(); return sock_fail(101); }
    unsigned slot = (unsigned)(fd - sockets);
    room->endpoints[node][slot] = (Endpoint){port, local.sin_port};
    unlock_room();

    fd->port = port;
    if (relay_mode) {
        relay_send(fd, 0, port, NULL, 0);
        fd->keepalive = GetTickCount64();
    }
    hos_log("wonder-ldn: virtual gameplay socket bound");
    return 0;
}

/* Fixed wire header: magic/version, session id, source node, target node,
   guest source/destination ports, payload length. Integers are network order. */
enum { WIRE_HEADER = 32 };
static uint64_t send_packet(Ctx *c) {
    LocalSocket *fd = fd_at(ARG(0));
    if (!fd) return sock_fail(9);
    if (!fd->port || !ARG(1) || !ARG(4) || ARG(5) < 8 || ARG(2) > DATA_SIZE) return sock_fail(22);
    const unsigned char *addr = GP(ARG(4));
    uint32_t ip = swap32(get32(addr, 4));
    if (!relay_mode && !lock_room()) return sock_fail(11);
    int node = own_node(), peer = -1;
    if (ip == VIRTUAL_IP(0)) peer = 0;
    if (ip == VIRTUAL_IP(1)) peer = 1;
    if (node >= 0 && (ip == 0xffffffffu || ip == 0xa9fe72ffu)) peer = 1 - node;
    unsigned char wire[WIRE_HEADER + DATA_SIZE] = {'W', 'L', 'D', 3};
    uint16_t host_port = 0, destination = get16(addr, 2);
    if (node >= 0 && peer >= 0) {
        for (unsigned i = 0; i < FD_COUNT; ++i)
            if (room->endpoints[peer][i].guest_port == destination) {
                host_port = room->endpoints[peer][i].host_port;
                break;
            }
        memcpy(wire + 4, room->info + 16, 16);
    }
    if (!relay_mode) unlock_room();
    if (node < 0 || peer < 0) return sock_fail(101);

    if (relay_mode) {
        if (!relay_send(fd, peer, destination, GP(ARG(1)), (unsigned)ARG(2))) return sock_fail(11);
        static unsigned logged;
        if (logged++ < 6) hos_log("wonder-ldn: RELAY sent %u bytes to node %d", (unsigned)ARG(2), peer);
        return ARG(2);
    }
    if (!host_port) return ARG(2); /* UDP permits packets to absent peers to be lost. */
    wire[20] = (unsigned char)node;
    wire[21] = (unsigned char)peer;
    put(wire, 22, fd->port, 2);
    put(wire, 24, destination, 2);
    put(wire, 26, htons((uint16_t)ARG(2)), 2);
    memcpy(wire + WIRE_HEADER, GP(ARG(1)), (size_t)ARG(2));
    struct sockaddr_in target = {0};
    target.sin_family = AF_INET;
    target.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    target.sin_port = host_port;
    int sent = sendto(fd->socket, (const char *)wire, WIRE_HEADER + (int)ARG(2), 0,
                      (const struct sockaddr *)&target, sizeof target);
    if (sent == SOCKET_ERROR) return sock_fail(WSAGetLastError() == WSAEWOULDBLOCK ? 11 : 5);
    static unsigned logged;
    if (logged++ < 6) hos_log("wonder-ldn: UDP sent %u bytes to node %d", (unsigned)ARG(2), peer);
    return ARG(2);
}


static uint64_t relay_receive(Ctx *c, LocalSocket *fd) {
    if (GetTickCount64() - fd->keepalive >= 500) {
        relay_send(fd, 0, fd->port, NULL, 0);
        fd->keepalive = GetTickCount64();
    }
    unsigned char wire[RELAY_HEADER + DATA_SIZE], mac[32], supplied[32];
    struct sockaddr_in source = {0};
    int source_size = sizeof source;
    int size;
#ifdef WONDER_WITH_ONLINE
    if (online_mode) size = wonder_online_receive(wire, sizeof wire, fd->port);
    else
#endif
    size = recvfrom(fd->socket, (char *)wire, sizeof wire, 0,
                    (struct sockaddr *)&source, &source_size);
    if (online_mode && size < 0) return sock_fail(11);
    if (size == SOCKET_ERROR) return sock_fail(WSAGetLastError() == WSAEWOULDBLOCK ? 11 : 5);
    if (size < RELAY_HEADER || memcmp(wire, "WLD4", 4) || memcmp(wire + 4, relay_key, 32) ||
        (!online_mode && (source.sin_addr.s_addr != relay_address.sin_addr.s_addr || source.sin_port != relay_address.sin_port)) ||
        wire[52] >= PEERS || wire[53] >= PEERS || get16(wire, 56) != fd->port ||
        ntohs(get16(wire, 58)) != size - RELAY_HEADER) return sock_fail(11);
    memcpy(supplied, wire + 64, 32);
    memset(wire + 64, 0, 32);
    if (relay_hash(relay_hmac, online_mode ? relay_key : relay_token, online_mode ? 32 : 16, wire, size, mac, 32) < 0) return sock_fail(11);
    unsigned different = 0;
    for (unsigned i = 0; i < 32; ++i) different |= mac[i] ^ supplied[i];
    if (different || !room) return sock_fail(11);
    int node = own_node();
    int valid = node == wire[53] && !memcmp(wire + 36, room->info + 16, 16);
    if (!valid) return sock_fail(11);
    unsigned count = (unsigned)(size - RELAY_HEADER);
    if (count > ARG(2)) count = (unsigned)ARG(2);
    memcpy(GP(ARG(1)), wire + RELAY_HEADER, count);
    if (ARG(4)) {
        unsigned char *addr = GP(ARG(4));
        memset(addr, 0, 16); addr[0] = 16; addr[1] = 2;
        put(addr, 2, get16(wire, 54), 2);
        put(addr, 4, swap32(VIRTUAL_IP(wire[52])), 4);
        G32(ARG(5)) = 16;
    }
    static unsigned logged;
    if (logged++ < 6) hos_log("wonder-ldn: RELAY received %u bytes on node %d", count, node);
    return count;
}
static uint64_t receive_packet(Ctx *c) {
    LocalSocket *fd = fd_at(ARG(0));
    if (!fd) return sock_fail(9);
    if (!fd->port || !ARG(1) || (ARG(4) && (!ARG(5) || G32(ARG(5)) < 16))) return sock_fail(22);
    if (relay_mode) return relay_receive(c, fd);
    for (unsigned attempt = 0; attempt < 8; ++attempt) {
        unsigned char wire[WIRE_HEADER + DATA_SIZE];
        struct sockaddr_in sender = {0};
        int sender_size = sizeof sender;
        int received = recvfrom(fd->socket, (char *)wire, sizeof wire, 0,
                                (struct sockaddr *)&sender, &sender_size);
        if (received == SOCKET_ERROR) return sock_fail(WSAGetLastError() == WSAEWOULDBLOCK ? 11 : 5);
        if (received < WIRE_HEADER || memcmp(wire, "WLD\3", 4) ||
            sender.sin_addr.s_addr != htonl(INADDR_LOOPBACK) || wire[20] >= PEERS ||
            wire[21] >= PEERS || get16(wire, 24) != fd->port ||
            ntohs(get16(wire, 26)) != received - WIRE_HEADER) continue;
        if (!lock_room()) return sock_fail(11);
        int node = own_node();
        int valid = node == wire[21] && !memcmp(wire + 4, room->info + 16, 16);
        int endpoint = 0;
        for (unsigned i = 0; i < FD_COUNT; ++i)
            endpoint |= room->endpoints[wire[20]][i].host_port == sender.sin_port &&
                        room->endpoints[wire[20]][i].guest_port == get16(wire, 22);
        unlock_room();
        if (!valid || !endpoint) continue;
        unsigned size = (unsigned)(received - WIRE_HEADER);
        if (size > ARG(2)) size = (unsigned)ARG(2);
        memcpy(GP(ARG(1)), wire + WIRE_HEADER, size);
        if (ARG(4)) {
            unsigned char *addr = GP(ARG(4));
            memset(addr, 0, 16);
            addr[0] = 16; addr[1] = 2;
            put(addr, 2, get16(wire, 22), 2);
            put(addr, 4, swap32(VIRTUAL_IP(wire[20])), 4);
            G32(ARG(5)) = 16;
        }
        static unsigned logged;
        if (logged++ < 6) hos_log("wonder-ldn: UDP received %u bytes on node %d", size, node);
        return size;
    }
    return sock_fail(11);
}

#define BEGIN() if (!hos_wonder_ldn_enabled()) { RET(LDN_DISABLED); return; } \
                int wonder_away = hos_vcore_away(); AcquireSRWLockExclusive(&state_lock)
#define END(value) do { RET(value); ReleaseSRWLockExclusive(&state_lock); \
                       if (wonder_away) hos_vcore_back(); } while (0)
#else
#define OFFLINE 1
#endif

/* Keep these symbols explicit so standalone.py can replace the generated imports. */
#ifdef _WIN32
HLE(_ZN2nn6socket13IsInitializedEv) { RET(hos_wonder_ldn_enabled() && InterlockedCompareExchange(&socket_initialized, 0, 0)); }
HLE(_ZN2nn3ldn10InitializeEv) { BEGIN(); if (!state && open_room()) transition(INITIALIZED); END(state ? 0 : LDN_DISABLED); }
HLE(_ZN2nn3ldn8FinalizeEv) {
    BEGIN();
    event = 0;
    unsigned result = close_host(NONE);

    if (!result) {
        for (unsigned i = 0; i < FD_COUNT; ++i) {
            if (sockets[i].open) closesocket(sockets[i].socket);
            sockets[i] = (LocalSocket){0};
        }
    }
    if (!result && room) {
        free(room);
        room = NULL;
    }
    END(result);
}
HLE(_ZN2nn3ldn8GetStateEv) {
    if (!hos_wonder_ldn_enabled()) { RET(NONE); return; }
    BEGIN();
    if (state == CONNECTED && lock_room_read()) {
        int lost = own_node() < 0;
        unlock_room_read();
        if (lost) transition(STATION);
    }
    END(state);
}
HLE(_ZN2nn3ldn11SetProtocolENS0_8ProtocolE) { BEGIN(); END(0); }
HLE(_ZN2nn3ldn22AttachStateChangeEventEPNS_2os15SystemEventTypeE) {
    BEGIN();
    if (!ARG(0)) { END(LDN_ARGUMENT); return; }
    event = ARG(0);
    ARG(1) = 0;
    ARG(2) = 0;
    imp__ZN2nn2os17CreateSystemEventEPNS0_15SystemEventTypeENS0_14EventClearModeEb(c);
    END(ARG(0));
}
HLE(_ZN2nn3ldn15OpenAccessPointEv) { BEGIN(); if (state == INITIALIZED) transition(ACCESS_POINT); END(state == ACCESS_POINT ? 0 : LDN_STATE); }
HLE(_ZN2nn3ldn16CloseAccessPointEv) { BEGIN(); END(state == ACCESS_POINT || state == HOSTING ? close_host(INITIALIZED) : LDN_STATE); }
HLE(_ZN2nn3ldn11OpenStationEv) { BEGIN(); if (state == INITIALIZED) transition(STATION); END(state == STATION ? 0 : LDN_STATE); }
HLE(_ZN2nn3ldn12CloseStationEv) { BEGIN(); END(state == STATION || state == CONNECTED ? close_host(INITIALIZED) : LDN_STATE); }
HLE(_ZN2nn3ldn10DisconnectEv) { BEGIN(); END(state == CONNECTED ? close_host(STATION) : LDN_STATE); }
HLE(_ZN2nn3ldn13CreateNetworkERKNS0_13NetworkConfigERKNS0_14SecurityConfigERKNS0_10UserConfigE) { BEGIN(); END(create_room(c, 0)); }
HLE(_ZN2nn3ldn20CreateNetworkPrivateERKNS0_13NetworkConfigERKNS0_14SecurityConfigERKNS0_17SecurityParameterERKNS0_10UserConfigEiPKNS0_12AddressEntryE) { BEGIN(); END(create_room(c, 1)); }
HLE(_ZN2nn3ldn14DestroyNetworkEv) { BEGIN(); END(state == HOSTING ? close_host(ACCESS_POINT) : LDN_STATE); }
HLE(_ZN2nn3ldn4ScanEPNS0_11NetworkInfoEPiiRKNS0_10ScanFilterEi) { BEGIN(); END(scan(c)); }
HLE(_ZN2nn3ldn11ScanPrivateEPNS0_11NetworkInfoEPiiRKNS0_10ScanFilterEi) { BEGIN(); END(scan(c)); }
HLE(_ZN2nn3ldn14GetNetworkInfoEPNS0_11NetworkInfoE) {
    BEGIN();
    if (!ARG(0) || !lock_room_read()) { END(LDN_STATE); return; }
    if (own_node() < 0) { unlock_room_read(); END(LDN_STATE); return; }
    memcpy(GP(ARG(0)), room->info, INFO_SIZE);
    unlock_room_read();
    END(0);
}
HLE(_ZN2nn3ldn16SetAdvertiseDataEPKvm) {
    BEGIN();
    uint64_t size = ARG(1);
    if (size > AD_MAX || (size && !ARG(0))) { END(LDN_ARGUMENT); return; }
    if (state == ACCESS_POINT) {
        if (size) memcpy(pending_advertise, GP(ARG(0)), size);
        pending_size = (unsigned)size;
        hos_log("wonder-ldn: queued %u bytes of room metadata before create", pending_size);
        END(0);
        return;
    }
    if (state != HOSTING || !lock_room()) { END(LDN_STATE); return; }
    put(room->info, AD_SIZE, size, 2);
    memset(room->info + AD_DATA, 0, AD_MAX);
    if (size) memcpy(room->info + AD_DATA, GP(ARG(0)), size);
    unlock_room();
    END(0);
}
HLE(_ZN2nn3ldn14GetIpv4AddressEPNS0_11Ipv4AddressEPNS0_10SubnetMaskE) {
    BEGIN();
    if (!lock_room_read()) { END(LDN_STATE); return; }
    int node = own_node();
    unlock_room_read();
    if (ARG(0)) G32(ARG(0)) = node < 0 ? 0 : VIRTUAL_IP(node);
    if (ARG(1)) G32(ARG(1)) = 0xffffff00;
    END(node >= 0 ? 0 : LDN_STATE);
}
HLE(_ZN2nn3ldn20GetSecurityParameterEPNS0_17SecurityParameterE) {
    BEGIN();
    if (!ARG(0) || !lock_room_read()) { END(LDN_STATE); return; }
    int node = own_node();
    if (node < 0) { unlock_room_read(); END(LDN_STATE); return; }
    unsigned char *out = GP(ARG(0));
    memcpy(out, room->info + 0x50, 16);
    memcpy(out + 16, room->info + 0x10, 16);
    unlock_room_read();
    static unsigned reads;
    if (reads++ < 4) hos_log("wonder-ldn: returned room security parameters to node %d", node);
    END(0);
}
HLE(_ZN2nn3ldn20MakeBroadcastAddressENS0_11Ipv4AddressENS0_10SubnetMaskE) { RET((uint32_t)ARG(0) | ~(uint32_t)ARG(1)); }
HLE(_ZN2nn3ldn7ConnectERKNS0_11NetworkInfoERKNS0_14SecurityConfigERKNS0_10UserConfigEiNS0_13ConnectOptionE) { BEGIN(); END(join_room(c, 0)); }
HLE(_ZN2nn3ldn14ConnectPrivateERKNS0_13NetworkConfigERKNS0_14SecurityConfigERKNS0_17SecurityParameterERKNS0_10UserConfigEiNS0_13ConnectOptionE) { BEGIN(); END(join_room(c, 1)); }

/* Only the datagram operations used by the two-player test are supported. */
#define SOCK_BEGIN() if (!hos_wonder_ldn_enabled()) { RET(sock_fail(93)); return; } \
                     int wonder_away = hos_vcore_away(); AcquireSRWLockExclusive(&state_lock)
HLE(_ZN2nn6socket6SocketENS0_6FamilyENS0_4TypeENS0_8ProtocolE) { SOCK_BEGIN(); END(open_socket((unsigned)ARG(0), (unsigned)ARG(1), (unsigned)ARG(2))); }
HLE(_ZN2nn6socket6SocketEiii) { SOCK_BEGIN(); END(open_socket((unsigned)ARG(0), (unsigned)ARG(1), (unsigned)ARG(2))); }
HLE(_ZN2nn6socket4BindEiPKNS0_8SockAddrEj) { SOCK_BEGIN(); END(bind_socket(c)); }
HLE(_ZN2nn6socket4BindEiPK8sockaddrj) { SOCK_BEGIN(); END(bind_socket(c)); }
HLE(_ZN2nn6socket10SetSockOptEiNS0_5LevelENS0_6OptionEPKvj) { SOCK_BEGIN(); END(fd_at(ARG(0)) ? 0 : sock_fail(9)); }
HLE(_ZN2nn6socket8ShutdownEii) { SOCK_BEGIN(); END(fd_at(ARG(0)) ? 0 : sock_fail(9)); }
HLE(_ZN2nn6socket5CloseEi) {
    SOCK_BEGIN();
    LocalSocket *fd = fd_at(ARG(0));

    if (fd) {
        if (lock_room()) {
            int node = own_node();
            if (node >= 0) room->endpoints[node][fd - sockets] = (Endpoint){0};
            unlock_room();
        }
        closesocket(fd->socket);
        *fd = (LocalSocket){0};
    }
    END(fd ? 0 : sock_fail(9));
}
HLE(_ZN2nn6socket6SendToEiPKvmNS0_7MsgFlagEPKNS0_8SockAddrEj) { SOCK_BEGIN(); END(send_packet(c)); }
HLE(_ZN2nn6socket6SendToEiPKvmiPK8sockaddrj) { SOCK_BEGIN(); END(send_packet(c)); }
static void receive(Ctx *c) {
    SOCK_BEGIN();
    uint64_t result = receive_packet(c);
    END(result);
    if (result == UINT64_MAX) hos_sleep_ns(2000000);
}
HLE(_ZN2nn6socket8RecvFromEiPvmNS0_7MsgFlagEPNS0_8SockAddrEPj) { receive(c); }
HLE(_ZN2nn6socket8RecvFromEiPvmiP8sockaddrPj) { receive(c); }
HLE(_ZN2nn6socket9InetHtonsEt) { RET(swap16((uint16_t)ARG(0))); }
HLE(_ZN2nn6socket9InetNtohsEt) { RET(swap16((uint16_t)ARG(0))); }
HLE(_ZN2nn6socket9InetHtonlEj) { RET(swap32((uint32_t)ARG(0))); }
HLE(_ZN2nn6socket9InetNtohlEj) { RET(swap32((uint32_t)ARG(0))); }
HLE(_ZN2nn6socket12GetLastErrorEv) { RET(socket_error); }
HLE(_ZN2nn6socket12GetLastErrnoEv) { RET(socket_error); }
#endif
