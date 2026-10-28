#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Required real Linux cooperative-checkpoint capture and explicit continuation."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
def load(name):
    spec = importlib.util.spec_from_file_location('durable_' + name, SCRIPTS / (name + '.py'))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
L = load('linux_tools'); C = load('checkpoint_tools'); CONFIG = None


class DurableLinux(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux': raise RuntimeError('Actual Linux engine required; not a passing skip')
        cls.temp = tempfile.TemporaryDirectory(prefix='rw-durable-linux-'); cls.root = Path(cls.temp.name).resolve(); cls.states = []
        p = L.profile({'schema_version': 1, 'docker_executable': CONFIG.docker, 'context': CONFIG.context,
                       'expected_engine_id': None, 'container_python': '/usr/local/bin/python'})
        engine = L.inspect_engine(p); p['expected_engine_id'] = engine['id']; L.inspect_image(p, CONFIG.image_id); cls.profile = p
        print(json.dumps({'engine': engine, 'image_id': CONFIG.image_id, 'scope': 'actual cooperative file checkpoints, not process-memory snapshots'}), flush=True)

    @classmethod
    def tearDownClass(cls):
        errors = []
        for state in cls.states:
            if not state.exists(): continue
            try: L.operate('cleanup', state, allow_remove=True)
            except Exception as exc:
                errors.append(str(exc))
                try: L.docker(cls.profile, ['rm', '--force', L.read_json(state / 'state.json')['container_name']], allow_missing=True)
                except Exception: pass
        cls.temp.cleanup()
        if errors: raise AssertionError('Owned-container cleanup failed: ' + repr(errors))

    def setUp(self):
        self.work = self.root / uuid.uuid4().hex; self.work.mkdir(); self.store = self.work / 'store'
        C.init_store(self.store, 8 * 1024**2, 8)

    def job(self, code, checkpoint=True, inputs=None):
        root = self.work / uuid.uuid4().hex; root.mkdir()
        m = {'schema_version': 2 if checkpoint else 1, 'job_id': uuid.uuid4().hex, 'image_id': CONFIG.image_id,
             'argv': ['/usr/local/bin/python', '-c', code], 'inputs': [], 'outputs': ['result.json'], 'required_device': 'cpu',
             'resources': {'wall_seconds': 40, 'retention_seconds': 20, 'memory_bytes': 256 * 1024**2,
                           'cpu_millis': 1000, 'pids': 64, 'work_bytes': 8 * 1024**2, 'tmp_bytes': 1024**2,
                           'max_log_bytes': 4096, 'max_output_bytes': 65536}}
        if checkpoint: m['checkpoint'] = {'directory': 'cp', 'max_bytes': 1024**2, 'max_files': 4}
        for name, raw in (inputs or {}).items():
            (root / name).write_bytes(raw); m['inputs'].append({'source': name, 'destination': name, 'sha256': L.digest(raw)})
        manifest = root / 'manifest.json'; L.save(manifest, m, True); state = root / 'state'
        L.prepare(self.profile, manifest, state, True); self.states.append(state)
        self.assertEqual(L.operate('submit', state, allow_execute=True)['state'], 'submitted')
        return state

    def publisher(self, mode='valid', identity=None):
        identity = identity or uuid.uuid4().hex
        code = """import hashlib,json,os,time
from pathlib import Path
g=IDENTITY; d=Path('cp')/g;d.mkdir(parents=True)
raw=b'{"counter":5}';(d/'counter.json').write_bytes(raw)
MODECODE
m={'schema_version':1,'checkpoint_id':g,'application':{'format':'counter','version':'1','resume_notes':'Data only; continuation requires a new explicit job.'},'files':[{'path':NAME,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]}
Path('cp/ready.tmp').write_text(json.dumps(m));os.replace('cp/ready.tmp','cp/ready.json')
Path('result.json').write_text('ready');time.sleep(35)
"""
        extra, name = '', 'counter.json'
        if mode == 'wrong_hash': extra = "(d/'counter.json').write_bytes(b'wrong')"
        elif mode == 'symlink': extra = "(d/'counter.json').unlink();os.symlink('/etc/hosts',d/'counter.json')"
        elif mode == 'hardlink': extra = "os.link(d/'counter.json',d/'second')"
        elif mode == 'fifo': extra = "(d/'counter.json').unlink();os.mkfifo(d/'counter.json')"
        elif mode == 'directory_symlink':
            extra = "Path('/tmp/outside').mkdir();Path('/tmp/outside/counter.json').write_bytes(raw);os.symlink('/tmp/outside',d/'nested')"; name = 'nested/counter.json'
        elif mode == 'traversal':
            extra = "Path('cp/counter.json').write_bytes(raw)"; name = '../counter.json'
        return code.replace('IDENTITY', repr(identity)).replace('MODECODE', extra).replace('NAME', repr(name)), identity

    def ready(self, state):
        saved = L.read_json(state / 'state.json'); deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                L.docker(self.profile, ['exec', saved['container_id'], '/usr/local/bin/python', '-c', "from pathlib import Path;raise SystemExit(0 if Path('/work/result.json').exists() else 1)"])
                return
            except ValueError: time.sleep(.1)
        self.fail('Checkpoint publisher never reached ready state')

    def checkpoint(self, state):
        return L.operate('checkpoint', state, checkpoint_store=self.store, allow_save=True)

    def terminal(self, state):
        deadline = time.monotonic() + 15; result = None
        while time.monotonic() < deadline:
            try:
                result = L.operate('recover', state)
                if result['state'] in L.TERMINAL | {'artifacts_unavailable'}: return result
            except ValueError: pass
            time.sleep(.1)
        self.fail('No terminal state: ' + repr(result))

    def test_01_capture_destroy_original_and_manually_resume_counter(self):
        code, identity = self.publisher(); state = self.job(code); self.ready(state)
        original = L.read_json(state / 'state.json'); captured = self.checkpoint(state)
        self.assertEqual(captured['state'], 'saved'); self.assertEqual(captured['checkpoint_id'], identity)
        self.assertEqual(captured['provenance']['job_id'], original['manifest']['job_id'])
        self.assertEqual(captured['provenance']['container_id'], original['container_id'])
        self.assertEqual(captured['consistency'], C.CONSISTENCY)
        L.operate('cleanup', state, allow_remove=True)
        for path in state.rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(state)
        self.assertFalse(state.exists())
        portable = self.work / 'portable'; C.backup(self.store, portable, True); shutil.rmtree(self.store)
        restore = self.work / 'restored'
        with patch.object(L, 'docker', side_effect=AssertionError('Verification/restore must not execute or contact an engine')):
            C.verify_store(portable, identity); C.restore(portable, identity, restore, True)
        check = self.work / 'fresh-verify.json'
        r = subprocess.run([sys.executable, str(SCRIPTS / 'checkpoint_tools.py'), 'verify', '--store', str(portable), '--checkpoint-id', identity, '--report', str(check)], cwd='/tmp', capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        resume = "import json;from pathlib import Path;n=json.loads(Path('resume.json').read_text())['counter'];Path('result.json').write_text(json.dumps({'counter':n+3}))"
        continued = self.job(resume, checkpoint=False, inputs={'resume.json': (restore / 'counter.json').read_bytes()})
        self.assertNotEqual(L.read_json(continued / 'state.json')['manifest']['job_id'], original['manifest']['job_id'])
        self.assertEqual(self.terminal(continued)['state'], 'succeeded')
        out = self.work / 'continued-output'; L.operate('collect', continued, destination=out)
        self.assertEqual(json.loads((out / 'result.json').read_text()), {'counter': 8})
        self.assertEqual(json.loads((restore / 'counter.json').read_text()), {'counter': 5})
        self.assertEqual(len(C.verify_store(portable)['checkpoints']), 1)
        print(json.dumps({'control': self.id(), 'checkpoint_id': identity, 'original_removed': True, 'saved_counter': 5, 'continued_counter': 8, 'new_job_id': L.read_json(continued / 'state.json')['manifest']['job_id']}), flush=True)

    def test_02_unsafe_declared_files_never_commit(self):
        for mode in ('wrong_hash', 'symlink', 'hardlink', 'fifo', 'directory_symlink', 'traversal'):
            with self.subTest(mode=mode):
                code, _ = self.publisher(mode); state = self.job(code); self.ready(state)
                with self.assertRaises(ValueError): self.checkpoint(state)
                self.assertEqual(C.verify_store(self.store)['checkpoints'], [])
                L.operate('cleanup', state, allow_remove=True)
        print(json.dumps({'control': self.id(), 'rejected': ['wrong_hash', 'symlink', 'hardlink', 'fifo', 'directory_symlink', 'traversal']}), flush=True)

    def test_03_atomic_marker_updates_never_mix_generations(self):
        ids = [uuid.uuid4().hex, uuid.uuid4().hex]
        code = """import hashlib,json,os,time
from pathlib import Path
ids=IDS
for i,g in enumerate(ids):
 d=Path('cp')/g;d.mkdir(parents=True);(d/'counter.json').write_bytes(json.dumps({'counter':i+1}).encode())
def publish(i):
 g=ids[i];raw=(Path('cp')/g/'counter.json').read_bytes()
 m={'schema_version':1,'checkpoint_id':g,'application':{'format':'counter','version':'1','resume_notes':''},'files':[{'path':'counter.json','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]}
 Path('cp/ready.tmp').write_text(json.dumps(m));os.replace('cp/ready.tmp','cp/ready.json')
publish(0);Path('result.json').write_text('ready');until=time.monotonic()+3;i=0
while time.monotonic()<until: publish(i%2);i+=1;time.sleep(.002)
publish(1);Path('stable').write_text('ready');time.sleep(30)
""".replace('IDS', repr(ids))
        state = self.job(code); self.ready(state)
        for _ in range(4):
            try: self.checkpoint(state)
            except ValueError: pass  # Torn declarations must fail, never commit mixed data.
        time.sleep(3); self.assertIn(self.checkpoint(state)['state'], ('saved', 'already_saved'))
        verified = C.verify_store(self.store)
        self.assertGreaterEqual(len(verified['checkpoints']), 1)
        for summary in verified['checkpoints']:
            out = self.work / ('restore-' + summary['checkpoint_id']); C.restore(self.store, summary['checkpoint_id'], out, True)
            self.assertEqual(json.loads((out / 'counter.json').read_text())['counter'], ids.index(summary['checkpoint_id']) + 1)

    def test_04_changed_bindings_refuse_capture(self):
        code, _ = self.publisher(); state = self.job(code); self.ready(state); original = L.read_json(state / 'state.json')
        variants = []
        for field in ('container_id',):
            changed = json.loads(json.dumps(original)); changed[field] = '0' * 64; variants.append(changed)
        changed = json.loads(json.dumps(original)); changed['binding']['nonce'] = '0' * 32; variants.append(changed)
        changed = json.loads(json.dumps(original)); changed['profile']['expected_engine_id'] = 'wrong-engine'; variants.append(changed)
        try:
            for changed in variants:
                L.save(state / 'state.json', changed)
                with self.assertRaises(ValueError): self.checkpoint(state)
                self.assertEqual(C.verify_store(self.store)['checkpoints'], [])
        finally: L.save(state / 'state.json', original)

    def test_05_no_capture_from_stopped_or_nonopted_job(self):
        code, _ = self.publisher(); state = self.job(code); self.ready(state)
        with self.assertRaises(ValueError): L.operate('checkpoint', state, checkpoint_store=self.store)
        L.operate('cleanup', state, allow_remove=True)
        with self.assertRaises(ValueError): self.checkpoint(state)
        old = self.job("from pathlib import Path;import time;Path('result.json').write_text('old');time.sleep(15)", checkpoint=False)
        with self.assertRaises(ValueError): self.checkpoint(old)
        self.assertEqual(C.verify_store(self.store)['checkpoints'], [])

    def test_06_commit_reply_loss_is_idempotent_without_resubmission(self):
        code, identity = self.publisher(); state = self.job(code); self.ready(state)
        helper = """import importlib.util,sys,os
s=importlib.util.spec_from_file_location('l',sys.argv[1]);l=importlib.util.module_from_spec(s);s.loader.exec_module(l)
l.operate('checkpoint',sys.argv[2],checkpoint_store=sys.argv[3],allow_save=True);os._exit(93)
"""
        crashed = subprocess.run([sys.executable, '-c', helper, str(SCRIPTS / 'linux_tools.py'), str(state), str(self.store)], timeout=30)
        self.assertEqual(crashed.returncode, 93)
        self.assertEqual(self.checkpoint(state)['state'], 'already_saved')
        saved = C.verify_store(self.store)
        self.assertEqual([x['checkpoint_id'] for x in saved['checkpoints']], [identity])
        original_id = L.read_json(state / 'state.json')['container_id']
        self.assertEqual(L.operate('recover', state)['container_id'], original_id)
        self.assertFalse(L.operate('recover', state)['reexecuted'])


def main():
    global CONFIG, SCRIPTS, L, C
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True); parser.add_argument('--context', required=True); parser.add_argument('--image-id', required=True)
    parser.add_argument('--skill', type=Path)
    CONFIG = parser.parse_args()
    if CONFIG.skill:
        SCRIPTS = CONFIG.skill.resolve() / 'scripts'; L = load('linux_tools'); C = load('checkpoint_tools')
    return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DurableLinux)).wasSuccessful() else 1


if __name__ == '__main__': raise SystemExit(main())
