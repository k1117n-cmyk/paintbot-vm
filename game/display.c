#include "display.h"

void display_frame(FILE *out, const Game *game, const int counts[GAME_BOTS][4]) {
    static const char *colors[] = {"\033[0;37;40m", "\033[0;97;44m", "\033[0;30;43m",
                                  "\033[0;30;42m", "\033[0;97;41m"};
    int scores[GAME_BOTS];
    game_scores(game, scores);
    fputs("\033[H", out);
    fprintf(out, "Paint battle | Turn %03d/%d | Left %03d\033[K\n",
            game->turns_played, GAME_TURNS, GAME_TURNS - game->turns_played);
    for (int i = 0; i < game->bot_count; ++i)
        fprintf(out, "%s ID %d %3d \033[0m%s", colors[i + 1], i + 1,
                scores[i], i + 1 == game->bot_count ? "\033[K\n" : "  ");
    for (int y = 0; y < GAME_SIZE; ++y) {
        for (int x = 0; x < GAME_SIZE; ++x) {
            char cell[3] = "  ";
            int occupants = 0;
            for (int i = 0; i < game->bot_count; ++i) {
                if (game->positions[i].x == x && game->positions[i].y == y) {
                    if (occupants < 2) cell[occupants] = (char)('1' + i);
                    ++occupants;
                }
            }
            if (occupants > 2) { cell[0] = '*'; cell[1] = ' '; }
            fputs(colors[game->board[y][x]], out);
            fputs(cell, out);
        }
        fputs("\033[0m\033[K\n", out);
    }
    if (game->bot_count == 2)
        fputs("Blue: ID 1 | Yellow: ID 2 | 12: overlap\033[K\n", out);
    else
        fputs("1:B 2:Y 3:G 4:R | *:3+ | A:ok T:timeout I:invalid E:VM-error\033[K\n", out);
    GameResult result = game_result(game);
    if (result == GAME_ONGOING) fputs("Match in progress\033[K\n", out);
    else if (result == GAME_DRAW) fputs("Result: draw\033[K\n", out);
    else fprintf(out, "Result: ID %d wins\033[K\n", result);
    for (int i = 0; i < game->bot_count; ++i) {
        if (game->bot_count > 2) {
            fprintf(out, "ID %d: A=%d T=%d I=%d E=%d%s", i + 1,
                    counts[i][0], counts[i][1], counts[i][2], counts[i][3],
                    i % 2 == 1 || i + 1 == game->bot_count ? "\033[K\n" : " | ");
            continue;
        }
        fprintf(out, "ID %d: accepted=%d timeout=%d invalid=%d VM-error=%d\033[K\n",
                i + 1, counts[i][0], counts[i][1], counts[i][2], counts[i][3]);
    }
    fflush(out);
}
