CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -pedantic
BUILD := build
VM_BUILD := ../vm/build
ASM := $(VM_BUILD)/small-asm
BOT_NAMES := right left wait left15 loop invalid explorer-h explorer-v raider-h raider-v
BOTS := $(addprefix $(BUILD)/,$(addsuffix .bin,$(BOT_NAMES)))
HOST := $(BUILD)/paint-host
TEST := $(BUILD)/test-game

.PHONY: all test
all: $(TEST) $(HOST) $(BOTS) $(BUILD)/paint-bots

.PHONY: test-strategies
test-strategies: all
	cd .. && python3 game/test_strategies.py

.PHONY: test-maintenance
test-maintenance: all
	cd .. && python3 -B game/test_logging.py
	cd .. && python3 -B game/test_backup.py
	cd .. && python3 -B game/test_benchmark.py

$(BUILD):
	mkdir -p $@

$(TEST): game.c game.h test_game.c | $(BUILD)
	$(CC) $(CFLAGS) game.c test_game.c -o $@

test: $(TEST)
	./$(TEST)

$(HOST): host.c game.c game.h display.c display.h bot_runner.c bot_runner.h | $(BUILD)
	$(CC) $(CFLAGS) game.c display.c host.c bot_runner.c -o $@

$(BUILD)/paint-bots: registry.c | $(BUILD)
	$(CC) $(CFLAGS) registry.c -o $@

.PHONY: test-menu-service
test-menu-service:
	cd .. && python3 game/test_menu_service.py

.PHONY: test-menu
test-menu: all
	cd .. && python3 game/test_menu.py

.PHONY: test-registry
test-registry: all
	cd .. && python3 game/test_registry.py

$(ASM): ../vm/tools/small-asm.c
	$(MAKE) -C ../vm

$(BUILD)/%.bin: bots/%.asm $(ASM) | $(BUILD)
	$(ASM) $< $@

$(BUILD)/test-host: test_host.c host.c game.c game.h display.c display.h bot_runner.c bot_runner.h | $(BUILD)
	$(CC) $(CFLAGS) game.c display.c test_host.c bot_runner.c -o $@

.PHONY: test-host
test-host: $(BUILD)/test-host
	./$(BUILD)/test-host

$(BUILD)/test-display: test_display.c display.c display.h game.c game.h | $(BUILD)
	$(CC) $(CFLAGS) game.c display.c test_display.c -o $@

.PHONY: test-display test-watch
test-display: $(BUILD)/test-display
	./$(BUILD)/test-display

# Run from the repository root: make -C game test-watch
test-watch: all
	cd .. && python3 game/test_watch.py

.PHONY: test-multi
test-multi: all
	cd .. && python3 game/test_multibot.py
