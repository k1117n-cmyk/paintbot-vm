#define _POSIX_C_SOURCE 200809L
#include "game_io.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static const int signals[] = {SIGINT, SIGTERM, SIGHUP};
static struct sigaction previous[3];
static int installed;
static struct termios saved;
static bool changed, ansi;
static struct timespec deadline;

static void stop(int signum) { interrupted = signum; }
int vm_game_signal(void) { return interrupted; }

bool vm_game_close(void) {
    bool ok = true;
    if (changed) {
        int result;
        do { result = tcsetattr(STDIN_FILENO, TCSANOW, &saved); }
        while (result < 0 && errno == EINTR);
        if (result < 0) { perror("VM game: restore terminal"); ok = false; }
        changed = false;
    }
    if (ansi) {
        if (fputs("\033[0m\033[?25h", stdout) == EOF || fflush(stdout)) ok = false;
        ansi = false;
    }
    while (installed) {
        --installed;
        if (sigaction(signals[installed], &previous[installed], NULL) < 0) ok = false;
    }
    return ok;
}

bool vm_game_open(void) {
    struct sigaction action;
    memset(&action, 0, sizeof action);
    action.sa_handler = stop;
    sigemptyset(&action.sa_mask);
    interrupted = 0;
    for (installed = 0; installed < 3; ++installed) {
        if (sigaction(signals[installed], &action, &previous[installed]) < 0) {
            perror("VM game: signal"); return false;
        }
    }
    if (isatty(STDIN_FILENO)) {
        if (tcgetattr(STDIN_FILENO, &saved) < 0) {
            perror("VM game: terminal"); return false;
        }
        struct termios mode = saved;
        mode.c_lflag &= ~(ICANON | ECHO);
        mode.c_cc[VMIN] = 1;
        mode.c_cc[VTIME] = 0;
        if (tcsetattr(STDIN_FILENO, TCSANOW, &mode) < 0) {
            perror("VM game: terminal"); return false;
        }
        changed = true;
    }
    if (clock_gettime(CLOCK_MONOTONIC, &deadline)) {
        perror("VM game: clock"); return false;
    }
    const char *term = getenv("TERM");
    ansi = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb");
    if (ansi) {
        fputs("\033[0m\033[2J\033[H\033[?25l", stdout);
        if (fflush(stdout)) return false;
    }
    return true;
}

bool vm_game_frame(const uint8_t *cells) {
    for (int i = 0; i < VM_FRAME_SIZE; ++i) {
        if (cells[i] < 32 || cells[i] > 126) {
            fputs("VM game: frame must contain printable ASCII\n", stderr);
            return false;
        }
    }
    if (ansi) fputs("\033[H", stdout);
    for (int row = 0; row < VM_FRAME_HEIGHT; ++row) {
        if (fwrite(cells + row * VM_FRAME_WIDTH, 1, VM_FRAME_WIDTH, stdout) != VM_FRAME_WIDTH ||
            putchar('\n') == EOF) return false;
    }
    return fflush(stdout) == 0;
}

bool vm_game_key(uint32_t *key) {
    *key = 0;
    struct pollfd input = {STDIN_FILENO, POLLIN, 0};
    int ready = poll(&input, 1, 0);
    if (ready < 0) {
        if (errno == EINTR) return true;
        perror("VM game: poll"); return false;
    }
    if (!ready) return true;
    if (input.revents & (POLLERR | POLLNVAL)) {
        fputs("VM game: input error\n", stderr); return false;
    }
    if (input.revents & (POLLIN | POLLHUP)) {
        unsigned char byte;
        ssize_t count = read(STDIN_FILENO, &byte, 1);
        if (count == 1) *key = byte;
        else if (count == 0) *key = VM_KEY_EOF;
        else if (errno != EINTR) { perror("VM game: read"); return false; }
    }
    return true;
}

bool vm_game_wait(uint32_t milliseconds) {
    if (milliseconds == 0 || milliseconds > 1000) {
        fputs("VM game: frame interval must be 1..1000 ms\n", stderr);
        return false;
    }
    deadline.tv_nsec += (long)milliseconds * 1000000L;
    deadline.tv_sec += deadline.tv_nsec / 1000000000L;
    deadline.tv_nsec %= 1000000000L;
    struct timespec now;
    while (!interrupted) {
        if (clock_gettime(CLOCK_MONOTONIC, &now)) { perror("VM game: clock"); return false; }
        if (now.tv_sec > deadline.tv_sec ||
            (now.tv_sec == deadline.tv_sec && now.tv_nsec >= deadline.tv_nsec)) {
            /* Drop accumulated delay instead of running catch-up frames. */
            deadline = now;
            return true;
        }
        struct timespec left = {deadline.tv_sec - now.tv_sec, deadline.tv_nsec - now.tv_nsec};
        if (left.tv_nsec < 0) { --left.tv_sec; left.tv_nsec += 1000000000L; }
        if (nanosleep(&left, NULL) < 0 && errno != EINTR) {
            perror("VM game: wait"); return false;
        }
    }
    return true;
}
