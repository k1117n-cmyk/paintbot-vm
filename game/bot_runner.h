#ifndef BOT_RUNNER_H
#define BOT_RUNNER_H
#include <stdint.h>
#include <stdio.h>

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

int64_t now_ns(void);
void print_timeout(FILE *stream, const TimeoutDetail *detail);
int run_bot(const char *vm, const char *program,
            const char *input, size_t input_size, Reply *reply);
#endif
