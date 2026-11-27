#define _POSIX_C_SOURCE 200809L
#include "game.h"
#include "display.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "bot_runner.h"

static size_t turn_input(const Game *game, int bot, char *input) {
    size_t size = 0;
    int x, y, i;
    for (y = 0; y < GAME_SIZE; ++y) {
        for (x = 0; x < GAME_SIZE; ++x) {
            unsigned char color = game->board[y][x];
            input[size++] = color ? (char)('0' + color) : '.';
        }
        input[size++] = '\n';
    }
    size += (size_t)sprintf(input + size, "%d %03d %d\n", bot + 1,
                           GAME_TURNS - game->turns_played, game->bot_count);
    for (i = 0; i < game->bot_count; ++i)
        size += (size_t)sprintf(input + size, "%d %02d %02d\n", i + 1,
                               game->positions[i].x, game->positions[i].y);
    return size;
}

int main(int argc, char **argv) {
    Game game;
    int counts[GAME_BOTS][4] = {{0}};
    int scores[GAME_BOTS], i, x, y;
    const char *term = getenv("TERM");
    int watch = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb") != 0;
    if (argc > 1 && (strcmp(argv[1], "--watch") == 0 ||
                     strcmp(argv[1], "--no-watch") == 0)) {
        watch = strcmp(argv[1], "--watch") == 0;
        --argc;
        ++argv;
    }
    if (argc < 4 || argc > 6) {
        fprintf(stderr, "usage: paint-host [--watch|--no-watch] vm-executable bot1.bin bot2.bin [bot3.bin [bot4.bin]]\n");
        return 1;
    }
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) { perror("host: SIGPIPE"); return 1; }
    if (!game_init_count(&game, argc - 2)) return 1;
    if (watch) {
        fputs("\033[0m\033[2J", stdout);
        display_frame(stdout, &game, (const int (*)[4])counts);
    }
    while (game.turns_played < GAME_TURNS) {
        int64_t frame_start = watch ? now_ns() : 0;
        if (frame_start < 0) { perror("host: clock"); return 1; }
        char actions[GAME_BOTS];
        for (i = 0; i < game.bot_count; ++i) {
            char input[512];
            Reply reply;
            size_t size = turn_input(&game, i, input);
            if (run_bot(argv[1], argv[i + 2], input, size, &reply) < 0) return 1;
            actions[i] = reply.action;
            ++counts[i][reply.outcome];
            /* Show the first diagnostic for each failure kind; totals below
             * cover every turn without repeating the same message 200 times. */
            if (!watch && reply.outcome != ACCEPTED && counts[i][reply.outcome] == 1) {
                static const char *names[] = {"accepted", "timeout", "invalid output", "VM error"};
                fprintf(stderr, "turn %d ID %d: %s -> X\n", game.turns_played + 1,
                        i + 1, names[reply.outcome]);
                fwrite(reply.diagnostic, 1, reply.diagnostic_size, stderr);
                if (reply.outcome == TIMED_OUT) print_timeout(stderr, &reply.timeout);
            }
        }
        if (!game_step(&game, actions)) { fprintf(stderr, "host: game_step failed\n"); return 1; }
        if (watch) {
            int64_t now;
            /* VM supervision has finished; pacing cannot consume its deadline. */
            while ((now = now_ns()) >= 0 && now - frame_start < 200000000LL) {
                int64_t remaining = 200000000LL - (now - frame_start);
                struct timespec delay = {remaining / 1000000000LL, remaining % 1000000000LL};
                if (nanosleep(&delay, NULL) < 0 && errno != EINTR) {
                    perror("host: display wait"); return 1;
                }
            }
            if (now < 0) { perror("host: clock"); return 1; }
            display_frame(stdout, &game, (const int (*)[4])counts);
        }
    }
    if (watch) return ferror(stdout) ? 1 : 0;
    printf("Final board (turns=%d):\n", game.turns_played);
    for (y = 0; y < GAME_SIZE; ++y) {
        for (x = 0; x < GAME_SIZE; ++x)
            putchar(game.board[y][x] ? '0' + game.board[y][x] : '.');
        putchar('\n');
    }
    game_scores(&game, scores);
    printf("Score: %d", scores[0]);
    for (i = 1; i < game.bot_count; ++i) printf(":%d", scores[i]);
    putchar('\n');
    GameResult result = game_result(&game);
    if (result == GAME_DRAW) puts("Result: draw");
    else printf("Result: ID %d wins\n", result);
    for (i = 0; i < game.bot_count; ++i)
        printf("ID %d: accepted=%d timeout=%d invalid=%d VM-error=%d\n", i + 1,
               counts[i][0], counts[i][1], counts[i][2], counts[i][3]);
    return 0;
}
