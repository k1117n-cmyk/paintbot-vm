CC ?= cc
CFLAGS ?= -Wall -Wextra -pedantic

BUILD := build
VM := $(BUILD)/handmade-vm
ASM := $(BUILD)/small-asm
PROGRAMS := $(BUILD)/hello.bin $(BUILD)/echo-char.bin

.PHONY: all clean

all: $(VM) $(ASM) $(PROGRAMS)

$(BUILD):
	mkdir -p $@

$(VM): notes/vm.c notes/game_io.c notes/game_io.h | $(BUILD)
	$(CC) $(CFLAGS) notes/vm.c notes/game_io.c -o $@

$(ASM): tools/small-asm.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD)/%.bin: programs/%.asm $(ASM) | $(BUILD)
	$(ASM) $< $@

clean:
	rm -rf $(BUILD)
