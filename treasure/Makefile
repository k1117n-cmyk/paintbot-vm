CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -pedantic
BUILD := build
ASM := ../vm/build/small-asm
BOTS := $(addprefix $(BUILD)/,seeker-h.bin seeker-v.bin right.bin wait.bin)
RUNTIME := ../game/bot_runner.c ../game/bot_runner.h

.PHONY: all test
all: $(BUILD)/treasure-host $(BOTS)

$(BUILD):
	mkdir -p $@

$(BUILD)/treasure-host: host.c game.c game.h $(RUNTIME) | $(BUILD)
	$(CC) $(CFLAGS) game.c host.c ../game/bot_runner.c -o $@

$(BUILD)/test-game: test_game.c game.c game.h | $(BUILD)
	$(CC) $(CFLAGS) game.c test_game.c -o $@

$(ASM): ../vm/tools/small-asm.c
	$(MAKE) -C ../vm

$(BUILD)/%.bin: bots/%.asm $(ASM) | $(BUILD)
	$(ASM) $< $@

test: all $(BUILD)/test-game
	$(MAKE) -C ../vm
	./$(BUILD)/test-game
	cd .. && python3 -B treasure/test_integration.py
