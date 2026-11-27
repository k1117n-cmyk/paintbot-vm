.PHONY: all setup run test

all:
	$(MAKE) -C vm
	$(MAKE) -C game
	$(MAKE) -C treasure
	$(MAKE) -C console

setup: all
	vm/build/handmade-vm --self-test
	@for task_bot in explorer-h explorer-v raider-h raider-v; do \
		if test ! -e "registered/$$task_bot.bin"; then \
			game/build/paint-bots register "$$task_bot" "game/build/$$task_bot.bin" || exit $$?; \
		fi; \
	done

run: setup
	console/build/game-console

test: all
	vm/build/handmade-vm --self-test
	$(MAKE) -C game test test-host test-display test-registry
	python3 -B game/test_bot_mode.py
	$(MAKE) -C treasure test
	$(MAKE) -C console test
