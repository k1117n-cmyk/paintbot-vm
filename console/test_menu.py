"""Launcher contracts and alternating full game/VM round trips in a 64x24 PTY."""
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
CLI = REPO / 'console/build/game-console'
ANSI = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')


def run(root, data):
    result = subprocess.run([str(CLI)], cwd=root, input=data,
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result
    return result.stdout, result.stderr


class Terminal:
    def __init__(self, root):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 64, 0, 0))
        self.data = bytearray()
        self.cursor = 0
        self.process = subprocess.Popen(
            [str(CLI)], cwd=root, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, env={**os.environ, 'TERM': 'xterm'})
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
                raise AssertionError(('timeout', marker, bytes(self.data[-3000:])))
            if select.select([self.master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(bytes(self.data[-3000:])) from error
                    raise
                assert chunk, bytes(self.data[-3000:])
                self.data.extend(chunk)

    def send(self, data):
        os.write(self.master, data)

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        self.process.wait(timeout=5)
        os.close(self.master)


with tempfile.TemporaryDirectory(prefix='console-menu-') as directory:
    root = Path(directory)
    for data in (b'q\n', b'', b'  q  \n'):
        out, err = run(root, data)
        assert out.count(b'VM Game Console') == 1 and not err
    out, err = run(root, b'\n5\n1x\n' + b'1' * 1024 + b'\nq\n')
    assert b'Input too long' in out and b'Choose 1, 2, 3, 4 or q.' in out
    assert b'Paintbot stopped' not in out and not err
    print('PASS quit, EOF, whitespace, invalid choices and long-line draining', flush=True)

    out, err = run(root, b'1\nq\n')
    assert b'status 127' in out and b'game/build/paint-bots' in err
    assert out.count(b'VM Game Console') == 2
    print('PASS missing paintbot executable returns to game selection', flush=True)

    out, err = run(root, b'3\nq\n')
    assert b'Maze stopped (status 127)' in out and b'maze/build/maze' in err
    assert out.count(b'VM Game Console') == 2
    print('PASS missing maze executable returns to game selection', flush=True)

    out, err = run(root, b'4\nq\n')
    assert b'Dot Chase stopped (status 127)' in out and b'vm/build/handmade-vm' in err
    assert out.count(b'VM Game Console') == 2
    print('PASS missing interactive VM returns to game selection', flush=True)

    child = root / 'game/build/paint-bots'
    child.parent.mkdir(parents=True)
    child.write_text('#!/bin/sh\nprintf "child-arg=%s\\n" "$@"\nexit 7\n')
    child.chmod(0o700)
    out, err = run(root, b'1\n1\nq\n')
    assert out.count(b'child-arg=menu') == 2 and out.count(b'status 7') == 2
    assert out.count(b'VM Game Console') == 3 and not err
    print('PASS exact child arguments, abnormal exit and repeated launch', flush=True)

    # The child must receive its input instead of losing it to parent buffering.
    child.write_text('#!/bin/sh\nIFS= read -r command\nprintf "received=%s\\n" "$command"\n')
    out, err = run(root, b'1\nchild-input\nq\n')
    assert b'received=child-input' in out and b'Returned from Paintbot.' in out
    assert out.count(b'VM Game Console') == 2 and not err
    print('PASS parent does not read ahead into child input', flush=True)

    child.write_text('#!/bin/sh\necho CHILD_RUNNING\nexec sleep 30\n')
    terminal = Terminal(root)
    try:
        screen = terminal.until(b'Games> ')
        lines = ANSI.sub(b'', screen).replace(b'\r', b'').splitlines()
        assert len(lines) <= 24 and max(map(len, lines)) <= 64
        terminal.send(b'1\n')
        terminal.until(b'CHILD_RUNNING')
        os.killpg(terminal.process.pid, signal.SIGINT)
        terminal.until(b'status 130')
        terminal.until(b'Games> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
    print('PASS 64x24 screen and interrupted child returns to game selection', flush=True)

with tempfile.TemporaryDirectory(prefix='console-treasure-') as directory:
    root = Path(directory)
    for data in (b'2\nq\nq\n', b'2\n', b'2\n1 2\n'):
        out, err = run(root, data)
        assert b'Treasure - select bots' in out and not err
        assert b'Treasure stopped' not in out
    out, err = run(root, b'2\n\n1\n0 2\n1 5\n1x 2\n1,2\n1 2 3 4 1\n' +
                   b'1'*1024 + b'\nq\nq\n')
    assert b'Input too long' in out and b'Choose 2-4 numbers' in out and not err
    for response in (b'n\n', b'y'*1024 + b'\n'):
        out, err = run(root, b'2\n1 2\n' + response + b'q\nq\n')
        assert b'Match cancelled.' in out and b'Treasure stopped' not in out and not err
    print('PASS treasure back/EOF, invalid choices, long lines and confirmation cancellation', flush=True)

    out, err = run(root, b'2\n1 2\ny\nq\nq\n')
    assert b'Bot missing: seeker-h' in out and not err
    build = root / 'treasure/build'
    build.mkdir(parents=True)
    for name in ('seeker-h', 'seeker-v', 'right', 'wait'):
        (build / f'{name}.bin').write_bytes(b'fixture')
    out, err = run(root, b'2\n1 2\ny\n\nq\nq\n')
    assert b'Treasure stopped (status 127)' in out and b'treasure/build/treasure-host' in err
    assert b'Returned from Treasure.' in out
    print('PASS missing treasure bot prevents launch; missing host returns through both menus', flush=True)

    host = build / 'treasure-host'
    host.write_text('#!/bin/sh\necho called >> calls\nprintf "arg=%s\\n" "$@"\n')
    host.chmod(0o700)
    for launch, selection in enumerate(((2, 1), (1, 2, 1), (1, 2, 1, 2)), 1):
        out, err = run(root, b'2\n' + ' '.join(map(str, selection)).encode() + b'\ny\n\nq\nq\n')
        names = ['seeker-h', 'seeker-v', 'right', 'wait']
        args = b'arg=--watch\narg=vm/build/handmade-vm\n' + b''.join(
            f'arg=treasure/build/{names[i-1]}.bin\n'.encode() for i in selection)
        assert args in out and not err
        assert out.count(b'Treasure - select bots') == 2
        assert (root / 'calls').read_text() == 'called\n' * launch
    host.write_text('#!/bin/sh\nexit 7\n')
    out, err = run(root, b'2\n3 4\ny\n\n1 2\ny\n\nq\nq\n')
    assert out.count(b'Treasure stopped (status 7)') == 2 and not err
    print('PASS treasure 2/3/4 bots, repeated kinds, exact ID order/paths, forced watch and repeated failure recovery', flush=True)

    host.write_text('#!/bin/sh\necho TREASURE_RUNNING\nexec sleep 30\n')
    terminal = Terminal(root)
    try:
        terminal.until(b'Games> ')
        terminal.send(b'2\n')
        screen = terminal.until(b'Treasure bots> ')
        lines = ANSI.sub(b'', screen).replace(b'\r', b'').splitlines()
        assert len(lines) <= 24 and max(map(len, lines)) <= 64
        terminal.send(b'1 2\n')
        terminal.until(b'Start treasure match? [y/N]> ')
        terminal.send(b'y\n')
        terminal.until(b'TREASURE_RUNNING')
        os.killpg(terminal.process.pid, signal.SIGINT)
        terminal.until(b'Treasure stopped (status 130)')
        terminal.until(b'Press Enter to return to treasure selection> ')
        terminal.send(b'\n')
        terminal.until(b'Treasure bots> ')
        terminal.send(b'q\n')
        terminal.until(b'Games> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
    print('PASS treasure 64x24 selection and interrupted match returns through both menus', flush=True)

    paint = root / 'game/build/paint-bots'
    paint.parent.mkdir(parents=True)
    paint.write_text('#!/bin/sh\nIFS= read -r command\nprintf "paint-input=%s\\n" "$command"\n')
    paint.chmod(0o700)
    host.write_text('#!/bin/sh\nprintf "arg=%s\\n" "$@"\n')
    out, err = run(root, b'2\n1 2\ny\n\nq\n1\nq\n2\nq\nq\n')
    assert out.count(b'VM Game Console') == 4 and out.count(b'Treasure - select bots') == 3
    assert b'paint-input=q' in out and not err
    assert b'Returned from Paintbot.' in out and b'Returned from Treasure.' in out
    print('PASS alternating games with piped input and no stale menu commands', flush=True)

with tempfile.TemporaryDirectory(prefix='console-real-') as directory:
    root = Path(directory)
    (root / 'game/build').mkdir(parents=True)
    (root / 'vm/build').mkdir(parents=True)
    (root / 'treasure/build').mkdir(parents=True)
    (root / 'registered').mkdir()
    for name in ('treasure-host', 'seeker-h.bin', 'seeker-v.bin'):
        (root / 'treasure/build' / name).symlink_to(REPO / 'treasure/build' / name)
    for name in ('paint-bots', 'paint-host'):
        (root / 'game/build' / name).symlink_to(REPO / 'game/build' / name)
    (root / 'vm/build/handmade-vm').symlink_to(REPO / 'vm/build/handmade-vm')
    for name in ('right', 'left'):
        (root / 'registered' / f'{name}.bin').write_bytes(
            (REPO / 'game/build' / f'{name}.bin').read_bytes())
    terminal = Terminal(root)
    try:
        terminal.until(b'Games> ')
        terminal.send(b'1\n')
        terminal.until(b'Bots> ')
        terminal.send(b'1 2\n')
        terminal.until(b'Start match? [y/N]> ')
        terminal.send(b'y\n')
        terminal.until(b'Press Enter to return to selection> ', timeout=55)
        text = ANSI.sub(b'', bytes(terminal.data)).replace(b'\r', b'')
        final = text.split(b'Paint battle | Turn 200/200')[-1]
        assert b'Left 000' in final and b'Result: draw' in final
        assert final.count(b'accepted=200 timeout=0 invalid=0 VM-error=0') == 2, final
        terminal.send(b'\n')
        terminal.until(b'Bots> ')
        terminal.send(b'q\n')
        terminal.until(b'Returned from Paintbot.')
        terminal.until(b'Games> ')
        # Switch to the second game, finish it, and then re-enter paintbot.
        terminal.send(b'2\n')
        terminal.until(b'Treasure bots> ')
        terminal.send(b'1 2\n')
        terminal.until(b'Start treasure match? [y/N]> ')
        terminal.send(b'y\n')
        terminal.until(b'Press Enter to return to treasure selection> ', timeout=55)
        text = ANSI.sub(b'', bytes(terminal.data)).replace(b'\r', b'')
        final = text.split(b'Treasure | Turn 200/200')[-1]
        assert b'Gems 00' in final and b'ID 1  23' in final and b'ID 2  29' in final, final
        assert b'Result: ID 2 wins' in final
        assert b'ID 1: A=200 T=0 I=0 E=0' in final and b'ID 2: A=200 T=0 I=0 E=0' in final
        terminal.send(b'\n')
        terminal.until(b'Treasure bots> ')
        terminal.send(b'q\n')
        terminal.until(b'Returned from Treasure.')
        terminal.until(b'Games> ')
        # Re-entry must start a fresh bot selection, without stale input/state.
        terminal.send(b'1\n')
        terminal.until(b'Bots> ')
        terminal.send(b'q\n')
        terminal.until(b'Games> ')
        terminal.send(b'q\n')
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
print('PASS real VM: alternating full Paintbot/Treasure matches, both bot menus, re-entry and clean exit', flush=True)
print('PASS 13 console groups, 0 failures', flush=True)
