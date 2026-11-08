#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Slurm contract controls with fake scheduler replies; NOT real Slurm acceptance."""
import copy
import getpass
import os
import time
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts'
sys.path.insert(0,str(SCRIPTS))
import slurm_tools as s


class SlurmContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.p={'schema_version':1,'job_root':str(self.root/'jobs'),'expected_hostname':socket.gethostname(),
                'expected_user':getpass.getuser(),'commands':{n:sys.executable for n in ('sbatch','squeue','sacct','scancel')},
                'partition':'test','account':'test','cluster':'test','queue_seconds':1}
        self.m={'schema_version':1,'job_id':uuid.uuid4().hex,'argv':[sys.executable,'-c',"from pathlib import Path;Path('result.txt').write_text('ok')"],
                'inputs':[],'outputs':['result.txt'],'resources':{'wall_seconds':5,'max_output_bytes':4096,'max_log_bytes':4096,'threads':1},'required_device':'cpu'}
        self.manifest=self.root/'manifest.json';s.worker.atomic(self.manifest,self.m)

    def tearDown(self): self.temp.cleanup()
    def prepare(self): s.prepare(self.p,self.manifest,True);return s.checked(self.p,self.m['job_id'])
    def row(self,saved,user=None,account='test',state='RUNNING',exit_code='0:0',ident='123'):
        return '|'.join([ident,user or self.p['expected_user'],saved['token'],state,exit_code,'2026-11-08T01:00:00',account])+'\n'

    def test_profile_rejects_secrets_identity_and_options(self):
        self.assertEqual(s.profile(self.p),self.p)
        for key,val in [('password','secret'),('expected_user','other'),('partition','--wrap=bad')]:
            p={**self.p,key:val}
            with self.assertRaises(ValueError): s.profile(p)

    def test_explicit_permission_and_immutable_payload(self):
        with self.assertRaises(ValueError): s.prepare(self.p,self.manifest)
        job,m,saved=self.prepare();(job/'batch.sh').write_text('modified')
        with self.assertRaises(ValueError): s.checked(self.p,m['job_id'])

    def test_lost_reply_durable_intent_no_retry_after_restart(self):
        job,m,saved=self.prepare();seen=[]
        def lost(p,n,args):
            seen.append(n);self.assertTrue(s.worker.read_json(job/'slurm.json')['submit_attempted'])
            raise ValueError('lost reply')
        with patch.object(s,'command',lost):
            result=s.operate(self.p,'submit',m['job_id'],True)
            self.assertEqual(result['status'],'uncertain')
            with self.assertRaises(ValueError):s.operate(self.p,'submit',m['job_id'],True)
        self.assertEqual(seen,['sbatch'])
        saved=s.worker.read_json(job/'slurm.json')
        with patch.object(s,'command',side_effect=['',self.row(saved)]):
            self.assertEqual(s.operate(self.p,'recover',m['job_id'])['scheduler']['scheduler_job_id'],'123')

    def test_missing_accounting_duplicate_owner_and_recycled_id(self):
        job,m,saved=self.prepare();saved.update(submit_attempted=True,attempted_at=1)
        cases=[['',ValueError('accounting unavailable')],['',''],['',self.row(saved)+self.row(saved,ident='124')],
               ['',self.row(saved)+self.row(saved,state='COMPLETED')],
               ['',self.row(saved,user='another')],['',self.row(saved,account='another')]]
        for replies in cases:
            with self.subTest(replies=str(replies)),patch.object(s,'command',side_effect=replies):
                self.assertEqual(s.reconcile(self.p,job,m,dict(saved))['status'],'uncertain')
        saved['scheduler_job_id']='999'
        with patch.object(s,'command',side_effect=['',self.row(saved)]):
            self.assertEqual(s.reconcile(self.p,job,m,saved)['status'],'uncertain')

    def test_completed_nonzero_and_missing_artifacts_fail(self):
        job,m,saved=self.prepare();saved.update(submit_attempted=True,attempted_at=1)
        for exit_code in ('7:0','0:0'):
            with patch.object(s,'command',side_effect=['',self.row(saved,state='COMPLETED',exit_code=exit_code)]):
                self.assertEqual(s.reconcile(self.p,job,m,dict(saved))['status'],'failed')

    def test_completed_collect_checksums_no_overwrite(self):
        job,m,saved=self.prepare();s.worker.run_job(job)
        saved.update(submit_attempted=True,attempted_at=1);s.worker.atomic(job/'slurm.json',saved)
        dest=self.root/'collection'
        with patch.object(s,'command',side_effect=['',self.row(saved,state='COMPLETED')]):
            result=s.operate(self.p,'collect',m['job_id'],destination=dest)
        self.assertEqual(result['status'],'succeeded');self.assertEqual((dest/'result.txt').read_text(),'ok')
        with patch.object(s,'command',side_effect=['',self.row(saved,state='COMPLETED')]),self.assertRaises(FileExistsError):
            s.operate(self.p,'collect',m['job_id'],destination=dest)

    def test_cancel_requires_permission_and_owner_reconciliation(self):
        job,m,saved=self.prepare();saved.update(submit_attempted=True,attempted_at=1);s.worker.atomic(job/'slurm.json',saved)
        with self.assertRaises(ValueError):s.operate(self.p,'cancel',m['job_id'])
        with patch.object(s,'command',side_effect=['',self.row(saved,user='other')]) as command:
            with self.assertRaises(ValueError):s.operate(self.p,'cancel',m['job_id'],allow_cancel=True)
            self.assertEqual(command.call_count,2)
        with patch.object(s,'command',side_effect=['',self.row(saved),'']) as command:
            self.assertTrue(s.operate(self.p,'cancel',m['job_id'],allow_cancel=True)['scheduler']['cancel_requested'])
            self.assertEqual(command.call_args.args[1:],('scancel',['--clusters=test','--user='+self.p['expected_user'],'123']))

    def test_queue_deadline_separate_from_running_timeout(self):
        job,m,saved=self.prepare();saved.update(submit_attempted=True,attempted_at=1)
        with patch.object(s,'command',side_effect=['',self.row(saved,state='PENDING')]):
            status=s.reconcile(self.p,job,m,saved)
        self.assertEqual(status['status'],'queued');self.assertTrue(status['queue_deadline_exceeded'])
        with patch.object(s,'command',side_effect=['',self.row(saved,state='TIMEOUT')]):
            self.assertEqual(s.reconcile(self.p,job,m,saved)['status'],'timed_out')


@unittest.skipUnless(os.environ.get('RW_SLURM_LIVE')=='1' and os.environ.get('RW_SLURM_PROFILE'),
                     'requires explicitly authorized actual Slurm profile; mocks are not acceptance')
class NativeSlurm(unittest.TestCase):
    """Leaves this run's immutable jobs/receipts in the selected root for evidence."""
    def setUp(self):
        self.p=s.profile(s.common.read_json(os.environ['RW_SLURM_PROFILE']))
        self.temp=tempfile.TemporaryDirectory(prefix='rw-slurm-live-fixture-')
        self.root=Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def prepare(self,code,wall=10):
        m={'schema_version':1,'job_id':uuid.uuid4().hex,'argv':[sys.executable,'-c',code],
           'inputs':[],'outputs':['result.txt'],'resources':{'wall_seconds':wall,'max_output_bytes':4096,'max_log_bytes':4096,'threads':1},'required_device':'cpu'}
        path=self.root/(m['job_id']+'.json');s.worker.atomic(path,m);s.prepare(self.p,path,True)
        print('LIVE_SLURM_JOB',m['job_id'],flush=True)
        return m

    def wait(self,m):
        end=time.monotonic()+min(self.p['queue_seconds']+30,180)
        while time.monotonic()<end:
            result=s.operate(self.p,'status',m['job_id'])
            if result['status'] in s.TERMINAL: return result
            time.sleep(.5)
        self.fail('No terminal Slurm confirmation within bounded acceptance interval: '+str(result))

    def test_live_roundtrip_lost_ack_reconcile(self):
        m=self.prepare("from pathlib import Path;Path('result.txt').write_text('live-ok')")
        native=s.command
        def lost(p,name,args):
            result=native(p,name,args)
            if name=='sbatch': raise ValueError('acceptance injection: real submit reply lost')
            return result
        with patch.object(s,'command',lost):
            self.assertEqual(s.operate(self.p,'submit',m['job_id'],True)['status'],'uncertain')
        with self.assertRaises(ValueError):s.operate(self.p,'submit',m['job_id'],True)
        self.assertEqual(self.wait(m)['status'],'succeeded')
        dest=self.root/'collected'
        result=s.operate(self.p,'collect',m['job_id'],destination=dest)
        self.assertEqual((dest/'result.txt').read_text(),'live-ok')
        # Durable collector receipt retains raw checksum evidence with the job.
        s.worker.atomic(Path(self.p['job_root'])/m['job_id']/'live-collection-receipt.json',result)

    def test_live_timeout_and_cancel(self):
        for cancel in (False,True):
            m=self.prepare('import time;time.sleep(30)',wall=10 if cancel else 1)
            s.operate(self.p,'submit',m['job_id'],True)
            if cancel: s.operate(self.p,'cancel',m['job_id'],allow_cancel=True)
            self.assertEqual(self.wait(m)['status'],'cancelled' if cancel else 'timed_out')
            s.operate(self.p,'collect',m['job_id'],destination=self.root/('cancelled' if cancel else 'timed-out'))


if __name__=='__main__': unittest.main()
