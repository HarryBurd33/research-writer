#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual disposable SSH streaming checks; loopback is one failure domain."""
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
import time
import tracemalloc
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run-ssh',action='store_true')
parser.add_argument('--skill',type=Path,default=ROOT/'skills/research-writer')
ARGS,REST=parser.parse_known_args(); SCRIPTS=ARGS.skill.absolute()/'scripts'
spec=importlib.util.spec_from_file_location('ssh_stream',SCRIPTS/'stream_backup_tools.py')
S=importlib.util.module_from_spec(spec); spec.loader.exec_module(S); B,C=S.B,S.C
old_argv=sys.argv; sys.argv=[str(ROOT/'evals/remote_loopback_checks.py'),'--run-ssh']
try:
    spec=importlib.util.spec_from_file_location('stream_fixture',ROOT/'evals/remote_loopback_checks.py')
    FIXTURE=importlib.util.module_from_spec(spec); spec.loader.exec_module(FIXTURE)
finally: sys.argv=old_argv


def packet(data):
    return {'schema_version':1,'checkpoint_id':uuid.uuid4().hex,'application':{'format':'counter','version':'1','resume_notes':''},
            'provenance':{'kind':'local','manifest_sha256':'a'*64},'consistency':C.CONSISTENCY,
            'files':[{'path':'first','size':len(data),'sha256':C.digest(data),'data_base64':base64.b64encode(data).decode()},
                     {'path':'second','size':len(data),'sha256':C.digest(data),'data_base64':base64.b64encode(data).decode()},
                     {'path':'zero','size':0,'sha256':C.digest(b''),'data_base64':''}]}


@unittest.skipUnless(ARGS.run_ssh,'Actual loopback SSH not requested')
class StreamLoopback(unittest.TestCase):
    cleanup=classmethod(FIXTURE.LoopbackChecks.cleanup.__func__)
    @classmethod
    def setUpClass(cls): FIXTURE.LoopbackChecks.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): cls.cleanup()
    def setUp(self):
        self.local=self.root/('stream-'+uuid.uuid4().hex); self.local.mkdir(mode=0o700)
        self.p=json.loads(self.profile.read_text()); self.p.update(schema_version=2,vault_id=uuid.uuid4().hex,
            remote_root=str(self.local/'vault'),max_backup_bytes=4*1024**2,rpc_timeout_seconds=60,chunk_bytes=65536)
        self.store=self.local/'source'; C.init_store(self.store,4*1024**2,3)
        C.save_packet(self.store,packet(b'counter:5'),True); C.save_packet(self.store,packet(b''),True)
        self.state=self.local/'state'; S.prepare(self.p,self.store,uuid.uuid4().hex,self.state)
        S.init_remote(self.p,True)

    def injected_source(self,old,new):
        original=C.regular
        def read(path,maximum):
            raw=original(path,maximum)
            if Path(path)==SCRIPTS/'stream_backup_tools.py':
                self.assertIn(old.encode(),raw); raw=raw.replace(old.encode(),new.encode(),1)
            return raw
        return patch.object(C,'regular',side_effect=read)

    def test_actual_cli_roundtrip_then_profile_migration_without_source_or_stage(self):
        profile=self.local/'profile.json'; profile.write_bytes(C.canonical(self.p))
        report=self.local/'push.json'
        run=subprocess.run([sys.executable,str(SCRIPTS/'stream_backup_tools.py'),'push','--profile',str(profile),
            '--state-dir',str(self.state),'--allow-transfer','--report',str(report)],capture_output=True,text=True,timeout=90)
        self.assertEqual(run.returncode,0,run.stderr); self.assertTrue(json.loads(report.read_text())['verification']['fresh_ssh_readback'])
        shutil.rmtree(self.store); shutil.rmtree(self.state/'snapshot')
        old=dict(self.p); old_config=Path(old['ssh_config']); newconfig=self.local/'new-config'
        newconfig.write_text(old_config.read_text().replace('Host rw-loopback','Host new-route'))
        old['ssh_config']='C:\\Users\\old-device\\.ssh\\config'
        intent=json.loads((self.state/'intent.json').read_text()); intent['profile']=old; intent['profile_sha256']=C.digest(C.canonical(old))
        (self.state/'intent.json').write_bytes(C.canonical(intent))
        before={str(x.relative_to(self.state)):x.read_bytes() for x in self.state.rglob('*') if x.is_file()}
        current={**self.p,'ssh_alias':'new-route','ssh_config':str(newconfig),'chunk_bytes':131072}
        migrated=self.local/'migrated'; answer=S.migrate_profile(old,current,self.state,migrated,True)
        self.assertTrue(answer['upload_permanently_blocked']); self.assertEqual(answer['verification']['generations'],2)
        self.assertEqual(before,{str(x.relative_to(self.state)):x.read_bytes() for x in self.state.rglob('*') if x.is_file()})
        with patch.object(S,'rpc',side_effect=AssertionError('No RPC')):
            with self.assertRaisesRegex(ValueError,'permanently blocks'): S.push(current,migrated,True)
        fetched=self.local/'fetched'; S.fetch(current,migrated,fetched,True)
        for item in C.verify_store(fetched)['checkpoints']:
            out=self.local/item['checkpoint_id']; C.restore(fetched,item['checkpoint_id'],out,True)
            self.assertTrue((out/'zero').is_file()); self.assertEqual((out/'zero').stat().st_size,0)

    def test_actual_legacy_v1_archive_migration_without_staging(self):
        old={k:v for k,v in self.p.items() if k!='chunk_bytes'}; old['schema_version']=1
        state=self.local/'legacy'; B.prepare(old,self.store,uuid.uuid4().hex,state); B.push(old,state,True)
        shutil.rmtree(state/'snapshot'); old['ssh_config']='/absent/old-device/config'
        intent=json.loads((state/'intent.json').read_text()); intent['profile_sha256']=C.digest(C.canonical(old))
        (state/'intent.json').write_bytes(C.canonical(intent))
        archive=Path(self.p['remote_root'])/'backups'/intent['descriptor']['backup_id']/'descriptor.json'; before=archive.read_bytes()
        answer=S.migrate_profile(old,self.p,state,self.local/'migrated-legacy',True)
        self.assertEqual(answer['descriptor']['schema_version'],1); self.assertEqual(archive.read_bytes(),before)

    def test_lost_ack_after_publication_readonly_reconciliation(self):
        old="C.fsync_directory(root/'backups'); C.fsync_directory(root)\n            return result('stored'"
        new="C.fsync_directory(root/'backups'); C.fsync_directory(root)\n            os._exit(72)\n            return result('stored'"
        with self.injected_source(old,new):
            with self.assertRaises(S.R.TransportError): S.push(self.p,self.state,True)
        with self.assertRaisesRegex(ValueError,'already attempted'): S.push(self.p,self.state,True)
        self.assertEqual(S.verify(self.p,self.state)['state'],'verified')
        self.assertEqual(len(list((Path(self.p['remote_root'])/'backups').iterdir())),1)

    def test_death_during_staging_preserves_prior(self):
        S.push(self.p,self.state,True); second=self.local/'second'; S.prepare(self.p,self.store,uuid.uuid4().hex,second)
        old="drill=checked_artifact(stage/'store',d,maximum,chunk_bytes)"
        with self.injected_source(old,"os._exit(73)\n            "+old):
            with self.assertRaises(S.R.TransportError): S.push(self.p,second,True)
        self.assertEqual(S.verify(self.p,self.state)['state'],'verified')
        with self.assertRaises((ValueError,S.R.TransportError)): S.verify(self.p,second)
        self.assertEqual(len(list((Path(self.p['remote_root'])/'backups').iterdir())),1)

    def test_client_deadline_after_publish_no_automatic_put_retry(self):
        p={**self.p,'rpc_timeout_seconds':5}; state=self.local/'deadline'; S.prepare(p,self.store,uuid.uuid4().hex,state)
        old="return result('stored',d,drill),None"
        with self.injected_source(old,"time.sleep(7); "+old):
            with self.assertRaises(S.R.TransportError): S.push(p,state,True)
        with self.assertRaisesRegex(ValueError,'already attempted'): S.push(p,state,True)
        time.sleep(2.5)
        self.assertEqual(S.verify(p,state)['state'],'verified')

    def test_actual_identity_and_hostkey_refusal(self):
        bad=self.local/'bad-hosts'; bad.write_text(''); config=self.local/'bad-config'
        config.write_text(Path(self.p['ssh_config']).read_text().replace(str(self.known_hosts),str(bad)))
        with self.assertRaises(S.R.TransportError): S.init_remote({**self.p,'ssh_config':str(config)},True)
        with self.assertRaises((ValueError,S.R.TransportError)): S.init_remote({**self.p,'expected_hostname':'wrong-host'},True)

    def test_large_valid_above_64mib_chunk_instrumented(self):
        large=self.local/'large'; C.init_store(large,128*1024**2,8)
        data=b'large-state\x00'*(7*1024**2//12)+b'x'*(7*1024**2%12)
        # Exactly seven MiB per file; five 14MiB generations exceed old64MiB.
        data=(data+b'x'*(7*1024**2))[:7*1024**2]
        for _ in range(5): C.save_packet(large,packet(data),True)
        del data
        p={**self.p,'max_backup_bytes':128*1024**2,'rpc_timeout_seconds':300}
        state=self.local/'large-state'; S.prepare(p,large,uuid.uuid4().hex,state); _,d=S.load_intent(p,state)
        self.assertGreater(d['size'],64*1024**2)
        with self.assertRaises(ValueError): S.prepare({**p,'max_backup_bytes':64*1024**2},large,uuid.uuid4().hex,self.local/'too-small')
        metrics={'database_bytes':d['size'],'largest_copy_read':0,'copy_bytes':0,'copy_peak_python_bytes':0,'chunk_bytes':p['chunk_bytes']}
        original=S.copy_body
        class Reader:
            def __init__(self,source): self.source=source
            def read(self,n):
                metrics['largest_copy_read']=max(metrics['largest_copy_read'],n)
                self_outer.assertLessEqual(n,p['chunk_bytes']); raw=self.source.read(n); metrics['copy_bytes']+=len(raw); return raw
        self_outer=self
        def measured(source,target,count,chunk_bytes,expected=None):
            tracemalloc.start()
            try:
                answer=original(Reader(source),target,count,chunk_bytes,expected)
                metrics['copy_peak_python_bytes']=max(metrics['copy_peak_python_bytes'],tracemalloc.get_traced_memory()[1]); return answer
            finally: tracemalloc.stop()
        original_regular=C.regular
        def no_db_whole(path,maximum):
            if Path(path).name==C.DB_NAME: raise AssertionError('Database-wide regular read forbidden')
            return original_regular(path,maximum)
        with patch.object(S,'copy_body',side_effect=measured),patch.object(C,'regular',side_effect=no_db_whole):
            answer=S.push(p,state,True)
        self.assertEqual(answer['verification']['generations'],5); self.assertTrue(answer['verification']['full_restore_drill'])
        self.assertLess(metrics['copy_peak_python_bytes'],4*p['chunk_bytes'])
        print('STREAM_TRANSFER_EVIDENCE '+json.dumps(metrics,sort_keys=True),flush=True)


if __name__=='__main__': unittest.main(argv=[sys.argv[0],*REST])
