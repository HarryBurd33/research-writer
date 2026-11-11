#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable transport contracts and an explicit native Windows SSH gate."""
import base64
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

    def test_lost_ack_persists_single_dispatch_intent(self):
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
        return self.command(operation, expected=expected, extra=('--job-id', identity, *flags))

    def wait_for(self, identity, statuses, *, operation='status', seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = self.call(operation, identity)
            if result['status'] in statuses:
                return result
            if result['status'] in win.core.TERMINAL:
                self.fail(f'Unexpected terminal state: {result}')
            time.sleep(0.1)
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
        terminate_fixture_controller(controller['pid'], self.p['remote_python'], job)
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


def main():
    native = sys.argv[1:] == ['--run-ssh']
    if sys.argv[1:] and not native:
        raise SystemExit('Usage: windows_remote_checks.py [--run-ssh]')
    if native and (os.name != 'nt' or not os.environ.get('RW_WINSSH_FIXTURE')):
        raise SystemExit('Native Windows and an explicit CI loopback fixture are required')
    classes = [TransportContracts, WindowsClientContracts]
    if native:
        classes.append(NativeWindowsSSH)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == (16 if native else 9)
    print('WINDOWS_SSH_CHECKS ' + json.dumps({
        'mode': 'native_loopback_ssh' if native else 'portable_source_contracts',
        'passed': passed, 'methods': result.testsRun, 'skipped': len(result.skipped),
    }), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
