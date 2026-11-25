#ifndef PAINT_DISPLAY_H
#define PAINT_DISPLAY_H

#include "game.h"
#include <stdio.h>

/* ANSI terminal, 64 columns by 24 rows. Does not change terminal modes. */
void display_frame(FILE *out, const Game *game, const int counts[GAME_BOTS][4]);

#endif
