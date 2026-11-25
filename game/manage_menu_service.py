"""Prepare/check/install/restore the reviewed tty1 service. Install/restore need sudo."""
from pathlib import Path
import argparse
import fcntl
import hashlib
import json
import os
import platform
import pwd
import stat
import subprocess
import sys
import tempfile

MENU = 'paintbot-menu.service'
GETTY = 'getty@tty1.service'
BINARY_SHA = 'b42d95e477a17cd1593178da4b97b9d3905dc466df205a5cb4e75a4c25535391'
UNIT_SHA = 'dbfb77369b2d31706f562d0d9b596925d380418f461d3c6a4062f181802bfaf9'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class System:
    def __init__(self, root=Path('/')):
        self.root = root
        self.unit = self.path('/etc/systemd/system/' + MENU)
        self.store = self.path('/var/lib/paintbot-menu')
        self.project = self.path('/home/pi/paintbot-vm')
        self.expected_binary = BINARY_SHA

    def path(self, absolute):
        return self.root / absolute.lstrip('/')

    def run(self, args, check=True):
        print('$ ' + ' '.join(args), flush=True)
        r = subprocess.run(args, capture_output=True, text=True, timeout=30,
                           env={**os.environ, 'SYSTEMD_PAGER': 'cat', 'SYSTEMD_COLORS': '0'})
        print(r.stdout + r.stderr, end='', flush=True)
        print(f'EXIT={r.returncode}', flush=True)
        if check:
            r.check_returncode()
        return r

    def ctl(self, *args, check=True):
        return self.run(['/usr/bin/systemctl', *args], check=check)

    def account(self):
        return pwd.getpwnam('pi')

    def terminal(self):
        require(stat.S_ISCHR(self.path('/dev/tty1').stat().st_mode), '/dev/tty1 is not a terminal')
        require(self.path('/sys/class/tty/tty0/active').read_text().strip() == 'tty1',
                'active virtual console changed; inspect before installation')

    def preflight(self, source):
        require(source.is_file() and not source.is_symlink() and digest(source) == UNIT_SHA,
                'service file differs from reviewed version')
        require(not os.path.lexists(self.unit), 'service destination already exists; refusing overwrite')
        menu_state = self.ctl('is-enabled', MENU, check=False)
        require(menu_state.returncode == 4 and menu_state.stdout.strip() == 'not-found',
                'a menu service already exists')
        require(self.ctl('get-default').stdout.strip() == 'multi-user.target', 'default target changed')
        require(self.ctl('is-enabled', GETTY).stdout.strip() == 'enabled', 'getty is not enabled')
        require(self.ctl('is-active', GETTY).stdout.strip() == 'active', 'getty is not active')
        require(not self.ctl('show', GETTY, '-p', 'DropInPaths', '--value').stdout.strip(),
                'getty drop-ins changed; inspect before installation')
        account = self.account()
        require(account.pw_uid != 0 and account.pw_dir == '/home/pi', 'unexpected pi account')
        require(self.project.stat().st_uid == account.pw_uid, 'project is not owned by pi')
        program = self.project / 'game/build/paint-bots'
        require(program.is_file() and os.access(program, os.X_OK) and digest(program) == self.expected_binary,
                'paint-bots differs from verified device binary')
        self.terminal()
        self.run(['/usr/bin/systemd-analyze', 'verify', str(source)])
        return self.ctl('cat', GETTY).stdout


def write_state(backup, state):
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=backup)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, backup / 'state.json')
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def publish_unit(system, data):
    fd, temporary = tempfile.mkstemp(prefix='.paintbot-menu-', dir=system.unit.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), 0o644)
        # Complete file, no overwrite even if another administrator created it.
        os.link(temporary, system.unit)
    finally:
        os.unlink(temporary)


def restore(system, backup):
    # Logging restoration needs the base menu unit. Refuse before any mutation,
    # including when only one file or an interrupted-install marker remains.
    for path in (system.path('/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf'),
                 system.path('/etc/systemd/journald@paintbot.conf'),
                 system.store / 'active-logging'):
        require(not os.path.lexists(path),
                'restore logging first with manage_logging.py restore: ' + str(path))
    require(backup.parent.resolve() == system.store.resolve() and not backup.is_symlink(),
            'backup must be an original setup directory in /var/lib/paintbot-menu')
    info = backup.stat()
    require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0, 'unsafe backup ownership/permissions')
    state = json.loads((backup / 'state.json').read_text())
    require(state['unit_sha256'] == UNIT_SHA and state['getty_enabled'] is True and
            state['getty_active'] is True, 'unsupported backup state')
    if state['state'] in ('restored', 'failed-rolled-back'):
        require(not os.path.lexists(system.unit), 'a later service exists; refusing old backup')
        print('ALREADY_RESTORED', flush=True)
        return
    require(state['state'] in ('prepared', 'applied', 'recovery-required'), 'unknown backup state')
    if os.path.lexists(system.unit):
        require(not system.unit.is_symlink() and system.unit.is_file() and digest(system.unit) == UNIT_SHA,
                'installed service changed; inspect before restoring')
    installed = os.path.lexists(system.unit)
    system.ctl('stop', MENU, check=installed)
    system.ctl('disable', MENU, check=installed)
    if os.path.lexists(system.unit):
        system.unit.unlink()
    system.ctl('daemon-reload')
    system.ctl('enable', GETTY)
    system.ctl('start', GETTY)
    require(system.ctl('is-enabled', GETTY).stdout.strip() == 'enabled' and
            system.ctl('is-active', GETTY).stdout.strip() == 'active', 'getty restore failed')
    state['state'] = 'restored'
    write_state(backup, state)
    print('RESTORE_EXIT=0', flush=True)


def install(system, source):
    getty_definition = system.preflight(source)
    system.store.mkdir(mode=0o700, exist_ok=True)
    info = system.store.stat()
    require(not system.store.is_symlink() and info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0,
            'unsafe backup store ownership/permissions')
    backup = Path(tempfile.mkdtemp(prefix='setup-', dir=system.store))
    state = {'state': 'prepared', 'unit_sha256': UNIT_SHA, 'getty_enabled': True, 'getty_active': True}
    (backup / 'getty-before.txt').write_text(getty_definition)
    (backup / MENU).write_bytes(source.read_bytes())
    write_state(backup, state)
    print('SETUP_BACKUP=' + str(backup), flush=True)
    published = False
    try:
        publish_unit(system, source.read_bytes())
        published = True
        system.ctl('daemon-reload')
        system.ctl('disable', GETTY)
        system.ctl('enable', MENU)
        # Conflicts + After stop getty (and its tty1 login) before starting menu.
        system.ctl('start', MENU)
        require(system.ctl('is-active', MENU).stdout.strip() == 'active', 'menu did not start')
        require(system.ctl('is-enabled', MENU).stdout.strip() == 'enabled', 'menu is not enabled')
        require(system.ctl('is-active', GETTY, check=False).stdout.strip() != 'active', 'getty still active')
        require(system.ctl('is-enabled', GETTY, check=False).stdout.strip() == 'disabled', 'getty still enabled')
        state['state'] = 'applied'
        write_state(backup, state)
    except BaseException:
        if published:
            try:
                restore(system, backup)
                state['state'] = 'failed-rolled-back'
            except BaseException as error:
                state['state'] = 'recovery-required'
                print('RECOVERY_FAILED: ' + str(error), file=sys.stderr, flush=True)
            write_state(backup, state)
        else:
            state['state'] = 'failed-before-change'
            write_state(backup, state)
        raise
    print('RESTORE_COMMAND=sudo python3 game/manage_menu_service.py restore ' + str(backup), flush=True)
    print('MENU_SETUP_EXIT=0', flush=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'install', 'restore'])
    parser.add_argument('backup', nargs='?', type=Path)
    args = parser.parse_args()
    require(platform.system() == 'Linux', 'run on the Raspberry Pi via SSH')
    ssh_terminal = os.isatty(0) and os.ttyname(0).startswith('/dev/pts/')
    require(bool(os.environ.get('SSH_CONNECTION')) or ssh_terminal, 'run from an SSH session, not tty1')
    system = System()
    source = Path(__file__).resolve().parent / 'systemd' / MENU
    if args.action == 'check':
        require(args.backup is None, 'check takes no backup argument')
        system.preflight(source)
        print('MENU_CHECK_EXIT=0 (read-only; not installed)')
        return
    require(os.geteuid() == 0, 'install/restore require sudo')
    require((args.action == 'restore') == (args.backup is not None), 'restore needs its setup backup path')
    fd = os.open('/run/paintbot-menu-setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'install':
            install(system, source)
        else:
            restore(system, args.backup)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyError, ValueError) as error:
        print('MENU_SETUP_ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
