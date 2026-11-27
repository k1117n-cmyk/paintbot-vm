#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* Child menus share the terminal and process group with this launcher. */
static int launch(char *const args[]) {
    struct sigaction ignore, previous;
    memset(&ignore, 0, sizeof ignore);
    ignore.sa_handler = SIG_IGN;
    sigemptyset(&ignore.sa_mask);
    if (sigaction(SIGINT, &ignore, &previous) < 0) {
        perror("game-console: signal");
        return -1;
    }
    fflush(stdout);
    pid_t child = fork();
    if (child == 0) {
        if (sigaction(SIGINT, &previous, NULL) < 0) _exit(126);
        execv(args[0], args);
        perror(args[0]);
        _exit(127);
    }
    int result = -1, status;
    if (child < 0) perror("game-console: fork");
    else {
        pid_t waited;
        do { waited = waitpid(child, &status, 0); }
        while (waited < 0 && errno == EINTR);
        if (waited < 0) perror("game-console: wait");
        else if (WIFEXITED(status)) result = WEXITSTATUS(status);
        else if (WIFSIGNALED(status)) result = 128 + WTERMSIG(status);
    }
    if (sigaction(SIGINT, &previous, NULL) < 0) {
        perror("game-console: signal");
        return -1;
    }
    return result;
}

/* Drain long lines so their tail cannot become a new command. */
static int read_command(char line[128]) {
    if (!fgets(line, 128, stdin)) return 0;
    if (!strchr(line, '\n') && !feof(stdin)) {
        int c;
        do { c = getchar(); } while (c != '\n' && c != EOF);
        return -1;
    }
    size_t length = strlen(line);
    while (length && isspace((unsigned char)line[length - 1]))
        line[--length] = '\0';
    return 1;
}

static int treasure_selection(const char *line, int selected[4]) {
    int count = 0;
    while (*line) {
        while (isspace((unsigned char)*line)) ++line;
        if (!*line) break;
        if (count == 4 || *line < '1' || *line > '4') return -1;
        selected[count++] = *line++ - '1';
        if (*line && !isspace((unsigned char)*line)) return -1;
    }
    return count >= 2 ? count : -1;
}

/* Built-in treasure bots have their own paths; no paintbot registration is used.
 * Return 1 for q (back to games), 0 for EOF or a read error. */
static int treasure_menu(int ansi) {
    static const char *names[] = {"seeker-h", "seeker-v", "right", "wait"};
    static char *paths[] = {"treasure/build/seeker-h.bin", "treasure/build/seeker-v.bin",
                            "treasure/build/right.bin", "treasure/build/wait.bin"};
    char line[128], notice[100] = "";
    for (;;) {
        if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
        puts("Treasure - select bots\n");
        for (int i = 0; i < 4; ++i) printf("%d: %s\n", i + 1, names[i]);
        puts("\nEnter 2-4 numbers in ID order (example: 1 2 1 2)");
        puts("Repeated numbers allowed | q: back to games");
        if (*notice) puts(notice);
        fputs("Treasure bots> ", stdout);
        fflush(stdout);
        int read_result = read_command(line);
        if (!read_result) return 0;
        if (read_result < 0) {
            strcpy(notice, "Input too long. Choose 2-4 treasure bot numbers.");
            continue;
        }
        char *command = line;
        while (isspace((unsigned char)*command)) ++command;
        if (!strcmp(command, "q")) return 1;
        int selected[4], count = treasure_selection(command, selected);
        if (count < 0) {
            strcpy(notice, "Choose 2-4 numbers from 1 to 4.");
            continue;
        }
        if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
        puts("Selected treasure bots:");
        for (int i = 0; i < count; ++i) printf("ID %d: %s\n", i + 1, names[selected[i]]);
        fputs("Start treasure match? [y/N]> ", stdout);
        fflush(stdout);
        read_result = read_command(line);
        if (!read_result) return 0;
        if (read_result < 0 || (strcmp(line, "y") && strcmp(line, "Y"))) {
            strcpy(notice, "Match cancelled.");
            continue;
        }
        int available = 1;
        for (int i = 0; i < count; ++i) {
            if (access(paths[selected[i]], R_OK) < 0) {
                snprintf(notice, sizeof notice, "Bot missing: %s. Run make -C treasure.", names[selected[i]]);
                available = 0;
                break;
            }
        }
        if (!available) continue;
        char *args[9] = {"treasure/build/treasure-host", "--watch", "vm/build/handmade-vm"};
        for (int i = 0; i < count; ++i) args[i + 3] = paths[selected[i]];
        args[count + 3] = NULL;
        int result = launch(args);
        if (result) printf("\nTreasure stopped (status %d).\n", result);
        fputs("\nPress Enter to return to treasure selection> ", stdout);
        fflush(stdout);
        if (!read_command(line)) return 0;
        notice[0] = '\0';
    }
}

int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) {
        fputs("usage (from project root): console/build/game-console\n", stderr);
        return 1;
    }
    /* Do not read ahead into input intended for the child menu. */
    if (setvbuf(stdin, NULL, _IONBF, 0)) return 1;
    const char *term = getenv("TERM");
    int ansi = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb");
    char line[128], notice[100] = "";
    for (;;) {
        if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
        puts("VM Game Console\n\n1: Paintbot\n2: Treasure\n3: Maze\n\nq: Quit console");
        puts("Press q in a game or bot menu to return here.");
        if (*notice) puts(notice);
        fputs("Games> ", stdout);
        fflush(stdout);
        int read_result = read_command(line);
        if (!read_result) return ferror(stdin) ? 1 : 0;
        if (read_result < 0) {
            strcpy(notice, "Input too long. Choose 1, 2, 3 or q.");
            continue;
        }
        char *command = line;
        while (isspace((unsigned char)*command)) ++command;
        if (!strcmp(command, "q")) return 0;
        if (!strcmp(command, "3")) {
            char *args[] = {"maze/build/maze", NULL};
            int result = launch(args);
            if (result)
                snprintf(notice, sizeof notice, "Maze stopped (status %d). Check build and diagnostics.", result);
            else strcpy(notice, "Returned from Maze.");
            continue;
        }
        if (!strcmp(command, "2")) {
            if (!treasure_menu(ansi)) return ferror(stdin) ? 1 : 0;
            strcpy(notice, "Returned from Treasure.");
            continue;
        }
        if (strcmp(command, "1")) {
            strcpy(notice, "Choose 1, 2, 3 or q.");
            continue;
        }
        char *args[] = {"game/build/paint-bots", "menu", NULL};
        int result = launch(args);
        if (result)
            snprintf(notice, sizeof notice,
                     "Paintbot stopped (status %d). Check build and diagnostics.", result);
        else strcpy(notice, "Returned from Paintbot.");
    }
}
