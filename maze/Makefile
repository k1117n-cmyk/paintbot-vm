CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -pedantic
BUILD := build

.PHONY: all test
all: $(BUILD)/maze

$(BUILD):
	mkdir -p $@

$(BUILD)/maze: maze.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

test: all
	$(MAKE) -C ../console
	python3 -B test_maze.py
