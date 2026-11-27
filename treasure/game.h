#ifndef TREASURE_GAME_H
#define TREASURE_GAME_H
#include <stdbool.h>
#include <stddef.h>

enum { TREASURE_SIZE = 16, TREASURE_BOTS = 4, TREASURE_TURNS = 200 };
typedef struct { int x, y; } TreasurePosition;
typedef struct {
    unsigned char board[TREASURE_SIZE][TREASURE_SIZE];
    TreasurePosition positions[TREASURE_BOTS];
    int scores[TREASURE_BOTS];
    int bot_count, turns_played;
} TreasureGame;

bool treasure_init(TreasureGame *game, int count);
bool treasure_step(TreasureGame *game, const char actions[TREASURE_BOTS]);
/* -1: ongoing, 0: draw, 1..4: winner ID. */
int treasure_result(const TreasureGame *game);
int treasure_remaining(const TreasureGame *game);
/* Caller supplies at least 512 bytes, bot is a zero-based active index. */
size_t treasure_input(const TreasureGame *game, int bot, char input[512]);
#endif
