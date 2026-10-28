#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit bounded OpenSSH job lifecycle. Profile data is not authorization."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
MAX_FILE = 8 * 1024 * 1024
MAX_INPUT = 16 * 1024 * 1024
MAX_RPC = 32 * 1024 * 1024
MAX_ERROR = 1024 * 1024
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
STATES = TERMINAL | {'prepared', 'launching', 'running', 'uncertain', 'not_found'}
PROFILE_FIELDS = {'schema_version','ssh_alias','ssh_config','remote_python','remote_root',
                  'expected_hostname','expected_user','connect_timeout_seconds'}
BOOTSTRAP = ("import io,json,sys; e=json.load(sys.stdin); "
             "sys.stdin=io.TextIOWrapper(io.BytesIO(json.dumps(e['request']).encode('utf-8')),encoding='utf-8'); "
             "exec(compile(e['source'],'<research-writer-worker>','exec'),{'__name__':'__main__'})")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def pairs(values):
    out = {}
    for key, value in values:
        if key in out:
            raise ValueError('Duplicate JSON key: ' + key)
        out[key] = value
    return out


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + x)))


def read_bytes(path, maximum=MAX_RPC):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Input exceeds byte limit')
    return raw


def read_json(path, maximum=MAX_ERROR):
    return decode_json(read_bytes(path, maximum).decode('utf-8'))


def save(path, data, exclusive=False):
    path = Path(path)
    raw = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if exclusive:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(raw)
        return
    fd, temp = tempfile.mkstemp(prefix='.rw-state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(raw)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def text(value, name):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or '\n' in value or '\r' in value:
        raise ValueError(name + ' must be a nonempty single-line string')
    return value


def relative(value):
    text(value, 'relative path')
    p, w = PurePosixPath(value), PureWindowsPath(value)
    if p.is_absolute() or w.drive or '\\' in value or str(p) != value or any(x in ('..', '.') for x in value.split('/')) or value.endswith('/'):
        raise ValueError('Confined POSIX relative path required')
    if any(x in ('.ssh','.aws','.git','.codex') or x == '.env' or x.startswith('.env.') for x in p.parts):
        raise ValueError('Credential/configuration path not permitted for transfer')
    return value


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('Job ID must be 32 lower-case hexadecimal characters')
    return value


def profile(value):
    if not isinstance(value, dict) or set(value) - PROFILE_FIELDS or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid profile schema or unknown fields; store no credentials')
    p = dict(value)
    alias = p.get('ssh_alias')
    if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,252}', alias):
        raise ValueError('Expected an existing plain SSH alias, not options or a URL')
    python = text(p.get('remote_python'), 'remote_python')
    if len(python) > 512 or not (re.fullmatch(r'python3(?:\.\d+)?', python) or
                               PurePosixPath(python).is_absolute() and '..' not in PurePosixPath(python).parts):
        raise ValueError('Remote Python must be a program token or absolute POSIX path')
    root = text(p.get('remote_root'), 'remote_root')
    if not PurePosixPath(root).is_absolute() or len(PurePosixPath(root).parts) < 3 or '..' in PurePosixPath(root).parts:
        raise ValueError('Select an absolute dedicated POSIX remote job root')
    p['remote_root'] = str(PurePosixPath(root))
    for name in ('expected_hostname','expected_user'):
        p.setdefault(name, None)
        if p[name] is not None:
            text(p[name], name)
    p.setdefault('ssh_config', None)
    if p['ssh_config'] is not None:
        conf = Path(text(p['ssh_config'], 'ssh_config')).expanduser().absolute()
        if not conf.is_file():
            raise ValueError('Explicit SSH config does not exist')
        p['ssh_config'] = str(conf)
    p.setdefault('connect_timeout_seconds', 10)
    if type(p['connect_timeout_seconds']) is not int or not 1 <= p['connect_timeout_seconds'] <= 30:
        raise ValueError('Connection timeout must be 1..30 seconds')
    return p


def validate_manifest(m):
    fields = {'schema_version','job_id','argv','inputs','outputs','resources','required_device'}
    if not isinstance(m, dict) or set(m) != fields or type(m.get('schema_version')) is not int or m['schema_version'] != 1:
        raise ValueError('Manifest fields/schema do not match version 1')
    job_id(m['job_id'])
    argv = m['argv']
    if not isinstance(argv, list) or not 1 <= len(argv) <= 128 or any(not isinstance(a,str) or not a or '\x00' in a or len(a)>8192 for a in argv):
        raise ValueError('A bounded explicit argv array is required')
    if m['required_device'] != 'cpu':
        raise ValueError('Only task-bounded CPU execution is supported in this release')
    r = m['resources']
    limits = {'wall_seconds':(1,3600),'max_output_bytes':(1,MAX_INPUT),
              'max_log_bytes':(1,MAX_ERROR),'threads':(1,16)}
    if not isinstance(r,dict) or set(r) != set(limits):
        raise ValueError('Exact resource fields required')
    for name, (low, high) in limits.items():
        if type(r[name]) is not int or not low <= r[name] <= high:
            raise ValueError('Resource bound out of range: ' + name)
    if not isinstance(m['inputs'],list) or len(m['inputs'])>32 or not isinstance(m['outputs'],list) or not 1 <= len(m['outputs']) <= 32:
        raise ValueError('Bounded inputs and explicit output names required')
    names = []
    for item in m['inputs']:
        if not isinstance(item,dict) or set(item) != {'source','destination','sha256'}:
            raise ValueError('Invalid input record')
        relative(item['source']); names.append(relative(item['destination']))
        if not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']):
            raise ValueError('Input needs an exact lower-case SHA-256')
    outputs = [relative(n) for n in m['outputs']]
    if '.collection.json' in outputs:
        raise ValueError('Reserved collection metadata name')
    if len(set(names))!=len(names) or len(set(outputs))!=len(outputs) or set(names)&set(outputs):
        raise ValueError('Input/output paths must be unique and nonoverlapping')
    # Reject file/directory collisions as well as exact duplicate names.
    allnames = names + outputs
    if any(a != b and b.startswith(a + '/') for a in allnames for b in allnames):
        raise ValueError('Input/output file-directory paths overlap')
    return m


def input_files(manifest, base):
    root = Path(base).resolve()
    out, total = [], 0
    for item in manifest['inputs']:
        p = root / relative(item['source'])
        if not p.resolve().is_relative_to(root) or any(x.is_symlink() for x in [p, *p.parents] if x != root and x.is_relative_to(root)):
            raise ValueError('Symlink or escaping input path')
        if not p.is_file():
            raise ValueError('Input must be a regular file')
        raw = read_bytes(p, MAX_FILE); total += len(raw)
        if total > MAX_INPUT or digest(raw) != item['sha256']:
            raise ValueError('Input total size/hash mismatch')
        out.append({'path':item['destination'],'sha256':item['sha256'],
                    'data':base64.b64encode(raw).decode('ascii')})
    return out


def ssh_argv(p):
    options = ['BatchMode=yes','StrictHostKeyChecking=yes',
               'ConnectTimeout='+str(p['connect_timeout_seconds']),'ConnectionAttempts=1',
               'ServerAliveInterval=5','ServerAliveCountMax=2','ForwardAgent=no',
               'ForwardX11=no','ClearAllForwardings=yes','PermitLocalCommand=no',
               'ControlMaster=no','ControlPath=none','RemoteCommand=none']
    argv = ['ssh','-T']
    for opt in options:
        argv.extend(['-o',opt])
    if p['ssh_config']:
        argv.extend(['-F',p['ssh_config']])
    argv.extend([p['ssh_alias'], shlex.join([p['remote_python'],'-c',BOOTSTRAP])])
    return argv


class TransportError(RuntimeError):
    pass


def rpc(p, request):
    source = read_bytes(ROOT / 'remote_worker.py', MAX_ERROR).decode('utf-8')
    payload = canonical({'source':source,'request':request})
    if len(payload)>MAX_RPC:
        raise ValueError('RPC input too large')
    with tempfile.TemporaryDirectory(prefix='rw-ssh-') as folder:
        root=Path(folder); incoming=root/'request.json'; incoming.write_bytes(payload)
        stdout, stderr=root/'stdout',root/'stderr'
        with incoming.open('rb') as inp, stdout.open('wb') as out, stderr.open('wb') as err:
            child=subprocess.Popen(ssh_argv(p),stdin=inp,stdout=out,stderr=err,
                                   shell=False,start_new_session=os.name=='posix')
            deadline=time.monotonic()+p['connect_timeout_seconds']+30
            reason=None
            while child.poll() is None:
                if time.monotonic()>deadline:
                    reason='SSH RPC timeout; remote outcome may be uncertain';break
                if stdout.stat().st_size>MAX_RPC or stderr.stat().st_size>MAX_ERROR:
                    reason='SSH RPC output limit; remote outcome may be uncertain';break
                time.sleep(.05)
            if reason:
                if os.name=='posix':
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                else:child.kill()
                child.wait(timeout=5)
                raise TransportError(reason)
            child.wait()
        if stdout.stat().st_size>MAX_RPC or stderr.stat().st_size>MAX_ERROR:
            raise TransportError('SSH RPC output limit; remote outcome may be uncertain')
        error=read_bytes(stderr,MAX_ERROR).decode('utf-8','replace')
        if child.returncode:
            raise TransportError('SSH exited '+str(child.returncode)+': '+error[-2000:])
        try:
            response=decode_json(read_bytes(stdout,MAX_RPC).decode('utf-8'))
        except (ValueError,UnicodeError) as exc:
            raise TransportError('Malformed remote JSON; outcome may be uncertain') from exc
    validate_response(response,p,request)
    return response


def validate_response(r,p,request):
    if not isinstance(r,dict) or type(r.get('protocol')) is not int or r['protocol']!=1 or type(r.get('ok')) is not bool:
        raise TransportError('Invalid protocol response')
    ident=r.get('identity')
    if not isinstance(ident,dict) or not isinstance(ident.get('hostname'),str) or not isinstance(ident.get('user'),str):
        raise TransportError('Missing remote identity')
    for key,field in [('expected_hostname','hostname'),('expected_user','user')]:
        if p[key] is not None and ident[field]!=p[key]:
            raise TransportError('Remote identity mismatch: '+field)
    expected=request['operation']
    if expected=='inspect':
        if r.get('status')!='inspected':raise TransportError('Invalid inspection status')
    else:
        if r.get('job_id')!=request['job_id'] or r.get('manifest_sha256')!=request['manifest_sha256'] or r.get('status') not in STATES:
            raise TransportError('Job identity/hash/status mismatch')
    return r


@contextmanager
def local_lock(state_dir, identity):
    root=Path(state_dir);root.mkdir(parents=True,exist_ok=True)
    lock=root/('.'+job_id(identity)+'.lock')
    # Keep the inode: unlinking an active lock would let a new caller lock a
    # different file. OS locks release on close and abrupt process death.
    stream=lock.open('a+b')
    acquired=False
    try:
        stream.seek(0,os.SEEK_END)
        if stream.tell()==0:
            stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError as exc:
            raise ValueError('Job is owned by another live local operation; do not replace its lock file') from exc
        yield root/(identity+'.json')
    finally:
        if acquired:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()


def base_request(p,operation,identity=None,manifest_hash=None):
    return {'protocol':1,'operation':operation,'remote_root':p['remote_root'],
            'expected_hostname':p['expected_hostname'],'expected_user':p['expected_user'],
            'job_id':identity,'manifest_sha256':manifest_hash}


def pinned(p):
    if not p['expected_hostname'] or not p['expected_user']:
        raise ValueError('Pin expected_hostname and expected_user after inspection before job operations')


def invoke(p,request,state,state_path):
    try:
        result=rpc(p,request)
    except (TransportError,OSError,subprocess.SubprocessError) as exc:
        state.update(status='uncertain',last_error=str(exc),uncertain_operation=request['operation'])
        save(state_path,state)
        raise TransportError(str(exc)) from exc
    # Keep restart metadata bounded: artifact/log bytes belong in returned
    # collection data, never in the durable state receipt.
    receipt={k:v for k,v in result.items() if k not in ('files','logs')}
    if isinstance(result.get('files'),list):
        receipt['files']=[{'path':f.get('path'),'sha256':f.get('sha256')} for f in result['files'] if isinstance(f,dict)]
    if isinstance(result.get('logs'),dict):
        receipt['logs']={name:{'sha256':entry.get('sha256')} for name,entry in result['logs'].items() if isinstance(entry,dict)}
    state.update(status=result['status'],last_remote=receipt,last_error=None)
    state.pop('uncertain_operation',None)
    save(state_path,state)
    return result


def load_state(path,p,identity):
    state=read_json(path,MAX_RPC)
    if not isinstance(state,dict) or state.get('job_id')!=identity or state.get('profile_sha256')!=digest(canonical(p)):
        raise ValueError('Saved state/profile binding differs')
    validate_manifest(state.get('manifest'))
    if digest(canonical(state['manifest']))!=state.get('manifest_sha256'):
        raise ValueError('Saved manifest binding differs')
    if not isinstance(state.get('worker_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',state['worker_sha256']):
        raise ValueError('Saved controller source binding is missing')
    return state


def prepare(p,manifest_path,state_dir,allow_transfer=False):
    pinned(p)
    if not allow_transfer:raise ValueError('Explicit --allow-transfer required')
    m=validate_manifest(read_json(manifest_path));files=input_files(m,Path(manifest_path).resolve().parent)
    identity=m['job_id'];h=digest(canonical(m))
    worker=read_bytes(ROOT/'remote_worker.py',MAX_ERROR).decode('utf-8')
    with local_lock(state_dir,identity) as state_path:
        if state_path.exists():raise FileExistsError('Job already has local state; reconcile status instead of preparing again')
        state={'schema_version':1,'job_id':identity,'manifest_sha256':h,'manifest':m,
               'profile_sha256':digest(canonical(p)),'worker_sha256':digest(worker.encode('utf-8')),
               'status':'prepare_attempted','submit_attempted':False}
        save(state_path,state,exclusive=True)
        request=base_request(p,'prepare',identity,h)
        request.update(manifest=m,files=files,worker_source=worker)
        return invoke(p,request,state,state_path)


def operate(p,operation,identity,state_dir,allow_execute=False,allow_cancel=False,destination=None):
    pinned(p);job_id(identity)
    with local_lock(state_dir,identity) as state_path:
        state=load_state(state_path,p,identity)
        if operation=='submit':
            if not allow_execute:raise ValueError('Explicit --allow-execute required')
            if state.get('submit_attempted') or state.get('status')!='prepared':
                raise ValueError('Submission already attempted or job is not prepared; never resubmit an uncertain job')
            if digest(read_bytes(ROOT/'remote_worker.py',MAX_ERROR))!=state['worker_sha256']:
                raise ValueError('Controller source changed since preparation; reconcile before execution')
            state.update(submit_attempted=True,status='launching')
            save(state_path,state)
        elif operation=='cancel':
            if not allow_cancel:raise ValueError('Explicit --allow-cancel required')
            state['cancel_attempted']=True;save(state_path,state)
        request=base_request(p,operation,identity,state['manifest_sha256'])
        result=invoke(p,request,state,state_path)
        if operation=='collect' and result['ok']:
            collected=collect_files(result,state['manifest'],destination)
            state['collection']=collected;save(state_path,state)
            result={**result,'collection':collected}
        return result


def collect_files(result,manifest,destination):
    if destination is None or result['status'] not in TERMINAL:
        raise ValueError('Collect requires a new destination and a terminal job')
    target=Path(destination).absolute()
    if target.exists() or target.is_symlink():raise FileExistsError('Collection destination already exists')
    if not target.parent.is_dir():raise ValueError('Collection parent must exist')
    files=result.get('files')
    if not isinstance(files,list):raise ValueError('Missing artifact list')
    expected=set(manifest['outputs']);seen=set();decoded=[];total=0
    for item in files:
        if not isinstance(item,dict) or set(item)!={'path','sha256','data'}:
            raise ValueError('Malformed collected artifact')
        name=relative(item['path'])
        if name not in expected or name in seen:raise ValueError('Unexpected/duplicate artifact')
        raw=base64.b64decode(item['data'],validate=True);total+=len(raw)
        if total>manifest['resources']['max_output_bytes'] or digest(raw)!=item['sha256']:
            raise ValueError('Collected artifact size/hash mismatch')
        decoded.append((name,raw));seen.add(name)
    missing=sorted(expected-seen)
    if result['status']=='succeeded' and (missing or result.get('partial') is not False):
        raise ValueError('Success cannot omit expected artifacts or be partial')
    partial=result['status']!='succeeded' or bool(missing)
    guard=local_lock(target.parent,digest(('collection:'+str(target)).encode('utf-8'))[:32])
    guard.__enter__()
    staged=None
    try:
        if target.exists() or target.is_symlink():raise FileExistsError('Collection destination already exists')
        staged=Path(tempfile.mkdtemp(prefix='.rw-collection-',dir=target.parent))
        for name,raw in decoded:
            path=staged/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        summary={'status':result['status'],'partial':partial,'missing':missing,
                 'files':[{'path':name,'sha256':digest(raw),'bytes':len(raw)} for name,raw in decoded]}
        save(staged/'.collection.json',summary,exclusive=True)
        if target.exists() or target.is_symlink():raise FileExistsError('Collection destination appeared')
        staged.rename(target);staged=None
        return {**summary,'destination':str(target)}
    finally:
        if staged is not None:shutil.rmtree(staged)
        guard.__exit__(None,None,None)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='operation',required=True)
    for op in ('inspect','prepare','submit','status','recover','collect','cancel'):
        cmd=commands.add_parser(op);cmd.add_argument('--profile',required=True);cmd.add_argument('--output',required=True)
        if op=='prepare':cmd.add_argument('--manifest',required=True);cmd.add_argument('--allow-transfer',action='store_true')
        if op!='inspect':cmd.add_argument('--state-dir',required=True)
        if op not in ('inspect','prepare'):cmd.add_argument('--job-id',required=True)
        if op=='submit':cmd.add_argument('--allow-execute',action='store_true')
        if op=='cancel':cmd.add_argument('--allow-cancel',action='store_true')
        if op=='collect':cmd.add_argument('--destination',required=True)
    args=parser.parse_args(argv)
    try:
        if Path(args.output).exists() or Path(args.output).is_symlink():raise FileExistsError('Output report exists')
        p=profile(read_json(args.profile))
        if args.operation=='inspect':result=rpc(p,base_request(p,'inspect'))
        elif args.operation=='prepare':result=prepare(p,args.manifest,args.state_dir,args.allow_transfer)
        else:result=operate(p,args.operation,args.job_id,args.state_dir,
                           getattr(args,'allow_execute',False),getattr(args,'allow_cancel',False),getattr(args,'destination',None))
        save(args.output,result,exclusive=True)
        return 0 if result['ok'] else 2
    except (OSError,ValueError,TypeError,KeyError,TransportError,subprocess.SubprocessError) as exc:
        failure={'protocol':1,'ok':False,'status':'failed','error':str(exc)}
        if not Path(args.output).exists() and not Path(args.output).is_symlink():
            try:save(args.output,failure,exclusive=True)
            except OSError:pass
        print(json.dumps(failure),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
