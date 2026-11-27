#ifndef VM_GAME_IO_H
#define VM_GAME_IO_H

#include <stdbool.h>
#include <stdint.h>

#define VM_FRAME_WIDTH 32
#define VM_FRAME_HEIGHT 18
#define VM_FRAME_SIZE (VM_FRAME_WIDTH * VM_FRAME_HEIGHT)
#define VM_KEY_EOF 256u

bool vm_game_open(void);
bool vm_game_close(void);
int vm_game_signal(void);
bool vm_game_frame(const uint8_t *cells);
bool vm_game_key(uint32_t *key);
bool vm_game_wait(uint32_t milliseconds);

#endif
