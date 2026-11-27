#include "game.h"
#include <stdio.h>
#include <string.h>

bool treasure_init(TreasureGame *game, int count) {
    static const int coordinates[] = {2, 4, 6, 9, 11, 13};
    static const TreasurePosition starts[] = {{0, 0}, {15, 15}, {15, 0}, {0, 15}};
    if (count < 2 || count > TREASURE_BOTS) return false;
    *game = (TreasureGame){0};
    game->bot_count = count;
    for (int i = 0; i < count; ++i) game->positions[i] = starts[i];
    for (int row = 0; row < 6; ++row) {
        for (int col = 0; col < 6; ++col) {
            int x = coordinates[col], y = coordinates[row];
            game->board[y][x] = ((x == 6 || x == 9) && (y == 6 || y == 9)) ? 5 : 1;
        }
    }
    return true;
}

bool treasure_step(TreasureGame *game, const char actions[TREASURE_BOTS]) {
    TreasurePosition next[TREASURE_BOTS];
    if (game->turns_played >= TREASURE_TURNS) return false;
    for (int i = 0; i < game->bot_count; ++i) {
        next[i] = game->positions[i];
        switch (actions[i]) {
        case 'W': --next[i].y; break;
        case 'A': --next[i].x; break;
        case 'S': ++next[i].y; break;
        case 'D': ++next[i].x; break;
        case 'X': break;
        default: return false;
        }
        if (next[i].x < 0 || next[i].x >= TREASURE_SIZE ||
            next[i].y < 0 || next[i].y >= TREASURE_SIZE)
            next[i] = game->positions[i];
    }
    /* Validate every action before mutating state; count stationary occupants too. */
    for (int i = 0; i < game->bot_count; ++i) {
        int occupants = 0;
        for (int j = 0; j < game->bot_count; ++j)
            if (next[i].x == next[j].x && next[i].y == next[j].y) ++occupants;
        game->positions[i] = next[i];
        if (occupants == 1) {
            game->scores[i] += game->board[next[i].y][next[i].x];
            game->board[next[i].y][next[i].x] = 0;
        }
    }
    ++game->turns_played;
    return true;
}

int treasure_result(const TreasureGame *game) {
    if (game->turns_played < TREASURE_TURNS) return -1;
    int highest = -1, winner = 0;
    for (int i = 0; i < game->bot_count; ++i) {
        if (game->scores[i] > highest) {
            highest = game->scores[i];
            winner = i + 1;
        } else if (game->scores[i] == highest) winner = 0;
    }
    return winner;
}

int treasure_remaining(const TreasureGame *game) {
    int count = 0;
    for (int y = 0; y < TREASURE_SIZE; ++y)
        for (int x = 0; x < TREASURE_SIZE; ++x) count += game->board[y][x] != 0;
    return count;
}

size_t treasure_input(const TreasureGame *game, int bot, char input[512]) {
    size_t size = 10;
    memcpy(input, "TREASURE1\n", size);
    for (int y = 0; y < TREASURE_SIZE; ++y) {
        for (int x = 0; x < TREASURE_SIZE; ++x)
            input[size++] = game->board[y][x] ? (char)('0' + game->board[y][x]) : '.';
        input[size++] = '\n';
    }
    size += (size_t)sprintf(input + size, "%d %03d %d\n", bot + 1,
                           TREASURE_TURNS - game->turns_played, game->bot_count);
    for (int i = 0; i < game->bot_count; ++i)
        size += (size_t)sprintf(input + size, "%d %02d %02d %03d\n", i + 1,
                               game->positions[i].x, game->positions[i].y, game->scores[i]);
    return size;
}
