#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Worker contracts and actual bounded POSIX jobs; no SSH/network or credentials."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts/remote_worker.py'
spec = importlib.util.spec_from_file_location('remote_worker_checked', SCRIPT)
W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)


def manifest(code="from pathlib import Path; Path('result.json').write_text('{\"value\": 0}')"):
    return {'schema_version': 1, 'job_id': uuid.uuid4().hex,
            'argv': [sys.executable, '-c', code], 'inputs': [], 'outputs': ['result.json'],
            'resources': {'wall_seconds': 3, 'max_output_bytes': 65536, 'max_log_bytes': 4096, 'threads': 1},
            'required_device': 'cpu'}


class ValidationChecks(unittest.TestCase):
    def test_manifest_bounds_and_unsupported_device(self):
        W.validate_manifest(manifest())
        for key, value in [('wall_seconds', True), ('wall_seconds', 0), ('wall_seconds', 3601),
                           ('threads', 0), ('max_output_bytes', 16777217), ('max_log_bytes', 1048577)]:
            m = manifest(); m['resources'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): W.validate_manifest(m)
        for value in ('cuda', 'mps', 'rocm', None):
            m = manifest(); m['required_device'] = value
            with self.subTest(device=value), self.assertRaises(ValueError): W.validate_manifest(m)

    def test_paths_hashes_and_argv_are_data(self):
        for name in ('../escape', '/absolute', 'a\\b', '.ssh/key', 'a/../x', 'a//b', './x', '.'):
            with self.subTest(path=name), self.assertRaises(ValueError): W.relative(name)
        m = manifest(); m['argv'] = ['python3', '-c', 'print("$(not-shell)")']
        W.validate_manifest(m)
        m['argv'][1] = '\x00'
        with self.assertRaises(ValueError): W.validate_manifest(m)
        m = manifest(); m['outputs'] = ['x', 'x/y']
        with self.assertRaises(ValueError): W.validate_manifest(m)
        m = manifest(); m['inputs'] = [{'source':'data','destination':'result.json','sha256':'0'*64}]
        with self.assertRaises(ValueError): W.validate_manifest(m)

    def test_json_nonfinite_duplicate_and_size_limits(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{', b'x' * (W.MAX_REQUEST + 1)):
            with self.subTest(prefix=raw[:20]), self.assertRaises((ValueError, UnicodeError)): W.parse(raw)
        self.assertEqual(W.parse(b'{"zero":0}'), {'zero':0})

    def test_cli_help_has_no_remote_effect(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0); self.assertIn('trusted-job', r.stdout)


@unittest.skipUnless(os.name == 'posix', 'Actual remote worker supports POSIX hosts only')
class ActualJobChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='remote-worker-test-')
        self.parent = Path(self.tmp.name).resolve(); self.root = self.parent / 'remote-jobs'
        self.jobs = []
        self.ident = W.identity()

    def tearDown(self):
        for req in self.jobs:
            W.handle({**req, 'operation':'cancel'})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(W.handle({**r, 'operation':'status'}).get('status') in W.TERMINAL | {'not_found', 'failed'} for r in self.jobs): break
            time.sleep(0.05)
        self.tmp.cleanup()

    def request(self, m, operation='prepare', files=None):
        return {'protocol':1, 'operation':operation, 'remote_root':str(self.root),
                'expected_hostname':self.ident['hostname'], 'expected_user':self.ident['user'],
                'job_id':m['job_id'], 'manifest_sha256':hashlib.sha256(W.canonical(m)).hexdigest(),
                **({'manifest':m, 'files':files or [], 'worker_source':SCRIPT.read_text(encoding='utf-8')} if operation=='prepare' else {})}

    def prepared(self, m=None, files=None):
        m = m or manifest(); req = self.request(m, files=files)
        result = W.handle(req); self.assertTrue(result['ok'], result); self.assertEqual(result['status'], 'prepared')
        self.jobs.append(req); return m, req

    def await_terminal(self, req, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = W.handle({**req, 'operation':'status'})
            if r.get('status') in W.TERMINAL: return r
            time.sleep(0.05)
        self.fail('Job failed to reach terminal state: ' + repr(r))

    def test_inspect_identity_and_no_directory_creation(self):
        m = manifest(); req = self.request(m, 'inspect'); req['expected_hostname'] = None; req['expected_user'] = None
        r = W.handle(req); self.assertTrue(r['ok']); self.assertEqual(r['status'], 'inspected')
        self.assertFalse(self.root.exists()); self.assertEqual(r['supported_devices'], ['cpu'])
        req['expected_user'] = 'wrong-account'
        self.assertFalse(W.handle(req)['ok']); self.assertFalse(self.root.exists())
        req = self.request(m); req['expected_hostname'] = 'wrong-host'
        self.assertFalse(W.handle(req)['ok']); self.assertFalse(self.root.exists())

    def test_prepare_transfer_hash_space_and_idempotence(self):
        data = b'zero\n'; sha = hashlib.sha256(data).hexdigest(); m = manifest()
        m['inputs'] = [{'source':'source.txt','destination':'data.txt','sha256':sha}]
        f = [{'path':'data.txt','sha256':sha,'data':base64.b64encode(data).decode()}]
        bad = copy.deepcopy(f); bad[0]['data'] = base64.b64encode(b'wrong').decode()
        self.assertFalse(W.handle(self.request(m, files=bad))['ok']); self.assertFalse(self.root.exists())
        with patch.object(W.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=0)):
            self.assertFalse(W.handle(self.request(m, files=f))['ok'])
        self.assertFalse(self.root.exists())
        _, req = self.prepared(m, f)
        self.assertEqual((self.root/m['job_id']/'work/data.txt').read_bytes(), data)
        self.assertTrue(W.handle(req)['already_prepared'])
        m2 = copy.deepcopy(m); m2['argv'][-1] += '; print(1)'
        self.assertFalse(W.handle(self.request(m2, files=f))['ok'])

    def test_real_success_duplicate_submission_and_restart_collection(self):
        code = "from pathlib import Path; p=Path('count');p.write_text(p.read_text()+'x' if p.exists() else 'x');Path('result.json').write_text('{\"value\":0}')"
        m, req = self.prepared(manifest(code))
        first = W.handle({**req, 'operation':'submit'}); self.assertTrue(first['ok'])
        # Lost reply is reconciled by status; replaying server submit remains idempotent.
        again = W.handle({**req, 'operation':'submit'}); self.assertTrue(again['already_submitted'])
        result = self.await_terminal(req); self.assertEqual(result['status'], 'succeeded')
        self.assertEqual((self.root/m['job_id']/'work/count').read_text(), 'x')
        # Fresh process models a restarted client with no in-memory job handle.
        r = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({**req,'operation':'collect'}), text=True, capture_output=True, timeout=10)
        collected = json.loads(r.stdout); self.assertTrue(collected['ok']); self.assertFalse(collected['partial'])
        raw = base64.b64decode(collected['files'][0]['data'])
        self.assertEqual(json.loads(raw), {'value':0}); self.assertEqual(hashlib.sha256(raw).hexdigest(), collected['files'][0]['sha256'])
        self.assertEqual(W.handle({**req,'operation':'submit'})['status'], 'succeeded')

    def test_wrong_binding_and_changed_output_refused(self):
        m, req = self.prepared(); self.assertFalse(W.handle({**req,'operation':'submit','manifest_sha256':'0'*64})['ok'])
        self.assertTrue(W.handle({**req,'operation':'submit'})['ok']); self.await_terminal(req)
        path = self.root/m['job_id']/'work/result.json'; path.write_text('tampered')
        r = W.handle({**req,'operation':'collect'}); self.assertFalse(r['ok']); self.assertIn('changed', r['error']['message'])
        path.unlink(); path.symlink_to(self.parent/'outside.json')
        (self.parent/'outside.json').write_text('outside')
        self.assertFalse(W.handle({**req,'operation':'collect'})['ok'])

    def test_cancel_prelaunch_and_running_owning_child(self):
        _, req = self.prepared()
        self.assertEqual(W.handle({**req,'operation':'cancel'})['status'], 'cancelled')
        self.assertFalse(W.handle({**req,'operation':'submit'})['ok'])
        m, req = self.prepared(manifest("import time; time.sleep(10)"))
        self.assertTrue(W.handle({**req,'operation':'submit'})['ok'])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if W.handle({**req,'operation':'status'})['status'] == 'running': break
            time.sleep(0.05)
        self.assertTrue(W.handle({**req,'operation':'cancel'})['cancel_requested'])
        self.assertEqual(self.await_terminal(req)['status'], 'cancelled')
        collected = W.handle({**req,'operation':'collect'}); self.assertTrue(collected['ok']); self.assertTrue(collected['partial'])

    def test_timeout_nonzero_missing_output_and_output_bounds(self):
        cases = [("import time;time.sleep(10)", 'timed_out'),
                 ("raise SystemExit(7)", 'failed'), ("pass", 'failed'),
                 ("from pathlib import Path;Path('unlisted').write_bytes(b'x'*100000)", 'failed'),
                 ("print('x'*100000)", 'failed')]
        for code, expected in cases:
            with self.subTest(code=code):
                m = manifest(code); m['resources']['wall_seconds'] = 1
                _, req = self.prepared(m); self.assertTrue(W.handle({**req,'operation':'submit'})['ok'])
                self.assertEqual(self.await_terminal(req)['status'], expected)

    def test_exception_path_bounds_logs_without_following_replacements(self):
        # A task emits over-budget logs then makes artifact inspection raise.
        # Log cleanup must still run, preserving the failed outcome.
        outside = self.parent / 'outside.txt'; outside.write_bytes(b'unchanged outside')
        code = "import os;from pathlib import Path;print('x'*10000);Path('result.json').symlink_to(" + repr(str(outside)) + ")"
        m = manifest(code); m['resources']['max_log_bytes'] = 100
        _, req = self.prepared(m); self.assertTrue(W.handle({**req, 'operation':'submit'})['ok'])
        state = self.await_terminal(req); self.assertEqual(state['status'], 'failed')
        job = self.root / m['job_id']
        for name in ('stdout.log', 'stderr.log'):
            self.assertLessEqual((job/name).stat().st_size, 100)
        # Replacing a diagnostic path with a symlink must never truncate its target.
        (job/'stdout.log').unlink(); (job/'stdout.log').symlink_to(outside)
        errors = W.bound_logs(job, 1)
        self.assertTrue(errors); self.assertEqual(outside.read_bytes(), b'unchanged outside')
        self.assertFalse(W.handle({**req,'operation':'collect'})['ok'])

    def test_stale_heartbeat_uncertain_never_resubmits(self):
        m, req = self.prepared(); job=self.root/m['job_id']
        W.atomic(job/'state.json', {'status':'running','heartbeat':time.time()-20,'updated_at':time.time()-20})
        (job/'submission.json').write_text('{}')
        r=W.handle({**req,'operation':'status'});self.assertEqual(r['status'],'uncertain')
        with patch.object(W.subprocess,'Popen',side_effect=AssertionError('Never relaunch')):
            self.assertTrue(W.handle({**req,'operation':'submit'})['already_submitted'])
        self.assertFalse(W.handle({**req,'operation':'collect'})['ok'])
        W.atomic(job/'state.json',{'status':'failed','reason':'fixture closes uncertain controller'})

    def test_metadata_and_work_symlink_refused(self):
        m, req = self.prepared(); job=self.root/m['job_id']
        (job/'manifest.json').rename(job/'original.json');(job/'manifest.json').symlink_to(job/'original.json')
        self.assertFalse(W.handle({**req,'operation':'status'})['ok'])
        (job/'manifest.json').unlink();(job/'original.json').rename(job/'manifest.json')
        (job/'work').rmdir();outside=self.parent/'outside';outside.mkdir();(job/'work').symlink_to(outside)
        W.atomic(job/'state.json',{'status':'failed'});W.atomic(job/'artifacts.json',{})
        self.assertFalse(W.handle({**req,'operation':'collect'})['ok'])


if __name__ == '__main__': unittest.main()
