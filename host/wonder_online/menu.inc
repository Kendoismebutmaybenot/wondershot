
using WonderOnlineCall = int (*)(int, void *, unsigned);
WonderOnlineCall online_call() {
#ifdef _WIN32
    return (WonderOnlineCall)GetProcAddress(GetModuleHandleW(nullptr), "wonder_online_ui");
#else
    return nullptr;
#endif
}
int online_enabled = 1, online_direct = 0;
TextField online_name_field{{}, 0, 0, 32, nullptr, nullptr};
void online_profile_show() {
    WonderOnlineView view{};
    if (auto fn = online_call(); fn && fn(WONDER_UI_GET, &view, sizeof view)) {
        online_enabled = view.enabled; online_direct = !view.privacy;
        text_set(online_name_field, view.name);
    }
}
const char *online_name_apply() {
    auto fn = online_call();
    if (!fn || !fn(WONDER_UI_NAME, online_name_field.text, (unsigned)strlen(online_name_field.text) + 1))
        return "Enter a name with 1 to 32 printable characters. The profile must be writable.";
    return nullptr;
}
std::string online_status_text() {
    WonderOnlineView view{}; auto fn = online_call();
    if (!fn || !fn(WONDER_UI_GET, &view, sizeof view)) return "Online support is unavailable in this executable.";
    return view.status;
}
MENU_MODULE(wonder_online) {
    online_profile_show();
    auto page = menu::tab("online");
    menu::Setting enabled;
    enabled.key = "wonder_online_enabled"; enabled.label = "Online multiplayer";
    enabled.help = "Use Play via Local Wireless in the game to create or find online rooms. Leave the current room before changing connection settings.";
    enabled.kind = menu::Kind::Toggle; enabled.value = &online_enabled; enabled.lo = 0; enabled.hi = 1;
    enabled.on_change = [](int v) { if (auto fn = online_call()) fn(WONDER_UI_ENABLE, &v, sizeof v); };
    page.row(std::move(enabled));
    menu::Setting name;
    name.key = "wonder_online_name"; name.label = "Online name";
    name.help = "Your name shown to other players. Enter edits; Enter saves and Escape cancels. Applies when you create or join the next room.";
    name.kind = menu::Kind::Action; page.row(std::move(name));
    menu::Setting connection;
    connection.key = "wonder_online_direct"; connection.label = "Connection";
    connection.help = "Private relay hides addresses from peers. Direct preferred tries P2P for lower latency and falls back to TURN; a direct peer can learn your IP. Applies to the next room.";
    connection.kind = menu::Kind::Choice; connection.value = &online_direct; connection.lo = 0; connection.hi = 1;
    connection.choices = {"Private relay", "Direct preferred"};
    connection.on_change = [](int v) { int privacy = !v; if (auto fn = online_call()) fn(WONDER_UI_PRIVACY, &privacy, sizeof privacy); };
    page.row(std::move(connection));
    menu::Setting status;
    status.key = "wonder_online_status"; status.label = "Connection status";
    status.help = "Your random network identity is saved automatically and stays the same when you change your name. Existing save folders are preserved.";
    status.kind = menu::Kind::Action; status.text = [](int) { return online_status_text(); };
    page.row(std::move(status));
}
