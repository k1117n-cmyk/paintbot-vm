#include "game.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL %s:%d: %s\n", __func__, __LINE__, #condition); \
        exit(EXIT_FAILURE); \
    } \
} while (0)

static void steps(Game *g, char first, char second, int count) {
    const char actions[GAME_BOTS] = {first, second};
    int i;
    for (i = 0; i < count; ++i) {
        CHECK(game_step(g, actions));
    }
}

static void position(const Game *g, int bot, int x, int y) {
    CHECK(g->positions[bot].x == x);
    CHECK(g->positions[bot].y == y);
}

static void scores(const Game *g, int first, int second) {
    int actual[GAME_BOTS];
    game_scores(g, actual);
    CHECK(actual[0] == first);
    CHECK(actual[1] == second);
}

static void same_state(const Game *a, const Game *b) {
    int i;
    CHECK(memcmp(a->board, b->board, sizeof a->board) == 0);
    CHECK(a->turns_played == b->turns_played);
    for (i = 0; i < GAME_BOTS; ++i) {
        position(a, i, b->positions[i].x, b->positions[i].y);
    }
}

static void initial_board(void) {
    Game g;
    int x, y;
    game_init(&g);
    position(&g, 0, 0, 0);
    position(&g, 1, 15, 15);
    for (y = 0; y < 16; ++y) {
        for (x = 0; x < 16; ++x) {
            int expected = (x == 0 && y == 0) ? 1 :
                           (x == 15 && y == 15) ? 2 : 0;
            CHECK(g.board[y][x] == expected);
        }
    }
    scores(&g, 1, 1);
    CHECK(g.turns_played == 0);
    CHECK(game_result(&g) == GAME_ONGOING);
}

static void movement_and_revisit(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'A', 1);
    steps(&g, 'S', 'W', 1);
    steps(&g, 'A', 'D', 1);
    steps(&g, 'W', 'S', 1);
    position(&g, 0, 0, 0);
    position(&g, 1, 15, 15);
    scores(&g, 4, 4);
}

static void all_four_boundaries(void) {
    Game g;
    game_init(&g);
    steps(&g, 'W', 'S', 2);
    steps(&g, 'A', 'D', 2);
    position(&g, 0, 0, 0);
    position(&g, 1, 15, 15);
    scores(&g, 1, 1);
}

static void overwrite_opponent(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'X', 15);
    steps(&g, 'X', 'W', 1); /* Vacate ID 2's starting cell. */
    steps(&g, 'S', 'X', 15);
    position(&g, 0, 15, 15);
    CHECK(g.board[15][15] == 1);
    CHECK(g.board[14][15] == 1); /* Moving ID 1 paints over waiting ID 2. */
    scores(&g, 31, 0);
}

static void collision_on_unpainted_cell(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'W', 15);
    position(&g, 0, 15, 0);
    position(&g, 1, 15, 0);
    CHECK(g.board[0][15] == 0);
    scores(&g, 15, 15);
}

static void collision_on_painted_cell(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'X', 15);
    steps(&g, 'A', 'W', 1);
    steps(&g, 'X', 'W', 13);
    steps(&g, 'D', 'W', 1);
    position(&g, 0, 15, 0);
    position(&g, 1, 15, 0);
    CHECK(g.board[0][15] == 1);
    scores(&g, 16, 15);
}

static void wait_does_not_repaint(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'X', 15);
    steps(&g, 'X', 'W', 15); /* Moving ID 2 meets waiting ID 1. */
    CHECK(g.board[0][15] == 2);
    steps(&g, 'A', 'X', 1);
    position(&g, 1, 15, 0);
    CHECK(g.board[0][15] == 2);
    scores(&g, 15, 16);
    steps(&g, 'X', 'A', 1); /* Moving ID 2 paints where ID 1 waits. */
    CHECK(g.board[0][14] == 2);
    steps(&g, 'X', 'D', 1); /* ID 1 keeps waiting on ID 2's color. */
    CHECK(g.board[0][14] == 2);
    scores(&g, 14, 17);
}

static void arrival_over_boundary_wait(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'W', 15); /* Both arrive at unpainted (15,0). */
    steps(&g, 'X', 'S', 1);
    steps(&g, 'W', 'W', 1); /* ID 1 is blocked; ID 2 arrives. */
    position(&g, 0, 15, 0);
    position(&g, 1, 15, 0);
    CHECK(g.board[0][15] == 2);
    scores(&g, 15, 16);

    game_init(&g);
    steps(&g, 'D', 'W', 15);
    steps(&g, 'A', 'X', 1);
    steps(&g, 'D', 'W', 1); /* ID 1 arrives; ID 2 is blocked. */
    position(&g, 0, 15, 0);
    position(&g, 1, 15, 0);
    CHECK(g.board[0][15] == 1);
    scores(&g, 16, 15);
}

static void overlapping_bots_can_separate(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'W', 15);
    steps(&g, 'A', 'S', 1);
    position(&g, 0, 14, 0);
    position(&g, 1, 15, 1);
    CHECK(g.board[0][15] == 0);
    CHECK(g.board[0][14] == 1);
    CHECK(g.board[1][15] == 2);
    scores(&g, 15, 15);
}

static void swapping_positions_paints_both(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'W', 14);
    steps(&g, 'X', 'W', 1);
    steps(&g, 'D', 'A', 1);
    position(&g, 0, 15, 0);
    position(&g, 1, 14, 0);
    CHECK(g.board[0][15] == 1);
    CHECK(g.board[0][14] == 2);
    scores(&g, 15, 16);
}

static void boundary_move_does_not_paint(void) {
    Game g;
    game_init(&g);
    steps(&g, 'D', 'W', 15); /* Shared, unpainted (15,0). */
    steps(&g, 'D', 'S', 1); /* ID 1 remains at edge and must not paint. */
    position(&g, 0, 15, 0);
    CHECK(g.board[0][15] == 0);
    scores(&g, 15, 15);
}

static void match_draw_and_no_overtime(void) {
    Game g, finished;
    const char actions[GAME_BOTS] = {'D', 'A'};
    game_init(&g);
    steps(&g, 'X', 'X', 199);
    CHECK(game_result(&g) == GAME_ONGOING);
    steps(&g, 'X', 'X', 1);
    scores(&g, 1, 1);
    CHECK(g.turns_played == 200);
    CHECK(game_result(&g) == GAME_DRAW);
    finished = g;
    CHECK(!game_step(&g, actions));
    same_state(&g, &finished);
    puts("  200 turns: score=1:1 result=draw; turn 201 rejected");
}

static void last_turn_win_1(void) {
    Game g;
    game_init(&g);
    steps(&g, 'X', 'X', 199);
    CHECK(game_result(&g) == GAME_ONGOING);
    steps(&g, 'D', 'X', 1);
    scores(&g, 2, 1);
    CHECK(game_result(&g) == GAME_WIN_1);
    puts("  200 turns: score=2:1 result=ID 1 wins (turn 200 paints)");
}

static void match_win_2(void) {
    Game g;
    game_init(&g);
    steps(&g, 'X', 'A', 15);
    steps(&g, 'X', 'X', 185);
    scores(&g, 1, 16);
    CHECK(game_result(&g) == GAME_WIN_2);
    puts("  200 turns: score=1:16 result=ID 2 wins");
}

static void snake_match_and_replay(void) {
    Game g, replay;
    int turn;
    game_init(&g);
    game_init(&replay);
    /* Fixed serpentine path: 15 horizontal moves, then one downward move. */
    for (turn = 0; turn < 200; ++turn) {
        char action = turn % 16 == 15 ? 'S' :
                      (turn / 16) % 2 == 0 ? 'D' : 'A';
        steps(&g, action, 'X', 1);
        steps(&replay, action, 'X', 1);
        same_state(&g, &replay);
        scores(&g, turn + 2, 1);
        CHECK(game_result(&g) == (turn == 199 ? GAME_WIN_1 : GAME_ONGOING));
    }
    position(&g, 0, 8, 12);
    puts("  200 turns: score=201:1 result=ID 1 wins; replay identical");
}

static void invalid_action_is_atomic(void) {
    Game g, before;
    const char invalid[GAME_BOTS] = {'D', '?'};
    game_init(&g);
    before = g;
    CHECK(!game_step(&g, invalid));
    same_state(&g, &before);
}

static void multi_initialization(void) {
    Game g, before;
    game_init(&g);
    before = g;
    CHECK(!game_init_count(&g, 1));
    CHECK(memcmp(&g, &before, sizeof g) == 0);
    CHECK(!game_init_count(&g, 5));
    CHECK(memcmp(&g, &before, sizeof g) == 0);
    for (int n = 3; n <= 4; ++n) {
        CHECK(game_init_count(&g, n));
        CHECK(g.bot_count == n);
        int actual[GAME_BOTS];
        game_scores(&g, actual);
        for (int i = 0; i < GAME_BOTS; ++i) CHECK(actual[i] == (i < n));
        position(&g, 2, 15, 0);
        CHECK(g.board[0][15] == 3);
        if (n == 4) { position(&g, 3, 0, 15); CHECK(g.board[15][0] == 4); }
        else CHECK(g.board[15][0] == 0);
    }
}

static void multi_collision(void) {
    /* Two, three or four arrivals preserve every possible underlying color. */
    for (int n = 2; n <= 4; ++n) {
        for (int color = 0; color <= 4; ++color) {
            Game g;
            CHECK(game_init_count(&g, 4));
            const GamePosition starts[] = {{7, 6}, {6, 7}, {7, 8}, {8, 7}};
            char actions[GAME_BOTS] = {'S', 'D', 'W', 'A'};
            for (int i = 0; i < 4; ++i) {
                g.positions[i] = i < n ? starts[i] : (GamePosition){7, 7};
                if (i >= n) actions[i] = 'X';
            }
            g.board[7][7] = (unsigned char)color;
            CHECK(game_step(&g, actions));
            CHECK(g.board[7][7] == color);
            for (int i = 0; i < 4; ++i) position(&g, i, 7, 7);
        }
    }
}

static void sole_arrival_and_separation(void) {
    for (int mover = 0; mover < 4; ++mover) {
        Game g;
        CHECK(game_init_count(&g, 4));
        char actions[GAME_BOTS] = {'X', 'X', 'X', 'X'};
        for (int i = 0; i < 4; ++i) g.positions[i] = (GamePosition){7, 7};
        g.positions[mover] = (GamePosition){6, 7};
        actions[mover] = 'D';
        CHECK(game_step(&g, actions));
        CHECK(g.board[7][7] == mover + 1);
        const char separate[GAME_BOTS] = {'W', 'A', 'S', 'D'};
        CHECK(game_step(&g, separate));
        for (int i = 0; i < 4; ++i)
            CHECK(g.board[g.positions[i].y][g.positions[i].x] == i + 1);
    }
}

static void blocked_moves_preserve_opponent_color(void) {
    Game g;
    CHECK(game_init_count(&g, 4));
    for (int i = 0; i < 4; ++i)
        g.board[g.positions[i].y][g.positions[i].x] = (unsigned char)((i + 1) % 4 + 1);
    Game before = g;
    const char actions[GAME_BOTS] = {'W', 'S', 'D', 'A'};
    CHECK(game_step(&g, actions));
    CHECK(memcmp(g.board, before.board, sizeof g.board) == 0);
    for (int i = 0; i < 4; ++i) position(&g, i, before.positions[i].x, before.positions[i].y);
}

static void check_overlap_without_arrivals(bool blocked) {
    for (int n = 2; n <= GAME_BOTS; ++n) {
        for (int color = 0; color <= n; ++color) {
            Game g, before;
            int scores_before[GAME_BOTS], scores_after[GAME_BOTS];
            char actions[GAME_BOTS];
            CHECK(game_init_count(&g, n));
            for (int i = 0; i < n; ++i) {
                g.positions[i] = (GamePosition){0, 0};
                actions[i] = blocked ? (i % 2 == 0 ? 'W' : 'A') : 'X';
            }
            g.board[0][0] = (unsigned char)color;
            before = g;
            game_scores(&g, scores_before);
            CHECK(game_step(&g, actions));
            CHECK(memcmp(g.board, before.board, sizeof g.board) == 0);
            for (int i = 0; i < n; ++i) position(&g, i, 0, 0);
            game_scores(&g, scores_after);
            CHECK(memcmp(scores_before, scores_after, sizeof scores_before) == 0);
            CHECK(g.turns_played == before.turns_played + 1);
        }
    }
}

static void overlapping_x_does_not_paint(void) {
    check_overlap_without_arrivals(false);
}

static void overlapping_blocked_moves_do_not_paint(void) {
    check_overlap_without_arrivals(true);
}

static void multi_match_results(void) {
    const char wait[GAME_BOTS] = {'X', 'X', 'X', 'X'};
    for (int n = 3; n <= 4; ++n) {
        for (int winner = 0; winner < n; ++winner) {
            Game g, replay;
            CHECK(game_init_count(&g, n));
            replay = g;
            for (int turn = 0; turn < GAME_TURNS; ++turn) {
                CHECK(game_step(&g, wait));
                CHECK(game_step(&replay, wait));
                same_state(&g, &replay);
            }
            CHECK(game_result(&g) == GAME_DRAW);
            CHECK(!game_step(&g, wait));
            g.board[7][7] = (unsigned char)(winner + 1);
            CHECK(game_result(&g) == (GameResult)(winner + 1));
            /* A tied maximum wins over lower scores, but remains a draw. */
            g.board[7][8] = (unsigned char)((winner + 1) % n + 1);
            CHECK(game_result(&g) == GAME_DRAW);
        }
    }
}

static void multi_invalid_action_atomic(void) {
    Game g;
    CHECK(game_init_count(&g, 4));
    Game before = g;
    const char invalid[GAME_BOTS] = {'D', 'A', 'S', '?'};
    CHECK(!game_step(&g, invalid));
    CHECK(memcmp(&g, &before, sizeof g) == 0);
}

int main(void) {
    const struct {
        const char *name;
        void (*run)(void);
    } tests[] = {
        {"overlapping_x_does_not_paint", overlapping_x_does_not_paint},
        {"overlapping_blocked_moves_do_not_paint", overlapping_blocked_moves_do_not_paint},
        {"multi_initialization", multi_initialization},
        {"multi_collision", multi_collision},
        {"sole_arrival_and_separation", sole_arrival_and_separation},
        {"blocked_moves_preserve_opponent_color", blocked_moves_preserve_opponent_color},
        {"multi_match_results", multi_match_results},
        {"multi_invalid_action_atomic", multi_invalid_action_atomic},
        {"initial_board", initial_board},
        {"movement_and_revisit", movement_and_revisit},
        {"all_four_boundaries", all_four_boundaries},
        {"overwrite_opponent", overwrite_opponent},
        {"collision_on_unpainted_cell", collision_on_unpainted_cell},
        {"collision_on_painted_cell", collision_on_painted_cell},
        {"wait_does_not_repaint", wait_does_not_repaint},
        {"arrival_over_boundary_wait", arrival_over_boundary_wait},
        {"overlapping_bots_can_separate", overlapping_bots_can_separate},
        {"swapping_positions_paints_both", swapping_positions_paints_both},
        {"boundary_move_does_not_paint", boundary_move_does_not_paint},
        {"match_draw_and_no_overtime", match_draw_and_no_overtime},
        {"last_turn_win_1", last_turn_win_1},
        {"match_win_2", match_win_2},
        {"snake_match_and_replay", snake_match_and_replay},
        {"invalid_action_is_atomic", invalid_action_is_atomic}
    };
    size_t i;
    for (i = 0; i < sizeof tests / sizeof tests[0]; ++i) {
        tests[i].run();
        printf("PASS %s\n", tests[i].name);
    }
    printf("PASS %zu tests, 0 failures\n", sizeof tests / sizeof tests[0]);
    return EXIT_SUCCESS;
}
