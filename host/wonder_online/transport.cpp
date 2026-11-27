// Wondershot's native WebRTC adapter. Room metadata goes through the Worker;
// gameplay is carried by an encrypted, unordered, unreliable data channel.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>
#include <rtc/rtc.hpp>
#include <nlohmann/json.hpp>
#include <mbedtls/md.h>
#include <atomic>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <regex>
#include <fstream>
#include "online_ui.h"
#include <thread>

using json = nlohmann::json;
using namespace std::chrono_literals;
namespace {
std::atomic<void (*)(const char *)> gameLogger{nullptr};
void logOnline(const std::string &message) {
    std::fprintf(stderr, "wonder-online: %s\n", message.c_str());
    if (auto logger = gameLogger.load()) logger(message.c_str());
}
struct Handle {
    HINTERNET value;
    explicit Handle(HINTERNET v) : value(v) { if (!v) throw std::runtime_error("HTTP handle failed"); }
    ~Handle() { WinHttpCloseHandle(value); }
    operator HINTERNET() const { return value; }
};
std::wstring wide(const std::string &s) { return {s.begin(), s.end()}; }
struct Session : std::enable_shared_from_this<Session> {
    std::wstring host, prefix;
    INTERNET_PORT port = 0;
    bool secure = true, hostRole = false;
    bool privacy = false;
    bool backgroundRoomChecks = false;
    std::atomic<int> route{0};
    std::string token, lease, roomCode, testAccess;
    uint32_t actor = 0;
    std::atomic<uint64_t> generation{1};
    rtc::Configuration configuration;
    std::atomic<bool> open{false}, stopped{false};
    std::shared_ptr<rtc::PeerConnection> pc;
    std::shared_ptr<rtc::DataChannel> dc;
    std::mutex queueMutex, dcMutex, roomMutex;
    std::deque<rtc::binary> packets;
    std::deque<json> outboundSignals;
    std::array<unsigned char, 1288> roomCache{};
    ULONGLONG roomSeen = 0;
    uint64_t roomGeneration = 0;

    void rememberRoom(const void *data, unsigned size) {
        std::lock_guard<std::mutex> lock(roomMutex);
        std::memcpy(roomCache.data(), data, size);
        roomSeen = GetTickCount64(); ++roomGeneration;
    }
    void refreshRoom() {
        uint64_t generation;
        { std::lock_guard<std::mutex> lock(roomMutex); generation = roomGeneration; }
        auto response = request("GET", "/state");
        auto encoded = response.at("data").get<std::string>();
        if (encoded.size() != roomCache.size() * 2) return;
        std::array<unsigned char, 1288> snapshot;
        for (unsigned i = 0; i < snapshot.size(); ++i)
            snapshot[i] = (unsigned char)std::stoul(encoded.substr(i * 2, 2), nullptr, 16);
        std::lock_guard<std::mutex> lock(roomMutex);
        if (roomGeneration != generation) return; // A local transaction committed during the request.
        roomCache = snapshot; roomSeen = GetTickCount64();
    }

    json request(const std::string &method, const std::string &path, const json *data = nullptr) {
        Handle session(WinHttpOpen(L"Wondershot-P2P-test/1", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                                   WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0));
        WinHttpSetTimeouts(session, 3000, 3000, 3000, 3000);
        Handle connection(WinHttpConnect(session, host.c_str(), port, 0));
        auto verb = wide(method), route = prefix + wide(path);
        Handle req(WinHttpOpenRequest(connection, verb.c_str(), route.c_str(), nullptr,
                                     WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                     secure ? WINHTTP_FLAG_SECURE : 0));
        DWORD redirects = WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
        if (!WinHttpSetOption(req, WINHTTP_OPTION_REDIRECT_POLICY, &redirects, sizeof redirects))
            throw std::runtime_error("HTTP redirect policy failed");
        auto headers = wide("Content-Type: application/json\r\nAuthorization: Bearer " + token + "\r\n");
        if (!testAccess.empty()) headers += wide("X-Wonder-Test: " + testAccess + "\r\n");
        std::string encoded = data ? data->dump() : "";
        if (!WinHttpSendRequest(req, headers.c_str(), (DWORD)-1,
                                encoded.empty() ? nullptr : encoded.data(), (DWORD)encoded.size(),
                                (DWORD)encoded.size(), 0) || !WinHttpReceiveResponse(req, nullptr))
            throw std::runtime_error("Worker request failed");
        DWORD status = 0, length = sizeof status;
        WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                            WINHTTP_HEADER_NAME_BY_INDEX, &status, &length, WINHTTP_NO_HEADER_INDEX);
        if (status == 409) return {{"busy", true}};
        if (status != 200) { logOnline("service returned HTTP " + std::to_string(status)); throw std::runtime_error("Worker rejected request"); }
        std::string result;
        char buffer[4096]; DWORD count;
        while (WinHttpReadData(req, buffer, sizeof buffer, &count) && count) {
            result.append(buffer, count);
            if (result.size() > 131072) throw std::runtime_error("Worker response too large");
        }
        return json::parse(result);
    }
    void signal(json message) {
        std::lock_guard<std::mutex> lock(queueMutex);
        message["generation"] = generation.load();
        if (outboundSignals.size() < 128) outboundSignals.push_back(std::move(message));
    }
    void initializePeer() {
        open = false; route = 0;
        if (pc) { pc->resetCallbacks(); pc->close(); }
        { std::lock_guard<std::mutex> lock(dcMutex); if (dc) { dc->resetCallbacks(); dc->close(); dc.reset(); } }
        { std::lock_guard<std::mutex> lock(queueMutex); packets.clear(); outboundSignals.clear(); }
        pc = std::make_shared<rtc::PeerConnection>(configuration);
        const auto weak = weak_from_this();
        const auto epoch = generation.load();
        std::weak_ptr<rtc::PeerConnection> connection=pc;
        pc->onStateChange([weak, epoch](rtc::PeerConnection::State state) { auto s = weak.lock(); if (!s || s->stopped || s->generation != epoch) return; logOnline("connection state " + std::to_string(static_cast<int>(state))); });
        pc->onLocalDescription([weak, epoch](rtc::Description description) {
            auto s = weak.lock(); if (!s || s->stopped || s->generation != epoch) return;
            description.extractCandidates(); // Candidate addresses are sent only through the filtered callback.
            s->signal({{"type", "description"}, {"kind", description.typeString()}, {"sdp", std::string(description)}});
        });
        pc->onLocalCandidate([weak, epoch](rtc::Candidate candidate) {
            auto s = weak.lock(); if (!s || s->stopped || s->generation != epoch) return;
            if (s->privacy && candidate.type() != rtc::Candidate::Type::Relayed) return;
            std::string encoded(candidate);
            if (s->privacy) encoded = std::regex_replace(encoded, std::regex(" raddr [^ ]+ rport [0-9]+"), " raddr 0.0.0.0 rport 0");
            s->signal({{"type", "candidate"}, {"candidate", encoded}, {"mid", candidate.mid()}});
        });
        pc->onDataChannel([weak, epoch, connection](std::shared_ptr<rtc::DataChannel> channel) { if (auto s = weak.lock(); s && !s->stopped && s->generation == epoch) s->channel(channel,epoch,connection); });
        if (hostRole) {
            rtc::DataChannelInit init;
            init.reliability.unordered = true;
            init.reliability.maxRetransmits = 0;
            channel(pc->createDataChannel("wondershot-gameplay", init),epoch,connection);
        }
    }
    void channel(std::shared_ptr<rtc::DataChannel> channel, uint64_t epoch, std::weak_ptr<rtc::PeerConnection> connection) {
        {
            std::lock_guard<std::mutex> lock(dcMutex);
            if (dc || stopped || generation!=epoch) return;
            dc = channel;
        }
        auto weak = weak_from_this();
        channel->onOpen([weak, epoch, connection] {
            auto self = weak.lock(); if (!self || self->stopped || self->generation != epoch) return;
            auto *thisSession = self.get();
            rtc::Candidate local, remote;
            if (auto peer = connection.lock(); peer && peer->getSelectedCandidatePair(&local, &remote))
                thisSession->route = local.type() == rtc::Candidate::Type::Relayed || remote.type() == rtc::Candidate::Type::Relayed ? 2 : 1;
            thisSession->open = true;
            logOnline(thisSession->route == 2 ? "encrypted channel open (TURN relay)" : thisSession->route == 1 ? "encrypted channel open (direct P2P)" : "encrypted channel open (route pending)");
        });
        channel->onClosed([weak, epoch] { if (auto self = weak.lock(); self && self->generation == epoch) self->open = false; });
        channel->onMessage([weak, epoch](rtc::message_variant message) {
            auto self = weak.lock(); if (!self || self->stopped || self->generation != epoch) return;
            auto *thisSession = self.get();
            if (!std::holds_alternative<rtc::binary>(message)) return;
            auto packet = std::get<rtc::binary>(std::move(message));
            if (packet.size() < 96 || packet.size() > 2144) return;
            std::lock_guard<std::mutex> lock(thisSession->queueMutex);
            if (thisSession->packets.size() >= 256) thisSession->packets.pop_front();
            thisSession->packets.push_back(std::move(packet));
        });
    }
    void run() {
        uint64_t cursor = 0; unsigned failures = 0;
        ULONGLONG lastStatus = 0;
        while (!stopped) {
            try {
                if (GetTickCount64() - lastStatus >= 1000) {
                    const auto response = request("GET", "/status");
                    lastStatus = GetTickCount64();
                    const auto epoch = response.at("generation").get<uint64_t>();
                    if (generation != epoch) {
                        generation = epoch; cursor = 0;
                        initializePeer();
                        logOnline("peer left; ready for another guest");
                    }
                }
                for (;;) {
                    json signal;
                    { std::lock_guard<std::mutex> lock(queueMutex); if (outboundSignals.empty()) break; signal = outboundSignals.front(); }
                    request("POST", "/signals", &signal);
                    { std::lock_guard<std::mutex> lock(queueMutex); if (!outboundSignals.empty()) outboundSignals.pop_front(); }
                }
                if (open) {
                    if (backgroundRoomChecks) refreshRoom();
                } else {
                    const auto response = request("GET", "/signals?after=" + std::to_string(cursor));
                    if (response.value("generation", uint64_t(1)) == generation) {
                        for (const auto &message : response.at("signals")) {
                            if (message.at("type") == "description")
                                pc->setRemoteDescription(rtc::Description(message.at("sdp").get<std::string>(), message.at("kind").get<std::string>()));
                            else if (message.at("type") == "candidate")
                                pc->addRemoteCandidate(rtc::Candidate(message.at("candidate").get<std::string>(), message.at("mid").get<std::string>()));
                        }
                        cursor = response.at("cursor").get<uint64_t>();
                    }
                }
                failures = 0;
            } catch (const std::exception &) {
                // Preserve queued signaling across a transient service failure.
                if (++failures == 1) logOnline("connection service unavailable; retrying");
                if (failures >= 30) { open = false; stopped = true; logOnline("room connection expired; create or join a room again"); }
            }
            std::this_thread::sleep_for(open ? 500ms : 250ms);
        }
        if (pc) { pc->resetCallbacks(); pc->close(); }
        { std::lock_guard<std::mutex> lock(dcMutex); if (dc) { dc->resetCallbacks(); dc->close(); dc.reset(); } }
    }
};
std::shared_ptr<Session> activeSession;
std::shared_ptr<Session> currentSession() { return std::atomic_load(&activeSession); }
void storeSession(std::shared_ptr<Session> session) { std::atomic_store(&activeSession, std::move(session)); }
std::mutex statusMutex;
std::string statusText = "Use Play via Local Wireless to create or join a room.";
struct ListedRoom { std::string code; std::array<unsigned char, 0x480> info; };
std::vector<ListedRoom> listedRooms;
std::string serviceUrl() {
    const char *url = std::getenv("WONDER_ONLINE_SERVICE");
    return url && *url ? url : "https://wondershot-rendezvous.wondershot-rendezvous.workers.dev";
}
void status(const std::string &value) { std::lock_guard<std::mutex> lock(statusMutex); statusText = value; }
std::unique_ptr<Session> serviceClient() {
    auto session = std::make_unique<Session>();
    auto address = wide(serviceUrl()); URL_COMPONENTS parsed{};
    parsed.dwStructSize = sizeof parsed; parsed.dwHostNameLength = parsed.dwUrlPathLength = (DWORD)-1;
    if (!WinHttpCrackUrl(address.c_str(), 0, 0, &parsed)) throw std::runtime_error("Invalid service address");
    session->host.assign(parsed.lpszHostName, parsed.dwHostNameLength);
    session->prefix.assign(parsed.lpszUrlPath, parsed.dwUrlPathLength);
    while (!session->prefix.empty() && session->prefix.back() == '/') session->prefix.pop_back();
    session->port = parsed.nPort; session->secure = parsed.nScheme == INTERNET_SCHEME_HTTPS;
    if (!session->secure && session->host != L"127.0.0.1" && session->host != L"localhost") throw std::runtime_error("HTTPS required");
    if (const char *file = std::getenv("WONDER_TEST_ACCESS_FILE"); file && *file) {
        std::ifstream input(file); session->testAccess = json::parse(input).at("key").get<std::string>();
    }
    return session;
}
std::string hex(const void *data, unsigned size) {
    static const char digits[] = "0123456789abcdef";
    const auto *bytes = static_cast<const unsigned char *>(data);
    std::string output(size * 2, '0');
    for (unsigned i = 0; i < size; ++i) { output[i * 2] = digits[bytes[i] >> 4]; output[i * 2 + 1] = digits[bytes[i] & 15]; }
    return output;
}
std::string admissionProof(const void *security) {
    if (!security) throw std::runtime_error("Missing security configuration");
    const auto *bytes = static_cast<const unsigned char *>(security);
    unsigned length = bytes[2] | (unsigned(bytes[3]) << 8);
    if (length > 64) throw std::runtime_error("Invalid security configuration");
    std::array<unsigned char, 68> canonical{};
    std::memcpy(canonical.data(), bytes, 4 + length);
    unsigned char digest[32];
    if (mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), canonical.data(), canonical.size(), digest))
        throw std::runtime_error("Admission hashing failed");
    return hex(digest, sizeof digest);
}
}
extern "C" uint32_t wonder_online_start(const char *url, const char *code, const char *token) {
    auto active = currentSession();
    if (active) return active->actor;
    try {
        auto session = std::make_shared<Session>();
        auto address = wide(url); URL_COMPONENTS parsed{};
        parsed.dwStructSize = sizeof parsed; parsed.dwHostNameLength = parsed.dwUrlPathLength = (DWORD)-1;
        if (!WinHttpCrackUrl(address.c_str(), 0, 0, &parsed)) return 0;
        session->host.assign(parsed.lpszHostName, parsed.dwHostNameLength);
        session->port = parsed.nPort; session->secure = parsed.nScheme == INTERNET_SCHEME_HTTPS;
        if (!session->secure && session->host != L"127.0.0.1" && session->host != L"localhost") return 0;
        session->prefix.assign(parsed.lpszUrlPath, parsed.dwUrlPathLength);
        while (!session->prefix.empty() && session->prefix.back() == '/') session->prefix.pop_back();
        session->prefix += L"/rooms/" + wide(code); session->token = token;
        session->roomCode = code;
        if (const char *mode = std::getenv("WONDER_ASYNC_ROOM_CHECKS")) session->backgroundRoomChecks = !std::strcmp(mode, "1");
        auto configResponse = session->request("GET", "/ice");
        session->actor = configResponse.at("actor").get<uint32_t>();
        session->hostRole = configResponse.at("role") == "host";
        rtc::Configuration config;
        config.maxMessageSize = 4096;
        if (!std::getenv("WONDER_ONLINE_NO_STUN")) {
            for (const auto &entry : configResponse.at("iceServers")) {
                for (const auto &uri : entry.at("urls")) {
                    rtc::IceServer server(uri.get<std::string>());
                    if (entry.contains("username")) server.username = entry.at("username").get<std::string>();
                    if (entry.contains("credential")) server.password = entry.at("credential").get<std::string>();
                    config.iceServers.push_back(server);
                }
            }
        }
        const char *privacy = std::getenv("WONDER_HIDE_IP");
        if ((privacy && !std::strcmp(privacy, "1")) || (wonder_online_auto() && wonder_profile_privacy())) {
            if (!configResponse.at("turn").get<bool>()) return 0;
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            session->privacy = true;
        }
        rtc::InitLogger(rtc::LogLevel::None);
        session->configuration = config;
        session->generation = configResponse.value("generation", uint64_t(1));
        session->initializePeer();
        storeSession(session);
        std::thread([session] { session->run(); }).detach();
        return session->actor;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "wonder-online: initialization failed\n"); return 0;
    }
}
extern "C" int wonder_online_acquire(void *data, unsigned size) {
    auto active = currentSession();
    if (!active || size != 1288) return 0;
    try {
        for (unsigned attempt = 0; attempt < 100; ++attempt) {
            const json empty = json::object();
            auto result = active->request("POST", "/acquire", &empty);
            if (result.value("busy", false)) { std::this_thread::sleep_for(20ms); continue; }
            auto encoded = result.at("data").get<std::string>();
            if (encoded.size() != size * 2) return 0;
            auto *output = static_cast<unsigned char *>(data);
            for (unsigned i = 0; i < size; ++i) output[i] = (unsigned char)std::stoul(encoded.substr(i * 2, 2), nullptr, 16);
            active->rememberRoom(data, size);
            active->lease = result.at("lease").get<std::string>(); return 1;
        }
    } catch (const std::exception &) { std::fprintf(stderr, "wonder-online: room read failed\n"); }
    return 0;
}
extern "C" int wonder_online_commit(const void *data, unsigned size) {
    auto active = currentSession();
    if (!active || size != 1288 || active->lease.empty()) return 0;
    try {
        json update = {{"lease", active->lease}, {"data", hex(data, size)}};
        auto result = active->request("POST", "/commit", &update);
        active->lease.clear();
        if (!result.value("ok", false)) return 0;
        active->rememberRoom(data, size); return 1;
    } catch (const std::exception &) { std::fprintf(stderr, "wonder-online: room update failed\n"); return 0; }
}
extern "C" int wonder_online_read(void *data, unsigned size) {
    auto active = currentSession();
    if (!active || size != 1288) return 0;
    if (!active->backgroundRoomChecks) {
        bool stale;
        { std::lock_guard<std::mutex> lock(active->roomMutex); stale = !active->roomSeen || GetTickCount64() - active->roomSeen >= 500; }
        if (stale) { try { active->refreshRoom(); } catch (...) { return 0; } }
    }
    std::lock_guard<std::mutex> lock(active->roomMutex);
    if (!active->roomSeen || GetTickCount64() - active->roomSeen > 30000) return 0;
    std::memcpy(data, active->roomCache.data(), size); return 1;
}
extern "C" int wonder_online_send(const void *data, unsigned size) {
    auto active = currentSession();
    if (!active || !active->open || size > 2144) return 0;
    try { std::lock_guard<std::mutex> lock(active->dcMutex); return active->dc && active->dc->send(static_cast<const std::byte *>(data), size); }
    catch (...) { return 0; }
}
extern "C" int wonder_online_receive(void *data, unsigned capacity, uint16_t port) {
    auto active = currentSession();
    if (!active) return -1;
    std::lock_guard<std::mutex> lock(active->queueMutex);
    for (auto it = active->packets.begin(); it != active->packets.end(); ++it) {
        uint16_t destination; std::memcpy(&destination, it->data() + 56, 2);
        if (destination != port) continue;
        unsigned size = (unsigned)it->size();
        if (size > capacity) { active->packets.erase(it); return -1; }
        std::memcpy(data, it->data(), size); active->packets.erase(it); return (int)size;
    }
    return -1;
}
extern "C" int wonder_online_ready() { auto active = currentSession(); return active && active->open; }
extern "C" int wonder_online_route() { auto active = currentSession(); return active ? active->route.load() : 0; }
extern "C" void wonder_online_set_logger(void (*logger)(const char *)) { gameLogger = logger; }

extern "C" int wonder_online_auto() {
    const char *value = std::getenv("WONDER_ONLINE_UI");
    return !value || !std::strcmp(value, "1");
}
extern "C" uint32_t wonder_online_identity() { auto active = currentSession(); return active ? active->actor : 0; }
extern "C" int wonder_online_copy_code(char *out, unsigned capacity) {
    auto active = currentSession();
    if (!active || capacity < 33) return 0;
    std::snprintf(out, capacity, "%s", active->roomCode.c_str()); return 1;
}
extern "C" int wonder_online_prepare_host(const void *security) {
    if (!wonder_profile_enabled()) { status("Enable Online multiplayer before creating a room."); return 0; }
    auto active = currentSession();
    if (active && !active->stopped) return 1;
    if (active) wonder_online_disconnect();
    try {
        status("Creating room...");
        auto service = serviceClient();
        const char *file = std::getenv("WONDER_TEST_ACCESS_FILE");
        if (file && *file) { std::ifstream input(file); service->testAccess = json::parse(input).at("key").get<std::string>(); }
        char identity[65]; wonder_profile_fingerprint(identity, sizeof identity);
        json data = {{"identity", identity}, {"admission", admissionProof(security)}};
        const auto room = service->request("POST", "/rooms", &data);
        auto code = room.at("code").get<std::string>(), token = room.at("token").get<std::string>();
        if (!wonder_online_start(serviceUrl().c_str(), code.c_str(), token.c_str())) throw std::runtime_error("Connection initialization failed");
        status("Hosting. Friends can find this room in the game's room list."); return 1;
    } catch (const std::exception &) { status("Could not create an online room. Check the connection and try again."); logOnline("room creation failed"); return 0; }
}
extern "C" int wonder_online_scan(void *out, unsigned capacity) {
    if (!wonder_profile_enabled()) { status("Enable Online multiplayer before searching for rooms."); return -1; }
    try {
        status("Searching for online rooms...");
        auto service = serviceClient(); const auto response = service->request("GET", "/rooms");
        listedRooms.clear();
        for (const auto &entry : response.at("rooms")) {
            if (listedRooms.size() >= capacity) break;
            auto code = entry.at("code").get<std::string>(), encoded = entry.at("info").get<std::string>();
            if (code.size() != 32 || encoded.size() != 0x480 * 2) continue;
            ListedRoom room; room.code = code;
            for (unsigned i = 0; i < room.info.size(); ++i) room.info[i] = (unsigned char)std::stoul(encoded.substr(i * 2, 2), nullptr, 16);
            std::memcpy(static_cast<unsigned char *>(out) + listedRooms.size() * 0x480, room.info.data(), room.info.size());
            listedRooms.push_back(std::move(room));
        }
        status(listedRooms.empty() ? "No online rooms found." : "Select a room in the game. Passwords are handled by the game.");
        return (int)listedRooms.size();
    } catch (...) { status("Could not search for online rooms. Check the connection."); return -1; }
}
extern "C" int wonder_online_prepare_join(const void *info, const void *security) {
    if (!wonder_profile_enabled()) { status("Enable Online multiplayer before joining a room."); return 0; }
    try {
        const ListedRoom *chosen = nullptr;
        for (const auto &room : listedRooms) if (!std::memcmp(room.info.data() + 16, static_cast<const unsigned char *>(info) + 16, 16)) { chosen = &room; break; }
        if (!chosen) return 0;
        status("Joining online room...");
        wonder_online_disconnect();
        auto service = serviceClient(); char identity[65]; wonder_profile_fingerprint(identity, sizeof identity);
        json data = {{"identity", identity}, {"admission", admissionProof(security)}};
        auto response = service->request("POST", "/rooms/" + chosen->code + "/join", &data);
        if (response.value("busy", false)) { status("This room is full, or this identity is already in it."); return 0; }
        auto token = response.at("token").get<std::string>();
        if (!wonder_online_start(serviceUrl().c_str(), chosen->code.c_str(), token.c_str())) return 0;
        status("Joined. The game is finishing the connection."); return 1;
    } catch (...) { status("Could not join this room. Refresh the game's room list."); return 0; }
}
extern "C" void wonder_online_disconnect() {
    auto old = std::atomic_exchange(&activeSession, std::shared_ptr<Session>{});
    if (old) {
        old->stopped = true; old->open = false;
        // Complete admission release before a short-lived client process can exit.
        try { const json empty = json::object(); old->request("POST", "/leave", &empty); } catch (...) {}
        status("Not in a room. Create or join one through Local Wireless.");
    }
}
extern "C" __declspec(dllexport) int wonder_online_ui(int action, void *data, unsigned size) {
    auto active = currentSession();
    try {
        if (action == WONDER_UI_GET && size == sizeof(WonderOnlineView)) {
            auto *view = static_cast<WonderOnlineView *>(data); std::memset(view, 0, sizeof *view);
            wonder_profile_name(view->name, sizeof view->name); view->enabled = wonder_profile_enabled(); view->privacy = wonder_profile_privacy();
            std::lock_guard<std::mutex> lock(statusMutex);
            const char *text = active && active->open ? (active->route == 2 ? "Connected through Cloudflare TURN." : active->route == 1 ? "Connected through direct P2P." : "Connected securely; checking the route.") : statusText.c_str();
            if (!wonder_profile_available()) text = "Online profile unavailable. Check user/online/profile.json and restart the game.";
            std::snprintf(view->status, sizeof view->status, "%s", text); return 1;
        }
        if (!data) return 0;
        if (action == WONDER_UI_NAME && size > 0 && size <= 33 && static_cast<char *>(data)[size - 1] == 0) return wonder_profile_set_name(static_cast<char *>(data));
        if (size != sizeof(int)) return 0;
        if (action == WONDER_UI_ENABLE) return wonder_profile_set_enabled(*static_cast<int *>(data));
        if (action == WONDER_UI_PRIVACY) return wonder_profile_set_privacy(*static_cast<int *>(data));
    } catch (...) { return 0; }
    return 0;
}
