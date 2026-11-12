#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable fault protocol controls; never invokes run/run_bound or native jobs."""
import ast
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import linux_checks as base

mod = base.mod
sup = mod.fault_protocol()
ID = 'c' * 64


class Clock:
    def __init__(self): self.value = 0.0
    def now(self): return self.value
    def sleep(self, amount): self.value += amount


class FaultContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rw-fault-offline-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        for obj, key in [(sup, 'run'), (sup, 'run_bound'), (sup, 'stop_namespace'), (sup.os, 'kill'),
                         (sup.os, 'killpg'), (subprocess, 'Popen'), (mod, 'docker')]:
            self.stack.enter_context(patch.object(obj, key, side_effect=AssertionError('No native action: ' + key), create=True))
        self.m = base.manifest(); self.p = base.profile()
        self.path = self.root / 'state'
        mod.save(self.root / 'manifest.json', self.m, True)
        with patch.object(mod, 'inspect_engine', return_value={'id': 'engine-control', 'architecture': 'amd64'}), \
                patch.object(mod, 'inspect_image', return_value={'architecture': 'amd64'}):
            mod.prepare(self.p, self.root / 'manifest.json', self.path, True)
        self.state = mod.read_json(self.path / 'state.json'); self.state['container_id'] = ID
        mod.save(self.path / 'state.json', self.state)

    def capsule(self, **change):
        return {'schema_version': 1, 'kind': 'supervisor_fault', 'job_id': self.m['job_id'], **self.state['binding'],
                'primary': sup.error_detail(OSError(5, 'synthetic primary'), 'receipt_publish'), 'secondary': None,
                'termination_basis': 'namespace_cleanup_confirmed', 'intended_exit_code': 2,
                'observed_at': 100.0, 'expires_at': 105.0, **change}

    def context(self, **change):
        return {'phase': 'receipt_publish', 'launch_attempted': True, 'cleanup_attempted': True,
                'cleanup_confirmed': True, 'retention_deadline': None, 'primary': None, **change}

    def retain(self, context=None, *, failure=None, sleep_failure=False):
        context = context or self.context(); clock = Clock(); published = []
        control = MagicMock(); control.lstat.return_value = type('Stat', (), {'st_mode': stat.S_IFDIR | 0o700, 'st_uid': 0})()
        control.__truediv__.return_value.exists.return_value = False
        control.__truediv__.return_value.is_symlink.return_value = False
        def publish(path, packet):
            if failure: raise failure
            published.append(copy.deepcopy(packet))
        with patch.object(sup.sys, 'platform', 'linux'), patch.object(sup.os, 'getpid', return_value=1), \
                patch.object(sup.os, 'getuid', return_value=0, create=True), patch.object(sup, 'CONTROL', control), \
                patch.object(sup, 'atomic', side_effect=publish), patch.object(sup.time, 'monotonic', clock.now), \
                patch.object(sup.time, 'time', return_value=100.0), \
                patch.object(sup.time, 'sleep', side_effect=OSError('retention fault') if sleep_failure else clock.sleep) as sleep, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = sup.retain_fault(self.m, self.state['binding'], context, OSError(5, 'primary fault'))
        return code, published, clock.value, sleep.call_count, stderr.getvalue()

    def test_exact_packet_and_normal_task_terminal_compatibility(self):
        packet = self.capsule(); self.assertEqual(sup.validate_fault(packet, self.m, self.state['binding']), packet)
        self.assertEqual(mod.TERMINAL, {'succeeded', 'failed', 'timed_out', 'cancelled'})
        self.assertEqual(sup.TERMINAL, mod.TERMINAL)
        self.assertLessEqual(len(sup.canonical(packet)), 4096)

    def test_multibyte_and_broken_exception_formatting_stays_byte_bounded(self):
        class Broken(Exception):
            def __str__(self): raise RuntimeError('broken formatter')
        for exc in (ValueError('\U0001f600' * 10000), Broken(), ValueError('\udfff' * 10000)):
            value = self.capsule(primary=sup.error_detail(exc, 'log_close'))
            self.assertLessEqual(len(value['primary']['message'].encode()), 1024)
            self.assertLessEqual(len(sup.canonical(value)), 4096)
            sup.validate_fault(value, self.m, self.state['binding'])

    def test_malformed_fields_binding_and_size_refused(self):
        changes = [{'schema_version': True}, {'kind': 'task_error'}, {'job_id': 'b' * 32}, {'nonce': 'd' * 32},
                   {'manifest_sha256': 'a' * 64}, {'supervisor_sha256': 'a' * 64}, {'extra': 1},
                   {'observed_at': float('nan')}, {'expires_at': 106.0}, {'intended_exit_code': True},
                   {'termination_basis': 'child_handle_missing'}, {'primary': None}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                sup.validate_fault(self.capsule(**change), self.m, self.state['binding'])
        for change in [{'phase': 'arbitrary'}, {'message': 'x' * 1025}, {'errno': True}, {'exception_type': 'x' * 129}]:
            packet = self.capsule(); packet['primary'].update(change)
            with self.assertRaises(ValueError): sup.validate_fault(packet, self.m, self.state['binding'])

    def test_invalid_manifest_and_binding_never_retained(self):
        for change in ({'job_id': 'invalid'}, {'outputs': ['../bad']}, {'required_device': 'cuda'}, {'argv': []}):
            manifest = {**self.m, **change}; binding = {**self.state['binding'], 'manifest_sha256': mod.digest(mod.canonical(manifest))}
            with self.assertRaises(ValueError): sup.fault_identity(manifest, binding)
        with self.assertRaises(ValueError): sup.fault_identity(self.m, {**self.state['binding'], 'nonce': 'bad'})

    def test_safe_retention_uses_one_original_deadline(self):
        code, packets, elapsed, _, _ = self.retain()
        self.assertEqual(code, 2); self.assertEqual(len(packets), 1); self.assertAlmostEqual(elapsed, 5)
        self.assertEqual(packets[0]['termination_basis'], 'namespace_cleanup_confirmed')
        ctx = self.context(retention_deadline=1.25)
        _, packets, elapsed, _, _ = self.retain(ctx)
        self.assertAlmostEqual(elapsed, 1.25); self.assertEqual(packets[0]['expires_at'], 101.25)
        ctx = self.context(launch_attempted=False, cleanup_attempted=False, cleanup_confirmed=False)
        _, packets, _, _, _ = self.retain(ctx)
        self.assertEqual(packets[0]['termination_basis'], 'never_launched')

    def test_attempted_launch_without_handle_or_cleanup_proof_never_sleeps(self):
        for context in (self.context(cleanup_attempted=False, cleanup_confirmed=False), self.context(cleanup_confirmed=False)):
            code, packets, elapsed, sleeps, text = self.retain(context)
            self.assertEqual((code, packets, elapsed, sleeps), (2, [], 0, 0)); self.assertIn('primary fault', text)
            sup.stop_namespace.assert_not_called()
        tree = ast.parse((base.SCRIPTS / 'linux_supervisor.py').read_text())
        body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_bound')
        assignments = [n for n in ast.walk(body) if isinstance(n, ast.Assign)]
        attempted = next(n.lineno for n in assignments if "context['launch_attempted']" in ast.unparse(n.targets[0]))
        popen = next(n.lineno for n in assignments if isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == 'subprocess.Popen')
        self.assertLess(attempted, popen)

    def test_publication_and_retention_errors_keep_primary_and_do_not_reset(self):
        code, packets, elapsed, sleeps, text = self.retain(failure=OSError('synthetic publish failure'))
        self.assertEqual((code, packets, elapsed, sleeps), (2, [], 0, 0))
        self.assertIn('primary fault', text); self.assertIn('publish failure', text)
        code, packets, elapsed, sleeps, text = self.retain(sleep_failure=True)
        self.assertEqual(code, 2); self.assertEqual(len(packets), 1); self.assertEqual(sleeps, 1)
        self.assertIn('retention fault', text)

    def test_first_valid_cache_is_immutable_and_repeat_is_identical(self):
        packet = self.capsule(); result = mod.cache_fault(self.path, self.state, packet)
        self.assertEqual(result['state'], 'artifacts_unavailable'); self.assertTrue(result['fault_cached'])
        original = (self.path / 'state.json').read_bytes()
        repeated = mod.cache_fault(self.path, self.state, copy.deepcopy(packet))
        self.assertEqual(repeated['fault_observation'], 'current_remote_identical_to_cached')
        self.assertEqual((self.path / 'state.json').read_bytes(), original)
        changed = self.capsule(); changed['primary']['message'] = 'contradiction'
        with self.assertRaises(ValueError): mod.cache_fault(self.path, self.state, changed)
        self.assertEqual((self.path / 'state.json').read_bytes(), original)

    def test_remote_primary_survives_local_cache_save_failure(self):
        with patch.object(mod, 'save', side_effect=OSError('synthetic disk full')):
            result = mod.cache_fault(self.path, self.state, self.capsule())
        self.assertFalse(result['fault_cached']); self.assertEqual(result['supervisor_fault'], self.capsule())
        self.assertIn('disk full', result['fault_cache_error']['message'])
        self.assertNotIn('supervisor_fault_cache', self.state)

    def test_cache_survives_fresh_load_and_stopped_or_missing_container(self):
        mod.cache_fault(self.path, self.state, self.capsule())
        for obj in (None, {'Id': ID, 'State': {'Running': False, 'ExitCode': 2, 'OOMKilled': False}}):
            state = mod.read_json(self.path / 'state.json')
            with patch.object(mod, 'inspect_container', return_value=obj), patch.object(mod, 'receipt') as receipt:
                result = mod.reconcile(self.path, state)
            self.assertEqual(result['supervisor_fault'], self.capsule()); receipt.assert_not_called()
            self.assertIn('historical_cached', result['fault_observation'])

    def test_bad_cache_identity_and_contradictory_remote_cannot_overwrite(self):
        mod.cache_fault(self.path, self.state, self.capsule()); original = (self.path / 'state.json').read_bytes()
        for key in ('container_id', 'container_name', 'engine_id', 'image_id'):
            envelope = copy.deepcopy(self.state['supervisor_fault_cache']); envelope[key] = 'different'
            with self.assertRaises(ValueError): mod.validate_fault_cache(self.state, envelope)
        with patch.object(mod, 'inspect_container', return_value={'Id': ID, 'State': {'Running': True}}), \
                patch.object(mod, 'receipt', return_value={'state': 'succeeded'}):
            with self.assertRaises(ValueError): mod.reconcile(self.path, self.state)
        self.assertEqual((self.path / 'state.json').read_bytes(), original)

    def test_fault_rpc_is_explicit_bounded_and_never_arbitrary_stderr(self):
        packet = {'schema_version': 1, 'job_id': self.m['job_id'], 'nonce': self.state['binding']['nonce'],
                  'manifest_sha256': self.state['binding']['manifest_sha256'], 'state': 'artifacts_unavailable', 'supervisor_fault': self.capsule()}
        with patch.object(mod, 'docker', return_value=mod.canonical(packet)):
            self.assertEqual(mod.receipt(self.state, 'status'), packet)
            with self.assertRaises(ValueError): mod.receipt(self.state, 'collect')
        for raw in (b'{"error":"arbitrary exec error"}', b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}'):
            with patch.object(mod, 'docker', return_value=raw), self.assertRaises(ValueError): mod.receipt(self.state, 'status')

    def test_direct_collect_checkpoint_and_client_collect_cannot_collect_fault(self):
        with patch.object(sup, 'checked_binding', return_value=(self.m, self.state['binding'])), \
                patch.object(sup, 'read_fault', return_value=self.capsule()):
            with self.assertRaises(ValueError): sup.report(True)
            with self.assertRaises(ValueError): sup.checkpoint()
        mod.cache_fault(self.path, self.state, self.capsule())
        with patch.object(mod, 'inspect_engine'), patch.object(mod, 'inspect_container', return_value=None):
            result = mod.operate('collect', self.path, destination=self.root / 'never-created')
        self.assertFalse(result['collected']); self.assertFalse((self.root / 'never-created').exists())

    def test_readonly_rpc_exception_cannot_publish_pid1_fault(self):
        with patch.object(sys, 'argv', ['supervisor', 'status']), patch.object(sup, 'report', side_effect=ValueError('RPC only')), \
                patch.object(sup, 'atomic') as publish, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sup.main(), 2)
        publish.assert_not_called(); sup.run.assert_not_called()

    def test_null_cache_is_corruption_not_permission_to_replace(self):
        self.state['supervisor_fault_cache'] = None
        original = (self.path / 'state.json').read_bytes()
        with self.assertRaises(ValueError): mod.cache_fault(self.path, self.state, self.capsule())
        with patch.object(mod, 'inspect_container', return_value=None), self.assertRaises(ValueError):
            mod.reconcile(self.path, self.state)
        self.assertEqual((self.path / 'state.json').read_bytes(), original)

    def test_stderr_escaping_and_retention_fault_have_absolute_bounds(self):
        detail = sup.error_detail(ValueError('\x01' * 10000), 'retention')
        with contextlib.redirect_stderr(io.StringIO()) as output:
            sup.emit_fault_error(detail, detail)
        self.assertLessEqual(len(output.getvalue().encode()), 4096)
        json.loads(output.getvalue())
        code, packets, elapsed, sleeps, _ = self.retain(self.context(phase='retention', retention_deadline=5))
        self.assertEqual((code, elapsed, sleeps), (2, 0, 0)); self.assertEqual(len(packets), 1)

    def test_schema_two_binding_remains_compatible(self):
        manifest = {**self.m, 'schema_version': 2, 'checkpoint': {'directory': 'checkpoints', 'max_bytes': 4096, 'max_files': 2}}
        mod.validate_manifest(manifest)
        binding = {**self.state['binding'], 'manifest_sha256': mod.digest(mod.canonical(manifest))}
        sup.fault_identity(manifest, binding)
        packet = {**self.capsule(), **binding}
        self.assertEqual(sup.validate_fault(packet, manifest, binding), packet)

    def test_native_injections_change_only_one_declared_source_anchor(self):
        import linux_fault_integration_checks as native
        raw = (base.SCRIPTS / 'linux_supervisor.py').read_bytes()
        for kind in native.CASES:
            changed, receipt = native.injected_source(raw, kind)
            self.assertEqual(changed.replace(receipt['after'].encode(), receipt['before'].encode(), 1), raw)
            self.assertEqual(receipt['replacements'], 1); self.assertEqual(receipt['production_sha256'], mod.digest(raw))
            ast.parse(changed)
        with self.assertRaises(ValueError): native.injected_source(raw + raw, 'safe_after_cleanup')
        with self.assertRaises(ValueError): native.injected_source(raw, 'unreviewed_case')

    def test_native_expiry_requires_full_retention_window(self):
        import linux_fault_integration_checks as native
        packet = {'observed_at': 100.0, 'expires_at': 130.0}
        native.check_retention_window(packet, 130.001)
        for candidate, finished in [(packet, 101.0), (packet, 129.98), (packet, 132.001),
                                    ({'observed_at': 100.0, 'expires_at': 101.0}, 101.0)]:
            with self.assertRaises(AssertionError): native.check_retention_window(candidate, finished)


if __name__ == '__main__':
    unittest.main(verbosity=2)
