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

enum { TIMEOUT_MS = 100, DIAGNOSTIC_LIMIT = 4096 };
typedef enum { ACCEPTED, TIMED_OUT, INVALID_OUTPUT, VM_ERROR } Outcome;
/* Parent-observed times, relative to launch; -1 means not observed. */
typedef struct {
    int64_t elapsed_ns, fork_ns, exec_eof_ns, input_ns, output_ns, exit_ns;
    int64_t max_gap_ns, cpu_ns;
    size_t sent, output_size;
    int open_outputs, reaped;
} TimeoutDetail;
typedef struct {
    char action;
    Outcome outcome;
    unsigned char diagnostic[DIAGNOSTIC_LIMIT];
    size_t diagnostic_size;
    TimeoutDetail timeout;
} Reply;

static int64_t now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0) return -1;
    return (int64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static int64_t child_cpu_ns(const struct rusage *usage) {
    return ((int64_t)usage->ru_utime.tv_sec + usage->ru_stime.tv_sec) * 1000000000LL
        + ((int64_t)usage->ru_utime.tv_usec + usage->ru_stime.tv_usec) * 1000;
}

static void print_timeout(FILE *stream, const TimeoutDetail *detail) {
    fprintf(stream, "timeout detail (parent observations, us): elapsed=%lld fork=%lld "
            "exec-eof=%lld input-done=%lld first-output=%lld exit=%lld "
            "max-loop-gap=%lld child-cpu=%lld sent=%zu stdout=%zu open-mask=%d reaped=%d\n",
            (long long)(detail->elapsed_ns / 1000), (long long)(detail->fork_ns / 1000),
            (long long)(detail->exec_eof_ns < 0 ? -1 : detail->exec_eof_ns / 1000),
            (long long)(detail->input_ns < 0 ? -1 : detail->input_ns / 1000),
            (long long)(detail->output_ns < 0 ? -1 : detail->output_ns / 1000),
            (long long)(detail->exit_ns < 0 ? -1 : detail->exit_ns / 1000),
            (long long)(detail->max_gap_ns / 1000),
            (long long)(detail->cpu_ns < 0 ? -1 : detail->cpu_ns / 1000),
            detail->sent, detail->output_size, detail->open_outputs, detail->reaped);
}

static void close_fd(int *fd) {
    if (*fd >= 0) close(*fd);
    *fd = -1;
}

/* Close-on-exec status pipe distinguishes host launch failures from VM errors. */
static void child_error(int fd) {
    int error = errno;
    const unsigned char *p = (const unsigned char *)&error;
    size_t sent = 0;
    while (sent < sizeof error) {
        ssize_t n = write(fd, p + sent, sizeof error - sent);
        if (n > 0) sent += (size_t)n;
        else if (n < 0 && errno == EINTR) continue;
        else break;
    }
    _exit(127);
}

static void kill_and_reap(pid_t pid, int reaped) {
    if (!reaped) {
        kill(pid, SIGKILL);
        while (waitpid(pid, NULL, 0) < 0 && errno == EINTR) {}
    }
}

/* input/output/error/exec-status pipes. Only the parent ends are nonblocking. */
static int run_bot(const char *vm, const char *program,
                   const char *input, size_t input_size, Reply *reply) {
    int pipes[4][2];
    int fd[4] = {-1, -1, -1, -1};
    pid_t pid = -1;
    int reaped = 0, status = 0, killed = 0, launch_error = 0;
    unsigned char launch_bytes[sizeof(int)];
    size_t launch_size = 0, sent = 0, output_size = 0;
    unsigned char output[2];
    int64_t start, deadline, previous;
    struct rusage cpu_before, cpu_after;
    int have_cpu;
    int i, j, saved_errno;
    *reply = (Reply){.action = 'X', .outcome = ACCEPTED};
    reply->timeout = (TimeoutDetail){.exec_eof_ns = -1, .input_ns = -1,
        .output_ns = -1, .exit_ns = -1, .cpu_ns = -1};
    for (i = 0; i < 4; ++i) pipes[i][0] = pipes[i][1] = -1;
    for (i = 0; i < 4; ++i) {
        if (pipe(pipes[i]) < 0) goto host_error;
        for (j = 0; j < 2; ++j) {
            if (fcntl(pipes[i][j], F_SETFD, FD_CLOEXEC) < 0) goto host_error;
        }
    }
    /* The host runs one child at a time, so the children CPU delta belongs
     * to this invocation. Sampling is diagnostic only, never a deadline. */
    have_cpu = getrusage(RUSAGE_CHILDREN, &cpu_before) == 0;
    start = now_ns();
    if (start < 0) goto host_error;
    deadline = start + TIMEOUT_MS * 1000000LL;
    pid = fork();
    if (pid < 0) goto host_error;
    if (pid == 0) {
        if (dup2(pipes[0][0], STDIN_FILENO) < 0 ||
            dup2(pipes[1][1], STDOUT_FILENO) < 0 ||
            dup2(pipes[2][1], STDERR_FILENO) < 0) child_error(pipes[3][1]);
        for (i = 0; i < 4; ++i) {
            for (j = 0; j < 2; ++j) {
                if (pipes[i][j] != pipes[3][1]) close(pipes[i][j]);
            }
        }
        execl(vm, vm, "--bot", program, (char *)NULL);
        child_error(pipes[3][1]);
    }
    reply->timeout.fork_ns = now_ns() - start;
    previous = start;
    for (i = 0; i < 4; ++i) {
        int parent_end = i == 0 ? 1 : 0;
        fd[i] = pipes[i][parent_end];
        pipes[i][parent_end] = -1;
        close_fd(&pipes[i][1 - parent_end]);
        int flags = fcntl(fd[i], F_GETFL);
        if (flags < 0 || fcntl(fd[i], F_SETFL, flags | O_NONBLOCK) < 0)
            goto host_error;
    }
    for (;;) {
        int64_t now = now_ns();
        struct pollfd watches[4];
        pid_t waited;
        if (now < 0) goto host_error;
        if (now - previous > reply->timeout.max_gap_ns)
            reply->timeout.max_gap_ns = now - previous;
        previous = now;
        if (now >= deadline) {
            reply->outcome = TIMED_OUT;
            break;
        }
        if (!reaped) {
            waited = waitpid(pid, &status, WNOHANG);
            if (waited == pid) {
                reaped = 1;
                reply->timeout.exit_ns = now_ns() - start;
            }
            else if (waited < 0 && errno != EINTR) goto host_error;
        }
        /* Finish only after exit AND EOF on both output pipes and exec status. */
        if (reaped && fd[1] < 0 && fd[2] < 0 && fd[3] < 0) {
            now = now_ns();
            if (now < 0) goto host_error;
            if (now - previous > reply->timeout.max_gap_ns)
                reply->timeout.max_gap_ns = now - previous;
            if (now >= deadline) reply->outcome = TIMED_OUT;
            break;
        }
        for (i = 0; i < 4; ++i) {
            watches[i] = (struct pollfd){fd[i], i == 0 ? POLLOUT : POLLIN, 0};
        }
        /* A short poll also bounds exit detection when all pipes have closed. */
        int wait_ms = (int)((deadline - now + 999999) / 1000000);
        if (wait_ms > 1) wait_ms = 1;
        if (poll(watches, 4, wait_ms) < 0) {
            if (errno == EINTR) continue;
            goto host_error;
        }
        for (i = 0; i < 4; ++i) {
            if (fd[i] < 0 || watches[i].revents == 0) continue;
            if (watches[i].revents & POLLNVAL) { errno = EBADF; goto host_error; }
            if (i == 0) {
                ssize_t n = write(fd[0], input + sent, input_size - sent);
                if (n > 0) {
                    sent += (size_t)n;
                    if (sent == input_size) {
                        reply->timeout.input_ns = now_ns() - start;
                        close_fd(&fd[0]);
                    }
                } else if (n < 0 && errno == EPIPE) close_fd(&fd[0]);
                else if (n < 0 && errno != EAGAIN && errno != EINTR) goto host_error;
            } else {
                unsigned char buffer[4096];
                /* Read no more than the third byte of stdout before stopping. */
                size_t capacity = i == 1 ? 3 - output_size : sizeof buffer;
                ssize_t n = read(fd[i], buffer, capacity);
                if (n == 0) {
                    if (i == 3) reply->timeout.exec_eof_ns = now_ns() - start;
                    close_fd(&fd[i]);
                }
                else if (n < 0) {
                    if (errno != EAGAIN && errno != EINTR) goto host_error;
                } else if (i == 1) {
                    if (reply->timeout.output_ns < 0)
                        reply->timeout.output_ns = now_ns() - start;
                    size_t keep = (size_t)n;
                    if (keep > 2 - output_size) keep = 2 - output_size;
                    memcpy(output + output_size, buffer, keep);
                    if ((size_t)n > keep) {
                        reply->outcome = INVALID_OUTPUT;
                        if (!reaped && !killed) { kill(pid, SIGKILL); killed = 1; }
                        close_fd(&fd[1]);
                        close_fd(&fd[0]);
                    }
                    output_size += keep;
                } else if (i == 2) {
                    size_t keep = (size_t)n;
                    if (keep > DIAGNOSTIC_LIMIT - reply->diagnostic_size)
                        keep = DIAGNOSTIC_LIMIT - reply->diagnostic_size;
                    memcpy(reply->diagnostic + reply->diagnostic_size, buffer, keep);
                    reply->diagnostic_size += keep;
                } else {
                    size_t keep = (size_t)n;
                    if (keep > sizeof(int) - launch_size) { errno = EIO; goto host_error; }
                    memcpy(launch_bytes + launch_size, buffer, keep);
                    launch_size += keep;
                    if (launch_size == sizeof(int)) {
                        memcpy(&launch_error, launch_bytes, sizeof(int));
                        errno = launch_error;
                        goto host_error;
                    }
                }
            }
        }
    }
    /* Snapshot BEFORE kill/reap: cleanup must not disguise the stalled phase. */
    if (reply->outcome == TIMED_OUT) {
        reply->timeout.elapsed_ns = now_ns() - start;
        reply->timeout.sent = sent;
        reply->timeout.output_size = output_size;
        reply->timeout.open_outputs = (fd[1] >= 0 ? 1 : 0) |
            (fd[2] >= 0 ? 2 : 0) | (fd[3] >= 0 ? 4 : 0);
        reply->timeout.reaped = reaped;
    }
    /* Check launch status even when the deadline or output limit caused stop. */
    kill_and_reap(pid, reaped);
    if (reply->outcome == TIMED_OUT && have_cpu &&
        getrusage(RUSAGE_CHILDREN, &cpu_after) == 0)
        reply->timeout.cpu_ns = child_cpu_ns(&cpu_after) - child_cpu_ns(&cpu_before);
    if (fd[3] >= 0 && launch_size < sizeof(int)) {
        ssize_t n = read(fd[3], launch_bytes + launch_size, sizeof(int) - launch_size);
        if (n > 0) launch_size += (size_t)n;
    }
    if (launch_size) {
        if (launch_size == sizeof(int)) memcpy(&launch_error, launch_bytes, sizeof(int));
        errno = launch_error ? launch_error : EIO;
        pid = -1; /* already reaped */
        goto host_error;
    }
    for (i = 0; i < 4; ++i) close_fd(&fd[i]);
    if (reply->outcome == ACCEPTED) {
        if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) reply->outcome = VM_ERROR;
        else if (output_size != 2 || output[1] != '\n' ||
                 strchr("WASDX", output[0]) == NULL || output[0] == 0)
            reply->outcome = INVALID_OUTPUT;
        else reply->action = (char)output[0];
    }
    return 0;

host_error:
    saved_errno = errno;
    if (pid > 0) kill_and_reap(pid, reaped);
    for (i = 0; i < 4; ++i) {
        close_fd(&fd[i]);
        close_fd(&pipes[i][0]);
        close_fd(&pipes[i][1]);
    }
    errno = saved_errno;
    perror("host: cannot run VM");
    return -1;
}

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
