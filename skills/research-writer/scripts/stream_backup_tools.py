#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit chunked, disk-spooled SSH backups and read-only connection migration."""
from __future__ import annotations
import argparse
import getpass
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
if __name__ != 'stream_backup_receiver':
    _spec = importlib.util.spec_from_file_location('rw_stream_backup', ROOT / 'backup_tools.py')
    B = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(B)
    C, R = B.C, B.R
MAX_SMALL = 1024**2
MAX_BACKUP = 512 * 1024**2
MIN_CHUNK = 64 * 1024
MAX_CHUNK = 1024**2
MAGIC = b'RWSB\x00\x02\r\n'
PREFIX = struct.Struct('!8sIQ')
# Only bounded source metadata precedes the independently bounded binary frame.
BOOTSTRAP = """import sys,struct,json,types
s=sys.stdin.buffer
def exact(n):
 b=bytearray()
 while len(b)<n:
  x=s.read(n-len(b))
  if not x: raise ValueError('Truncated bootstrap')
  b.extend(x)
 return bytes(b)
n=struct.unpack('!I',exact(4))[0]
if n>1048576: raise ValueError('Bootstrap exceeds bound')
def pairs(p):
 d={}
 for k,v in p:
  if k in d: raise ValueError('Duplicate bootstrap key')
  d[k]=v
 return d
e=json.loads(exact(n),object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite bootstrap')))
if set(e)!={'checkpoint_source','backup_source','stream_source'}: raise ValueError('Invalid bootstrap')
c=types.ModuleType('checkpoint_tools');c.__file__='<checkpoint_tools.py>'
exec(compile(e['checkpoint_source'],c.__file__,'exec'),c.__dict__)
b=types.ModuleType('backup_receiver');b.__file__='<backup_tools.py>';b.C=c
exec(compile(e['backup_source'],b.__file__,'exec'),b.__dict__)
g={'__name__':'stream_backup_receiver','__file__':'<stream_backup_tools.py>','C':c,'B':b}
exec(compile(e['stream_source'],g['__file__'],'exec'),g)
g['receiver_main'](s,sys.stdout.buffer)
"""
canonical = B.canonical
decode = B.decode
private_directory = B.private_directory
write_new = B.write_new
new_parent = B.new_parent
result = B.result
fsync_file = B.fsync_file


def cap(value):
    if type(value) is not int or not 1024**2 <= value <= MAX_BACKUP or value % 1024**2:
        raise ValueError('Explicit backup cap must be whole MiB in 1..512MiB')
    return value


def chunk(value):
    if type(value) is not int or not MIN_CHUNK <= value <= MAX_CHUNK or value & (value - 1):
        raise ValueError('Explicit chunk_bytes must be a power of two in 64KiB..1MiB')
    return value


def profile(value, historical=False):
    """Historical profiles are normalized data; never touch old device paths."""
    extras = {'vault_id','max_backup_bytes','rpc_timeout_seconds'}
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int:
        raise ValueError('Invalid backup profile')
    version = value['schema_version']
    if version == 2: extras = extras | {'chunk_bytes'}
    elif version != 1 or not historical: raise ValueError('Current stream profile requires schema_version 2')
    if set(value) != B.R.PROFILE_FIELDS | extras:
        raise ValueError('Exact profile fields required; no credentials')
    base = {k:v for k,v in value.items() if k not in extras}
    old_config = base['ssh_config']; base['schema_version'] = 1
    if historical:
        if old_config is not None:
            B.R.text(old_config, 'historical ssh_config')
            if not (PurePosixPath(old_config).is_absolute() or PureWindowsPath(old_config).is_absolute()) or '..' in old_config.replace('\\','/').split('/'):
                raise ValueError('Historical SSH config must use explicit normalized absolute values')
        base['ssh_config'] = None
    p = B.R.profile(base)
    if historical:
        p['ssh_config'] = old_config
        if p['remote_root'] != value['remote_root']:
            raise ValueError('Historical profile must contain original normalized values')
    for name in ('expected_hostname','expected_user'): B.R.text(p[name], name)
    C.identifier(value['vault_id'])
    if version == 1: B.cap(value['max_backup_bytes'])
    else: cap(value['max_backup_bytes']); chunk(value['chunk_bytes'])
    if type(value['rpc_timeout_seconds']) is not int or not 5 <= value['rpc_timeout_seconds'] <= 300:
        raise ValueError('RPC timeout must be explicit 5..300 seconds')
    p.update({k:value[k] for k in extras}); p['schema_version'] = version
    if len(canonical(p))>64*1024: raise ValueError('Normalized profile exceeds 64KiB bound')
    return p


def descriptor(value):
    if not isinstance(value,dict) or set(value) != {'schema_version','backup_id','size','sha256','logical_sha256'}:
        raise ValueError('Exact backup descriptor fields required')
    if type(value['schema_version']) is not int or value['schema_version'] not in (1,2):
        raise ValueError('Unknown backup descriptor version')
    C.identifier(value['backup_id']); C.sha(value['sha256']); C.sha(value['logical_sha256'])
    if type(value['size']) is not int or not 1 <= value['size'] <= (B.MAX_BACKUP if value['schema_version']==1 else MAX_BACKUP):
        raise ValueError('Backup size outside absolute bound')
    return value


def write_all(stream, raw):
    view = memoryview(raw)
    while view:
        count = stream.write(view)
        if type(count) is not int or not 0 < count <= len(view): raise OSError('Short or invalid stream write')
        view = view[count:]


def exact(stream, size):
    out = bytearray()
    while len(out) < size:
        raw = stream.read(size-len(out))
        if not raw: raise ValueError('Truncated frame header')
        out.extend(raw)
    return bytes(out)


def read_header(stream, maximum=MAX_BACKUP):
    magic, size, count = PREFIX.unpack(exact(stream, PREFIX.size))
    if magic != MAGIC or not 1 <= size <= MAX_SMALL or count > maximum:
        raise ValueError('Frame magic/header/body bound mismatch')
    meta = decode(exact(stream,size))
    if not isinstance(meta,dict): raise ValueError('Frame metadata must be an object')
    return meta, count


def eof(stream):
    if stream.read(1): raise ValueError('Trailing bytes after frame')


def copy_body(source, target, count, chunk_bytes, expected=None):
    chunk(chunk_bytes)
    h = hashlib.sha256(); remaining = count
    while remaining:
        raw = source.read(min(remaining,chunk_bytes))
        if not raw: raise ValueError('Truncated frame body')
        if len(raw) > min(remaining,chunk_bytes): raise ValueError('Reader exceeded requested bound')
        write_all(target,raw); h.update(raw); remaining -= len(raw)
    if expected is not None and h.hexdigest() != expected: raise ValueError('Transfer checksum mismatch')
    return h.hexdigest()


def write_header(stream, meta, count):
    raw = canonical(meta)
    if len(raw)>MAX_SMALL or type(count) is not int or not 0<=count<=MAX_BACKUP:
        raise ValueError('Frame exceeds bound')
    write_all(stream,PREFIX.pack(MAGIC,len(raw),count)); write_all(stream,raw)


from contextlib import contextmanager
@contextmanager
def artifact_stream(path, maximum):
    path = C.no_symlinks(path); before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= maximum:
        raise ValueError('Bounded regular non-hardlinked database required')
    fd = os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        actual = os.fstat(fd)
        if (before.st_dev,before.st_ino) != (actual.st_dev,actual.st_ino) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValueError('Database changed during open')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            yield stream,actual.st_size
        after = os.fstat(fd); current = path.lstat()
        fields = lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_nlink)
        if fields(actual)!=fields(after) or fields(after)!=fields(current): raise ValueError('Database changed during read')
    finally: os.close(fd)


@contextmanager
def private_sink(path):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        yield stream


def hash_file(path, maximum, chunk_bytes):
    chunk(chunk_bytes)
    h = hashlib.sha256()
    with artifact_stream(path,maximum) as (stream,size):
        remaining = size
        while remaining:
            raw=stream.read(min(remaining,chunk_bytes))
            if not raw: raise ValueError('Database truncated')
            h.update(raw); remaining-=len(raw)
        eof(stream)
    return size,h.hexdigest()


def checked_artifact(store, d, maximum, chunk_bytes):
    descriptor(d)
    if d['size']>cap(maximum): raise ValueError('Backup exceeds selected cap')
    path=Path(store)/C.DB_NAME
    if hash_file(path,maximum,chunk_bytes)!=(d['size'],d['sha256']): raise ValueError('Backup bytes do not match immutable intent')
    drill=B.drill_store(store)
    if drill['logical_sha256']!=d['logical_sha256']: raise ValueError('Logical inventory mismatch')
    if hash_file(path,maximum,chunk_bytes)!=(d['size'],d['sha256']): raise ValueError('Backup changed during verification')
    return drill


def pins(p):
    return {k:p[k] for k in ('remote_root','vault_id','expected_hostname','expected_user')}


def make_intent(p,d,lineage=None):
    value={'schema_version':2,'profile_sha256':C.digest(canonical(p)),'profile':p,
           'destination':pins(p),'descriptor':d,'lineage':lineage}
    if len(canonical(value))>MAX_SMALL: raise ValueError('Intent exceeds metadata bound')
    return value


def prepare(p,store,backup_id,state_dir):
    p=profile(p); C.identifier(backup_id); destination=new_parent(state_dir); source=C.no_symlinks(store)
    if destination==source or source in destination.parents or destination in source.parents: raise ValueError('State must be separate from source')
    stage=Path(tempfile.mkdtemp(prefix='.rw-stream-prepare-',dir=destination.parent))
    try:
        C.backup(source,stage/'snapshot',True,max_backup_bytes=p['max_backup_bytes'])
        size,digest=hash_file(stage/'snapshot'/C.DB_NAME,p['max_backup_bytes'],p['chunk_bytes'])
        drill=B.drill_store(stage/'snapshot')
        if hash_file(stage/'snapshot'/C.DB_NAME,p['max_backup_bytes'],p['chunk_bytes'])!=(size,digest):
            raise ValueError('Prepared database changed during drill')
        d=descriptor({'schema_version':2,'backup_id':backup_id,'size':size,'sha256':digest,'logical_sha256':drill['logical_sha256']})
        fsync_file(stage/'snapshot'/C.DB_NAME)
        write_new(stage/'intent.json',canonical(make_intent(p,d))); C.fsync_directory(stage)
        C.rename_new(stage,destination); C.fsync_directory(destination.parent)
        return result('prepared',d,drill)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def load_intent(p,state_dir,historical=False):
    p=profile(p,historical=historical); root=private_directory(state_dir)
    entries=list(root.iterdir())
    if {x.name for x in entries}-{'intent.json','snapshot','attempt.json','upload-block.json'}: raise ValueError('Unexpected state entry')
    if any(x.is_symlink() for x in entries): raise ValueError('Symlink state entry forbidden')
    value=decode(C.regular(root/'intent.json',MAX_SMALL))
    if not isinstance(value,dict) or type(value.get('schema_version')) is not int: raise ValueError('Invalid intent')
    if value['schema_version']==1:
        if set(value)!={'schema_version','profile_sha256','descriptor'} or p['schema_version']!=1: raise ValueError('Invalid legacy intent')
    elif value['schema_version']==2:
        if set(value)!={'schema_version','profile_sha256','profile','destination','descriptor','lineage'}: raise ValueError('Invalid stream intent')
        if value['profile']!=p or value['destination']!=pins(p): raise ValueError('Saved profile/destination mismatch')
        lineage=value['lineage']
        if lineage is not None:
            if not isinstance(lineage,dict) or set(lineage)!={'old_intent_sha256','old_profile_sha256','new_profile_sha256'}: raise ValueError('Invalid lineage')
            for digest in lineage.values(): C.sha(digest)
            if lineage['new_profile_sha256']!=C.digest(canonical(p)): raise ValueError('Invalid new profile lineage')
            block=decode(C.regular(root/'upload-block.json',MAX_SMALL))
            if block!={'schema_version':2,'upload_permanently_blocked':True,'lineage':lineage}: raise ValueError('Missing permanent migration block')
    else: raise ValueError('Unknown intent version')
    if value['profile_sha256']!=C.digest(canonical(p)): raise ValueError('Profile changed since preparation')
    d=descriptor(value['descriptor'])
    if d['size']>p['max_backup_bytes']: raise ValueError('Intent exceeds selected cap')
    return root,d


def request(p,operation,d=None):
    return {'schema_version':2,'operation':operation,**pins(p),'max_backup_bytes':p['max_backup_bytes'],
            'chunk_bytes':p['chunk_bytes'],'descriptor':d}


def rpc(p,req,upload=None,download=None):
    """Single SSH process, regular file stdio, bounded buffers; disk O(artifact)."""
    sources={name:C.regular(ROOT/file,MAX_SMALL).decode() for name,file in
             [('checkpoint_source','checkpoint_tools.py'),('backup_source','backup_tools.py'),('stream_source','stream_backup_tools.py')]}
    bootstrap=canonical(sources)
    if len(bootstrap)>MAX_SMALL: raise ValueError('Bootstrap exceeds bound')
    argv=R.ssh_argv(p); argv[-1]=shlex.join([p['remote_python'],'-c',BOOTSTRAP])
    with tempfile.TemporaryDirectory(prefix='rw-stream-rpc-') as directory:
        folder=Path(directory).resolve(); inp,out,err=[folder/n for n in ('input','output','error')]
        with inp.open('xb') as target:
            write_all(target,struct.pack('!I',len(bootstrap))); write_all(target,bootstrap)
            d=req['descriptor']; count=d['size'] if upload is not None else 0
            write_header(target,req,count)
            if upload is not None:
                with artifact_stream(upload,p['max_backup_bytes']) as (source,size):
                    if size!=count: raise ValueError('Upload length changed')
                    copy_body(source,target,count,p['chunk_bytes'],d['sha256']); eof(source)
            target.flush(); os.fsync(target.fileno())
        with inp.open('rb') as source,out.open('xb') as stdout,err.open('xb') as stderr:
            child=subprocess.Popen(argv,stdin=source,stdout=stdout,stderr=stderr,shell=False,start_new_session=os.name=='posix')
            deadline=time.monotonic()+p['rpc_timeout_seconds']; reason=None
            try:
                while child.poll() is None:
                    if time.monotonic()>deadline: reason='SSH deadline; outcome uncertain'; break
                    if out.stat().st_size>p['max_backup_bytes']+MAX_SMALL+PREFIX.size or err.stat().st_size>MAX_SMALL:
                        reason='SSH output limit; outcome uncertain'; break
                    time.sleep(.025)
                if reason: raise R.TransportError(reason)
                child.wait()
            finally:
                if child.poll() is None:
                    if os.name=='posix':
                        try: os.killpg(child.pid,signal.SIGKILL)
                        except ProcessLookupError: pass
                    else: child.kill()
                    child.wait(timeout=5)
        if out.stat().st_size>p['max_backup_bytes']+MAX_SMALL+PREFIX.size or err.stat().st_size>MAX_SMALL:
            raise R.TransportError('SSH output limit; outcome uncertain')
        if child.returncode: raise R.TransportError('SSH failed; outcome uncertain: '+C.regular(err,MAX_SMALL).decode('utf-8','replace')[-1000:])
        with out.open('rb') as source:
            reply,count=read_header(source,p['max_backup_bytes'])
            fields={'schema_version','hostname','user','remote_root','vault_id','ok','receipt'}
            if set(reply)!=fields or type(reply['schema_version']) is not int or reply['schema_version']!=2 or type(reply['ok']) is not bool or reply['hostname']!=p['expected_hostname'] or reply['user']!=p['expected_user'] or reply['remote_root']!=p['remote_root'] or reply['vault_id']!=p['vault_id']:
                raise R.TransportError('Receiver identity/protocol mismatch; outcome uncertain')
            receipt=reply['receipt']
            if not isinstance(receipt,dict): raise ValueError('Invalid receipt')
            if not reply['ok']:
                if count: raise ValueError('Failure response has body')
                eof(source); raise ValueError('Receiver rejected: '+str(receipt.get('error','unknown'))[:1000])
            expected=d['size'] if req['operation']=='get' else 0
            if count!=expected or (d is not None and receipt.get('descriptor')!=d): raise ValueError('Readback descriptor/length mismatch')
            if count:
                if download is None: raise ValueError('Missing readback sink')
                with private_sink(download) as target:
                    copy_body(source,target,count,p['chunk_bytes'],d['sha256']); eof(source)
                    target.flush(); os.fsync(target.fileno())
            else: eof(source)
        return receipt


def init_remote(p,allow_transfer=False):
    p=profile(p)
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required')
    rpc(p,request(p,'init')); return {**result('vault_ready'),'vault_id':p['vault_id']}


def push(p,state_dir,allow_transfer=False):
    p=profile(p)
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required')
    root,d=load_intent(p,state_dir)
    if (root/'upload-block.json').exists(): raise ValueError('Migrated state permanently blocks upload; verify/fetch only')
    if (root/'attempt.json').exists(): raise ValueError('Upload already attempted; use read-only verify/fetch')
    checked_artifact(root/'snapshot',d,p['max_backup_bytes'],p['chunk_bytes'])
    write_new(root/'attempt.json',canonical({'schema_version':2,'descriptor':d})); C.fsync_directory(root)
    try:
        rpc(p,request(p,'put',d),upload=root/'snapshot'/C.DB_NAME)
        return verify(p,root)
    except Exception as exc: raise R.TransportError('Backup outcome uncertain; reconcile with verify/fetch: '+str(exc)[:1000]) from exc


def receive(p,d,destination):
    destination=new_parent(destination); stage=Path(tempfile.mkdtemp(prefix='.rw-stream-fetch-',dir=destination.parent))
    try:
        rpc(p,request(p,'get',d),download=stage/C.DB_NAME)
        drill=checked_artifact(stage,d,p['max_backup_bytes'],p['chunk_bytes'])
        fsync_file(stage/C.DB_NAME); C.fsync_directory(stage)
        C.rename_new(stage,destination); C.fsync_directory(destination.parent)
        return drill
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(p,state_dir):
    p=profile(p); root,d=load_intent(p,state_dir)
    with tempfile.TemporaryDirectory(prefix='rw-stream-readback-') as directory:
        drill=receive(p,d,Path(directory).resolve()/'store')
    return result('verified',d,{**drill,'fresh_ssh_readback':True})


def fetch(p,state_dir,destination,allow_restore=False):
    p=profile(p)
    if not allow_restore: raise ValueError('Explicit --allow-restore required')
    root,d=load_intent(p,state_dir); destination=new_parent(destination)
    if destination==root or root in destination.parents or destination in root.parents: raise ValueError('Fetch destination must be separate from state')
    drill=receive(p,d,destination)
    return {**result('fetched',d,{**drill,'fresh_ssh_readback':True}),'destination':str(destination)}


def migrate_profile(source_profile,p,state_dir,destination,allow_migrate=False):
    if not allow_migrate: raise ValueError('Explicit --allow-migrate required')
    old=profile(source_profile,historical=True); p=profile(p)
    root,d=load_intent(old,state_dir,historical=True); destination=new_parent(destination)
    if destination==root or root in destination.parents or destination in root.parents: raise ValueError('Migration destination must be separate from old state')
    if pins(old)!=pins(p): raise ValueError('Migration cannot change host/user/root/vault destination pins')
    if d['size']>p['max_backup_bytes']: raise ValueError('New cap cannot fit artifact')
    # A retained snapshot is checked; the immutable intent also supports
    # recovery after source/staging loss, with fresh remote bytes as authority.
    if (root/'snapshot').exists():
        checked_artifact(root/'snapshot',d,old['max_backup_bytes'],old.get('chunk_bytes',MIN_CHUNK))
    old_intent=C.regular(root/'intent.json',MAX_SMALL)
    stage=Path(tempfile.mkdtemp(prefix='.rw-stream-migrate-',dir=destination.parent))
    try:
        drill=receive(p,d,stage/'snapshot')
        lineage={'old_intent_sha256':C.digest(old_intent),'old_profile_sha256':C.digest(canonical(old)),
                 'new_profile_sha256':C.digest(canonical(p))}
        write_new(stage/'intent.json',canonical(make_intent(p,d,lineage)))
        write_new(stage/'upload-block.json',canonical({'schema_version':2,'upload_permanently_blocked':True,'lineage':lineage}))
        if (root/'attempt.json').exists(): write_new(stage/'attempt.json',C.regular(root/'attempt.json',MAX_SMALL))
        C.fsync_directory(stage); C.rename_new(stage,destination); C.fsync_directory(destination.parent)
        return {**result('profile_migrated_read_only',d,{**drill,'fresh_ssh_readback':True}),'lineage':lineage,'upload_permanently_blocked':True,'destination':str(destination)}
    finally:
        if stage.exists(): shutil.rmtree(stage)


def read_archive(root,d,maximum,chunk_bytes):
    target=private_directory(root/'backups'/d['backup_id'])
    if {x.name for x in target.iterdir()}!={'descriptor.json','store'}: raise ValueError('Unexpected archive entry')
    if decode(C.regular(target/'descriptor.json',MAX_SMALL))!=d: raise ValueError('Immutable ID has different descriptor')
    drill=checked_artifact(target/'store',d,maximum,chunk_bytes)
    return target/'store'/C.DB_NAME,drill


def receiver(req,count,source):
    if os.name!='posix': raise ValueError('Receiver requires POSIX filesystem')
    fields={'schema_version','operation','remote_root','vault_id','expected_hostname','expected_user','max_backup_bytes','chunk_bytes','descriptor'}
    if set(req)!=fields or type(req['schema_version']) is not int or req['schema_version']!=2 or req['operation'] not in ('init','put','get'): raise ValueError('Invalid stream request')
    if req['expected_hostname']!=socket.gethostname() or req['expected_user']!=getpass.getuser(): raise ValueError('Receiver host/user mismatch')
    maximum=cap(req['max_backup_bytes']); chunk_bytes=chunk(req['chunk_bytes']); C.identifier(req['vault_id'])
    name=req['remote_root']
    if not isinstance(name,str) or not PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or str(PurePosixPath(name))!=name or len(PurePosixPath(name).parts)<3: raise ValueError('Absolute dedicated vault root required')
    root=C.outside_skill(name)
    if any((p/'SKILL.md').is_file() for p in (root,*root.parents)): raise ValueError('Remote vault must be outside skill folders')
    if req['operation']=='init':
        if req['descriptor'] is not None or count: raise ValueError('Invalid init payload')
        eof(source); return B.init_vault(root,req['vault_id']),None
    d=descriptor(req['descriptor'])
    if d['size']>maximum or count!=(d['size'] if req['operation']=='put' else 0): raise ValueError('Payload length/cap mismatch')
    with B.vault_lock(root):
        B.vault(root,req['vault_id'])
        if req['operation']=='get':
            eof(source); path,drill=read_archive(root,d,maximum,chunk_bytes)
            return result('verified',d,drill),path
        stage=root/('.stage-'+uuid.uuid4().hex); stage.mkdir(mode=0o700)
        try:
            (stage/'store').mkdir(mode=0o700)
            with private_sink(stage/'store'/C.DB_NAME) as target:
                copy_body(source,target,count,chunk_bytes,d['sha256']); eof(source)
                target.flush(); os.fsync(target.fileno())
            drill=checked_artifact(stage/'store',d,maximum,chunk_bytes)
            destination=root/'backups'/d['backup_id']
            if destination.exists():
                read_archive(root,d,maximum,chunk_bytes)
                return result('already_present',d,drill),None
            write_new(stage/'descriptor.json',canonical(d)); fsync_file(stage/'store'/C.DB_NAME)
            C.fsync_directory(stage/'store'); C.fsync_directory(stage)
            C.rename_new(stage,destination)
            C.fsync_directory(root/'backups'); C.fsync_directory(root)
            return result('stored',d,drill),None
        finally:
            if stage.exists(): shutil.rmtree(stage)


def receiver_main(source=None,target=None):
    source=source or sys.stdin.buffer; target=target or sys.stdout.buffer
    req={}; path=None
    try:
        req,count=read_header(source)
        receipt,path=receiver(req,count,source); ok=True
    except Exception as exc:
        receipt={'state':'failed_or_uncertain','error':str(exc)[:1500],'execution_clearance':'not_granted'}; ok=False
    identity={'schema_version':2,'hostname':socket.gethostname(),'user':getpass.getuser(),
              'remote_root':req.get('remote_root'),'vault_id':req.get('vault_id'),'ok':ok,'receipt':receipt}
    # Once output starts, errors propagate: never append a second valid-looking frame.
    count=receipt['descriptor']['size'] if path is not None else 0
    write_header(target,identity,count)
    if path is not None:
        with artifact_stream(path,req['max_backup_bytes']) as (stream,size):
            if size!=count: raise ValueError('Readback length changed')
            copy_body(stream,target,count,req['chunk_bytes'],receipt['descriptor']['sha256']); eof(stream)
    target.flush()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='operation',required=True)
    for op in ('init-remote','prepare','push','verify','fetch','migrate-profile'):
        cmd=sub.add_parser(op); cmd.add_argument('--profile',required=True); cmd.add_argument('--report',required=True)
        if op!='init-remote': cmd.add_argument('--state-dir',required=True)
        if op=='prepare': cmd.add_argument('--store',required=True); cmd.add_argument('--backup-id',required=True)
        if op in ('init-remote','push'): cmd.add_argument('--allow-transfer',action='store_true')
        if op=='fetch': cmd.add_argument('--destination',required=True); cmd.add_argument('--allow-restore',action='store_true')
        if op=='migrate-profile':
            cmd.add_argument('--source-profile',required=True); cmd.add_argument('--destination',required=True); cmd.add_argument('--allow-migrate',action='store_true')
    args=parser.parse_args(argv); report=None; safe=False
    try:
        report=C.outside_skill(args.report)
        if report.exists(): raise ValueError('Report must be new')
        private_directory(report.parent)
        for name in ('store','state_dir','destination'):
            if getattr(args,name,None) is not None:
                protected=C.no_symlinks(getattr(args,name))
                if report==protected or protected in report.parents: raise ValueError('Report must be separate from source/state/destination')
        safe=True; p=profile(decode(C.regular(args.profile,MAX_SMALL)))
        if args.operation=='init-remote': reply=init_remote(p,args.allow_transfer)
        elif args.operation=='prepare': reply=prepare(p,args.store,args.backup_id,args.state_dir)
        elif args.operation=='push': reply=push(p,args.state_dir,args.allow_transfer)
        elif args.operation=='verify': reply=verify(p,args.state_dir)
        elif args.operation=='fetch': reply=fetch(p,args.state_dir,args.destination,args.allow_restore)
        else: reply=migrate_profile(decode(C.regular(args.source_profile,MAX_SMALL)),p,args.state_dir,args.destination,args.allow_migrate)
        B.publish_report(report,canonical({'schema_version':2,'ok':True,**reply})+b'\n'); return 0
    except Exception as exc:
        reply={'schema_version':2,'ok':False,'state':'failed_or_uncertain','error':str(exc)[:1500],'execution_clearance':'not_granted'}
        try:
            if safe and report is not None and not report.exists(): write_new(report,canonical(reply)+b'\n')
        except Exception: pass
        print(canonical(reply).decode(),file=sys.stderr); return 2


if __name__=='__main__': raise SystemExit(main())
