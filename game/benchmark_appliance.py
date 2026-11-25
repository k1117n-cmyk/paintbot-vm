"""Sequential 2/3/4-bot timing plus 2/4-bot PTY watch timing; keeps every run."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
import platform
import pty
import re
import select
import signal
import statistics
import struct
import subprocess
import termios
import time

NAMES = ('explorer-h', 'raider-v', 'explorer-v', 'raider-h')
ANSI = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')
HEADER = re.compile(rb'Paint battle \| Turn \d{3}/200')
OUTPUT_LIMIT = 2*1024*1024


def parse_output(raw, count, watch):
    frame = raw.split(b'\x1b[H')[-1] if watch else raw
    text = ANSI.sub(b'',frame).replace(b'\r',b'').decode(errors='replace')
    rows = re.findall(r'ID (\d): accepted=(\d+) timeout=(\d+) invalid=(\d+) VM-error=(\d+)',text)
    rows += re.findall(r'ID (\d): A=(\d+) T=(\d+) I=(\d+) E=(\d+)',text)
    totals = {int(row[0]):dict(zip(('accepted','timeout','invalid','vm_error'),map(int,row[1:]))) for row in rows}
    complete = (('Turn 200/200' in text if watch else 'Final board (turns=200):' in text) and
                len(rows)==count and sorted(totals)==list(range(1,count+1)) and
                all(sum(item.values())==200 for item in totals.values()))
    healthy = complete and all(item==dict(accepted=200,timeout=0,invalid=0,vm_error=0) for item in totals.values())
    result = re.search(r'Result: ([^\n]+)',text)
    score = re.search(r'Score: ([^\n]+)',text)
    return dict(complete=complete,all_healthy=healthy,totals=totals,
                result=result.group(1) if result else None,score=score.group(1) if score else None)


def environment():
    data=dict(utc=datetime.now(timezone.utc).isoformat(),system=platform.system(),
              release=platform.release(),machine=platform.machine(),python=platform.python_version(),
              cpu_count=os.cpu_count(),load_average=list(os.getloadavg()))
    for name,filename in [('memory','/proc/meminfo'),('governor','/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'),
                          ('frequency_khz','/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'),
                          ('temperature_millidegrees','/sys/class/thermal/thermal_zone0/temp')]:
        try:
            text=Path(filename).read_text()
            data[name]=('\n'.join(line for line in text.splitlines() if line.startswith(('MemTotal:','MemAvailable:')))
                        if name=='memory' else text.strip())
        except OSError:
            data[name]=None
    return data


def stop_group(process):
    try:
        os.killpg(process.pid,signal.SIGKILL)
    except (PermissionError,ProcessLookupError):
        # macOS can return EPERM while the child is already exiting. Accept
        # this only when wait4 confirms exit; genuine denial must still fail.
        for _ in range(10):
            result=os.wait4(process.pid,os.WNOHANG)
            if result[0]:
                return result
            time.sleep(0.01)
        raise
    return os.wait4(process.pid,0)


def run_match(command, prefix, watch, timeout=120):
    rawpath=prefix.with_suffix('.stdout')
    errorpath=prefix.with_suffix('.stderr')
    master=slave=None
    started=time.monotonic()
    arrivals=[]
    received=bytearray()
    status=usage=None
    timed_out=False
    termination_attempted=False
    with rawpath.open('wb') as output, errorpath.open('wb') as errors:
        if watch:
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,64,0,0))
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=slave if watch else output,
                                 stderr=errors,env={**os.environ,'TERM':'linux'},start_new_session=True)
        if slave is not None:
            os.close(slave)
        try:
            while status is None:
                if time.monotonic()-started>timeout:
                    timed_out=True
                if watch and select.select([master],[],[],0.01)[0]:
                    try:
                        chunk=os.read(master,16384)
                    except OSError as error:
                        if error.errno!=errno.EIO:
                            raise
                        chunk=b''
                    remaining = OUTPUT_LIMIT-len(received)
                    if len(chunk)>remaining:
                        timed_out=True
                    chunk=chunk[:remaining]
                    output.write(chunk)
                    received.extend(chunk)
                    n=len(HEADER.findall(received))
                    arrivals.extend([time.monotonic()-started]*(n-len(arrivals)))
                elif not watch:
                    time.sleep(0.005)
                if not watch and os.fstat(output.fileno()).st_size>OUTPUT_LIMIT:
                    timed_out=True
                if os.fstat(errors.fileno()).st_size>OUTPUT_LIMIT:
                    timed_out=True
                pid,code,child_usage=os.wait4(process.pid,os.WNOHANG)
                if pid:
                    status,usage=code,child_usage
                elif timed_out:
                    termination_attempted=True
                    _,status,usage=stop_group(process)
            process.returncode=os.waitstatus_to_exitcode(status)
            if watch:
                while select.select([master],[],[],0)[0]:
                    try:
                        chunk=os.read(master,16384)
                    except OSError as error:
                        if error.errno!=errno.EIO:
                            raise
                        break
                    if not chunk:
                        break
                    remaining=OUTPUT_LIMIT-len(received)
                    if len(chunk)>remaining:
                        timed_out=True
                    chunk=chunk[:remaining]
                    output.write(chunk)
                    received.extend(chunk)
                    n=len(HEADER.findall(received))
                    arrivals.extend([time.monotonic()-started]*(n-len(arrivals)))
                    if timed_out:
                        break
        finally:
            try:
                if status is None and not termination_attempted:
                    _,status,usage=stop_group(process)
                    process.returncode=os.waitstatus_to_exitcode(status)
            finally:
                if master is not None:
                    os.close(master)
    elapsed=time.monotonic()-started
    for path in (rawpath,errorpath):
        if path.stat().st_size>OUTPUT_LIMIT:
            timed_out=True
            with path.open('r+b') as stream:
                stream.truncate(OUTPUT_LIMIT)
    raw=rawpath.read_bytes()
    return dict(command=command,exit=process.returncode,wall_seconds=elapsed,
                user_seconds=usage.ru_utime,system_seconds=usage.ru_stime,
                child_maxrss_kib=usage.ru_maxrss/(1024 if platform.system()=='Darwin' else 1),
                watch=watch,watch_frames=len(HEADER.findall(raw)) if watch else None,
                min_observed_frame_interval=min((b-a for a,b in zip(arrivals,arrivals[1:])),default=None),
                killed_by_measurement_limit=timed_out,stdout=rawpath.name,stderr=errorpath.name)


def measure(output, repetitions=3, watch=True):
    if repetitions<1:
        raise RuntimeError('repetitions must be positive')
    output.mkdir(parents=False,exist_ok=False)
    report=dict(version=1,deadline_ms=100,environment_before=environment(),runs=[],artifacts={})
    for path in [Path('game/build/paint-host'),Path('vm/build/handmade-vm'),*[Path('game/build/'+n+'.bin') for n in NAMES]]:
        report['artifacts'][str(path)]=dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    cases=[(n,False,i+1) for n in (2,3,4) for i in range(repetitions)]
    if watch:
        cases.extend([(2,True,1),(4,True,1)])
    try:
        for n,view,iteration in cases:
            label=f'{n}-bots-'+('watch' if view else 'plain')+f'-{iteration}'
            command=['game/build/paint-host','--watch' if view else '--no-watch',
                     'vm/build/handmade-vm',*['game/build/'+name+'.bin' for name in NAMES[:n]]]
            result=run_match(command,output/label,view)
            result.update(parse_output((output/result['stdout']).read_bytes(),n,view))
            result.update(bots=n,iteration=iteration)
            if result['exit']!=0 or result['killed_by_measurement_limit']:
                result['complete']=result['all_healthy']=False
            if view and (result['watch_frames']!=201 or result['wall_seconds']<40):
                result['complete']=result['all_healthy']=False
            report['runs'].append(result)
            (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
            print(label, 'wall=%.3fs'%result['wall_seconds'], 'rss=%.0fKiB'%result['child_maxrss_kib'],
                  'complete='+str(result['complete']),'healthy='+str(result['all_healthy']),flush=True)
    finally:
        report['environment_after']=environment()
        report['measurement_complete']=len(report['runs'])==len(cases) and all(r['complete'] for r in report['runs'])
        report['all_healthy']=report['measurement_complete'] and all(r['all_healthy'] for r in report['runs'])
        report['responses']=sum(sum(t.values()) for r in report['runs'] for t in r.get('totals',{}).values())
        report['summary']={str(n):dict(min_seconds=min(times),median_seconds=statistics.median(times),max_seconds=max(times))
                           for n in (2,3,4) if (times:=[r['wall_seconds'] for r in report['runs'] if r['bots']==n and not r['watch']])}
        (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print('BENCHMARK_RESULTS='+str(output/'results.json'),flush=True)
    print('BENCHMARK_COMPLETE='+str(int(report['measurement_complete'])),flush=True)
    print('BENCHMARK_ALL_HEALTHY='+str(int(report['all_healthy'])),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--no-watch',action='store_true')
    args=parser.parse_args()
    report=measure(args.output,args.repetitions,not args.no_watch)
    if not report['measurement_complete']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
