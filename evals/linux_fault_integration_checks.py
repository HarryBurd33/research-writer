#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit deterministic native PID1 fault controls; source copies only, two jobs once."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

import linux_integration_checks as integration
import linux_startup_diagnostic as bounds

mod = integration.mod
CASES = ('unsafe_cleanup', 'safe_after_cleanup')
SAFE_CODE = "import os;os.symlink('/etc/hosts','result.json')"
UNSAFE_CODE = "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);open('result.json','w').write('{}')"


def check_retention_window(capsule, finished):
    # 10ms covers wall-clock/serialized timestamp resolution, not early retention exit.
    if not 29.99 <= capsule['expires_at'] - capsule['observed_at'] <= 30:
        raise AssertionError('Fault capsule did not declare the original 30s retention window')
    if not capsule['expires_at'] - 0.01 <= finished <= capsule['expires_at'] + 2:
        raise AssertionError('Native exit did not preserve the original retention deadline')


def injected_source(raw, kind):
    if kind == 'unsafe_cleanup':
        before = b'\n        stop_namespace(child)\n'
        after = b"\n        raise RuntimeError('CI injected uncertain namespace cleanup')\n"
    elif kind == 'safe_after_cleanup':
        before = b"\n    result['cgroup_counters'] = counters()\n"
        after = b"\n    raise RuntimeError('CI injected fault after verified namespace cleanup')\n"
    else:
        raise ValueError('Unknown fixed native fault control')
    if raw.count(before) != 1:
        raise ValueError('Injection anchor must occur exactly once in pinned source')
    changed = raw.replace(before, after, 1)
    return changed, {'before': before.decode(), 'after': after.decode(), 'replacements': 1,
                     'production_sha256': bounds.sha(raw), 'injected_sha256': bounds.sha(changed)}


class NativeFaults(bounds.Batch):
    """Reuse accepted 60/54/80/90s budget, bounded journal and validated-ID cleanup."""
    def run_case(self, index, kind):
        entry = {'index': index, 'kind': kind, 'state_path': None, 'popen_attempted': False,
                 'inspections': [], 'inspections_truncated': False}
        self.current = entry
        primary = None; cleanup = None; observed = {}
        try:
            production = (integration.SCRIPTS / 'linux_supervisor.py').read_bytes()
            modified, injection = injected_source(production, kind)
            copied = self.root / ('source-' + kind); copied.mkdir(mode=0o700)
            source = copied / 'linux_supervisor.py'; source.write_bytes(modified); source.chmod(0o444)
            case = integration.LinuxActual('test_08_actual_unsafe_and_oversized_outputs')
            case.root, case.p, case.states = self.root, self.p, []
            # Only staging reads from the copy; production files are never modified.
            with patch.object(mod, 'ROOT', copied):
                state = case.job(UNSAFE_CODE if kind == 'unsafe_cleanup' else SAFE_CODE,
                                 {'memory_bytes': 128 * 1024**2}, submit=False)
            entry['state_path'] = str(state)
            local = mod.read_json(state / 'state.json')
            entry.update(job_id=local['manifest']['job_id'], container_name=local['container_name'],
                         binding=local['binding'], injection=injection, resources=local['manifest']['resources'])
            if local['binding']['supervisor_sha256'] != injection['injected_sha256']:
                raise AssertionError('Injected source binding mismatch')
            argv = [self.p['docker_executable'], '--context', self.p['context'], *mod.run_arguments(local)]
            self.emit('native_fixture_intent', {**entry, 'original_detached_argv': argv, 'argv_sha256': bounds.sha(mod.canonical(argv))})
            self.budget.launch()
            entry['popen_attempted'] = True; began = time.monotonic()
            try:
                reply = mod.operate('submit', state, allow_execute=True)
            except BaseException:
                self.budget.uncertain = True
                raise
            entry['container_id'] = reply['container_id']
            case.assertEqual(reply['state'], 'submitted')
            obj = self.inspect(mod.read_json(state / 'state.json'), entry, 'native_start')
            case.assertTrue(bounds.start_proof(obj))
            terminal = case.terminal(state)
            observed['first_result'] = terminal
            case.assertEqual(terminal['state'], 'artifacts_unavailable')
            if kind == 'unsafe_cleanup':
                case.assertNotIn('supervisor_fault', terminal)
                case.assertEqual(terminal['container_exit_code'], 2)
                case.assertFalse(terminal['oom_killed'])
                case.assertLess(time.monotonic() - began, 15)  # Must not spend the 30s retention interval.
                case.assertNotIn('supervisor_fault_cache', mod.read_json(state / 'state.json'))
            else:
                capsule = terminal['supervisor_fault']
                case.assertEqual(capsule['primary']['phase'], 'counters')
                case.assertEqual(capsule['termination_basis'], 'namespace_cleanup_confirmed')
                case.assertEqual(capsule['supervisor_sha256'], injection['injected_sha256'])
                case.assertTrue(terminal['fault_cached'])
                saved = mod.read_json(state / 'state.json')
                case.assertEqual(saved['supervisor_fault_cache']['capsule'], capsule)
                destination = state.parent / 'forbidden-collection'
                refused = mod.operate('collect', state, destination=destination)
                case.assertFalse(refused['collected']); case.assertFalse(destination.exists())
                for operation in ('collect', 'checkpoint'):
                    with case.assertRaisesRegex(ValueError, 'Supervisor fault cannot'):
                        mod.docker(self.p, ['exec', '--user', '0:0', entry['container_id'], self.p['container_python'],
                                            '/runner/linux_supervisor.py', operation])
                repeated = mod.operate('submit', state, allow_execute=True)
                case.assertFalse(repeated['reexecuted']); case.assertEqual(repeated['supervisor_fault'], capsule)
                # One original 30s retention window, never renewed by repeated reads.
                while True:
                    saved = mod.read_json(state / 'state.json')
                    obj = mod.inspect_container(saved)
                    if not obj['State']['Running']:
                        break
                    time.sleep(0.15)
                case.assertEqual(obj['State']['ExitCode'], 2); case.assertFalse(obj['State']['OOMKilled'])
                spec = importlib.util.spec_from_file_location('fresh_fault_native_client', integration.SCRIPTS / 'linux_tools.py')
                fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
                fresh.bounded_run = mod.bounded_run  # Preserve the same absolute per-RPC deadline adapter.
                recovered = fresh.operate('recover', state)
                case.assertEqual(recovered['supervisor_fault'], capsule)
                case.assertEqual(recovered['fault_observation'], 'historical_cached_container_stopped')
                observed.update(after_expiry=recovered, stopped_state=bounds.container_state(obj['State']),
                                capsule_lifetime_seconds=capsule['expires_at'] - capsule['observed_at'])
                finished = datetime.fromisoformat(obj['State']['FinishedAt'].replace('Z', '+00:00')).timestamp()
                check_retention_window(capsule, finished)
                observed['native_finish_minus_fault_expiry_seconds'] = finished - capsule['expires_at']
            observed['elapsed_seconds'] = time.monotonic() - began
        except BaseException as exc:
            primary = bounds.error(exc)
        finally:
            self.budget.phase = 'cleanup'
            try:
                cleanup = self.cleanup(entry)
            except Exception as exc:
                cleanup = {'verified': False, 'error': bounds.error(exc)}
            finally:
                self.budget.phase = 'work'
            good = primary is None and cleanup.get('verified') is True and not self.budget.exhausted and not self.budget.uncertain
            record = {**entry, 'observed': observed, 'primary_failure': primary, 'cleanup': cleanup, 'accepted': good}
            self.current = record
            self.completed.append({'kind': kind, 'accepted': good, 'job_id': entry.get('job_id')})
            self.emit('native_fixture_result', record); self.current = None
        return good

    def run(self):
        failure = None
        with self.budget.transport():
            try:
                pins = {p.name: bounds.sha(p.read_bytes()) for p in [Path(__file__), Path(__file__).with_name('linux_fault_checks.py'),
                    Path(bounds.__file__), Path(integration.__file__), Path(__file__).with_name('linux_observer.py'),
                    integration.SCRIPTS / 'linux_tools.py', integration.SCRIPTS / 'linux_supervisor.py']}
                self.emit('native_fault_batch', {'cases': list(CASES), 'source_sha256': pins, 'state_root': str(self.root),
                    'limits': {'work': 60, 'rpc': 54, 'cleanup': 80, 'total': 90},
                    'scope': 'deterministic source-copy injections; historical cause remains unknown'})
                self.setup()
                for index, kind in enumerate(CASES, 1):
                    self.budget.admit()
                    if not self.run_case(index, kind):
                        break
            except BaseException as exc:
                failure = bounds.error(exc)
            accepted = failure is None and len(self.completed) == 2 and all(x['accepted'] for x in self.completed)
            accepted = accepted and not self.budget.exhausted and not self.budget.uncertain and self.budget.elapsed() < 90
            self.journal.emit('summary', {'classification': 'deterministic_fault_controls_passed' if accepted else 'failed_or_incomplete',
                'samples': self.completed, 'failure': failure, 'unwritten_sample': self.current,
                'elapsed': self.budget.elapsed(), 'budget_exhausted': self.budget.exhausted,
                'uncertain_mutation': self.budget.uncertain, 'historical_exit_2_resolved': False}, final=True)
        return 0 if accepted else 1


def main(argv=None):
    budget = bounds.Budget()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-native', action='store_true', required=True)
    parser.add_argument('--docker', required=True); parser.add_argument('--context', required=True)
    parser.add_argument('--image-id', required=True); parser.add_argument('--report', required=True)
    config = parser.parse_args(argv)
    journal = bounds.Journal(config.report)
    try:
        return NativeFaults(config, journal, budget).run()
    finally:
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
