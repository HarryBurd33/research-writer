#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Strict fake transports/clocks and pure supervisor path; no native jobs/signals."""
from __future__ import annotations
import ast
import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import linux_startup_diagnostic as batch
import linux_checks as baseline

ID = 'c' * 64
START = '2026-11-11T10:00:00.123456789Z'
FINISH = '2026-11-11T10:00:01.123456789Z'
ZERO = '0001-01-01T00:00:00Z'


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakeBatch(batch.Batch):
    def setup(self):
        self.root.mkdir(mode=0o700)
        self.p = baseline.profile()
        batch.integration.CONFIG = self.config
        if self.modes.get(0) == 'setup_budget':
            self.clock.now = 40


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rw-startup-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(batch.mod, 'bounded_run', side_effect=AssertionError('Native Docker forbidden')).start()
        patch.object(subprocess, 'Popen', side_effect=AssertionError('Native subprocess forbidden')).start()
        patch.object(os, 'kill', side_effect=AssertionError('Native signals forbidden')).start()
        patch.object(os, 'killpg', side_effect=AssertionError('Native group signals forbidden')).start()

    def state(self):
        m = baseline.manifest(); m['resources'] = dict(batch.RESOURCES)
        m['argv'][-1] = batch.CODE; m['outputs'] = ['result.json']
        folder = self.root / ('fixture-' + str(len(list(self.root.iterdir())))); folder.mkdir()
        path = folder / 'manifest.json'; batch.mod.save(path, m, True)
        with patch.object(batch.mod, 'inspect_engine', return_value={'id': 'engine-control', 'architecture': 'amd64'}), \
                patch.object(batch.mod, 'inspect_image', return_value={'architecture': 'amd64'}):
            batch.mod.prepare(baseline.profile(), path, folder / 'state', True)
        return batch.mod.read_json(folder / 'state/state.json')

    def cid(self):
        value = batch.CIDFile(self.root / ('cid-' + str(len(list(self.root.iterdir())))))
        self.addCleanup(value.close)
        return value

    def test_only_exact_command_is_transformed_and_every_other_token_delta_refused(self):
        state = self.state(); p = state['profile']
        original = [p['docker_executable'], '--context', p['context'], *batch.mod.run_arguments(state)]
        result = batch.foreground_arguments(p, state, original, '/private/cid')
        expected = original.copy(); expected.remove('--detach')
        self.assertEqual(result, expected[:-3] + ['--attach=stdout', '--attach=stderr', '--sig-proxy=false', '--cidfile', '/private/cid'] + expected[-3:])
        self.assertIn('--log-driver=none', result); self.assertNotIn('--rm', result)
        for index in range(len(original)):
            changed = original.copy(); changed[index] += '-changed'
            with self.subTest(index=index), self.assertRaises(ValueError):
                batch.foreground_arguments(p, state, changed, '/private/cid')
        for changed in (original + ['--privileged'], original[1:], original + ['--detach']):
            with self.assertRaises(ValueError): batch.foreground_arguments(p, state, changed, '/private/cid')

    def test_fixture_matches_original_first_symlink_case_and_resources(self):
        tree = ast.parse(Path(batch.integration.__file__).read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'test_08_actual_unsafe_and_oversized_outputs')
        loop = method.body[0]
        self.assertEqual(ast.literal_eval(loop.iter.elts[0]), batch.CODE)
        expected = ast.parse("{'memory_bytes': 128 * 1024**2}", mode='eval').body
        self.assertEqual(ast.dump(loop.body[0].value.args[1]), ast.dump(expected))
        self.assertEqual(self.state()['manifest']['resources'], batch.RESOURCES)

    def test_cid_missing_partial_and_complete_bytes(self):
        cid = self.cid(); self.assertIsNone(cid.read())
        cid.path.write_bytes(b''); self.assertIsNone(cid.read())
        cid.path.write_bytes(b'a' * 32); self.assertIsNone(cid.read())
        cid.path.write_bytes(b'a' * 64); self.assertEqual(cid.read(), 'a' * 64)
        cid.path.write_bytes(b'a' * 64 + b'\n'); self.assertEqual(cid.read(), 'a' * 64)
        cid.path.write_bytes(b'a' * 32)
        with self.assertRaises(ValueError): cid.read()

    def test_cid_malformed_oversized_symlink_hardlink_replacement_and_disappearance(self):
        for raw in (b'A' * 64, b'a' * 63 + b'!', b'a' * 66, b'a' * 63 + b'\n', b'x\x00'):
            cid = self.cid(); cid.path.write_bytes(raw)
            with self.subTest(raw=raw[:5]), self.assertRaises(ValueError): cid.read()
        cid = self.cid(); target = self.root / 'target'; target.write_bytes(ID.encode())
        cid.path.symlink_to(target)
        with self.assertRaises(ValueError): cid.read()
        cid = self.cid(); os.link(target, cid.path)
        with self.assertRaises(ValueError): cid.read()
        cid = self.cid(); cid.path.write_bytes(ID.encode()); cid.read()
        replacement = cid.directory / 'replacement'; replacement.write_bytes(ID.encode()); replacement.replace(cid.path)
        with self.assertRaisesRegex(ValueError, 'replacement'): cid.read()
        cid = self.cid(); cid.path.write_bytes(ID.encode()); cid.read(); cid.path.unlink()
        with self.assertRaisesRegex(ValueError, 'disappeared'): cid.read()

    def test_cid_directory_replacement_symlink_and_mode_refused(self):
        cid = self.cid(); cid.directory.rename(cid.directory.with_name('moved'))
        cid.directory.mkdir(mode=0o700)
        with self.assertRaises(ValueError): cid.read()
        cid = self.cid(); cid.directory.chmod(0o755)
        with self.assertRaises(ValueError): cid.read()
        parent = self.root / 'alias'; parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): batch.CIDFile(parent / 'new')

    def test_cid_change_during_read_and_no_follow_nonblocking_flags(self):
        cid = self.cid(); cid.path.write_bytes(ID.encode())
        original_read = os.read
        def changed(fd, size):
            raw = original_read(fd, size); cid.path.write_bytes(b'd' * 64); return raw
        with patch.object(os, 'read', side_effect=changed), self.assertRaisesRegex(ValueError, 'during'):
            cid.read()
        cid = self.cid(); cid.path.write_bytes(ID.encode())
        with patch.object(os, 'open', wraps=os.open) as opened:
            self.assertEqual(cid.read(), ID)
        self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)
        self.assertTrue(opened.call_args.args[1] & os.O_NONBLOCK)
        self.assertEqual(opened.call_args.kwargs['dir_fd'], cid.fd)

    def test_cid_constructor_failure_closes_directory_handle_and_fifo_refused(self):
        with patch.object(batch.CIDFile, 'validate_directory', side_effect=ValueError('directory validation failed')), \
                patch.object(os, 'close', wraps=os.close) as closed:
            with self.assertRaises(ValueError): batch.CIDFile(self.root / 'failed-cid')
        closed.assert_called_once()
        cid = self.cid(); os.mkfifo(cid.path)
        with self.assertRaises(ValueError): cid.read()

    def test_created_is_not_started_and_immediate_exit_two_has_start_proof(self):
        obj = {'State': {'StartedAt': ZERO, 'FinishedAt': ZERO, 'Running': False}}
        self.assertFalse(batch.start_proof(obj))
        obj['State'].update(StartedAt=START, Running=True)
        self.assertTrue(batch.start_proof(obj))
        obj['State'].update(Running=False, FinishedAt=FINISH, ExitCode=2)
        self.assertTrue(batch.start_proof(obj))
        obj['State']['FinishedAt'] = '2026-11-11T10:00:00.123456788Z'
        self.assertFalse(batch.start_proof(obj))
        obj['State']['FinishedAt'] = '2026-11-11T09:59:00Z'; self.assertFalse(batch.start_proof(obj))
        for value in ('', 'not-a-time', '0' * 1000, '0000-00-00T00:00:00Z'):
            obj['State']['StartedAt'] = value
            with self.assertRaises(ValueError): batch.start_proof(obj)

    def test_unchanged_production_validator_refuses_identity_binding_and_configuration(self):
        state = self.state(); state['container_id'] = ID; obj = baseline.fake_inspect(state)
        self.assertEqual(batch.mod.check_container(state, obj), obj)
        for change in ('id', 'nonce', 'image', 'memory', 'mount'):
            value = copy.deepcopy(obj)
            if change == 'id': value['Id'] = 'd' * 64
            if change == 'nonce': value['Config']['Labels']['rw.nonce'] = '0' * 32
            if change == 'image': value['Image'] = 'sha256:' + 'd' * 64
            if change == 'memory': value['HostConfig']['Memory'] += 1
            if change == 'mount': value['Mounts'][0]['RW'] = True
            with self.subTest(change=change), self.assertRaises(ValueError): batch.mod.check_container(state, value)

    def test_budget_origin_admission_launch_rpc_tail_and_permanent_refusal(self):
        clock = Clock(); budget = batch.Budget(clock)
        clock.now = 30; budget.admit(); clock.now = 30.001
        with self.assertRaises(batch.BudgetExhausted): budget.admit()
        clock.now = 0
        with self.assertRaises(batch.BudgetExhausted): budget.admit()
        budget = batch.Budget(clock); clock.now = 34; budget.launch(); clock.now = 34.001
        with self.assertRaises(batch.BudgetExhausted): budget.launch()
        self.assertFalse(issubclass(batch.BudgetExhausted, ValueError))
        clock.now = 0; budget = batch.Budget(clock); runner = MagicMock(return_value=b'ok')
        clock.now = 38; budget.rpc(runner, ['docker', '--context', 'x', 'inspect'], timeout=30)
        self.assertEqual(runner.call_args.kwargs['timeout'], 1)
        clock.now = 39
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(runner, [], timeout=30)
        budget.phase = 'cleanup'; clock.now = 64; budget.rpc(runner, [], timeout=30)
        self.assertEqual(runner.call_args.kwargs['timeout'], 1)
        clock.now = 65
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(runner, [])

    def test_rpc_maximum_tail_and_unknown_remove_never_reset(self):
        clock = Clock(); budget = batch.Budget(clock); clock.now = 38
        def consumes_tail(argv, timeout, maximum):
            clock.now += timeout + 15; return b'ok'
        self.assertEqual(budget.rpc(consumes_tail, []), b'ok'); self.assertEqual(clock.now, 54)
        budget.phase = 'cleanup'; clock.now = 64
        self.assertEqual(budget.rpc(consumes_tail, []), b'ok'); self.assertEqual(clock.now, 80)
        clock.now = 0; budget = batch.Budget(clock)
        with self.assertRaises(ValueError):
            budget.rpc(MagicMock(side_effect=ValueError('lost rm response')), ['docker', '--context', 'x', 'rm', ID])
        self.assertTrue(budget.uncertain)
        with self.assertRaises(batch.BudgetExhausted): budget.admit()

    def test_rpc_late_reply_marks_exhausted_and_evidence_deadline_refuses_append(self):
        clock = Clock(); budget = batch.Budget(clock)
        def late(argv, timeout, maximum):
            clock.now = 54.001; return b'late'
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(late, [])
        self.assertTrue(budget.exhausted)
        journal = batch.Journal(self.root / 'deadline.jsonl', io.StringIO()); self.addCleanup(journal.close)
        owner = batch.Batch(SimpleNamespace(), journal, budget)
        clock.now = 90
        with self.assertRaises(batch.BudgetExhausted): owner.emit('late', {})
        self.assertEqual(journal.records, 0)

    def test_budget_adapter_preserves_rpc_cap_and_restores_runner(self):
        clock = Clock(); budget = batch.Budget(clock); original = batch.mod.bounded_run
        runner = MagicMock(return_value=b'ok')
        with patch.object(batch.mod, 'bounded_run', runner):
            with budget.transport():
                clock.now = 38
                self.assertEqual(batch.mod.bounded_run(['docker'], timeout=45, maximum=123), b'ok')
                self.assertEqual(runner.call_args.kwargs, {'timeout': 1, 'maximum': 123})
            self.assertIs(batch.mod.bounded_run, runner)
        self.assertIs(batch.mod.bounded_run, original)

    def test_capture_caps_lossless_binary_and_exact_owned_popen_options(self):
        capture = batch.Capture(['never-run'])
        for _ in range(100): capture.keep('stderr', b'\xff\x00' * 10000)
        capture.keep('stdout', b'o' * 8192)
        process = MagicMock(); process.poll.return_value = 2
        thread = MagicMock(); thread.is_alive.return_value = False
        with patch.object(subprocess, 'Popen', return_value=process) as create, patch.object(batch.threading, 'Thread', return_value=thread):
            capture.start(); capture.closed = True; result = capture.finish()
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.kwargs, dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, start_new_session=True, close_fds=True))
        self.assertEqual(result['streams']['stderr']['bytes'], 8192)
        raw = base64.b64decode(result['streams']['stderr']['base64'])
        self.assertEqual(raw, b'\xff\x00' * 4096); self.assertEqual(result['streams']['stderr']['sha256'], batch.sha(raw))
        self.assertTrue(result['streams']['stderr']['truncated']); self.assertFalse(result['streams']['stdout']['truncated'])
        with self.assertRaises(batch.LaunchUncertain): capture.start()

    def test_capture_thread_creation_and_start_failures_reap_owned_handle(self):
        for stage in ('construct', 'start'):
            capture = batch.Capture(['never-run']); process = MagicMock()
            process.poll.side_effect = [None, -9, -9, -9]
            thread = MagicMock(); thread.start.side_effect = RuntimeError('thread start failure')
            with patch.object(subprocess, 'Popen', return_value=process), \
                    patch.object(batch.threading, 'Thread', side_effect=RuntimeError('thread construct failure') if stage == 'construct' else None, return_value=thread):
                with self.assertRaises(RuntimeError): capture.start()
            process.kill.assert_called_once(); process.wait.assert_called_once_with(timeout=1)
            process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()
            self.assertTrue(capture.errors)

    def test_capture_popen_and_missing_pipe_failures_are_incomplete(self):
        capture = batch.Capture(['never-run'])
        with patch.object(subprocess, 'Popen', side_effect=OSError('pipe/process creation failed')):
            with self.assertRaises(OSError): capture.start()
        self.assertFalse(capture.finish()['cleanup_verified'])
        capture = batch.Capture(['never-run']); capture.process = MagicMock(); capture.started = 0
        capture.process.stdout = None; capture.process.poll.return_value = 2
        capture.drain()
        result = capture.finish(); self.assertFalse(result['cleanup_verified']); self.assertTrue(result['errors'])

    def test_capture_selector_failure_pipe_close_failure_and_finish_six_second_cap(self):
        capture = batch.Capture(['never-run']); capture.started = 0
        capture.process = MagicMock(); capture.process.poll.return_value = -9
        capture.process.stdout.close.side_effect = OSError('close failed')
        with patch.object(batch.selectors, 'DefaultSelector', side_effect=OSError('selector failed')):
            capture.drain()
        self.assertFalse(capture.finish()['cleanup_verified'])
        self.assertGreaterEqual(len(capture.errors), 2)
        capture = batch.Capture(['never-run']); capture.process = MagicMock(); capture.process.poll.return_value = None
        capture.thread = MagicMock(); capture.thread.is_alive.return_value = True
        result = capture.finish()
        self.assertFalse(result['cleanup_verified']); self.assertEqual([call.kwargs['timeout'] for call in capture.thread.join.call_args_list], [3, 2])
        capture.process.wait.assert_called_once_with(timeout=1)

    def test_retained_binary_prefix_survives_poll_join_close_and_unexpected_finish_faults(self):
        raw = b'\x00\xffstartup diagnostic prefix'
        for fault in ('poll', 'join', 'close', 'unexpected_finish'):
            capture = batch.Capture(['never-run']); capture.keep('stderr', raw)
            capture.keep('stdout', b'o' * (batch.STREAM_BYTES + 1))
            capture.process = MagicMock(); capture.process.poll.return_value = 2
            if fault == 'poll': capture.process.poll.side_effect = OSError('synthetic poll fault')
            if fault == 'join':
                capture.thread = MagicMock(); capture.thread.join.side_effect = RuntimeError('synthetic join fault')
            if fault == 'close': capture.process.stderr.close.side_effect = OSError('synthetic close fault')
            if fault == 'unexpected_finish': capture.finish = MagicMock(side_effect=RuntimeError('unexpected finish fault'))
            result = batch.Batch.finish_capture(capture)
            with self.subTest(fault=fault):
                self.assertFalse(result['cleanup_verified'])
                self.assertEqual(base64.b64decode(result['streams']['stderr']['base64']), raw)
                self.assertEqual(result['streams']['stderr']['sha256'], batch.sha(raw))
                self.assertEqual(result['streams']['stdout']['bytes'], batch.STREAM_BYTES)
                self.assertTrue(result['streams']['stdout']['truncated'])
                self.assertTrue(result.get('finish_error') or result.get('errors'))

    def test_capture_early_binary_drain_and_twenty_second_deadline_without_caller(self):
        for expired in (False, True):
            clock = Clock(); capture = batch.Capture(['never-run'], clock); capture.started = 0
            capture.process = MagicMock(); capture.process.poll.return_value = 2
            key = SimpleNamespace(fileobj=capture.process.stderr, data='stderr')
            selector = MagicMock(); selector.get_map.return_value = {1: key}
            selector.select.return_value = [(key, 1)]
            def read(fd, maximum):
                if capture.buffers['stderr']: selector.get_map.return_value = {}; return b''
                return b'\xffearly-before-cid'
            clock.now = 20 if expired else 0
            with patch.object(batch.selectors, 'DefaultSelector', return_value=selector), \
                    patch.object(os, 'set_blocking'), patch.object(os, 'read', side_effect=read):
                capture.drain()
            report = capture.finish()
            self.assertEqual(report['deadline_reached'], expired)
            self.assertTrue(report['cleanup_verified'])
            if not expired: self.assertEqual(base64.b64decode(report['streams']['stderr']['base64']), b'\xffearly-before-cid')

    def run_fake(self, modes=None, evidence_failure=False):
        clock = Clock(); budget = batch.Budget(clock)
        journal = batch.Journal(self.root / ('report-' + str(len(list(self.root.iterdir()))) + '.jsonl'), io.StringIO())
        config = SimpleNamespace(docker=sys.executable, context='explicit-test', image_id='sha256:' + 'b' * 64)
        owner = FakeBatch(config, journal, budget); owner.clock, owner.modes = clock, modes or {}
        owner.objects, owner.calls, owner.captures = {}, [], []
        owner.read_error_used = False
        synced = []; original_fsync = os.fsync
        owner.synced = synced
        def fsync(fd):
            value = os.fstat(fd); synced.append((value.st_ino, value.st_size)); return original_fsync(fd)
        def fake_docker(p, args, timeout=30, allow_missing=False):
            owner.calls.append(args)
            entry = owner.current or {}; mode = owner.modes.get(entry.get('index'), 'normal')
            if args[0:2] == ['container', 'inspect']:
                if mode == 'final_budget' and entry.get('original_assertions') and budget.phase == 'work':
                    budget.refuse('synthetic final inspection budget')
                obj = next((o for o in owner.objects.values() if args[2] in (o['Id'], o['Name'][1:])), None)
                if obj is None: return None
                if args[-1] == '{{json .Id}}': return batch.mod.canonical(obj['Id'])
                return batch.mod.canonical(obj)
            if args[0] == 'exec':
                if mode == 'read_error' and not owner.read_error_used:
                    owner.read_error_used = True; raise ValueError('transient synthetic read error')
                if args[-1] == 'collect': raise ValueError('synthetic unsafe collection refused')
                local = batch.mod.read_json(Path(entry['state_path']) / 'state.json')
                return batch.mod.canonical({'schema_version': 1, 'job_id': local['manifest']['job_id'],
                    'nonce': local['binding']['nonce'], 'manifest_sha256': local['binding']['manifest_sha256'],
                    'state': 'failed', 'reason': 'another reason' if mode in ('wrong_reason', 'primary_and_cleanup') else batch.EXPECTED_REASON,
                    'artifacts': []})
            if args[0] == 'rm':
                self.assertRegex(args[2], '^[0-9a-f]{64}$')
                if mode != 'absence_failure': owner.objects.pop(args[2], None)
                if mode in ('rm_unknown', 'primary_and_cleanup'): raise ValueError('lost remove reply')
                return b''
            raise AssertionError('Unexpected transport command: ' + repr(args))
        test = self
        class FakeCapture:
            def __init__(self, argv):
                self.argv = argv; self.errors = []; self.started = None; self.finished = 0
                self.process = MagicMock(); self.process.poll.return_value = None
                self.raw = b''; owner.captures.append(self)
            def start(self):
                self.started = clock(); entry = owner.current; mode = owner.modes.get(entry['index'], 'normal')
                local = batch.mod.read_json(Path(entry['state_path']) / 'state.json')
                test.assertTrue(local['submit_attempted']); test.assertEqual(local['status'], 'uncertain')
                for path in (journal.path, Path(entry['state_path']) / 'state.json'):
                    value = path.stat(); test.assertIn((value.st_ino, value.st_size), synced)
                records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                test.assertEqual(records[-1]['record'], 'dispatch_intent')
                test.assertEqual(records[-2]['record'], 'fixture_prepared')
                identifier = format(entry['index'], '064x')
                obj = baseline.fake_inspect(local); obj['Id'] = identifier
                obj['State'].update(StartedAt=START, FinishedAt=ZERO)
                if mode == 'created': obj['State'].update(StartedAt=ZERO, Running=False)
                if mode in ('early_exit', 'early_missing', 'launch_unknown'):
                    self.raw = b'\xffsynthetic startup exception before CID'
                    obj['State'].update(Running=False, ExitCode=2, FinishedAt=FINISH)
                    self.process.poll.return_value = 2
                if mode == 'changed_binding': obj['Config']['Labels']['rw.nonce'] = '0' * 32
                owner.objects[identifier] = obj
                if mode not in ('early_missing', 'launch_unknown', 'missing'): entry['cid'].path.write_text(identifier)
                if mode == 'partial': entry['cid'].path.write_text(identifier[:32])
                if mode == 'malformed': entry['cid'].path.write_text('X' * 64)
                if mode == 'launch_unknown': raise OSError('synthetic reader setup failure after launch')
                if mode == 'interrupt': raise KeyboardInterrupt('synthetic interruption')
                if mode == 'late_final_budget': clock.now = 38.5
                clock.now += .1
            def finish(self):
                self.finished += 1; entry = owner.current; mode = owner.modes.get(entry['index'], 'normal')
                if mode == 'finish_exception': raise OSError('synthetic finish failure')
                if mode == 'swallowed_budget':
                    try: budget.refuse('synthetic final observation budget')
                    except Exception: pass
                return {'cleanup_verified': mode != 'observer_cleanup', 'errors': [], 'deadline_reached': False,
                    'cli_exit_code': self.process.poll(),
                    'streams': {name: {'bytes': len(self.raw) if name == 'stderr' else 0,
                        'base64': base64.b64encode(self.raw if name == 'stderr' else b'').decode(),
                        'sha256': batch.sha(self.raw if name == 'stderr' else b''), 'truncated': mode == 'flood'}
                        for name in ('stdout', 'stderr')}}
        original_emit = journal.emit
        def emit(kind, value, **kwargs):
            if evidence_failure and kind == 'fixture_result': raise batch.EvidenceError('synthetic record cap')
            result = original_emit(kind, value, **kwargs)
            if kind == 'fixture_prepared' and owner.modes.get(value['index']) == 'late_launch': clock.now = 35
            return result
        journal.emit = emit
        try:
            with patch.object(batch.mod, 'inspect_engine', return_value={'id': 'engine-control', 'architecture': 'amd64'}), \
                    patch.object(batch.mod, 'inspect_image', return_value={'architecture': 'amd64'}), \
                    patch.object(batch.mod, 'docker', side_effect=fake_docker), patch.object(batch, 'Capture', FakeCapture), \
                    patch.object(batch.time, 'monotonic', clock), patch.object(batch.time, 'sleep', clock.sleep), \
                    patch.object(os, 'fsync', side_effect=fsync), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = owner.run()
        finally:
            journal.close()
        return code, [json.loads(line) for line in journal.path.read_text().splitlines()], owner

    def test_three_fresh_intents_and_exact_cleanup_before_next_submit(self):
        code, records, owner = self.run_fake()
        self.assertEqual(code, 0, records[-1]); self.assertEqual(records[-1]['classification'], 'not_reproduced_in_3')
        self.assertEqual(len(owner.captures), 3); self.assertEqual(len(owner.seen_jobs), 3); self.assertEqual(len(owner.seen_ids), 3)
        order = [x['record'] for x in records]
        self.assertEqual(order.count('cleanup_intent'), 3)
        for result in [x for x in records if x['record'] == 'fixture_result']:
            self.assertTrue(result['accepted']); self.assertTrue(result['cleanup']['absence_verified'])
            self.assertEqual(result['terminal_result']['reason'], batch.EXPECTED_REASON)
        self.assertFalse(records[-1]['historical_exit_2_resolved'])
        self.assertTrue(owner.root.exists())

    def test_original_transient_read_error_recovers(self):
        code, records, _ = self.run_fake({1: 'read_error'})
        self.assertEqual(code, 0, records[-1])
        first = next(x for x in records if x['record'] == 'fixture_result')
        self.assertIn('read_error', [x['event'] for x in first['status_queries']['entries']])

    def test_early_exit_before_ack_retains_binary_and_start_binding_then_stops(self):
        for mode in ('early_exit', 'early_missing', 'launch_unknown'):
            code, records, owner = self.run_fake({1: mode})
            self.assertEqual(code, 1); self.assertEqual(len(owner.captures), 1)
            result = next(x for x in records if x['record'] == 'fixture_result')
            self.assertTrue(result['start_proven']); self.assertEqual(result['last_container_state']['ExitCode'], 2)
            self.assertTrue(base64.b64decode(result['observer']['streams']['stderr']['base64']).startswith(b'\xff'))
            self.assertTrue(result['cleanup']['verified']); self.assertTrue(records[-1]['uncertain_launch_or_remove'])
            self.assertFalse(result['submit_confirmed'])

    def test_validated_start_identity_is_fsynced_before_exception_cleanup_boundary(self):
        original_cleanup = batch.Batch.cleanup
        observations = []
        def observe(owner, entry):
            # This is after unchanged production submit catches/rewrites its old
            # state, but before any diagnostic cleanup or cleanup-intent record.
            local = batch.mod.read_json(Path(entry['state_path']) / 'state.json')
            records = [json.loads(line) for line in owner.journal.path.read_text().splitlines()]
            validated = [record for record in records if record['record'] == 'validated_identity']
            self.assertIsNone(local['container_id'])  # Production behavior is unchanged.
            self.assertTrue(local['submit_attempted']); self.assertEqual(local['status'], 'uncertain')
            self.assertEqual(len(validated), 1)
            record = validated[0]
            self.assertEqual(record['container_id'], entry['container_id'])
            self.assertEqual(record['binding'], local['binding'])
            self.assertEqual(record['container_name'], local['container_name'])
            self.assertEqual(record['container_state']['StartedAt'], START)
            self.assertEqual(record['container_state']['ExitCode'], 2)
            self.assertTrue(record['start_proven']); self.assertFalse(record['submit_acknowledged'])
            current = owner.journal.path.stat()
            self.assertIn((current.st_ino, current.st_size), owner.synced)
            observations.append(record)
            return original_cleanup(owner, entry)
        for mode in ('early_exit', 'early_missing'):
            with patch.object(batch.Batch, 'cleanup', observe):
                code, records, owner = self.run_fake({1: mode})
            self.assertEqual(code, 1); self.assertEqual(len(owner.captures), 1)
            self.assertTrue(records[-1]['uncertain_launch_or_remove'])
        self.assertEqual(len(observations), 2)

    def test_workflow_requires_contract_success_and_reports_missing_prerequisite(self):
        workflow = (Path(batch.__file__).resolve().parents[1] / '.github/workflows/research-writer-ci.yml').read_text()
        def step(name):
            return workflow.split('- name: ' + name, 1)[1].split('- name:', 1)[0]
        contracts = step('Check bounded Linux diagnostic observer contracts')
        self.assertIn('id: linux_diagnostic_contracts', contracts)
        dispatch = step('Capture one bounded startup diagnostic with a 90 second watchdog')
        refusal = step('Report startup diagnostic prerequisite failure')
        for identity in ('linux_diagnostic_contracts', 'provision_linux_image'):
            self.assertIn("steps." + identity + ".outcome == 'success'", dispatch)
            self.assertIn("steps." + identity + ".outcome != 'success'", refusal)
        self.assertIn('exit 1', refusal)
        self.assertIn('timeout --signal=KILL 90s', dispatch)
        native = step('Require actual Linux resource and interrupted-recovery controls')
        self.assertIn('inputs.linux_startup_diagnostic', native)
        self.assertNotIn('steps.linux_diagnostic_contracts', native)

    def test_unexpected_reason_capture_errors_and_swallowed_budget_cannot_pass(self):
        for mode in ('wrong_reason', 'observer_cleanup', 'finish_exception', 'flood', 'swallowed_budget'):
            code, records, owner = self.run_fake({1: mode})
            self.assertEqual(code, 1, mode); self.assertEqual(len(owner.captures), 1, mode)
            result = next(x for x in records if x['record'] == 'fixture_result')
            self.assertFalse(result['accepted']); self.assertTrue(result['cleanup']['verified'])
            self.assertEqual(owner.captures[0].finished, 1, mode)

    def test_created_only_changed_binding_and_unknown_remove_no_retry_or_name_removal(self):
        for mode in ('created', 'missing', 'partial', 'malformed', 'changed_binding', 'rm_unknown', 'absence_failure'):
            code, records, owner = self.run_fake({1: mode})
            self.assertEqual(code, 1, mode); self.assertEqual(len(owner.captures), 1)
            removals = [args for args in owner.calls if args[0] == 'rm']
            self.assertLessEqual(len(removals), 1)
            if mode == 'changed_binding': self.assertEqual(removals, [])
            for args in removals: self.assertRegex(args[2], '^[0-9a-f]{64}$')

    def test_setup_time_counts_and_evidence_failure_retains_primary(self):
        code, records, owner = self.run_fake({0: 'setup_budget'})
        self.assertEqual(code, 1); self.assertEqual(owner.captures, [])
        self.assertTrue(records[-1]['budget_exhausted'])
        code, records, owner = self.run_fake({1: 'early_exit'}, evidence_failure=True)
        self.assertEqual(code, 1); self.assertEqual(len(owner.captures), 1)
        summary = records[-1]; self.assertIsNotNone(summary['unwritten_sample']['primary_failure'])
        self.assertTrue(summary['unwritten_sample']['observer']['streams']['stderr']['base64'])

    def test_late_launch_refusal_preserves_durable_intent_without_popen(self):
        code, records, owner = self.run_fake({1: 'late_launch'})
        self.assertEqual(code, 1); self.assertEqual(owner.captures, [])
        result = next(x for x in records if x['record'] == 'fixture_result')
        self.assertFalse(result['popen_attempted']); self.assertIn('launch_refused', result)
        self.assertTrue(records[-1]['uncertain_launch_or_remove'])
        state = Path(result['state_path']); self.assertTrue(state.exists())
        self.assertTrue(batch.mod.read_json(state / 'state.json')['submit_attempted'])

    def test_primary_cleanup_failure_and_previous_success_survive_together(self):
        code, records, owner = self.run_fake({2: 'primary_and_cleanup'})
        self.assertEqual(code, 1); self.assertEqual(len(owner.captures), 2)
        results = [x for x in records if x['record'] == 'fixture_result']
        self.assertTrue(results[0]['accepted']); self.assertEqual(results[1]['primary_failure']['kind'], 'AssertionError')
        self.assertIn('lost remove reply', results[1]['cleanup']['error']['text'])
        self.assertEqual(sum(args[0] == 'rm' for args in owner.calls), 2)

    def test_third_final_inspection_or_swallowed_budget_never_qualifies_complete_batch(self):
        for mode in ('final_budget', 'swallowed_budget', 'interrupt'):
            code, records, owner = self.run_fake({3: mode})
            self.assertEqual(code, 1); self.assertEqual(len(owner.captures), 3)
            if mode != 'interrupt': self.assertTrue(records[-1]['budget_exhausted'])
            self.assertEqual(records[-1]['classification'], 'failed_or_incomplete')

    def test_journal_exclusive_record_aggregate_caps_and_summary_reserve(self):
        path = self.root / 'journal.jsonl'; journal = batch.Journal(path, io.StringIO())
        self.addCleanup(journal.close)
        with self.assertRaises(FileExistsError): batch.Journal(path, io.StringIO())
        with self.assertRaises(batch.EvidenceError): journal.emit('big', {'x': 'x' * 65537})
        with self.assertRaises(batch.EvidenceError): journal.emit('big', {'x': ['x' * 60000] * 3})
        for index in range(31): journal.emit('bounded', {'index': index})
        with self.assertRaises(batch.EvidenceError): journal.emit('overflow', {})
        journal.emit('summary', {'classification': 'failed_or_incomplete'}, final=True)
        self.assertEqual(journal.records, 32)
        path2 = self.root / 'byte-cap.jsonl'; other = batch.Journal(path2, io.StringIO()); self.addCleanup(other.close)
        for _ in range(7): other.emit('large', {'x': ['x' * 60000] * 2})
        with self.assertRaises(batch.EvidenceError): other.emit('large', {'x': ['x' * 60000] * 2})
        other.emit('summary', {'classification': 'failed_or_incomplete'}, final=True)
        self.assertLessEqual(other.bytes, batch.REPORT_BYTES)

    def test_pure_supervisor_symlink_rejection_and_separate_publication_exception(self):
        source = batch.integration.SCRIPTS / 'linux_supervisor.py'
        spec = importlib.util.spec_from_file_location('startup_pure_supervisor', source)
        sup = importlib.util.module_from_spec(spec); spec.loader.exec_module(sup)
        for injected in (False, True):
            folder = self.root / ('supervisor-' + str(injected)); folder.mkdir()
            work = folder / 'work'; control = folder / 'control'; work.mkdir(); control.mkdir()
            (work / 'result.json').symlink_to('/etc/hosts')
            manifest = {'job_id': 'a' * 32, 'resources': dict(batch.RESOURCES), 'inputs': [],
                        'outputs': ['result.json'], 'argv': ['/never-executed']}
            binding = {'nonce': 'b' * 32, 'manifest_sha256': 'c' * 64}
            receipts = []
            def atomic(path, value):
                if injected and receipts: raise OSError('synthetic publication exception; not actual CI cause')
                receipts.append(copy.deepcopy(value))
            child = MagicMock(returncode=0); child.poll.return_value = 0
            selector = MagicMock(); selector.select.return_value = []; selector.get_map.return_value = {}
            with contextlib.ExitStack() as stack:
                for key, value in [('WORK', work), ('CONTROL', control), ('_CANCEL', False),
                                   ('checked_binding', lambda: (manifest, binding)), ('effective_limits', lambda r: {}),
                                   ('atomic', atomic), ('counters', lambda: {}), ('stop_namespace', MagicMock())]:
                    stack.enter_context(patch.object(sup, key, value))
                stack.enter_context(patch.object(sup.sys, 'platform', 'linux'))
                stack.enter_context(patch.object(sup.sys, 'argv', ['supervisor', 'run']))
                stack.enter_context(patch.object(sup.os, 'getpid', return_value=1))
                stack.enter_context(patch.object(sup.os, 'getuid', return_value=0))
                stack.enter_context(patch.object(sup.os, 'set_blocking'))
                stack.enter_context(patch.object(sup.signal, 'signal'))
                stack.enter_context(patch.object(sup.subprocess, 'Popen', return_value=child))
                stack.enter_context(patch.object(sup.selectors, 'DefaultSelector', return_value=selector))
                stack.enter_context(patch.object(sup.time, 'monotonic', side_effect=[0, 0, 1, 32]))
                stack.enter_context(patch.object(sup.time, 'sleep', side_effect=AssertionError('Real wait forbidden')))
                stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                code = sup.main()
            if injected:
                self.assertEqual(code, 2); self.assertIn('synthetic publication exception', stderr.getvalue())
                self.assertEqual([x['state'] for x in receipts], ['running'])
            else:
                self.assertEqual(code, 1); self.assertEqual(receipts[-1]['state'], 'failed')
                self.assertEqual(receipts[-1]['reason'], batch.EXPECTED_REASON)
                self.assertEqual(receipts[-1]['artifacts'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
