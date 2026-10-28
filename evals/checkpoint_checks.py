#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual portable SQLite transaction, crash and bounded-file contracts; no Docker."""
from __future__ import annotations
import base64
import copy
import importlib.util
import json
import io
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts'
SCRIPT = SCRIPTS / 'checkpoint_tools.py'
spec = importlib.util.spec_from_file_location('checked_checkpoint', SCRIPT)
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
lspec = importlib.util.spec_from_file_location('checked_linux_checkpoint', SCRIPTS / 'linux_tools.py')
L = importlib.util.module_from_spec(lspec); lspec.loader.exec_module(L)
sspec = importlib.util.spec_from_file_location('checked_supervisor_checkpoint', SCRIPTS / 'linux_supervisor.py')
S = importlib.util.module_from_spec(sspec); sspec.loader.exec_module(S)


def packet(raw=b'counter:5', identity=None, name='state.txt'):
    return {'schema_version': 1, 'checkpoint_id': identity or uuid.uuid4().hex,
            'application': {'format': 'counter', 'version': '1', 'resume_notes': ''},
            'provenance': {'kind': 'local', 'manifest_sha256': 'a' * 64},
            'files': [{'path': name, 'size': len(raw), 'sha256': C.digest(raw), 'data_base64': base64.b64encode(raw).decode('ascii')}],
            'consistency': C.CONSISTENCY}


class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rw-checkpoint-')
        self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name).resolve()
        self.store = self.root / 'store'; C.init_store(self.store, 4 * 1024**2, 3)

    def save(self, p=None):
        p = p or packet(); C.save_packet(self.store, p, True); return p

    def local(self, data=b'zero'):
        source = self.root / 'source.txt'; source.write_bytes(data)
        m = {'schema_version': 1, 'checkpoint_id': uuid.uuid4().hex,
             'application': {'format': 'text', 'version': '1', 'resume_notes': ''},
             'files': [{'source': source.name, 'path': 'sub/result.txt', 'size': len(data), 'sha256': C.digest(data)}]}
        path = self.root / 'input.json'; path.write_bytes(C.canonical(m)); return path, m

    def cli(self, *args, expected=0):
        report = self.root / ('report-' + uuid.uuid4().hex + '.json')
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args), '--report', str(report)], cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
        self.assertTrue(report.is_file()); return json.loads(report.read_text())

    def test_cli_full_local_roundtrip(self):
        path, m = self.local()
        self.assertTrue(self.cli('save', '--store', self.store, '--manifest', path, '--allow-save')['ok'])
        self.assertEqual(self.cli('list', '--store', self.store)['state'], 'verified')
        self.cli('verify', '--store', self.store, '--checkpoint-id', m['checkpoint_id'])
        out = self.root / 'out'; self.cli('restore', '--store', self.store, '--checkpoint-id', m['checkpoint_id'], '--destination', out, '--allow-restore')
        self.assertEqual((out / 'sub/result.txt').read_bytes(), b'zero')
        self.assertEqual(json.loads((out / '.checkpoint.json').read_text())['execution_clearance'], 'not_granted')

    def test_zero_byte_and_empty_notes_valid(self):
        p = self.save(packet(b'')); C.restore(self.store, p['checkpoint_id'], self.root / 'zero', True)
        self.assertEqual((self.root / 'zero/state.txt').read_bytes(), b'')

    def test_idempotent_before_full_generation_quota(self):
        limited = self.root / 'one'; C.init_store(limited, 4 * 1024**2, 1); p = packet()
        C.save_packet(limited, p, True)
        self.assertEqual(C.save_packet(limited, p, True)['state'], 'already_saved')
        with self.assertRaises(ValueError): C.save_packet(limited, packet(), True)
        self.assertEqual(len(C.verify_store(limited)['checkpoints']), 1)

    def test_same_id_changed_bytes_or_provenance_refused(self):
        p = self.save()
        for q in (packet(b'changed', p['checkpoint_id']), {**p, 'provenance': {'kind': 'local', 'manifest_sha256': 'b' * 64}}):
            with self.assertRaises(ValueError): C.save_packet(self.store, q, True)
        self.assertEqual(len(C.verify_store(self.store)['checkpoints']), 1)

    def test_every_mutation_needs_explicit_flag(self):
        p = self.save()
        for call in (lambda: C.save_packet(self.store, packet()), lambda: C.restore(self.store, p['checkpoint_id'], self.root/'out'), lambda: C.backup(self.store, self.root/'copy'), lambda: C.delete(self.store, p['checkpoint_id'])):
            with self.assertRaises(ValueError): call()

    def test_policy_bounds_and_bool_refused(self):
        for b, n in ((True, 1), (3 * 1024**2, 1), (4 * 1024**2 + 1, 1), (4 * 1024**2, True), (4 * 1024**2, 0), (4 * 1024**2, 129)):
            with self.assertRaises(ValueError): C.init_store(self.root / uuid.uuid4().hex, b, n)

    def test_page_ceiling_reapplied_after_fresh_connection(self):
        with C.store_lock(self.store):
            conn, _ = C.connect_store(self.store)
            try: self.assertEqual(conn.execute('PRAGMA max_page_count').fetchone(), (1024,))
            finally: conn.close()
        C.verify_store(self.store)
        with C.store_lock(self.store):
            conn, _ = C.connect_store(self.store)
            try: self.assertEqual(conn.execute('PRAGMA max_page_count').fetchone(), (1024,))
            finally: conn.close()

    def test_actual_sqlite_full_rolls_back_prior_generation(self):
        p = self.save()
        with self.assertRaises(sqlite3.OperationalError) as caught:
            C.save_packet(self.store, packet(b'x' * (8 * 1024**2)), True)
        self.assertIn('full', str(caught.exception).lower())
        verified = C.verify_store(self.store)
        self.assertEqual([x['checkpoint_id'] for x in verified['checkpoints']], [p['checkpoint_id']])
        self.assertLessEqual((self.store / C.DB_NAME).stat().st_size, 4 * 1024**2)

    def test_explicit_delete_reuses_capacity_without_pruning(self):
        ps = [self.save() for _ in range(3)]
        with self.assertRaises(ValueError): self.save()
        C.delete(self.store, ps[1]['checkpoint_id'], True); newest = self.save()
        ids = {x['checkpoint_id'] for x in C.verify_store(self.store)['checkpoints']}
        self.assertEqual(ids, {ps[0]['checkpoint_id'], ps[2]['checkpoint_id'], newest['checkpoint_id']})

    def test_backup_survives_original_store_removal(self):
        p = self.save(); copy_path = self.root / 'portable-copy'; C.backup(self.store, copy_path, True)
        shutil.rmtree(self.store)
        self.cli('verify', '--store', copy_path, '--checkpoint-id', p['checkpoint_id'])
        C.restore(copy_path, p['checkpoint_id'], self.root / 'restore', True)
        self.assertEqual((self.root / 'restore/state.txt').read_bytes(), b'counter:5')

    def test_data_tamper_refused(self):
        p = self.save(); conn = sqlite3.connect(self.store / C.DB_NAME)
        conn.execute('UPDATE files SET data=? WHERE checkpoint_id=?', (sqlite3.Binary(b'counter:9'), p['checkpoint_id'])); conn.commit(); conn.close()
        with self.assertRaises(ValueError): C.verify_store(self.store)
        with self.assertRaises(ValueError): C.restore(self.store, p['checkpoint_id'], self.root / 'bad', True)
        self.assertFalse((self.root / 'bad').exists())

    def test_policy_valid_value_tamper_refused(self):
        conn = sqlite3.connect(self.store / C.DB_NAME); body = json.loads(conn.execute('SELECT body FROM policy').fetchone()[0]); body['max_generations'] = 4
        conn.execute('UPDATE policy SET body=?', (C.canonical(body).decode(),)); conn.commit(); conn.close()
        with self.assertRaises(ValueError): C.verify_store(self.store)

    def test_missing_foreign_key_schema_refused(self):
        conn = sqlite3.connect(self.store / C.DB_NAME)
        conn.execute('DROP TABLE files'); conn.execute('CREATE TABLE files(checkpoint_id TEXT,path TEXT,size INTEGER,sha256 TEXT,data BLOB)'); conn.commit(); conn.close()
        with self.assertRaises(ValueError): C.verify_store(self.store)
        with self.assertRaises(ValueError): self.save()

    def test_wrong_database_and_corrupt_header_refused(self):
        (self.store / C.DB_NAME).write_bytes(b'not a SQLite database')
        with self.assertRaises((ValueError, sqlite3.Error)): C.verify_store(self.store)

    def test_metadata_and_identity_corruption_refused(self):
        p = self.save(); conn = sqlite3.connect(self.store / C.DB_NAME)
        conn.execute('UPDATE snapshots SET metadata=? WHERE id=?', ('{}', p['checkpoint_id'])); conn.commit(); conn.close()
        with self.assertRaises(ValueError): C.verify_store(self.store)

    def test_portable_path_special_and_alias_refusal(self):
        for name in ('../outside', '/abs', 'a//b', 'a/./b', 'C:/x', 'a:stream', 'NUL', 'con.txt', 'COM1.log', 'COM¹.txt', 'LPT²', 'COM³', 'a.', 'a ', 'a?b', '.ENV', 'x/.checkpoint.json', 'e\u0301.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError): C.relative(name)
        for names in (('A', 'a'), ('Dir', 'dir/x'), ('Straße', 'STRASSE')):
            p = packet(); p['files'] = [packet(name=x)['files'][0] for x in names]
            with self.assertRaises(ValueError): C.validate_packet(p)

    def test_packet_strict_fields_hash_size_and_total(self):
        for field, value in (('schema_version', True), ('checkpoint_id', 'bad'), ('consistency', 'verified')):
            p = packet(); p[field] = value
            with self.assertRaises(ValueError): C.validate_packet(p)
        for field, value in (('size', True), ('size', -1), ('sha256', '0' * 64), ('data_base64', '!')):
            p = packet(); p['files'][0][field] = value
            with self.assertRaises(ValueError): C.validate_packet(p)
        p = packet(); p['files'].append(copy.deepcopy(p['files'][0]))
        with self.assertRaises(ValueError): C.validate_packet(p)

    def test_local_metadata_limit_before_file_io(self):
        path, m = self.local(); m['files'] = [{'source': 'missing' + str(i), 'path': 'state' + str(i), 'size': 8 * 1024**2, 'sha256': 'a' * 64} for i in range(3)]
        path.write_bytes(C.canonical(m))
        with self.assertRaises(ValueError): C.local_packet(path)

    def test_local_hash_symlink_hardlink_and_fifo_refused(self):
        path, m = self.local(); m['files'][0]['sha256'] = '0' * 64; path.write_bytes(C.canonical(m))
        with self.assertRaises(ValueError): C.local_packet(path)
        source = self.root / 'source.txt'; source.unlink(); target = self.root / 'target'; target.write_bytes(b'zero')
        source.symlink_to(target)
        with self.assertRaises(ValueError): C.local_packet(path)
        source.unlink(); os.link(target, source)
        with self.assertRaises(ValueError): C.local_packet(path)
        source.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(source)
            with self.assertRaises(ValueError): C.local_packet(path)

    def test_restore_and_backup_existing_empty_destination_refused(self):
        p = self.save(); out = self.root / 'existing'; out.mkdir()
        with self.assertRaises(ValueError): C.restore(self.store, p['checkpoint_id'], out, True)
        with self.assertRaises(ValueError): C.backup(self.store, out, True)
        self.assertEqual(list(out.iterdir()), [])

    def test_restore_publication_race_does_not_replace(self):
        p = self.save(); out = self.root / 'raced'; original = C.rename_new
        def race(src, dest):
            Path(dest).mkdir(); original(src, dest)
        with patch.object(C, 'rename_new', side_effect=race), self.assertRaises(OSError): C.restore(self.store, p['checkpoint_id'], out, True)
        self.assertEqual(list(out.iterdir()), [])

    def test_existing_report_and_symlink_parent_untouched(self):
        existing = self.root / 'report'; existing.write_text('keep')
        self.assertEqual(C.main(['list', '--store', str(self.store), '--report', str(existing)]), 2)
        self.assertEqual(existing.read_text(), 'keep')
        outside = self.root / 'outside'; outside.mkdir(); link = self.root / 'link'; link.symlink_to(outside, target_is_directory=True)
        self.assertEqual(C.main(['list', '--store', str(self.store), '--report', str(link / 'error.json')]), 2)
        self.assertFalse((outside / 'error.json').exists())

    def test_json_duplicate_nonfinite_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError): C.decode(raw)

    def test_help_has_no_external_effect(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0); self.assertIn('checkpoints', r.stdout)

    def test_actual_mid_transaction_process_death(self):
        p = self.save(); ready = self.root / 'ready'
        code = """import importlib.util,sys,time,sqlite3
from pathlib import Path
s=importlib.util.spec_from_file_location('c',sys.argv[1]);c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
with c.store_lock(sys.argv[2]) as root:
 conn,policy=c.connect_store(root);conn.execute('PRAGMA cache_size=8');conn.execute('BEGIN IMMEDIATE')
 conn.execute('INSERT INTO snapshots VALUES(?,?,?,?)',('b'*32,'{}','a'*64,0))
 conn.execute('INSERT INTO files VALUES(?,?,?,?,?)',('b'*32,'partial',2097152,'a'*64,sqlite3.Binary(b'x'*2097152)))
 Path(sys.argv[3]).write_text('ready');time.sleep(30)
"""
        child = subprocess.Popen([sys.executable, '-c', code, str(SCRIPT), str(self.store), str(ready)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            end = time.monotonic() + 8
            while not ready.exists() and child.poll() is None and time.monotonic() < end: time.sleep(0.02)
            self.assertTrue(ready.exists())
            self.assertTrue((self.store / (C.DB_NAME + '-journal')).exists())
            child.kill(); child.wait(timeout=5)
            verified = C.verify_store(self.store)
            self.assertEqual([x['checkpoint_id'] for x in verified['checkpoints']], [p['checkpoint_id']])
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.communicate(timeout=5)

    def test_actual_commit_then_lost_reply_is_idempotent(self):
        p = packet(); payload = self.root / 'packet.json'; payload.write_bytes(C.canonical(p))
        code = "import importlib.util,sys,os;from pathlib import Path;s=importlib.util.spec_from_file_location('c',sys.argv[1]);c=importlib.util.module_from_spec(s);s.loader.exec_module(c);c.save_packet(sys.argv[2],c.decode(Path(sys.argv[3]).read_bytes()),True);os._exit(91)"
        r = subprocess.run([sys.executable, '-c', code, str(SCRIPT), str(self.store), str(payload)], timeout=10)
        self.assertEqual(r.returncode, 91)
        self.assertEqual(C.save_packet(self.store, p, True)['state'], 'already_saved')
        self.assertEqual(len(C.verify_store(self.store)['checkpoints']), 1)

    def test_actual_lock_contention_and_process_death_retains_inode(self):
        ready = self.root / 'ready'
        code = "import importlib.util,sys,time;from pathlib import Path;s=importlib.util.spec_from_file_location('c',sys.argv[1]);c=importlib.util.module_from_spec(s);s.loader.exec_module(c);lock=c.store_lock(sys.argv[2]);lock.__enter__();Path(sys.argv[3]).write_text('ready');time.sleep(30)"
        child = subprocess.Popen([sys.executable, '-c', code, str(SCRIPT), str(self.store), str(ready)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            end = time.monotonic() + 8
            while not ready.exists() and child.poll() is None and time.monotonic() < end: time.sleep(0.02)
            self.assertTrue(ready.exists()); inode = (self.store / '.lock').stat().st_ino
            with self.assertRaises(ValueError): C.verify_store(self.store)
            child.kill(); child.wait(timeout=5); C.verify_store(self.store)
            self.assertEqual((self.store / '.lock').stat().st_ino, inode)
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.communicate(timeout=5)

    def test_unknown_store_entries_preserved(self):
        extra = self.store / 'unrelated'; extra.write_text('keep')
        with self.assertRaises(ValueError): C.verify_store(self.store)
        self.assertEqual(extra.read_text(), 'keep')

    def test_v1_unchanged_v2_checkpoint_is_explicit(self):
        m = {'schema_version': 1, 'job_id': 'a'*32, 'image_id': 'sha256:'+'b'*64, 'argv': ['python', '-c', 'pass'], 'inputs': [], 'outputs': ['out'], 'required_device': 'cpu', 'resources': {'wall_seconds': 3, 'retention_seconds': 5, 'memory_bytes': 64*1024**2, 'cpu_millis': 500, 'pids': 32, 'work_bytes': 1024**2, 'tmp_bytes': 1024**2, 'max_log_bytes': 128, 'max_output_bytes': 128}}
        L.validate_manifest(m)
        m['checkpoint'] = {'directory': 'cp', 'max_bytes': 100, 'max_files': 1}
        with self.assertRaises(ValueError): L.validate_manifest(m)
        m['schema_version'] = 2; L.validate_manifest(m)
        m['checkpoint']['directory'] = 'out'
        with self.assertRaises(ValueError): L.validate_manifest(m)
        m['checkpoint']['directory'] = 'cp'; m['checkpoint']['max_files'] = True
        with self.assertRaises(ValueError): L.validate_manifest(m)

    def capture_fixture(self, raw=b'inside', declared=None):
        work = self.root / 'work'; work.mkdir(); cp = work / 'cp'; cp.mkdir(); identity = 'a'*32
        generation = cp / identity; generation.mkdir(); (generation / 'state.txt').write_bytes(raw)
        expected = raw if declared is None else declared
        marker = {'schema_version': 1, 'checkpoint_id': identity,
                  'application': {'format': 'counter', 'version': '1', 'resume_notes': ''},
                  'files': [{'path': 'state.txt', 'size': len(expected), 'sha256': C.digest(expected)}]}
        (cp / 'ready.json').write_bytes(C.canonical(marker))
        manifest = {'schema_version': 2, 'job_id': 'b'*32, 'checkpoint': {'directory': 'cp', 'max_bytes': 1024, 'max_files': 2}}
        binding = {'nonce': 'c'*32, 'manifest_sha256': 'd'*64}
        return work, cp, generation, marker, manifest, binding

    @unittest.skipUnless(os.name == 'posix' and os.open in os.supports_dir_fd, 'Anchored live capture requires POSIX dir_fd; actual Linux CI is separately mandatory')
    def test_live_capture_directory_replacement_cannot_escape_anchor(self):
        outside = self.root / 'outside'; outside.mkdir(); secret = b'outside-only'; (outside / 'state.txt').write_bytes(secret)
        work, cp, gen, marker, manifest, binding = self.capture_fixture(declared=secret)
        original = S._checkpoint_dir; swapped = False
        def race(parent_fd, parts):
            nonlocal swapped
            fd = original(parent_fd, parts)
            if parts == ('a'*32,) and not swapped:
                swapped = True; gen.rename(cp / 'old-generation'); gen.symlink_to(outside, target_is_directory=True)
            return fd
        output = io.BytesIO()
        class Target:
            buffer = output
        with patch.object(S, 'WORK', work), patch.object(S, 'checked_binding', return_value=(manifest, binding)), patch.object(S, '_checkpoint_dir', side_effect=race), patch.object(S.sys, 'stdout', Target()):
            with self.assertRaises(ValueError): S.checkpoint()
        self.assertTrue(swapped); self.assertEqual(output.getvalue(), b'')
        self.assertEqual((outside / 'state.txt').read_bytes(), secret)

    @unittest.skipUnless(os.name == 'posix' and os.open in os.supports_dir_fd, 'Anchored live capture requires POSIX dir_fd; actual Linux CI is separately mandatory')
    def test_live_capture_equal_byte_marker_replacement_refused(self):
        work, cp, gen, marker, manifest, binding = self.capture_fixture()
        original = S._checkpoint_read; reads = 0
        def replace_marker(parent_fd, name, maximum):
            nonlocal reads
            answer = original(parent_fd, name, maximum)
            if name == 'ready.json':
                reads += 1
                if reads == 1:
                    temp = cp / 'ready-new.json'; temp.write_bytes(C.canonical(marker)); os.replace(temp, cp / 'ready.json')
            return answer
        output = io.BytesIO()
        class Target:
            buffer = output
        with patch.object(S, 'WORK', work), patch.object(S, 'checked_binding', return_value=(manifest, binding)), patch.object(S, '_checkpoint_read', side_effect=replace_marker), patch.object(S.sys, 'stdout', Target()):
            with self.assertRaises(ValueError): S.checkpoint()
        self.assertEqual(reads, 2); self.assertEqual(output.getvalue(), b'')

    @unittest.skipUnless(os.name == 'posix' and os.open in os.supports_dir_fd, 'Anchored live capture requires POSIX dir_fd; actual Linux CI is separately mandatory')
    def test_live_capture_file_hash_and_config_bounds(self):
        work, cp, gen, marker, manifest, binding = self.capture_fixture()
        output = io.BytesIO()
        class Target:
            buffer = output
        with patch.object(S, 'WORK', work), patch.object(S, 'checked_binding', return_value=(manifest, binding)), patch.object(S.sys, 'stdout', Target()):
            S.checkpoint()
        captured = C.decode(output.getvalue())
        self.assertEqual(base64.b64decode(captured['files'][0]['data_base64']), b'inside')
        self.assertEqual(captured['consistency'], C.CONSISTENCY)
        (gen / 'state.txt').write_bytes(b'wrong')
        with patch.object(S, 'WORK', work), patch.object(S, 'checked_binding', return_value=(manifest, binding)):
            with self.assertRaises(ValueError): S.checkpoint()


if __name__ == '__main__': unittest.main(verbosity=2)
