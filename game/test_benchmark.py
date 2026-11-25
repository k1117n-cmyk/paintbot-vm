"""Parser/process-measurement checks; real game workload is measured separately."""
from pathlib import Path
from contextlib import redirect_stdout
import argparse
import io
import json
import os
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

import benchmark_appliance as benchmark

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--unit-only',action='store_true',
                    help='run parser, orchestration and simulated OS tests without launching child processes')
args=parser.parse_args()

plain=(b'Final board (turns=200):\n'+b'................\n'*16+
       b'Score: 70:185\nResult: ID 2 wins\n'
       b'ID 1: accepted=200 timeout=0 invalid=0 VM-error=0\n'
       b'ID 2: accepted=200 timeout=0 invalid=0 VM-error=0\n')
r=benchmark.parse_output(plain,2,False)
assert r['complete'] and r['all_healthy'] and r['score']=='70:185'
assert r['totals'][2]['accepted']==200
bad=plain.replace(b'accepted=200 timeout=0',b'accepted=199 timeout=1',1)
r=benchmark.parse_output(bad,2,False)
assert r['complete'] and not r['all_healthy'] and r['totals'][1]['timeout']==1
assert not benchmark.parse_output(plain,3,False)['complete']
assert not benchmark.parse_output(plain.replace(b'turns=200',b'turns=199'),2,False)['complete']
assert not benchmark.parse_output(plain+plain.split(b'ID 2:')[1].join([b'ID 2:',b'']),2,False)['complete']
print('PASS final-result parser retains abnormal responses and rejects incomplete/duplicate IDs')

watch=(b'\x1b[HPaint battle | Turn 199/200 | Left 001\n'
       b'\x1b[HPaint battle | Turn 200/200 | Left 000\n'
       b'ID 1  20 | ID 2  88 | ID 3  89 | ID 4  59\nResult: ID 3 wins\n'
       b'ID 1: A=200 T=0 I=0 E=0 | ID 2: A=200 T=0 I=0 E=0\n'
       b'ID 3: A=200 T=0 I=0 E=0 | ID 4: A=200 T=0 I=0 E=0\n')
r=benchmark.parse_output(watch,4,True)
assert r['complete'] and r['all_healthy'] and len(r['totals'])==4
assert benchmark.parse_output(b'\x1b[HPaint battle | Turn 200/200\n'+plain,2,True)['all_healthy']
print('PASS PTY final frame parser handles compact 4-player and full 2-player totals')

with tempfile.TemporaryDirectory(prefix='paint-measure-tests-') as directory:
    root=Path(directory)
    previous=Path.cwd()
    try:
        os.chdir(root)
        for name in ['game/build/paint-host','vm/build/handmade-vm',
                     *['game/build/'+n+'.bin' for n in benchmark.NAMES]]:
            path=Path(name)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'measurement artifact fixture')

        def fake_match(command,prefix,view):
            count=len(command)-3
            raw=(b'\x1b[HPaint battle | Turn 200/200\n' if view else b'Final board (turns=200):\n')
            raw+=b''.join(f'ID {i}: accepted=200 timeout=0 invalid=0 VM-error=0\n'.encode()
                          for i in range(1,count+1))
            prefix.with_suffix('.stdout').write_bytes(raw)
            prefix.with_suffix('.stderr').write_bytes(b'')
            return dict(command=command,exit=0,wall_seconds=40 if view else float(prefix.name[-1]),
                        user_seconds=0.5,system_seconds=0.2,child_maxrss_kib=123,
                        watch=view,watch_frames=201 if view else None,
                        killed_by_measurement_limit=False,
                        stdout=prefix.with_suffix('.stdout').name,stderr=prefix.with_suffix('.stderr').name)

        with patch.object(benchmark,'environment',return_value={'fixture':True}), \
             patch.object(benchmark,'run_match',side_effect=fake_match), redirect_stdout(io.StringIO()):
            report=benchmark.measure(root/'normal')
        assert report['measurement_complete'] and report['all_healthy']
        assert len(report['runs'])==11 and report['responses']==6600
        assert report['summary']=={str(n):dict(min_seconds=1.0,median_seconds=2.0,max_seconds=3.0)
                                  for n in (2,3,4)}
        assert report['environment_before']==report['environment_after']=={'fixture':True}
        assert len(report['artifacts'])==6
        assert json.loads((root/'normal/results.json').read_text())['summary']==report['summary']
        print('PASS measure aggregates 11 runs, 6600 responses, min/median/max and saved JSON')

        for tag,change in [('exit',{'exit':3}),('limit',{'killed_by_measurement_limit':True}),
                           ('frames-low',{'watch_frames':200}),('frames-high',{'watch_frames':202}),
                           ('duration',{'wall_seconds':39.999})]:
            def altered(command,prefix,view):
                result=fake_match(command,prefix,view)
                if view:
                    result.update(change)
                return result
            with patch.object(benchmark,'environment',return_value={}), \
                 patch.object(benchmark,'run_match',side_effect=altered), redirect_stdout(io.StringIO()):
                report=benchmark.measure(root/tag,repetitions=1)
            assert not report['measurement_complete'] and not report['all_healthy']
            assert all(not r['complete'] and not r['all_healthy'] for r in report['runs'] if r['watch'])
            assert all(r['complete'] and r['all_healthy'] for r in report['runs'] if not r['watch'])
        # Nonzero/limit must reject plain runs too.
        for field,value in [('exit',7),('killed_by_measurement_limit',True)]:
            def altered_plain(command,prefix,view):
                result=fake_match(command,prefix,view)
                result[field]=value
                return result
            with patch.object(benchmark,'environment',return_value={}), \
                 patch.object(benchmark,'run_match',side_effect=altered_plain), redirect_stdout(io.StringIO()):
                report=benchmark.measure(root/('plain-'+field),repetitions=1,watch=False)
            assert not report['measurement_complete'] and not report['all_healthy']
            assert all(not r['complete'] and not r['all_healthy'] for r in report['runs'])
        with patch.object(benchmark,'environment',return_value={}), \
             patch.object(benchmark,'run_match',side_effect=fake_match), \
             patch.object(benchmark,'parse_output',side_effect=lambda raw,n,view:
                 dict(complete=True,all_healthy=False,totals={i:dict(accepted=199,timeout=1,invalid=0,vm_error=0)
                                                           for i in range(1,n+1)})), \
             redirect_stdout(io.StringIO()):
            report=benchmark.measure(root/'unhealthy',repetitions=1,watch=False)
        assert report['measurement_complete'] and not report['all_healthy'] and report['responses']==1800
        print('PASS measure rejects exit/limit/watch failures and distinguishes complete from healthy')

        for interruption in (RuntimeError,KeyboardInterrupt):
            calls=[]
            def interrupted(command,prefix,view):
                if calls:
                    saved=json.loads((prefix.parent/'results.json').read_text())
                    assert len(saved['runs'])==1  # saved before starting the next match
                    raise interruption('injected interruption')
                calls.append(prefix)
                return fake_match(command,prefix,view)
            destination=root/interruption.__name__
            with patch.object(benchmark,'environment',return_value={'fixture':True}), \
                 patch.object(benchmark,'run_match',side_effect=interrupted), redirect_stdout(io.StringIO()):
                try:
                    benchmark.measure(destination,repetitions=1)
                except interruption:
                    pass
                else:
                    raise AssertionError('expected measurement interruption')
            saved=json.loads((destination/'results.json').read_text())
            assert len(saved['runs'])==1 and saved['responses']==400
            assert not saved['measurement_complete'] and not saved['all_healthy']
            assert saved['environment_after']=={'fixture':True}
        print('PASS partial JSON survives errors and KeyboardInterrupt with final incomplete flags')
    finally:
        os.chdir(previous)
# Exercise the limit branches with simulated OS dependencies as well as the
# real process tests below; no signal is delivered by this unit test.
with tempfile.TemporaryDirectory(prefix='paint-limit-tests-') as directory:
    for view in (False,True):
        signals=[]
        chunks=iter([b'x'*benchmark.OUTPUT_LIMIT,b'x',b'',b'',b''])
        polls_after_signal=[]
        class Process:
            pid=4321
            returncode=None
            def __init__(self,command,**kwargs):
                assert kwargs['start_new_session']
                if not view:
                    kwargs['stdout'].write(b'x'*(benchmark.OUTPUT_LIMIT+1))
                    kwargs['stdout'].flush()
        def wait(pid,options):
            if signals:
                polls_after_signal.append(True)
                assert options==0  # block to reap after the one stop signal
            return (pid,9,SimpleNamespace(ru_utime=0.1,ru_stime=0.1,ru_maxrss=1024)) if signals else (0,0,None)
        with patch.object(benchmark.subprocess,'Popen',Process), \
             patch.object(benchmark.os,'killpg',side_effect=lambda pid,sig: signals.append((pid,sig))), \
             patch.object(benchmark.os,'wait4',side_effect=wait), \
             patch.object(benchmark.pty,'openpty',return_value=(100,101)), \
             patch.object(benchmark.fcntl,'ioctl'), \
             patch.object(benchmark.select,'select',return_value=([100],[],[])), \
             patch.object(benchmark.os,'read',side_effect=lambda fd,size: next(chunks,b'')), \
             patch.object(benchmark.os,'close'):
            result=benchmark.run_match(['fixture'],Path(directory)/str(view),view)
        assert signals==[(4321,benchmark.signal.SIGKILL)]
        assert len(polls_after_signal)==1
        assert result['killed_by_measurement_limit'] and result['exit']==-9
        assert (Path(directory)/result['stdout']).stat().st_size==benchmark.OUTPUT_LIMIT
print('PASS simulated OS confirms plain/PTY limit detection, group kill and bounded retained output')

for error in (PermissionError,ProcessLookupError):
    completed=(4321,0,SimpleNamespace(ru_utime=0,ru_stime=0,ru_maxrss=1024))
    with patch.object(benchmark.os,'killpg',side_effect=error('already exiting')) as kill, \
         patch.object(benchmark.os,'wait4',side_effect=[(0,0,None),(0,0,None),completed]), \
         patch.object(benchmark.time,'sleep'):
        assert benchmark.stop_group(SimpleNamespace(pid=4321))==completed
        assert kill.call_count==1
    with patch.object(benchmark.os,'killpg',side_effect=error('still running')) as kill, \
         patch.object(benchmark.os,'wait4',return_value=(0,0,None)) as wait, \
         patch.object(benchmark.time,'sleep'):
        try:
            benchmark.stop_group(SimpleNamespace(pid=4321))
        except error:
            pass
        else:
            raise AssertionError('an unconfirmed exit must not hide signal errors')
        assert kill.call_count==1 and wait.call_count==10
print('PASS stop races accept only confirmed exits; genuine signal denial remains an error')

if not args.unit_only:
    with tempfile.TemporaryDirectory(prefix='paint-benchmark-tests-') as directory:
        root=Path(directory)
        r=benchmark.run_match([sys.executable,'-c','print("measurement fixture")'],root/'normal',False)
        assert r['exit']==0 and r['wall_seconds']>0 and r['child_maxrss_kib']>0
        assert r['user_seconds']>=0 and r['system_seconds']>=0
        assert (root/r['stdout']).read_bytes()==b'measurement fixture\n'
        r=benchmark.run_match([sys.executable,'-c','import sys; print("kept"); sys.exit(3)'],root/'nonzero',False)
        assert r['exit']==3 and (root/r['stdout']).read_bytes()==b'kept\n'
        print('PASS wait4 measurement records wall/CPU/RSS and preserves nonzero-run output')
        r=benchmark.run_match([sys.executable,'-c','import time; time.sleep(10)'],root/'timeout',False,timeout=0.02)
        assert r['exit']<0 and r['killed_by_measurement_limit']
        print('PASS measurement deadline terminates the process group and records the limit')
        r=benchmark.run_match([sys.executable,'-c','print("Paint battle | Turn 200/200")'],root/'pty',True)
        assert r['exit']==0 and r['watch_frames']==1 and b'Turn 200/200' in (root/r['stdout']).read_bytes()
        print('PASS real 64x24 PTY execution is drained through process exit')
        for view in (False,True):
            r=benchmark.run_match([sys.executable,'-c',
                'import os,time; os.write(1,b"x"*(3*1024*1024)); time.sleep(10)'],
                root/('overflow-'+str(view)),view)
            assert r['exit']<0 and r['killed_by_measurement_limit']
            assert (root/r['stdout']).stat().st_size==benchmark.OUTPUT_LIMIT
        # Also check a quick exit; the child may finish before the polling loop sees size.
        r=benchmark.run_match([sys.executable,'-c','import os; os.write(1,b"x"*(3*1024*1024))'],
                              root/'overflow-exit',False)
        assert r['killed_by_measurement_limit']
        assert (root/r['stdout']).stat().st_size==benchmark.OUTPUT_LIMIT
        print('PASS 2MiB stdout limit stops plain/PTY writers and caps retained output even on quick exit')

        for view in (False,True):
            for tag,size,pause in [('boundary',benchmark.OUTPUT_LIMIT,False),
                                   ('overflow',benchmark.OUTPUT_LIMIT+1,True),
                                   ('quick-exit',3*benchmark.OUTPUT_LIMIT,False)]:
                script=('import os,time; os.write(1,b"stdout retained\\n"); '
                        f'os.write(2,b"e"*{size}); '+('time.sleep(10)' if pause else ''))
                r=benchmark.run_match([sys.executable,'-c',script],root/('stderr-'+tag+'-'+str(view)),view)
                assert (root/r['stderr']).read_bytes()==b'e'*benchmark.OUTPUT_LIMIT
                assert b'stdout retained' in (root/r['stdout']).read_bytes()
                if size==benchmark.OUTPUT_LIMIT:
                    assert r['exit']==0 and not r['killed_by_measurement_limit']
                else:
                    assert r['killed_by_measurement_limit']
                    if pause:
                        assert r['exit']<0
        print('PASS 2MiB stderr boundary, forced stop and quick-exit cap in plain/PTY modes preserve stdout')

print('PASS '+('7 benchmark unit groups' if args.unit_only else '12 benchmark groups')+', 0 failures'+(' (real child-process checks not requested)' if args.unit_only else ''))
