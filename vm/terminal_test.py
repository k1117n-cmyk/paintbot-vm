"""Small PTY harness shared by interactive VM and VM-game checks."""
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


class Terminal:
    def __init__(self, args, cwd=ROOT):
        self.master, self.slave = pty.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 64, 0, 0))
        self.original = termios.tcgetattr(self.slave)
        self.process = subprocess.Popen(
            args, cwd=cwd, stdin=self.slave, stdout=self.slave, stderr=self.slave,
            start_new_session=True, env={**os.environ, 'TERM': 'xterm'})
        self.data = bytearray()
        self.cursor = 0

    def until(self, marker, timeout=5):
        deadline = time.monotonic()+timeout
        while True:
            at = self.data.find(marker, self.cursor)
            if at >= 0:
                result = bytes(self.data[self.cursor:at+len(marker)])
                self.cursor = at+len(marker)
                return result
            assert time.monotonic() < deadline, (marker, bytes(self.data[-2000:]))
            if select.select([self.master], [], [], 0.05)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(bytes(self.data[-2000:])) from error
                    raise
                assert chunk
                self.data.extend(chunk)

    def frame(self):
        title = b'Dot Chase (VM)'
        self.until(title)
        text = title+self.until(b'\n')
        for _ in range(17):
            text += self.until(b'\n')
        lines = text.replace(b'\r', b'').splitlines()
        assert len(lines) == 18 and all(len(line) == 32 for line in lines), lines
        return lines

    def send(self, data):
        os.write(self.master, data)

    def restored(self):
        actual, expected = termios.tcgetattr(self.slave), self.original.copy()
        # macOS marks pending-input reprocessing on return to canonical mode.
        actual[3] &= ~getattr(termios, 'PENDIN', 0)
        expected[3] &= ~getattr(termios, 'PENDIN', 0)
        assert actual == expected, (actual, expected)

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=5)
        os.close(self.master)
        os.close(self.slave)
