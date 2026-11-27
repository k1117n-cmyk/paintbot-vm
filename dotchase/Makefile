BUILD := build
ASM := ../vm/build/small-asm

.PHONY: all test
all: $(BUILD)/dotchase.bin

$(BUILD):
	mkdir -p $@

$(ASM): ../vm/tools/small-asm.c
	$(MAKE) -C ../vm

$(BUILD)/dotchase.bin: game.asm $(ASM) | $(BUILD)
	$(ASM) $< $@

test: all
	$(MAKE) -C ../vm
	$(MAKE) -C ../console
	python3 -B test_game.py
