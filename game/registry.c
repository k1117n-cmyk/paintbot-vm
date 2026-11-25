#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

enum { NAME_LIMIT = 32, PROGRAM_LIMIT = 1024 * 1024 };

static int valid_name(const char *name) {
    size_t n = strlen(name);
    if (n == 0 || n > NAME_LIMIT || name[0] == '-') return 0;
    for (size_t i = 0; i < n; ++i) {
        unsigned char c = (unsigned char)name[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '-' || c == '_')) return 0;
    }
    return 1;
}

static void bot_path(char path[64], const char *name) {
    snprintf(path, 64, "registered/%s.bin", name);
}

/* O_NONBLOCK prevents a FIFO from blocking before fstat can reject it. */
static int open_program(const char *path) {
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    struct stat st;
    if (fd < 0) { perror(path); return -1; }
    if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode) ||
        st.st_size < 1 || st.st_size > PROGRAM_LIMIT) {
        fprintf(stderr, "paint-bots: %s: expected regular file, 1..%d bytes\n",
                path, PROGRAM_LIMIT);
        close(fd);
        return -1;
    }
    return fd;
}

static int ensure_directory(const char *path) {
    struct stat st;
    if (mkdir(path, 0777) < 0 && errno != EEXIST) { perror(path); return -1; }
    if (lstat(path, &st) < 0 || !S_ISDIR(st.st_mode)) {
        fprintf(stderr, "paint-bots: %s: expected directory (no symlink)\n", path);
        return -1;
    }
    return 0;
}

static int register_bot(const char *name, const char *source) {
    char destination[64], temporary[] = "registered/.pending-XXXXXX";
    unsigned char buffer[8192];
    size_t total = 0;
    int input = -1, output = -1, result = 1;
    if (!valid_name(name)) { fputs("paint-bots: invalid name (1..32 ASCII letters/digits/-/_, no leading '-')\n", stderr); return 1; }
    input = open_program(source);
    if (input < 0) return 1;
    if (ensure_directory("incoming") < 0 || ensure_directory("registered") < 0) goto done;
    output = mkstemp(temporary);
    if (output < 0) { perror("paint-bots: temporary file"); goto done; }
    for (;;) {
        ssize_t n = read(input, buffer, sizeof buffer);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { perror(source); goto cleanup; }
        if (n == 0) break;
        total += (size_t)n;
        if (total > PROGRAM_LIMIT) { fputs("paint-bots: source grew beyond limit\n", stderr); goto cleanup; }
        for (ssize_t offset = 0; offset < n;) {
            ssize_t written = write(output, buffer + offset, (size_t)(n - offset));
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) { perror("paint-bots: write"); goto cleanup; }
            offset += written;
        }
    }
    if (total == 0) { fputs("paint-bots: source became empty\n", stderr); goto cleanup; }
    if (close(output) < 0) { output = -1; perror("paint-bots: close"); goto cleanup; }
    output = -1;
    bot_path(destination, name);
    /* A hard link publishes the complete copy and atomically refuses overwrite. */
    if (link(temporary, destination) < 0) { perror(destination); goto cleanup; }
    printf("Registered %s (%zu bytes)\n", name, total);
    result = 0;
cleanup:
    if (output >= 0) close(output);
    if (unlink(temporary) < 0) { perror("paint-bots: remove temporary file"); result = 1; }
done:
    close(input);
    return result;
}

static int compare_names(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

typedef struct { char **names; size_t count; } BotNames;

static void free_names(BotNames *bots) {
    for (size_t i = 0; i < bots->count; ++i) free(bots->names[i]);
    free(bots->names);
    bots->names = NULL;
    bots->count = 0;
}

static int collect_bots(BotNames *bots) {
    DIR *directory = opendir("registered");
    struct dirent *entry;
    char **names = NULL;
    size_t count = 0;
    int result = 1;
    if (!directory) {
        if (errno == ENOENT) return 0;
        perror("registered"); return 1;
    }
    for (;;) {
        char name[NAME_LIMIT + 1], path[64];
        struct stat st;
        size_t length;
        errno = 0;
        entry = readdir(directory);
        if (!entry) {
            if (errno) { perror("paint-bots: readdir"); goto done; }
            break;
        }
        length = strlen(entry->d_name);
        if (length <= 4 || length > NAME_LIMIT + 4 || strcmp(entry->d_name + length - 4, ".bin")) continue;
        memcpy(name, entry->d_name, length - 4);
        name[length - 4] = '\0';
        if (!valid_name(name)) continue;
        bot_path(path, name);
        if (lstat(path, &st) < 0) { perror(path); goto done; }
        if (!S_ISREG(st.st_mode) || st.st_size < 1 || st.st_size > PROGRAM_LIMIT) continue;
        char **grown = realloc(names, (count + 1) * sizeof *names);
        if (!grown) { perror("paint-bots: allocation"); goto done; }
        names = grown;
        names[count] = strdup(name);
        if (!names[count]) { perror("paint-bots: allocation"); goto done; }
        ++count;
    }
    if (count > 1) qsort(names, count, sizeof *names, compare_names);
    bots->names = names;
    bots->count = count;
    result = 0;
done:
    if (result) {
        for (size_t i = 0; i < count; ++i) free(names[i]);
        free(names);
    }
    closedir(directory);
    return result;
}

static int list_bots(void) {
    BotNames bots = {NULL, 0};
    if (collect_bots(&bots)) return 1;
    int result = 0;
    for (size_t i = 0; i < bots.count; ++i) {
        if (puts(bots.names[i]) == EOF) { perror("paint-bots: stdout"); result = 1; break; }
    }
    if (fflush(stdout)) result = 1;
    free_names(&bots);
    return result;
}

static int match(int argc, char **argv) {
    char paths[4][64];
    char *args[9] = {"game/build/paint-host"};
    int first = 2, next = 1;
    if (argc > first && (!strcmp(argv[first], "--watch") || !strcmp(argv[first], "--no-watch")))
        args[next++] = argv[first++];
    if (argc > first && argv[first][0] == '-') {
        fprintf(stderr, "paint-bots: unknown option: %s\n", argv[first]);
        return 1;
    }
    int count = argc - first;
    if (count < 2 || count > 4) { fputs("paint-bots: match requires 2..4 distinct names\n", stderr); return 1; }
    args[next++] = "vm/build/handmade-vm";
    for (int i = 0; i < count; ++i) {
        if (!valid_name(argv[first + i])) { fputs("paint-bots: invalid participant name\n", stderr); return 1; }
        for (int j = 0; j < i; ++j) {
            if (!strcmp(argv[first + i], argv[first + j])) {
                fputs("paint-bots: duplicate participant name\n", stderr); return 1;
            }
        }
        bot_path(paths[i], argv[first + i]);
        int fd = open_program(paths[i]);
        if (fd < 0) return 1;
        close(fd);
        args[next++] = paths[i];
    }
    args[next] = NULL;
    execv(args[0], args);
    perror("paint-bots: cannot run host");
    return 1;
}


/* Returns 1 for a complete line, 0 for EOF and -1 after draining a long line. */
static int menu_line(char line[256]) {
    if (!fgets(line, 256, stdin)) return 0;
    if (!strchr(line, '\n') && !feof(stdin)) {
        int c;
        while ((c = getchar()) != '\n' && c != EOF) {}
        return -1;
    }
    size_t length = strlen(line);
    while (length && isspace((unsigned char)line[length - 1])) line[--length] = '\0';
    return 1;
}

static int select_bots(char *line, size_t available, size_t selected[4]) {
    int count = 0;
    char *cursor = line;
    for (;;) {
        while (isspace((unsigned char)*cursor)) ++cursor;
        if (!*cursor) return count >= 2 ? count : -1;
        if (count == 4 || !isdigit((unsigned char)*cursor)) return -1;
        char *end;
        errno = 0;
        long number = strtol(cursor, &end, 10);
        if (errno || number < 1 || (unsigned long)number > available ||
            (*end && !isspace((unsigned char)*end))) return -1;
        for (int i = 0; i < count; ++i)
            if (selected[i] == (size_t)number - 1) return -1;
        selected[count++] = (size_t)number - 1;
        cursor = end;
    }
}

static int menu_match(const BotNames *bots, const size_t selected[4], int count) {
    struct sigaction ignore, previous;
    memset(&ignore, 0, sizeof ignore);
    ignore.sa_handler = SIG_IGN;
    sigemptyset(&ignore.sa_mask);
    if (sigaction(SIGINT, &ignore, &previous) < 0) { perror("paint-bots: signal"); return 1; }
    fflush(stdout);
    pid_t child = fork();
    if (child == 0) {
        if (sigaction(SIGINT, &previous, NULL) < 0) _exit(1);
        char *args[8] = {"game/build/paint-bots", "match", "--watch"};
        for (int i = 0; i < count; ++i) args[i + 3] = bots->names[selected[i]];
        args[count + 3] = NULL;
        _exit(match(count + 3, args));
    }
    int status = 0, result = 1;
    if (child < 0) perror("paint-bots: fork");
    else {
        pid_t waited;
        do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
        if (waited < 0) perror("paint-bots: wait");
        else if (WIFEXITED(status)) result = WEXITSTATUS(status);
        else if (WIFSIGNALED(status)) result = 128 + WTERMSIG(status);
    }
    if (sigaction(SIGINT, &previous, NULL) < 0) { perror("paint-bots: signal"); return 1; }
    return result;
}

static int menu(void) {
    const char *term = getenv("TERM");
    int ansi = isatty(STDOUT_FILENO) && term && strcmp(term, "dumb");
    size_t page = 0;
    char line[256], notice[80] = "";
    for (;;) {
        BotNames bots = {NULL, 0};
        if (collect_bots(&bots)) return 1;
        size_t pages = bots.count ? (bots.count + 7) / 8 : 1;
        if (page >= pages) page = pages - 1;
        if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
        printf("Paint battle - select bots\nRegistered: %zu | Page %zu/%zu\n\n",
               bots.count, page + 1, pages);
        if (!bots.count) puts("No bots registered. Register bots from another computer.");
        for (size_t i = page * 8; i < bots.count && i < page * 8 + 8; ++i)
            printf("%zu: %s\n", i + 1, bots.names[i]);
        puts("\nEnter 2-4 numbers in ID order (example: 1 3)");
        puts("n: next | p: previous | r: refresh | q: quit");
        if (*notice) puts(notice);
        fputs("Bots> ", stdout);
        fflush(stdout);
        int read_result = menu_line(line);
        if (!read_result) { free_names(&bots); return ferror(stdin) ? 1 : 0; }
        if (read_result < 0) {
            strcpy(notice, "Input too long. Choose 2-4 different bot numbers.");
            free_names(&bots); continue;
        }
        char *command = line;
        while (isspace((unsigned char)*command)) ++command;
        notice[0] = '\0';
        if (!strcmp(command, "q")) { free_names(&bots); return 0; }
        if (!strcmp(command, "n") || !strcmp(command, "p") || !strcmp(command, "r")) {
            if (*command == 'n' && page + 1 < pages) ++page;
            if (*command == 'p' && page) --page;
            free_names(&bots); continue;
        }
        size_t selected[4];
        int count = select_bots(command, bots.count, selected);
        if (count < 0) {
            strcpy(notice, "Choose 2-4 different bot numbers from the list.");
            free_names(&bots); continue;
        }
        if (ansi) fputs("\033[0m\033[2J\033[H", stdout);
        puts("Selected bots:");
        for (int i = 0; i < count; ++i) printf("ID %d: %s\n", i + 1, bots.names[selected[i]]);
        fputs("Start match? [y/N]> ", stdout);
        fflush(stdout);
        read_result = menu_line(line);
        if (!read_result) { free_names(&bots); return ferror(stdin) ? 1 : 0; }
        if (read_result < 0 || (strcmp(line, "y") && strcmp(line, "Y"))) {
            strcpy(notice, "Match cancelled.");
            free_names(&bots); continue;
        }
        int result = menu_match(&bots, selected, count);
        free_names(&bots);
        if (result) printf("\nMatch stopped (status %d).\n", result);
        fputs("\nPress Enter to return to selection> ", stdout);
        fflush(stdout);
        read_result = menu_line(line);
        if (!read_result) return ferror(stdin) ? 1 : 0;
    }
}

int main(int argc, char **argv) {
    if (argc == 4 && !strcmp(argv[1], "register")) return register_bot(argv[2], argv[3]);
    if (argc == 2 && !strcmp(argv[1], "list")) return list_bots();
    if (argc == 2 && !strcmp(argv[1], "menu")) return menu();
    if (argc >= 2 && !strcmp(argv[1], "match")) return match(argc, argv);
    fputs("usage (from project root):\n"
          "  game/build/paint-bots register NAME FILE\n"
          "  game/build/paint-bots list\n"
          "  game/build/paint-bots menu\n"
          "  game/build/paint-bots match [--watch|--no-watch] NAME NAME [NAME [NAME]]\n", stderr);
    return 1;
}
