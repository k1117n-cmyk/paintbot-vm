"""Fake service manager and isolated roots; not a live systemd test."""
from pathlib import Path
import configparser
import json
import os
import subprocess
import tempfile
from unittest.mock import patch

import manage_logging as logs


class Fake(logs.System):
    def __init__(self, root):
        super().__init__(root)
        self.configuration_owner=os.geteuid()
        self.unit.parent.mkdir(parents=True)
        # Model root-owned /etc/systemd{,/system}; fixture setup must not
        # inherit the caller's umask. Newly installed directories stay absent.
        self.unit.parent.chmod(0o755)
        self.unit.parent.parent.chmod(0o755)
        self.unit.write_bytes((Path(__file__).parent/'systemd'/logs.MENU).read_bytes())
        program=self.project/'game/build/paint-bots'
        program.parent.mkdir(parents=True)
        program.write_bytes(b'fixture-menu')
        program.chmod(0o755)
        self.expected_binary=logs.digest(program)
        self.states={logs.MENU: 'active', logs.GETTY: 'inactive', **{u:'inactive' for u in logs.NAMESPACE_UNITS}}
        self.calls=[]
        self.fail=[]
        self.probe_fail=False
        self.probes=0

    def run(self, args, check=True):
        self.calls.append(tuple(args))
        if args in self.fail:
            self.fail.remove(args)
            raise subprocess.CalledProcessError(1,args)
        if args[0].endswith('systemd-analyze'):
            assert args[1]=='verify'
            candidate=Path(args[2])
            assert candidate.name==logs.MENU
            assert candidate.read_bytes()==self.unit.read_bytes()+b'\n'+logs.CONTENTS[logs.DROPIN]
            return subprocess.CompletedProcess(args,0,'verified\n','')
        action=args[1]
        unit=args[2] if len(args)>2 else ''
        output=''
        code=0
        if action=='is-active':
            output=self.states.get(unit,'inactive')
            code=0 if output=='active' else 3
        elif action=='is-enabled':
            output='enabled' if unit==logs.MENU else 'disabled'
            code=0 if output=='enabled' else 1
        elif action=='show':
            if 'FragmentPath' in args:
                output='/usr/lib/systemd/system/template'
            elif 'DropInPaths' in args:
                output=str(self.path(logs.DROPIN)) if self.path(logs.DROPIN).exists() else ''
            elif 'LogNamespace' in args:
                output='paintbot' if self.path(logs.DROPIN).exists() else ''
        elif action in ('start','restart'):
            self.states[unit]='active'
            if self.path(logs.DROPIN).exists():
                self.states.update({u:'active' for u in logs.NAMESPACE_UNITS})
        elif action=='stop':
            for unit in args[2:]:
                self.states[unit]='inactive'
        result=subprocess.CompletedProcess(args,code,output+'\n','')
        if check:
            result.check_returncode()
        return result

    def smoke(self):
        self.probes+=1
        if self.probe_fail:
            self.probe_fail=False
            raise RuntimeError('probe failure')


def refused(function):
    try:
        function()
    except (RuntimeError, OSError, subprocess.CalledProcessError):
        return
    raise AssertionError('expected refusal')


def clean(system):
    assert all(not system.path(p).exists() for p in logs.CONTENTS)
    assert not (system.store/'active-logging').exists()
    assert system.states[logs.MENU]=='active' and system.states[logs.GETTY]=='inactive'
    assert all(system.states[u]=='inactive' for u in logs.NAMESPACE_UNITS)


with tempfile.TemporaryDirectory(prefix='paint-log-tests-') as directory:
    root=Path(directory)
    for path,data in logs.CONTENTS.items():
        assert (Path(__file__).parent/'systemd'/Path(path).name).read_bytes()==data
    config=configparser.ConfigParser()
    config.read_string(logs.CONTENTS[logs.JOURNAL].decode())
    assert config['Journal']['SystemMaxUse']=='50M'
    assert config['Journal']['SystemMaxFileSize']=='8M'
    assert config['Journal']['MaxRetentionSec']=='7day'
    print('PASS reviewed logging files match: namespace, capacity, file size, retention')

    system=Fake(root/'readonly')
    system.preflight(private=False)
    assert any(c[:2]==('/usr/bin/systemd-analyze','verify') for c in system.calls)
    assert not system.store.exists()
    assert not any(c[1] in ('start','stop','restart','daemon-reload') for c in system.calls)
    system.store.mkdir(mode=0o700,parents=True)
    marker=system.store/'active-logging'
    marker.write_text('existing installation')
    system.preflight(private=False)
    refused(lambda: logs.install(system))
    assert marker.read_text()=='existing installation'
    assert not any(system.path(p).exists() for p in logs.CONTENTS)
    print('PASS preflight is read-only and verifies candidate with systemd-analyze')

    system=Fake(root/'normal')
    original=system.unit.read_bytes()
    backup=logs.install(system)
    system.check_applied()
    assert system.probes==1 and system.unit.read_bytes()==original
    assert json.loads((backup/'state.json').read_text())['state']=='applied'
    assert (backup/'80-paintbot-logging.conf').read_bytes()==logs.CONTENTS[logs.DROPIN]
    logs.restore(system,backup)
    clean(system)
    (system.store/'active-logging').write_text(backup.name)
    logs.restore(system,backup)
    clean(system)
    logs.restore(system,backup)
    assert system.unit.read_bytes()==original
    print('PASS install, probe, exact backup, restore, idempotent restore preserve base unit/getty')

    for tag in ('existing','symlink','override','busy','changed-base'):
        system=Fake(root/tag)
        if tag=='existing':
            p=system.path(logs.JOURNAL)
            p.write_text('administrator config')
        elif tag=='symlink':
            p=system.path('/etc/systemd/system/paintbot-menu.service.d')
            other=root/'external'
            other.mkdir()
            p.symlink_to(other,target_is_directory=True)
        elif tag=='override':
            p=system.path('/run/systemd/journald@paintbot.conf.d/99-other.conf')
            p.parent.mkdir(parents=True)
            p.write_text('override')
        elif tag=='busy':
            system.states[logs.NAMESPACE_UNITS[0]]='active'
        else:
            system.unit.write_text('changed base')
        refused(system.preflight)
        assert not system.store.exists()
    print('PASS existing config, parent symlink, override, busy namespace, changed base refused')

    for tag,args in [('reload',['/usr/bin/systemctl','daemon-reload']),
                     ('restart',['/usr/bin/systemctl','restart',logs.MENU]),
                     ('probe',None)]:
        system=Fake(root/('fail-'+tag))
        if args:
            system.fail.append(args)
        else:
            system.probe_fail=True
        refused(lambda: logs.install(system))
        clean(system)
        backup=next(system.store.glob('logging-*'))
        assert json.loads((backup/'state.json').read_text())['state']=='restored'
    print('PASS three apply failure points roll back configuration and restart original menu')

    system=Fake(root/'publish-failure')
    publish=system.publish
    def fail_second(absolute,data):
        if absolute==logs.JOURNAL:
            raise OSError('injected publish failure')
        publish(absolute,data)
    system.publish=fail_second
    refused(lambda: logs.install(system))
    clean(system)
    print('PASS partial publication failure removes only the first owned configuration')

    system=Fake(root/'changed-after')
    backup=logs.install(system)
    system.path(logs.JOURNAL).write_text('administrator change')
    calls=len(system.calls)
    refused(lambda: logs.restore(system,backup))
    assert len(system.calls)==calls and system.path(logs.JOURNAL).read_text()=='administrator change'
    system.path(logs.JOURNAL).write_bytes(logs.CONTENTS[logs.JOURNAL])
    override=system.path('/run/systemd/journald@paintbot.conf.d/99-admin.conf')
    override.parent.mkdir(parents=True)
    override.write_text('[Journal]\nSystemMaxUse=1G\n')
    refused(system.check_applied)
    assert override.exists()
    print('PASS administrator edits refuse restore before stopping/removing anything')

    system=Fake(root/'recovery')
    system.probe_fail=True
    system.fail.append(['/usr/bin/systemctl','start',logs.MENU])
    refused(lambda: logs.install(system))
    backup=next(system.store.glob('logging-*'))
    assert json.loads((backup/'state.json').read_text())['state']=='recovery-required'
    assert (system.store/'active-logging').exists()
    logs.restore(system,backup)
    clean(system)
    print('PASS failed rollback keeps recovery state and supports explicit restore')

    system=Fake(root/'old-backup')
    old=logs.install(system)
    logs.restore(system,old)
    current=logs.install(system)
    refused(lambda: logs.restore(system,old))
    system.check_applied()
    logs.restore(system,current)
    print('PASS old restored backup cannot remove a later installation')

    for mask in (0o002,0o000,0o077):
        previous=os.umask(mask)
        try:
            system=Fake(root/('umask-'+str(mask)))
            backup=logs.install(system)
            assert system.store.stat().st_mode&0o777==0o700
            assert system.path(logs.DROPIN).parent.stat().st_mode&0o777==0o755
            logs.restore(system,backup)
            clean(system)
        finally:
            os.umask(previous)
    system=Fake(root/'unsafe-existing-store')
    system.store.mkdir(parents=True)
    system.store.chmod(0o775)
    refused(lambda: logs.install(system))
    assert system.store.stat().st_mode&0o777==0o775 and not list(system.store.iterdir())
    for absolute in (logs.DROPIN,logs.JOURNAL):
        system=Fake(root/('unsafe-parent-'+Path(absolute).name))
        parent=system.path(absolute).parent
        parent.mkdir(exist_ok=True)
        parent.chmod(0o777)
        original=system.unit.read_bytes()
        refused(lambda: system.preflight(private=False))
        refused(lambda: logs.install(system))
        assert parent.stat().st_mode&0o777==0o777
        assert not system.store.exists() and system.unit.read_bytes()==original
        assert not any(c[1] in ('start','stop','restart','daemon-reload') for c in system.calls)
        clean(system)
    system=Fake(root/'parent-changed-after-preflight')
    system.preflight()
    parent=system.path(logs.JOURNAL).parent
    parent.chmod(0o777)
    refused(lambda: system.publish(logs.JOURNAL,logs.CONTENTS[logs.JOURNAL]))
    assert not system.path(logs.JOURNAL).exists() and parent.stat().st_mode&0o777==0o777
    print('PASS umask 0002/0000/0077 set directory modes; unsafe existing directories refused without chmod')

    system=Fake(root/'verify-failure')
    run=system.run
    def fail_verify(args,check=True):
        if args[:2]==['/usr/bin/systemd-analyze','verify']:
            raise subprocess.CalledProcessError(1,args)
        return run(args,check)
    with patch.object(system,'run',side_effect=fail_verify):
        refused(lambda: logs.install(system))
    assert not system.store.exists() and not any(system.path(p).exists() for p in logs.CONTENTS)
    print('PASS rejected systemd verification prevents publication')

    system=Fake(root/'real-smoke')
    token='paintbot-log-probe-fixture'
    def probe_run(args,check=True):
        return subprocess.CompletedProcess(args,0,token+'\n' if '-o' in args else '', '')
    with patch.object(logs.uuid,'uuid4') as identifier:
        identifier.return_value.hex='fixture'
        with patch.object(system,'run',side_effect=probe_run) as commands:
            logs.System.smoke(system)
        expected=[
            ['/usr/bin/systemd-run','--quiet','--wait','--collect','--unit='+token,
             '--property=LogNamespace=paintbot','--property=User=pi',
             '--property=StandardOutput=journal','/usr/bin/printf',token+'\n'],
            ['/usr/bin/journalctl','--namespace=paintbot','--sync'],
            ['/usr/bin/journalctl','--namespace=paintbot','--no-pager','-o','cat','-n','30'],
            ['/usr/bin/journalctl','--namespace=paintbot','--verify'],
            ['/usr/bin/journalctl','--namespace=paintbot','--disk-usage'],
            ['/usr/bin/systemd-analyze','cat-config','systemd/journald@paintbot.conf']]
        assert [call.args[0] for call in commands.call_args_list]==expected
        with patch.object(system,'run',return_value=subprocess.CompletedProcess([],0,'other token','')) as commands:
            refused(lambda: logs.System.smoke(system))
            assert commands.call_count==3
        for failure in range(len(expected)):
            results=[probe_run(command) for command in expected[:failure]]
            results.append(subprocess.CalledProcessError(1,expected[failure]))
            with patch.object(system,'run',side_effect=results) as commands:
                refused(lambda: logs.System.smoke(system))
                assert commands.call_count==failure+1
    print('PASS actual smoke logic checks namespace write/read, missing token, and every command failure')
print('PASS 12 logging groups, 0 failures (fake systemd; not a live-device test)')
