"""Apply/restore only the reviewed console drop-in. Run on Zero with sudo."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import tempfile

UNIT = '/etc/systemd/system/paintbot-menu.service'
LOGGING = '/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf'
DROPIN = '/etc/systemd/system/paintbot-menu.service.d/90-game-console.conf'
UNIT_SHA = 'dbfb77369b2d31706f562d0d9b596925d380418f461d3c6a4062f181802bfaf9'
LOG_SHA = '14c78b5626c3e2c42f789584000832e69fea8089332bba0ef377e6c9a8ae4fa4'
PROJECT = re.compile(r'/home/pi/vm-game-console-stage5-([0-9a-f]{12})/project\Z')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def candidate(project):
    require(PROJECT.fullmatch(project), 'unexpected release path')
    return ('[Service]\nWorkingDirectory=' + project + '\nExecStart=\nExecStart=' +
            project + '/console/build/game-console\n').encode()


class System:
    def __init__(self, root=Path('/')):
        self.root = root.resolve()

    def path(self, name):
        return self.root / str(name).lstrip('/')

    def read(self, name):
        path = self.path(name)
        for parent in (path, *path.parents):
            require(not parent.is_symlink(), 'linked path: ' + str(parent))
            if parent == self.root:
                break
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 2*1024*1024,
                'expected bounded regular file: ' + str(path))
        return path.read_bytes()

    def run(self, args):
        print('$ ' + ' '.join(args), flush=True)
        result = subprocess.run(args, capture_output=True, text=True, timeout=30,
                                env={**os.environ, 'SYSTEMD_PAGER': 'cat', 'SYSTEMD_COLORS': '0'})
        print(result.stdout + result.stderr, end='', flush=True)
        result.check_returncode()
        return result.stdout.strip()

    def ctl(self, *args):
        return self.run(['systemctl', *args])

    def baseline(self):
        require(sha(self.read(UNIT)) == UNIT_SHA, 'original service changed')
        require(sha(self.read(LOGGING)) == LOG_SHA, 'logging drop-in changed')

    def state(self, backup, state):
        self.path(backup + '/state.json').write_text(json.dumps(state, indent=2) + '\n')


def remove_owned_dropin(system, expected):
    require(system.read(DROPIN) == expected, 'console drop-in changed; refusing removal')
    system.path(DROPIN).unlink()


def install(system, project):
    content = candidate(project)
    system.baseline()
    require(not os.path.lexists(system.path(DROPIN)), 'console drop-in already exists')
    require(system.ctl('show', 'paintbot-menu.service', '-p', 'DropInPaths', '--value') == LOGGING,
            'unexpected service overrides')
    require(system.ctl('is-active', 'paintbot-menu.service') == 'active', 'service is not active')
    require(system.ctl('is-enabled', 'paintbot-menu.service') == 'enabled', 'service is not enabled')
    require(system.ctl('show', 'paintbot-menu.service', '-p', 'WorkingDirectory', '--value') ==
            '/home/pi/paintbot-vm', 'unexpected current working directory')
    require(system.ctl('show', 'paintbot-menu.service', '-p', 'User', '--value') == 'pi', 'unexpected user')
    require(system.ctl('show', 'paintbot-menu.service', '-p', 'LogNamespace', '--value') == 'paintbot',
            'unexpected logging namespace')
    require(system.read(project + '/console/90-game-console.conf') == content, 'candidate differs')
    binary = project + '/console/build/game-console'
    system.read(binary)
    require(os.access(system.path(binary), os.X_OK), 'console is not executable')
    if system.root == Path('/'):
        require(system.path(binary).stat().st_uid == pwd.getpwnam('pi').pw_uid, 'unexpected binary owner')
    result = json.loads(system.read(str(Path(project).parent / 'result.json')))
    require(result.get('checks_passed') is True and result.get('project') == project and
            result.get('service_changed') is False, 'release checks not complete')
    release = PROJECT.fullmatch(project).group(1)
    backup = '/var/lib/paintbot-menu/console-' + release
    store = system.path('/var/lib/paintbot-menu')
    require(store.is_dir() and not store.is_symlink(), 'backup store missing or linked')
    for parent in store.parents:
        require(not parent.is_symlink(), 'linked backup store parent')
        if parent == system.root:
            break
    system.path(backup).mkdir(mode=0o700)  # Never reuse or overwrite an earlier backup.
    for name, source in [('paintbot-menu.service', UNIT), ('80-paintbot-logging.conf', LOGGING)]:
        system.path(backup + '/' + name).write_bytes(system.read(source))
    system.path(backup + '/90-game-console.conf').write_bytes(content)
    state = {'project': project, 'dropin_sha256': sha(content), 'phase': 'prepared'}
    system.state(backup, state)
    verified = system.path(backup + '/verify')
    verified.mkdir()
    merged = system.read(UNIT).decode().replace('WorkingDirectory=/home/pi/paintbot-vm',
                                              'WorkingDirectory=' + project).replace(
        'ExecStart=/home/pi/paintbot-vm/game/build/paint-bots menu', 'ExecStart=' + binary)
    (verified/'paintbot-menu.service').write_text(merged)
    system.run(['systemd-analyze', 'verify', str(verified/'paintbot-menu.service')])
    # Publish a complete file without overwriting an administrator's concurrent edit.
    published = False
    temporary = None
    try:
        system.baseline()
        fd, name = tempfile.mkstemp(prefix='.game-console-', dir=system.path(DROPIN).parent)
        temporary = Path(name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o644)
        os.link(temporary, system.path(DROPIN))
        published = True
        temporary.unlink()
        system.ctl('daemon-reload')
        system.ctl('restart', 'paintbot-menu.service')
        require(system.ctl('is-active', 'paintbot-menu.service') == 'active', 'console service not active')
        require(system.ctl('show', 'paintbot-menu.service', '-p', 'WorkingDirectory', '--value') == project,
                'working directory not switched')
        require(system.ctl('show', 'paintbot-menu.service', '-p', 'LogNamespace', '--value') == 'paintbot',
                'logging namespace changed')
        state['phase'] = 'installed'
        system.state(backup, state)
    except BaseException:
        if published:
            try:
                remove_owned_dropin(system, content)
                system.ctl('daemon-reload')
                system.ctl('restart', 'paintbot-menu.service')
                require(system.ctl('is-active', 'paintbot-menu.service') == 'active', 'original service inactive')
                state['phase'] = 'rolled-back'
                system.state(backup, state)
                print('ROLLBACK=original-paintbot', flush=True)
            except Exception:
                print('RECOVERY_REQUIRED=' + backup, flush=True)
                raise
        raise
    finally:
        if temporary is not None and os.path.lexists(temporary):
            temporary.unlink()
    print('CONSOLE_BACKUP=' + backup, flush=True)
    print('RESTORE_COMMAND=sudo python3 ' + project + '/console/manage_device_menu.py restore ' + backup, flush=True)
    print('CONSOLE_INSTALL_EXIT=0', flush=True)


def restore(system, backup):
    require(re.fullmatch(r'/var/lib/paintbot-menu/console-[0-9a-f]{12}', backup), 'unexpected backup path')
    system.baseline()
    state = json.loads(system.read(backup + '/state.json'))
    content = candidate(state['project'])
    require(backup.endswith(PROJECT.fullmatch(state['project']).group(1)), 'backup/release mismatch')
    require(state['phase'] in ('prepared', 'installed') and state['dropin_sha256'] == sha(content), 'backup state differs')
    require(system.read(backup + '/paintbot-menu.service') == system.read(UNIT) and
            system.read(backup + '/80-paintbot-logging.conf') == system.read(LOGGING), 'baseline/backup differs')
    if os.path.lexists(system.path(DROPIN)):
        remove_owned_dropin(system, content)
    system.ctl('daemon-reload')
    system.ctl('restart', 'paintbot-menu.service')
    require(system.ctl('is-active', 'paintbot-menu.service') == 'active', 'original service inactive')
    require(system.ctl('show', 'paintbot-menu.service', '-p', 'WorkingDirectory', '--value') ==
            '/home/pi/paintbot-vm', 'original working directory not restored')
    state['phase'] = 'restored'
    system.state(backup, state)
    print('CONSOLE_RESTORE_EXIT=0', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'restore'])
    parser.add_argument('path')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'sudo is required for systemd changes')
    os.umask(0o077)
    if args.action == 'install':
        install(System(), args.path)
    else:
        restore(System(), args.path)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print('CONSOLE_SETUP_ERROR=' + str(error), flush=True)
        raise SystemExit(1)
