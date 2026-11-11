#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run authorized CPU jobs through an existing SSH alias for a native Windows worker."""
from __future__ import annotations
import argparse
import base64
from pathlib import Path, PureWindowsPath
import re
import subprocess

import remote_tools as core
import windows_worker as worker
from transport_common import CaptureError, run_bounded, save_state

HERE = Path(__file__).resolve().parent

# No profile, manifest, path, or request value is interpolated into this script.
# Use .NET byte streams because Windows PowerShell 5.1's text pipeline can recode UTF-8.
PS_BOOTSTRAP = r'''$ErrorActionPreference='Stop'
$stdin = [Console]::OpenStandardInput()
$header = New-Object System.IO.MemoryStream
while (($byte = $stdin.ReadByte()) -ne 10) {
  if ($byte -lt 0 -or $header.Length -ge 4096) { throw 'Invalid RPC header' }
  $header.WriteByte([byte]$byte)
}
$count = $header.Length + 1
$raw = [System.Text.UTF8Encoding]::new($false, $true).GetString($header.ToArray())
$header.Dispose()
$e = ConvertFrom-Json -InputObject $raw
if ($null -eq $e.python_path -or $e.python_path -notmatch '^[A-Za-z]:\\') { throw 'Missing absolute Python path' }
if (($e.body_bytes -isnot [int] -and $e.body_bytes -isnot [long]) -or
    $e.body_bytes -lt 1 -or $e.body_bytes -gt (33554432 - $count)) { throw 'Invalid RPC body length' }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = [string]$e.python_path
$start.Arguments = ('-I -c "import io,json,os,sys; ' +
  'n=int(os.environ.pop(''RW_WINDOWS_BODY_BYTES'')); raw=sys.stdin.buffer.read(n); ' +
  'len(raw)==n or sys.exit(''Incomplete RPC body''); e=json.loads(raw.decode(''utf-8'')); ' +
  'sys.stdin=io.TextIOWrapper(io.BytesIO(json.dumps(e[''request'']).encode(''utf-8'')),encoding=''utf-8''); ' +
  'exec(compile(e[''source''],''<windows-worker>'',''exec''),{''__name__'':''__main__''})"')
$start.EnvironmentVariables['RW_WINDOWS_BODY_BYTES'] = [string]$e.body_bytes
$start.UseShellExecute = $false
# Python inherits the existing SSH stdin handle at the byte after the header.
# Redirecting output enables explicit standard-handle assignment in .NET.
$start.RedirectStandardInput = $false
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($start)
try {
  $stdoutTask = $p.StandardOutput.BaseStream.CopyToAsync([Console]::OpenStandardOutput())
  $stderrTask = $p.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError())
  $p.WaitForExit()
  [void]$stdoutTask.GetAwaiter().GetResult()
  [void]$stderrTask.GetAwaiter().GetResult()
  exit $p.ExitCode
} finally {
  if (-not $p.HasExited) { $p.Kill() }
  $p.Dispose()
}
'''
ENCODED = base64.b64encode(PS_BOOTSTRAP.encode('utf-16le')).decode('ascii')
PROFILE_FIELDS = {'schema_version','ssh_alias','ssh_config','remote_python','remote_root',
                  'expected_hostname','expected_user','connect_timeout_seconds'}
STATES = core.TERMINAL | {'prepared','launching','running','uncertain','not_found'}


def windows_path(value, label):
    core.text(value, label)
    p = PureWindowsPath(value)
    if (len(value) > 512 or not re.fullmatch(r'[A-Za-z]:', p.drive) or not p.is_absolute()
            or not re.match(r'^[A-Za-z]:\\', value)
            or '..' in p.parts or any(c in value for c in '"\';&|^`$%<>?*')
            or any(ord(c) < 32 for c in value)
            or (label == 'remote_python' and p.suffix.casefold() != '.exe')):
        raise ValueError(label + ' must be a bounded absolute local-drive path')
    if len(p.parts) > 1:
        worker.relative('/'.join(p.parts[1:]))
    return value


def profile(value):
    if not isinstance(value, dict) or set(value) - PROFILE_FIELDS or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid profile schema or unknown fields')
    p = dict(value)
    if not isinstance(p.get('ssh_alias'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,252}', p['ssh_alias']):
        raise ValueError('Plain existing SSH alias required')
    p['remote_python'] = windows_path(p.get('remote_python'), 'remote_python')
    p['remote_root'] = windows_path(p.get('remote_root'), 'remote_root')
    if PureWindowsPath(p['remote_root']) == PureWindowsPath(PureWindowsPath(p['remote_root']).anchor):
        raise ValueError('Dedicated remote job root required')
    for field in ('expected_hostname','expected_user'):
        p.setdefault(field, None)
        if p[field] is not None: core.text(p[field], field)
    p.setdefault('ssh_config', None)
    if p['ssh_config'] is not None:
        path = Path(core.text(p['ssh_config'], 'ssh_config')).expanduser().absolute()
        if not path.is_file(): raise ValueError('SSH config does not exist')
        p['ssh_config'] = str(path)
    p.setdefault('connect_timeout_seconds', 10)
    if type(p['connect_timeout_seconds']) is not int or not 1 <= p['connect_timeout_seconds'] <= 30:
        raise ValueError('Connection timeout must be 1..30 seconds')
    return p


def ssh_argv(p):
    opts = ['BatchMode=yes','StrictHostKeyChecking=yes','ConnectTimeout='+str(p['connect_timeout_seconds']),
            'ConnectionAttempts=1','UpdateHostKeys=no','AddKeysToAgent=no','ServerAliveInterval=5','ServerAliveCountMax=2','ForwardAgent=no',
            'ForwardX11=no','ClearAllForwardings=yes','PermitLocalCommand=no','ControlMaster=no',
            'ControlPath=none','RemoteCommand=none','RequestTTY=no','StdinNull=no']
    argv = ['ssh','-T']
    for opt in opts: argv.extend(['-o',opt])
    if p['ssh_config']: argv.extend(['-F',p['ssh_config']])
    return argv + [p['ssh_alias'], 'powershell.exe -NoProfile -NonInteractive -EncodedCommand '+ENCODED]


def worker_source():
    raw = core.read_bytes(HERE/'windows_worker.py', 96*1024)
    return raw.decode('utf-8'), core.digest(raw)


def request_for(p, operation, identity=None, manifest_hash=None):
    return {'protocol':1,'operation':operation,'remote_root':p['remote_root'],
            'expected_hostname':p['expected_hostname'],'expected_user':p['expected_user'],
            'job_id':identity,'manifest_sha256':manifest_hash}


def encode_request(p, request, source):
    body = core.canonical({'source': source, 'request': request})
    header = core.canonical({'python_path': p['remote_python'], 'body_bytes': len(body)})
    return header + b'\n' + body


def rpc(p, request, *, source=None):
    if source is None:
        source, _ = worker_source()
    payload = encode_request(p, request, source)
    try:
        child = run_bounded(ssh_argv(p), payload, timeout=p['connect_timeout_seconds'] + 30,
                            max_input=core.MAX_RPC, max_stdout=core.MAX_RPC, max_stderr=core.MAX_ERROR)
    except CaptureError as exc:
        raise core.TransportError(f'SSH RPC failed; outcome uncertain: {exc}') from exc
    if child.returncode:
        detail = child.stderr.decode('utf-8', 'replace')[-2000:]
        raise core.TransportError(f'SSH exited {child.returncode}: {detail}')
    try:
        result = core.decode_json(child.stdout.decode('utf-8'))
    except ValueError as exc:
        raise core.TransportError('Malformed remote JSON; outcome uncertain') from exc
    return validate_response(result, p, request)


def validate_response(result,p,request):
    if not isinstance(result,dict) or type(result.get('protocol')) is not int or result['protocol']!=1 or type(result.get('ok')) is not bool:
        raise core.TransportError('Invalid protocol response')
    ident=result.get('identity')
    if not isinstance(ident,dict) or not isinstance(ident.get('hostname'),str) or not isinstance(ident.get('user'),str):
        raise core.TransportError('Missing remote identity')
    for key,field in (('expected_hostname','hostname'),('expected_user','user')):
        if p[key] is not None and ident[field]!=p[key]: raise core.TransportError('Remote identity mismatch: '+field)
    if request['operation']=='inspect':
        if result.get('status')!='inspected' or result.get('supported_remote_os')!='windows' or ident.get('os')!='Windows':
            raise core.TransportError('Invalid Windows inspection')
    elif result.get('job_id')!=request['job_id'] or result.get('manifest_sha256')!=request['manifest_sha256'] or result.get('status') not in STATES:
        raise core.TransportError('Job identity/hash/status mismatch')
    return result


def validate_manifest(manifest):
    manifest = worker.validate_manifest(manifest)
    for name in manifest['outputs']:
        if name.split('/', 1)[0].casefold() == '.collection.json':
            raise ValueError('Output uses the reserved root .collection.json namespace')
    return manifest


def invoke(p,req,state,path,source):
    try: result=rpc(p,req,source=source)
    except (core.TransportError,OSError,subprocess.SubprocessError) as exc:
        state.update(status='uncertain',uncertain_operation=req['operation'],last_error=str(exc))
        save_state(path,state)
        raise
    receipt = {key: result[key] for key in ('ok', 'status', 'job_id', 'manifest_sha256')}
    error = result.get('error')
    message = error.get('message') if isinstance(error, dict) else None
    state.update(status=result['status'], last_remote=receipt,
                 last_error=message[:2000] if isinstance(message, str) else None)
    state.pop('uncertain_operation',None)
    save_state(path,state)
    return result


def load_state(path,p,identity,source_hash):
    state=core.read_json(path,core.MAX_RPC)
    if (not isinstance(state,dict) or state.get('schema_version')!=1
            or type(state.get('submit_attempted')) is not bool or state.get('job_id')!=identity
            or state.get('profile_sha256')!=core.digest(core.canonical(p))):
        raise ValueError('Saved state/profile mismatch')
    m=validate_manifest(state.get('manifest'))
    if m['job_id']!=identity or core.digest(core.canonical(m))!=state.get('manifest_sha256'):
        raise ValueError('Saved manifest mismatch')
    if source_hash!=state.get('worker_sha256'):
        raise ValueError('Reviewed Windows worker source changed')
    return state


def validate_collection(result, manifest):
    if not result.get('ok') or result.get('status') not in core.TERMINAL:
        raise ValueError('Terminal successful collection response required')
    files=result.get('files'); logs=result.get('logs'); missing=result.get('missing')
    if not isinstance(files,list) or not isinstance(logs,dict) or set(logs)-{'stdout.log','stderr.log'} or not isinstance(missing,list):
        raise ValueError('Malformed collection records')
    expected=set(manifest['outputs']); seen=set(); total=0
    for item in files:
        if not isinstance(item,dict) or set(item)!={'path','sha256','data'}: raise ValueError('Malformed artifact')
        name=worker.relative(item['path'])
        if name not in expected or name in seen: raise ValueError('Unexpected artifact')
        raw=base64.b64decode(item['data'],validate=True); total+=len(raw)
        if total>manifest['resources']['max_output_bytes'] or core.digest(raw)!=item['sha256']:
            raise ValueError('Artifact bound/hash mismatch')
        seen.add(name)
    if set(missing)!=expected-seen or len(missing)!=len(set(missing)):
        raise ValueError('Missing artifact declaration mismatch')
    for item in logs.values():
        if not isinstance(item,dict) or set(item)!={'data','sha256'}: raise ValueError('Malformed log')
        raw=base64.b64decode(item['data'],validate=True)
        if len(raw)>manifest['resources']['max_log_bytes'] or core.digest(raw)!=item['sha256']:
            raise ValueError('Log bound/hash mismatch')
    if result['status']=='succeeded' and (missing or result.get('partial') is not False):
        raise ValueError('Successful collection is partial')
    if result['status']!='succeeded' and result.get('partial') is not True:
        raise ValueError('Failed collection must declare partial')


def prepare(p,manifest_path,state_dir,allow_transfer=False):
    core.pinned(p)
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required')
    m = validate_manifest(core.read_json(manifest_path))
    files = core.input_files(m, Path(manifest_path).resolve().parent)
    source,source_hash=worker_source(); identity=m['job_id']; h=core.digest(core.canonical(m))
    with core.local_lock(state_dir,identity) as path:
        if path.exists(): raise FileExistsError('Local state exists; reconcile without preparing again')
        state={'schema_version':1,'job_id':identity,'manifest_sha256':h,'manifest':m,
               'profile_sha256':core.digest(core.canonical(p)),'worker_sha256':source_hash,
               'status':'prepare_attempted','submit_attempted':False}
        save_state(path,state,exclusive=True)
        req=request_for(p,'prepare',identity,h); req.update(manifest=m,files=files,worker_source=source)
        return invoke(p,req,state,path,source)


def operate(p,operation,identity,state_dir,allow_execute=False,allow_cancel=False,destination=None):
    core.pinned(p); core.job_id(identity)
    with core.local_lock(state_dir,identity) as path:
        source, source_hash = worker_source()
        state=load_state(path,p,identity,source_hash)
        if operation=='submit':
            if not allow_execute or state.get('submit_attempted') or state.get('status')!='prepared':
                raise ValueError('Explicit first execution authorization and prepared state required; never resubmit')
            state.update(submit_attempted=True,status='launching'); save_state(path,state)
        if operation=='cancel':
            if not allow_cancel: raise ValueError('Explicit --allow-cancel required')
            state['cancel_attempted']=True; save_state(path,state)
        req=request_for(p,operation,identity,state['manifest_sha256'])
        result=invoke(p,req,state,path,source)
        if operation=='collect' and result['ok']:
            validate_collection(result,state['manifest'])
            summary=core.collect_files(result,state['manifest'],destination)
            state['collection']=summary;save_state(path,state)
            result={**result,'collection':summary}
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='operation',required=True)
    for op in ('inspect','prepare','submit','status','recover','collect','cancel'):
        cmd=commands.add_parser(op);cmd.add_argument('--profile',required=True);cmd.add_argument('--output',required=True)
        if op=='prepare': cmd.add_argument('--manifest',required=True);cmd.add_argument('--allow-transfer',action='store_true')
        if op!='inspect': cmd.add_argument('--state-dir',required=True)
        if op not in ('inspect','prepare'): cmd.add_argument('--job-id',required=True)
        if op=='submit': cmd.add_argument('--allow-execute',action='store_true')
        if op=='cancel': cmd.add_argument('--allow-cancel',action='store_true')
        if op=='collect': cmd.add_argument('--destination',required=True)
    args=parser.parse_args(argv)
    try:
        if Path(args.output).exists() or Path(args.output).is_symlink(): raise FileExistsError('Output report exists')
        p=profile(core.read_json(args.profile))
        if args.operation=='inspect': result=rpc(p,request_for(p,'inspect'))
        elif args.operation=='prepare': result=prepare(p,args.manifest,args.state_dir,args.allow_transfer)
        else: result=operate(p,args.operation,args.job_id,args.state_dir,
                             getattr(args,'allow_execute',False),getattr(args,'allow_cancel',False),getattr(args,'destination',None))
        save_state(args.output,result,exclusive=True)
        return 0 if result['ok'] else 2
    except (OSError,ValueError,TypeError,KeyError,core.TransportError,subprocess.SubprocessError) as exc:
        failure={'protocol':1,'ok':False,'status':'failed','error':str(exc)}
        if not Path(args.output).exists() and not Path(args.output).is_symlink():
            try: save_state(args.output,failure,exclusive=True)
            except OSError: pass
        return 2

if __name__=='__main__': raise SystemExit(main())
