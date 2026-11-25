/* Exercise the actual supervisor with a child that controls pipe/exit behavior. */
#define main paint_host_main
#include "host.c"
#undef main

#include <stdlib.h>

#define CHECK(c) do { if (!(c)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); exit(1); \
} } while (0)

static void pause_child(void) {
    struct timespec duration = {1, 0};
    nanosleep(&duration, NULL);
}

static int fixture(const char *mode) {
    if (strcmp(mode, "delayed") == 0) pause_child();
    if (strcmp(mode, "input") == 0) {
        char input[4];
        size_t n = fread(input, 1, sizeof input, stdin);
        if (n != 3 || memcmp(input, "abc", 3) != 0 || !feof(stdin)) return 1;
    }
    if (strcmp(mode, "stderr") == 0) {
        char noise[8192];
        memset(noise, 'E', sizeof noise);
        if (write(STDERR_FILENO, noise, sizeof noise) != sizeof noise) return 1;
    }
    if (strcmp(mode, "empty") == 0) return 0;
    if (strcmp(mode, "short") == 0) { write(1, "D", 1); return 0; }
    if (strcmp(mode, "lower") == 0) { write(1, "d\n", 2); return 0; }
    if (strcmp(mode, "nul") == 0) { write(1, "\0\n", 2); return 0; }
    if (strcmp(mode, "cr") == 0) { write(1, "D\r\n", 3); return 0; }
    if (strcmp(mode, "excess") == 0) {
        write(1, "D\nX", 3);
        pause_child(); /* Must be killed on the third byte, before timeout. */
        return 0;
    }
    write(1, "D\n", 2);
    if (strcmp(mode, "late") == 0) pause_child();
    if (strcmp(mode, "closed") == 0) {
        close(0); close(1); close(2);
        pause_child(); /* EOF alone is insufficient for success. */
    }
    return strcmp(mode, "error") == 0 ? 1 : 0;
}

static void check_reply(const char *vm, const char *mode, Outcome outcome) {
    Reply reply;
    int status;
    int run_result = run_bot(vm, mode, "abc", 3, &reply);
    if (outcome == TIMED_OUT || reply.outcome == TIMED_OUT) {
        printf("timeout observation %s: actual outcome=%d\n", mode, reply.outcome);
        print_timeout(stdout, &reply.timeout);
        fflush(stdout); /* Preserve observations even if the next CHECK exits. */
    }
    CHECK(run_result == 0);
    CHECK(reply.outcome == outcome);
    CHECK(reply.action == (outcome == ACCEPTED ? 'D' : 'X'));
    if (outcome == TIMED_OUT) {
        CHECK(reply.timeout.cpu_ns >= -1);
        CHECK(reply.timeout.sent <= 3 && reply.timeout.output_size <= 2);
        /* A delayed child may time out before exec or output. Check snapshot
         * consistency, not whether it reached a phase within 100ms. */
        CHECK((reply.timeout.input_ns >= 0) == (reply.timeout.sent == 3));
        CHECK((reply.timeout.output_ns >= 0) == (reply.timeout.output_size > 0));
        CHECK((reply.timeout.exec_eof_ns >= 0) == !(reply.timeout.open_outputs & 4));
        CHECK((reply.timeout.exit_ns >= 0) == !!reply.timeout.reaped);
    }
    CHECK(waitpid(-1, &status, WNOHANG) == -1 && errno == ECHILD);
    if (strcmp(mode, "stderr") == 0) {
        CHECK(reply.diagnostic_size == DIAGNOSTIC_LIMIT);
        for (size_t i = 0; i < reply.diagnostic_size; ++i) CHECK(reply.diagnostic[i] == 'E');
    }
    printf("PASS supervisor %s\n", mode);
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "--bot") == 0) return fixture(argv[2]);
    const struct { const char *mode; Outcome outcome; } cases[] = {
        {"input", ACCEPTED}, {"stderr", ACCEPTED}, {"empty", INVALID_OUTPUT},
        {"short", INVALID_OUTPUT}, {"lower", INVALID_OUTPUT}, {"nul", INVALID_OUTPUT},
        {"cr", INVALID_OUTPUT}, {"excess", INVALID_OUTPUT}, {"error", VM_ERROR},
        {"late", TIMED_OUT}, {"closed", TIMED_OUT}, {"delayed", TIMED_OUT}
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i)
        check_reply(argv[0], cases[i].mode, cases[i].outcome);
    Reply reply;
    CHECK(run_bot("/nonexistent-paintbot-vm", "input", "abc", 3, &reply) == -1);
    puts("PASS supervisor exec failure aborts");
    Game game;
    char input[512], other[512], expected[512];
    game_init(&game);
    size_t n = turn_input(&game, 0, input);
    size_t offset = 0;
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x)
            expected[offset++] = y == 0 && x == 0 ? '1' : y == 15 && x == 15 ? '2' : '.';
        expected[offset++] = '\n';
    }
    memcpy(expected + offset, "1 200 2\n1 00 00\n2 15 15\n", 24);
    CHECK(n == 296 && memcmp(input, expected, n) == 0);
    CHECK(turn_input(&game, 1, other) == n);
    CHECK(memcmp(input, other, 272) == 0 && other[272] == '2');
    CHECK(memcmp(input + 273, other + 273, n - 273) == 0);
    game.turns_played = 199;
    CHECK(turn_input(&game, 0, input) == n);
    CHECK(memcmp(input + 272, "1 001 2\n", 8) == 0);
    puts("PASS protocol snapshot, IDs, coordinates, 200 and 001");
    for (int n_bots = 3; n_bots <= 4; ++n_bots) {
        CHECK(game_init_count(&game, n_bots));
        for (int turn = 0; turn < GAME_TURNS; ++turn) {
            game.turns_played = turn;
            size_t size = 0;
            for (int y = 0; y < 16; ++y) {
                for (int x = 0; x < 16; ++x)
                    expected[size++] = y == 0 && x == 0 ? '1' :
                        y == 15 && x == 15 ? '2' :
                        y == 0 && x == 15 ? '3' :
                        n_bots == 4 && y == 15 && x == 0 ? '4' : '.';
                expected[size++] = '\n';
            }
            for (int bot = 0; bot < n_bots; ++bot) {
                const char *positions = n_bots == 3 ?
                    "1 00 00\n2 15 15\n3 15 00\n" :
                    "1 00 00\n2 15 15\n3 15 00\n4 00 15\n";
                snprintf(expected + size, sizeof expected - size,
                         "%d %03d %d\n%s", bot + 1, 200 - turn, n_bots, positions);
                n = turn_input(&game, bot, input);
                CHECK(n == (size_t)(280 + n_bots * 8));
                CHECK(n == strlen(expected) && memcmp(input, expected, n) == 0);
            }
        }
        printf("PASS protocol %d bots: all 200 turns, all IDs, exact bytes, same snapshot, colors/positions\n", n_bots);
    }
    puts("PASS 16 host checks, 0 failures");
    return 0;
}
