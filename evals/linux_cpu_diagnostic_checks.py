#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fake-clock and harmless local contracts; never starts Docker or a subprocess."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

import linux_cpu_diagnostic as batch

ID = 'a' * 64


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now


class FakeCPU(batch.DiagnosticCPU):
    def run(self, result):
        result.startTest(self)
        index = self.entry['index']; owner = self.owner
        mode = owner.modes.get(index, 'success')
        self.state_path = None if mode == 'prepare' else Path('/synthetic/state-' + str(index))
        self.entry.update(job_id=format(index, '032x'), container_id=format(index, '064x'),
                          submit_attempted=mode != 'prepare', submit_confirmed=mode not in ('prepare', 'submit_unknown'))
        if mode != 'prepare': owner.order.append(('submit', index))
        self.diagnostic = {'attachment': {'cleanup_verified': mode != 'observer'},
                           'status_queries': {'entries': [{'event': 'read_error'}, {'event': 'receipt_state', 'value': 'succeeded'}]}}
        self.terminal_result = {'state': 'succeeded'}
        owner.clock.now += 1
        try:
            if mode == 'submit_unknown':
                owner.budget.uncertain_mutation = True
                raise ValueError('synthetic lost submit reply')
            if mode == 'prepare': raise ValueError('synthetic prepare failure')
            if mode == 'assertion': raise AssertionError('primary fixture failure')
            if mode == 'budget':
                owner.clock.now = 150
                owner.budget.refuse('synthetic work deadline')
            if mode == 'swallowed_budget':
                try:
                    owner.budget.refuse('synthetic final inspect deadline')
                except Exception as exc:
                    self.diagnostic['final_inspect_unavailable'] = str(exc)
            result.addSuccess(self)
        except AssertionError:
            result.addFailure(self, sys.exc_info())
        except Exception:
            result.addError(self, sys.exc_info())
        finally:
            result.stopTest(self)


class FakeBatch(batch.Batch):
    def setup(self):
        self.case_class = FakeCPU
        if self.setup_failure: raise ValueError('synthetic setup failure')

    def cleanup(self, case):
        index = case.entry['index']; self.order.append(('cleanup', index))
        if index in self.cleanup_failures:
            if self.cleanup_failures[index] == 'remove': self.budget.uncertain_mutation = True
            raise ValueError('secondary cleanup failure: ' + self.cleanup_failures[index])
        return {'verified': True, 'container_id': case.entry['container_id'], 'absent_after_remove': True}


class BatchContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rw-cpu-batch-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(docker='/never-run-docker', context='synthetic', image_id='sha256:' + 'b' * 64)

    def run_fake(self, modes=None, cleanup=None, setup_failure=False, evidence_failure=False):
        clock = Clock(); budget = batch.Budget(clock)
        journal = batch.Journal(self.root / ('report-' + str(len(list(self.root.iterdir()))) + '.jsonl'), io.StringIO())
        if evidence_failure:
            emit = journal.emit
            def limited(kind, value, **kwargs):
                if kind == 'fixture_result': raise batch.EvidenceError('synthetic evidence cap')
                return emit(kind, value, **kwargs)
            journal.emit = limited
        owner = FakeBatch(self.config, journal, budget)
        owner.clock, owner.modes, owner.cleanup_failures = clock, modes or {}, cleanup or {}
        owner.order, owner.setup_failure = [], setup_failure
        with patch.object(batch.mod, 'bounded_run', side_effect=AssertionError('no Docker or subprocess permitted')):
            code = owner.run()
        journal.close()
        records = [json.loads(line) for line in journal.path.read_text().splitlines()]
        return code, records, owner

    def test_exactly_eight_fresh_samples_and_cleanup_before_next_submit(self):
        code, records, owner = self.run_fake()
        self.assertEqual(code, 0)
        self.assertEqual(owner.order, [(op, n) for n in range(1, 9) for op in ('submit', 'cleanup')])
        samples = [x for x in records if x['record'] == 'fixture_result']
        self.assertEqual(len({x['job_id'] for x in samples}), 8)
        self.assertEqual(len({x['container_id'] for x in samples}), 8)
        self.assertEqual(records[-1]['classification'], 'not_reproduced_in_8')
        self.assertIs(records[-1]['historical_exit_2_resolved'], False)
        self.assertTrue(all(x['supervisor_diagnostic']['status_queries']['entries'][0]['event'] == 'read_error' for x in samples))

    def test_first_failure_matrix_preserves_earlier_success_and_stops(self):
        for mode in ('prepare', 'submit_unknown', 'assertion', 'observer', 'budget'):
            with self.subTest(mode=mode):
                code, records, owner = self.run_fake({2: mode})
                samples = [x for x in records if x['record'] == 'fixture_result']
                self.assertEqual(code, 1); self.assertEqual(len(samples), 2)
                self.assertTrue(samples[0]['accepted']); self.assertFalse(samples[1]['accepted'])
                self.assertFalse(any(n > 2 for _, n in owner.order))
                self.assertEqual(records[-1]['classification'], 'failed_or_incomplete')

    def test_cleanup_failure_matrix_and_primary_failure_are_retained(self):
        for fault in ('remove', 'identity', 'absence'):
            with self.subTest(fault=fault):
                code, records, owner = self.run_fake({2: 'assertion'}, {2: fault})
                sample = [x for x in records if x['record'] == 'fixture_result'][-1]
                self.assertEqual(code, 1); self.assertEqual(len(owner.completed), 2)
                self.assertIn('primary fixture failure', sample['primary_failure']['errors'][0]['text'])
                self.assertIn('secondary cleanup failure', sample['container_cleanup']['error']['text'])

    def test_setup_failure_emits_summary_without_sample(self):
        code, records, owner = self.run_fake(setup_failure=True)
        self.assertEqual(code, 1); self.assertEqual(owner.order, [])
        self.assertEqual(records[-1]['failure']['kind'], 'ValueError')
        self.assertIn('setup failure', records[-1]['failure']['error']['text'])

    def test_eighth_sample_swallowed_final_inspect_budget_still_fails_batch(self):
        code, records, owner = self.run_fake({8: 'swallowed_budget'})
        samples = [x for x in records if x['record'] == 'fixture_result']
        self.assertEqual(code, 1); self.assertEqual(len(samples), 8)
        self.assertTrue(all(x['accepted'] for x in samples[:7])); self.assertFalse(samples[7]['accepted'])
        self.assertTrue(samples[7]['budget_exhausted'])
        self.assertEqual(samples[7]['supervisor_diagnostic']['final_inspect_unavailable'], 'synthetic final inspect deadline')
        self.assertEqual(records[-1]['classification'], 'failed_or_incomplete')

    def test_budget_absolute_admission_and_maximum_rpc_tail_plus_observer_finish(self):
        clock = Clock(); budget = batch.Budget(clock)
        clock.now = 125; budget.admit()
        clock.now = 125.001
        with self.assertRaises(batch.BudgetExhausted): budget.admit()
        self.assertTrue(budget.exhausted)
        clock = Clock(); budget = batch.Budget(clock); clock.now = 128
        calls = []
        def slow(argv, timeout, maximum):
            calls.append((argv, timeout, maximum)); clock.now += timeout + 15
            return 0, b'ok', b''
        argv = ['/docker', '--context', 'frozen', 'exec', ID]
        budget.rpc(slow, argv, timeout=30, maximum=123)
        self.assertEqual(calls, [(argv, 1, 123)]); self.assertEqual(clock.now, 144)
        clock.now += 6  # Entire existing finish() budget, including both joins.
        self.assertEqual(clock.now, 150)
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(slow, argv)
        budget.phase = 'cleanup'
        budget.rpc(slow, argv)
        self.assertEqual(calls[-1][1], 10); self.assertEqual(clock.now, 175)
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(slow, argv)
        self.assertEqual(len(calls), 2); self.assertEqual(batch.TOTAL_SECONDS - clock.now, 5)

    def test_budget_setup_uses_same_clock_and_never_increases_timeout(self):
        clock = Clock(); budget = batch.Budget(clock)
        clock.now = 100  # Time spent during setup before first inspection.
        seen = []
        budget.rpc(lambda a, **kw: seen.append(kw) or (0, b'', b''), ['/docker', '--context', 'x', 'info'], timeout=2, maximum=99)
        self.assertEqual(seen, [{'timeout': 2, 'maximum': 99}])
        clock.now = 129
        with self.assertRaises(batch.BudgetExhausted): budget.rpc(lambda *a, **kw: self.fail('late RPC'), [])

    def test_budget_exhaustion_bypasses_existing_terminal_valueerror_retry(self):
        case = batch.integration.LinuxActual('test_02_actual_cpu_throttling_rate')
        self.assertFalse(issubclass(batch.BudgetExhausted, ValueError))
        with patch.object(batch.mod, 'operate', side_effect=batch.BudgetExhausted('stop')) as operate, \
                patch.object(batch.integration.time, 'sleep') as sleep:
            with self.assertRaises(batch.BudgetExhausted): case.terminal(Path('/fixture'))
        self.assertEqual(operate.call_count, 1); sleep.assert_not_called()

    def test_unknown_mutation_permanently_blocks_admission_after_reconciliation(self):
        for operation in ('run', 'rm'):
            with self.subTest(operation=operation):
                budget = batch.Budget(Clock())
                def lost(*a, **kw): raise ValueError('lost reply')
                with self.assertRaises(ValueError): budget.rpc(lost, ['/docker', '--context', 'x', operation])
                budget.phase = 'cleanup'
                budget.rpc(lambda *a, **kw: (0, b'bound immutable ID', b''), ['/docker', '--context', 'x', 'container'])
                budget.phase = 'work'
                with self.assertRaises(batch.BudgetExhausted): budget.admit()

    def job_case(self, lost=False):
        state = self.root / 'prepared'; state.mkdir()
        local = {'manifest': {'job_id': 'c' * 32, 'resources': {'cpu_millis': 250}},
                 'binding': {'manifest_sha256': 'd' * 64}, 'container_name': 'owned-synthetic'}
        (state / 'state.json').write_text(json.dumps(local))
        journal = batch.Journal(self.root / 'intent.jsonl', io.StringIO())
        self.addCleanup(journal.close)
        owner = batch.Batch(self.config, journal, batch.Budget(Clock()))
        case = batch.DiagnosticCPU('test_02_actual_cpu_throttling_rate'); case.owner = owner
        case.entry = {'index': 1}; case.state_path = None
        def submit(*args, **kw):
            records = [json.loads(x) for x in journal.path.read_text().splitlines()]
            self.assertEqual(records[-1]['record'], 'fixture_prepared')
            self.assertEqual(args, ('submit', state)); self.assertEqual(kw, {'allow_execute': True})
            if lost: raise ValueError('lost submit reply')
            return {'state': 'submitted', 'container_id': ID}
        return state, owner, case, submit

    def test_prepared_identity_fsynced_before_single_submit_and_duplicates_refused(self):
        state, owner, case, submit = self.job_case()
        with patch.object(batch.integration.LinuxActual, 'job', return_value=state), \
                patch.object(batch.mod, 'operate', side_effect=submit) as operate:
            case.job('original code', {'cpu_millis': 250})
            with self.assertRaisesRegex(RuntimeError, 'Duplicate'): case.job('original code', {'cpu_millis': 250})
        self.assertEqual(operate.call_count, 1); self.assertEqual(case.entry['container_id'], ID)

    def test_lost_submit_keeps_state_and_permanent_uncertainty(self):
        state, owner, case, submit = self.job_case(lost=True)
        with patch.object(batch.integration.LinuxActual, 'job', return_value=state), patch.object(batch.mod, 'operate', side_effect=submit):
            with self.assertRaises(ValueError): case.job('original code')
        self.assertEqual(case.state_path, state); self.assertTrue(state.exists())
        self.assertTrue(owner.budget.uncertain_mutation)

    def cleanup_fixture(self, *, discovered=ID, entry_id=ID, remove_error=False, absent=True, uncertain=False):
        journal = batch.Journal(self.root / ('cleanup-' + str(len(list(self.root.iterdir()))) + '.jsonl'), io.StringIO())
        self.addCleanup(journal.close)
        owner = batch.Batch(self.config, journal, batch.Budget(Clock()))
        owner.budget.uncertain_mutation = uncertain
        case = SimpleNamespace(state_path=Path('/synthetic/state'), entry={'index': 1, 'job_id': 'c' * 32,
                               'container_id': entry_id, 'submit_attempted': True, 'submit_confirmed': not uncertain})
        local = {'profile': {}, 'container_id': entry_id}
        obj = None if discovered is None else {'Id': discovered}
        calls = []
        def remove(*args, **kwargs):
            calls.append(('remove', local['container_id']))
            if remove_error: raise ValueError('unknown remove reply')
            return {'state': 'removed'}
        def inspect(_profile, argv, **kwargs):
            calls.append(('inspect_absence', argv[2]))
            self.assertEqual(argv, ['container', 'inspect', ID, '--format', '{{json .Id}}'])
            return None if absent else b'"still-present"'
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(batch.mod, 'state_lock', return_value=contextlib.nullcontext(Path('/synthetic/state'))))
            stack.enter_context(patch.object(batch.mod, 'checked_state', return_value=local))
            stack.enter_context(patch.object(batch.mod, 'inspect_container', return_value=obj))
            stack.enter_context(patch.object(batch.mod, 'save'))
            stack.enter_context(patch.object(batch.mod, 'operate', side_effect=remove))
            stack.enter_context(patch.object(batch.mod, 'docker', side_effect=inspect))
            try: outcome = owner.cleanup(case)
            except Exception as exc: outcome = exc
        return owner, outcome, calls

    def test_exact_id_cleanup_once_then_absence_confirmation(self):
        owner, result, calls = self.cleanup_fixture()
        self.assertTrue(result['verified']); self.assertEqual(calls, [('remove', ID), ('inspect_absence', ID)])

    def test_discovered_submit_identity_can_clean_but_never_resume_admission(self):
        owner, result, calls = self.cleanup_fixture(entry_id=None, uncertain=True)
        self.assertTrue(result['verified']); self.assertEqual(calls[0], ('remove', ID))
        with self.assertRaises(batch.BudgetExhausted): owner.budget.admit()

    def test_missing_or_changed_identity_never_causes_name_deletion(self):
        for discovered in (None, 'b' * 64):
            owner, result, calls = self.cleanup_fixture(discovered=discovered)
            self.assertEqual(calls, [])
            self.assertTrue(isinstance(result, Exception) or result['verified'] is False)

    def test_remove_uncertainty_and_absence_failure_never_retry(self):
        owner, result, calls = self.cleanup_fixture(remove_error=True)
        self.assertIsInstance(result, ValueError); self.assertEqual(calls, [('remove', ID)])
        self.assertTrue(owner.budget.uncertain_mutation)
        _, result, calls = self.cleanup_fixture(absent=False)
        self.assertIsInstance(result, RuntimeError); self.assertEqual(calls, [('remove', ID), ('inspect_absence', ID)])

    def test_journal_bounds_preserve_previous_records_and_summary_reserve(self):
        journal = batch.Journal(self.root / 'bounded.jsonl', io.StringIO())
        self.addCleanup(journal.close)
        journal.emit('first', {'outcome': 'failure-preserved'})
        before = journal.path.read_bytes()
        with self.assertRaises(batch.EvidenceError): journal.emit('oversized', {'value': 'x' * 65537})
        self.assertEqual(journal.path.read_bytes(), before)
        with self.assertRaises(batch.EvidenceError):
            for _ in range(100): journal.emit('bounded', {'value': 'x' * 60000})
        journal.emit('summary', {'classification': 'failed_or_incomplete'}, final=True)
        raw = journal.path.read_bytes()
        self.assertLessEqual(len(raw), batch.REPORT_BYTES)
        self.assertLessEqual(max(len(line) + 1 for line in raw.splitlines()), batch.RECORD_BYTES)
        self.assertEqual(json.loads(raw.splitlines()[0])['outcome'], 'failure-preserved')
        with self.assertRaises(FileExistsError): batch.Journal(journal.path, io.StringIO())
        self.assertTrue(batch.error_record('x' * 5000)['truncated'])

    def test_cli_has_no_count_or_budget_enlargement_options(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            batch.main(['--docker', '/no', '--context', 'x', '--image-id', 'sha256:' + 'b' * 64,
                        '--report', str(self.root / 'never-created'), '--count', '9'])
        self.assertFalse((self.root / 'never-created').exists())

    def test_record_count_cap_keeps_final_summary_slot(self):
        journal = batch.Journal(self.root / 'count.jsonl', io.StringIO())
        self.addCleanup(journal.close)
        for _ in range(batch.MAX_RECORDS - 1): journal.emit('small', {})
        with self.assertRaises(batch.EvidenceError): journal.emit('too-many', {})
        journal.emit('summary', {'classification': 'failed_or_incomplete'}, final=True)
        self.assertEqual(journal.records, batch.MAX_RECORDS)

    def test_evidence_refusal_keeps_primary_failure_identity_in_reserved_summary(self):
        code, records, owner = self.run_fake({1: 'assertion'}, evidence_failure=True)
        self.assertEqual(code, 1); self.assertEqual(len(owner.completed), 1)
        pending = records[-1]['unwritten_sample']
        self.assertEqual(pending['job_id'], format(1, '032x'))
        self.assertEqual(pending['container_id'], format(1, '064x'))
        self.assertIn('primary fixture failure', pending['primary_failure']['errors'][0]['text'])
        self.assertEqual(records[-1]['failure']['kind'], 'EvidenceError')

    def test_reused_real_cpu_method_retains_observer_hook_and_swallowed_budget(self):
        for final_budget in (False, True):
            with self.subTest(final_budget=final_budget):
                state = self.root / ('real-method-' + str(final_budget)); state.mkdir()
                local = {'container_id': ID, 'container_name': 'owned-synthetic',
                         'manifest': {'job_id': 'c' * 32, 'resources': {'cpu_millis': 250}},
                         'binding': {'manifest_sha256': 'd' * 64, 'supervisor_sha256': 'e' * 64},
                         'profile': {'docker_executable': '/never-run-docker', 'context': 'synthetic'}}
                (state / 'state.json').write_text(json.dumps(local))
                journal = batch.Journal(self.root / ('real-method-' + str(final_budget) + '.jsonl'), io.StringIO())
                self.addCleanup(journal.close)
                owner = batch.Batch(self.config, journal, batch.Budget(Clock()))
                obj = {'Id': ID, 'State': {'Running': True}}
                count = [0]
                def snapshot(_state):
                    count[0] += 1
                    if final_budget and count[0] == 2:
                        owner.budget.refuse('real final snapshot exhausted')
                    return local, obj
                live = MagicMock(); live.finish.return_value = {'cleanup_verified': True}
                dest = MagicMock(); dest.__truediv__.return_value.read_text.return_value = '{"cpu_seconds":0.6}'
                terminal = {'state': 'succeeded', 'effective_limits': {'cpu_millis': 250},
                            'cgroup_counters': {'cpu.stat': {'nr_throttled': '1'}}}
                with patch.object(batch.integration.LinuxActual, 'job', return_value=state), \
                        patch.object(batch.mod, 'operate', return_value={'state': 'submitted', 'container_id': ID}) as submit, \
                        patch.object(batch.integration.LinuxActual, 'observer_snapshot', side_effect=snapshot), \
                        patch.object(batch.integration.LinuxActual, 'terminal', return_value=terminal), \
                        patch.object(batch.integration.LinuxActual, 'collected', return_value=({}, dest)), \
                        patch.object(batch.integration, 'LiveObserver', return_value=live), \
                        patch.object(owner, 'cleanup', return_value={'verified': True}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    good = owner.sample(1)
                records = [json.loads(x) for x in journal.path.read_text().splitlines()]
                sample = records[-1]
                self.assertEqual(good, not final_budget); self.assertEqual(submit.call_count, 1)
                self.assertEqual(sample['terminal_result'], terminal)
                self.assertTrue(sample['supervisor_diagnostic']['attachment']['cleanup_verified'])
                if final_budget:
                    self.assertTrue(sample['budget_exhausted'])
                    self.assertEqual(sample['supervisor_diagnostic']['final_inspect_unavailable'], 'real final snapshot exhausted')


def load_tests(loader, _tests, _pattern):
    # FakeCPU inherits the real acceptance fixture but must never be discovered
    # as a runnable suite: these controls explicitly substitute its run method.
    return loader.loadTestsFromTestCase(BatchContracts)


if __name__ == '__main__':
    unittest.main(verbosity=2)
