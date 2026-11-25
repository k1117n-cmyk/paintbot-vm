#ifndef PAINT_GAME_H
#define PAINT_GAME_H

#include <stdbool.h>

enum { GAME_SIZE = 16, GAME_BOTS = 4, GAME_TURNS = 200 };

typedef struct {
    int x;
    int y;
} GamePosition;

typedef struct {
    /* 0 = unpainted, 1..4 = bot ID; indexed by [y][x]. */
    unsigned char board[GAME_SIZE][GAME_SIZE];
    GamePosition positions[GAME_BOTS]; /* ID order; first bot_count entries active */
    int bot_count;
    int turns_played;
} Game;

typedef enum {
    GAME_ONGOING = -1,
    GAME_DRAW = 0,
    GAME_WIN_1 = 1,
    GAME_WIN_2 = 2,
    GAME_WIN_3 = 3,
    GAME_WIN_4 = 4
} GameResult;

/* Two-player convenience initializer. */
void game_init(Game *game);
/* Invalid counts return false without changing state. */
bool game_init_count(Game *game, int bot_count);
/* Caller supplies all active actions chosen from the same turn-start state.
 * W/A/S/D/X only. Invalid actions or a finished game return false unchanged.
 * Protocol validation and error-to-X conversion belong to the host.
 */
bool game_step(Game *game, const char actions[GAME_BOTS]);
void game_scores(const Game *game, int scores[GAME_BOTS]);
GameResult game_result(const Game *game);

#endif
