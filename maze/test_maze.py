"""Play the compiled game through pipes and a 64x24 pseudo terminal."""
from collections import deque
from pathlib import Path
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / 'maze/build/maze'
MENU = ROOT / 'console/build/game-console'


def run(data):
    result = subprocess.run([GAME], input=data, capture_output=True, timeout=5)
    assert result.returncode == 0 and not result.stderr, result
    return result.stdout


initial = run(b'')
board = [line for line in initial.splitlines() if line.startswith(b'#')]
assert len(board) == 9 and all(len(row) == 17 for row in board)
start = next((x, y) for y, row in enumerate(board) for x, c in enumerate(row) if c == ord('@'))
goal = next((x, y) for y, row in enumerate(board) for x, c in enumerate(row) if c == ord('G'))
queue = deque([(start, b'')])
visited = {start}
route = None
while queue:
    (x, y), path = queue.popleft()
    if (x, y) == goal:
        route = path
        break
    for key, dx, dy in ((b'w', 0, -1), (b'a', -1, 0), (b's', 0, 1), (b'd', 1, 0)):
        point = x + dx, y + dy
        if 0 <= point[1] < 9 and 0 <= point[0] < 17 and board[point[1]][point[0]] != ord('#') and point not in visited:
            visited.add(point)
            queue.append((point, path + key))
assert route, 'Goal must be reachable from the displayed start'
out = run(route + b'\n')
assert b'Cleared!' in out and f'Moves: {len(route)}\n'.encode() in out
assert out.count(b'Cleared!') == 1
assert b'Cleared!' in run(route.upper() + b'Q')
print('PASS displayed maze is solvable; lowercase/uppercase movement and clear', flush=True)

out = run(b'waz\nrq')
assert out.count(b'Wall.') == 2 and b'Use W/A/S/D' in out
assert b'Moves: 1\n' not in out and b'Restarted.' in out
out = run(b'ddrq')
assert b'Moves: 2\n' in out and b'Moves: 0\n' in out.split(b'Moves: 2\n')[-1]
assert b'Cleared!' not in run(b'q') and b'Cleared!' not in run(b'd')
assert b'Cleared!' in run(route)  # EOF at the result also exits cleanly.
print('PASS walls, invalid input, newlines, restart, quit and EOF', flush=True)


class Terminal:
    def __init__(self, executable):
        self.master, self.slave = pty.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 64, 0, 0))
        self.original = termios.tcgetattr(self.slave)
        self.process = subprocess.Popen(
            [executable], cwd=ROOT, stdin=self.slave, stdout=self.slave, stderr=self.slave,
            start_new_session=True, env={**os.environ, 'TERM': 'xterm'})
        self.data = bytearray()
        self.cursor = 0

    def until(self, marker):
        deadline = time.monotonic() + 5
        while True:
            position = self.data.find(marker, self.cursor)
            if position >= 0:
                result = bytes(self.data[self.cursor:position + len(marker)])
                self.cursor = position + len(marker)
                return result
            assert time.monotonic() < deadline, (marker, self.data[-2000:])
            if select.select([self.master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(self.data[-2000:]) from error
                    raise
                assert chunk
                self.data.extend(chunk)

    def send(self, data):
        os.write(self.master, data)

    def restored(self):
        actual = termios.tcgetattr(self.slave)
        expected = self.original.copy()
        # macOS sets PENDIN when canonical mode is restored: it describes
        # pending-input reprocessing rather than a changed terminal setting.
        actual[3] &= ~getattr(termios, 'PENDIN', 0)
        expected[3] &= ~getattr(termios, 'PENDIN', 0)
        assert actual == expected, (expected, actual)

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=5)
        os.close(self.master)
        os.close(self.slave)


for signum in (None, signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    terminal = Terminal(GAME)
    try:
        screen = terminal.until(b'Press a key (no Enter needed).')
        assert b'\x1b[2J' in screen
        lines = screen.replace(b'\r', b'').splitlines()
        assert len(lines) <= 24 and max(map(len, lines)) <= 64
        assert not (termios.tcgetattr(terminal.slave)[3] & termios.ICANON)
        terminal.send(b'd')
        terminal.until(b'Moves: 1')
        if signum is None:
            terminal.send(b'q')
        else:
            os.kill(terminal.process.pid, signum)
        assert terminal.process.wait(timeout=5) == (0 if signum is None else 128 + signum)
        terminal.restored()
    finally:
        terminal.close()
print('PASS immediate keys, 64x24 display and terminal restoration on quit/INT/TERM/HUP', flush=True)

terminal = Terminal(MENU)
try:
    terminal.until(b'Games> ')
    terminal.send(b'3\n')
    terminal.until(b'Press a key (no Enter needed).')
    terminal.send(route)
    terminal.until(b'Cleared! Enter or Q: back to games')
    terminal.send(b'\n')
    terminal.until(b'Returned from Maze.')
    terminal.until(b'Games> ')
    terminal.restored()
    terminal.send(b'3\n')
    terminal.until(b'Moves: 0')
    terminal.until(b'Press a key (no Enter needed).')
    os.killpg(terminal.process.pid, signal.SIGINT)
    terminal.until(b'Maze stopped (status 130)')
    terminal.until(b'Games> ')
    terminal.restored()
    terminal.send(b'3\n')
    terminal.until(b'Press a key (no Enter needed).')
    terminal.send(b'q')
    terminal.until(b'Returned from Maze.')
    terminal.until(b'Games> ')
    terminal.restored()
    terminal.send(b'q\n')
    assert terminal.process.wait(timeout=5) == 0
finally:
    terminal.close()
result = subprocess.run([MENU], cwd=ROOT, input=b'3\nq' + b'q\n', capture_output=True, timeout=5)
assert result.returncode == 0 and not result.stderr
assert result.stdout.count(b'VM Game Console') == 2
assert b'Returned from Maze.' in result.stdout
print('PASS menu clear, re-entry reset, interrupted game, quit and piped command ownership', flush=True)
print('PASS 4 maze groups, 0 failures', flush=True)
