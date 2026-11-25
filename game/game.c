#include "game.h"

bool game_init_count(Game *game, int bot_count) {
    static const GamePosition starts[GAME_BOTS] = {
        {0, 0}, {15, 15}, {15, 0}, {0, 15}
    };
    if (bot_count < 2 || bot_count > GAME_BOTS) return false;
    *game = (Game){0};
    game->bot_count = bot_count;
    for (int i = 0; i < bot_count; ++i) {
        game->positions[i] = starts[i];
        game->board[starts[i].y][starts[i].x] = (unsigned char)(i + 1);
    }
    return true;
}

void game_init(Game *game) {
    (void)game_init_count(game, 2);
}

bool game_step(Game *game, const char actions[GAME_BOTS]) {
    GamePosition destinations[GAME_BOTS];
    bool arrived[GAME_BOTS];
    int i;

    if (game->turns_played >= GAME_TURNS) {
        return false;
    }
    /* Collect and resolve all destinations before changing any game state. */
    for (i = 0; i < game->bot_count; ++i) {
        GamePosition next = game->positions[i];
        switch (actions[i]) {
        case 'W': --next.y; break;
        case 'A': --next.x; break;
        case 'S': ++next.y; break;
        case 'D': ++next.x; break;
        case 'X': break;
        default: return false;
        }
        if (next.x < 0 || next.x >= GAME_SIZE ||
            next.y < 0 || next.y >= GAME_SIZE) {
            next = game->positions[i];
        }
        destinations[i] = next;
        arrived[i] = next.x != game->positions[i].x ||
                     next.y != game->positions[i].y;
    }

    /* Count actual arrivals, independently of stationary occupants and ID order. */
    for (i = 0; i < game->bot_count; ++i) {
        int arrivals = 0;
        for (int j = 0; j < game->bot_count; ++j) {
            if (arrived[j] && destinations[j].x == destinations[i].x &&
                destinations[j].y == destinations[i].y) ++arrivals;
        }
        game->positions[i] = destinations[i];
        if (arrived[i] && arrivals == 1)
            game->board[destinations[i].y][destinations[i].x] = (unsigned char)(i + 1);
    }
    ++game->turns_played;
    return true;
}

void game_scores(const Game *game, int scores[GAME_BOTS]) {
    int x, y;
    for (int i = 0; i < GAME_BOTS; ++i) scores[i] = 0;
    for (y = 0; y < GAME_SIZE; ++y) {
        for (x = 0; x < GAME_SIZE; ++x) {
            unsigned char color = game->board[y][x];
            if (color >= 1 && color <= game->bot_count) {
                ++scores[color - 1];
            }
        }
    }
}

GameResult game_result(const Game *game) {
    int scores[GAME_BOTS];
    if (game->turns_played < GAME_TURNS) {
        return GAME_ONGOING;
    }
    game_scores(game, scores);
    int best = 0;
    bool tied = false;
    for (int i = 1; i < game->bot_count; ++i) {
        if (scores[i] > scores[best]) { best = i; tied = false; }
        else if (scores[i] == scores[best]) tied = true;
    }
    return tied ? GAME_DRAW : (GameResult)(best + 1);
}
