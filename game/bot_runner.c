#define _POSIX_C_SOURCE 200809L
#include "bot_runner.h"
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

int64_t now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0) return -1;
    return (int64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static int64_t child_cpu_ns(const struct rusage *usage) {
    return ((int64_t)usage->ru_utime.tv_sec + usage->ru_stime.tv_sec) * 1000000000LL
        + ((int64_t)usage->ru_utime.tv_usec + usage->ru_stime.tv_usec) * 1000;
}

void print_timeout(FILE *stream, const TimeoutDetail *detail) {
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
int run_bot(const char *vm, const char *program,
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
