"""Bounded manual backups and verified restoration into a NEW directory only."""
from pathlib import Path, PurePosixPath
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import uuid
import zipfile

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_GENERATIONS = 5
MAX_MEMBERS = 1024
MAX_FILE = 2 * 1024 * 1024
BOT_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,31}\.bin\Z')
BACKUP_NAME = re.compile(r'paintbot-\d{8}T\d{6}Z-[0-9a-f]{8}\.zip\Z')
CONFIGS = {
    'system/paintbot-menu.service': '/etc/systemd/system/paintbot-menu.service',
    'system/80-paintbot-logging.conf': '/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf',
    'system/journald@paintbot.conf': '/etc/systemd/journald@paintbot.conf',
}
SUFFIXES = {'.c', '.h', '.py', '.asm', '.md', '.conf', '.service'}
SOURCE_NAMES = {'Makefile', '.gitignore', 'LICENSE'}
EXCLUDED = {'build', '__pycache__', '.git', 'incoming', 'registered'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    path = path.absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlink path: ' + str(part))
    return path


def read_regular(path, limit):
    no_links(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'not a bounded regular file: ' + str(path))
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(len(data) <= limit and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file changed/too large: ' + str(path))
    return data


def allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or '..' in path.parts or '\\' in name or len(name) > 240:
        return False
    if name in CONFIGS:
        return True
    if len(path.parts) == 3 and path.parts[:2] == ('project', 'registered'):
        return bool(BOT_NAME.fullmatch(path.name))
    return (len(path.parts) >= 3 and path.parts[0] == 'project' and
            path.parts[1] in ('game', 'vm') and not (set(path.parts[2:-1]) & EXCLUDED) and
            (path.suffix in SUFFIXES or path.name in SOURCE_NAMES))


def collect(project, system_root):
    project = no_links(project)
    files = {}
    total = 0

    def add(name, path):
        nonlocal total
        require(allowed(name), 'unsupported backup path: ' + name)
        limit = 1024*1024 if name.startswith('project/registered/') else MAX_FILE
        data = read_regular(path, limit)
        if name.startswith('project/registered/'):
            require(bool(data), 'empty bot: ' + str(path))
        total += len(data)
        require(total < MAX_ARCHIVE and len(files) < MAX_MEMBERS-1, 'backup content exceeds limits')
        files[name] = data

    for folder in ('game', 'vm'):
        source = no_links(project/folder)
        require(source.is_dir(), 'source tree missing: ' + str(source))
        for directory, dirs, names in os.walk(source, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
            for name in dirs:
                no_links(Path(directory)/name)
            for name in sorted(names):
                p = Path(directory)/name
                if p.suffix in SUFFIXES or p.name in SOURCE_NAMES:
                    add('project/'+p.relative_to(project).as_posix(), p)
    registered = no_links(project/'registered')
    require(registered.is_dir(), 'registered directory is missing')
    before = sorted(p.name for p in registered.iterdir())
    for name in before:
        require(bool(BOT_NAME.fullmatch(name)), 'unrecognized registration entry: ' + name)
        add('project/registered/'+name, registered/name)
    require(before == sorted(p.name for p in registered.iterdir()), 'registration list changed during backup')
    for name in before:
        require(sha(read_regular(registered/name, 1024*1024)) == sha(files['project/registered/'+name]),
                'registration changed during backup: ' + name)
    for name, absolute in CONFIGS.items():
        path = system_root/absolute.lstrip('/')
        if os.path.lexists(path):
            add(name, path)
    require('system/paintbot-menu.service' in files, 'installed menu configuration is missing')
    return files


def inspect(archive):
    raw = read_regular(archive, MAX_ARCHIVE)
    require(len(raw) > 0, 'empty backup')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        names = [p.filename for p in infos]
        require(len(infos) <= MAX_MEMBERS and len(names) == len(set(names)), 'duplicate/too many members')
        require(names.count('manifest.json') == 1, 'manifest missing')
        require(sum(p.file_size for p in infos) <= MAX_ARCHIVE, 'expanded backup too large')
        for p in infos:
            mode = p.external_attr >> 16
            require(p.compress_type == zipfile.ZIP_STORED and not p.is_dir() and
                    (not stat.S_IFMT(mode) or stat.S_ISREG(mode)) and
                    p.file_size <= MAX_FILE and not (p.flag_bits & 1), 'unsupported member: '+p.filename)
            require(p.filename == 'manifest.json' or allowed(p.filename), 'unsafe member: '+p.filename)
        manifest = json.loads(z.read('manifest.json'))
        require(type(manifest.get('version')) is int and manifest['version'] == 1 and
                isinstance(manifest.get('files'), dict), 'unsupported manifest')
        expected = manifest['files']
        require(set(names) == {'manifest.json', *expected}, 'manifest/file list mismatch')
        files = {}
        for name, entry in expected.items():
            require(allowed(name) and isinstance(entry, dict) and type(entry.get('bytes')) is int and
                    isinstance(entry.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}',entry['sha256']),
                    'invalid manifest entry')
            data = z.read(name)
            require(len(data) == entry['bytes'] and sha(data) == entry['sha256'], 'backup hash/size mismatch: '+name)
            if name.startswith('project/registered/'):
                require(0 < len(data) <= 1024*1024, 'invalid bot size')
            files[name] = data
        require('system/paintbot-menu.service' in files and 'project/game/Makefile' in files and
                'project/vm/Makefile' in files, 'backup lacks required project/settings files')
    return manifest, files, sha(raw)


def create(project, store, system_root=Path('/')):
    store = no_links(store)
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(store.is_dir() and store.stat().st_uid == os.geteuid() and store.stat().st_mode & 0o022 == 0,
            'backup store is not a safe owned directory')
    lock = os.open(store/'.backup.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        generations = [p for p in store.iterdir() if BACKUP_NAME.fullmatch(p.name)]
        require(len(generations) < MAX_GENERATIONS, '5 backup generations already exist; nothing deleted')
        files = collect(project, system_root)
        now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        manifest = {'version':1, 'created_utc':now, 'files':{
            name:{'bytes':len(data),'sha256':sha(data)} for name,data in sorted(files.items())}}
        fd, temp = tempfile.mkstemp(prefix='.backup-', dir=store)
        temp = Path(temp)
        try:
            with os.fdopen(fd,'wb') as stream:
                with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as z:
                    z.writestr('manifest.json', json.dumps(manifest,sort_keys=True,indent=2)+'\n')
                    for name,data in sorted(files.items()):
                        z.writestr(name,data)
                stream.flush()
                os.fsync(stream.fileno())
            require(temp.stat().st_size <= MAX_ARCHIVE, 'archive exceeds 64MiB; nothing published')
            inspect(temp)
            dest = store/f'paintbot-{now}-{uuid.uuid4().hex[:8]}.zip'
            os.link(temp,dest)  # exclusive publication: never overwrite an older archive
            print('BACKUP_PATH='+str(dest),flush=True)
            print('BACKUP_SHA256='+sha(dest.read_bytes()),flush=True)
            print('BACKUP_BYTES='+str(dest.stat().st_size),flush=True)
            print('BACKUP_FILES='+str(len(files)),flush=True)
            return dest
        finally:
            temp.unlink(missing_ok=True)
    finally:
        os.close(lock)


def restore(archive, destination):
    manifest, files, digest = inspect(archive)  # verify everything before creating any destination
    destination = no_links(destination)
    require(destination.parent.is_dir(), 'restore parent directory is missing')
    destination.mkdir(mode=0o700)  # exclusive: an existing directory is NEVER accepted
    marker = destination/'.restore-incomplete'
    marker.write_text('Verified archive SHA256='+digest+'\n')
    # A disk/I/O failure leaves an explicit incomplete directory, never replaces live data.
    for name,data in files.items():
        path = destination/name
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        require(sha(path.read_bytes())==manifest['files'][name]['sha256'], 'restore verification failed: '+name)
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'project'/'registered').mkdir(parents=True,exist_ok=True)
    marker.unlink()
    print('RESTORE_PATH='+str(destination),flush=True)
    print('RESTORE_MATCH='+str(len(files)),flush=True)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    backup=sub.add_parser('create')
    backup.add_argument('--project',type=Path,default=Path.cwd())
    backup.add_argument('--store',type=Path,default=Path.home()/'paintbot-backups')
    backup.add_argument('--system-root',type=Path,default=Path('/'))
    verify=sub.add_parser('verify')
    verify.add_argument('archive',type=Path)
    recover=sub.add_parser('restore')
    recover.add_argument('archive',type=Path)
    recover.add_argument('destination',type=Path)
    args=parser.parse_args()
    if args.action=='create':
        create(args.project,args.store,args.system_root)
    elif args.action=='restore':
        restore(args.archive,args.destination)
    else:
        manifest,files,digest=inspect(args.archive)
        print('VERIFY_MATCH='+str(len(files))+' SHA256='+digest)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('BACKUP_ERROR: '+str(error))
