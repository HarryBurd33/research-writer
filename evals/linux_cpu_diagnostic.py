#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit single CPU diagnostic batch; eight green fixtures mean not reproduced."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
import uuid

import linux_integration_checks as integration
from linux_observer import bounded_text

mod = integration.mod
MAX_SAMPLES = 8
WORK_SECONDS = 150
CLEANUP_SECONDS = 175
TOTAL_SECONDS = 180
OBSERVER_FINISH_SECONDS = 6
RPC_TAIL_SECONDS = 15
ADMISSION_SECONDS = 25
RECORD_BYTES = 128 * 1024
REPORT_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 48


class BudgetExhausted(RuntimeError):
    """Intentionally not ValueError: terminal() must not retry this exception."""


class EvidenceError(RuntimeError):
    pass


def error_record(value):
    raw = str(value).encode('utf-8', errors='replace')
    return {'text': bounded_text(value, 4096), 'truncated': len(raw) > 4096}


class Budget:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()  # Before report setup, engine/image inspection or staging.
        self.phase = 'work'
        self.exhausted = False
        self.clamped_calls = 0
        self.uncertain_mutation = False

    def elapsed(self):
        return self.clock() - self.started

    def refuse(self, reason):
        self.exhausted = True
        raise BudgetExhausted(reason)

    def admit(self):
        if self.exhausted or self.uncertain_mutation:
            self.refuse('Batch stopped permanently after exhausted budget or uncertain mutation')
        if WORK_SECONDS - self.elapsed() < ADMISSION_SECONDS:
            self.refuse('Fewer than 25 work seconds remain; no fresh fixture admitted')

    def rpc(self, runner, argv, timeout=30, maximum=mod.MAX_RPC):
        end = CLEANUP_SECONDS if self.phase == 'cleanup' else WORK_SECONDS - OBSERVER_FINISH_SECONDS
        available = end - self.elapsed() - RPC_TAIL_SECONDS
        if available <= 0:
            self.refuse('No Docker reply allowance remains in ' + self.phase + ' phase')
        wait = min(timeout, available)
        if wait < timeout:
            self.clamped_calls += 1
        mutation = len(argv) > 3 and argv[3] in ('run', 'rm')
        try:
            return runner(argv, timeout=wait, maximum=maximum)
        except BaseException:
            if mutation:
                self.uncertain_mutation = True
            raise

    @contextmanager
    def transport(self):
        original = mod.bounded_run
        mod.bounded_run = lambda argv, timeout=30, maximum=mod.MAX_RPC: self.rpc(original, argv, timeout, maximum)
        try:
            yield
        finally:
            mod.bounded_run = original


def _check_payload(value, remaining):
    remaining[0] -= 1
    if remaining[0] < 0:
        raise EvidenceError('Evidence object count limit')
    if isinstance(value, str):
        if len(value) > 65536 or len(value.encode('utf-8')) > 65536:
            raise EvidenceError('Evidence text field limit')
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise EvidenceError('Evidence key limit')
            _check_payload(item, remaining)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_payload(item, remaining)
    elif value is not None and type(value) not in (bool, int, float):
        raise EvidenceError('Unsupported evidence value')


class Journal:
    def __init__(self, path, output=None):
        self.path = Path(path).absolute()
        self.stream = self.path.open('x', encoding='utf-8')
        self.output = output if output is not None else sys.stdout
        self.bytes = 0
        self.records = 0

    def emit(self, kind, value, *, final=False):
        record = {'record': kind, **value}
        _check_payload(record, [8192])
        raw = bytearray()
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(record):
            part = chunk.encode('utf-8')
            if len(raw) + len(part) + 1 > RECORD_BYTES:
                raise EvidenceError('Evidence record byte limit')
            raw.extend(part)
        raw.extend(b'\n')
        reserve = 0 if final else RECORD_BYTES
        if self.records >= MAX_RECORDS - (0 if final else 1) or self.bytes + len(raw) + reserve > REPORT_BYTES:
            raise EvidenceError('Evidence aggregate limit; previous records preserved')
        line = raw.decode('utf-8')
        self.stream.write(line); self.stream.flush(); os.fsync(self.stream.fileno())
        self.bytes += len(raw); self.records += 1
        self.output.write(line); self.output.flush()

    def close(self):
        self.stream.close()


class DiagnosticCPU(integration.LinuxActual):
    def job(self, code, resources=None, inputs=None, outputs=None, submit=True):
        state = super().job(code, resources, inputs, outputs, submit=False)
        self.state_path = state
        local = mod.read_json(state / 'state.json')
        self.entry.update(state_path=str(state), job_id=local['manifest']['job_id'],
                          manifest_sha256=local['binding']['manifest_sha256'],
                          container_name=local['container_name'], resources=local['manifest']['resources'])
        identity = self.entry['job_id']
        if identity in self.owner.seen_jobs:
            raise RuntimeError('Duplicate diagnostic job identity refused before submit')
        self.owner.seen_jobs.add(identity)
        self.owner.journal.emit('fixture_prepared', dict(self.entry))  # fsynced before submit mutation.
        if submit:
            self.entry['submit_attempted'] = True
            try:
                result = mod.operate('submit', state, allow_execute=True)
                self.assertEqual(result['state'], 'submitted')
                identifier = result['container_id']
                if not re.fullmatch('[0-9a-f]{64}', identifier) or identifier in self.owner.seen_containers:
                    raise RuntimeError('Invalid or duplicate immutable container ID')
                self.owner.seen_containers.add(identifier)
                self.entry.update(container_id=identifier, submit_confirmed=True)
                self.owner.journal.emit('fixture_submitted', dict(self.entry))
            except BaseException:
                self.owner.budget.uncertain_mutation = True
                raise
        return state

    def terminal(self, state, timeout=18, chronology=None):
        result = super().terminal(state, timeout, chronology)
        self.terminal_result = result
        return result

    def emit_supervisor_diagnostic(self, diagnostic):
        self.diagnostic = diagnostic
        super().emit_supervisor_diagnostic(diagnostic)


class Batch:
    def __init__(self, config, journal, budget):
        self.config, self.journal, self.budget = config, journal, budget
        self.seen_jobs, self.seen_containers = set(), set()
        self.completed = []
        self.unwritten_sample = None
        self.root = journal.path.parent / ('rw-cpu-diagnostic-' + uuid.uuid4().hex)
        self.case_class = DiagnosticCPU

    def setup(self):
        if sys.platform != 'linux':
            raise RuntimeError('Actual Linux runner required; no passing skip')
        self.root.mkdir(mode=0o700)  # No TemporaryDirectory finalizer: unresolved state survives.
        p = mod.profile({'schema_version': 1, 'docker_executable': self.config.docker,
                         'context': self.config.context, 'expected_engine_id': None,
                         'container_python': '/usr/local/bin/python'})
        info = mod.inspect_engine(p); p['expected_engine_id'] = info['id']
        mod.inspect_image(p, self.config.image_id)
        integration.CONFIG = self.config
        self.case_class.p, self.case_class.root, self.case_class.states = p, self.root, []
        self.journal.emit('engine', {'engine': info, 'image_id': self.config.image_id})

    def cleanup(self, case):
        state_path = case.state_path
        if state_path is None:
            return {'verified': True, 'container_created': False}
        with mod.state_lock(state_path) as root:
            local = mod.checked_state(root)
            obj = mod.inspect_container(local)  # May discover by bound name; full production validation.
            if obj is None:
                return {'verified': not case.entry.get('submit_attempted', False),
                        'absent_at_inspect': True, 'unknown_submit': not case.entry.get('submit_confirmed', False)}
            identifier = obj['Id']
            if not re.fullmatch('[0-9a-f]{64}', identifier):
                raise RuntimeError('Cleanup needs immutable ID')
            if case.entry.get('container_id') not in (None, identifier):
                raise RuntimeError('Cleanup identity differs from submitted fixture')
            local['container_id'] = identifier
            mod.save(root / 'state.json', local)
            case.entry['container_id'] = identifier
        self.journal.emit('cleanup_target', {'index': case.entry['index'], 'container_id': identifier,
                                             'job_id': case.entry['job_id']})
        try:
            removed = mod.operate('cleanup', state_path, allow_remove=True)  # Deletes validated obj['Id'] only.
            if removed.get('state') != 'removed':
                raise RuntimeError('Cleanup acknowledgement missing')
        except BaseException:
            self.budget.uncertain_mutation = True
            raise  # Never retry an uncertain remove, even if later reconciliation could find absence.
        raw = mod.docker(local['profile'], ['container', 'inspect', identifier, '--format', '{{json .Id}}'], allow_missing=True)
        if raw is not None:
            raise RuntimeError('Exact container ID still present after cleanup')
        return {'verified': True, 'container_id': identifier, 'removed_acknowledged': True, 'absent_after_remove': True}

    def sample(self, index):
        case = self.case_class('test_02_actual_cpu_throttling_rate')
        case.owner = self
        case.entry = {'index': index, 'started_elapsed': round(self.budget.elapsed(), 6),
                      'submit_attempted': False, 'submit_confirmed': False}
        case.state_path = None; case.diagnostic = None; case.terminal_result = None
        self.journal.emit('fixture_admitted', dict(case.entry))
        result = unittest.TestResult()
        primary = None
        try:
            case.run(result)  # Direct run intentionally does not invoke class setup/teardown.
            if not result.wasSuccessful() or result.testsRun != 1 or result.skipped:
                primary = {'kind': 'acceptance_failed', 'errors':
                           [error_record(message) for _, message in (result.failures + result.errors)[:2]],
                           'tests_run': result.testsRun, 'skipped': bool(result.skipped)}
        except BaseException as exc:
            primary = {'kind': type(exc).__name__, 'errors': [error_record(exc)]}
            raise
        finally:
            if self.budget.elapsed() >= WORK_SECONDS:
                self.budget.exhausted = True
                if primary is None:
                    primary = {'kind': 'BudgetExhausted', 'errors': [error_record('Work and observer cleanup exceeded 150 seconds')]}
            self.budget.phase = 'cleanup'
            try:
                cleanup = self.cleanup(case)
            except Exception as exc:
                cleanup = {'verified': False, 'error': error_record(type(exc).__name__ + ': ' + str(exc))}
            finally:
                self.budget.phase = 'work'
            observer_ok = isinstance(case.diagnostic, dict) and case.diagnostic.get('attachment', {}).get('cleanup_verified') is True
            good = (primary is None and observer_ok and cleanup.get('verified') is True
                    and not self.budget.exhausted and not self.budget.uncertain_mutation)
            record = {**case.entry, 'elapsed': round(self.budget.elapsed(), 6), 'accepted': good,
                      'primary_failure': primary, 'observer_cleanup_verified': observer_ok,
                      'terminal_result': case.terminal_result, 'supervisor_diagnostic': case.diagnostic,
                      'container_cleanup': cleanup, 'budget_exhausted': self.budget.exhausted,
                      'uncertain_mutation': self.budget.uncertain_mutation,
                      'rpc_clamp_count': self.budget.clamped_calls}
            self.completed.append({'index': index, 'accepted': good, 'job_id': case.entry.get('job_id')})
            self.unwritten_sample = {'index': index, 'job_id': case.entry.get('job_id'),
                                     'container_id': case.entry.get('container_id'), 'accepted': False,
                                     'primary_failure': primary, 'container_cleanup': cleanup,
                                     'full_record_unavailable': 'Evidence emission failed; existing records retained'}
            self.journal.emit('fixture_result', record)
            self.unwritten_sample = None
        return good

    def run(self):
        failure = None
        with self.budget.transport():
            try:
                pins = {}
                for path in [Path(__file__), Path(integration.__file__), Path(__file__).with_name('linux_observer.py'),
                             integration.SCRIPTS / 'linux_tools.py', integration.SCRIPTS / 'linux_supervisor.py']:
                    pins[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                commit = os.environ.get('GITHUB_SHA', '')
                self.journal.emit('batch', {'batch_id': self.root.name, 'planned_samples': MAX_SAMPLES,
                    'source_sha256': pins, 'ci_commit': commit if re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', commit) else None,
                    'image_id': self.config.image_id, 'state_root': str(self.root),
                    'limits': {'work_seconds': WORK_SECONDS, 'work_rpc_seconds': WORK_SECONDS - OBSERVER_FINISH_SECONDS,
                               'cleanup_seconds': CLEANUP_SECONDS, 'outer_seconds': TOTAL_SECONDS,
                               'record_bytes': RECORD_BYTES, 'report_bytes': REPORT_BYTES, 'record_count': MAX_RECORDS}})
                self.setup()
                for index in range(1, MAX_SAMPLES + 1):
                    self.budget.admit()
                    if not self.sample(index):
                        break
            except Exception as exc:
                failure = {'kind': type(exc).__name__, 'error': error_record(exc)}
            finally:
                accepted = (failure is None and len(self.completed) == MAX_SAMPLES
                            and all(item['accepted'] for item in self.completed)
                            and not self.budget.exhausted and not self.budget.uncertain_mutation
                            and self.budget.elapsed() < TOTAL_SECONDS)
                summary = {'classification': 'not_reproduced_in_8' if accepted else 'failed_or_incomplete',
                           'samples': self.completed, 'failure': failure, 'elapsed': round(self.budget.elapsed(), 6),
                           'budget_exhausted': self.budget.exhausted, 'rpc_clamp_count': self.budget.clamped_calls,
                           'uncertain_mutation': self.budget.uncertain_mutation, 'state_retained_at': str(self.root),
                           'unwritten_sample': self.unwritten_sample,
                           'historical_exit_2_resolved': False}
                self.journal.emit('summary', summary, final=True)
        return 0 if accepted else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--report', required=True, help='New bounded synthetic JSONL file; never overwritten')
    config = parser.parse_args(argv)
    budget = Budget()
    journal = None
    try:
        journal = Journal(config.report)
        return Batch(config, journal, budget).run()
    except Exception as exc:
        print(json.dumps({'diagnostic_error': bounded_text(type(exc).__name__ + ': ' + str(exc), 4096),
                          'classification': 'failed_or_incomplete'}), file=sys.stderr, flush=True)
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
