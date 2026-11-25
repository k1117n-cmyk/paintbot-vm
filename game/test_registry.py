"""Registry CLI contract and real registered matches; run from project root."""
from pathlib import Path
import os
import subprocess
import tempfile

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / 'game/build/paint-bots'
LIMIT = 1024 * 1024


def run(root, *args, ok=True):
    r = subprocess.run([str(CLI), *map(str, args)], cwd=root,
                       capture_output=True, timeout=35)
    if (r.returncode == 0) != ok:
        raise AssertionError((args, r.returncode, r.stdout, r.stderr))
    if not ok:
        assert not r.stdout, (args, r.stdout)
    return r


with tempfile.TemporaryDirectory(prefix='paint-registry-') as directory:
    root = Path(directory)
    source = root / 'upload.bin'
    source.write_bytes(b'original')
    assert run(root, 'list').stdout == b''
    assert not (root / 'registered').exists()
    run(root, ok=False)
    run(root, 'unknown', ok=False)
    run(root, 'register', 'name', ok=False)
    print('PASS empty list and invalid CLI: no match or registration')

    for name in ['', '.', '..', '../escape', 'a/b', 'a.bin', 'a b', 'a\n', '日本語', 'a' * 33]:
        run(root, 'register', name, source, ok=False)
    assert not (root / 'registered').exists()
    for name in ['z', 'A_0-', 'a' * 32, '_', '_bot', '0']:
        r = run(root, 'register', name, source)
        assert r.stdout == f'Registered {name} (8 bytes)\n'.encode()
        assert (root / 'registered' / f'{name}.bin').read_bytes() == b'original'
    source.write_bytes(b'changed')
    assert (root / 'registered/z.bin').read_bytes() == b'original'
    assert (root / 'incoming').is_dir()
    print('PASS names: ASCII alphabet, 1/32/33 boundaries, immutable copied content')

    for name in ['-', '-a', '--watch', '--no-watch', '--bad', '-' + 'a' * 31]:
        r = run(root, 'register', name, source, ok=False)
        assert b"no leading '-'" in r.stderr
        assert not (root / 'registered' / f'{name}.bin').exists()
    print('PASS leading hyphen rejected for single/32-character names and option-like names')

    run(root, 'register', 'z', source, ok=False)
    assert (root / 'registered/z.bin').read_bytes() == b'original'
    assert not list((root / 'registered').glob('.pending-*'))
    print('PASS duplicate rejection preserves existing bytes and removes temporary copy')

    for name, size, ok in [('empty', 0, False), ('one', 1, True),
                           ('maximum', LIMIT, True), ('oversized', LIMIT + 1, False)]:
        source.write_bytes(b'\0' * size)
        run(root, 'register', name, source, ok=ok)
        destination = root / 'registered' / f'{name}.bin'
        assert destination.exists() == ok
        if ok:
            assert destination.read_bytes() == source.read_bytes()
    print('PASS size boundaries: 0 rejected, 1 and 1048576 copied exactly, 1048577 rejected')

    source.write_bytes(b'input')
    symlink = root / 'link.bin'
    symlink.symlink_to(source)
    fifo = root / 'fifo.bin'
    os.mkfifo(fifo)
    for invalid in [root / 'missing', root, symlink, fifo]:
        run(root, 'register', 'invalid', invalid, ok=False)
    assert not (root / 'registered/invalid.bin').exists()
    print('PASS rejects missing file, directory, symlink and FIFO without blocking')

    # Both processes race to publish one name. Exactly one complete copy wins.
    other = root / 'other.bin'
    other.write_bytes(b'second' * 1000)
    children = [subprocess.Popen([str(CLI), 'register', 'race', str(path)],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for path in (source, other)]
    outputs = [p.communicate(timeout=5) for p in children]
    assert sorted(p.returncode for p in children) == [0, 1], outputs
    assert (root / 'registered/race.bin').read_bytes() in (source.read_bytes(), other.read_bytes())
    assert not list((root / 'registered').glob('.pending-*'))
    print('PASS concurrent same-name registration: exactly one complete copy, no overwrite')

    registered = root / 'registered'
    (registered / '.pending-hidden').write_bytes(b'x')
    (registered / 'bad name.bin').write_bytes(b'x')
    (registered / 'empty.bin').write_bytes(b'')
    (registered / 'huge.bin').write_bytes(b'x' * (LIMIT + 1))
    (registered / 'directory.bin').mkdir()
    (registered / 'linked.bin').symlink_to(source)
    # Legacy files remain on disk, but the new name rule excludes them.
    for name in ['-old', '--watch', '--no-watch', '--bad']:
        (registered / f'{name}.bin').write_bytes(b'legacy')
    expected = sorted(['z', 'A_0-', 'a' * 32, '_', '_bot', '0', 'one', 'maximum', 'race'])
    assert run(root, 'list').stdout.decode().splitlines() == expected
    assert all((registered / f'{name}.bin').read_bytes() == b'legacy'
               for name in ['-old', '--watch', '--no-watch', '--bad'])
    print('PASS sorted list includes only valid registered names and regular nonempty bounded files')

    (root / 'game/build').mkdir(parents=True)
    (root / 'vm/build').mkdir(parents=True)
    host = root / 'game/build/paint-host'
    host.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n')
    host.chmod(0o700)

    for args in [[], ['z'], ['z'] * 5, ['z', 'z'], ['z', 'missing'],
                 ['z', '../escape'], ['z', 'linked'], ['z', 'empty'],
                 ['z', 'huge'], ['z', 'directory'], ['--bad', 'z', 'one']]:
        run(root, 'match', *args, ok=False)
    # The fixture prints on every launch: empty stdout proves preflight rejection.
    print('PASS match preflight: participant count, duplicates, invalid and unavailable programs')

    # Existing legacy files rule out "missing file" as the rejection reason.
    for options in [[], ['--watch'], ['--no-watch']]:
        for name in ['-old', '--bad']:
            r = run(root, 'match', *options, name, 'z', ok=False)
            assert r.stderr == f'paint-bots: unknown option: {name}\n'.encode()
    for name in ['--watch', '--no-watch', '-old', '--bad']:
        r = run(root, 'match', 'z', name, ok=False)
        assert b'invalid participant name' in r.stderr
    for option in ['--watch', '--no-watch']:
        r = run(root, 'match', option, '--watch', 'z', ok=False)
        assert r.stderr == b'paint-bots: unknown option: --watch\n'
    print('PASS unknown options explicitly rejected despite existing files; legacy names cannot participate')

    for options in [[], ['--watch'], ['--no-watch']]:
        r = subprocess.run(
            [str(CLI), 'match', *options, 'one', 'z'], cwd=root, capture_output=True, timeout=2)
        assert r.returncode == 7 and r.stderr == b''
        assert r.stdout.decode().splitlines() == [*options, 'vm/build/handmade-vm',
                                                  'registered/one.bin', 'registered/z.bin']
    host.unlink()
    run(root, 'match', 'one', 'z', ok=False)
    print('PASS host arguments: ID order, default/forced watch, exit status and launch failure')

    host.symlink_to(REPO / 'game/build/paint-host')
    (root / 'vm/build/handmade-vm').symlink_to(REPO / 'vm/build/handmade-vm')
    for name, bot in [('right', 'right'), ('left', 'left'), ('wait3', 'wait'), ('wait4', 'wait')]:
        run(root, 'register', name, REPO / f'game/build/{bot}.bin')
    for names, score in [(['right', 'left'], '16:16'),
                         (['right', 'left', 'wait3'], '16:16:0'),
                         (['right', 'left', 'wait3', 'wait4'], '16:16:0:0')]:
        r = run(root, 'match', '--no-watch', *names)
        if r.stderr or f'Score: {score}\nResult: draw\n'.encode() not in r.stdout:
            print(f'FAIL registered match {names}: exit={r.returncode}', flush=True)
            print(r.stdout.decode(errors='replace'), r.stderr.decode(errors='replace'), flush=True)
        assert r.stderr == b'', r.stderr
        assert f'Final board (turns=200):\n'.encode() in r.stdout
        assert f'Score: {score}\nResult: draw\n'.encode() in r.stdout
        for i in range(1, len(names) + 1):
            assert f'ID {i}: accepted=200 timeout=0 invalid=0 VM-error=0\n'.encode() in r.stdout
        print(f'PASS registered {len(names)}-bot real VM match: 200 turns, score={score}, all accepted=200')

print('PASS 14 registry groups, 0 failures')
