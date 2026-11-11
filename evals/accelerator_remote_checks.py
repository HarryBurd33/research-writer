#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable contracts and an opt-in, disposable native MPS SSH fixture."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'research-writer' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import accelerator_remote_tools as client
import accelerator_remote_worker as wire
import accelerator_tools as accelerator
from accelerator_checks import synthetic_result
from transport_common import save_state

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-ssh', action='store_true')
for option in ('python', 'site-packages', 'model-dir', 'evidence-dir'):
    parser.add_argument('--' + option, type=Path)
ARGS, REST = parser.parse_known_args()


def selected_profile(identity, python, site, runtime, scripts, model, jobs, ssh):
    return {'contract': wire.CONTRACT, 'ssh': ssh, 'source_pins': client.source_pins(),
            'target': {'hostname': identity['hostname'], 'user': identity['user'], 'python': str(python),
                       'site_packages': str(site), 'scripts': str(scripts), 'model': str(model),
                       'jobs': str(jobs), 'runtime': runtime},
            'workload': {'contract': accelerator.CONTRACT, 'expected_hostname': identity['hostname'],
                         'expected_user': identity['user'], 'device': 'mps', 'wall_seconds': 45,
                         'max_log_bytes': 16384, 'max_result_bytes': wire.MAX_RESULT,
                         'max_accelerator_memory_bytes': 1024 * 1024**2, 'threads': 1}}


class PortableContracts(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rw-gpu-transport-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.directory = self.root / 'state'
        self.fixture = self.root / 'control.fasta'
        self.fixture.write_bytes(accelerator.CONTROL)
        self.profile_path = self.root / 'profile.json'
        identity = wire.identity()
        pin = {'version': 'synthetic', 'metadata_sha256': '1' * 64, 'record_sha256': '2' * 64}
        runtime = {'identity': identity, 'python': '/fixture/runtime/python', 'python_version': '3.12.0',
                   'site_packages': '/fixture/runtime/packages', 'python_sha256': '3' * 64,
                   'pyvenv_cfg_sha256': None, 'distributions': {name: pin.copy()
                       for name in ('torch', 'transformers', 'safetensors')}}
        key = self.root / 'key-placeholder'
        key.touch()
        key_prefix = bytes.fromhex('0000000b') + b'ssh-ed25519' + bytes.fromhex('00000020')
        ssh = {'host': '127.0.0.1', 'port': 2222, 'identity_file': str(key),
               'ed25519_host_key': 'ssh-ed25519 ' + base64.b64encode(key_prefix + b'1' * 32).decode(),
               'connect_timeout_seconds': 3}
        self.p = selected_profile(identity, runtime['python'], runtime['site_packages'], runtime,
                                  SCRIPTS, '/fixture/model/directory', '/fixture/private/jobs', ssh)

    def prepare_without_network(self):
        with patch.object(client, 'rpc', side_effect=client.RPCError('Synthetic lost prepare acknowledgement')):
            response = client.prepare(self.p, self.directory, self.fixture)
        self.assertEqual(response['status'], 'uncertain')
        return client.load_job(self.p, self.directory)[1]

    def test_fixed_profile_and_pins_fail_before_transfer(self):
        save_state(self.profile_path, self.p)
        self.assertEqual(client.profile(self.profile_path), self.p)
        cases = [
            ('workload', 'device', device) for device in ('cpu', 'auto', 'mps:0', 'cuda:16', 'rocm:0')
        ] + [('ssh', 'password', 'unexpected'), ('ssh', 'ed25519_host_key', 'wrong'),
             ('target', 'python', '/different/runtime/python'), ('target', 'user', 'different'),
             ('source_pins', 'accelerator_tools.py', '0' * 64)]
        for category, key, value in cases:
            with self.subTest(category=category, key=key, value=value):
                changed = copy.deepcopy(self.p)
                changed[category][key] = value
                save_state(self.profile_path, changed)
                with self.assertRaises(ValueError):
                    client.profile(self.profile_path)

    def test_bound_prepare_lost_ack_and_read_only_recover(self):
        binding = self.prepare_without_network()
        with patch.object(client, 'rpc', side_effect=lambda p, req: wire.state_for(req, 'prepared', executed=False)):
            status = client.operate(self.p, 'recover', self.directory)
        self.assertEqual(status['status'], 'prepared')
        self.assertEqual(status['job_id'], binding['job_id'])
        self.assertFalse((self.directory / 'submit-intent.json').exists())
        changed = copy.deepcopy(self.p)
        changed['ssh']['port'] += 1
        with self.assertRaises(ValueError):
            client.load_job(changed, self.directory)

    def test_submit_concurrent_and_lost_ack_are_one_dispatch(self):
        binding = self.prepare_without_network()
        barrier = threading.Barrier(2)
        submissions = []

        def transport(p, req):
            if req['operation'] == 'status':
                barrier.wait(timeout=3)
                return wire.state_for(req, 'prepared', executed=False)
            self.assertEqual(req['operation'], 'submit')
            intent = wire.load_json(self.directory / 'submit-intent.json')
            self.assertEqual(intent, wire.state_for(req, 'dispatch_intent'))
            submissions.append(req['binding']['job_id'])
            raise client.RPCError('Synthetic lost submit acknowledgement')

        def submit():
            try:
                return client.operate(self.p, 'submit', self.directory)['status']
            except FileExistsError:
                return 'already_claimed'

        with patch.object(client, 'rpc', side_effect=transport):
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = tuple(pool.map(lambda unused: submit(), range(2)))
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                client.operate(self.p, 'submit', self.directory)
        self.assertCountEqual(statuses, ['uncertain', 'already_claimed'])
        self.assertEqual(submissions, [binding['job_id']])
        with patch.object(client, 'rpc', side_effect=lambda p, req: wire.state_for(req, 'not_found')):
            self.assertEqual(client.operate(self.p, 'recover', self.directory)['status'], 'uncertain')

    def test_collection_refuses_corruption_before_publishing(self):
        binding = self.prepare_without_network()
        req = client.envelope(self.p, 'collect', binding)
        request = wire.workload_request(req, accelerator, client.protein)
        result = synthetic_result(request)
        runtime = self.p['target']['runtime']
        result.update(identity={**runtime['identity'], 'python': runtime['python'],
                                'python_version': runtime['python_version']},
                      device_requested='mps',
                      versions={'torch': 'synthetic', 'transformers': 'synthetic', 'cuda_runtime': None})
        result['accelerator'].update(total_memory_bytes=2 * 1024**3, reserved_or_driver_bytes=1000,
                                     memory_measurement='mps_allocator_limit_and_terminal_observation_not_exact_peak')
        raw = wire.canonical(result)
        response = wire.state_for(req, 'succeeded', result_sha256=wire.digest(raw), result_bytes=len(raw),
                                  comparison=result['comparison'], elapsed_seconds=1,
                                  result_base64=base64.b64encode(raw).decode())
        destination = self.root / 'result.json'
        altered = {**response, 'result_base64': base64.b64encode(raw[:-1] + b'!').decode()}
        with self.assertRaisesRegex(ValueError, 'checksum'):
            client.collect(req, altered, destination)
        altered = copy.deepcopy(result)
        altered['identity']['python'] = '/different/runtime/python'
        wrong_runtime = wire.canonical(altered)
        with self.assertRaisesRegex(ValueError, 'runtime'):
            client.collect(req, {**response, 'result_sha256': wire.digest(wrong_runtime),
                                 'result_bytes': len(wrong_runtime),
                                 'result_base64': base64.b64encode(wrong_runtime).decode()}, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(client.collect(req, response, destination)['comparison']['elements'], 8320)
        self.assertEqual(destination.read_bytes(), raw)
        with self.assertRaises(FileExistsError):
            client.collect(req, response, destination)

    def test_stale_controller_is_uncertain_even_with_raw_file(self):
        binding = self.prepare_without_network()
        req = client.envelope(self.p, 'status', binding)
        state = wire.state_for(req, 'running', heartbeat=1, pid=12345)
        save_state(self.directory / 'state.json', state)
        (self.directory / 'result.json').write_bytes(b'pretend stale output')
        self.assertEqual(wire.snapshot(req, self.directory)['status'], 'uncertain')
        self.assertEqual(wire.load_json(self.directory / 'state.json'), state)


@unittest.skipUnless(ARGS.run_ssh, 'Explicit native MPS SSH test not requested')
class NativeMpsSsh(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the pre-existing disposable fixture, never the user's sshd.
        from remote_loopback_checks import LoopbackChecks
        if not all((ARGS.python, ARGS.site_packages, ARGS.model_dir, ARGS.evidence_dir)):
            raise RuntimeError('Native fixture requires explicit Python, site-packages, model and evidence paths')
        cls.evidence = ARGS.evidence_dir.absolute()
        cls.evidence.mkdir(mode=0o700)
        cls.cleanup = classmethod(LoopbackChecks.cleanup.__func__).__get__(None, cls)
        LoopbackChecks.setUpClass.__func__(cls)
        cls.addClassCleanup(cls.cleanup)
        cls.addClassCleanup(cls.archive_server_log)
        cls.python = ARGS.python.absolute()  # The selected venv path is intentionally literal.
        proc = subprocess.run([str(cls.python), '-I', '-S', '-B', str(SCRIPTS / 'accelerator_remote_worker.py'),
                               '--inventory', '--site-packages', str(ARGS.site_packages.absolute())],
                              timeout=15, capture_output=True)
        (cls.evidence / 'runtime-inventory.stderr').write_bytes(proc.stderr)
        proc.check_returncode()
        runtime = wire.decode(proc.stdout)
        (cls.evidence / 'runtime-inventory.json').write_bytes(proc.stdout)
        if runtime['identity']['os'] != 'Darwin' or runtime['identity']['machine'] != 'arm64':
            raise RuntimeError('Native fixture requires the selected Apple Silicon MPS host')
        cls.jobs = cls.root / 'accelerator jobs'
        cls.jobs.mkdir(mode=0o700)
        cls.p = selected_profile(runtime['identity'], cls.python, ARGS.site_packages.absolute(), runtime,
                                 SCRIPTS, ARGS.model_dir.absolute(), cls.jobs,
                                 {'host': '127.0.0.1', 'port': cls.port, 'identity_file': str(cls.root / 'client'),
                                  'ed25519_host_key': ' '.join((cls.root / 'host.pub').read_text().split()[:2]),
                                  'connect_timeout_seconds': 5})

    @classmethod
    def archive_server_log(cls):
        log = cls.root / 'server.log'
        if log.is_file():
            shutil.copyfile(log, cls.evidence / 'fixture-sshd.log')

    def setUp(self):
        self.case = self.evidence / self._testMethodName
        self.case.mkdir(mode=0o700)
        self.state = self.case / 'local-state'
        self.profile_path = self.case / 'profile.json'
        self.input_path = self.case / 'control.fasta'
        self.input_path.write_bytes(accelerator.CONTROL)
        self.profile_value = copy.deepcopy(self.p)
        self.counter = 0

    def configure(self, wall=45):
        self.profile_value['workload']['wall_seconds'] = wall
        save_state(self.profile_path, self.profile_value)

    def call(self, op, *extra, expect=0, drop_ack=False):
        self.counter += 1
        stem = self.case / f'{self.counter:02d}-{op}'
        output = stem.with_suffix('.json')
        prefix = [sys.executable, str(SCRIPTS / 'accelerator_remote_tools.py')]
        if drop_ack:
            # Transport fault only: the authentic SSH worker dispatches and
            # replies. The capture cap discards that reply and closes the client.
            code = """import sys
sys.path.insert(0, sys.argv.pop(1))
import accelerator_remote_tools as c
real = c.run_bounded
def drop(argv, payload, **kw):
    if c.wire.decode(payload)['operation'] in {'prepare', 'submit'}:
        kw['max_stdout'] = 0
    return real(argv, payload, **kw)
c.run_bounded = drop
raise SystemExit(c.main())
"""
            prefix = [sys.executable, '-c', code, str(SCRIPTS)]
        argv = [*prefix, op, '--profile', str(self.profile_path), '--output', str(output), *map(str, extra)]
        if op != 'inspect':
            argv.extend(('--directory', str(self.state)))
        proc = subprocess.run(argv, timeout=20, capture_output=True)
        stem.with_suffix('.stdout').write_bytes(proc.stdout)
        stem.with_suffix('.stderr').write_bytes(proc.stderr)
        self.last_stderr = proc.stderr.decode(errors='replace')
        if expect is not None:
            self.assertEqual(proc.returncode, expect, self.last_stderr)
        return wire.load_json(output) if output.exists() else None

    def prepare(self, drop_ack=False):
        reply = self.call('prepare', '--allow-transfer', '--input', self.input_path,
                          expect=2 if drop_ack else 0, drop_ack=drop_ack)
        if drop_ack:
            self.assertIn('stdout exceeds 0 bytes', reply['reason'])
            self.assertEqual(reply['status'], 'uncertain')
            reply = self.call('recover')
        self.assertEqual(reply['status'], 'prepared')
        self.assertIs(reply['executed'], False)
        return self.jobs / reply['job_id']

    def terminal(self, expected):
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            reply = self.call('status', expect=None)
            if reply['status'] in wire.TERMINAL | {'uncertain'}:
                self.assertEqual(reply['status'], expected, reply)
                return reply
            time.sleep(.08)
        self.fail('Native fixture job did not reach terminal state')

    def preserve_remote_receipts(self, job):
        remote = self.case / 'remote-receipts'
        remote.mkdir(mode=0o700)
        for name in ('attempt.json', 'binding.json', 'compute.json', 'controller.json', 'state.json',
                     'control.fasta', 'cancel.request', 'worker.stderr'):
            if (job / name).is_file():
                shutil.copyfile(job / name, remote / name)

    def owned_controller(self, req, job, diagnostic):
        # A fixture parent can signal the exact owned Popen. Use the same
        # isolated launcher as SSH with the pinned literal virtualenv Python.
        with tempfile.TemporaryFile() as stdin:
            stdin.write(wire.canonical(req))
            stdin.seek(0)
            return subprocess.Popen([str(self.python), '-I', '-S', '-B', '-c', wire.BOOTSTRAP, 'controller'],
                                    stdin=stdin, stdout=subprocess.DEVNULL, stderr=diagnostic,
                                    start_new_session=True, cwd=job)

    def test_01_authenticated_real_mps_lost_acks_and_collection(self):
        self.configure()
        self.assertEqual(self.call('inspect')['status'], 'verified')
        job = self.prepare(drop_ack=True)
        self.addCleanup(self.preserve_remote_receipts, job)
        lost = self.call('submit', '--allow-execute', expect=2, drop_ack=True)
        self.assertIn('stdout exceeds 0 bytes', lost['reason'])
        self.assertEqual(lost['status'], 'uncertain')
        self.terminal('succeeded')
        self.assertEqual(self.call('recover')['status'], 'succeeded')
        self.call('submit', '--allow-execute', expect=2)
        destination = self.case / 'collected-raw.json'
        receipt = self.call('collect', '--destination', destination)
        raw = destination.read_bytes()
        result = wire.decode(raw)
        self.assertEqual(receipt['result_sha256'], wire.digest(raw))
        self.assertEqual(result['device_observed'], 'mps:0')
        self.assertEqual(result['comparison']['elements'], 8320)
        self.assertTrue((job / 'compute.json').is_file())
        existing = self.case / 'existing-result.json'
        existing.write_bytes(b'keep')
        self.call('collect', '--destination', existing, expect=2)
        self.assertEqual(existing.read_bytes(), b'keep')
        (job / 'result.json').write_bytes(raw[:-1] + b'!')
        corrupted = self.case / 'must-not-publish.json'
        self.call('collect', '--destination', corrupted, expect=2)
        self.assertFalse(corrupted.exists())

    def test_02_cancel_owned_native_worker(self):
        self.configure()
        job = self.prepare()
        self.addCleanup(self.preserve_remote_receipts, job)
        self.call('submit', '--allow-execute')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (job / 'compute.json').is_file():
            time.sleep(.015)
        self.assertTrue((job / 'compute.json').is_file())
        reply = self.call('cancel', '--allow-cancel')
        self.assertTrue(reply.get('cancel_requested') or reply['status'] == 'cancelled')
        self.terminal('cancelled')
        self.call('submit', '--allow-execute', expect=2)

    def test_03_native_worker_deadline(self):
        self.configure(wall=1)
        job = self.prepare()
        self.addCleanup(self.preserve_remote_receipts, job)
        self.call('submit', '--allow-execute')
        self.assertIn('deadline', self.terminal('timed_out')['reason'])
        self.call('submit', '--allow-execute', expect=2)

    def test_04_real_controller_death_uncertain_without_replay(self):
        self.configure(wall=10)
        job = self.prepare()
        self.addCleanup(self.preserve_remote_receipts, job)
        _, binding = client.load_job(self.profile_value, self.state)
        req = client.envelope(self.profile_value, 'controller', binding)
        save_state(self.state / 'submit-intent.json', wire.state_for(req, 'dispatch_intent'), exclusive=True)
        save_state(job / 'attempt.json', wire.state_for(req, 'dispatch_intent'), exclusive=True)
        save_state(job / 'state.json', wire.state_for(req, 'launching', heartbeat=time.time()))
        # Fixture owns this process handle directly, using the identical
        # reviewed detached launcher. No saved/rediscovered PID is signalled.
        with (self.case / 'controller.stderr').open('wb') as diagnostic:
            controller = self.owned_controller(req, job, diagnostic)
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not (job / 'compute.json').is_file():
                    self.assertIsNone(controller.poll())
                    time.sleep(.015)
                self.assertTrue((job / 'compute.json').is_file())
            finally:
                if controller.poll() is None:
                    controller.kill()
                controller.wait(timeout=3)
        self.assertEqual(controller.returncode, -9)
        time.sleep(wire.STALE_SECONDS + 0.3)
        self.assertEqual(self.call('recover', expect=2)['status'], 'uncertain')
        with (self.case / 'restarted-controller.stderr').open('wb') as diagnostic:
            restarted = self.owned_controller(req, job, diagnostic)
            self.assertNotEqual(restarted.wait(timeout=4), 0)
        self.assertIn(b'Controller requires a launching reservation',
                      (self.case / 'restarted-controller.stderr').read_bytes())
        self.assertEqual(self.call('recover', expect=2)['status'], 'uncertain')
        self.call('submit', '--allow-execute', expect=2)
        self.call('collect', '--destination', self.case / 'must-not-publish.json', expect=2)

    def test_05_host_key_runtime_and_source_refusals(self):
        self.configure()
        wrong_key = copy.deepcopy(self.profile_value)
        wrong_key['ssh']['ed25519_host_key'] = ' '.join((self.root / 'client.pub').read_text().split()[:2])
        save_state(self.profile_path, wrong_key)
        self.call('inspect', expect=2)
        self.assertIn('Host key verification failed', self.last_stderr)
        wrong_runtime = copy.deepcopy(self.profile_value)
        wrong_runtime['target']['runtime']['python_sha256'] = '0' * 64
        save_state(self.profile_path, wrong_runtime)
        self.call('inspect', expect=2)
        self.assertIn('Selected Python runtime pin differs', self.last_stderr)
        alternate = self.root / 'wrong reviewed installation'
        alternate.mkdir(mode=0o700)
        for name in wire.SOURCE_NAMES:
            shutil.copyfile(SCRIPTS / name, alternate / name)
        with (alternate / 'protein_tools.py').open('ab') as stream:
            stream.write(b'\n# intentionally changed test source\n')
        changed = copy.deepcopy(self.profile_value)
        changed['target']['scripts'] = str(alternate)
        save_state(self.profile_path, changed)
        self.call('inspect', expect=2)
        self.assertIn('Installed skill source hash differs: protein_tools.py', self.last_stderr)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *REST])
