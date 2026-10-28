#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual POSIX lock-crash and read-only legacy recovery regression controls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts/remote_worker.py'
spec=importlib.util.spec_from_file_location('recovery_worker',SCRIPT)
W=importlib.util.module_from_spec(spec);spec.loader.exec_module(W)

@unittest.skipUnless(os.name=='posix','Worker supports POSIX only')
class RecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rw-recovery-');self.root=Path(self.tmp.name).resolve()
    def tearDown(self):self.tmp.cleanup()
    def test_kernel_lock_survives_inode_and_releases_after_rpc_death(self):
        ready=self.root/'ready'
        code="import importlib.util,sys,time;from pathlib import Path;s=importlib.util.spec_from_file_location('w',sys.argv[1]);w=importlib.util.module_from_spec(s);s.loader.exec_module(w);ctx=w.mutation_lock(Path(sys.argv[2]));ctx.__enter__();Path(sys.argv[3]).write_text('ready');time.sleep(20)"
        child=subprocess.Popen([sys.executable,'-c',code,str(SCRIPT),str(self.root),str(ready)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(ready.exists())
            inode=(self.root/'.rpc-lock').stat().st_ino
            with self.assertRaises(ValueError):
                with W.mutation_lock(self.root):pass
            child.kill();child.wait(timeout=5)
            with W.mutation_lock(self.root):self.assertEqual((self.root/'.rpc-lock').stat().st_ino,inode)
            with W.mutation_lock(self.root):pass
            self.assertTrue((self.root/'.rpc-lock').is_file())
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.communicate(timeout=5)
    def test_old_directory_symlink_and_hardlink_locks_are_not_stolen(self):
        lock=self.root/'.rpc-lock';lock.mkdir()
        with self.assertRaises((ValueError,OSError)):
            with W.mutation_lock(self.root):pass
        self.assertTrue(lock.is_dir());lock.rmdir()
        target=self.root/'outside';target.write_text('keep')
        lock.symlink_to(target)
        with self.assertRaises((ValueError,OSError)):
            with W.mutation_lock(self.root):pass
        self.assertEqual(target.read_text(),'keep');lock.unlink()
        os.link(target,lock)
        with self.assertRaises((ValueError,OSError)):
            with W.mutation_lock(self.root):pass
        self.assertEqual(target.read_text(),'keep')
    def test_recover_stale_state_is_read_only_without_pid_action(self):
        m={'schema_version':1,'job_id':'a'*32,'argv':[sys.executable,'-c','pass'],'inputs':[], 'outputs':['out'], 'resources':{'wall_seconds':3,'max_output_bytes':32,'max_log_bytes':32,'threads':1},'required_device':'cpu'}
        ident=W.identity();req={'protocol':1,'operation':'prepare','remote_root':str(self.root/'jobs'),'expected_hostname':ident['hostname'],'expected_user':ident['user'],'job_id':m['job_id'],'manifest_sha256':W.digest(W.canonical(m)),'manifest':m,'files':[],'worker_source':SCRIPT.read_text()}
        self.assertTrue(W.handle(req)['ok']);job=self.root/'jobs'/m['job_id']
        W.atomic(job/'submission.json',{'attempted_at':0})
        W.atomic(job/'state.json',{'status':'running','heartbeat':0,'job_id':m['job_id']})
        W.atomic(job/'controller-receipt.json',{'pid':os.getpid()})
        before={str(p.relative_to(job)):p.read_bytes() for p in job.rglob('*') if p.is_file()}
        with patch.object(W.subprocess,'Popen',side_effect=AssertionError('no launch')),patch.object(W.os,'kill',side_effect=AssertionError('no PID signals')),patch.object(W.os,'killpg',side_effect=AssertionError('no process group signals')):
            for _ in range(2):
                result=W.handle({**req,'operation':'recover'})
                self.assertTrue(result['ok'],result);self.assertEqual(result['status'],'uncertain')
                self.assertFalse(result['reconciliation']['restarted']);self.assertFalse(result['reconciliation']['pid_signal_sent'])
        self.assertEqual(before,{str(p.relative_to(job)):p.read_bytes() for p in job.rglob('*') if p.is_file()})
    def test_recover_binding_and_unprepared_job(self):
        ident=W.identity();req={'protocol':1,'operation':'recover','remote_root':str(self.root/'jobs'),'expected_hostname':ident['hostname'],'expected_user':ident['user'],'job_id':'b'*32,'manifest_sha256':'0'*64}
        self.assertEqual(W.handle(req)['status'],'not_found');self.assertFalse((self.root/'jobs').exists())
        self.assertFalse(W.handle({**req,'expected_user':'other'})['ok'])

if __name__=='__main__':unittest.main()
