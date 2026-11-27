"""Apply/restore contracts with a fake root and simulated systemd, no sudo."""
from pathlib import Path
import json
import os
import subprocess
import tempfile

import manage_device_menu as menu

ROOT = Path(__file__).resolve().parent.parent
PROJECT = '/home/pi/vm-game-console-stage5-0dacbb6eaad2/project'
BACKUP = '/var/lib/paintbot-menu/console-0dacbb6eaad2'


class Fake(menu.System):
    def __init__(self, root):
        super().__init__(root)
        self.calls = []
        self.fail_restart = False
        self.fail_verify = False
        for name, data in ((menu.UNIT, (ROOT/'game/systemd/paintbot-menu.service').read_bytes()),
                           (menu.LOGGING, (ROOT/'game/systemd/80-paintbot-logging.conf').read_bytes()),
                           (PROJECT+'/console/90-game-console.conf', menu.candidate(PROJECT)),
                           (PROJECT+'/console/build/game-console', b'fixture'),
                           (str(Path(PROJECT).parent/'result.json'), json.dumps({
                               'checks_passed': True, 'project': PROJECT, 'service_changed': False}).encode())):
            path = self.path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.path(PROJECT+'/console/build/game-console').chmod(0o755)
        self.path('/var/lib/paintbot-menu').mkdir(parents=True)

    def run(self, args):
        self.calls.append(args)
        if args[0] == 'systemd-analyze':
            if self.fail_verify:
                raise RuntimeError('fixture verify failure')
            assert self.path(PROJECT+'/console/build/game-console').as_posix() not in Path(args[-1]).read_text()
            assert 'ExecStart='+PROJECT+'/console/build/game-console' in Path(args[-1]).read_text()
            return ''
        if args[1] == 'restart' and self.fail_restart:
            self.fail_restart = False
            raise subprocess.CalledProcessError(1, args)
        if args[1] == 'is-active':
            return 'active'
        if args[1] == 'is-enabled':
            return 'enabled'
        if args[1] == 'show':
            field = args[4]
            if field == 'WorkingDirectory':
                return PROJECT if self.path(menu.DROPIN).exists() else '/home/pi/paintbot-vm'
            return {'User': 'pi', 'LogNamespace': 'paintbot', 'DropInPaths': menu.LOGGING}[field]
        assert args[1] in ('restart', 'daemon-reload')
        return ''


def refused(function):
    try:
        function()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return
    raise AssertionError('expected refusal')


with tempfile.TemporaryDirectory(prefix='console-service-test-') as directory:
    root = Path(directory).resolve()
    system = Fake(root/'normal')
    original, logging = system.read(menu.UNIT), system.read(menu.LOGGING)
    menu.install(system, PROJECT)
    assert system.read(menu.DROPIN) == menu.candidate(PROJECT)
    assert system.read(menu.UNIT) == original and system.read(menu.LOGGING) == logging
    assert system.path(BACKUP).stat().st_mode & 0o777 == 0o700
    assert system.path(menu.DROPIN).stat().st_mode & 0o777 == 0o644
    assert not list(system.path(menu.DROPIN).parent.glob('.game-console-*'))
    refused(lambda: menu.install(system, PROJECT))
    menu.restore(system, BACKUP)
    assert not system.path(menu.DROPIN).exists()
    assert system.read(menu.UNIT) == original and system.read(menu.LOGGING) == logging
    assert json.loads(system.read(BACKUP+'/state.json'))['phase'] == 'restored'
    assert not any('enable' in call or 'disable' in call or 'reboot' in call for call in system.calls)
    print('PASS install/restore: only own drop-in, exact baseline/log preservation, modes and no reboot/getty changes')

    for name in (menu.UNIT, menu.LOGGING, PROJECT+'/console/90-game-console.conf'):
        system = Fake(root/('modified-'+str(len(list(root.iterdir())))))
        system.path(name).write_bytes(b'changed')
        refused(lambda: menu.install(system, PROJECT))
        assert not system.path(menu.DROPIN).exists()
        assert not any(call[1] == 'restart' for call in system.calls)
    system = Fake(root/'linked')
    system.path(menu.DROPIN).symlink_to(system.path(menu.LOGGING))
    refused(lambda: menu.install(system, PROJECT))
    assert system.path(menu.DROPIN).is_symlink()
    print('PASS changed service/log/candidate and pre-existing linked drop-in refused before changes')

    system = Fake(root/'verify-failure')
    system.fail_verify = True
    refused(lambda: menu.install(system, PROJECT))
    assert not system.path(menu.DROPIN).exists()
    assert not any(call[1] == 'restart' for call in system.calls)
    system = Fake(root/'restart-failure')
    system.fail_restart = True
    refused(lambda: menu.install(system, PROJECT))
    assert not system.path(menu.DROPIN).exists()
    assert json.loads(system.read(BACKUP+'/state.json'))['phase'] == 'rolled-back'
    assert sum(call[1] == 'restart' for call in system.calls) == 2
    print('PASS verification failure leaves live settings untouched; restart failure restores original service')

    system = Fake(root/'admin-change')
    menu.install(system, PROJECT)
    system.path(menu.DROPIN).write_bytes(b'administrator change')
    refused(lambda: menu.restore(system, BACKUP))
    assert system.read(menu.DROPIN) == b'administrator change'
    system = Fake(root/'interrupted')
    menu.install(system, PROJECT)
    state = json.loads(system.read(BACKUP+'/state.json'))
    state['phase'] = 'prepared'
    system.state(BACKUP, state)
    menu.restore(system, BACKUP)
    assert not system.path(menu.DROPIN).exists()
    system = Fake(root/'restore-retry')
    menu.install(system, PROJECT)
    system.fail_restart = True
    refused(lambda: menu.restore(system, BACKUP))
    assert not system.path(menu.DROPIN).exists()
    menu.restore(system, BACKUP)
    assert json.loads(system.read(BACKUP+'/state.json'))['phase'] == 'restored'
    print('PASS restore refuses administrator changes and supports interrupted/retried recovery')
print('PASS 4 service setup groups, 0 failures')
