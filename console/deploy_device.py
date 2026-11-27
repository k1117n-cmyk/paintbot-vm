"""Package reviewed sources and run isolated device checks with interactive SSH auth."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent.parent


def sources(root):
    selected = []
    for folder in ('vm', 'treasure', 'maze', 'dotchase'):
        selected.extend(p for p in (root/folder).rglob('*') if p.is_file() and
                        not set(p.relative_to(root/folder).parts) & {'build', '__pycache__', '.git'} and
                        (p.suffix in {'.c', '.h', '.py', '.asm', '.md'} or p.name in {'Makefile', 'LICENSE'}))
    selected.extend(root/'game'/name for name in (
        'Makefile', 'game.c', 'game.h', 'host.c', 'display.c', 'display.h', 'registry.c',
        'bot_runner.c', 'bot_runner.h', 'test_game.c', 'test_host.c', 'test_display.c',
        'PLAYING.md', 'REGISTRATION.md'))
    selected.extend((root/'game/bots').glob('*.asm'))
    selected.extend(root/'console'/name for name in ('Makefile', 'menu.c', 'test_menu.py', 'README.md', 'DEVICE.md'))
    return sorted(selected)


def prepare(root, output):
    files = {}
    for path in sources(root):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('not a regular source: ' + str(path))
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files['MANIFEST.json'] = (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode()
    archive = output/'source.tar'
    with tarfile.open(archive, 'w') as bundle:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o600, 0
            bundle.addfile(entry, io.BytesIO(data))
    shutil.copyfile(root/'console/device_stage5.py', output/'device_stage5.py')
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest(), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default='pi@raspberrypi.local')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9_][A-Za-z0-9_.-]*', args.target):
        parser.error('expected user@host')
    output = Path(tempfile.mkdtemp(prefix='vm-console-stage5-')).resolve()
    archive, digest, manifest = prepare(ROOT, output)
    print('PACKAGE=' + str(output), flush=True)
    print('ARCHIVE_SHA256=' + digest + '\nSOURCES=' + str(len(manifest)), flush=True)
    if args.prepare_only:
        return
    remote = '/home/pi/vm-game-console-stage5-' + uuid.uuid4().hex[:12]
    print('REMOTE=' + remote, flush=True)
    print('SSH passwords are entered in the terminal; no service settings will be changed.', flush=True)
    subprocess.run(['ssh', '-o', 'ConnectTimeout=10', args.target,
                    'umask 077; mkdir -m 700 ' + shlex.quote(remote)], check=True)
    subprocess.run(['scp', str(archive), str(output/'device_stage5.py'), args.target+':'+remote+'/'], check=True)
    command = 'python3 -u ' + shlex.quote(remote+'/device_stage5.py') + ' ' + shlex.quote(remote+'/source.tar') + ' ' + digest
    print('LOG=' + str(output/'device-check.log'), flush=True)
    with (output/'device-check.log').open('wb') as log:
        child = subprocess.Popen(['ssh', '-o', 'ConnectTimeout=10', args.target, command],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line.decode(errors='replace'), end='', flush=True)
        result = child.wait()
    print('DEPLOY_EXIT=' + str(result), flush=True)
    if result:
        raise SystemExit(result)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print('DEPLOY_ERROR=' + str(error), flush=True)
        raise SystemExit(1)
