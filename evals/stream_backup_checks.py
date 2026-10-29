#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable binary framing, artifact and offline migration contracts."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import getpass
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--skill',type=Path,default=ROOT/'skills/research-writer')
ARGS,REST=parser.parse_known_args()
spec=importlib.util.spec_from_file_location('stream_contract',ARGS.skill.absolute()/'scripts/stream_backup_tools.py')
S=importlib.util.module_from_spec(spec); spec.loader.exec_module(S); B,C=S.B,S.C


def packet(data=b'counter:1'):
    return {'schema_version':1,'checkpoint_id':uuid.uuid4().hex,'application':{'format':'counter','version':'1','resume_notes':''},
            'provenance':{'kind':'local','manifest_sha256':'a'*64},'consistency':C.CONSISTENCY,
            'files':[{'path':'state.bin','size':len(data),'sha256':C.digest(data),'data_base64':base64.b64encode(data).decode()},
                     {'path':'zero','size':0,'sha256':C.digest(b''),'data_base64':''}]}


class StreamContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rw-stream-test-'); self.root=Path(self.tmp.name).resolve()
        self.config=self.root/'config'; self.config.write_text('Host test\n HostName 127.0.0.1\n')
        self.p={'schema_version':2,'ssh_alias':'test','ssh_config':str(self.config),'remote_python':'python3',
                'remote_root':str(self.root/'vault') if os.name=='posix' else '/var/tmp/rw-stream-fixture','expected_hostname':socket.gethostname(),'expected_user':getpass.getuser(),
                'connect_timeout_seconds':5,'vault_id':uuid.uuid4().hex,'max_backup_bytes':4*1024**2,
                'rpc_timeout_seconds':10,'chunk_bytes':65536}
        self.store=self.root/'source'; C.init_store(self.store,4*1024**2,3)
        C.save_packet(self.store,packet(),True); C.save_packet(self.store,packet(b''),True)
        self.state=self.root/'state'; S.prepare(self.p,self.store,uuid.uuid4().hex,self.state)

    def tearDown(self): self.tmp.cleanup()

    def frame(self,meta,count=0,body=b''):
        s=io.BytesIO(); S.write_header(s,meta,count); s.write(body); s.seek(0); return s

    def local_rpc(self,p,req,upload=None,download=None):
        body=io.BytesIO()
        if upload is not None:
            with Path(upload).open('rb') as source: S.copy_body(source,body,req['descriptor']['size'],p['chunk_bytes'])
        body.seek(0); receipt,path=S.receiver(req,body.getbuffer().nbytes,body)
        if path is not None:
            with Path(path).open('rb') as source,S.private_sink(download) as target:
                S.copy_body(source,target,req['descriptor']['size'],p['chunk_bytes'],req['descriptor']['sha256'])
        return receipt

    def test_profile_explicit_bounds_unknown_fields_and_zero(self):
        self.assertEqual(S.cap(512*1024**2),512*1024**2)
        for v in (0,True,513*1024**2,1024**2+1):
            with self.assertRaises(ValueError): S.cap(v)
        for v in (0,True,65535,65537,2*1024**2):
            with self.assertRaises(ValueError): S.chunk(v)
        for field,value in [('max_backup_bytes',None),('chunk_bytes',None),('password','secret'),('ssh_alias','../alias')]:
            p=dict(self.p)
            if value is None: del p[field]
            else: p[field]=value
            with self.assertRaises(ValueError): S.profile(p)

    def test_short_reader_writer_and_no_progress(self):
        class Reader(io.BytesIO):
            largest=0
            def read(self,n=-1):
                self.largest=max(self.largest,n); return super().read(min(n,3))
        class Writer(io.BytesIO):
            def write(self,b): return super().write(b[:2])
        raw=b'abcdef'*50000; source=Reader(raw); target=Writer()
        S.copy_body(source,target,len(raw),65536,C.digest(raw)); self.assertEqual(target.getvalue(),raw)
        self.assertLessEqual(source.largest,65536)
        class Zero:
            def write(self,b): return 0
        with self.assertRaises(OSError): S.write_all(Zero(),b'abc')

    def test_frame_header_duplicates_nonfinite_and_before_allocation_bounds(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'[]'):
            source=io.BytesIO(S.PREFIX.pack(S.MAGIC,len(raw),0)+raw)
            with self.assertRaises(ValueError): S.read_header(source)
        for header in (S.PREFIX.pack(b'badmagic',1,0),S.PREFIX.pack(S.MAGIC,S.MAX_SMALL+1,0),S.PREFIX.pack(S.MAGIC,1,S.MAX_BACKUP+1)):
            source=io.BytesIO(header)
            with self.assertRaises(ValueError): S.read_header(source)
            self.assertEqual(source.tell(),S.PREFIX.size)
        for n in range(S.PREFIX.size):
            with self.assertRaises(ValueError): S.read_header(io.BytesIO(b'x'*n))

    def test_body_truncation_checksum_trailing(self):
        with self.assertRaises(ValueError): S.copy_body(io.BytesIO(b'a'),io.BytesIO(),2,65536)
        with self.assertRaises(ValueError): S.copy_body(io.BytesIO(b'a'),io.BytesIO(),1,65536,'0'*64)
        with self.assertRaises(ValueError): S.eof(io.BytesIO(b'x'))

    def test_prepare_hashing_never_reads_database_whole(self):
        original=C.regular
        def read(path,maximum):
            if Path(path).name==C.DB_NAME: raise AssertionError('Whole database read forbidden')
            return original(path,maximum)
        with patch.object(C,'regular',side_effect=read):
            S.prepare(self.p,self.store,uuid.uuid4().hex,self.root/'second')
            root,d=S.load_intent(self.p,self.state)
            self.assertTrue(S.checked_artifact(root/'snapshot',d,self.p['max_backup_bytes'],65536)['full_restore_drill'])

    @unittest.skipUnless(os.name=='posix','POSIX receiver contract')
    def test_roundtrip_shared_vault_zero_and_fresh_drill(self):
        with patch.object(S,'rpc',side_effect=self.local_rpc):
            S.init_remote(self.p,True); answer=S.push(self.p,self.state,True)
            self.assertTrue(answer['verification']['fresh_ssh_readback'])
            fetched=self.root/'fetched'; S.fetch(self.p,self.state,fetched,True)
            for item in C.verify_store(fetched)['checkpoints']:
                output=self.root/item['checkpoint_id']; C.restore(fetched,item['checkpoint_id'],output,True)
                self.assertTrue((output/'zero').is_file()); self.assertEqual((output/'zero').stat().st_size,0)
            with self.assertRaisesRegex(ValueError,'already attempted'): S.push(self.p,self.state,True)

    @unittest.skipUnless(os.name=='posix','POSIX receiver contract')
    def test_receiver_rejects_trailing_and_corrupt_without_archive(self):
        B.init_vault(self.p['remote_root'],self.p['vault_id']); root,d=S.load_intent(self.p,self.state)
        raw=(root/'snapshot'/C.DB_NAME).read_bytes()
        for body,count in ((raw+b'x',len(raw)),(raw[:-1],len(raw)),(b'x'+raw[1:],len(raw)),(raw,len(raw)+1)):
            with self.assertRaises(ValueError): S.receiver(S.request(self.p,'put',d),count,io.BytesIO(body))
            self.assertFalse((Path(self.p['remote_root'])/'backups'/d['backup_id']).exists())

    @unittest.skipUnless(os.name=='posix','POSIX receiver contract')
    def test_immutable_conflict_and_storage_fault_preserve_prior(self):
        with patch.object(S,'rpc',side_effect=self.local_rpc):
            S.init_remote(self.p,True); S.push(self.p,self.state,True)
            root,d=S.load_intent(self.p,self.state); raw=(root/'snapshot'/C.DB_NAME).read_bytes()
            bad={**d,'logical_sha256':'b'*64}
            with self.assertRaises(ValueError): S.receiver(S.request(self.p,'put',bad),len(raw),io.BytesIO(raw))
            self.assertEqual(S.verify(self.p,self.state)['state'],'verified')
            second=self.root/'second'; S.prepare(self.p,self.store,uuid.uuid4().hex,second); _,d2=S.load_intent(self.p,second)
            with patch.object(S.os,'fsync',side_effect=OSError('injected EIO')):
                with self.assertRaises(OSError): S.receiver(S.request(self.p,'put',d2),len(raw),io.BytesIO(raw))
            self.assertFalse((Path(self.p['remote_root'])/'backups'/d2['backup_id']).exists())
            self.assertEqual(S.verify(self.p,self.state)['state'],'verified')

    def test_historical_foreign_config_no_stat_and_profile_binding(self):
        for config in ('C:\\Users\\former\\.ssh\\config','/absent/former/config'):
            p={**self.p,'ssh_config':config}
            self.assertEqual(S.profile(p,historical=True)['ssh_config'],config)
            with self.assertRaises(ValueError): S.profile(p)
        p=dict(self.p); p['ssh_config']='~/oldconfig'
        with self.assertRaises(ValueError): S.profile(p,historical=True)

    def test_migration_needs_consent_pins_cap_and_real_new_config(self):
        with patch.object(S,'rpc',side_effect=AssertionError('No RPC expected')):
            with self.assertRaises(ValueError): S.migrate_profile(self.p,self.p,self.state,self.root/'new')
            for key in ('vault_id','remote_root','expected_hostname','expected_user'):
                p={**self.p,key:'different' if key!='remote_root' else '/tmp/different-vault'}
                with self.assertRaises(ValueError): S.migrate_profile(self.p,p,self.state,self.root/'new',True)
            p={**self.p,'ssh_config':str(self.root/'absent')}
            with self.assertRaises(ValueError): S.migrate_profile(self.p,p,self.state,self.root/'new',True)

    def test_offline_migration_legacy_foreign_profile_and_permanent_block(self):
        # A fake read-only connection returns the exact immutable artifact; all
        # local platform file I/O/publication paths execute, including Windows CI.
        old={k:v for k,v in self.p.items() if k!='chunk_bytes'}; old['schema_version']=1
        old['ssh_config']='C:\\Users\\old-device\\.ssh\\config'
        root,d=S.load_intent(self.p,self.state); d={**d,'schema_version':1}
        (root/'intent.json').write_bytes(C.canonical({'schema_version':1,'profile_sha256':C.digest(C.canonical(old)),'descriptor':d}))
        (root/'attempt.json').write_bytes(b'{"attempted":true}')
        before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        calls=[]
        def read_only(p,req,upload=None,download=None):
            calls.append(req['operation']); self.assertEqual(req['operation'],'get'); self.assertIsNone(upload)
            with (root/'snapshot'/C.DB_NAME).open('rb') as source,S.private_sink(download) as target:
                S.copy_body(source,target,d['size'],p['chunk_bytes'],d['sha256'])
            return S.result('verified',d)
        destination=self.root/'migrated'
        with patch.object(S,'rpc',side_effect=read_only):
            answer=S.migrate_profile(old,self.p,root,destination,True)
            self.assertTrue(answer['upload_permanently_blocked']); self.assertEqual(calls,['get'])
            self.assertEqual(S.verify(self.p,destination)['state'],'verified')
            with self.assertRaisesRegex(ValueError,'permanently blocks'): S.push(self.p,destination,True)
        self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.assertEqual((destination/'attempt.json').read_bytes(),b'{"attempted":true}')
        self.assertEqual(json.loads((destination/'intent.json').read_text())['descriptor'],d)

    def test_migration_missing_remote_creates_no_new_state(self):
        with patch.object(S,'rpc',side_effect=ValueError('Backup not found')):
            with self.assertRaises(ValueError): S.migrate_profile(self.p,self.p,self.state,self.root/'missing',True)
        self.assertFalse((self.root/'missing').exists())

    def subprocess_argv(self, mode='valid'):
        # A real Python child uses the same regular stdin/stdout/stderr handles
        # as ssh. It is a portable transport fixture, not a POSIX receiver.
        stub = """import importlib.util,sys,struct,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('stub_stream',sys.argv[1])
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
inp=sys.stdin.buffer;out=sys.stdout.buffer
n=struct.unpack('!I',s.exact(inp,4))[0]
s.exact(inp,n)
req,count=s.read_header(inp);s.eof(inp)
mode=sys.argv[3]
if mode=='timeout': time.sleep(7)
d=req['descriptor']
receipt=s.result('verified',d)
meta={'schema_version':2,'hostname':req['expected_hostname'],'user':req['expected_user'],'remote_root':req['remote_root'],'vault_id':req['vault_id'],'ok':True,'receipt':receipt}
s.write_header(out,meta,d['size']+(1 if mode=='length' else 0))
with Path(sys.argv[2]).open('rb') as source:
 s.copy_body(source,out,d['size'],req['chunk_bytes'],d['sha256'])
if mode=='trailing': out.write(b'x')
out.flush()
"""
        return [sys.executable,'-c',stub,str(S.ROOT/'stream_backup_tools.py'),str(self.state/'snapshot'/C.DB_NAME),mode,'unused-remote-command']

    def test_portable_real_popen_regular_stdio_readback(self):
        import stat
        original=S.subprocess.Popen; calls=[]
        def launch(argv,**kwargs):
            for key in ('stdin','stdout','stderr'):
                self.assertTrue(stat.S_ISREG(os.fstat(kwargs[key].fileno()).st_mode))
            calls.append(True); return original(argv,**kwargs)
        with patch.object(S.R,'ssh_argv',side_effect=lambda p:self.subprocess_argv()),patch.object(S.subprocess,'Popen',side_effect=launch):
            answer=S.verify(self.p,self.state)
        self.assertEqual(calls,[True]); self.assertTrue(answer['verification']['fresh_ssh_readback'])

    def test_portable_real_popen_malformed_frames_no_publication(self):
        for mode in ('length','trailing'):
            destination=self.root/('reject-'+mode)
            with patch.object(S.R,'ssh_argv',side_effect=lambda p:self.subprocess_argv(mode)):
                with self.assertRaises(ValueError): S.fetch(self.p,self.state,destination,True)
            self.assertFalse(destination.exists())

    def test_portable_real_popen_deadline_kills_and_reaps(self):
        p={**self.p,'rpc_timeout_seconds':5}; _,d=S.load_intent(self.p,self.state)
        with patch.object(S.R,'ssh_argv',side_effect=lambda p:self.subprocess_argv('timeout')):
            with self.assertRaisesRegex(S.R.TransportError,'deadline'):
                S.rpc(p,S.request(p,'get',d),download=self.root/'timeout-download')
        self.assertFalse((self.root/'timeout-download').exists())

    def test_giant_profile_rejected_before_snapshot_copy(self):
        p={**self.p,'expected_hostname':'x'*(65*1024)}
        with patch.object(C,'backup',side_effect=AssertionError('Must reject before SQLite copy')):
            with self.assertRaisesRegex(ValueError,'profile exceeds'):
                S.prepare(p,self.store,uuid.uuid4().hex,self.root/'giant-profile')
        self.assertFalse((self.root/'giant-profile').exists())

    @unittest.skipUnless(os.name=='posix','Symlink creation requires platform capability')
    def test_dangling_snapshot_and_attempt_aliases_refused(self):
        import shutil
        shutil.rmtree(self.state/'snapshot')
        for name in ('snapshot','attempt.json'):
            (self.state/name).symlink_to(self.root/'absent-target')
            with patch.object(S,'rpc',side_effect=AssertionError('No RPC for aliases')):
                with self.assertRaisesRegex(ValueError,'Symlink'):
                    S.migrate_profile(self.p,self.p,self.state,self.root/'alias-migration',True)
            (self.state/name).unlink()

    def test_permission_and_private_paths(self):
        with self.assertRaises(ValueError): S.push(self.p,self.state)
        with self.assertRaises(ValueError): S.fetch(self.p,self.state,self.root/'fetch')
        with self.assertRaises(ValueError): S.init_remote(self.p)
        with self.assertRaises(ValueError): S.new_parent(self.state)
        with self.assertRaises(ValueError): S.new_parent(self.root/'..'/'escape')


if __name__=='__main__': unittest.main(argv=[sys.argv[0],*REST])
