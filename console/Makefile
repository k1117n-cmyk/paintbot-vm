CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -pedantic
BUILD := build

.PHONY: all test
all: $(BUILD)/game-console

$(BUILD):
	mkdir -p $@

$(BUILD)/game-console: menu.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

test: all
	cd .. && python3 -B console/test_menu.py
