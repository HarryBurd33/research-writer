#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable transport contracts and an explicit native Windows SSH gate."""
import base64
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
sys.path.insert(0, str(SCRIPTS))
import transport_common as transport
import windows_remote_tools as win


def manifest(argv, wall=20):
    return {
        'schema_version': 1, 'job_id': uuid.uuid4().hex, 'argv': argv,
        'inputs': [], 'outputs': ['result.txt'], 'required_device': 'cpu',
        'resources': {'wall_seconds': wall, 'max_output_bytes': 4096,
                      'max_log_bytes': 4096, 'threads': 1},
    }


def profile():
    return win.profile({
        'schema_version': 1, 'ssh_alias': 'existing-host',
        'remote_python': r'C:\Python 研究\python.exe', 'remote_root': r'C:\Research Jobs\Worker',
        'expected_hostname': 'WINHOST', 'expected_user': 'worker',
    })


class TransportContracts(unittest.TestCase):
    def run_child(self, code, payload=b'', *, timeout=3, max_input=1024,
                  max_stdout=1024, max_stderr=1024):
        return transport.run_bounded([sys.executable, '-c', code], payload, timeout=timeout,
                                     max_input=max_input, max_stdout=max_stdout, max_stderr=max_stderr)

    def test_binary_roundtrip_and_exact_caps(self):
        raw = b'\x00\r\n\xff' * 16384
        code = ('import sys; raw=sys.stdin.buffer.read(); '
                'sys.stderr.buffer.write(raw[::-1]); sys.stderr.flush(); sys.stdout.buffer.write(raw)')
        result = self.run_child(code, raw, max_input=len(raw), max_stdout=len(raw), max_stderr=len(raw))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, raw, raw[::-1]))
        empty = self.run_child('pass', max_input=0, max_stdout=0, max_stderr=0)
        self.assertEqual((empty.stdout, empty.stderr), (b'', b''))

    def test_caps_checked_before_launch_or_retention(self):
        with patch.object(transport.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(transport.CaptureError, 'stdin exceeds'):
                self.run_child('pass', b'xx', max_input=1)
            launch.assert_not_called()
        for stream, limit in (('stdout', 1024), ('stderr', 512)):
            with self.subTest(stream=stream):
                code = (f'import sys,time; s=sys.{stream}.buffer; '
                        f's.write(b"x"*{limit+1}); s.flush(); time.sleep(30)')
                with self.assertRaisesRegex(transport.CaptureError, f'{stream} exceeds {limit}'):
                    self.run_child(code, max_stdout=1024, max_stderr=512)

    def test_repeated_deadlines_reap_owned_child_and_leave_no_threads(self):
        before = threading.active_count()
        real_launch = subprocess.Popen
        children = []
        def start(*args, **kwargs):
            child = real_launch(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(transport.subprocess, 'Popen', side_effect=start):
            for _ in range(2):
                with self.assertRaisesRegex(transport.CaptureError, 'deadline'):
                    self.run_child('import time; time.sleep(30)', b'x' * (2 * 1024 * 1024),
                                   max_input=2 * 1024 * 1024, timeout=0.5)
        self.assertEqual(len(children), 2)
        for child in children:
            self.assertIsNotNone(child.returncode)
            self.assertTrue(child.stdout.closed and child.stderr.closed)
        self.assertEqual(threading.active_count(), before)

    def test_fsync_before_exclusive_publish_and_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            with patch.object(transport.os, 'fsync', wraps=os.fsync) as sync:
                transport.save_state(path, {'submit_attempted': False}, exclusive=True)
                self.assertEqual(sync.call_count, 1)
                with self.assertRaises(FileExistsError):
                    transport.save_state(path, {'wrong': True}, exclusive=True)
                self.assertFalse(win.core.read_json(path)['submit_attempted'])
                transport.save_state(path, {'submit_attempted': True})
                self.assertTrue(win.core.read_json(path)['submit_attempted'])
                self.assertEqual(sync.call_count, 3)
            with patch.object(transport.os, 'fsync', side_effect=OSError('flush failed')):
                with self.assertRaisesRegex(OSError, 'flush failed'):
                    transport.save_state(path, {'wrong': True})
            self.assertEqual(win.core.read_json(path), {'submit_attempted': True})
            self.assertEqual(list(path.parent.iterdir()), [path])


class WindowsClientContracts(unittest.TestCase):
    def test_profile_and_static_bootstrap(self):
        p = profile()
        for change in ({'extra': 'x'}, {'ssh_alias': '-oProxyCommand=bad'},
                       {'remote_root': r'\\server\share\jobs'}, {'remote_python': 'python.exe'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                win.profile({**p, **change})
        argv = win.ssh_argv(p)
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'UpdateHostKeys=no',
                       'ClearAllForwardings=yes', 'PermitLocalCommand=no', 'ControlPath=none'):
            self.assertIn(option, argv)
        self.assertEqual(argv[-2], 'existing-host')
        decoded = base64.b64decode(argv[-1].split(' -EncodedCommand ')[1]).decode('utf-16le')
        self.assertEqual(decoded, win.PS_BOOTSTRAP)
        self.assertNotIn(p['remote_root'], decoded)
        self.assertNotIn(p['remote_python'], decoded)
        request = {'value': '研究'}
        header, body = win.encode_request(p, request, 'pass').split(b'\n', 1)
        self.assertEqual(json.loads(header), {'python_path': p['remote_python'], 'body_bytes': len(body)})
        self.assertGreater(len(body), len(body.decode('utf-8')))
        self.assertEqual(json.loads(body), {'request': request, 'source': 'pass'})
        polluted = subprocess.CompletedProcess(argv, 0, b'{"ok":true}\nextra\n', b'')
        with patch.object(win, 'run_bounded', return_value=polluted), self.assertRaisesRegex(
                win.core.TransportError, 'Malformed remote JSON'):
            win.rpc(p, request, source='pass')

    def test_windows_aliases_and_reserved_root_refused_before_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'manifest.json'
            state = root / 'state'
            for outputs in (['A.txt', 'a.TXT'], ['.collection.json'],
                            ['.COLLECTION.JSON'], ['.Collection.Json/result.txt']):
                m = manifest(['python', '-c', 'pass'])
                m['outputs'] = outputs
                source.write_bytes(win.core.canonical(m))
                with self.subTest(outputs=outputs), patch.object(win.core, 'input_files') as read, patch.object(win, 'rpc') as rpc:
                    with self.assertRaises(ValueError):
                        win.prepare(profile(), source, state, allow_transfer=True)
                    read.assert_not_called()
                    rpc.assert_not_called()
                    self.assertFalse(state.exists())
            m['outputs'] = ['sub/.collection.json']
            self.assertIs(win.validate_manifest(m), m)

    def test_identity_and_receipt_bindings(self):
        p = profile()
        req = win.request_for(p, 'status', 'a' * 32, 'b' * 64)
        response = {'protocol': 1, 'ok': True, 'status': 'running', 'identity': {
            'hostname': p['expected_hostname'], 'user': p['expected_user']},
            'job_id': req['job_id'], 'manifest_sha256': req['manifest_sha256']}
        self.assertEqual(win.validate_response(response, p, req), response)
        for change in ({'job_id': 'b' * 32}, {'manifest_sha256': 'a' * 64},
                       {'identity': {**response['identity'], 'user': 'other'}}):
            with self.subTest(change=change), self.assertRaises(win.core.TransportError):
                win.validate_response({**response, **change}, p, req)

    def test_collection_checks_raw_hash_bounds_and_partial_declaration(self):
        m = manifest(['python', '-c', 'pass'])
        raw = b'\x00ok'
        item = {'path': 'result.txt', 'sha256': win.core.digest(raw),
                'data': base64.b64encode(raw).decode('ascii')}
        result = {'ok': True, 'status': 'succeeded', 'files': [item],
                  'missing': [], 'partial': False, 'logs': {}}
        win.validate_collection(result, m)
        for changed in ({'files': [{**item, 'sha256': '0' * 64}]},
                        {'files': [{**item, 'data': base64.b64encode(b'x' * 4097).decode()}]},
                        {'missing': ['result.txt']}, {'partial': True},
                        {'logs': {'stdout.log': {'data': '!!!', 'sha256': '0' * 64}}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                win.validate_collection({**result, **changed}, m)

    def test_failed_or_unacknowledged_launch_preserves_single_intent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = profile()
            m = manifest(['python', '-c', 'pass'])
            identity = m['job_id']
            path = root / (identity + '.json')
            initial = {
                'schema_version': 1, 'job_id': identity,
                'manifest_sha256': win.core.digest(win.core.canonical(m)),
                'manifest': m, 'profile_sha256': win.core.digest(win.core.canonical(p)),
                'worker_sha256': win.worker_source()[1], 'status': 'prepared', 'submit_attempted': False,
            }
            transport.save_state(path, initial, exclusive=True)
            def lose_ack(*args, **kwargs):
                self.assertTrue(win.core.read_json(path)['submit_attempted'])
                raise win.core.TransportError('lost acknowledgement')
            with patch.object(win, 'rpc', side_effect=lose_ack) as rpc:
                with self.assertRaises(win.core.TransportError):
                    win.operate(p, 'submit', identity, root, allow_execute=True)
                with self.assertRaisesRegex(ValueError, 'never resubmit'):
                    win.operate(p, 'submit', identity, root, allow_execute=True)
                self.assertEqual(rpc.call_count, 1)
            self.assertEqual(win.core.read_json(path)['status'], 'uncertain')

        # Exercise the actual worker transition using a denied CreateProcess call.
        flags = {'CREATE_NEW_PROCESS_GROUP': 0x200, 'CREATE_BREAKAWAY_FROM_JOB': 0x1000000,
                 'DETACHED_PROCESS': 0x8}
        p = profile()
        request = win.request_for(p, 'submit', 'a' * 32, 'b' * 64)
        for ssh_controller in (False, True):
            with self.subTest(ssh_controller=ssh_controller), tempfile.TemporaryDirectory() as folder:
                job = Path(folder) / request['job_id']
                job.mkdir()
                win.worker.atomic(job / 'state.json', {'status': 'prepared'})
                ident = {'hostname': p['expected_hostname'], 'user': p['expected_user']}
                with patch.multiple(win.worker, identity=lambda: ident, root_path=lambda _: job.parent,
                                    checked_job=lambda *_: job, mutation_lock=lambda _: nullcontext()), \
                        patch.multiple(win.worker.subprocess, create=True, **flags), \
                        patch.object(win.worker.subprocess, 'Popen', side_effect=PermissionError('fixture launch denied')) as launch:
                    denied = win.worker.handle(request, ssh_controller=ssh_controller)
                    self.assertFalse(denied['ok'], denied)
                    self.assertEqual(denied['status'], 'uncertain' if ssh_controller else 'failed')
                    self.assertEqual(win.worker.read_json(job / 'state.json')['status'], 'uncertain')
                    self.assertTrue((job / 'submission.json').is_file())
                    repeated = win.worker.handle(request, ssh_controller=ssh_controller)
                    self.assertTrue(repeated['already_submitted'], repeated)
                    expected_flags = flags['CREATE_NEW_PROCESS_GROUP']
                    if ssh_controller:
                        expected_flags |= flags['CREATE_BREAKAWAY_FROM_JOB'] | flags['DETACHED_PROCESS']
                    self.assertEqual(launch.call_count, 1)
                    self.assertEqual(launch.call_args.kwargs['creationflags'], expected_flags)
                    self.assertTrue(launch.call_args.kwargs['close_fds'])
                    self.assertEqual(launch.call_args.kwargs['stdin'], subprocess.DEVNULL)


class NativeWindowsSSH(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(os.environ['RW_WINSSH_FIXTURE']).resolve(strict=True)
        self.profile_path = self.fixture / 'profile.json'
        self.p = win.profile(win.core.read_json(self.profile_path))
        self.jobs = Path(self.p['remote_root'])
        self.assertEqual(self.jobs.parent, self.fixture)
        self.scratch = self.fixture / ('client-' + uuid.uuid4().hex)
        self.scratch.mkdir()
        self.state_dir = self.scratch / 'state'
        self.owned_ids = []
        self.addCleanup(self.reconcile_owned)

    def diagnose_controller(self, identity):
        if identity not in self.owned_ids:
            return
        job = self.jobs / identity
        observed = {'job_id': identity}
        for name in ('state.json', 'controller-receipt.json', 'controller.log'):
            try:
                with (job / name).open('rb') as stream:
                    data = stream.read(4097)
                observed[name] = {'prefix': data[:4096].decode('utf-8', 'replace'), 'truncated': len(data) > 4096}
            except OSError as exc:
                observed[name] = str(exc)[:400]
        script = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$target=ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
$rows=Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine.IndexOf($target.controller, [StringComparison]::OrdinalIgnoreCase) -ge 0 `
    -and $_.CommandLine.Contains('--run-job')
} | Select-Object -First 4 ProcessId, ParentProcessId, ExecutablePath
$data=[Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -Compress -InputObject @($rows)))
[Console]::OpenStandardOutput().Write($data, 0, $data.Length)
'''
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        try:
            process = transport.run_bounded(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                json.dumps({'controller': str(job / 'controller.py')}).encode('ascii'),
                timeout=8, max_input=4096, max_stdout=8192, max_stderr=4096,
            )
            observed['matching_processes'] = json.loads(process.stdout) if process.returncode == 0 else {
                'exit': process.returncode, 'stderr': process.stderr.decode('utf-8', 'replace')[:1000],
            }
        except (transport.CaptureError, ValueError) as exc:
            observed['matching_processes'] = {'error': str(exc)[:400]}
        print('WINDOWS_SSH_CONTROLLER_DIAGNOSTIC ' + json.dumps(observed, sort_keys=True), flush=True)

    def reconcile_owned(self):
        for identity in self.owned_ids:
            path = self.state_dir / (identity + '.json')
            if path.exists() and win.core.read_json(path)['status'] in ('prepared', 'launching', 'running'):
                win.operate(self.p, 'cancel', identity, self.state_dir, allow_cancel=True)

    def command(self, op, *, expected=0, use_profile=None, extra=()):
        output = self.scratch / (uuid.uuid4().hex + '.json')
        argv = [sys.executable, str(SCRIPTS / 'windows_remote_tools.py'), op,
                '--profile', str(use_profile or self.profile_path), '--output', str(output), *extra]
        if op != 'inspect':
            argv.extend(['--state-dir', str(self.state_dir)])
        proc = subprocess.run(argv, timeout=45, capture_output=True)
        self.assertTrue(output.exists(), (proc.returncode, proc.stdout, proc.stderr))
        receipt = win.core.read_json(output, win.core.MAX_RPC)
        print('WINDOWS_SSH_RECEIPT ' + json.dumps({
            'operation': op, 'exit': proc.returncode, 'receipt_sha256': win.core.digest(output.read_bytes()),
            'receipt': receipt,
        }, sort_keys=True), flush=True)
        self.assertEqual(proc.returncode, expected, receipt)
        return receipt

    def prepare(self, m):
        source = self.scratch / (m['job_id'] + '.manifest.json')
        source.write_bytes(win.core.canonical(m))
        self.owned_ids.append(m['job_id'])
        result = self.command('prepare', extra=('--manifest', str(source), '--allow-transfer'))
        self.assertEqual(result['status'], 'prepared', result)
        self.assertEqual(result['manifest_sha256'], win.core.digest(source.read_bytes()))
        return m['job_id']

    def call(self, operation, identity, *flags, expected=0):
        try:
            return self.command(operation, expected=expected, extra=('--job-id', identity, *flags))
        except (AssertionError, subprocess.SubprocessError):
            self.diagnose_controller(identity)
            raise

    def wait_for(self, identity, statuses, *, operation='status', seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = self.call(operation, identity)
            if result['status'] in statuses:
                return result
            if result['status'] in win.core.TERMINAL:
                self.diagnose_controller(identity)
                self.fail(f'Unexpected terminal state: {result}')
            time.sleep(0.1)
        self.diagnose_controller(identity)
        self.fail(f'Expected {statuses} from {operation}; last response: {result}')

    def test_inspect_and_refuse_unknown_or_changed_host_key_and_wrong_identity(self):
        inspected = self.command('inspect')
        identity = inspected['identity']
        self.assertEqual(inspected['supported_remote_os'], 'windows')
        self.assertEqual(identity['user'], self.p['expected_user'])
        self.assertEqual(identity['hostname'], self.p['expected_hostname'])
        self.assertEqual(Path(identity['python']), Path(self.p['remote_python']))
        config = Path(self.p['ssh_config']).read_text(encoding='utf-8')
        known = self.fixture / 'known_hosts'
        before = known.read_bytes()
        for name in ('empty_known_hosts', 'wrong_known_hosts'):
            alternate = self.fixture / name
            snapshot = alternate.read_bytes()
            bad_config = self.scratch / name
            bad_config.write_text(config.replace(known.as_posix(), alternate.as_posix()), encoding='utf-8')
            bad_profile = bad_config.with_suffix('.json')
            transport.save_state(bad_profile, {**self.p, 'ssh_config': str(bad_config)})
            refused = self.command('inspect', use_profile=bad_profile, expected=2)
            self.assertIn('Host key verification failed', refused['error'])
            self.assertEqual(alternate.read_bytes(), snapshot)
        self.assertEqual(known.read_bytes(), before)
        bad_profile = self.scratch / 'bad_identity.json'
        transport.save_state(bad_profile, {**self.p, 'expected_user': 'wrong-user'})
        self.assertIn('identity mismatch', self.command('inspect', use_profile=bad_profile, expected=2)['error'])

    def test_bootstrap_exact_single_json_and_large_binary_stream(self):
        source = '''
import base64, hashlib, json, sys
request = json.load(sys.stdin)
raw = base64.b64decode(request['data'], validate=True)
response = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
sys.stdout.buffer.write(json.dumps(response, sort_keys=True, separators=(',', ':')).encode() + b'\\n')
sys.stderr.buffer.write(b'\\x00\\x80\\xff\\r\\n')
'''
        argv = win.ssh_argv(self.p)

        def capture(raw, command):
            request = {'data': base64.b64encode(raw).decode('ascii')}
            payload = win.encode_request(self.p, request, source)
            response = win.core.canonical({'bytes': len(raw), 'sha256': win.core.digest(raw)}) + b'\n'
            process = transport.run_bounded(command, payload, timeout=self.p['connect_timeout_seconds'] + 30,
                                            max_input=win.core.MAX_RPC, max_stdout=4096, max_stderr=4096)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, b'\x00\x80\xff\r\n')
            return process.stdout, response

        # Change only the PowerShell result suppression in this small, read-only probe.
        uncast = win.PS_BOOTSTRAP.replace('[void]$stdoutTask', '$stdoutTask').replace(
            '[void]$stderrTask', '$stderrTask')
        uncast_arg = base64.b64encode(uncast.encode('utf-16le')).decode('ascii')
        old_stdout, expected = capture(b'control', [*argv[:-1], argv[-1].replace(win.ENCODED, uncast_arg)])
        self.assertTrue(old_stdout.startswith(expected), old_stdout)
        print('WINDOWS_SSH_BOOTSTRAP_PROBE ' + json.dumps({
            'uncast_trailing_stdout_base64': base64.b64encode(old_stdout[len(expected):]).decode('ascii'),
        }), flush=True)
        for raw in (b'control', bytes(range(256)) * 10000):
            with self.subTest(bytes=len(raw)):
                stdout, expected = capture(raw, argv)
                self.assertEqual(stdout, expected)
                print('WINDOWS_SSH_BOOTSTRAP_PROBE ' + json.dumps({
                    'payload_bytes': len(raw), 'stdout_sha256': win.core.digest(stdout),
                    'stdout': stdout.decode('ascii'),
                }), flush=True)

    def test_native_roundtrip_with_binary_unicode_and_fresh_client(self):
        path = 'space 研究/入力.bin'
        name = 'output 研究/結果.bin'
        value = '漢字 with spaces, "quotes" and a trailing slash \\'
        source = self.scratch / path
        source.parent.mkdir()
        raw = bytes(range(256)) * 10000
        source.write_bytes(raw)
        code = ('import hashlib,pathlib,sys; inp,out,arg=sys.argv[1:]; p=pathlib.Path(out); '
                'p.parent.mkdir(); p.write_bytes(hashlib.sha256(pathlib.Path(inp).read_bytes()).digest()+arg.encode()); '
                'sys.stdout.buffer.write(bytes([0,255,10])); sys.stderr.buffer.write(bytes([128,13,10]))')
        m = manifest([self.p['remote_python'], '-c', code, path, name, value])
        m['inputs'] = [{'source': path, 'destination': path, 'sha256': win.core.digest(raw)}]
        m['outputs'] = [name]
        identity = self.prepare(m)
        self.call('submit', identity, '--allow-execute')
        terminal = self.wait_for(identity, {'succeeded'})
        recovered = self.call('recover', identity)
        self.assertEqual(recovered['state'], terminal['state'])
        self.assertEqual(recovered['reconciliation']['mode'], 'read_only')
        self.assertFalse(recovered['reconciliation']['restarted'])
        with self.subTest('one dispatch'):
            refused = self.call('submit', identity, '--allow-execute', expected=2)
            self.assertIn('never resubmit', refused['error'])
        destination = self.scratch / 'new collection 研究'
        collected = self.call('collect', identity, '--destination', str(destination))
        expected = bytes.fromhex(win.core.digest(raw)) + value.encode()
        self.assertEqual((destination / name).read_bytes(), expected)
        self.assertEqual(collected['collection']['files'][0]['sha256'], win.core.digest(expected))
        self.assertEqual(win.core.read_json(destination / '.collection.json')['files'][0]['bytes'], len(expected))
        for name, content in (('stdout.log', b'\x00\xff\n'), ('stderr.log', b'\x80\r\n')):
            self.assertEqual(base64.b64decode(collected['logs'][name]['data']), content)
            self.assertEqual(collected['logs'][name]['sha256'], win.core.digest(content))

    def drop_acknowledgement(self, op, identity, source=None):
        crash = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import windows_remote_tools as win
native = win.rpc
op = sys.argv[3]

def drop(*args, **kwargs):
    receipt = native(*args, **kwargs)
    assert receipt['ok'] and receipt['status'] == {'prepare':'prepared','submit':'launching'}[op], receipt
    print('WINDOWS_SSH_DISCARDED_ACK ' + json.dumps(receipt, sort_keys=True), flush=True)
    os._exit(73)

win.rpc = drop
profile = win.profile(win.core.read_json(sys.argv[2]))
if op == 'prepare':
    win.prepare(profile, sys.argv[6], sys.argv[5], allow_transfer=True)
else:
    win.operate(profile, 'submit', sys.argv[4], sys.argv[5], allow_execute=True)
'''
        proc = subprocess.run([sys.executable, '-c', crash, str(SCRIPTS), str(self.profile_path),
                               op, identity, str(self.state_dir), str(source or '')],
                              timeout=45, capture_output=True)
        print(proc.stdout.decode('utf-8', 'replace').strip(), flush=True)
        self.assertEqual(proc.returncode, 73, (proc.stdout, proc.stderr))
        return win.core.read_json(self.state_dir / (identity + '.json'))

    def test_abrupt_client_loss_after_real_prepare_before_recording_ack(self):
        m = manifest([self.p['remote_python'], '-c', 'pass'])
        identity = m['job_id']
        source = self.scratch / 'prepare-ack.manifest.json'
        source.write_bytes(win.core.canonical(m))
        self.owned_ids.append(identity)
        state = self.drop_acknowledgement('prepare', identity, source)
        self.assertEqual(state['status'], 'prepare_attempted')
        self.assertFalse(state['submit_attempted'])
        recovered = self.call('recover', identity)
        self.assertEqual(recovered['status'], 'prepared')
        self.assertFalse(recovered['reconciliation']['execution_attempted'])
        refused = self.command('prepare', expected=2, extra=('--manifest', str(source), '--allow-transfer'))
        self.assertIn('reconcile without preparing again', refused['error'])
        cancelled = self.call('cancel', identity, '--allow-cancel')
        self.assertEqual(cancelled['status'], 'cancelled')

    def test_abrupt_client_loss_after_real_submit_before_recording_ack(self):
        code = "from pathlib import Path; Path('result.txt').open('xb').write(b'once')"
        identity = self.prepare(manifest([self.p['remote_python'], '-c', code]))
        state = self.drop_acknowledgement('submit', identity)
        self.assertTrue(state['submit_attempted'])
        self.assertEqual(state['status'], 'launching')
        submission = self.jobs / identity / 'submission.json'
        receipt = submission.read_bytes()
        refused = self.call('submit', identity, '--allow-execute', expected=2)
        self.assertIn('never resubmit', refused['error'])
        recovered = self.wait_for(identity, {'succeeded'}, operation='recover')
        self.assertTrue(recovered['reconciliation']['execution_attempted'])
        self.assertFalse(recovered['reconciliation']['restarted'])
        self.assertEqual(submission.read_bytes(), receipt)
        self.assertEqual((self.jobs / identity / 'work/result.txt').read_bytes(), b'once')

    def test_timeout_and_cancel_close_owned_tree(self):
        escaped = "import time; from pathlib import Path; time.sleep(7); Path('escaped.txt').write_bytes(b'bad')"
        code = ('import subprocess,sys,time; from pathlib import Path; '
                f'subprocess.Popen([sys.executable,"-c",{escaped!r}]); '
                "Path('started.txt').write_bytes(b'yes'); time.sleep(40)")
        for status, wall in (('timed_out', 3), ('cancelled', 30)):
            with self.subTest(status=status):
                identity = self.prepare(manifest([self.p['remote_python'], '-c', code], wall=wall))
                work = self.jobs / identity / 'work'
                self.call('submit', identity, '--allow-execute')
                until = time.monotonic() + 8
                while not (work / 'started.txt').is_file() and time.monotonic() < until:
                    time.sleep(0.05)
                self.assertTrue((work / 'started.txt').is_file())
                started = time.monotonic()
                if status == 'cancelled':
                    self.assertTrue(self.call('cancel', identity, '--allow-cancel')['cancel_requested'])
                self.wait_for(identity, {status})
                destination = self.scratch / ('partial-' + status)
                collected = self.call('collect', identity, '--destination', str(destination))
                self.assertTrue(collected['collection']['partial'])
                self.assertEqual(collected['missing'], ['result.txt'])
                time.sleep(max(0, started + 8 - time.monotonic()))
                self.assertFalse((work / 'escaped.txt').exists())

    def test_failed_workload_and_bounds_return_checked_partial_or_refuse(self):
        cases = {
            'exit': 'raise SystemExit(7)',
            'log': 'import sys; sys.stderr.buffer.write(b"x"*8192); sys.stderr.flush()',
            'output': 'from pathlib import Path; Path("result.txt").write_bytes(b"x"*8192)',
        }
        for kind, code in cases.items():
            with self.subTest(kind=kind):
                identity = self.prepare(manifest([self.p['remote_python'], '-c', code]))
                self.call('submit', identity, '--allow-execute')
                terminal = self.wait_for(identity, {'failed'})
                destination = self.scratch / ('failed-' + kind)
                if kind == 'output':
                    self.call('collect', identity, '--destination', str(destination), expected=2)
                    self.assertFalse(destination.exists())
                    continue
                collection = self.call('collect', identity, '--destination', str(destination))
                self.assertTrue(collection['collection']['partial'])
                self.assertEqual(collection['missing'], ['result.txt'])
                if kind == 'exit':
                    self.assertEqual(terminal['state']['returncode'], 7)
                else:
                    log = collection['logs']['stderr.log']
                    raw = base64.b64decode(log['data'], validate=True)
                    self.assertEqual(len(raw), 4096)
                    self.assertEqual(win.core.digest(raw), log['sha256'])

    def test_controller_loss_is_read_only_uncertainty_and_kills_descendants(self):
        descendant = "import time; from pathlib import Path; time.sleep(20); Path('result.txt').write_bytes(b'escaped')"
        code = ('import subprocess,sys,time; from pathlib import Path; '
                f'subprocess.Popen([sys.executable,"-c",{descendant!r}]); '
                "Path('started.txt').write_bytes(b'ok'); time.sleep(30)")
        identity = self.prepare(manifest([self.p['remote_python'], '-c', code], wall=30))
        self.call('submit', identity, '--allow-execute')
        self.wait_for(identity, {'running'})
        job = self.jobs / identity
        deadline = time.monotonic() + 6
        while not (job / 'work/started.txt').is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((job / 'work/started.txt').is_file())
        started = time.monotonic()
        controller = win.core.read_json(job / 'controller-receipt.json')
        try:
            terminate_fixture_controller(controller['pid'], self.p['remote_python'], job)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            self.diagnose_controller(identity)
            raise
        receipt = self.wait_for(identity, {'uncertain'}, operation='recover', seconds=16)
        self.assertFalse(receipt['reconciliation']['restarted'])
        self.assertFalse(receipt['reconciliation']['pid_signal_sent'])
        self.assertTrue(receipt['reconciliation']['execution_attempted'])
        self.call('submit', identity, '--allow-execute', expected=2)
        time.sleep(max(0, started + 20.5 - time.monotonic()))
        self.assertFalse((job / 'work/result.txt').exists())


def terminate_fixture_controller(pid, python, job):
    """CI fault injection: verify exact live fixture command before signalling its handle."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        script = (
            "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$env:RW_FIXTURE_PID);"
            "if ($p.CommandLine -cne $env:RW_FIXTURE_COMMAND) { exit 71 }; exit 0"
        )
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                       env={**os.environ, 'RW_FIXTURE_PID': str(pid),
                            'RW_FIXTURE_COMMAND': subprocess.list2cmdline(
                                [python, str(job / 'controller.py'), '--run-job', str(job)])},
                       timeout=8, check=True)
        if kernel.WaitForSingleObject(handle, 0) != 258:
            raise RuntimeError('Verified fixture controller is no longer running')
        if not kernel.TerminateProcess(handle, 19):
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.WaitForSingleObject(handle, 5000) != 0:
            raise RuntimeError('Fixture controller did not exit')
    finally:
        kernel.CloseHandle(handle)


METADATA_PROBE = r'''
import ctypes as c
from ctypes import wintypes as wt
import json, msvcrt, os, stat, sys, tempfile, time
from contextlib import nullcontext
from pathlib import Path

request = json.load(sys.stdin)
worker = {'__name__': 'metadata_probe_worker'}
exec(compile(request['worker_source'], '<metadata-probe-worker>', 'exec'), worker)
kernel = c.WinDLL('kernel32', use_last_error=True)
adv = c.WinDLL('advapi32', use_last_error=True)
ptr = c.c_void_p
kernel.GetCurrentProcess.restype = wt.HANDLE
kernel.CloseHandle.argtypes = [wt.HANDLE]
kernel.LocalFree.argtypes = [ptr]
kernel.LocalFree.restype = ptr
kernel.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ptr, wt.DWORD, wt.DWORD, wt.HANDLE]
kernel.CreateFileW.restype = wt.HANDLE
adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, c.POINTER(wt.HANDLE)]
adv.GetTokenInformation.argtypes = [wt.HANDLE, c.c_int, ptr, wt.DWORD, c.POINTER(wt.DWORD)]
adv.ConvertSidToStringSidW.argtypes = [ptr, c.POINTER(wt.LPWSTR)]
adv.GetNamedSecurityInfoW.argtypes = [wt.LPWSTR, wt.DWORD, wt.DWORD, c.POINTER(ptr), ptr, ptr, ptr, c.POINTER(ptr)]
adv.GetNamedSecurityInfoW.restype = wt.DWORD

def sid_string(sid):
    value = wt.LPWSTR()
    if not adv.ConvertSidToStringSidW(sid, c.byref(value)):
        raise c.WinError(c.get_last_error())
    try:
        return value.value
    finally:
        kernel.LocalFree(c.cast(value, ptr))

def token_sid(token, info_class):
    size = wt.DWORD()
    adv.GetTokenInformation(token, info_class, None, 0, c.byref(size))
    if not size.value:
        raise c.WinError(c.get_last_error())
    value = c.create_string_buffer(size.value)
    if not adv.GetTokenInformation(token, info_class, value, size, c.byref(size)):
        raise c.WinError(c.get_last_error())
    return sid_string(c.cast(value, c.POINTER(ptr))[0])

def metadata(path):
    owner, descriptor = ptr(), ptr()
    code = adv.GetNamedSecurityInfoW(str(path), 1, 1, c.byref(owner), None, None, None, c.byref(descriptor))
    if code:
        raise c.WinError(code)
    try:
        info = path.lstat()
        return {'owner_sid': sid_string(owner), 'nlink': info.st_nlink,
                'reparse': bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                'regular': stat.S_ISREG(info.st_mode), 'directory': stat.S_ISDIR(info.st_mode)}
    finally:
        kernel.LocalFree(descriptor)

def open_reader(path, share):
    handle = kernel.CreateFileW(str(path), 0x80000000, share, None, 3, 0x00200000, None)
    if handle == wt.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise

token = wt.HANDLE()
if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)):
    raise c.WinError(c.get_last_error())
try:
    probe = {'token_user_sid': token_sid(token, 1), 'token_owner_sid': token_sid(token, 4), 'cases': []}
finally:
    kernel.CloseHandle(token)

root = worker['root_path'](request['fixture'])
if root != Path(request['remote_root']).parent or not root.name.startswith('rw-winssh-'):
    raise ValueError('Expected the disposable SSH fixture root')
old, new = b'{"value":"old"}\n', b'{"value":"new"}\n'
with tempfile.TemporaryDirectory(prefix='metadata-probe-', dir=root) as folder:
    for share in (None, 3, 7):
        source, target = Path(folder) / f'source-{share}.json', Path(folder) / f'target-{share}.json'
        source.write_bytes(new)
        target.write_bytes(old)
        case = {'share_mode': share, 'source': metadata(source), 'target': metadata(target),
                'parent': metadata(target.parent)}
        reader = nullcontext() if share is None else open_reader(target, share)
        with reader as held:
            try:
                case['retryable_metadata'] = worker['retryable_metadata'](source, target)
            except OSError as exc:
                case.update(retryable_metadata=None, retryable_metadata_winerror=exc.winerror)
            started = time.monotonic_ns()
            try:
                os.replace(source, target)
            except OSError as exc:
                case.update(replaced=False, winerror=exc.winerror)
            else:
                case.update(replaced=True, winerror=None)
            finally:
                case['elapsed_ns'] = time.monotonic_ns() - started
            case['held_bytes'] = None if held is None else held.read(128).hex()
            case['target_bytes'] = target.read_bytes().hex()
            case['source_bytes'] = source.read_bytes().hex() if source.exists() else None
        probe['cases'].append(case)
ident = worker['identity']()
result = {'protocol': 1, 'ok': True, 'status': 'inspected', 'supported_remote_os': 'windows',
          'identity': ident, 'worker_sha256': worker['digest'](request['worker_source'].encode('utf-8')),
          'metadata_probe': probe}
sys.stdout.buffer.write(worker['canonical'](result) + b'\n')
'''


def native_metadata_probe():
    fixture = Path(os.environ['RW_WINSSH_FIXTURE']).resolve(strict=True)
    p = win.profile(win.core.read_json(fixture / 'profile.json'))
    win.core.pinned(p)
    if Path(p['remote_root']).parent != fixture:
        raise ValueError('Metadata probe requires the isolated Windows SSH fixture')
    worker_source, worker_hash = win.worker_source()
    request = {**win.request_for(p, 'inspect'), 'fixture': str(fixture), 'worker_source': worker_source}
    child = transport.run_bounded(win.ssh_argv(p), win.encode_request(p, request, METADATA_PROBE),
                                  timeout=20, max_input=win.core.MAX_RPC, max_stdout=8192, max_stderr=4096)
    if child.returncode:
        raise RuntimeError(f'Metadata probe SSH exited {child.returncode}: {child.stderr[-2000:]!r}')
    result = win.validate_response(win.core.decode_json(child.stdout.decode('utf-8')), p, request)
    probe = result['metadata_probe']
    print('WINDOWS_METADATA_PROBE ' + json.dumps({'worker_sha256': result['worker_sha256'], **probe},
                                                sort_keys=True), flush=True)
    if not result['ok'] or result['worker_sha256'] != worker_hash or [c['share_mode'] for c in probe['cases']] != [None, 3, 7]:
        raise ValueError('Metadata probe source or sharing controls differ')
    old, new = b'{"value":"old"}\n'.hex(), b'{"value":"new"}\n'.hex()
    for case in probe['cases']:
        expected_held = None if case['share_mode'] is None else old
        if case['held_bytes'] != expected_held or not case['source']['regular'] or not case['target']['regular'] or not case['parent']['directory']:
            raise ValueError('Metadata probe file type or held-reader bytes differ')
        if type(case['elapsed_ns']) is not int or case['elapsed_ns'] < 0:
            raise ValueError('Metadata probe lacks a monotonic replacement duration')
        if case['replaced']:
            if case['target_bytes'] != new or case['source_bytes'] is not None:
                raise ValueError('Successful replacement did not publish exact new bytes')
        elif case['target_bytes'] != old or case['source_bytes'] != new:
            raise ValueError('Denied replacement changed source or target bytes')
    if not probe['cases'][0]['replaced']:
        raise ValueError('Uncontended replacement baseline failed')


def main():
    native = sys.argv[1:] == ['--run-ssh']
    if sys.argv[1:] and not native:
        raise SystemExit('Usage: windows_remote_checks.py [--run-ssh]')
    if native and (os.name != 'nt' or not os.environ.get('RW_WINSSH_FIXTURE')):
        raise SystemExit('Native Windows and an explicit CI loopback fixture are required')
    probe_ok = True
    if native:
        try:
            native_metadata_probe()
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            print('WINDOWS_METADATA_PROBE ' + json.dumps({'error': str(exc)[:2000]}), flush=True)
            probe_ok = False
    classes = [TransportContracts, WindowsClientContracts]
    if native:
        classes.append(NativeWindowsSSH)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = probe_ok and result.wasSuccessful() and not result.skipped and result.testsRun == (17 if native else 9)
    print('WINDOWS_SSH_CHECKS ' + json.dumps({
        'mode': 'native_loopback_ssh' if native else 'portable_source_contracts',
        'passed': passed, 'methods': result.testsRun, 'skipped': len(result.skipped),
    }), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
