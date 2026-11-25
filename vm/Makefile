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

$(VM): notes/vm.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

$(ASM): tools/small-asm.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD)/%.bin: programs/%.asm $(ASM) | $(BUILD)
	$(ASM) $< $@

clean:
	rm -rf $(BUILD)
