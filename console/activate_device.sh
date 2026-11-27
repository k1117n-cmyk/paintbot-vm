#!/bin/sh
# Apply only after checking the device and finishing any running match.
set -eu
if [ "$#" -ne 2 ]; then
    echo "usage: sh console/activate_device.sh pi@host release-id" >&2
    exit 2
fi
task_target=$1
task_release=$2
case "$task_target" in
    pi@?*) ;;
    *) echo "expected pi@host; other users require adapting the device tools" >&2; exit 2 ;;
esac
case "$task_release" in
    *[!0-9a-f]*|'') echo "expected 12 lowercase hexadecimal digits" >&2; exit 2 ;;
esac
if [ "${#task_release}" -ne 12 ]; then
    echo "expected 12 lowercase hexadecimal digits" >&2
    exit 2
fi
task_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_project=/home/pi/vm-game-console-stage5-$task_release/project
scp "$task_script_dir/manage_device_menu.py" "$task_target:$task_project/console/manage_device_menu.py"
ssh -t "$task_target" "sudo python3 $task_project/console/manage_device_menu.py install $task_project"
printf 'CONSOLE_ACTIVATE_EXIT=0\n'
