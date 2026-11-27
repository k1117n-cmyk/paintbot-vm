"""Build and check a new isolated release on Zero; never change systemd settings."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile

LIMIT = 4 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def unpack(archive, expected, destination):
    require(archive.is_file() and archive.stat().st_size <= LIMIT, 'invalid archive size')
    data = archive.read_bytes()
    require(sha(data) == expected, 'archive hash mismatch')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as bundle:
        members = bundle.getmembers()
        require(0 < len(members) <= 128, 'invalid member count')
        total = 0
        for member in members:
            name = member.name
            path = PurePosixPath(name)
            require(member.isfile() and not path.is_absolute() and '..' not in path.parts
                    and str(path) == name and '\\' not in name and name not in files,
                    'invalid/duplicate archive member: ' + name)
            require(name == 'MANIFEST.json' or (len(path.parts) >= 2 and
                    path.parts[0] in ('vm', 'game', 'treasure', 'maze', 'dotchase', 'console') and
                    not set(path.parts[1:]) & {'build', 'registered', '.git', '__pycache__'}),
                    'unexpected archive path: ' + name)
            total += member.size
            require(0 <= member.size <= 1024 * 1024 and total <= LIMIT, 'archive contents too large')
            files[name] = bundle.extractfile(member).read()
    manifest = json.loads(files.pop('MANIFEST.json'))
    require(manifest == {name: sha(data) for name, data in files.items()}, 'manifest mismatch')
    require(not os.path.lexists(destination), 'release destination already exists')
    destination.mkdir(mode=0o700)
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    return manifest


def registered_state(directory):
    require(directory.is_dir() and not directory.is_symlink(), 'registered directory missing or linked')
    entries = sorted(directory.iterdir())
    require(len(entries) <= 256, 'too many registered files')
    state = {}
    total = 0
    for path in entries:
        require(path.is_file() and not path.is_symlink(), 'unexpected registered entry: ' + str(path))
        size = path.stat().st_size
        total += size
        require(size <= 1024 * 1024 and total <= 64 * 1024 * 1024, 'registered files too large')
        state[path.name] = sha(path.read_bytes())
    return state


def verify_sources(project, manifest):
    require(all((project/name).is_file() and not (project/name).is_symlink() and
                sha((project/name).read_bytes()) == digest for name, digest in manifest.items()),
            'release sources changed during checks')


def run(args, project):
    print('$ ' + ' '.join(args), flush=True)
    subprocess.run(args, cwd=project, check=True, timeout=300,
                   env={**os.environ, 'PYTHONUNBUFFERED': '1',
                        'SYSTEMD_PAGER': 'cat', 'SYSTEMD_COLORS': '0'})


def main():
    require(len(sys.argv) == 3, 'usage: device_stage5.py source.tar sha256')
    home = Path.home()
    require(platform.system() == 'Linux' and platform.machine() in ('armv7l', 'aarch64'),
            'expected Raspberry Pi Linux')
    require(home == Path('/home/pi') and os.getuid() != 0, 'run as pi, without sudo')
    archive = Path(sys.argv[1]).absolute()
    require(not archive.is_symlink() and archive.parent.parent == home and
            archive.parent.name.startswith('vm-game-console-stage5-') and
            not archive.parent.is_symlink(), 'unexpected staging location')
    original = home / 'paintbot-vm'
    require(original.is_dir() and not original.is_symlink(), 'original project missing or linked')
    registered = original / 'registered'
    before = registered_state(registered)
    project = archive.parent / 'project'
    manifest = unpack(archive, sys.argv[2], project)
    # Keep the existing Mini/Air registration destination; do not copy or edit bots.
    (project/'registered').symlink_to(registered, target_is_directory=True)
    print('DEVICE=' + platform.platform(), flush=True)
    print('PROJECT=' + str(project), flush=True)
    print('REGISTERED_BEFORE=' + json.dumps(before, sort_keys=True), flush=True)
    run(['systemctl', 'show', 'paintbot-menu.service', '-p', 'User', '-p', 'ExecStart',
         '-p', 'WorkingDirectory', '-p', 'DropInPaths', '-p', 'LogNamespace', '-p', 'ActiveState'], project)
    for folder in ('vm', 'game', 'treasure', 'maze', 'dotchase', 'console'):
        run(['make', '-C', folder], project)
    run(['vm/build/handmade-vm', '--self-test'], project)
    run(['make', '-C', 'game', 'test', 'test-host', 'test-display'], project)
    run(['make', '-C', 'treasure', 'test'], project)
    run(['make', '-C', 'maze', 'test'], project)
    run(['python3', '-B', 'vm/test_game_io.py'], project)
    run(['make', '-C', 'dotchase', 'test'], project)
    run(['make', '-C', 'console', 'test'], project)
    run(['game/build/paint-bots', 'list'], project)
    verify_sources(project, manifest)
    require(registered_state(registered) == before, 'original registered files changed')
    candidate = project/'console/90-game-console.conf'
    candidate.write_text('[Service]\nWorkingDirectory=' + str(project) + '\nExecStart=\nExecStart=' +
                         str(project/'console/build/game-console') + '\n')
    (archive.parent/'result.json').write_text(json.dumps({
        'project': str(project), 'source_sha256': sys.argv[2], 'sources': len(manifest),
        'registered': before, 'checks_passed': True, 'service_changed': False,
        'candidate_dropin': str(candidate),
    }, indent=2) + '\n')
    print('SOURCE_MATCH=' + str(len(manifest)), flush=True)
    print('REGISTERED_UNCHANGED=' + str(len(before)), flush=True)
    print('CANDIDATE_DROPIN=' + str(candidate), flush=True)
    print('MANUAL_COMMAND=cd ' + str(project) + ' && console/build/game-console', flush=True)
    print('SERVICE_CHANGED=no\nSTAGE5_EXIT=0', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, tarfile.TarError,
            subprocess.SubprocessError) as error:
        print('STAGE5_ERROR=' + str(error), file=sys.stderr, flush=True)
        print('STAGE5_EXIT=1', flush=True)
        sys.exit(1)
