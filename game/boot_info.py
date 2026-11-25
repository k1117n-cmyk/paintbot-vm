"""Read-only Raspberry Pi boot/console facts; makes no configuration changes."""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys


def main():
    if platform.system() != 'Linux':
        print('Run this read-only check on the Raspberry Pi.')
        return 1
    print('BOOT_INFO: read-only; no service/configuration changes', flush=True)
    print(f'OS={platform.system()} MACHINE={platform.machine()} UID={os.getuid()}', flush=True)
    for tool in ['systemctl', 'tty', 'cc', 'make', 'python3']:
        print(f'TOOL {tool}={shutil.which(tool) or "missing"}', flush=True)
    for name in ['/etc/os-release', '/sys/class/tty/console/active', '/sys/class/tty/tty0/active']:
        print('FILE ' + name, flush=True)
        try:
            print(Path(name).read_text(), end='', flush=True)
        except OSError as error:
            print(str(error), flush=True)
    commands = [
        ['systemctl', '--version'],
        ['systemctl', 'get-default'],
        ['systemctl', 'is-enabled', 'getty@tty1.service'],
        ['systemctl', 'is-active', 'getty@tty1.service'],
        ['systemctl', 'cat', 'getty@tty1.service'],
        ['systemctl', 'show', 'getty@tty1.service', '-p', 'ActiveState', '-p', 'SubState',
         '-p', 'UnitFileState', '-p', 'FragmentPath', '-p', 'DropInPaths', '-p', 'TTYPath'],
        ['systemctl', 'is-enabled', 'paintbot-menu.service'],
        ['tty'],
    ]
    for cmd in commands:
        print('$ ' + ' '.join(cmd), flush=True)
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10,
                                    env={**os.environ, 'SYSTEMD_PAGER': 'cat', 'SYSTEMD_COLORS': '0'})
            sys.stdout.flush()
            sys.stdout.buffer.write(result.stdout + result.stderr)
            sys.stdout.buffer.flush()
            print(f'EXIT={result.returncode}', flush=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(str(error), flush=True)
    print('BOOT_INFO_DONE (individual exits above describe current state)', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
