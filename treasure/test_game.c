#include "game.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); exit(1); } } while (0)

static int total(const TreasureGame *game) {
    int points = 0;
    for (int y = 0; y < 16; ++y)
        for (int x = 0; x < 16; ++x) points += game->board[y][x];
    for (int i = 0; i < game->bot_count; ++i) points += game->scores[i];
    return points;
}

static TreasureGame empty(int count) {
    TreasureGame game;
    CHECK(treasure_init(&game, count));
    memset(game.board, 0, sizeof game.board);
    return game;
}

int main(void) {
    TreasureGame game, before;
    for (int count = 2; count <= 4; ++count) {
        CHECK(treasure_init(&game, count));
        CHECK(game.bot_count == count && game.turns_played == 0);
        CHECK(treasure_remaining(&game) == 36 && total(&game) == 52);
        CHECK(game.positions[0].x == 0 && game.positions[1].x == 15);
        for (int y = 0; y < 16; ++y)
            for (int x = 0; x < 16; ++x) {
                CHECK(game.board[y][x] == game.board[15-y][15-x]);
                CHECK(game.board[y][x] == game.board[x][y]);
            }
    }
    before = game;
    CHECK(!treasure_init(&game, 1) && !memcmp(&game, &before, sizeof game));
    CHECK(!treasure_init(&game, 5) && !memcmp(&game, &before, sizeof game));
    puts("PASS initial layout, symmetry, 36 treasures/52 points, 2-4 bots and invalid counts");

    game = empty(2);
    game.board[0][1] = 1;
    game.board[15][14] = 5;
    CHECK(treasure_step(&game, "DA"));
    CHECK(game.scores[0] == 1 && game.scores[1] == 5 && !treasure_remaining(&game));
    CHECK(treasure_step(&game, "XX"));
    CHECK(game.scores[0] == 1 && game.scores[1] == 5);
    puts("PASS simultaneous collection, different values, removal and no duplicate scoring");

    game = empty(2);
    CHECK(treasure_step(&game, "AD"));
    CHECK(game.positions[0].x == 0 && game.positions[1].x == 15);
    CHECK(treasure_step(&game, "WS"));
    CHECK(game.positions[0].y == 0 && game.positions[1].y == 15);
    CHECK(treasure_step(&game, "SW"));
    CHECK(game.positions[0].y == 1 && game.positions[1].y == 14);
    puts("PASS all boundaries and vertical movement");

    game = empty(2);
    game.positions[1] = (TreasurePosition){2, 0};
    game.board[0][1] = 5;
    CHECK(treasure_step(&game, "DA"));
    CHECK(game.positions[0].x == 1 && game.positions[1].x == 1);
    CHECK(game.board[0][1] == 5 && game.scores[0] == 0 && game.scores[1] == 0);
    CHECK(treasure_step(&game, "XX"));
    CHECK(game.board[0][1] == 5);
    CHECK(treasure_step(&game, "XD"));
    CHECK(game.scores[0] == 5 && game.scores[1] == 0 && !treasure_remaining(&game));
    puts("PASS contested treasure remains, then sole waiting occupant collects");

    game = empty(2);
    game.positions[1] = (TreasurePosition){1, 0};
    game.board[0][1] = 1;
    CHECK(treasure_step(&game, "DX"));
    CHECK(game.board[0][1] == 1 && game.scores[0] == 0);
    CHECK(treasure_step(&game, "AD"));
    CHECK(game.board[0][1] == 1);
    game.positions[0] = (TreasurePosition){1, 0};
    game.positions[1] = (TreasurePosition){2, 0};
    game.board[0][2] = 5;
    CHECK(treasure_step(&game, "DA"));
    CHECK(game.scores[0] == 5 && game.scores[1] == 1);
    puts("PASS stationary occupant prevents collection, separation and position swapping");

    for (int count = 3; count <= 4; ++count) {
        game = empty(count);
        for (int i = 0; i < count; ++i) game.positions[i] = (TreasurePosition){6, 6};
        game.board[6][6] = 5;
        CHECK(treasure_step(&game, "XXXX"));
        CHECK(game.board[6][6] == 5 && total(&game) == 5);
        CHECK(treasure_step(&game, count == 3 ? "XDA" : "XDAS"));
        CHECK(game.scores[0] == 5 && !treasure_remaining(&game));
    }
    puts("PASS 3/4-way overlap and subsequent collection");

    CHECK(treasure_init(&game, 4));
    before = game;
    CHECK(!treasure_step(&game, "DS?X"));
    CHECK(!memcmp(&game, &before, sizeof game));
    puts("PASS invalid action leaves entire state unchanged");

    game = empty(2);
    CHECK(treasure_result(&game) == -1);
    for (int turn = 0; turn < 199; ++turn) CHECK(treasure_step(&game, "XX"));
    CHECK(treasure_result(&game) == -1);
    game.board[0][1] = 5;
    CHECK(treasure_step(&game, "DX"));
    CHECK(treasure_result(&game) == 1 && game.scores[0] == 5);
    before = game;
    CHECK(!treasure_step(&game, "XX") && !memcmp(&game, &before, sizeof game));
    puts("PASS no early finish on empty board, last-turn collection and no overtime");

    CHECK(treasure_init(&game, 4));
    game.turns_played = 200;
    CHECK(treasure_result(&game) == 0);
    game.scores[2] = 5;
    CHECK(treasure_result(&game) == 3);
    game.scores[3] = 5;
    CHECK(treasure_result(&game) == 0);
    game.scores[3] = 6;
    CHECK(treasure_result(&game) == 4);
    puts("PASS zero-score draw, later ID winner, tied leaders and unique leader");

    for (int count = 2; count <= 4; ++count) {
        CHECK(treasure_init(&game, count));
        TreasureGame replay = game;
        for (int turn = 0; turn < 200; ++turn) {
            char actions[4];
            for (int i = 0; i < count; ++i) actions[i] = "DSAWX"[(turn * 7 + i) % 5];
            CHECK(treasure_step(&game, actions) && treasure_step(&replay, actions));
            CHECK(total(&game) == 52 && !memcmp(&game, &replay, sizeof game));
        }
    }
    puts("PASS deterministic 200-turn replay and point conservation for 2/3/4 bots");

    for (int count = 2; count <= 4; ++count) {
        CHECK(treasure_init(&game, count));
        game.positions[0] = (TreasurePosition){12, 9};
        game.scores[0] = 5;
        before = game;
        for (int turn = 0; turn < 200; ++turn) {
            game.turns_played = turn;
            for (int bot = 0; bot < count; ++bot) {
                char input[512], expected[80];
                size_t size = treasure_input(&game, bot, input);
                CHECK(size == (size_t)(290 + count * 12));
                CHECK(!memcmp(input, "TREASURE1\n", 10));
                for (int y = 0; y < 16; ++y) {
                    for (int x = 0; x < 16; ++x)
                        CHECK(input[10+y*17+x] == (game.board[y][x] ? '0'+game.board[y][x] : '.'));
                    CHECK(input[10+y*17+16] == '\n');
                }
                snprintf(expected, sizeof expected, "%d %03d %d\n1 12 09 005\n", bot+1, 200-turn, count);
                CHECK(!memcmp(input+282, expected, strlen(expected)));
                for (int i = 1; i < count; ++i) {
                    snprintf(expected, sizeof expected, "%d %02d %02d 000\n", i+1,
                             game.positions[i].x, game.positions[i].y);
                    CHECK(!memcmp(input+290+i*12, expected, 12));
                }
                CHECK(input[size] == '\0');
            }
        }
        game.turns_played = before.turns_played;
        CHECK(!memcmp(&game, &before, sizeof game));
    }
    puts("PASS exact protocol bytes, IDs, scores, coordinates, remaining turns and unchanged snapshot");
    puts("PASS 11 treasure game groups, 0 failures");
    return 0;
}
