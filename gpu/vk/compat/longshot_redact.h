// Automatic privacy filtering: IP addresses and labelled connection secrets/names, plus
// the home folder and the user's name out of a line of the logs, one implementation for the host (C) and the renderer (C++):
// the home folder, as a whole, written ~ (%USERPROFILE% on Windows), and the user's name as a folder of any path <user>
// (/run/media/<user>, D:\Users\<user>, /var/home/<user>). The rest of the line, the rest of each path too, stays as it is.
// Used by the game's log as it writes it (host/log_redact.c), the crash window (host/hos_crash_dialog.h
// hos_crash_redact_line) and the Insert menu's Bug report (gpu/vk/vk_bug_report.cpp redact). A line redacted again comes out
// the same: ~, %USERPROFILE% and <user> are never a home folder or a name to take out.
#ifndef LONGSHOT_REDACT_H
#define LONGSHOT_REDACT_H

#include <stddef.h>
#include <string.h>

static inline int longshot_redact_sep(char c) { return c == '/' || c == '\\'; }
/* (a character a file or folder name has: a name ends at any other) */
static inline int longshot_redact_name_char(char c) {
    const unsigned char u = (unsigned char)c;
    return (u >= '0' && u <= '9') || (u >= 'a' && u <= 'z') || (u >= 'A' && u <= 'Z') || c == '.' || c == '_' || c == '-' || u >= 0x80;
}
/* (Windows: either separator for either, in any case) */
static inline int longshot_redact_matches_at(const char *s, size_t n, size_t at, const char *what, size_t wn, int windows) {
    if (!wn || at + wn > n) return 0;
    for (size_t i = 0; i < wn; i++) {
        char a = s[at + i], b = what[i];
        if (longshot_redact_sep(a) && longshot_redact_sep(b)) {
            if (!windows && a != b) return 0;
            continue;
        }
        if (windows) {
            if (a >= 'A' && a <= 'Z') a = (char)(a + 32);
            if (b >= 'A' && b <= 'Z') b = (char)(b + 32);
        }
        if (a != b) return 0;
    }
    return 1;
}

/* No allocation or networking: shared by the logger, crash window and copied reports. */
static inline int longshot_redact_digit(char c) { return c >= '0' && c <= '9'; }
static inline int longshot_redact_hex(char c) {
    return longshot_redact_digit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
static inline int longshot_redact_address_end(const char *s, size_t n, size_t at) {
    return at == n || (!longshot_redact_name_char(s[at]) && s[at] != ':') ||
        (s[at] == '.' && (at + 1 == n || !longshot_redact_name_char(s[at + 1])));
}
static inline size_t longshot_redact_ipv4(const char *s, size_t n) {
    size_t i = 0;
    for (int part = 0; part < 4; part++) {
        unsigned value = 0, digits = 0;
        while (i < n && longshot_redact_digit(s[i])) {
            value = value * 10 + (unsigned)(s[i++] - '0');
            if (++digits > 3 || value > 255) return 0;
        }
        if (!digits) return 0;
        if (part < 3 && (i >= n || s[i++] != '.')) return 0;
    }
    return i;
}
static inline size_t longshot_redact_ip(const char *s, size_t n) {
    size_t v4 = longshot_redact_ipv4(s, n);
    if (v4 && longshot_redact_address_end(s, n, v4)) return v4;
    /* An IPv4 port is left to the caller as ordinary punctuation. */
    if (v4 && v4 < n && s[v4] == ':') return v4;
    size_t i = 0;
    unsigned groups = 0;
    int compressed = 0;
    if (n >= 2 && s[0] == ':' && s[1] == ':') { compressed = 1; i = 2; }
    else if (!n || s[0] == ':') return 0;
    while (i < n && longshot_redact_hex(s[i])) {
        const size_t start = i;
        while (i < n && longshot_redact_hex(s[i])) i++;
        if (i + 1 < n && s[i] == '.' && longshot_redact_digit(s[i + 1])) {
            v4 = longshot_redact_ipv4(s + start, n - start);
            if (!v4) return 0;
            i = start + v4; groups += 2; break;
        }
        if (i - start > 4) return 0;
        groups++;
        if (i == n || s[i] != ':') break;
        i++;
        if (i < n && s[i] == ':') {
            if (compressed) return 0;
            compressed = 1; i++;
        } else if (i == n || !longshot_redact_hex(s[i])) return 0;
    }
    if (!(compressed ? groups < 8 : groups == 8)) return 0;
    if (i < n && s[i] == '%') {
        i++;
        while (i < n && longshot_redact_name_char(s[i])) i++;
    }
    return i && longshot_redact_address_end(s, n, i) ? i : 0;
}
/* Sensitive labelled values consume the rest of their line. This deliberately avoids
   guessing where a quoted, escaped, multiword or truncated value ends. */
static inline size_t longshot_redact_private_value(const char *s, size_t n) {
    static const char *const keys[] = {
        "password", "passwd", "pin", "token", "access_token", "session_token", "refresh_token",
        "authorization", "credential", "credentials", "api_key", "apikey", "secret", "client_secret",
        "turn_password", "turn_username", "test_access_key", "cookie", "set-cookie",
        "username", "display_name", "displayName", "player_name", "playerName", "nickname",
        "network_id", "networkId", "uid", "sdp", "candidate", "ice-ufrag", "ice-pwd"
    };
    for (size_t k = 0; k < sizeof keys / sizeof keys[0]; k++) {
        size_t j = strlen(keys[k]);
        if (!longshot_redact_matches_at(s, n, 0, keys[k], j, 1)) continue;
        if (j < n && (s[j] == '"' || s[j] == '\'')) j++;
        while (j < n && (s[j] == ' ' || s[j] == '\t')) j++;
        if (j == n || (s[j] != ':' && s[j] != '=')) continue;
        j++;
        while (j < n && (s[j] == ' ' || s[j] == '\t')) j++;
        return j;
    }
    return 0;
}

/* line (n bytes) into out (cap bytes, NUL-terminated, cut to fit) with home and user taken out. The length written. home and
   user may be NULL or empty (then nothing of theirs is taken out). out needs at most n * 7 + 1 bytes: a home of 2 bytes becomes
   %USERPROFILE%'s 13, a name of 1 byte <user>'s 6 */
static inline size_t longshot_redact_line(char *out, size_t cap, const char *line, size_t n, const char *home, const char *user,
                                          int windows) {
    size_t hn = home ? strlen(home) : 0, un = user ? strlen(user) : 0, o = 0;
    while (hn > 1 && longshot_redact_sep(home[hn - 1])) hn--;
    const int with_home = hn > 1;
    if (!cap) return 0;
#define LONGSHOT_REDACT_OUT(s, k) do { for (size_t j_ = 0; j_ < (k) && o + 1 < cap; j_++) out[o++] = (s)[j_]; } while (0)
    for (size_t i = 0; i < n;) {

        if (i == 0 || !longshot_redact_name_char(line[i - 1])) {
            const size_t value = longshot_redact_private_value(line + i, n - i);
            if (value) {
                LONGSHOT_REDACT_OUT(line + i, value);
                LONGSHOT_REDACT_OUT("<redacted>", 10);
                i += value;
                while (i < n && line[i] != '\r' && line[i] != '\n') i++;
                continue;
            }
            const size_t address = longshot_redact_ip(line + i, n - i);
            if (address) {
                LONGSHOT_REDACT_OUT("<ip>", 4);
                i += address;
                continue;
            }
        }
        /* (the home folder as a whole: not inside a longer name, not the end of another path) */
        if (with_home && (i == 0 || (!longshot_redact_name_char(line[i - 1]) && !longshot_redact_sep(line[i - 1]))) &&
            longshot_redact_matches_at(line, n, i, home, hn, windows) && (i + hn >= n || !longshot_redact_name_char(line[i + hn]))) {
            const char *w = windows ? "%USERPROFILE%" : "~";
            LONGSHOT_REDACT_OUT(w, strlen(w));
            i += hn;
            continue;
        }
        /* (the user's name as a folder of any path) */
        if (un && i > 0 && longshot_redact_sep(line[i - 1]) && longshot_redact_matches_at(line, n, i, user, un, windows) &&
            (i + un >= n || !longshot_redact_name_char(line[i + un]))) {
            LONGSHOT_REDACT_OUT("<user>", 6);
            i += un;
            continue;
        }
        LONGSHOT_REDACT_OUT(line + i, 1);
        i++;
    }
#undef LONGSHOT_REDACT_OUT
    out[o] = 0;
    return o;
}

#endif
