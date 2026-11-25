"""Install/undo only the reviewed paintbot journal namespace, via SSH + sudo."""
from pathlib import Path
import argparse
import fcntl
import json
import os
import platform
import stat
import tempfile
import uuid

from manage_menu_service import System as MenuSystem, MENU, GETTY, UNIT_SHA, digest, require, write_state

DROPIN = '/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf'
JOURNAL = '/etc/systemd/journald@paintbot.conf'
NAMESPACE_UNITS = ('systemd-journald@paintbot.service', 'systemd-journald@paintbot.socket',
                   'systemd-journald-varlink@paintbot.socket')
CONTENTS = {
    DROPIN: b'[Service]\nLogNamespace=paintbot\n',
    JOURNAL: (b'[Journal]\nStorage=persistent\nSplitMode=none\nSystemMaxUse=50M\n'
              b'SystemMaxFileSize=8M\nSystemMaxFiles=8\nRuntimeMaxUse=8M\n'
              b'RuntimeMaxFileSize=2M\nMaxRetentionSec=7day\nMaxFileSec=1day\n'
              b'ReadKMsg=no\nForwardToSyslog=no\nForwardToKMsg=no\n'
              b'ForwardToConsole=no\nForwardToWall=no\n'),
}


class System(MenuSystem):
    def __init__(self, root=Path('/')):
        super().__init__(root.resolve())
        self.configuration_owner = 0

    def check_directory(self, directory):
        info = self.safe(directory).stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == self.configuration_owner and
                info.st_mode & 0o022 == 0, 'unsafe configuration directory: ' + str(directory))

    def safe(self, path):
        current = self.root
        for part in path.relative_to(self.root).parts:
            current /= part
            require(not current.is_symlink(), 'symlink in configuration path: ' + str(current))
        return path

    def reviewed(self):
        require(self.safe(self.unit).is_file() and digest(self.unit) == UNIT_SHA,
                'base menu unit differs from reviewed installed version')
        for name, data in CONTENTS.items():
            source = Path(__file__).parent / 'systemd' / Path(name).name
            require(source.is_file() and not source.is_symlink() and source.read_bytes() == data,
                    'logging source differs from reviewed configuration')

    def no_overrides(self, installed=False):
        permitted = {self.path(p) for p in CONTENTS} if installed else set()
        for prefix in ('/etc', '/run', '/usr/local/lib', '/usr/lib'):
            for relative in ('systemd/system/paintbot-menu.service.d',
                             'systemd/journald@paintbot.conf.d'):
                directory = self.safe(self.path(prefix + '/' + relative))
                require(not directory.exists() or not any(p not in permitted for p in directory.glob('*.conf')),
                        'unreviewed namespace/menu configuration: ' + str(directory))
            main = self.safe(self.path(prefix + '/systemd/journald@paintbot.conf'))
            require(not os.path.lexists(main) or main in permitted, 'unreviewed journal namespace configuration')

    def preflight(self, private=True):
        self.reviewed()
        program = self.safe(self.project / 'game/build/paint-bots')
        require(program.is_file() and os.access(program, os.X_OK) and digest(program) == self.expected_binary,
                'menu executable differs from the verified device binary')
        if private:
            require(not os.path.lexists(self.safe(self.store / 'active-logging')),
                    'previous logging installation requires restoration/inspection')
        else:
            print('PRIVATE_STATE_CHECK=deferred until sudo install', flush=True)
        require(self.ctl('is-active', MENU).stdout.strip() == 'active', 'menu is not active')
        require(self.ctl('is-enabled', MENU).stdout.strip() == 'enabled', 'menu is not enabled')
        require(self.ctl('is-active', GETTY, check=False).stdout.strip() == 'inactive', 'getty changed')
        require(self.ctl('is-enabled', GETTY, check=False).stdout.strip() == 'disabled', 'getty changed')
        require(not self.ctl('show', MENU, '-p', 'DropInPaths', '--value').stdout.strip(),
                'existing menu drop-ins; inspect before installing')
        for absolute in CONTENTS:
            path = self.safe(self.path(absolute))
            require(not os.path.lexists(path), 'configuration already exists: ' + absolute)
            self.check_directory(path.parent if path.parent.exists() else path.parent.parent)
        self.no_overrides()
        for unit in NAMESPACE_UNITS:
            require(self.ctl('is-active', unit, check=False).stdout.strip() == 'inactive',
                    'namespace is already in use: ' + unit)
            require(bool(self.ctl('show', unit, '-p', 'FragmentPath', '--value').stdout.strip()),
                    'namespace template missing: ' + unit)
        with tempfile.TemporaryDirectory(prefix='paintbot-log-verify-') as directory:
            candidate = Path(directory) / MENU
            candidate.write_bytes(self.unit.read_bytes() + b'\n' + CONTENTS[DROPIN])
            self.run(['/usr/bin/systemd-analyze', 'verify', str(candidate)])

    def publish(self, absolute, data):
        path = self.safe(self.path(absolute))
        try:
            path.parent.mkdir(mode=0o755)
        except FileExistsError:
            pass
        else:
            # mkdir's mode is filtered by umask; fix only the directory we created.
            path.parent.chmod(0o755)
        self.check_directory(path.parent)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def smoke(self):
        token = 'paintbot-log-probe-' + uuid.uuid4().hex
        self.run(['/usr/bin/systemd-run', '--quiet', '--wait', '--collect',
                  '--unit=' + token, '--property=LogNamespace=paintbot',
                  '--property=User=pi', '--property=StandardOutput=journal',
                  '/usr/bin/printf', token + '\n'])
        self.run(['/usr/bin/journalctl', '--namespace=paintbot', '--sync'])
        result = self.run(['/usr/bin/journalctl', '--namespace=paintbot', '--no-pager', '-o', 'cat', '-n', '30'])
        require(token in result.stdout, 'namespace write/read probe did not appear')
        self.run(['/usr/bin/journalctl', '--namespace=paintbot', '--verify'])
        self.run(['/usr/bin/journalctl', '--namespace=paintbot', '--disk-usage'])
        self.run(['/usr/bin/systemd-analyze', 'cat-config', 'systemd/journald@paintbot.conf'])

    def check_applied(self, probe=False):
        self.reviewed()
        self.no_overrides(installed=True)
        for absolute, data in CONTENTS.items():
            path = self.safe(self.path(absolute))
            require(path.is_file() and path.read_bytes() == data, 'logging configuration changed: ' + absolute)
        require(self.ctl('show', MENU, '-p', 'LogNamespace', '--value').stdout.strip() == 'paintbot',
                'effective namespace is not paintbot')
        require(self.ctl('show', MENU, '-p', 'DropInPaths', '--value').stdout.split() == [str(self.path(DROPIN))],
                'effective menu drop-ins differ from reviewed configuration')
        require(self.ctl('is-active', MENU).stdout.strip() == 'active', 'menu did not start')
        require(self.ctl('is-enabled', MENU).stdout.strip() == 'enabled', 'menu enable state changed')
        require(self.ctl('is-active', GETTY, check=False).stdout.strip() == 'inactive', 'getty changed')
        require(self.ctl('is-enabled', GETTY, check=False).stdout.strip() == 'disabled', 'getty changed')
        require(self.ctl('is-active', NAMESPACE_UNITS[0]).stdout.strip() == 'active', 'namespace journal not active')
        if probe:
            self.smoke()


def restore(system, backup):
    require(backup.parent.resolve() == system.store.resolve() and not backup.is_symlink(),
            'use the original logging backup in /var/lib/paintbot-menu')
    info = backup.stat()
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, 'unsafe backup directory')
    state_path = system.safe(backup / 'state.json')
    state = json.loads(state_path.read_text())
    require(state.get('kind') == 'logging-v1' and state.get('base_sha256') == UNIT_SHA,
            'not a supported logging backup')
    require(state.get('state') in ('prepared', 'applied', 'recovery-required', 'restored'), 'unknown backup state')
    system.reviewed()
    marker = system.safe(system.store / 'active-logging')
    if state['state'] == 'restored':
        require(not any(os.path.lexists(system.path(name)) for name in CONTENTS) and
                (not os.path.lexists(marker) or marker.read_text() == backup.name),
                'later logging installation exists; refusing old backup')
        if marker.exists():
            marker.unlink()  # finish a previous restore interrupted after its state write
        return
    require(marker.is_file() and marker.read_text() == backup.name, 'backup is not the active logging installation')
    # Validate ALL destinations before stopping/removing anything.
    for absolute, data in CONTENTS.items():
        path = system.safe(system.path(absolute))
        require(not os.path.lexists(path) or (path.is_file() and path.read_bytes() == data),
                'configuration was edited; refusing removal: ' + absolute)
    system.ctl('stop', MENU)
    for absolute in CONTENTS:
        path = system.path(absolute)
        if path.exists():
            path.unlink()
    system.ctl('daemon-reload')
    system.ctl('start', MENU)
    require(system.ctl('is-active', MENU).stdout.strip() == 'active', 'original menu did not restart')
    system.ctl('stop', *NAMESPACE_UNITS)
    state['state'] = 'restored'
    write_state(backup, state)
    marker.unlink()
    print('LOG_RESTORE_EXIT=0 (original menu restored; journal data retained)', flush=True)


def install(system):
    system.preflight()
    system.safe(system.store).mkdir(mode=0o700, parents=True, exist_ok=True)
    info = system.store.stat()
    require(info.st_uid == os.geteuid() and info.st_mode & 0o022 == 0, 'unsafe logging state store')
    backup = Path(tempfile.mkdtemp(prefix='logging-', dir=system.store))
    state = {'kind': 'logging-v1', 'base_sha256': UNIT_SHA, 'state': 'prepared'}
    write_state(backup, state)
    for absolute, data in CONTENTS.items():
        (backup / Path(absolute).name).write_bytes(data)
    print('LOG_SETUP_BACKUP=' + str(backup), flush=True)
    system.publish('/var/lib/paintbot-menu/active-logging', backup.name.encode())
    try:
        for absolute, data in CONTENTS.items():
            system.publish(absolute, data)
        system.ctl('daemon-reload')
        system.ctl('restart', MENU)
        system.check_applied(probe=True)
        state['state'] = 'applied'
        write_state(backup, state)
    except BaseException:
        try:
            restore(system, backup)
        except BaseException as error:
            state['state'] = 'recovery-required'
            write_state(backup, state)
            print('LOG_RECOVERY_REQUIRED=' + str(backup) + ' ' + str(error), flush=True)
        raise
    print('LOG_RESTORE_COMMAND=sudo python3 game/manage_logging.py restore ' + str(backup), flush=True)
    print('LOG_SETUP_EXIT=0 (no OS reboot)', flush=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'install', 'status', 'restore'))
    parser.add_argument('backup', nargs='?', type=Path)
    args = parser.parse_args()
    require(platform.system() == 'Linux', 'run on the Raspberry Pi')
    ssh_terminal = os.isatty(0) and os.ttyname(0).startswith('/dev/pts/')
    require(bool(os.environ.get('SSH_CONNECTION')) or ssh_terminal, 'run via SSH, not tty1')
    require((args.action == 'restore') == (args.backup is not None), 'only restore takes a backup path')
    system = System()
    if args.action == 'check':
        system.preflight(private=os.geteuid() == 0)
        print('LOG_CHECK_EXIT=0 (read-only)')
        return
    require(os.geteuid() == 0, 'install/status/restore require sudo')
    fd = os.open('/run/paintbot-menu-setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'install':
            install(system)
        elif args.action == 'restore':
            restore(system, args.backup)
        else:
            system.check_applied(probe=True)
            print('LOG_STATUS_EXIT=0')
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('LOG_ERROR: ' + str(error))
