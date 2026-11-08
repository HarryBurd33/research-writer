#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit selected-host Slurm CPU jobs. Profiles are configuration, not authorization."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import getpass
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import remote_worker as worker
import remote_tools as common

TERMINAL = worker.TERMINAL
FIELDS = {'schema_version','job_root','expected_hostname','expected_user','commands',
          'partition','account','cluster','queue_seconds'}


def profile(p):
    if not isinstance(p,dict) or set(p)!=FIELDS or type(p['schema_version']) is not int or p['schema_version']!=1:
        raise ValueError('Exact Slurm profile schema required; credentials are forbidden')
    if os.name!='posix': raise ValueError('Run on the selected POSIX Slurm submission host')
    for key in ('partition','account','cluster'):
        if not isinstance(p[key],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',p[key]):
            raise ValueError('Invalid explicit '+key)
    if type(p['queue_seconds']) is not int or not 1<=p['queue_seconds']<=86400:
        raise ValueError('Queue deadline must be 1..86400 seconds')
    if p['expected_hostname']!=socket.gethostname() or p['expected_user']!=getpass.getuser():
        raise ValueError('Pinned submission host/user mismatch')
    root=worker.root_path(p['job_root'])
    if len(root.parts)<3: raise ValueError('Dedicated job root required')
    if not isinstance(p['commands'],dict) or set(p['commands'])!={'sbatch','squeue','sacct','scancel'}:
        raise ValueError('Exact native Slurm command mapping required')
    for path in p['commands'].values():
        if not isinstance(path,str) or not Path(path).is_absolute() or not Path(path).is_file() or not os.access(path,os.X_OK):
            raise ValueError('Select absolute installed native executables')
    return p


def command(p,name,args):
    """No shell evaluation; bounded reply and deadline even for a broken scheduler CLI."""
    with tempfile.TemporaryDirectory(prefix='rw-slurm-rpc-') as folder:
        out,err=Path(folder)/'out',Path(folder)/'err'
        with out.open('wb') as stdout,err.open('wb') as stderr:
            child=subprocess.Popen([p['commands'][name],*args],stdin=subprocess.DEVNULL,
                                   stdout=stdout,stderr=stderr,shell=False,start_new_session=True)
            end=time.monotonic()+20
            try:
                while child.poll() is None:
                    if time.monotonic()>end or out.stat().st_size>1024*1024 or err.stat().st_size>65536:
                        raise ValueError('Scheduler reply timeout/size limit; mutation outcome may be uncertain')
                    time.sleep(.02)
            finally:
                if child.poll() is None:
                    import signal
                    os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
        if out.stat().st_size>1024*1024 or err.stat().st_size>65536:
            raise ValueError('Scheduler reply exceeds limit; outcome may be uncertain')
        if child.returncode: raise ValueError('Scheduler command failed: '+err.read_text(errors='replace')[-1000:])
        return out.read_text(encoding='utf-8')


def binding(p,m):
    return {'profile_sha256':worker.digest(worker.canonical(p)),
            'manifest_sha256':worker.digest(worker.canonical(m)),
            'token':'rw:'+m['job_id']+':'+worker.digest(worker.canonical(m)),
            'cluster':p['cluster'],'owner':p['expected_user'],'account':p['account']}


def checked(p,job_id):
    common.job_id(job_id)
    root=worker.root_path(p['job_root']);job=root/job_id
    saved=worker.read_json(worker.inside(job,'slurm.json'))
    m=worker.validate_manifest(worker.read_json(worker.inside(job,'manifest.json')))
    for key,value in binding(p,m).items():
        if saved.get(key)!=value: raise ValueError('Immutable Slurm binding differs: '+key)
    worker.checked_job(root,{'job_id':job_id,'manifest_sha256':saved['manifest_sha256']})
    script=worker.inside(job,'batch.sh')
    if worker.digest(script.read_bytes())!=saved['batch_sha256']:
        raise ValueError('Immutable batch script changed')
    return job,m,saved


def prepare(p,manifest_path,allow_transfer=False):
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required')
    m=worker.validate_manifest(common.read_json(manifest_path));common.validate_manifest(m)
    files=common.input_files(m,Path(manifest_path).resolve().parent)
    root=worker.root_path(p['job_root']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    job=root/m['job_id']
    # The persistent per-job inode lives outside the not-yet-created prepared directory.
    with common.local_lock(root,m['job_id']):
        if job.exists() or job.is_symlink(): raise FileExistsError('Existing job: reconcile without preparing again')
        source=Path(worker.__file__).read_text(encoding='utf-8')
        req={'job_id':m['job_id'],'manifest_sha256':worker.digest(worker.canonical(m)),
             'manifest':m,'files':files,'worker_source':source}
        result=worker.prepare(root,req,worker.identity())
        # Only fixed validated absolute interpreter/controller/job paths enter the shell script.
        script='#!/bin/sh\nexec '+shlex.join([sys.executable,str(job/'controller.py'),'--run-job',str(job)])+'\n'
        (job/'batch.sh').write_text(script,encoding='utf-8')
        saved={**binding(p,m),'job_id':m['job_id'],'batch_sha256':worker.digest(script.encode()),
               'submit_attempted':False,'status':'prepared'}
        worker.atomic(job/'slurm.json',saved)
        return {**result,'scheduler':saved}


def rows(p,saved):
    """Require both queue and accounting replies. No missing-job success inference."""
    query=['--clusters='+p['cluster'],'--user='+p['expected_user']]
    queued=command(p,'squeue',[*query,'--noheader','--format=%i|%u|%k|%T|%V|%a'])
    since=time.strftime('%Y-%m-%dT%H:%M:%S',time.localtime(saved.get('attempted_at',time.time())-60))
    accounted=command(p,'sacct',[*query,'--starttime='+since,'--allocations','--noheader','--parsable2',
                                 '--duplicates','--format=JobIDRaw%32,User%256,Comment%128,State%64,ExitCode%32,Submit%32,Account%64'])
    matches={}; observed={}
    for raw,accounting in ((queued,False),(accounted,True)):
        for line in raw.splitlines():
            fields=[field.strip() for field in line.rstrip('|').split('|')]
            if len(fields)!=(7 if accounting else 6): raise ValueError('Malformed scheduler identity row')
            ident,user,token,state=fields[:4]
            account=fields[6] if accounting else fields[5]
            if token!=saved['token']: continue
            if user!=saved['owner'] or account!=saved['account'] or not re.fullmatch('[0-9]+',ident):
                raise ValueError('Scheduler ownership/account/job identity mismatch')
            if saved.get('scheduler_job_id') and ident!=saved['scheduler_job_id']:
                raise ValueError('Duplicate/recycled scheduler identity; do not adopt')
            row={'scheduler_job_id':ident,'scheduler_state':state.split()[0].rstrip('+'),
                 'exit_code':fields[4] if accounting else None,'submit':fields[5] if accounting else fields[4]}
            key=(accounting,ident)
            if key in observed and observed[key]!=row:
                raise ValueError('Contradictory duplicate scheduler records; outcome uncertain')
            observed[key]=row
            if ident in matches and row['submit']!=matches[ident]['submit']:
                raise ValueError('Recycled/requeued scheduler submission identity differs')
            if saved.get('submit') and saved['submit']!=row['submit']:
                raise ValueError('Scheduler submit identity changed')
            if ident not in matches or accounting: matches[ident]=row
    if len(matches)!=1: raise ValueError('Absent or multiple exact scheduler matches; outcome uncertain')
    return next(iter(matches.values()))


def reconcile(p,job,m,saved):
    if not saved['submit_attempted']: return saved
    try:
        row=rows(p,saved);saved.update(row)
        scheduler=row['scheduler_state']
        if scheduler=='COMPLETED':
            local=worker.snapshot(job)
            valid = row['exit_code']=='0:0' and local['status']=='succeeded'
            index=worker.read_json(worker.inside(job,'artifacts.json')) if valid else {}
            for name in m['outputs']:
                if valid:
                    path=worker.inside(job/'work',name)
                    raw=common.read_bytes(path,m['resources']['max_output_bytes'])
                    valid=name in index and worker.digest(raw)==index[name]['sha256']
            saved['status']='succeeded' if valid else (local['status'] if row['exit_code']=='0:0' and local['status'] in ('timed_out','cancelled') else 'failed')
        elif scheduler in ('CANCELLED','TIMEOUT','FAILED','NODE_FAIL','OUT_OF_MEMORY','BOOT_FAIL','DEADLINE','PREEMPTED'):
            saved['status']={'CANCELLED':'cancelled','TIMEOUT':'timed_out'}.get(scheduler,'failed')
        elif scheduler in ('PENDING','CONFIGURING','REQUEUED','REQUEUE_FED','REQUEUE_HOLD'):
            saved['status']='queued'
            saved['queue_deadline_exceeded']=time.time()-saved['attempted_at']>p['queue_seconds']
        elif scheduler in ('RUNNING','COMPLETING','SUSPENDED','RESIZING'):
            saved['status']='running'
        else: saved['status']='uncertain'
        saved.pop('error',None)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        saved.update(status='uncertain',error=str(exc)[:2000])
    worker.atomic(job/'slurm.json',saved)
    return saved


def operate(p,operation,job_id,allow_execute=False,allow_cancel=False,destination=None):
    root=worker.root_path(p['job_root'])
    with common.local_lock(root,job_id):
        job,m,saved=checked(p,job_id)
        if operation=='submit':
            if not allow_execute: raise ValueError('Explicit --allow-execute required')
            if saved['submit_attempted'] or saved['status']!='prepared':
                raise ValueError('Submission already attempted/not prepared: never retry')
            saved.update(submit_attempted=True,status='uncertain',attempted_at=time.time())
            worker.atomic(job/'slurm.json',saved)  # durable before native mutation
            r=m['resources']
            args=['--parsable','--clusters='+p['cluster'],'--partition='+p['partition'],'--account='+p['account'],
                  '--job-name=rw-'+job_id,'--comment='+saved['token'],'--no-requeue',
                  '--cpus-per-task='+str(r['threads']),'--time='+str(math.ceil(r['wall_seconds']/60)),
                  '--output=/dev/null','--error=/dev/null','--export=NONE',str(job/'batch.sh')]
            try:
                receipt=command(p,'sbatch',args).strip()
                if not re.fullmatch('[0-9]+(?:;'+re.escape(p['cluster'])+')?',receipt):
                    raise ValueError('Malformed/wrong-cluster submission receipt; reconcile only')
                saved.update(scheduler_job_id=receipt.split(';')[0],status='queued')
                worker.atomic(job/'slurm.json',saved)
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                saved.update(status='uncertain',error=str(exc));worker.atomic(job/'slurm.json',saved)
        elif operation in ('status','recover'):
            saved=reconcile(p,job,m,saved)
        elif operation=='cancel':
            if not allow_cancel: raise ValueError('Explicit --allow-cancel required')
            if not saved['submit_attempted']:
                saved['status']='cancelled';worker.atomic(job/'slurm.json',saved)
            else:
                saved=reconcile(p,job,m,saved)
                if saved['status']=='uncertain': raise ValueError('Cannot cancel without exact scheduler ownership reconciliation')
                if saved['status'] not in TERMINAL:
                    command(p,'scancel',['--clusters='+p['cluster'],'--user='+p['expected_user'],saved['scheduler_job_id']])
                    saved['cancel_requested']=True;worker.atomic(job/'slurm.json',saved)
        elif operation=='collect':
            saved=reconcile(p,job,m,saved)
            if saved['status'] not in TERMINAL: raise ValueError('Terminal scheduler confirmation required before collection')
            # Worker checkpointed artifacts are mandatory; scheduler completion alone is insufficient.
            req={'protocol':1,'operation':'collect','remote_root':str(root),'expected_hostname':p['expected_hostname'],
                 'expected_user':p['expected_user'],'job_id':job_id,'manifest_sha256':saved['manifest_sha256']}
            if worker.snapshot(job)['status'] not in TERMINAL:
                # Scheduler terminal ownership proof makes postmortem checkpoint safe.
                artifacts={};total=0
                for name in m['outputs']:
                    path=worker.inside(job/'work',name,False)
                    if not path.exists(): continue
                    raw=common.read_bytes(worker.inside(job/'work',name),m['resources']['max_output_bytes'])
                    total+=len(raw)
                    if total>m['resources']['max_output_bytes']: raise ValueError('Postmortem artifact budget exceeded')
                    artifacts[name]={'sha256':worker.digest(raw),'bytes':len(raw)}
                errors=worker.bound_logs(job,m['resources']['max_log_bytes'])
                if errors: raise ValueError('Invalid postmortem diagnostics')
                worker.atomic(job/'artifacts.json',artifacts)
                worker.atomic(job/'state.json',{'status':saved['status'],'job_id':job_id,
                              'reason':'Scheduler-confirmed terminal postmortem checkpoint','updated_at':time.time()})
            result=worker.handle(req)
            if not result['ok']: raise ValueError('No valid terminal worker artifact checkpoint')
            result['status']=saved['status'];result['partial']=saved['status']!='succeeded'
            collection=common.collect_files(result,m,destination)
            return {'ok':True,'status':saved['status'],'scheduler':saved,'collection':collection}
        else: raise ValueError('Unknown lifecycle operation')
        return {'ok':True,'status':saved['status'],'scheduler':saved}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='operation',required=True)
    for op in ('inspect','prepare','submit','status','recover','collect','cancel'):
        c=subs.add_parser(op);c.add_argument('--profile',required=True);c.add_argument('--output',required=True)
        if op=='prepare': c.add_argument('--manifest',required=True);c.add_argument('--allow-transfer',action='store_true')
        if op not in ('inspect','prepare'): c.add_argument('--job-id',required=True)
        if op=='submit': c.add_argument('--allow-execute',action='store_true')
        if op=='cancel': c.add_argument('--allow-cancel',action='store_true')
        if op=='collect': c.add_argument('--destination',required=True)
    a=parser.parse_args(argv)
    try:
        if Path(a.output).exists() or Path(a.output).is_symlink(): raise ValueError('Output exists')
        p=profile(common.read_json(a.profile))
        if a.operation=='inspect':
            result={'ok':True,'status':'inspected','identity':worker.identity(),'cluster':p['cluster'],
                    'versions':{n:command(p,n,['--version']).strip() for n in p['commands']},
                    'runtime_prerequisites':{'accounting_job_comment_retention':'not_verified',
                    'shared_job_root_and_interpreter':'not_verified','real_scheduler_lifecycle':'not_verified'}}
        elif a.operation=='prepare': result=prepare(p,a.manifest,a.allow_transfer)
        else: result=operate(p,a.operation,a.job_id,getattr(a,'allow_execute',False),getattr(a,'allow_cancel',False),getattr(a,'destination',None))
        common.save(a.output,result,exclusive=True);return 0
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr);return 2


if __name__=='__main__': raise SystemExit(main())
