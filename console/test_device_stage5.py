"""Isolated source deployment checks; no SSH, sudo or systemd changes."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile

import deploy_device as deploy
import device_stage5 as device


def refused(function):
    try:
        function()
    except (RuntimeError, OSError, ValueError, KeyError, tarfile.TarError):
        return
    raise AssertionError('expected refusal')


def archive_at(path, entries):
    with tarfile.open(path, 'w') as bundle:
        for name, data, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(data)
            bundle.addfile(entry, io.BytesIO(data))
    return device.sha(path.read_bytes())


with tempfile.TemporaryDirectory(prefix='console-device-test-') as directory:
    root = Path(directory).resolve()
    archive, digest, manifest = deploy.prepare(deploy.ROOT, root)
    assert len(manifest) < 128 and archive.stat().st_size <= device.LIMIT
    assert all('/build/' not in name and 'registered' not in name for name in manifest)
    assert 'game/bot_runner.c' in manifest and 'treasure/bots/seeker-h.asm' in manifest
    assert {'maze/maze.c', 'maze/Makefile', 'maze/test_maze.py'} <= manifest.keys()
    project = root/'project'
    assert device.unpack(archive, digest, project) == manifest
    device.verify_sources(project, manifest)
    refused(lambda: device.unpack(archive, digest, project))
    refused(lambda: device.unpack(archive, '0'*64, root/'wrong-hash'))
    assert not (root/'wrong-hash').exists()
    print('PASS bounded source-only package, manifest, exact extraction, hash and existing-destination refusal', flush=True)

    bad = root/'bad.tar'
    for name, kind in (('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                       ('game/link', tarfile.SYMTYPE), ('game/build/private', tarfile.REGTYPE)):
        bad_digest = archive_at(bad, [(name, b'x', kind)])
        refused(lambda: device.unpack(bad, bad_digest, root/'rejected'))
        assert not (root/'rejected').exists()
    bad_digest = archive_at(bad, [('game/a.c', b'x', tarfile.REGTYPE)]*2)
    refused(lambda: device.unpack(bad, bad_digest, root/'rejected'))
    bad_digest = archive_at(bad, [('game/a.c', b'x', tarfile.REGTYPE),
                                ('MANIFEST.json', b'{}', tarfile.REGTYPE)])
    refused(lambda: device.unpack(bad, bad_digest, root/'rejected'))
    assert not (root/'rejected').exists()
    print('PASS traversal, absolute paths, symlinks, build payloads, duplicates and altered manifests refused', flush=True)

    registered = root/'original-registered'
    registered.mkdir()
    (registered/'mini.bin').write_bytes(b'mini-bot')
    (registered/'air.bin').write_bytes(b'air-bot')
    before = device.registered_state(registered)
    (project/'registered').symlink_to(registered, target_is_directory=True)
    assert device.registered_state(registered) == before
    for folder in ('vm', 'game', 'treasure', 'maze', 'console'):
        result = subprocess.run(['make', '-C', folder], cwd=project, capture_output=True, timeout=30)
        assert result.returncode == 0, (folder, result.stdout, result.stderr)
    assert (project/'console/build/game-console').is_file()
    # Verify the freshly built VM before launching it under a 100ms bot deadline.
    # macOS may delay the first execution of a newly compiled binary.
    result = subprocess.run(['vm/build/handmade-vm', '--self-test'], cwd=project,
                            capture_output=True, timeout=10)
    assert result.returncode == 0 and b'VM flow complete.' in result.stdout, result
    for folder, host, bots in (
        ('game', 'paint-host', ['right', 'left']),
        ('treasure', 'treasure-host', ['seeker-h', 'seeker-v']),
    ):
        result = subprocess.run([str(project/f'{folder}/build/{host}'), '--no-watch',
                                 str(project/'vm/build/handmade-vm'),
                                 *[str(project/f'{folder}/build/{bot}.bin') for bot in bots]],
                                cwd=project, capture_output=True, timeout=30)
        assert result.returncode == 0 and result.stdout.count(b'accepted=200 timeout=0 invalid=0 VM-error=0') == 2, result
    result = subprocess.run(['console/build/game-console'], cwd=project, input=b'2\nq\nq\n',
                            capture_output=True, timeout=3)
    assert result.returncode == 0 and b'Treasure - select bots' in result.stdout
    result = subprocess.run(['console/build/game-console'], cwd=project, input=b'3\nqq\n',
                            capture_output=True, timeout=3)
    assert result.returncode == 0 and not result.stderr and b'Returned from Maze.' in result.stdout, result
    assert device.registered_state(registered) == before
    device.verify_sources(project, manifest)
    (project/'console/menu.c').write_text('changed')
    refused(lambda: device.verify_sources(project, manifest))
    print('PASS isolated rebuild of all five components, both 200-turn games, maze/menu round trip, original registrations preserved and source recheck', flush=True)
print('PASS 3 device preparation groups, 0 failures', flush=True)
