#include "display.h"
#include <stdlib.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); exit(1); \
} } while (0)

static void render(const Game *game, char *buffer, size_t capacity) {
    const int counts[GAME_BOTS][4] = {{198, 1, 1, 0}, {200, 0, 0, 0}};
    FILE *out = tmpfile();
    CHECK(out != NULL);
    display_frame(out, game, counts);
    CHECK(!ferror(out));
    rewind(out);
    size_t size = fread(buffer, 1, capacity - 1, out);
    CHECK(size < capacity - 1 && feof(out));
    buffer[size] = '\0';
    CHECK(fclose(out) == 0);
}

int main(void) {
    Game game, before;
    char buffer[16384];
    game_init(&game);
    before = game;
    render(&game, buffer, sizeof buffer);
    CHECK(memcmp(&before, &game, sizeof game) == 0);
    CHECK(strstr(buffer, "Turn 000/200 | Left 200"));
    CHECK(strstr(buffer, "\033[0;97;44m1 "));
    CHECK(strstr(buffer, "\033[0;30;43m2 "));
    CHECK(strstr(buffer, "\033[0;37;40m  "));
    CHECK(strstr(buffer, "Match in progress"));
    puts("PASS display initial positions, colors, score and unchanged state");
    game.positions[1] = game.positions[0];
    for (int color = 0; color <= 2; ++color) {
        const char *expected[] = {"\033[0;37;40m12", "\033[0;97;44m12", "\033[0;30;43m12"};
        game.board[0][0] = (unsigned char)color;
        render(&game, buffer, sizeof buffer);
        CHECK(strstr(buffer, expected[color]));
    }
    puts("PASS display overlap preserves all three underlying colors");
    game_init(&game);
    game.turns_played = GAME_TURNS;
    render(&game, buffer, sizeof buffer);
    CHECK(strstr(buffer, "Turn 200/200 | Left 000"));
    CHECK(strstr(buffer, "Result: draw"));
    CHECK(strstr(buffer, "ID 1: accepted=198 timeout=1 invalid=1 VM-error=0"));
    game.board[0][1] = 1;
    render(&game, buffer, sizeof buffer);
    CHECK(strstr(buffer, "Result: ID 1 wins"));
    game.board[0][1] = 2;
    render(&game, buffer, sizeof buffer);
    CHECK(strstr(buffer, "Result: ID 2 wins"));
    puts("PASS display remaining zero, draw, both winners and error totals");
    for (int n = 3; n <= 4; ++n) {
        CHECK(game_init_count(&game, n));
        render(&game, buffer, sizeof buffer);
        CHECK(strstr(buffer, "\033[0;30;42m3 "));
        if (n == 4) CHECK(strstr(buffer, "\033[0;97;41m4 "));
        for (int i = 0; i < n; ++i) game.positions[i] = (GamePosition){7, 7};
        for (int color = 0; color <= 4; ++color) {
            game.board[7][7] = (unsigned char)color;
            render(&game, buffer, sizeof buffer);
            const char *expected[] = {"\033[0;37;40m* ", "\033[0;97;44m* ",
                "\033[0;30;43m* ", "\033[0;30;42m* ", "\033[0;97;41m* "};
            CHECK(strstr(buffer, expected[color]));
        }
        game_init_count(&game, n);
        game.positions[2] = game.positions[1];
        render(&game, buffer, sizeof buffer);
        CHECK(strstr(buffer, "\033[0;30;43m23"));
        game.turns_played = GAME_TURNS;
        for (int winner = 2; winner < n; ++winner) {
            game.board[7][7] = (unsigned char)(winner + 1);
            render(&game, buffer, sizeof buffer);
            CHECK(strstr(buffer, winner == 2 ? "Result: ID 3 wins" : "Result: ID 4 wins"));
        }
        printf("PASS display %d bots: colors, overlaps, winners, compact counts\n", n);
    }
    puts("PASS 5 display groups, 0 failures");
    return 0;
}
