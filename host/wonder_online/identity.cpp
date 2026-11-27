#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <mbedtls/md.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <cstdio>
#include <cstring>
#include "online_ui.h"

namespace {
std::mutex mutex;
bool loaded;
bool unavailable;
uint64_t uid[2], saveUid[2] = {1, 0x5a3c9e1f0b7d2468ULL};
std::string name = "Player";
int enabled = 1, privacy = 1;
std::filesystem::path path;
std::string encode(const uint64_t *value) {
    char buffer[33]; std::snprintf(buffer, sizeof buffer, "%016llx%016llx", (unsigned long long)value[1], (unsigned long long)value[0]); return buffer;
}
bool decode(const std::string &text, uint64_t *value) {
    if (text.size() != 32 || text.find_first_not_of("0123456789abcdef") != std::string::npos) return false;
    value[1] = std::stoull(text.substr(0, 16), nullptr, 16); value[0] = std::stoull(text.substr(16), nullptr, 16);
    return value[0] || value[1];
}
bool validName(const char *text) {
    if (!text || !*text || std::strlen(text) > 32) return false;
    bool meaningful = false;
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p < 32 || *p > 126) return false;
        if (*p != ' ') meaningful = true;
    }
    return meaningful;
}
bool save() {
    try {
        std::filesystem::create_directories(path.parent_path());
        auto temp = path; temp += ".tmp-" + std::to_string(GetCurrentProcessId());
        nlohmann::json data = {{"version",1},{"network_id",encode(uid)},{"save_id",encode(saveUid)},
                               {"name",name},{"enabled",enabled},{"hide_ip",privacy}};
        { std::ofstream file(temp, std::ios::binary | std::ios::trunc); file << data.dump(2) << '\n'; file.flush(); if (!file) return false; }
        return MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
    } catch (...) { return false; }
}
void load() {
    if (loaded) return;
    const char *configured = std::getenv("WONDER_PROFILE_DIR");
    path = (configured && *configured ? std::filesystem::u8path(configured) : std::filesystem::path("user") / "online") / "profile.json";
    if (std::filesystem::exists(path)) {
        // Refuse to overwrite an unreadable profile: silently changing identity would break persistence.
        std::ifstream file(path); const auto data = nlohmann::json::parse(file);
        if (!decode(data.at("network_id").get<std::string>(), uid) || !decode(data.at("save_id").get<std::string>(), saveUid))
            throw std::runtime_error("Invalid online profile");
        const auto savedName = data.value("name", std::string("Player"));
        if (validName(savedName.c_str())) name = savedName;
        enabled = data.value("enabled", 1) != 0; privacy = data.value("hide_ip", 1) != 0;
    } else {
        if (BCryptGenRandom(nullptr, (PUCHAR)uid, sizeof uid, BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0 || !(uid[0] || uid[1]))
            throw std::runtime_error("Unable to generate online identity");
        const char *role = std::getenv("WONDER_LDN_ROLE");
        if (role && !std::strcmp(role, "guest")) { saveUid[0] = 2; name = "Guest"; }
        if (!save()) throw std::runtime_error("Unable to persist online identity");
    }
    loaded = true;
}
void loadSafe() {
    try { load(); }
    catch (...) {
        // Offline play can retain the original account/save mapping. Never invent
        // a replacement online identity when its existing file cannot be read.
        saveUid[0] = 1; saveUid[1] = 0x5a3c9e1f0b7d2468ULL;
        const char *role = std::getenv("WONDER_LDN_ROLE");
        if (role && !std::strcmp(role, "guest")) saveUid[0] = 2;
        uid[0] = saveUid[0]; uid[1] = saveUid[1];
        enabled = 0; privacy = 1; unavailable = true; loaded = true;
    }
}
}
extern "C" const uint64_t *wonder_profile_uid() { std::lock_guard<std::mutex> lock(mutex); loadSafe(); return uid; }
extern "C" const uint64_t *wonder_profile_save_uid() { std::lock_guard<std::mutex> lock(mutex); loadSafe(); return saveUid; }
extern "C" void wonder_profile_name(char *out, unsigned capacity) {
    if (!out || !capacity) return;
    std::lock_guard<std::mutex> lock(mutex); loadSafe(); std::snprintf(out, capacity, "%s", name.c_str());
}
extern "C" int wonder_profile_enabled() { std::lock_guard<std::mutex> lock(mutex); loadSafe(); return enabled; }
extern "C" int wonder_profile_privacy() { std::lock_guard<std::mutex> lock(mutex); loadSafe(); return privacy; }
extern "C" int wonder_profile_set_name(const char *value) {
    if (!validName(value)) return 0;
    std::lock_guard<std::mutex> lock(mutex); loadSafe(); auto old = name; name = value;
    if (!unavailable && save()) return 1; name = old; return 0;
}
extern "C" int wonder_profile_set_enabled(int value) {
    std::lock_guard<std::mutex> lock(mutex); loadSafe(); auto old = enabled; enabled = !!value;
    if (!unavailable && save()) return 1; enabled = old; return 0;
}
extern "C" int wonder_profile_set_privacy(int value) {
    std::lock_guard<std::mutex> lock(mutex); loadSafe(); auto old = privacy; privacy = !!value;
    if (!unavailable && save()) return 1; privacy = old; return 0;
}
extern "C" void wonder_profile_fingerprint(char *out, unsigned capacity) {
    std::lock_guard<std::mutex> lock(mutex); loadSafe();
    unsigned char digest[32]; mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const unsigned char *)uid, sizeof uid, digest);
    char text[65]; for (unsigned i = 0; i < 32; ++i) std::sprintf(text + i * 2, "%02x", digest[i]);
    std::snprintf(out, capacity, "%s", text);
}

extern "C" int wonder_profile_available() { std::lock_guard<std::mutex> lock(mutex); loadSafe(); return !unavailable; }
