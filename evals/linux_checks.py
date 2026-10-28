#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable offline contract checks. These do not claim Linux runtime enforcement."""
from __future__ import annotations
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
spec = importlib.util.spec_from_file_location('rw_linux', SCRIPTS / 'linux_tools.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def manifest():
    return {'schema_version': 1, 'job_id': 'a' * 32, 'image_id': 'sha256:' + 'b' * 64,
            'argv': ['/usr/local/bin/python', '-c', 'pass'], 'inputs': [], 'outputs': ['out.txt'],
            'required_device': 'cpu', 'resources': {'wall_seconds': 3, 'retention_seconds': 5,
            'memory_bytes': 64 * 1024**2, 'cpu_millis': 250, 'pids': 32,
            'work_bytes': 2 * 1024**2, 'tmp_bytes': 1024**2,
            'max_log_bytes': 1024, 'max_output_bytes': 4096}}


def profile():
    return {'schema_version': 1, 'docker_executable': sys.executable, 'context': 'explicit-test',
            'expected_engine_id': 'engine-control', 'container_python': '/usr/local/bin/python'}


def fake_inspect(state):
    r = state['manifest']['resources']; runner, inputs = mod.staged_paths(state)
    mounts = [{'Type': 'bind', 'Destination': d, 'Source': str(s), 'RW': False}
              for s, d in [(runner, '/runner'), (inputs, '/inputs'),
                  *((runner / n, '/etc/' + n) for n in ('hosts', 'hostname', 'resolv.conf'))]]
    return {'Id': 'c' * 64, 'Name': '/' + state['container_name'], 'Image': state['manifest']['image_id'],
            'State': {'Running': True, 'ExitCode': 0, 'OOMKilled': False}, 'Mounts': mounts,
            'Config': {'User': '0:0', 'WorkingDir': '/work', 'Entrypoint': ['/usr/local/bin/python'],
                       'Cmd': ['/runner/linux_supervisor.py', 'run'], 'Labels': mod.labels(state),
                       'Volumes': None, 'Healthcheck': {'Test': ['NONE']}},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'IpcMode': 'private',
                'CgroupnsMode': 'private', 'Memory': r['memory_bytes'], 'MemorySwap': r['memory_bytes'],
                'PidsLimit': r['pids'], 'NanoCpus': r['cpu_millis'] * 1000000, 'ShmSize': 1024**2,
                'Privileged': False, 'PidMode': '', 'AutoRemove': False, 'Init': False,
                'RestartPolicy': {'Name': 'no'}, 'LogConfig': {'Type': 'none'},
                'CapDrop': ['ALL'], 'CapAdd': ['SETUID', 'SETGID', 'KILL', 'DAC_OVERRIDE'],
                'SecurityOpt': ['no-new-privileges'], 'Devices': None, 'DeviceRequests': None,
                'Tmpfs': {target: f'rw,nosuid,nodev,size={size},mode={mode},nr_inodes={128 if target == "/control" else 1024}'
                    for target, size, mode in [('/work', r['work_bytes'], '1777'),
                        ('/tmp', r['tmp_bytes'], '1777'), ('/control', 4 * 1024**2, '0700')]}}}


class LinuxContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rw-linux-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.m = manifest(); self.p = profile()
        self.manifest = self.root / 'manifest.json'; mod.save(self.manifest, self.m, True)
        self.state_dir = self.root / 'state'

    def prepared(self):
        with patch.object(mod, 'inspect_engine', return_value={'id': 'engine-control', 'architecture': 'amd64'}), patch.object(mod, 'inspect_image', return_value={'architecture': 'amd64'}):
            mod.prepare(self.p, self.manifest, self.state_dir, True)
        return mod.read_json(self.state_dir / 'state.json')

    def test_valid_schema(self):
        self.assertEqual(mod.validate_manifest(self.m), self.m)
        self.assertEqual(mod.profile(self.p), self.p)

    def test_reject_implicit_profile_and_secrets(self):
        for key, value in [('context', None), ('container_python', 'python'), ('password', 'bad')]:
            p = dict(self.p); p[key] = value
            with self.assertRaises(ValueError): mod.profile(p)

    def test_integer_resource_bounds(self):
        for name, (lo, hi) in mod.LIMITS.items():
            for value in (True, 0, hi + 1, 1.5):
                m = copy.deepcopy(self.m); m['resources'][name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError): mod.validate_manifest(m)

    def test_rounding_budget_rejected(self):
        for name in ('memory_bytes', 'work_bytes', 'tmp_bytes'):
            m = copy.deepcopy(self.m); m['resources'][name] += 1
            with self.assertRaises(ValueError): mod.validate_manifest(m)

    def test_image_tag_and_gpu_refused(self):
        for key, value in [('image_id', 'python:latest'), ('required_device', 'cuda')]:
            m = copy.deepcopy(self.m); m[key] = value
            with self.assertRaises(ValueError): mod.validate_manifest(m)

    def test_paths_and_generated_names_refused(self):
        for name in ('../escape', '/root', 'a//b', 'a/./b', 'C:/escape', 'a\\b', '.ssh/key', '.env', '.logs/stdout.log', 'x/.collection.json', '.collection.json/sub'):
            with self.subTest(name=name), self.assertRaises(ValueError): mod.relative(name)

    def test_input_output_parent_conflict(self):
        self.m['outputs'] = ['a', 'a/b']
        with self.assertRaises(ValueError): mod.validate_manifest(self.m)

    def test_duplicate_json_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError): mod.decode(raw)

    def test_staging_requires_pin_and_permission(self):
        with self.assertRaises(ValueError): mod.prepare(self.p, self.manifest, self.state_dir)
        self.p['expected_engine_id'] = None
        with self.assertRaises(ValueError): mod.prepare(self.p, self.manifest, self.state_dir, True)
        self.assertFalse(self.state_dir.exists())

    def test_prepare_no_execution_or_pull(self):
        state = self.prepared()
        self.assertFalse(state['submit_attempted']); self.assertIsNone(state['container_id'])
        args = mod.run_arguments(state)
        for value in ('--pull=never', '--read-only', '--network=none', '--log-driver=none', '--init=false'):
            self.assertIn(value, args)
        self.assertNotIn('--privileged', args)
        for value in [args[i + 1] for i, x in enumerate(args[:-1]) if x == '--mount']:
            self.assertTrue(value.endswith(',readonly'))

    def test_staging_input_hash_symlink_and_hardlink(self):
        source = self.root / 'in.txt'; source.write_bytes(b'input')
        m = copy.deepcopy(self.m); m['inputs'] = [{'source': 'in.txt', 'destination': 'data/input', 'sha256': '0' * 64}]
        mod.save(self.manifest, m)
        with patch.object(mod, 'inspect_engine', return_value={'architecture': 'amd64'}), patch.object(mod, 'inspect_image', return_value={'architecture': 'amd64'}), self.assertRaises(ValueError):
            mod.prepare(self.p, self.manifest, self.state_dir, True)
        if hasattr(os, 'link'):
            os.link(source, self.root / 'link')
            with self.assertRaises(ValueError): mod.regular(source)

    def test_engine_context_refuses_remote_and_rootless(self):
        with patch.object(mod, 'docker', return_value=b'"ssh://remote"'), self.assertRaises(ValueError): mod.inspect_engine(self.p)
        responses = [b'"unix:///docker.sock"', mod.canonical({'id': 'engine-control', 'os': 'linux', 'cgroup_version': '2', 'security_options': ['name=rootless']})]
        with patch.object(mod, 'docker', side_effect=responses), self.assertRaises(ValueError): mod.inspect_engine(self.p)

    def test_engine_identity_and_os_refused(self):
        for info in ({'id': 'other', 'os': 'linux', 'cgroup_version': '2'}, {'id': 'engine-control', 'os': 'windows', 'cgroup_version': '2'}, {'id': 'engine-control', 'os': 'linux', 'cgroup_version': '1'}):
            with patch.object(mod, 'docker', side_effect=[b'"unix:///docker.sock"', mod.canonical(info)]), self.assertRaises(ValueError): mod.inspect_engine(self.p)

    def test_image_volumes_refused(self):
        obj = {'id': self.m['image_id'], 'os': 'linux', 'volumes': {'/data': {}}}
        with patch.object(mod, 'docker', return_value=mod.canonical(obj)), self.assertRaises(ValueError): mod.inspect_image(self.p, self.m['image_id'])

    def test_effective_config_changes_refused(self):
        state = self.prepared(); obj = fake_inspect(state)
        self.assertEqual(mod.check_container(state, obj), obj)
        for field, value in [('Memory', 0), ('MemorySwap', -1), ('PidsLimit', 0), ('ReadonlyRootfs', False), ('NetworkMode', 'host'), ('Privileged', True), ('SecurityOpt', ['seccomp=unconfined'])]:
            changed = copy.deepcopy(obj); changed['HostConfig'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): mod.check_container(state, changed)
        changed = copy.deepcopy(obj); changed['Mounts'][0]['RW'] = True
        with self.assertRaises(ValueError): mod.check_container(state, changed)

    def test_docker_prefixed_capabilities_preserve_exact_allowlist(self):
        state = self.prepared(); obj = fake_inspect(state)
        obj['HostConfig']['CapAdd'] = ['CAP_SETUID', 'CAP_SETGID', 'CAP_KILL', 'CAP_DAC_OVERRIDE']
        self.assertEqual(mod.check_container(state, obj), obj)
        for values in (['CAP_SETUID', 'CAP_SETGID', 'CAP_KILL', 'CAP_DAC_OVERRIDE', 'CAP_SYS_ADMIN'],
                       ['CAP_CAP_SETUID', 'CAP_SETGID', 'CAP_KILL', 'CAP_DAC_OVERRIDE'],
                       ['CAP_SETUID', 'SETUID', 'CAP_SETGID', 'CAP_KILL', 'CAP_DAC_OVERRIDE'],
                       ['cap_setuid', 'CAP_SETGID', 'CAP_KILL', 'CAP_DAC_OVERRIDE'],
                       ['CAP_SETUID', 'CAP_SETGID', 'CAP_KILL', True],
                       'CAP_SETUID'):
            changed = copy.deepcopy(obj); changed['HostConfig']['CapAdd'] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                mod.check_container(state, changed)
        for values in (['CAP_ALL'], ['ALL', 'ALL'], [], None):
            changed = copy.deepcopy(obj); changed['HostConfig']['CapDrop'] = values
            with self.subTest(drop=values), self.assertRaises(ValueError):
                mod.check_container(state, changed)

    def test_identity_changes_refused(self):
        state = self.prepared(); obj = fake_inspect(state)
        for field, value in [('Id', 'x'), ('Image', 'sha256:' + '0' * 64), ('Name', '/other')]:
            changed = copy.deepcopy(obj); changed[field] = value
            with self.assertRaises(ValueError): mod.check_container(state, changed)
        changed = copy.deepcopy(obj); changed['Config']['Labels']['rw.nonce'] = '0' * 32
        with self.assertRaises(ValueError): mod.check_container(state, changed)

    def test_intent_persisted_before_uncertain_submission(self):
        self.prepared()
        def fail_run(_p, args, **kw):
            self.assertEqual(args[0], 'run')
            self.assertTrue(mod.read_json(self.state_dir / 'state.json')['submit_attempted'])
            raise ValueError('lost reply')
        with patch.object(mod, 'inspect_engine'), patch.object(mod, 'inspect_image'), patch.object(mod, 'inspect_container', return_value=None), patch.object(mod, 'docker', side_effect=fail_run), self.assertRaises(ValueError):
            mod.operate('submit', self.state_dir, allow_execute=True)
        with patch.object(mod, 'inspect_engine'), patch.object(mod, 'inspect_container', return_value=None), patch.object(mod, 'docker') as call:
            for op in ('recover', 'recover', 'submit'):
                result = mod.operate(op, self.state_dir, allow_execute=True)
                self.assertEqual(result['state'], 'uncertain')
            call.assert_not_called()

    def test_stopped_receipt_never_scientific_success(self):
        state = self.prepared(); state['submit_attempted'] = True
        obj = fake_inspect(state); obj['State']['Running'] = False
        with patch.object(mod, 'inspect_container', return_value=obj):
            result = mod.reconcile(self.state_dir, state)
        self.assertEqual(result['state'], 'artifacts_unavailable'); self.assertFalse(result['reexecuted'])

    def test_missing_pinned_id_reconciles_name_and_refuses_replacement(self):
        state = self.prepared(); state['container_id'] = '0' * 64
        obj = fake_inspect(state)
        calls = []
        def observed(_p, args, **kwargs):
            calls.append(args)
            return None if len(calls) == 1 else mod.canonical(obj)
        with patch.object(mod, 'docker', side_effect=observed), self.assertRaises(ValueError):
            mod.inspect_container(state)
        self.assertEqual(calls[0][2], '0' * 64)
        self.assertEqual(calls[1][2], state['container_name'])
        self.assertTrue(all(args[:2] == ['container', 'inspect'] for args in calls))
        state['submit_attempted'] = True
        with patch.object(mod, 'docker', return_value=None):
            self.assertIsNone(mod.inspect_container(state))
            result = mod.reconcile(self.state_dir, state)
        self.assertEqual(result['state'], 'uncertain'); self.assertFalse(result['reexecuted'])

    def test_controller_guard_prevents_host_namespace_signals(self):
        code = [sys.executable, str(SCRIPTS / 'linux_supervisor.py'), 'run']
        result = subprocess.run(code, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2); self.assertIn(b'PID1', result.stderr)

    def test_lock_inode_stable_and_symlink_refused(self):
        self.state_dir.mkdir()
        with mod.state_lock(self.state_dir):
            inode = (self.state_dir / '.lock').stat().st_ino
            with self.assertRaises(ValueError):
                with mod.state_lock(self.state_dir): pass
        with mod.state_lock(self.state_dir):
            self.assertEqual((self.state_dir / '.lock').stat().st_ino, inode)
        if os.name == 'posix':
            (self.state_dir / '.lock').unlink(); (self.state_dir / '.lock').symlink_to(self.manifest)
            with self.assertRaises(ValueError):
                with mod.state_lock(self.state_dir): pass

    def test_bounded_process_reply(self):
        with self.assertRaises(ValueError):
            mod.bounded_run([sys.executable, '-c', 'import sys;sys.stdout.write("x"*100000)'], maximum=1024)

    def test_invalid_report_parent_does_not_write_through_symlink(self):
        if os.name != 'posix': self.skipTest('POSIX symlink control')
        real = self.root / 'real'; real.mkdir(); link = self.root / 'link'; link.symlink_to(real, target_is_directory=True)
        result = mod.main(['inspect', '--profile', str(self.manifest), '--report', str(link / 'new.json')])
        self.assertEqual(result, 2); self.assertFalse((real / 'new.json').exists())

    def test_atomic_no_replace_even_empty_directory(self):
        source, dest = self.root / 'stage', self.root / 'dest'; source.mkdir(); dest.mkdir()
        with self.assertRaises((OSError, ValueError)): mod.rename_new(source, dest)
        self.assertTrue(source.exists()); self.assertEqual(list(dest.iterdir()), [])

    def test_collection_hash_names_and_limits(self):
        state = self.prepared(); raw = b'control'; empty = b''
        def item(name, data): return {'name': name, 'sha256': mod.digest(data), 'size': len(data), 'data_base64': base64.b64encode(data).decode()}
        result = {'state': 'succeeded', 'artifacts': [item('out.txt', raw)], 'missing_outputs': [],
                  'logs': {n: item(n + '.log', empty) for n in ('stdout', 'stderr')}}
        dest = self.root / 'collected'
        summary = mod.collect_files(self.state_dir, state, copy.deepcopy(result), dest)
        self.assertFalse(summary['partial']); self.assertEqual((dest / 'out.txt').read_bytes(), raw)
        bad = copy.deepcopy(result); bad['artifacts'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError): mod.collect_files(self.state_dir, state, bad, self.root / 'bad')
        with self.assertRaises(ValueError): mod.collect_files(self.state_dir, state, result, dest)


if __name__ == '__main__':
    unittest.main(verbosity=2)
