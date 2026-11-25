"""Selection menu contracts and PTY/real-VM integration. Run after builds."""
from contextlib import contextmanager
from pathlib import Path
import errno
import fcntl
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

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / 'game/build/paint-bots'
ANSI = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')


@contextmanager
def fixture(count=4, status=0):
    with tempfile.TemporaryDirectory(prefix='paint-menu-') as directory:
        root = Path(directory)
        (root / 'game/build').mkdir(parents=True)
        (root / 'vm/build').mkdir(parents=True)
        for i in range(count):
            (root / 'registered').mkdir(exist_ok=True)
            (root / 'registered' / f'bot{i:02}.bin').write_bytes(b'fixture')
        (root / 'game/build/paint-host').write_text(
            '#!/bin/sh\necho called >> calls\nprintf "arg=%s\\n" "$@"\n' + f'exit {status}\n')
        (root / 'game/build/paint-host').chmod(0o700)
        yield root


def plain(root, data):
    r = subprocess.run([str(CLI), 'menu'], cwd=root, input=data,
                       capture_output=True, timeout=5)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


class Terminal:
    def __init__(self, root):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 64, 0, 0))
        self.data = bytearray()
        self.cursor = 0
        self.process = subprocess.Popen([str(CLI), 'menu'], cwd=root,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            env={**os.environ, 'TERM': 'xterm'})
        os.close(slave)

    def until(self, marker, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            position = self.data.find(marker, self.cursor)
            if position >= 0:
                result = bytes(self.data[self.cursor:position + len(marker)])
                self.cursor = position + len(marker)
                return result
            if time.monotonic() >= deadline:
                raise AssertionError(('timeout', marker, bytes(self.data[-5000:])))
            if select.select([self.master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(('terminal closed', bytes(self.data[-5000:]))) from error
                    raise
                if not chunk:
                    raise AssertionError(('EOF', bytes(self.data[-5000:])))
                self.data.extend(chunk)

    def send(self, data):
        os.write(self.master, data)

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        self.process.wait(timeout=5)
        os.close(self.master)


for count in (0, 1):
    with fixture(count) as root:
        out = plain(root, b'q\n')
        assert f'Registered: {count}'.encode() in out
        assert not (root / 'calls').exists()
        assert b'Bots> ' in plain(root, b'')
print('PASS empty/one-bot screen and EOF: no implicit match')

with fixture() as root:
    invalid = b'\n1\n0 2\n1 5\n1 1\n1 2 3 4 5\n-1 2\n1,2\n1x 2\n' + b'1' * 1024 + b'\nq\n'
    out = plain(root, invalid)
    assert b'Input too long' in out and b'Choose 2-4 different' in out
    assert not (root / 'calls').exists()
print('PASS invalid selection: counts, bounds, duplicates, syntax, drained long input')

with fixture() as root:
    for data in [b'1 2\nn\nq\n', b'1 2\n', b'1 2\n' + b'y' * 1024 + b'\nq\n']:
        out = plain(root, data)
        assert b'ID 1: bot00\nID 2: bot01' in out
        assert not (root / 'calls').exists()
print('PASS confirmation cancel, long response and EOF never start a match')

for indices in [(2, 1), (3, 1, 2), (4, 2, 1, 3)]:
    with fixture() as root:
        data = (' '.join(map(str, indices)) + '\ny\n\nq\n').encode()
        out = plain(root, data)
        expected = b'arg=--watch\narg=vm/build/handmade-vm\n' + b''.join(
            f'arg=registered/bot{i - 1:02}.bin\n'.encode() for i in indices)
        assert expected in out
        assert (root / 'calls').read_text() == 'called\n'
        assert out.count(b'Paint battle - select bots') == 2
print('PASS 2/3/4 selection: exact ID order, forced watch, single launch, Enter returns')

with fixture(status=7) as root:
    out = plain(root, b'1 2\ny\n\nq\n')
    assert b'Match stopped (status 7)' in out
    assert out.count(b'Paint battle - select bots') == 2
print('PASS failed match status displayed and selection resumes')

with fixture(10) as root:
    out = plain(root, b'p\nn\nn\np\nr\nq\n')
    assert out.count(b'Page 2/2') == 2
    assert b'9: bot08\n10: bot09' in out
    assert not (root / 'calls').exists()
print('PASS pagination bounds and refresh never start a match')

with fixture(10) as root:
    terminal = Terminal(root)
    try:
        first = terminal.until(b'Bots> ')
        lines = ANSI.sub(b'', first).replace(b'\r', b'').splitlines()
        assert len(lines) <= 24 and max(map(len, lines)) <= 64, lines
        assert terminal.process.poll() is None and not (root / 'calls').exists()
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS 64x24 PTY screen waits for operator input')

with fixture(1) as root:
    terminal = Terminal(root)
    try:
        terminal.until(b'Bots> ')
        (root / 'registered/new.bin').write_bytes(b'new')
        terminal.send(b'r\n')
        out = terminal.until(b'Bots> ')
        assert b'Registered: 2' in out and b'2: new' in out
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS refresh sees bots registered while the menu is waiting')

with fixture() as root:
    terminal = Terminal(root)
    try:
        terminal.until(b'Bots> ')
        terminal.send(b'1 2\n')
        terminal.until(b'Start match? [y/N]> ')
        (root / 'registered/bot01.bin').unlink()
        terminal.send(b'y\n')
        terminal.until(b'Match stopped (status 1)')
        terminal.until(b'Press Enter to return to selection> ')
        assert not (root / 'calls').exists()
        terminal.send(b'\n')
        terminal.until(b'Bots> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS match revalidates removed participant and returns without launching host')

with fixture() as root:
    host = root / 'game/build/paint-host'
    host.write_text('#!/bin/sh\necho MATCH_RUNNING\nexec sleep 30\n')
    terminal = Terminal(root)
    try:
        terminal.until(b'Bots> ')
        terminal.send(b'1 2\ny\n')
        terminal.until(b'MATCH_RUNNING')
        os.killpg(terminal.process.pid, signal.SIGINT)
        terminal.until(b'Match stopped (status 130)')
        terminal.until(b'Press Enter to return to selection> ')
        terminal.send(b'\n')
        terminal.until(b'Bots> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS Ctrl-C during a match interrupts child and returns to selection')

with fixture(2) as root:
    host = root / 'game/build/paint-host'
    host.unlink()
    host.symlink_to(REPO / 'game/build/paint-host')
    (root / 'vm/build/handmade-vm').symlink_to(REPO / 'vm/build/handmade-vm')
    for i, name in enumerate(['right', 'left']):
        (root / 'registered' / f'bot{i:02}.bin').write_bytes((REPO / f'game/build/{name}.bin').read_bytes())
    terminal = Terminal(root)
    try:
        terminal.until(b'Bots> ')
        terminal.send(b'1 2\ny\n')
        terminal.until(b'Press Enter to return to selection> ', timeout=55)
        text = ANSI.sub(b'', bytes(terminal.data)).replace(b'\r', b'')
        final = text.split(b'Paint battle | Turn 200/200')[-1]
        assert b'Left 000' in final and b'Result: draw' in final
        assert final.count(b'accepted=200 timeout=0 invalid=0 VM-error=0') == 2, final
        assert b'ID 1  16' in final and b'ID 2  16' in final
        assert b'Paint battle - select bots' not in final
        terminal.send(b'\n')
        terminal.until(b'Bots> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS real VM menu match: 200 turns, 16:16 draw, all accepted=200, Enter returns')
print('PASS 11 menu groups, 0 failures')
