#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

static const char *const board[] = {
    "#################",
    "#S    #         #",
    "# ### # ####### #",
    "# #   #     #   #",
    "# # ####### # # #",
    "# #         # # #",
    "# ########### # #",
    "#             #G#",
    "#################"
};
static volatile sig_atomic_t interrupted;

static void stop(int signum) { interrupted = signum; }

/* Read exactly one byte: never consume the launcher's next command. */
static int next_key(void) {
    unsigned char key;
    while (!interrupted) {
        ssize_t count = read(STDIN_FILENO, &key, 1);
        if (count == 1) return key;
        if (count == 0) return -1;
        if (errno != EINTR) { perror("maze: read"); return -2; }
    }
    return -1;
}

static void draw(int x, int y, unsigned moves, int ansi, const char *notice) {
    if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
    puts("Maze - reach G\n");
    for (int row = 0; row < 9; ++row) {
        for (int col = 0; col < 17; ++col)
            putchar(col == x && row == y ? '@' : board[row][col]);
        putchar('\n');
    }
    printf("\nMoves: %u\n", moves);
    puts("W/A/S/D: move | R: restart | Q: back to games");
    puts("@: you | #: wall | S: start | G: goal");
    puts(notice);
    fflush(stdout);
}

int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) { fputs("usage: maze/build/maze\n", stderr); return 1; }
    const int signals[] = {SIGINT, SIGTERM, SIGHUP};
    struct sigaction action, previous[3];
    memset(&action, 0, sizeof action);
    action.sa_handler = stop;
    sigemptyset(&action.sa_mask);
    int installed = 0, status = 0, changed = 0;
    struct termios saved;
    for (; installed < 3; ++installed) {
        if (sigaction(signals[installed], &action, &previous[installed]) < 0) {
            perror("maze: signal"); status = 1; goto cleanup;
        }
    }
    int terminal = isatty(STDIN_FILENO);
    if (terminal) {
        if (tcgetattr(STDIN_FILENO, &saved) < 0) {
            perror("maze: terminal"); status = 1; goto cleanup;
        }
        struct termios mode = saved;
        mode.c_lflag &= ~(ICANON | ECHO);
        mode.c_cc[VMIN] = 1;
        mode.c_cc[VTIME] = 0;
        if (tcsetattr(STDIN_FILENO, TCSANOW, &mode) < 0) {
            perror("maze: terminal"); status = 1; goto cleanup;
        }
        changed = 1;
    }
    const char *term = getenv("TERM");
    int ansi = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb");
    int x = 1, y = 1;
    unsigned moves = 0;
    draw(x, y, moves, ansi, terminal ? "Press a key (no Enter needed)." : "Enter W/A/S/D commands.");
    for (;;) {
        int key = next_key();
        if (key < 0) { if (key == -2) status = 1; break; }
        if (key == 'q' || key == 'Q') break;
        if (key == '\r' || key == '\n') continue;
        if (key == 'r' || key == 'R') {
            x = y = 1; moves = 0;
            draw(x, y, moves, ansi, "Restarted.");
            continue;
        }
        int dx = 0, dy = 0;
        switch (key) {
        case 'w': case 'W': dy = -1; break;
        case 's': case 'S': dy = 1; break;
        case 'a': case 'A': dx = -1; break;
        case 'd': case 'D': dx = 1; break;
        default: draw(x, y, moves, ansi, "Use W/A/S/D, R or Q."); continue;
        }
        if (board[y + dy][x + dx] == '#') {
            draw(x, y, moves, ansi, "Wall. Choose another direction.");
            continue;
        }
        x += dx; y += dy; ++moves;
        if (board[y][x] == 'G') {
            draw(x, y, moves, ansi, "Cleared! Enter or Q: back to games");
            do { key = next_key(); } while (key >= 0 && key != '\r' && key != '\n' && key != 'q' && key != 'Q');
            if (key == -2) status = 1;
            break;
        }
        draw(x, y, moves, ansi, "Reach G to clear the maze.");
    }

cleanup:
    if (changed && tcsetattr(STDIN_FILENO, TCSANOW, &saved) < 0) {
        perror("maze: restore terminal"); status = 1;
    }
    for (int i = installed - 1; i >= 0; --i)
        if (sigaction(signals[i], &previous[i], NULL) < 0) status = 1;
    return interrupted ? 128 + interrupted : status;
}
