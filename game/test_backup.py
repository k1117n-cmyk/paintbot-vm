"""Real bounded zip snapshots/restores, including a rebuilt VM game in isolation."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import zipfile

import backup_appliance as backup


def refused(function):
    try:
        function()
    except (RuntimeError,OSError,ValueError,zipfile.BadZipFile):
        return
    raise AssertionError('expected refusal')


def fixture(root, full=False):
    project=root/'project'
    project.mkdir(parents=True)
    for name in ('game','vm'):
        if full:
            shutil.copytree(Path(name), project/name, ignore=shutil.ignore_patterns('build','__pycache__'))
        else:
            (project/name).mkdir()
            (project/name/'Makefile').write_text('# fixture\n')
    (project/'registered').mkdir()
    for name in ('explorer-h','raider-v'):
        (project/'registered'/(name+'.bin')).write_bytes(Path('game/build/'+name+'.bin').read_bytes())
    system=root/'system-root'
    for name, absolute in backup.CONFIGS.items():
        p=system/absolute.lstrip('/')
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((Path('game/systemd')/Path(name).name).read_bytes())
    return project,system


with tempfile.TemporaryDirectory(prefix='paint-backup-tests-') as directory:
    root=Path(directory).resolve()
    project,system=fixture(root/'normal',full=True)
    (project/'game'/'build').mkdir()
    (project/'game'/'build'/'private.log').write_text('exclude')
    archive=backup.create(project,root/'store',system)
    manifest,files,digest=backup.inspect(archive)
    assert len(digest)==64 and len(files)>40
    assert not any('/build/' in name for name in files)
    assert 'project/vm/LICENSE' in files
    assert all(name in files for name in backup.CONFIGS)
    assert archive.stat().st_mode & 0o777==0o600
    print('PASS snapshot includes sources, 2 bots and all settings; excludes builds; private archive')

    restored=backup.restore(archive,root/'restore')
    assert not (restored/'.restore-incomplete').exists()
    for name,data in files.items():
        assert (restored/name).read_bytes()==data
    before=(project/'registered'/'explorer-h.bin').read_bytes()
    refused(lambda: backup.restore(archive,project))
    assert (project/'registered'/'explorer-h.bin').read_bytes()==before
    print('PASS separate-directory restore matches every file and refuses live/existing destination')

    for command in (['make','-C','vm'],['make','-C','game'],
                    ['vm/build/handmade-vm','--self-test'],
                    ['game/build/paint-bots','match','--no-watch','explorer-h','raider-v']):
        r=subprocess.run(command,cwd=restored/'project',capture_output=True)
        print('$',repr(command),'EXIT='+str(r.returncode),flush=True)
        print(r.stdout.decode(errors='replace'),end='',flush=True)
        print(r.stderr.decode(errors='replace'),end='',flush=True)
        assert r.returncode==0
        if '--self-test' in command:
            assert r.stdout==b'A\nVM flow complete.\nCPU halted.\n' and not r.stderr
    # Keep this strict integration result, but finish the independent archive
    # safety checks before returning a failure. Never hide a timeout with a retry.
    match_ok=(b'Score: 70:185\n' in r.stdout and
              b'ID 1: accepted=200 timeout=0 invalid=0 VM-error=0' in r.stdout and
              b'ID 2: accepted=200 timeout=0 invalid=0 VM-error=0' in r.stdout)
    print(('PASS' if match_ok else 'FAIL')+
          ' restored source rebuilds VM/game and restored registered bots complete 200-turn match')

    for i in range(4):
        backup.create(project,root/'store',system)
    hashes={p.name:backup.sha(p.read_bytes()) for p in (root/'store').glob('*.zip')}
    refused(lambda: backup.create(project,root/'store',system))
    assert hashes=={p.name:backup.sha(p.read_bytes()) for p in (root/'store').glob('*.zip')}
    print('PASS 5-generation cap refuses sixth and never deletes/overwrites prior archives')

    limit=backup.MAX_ARCHIVE
    backup.MAX_ARCHIVE=100
    refused(lambda: backup.create(project,root/'small-store',system))
    assert not list((root/'small-store').glob('*.zip'))
    backup.MAX_ARCHIVE=limit
    print('PASS content/archive capacity refusal publishes no backup')

    linked=root/'linked.zip'
    linked.symlink_to(archive)
    refused(lambda: backup.inspect(linked))
    target=root/'outside'
    target.mkdir()
    (root/'restore-link').symlink_to(target,target_is_directory=True)
    refused(lambda: backup.restore(archive,root/'restore-link'/'new'))
    p,s=fixture(root/'link-source')
    (p/'registered'/'leak.bin').symlink_to(archive)
    refused(lambda: backup.create(p,root/'link-store',s))
    assert not list((root/'link-store').glob('*.zip'))
    print('PASS archive, restore-parent and registration symlinks refused')

    p,s=fixture(root/'invalid-bot')
    (p/'registered'/'bad.bin').write_bytes(b'')
    refused(lambda: backup.create(p,root/'bad-store',s))
    (p/'registered'/'bad.bin').write_bytes(b'X'*(1024*1024+1))
    refused(lambda: backup.create(p,root/'bad-store',s))
    print('PASS empty/oversized bots refuse snapshot rather than silently omitting data')

    def malicious(label, modify, compression=zipfile.ZIP_STORED):
        path=root/(label+'.zip')
        entries={name:data for name,data in files.items()}
        m=json.loads(json.dumps(manifest))
        modify(entries,m)
        with zipfile.ZipFile(path,'w',compression=compression) as z:
            z.writestr('manifest.json',json.dumps(m))
            for name,data in entries.items():
                z.writestr(name,data)
        destination=root/('rejected-'+label)
        refused(lambda: backup.restore(path,destination))
        assert not destination.exists()
    malicious('traversal',lambda f,m:f.update({'../escape':b'bad'}))
    malicious('absolute',lambda f,m:f.update({'/etc/config':b'bad'}))
    malicious('hash',lambda f,m:f.update({'project/registered/explorer-h.bin':b'changed'}))
    malicious('unlisted',lambda f,m:m['files'].pop('system/paintbot-menu.service'))
    malicious('compressed',lambda f,m:None,zipfile.ZIP_DEFLATED)
    print('PASS traversal, absolute paths, tampered hashes, unlisted files and compression refused before restore')

    duplicate=root/'duplicate.zip'
    with zipfile.ZipFile(duplicate,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest))
        z.writestr('manifest.json',json.dumps(manifest))
    refused(lambda: backup.inspect(duplicate))
    nonregular=root/'member-link.zip'
    with zipfile.ZipFile(nonregular,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest))
        for name,data in files.items():
            info=zipfile.ZipInfo(name)
            info.external_attr=(0o120777 if name=='system/paintbot-menu.service' else 0o100600)<<16
            z.writestr(info,data)
    refused(lambda: backup.inspect(nonregular))
    print('PASS duplicate members and archive symlinks refused')

    p,s=fixture(root/'empty-registry')
    for item in (p/'registered').iterdir():
        item.unlink()
    empty=backup.create(p,root/'empty-store',s)
    dest=backup.restore(empty,root/'empty-restored')
    assert (dest/'project/registered').is_dir() and not list((dest/'project/registered').iterdir())
    print('PASS empty registration directory survives backup/restore')

    p,s=fixture(root/'umask-source')
    for mask in (0o002,0o000):
        store=root/('umask-store-'+str(mask))
        previous=os.umask(mask)
        try:
            private=backup.create(p,store,s)
            assert store.stat().st_mode&0o777==0o700 and private.stat().st_mode&0o777==0o600
        finally:
            os.umask(previous)
    unsafe=root/'unsafe-existing-store'
    unsafe.mkdir()
    unsafe.chmod(0o775)
    (unsafe/'keep.txt').write_text('preserve')
    refused(lambda: backup.create(p,unsafe,s))
    assert unsafe.stat().st_mode&0o777==0o775 and (unsafe/'keep.txt').read_text()=='preserve'
    print('PASS umask 0002/0000 create private backups; unsafe existing store refused without changes')
if not match_ok:
    print('FAIL backup groups: 10 passed, 1 failed (strict restored-match result; no retry)')
    raise AssertionError('restored match did not meet original score/normal-response expectations')
print('PASS 11 backup groups, 0 failures')
