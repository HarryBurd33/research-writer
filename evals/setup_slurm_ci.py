#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Configure only an ephemeral GitHub-hosted Ubuntu Slurm acceptance runner.

Requires apt-installed Slurm, slurmdbd, MariaDB and munge. Never a production setup.
The random database generated_db_value is supplied over stdin and stored only in a 0600 file.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import time

CLUSTER='rwci'
SERVICES=('slurmd','slurmctld','slurmdbd')


def run(argv,secret_input=None,check=True):
    result=subprocess.run(argv,input=secret_input,text=True,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,timeout=45,check=False)
    if check and result.returncode:
        # Never relay a secret SQL statement or database/daemon configuration.
        raise RuntimeError('Command failed: '+Path(argv[0]).name+' '+('secret stdin redacted' if secret_input else ' '.join(argv[1:3])))
    return result


def wait_for(label,fn,seconds=60):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            if fn(): return
        except (OSError,RuntimeError,subprocess.SubprocessError): pass
        time.sleep(1)
    raise RuntimeError('Readiness deadline: '+label)


def write(path,text,mode=0o644,owner=None):
    path=Path(path)
    if path.is_symlink(): raise ValueError('Refusing symlink configuration')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,mode)
    os.fchmod(fd,mode)  # restrict an existing file before any secret bytes are written
    with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(text)
    path.chmod(mode)
    if owner:
        account=pwd.getpwnam(owner);os.chown(path,account.pw_uid,account.pw_gid)


def guard():
    if os.name!='posix' or os.geteuid()!=0 or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise ValueError('Only root on an explicitly ephemeral GitHub-hosted runner is supported')
    release=Path('/etc/os-release').read_text()
    if 'ID=ubuntu' not in release or 'VERSION_ID="24.04"' not in release:
        raise ValueError('This harness selects Ubuntu 24.04 packages only')


def setup(a):
    guard();user=pwd.getpwnam(a.user)
    if user.pw_uid==0 or not re.fullmatch('[A-Za-z_][A-Za-z0-9_-]*',a.user):
        raise ValueError('Select the unprivileged ephemeral runner account')
    root=Path(a.root)
    if not root.is_absolute() or root.exists() or root.is_symlink() or not root.parent.is_dir():
        raise ValueError('A new absolute owned acceptance root is required')
    for name in SERVICES:
        if run(['systemctl','is-active','--quiet',name],check=False).returncode==0:
            raise ValueError('Refusing an already-running Slurm service')
    root.mkdir(mode=0o700);os.chown(root,user.pw_uid,user.pw_gid)
    write(root/'CI-OWNER.json',json.dumps({'schema_version':1,'hostname':socket.gethostname(),'user':a.user,'cluster':CLUSTER})+'\n',0o600,a.user)
    for sub,owner,mode in (('jobs',a.user,0o700),('state','slurm',0o700),('spool','root',0o755),('logs','slurm',0o750)):
        path=root/sub;path.mkdir(mode=mode);account=pwd.getpwnam(owner);os.chown(path,account.pw_uid,account.pw_gid)
    # Daemons must traverse the private runner parent/root; ACL grant is confined to this new root.
    run(['setfacl','-m','u:slurm:--x',str(root.parent)])
    run(['setfacl','-m','u:slurm:--x',str(root)])
    run(['systemctl','start','munge','mariadb'])
    wait_for('MariaDB local root socket',lambda:run(['mariadb','--protocol=socket','-uroot','-Nse','SELECT 1'],check=False).stdout.strip()=='1')
    generated_db_value=secrets.token_hex(32)
    sql="CREATE DATABASE rwslurm; CREATE USER 'rwslurm'@'localhost' IDENTIFIED BY '"+generated_db_value+"'; GRANT ALL PRIVILEGES ON rwslurm.* TO 'rwslurm'@'localhost'; FLUSH PRIVILEGES;\n"
    run(['mariadb','--protocol=socket','-uroot'],secret_input=sql)
    Path('/etc/slurm').mkdir(exist_ok=True)
    dbd='\n'.join(['AuthType=auth/munge','DbdHost=localhost','DbdAddr=127.0.0.1','DbdPort=6819',
                   'SlurmUser=slurm','StorageType=accounting_storage/mysql','StorageHost=localhost',
                   'StorageLoc=rwslurm','StorageUser=rwslurm','StoragePass='+generated_db_value,
                   'PidFile=/run/slurmdbd.pid','LogFile='+str(root/'logs/slurmdbd.log'),'DebugLevel=info'])+'\n'
    write('/etc/slurm/slurmdbd.conf',dbd,0o600,'slurm')
    del generated_db_value,sql,dbd
    host=socket.gethostname()
    if not re.fullmatch('[A-Za-z0-9_.-]+',host): raise ValueError('Unexpected node name')
    hardware=run(['/usr/sbin/slurmd','-C']).stdout
    wanted=('CPUs','Boards','SocketsPerBoard','CoresPerSocket','ThreadsPerCore')
    fields=dict(re.findall(r'(\w+)=(\S+)',hardware))
    if any(not fields.get(k,'').isdigit() for k in wanted): raise ValueError('Cannot parse actual Slurm CPU topology')
    topology=' '.join(k+'='+fields[k] for k in wanted)
    conf='\n'.join([
        'ClusterName='+CLUSTER,'SlurmctldHost='+host+'(127.0.0.1)','SlurmUser=slurm','SlurmdUser=root',
        'AuthType=auth/munge','StateSaveLocation='+str(root/'state'),'SlurmdSpoolDir='+str(root/'spool'),
        'SlurmctldLogFile='+str(root/'logs/slurmctld.log'),'SlurmdLogFile='+str(root/'logs/slurmd.log'),
        'SlurmctldPidFile=/run/slurmctld.pid','SlurmdPidFile=/run/slurmd.pid',
        'SchedulerType=sched/backfill','SelectType=select/cons_tres','SelectTypeParameters=CR_CPU_Memory',
        'ProctrackType=proctrack/cgroup','TaskPlugin=task/cgroup','JobAcctGatherType=jobacct_gather/cgroup',
        'AccountingStorageType=accounting_storage/slurmdbd','AccountingStorageHost=localhost',
        'AccountingStoragePort=6819','AccountingStoreFlags=job_comment','AccountingStorageEnforce=associations',
        'ReturnToService=2','SlurmctldTimeout=30','SlurmdTimeout=30','MessageTimeout=10','MinJobAge=30',
        'NodeName='+host+' NodeAddr=127.0.0.1 '+topology+' RealMemory=1024 State=UNKNOWN',
        'PartitionName=rwci Nodes='+host+' Default=YES MaxTime=00:02:00 DefaultTime=00:01:00 DefMemPerCPU=256 MaxMemPerCPU=512 State=UP'])+'\n'
    write('/etc/slurm/slurm.conf',conf)
    write('/etc/slurm/cgroup.conf','CgroupPlugin=autodetect\nConstrainCores=no\nConstrainRAMSpace=yes\nConstrainSwapSpace=yes\n')
    run(['systemctl','restart','slurmdbd'])
    wait_for('slurmdbd accounting',lambda:run(['sacctmgr','-nP','show','cluster','format=Cluster'],check=False).returncode==0)
    run(['sacctmgr','-i','add','cluster',CLUSTER])
    run(['sacctmgr','-i','add','account','rwci','Cluster='+CLUSTER,'Description=disposable-acceptance','Organization=ci'])
    run(['sacctmgr','-i','add','user',a.user,'Cluster='+CLUSTER,'Account=rwci','DefaultAccount=rwci'])
    run(['systemctl','start','slurmctld','slurmd'])
    wait_for('controller ping',lambda:'UP' in run(['scontrol','ping'],check=False).stdout)
    wait_for('compute node registration',lambda:bool(re.search(r'\b(idle|mix)\b',run(['sinfo','--noheader','--format=%T'],check=False).stdout)))
    commands={name:shutil.which(name) for name in ('sbatch','squeue','sacct','scancel')}
    if not all(commands.values()): raise ValueError('Native Slurm command missing')
    profile={'schema_version':1,'job_root':str(root/'jobs'),'expected_hostname':host,'expected_user':a.user,
             'commands':commands,'partition':'rwci','account':'rwci','cluster':CLUSTER,'queue_seconds':60}
    write(a.profile,json.dumps(profile,indent=2)+'\n',0o600,a.user)
    packages=run(['dpkg-query','-W','-f=${Package} ${Version}\n','slurm-wlm','slurmdbd','mariadb-server','munge']).stdout
    print(packages,end='')
    print(json.dumps({'status':'ready','cluster':CLUSTER,'node':host,'user':a.user,
                      'profile':a.profile,'config_sha256':hashlib.sha256(conf.encode()).hexdigest(),
                      'accounting_comment_retention':'configured_job_comment','tracking':'actual_cgroup_runtime_required'}))


def cleanup(a):
    guard();root=Path(a.root)
    owner=root/'CI-OWNER.json'
    if not owner.is_file() or root.is_symlink(): raise ValueError('No owned disposable setup marker; refusing cleanup')
    marker=json.loads(owner.read_text())
    if marker!={'schema_version':1,'hostname':socket.gethostname(),'user':a.user,'cluster':CLUSTER}:
        raise ValueError('Disposable owner marker mismatch')
    # This entire cluster belongs to this one ephemeral job. Never broaden to another cluster/user.
    run(['scancel','--clusters='+CLUSTER,'--user='+a.user],check=False)
    for service in SERVICES:run(['systemctl','stop',service],check=False)
    # Only nonsecret job receipts can be printed; no DB config, environment or daemon logs.
    for path in sorted((root/'jobs').glob('*/slurm.json')):
        print('SLURM_RECEIPT',path.parent.name,path.read_text().strip())
    run(['mariadb','--protocol=socket','-uroot'],secret_input="DROP DATABASE IF EXISTS rwslurm; DROP USER IF EXISTS 'rwslurm'@'localhost';\n",check=False)
    Path('/etc/slurm/slurmdbd.conf').unlink(missing_ok=True)
    run(['systemctl','stop','mariadb','munge'],check=False)
    print('Owned disposable services stopped; ephemeral runner teardown removes remaining state')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('setup','cleanup'))
    p.add_argument('--user',required=True);p.add_argument('--root',required=True);p.add_argument('--profile',required=True)
    a=p.parse_args()
    try:
        (setup if a.operation=='setup' else cleanup)(a)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        # A failed setup does not become success or trigger automatic reprovision.
        print(type(exc).__name__+': '+str(exc));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
