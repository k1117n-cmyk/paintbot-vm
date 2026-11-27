"""Real VM strategies, independent game model, failures and ANSI observation."""
from pathlib import Path
import errno
import fcntl
import importlib.util
import os
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / 'treasure/build/treasure-host'
VM = ROOT / 'vm/build/handmade-vm'
ASM = ROOT / 'vm/build/small-asm'
BOTDIR = ROOT / 'treasure/build'
ANSI = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')
DELTA = {'W': (0, -1), 'A': (-1, 0), 'S': (0, 1), 'D': (1, 0), 'X': (0, 0)}


def initial(count):
    board = [[0] * 16 for _ in range(16)]
    for y in (2, 4, 6, 9, 11, 13):
        for x in (2, 4, 6, 9, 11, 13):
            board[y][x] = 5 if x in (6, 9) and y in (6, 9) else 1
    return board, [(0, 0), (15, 15), (15, 0), (0, 15)][:count], [0] * count


def snapshot(board, positions, scores, bot, turn=0):
    rows = [''.join(str(v) if v else '.' for v in row) for row in board]
    records = [f'{i+1} {x:02} {y:02} {scores[i]:03}'
               for i, (x, y) in enumerate(positions)]
    return ('TREASURE1\n' + '\n'.join(rows) + '\n' +
            f'{bot+1} {200-turn:03} {len(positions)}\n' + '\n'.join(records) + '\n').encode()


def choose(board, positions, bot, vertical):
    position = positions[bot]
    x, y = position
    overlapping = [i for i, p in enumerate(positions) if p == position]
    if len(overlapping) > 1:
        return 'X' if bot == min(overlapping) else ('A' if x == 15 else 'D')
    targets = [(tx, ty) for ty, row in enumerate(board) for tx, v in enumerate(row)
               if v and (tx, ty) != position]
    if not targets:
        return 'X'
    tx, ty = min(targets, key=lambda p: (abs(x-p[0]) + abs(y-p[1]),
                                       p[0] if vertical else p[1],
                                       p[1] if vertical else p[0]))
    if y != ty and (vertical or x == tx):
        return 'S' if ty > y else 'W'
    return 'D' if tx > x else 'A'


def simulate(count):
    board, positions, scores = initial(count)
    for _ in range(200):
        actions = [choose(board, positions, i, i % 2 == 1) for i in range(count)]
        destinations = [(x + DELTA[a][0], y + DELTA[a][1])
                        for (x, y), a in zip(positions, actions)]
        for i, (x, y) in enumerate(destinations):
            if destinations.count((x, y)) == 1:
                scores[i] += board[y][x]
                board[y][x] = 0
        positions = destinations
    assert sum(scores) == 52 and not any(map(any, board)), (count, scores, board)
    return board, scores


def match(bots, option='--no-watch', vm=VM):
    return subprocess.run([str(HOST), option, str(vm), *map(str, bots)],
                          cwd=ROOT, capture_output=True, timeout=30)


def check_result(text, count):
    board, scores = simulate(count)
    rows = '\n'.join(''.join(str(v) if v else '.' for v in row) for row in board)
    assert f'Final board (turns=200):\n{rows}\n' in text
    assert 'Score: ' + ':'.join(map(str, scores)) + '\n' in text
    assert f'Treasures left: {sum(bool(v) for row in board for v in row)}\n' in text
    winners = [i + 1 for i, s in enumerate(scores) if s == max(scores)]
    result = 'Result: draw' if len(winners) != 1 else f'Result: ID {winners[0]} wins'
    assert result in text
    for i in range(count):
        assert f'ID {i+1}: accepted=200 timeout=0 invalid=0 VM-error=0' in text, text


# Ensure generated sources can be reproduced; the runtime uses only the VM.
spec = importlib.util.spec_from_file_location('treasure_generator', ROOT / 'treasure/bots/generate_seekers.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
for suffix, vertical in [('h', False), ('v', True)]:
    assert (ROOT / f'treasure/bots/seeker-{suffix}.asm').read_text() == generator.assembly(vertical)
    for y in range(16):
        for x in range(16):
            board, positions, scores = initial(4)
            bot = (x + y) % 4
            positions[bot] = (x, y)
            scores[bot] = 12
            data = snapshot(board, positions, scores, bot, (x*16+y) % 200)
            result = subprocess.run([str(VM), '--bot', str(BOTDIR / f'seeker-{suffix}.bin')],
                                    input=data, capture_output=True, timeout=2)
            expected = choose(board, positions, bot, vertical).encode() + b'\n'
            assert result.returncode == 0 and result.stdout == expected, (suffix, x, y, result)
    for only_self in (False, True):
        board, positions, scores = initial(2)
        board = [[0] * 16 for _ in range(16)]
        positions[1] = (6, 9)
        if only_self:
            board[9][6] = 5
        result = subprocess.run([str(VM), '--bot', str(BOTDIR / f'seeker-{suffix}.bin')],
                                input=snapshot(board, positions, scores, 1),
                                capture_output=True, timeout=2)
        assert result.returncode == 0 and result.stdout == b'X\n', result
print('PASS reproducible assembly; 512 all-position strategy checks, all IDs and empty/disputed-only boards', flush=True)

for positions in (
    [(12, 2), (12, 2)],  # Reported oscillation between the two upper-right treasures.
    [(6, 6), (6, 6)],   # Last treasure: one waits and the other leaves.
    [(0, 0), (0, 0)],
    [(15, 15), (15, 15)],
    [(0, 0), (12, 2), (12, 2)],  # Lowest overlapping ID is not ID 1.
    [(0, 0), (15, 15), (15, 15), (15, 15)],
    [(6, 6)] * 4,
):
    board = [[0] * 16 for _ in range(16)]
    board[6][6] = 5
    for vertical, suffix in ((False, 'h'), (True, 'v')):
        for bot in range(len(positions)):
            result = subprocess.run([str(VM), '--bot', str(BOTDIR / f'seeker-{suffix}.bin')],
                                    input=snapshot(board, positions, [0]*len(positions), bot),
                                    capture_output=True, timeout=2)
            expected = choose(board, positions, bot, vertical)
            assert result.returncode == 0 and result.stdout == (expected+'\n').encode(), result
            x, y = positions[bot]
            dx, dy = DELTA[expected]
            assert 0 <= x+dx < 16 and 0 <= y+dy < 16
            group = [i for i, p in enumerate(positions) if p == positions[bot]]
            if len(group) > 1:
                assert (expected == 'X') == (bot == min(group))
print('PASS reported overlap, last treasure, all IDs, 3/4-way overlaps and safe edge escapes', flush=True)

for count in (2, 3, 4):
    bots = [BOTDIR / ('seeker-v.bin' if i % 2 else 'seeker-h.bin') for i in range(count)]
    result = match(bots)
    assert result.returncode == 0 and not result.stderr, result
    check_result(result.stdout.decode(), count)
print('PASS real VM 2/3/4-bot matches: final boards, points, remaining treasures, winners and all replies match model', flush=True)

result = match([BOTDIR / 'wait.bin', BOTDIR / 'wait.bin'])
assert result.returncode == 0 and b'Score: 0:0\n' in result.stdout
assert b'Treasures left: 36\nResult: draw' in result.stdout
result = match([BOTDIR / 'right.bin', BOTDIR / 'wait.bin'])
assert result.returncode == 0 and b'Score: 0:0\n' in result.stdout
assert b'ID 1: accepted=200 timeout=0 invalid=0 VM-error=0' in result.stdout
print('PASS simple wait/right bots, zero-score draw and boundary behavior', flush=True)

with tempfile.TemporaryDirectory(prefix='treasure-failures-') as directory:
    directory = Path(directory)
    for name, source, expected in [
        ('invalid', 'MOVI R0, 63\nSYSCALL 0\nHALT\n', 'invalid=200 VM-error=0'),
        ('error', 'SYSCALL 4\nHALT\n', 'invalid=0 VM-error=200'),
    ]:
        asm, binary = directory / f'{name}.asm', directory / f'{name}.bin'
        asm.write_text(source)
        subprocess.run([str(ASM), str(asm), str(binary)], check=True, capture_output=True)
        result = match([binary, BOTDIR / 'wait.bin'])
        assert result.returncode == 0 and b'Score: 0:0\n' in result.stdout, result
        assert expected.encode() in result.stdout and b'-> X' in result.stderr, result
    result = match([BOTDIR / 'wait.bin', BOTDIR / 'wait.bin'], vm=directory / 'missing-vm')
    assert result.returncode != 0 and b'cannot run VM' in result.stderr
    assert b'Result:' not in result.stdout
    for args in ([], ['--bad'], [str(VM), str(BOTDIR / 'wait.bin')],
                 [str(VM)] + [str(BOTDIR / 'wait.bin')] * 5):
        result = subprocess.run([str(HOST), *args], capture_output=True, timeout=2)
        assert result.returncode != 0 and b'usage:' in result.stderr
print('PASS invalid output/VM error become waits; launch failure aborts; invalid CLI rejected', flush=True)


class Terminal:
    def __init__(self, bots):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 64, 0, 0))
        self.process = subprocess.Popen([str(HOST), '--watch', str(VM), *map(str, bots)],
                                        cwd=ROOT, stdin=slave, stdout=slave, stderr=slave,
                                        start_new_session=True, env={**os.environ, 'TERM': 'xterm'})
        os.close(slave)
        self.data = bytearray()

    def collect(self, marker, timeout):
        deadline = time.monotonic() + timeout
        while marker not in self.data:
            assert time.monotonic() < deadline, bytes(self.data[-3000:])
            if select.select([self.master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(bytes(self.data[-3000:])) from error
                    raise
                assert chunk
                self.data.extend(chunk)

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        self.process.wait(timeout=5)
        os.close(self.master)


with tempfile.TemporaryDirectory(prefix='treasure-timeout-') as directory:
    asm, binary = Path(directory) / 'loop.asm', Path(directory) / 'loop.bin'
    asm.write_text('again:\nJUMP again\n')
    subprocess.run([str(ASM), str(asm), str(binary)], check=True, capture_output=True)
    terminal = Terminal([binary, BOTDIR / 'wait.bin'])
    try:
        terminal.collect(b'Turn 002/200', 5)
        text = ANSI.sub(b'', terminal.data).replace(b'\r', b'')
        assert b'ID 1: A=0 T=1 I=0 E=0' in text and b'ID 2: A=1 T=0 I=0 E=0' in text
    finally:
        terminal.close()
print('PASS looping VM times out, other bot responds and next turn starts', flush=True)

bots = [BOTDIR / f'seeker-{suffix}.bin' for suffix in ('h', 'v', 'h', 'v')]
terminal = Terminal(bots)
try:
    terminal.collect(b'Turn 200/200', 55)
    terminal.collect(b'ID 4: A=200 T=0 I=0 E=0', 5)
    assert terminal.process.wait(timeout=5) == 0
    frames = bytes(terminal.data).split(b'\x1b[H')[1:]
    assert len(frames) == 201, len(frames)
    for frame in frames:
        lines = ANSI.sub(b'', frame).replace(b'\r', b'').splitlines()
        assert len(lines) == 22 and max(map(len, lines)) <= 64, lines
    first = ANSI.sub(b'', frames[0]).replace(b'\r', b'')
    assert first.count(b'$') == 5 and first.count(b'o ') == 32  # includes legend $
    board, scores = simulate(4)
    final = ANSI.sub(b'', frames[-1]).replace(b'\r', b'')
    for i, score in enumerate(scores):
        assert f'ID {i+1} {score:3}'.encode() in final, final
    for i in range(4):
        assert f'ID {i+1}: A=200 T=0 I=0 E=0'.encode() in final, final
    assert b'Result:' in final and b'Left 000' in final
finally:
    terminal.close()
print('PASS full watch match: 201 frames, 64x24 layout, treasure symbols, model scores and clean exit', flush=True)
print('PASS 7 treasure integration groups, 0 failures', flush=True)
