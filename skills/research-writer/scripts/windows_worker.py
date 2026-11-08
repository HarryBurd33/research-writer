#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Windows trusted-job JSON worker. Job Objects control descendants; this is not a security sandbox."""
from __future__ import annotations
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

PROTOCOL = 1
MAX_REQUEST = 32 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_INPUT = 16 * 1024 * 1024
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
# Retain handles only within a long-lived library caller; SSH RPC exits detach.
_LOCAL_CONTROLLERS = {}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    if len(raw) > MAX_REQUEST:
        raise ValueError('JSON input limit exceeded')
    def constant(_):
        raise ValueError('Nonfinite JSON number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)


def read_json(path):
    path=Path(path);deadline=time.monotonic()+1.0
    while True:
        try:
            if path.is_symlink() or (os.name=='nt' and reparse(path)):
                raise ValueError('Metadata reparse point forbidden')
            with path.open('rb') as stream:
                return parse(stream.read(MAX_REQUEST + 1))
        except PermissionError as exc:
            # Replacement can temporarily deny an observer's open on Windows.
            # Retry only the read: never change permissions, delete or dispatch.
            if os.name!='nt' or getattr(exc,'winerror',None) not in (5,32,33) or time.monotonic()>=deadline:
                raise
            time.sleep(min(.02,max(0,deadline-time.monotonic())))


def current_account_owns(path):
    """Compare the file's Windows owner SID with this process TokenUser SID."""
    import ctypes
    from ctypes import wintypes as w
    adv=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    pointer=ctypes.c_void_p
    adv.GetNamedSecurityInfoW.argtypes=[w.LPWSTR,w.DWORD,w.DWORD,ctypes.POINTER(pointer),pointer,pointer,pointer,ctypes.POINTER(pointer)]
    adv.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,pointer,w.DWORD,ctypes.POINTER(w.DWORD)]
    adv.EqualSid.argtypes=[pointer,pointer]
    kernel.GetCurrentProcess.restype=w.HANDLE;kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.LocalFree.argtypes=[pointer];kernel.LocalFree.restype=pointer
    owner=pointer();descriptor=pointer();token=w.HANDLE()
    if adv.GetNamedSecurityInfoW(str(path),1,1,ctypes.byref(owner),None,None,None,ctypes.byref(descriptor)):
        return False
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):return False
        needed=w.DWORD()
        adv.GetTokenInformation(token,1,None,0,ctypes.byref(needed))
        if not needed.value:return False
        buffer=ctypes.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token,1,buffer,needed,ctypes.byref(needed)):return False
        current=ctypes.cast(buffer,ctypes.POINTER(pointer))[0]
        return bool(adv.EqualSid(owner,current))
    finally:
        if token:kernel.CloseHandle(token)
        kernel.LocalFree(descriptor)


def retryable_metadata(source,target):
    for path in (Path(source),Path(target),Path(target).parent):
        try:
            info=path.lstat()
        except FileNotFoundError:
            if path==Path(target):continue
            return False
        if path.is_symlink() or reparse(path) or info.st_nlink!=1 or not current_account_owns(path):return False
        if path==Path(target).parent:
            if not stat.S_ISDIR(info.st_mode):return False
        elif not stat.S_ISREG(info.st_mode):return False
    return True


def atomic(path, value):
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(canonical(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        deadline=time.monotonic()+1.0
        while True:
            try:
                os.replace(name,path)
                break
            except PermissionError as exc:
                # Sharing/delete denial can be transient while a status reader holds
                # the old file. Never chmod, unlink, retry other errors or dispatch again.
                if (os.name!='nt' or getattr(exc,'winerror',None) not in (5,32,33)
                        or time.monotonic()>=deadline or not retryable_metadata(name,path)):
                    raise
                time.sleep(min(.02,max(0,deadline-time.monotonic())))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identity():
    if os.name != 'nt':
        raise ValueError('Windows worker requires native Windows Python')
    return {'hostname': socket.gethostname(), 'user': getpass.getuser(),
            'python': sys.executable, 'python_version': platform.python_version(),
            'os': platform.system(), 'machine': platform.machine()}



def reparse(path):
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 512 or '\\' in value or '\x00' in value:
        raise ValueError('Expected bounded POSIX relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or value in ('.', '') or any(x.casefold() in ('.ssh', '.aws', '.git', '.codex', '.env') or x.casefold().startswith('.env.') for x in p.parts):
        raise ValueError('Unsafe relative path')
    if p.as_posix() != value:
        raise ValueError('Relative paths must be normalized')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {f'{x}{n}' for x in ('COM', 'LPT') for n in (*map(str,range(1,10)), '¹', '²', '³')}
    if PureWindowsPath(value).drive or any(
            any(c in part for c in '<>:"|?*') or any(ord(c) < 32 for c in part)
            or part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved
            for part in p.parts):
        raise ValueError('Windows reserved or aliasing path')
    return p.as_posix()


def hash_string(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected lowercase SHA-256')
    return value


def validate_manifest(m):
    if not isinstance(m, dict) or type(m.get('schema_version')) is not int or m['schema_version'] != 1:
        raise ValueError('Unsupported manifest schema')
    if set(m) != {'schema_version', 'job_id', 'argv', 'inputs', 'outputs', 'resources', 'required_device'}:
        raise ValueError('Unexpected/missing manifest fields')
    if not isinstance(m['job_id'], str) or not re.fullmatch('[0-9a-f]{32}', m['job_id']):
        raise ValueError('Expected 32 lowercase hex job ID')
    argv = m['argv']
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or not all(isinstance(x, str) and x and len(x) <= 4096 and '\x00' not in x for x in argv) or sum(map(len, argv)) > 32768:
        raise ValueError('Invalid bounded command argument array')
    if m['required_device'] != 'cpu':
        raise ValueError('Only explicitly selected CPU jobs are supported by this controller')
    resources = m['resources']
    bounds = {'wall_seconds': (1, 3600), 'max_output_bytes': (1, MAX_INPUT),
              'max_log_bytes': (1, 1024 * 1024), 'threads': (1, 16)}
    if not isinstance(resources, dict) or set(resources) != set(bounds):
        raise ValueError('Missing/unknown resource fields')
    for key, (low, high) in bounds.items():
        if type(resources[key]) is not int or not low <= resources[key] <= high:
            raise ValueError('Invalid resource bound: ' + key)
    if not isinstance(m['inputs'], list) or len(m['inputs']) > 32 or not isinstance(m['outputs'], list) or not 1 <= len(m['outputs']) <= 32:
        raise ValueError('Invalid bounded input/output lists')
    names = []
    for entry in m['inputs']:
        if not isinstance(entry, dict) or set(entry) != {'source', 'destination', 'sha256'}:
            raise ValueError('Invalid input entry')
        relative(entry['source']); names.append(relative(entry['destination'])); hash_string(entry['sha256'])
    outputs = [relative(x) for x in m['outputs']]
    if len(set(x.casefold() for x in names + outputs)) != len(names + outputs):
        raise ValueError('Windows case-insensitive path collision')
    if len(names) != len(set(names)) or len(outputs) != len(set(outputs)) or set(names) & set(outputs):
        raise ValueError('Duplicate or overlapping input/output paths')
    # Parent/child file conflicts cannot be staged safely.
    paths = [PurePosixPath(x.casefold()) for x in names + outputs]
    if any(a != b and a in b.parents for a in paths for b in paths):
        raise ValueError('Input/output paths conflict as files and directories')
    return m


def root_path(value):
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError('Expected absolute dedicated Windows root')
    native = PureWindowsPath(value)
    if not re.fullmatch('[A-Za-z]:', native.drive) or not native.is_absolute():
        raise ValueError('Only absolute local drive roots supported; UNC/device paths forbidden')
    relative('/'.join(native.parts[1:]))
    root = Path(value)
    if not root.is_absolute() or root == Path(root.anchor) or '..' in root.parts:
        raise ValueError('Expected absolute dedicated Windows root')
    for part in (root, *root.parents):
        if part.is_symlink() or reparse(part):
            raise ValueError('Root reparse points are forbidden')
    if root.exists() and not root.is_dir():
        raise ValueError('Root is not a directory')
    return root.resolve()


def inside(root, name, must_exist=True):
    name = relative(name)
    if root.is_symlink() or reparse(root):
        raise ValueError('Work directory symlink is forbidden')
    candidate = root / name
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink() or reparse(cursor):
            raise ValueError('Symlink artifact is forbidden')
        cursor = cursor.parent
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError('Artifact escapes job work directory')
    if must_exist and not candidate.is_file():
        raise ValueError('Artifact is missing or not a regular file')
    return candidate


def nearest_existing(path):
    while not path.exists():
        path = path.parent
    return path


@contextmanager
def mutation_lock(job):
    import msvcrt
    lock = job / '.rpc-lock'
    if lock.is_symlink() or reparse(lock):
        raise ValueError('Invalid lock reparse point')
    with lock.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('Concurrent mutation; never steal lock') from exc
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def snapshot(job):
    state = read_json(job / 'state.json')
    if state['status'] in ('running', 'launching') and time.time() - state.get('heartbeat', state.get('updated_at', 0)) > 5:
        return {**state, 'status': 'uncertain', 'reason': 'Controller heartbeat stale; no PID-based action or relaunch performed'}
    return state


def reply(ident, request, status, **extra):
    child = _LOCAL_CONTROLLERS.get(request.get('job_id'))
    if child is not None and status in TERMINAL:
        try:
            child.wait(timeout=1)
            _LOCAL_CONTROLLERS.pop(request.get('job_id'), None)
        except subprocess.TimeoutExpired:
            pass
    return {'protocol': PROTOCOL, 'ok': True, 'status': status, 'identity': ident,
            'job_id': request.get('job_id'), 'manifest_sha256': request.get('manifest_sha256'), **extra}


def prepare(root, req, ident):
    m = validate_manifest(req.get('manifest'))
    if m['job_id'] != req['job_id'] or digest(canonical(m)) != req['manifest_sha256']:
        raise ValueError('Manifest identity/hash mismatch')
    files = req.get('files')
    if not isinstance(files, list) or len(files) != len(m['inputs']):
        raise ValueError('Transferred file count mismatch')
    expected = {x['destination']: x['sha256'] for x in m['inputs']}
    decoded, total = {}, 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'data'}:
            raise ValueError('Invalid transfer record')
        name = relative(entry['path'])
        if name in decoded or name not in expected or entry['sha256'] != expected[name] or not isinstance(entry['data'], str) or len(entry['data']) > 4 * (MAX_FILE // 3 + 2):
            raise ValueError('Transferred identity/size mismatch')
        raw = base64.b64decode(entry['data'], validate=True)
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_INPUT or digest(raw) != expected[name]:
            raise ValueError('Transfer size/hash mismatch')
        decoded[name] = raw
    code = req.get('worker_source')
    if not isinstance(code, str) or not code or len(code.encode()) > 96 * 1024:
        raise ValueError('Missing/bounded worker source required')
    compile(code, '<staged-controller>', 'exec')
    job = root / req['job_id']
    if (job.is_symlink() or reparse(job)) or job.exists() and not job.is_dir():
        raise ValueError('Existing job directory ownership/type mismatch')
    if job.exists():
        saved = read_json(job / 'prepared.json')
        if saved['manifest_sha256'] != req['manifest_sha256'] or saved['worker_sha256'] != digest(code.encode()):
            raise ValueError('Existing job has different immutable inputs/controller')
        s = snapshot(job)
        return reply(ident, req, s['status'], state=s, already_prepared=True)
    free = shutil.disk_usage(nearest_existing(root)).free
    required = total + m['resources']['max_output_bytes'] + 2 * m['resources']['max_log_bytes'] + MAX_INPUT
    if free < required:
        raise ValueError('Insufficient remote disk space for bounded preparation')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.prepare-', dir=root))
    try:
        (stage / 'work').mkdir(mode=0o700)
        for name, raw in decoded.items():
            path = inside(stage / 'work', name, False)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        (stage / 'controller.py').write_text(code, encoding='utf-8', newline='\n')
        atomic(stage / 'manifest.json', m)
        atomic(stage / 'prepared.json', {'manifest_sha256': req['manifest_sha256'],
                                        'worker_sha256': digest(code.encode()), 'input_bytes': total})
        atomic(stage / 'state.json', {'status': 'prepared', 'updated_at': time.time(), 'job_id': m['job_id']})
        # A prepared directory is never empty; concurrent rename cannot replace it.
        os.rename(stage, job)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return reply(ident, req, 'prepared', state=read_json(job / 'state.json'))


def checked_job(root, req):
    job = root / req['job_id']
    if (job.is_symlink() or reparse(job)) or job.exists() and not job.is_dir():
        raise ValueError('Invalid job directory ownership/type')
    if not job.exists():
        return None
    for name in ('prepared.json', 'manifest.json', 'controller.py', 'state.json'):
        if (job / name).is_symlink() or reparse(job / name) or not (job / name).is_file():
            raise ValueError('Job metadata must remain regular files')
    saved = read_json(job / 'prepared.json')
    if saved['manifest_sha256'] != req['manifest_sha256']:
        raise ValueError('Job manifest binding mismatch')
    m = validate_manifest(read_json(job / 'manifest.json'))
    if digest(canonical(m)) != req['manifest_sha256'] or m['job_id'] != req['job_id']:
        raise ValueError('Stored manifest changed')
    if digest((job / 'controller.py').read_bytes()) != saved['worker_sha256']:
        raise ValueError('Stored controller changed')
    return job


def handle(req):
    ident = {}
    try:
        ident = identity()
        if not isinstance(req, dict) or type(req.get('protocol')) is not int or req['protocol'] != PROTOCOL:
            raise ValueError('Unsupported protocol')
        operation = req.get('operation')
        if operation not in ('inspect', 'prepare', 'submit', 'status', 'recover', 'collect', 'cancel'):
            raise ValueError('Unsupported operation')
        root = root_path(req.get('remote_root'))
        if operation == 'inspect':
            for key, observed in (('expected_hostname', ident['hostname']), ('expected_user', ident['user'])):
                if req.get(key) is not None and req[key] != observed:
                    raise ValueError('Remote identity mismatch: ' + key)
            usage = shutil.disk_usage(nearest_existing(root))
            return reply(ident, req, 'inspected', free_bytes=usage.free,
                         supported_devices=['cpu'], supported_remote_os='windows', root_exists=root.exists())
        if req.get('expected_hostname') != ident['hostname'] or req.get('expected_user') != ident['user']:
            raise ValueError('Pinned remote host/user identity mismatch')
        if not isinstance(req.get('job_id'), str) or not re.fullmatch('[0-9a-f]{32}', req['job_id']):
            raise ValueError('Invalid job ID')
        hash_string(req.get('manifest_sha256'))
        if operation == 'prepare':
            return prepare(root, req, ident)
        job = checked_job(root, req)
        if job is None:
            return reply(ident, req, 'not_found')
        if operation in ('status', 'recover'):
            s = snapshot(job)
            if operation == 'recover':
                return reply(ident, req, s['status'], state=s, reconciliation={
                    'mode': 'read_only', 'execution_attempted': (job / 'submission.json').exists(),
                    'restarted': False, 'pid_signal_sent': False,
                    'liveness': 'not_proven_by_heartbeat_or_stored_pid',
                    'next_action': 'Collect terminal artifacts; otherwise reconcile the original job without resubmitting'})
            return reply(ident, req, s['status'], state=s)
        if operation == 'collect':
            s = snapshot(job)
            if s['status'] not in TERMINAL:
                raise ValueError('Only terminal jobs can be collected; uncertain jobs require reconciliation')
            manifest = read_json(job / 'manifest.json')
            if (job / 'artifacts.json').is_symlink() or reparse(job / 'artifacts.json'):
                raise ValueError('Artifact index symlink is forbidden')
            saved = read_json(job / 'artifacts.json') if (job / 'artifacts.json').exists() else {}
            files, missing, total = [], [], 0
            for name in manifest['outputs']:
                path = inside(job / 'work', name, False)
                if not path.exists():
                    missing.append(name); continue
                path = inside(job / 'work', name)
                with path.open('rb') as stream:
                    raw = stream.read(manifest['resources']['max_output_bytes'] + 1)
                total += len(raw)
                if total > manifest['resources']['max_output_bytes'] or name not in saved or digest(raw) != saved[name]['sha256']:
                    raise ValueError('Output changed, oversized or not checkpointed')
                files.append({'path': name, 'sha256': digest(raw), 'data': base64.b64encode(raw).decode('ascii')})
            if s['status'] == 'succeeded' and missing:
                raise ValueError('Successful-job output is missing')
            logs = {}
            for name in ('stdout.log', 'stderr.log'):
                path = job / name
                if path.is_symlink() or reparse(path):
                    raise ValueError('Log symlink is forbidden')
                if path.exists():
                    with path.open('rb') as stream:
                        raw = stream.read(manifest['resources']['max_log_bytes'])
                    logs[name] = {'data': base64.b64encode(raw).decode('ascii'), 'sha256': digest(raw)}
            return reply(ident, req, s['status'], state=s, files=files, missing=missing,
                         partial=s['status'] != 'succeeded' or bool(missing), logs=logs)
        with mutation_lock(job):
            s = snapshot(job)
            if operation == 'cancel':
                if s['status'] in TERMINAL:
                    return reply(ident, req, s['status'], state=s, cancel_requested=False)
                with (job / 'cancel.request').open('a'):
                    pass
                if s['status'] == 'prepared':
                    s = {**s, 'status': 'cancelled', 'reason': 'Cancelled before launch', 'updated_at': time.time()}
                    atomic(job / 'state.json', s)
                return reply(ident, req, s['status'], state=s, cancel_requested=True)
            if (job / 'submission.json').exists():
                return reply(ident, req, s['status'], state=s, already_submitted=True)
            if s['status'] != 'prepared' or (job / 'cancel.request').exists():
                raise ValueError('Job is not prepared for first submission')
            with (job / 'submission.json').open('x', encoding='utf-8') as stream:
                json.dump({'attempted_at': time.time(), 'manifest_sha256': req['manifest_sha256']}, stream)
                stream.flush(); os.fsync(stream.fileno())
            atomic(job / 'state.json', {'status': 'launching', 'updated_at': time.time(), 'heartbeat': time.time(), 'job_id': req['job_id']})
            try:
                with (job / 'controller.log').open('xb') as log:
                    p = subprocess.Popen([sys.executable, str(job / 'controller.py'), '--run-job', str(job)],
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
                _LOCAL_CONTROLLERS[req['job_id']] = p
                atomic(job / 'controller-receipt.json', {'pid': p.pid, 'purpose': 'diagnostic only; never used for PID-based cancellation'})
            except Exception:
                atomic(job / 'state.json', {'status': 'uncertain', 'updated_at': time.time(), 'reason': 'Launch attempted; operator reconciliation required'})
                raise
            return reply(ident, req, 'launching', state={'status': 'launching', 'job_id': req['job_id']})
    except Exception as exc:
        return {'protocol': PROTOCOL, 'ok': False, 'status': 'failed', 'identity': ident,
                'job_id': req.get('job_id') if isinstance(req, dict) else None,
                'manifest_sha256': req.get('manifest_sha256') if isinstance(req, dict) else None,
                'error': {'code': type(exc).__name__, 'message': str(exc)[:2000]}}


def windows_spawn(argv, cwd, stdout, stderr, env):
    """Trusted Python gate cannot run workload until assigned to kill-on-close job."""
    import ctypes
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    class BASIC(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount',
                                                    'ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class EXTENDED(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BASIC), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; k.CreateJobObjectW.restype = w.HANDLE
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.CreateJobObjectW(None, None)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    child = None
    try:
        info = EXTENDED(); info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        gate = "import sys,subprocess; token=sys.stdin.buffer.read(1); sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) if token==b'G' else 125)"
        child = subprocess.Popen([sys.executable, '-c', gate, *argv], cwd=cwd, stdin=subprocess.PIPE,
                                 stdout=stdout, stderr=stderr, env=env, shell=False, close_fds=True)
        if not k.AssignProcessToJobObject(handle, w.HANDLE(int(child._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        child._owned_job = (k, handle)
        child.stdin.write(b'G'); child.stdin.flush(); child.stdin.close()
        return child
    except Exception:
        if child is not None:
            child.kill(); child.wait(timeout=5)
        k.CloseHandle(handle)
        raise


def terminate(child):
    # Only a live owned handle is used. A stored PID is never sufficient authority.
    owned = getattr(child, '_owned_job', None)
    if owned:
        k, handle = owned
        if not k.TerminateJobObject(handle, 1):
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())
        child.wait(timeout=5)
        k.CloseHandle(handle); child._owned_job = None
    elif child.poll() is None:
        child.kill(); child.wait(timeout=5)


def work_bytes(work):
    total, count = 0, 0
    for directory, dirs, files in os.walk(work, followlinks=False):
        if len(dirs) + len(files) > 256:
            raise ValueError('Work directory entry limit exceeded')
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink() or reparse(path):
                raise ValueError('Work directory contains a symlink')
        for name in files:
            count += 1
            if count > 256:
                raise ValueError('Work file count exceeded')
            total += (Path(directory) / name).stat().st_size
    return total


def bound_logs(job, limit):
    errors = []
    for name in ('stdout.log', 'stderr.log'):
        path = job / name
        try:
            if path.is_symlink() or reparse(path):
                raise ValueError('Log reparse point forbidden')
            if path.exists():
                if not path.is_file(): raise ValueError('Log not regular')
                with path.open('r+b') as stream:
                    stream.truncate(min(path.stat().st_size, limit))
        except (OSError, ValueError) as exc:
            errors.append(name + ': ' + str(exc)[:200])
    return errors


def run_job(directory):
    job = Path(directory).resolve()
    child = None
    resources = None
    state = {'status': 'failed', 'job_id': job.name, 'updated_at': time.time()}
    artifacts = {}
    try:
        m = validate_manifest(read_json(job / 'manifest.json'))
        prepared = read_json(job / 'prepared.json')
        if digest(canonical(m)) != prepared['manifest_sha256'] or digest((job / 'controller.py').read_bytes()) != prepared['worker_sha256']:
            raise ValueError('Controller/manifest changed before execution')
        resources = m['resources']
        if (job / 'cancel.request').exists():
            state.update(status='cancelled', reason='Cancelled before execution')
        else:
            env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': str(resources['threads']),
                   'OPENBLAS_NUM_THREADS': str(resources['threads']), 'MKL_NUM_THREADS': str(resources['threads']),
                   'NUMEXPR_NUM_THREADS': str(resources['threads']), 'VECLIB_MAXIMUM_THREADS': str(resources['threads'])}
            started = time.monotonic()
            with (job / 'stdout.log').open('xb') as stdout, (job / 'stderr.log').open('xb') as stderr:
                child = windows_spawn(m['argv'], job / 'work', stdout, stderr, env)
                state.update(status='running', heartbeat=time.time(), started_at=time.time())
                atomic(job / 'state.json', state)
                while True:
                    reason = None
                    if (job / 'cancel.request').exists():
                        state['status'], reason = 'cancelled', 'Cancellation request observed by owning controller'
                    elif time.monotonic() - started >= resources['wall_seconds']:
                        state['status'], reason = 'timed_out', 'Wall-time limit exceeded'
                    elif any((job / n).stat().st_size > resources['max_log_bytes'] for n in ('stdout.log', 'stderr.log')):
                        state['status'], reason = 'failed', 'Log-size limit exceeded'
                    elif work_bytes(job / 'work') > prepared['input_bytes'] + resources['max_output_bytes']:
                        state['status'], reason = 'failed', 'Work/output-size limit exceeded'
                    if reason:
                        state['reason'] = reason; terminate(child); break
                    if child.poll() is not None:
                        state['returncode'] = child.returncode
                        state['status'] = 'succeeded' if child.returncode == 0 else 'failed'
                        if child.returncode:
                            state['reason'] = 'Task exited nonzero'
                        break
                    state['heartbeat'] = time.time(); atomic(job / 'state.json', state); time.sleep(0.1)
                state['returncode'] = child.wait()
                terminate(child)  # close/kill remaining descendants before artifact checkpoint
            total = 0
            for name in m['outputs']:
                path = inside(job / 'work', name, False)
                if not path.exists():
                    if state['status'] == 'succeeded':
                        state.update(status='failed', reason='Declared output missing')
                    continue
                path = inside(job / 'work', name)
                with path.open('rb') as stream:
                    raw = stream.read(resources['max_output_bytes'] + 1)
                total += len(raw)
                if total > resources['max_output_bytes']:
                    state.update(status='failed', reason='Declared output-size limit exceeded')
                    artifacts = {}; break
                artifacts[name] = {'sha256': digest(raw), 'bytes': len(raw)}
    except Exception as exc:
        if child is not None:
            terminate(child)
        state.update(status='failed', reason=f'{type(exc).__name__}: {str(exc)[:1000]}')
    finally:
        # Artifact validation can fail after a task has emitted diagnostics.
        # Stop the owned child first, then bound logs on every terminal path.
        if child is not None:
            try:
                terminate(child)
            except Exception as exc:
                state.update(status='uncertain', reason='Owned child cleanup failed: ' + str(exc)[:500])
        if resources is not None:
            cleanup_errors = bound_logs(job, resources['max_log_bytes'])
            if cleanup_errors:
                state['log_cleanup_errors'] = cleanup_errors
                if state['status'] == 'succeeded':
                    state.update(status='failed', reason='Available diagnostic cleanup failed')
        state.update(updated_at=time.time(), finished_at=time.time())
        atomic(job / 'artifacts.json', artifacts)
        atomic(job / 'state.json', state)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-job', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_job:
        return run_job(args.run_job)
    try:
        request = parse(sys.stdin.buffer.read(MAX_REQUEST + 1))
        result = handle(request)
    except Exception as exc:
        result = {'protocol': PROTOCOL, 'ok': False, 'status': 'failed', 'error': {'code': type(exc).__name__, 'message': str(exc)[:2000]}}
    raw = canonical(result) + b'\n'
    if len(raw) > MAX_REQUEST:
        raw = canonical({'protocol': PROTOCOL, 'ok': False, 'status': 'failed', 'error': {'code': 'response_limit', 'message': 'Response exceeds limit'}}) + b'\n'
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
