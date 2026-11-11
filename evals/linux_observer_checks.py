#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Harmless local observer contracts: no Docker or container execution."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import linux_observer as observer
import linux_integration_checks as integration

ID = 'a' * 64


class ObserverContracts(unittest.TestCase):
    def local_child(self, code):
        """Substitute only a disposable stdlib Python child for the attach CLI."""
        real_popen = subprocess.Popen
        calls = []

        def start(argv, **kwargs):
            proc = real_popen([sys.executable, '-c', code], **kwargs)
            calls.append((argv, kwargs, proc))
            return proc

        return calls, patch.object(observer.subprocess, 'Popen', side_effect=start)

    def test_requires_exact_immutable_identity_before_any_process(self):
        with patch.object(observer.subprocess, 'Popen') as create:
            for identity, validated in [('fixture-name', 'fixture-name'), ('a' * 63, 'a' * 63),
                                        ('A' * 64, 'A' * 64), (ID, 'b' * 64), (None, None)]:
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    observer.LiveObserver('/never-run-docker', 'fixture', identity, validated)
            create.assert_not_called()

    def test_continuous_bounded_drain_on_both_streams(self):
        code = "import os\nfor _ in range(128):\n os.write(1,b'o'*16384);os.write(2,b'e'*16384)"
        calls, create = self.local_child(code)
        with create:
            live = observer.LiveObserver('/never-run-docker', 'fixture', ID, ID)
            try:
                live._thread.join(timeout=5)
            finally:
                report = live.finish()
        self.assertTrue(report['cleanup_verified']); self.assertEqual(report['exit_code'], 0)
        self.assertEqual((report['stdout_bytes'], report['stderr_bytes']), (8192, 8192))
        self.assertEqual(report['stdout'], 'o' * 8192); self.assertEqual(report['stderr'], 'e' * 8192)
        self.assertEqual(report['truncated'], {'stdout': True, 'stderr': True})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ['/never-run-docker', '--context', 'fixture', 'attach',
                                     '--no-stdin', '--sig-proxy=false', ID])
        self.assertIs(calls[0][1]['shell'], False)
        self.assertEqual(calls[0][1]['stdin'], subprocess.DEVNULL)
        self.assertEqual(report['errors'], [])
        self.assertIn('earlier_output_unavailable', report['coverage'])

    def test_deadline_stops_owned_cli_without_caller_polling(self):
        calls, create = self.local_child('import time;time.sleep(60)')
        with create, patch.object(observer, 'LIFETIME_SECONDS', 0.15):
            live = observer.LiveObserver('/never-run-docker', 'fixture', ID, ID)
            try:
                live._thread.join(timeout=3)
                # Observe independent deadline enforcement before finish().
                stopped_independently = not live._thread.is_alive() and live._process.poll() is not None
            finally:
                report = live.finish()
        self.assertTrue(stopped_independently)
        self.assertTrue(report['deadline_reached']); self.assertTrue(report['cleanup_verified'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(live._process.stdout.closed); self.assertTrue(live._process.stderr.closed)

    def test_finally_cleanup_after_caller_assertion_and_idempotent_finish(self):
        calls, create = self.local_child('import time;time.sleep(60)')
        with create:
            live = observer.LiveObserver('/never-run-docker', 'fixture', ID, ID)
            with self.assertRaisesRegex(AssertionError, 'synthetic acceptance failure'):
                try:
                    raise AssertionError('synthetic acceptance failure')
                finally:
                    first = live.finish()
            second = live.finish()
        self.assertTrue(first['cleanup_verified']); self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_capture_initialization_failure_still_cleans_up(self):
        _, create = self.local_child('import time;time.sleep(60)')
        with create, patch.object(observer.selectors, 'DefaultSelector', side_effect=OSError('synthetic selector failure')):
            live = observer.LiveObserver('/never-run-docker', 'fixture', ID, ID)
            live._thread.join(timeout=3)
            report = live.finish()
        self.assertTrue(report['cleanup_verified'])
        self.assertIn('synthetic selector failure', report['errors'][0])
        self.assertTrue(live._process.stdout.closed); self.assertTrue(live._process.stderr.closed)

    def test_thread_start_failure_still_cleans_up(self):
        calls, create = self.local_child('import time;time.sleep(60)')
        with create:
            with patch.object(observer.threading.Thread, 'start', side_effect=RuntimeError('synthetic thread failure')):
                with self.assertRaisesRegex(RuntimeError, 'synthetic thread failure'):
                    observer.LiveObserver('/never-run-docker', 'fixture', ID, ID)
        self.assertEqual(len(calls), 1)
        proc = calls[0][2]
        self.assertIsNotNone(proc.poll()); self.assertTrue(proc.stdout.closed); self.assertTrue(proc.stderr.closed)

    def test_chronology_and_inspect_output_are_bounded_and_allowlisted(self):
        history = observer.QueryChronology()
        for _ in range(1000):
            history.add('read_error', 'x' * 10000)
        result = history.report()
        self.assertTrue(result['truncated']); self.assertLessEqual(len(result['entries']), 32)
        self.assertLessEqual(sum(len(x['value'].encode()) for x in result['entries']), 8192)
        self.assertTrue(all(len(x['value'].encode()) <= 512 for x in result['entries']))
        state = observer.container_state({'StartedAt': 'x' * 1000, 'FinishedAt': 'y' * 1000,
                                          'Error': 'z' * 10000, 'Running': False, 'ExitCode': 2,
                                          'OOMKilled': False, 'Env': ['SECRET=never-output']})
        self.assertEqual(set(state), {'StartedAt', 'FinishedAt', 'Error', 'Running', 'ExitCode', 'OOMKilled'})
        self.assertEqual(state['ExitCode'], 2); self.assertLessEqual(len(state['Error']), 512)
        self.assertLessEqual(len(observer.bounded_text('\u2603' * 1000).encode('utf-8')), 512)

    def test_snapshot_refuses_changed_binding_or_id_before_attach(self):
        case = integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(integration.mod, 'state_lock', return_value=contextlib.nullcontext(Path('/fixture'))))
            checked = stack.enter_context(patch.object(integration.mod, 'checked_state', return_value={'container_id': ID}))
            inspected = stack.enter_context(patch.object(integration.mod, 'inspect_container', return_value={'Id': 'b' * 64}))
            create = stack.enter_context(patch.object(integration, 'LiveObserver'))
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                case.observer_snapshot(Path('/fixture'))
            checked.side_effect = ValueError('changed supervisor binding')
            with self.assertRaisesRegex(ValueError, 'changed supervisor binding'):
                case.observer_snapshot(Path('/fixture'))
            create.assert_not_called(); self.assertEqual(inspected.call_count, 1)

    def test_cpu_assertion_failure_retains_diagnostics_and_finishes_once(self):
        case = integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        local = {'container_id': ID, 'binding': {'manifest_sha256': 'b' * 64, 'supervisor_sha256': 'c' * 64},
                 'profile': {'docker_executable': '/never-run-docker', 'context': 'fixture'}}
        obj = {'Id': ID, 'State': {'Running': True}}
        live = MagicMock(); live.finish.return_value = {'cleanup_verified': True}
        with patch.object(case, 'job', return_value=Path('/fixture')) as job, \
                patch.object(case, 'observer_snapshot', return_value=(local, obj)), \
                patch.object(integration, 'LiveObserver', return_value=live) as create, \
                patch.object(case, 'terminal', return_value={'state': 'artifacts_unavailable'}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(AssertionError):
                case.test_02_actual_cpu_throttling_rate()
        self.assertEqual(job.call_count, 1); self.assertEqual(job.call_args.args[1], {'cpu_millis': 250})
        self.assertEqual(create.call_count, 1); live.finish.assert_called_once_with()
        diagnostic = json.loads(output.getvalue())['supervisor_diagnostic']
        self.assertTrue(diagnostic['attachment']['cleanup_verified'])
        self.assertEqual(diagnostic['container_id'], ID)

    def test_cpu_changed_binding_never_attaches_or_retries_the_job(self):
        case = integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        with patch.object(case, 'job', return_value=Path('/fixture')) as job, \
                patch.object(case, 'observer_snapshot', side_effect=ValueError('changed binding')), \
                patch.object(integration, 'LiveObserver') as create, \
                patch.object(case, 'terminal', return_value={'state': 'artifacts_unavailable'}) as terminal, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(AssertionError):
                case.test_02_actual_cpu_throttling_rate()
        create.assert_not_called(); self.assertEqual(job.call_count, 1); self.assertEqual(terminal.call_count, 1)
        diagnostic = json.loads(output.getvalue())['supervisor_diagnostic']
        self.assertEqual(diagnostic['observer_unavailable'], 'changed binding')
        self.assertEqual(diagnostic['final_inspect_unavailable'], 'changed binding')

    def test_recover_error_chronology_preserves_order(self):
        case = integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        history = observer.QueryChronology()
        with patch.object(integration.mod, 'operate', side_effect=[ValueError('synthetic read race'), {'state': 'succeeded'}]) as operate, \
                patch.object(integration.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            result = case.terminal(Path('/fixture'), chronology=history)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual([x['event'] for x in history.report()['entries']], ['read_error', 'receipt_state'])
        self.assertTrue(all(x.args == ('recover', Path('/fixture')) for x in operate.call_args_list))

    def cpu_cleanup_result(self, *, finish_raises=False, primary_failure=False):
        case = integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        local = {'container_id': ID, 'binding': {'manifest_sha256': 'b' * 64, 'supervisor_sha256': 'c' * 64},
                 'profile': {'docker_executable': '/never-run-docker', 'context': 'fixture'}}
        obj = {'Id': ID, 'State': {'Running': True, 'StartedAt': 'synthetic-start'}}
        live = MagicMock()
        live.finish.return_value = {'cleanup_verified': False, 'errors': ['synthetic cleanup failure']}
        if finish_raises:
            live.finish.side_effect = RuntimeError('synthetic finish failure')
        primary = AssertionError('primary CPU failure')
        destination = MagicMock()
        destination.__truediv__.return_value.read_text.return_value = '{"cpu_seconds":0.6}'

        def terminal(_state, *, chronology):
            chronology.add('receipt_state', 'synthetic receipt')
            if primary_failure:
                raise primary
            return {'state': 'succeeded', 'effective_limits': {'cpu_millis': 250},
                    'cgroup_counters': {'cpu.stat': {'nr_throttled': '1'}}}

        with patch.object(case, 'job', return_value=Path('/fixture')) as job, \
                patch.object(case, 'observer_snapshot', return_value=(local, obj)) as snapshot, \
                patch.object(integration, 'LiveObserver', return_value=live) as create, \
                patch.object(case, 'terminal', side_effect=terminal), \
                patch.object(case, 'collected', return_value=({}, destination)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(AssertionError) as caught:
                case.test_02_actual_cpu_throttling_rate()
        self.assertEqual(job.call_count, 1); self.assertEqual(create.call_count, 1)
        live.finish.assert_called_once_with(); self.assertEqual(snapshot.call_count, 2)
        diagnostic = json.loads(output.getvalue())['supervisor_diagnostic']
        self.assertEqual(diagnostic['final_container_state']['StartedAt'], 'synthetic-start')
        self.assertEqual(diagnostic['status_queries']['entries'][0]['value'], 'synthetic receipt')
        self.assertIs(diagnostic['attachment']['cleanup_verified'], False)
        if primary_failure:
            self.assertIs(caught.exception, primary)
        else:
            self.assertIn('Local observer cleanup could not be verified', str(caught.exception))
        return diagnostic

    def test_unverified_cleanup_fails_otherwise_successful_cpu_test(self):
        self.cpu_cleanup_result()

    def test_callers_handled_exception_does_not_hide_cleanup_failure(self):
        try:
            raise ValueError('unrelated caller exception')
        except ValueError:
            self.cpu_cleanup_result()

    def test_finish_exception_emits_diagnostics_and_fails_successful_cpu_test(self):
        diagnostic = self.cpu_cleanup_result(finish_raises=True)
        self.assertIn('RuntimeError: synthetic finish failure', diagnostic['attachment']['finish_error'])

    def test_unverified_cleanup_preserves_primary_cpu_failure(self):
        self.cpu_cleanup_result(primary_failure=True)

    def test_finish_exception_emits_diagnostics_and_preserves_primary_failure(self):
        diagnostic = self.cpu_cleanup_result(finish_raises=True, primary_failure=True)
        self.assertIn('RuntimeError: synthetic finish failure', diagnostic['attachment']['finish_error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
