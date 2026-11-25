"""Service install/restore transactions with a fake system manager in a temp root.
No actual systemd/privilege/configuration changes are made by these tests.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import configparser
import hashlib
import json
import os
import subprocess
import tempfile
import sys
sys.dont_write_bytecode = True
import manage_menu_service as service

SOURCE = Path(__file__).parent / 'systemd' / service.MENU


class FakeSystem(service.System):
    def __init__(self, root):
        super().__init__(root)
        self.enabled = {service.GETTY: True, service.MENU: False}
        self.active = {service.GETTY: True, service.MENU: False}
        self.calls = []
        self.fail = None
        self.default_target = 'multi-user.target'
        self.dropins = ''
        self.project.mkdir(parents=True)
        if os.geteuid() == 0:
            os.chown(self.project, 1000, -1)
        self.unit.parent.mkdir(parents=True)
        self.store.parent.mkdir(parents=True)
        program = self.project / 'game/build/paint-bots'
        program.parent.mkdir(parents=True)
        program.write_bytes(b'verified executable')
        program.chmod(0o700)
        self.expected_binary = service.digest(program)
        self.registered = self.project / 'registered/keep.bin'
        self.registered.parent.mkdir()
        self.registered.write_bytes(b'keep this registration')

    def account(self):
        return SimpleNamespace(pw_uid=os.geteuid() or 1000, pw_dir='/home/pi')

    def terminal(self):
        pass  # Device/console discovery is the mocked external dependency.

    def run(self, args, check=True):
        parts = tuple(args[1:])
        self.calls.append(tuple(args))
        if self.fail == parts:
            self.fail = None
            raise subprocess.CalledProcessError(1, args)
        out, code = '', 0
        if args[0] == '/usr/bin/systemd-analyze':
            assert parts == ('verify', str(SOURCE))
        elif parts == ('get-default',):
            out = self.default_target
        elif parts == ('show', service.GETTY, '-p', 'DropInPaths', '--value'):
            out = self.dropins
        elif parts == ('cat', service.GETTY):
            out = '[Service]\nExecStart=/sbin/agetty\n'
        else:
            action, name = parts
            if action == 'is-enabled':
                if name == service.MENU and not self.unit.exists():
                    out, code = 'not-found', 4
                else:
                    out = 'enabled' if self.enabled[name] else 'disabled'
                    code = 0 if self.enabled[name] else 1
            elif action == 'is-active':
                out = 'active' if self.active[name] else 'inactive'
                code = 0 if self.active[name] else 3
            elif action in ('enable', 'disable'):
                self.enabled[name] = action == 'enable'
            elif action in ('start', 'stop'):
                self.active[name] = action == 'start'
                if action == 'start':
                    other = service.GETTY if name == service.MENU else service.MENU
                    self.active[other] = False
            else:
                raise AssertionError(args)
        r = subprocess.CompletedProcess(args, code, out + '\n', '')
        if check:
            r.check_returncode()
        return r

    def ctl(self, *args, check=True):
        if args == ('daemon-reload',):
            self.calls.append(('/usr/bin/systemctl', *args))
            if self.fail == args:
                self.fail = None
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, '', '')
        return super().ctl(*args, check=check)


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='paint-service-') as directory:
        yield FakeSystem(Path(directory))


def must_fail(function):
    try:
        function()
    except (RuntimeError, subprocess.CalledProcessError):
        return
    raise AssertionError('expected refusal')


def original(system):
    assert system.enabled[service.GETTY] and system.active[service.GETTY]
    assert not system.enabled[service.MENU] and not system.active[service.MENU]
    assert not system.unit.exists()
    assert system.registered.read_bytes() == b'keep this registration'


config = configparser.ConfigParser(interpolation=None)
config.read(SOURCE)
assert config['Service']['User'] == 'pi'
assert config['Service']['ExecStart'] == '/home/pi/paintbot-vm/game/build/paint-bots menu'
assert config['Service']['WorkingDirectory'] == '/home/pi/paintbot-vm'
assert config['Service']['StandardInput'] == config['Service']['StandardOutput'] == 'tty'
assert config['Service']['TTYPath'] == '/dev/tty1'
assert config['Unit']['Conflicts'] == service.GETTY and service.GETTY in config['Unit']['After']
assert config['Service']['Restart'] == 'always' and config['Service']['RestartSec'] == '3'
assert config['Unit']['StartLimitIntervalSec'] == '60' and config['Unit']['StartLimitBurst'] == '10'
assert service.digest(SOURCE) == service.UNIT_SHA
print('PASS reviewed unit: pi/menu/tty1, conflict ordering and bounded restart policy')

with fixture() as system:
    system.preflight(SOURCE)
    original(system)
    assert not system.store.exists()
    assert not any(call[1] in ('enable', 'disable', 'start', 'stop') for call in system.calls)
print('PASS preflight is read-only and requests systemd verification before installation')

with fixture() as system:
    backup = service.install(system, SOURCE)
    assert system.unit.read_bytes() == SOURCE.read_bytes()
    assert system.unit.stat().st_mode & 0o777 == 0o644
    assert system.enabled[service.MENU] and system.active[service.MENU]
    assert not system.enabled[service.GETTY] and not system.active[service.GETTY]
    assert json.loads((backup / 'state.json').read_text())['state'] == 'applied'
    assert (backup / 'getty-before.txt').read_text().startswith('[Service]')
    assert (backup / service.MENU).read_bytes() == SOURCE.read_bytes()
    assert system.registered.read_bytes() == b'keep this registration'
    assert system.calls.index(('/usr/bin/systemd-analyze', 'verify', str(SOURCE))) < system.calls.index(('/usr/bin/systemctl', 'disable', service.GETTY))
    service.restore(system, backup)
    original(system)
    assert json.loads((backup / 'state.json').read_text())['state'] == 'restored'
    service.restore(system, backup)
print('PASS install/exact backup/restore/idempotent restore preserve registrations and original getty')

with fixture() as system:
    system.unit.write_bytes(b'existing administrator unit')
    must_fail(lambda: service.install(system, SOURCE))
    assert system.unit.read_bytes() == b'existing administrator unit'
    assert not system.store.exists() and not system.calls
print('PASS existing unit refused without filesystem or service changes')

with fixture() as system:
    backup = service.install(system, SOURCE)
    system.unit.write_bytes(b'changed by administrator')
    before = list(system.calls)
    must_fail(lambda: service.restore(system, backup))
    assert system.unit.read_bytes() == b'changed by administrator' and system.calls == before
print('PASS changed unit refused before any restore actions')

for failed in [('daemon-reload',), ('disable', service.GETTY), ('enable', service.MENU),
               ('start', service.MENU), ('is-active', service.MENU), ('is-enabled', service.MENU)]:
    with fixture() as system:
        # is-enabled MENU occurs in preflight too: fail only after publication.
        run = system.run
        def fail_after_publication(args, check=True):
            if tuple(args[1:]) == failed and system.unit.exists():
                system.run = run
                raise subprocess.CalledProcessError(1, args)
            return run(args, check=check)
        if failed == ('daemon-reload',):
            system.fail = failed
        else:
            system.run = fail_after_publication
        must_fail(lambda: service.install(system, SOURCE))
        original(system)
        backup = next(system.store.iterdir())
        assert json.loads((backup / 'state.json').read_text())['state'] == 'failed-rolled-back'
print('PASS six injected install failures roll back unit/enabled/running state')

for field in ['binary', 'default_target', 'dropins']:
    with fixture() as system:
        if field == 'binary':
            (system.project / 'game/build/paint-bots').write_bytes(b'changed')
        elif field == 'default_target':
            system.default_target = 'graphical.target'
        else:
            system.dropins = '/etc/systemd/system/getty@tty1.service.d/changed.conf'
        must_fail(lambda: service.install(system, SOURCE))
        assert not system.store.exists()
        original(system)
print('PASS changed binary/default target/getty drop-ins refused before changes')

with fixture() as system:
    backup = service.install(system, SOURCE)
    service.restore(system, backup)
    later = service.install(system, SOURCE)
    must_fail(lambda: service.restore(system, backup))
    assert system.unit.read_bytes() == SOURCE.read_bytes()
    assert json.loads((later / 'state.json').read_text())['state'] == 'applied'
print('PASS old restored backup cannot remove a later installation')
with fixture() as system:
    run = system.run
    failures = {('start', service.MENU), ('stop', service.MENU)}
    def fail_install_and_recovery(args, check=True):
        parts = tuple(args[1:])
        if parts in failures:
            failures.remove(parts)
            raise subprocess.CalledProcessError(1, args)
        return run(args, check=check)
    system.run = fail_install_and_recovery
    must_fail(lambda: service.install(system, SOURCE))
    backup = next(system.store.iterdir())
    assert json.loads((backup / 'state.json').read_text())['state'] == 'recovery-required'
    assert system.registered.read_bytes() == b'keep this registration'
    service.restore(system, backup)
    original(system)
print('PASS failed automatic recovery preserves backup and supports later explicit restore')
for relative in ('/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf',
                 '/etc/systemd/journald@paintbot.conf', '/var/lib/paintbot-menu/active-logging'):
    for symlink in (False,True):
        with fixture() as system:
            backup=service.install(system,SOURCE)
            leftover=system.path(relative)
            leftover.parent.mkdir(parents=True,exist_ok=True)
            if symlink:
                leftover.symlink_to(system.root/'missing')
            else:
                leftover.write_text('logging configuration/state')
            before=list(system.calls)
            state=(backup/'state.json').read_bytes()
            must_fail(lambda: service.restore(system,backup))
            assert system.calls==before and system.unit.read_bytes()==SOURCE.read_bytes()
            assert (backup/'state.json').read_bytes()==state and os.path.lexists(leftover)
            assert system.active[service.MENU] and not system.active[service.GETTY]
            leftover.unlink()
            service.restore(system,backup)
            original(system)
print('PASS logging file/marker remnants (including dangling symlinks) block menu restore before changes')
print('PASS 10 service preparation groups, 0 failures (fake manager; not a live systemd test)')
