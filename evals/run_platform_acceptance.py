#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Require native acceptance methods to execute; never count skipped tests as runtime proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import subprocess
import time
from unittest.mock import patch
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('platform',choices=('windows','slurm'));args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    name=args.platform
    if name=='windows' and os.name!='nt':raise SystemExit('Native Windows required')
    if name=='slurm' and (platform.system()!='Linux' or os.environ.get('RW_SLURM_LIVE')!='1' or not os.environ.get('RW_SLURM_PROFILE')):
        raise SystemExit('Explicit real Linux Slurm configuration required')
    filename='windows_worker_checks.py' if name=='windows' else 'slurm_checks.py'
    ns=runpy.run_path(str(root/'evals'/filename),run_name='platform_acceptance_cases')
    classes=('Paths','NativeWindows') if name=='windows' else ('SlurmContract','NativeSlurm')
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(ns[k]) for k in classes)
    if name=='slurm':
        backend=ns['s']
        class NativeSchedulerGates(unittest.TestCase):
            def setUp(self):
                self.fixture=ns['NativeSlurm']();self.fixture.setUp()
                self.fixture.p={**self.fixture.p,'queue_seconds':1}
                self.jobs=[]
            def tearDown(self):
                # Always reconcile/cancel our exact token; never submit a repair job.
                for m in self.jobs:
                    try:backend.operate(self.fixture.p,'cancel',m['job_id'],allow_cancel=True)
                    except Exception:pass
                self.fixture.tearDown()
            def held(self):
                m=self.fixture.prepare('import time;time.sleep(30)');self.jobs.append(m)
                native=backend.command
                def hold(p,n,args):
                    return native(p,n,[*args[:-1],'--hold',args[-1]] if n=='sbatch' else args)
                with patch.object(backend,'command',hold):
                    backend.operate(self.fixture.p,'submit',m['job_id'],True)
                return m
            def test_actual_queue_deadline_and_fresh_client_after_controller_restart(self):
                m=self.held();time.sleep(1.2)
                status=backend.operate(self.fixture.p,'status',m['job_id'])
                self.assertEqual(status['status'],'queued');self.assertTrue(status['scheduler']['queue_deadline_exceeded'])
                subprocess.run(['sudo','-n','systemctl','restart','slurmctld'],check=True,timeout=30)
                profile=self.fixture.root/'selected-profile.json';backend.worker.atomic(profile,self.fixture.p)
                output=self.fixture.root/'fresh-recover.json'
                end=time.monotonic()+30
                while time.monotonic()<end:
                    output.unlink(missing_ok=True)
                    completed=subprocess.run([sys.executable,str(root/'skills/research-writer/scripts/slurm_tools.py'),'recover',
                        '--profile',str(profile),'--job-id',m['job_id'],'--output',str(output)],timeout=25,check=False)
                    if completed.returncode==0 and json.loads(output.read_text())['status']=='queued':break
                    time.sleep(.5)
                else:self.fail('Fresh client could not reconcile after real controller restart')
                recovered=json.loads(output.read_text())
                self.assertEqual(recovered['scheduler']['scheduler_job_id'],status['scheduler']['scheduler_job_id'])
                backend.operate(self.fixture.p,'cancel',m['job_id'],allow_cancel=True)
                self.assertEqual(self.fixture.wait(m)['status'],'cancelled')
            def test_actual_accounting_outage_remains_uncertain(self):
                m=self.held()
                subprocess.run(['sudo','-n','systemctl','stop','slurmdbd'],check=True,timeout=30)
                try:
                    self.assertEqual(backend.operate(self.fixture.p,'recover',m['job_id'])['status'],'uncertain')
                    with self.assertRaises(ValueError):backend.operate(self.fixture.p,'submit',m['job_id'],True)
                finally:subprocess.run(['sudo','-n','systemctl','start','slurmdbd'],check=True,timeout=30)
                end=time.monotonic()+30
                while time.monotonic()<end:
                    if backend.operate(self.fixture.p,'recover',m['job_id'])['status']=='queued':break
                    time.sleep(.5)
                else:self.fail('Accounting did not recover within bound')
                backend.operate(self.fixture.p,'cancel',m['job_id'],allow_cancel=True)
                self.assertEqual(self.fixture.wait(m)['status'],'cancelled')
            def test_actual_cancel_terminates_descendant_before_collection(self):
                code="import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,'-c',\"import time;from pathlib import Path;time.sleep(4);Path('escaped.txt').write_text('bad')\"]);Path('started.txt').write_text('yes');time.sleep(30)"
                m=self.fixture.prepare(code,wall=20);self.jobs.append(m)
                backend.operate(self.fixture.p,'submit',m['job_id'],True)
                job=Path(self.fixture.p['job_root'])/m['job_id'];end=time.monotonic()+45
                while time.monotonic()<end:
                    if (job/'work/started.txt').is_file():break
                    time.sleep(.1)
                else:self.fail('Workload did not actually spawn descendant')
                backend.operate(self.fixture.p,'cancel',m['job_id'],allow_cancel=True)
                self.assertEqual(self.fixture.wait(m)['status'],'cancelled')
                time.sleep(4.2);self.assertFalse((job/'work/escaped.txt').exists())
                backend.operate(self.fixture.p,'collect',m['job_id'],destination=self.fixture.root/'cancel-tree')
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(NativeSchedulerGates))
    expected=9 if name=='windows' else 15
    if suite.countTestCases()<expected:raise SystemExit('Native acceptance cases missing')
    script='windows_worker.py' if name=='windows' else 'slurm_tools.py'
    paths=[root/'evals'/filename,root/'skills/research-writer/scripts'/script,Path(__file__)]
    if name=='slurm':paths.extend([root/'evals/setup_slurm_ci.py',root/'skills/research-writer/scripts/remote_worker.py',root/'skills/research-writer/scripts/remote_tools.py'])
    provenance={'platform':name,'host':platform.platform(),'python':sys.version,'github_sha':os.environ.get('GITHUB_SHA'),
                'sources':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    print('PLATFORM_PROVENANCE '+json.dumps(provenance,sort_keys=True),flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    passed=result.wasSuccessful() and result.testsRun>=expected and not result.skipped
    print('PLATFORM_ACCEPTANCE '+json.dumps({'platform':name,'passed':passed,'methods':result.testsRun,
          'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors)}),flush=True)
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
