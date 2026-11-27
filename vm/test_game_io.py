"""Black-box ABI, mode isolation, timing and terminal lifecycle checks."""
from pathlib import Path
import os
import signal
import struct
import subprocess
import tempfile
import time

from terminal_test import ROOT, Terminal

VM = ROOT/'vm/build/handmade-vm'


def mov(register, value):
    return 0x40000000 | (register << 20) | value


def program(directory, words, address=None, data=b''):
    code = b''.join(struct.pack('>I', word) for word in words)
    if address is not None:
        assert address >= len(code)
        code = code.ljust(address, b'\0')+data
    path = directory/f'probe-{len(list(directory.iterdir()))}.bin'
    path.write_bytes(code)
    return path


def run(path, data=b'', option='--game'):
    return subprocess.run([VM, option, path], input=data, capture_output=True, timeout=5)


with tempfile.TemporaryDirectory(prefix='vm-game-io-') as directory:
    directory = Path(directory).resolve()
    for address in (4096, 1024*1024-576):
        path = program(directory, [mov(0, address), 0x60000004, 0x01000000], address, b'A'*576)
        result = run(path)
        assert (result.returncode, result.stdout, result.stderr) == (0, (b'A'*32+b'\n')*18, b''), result
    path = program(directory, [mov(0, 1024*1024-575), 0x60000004, 0x01000000])
    result = run(path)
    assert result.returncode == 1 and not result.stdout and b'address out of range' in result.stderr
    for invalid in (0, 10, 27, 127, 255):
        path = program(directory, [mov(0, 4096), 0x60000004, 0x01000000], 4096,
                       b'A'*575+bytes([invalid]))
        result = run(path)
        assert result.returncode == 1 and not result.stdout and b'printable ASCII' in result.stderr
    print('PASS exact 32x18 frames, final valid memory range, out-of-range/control-byte refusal without partial frame', flush=True)

    # All new services remain unavailable to the existing --bot protocol.
    for number in (4, 5, 6):
        result = run(program(directory, [0x60000000+number, 0x01000000]), option='--bot')
        assert result.returncode == 1 and not result.stdout
        assert result.stderr == f'unimplemented syscall: {number}\n'.encode()
    result = run(program(directory, [mov(0, 90), 0x60000003, 0x01000000]))
    assert result.returncode == 0 and result.stdout == b'Z' and not result.stderr
    print('PASS game syscall isolation from bot mode and existing raw output syscall', flush=True)

    # Read byte then EOF, proving EOF is distinct from both a key and no-input.
    words = [0x60000005, 0x60000003, 0x60000005, mov(1, 256), 0x24010000,
             0x6A000020, mov(0, 33), 0x60000003, 0x01000000]
    result = run(program(directory, words), b'Z')
    assert result.returncode == 0 and result.stdout == b'Z' and not result.stderr, result
    path = program(directory, [0x60000005, 0x60000003, 0x01000000])
    terminal = Terminal([VM, '--game', path])
    try:
        terminal.until(b'\0')
        assert terminal.process.wait(timeout=2) == 0
        terminal.restored()
    finally:
        terminal.close()
    print('PASS nonblocking no-input on open terminal, byte input and distinct EOF', flush=True)

    for milliseconds in (0, 1001):
        result = run(program(directory, [mov(0, milliseconds), 0x60000006, 0x01000000]))
        assert result.returncode == 1 and b'1..1000 ms' in result.stderr
    path = program(directory, [mov(0, 30), 0x60000006]*3+[0x01000000])
    started = time.monotonic()
    result = run(path)
    elapsed = time.monotonic()-started
    assert result.returncode == 0 and not result.stderr and 0.08 <= elapsed < 3, elapsed
    print('PASS interval bounds and wait smoke check (not clock precision or delay recovery)', flush=True)

    # Both CPU-only infinite loops and a sleeping game must be interruptible.
    for waiting in (False, True):
        words = [mov(0, 1000), 0x60000006, 0x68000008] if waiting else [0x68000008]
        path = program(directory, [mov(0, 90), 0x60000000]+words)
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            terminal = Terminal([VM, '--game', path])
            try:
                terminal.until(b'Z')
                os.kill(terminal.process.pid, signum)
                assert terminal.process.wait(timeout=2) == 128+signum
                terminal.restored()
                terminal.until(b'\x1b[?25h')
            finally:
                terminal.close()
    # A VM runtime failure also restores terminal settings.
    path = program(directory, [mov(0, 90), 0x60000003, 0])
    terminal = Terminal([VM, '--game', path])
    try:
        terminal.until(b'unknown instruction')
        assert terminal.process.wait(timeout=2) == 1
        terminal.restored()
    finally:
        terminal.close()
    print('PASS CPU/sleep INT/TERM/HUP and runtime-error terminal/cursor restoration', flush=True)
print('PASS 5 interactive VM groups, 0 failures', flush=True)
