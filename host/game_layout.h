/* The game folder's cache/ and logs/ (host/game_layout.c): made at the start, and what a build from before left loose beside
   the game moved into them once. Paths are UTF-8. */
#pragma once
#define HOS_RUNTIME_LOG_STEM "wondershot"
#define HOS_RUNTIME_LOG_NAME HOS_RUNTIME_LOG_STEM ".log"
#define HOS_PREVIOUS_RUNTIME_LOG_NAME HOS_RUNTIME_LOG_STEM ".1.log"
/* Makes cache/, cache/prompts and logs/ in the game folder and moves the loose caches and logs of a build from before into them.
   Before anything writes there; once a process, the calls after the first do nothing */
void hos_game_layout(void);
/* What hos_game_layout moved or left, into the log: once the log is open */
void hos_game_layout_log(void);
