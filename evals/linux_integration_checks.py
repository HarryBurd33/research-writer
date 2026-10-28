#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Required actual Linux/Docker controls. No implicit engine/image or passing skips."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
spec = importlib.util.spec_from_file_location('rw_linux', SCRIPTS / 'linux_tools.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
CONFIG = None


class LinuxActual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux':
            raise RuntimeError('Actual Linux runner is required; this is not a passing skip')
        cls.base = tempfile.TemporaryDirectory(prefix='rw-linux-actual-')
        cls.root = Path(cls.base.name).resolve()
        p = {'schema_version': 1, 'docker_executable': CONFIG.docker, 'context': CONFIG.context,
             'expected_engine_id': None, 'container_python': '/usr/local/bin/python'}
        p = mod.profile(p); info = mod.inspect_engine(p); p['expected_engine_id'] = info['id']
        cls.p = p; cls.states = []
        mod.inspect_image(p, CONFIG.image_id)
        print(json.dumps({'actual_linux_engine': info, 'image_id': CONFIG.image_id}), flush=True)

    @classmethod
    def tearDownClass(cls):
        errors = []
        for path in cls.states:
            try:
                mod.operate('cleanup', path, allow_remove=True)
            except Exception as exc:
                errors.append(str(exc))
                # Disposable acceptance may remove its exact privately generated name
                # even if production validation failed; never touch unrelated objects.
                try:
                    state = mod.read_json(path / 'state.json')
                    mod.docker(cls.p, ['rm', '--force', state['container_name']], allow_missing=True)
                except Exception:
                    pass
        cls.base.cleanup()
        if errors:
            raise AssertionError('Production cleanup failed: ' + repr(errors))

    def job(self, code, resources=None, inputs=None, outputs=None, submit=True):
        job_root = self.root / uuid.uuid4().hex; job_root.mkdir()
        m = {'schema_version': 1, 'job_id': uuid.uuid4().hex, 'image_id': CONFIG.image_id,
             'argv': ['/usr/local/bin/python', '-c', code], 'inputs': [], 'outputs': outputs or ['result.json'],
             'required_device': 'cpu', 'resources': {'wall_seconds': 8, 'retention_seconds': 30,
             'memory_bytes': 64 * 1024**2, 'cpu_millis': 500, 'pids': 32,
             'work_bytes': 2 * 1024**2, 'tmp_bytes': 1024**2,
             'max_log_bytes': 1024, 'max_output_bytes': 65536}}
        m['resources'].update(resources or {})
        for name, raw in (inputs or {}).items():
            path = job_root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            m['inputs'].append({'source': name, 'destination': name, 'sha256': mod.digest(raw)})
        manifest_path = job_root / 'manifest.json'; mod.save(manifest_path, m, True)
        state = job_root / 'state'; mod.prepare(self.p, manifest_path, state, True); self.states.append(state)
        if submit:
            result = mod.operate('submit', state, allow_execute=True)
            self.assertEqual(result['state'], 'submitted')
        return state

    def terminal(self, state, timeout=18):
        until = time.monotonic() + timeout; last = None
        while time.monotonic() < until:
            try:
                last = mod.operate('recover', state)
                if last['state'] in mod.TERMINAL | {'artifacts_unavailable'}:
                    print(json.dumps({'control': self.id(), 'container_id': last.get('container_id'),
                                      'state': last['state'], 'reason': last.get('reason'),
                                      'effective_limits': last.get('effective_limits'),
                                      'cgroup_counters': last.get('cgroup_counters')}), flush=True)
                    return last
            except ValueError as exc:
                # A read-only exec may race PID1 initialization or namespace cleanup.
                last = {'read_uncertain': str(exc)}
            time.sleep(0.1)
        self.fail('No terminal receipt: ' + repr(last))

    def collected(self, state):
        destination = state.parent / ('collected-' + uuid.uuid4().hex)
        result = mod.operate('collect', state, destination=destination)
        self.assertTrue(result['collected']); self.assertTrue((destination / '.collection.json').is_file())
        return result, destination

    def test_01_actual_limits_privileges_readonly_network_nested_collection(self):
        code = """import json,os,socket
from pathlib import Path
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert Path('data/input.txt').read_text()=='control'
try:
 os.kill(1,0)
 raise AssertionError('task could signal root supervisor')
except PermissionError: pass
try:
 Path('data/input.txt').unlink()
 raise AssertionError('task could remove root-owned input')
except PermissionError: pass
try:
 Path('/control/task-forgery').write_text('x')
 raise AssertionError('task wrote private status')
except PermissionError: pass
out={'uid':os.getuid(),'gid':os.getgid(),'caps':status['CapEff'].strip(),'no_new_privileges':status['NoNewPrivs'].strip(),'interfaces':socket.if_nameindex()}
Path('data/result.json').write_text(json.dumps(out))
"""
        state = self.job(code, inputs={'data/input.txt': b'control'}, outputs=['data/result.json'])
        result = self.terminal(state); self.assertEqual(result['state'], 'succeeded')
        limits = result['effective_limits']; self.assertEqual(limits['memory_bytes'], 64 * 1024**2)
        self.assertEqual(limits['swap_bytes'], 0); self.assertEqual(limits['pids'], 32)
        self.assertTrue(all(limits['read_only_checks'].values()))
        for name, bound in [('/work', 2 * 1024**2), ('/tmp', 1024**2), ('/control', 4 * 1024**2), ('/dev/shm', 1024**2)]:
            self.assertLessEqual(limits['scratch_filesystems'][name]['bytes'], bound)
        summary, dest = self.collected(state); out = json.loads((dest / 'data/result.json').read_text())
        self.assertEqual((out['uid'], out['gid'], int(out['caps'], 16), out['no_new_privileges']), (65534, 65534, 0, '1'))
        self.assertEqual([name for _, name in out['interfaces']], ['lo']); self.assertFalse(summary['partial'])

    def test_02_actual_cpu_throttling_rate(self):
        state = self.job("import time,json;from pathlib import Path;t=time.process_time();\nwhile time.process_time()-t<0.6: pass\nPath('result.json').write_text(json.dumps({'cpu_seconds':time.process_time()-t}))", {'cpu_millis': 250})
        result = self.terminal(state); self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['effective_limits']['cpu_millis'], 250)
        self.assertGreater(int(result['cgroup_counters']['cpu.stat']['nr_throttled']), 0)
        _, dest = self.collected(state); self.assertGreaterEqual(json.loads((dest / 'result.json').read_text())['cpu_seconds'], 0.6)

    def test_03_actual_memory_pressure(self):
        state = self.job("from pathlib import Path;Path('result.json').write_text('started');x=bytearray(512*1024*1024)")
        result = self.terminal(state)
        self.assertIn(result['state'], {'failed', 'artifacts_unavailable'})
        if result['state'] == 'failed':
            self.assertGreater(int(result['cgroup_counters']['memory.events']['oom_kill']), 0)
            summary, _ = self.collected(state); self.assertTrue(summary['partial'])
        else:
            self.assertTrue(result['oom_killed'])

    def test_04_actual_pid_pressure(self):
        code = """import errno,json,os,signal,time
from pathlib import Path
children=[];blocked=False
try:
 for i in range(100):
  try: p=os.fork()
  except OSError as exc:
   assert exc.errno==errno.EAGAIN;blocked=True;break
  if p==0: time.sleep(30);os._exit(0)
  children.append(p)
finally:
 for p in children: os.kill(p,signal.SIGKILL)
 for p in children: os.waitpid(p,0)
Path('result.json').write_text(json.dumps({'blocked':blocked,'children':len(children)}))
"""
        state = self.job(code, {'pids': 16}); result = self.terminal(state)
        self.assertEqual(result['state'], 'succeeded'); self.assertGreater(int(result['cgroup_counters']['pids.events']['max']), 0)
        _, dest = self.collected(state); out = json.loads((dest / 'result.json').read_text())
        self.assertTrue(out['blocked']); self.assertLess(out['children'], 100)

    def test_05_actual_work_tmp_and_inode_exhaustion(self):
        code = """import errno,json,os
from pathlib import Path
out={}
for base in (Path('/work'),Path('/tmp'),Path('/dev/shm')):
 p=base/'fill'
 try:
  with p.open('wb') as f:
   for _ in range(64): f.write(b'x'*65536);f.flush()
 except OSError as exc: out[str(base)]=exc.errno==errno.ENOSPC
 finally:
  if p.exists():p.unlink()
files=[]
try:
 for i in range(2000):
  p=Path('/tmp')/('inode'+str(i));p.touch();files.append(p)
except OSError as exc: out['inodes']=exc.errno==errno.ENOSPC
finally:
 for p in files:p.unlink()
Path('result.json').write_text(json.dumps(out))
"""
        state = self.job(code, {'work_bytes': 1024**2}); result = self.terminal(state)
        self.assertEqual(result['state'], 'succeeded'); _, dest = self.collected(state)
        self.assertEqual(json.loads((dest / 'result.json').read_text()), {'/work': True, '/tmp': True, '/dev/shm': True, 'inodes': True})

    def test_06_lost_client_reply_recovers_same_container_and_wall_kills_setsid(self):
        code = """import subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable,'-c',"import time;from pathlib import Path;Path('escaped.pid').write_text(str(__import__('os').getpid()));time.sleep(60)"],start_new_session=True)
Path('result.json').write_text('started')
time.sleep(60)
"""
        state = self.job(code, {'wall_seconds': 2}, submit=False)
        helper = """import importlib.util,os,sys
s=importlib.util.spec_from_file_location('client',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
original=m.docker
def interrupted(p,args,**kwargs):
 result=original(p,args,**kwargs)
 if args[0]=='run': os._exit(97)
 return result
m.docker=interrupted
m.operate('submit',sys.argv[2],allow_execute=True)
"""
        crashed = subprocess.run([sys.executable, '-c', helper, str(SCRIPTS / 'linux_tools.py'), str(state)], timeout=30)
        self.assertEqual(crashed.returncode, 97)
        saved = mod.read_json(state / 'state.json'); self.assertTrue(saved['submit_attempted']); self.assertIsNone(saved['container_id'])
        result = self.terminal(state); self.assertEqual(result['state'], 'timed_out')
        first_id = mod.read_json(state / 'state.json')['container_id']
        for operation in ('recover', 'recover', 'submit'):
            again = mod.operate(operation, state, allow_execute=True)
            self.assertEqual(again['container_id'], first_id); self.assertFalse(again['reexecuted'])
        saved = mod.read_json(state / 'state.json')
        raw = mod.docker(self.p, ['exec', first_id, '/usr/local/bin/python', '-c', "from pathlib import Path;print([p.name for p in Path('/proc').iterdir() if p.name.isdigit() and p.stat().st_uid==65534])"])
        self.assertEqual(raw.strip(), b'[]')
        summary, _ = self.collected(state); self.assertTrue(summary['partial'])

    def test_07_actual_cancel_log_and_output_bounds(self):
        state = self.job("import sys,time;from pathlib import Path;Path('result.json').write_text('partial');sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(30)")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                status = mod.operate('status', state)
                if status.get('state') == 'running': break
            except ValueError: pass
            time.sleep(0.1)
        time.sleep(0.3); mod.operate('cancel', state, allow_cancel=True)
        result = self.terminal(state); self.assertEqual(result['state'], 'cancelled')
        summary, dest = self.collected(state); self.assertTrue(summary['partial'])
        self.assertLessEqual((dest / '.logs/stdout.log').stat().st_size, 1024)
        self.assertTrue(result['log_truncated']['stdout'])

    def test_08_actual_unsafe_and_oversized_outputs(self):
        for code in ("import os;os.symlink('/etc/hosts','result.json')", "from pathlib import Path;Path('result.json').write_bytes(b'x'*65537)", "import os;from pathlib import Path;Path('other').write_text('x');os.link('other','result.json')"):
            state = self.job(code); result = self.terminal(state)
            self.assertEqual(result['state'], 'failed'); self.assertEqual(result['artifacts'], [])
            with self.assertRaises(ValueError): self.collected(state)

    def test_09_actual_expiry_and_pid1_loss_do_not_claim_success(self):
        state = self.job("from pathlib import Path;Path('result.json').write_text('ok')", {'retention_seconds': 5})
        result = self.terminal(state); self.assertEqual(result['state'], 'succeeded')
        time.sleep(6)
        result = mod.operate('recover', state); self.assertEqual(result['state'], 'artifacts_unavailable')
        self.assertFalse(mod.operate('collect', state, destination=state.parent / 'expired')['collected'])
        state2 = self.job("import time;time.sleep(30)")
        saved = mod.read_json(state2 / 'state.json'); mod.inspect_container(saved)
        mod.docker(self.p, ['kill', '--signal=KILL', saved['container_id']])
        result = self.terminal(state2); self.assertEqual(result['state'], 'artifacts_unavailable')

    def test_10_actual_changed_binding_refuses_collection_cancel_cleanup(self):
        state = self.job("from pathlib import Path;Path('result.json').write_text('ok')")
        self.assertEqual(self.terminal(state)['state'], 'succeeded')
        original = mod.read_json(state / 'state.json'); changed = json.loads(json.dumps(original)); changed['container_id'] = '0' * 64
        mod.save(state / 'state.json', changed)
        try:
            for op in ('collect', 'cancel', 'cleanup'):
                with self.assertRaises(ValueError):
                    mod.operate(op, state, allow_cancel=True, allow_remove=True, destination=state.parent / 'bad')
        finally:
            mod.save(state / 'state.json', original)


def main():
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True, help='Existing absolute Docker executable')
    parser.add_argument('--context', required=True, help='Existing explicit local Linux engine context')
    parser.add_argument('--image-id', required=True, help='Existing immutable local image sha256 ID, Python3.10+ at /usr/local/bin/python')
    CONFIG = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LinuxActual)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
