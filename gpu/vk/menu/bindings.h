// The Controls page module's (gpu/vk/menu/bindings.cpp, #1633) that the rest of the menu uses (vk_menu.cpp: the bindings grid,
// the options file's pad_/key_ lines, menu_tick's layout read when the menu opens).
#pragma once

namespace mkwvk {
bool can_bind();             // (the host takes bindings: the grid and the Layout preset work)
void apply_pad_layout(int layout);   // (preset layout's face buttons (3: every button the Switch pad's own) bound)
int detect_pad_layout();
bool ctl_keyboard();         // (Wondershot) the Controls page's player has the keyboard and mouse: the full grid
int ctl_pad_set();           // (the host's binding set for that player: HOS_BIND_PAD, or another player's HOS_BIND_PAD_P*)
void ctl_refresh();          // (the Controller row's value, from the host: when the page opens or the player changes)     // (the preset the bindings are now; 4, Custom, when none)
} // namespace mkwvk
