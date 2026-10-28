#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable backup contracts plus POSIX receiver storage-failure injection."""
from __future__ import annotations
import base64
import copy
import errno
import getpass
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
spec = importlib.util.spec_from_file_location('checked_backup', SCRIPTS / 'backup_tools.py')
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
C = B.C


def packet(raw=b'counter:5'):
    return {'schema_version': 1, 'checkpoint_id': uuid.uuid4().hex,
            'application': {'format': 'counter', 'version': '1', 'resume_notes': ''},
            'provenance': {'kind': 'local', 'manifest_sha256': 'a' * 64},
            'files': [{'path': 'sub/state.txt', 'size': len(raw), 'sha256': C.digest(raw),
                       'data_base64': base64.b64encode(raw).decode('ascii')}],
            'consistency': C.CONSISTENCY}


class BackupFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rw-backup-check-')
        self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name).resolve()
        self.store = self.root / 'source'; C.init_store(self.store, 4 * 1024**2, 3)
        self.packets = [packet(), packet(b'')]
        for p in self.packets: C.save_packet(self.store, p, True)
        self.p = {'schema_version': 1, 'ssh_alias': 'rw-test', 'ssh_config': None,
                  'remote_python': 'python3',
                  'remote_root': str(self.root / 'vault') if os.name == 'posix' else '/var/tmp/rw-test-vault',
                  'expected_hostname': socket.gethostname(), 'expected_user': getpass.getuser(),
                  'connect_timeout_seconds': 5, 'vault_id': uuid.uuid4().hex,
                  'max_backup_bytes': 4 * 1024**2, 'rpc_timeout_seconds': 30}
        self.state = self.root / 'state'; self.identity = uuid.uuid4().hex

    def prepare(self):
        return B.prepare(self.p, self.store, self.identity, self.state)

    def artifact(self):
        self.prepare(); _, d = B.load_intent(self.p, self.state)
        return d, C.regular(self.state / 'snapshot' / C.DB_NAME, B.MAX_BACKUP)

    def reply(self, d, raw):
        return {'descriptor': d, 'data_base64': base64.b64encode(raw).decode('ascii')}


class BackupContracts(BackupFixture):
    def test_prepare_preserves_entire_format1_store(self):
        answer = self.prepare()
        self.assertEqual(answer['verification']['generations'], 2)
        self.assertEqual(C.verify_store(self.store)['policy'], C.verify_store(self.state / 'snapshot')['policy'])
        self.assertEqual(C.SCHEMA['policy'], 'CREATE TABLE policy(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,fingerprint TEXT NOT NULL)')

    def test_fetch_without_original_or_staged_database(self):
        d, raw = self.artifact(); shutil.rmtree(self.store); shutil.rmtree(self.state / 'snapshot')
        with patch.object(B, 'rpc', return_value=self.reply(d, raw)):
            response = B.fetch(self.p, self.state, self.root / 'recovered', True)
        self.assertEqual(response['verification']['generations'], 2)
        for p in self.packets:
            out = self.root / p['checkpoint_id']; C.restore(self.root / 'recovered', p['checkpoint_id'], out, True)
            self.assertEqual((out / 'sub/state.txt').read_bytes(), base64.b64decode(p['files'][0]['data_base64']))

    def test_zero_file_valid_missing_identity_or_limit_invalid(self):
        self.assertTrue(B.drill_store(self.store)['full_restore_drill'])
        for field in ('vault_id','max_backup_bytes','expected_hostname','expected_user','rpc_timeout_seconds'):
            p = dict(self.p); del p[field]
            with self.assertRaises(ValueError): B.profile(p)
        for field in ('expected_hostname','expected_user'):
            p = dict(self.p); p[field] = ''
            with self.assertRaises(ValueError): B.profile(p)

    def test_exact_profile_rejects_credentials_unknown_and_bool_caps(self):
        for addition in ({'password': 'no'}, {'private_key': 'no'}, {'unexpected': 1}):
            with self.assertRaises(ValueError): B.profile({**self.p, **addition})
        for value in (True, 0, 1024, 65 * 1024**2, 1024**2 + 1):
            with self.assertRaises(ValueError): B.profile({**self.p, 'max_backup_bytes': value})

    def test_source_above_cap_rejected_before_backup_copy(self):
        C.save_packet(self.store, packet(b'x' * (2 * 1024**2)), True)
        p = {**self.p, 'max_backup_bytes': 1024**2}
        with patch.object(B, 'rpc', side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(ValueError, 'exceeds selected backup cap'):
                B.prepare(p, self.store, self.identity, self.state)
        self.assertFalse(self.state.exists()); self.assertEqual(len(C.verify_store(self.store)['checkpoints']), 3)

    def test_profile_change_and_forged_intent_rejected(self):
        self.prepare()
        with self.assertRaises(ValueError): B.load_intent({**self.p, 'vault_id': uuid.uuid4().hex}, self.state)
        path = self.state / 'intent.json'; q = json.loads(path.read_text()); q['descriptor']['size'] = True
        path.write_bytes(C.canonical(q))
        with self.assertRaises(ValueError): B.load_intent(self.p, self.state)

    def test_upload_one_shot_marker_precedes_network(self):
        self.prepare()
        def failed(p, q):
            self.assertTrue((self.state / 'attempt.json').is_file())
            raise B.R.TransportError('lost acknowledgement')
        with patch.object(B, 'rpc', side_effect=failed):
            with self.assertRaises(B.R.TransportError): B.push(self.p, self.state, True)
        with patch.object(B, 'rpc', side_effect=AssertionError('mutation replay forbidden')):
            with self.assertRaisesRegex(ValueError, 'already attempted'): B.push(self.p, self.state, True)

    def test_allow_flags_required_before_network(self):
        self.prepare()
        with patch.object(B, 'rpc', side_effect=AssertionError('network forbidden')):
            for fn in (lambda: B.push(self.p, self.state), lambda: B.init_remote(self.p),
                       lambda: B.fetch(self.p, self.state, self.root / 'out')):
                with self.assertRaises(ValueError): fn()

    def test_client_readback_corruption_and_descriptor_change_refused(self):
        d, raw = self.artifact()
        for response in (self.reply(d, raw[:-1]), self.reply(d, b'x' + raw[1:]),
                         self.reply({**d, 'sha256': 'b'*64}, raw)):
            with patch.object(B, 'rpc', return_value=response):
                with self.assertRaises(ValueError): B.verify(self.p, self.state)

    def test_fetch_never_overwrites_existing_destination(self):
        self.prepare(); out = self.root / 'existing'; out.mkdir(); (out / 'keep').write_bytes(b'kept')
        with patch.object(B, 'rpc', side_effect=AssertionError('network forbidden')):
            with self.assertRaises(ValueError): B.fetch(self.p, self.state, out, True)
        self.assertEqual((out / 'keep').read_bytes(), b'kept')

    def test_prepare_write_fsync_and_rename_faults_preserve_source(self):
        old = B.drill_store(self.store)
        for name, target in (('write', 'write_new'), ('fsync', 'fsync_file')):
            with self.subTest(name=name), patch.object(B, target, side_effect=OSError(errno.EIO, 'injected')):
                with self.assertRaises(OSError): B.prepare(self.p, self.store, uuid.uuid4().hex, self.root / name)
            self.assertEqual(old, B.drill_store(self.store))
        with patch.object(C, 'rename_new', side_effect=OSError(errno.ENOSPC, 'injected')):
            with self.assertRaises(OSError): self.prepare()
        self.assertEqual(old, B.drill_store(self.store))

    def test_short_write_is_error(self):
        class Short:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, raw): return len(raw) - 1
        with patch.object(B.os, 'fdopen', return_value=Short()):
            with self.assertRaisesRegex(OSError, 'Short backup write'): B.write_new(self.root / 'short', b'abc')

    def test_success_report_file_fsync_failure_leaves_no_success(self):
        out = self.root / 'report'
        with patch.object(B.os, 'fsync', side_effect=OSError(errno.EIO, 'flush')):
            with self.assertRaises(OSError): B.publish_report(out, b'{"ok":true}')
        self.assertFalse(out.exists())

    def test_artifact_flush_uses_writable_windows_and_readonly_posix_handle(self):
        path = self.root / 'artifact'
        for platform, expected in (('nt',os.O_RDWR), ('posix',os.O_RDONLY)):
            with self.subTest(platform=platform), patch.object(B.os,'name',platform), \
                    patch.object(B.os,'open',return_value=99) as opened, \
                    patch.object(B.os,'fsync') as flushed, patch.object(B.os,'close') as closed:
                B.fsync_file(path)
                opened.assert_called_once_with(path,expected|getattr(os,'O_NOFOLLOW',0))
                flushed.assert_called_once_with(99); closed.assert_called_once_with(99)

    def test_success_report_postrename_flush_failure_removes_own_report(self):
        out = self.root / 'report'
        with patch.object(C, 'fsync_directory', side_effect=OSError(errno.EIO, 'flush')):
            with self.assertRaises(OSError): B.publish_report(out, b'{"ok":true}')
        self.assertFalse(out.exists())

    def test_report_existing_preserved(self):
        out = self.root / 'report'; out.write_bytes(b'kept')
        with self.assertRaises(OSError): B.publish_report(out, b'{"ok":true}')
        self.assertEqual(out.read_bytes(), b'kept')

    def test_cli_prepare_and_existing_report_negative(self):
        profile = self.root / 'profile.json'; profile.write_bytes(C.canonical(self.p))
        report = self.root / 'report.json'
        argv = [sys.executable, str(SCRIPTS / 'backup_tools.py'), 'prepare', '--profile', str(profile),
                '--store', str(self.store), '--backup-id', self.identity, '--state-dir', str(self.state), '--report', str(report)]
        run = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr); self.assertTrue(json.loads(report.read_text())['ok'])
        old = report.read_bytes(); run = subprocess.run(argv, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 2); self.assertEqual(report.read_bytes(), old)

    def test_cli_report_inside_source_or_intent_refused_before_mutation(self):
        profile = self.root / 'profile.json'; profile.write_bytes(C.canonical(self.p))
        for report, op in ((self.store/'report.json','prepare'), (self.root/'state'/'report.json','verify')):
            if op == 'verify': self.prepare()
            argv = [sys.executable,str(SCRIPTS/'backup_tools.py'),op,'--profile',str(profile),
                    '--state-dir',str(self.state),'--report',str(report)]
            if op == 'prepare': argv += ['--store',str(self.store),'--backup-id',self.identity]
            run = subprocess.run(argv,capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,2)
            self.assertFalse(report.exists())
            self.assertEqual(len(C.verify_store(self.store)['checkpoints']),2)

    def test_cli_report_parent_alias_rejected_without_source_pollution(self):
        profile = self.root / 'profile.json'; profile.write_bytes(C.canonical(self.p))
        alternate = self.root / 'alternate'; alternate.mkdir(mode=0o700)
        report = alternate / '..' / 'source' / 'bad-report.json'
        argv = [sys.executable,str(SCRIPTS/'backup_tools.py'),'prepare','--profile',str(profile),
                '--store',str(self.store),'--backup-id',self.identity,'--state-dir',str(self.state),
                '--report',str(report)]
        run = subprocess.run(argv,capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,2)
        self.assertFalse((self.store/'bad-report.json').exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(len(C.verify_store(self.store)['checkpoints']),2)

    def test_fetch_parent_alias_rejected_before_rpc_and_state_pollution(self):
        self.prepare(); alternate = self.root / 'alternate'; alternate.mkdir(mode=0o700)
        destination = alternate / '..' / 'state' / 'new-store'
        with patch.object(B,'rpc',side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(ValueError,'Parent traversal'):
                B.fetch(self.p,self.state,destination,True)
        self.assertFalse((self.state/'new-store').exists())
        B.load_intent(self.p,self.state)


@unittest.skipUnless(os.name == 'posix', 'POSIX receiver only; portable client controls run separately')
class ReceiverContracts(BackupFixture):
    def setup_vault(self):
        self.d, self.raw = self.artifact()
        B.receiver(B.request(self.p, 'init'))
        self.put = B.request(self.p, 'put', self.d)
        self.put['data_base64'] = base64.b64encode(self.raw).decode('ascii')
        self.root_vault = Path(self.p['remote_root'])

    def test_receiver_roundtrip_conflict_and_readonly_reconcile(self):
        self.setup_vault(); B.receiver(self.put)
        self.assertEqual(B.receiver(self.put)['state'], 'already_present')
        reply = B.receiver(B.request(self.p, 'get', self.d))
        self.assertEqual(base64.b64decode(reply['data_base64']), self.raw)
        changed = copy.deepcopy(self.put); changed['descriptor']['logical_sha256'] = 'c'*64
        with self.assertRaises(ValueError): B.receiver(changed)
        self.assertEqual(B.receiver(B.request(self.p, 'get', self.d))['descriptor'], self.d)

    def test_wrong_host_user_vault_and_unknown_request_refused(self):
        self.setup_vault()
        for field, value in (('expected_hostname','wrong'),('expected_user','wrong'),('vault_id',uuid.uuid4().hex)):
            with self.assertRaises(ValueError): B.receiver({**self.put, field: value})
        with self.assertRaises(ValueError): B.receiver({**self.put, 'extra': 1})

    def test_receiver_installed_skill_ancestor_and_dotdot_refused(self):
        self.setup_vault(); skill = self.root / 'other-skill'; skill.mkdir(mode=0o700)
        (skill / 'SKILL.md').write_text('unrelated skill')
        with self.assertRaises(ValueError):
            B.receiver({**B.request(self.p,'init'),'remote_root':str(skill/'vault')})
        with self.assertRaises(ValueError):
            B.receiver({**B.request(self.p,'init'),'remote_root':str(self.root/'anything'/'..'/'vault2')})

    def test_init_reconcile_same_vault_and_refuse_unrelated_root(self):
        self.setup_vault(); self.assertEqual(B.receiver(B.request(self.p,'init'))['state'], 'vault_ready')
        unrelated = self.root / 'unrelated'; unrelated.mkdir(mode=0o700); (unrelated / 'keep').write_bytes(b'kept')
        with self.assertRaises((ValueError,FileNotFoundError)):
            B.receiver({**B.request(self.p,'init'),'remote_root': str(unrelated)})
        self.assertEqual((unrelated / 'keep').read_bytes(), b'kept')

    def test_receiver_cap_before_base64_decode(self):
        self.setup_vault(); q = copy.deepcopy(self.put); q['descriptor']['size'] = 5 * 1024**2
        with patch.object(B.base64, 'b64decode', side_effect=AssertionError('decode forbidden')):
            with self.assertRaises(ValueError): B.receiver(q)

    def test_receiver_corruption_and_truncation_refused(self):
        self.setup_vault()
        for raw in (self.raw[:-1], b'x'+self.raw[1:]):
            q = copy.deepcopy(self.put); q['data_base64'] = base64.b64encode(raw).decode('ascii')
            with self.assertRaises(ValueError): B.receiver(q)
        self.assertFalse((self.root_vault / 'backups' / self.identity).exists())

    def test_receiver_storage_errors_preserve_old_backup(self):
        self.setup_vault(); B.receiver(self.put)
        old = B.receiver(B.request(self.p, 'get', self.d))
        q = copy.deepcopy(self.put); q['descriptor']['backup_id'] = uuid.uuid4().hex
        for number in (errno.ENOSPC, errno.EIO):
            with self.subTest(errno=number), patch.object(B, 'write_new', side_effect=OSError(number,'injected')):
                with self.assertRaises(OSError): B.receiver(q)
            self.assertEqual(B.receiver(B.request(self.p, 'get', self.d)), old)
        for target in ('fsync_file',):
            with patch.object(B, target, side_effect=OSError(errno.EIO,'injected')):
                with self.assertRaises(OSError): B.receiver(q)
            self.assertEqual(B.receiver(B.request(self.p, 'get', self.d)), old)

    def test_receiver_prerename_flush_and_rename_faults_no_publication(self):
        self.setup_vault()
        with patch.object(C, 'fsync_directory', side_effect=OSError(errno.EIO, 'flush')):
            with self.assertRaises(OSError): B.receiver(self.put)
        self.assertFalse((self.root_vault/'backups'/self.identity).exists())
        with patch.object(C, 'rename_new', side_effect=OSError(errno.EIO, 'rename')):
            with self.assertRaises(OSError): B.receiver(self.put)
        self.assertFalse((self.root_vault/'backups'/self.identity).exists())

    def test_receiver_postrename_flush_uncertain_then_get(self):
        self.setup_vault(); original = C.fsync_directory
        def flush(path):
            if Path(path) == self.root_vault / 'backups': raise OSError(errno.EIO, 'postrename')
            return original(path)
        with patch.object(C, 'fsync_directory', side_effect=flush):
            with self.assertRaises(OSError): B.receiver(self.put)
        self.assertTrue((self.root_vault/'backups'/self.identity).is_dir())
        reply = B.receiver(B.request(self.p, 'get', self.d))
        self.assertEqual(reply['descriptor'], self.d)

    def test_vault_lock_contention_and_symlink_refused(self):
        self.setup_vault()
        with B.vault_lock(self.root_vault):
            with self.assertRaises(BlockingIOError): B.receiver(self.put)
        link = self.root / 'link'; link.symlink_to(self.root_vault, target_is_directory=True)
        with self.assertRaises(ValueError): B.receiver({**self.put,'remote_root':str(link)})

    def test_receiver_publication_race_does_not_overwrite(self):
        self.setup_vault(); target = self.root_vault/'backups'/self.identity; original = C.rename_new
        def race(source, destination):
            if Path(destination) == target:
                target.mkdir(mode=0o700); (target/'keep').write_bytes(b'kept')
            return original(source,destination)
        with patch.object(C,'rename_new',side_effect=race):
            with self.assertRaises(OSError): B.receiver(self.put)
        self.assertEqual((target/'keep').read_bytes(), b'kept')

    def test_orphan_stage_never_counts_as_backup_or_blocks_old_reads(self):
        self.setup_vault(); B.receiver(self.put)
        orphan = self.root_vault / ('.stage-' + uuid.uuid4().hex)
        orphan.mkdir(mode=0o700); (orphan / 'partial').write_bytes(b'partial')
        answer = B.receiver(B.request(self.p, 'get', self.d))
        self.assertEqual(answer['descriptor'], self.d)
        self.assertEqual((orphan / 'partial').read_bytes(), b'partial')


if __name__ == '__main__': unittest.main()
