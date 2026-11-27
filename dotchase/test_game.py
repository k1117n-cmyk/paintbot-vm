"""Play the real VM game, plus small maps exercising the same generated logic."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'vm'))
from terminal_test import Terminal
from generate_game import LEVEL, BOARD, assembly

VM = ROOT/'vm/build/handmade-vm'
ASM = ROOT/'vm/build/small-asm'
GAME = ROOT/'dotchase/build/dotchase.bin'
MENU = ROOT/'console/build/game-console'


def location(frame, character):
    positions = [(x, y) for y, row in enumerate(frame[3:14])
                 for x, cell in enumerate(row[:16]) if cell == ord(character)]
    assert len(positions) == 1, (character, positions)
    return positions[0]


assert (ROOT/'dotchase/game.asm').read_text() == assembly()
assert GAME.stat().st_size < BOARD
assert sum(row.count(' ') for row in LEVEL)-1 == 89
print('PASS reproducible VM source, 89 reachable pellets and code/table below mutable board', flush=True)

terminal = Terminal([VM, '--game', GAME])
try:
    frame = terminal.frame()
    assert location(frame, '@') == (1, 1) and location(frame, 'G') == (14, 9)
    assert b'Dots: 00/89' in frame[1]
    terminal.send(b'w')
    frame = terminal.frame()
    assert location(frame, '@') == (1, 1) and b'00/89' in frame[1]
    terminal.send(b'D')
    started = time.monotonic()
    frame = terminal.frame()
    assert location(frame, '@') == (2, 1) and b'01/89' in frame[1]
    response = time.monotonic()-started
    assert response < 0.1, response
    # A repeat during the speed cap is discarded, rather than queued to run later.
    terminal.send(b'd')
    frame = terminal.frame()
    assert location(frame, '@') == (2, 1) and b'01/89' in frame[1]
    for _ in range(7):
        frame = terminal.frame()
        assert location(frame, '@') == (2, 1) and b'01/89' in frame[1]
    # A burst must cause at most one step, with no run-on after input stops.
    terminal.send(b'd'*20)
    frame = terminal.frame()
    assert location(frame, '@') == (3, 1) and b'02/89' in frame[1]
    for _ in range(10):
        frame = terminal.frame()
        assert location(frame, '@') == (3, 1) and b'02/89' in frame[1]
    terminal.send(b'a')
    frame = terminal.frame()
    assert location(frame, '@') == (2, 1) and b'02/89' in frame[1]
    for _ in range(2):
        frame = terminal.frame()
    assert location(frame, 'G') == (14, 8)
    assert b'02/89' in frame[1]
    # The latest direction wins within a poll; X cancels that poll's movement.
    terminal.send(b'dx')
    frame = terminal.frame()
    assert location(frame, '@') == (2, 1) and b'02/89' in frame[1]
    terminal.send(b'r')
    frame = terminal.frame()
    assert location(frame, '@') == (1, 1) and location(frame, 'G') == (14, 9)
    assert b'00/89' in frame[1]
    terminal.send(b'd')
    frame = terminal.frame()
    assert location(frame, '@') == (2, 1) and b'01/89' in frame[1]
    terminal.send(b'q')
    assert terminal.process.wait(timeout=3) == 0
    terminal.restored()
finally:
    terminal.close()
print(f'PASS real level: {response*1000:.1f}ms response, idle stop, speed cap, burst drain, wall, cancel, pellet/revisit, enemy every 24 updates (wall-clock precision unmeasured) and cooldown reset', flush=True)


def fixture(directory, name, rows, ghost):
    level = ['#'*16 for _ in range(11)]
    for y, row in rows.items():
        level[y] = row
    source = directory/(name+'.asm')
    binary = directory/(name+'.bin')
    source.write_text(assembly(tuple(level), player=17, ghost=ghost, interval=40,
                               player_ticks=1, enemy_ticks=4))
    subprocess.run([ASM, source, binary], check=True, capture_output=True, timeout=5)
    return binary


with tempfile.TemporaryDirectory(prefix='dotchase-vm-') as directory:
    directory = Path(directory).resolve()
    room = fixture(directory, 'room', {1: '#  #############', 2: '#  #############'}, 34)
    terminal = Terminal([VM, '--game', room])
    try:
        terminal.frame()
        # Stay above the enemy until it moves up, then go around its other side.
        for key in b'dwwasd':
            terminal.send(bytes([key]))
            frame = terminal.frame()
        assert b'03/03' in frame[1] and b'Cleared!' in frame[17], frame
        assert location(frame, '@') == (2, 2) and location(frame, 'G') == (2, 1)
        terminal.send(b'R')
        frame = terminal.frame()
        assert b'00/03' in frame[1] and b'Collect dots' in frame[17]
        # No input: the enemy moves every fourth update and eventually catches us.
        for _ in range(8):
            frame = terminal.frame()
        assert b'Caught!' in frame[17] and b'00/03' in frame[1], frame
        assert location(frame, '!') == (1, 1)
        terminal.send(b'\n')
        assert terminal.process.wait(timeout=3) == 0
        terminal.restored()
    finally:
        terminal.close()
    narrow = fixture(directory, 'collision', {1: '#  #############'}, 18)
    terminal = Terminal([VM, '--game', narrow])
    try:
        terminal.frame()
        terminal.send(b'd')
        frame = terminal.frame()
        assert b'Caught!' in frame[17] and b'Cleared!' not in frame[17]
        assert b'00/01' in frame[1]  # Enemy collision takes priority over its pellet.
        terminal.send(b'q')
        assert terminal.process.wait(timeout=3) == 0
        terminal.restored()
    finally:
        terminal.close()
print('PASS VM-owned clear, enemy collision, capture on enemy turn, loss-before-last-pellet, result restart and Enter/Q exit', flush=True)

terminal = Terminal([MENU])
try:
    terminal.until(b'Games> ')
    terminal.send(b'4\n')
    terminal.frame()
    os.killpg(terminal.process.pid, signal.SIGINT)
    terminal.until(b'Dot Chase stopped (status 130)')
    terminal.until(b'Games> ')
    terminal.restored()
    terminal.send(b'4\n')
    frame = terminal.frame()
    assert b'00/89' in frame[1]
    terminal.send(b'q')
    terminal.until(b'Returned from Dot Chase.')
    terminal.until(b'Games> ')
    terminal.restored()
    terminal.send(b'q\n')
    assert terminal.process.wait(timeout=3) == 0
finally:
    terminal.close()
result = subprocess.run([MENU], cwd=ROOT, input=b'4\nqq\n', capture_output=True, timeout=3)
assert result.returncode == 0 and not result.stderr and b'Returned from Dot Chase.' in result.stdout
assert result.stdout.count(b'VM Game Console') == 2
result = subprocess.run([VM, '--game', GAME], input=b'', capture_output=True, timeout=3)
assert result.returncode == 0 and not result.stderr
with tempfile.TemporaryDirectory(prefix='dotchase-missing-') as directory:
    root = Path(directory)
    (root/'vm/build').mkdir(parents=True)
    (root/'vm/build/handmade-vm').symlink_to(VM)
    result = subprocess.run([MENU], cwd=root, input=b'4\nq\n', capture_output=True, timeout=3)
    assert result.returncode == 0 and b'Dot Chase stopped (status 1)' in result.stdout
    assert b'dotchase/build/dotchase.bin' in result.stderr
print('PASS menu re-entry, Ctrl-C recovery, terminal restoration, piped command ownership, EOF and missing bytecode recovery', flush=True)
print('PASS 4 Dot Chase groups, 0 failures', flush=True)
