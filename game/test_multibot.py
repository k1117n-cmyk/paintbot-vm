"""2..4-player host integration, including real VM failures. Run from repo root."""
from pathlib import Path
import struct
import subprocess
import tempfile

HOST = 'game/build/paint-host'
VM = 'vm/build/handmade-vm'
BOT = 'game/build/'


def run(args, score, result, totals):
    r = subprocess.run([HOST, '--no-watch', *args], capture_output=True, timeout=35)
    try:
        assert r.returncode == 0
        assert f'Final board (turns=200):\n'.encode() in r.stdout
        assert f'Score: {score}\nResult: {result}\n'.encode() in r.stdout
        for i, counts in enumerate(totals, 1):
            expected = f'ID {i}: accepted={counts[0]} timeout={counts[1]} invalid={counts[2]} VM-error={counts[3]}\n'
            assert expected.encode() in r.stdout
    except AssertionError:
        print(f'FAIL args={args!r} exit={r.returncode}', flush=True)
        print(r.stdout.decode(errors='replace'), r.stderr.decode(errors='replace'), flush=True)
        raise
    return r


accepted = (200, 0, 0, 0)
with tempfile.TemporaryDirectory(prefix='paint-multi-') as directory:
    root = Path(directory)
    # Exhaustive protocol serialization checks are in test_host.c, without
    # conflating serialization correctness with child-process scheduling.
    for n in (3, 4):
        run([VM, BOT+'right.bin', BOT+'left.bin', *([BOT+'wait.bin'] * (n-2))],
            '16:16:0' + (':0' if n == 4 else ''), 'draw', [accepted] * n)
        print(f'PASS {n} real VM bots: 200 turns, moving bots overwrite stationary corner occupants')
    run([VM, BOT+'wait.bin', BOT+'wait.bin', BOT+'left.bin', BOT+'wait.bin'],
        '0:1:16:1', 'ID 3 wins', [accepted] * 4)
    print('PASS real VM ID 3 wins, score=0:1:16:1')
    run([VM, BOT+'wait.bin', BOT+'wait.bin', BOT+'wait.bin', BOT+'right.bin'],
        '1:0:1:16', 'ID 4 wins', [accepted] * 4)
    print('PASS real VM ID 4 wins, score=1:0:1:16')
    broken = root / 'unknown.bin'
    broken.write_bytes(struct.pack('>I', 0))
    run([VM, BOT+'loop.bin', BOT+'invalid.bin', str(broken), BOT+'right.bin'],
        '1:0:1:16', 'ID 4 wins',
        [(0,200,0,0), (0,0,200,0), (0,0,0,200), accepted])
    print('PASS four real VM bots: timeout/invalid/instruction error each retried 200 times; healthy ID 4 accepted=200 and wins')
    for count in (1, 5):
        r = subprocess.run([HOST, VM, *([BOT+'wait.bin'] * count)], capture_output=True, timeout=2)
        assert r.returncode != 0 and not r.stdout and b'usage:' in r.stderr
    print('PASS CLI rejects 1 and 5 participants before starting a match')
print('PASS 6 multibot integration groups, 0 failures')
