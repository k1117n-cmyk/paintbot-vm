"""Real VM behavior and 200-turn matches for playable bots, run at repo root."""
import importlib.util
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

VM = 'vm/build/handmade-vm'
ASM = 'vm/build/small-asm'
HOST = 'game/build/paint-host'
NAMES = ('explorer-h', 'explorer-v', 'raider-h', 'raider-v')
DELTAS = {'W': (0, -1), 'A': (-1, 0), 'S': (0, 1), 'D': (1, 0)}


def check(condition, detail):
    if not condition:
        raise AssertionError(detail)


def run_bot(name, board, identity=1, count=2, position=(7, 7), remaining=123):
    # Other positions need not match their painted cells; both are legal state.
    positions = [(0, 0), (15, 15), (15, 0), (0, 15)][:count]
    positions[identity - 1] = position
    data = ''.join(''.join(row) + '\n' for row in board)
    data += f'{identity} {remaining:03d} {count}\n'
    data += ''.join(f'{i} {x:02d} {y:02d}\n' for i, (x, y) in enumerate(positions, 1))
    r = subprocess.run([VM, '--bot', f'game/build/{name}.bin'],
                       input=data.encode(), capture_output=True, timeout=2)
    check(r.returncode == 0 and r.stdout in (b'W\n', b'A\n', b'S\n', b'D\n'),
          (name, identity, position, r.returncode, r.stdout, r.stderr))
    return r.stdout.decode().strip()


def board_of(color):
    return [[color] * 16 for _ in range(16)]


# Build a cycle independently from the generator's local decision rules.
cycle = [(0, 0)]
for y in range(16):
    cycle += [(x, y) for x in (range(1, 16) if y % 2 == 0 else range(15, 0, -1))]
cycle += [(0, y) for y in range(15, 0, -1)]
check(len(cycle) == len(set(cycle)) == 256, 'cycle must visit every cell once')

with tempfile.TemporaryDirectory(prefix='paint-strategies-') as directory:
    root = Path(directory)
    source = root / 'arithmetic.asm'
    binary = root / 'arithmetic.bin'
    instructions = [('MOV R3, R5', 0x10350000), ('DEC R7', 0x21700000),
                    ('ADD R2, R6', 0x22260000), ('SUB R4, R1', 0x23410000)]
    source.write_text('\n'.join(text for text, _ in instructions) + '\n')
    r = subprocess.run([ASM, str(source), str(binary)], capture_output=True)
    check(r.returncode == 0 and binary.read_bytes() == b''.join(
        struct.pack('>I', word) for _, word in instructions), r.stderr)
    for instruction in ('MOV R8, R0', 'MOV R0', 'MOV R0, R1, R2',
                        'DEC R8', 'DEC R0, R1', 'ADD R0, 1', 'SUB R0, R8'):
        source.write_text(instruction + '\n')
        r = subprocess.run([ASM, str(source), str(binary)], capture_output=True)
        check(r.returncode != 0, instruction)
    source.write_text('MOVI R0, 65\nMOV R1, R0\nINC R1\nDEC R1\n'
                      'MOVI R2, 2\nADD R1, R2\nSUB R1, R2\nMOV R0, R1\nSYSCALL 0\nHALT\n')
    r = subprocess.run([ASM, str(source), str(binary)], capture_output=True)
    check(r.returncode == 0, r.stderr)
    r = subprocess.run([VM, '--bot', str(binary)], capture_output=True)
    check(r.returncode == 0 and r.stdout == b'A\n', (r.stdout, r.stderr))
print('PASS assembler arithmetic: exact encodings, 7 invalid forms, real VM execution')

spec = importlib.util.spec_from_file_location('strategy_generator', 'game/bots/generate_strategies.py')
generator = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(generator)
for name in NAMES:
    check(Path(f'game/bots/{name}.asm').read_text() == generator.assembly(name), name)
print('PASS 4 generated assembly sources match generator exactly')

for name in NAMES:
    path = [(y, x) for x, y in cycle] if name.endswith('-v') else cycle
    for i, position in enumerate(path):
        nx, ny = path[(i + 1) % len(path)]
        x, y = position
        expected = next(action for action, delta in DELTAS.items() if delta == (nx-x, ny-y))
        check(run_bot(name, board_of('1'), position=position) == expected, (name, position))
print('PASS all 256 positions x 4 bots: safe tour, all edges and two-digit coordinates')

for count in (2, 3, 4):
    for identity in range(1, count + 1):
        own = str(identity)
        rival = str(identity % count + 1)
        for name in NAMES:
            for expected, (dx, dy) in DELTAS.items():
                board = board_of(own)
                board[7+dy][7+dx] = '.'
                check(run_bot(name, board, identity, count) == expected, (name, expected, identity, count))
            for remaining in (200, 1):
                board = board_of(own)
                board[7][8] = '.'
                board[8][7] = rival
                expected = 'S' if name.startswith('raider') else 'D'
                check(run_bot(name, board, identity, count, remaining=remaining) == expected,
                      (name, identity, count, remaining, expected))
print('PASS all IDs in 2/3/4-player inputs: four directions, live board priorities, first/last turn')

# A non-owned CURRENT cell is not a legal destination unless we return later.
for name in NAMES:
    board = board_of('1')
    board[0][0] = '.'
    action = run_bot(name, board, position=(0, 0))
    check(action in ('D', 'S'), (name, action))
print('PASS current cell and boundary: move into board instead of waiting or hitting wall')

for count in (2, 3, 4):
    names = [NAMES[0], NAMES[3], NAMES[1], NAMES[2]][:count]
    r = subprocess.run([HOST, '--no-watch', VM, *[f'game/build/{name}.bin' for name in names]],
                       capture_output=True, timeout=35)
    print(f'MATCH {count}: {names!r} exit={r.returncode}', flush=True)
    print(r.stdout.decode(errors='replace'), end='', flush=True)
    print(r.stderr.decode(errors='replace'), end='', flush=True)
    check(r.returncode == 0, r.stderr)
    text = r.stdout.decode()
    check('Final board (turns=200):\n' in text, text)
    for i in range(1, count+1):
        check(f'ID {i}: accepted=200 timeout=0 invalid=0 VM-error=0\n' in text, text)
    board = text.split('Final board (turns=200):\n', 1)[1].splitlines()[:16]
    painted = [(x, y) for y, row in enumerate(board) for x, color in enumerate(row) if color in '1234']
    check(len(painted) >= 128 and len({x for x, y in painted}) == 16 and
          len({y for x, y in painted}) == 16, ('coverage', board))
    # Every participant must get beyond its starting row AND starting column.
    for identity in range(1, count+1):
        cells = [(x,y) for y,row in enumerate(board) for x,color in enumerate(row) if color == str(identity)]
        check(len({x for x,y in cells}) >= 2 and len({y for x,y in cells}) >= 2,
              ('two dimensional paint', identity, board))
    print(f'PASS {count}-player real VM match: 200 turns, all accepted, {len(painted)} painted cells across 16 rows/columns')
print('PASS 8 strategy groups, 0 failures')
