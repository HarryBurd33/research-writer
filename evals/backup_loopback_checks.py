#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual isolated SSH backup/recovery; loopback is not a second failure domain."""
from __future__ import annotations
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-ssh', action='store_true')
parser.add_argument('--skill', type=Path, default=ROOT / 'skills/research-writer')
ARGS, REST = parser.parse_known_args()
SCRIPTS = ARGS.skill.absolute() / 'scripts'
spec = importlib.util.spec_from_file_location('loopback_backup', SCRIPTS / 'backup_tools.py')
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B); C = B.C
# Reuse only the disposable server setup/cleanup, not its job-execution tests.
old_argv = sys.argv; sys.argv = [str(ROOT / 'evals/remote_loopback_checks.py'), '--run-ssh']
try:
    spec = importlib.util.spec_from_file_location('backup_ssh_fixture', ROOT / 'evals/remote_loopback_checks.py')
    FIXTURE = importlib.util.module_from_spec(spec); spec.loader.exec_module(FIXTURE)
finally: sys.argv = old_argv


@unittest.skipUnless(ARGS.run_ssh, 'Actual loopback SSH not requested')
class BackupLoopback(unittest.TestCase):
    cleanup = classmethod(FIXTURE.LoopbackChecks.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        FIXTURE.LoopbackChecks.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls): cls.cleanup()

    def setUp(self):
        self.local = self.root / ('backup-case-' + uuid.uuid4().hex); self.local.mkdir(mode=0o700)
        self.p = json.loads(self.profile.read_text())
        self.p.update(vault_id=uuid.uuid4().hex, max_backup_bytes=4 * 1024**2,
                      rpc_timeout_seconds=30, remote_root=str(self.local / 'vault'))
        self.profile_path = self.local / 'backup-profile.json'; self.profile_path.write_bytes(C.canonical(self.p))
        self.store = self.local / 'source'; C.init_store(self.store, 4 * 1024**2, 3)
        self.packets = []
        for raw in (b'counter:5', b''):
            p = {'schema_version':1, 'checkpoint_id':uuid.uuid4().hex,
                 'application':{'format':'counter','version':'1','resume_notes':''},
                 'provenance':{'kind':'local','manifest_sha256':'a'*64},
                 'files':[{'path':'sub/state.txt','size':len(raw),'sha256':C.digest(raw),
                           'data_base64':base64.b64encode(raw).decode('ascii')}],
                 'consistency':C.CONSISTENCY}
            C.save_packet(self.store,p,True); self.packets.append(p)
        self.identity = uuid.uuid4().hex; self.state = self.local / 'intent'
        B.prepare(self.p,self.store,self.identity,self.state)
        B.init_remote(self.p,True)

    def cli(self, operation, *extra, expected=0):
        report = self.local / ('reply-' + uuid.uuid4().hex + '.json')
        cmd = [sys.executable,str(SCRIPTS / 'backup_tools.py'),operation,
               '--profile',str(self.profile_path),'--state-dir',str(self.state),'--report',str(report),*map(str,extra)]
        run = subprocess.run(cmd,capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,expected,run.stdout+run.stderr)
        return json.loads(report.read_text())

    def injected_source(self, old, new):
        original = C.regular
        def read(path, maximum):
            raw = original(path,maximum)
            if Path(path) == SCRIPTS / 'backup_tools.py':
                self.assertIn(old.encode(),raw); raw = raw.replace(old.encode(),new.encode(),1)
            return raw
        return patch.object(C,'regular',side_effect=read)

    def test_actual_cli_recovery_without_source_or_staged_copy(self):
        pushed = self.cli('push','--allow-transfer')
        self.assertTrue(pushed['ok']); self.assertTrue(pushed['verification']['fresh_ssh_readback'])
        shutil.rmtree(self.store); shutil.rmtree(self.state / 'snapshot')
        recovered = self.local / 'recovered'
        answer = self.cli('fetch','--destination',recovered,'--allow-restore')
        self.assertEqual(answer['verification']['generations'],2)
        self.assertIn('unverified',answer['failure_domain'])
        for p in self.packets:
            out=self.local/p['checkpoint_id'];C.restore(recovered,p['checkpoint_id'],out,True)
            self.assertEqual((out/'sub/state.txt').read_bytes(),base64.b64decode(p['files'][0]['data_base64']))

    def test_receiver_death_after_publication_reconciles_without_put(self):
        old = "C.fsync_directory(root / 'backups'); C.fsync_directory(root)\n        return result('stored'"
        new = "C.fsync_directory(root / 'backups'); C.fsync_directory(root)\n        os._exit(72)\n        return result('stored'"
        with self.injected_source(old,new):
            with self.assertRaises(B.R.TransportError): B.push(self.p,self.state,True)
        with self.assertRaisesRegex(ValueError,'already attempted'): B.push(self.p,self.state,True)
        self.assertEqual(B.verify(self.p,self.state)['state'],'verified')
        self.assertEqual(len(list((Path(self.p['remote_root'])/'backups').iterdir())),1)

    def test_receiver_death_during_staging_preserves_previous_archive(self):
        B.push(self.p,self.state,True)
        second = self.local/'second-intent'; B.prepare(self.p,self.store,uuid.uuid4().hex,second)
        old = "write_new(stage / 'store' / C.DB_NAME, raw)"
        with self.injected_source(old,old+'; os._exit(73)'):
            with self.assertRaises(B.R.TransportError): B.push(self.p,second,True)
        self.assertEqual(B.verify(self.p,self.state)['state'],'verified')
        with self.assertRaises((ValueError,B.R.TransportError)): B.verify(self.p,second)
        vault = Path(self.p['remote_root'])
        self.assertEqual(len(list((vault/'backups').iterdir())),1)
        self.assertEqual(len(list(vault.glob('.stage-*'))),1)

    def test_actual_host_key_and_host_identity_refused(self):
        bad = self.local/'bad_known_hosts'; bad.write_text('')
        client_config = Path(self.p['ssh_config'])
        p = dict(self.p); config = self.local/'bad-config'
        config.write_text(client_config.read_text().replace(str(self.known_hosts),str(bad)))
        p['ssh_config']=str(config)
        with self.assertRaises(B.R.TransportError): B.init_remote(p,True)
        p=dict(self.p);p['expected_hostname']='wrong-host'
        with self.assertRaises((ValueError,B.R.TransportError)): B.init_remote(p,True)

    def test_actual_init_reply_loss_same_vault_identity_reconciles(self):
        p=dict(self.p);p['remote_root']=str(self.local/'other-vault')
        old="return init_vault(root, req['vault_id'])"
        new="answer = init_vault(root, req['vault_id']); os._exit(74); return answer"
        with self.injected_source(old,new):
            with self.assertRaises(B.R.TransportError): B.init_remote(p,True)
        self.assertEqual(B.init_remote(p,True)['state'],'vault_ready')
        wrong={**p,'vault_id':uuid.uuid4().hex}
        with self.assertRaises(ValueError): B.init_remote(wrong,True)


if __name__ == '__main__': unittest.main(argv=[sys.argv[0],*REST])
