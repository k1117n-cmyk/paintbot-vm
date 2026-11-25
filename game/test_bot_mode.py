"""Real VM checks; run from the repository root after make -C vm/game."""
import struct
import subprocess
import tempfile
from pathlib import Path

VM = "vm/build/handmade-vm"
HOST = "game/build/paint-host"


def check(condition):
    if not condition:
        raise AssertionError("verification failed")


with tempfile.TemporaryDirectory(prefix="paintbot-check-") as directory:
    root = Path(directory)
    cases = {
        "halt": ([0x40000044, 0x60000000, 0x01000000], b"D\n", b"CPU halted.\n", 0),
        "unknown": ([0], b"", b"unknown instruction: 00000000\n", 1),
        "after_action_error": ([0x40000044, 0x60000000, 0], b"D\n", b"unknown instruction: 00000000\n", 1),
        "register": ([0x40800000], b"", b"invalid register: R8\n", 1),
        "pair": ([0x10800000], b"", b"invalid register: rd=R8 rs=R0\n", 1),
        "memory": ([0x500FFFFF], b"", b"memory address out of range: 0x000FFFFF\n", 1),
        "byte_memory": ([0x401FFFFF, 0x20100000, 0x30010000], b"", b"memory address out of range: 0x00100000\n", 1),
        "jump": ([0x680FFFFF], b"", b"jump target out of range: 0x000FFFFF\n", 1),
        # Jump to INC R0 at the final word, then fetch beyond the 1 MiB memory.
        "pc": ([0x680FFFFC] + [0] * (0xFFFFC // 4 - 1) + [0x20000000],
               b"", b"pc out of range: 0x00100000\n", 1),
        "stack": ([0x02000000], b"", b"stack underflow\n", 1),
        "eof": ([0x60000002], b"", b"input EOF\n", 1),
        "syscall": ([0x60000004], b"", b"unimplemented syscall: 4\n", 1),
    }
    for name, (words, output, diagnostic, code) in cases.items():
        path = root / (name + ".bin")
        path.write_bytes(b"".join(struct.pack(">I", word) for word in words))
        r = subprocess.run([VM, "--bot", str(path)], input=b"", capture_output=True, timeout=2)
        check((r.returncode, r.stdout, r.stderr) == (code, output, diagnostic))
        print(f"PASS bot mode {name}: exit={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}")
    missing = root / "missing.bin"
    r = subprocess.run([VM, "--bot", str(missing)], capture_output=True)
    check(r.returncode != 0 and r.stdout == b"" and r.stderr)
    print("PASS bot mode missing program: nonzero, stdout empty, stderr diagnostic")
    oversized = root / "oversized.bin"
    oversized.write_bytes(b"\0" * (1024 * 1024 + 1))
    r = subprocess.run([VM, "--bot", str(oversized)], capture_output=True)
    check(r.returncode != 0 and r.stdout == b"" and b"program too large:" in r.stderr)
    print("PASS bot mode oversized program: nonzero, stdout empty, stderr diagnostic")
    for remaining in range(200, 0, -1):
        input_data = ("................\n" * 16 + f"2 {remaining:03d} 2\n1 00 00\n2 15 15\n").encode()
        r = subprocess.run([VM, "--bot", "game/build/left15.bin"], input=input_data, capture_output=True, timeout=2)
        check(r.returncode == 0 and r.stdout == (b"A\n" if remaining >= 186 else b"X\n"))
    print("PASS left15: all 200 remaining-turn values; A for 200..186, X for 185..001")
    for program, expected in [(root / "after_action_error.bin", "VM-error=200"), (missing, "VM-error=200")]:
        r = subprocess.run([HOST, VM, str(program), "game/build/wait.bin"], capture_output=True, timeout=20)
        try:
            check(r.returncode == 0 and b"Score: 1:1\nResult: draw\n" in r.stdout and expected.encode() in r.stdout)
        except AssertionError:
            print(f"FAIL host {program.name}: exit={r.returncode}; host stdout:", flush=True)
            print(r.stdout.decode("utf-8", errors="replace"), end="", flush=True)
            print("host stderr:", flush=True)
            print(r.stderr.decode("utf-8", errors="replace"), end="", flush=True)
            raise
        print(f"PASS host {program.name}: 200 retries, X each turn, score=1:1 draw, exit=0")
    r = subprocess.run([HOST, str(missing), "game/build/wait.bin", "game/build/wait.bin"], capture_output=True, timeout=2)
    check(r.returncode != 0 and r.stdout == b"" and b"host: cannot run VM:" in r.stderr)
    print("PASS host missing VM executable: abort, nonzero, no final result")
print("PASS 18 VM/integration groups, 0 failures (includes 200 left15 inputs)")
