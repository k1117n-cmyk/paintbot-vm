#define _POSIX_C_SOURCE 200809L
#include "game.h"
#include "../game/bot_runner.h"
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static void result(FILE *out, const TreasureGame *game) {
    int winner = treasure_result(game);
    if (winner < 0) fputs("Match in progress", out);
    else if (!winner) fputs("Result: draw", out);
    else fprintf(out, "Result: ID %d wins", winner);
}

static void frame(const TreasureGame *game, const int counts[TREASURE_BOTS][4]) {
    fputs("\033[H", stdout);
    printf("Treasure | Turn %03d/200 | Left %03d | Gems %02d\033[K\n",
           game->turns_played, TREASURE_TURNS - game->turns_played,
           treasure_remaining(game));
    for (int i = 0; i < game->bot_count; ++i)
        printf(" ID %d %3d ", i + 1, game->scores[i]);
    fputs("\033[K\n", stdout);
    for (int y = 0; y < TREASURE_SIZE; ++y) {
        for (int x = 0; x < TREASURE_SIZE; ++x) {
            int occupants = 0;
            unsigned char value = game->board[y][x];
            char cell[3] = {value == 5 ? '$' : value ? 'o' : '.', ' ', '\0'};
            for (int i = 0; i < game->bot_count; ++i) {
                if (game->positions[i].x == x && game->positions[i].y == y) {
                    if (occupants < 2) cell[occupants] = (char)('1' + i);
                    ++occupants;
                }
            }
            if (occupants > 2) { cell[0] = '*'; cell[1] = ' '; }
            fputs(value == 5 ? "\033[30;43m" : value ? "\033[30;46m" : "\033[0m", stdout);
            fputs(cell, stdout);
        }
        fputs("\033[0m\033[K\n", stdout);
    }
    fputs("o:1pt $:5pt | digits:bots *:3+ | A:ok T:timeout I:bad E:VM\033[K\n", stdout);
    result(stdout, game);
    fputs("\033[K\n", stdout);
    for (int i = 0; i < game->bot_count; ++i)
        printf("ID %d: A=%d T=%d I=%d E=%d%s", i + 1,
               counts[i][0], counts[i][1], counts[i][2], counts[i][3],
               i % 2 == 1 || i + 1 == game->bot_count ? "\033[K\n" : " | ");
    fflush(stdout);
}

int main(int argc, char **argv) {
    const char *term = getenv("TERM");
    int watch = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb");
    if (argc > 1 && (!strcmp(argv[1], "--watch") || !strcmp(argv[1], "--no-watch"))) {
        watch = !strcmp(argv[1], "--watch");
        --argc; ++argv;
    }
    if (argc < 4 || argc > 6 || argv[1][0] == '-') {
        fputs("usage: treasure-host [--watch|--no-watch] vm bot1.bin bot2.bin [bot3.bin [bot4.bin]]\n", stderr);
        return 1;
    }
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("treasure: SIGPIPE"); return 1; }
    TreasureGame game;
    int counts[TREASURE_BOTS][4] = {{0}};
    if (!treasure_init(&game, argc - 2)) return 1;
    if (watch) {
        fputs("\033[0m\033[2J", stdout);
        frame(&game, (const int (*)[4])counts);
    }
    while (game.turns_played < TREASURE_TURNS) {
        int64_t start = watch ? now_ns() : 0;
        if (start < 0) { perror("treasure: clock"); return 1; }
        char actions[TREASURE_BOTS];
        for (int i = 0; i < game.bot_count; ++i) {
            char input[512];
            Reply reply;
            size_t size = treasure_input(&game, i, input);
            if (run_bot(argv[1], argv[i + 2], input, size, &reply) < 0) return 1;
            actions[i] = reply.action;
            ++counts[i][reply.outcome];
            if (!watch && reply.outcome != ACCEPTED && counts[i][reply.outcome] == 1) {
                static const char *names[] = {"accepted", "timeout", "invalid output", "VM error"};
                fprintf(stderr, "turn %d ID %d: %s -> X\n", game.turns_played + 1,
                        i + 1, names[reply.outcome]);
                fwrite(reply.diagnostic, 1, reply.diagnostic_size, stderr);
                if (reply.outcome == TIMED_OUT) print_timeout(stderr, &reply.timeout);
            }
        }
        if (!treasure_step(&game, actions)) return 1;
        if (watch) {
            int64_t now;
            while ((now = now_ns()) >= 0 && now - start < 200000000LL) {
                int64_t remaining = 200000000LL - (now - start);
                struct timespec delay = {remaining / 1000000000LL, remaining % 1000000000LL};
                if (nanosleep(&delay, NULL) < 0 && errno != EINTR) {
                    perror("treasure: display wait"); return 1;
                }
            }
            if (now < 0) { perror("treasure: clock"); return 1; }
            frame(&game, (const int (*)[4])counts);
        }
    }
    if (!watch) {
        printf("Final board (turns=%d):\n", game.turns_played);
        for (int y = 0; y < TREASURE_SIZE; ++y) {
            for (int x = 0; x < TREASURE_SIZE; ++x)
                putchar(game.board[y][x] ? '0' + game.board[y][x] : '.');
            putchar('\n');
        }
        printf("Score: %d", game.scores[0]);
        for (int i = 1; i < game.bot_count; ++i) printf(":%d", game.scores[i]);
        printf("\nTreasures left: %d\n", treasure_remaining(&game));
        result(stdout, &game);
        putchar('\n');
        for (int i = 0; i < game.bot_count; ++i)
            printf("ID %d: accepted=%d timeout=%d invalid=%d VM-error=%d\n", i + 1,
                   counts[i][0], counts[i][1], counts[i][2], counts[i][3]);
    }
    return ferror(stdout) ? 1 : 0;
}
