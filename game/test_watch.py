"""Terminal integration; run from repo root after make -C game. Takes ~2min."""
import errno
import os
import pty
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path

HOST = "game/build/paint-host"
ARGS = ["vm/build/handmade-vm", "game/build/right.bin", "game/build/left.bin"]
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]")


def check(condition, output=None):
    if not condition:
        if output is not None:
            # Keep the last screen (including per-ID outcome totals), not the
            # entire 201-frame stream. Also works for plain terminal output.
            last = bytes(output).split(b"\x1b[H")[-1]
            print("FAIL watch captured final output:", flush=True)
            print(ANSI.sub(b"", last).decode(errors="replace"), flush=True)
        raise AssertionError("watch verification failed")


def terminal_run(options=(), term="xterm", bot_args=ARGS):
    master, slave = pty.openpty()
    # The screen contract is 64 columns, 24 rows.
    import fcntl
    import struct
    import termios
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 64, 0, 0))
    output = bytearray()
    arrivals = []
    started = time.monotonic()
    environment = dict(os.environ)
    if term is None:
        environment.pop("TERM", None)
    else:
        environment["TERM"] = term
    process = subprocess.Popen([HOST, *options, *bot_args], stdout=slave,
                               stderr=subprocess.PIPE, env=environment)
    os.close(slave)
    try:
        while True:
            check(time.monotonic() - started < 55, output)
            if not select.select([master], [], [], 1)[0]:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output.extend(chunk)
            frames = len(re.findall(rb"Paint battle \| Turn \d{3}/200", output))
            arrivals.extend([time.monotonic()] * (frames - len(arrivals)))
        check(process.wait(timeout=2) == 0, output)
        diagnostic = process.stderr.read()
        if diagnostic:
            print("FAIL watch host stderr:", diagnostic.decode(errors="replace"), flush=True)
        check(diagnostic == b"", output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stderr.close()
        os.close(master)
    return bytes(output), arrivals, time.monotonic() - started


output, arrivals, elapsed = terminal_run()
frames = output.split(b"\x1b[H")[1:]
check(len(frames) == 201 and len(arrivals) == 201)
for turn, frame in enumerate(frames):
    plain = ANSI.sub(b"", frame).replace(b"\r", b"")
    lines = plain.splitlines()
    check(len(lines) == 22 and max(map(len, lines)) <= 64)
    check(f"Turn {turn:03}/200 | Left {200-turn:03}".encode() in lines[0])
    check(all(len(row) == 32 for row in lines[2:18]))
    if turn < 200:
        check(lines[19] == b"Match in progress")
    else:
        check(lines[19] == b"Result: draw", output)
        check(b"ID 1  16" in lines[1] and b"ID 2  16" in lines[1], output)
        check(lines[2][30:32] == b"1 " and lines[17][:2] == b"2 ", output)
        check(all(b"accepted=200 timeout=0 invalid=0 VM-error=0" in row
                  for row in lines[20:22]), output)
# Arrival times include reader scheduling and PTY buffering. A delayed read can
# shorten the next observed interval even when host frames are >=200ms apart.
# Allow 20ms of observation jitter here; the host minimum remains 200ms, and
# elapsed >=40s separately checks the budget for all 200 turns.
check(elapsed >= 40 and all(b - a >= 0.18 for a, b in zip(arrivals, arrivals[1:])))
print(f"PASS terminal auto watch: 201 frames, 64x24, final draw 16:16, elapsed={elapsed:.3f}s")
print(f"PASS pacing: minimum observed interval={min(b-a for a,b in zip(arrivals, arrivals[1:])):.3f}s")

for options, term in [((), "dumb"), ((), None), (("--no-watch",), "xterm")]:
    output, arrivals, elapsed = terminal_run(options, term)
    check(not arrivals and b"\x1b" not in output)
    check(b"Score: 16:16\r\nResult: draw\r\n" in output, output)
    print(f"PASS plain terminal: options={options!r} TERM={term}, no ANSI, draw 16:16")

plain = subprocess.run([HOST, *ARGS], capture_output=True, timeout=10)
check(plain.returncode == 0 and plain.stderr == b"" and b"\x1b" not in plain.stdout)
check(b"Score: 16:16\nResult: draw\n" in plain.stdout)
print("PASS redirected stdout: original plain format, draw 16:16")

forced = subprocess.Popen([HOST, "--watch", *ARGS], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    check(select.select([forced.stdout], [], [], 2)[0])
    first = os.read(forced.stdout.fileno(), 16384)
    check(b"\x1b[H" in first and b"Turn 000/200 | Left 200" in first)
finally:
    forced.terminate()
    forced.wait(timeout=2)
    forced.stdout.close()
    forced.stderr.close()
print("PASS --watch forces initial ANSI frame on redirected stdout (then terminated)")


def check_error_match(bot_args, expected_totals):
    output, arrivals, elapsed = terminal_run(("--watch",), bot_args=bot_args)
    frames = output.split(b"\x1b[H")[1:]
    check(len(frames) == 201 and len(arrivals) == 201 and elapsed >= 40)
    for turn, frame in enumerate(frames):
        lines = ANSI.sub(b"", frame).replace(b"\r", b"").splitlines()
        check(len(lines) == 22 and max(map(len, lines)) <= 64)
        check(f"Turn {turn:03}/200 | Left {200-turn:03}".encode() in lines[0])
        check(all(len(row) == 32 for row in lines[2:18]))
    check(b"ID 1   1" in lines[1] and b"ID 2   1" in lines[1], output)
    check(lines[19] == b"Result: draw", output)
    check(lines[20:22] == expected_totals, output)
    return elapsed


elapsed = check_error_match(
    [ARGS[0], "game/build/loop.bin", "game/build/invalid.bin"],
    [b"ID 1: accepted=0 timeout=200 invalid=0 VM-error=0",
     b"ID 2: accepted=0 timeout=0 invalid=200 VM-error=0"])
print(f"PASS watch timeout/invalid: 201 frames, 200 retries each, draw 1:1, elapsed={elapsed:.3f}s")

with tempfile.TemporaryDirectory(prefix="paint-watch-error-") as directory:
    broken = Path(directory) / "unknown.bin"
    broken.write_bytes(b"\x00\x00\x00\x00")  # Invalid VM instruction, exit nonzero.
    elapsed = check_error_match(
        [ARGS[0], str(broken), "game/build/wait.bin"],
        [b"ID 1: accepted=0 timeout=0 invalid=0 VM-error=200",
         b"ID 2: accepted=200 timeout=0 invalid=0 VM-error=0"])
print(f"PASS watch VM-error: 201 frames, 200 retries, opponent accepted=200, draw 1:1, elapsed={elapsed:.3f}s")
with tempfile.TemporaryDirectory(prefix="paint-watch-four-") as directory:
    broken = Path(directory) / "unknown.bin"
    broken.write_bytes(b"\x00\x00\x00\x00")
    output, arrivals, elapsed = terminal_run(("--watch",), bot_args=[
        ARGS[0], "game/build/loop.bin", "game/build/invalid.bin",
        str(broken), "game/build/right.bin"])
    frames = output.split(b"\x1b[H")[1:]
    check(len(frames) == 201 and len(arrivals) == 201 and elapsed >= 40)
    for turn, frame in enumerate(frames):
        lines = ANSI.sub(b"", frame).replace(b"\r", b"").splitlines()
        check(len(lines) == 22 and max(map(len, lines)) <= 64)
        check(f"Turn {turn:03}/200 | Left {200-turn:03}".encode() in lines[0])
        check(all(len(row) == 32 for row in lines[2:18]))
    try:
        check(lines[19] == b"Result: ID 4 wins")
        check(all(value in lines[1] for value in [b"ID 1   1", b"ID 2   0", b"ID 3   1", b"ID 4  16"]))
        check(lines[20:22] == [
            b"ID 1: A=0 T=200 I=0 E=0 | ID 2: A=0 T=0 I=200 E=0",
            b"ID 3: A=0 T=0 I=0 E=200 | ID 4: A=200 T=0 I=0 E=0"])
    except AssertionError:
        print("FAIL four-bot watch final frame:", lines, flush=True)
        raise
    print(f"PASS four-bot watch: 201 frames, 64x24, 3 error kinds, healthy winner, elapsed={elapsed:.3f}s")
print("PASS 10 watch integration groups, 0 failures")
