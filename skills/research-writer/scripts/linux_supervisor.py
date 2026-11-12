#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Linux container PID1 supervisor; never run `run` outside the selected container."""
from __future__ import annotations
import argparse
import base64
import errno
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import selectors
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata

CONTROL = Path('/control')
WORK = Path('/work')
RUNNER = Path('/runner')
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
MAX_RPC = 32 * 1024 * 1024
_CANCEL = False
FAULT_BYTES = 4096
FAULT_MESSAGE_BYTES = 1024
FAULT_PHASES = {'setup', 'task_launch', 'task_io', 'namespace_cleanup', 'log_close',
                'artifact_finalize', 'counters', 'receipt_publish', 'retention'}
FAULT_FILE = 'supervisor-fault.json'


def error_detail(exc, phase):
    try:
        message = str(exc)
    except Exception:
        message = 'Exception message unavailable'
    return {'phase': phase, 'exception_type': type(exc).__name__.encode('utf-8', 'replace')[:128].decode('utf-8', 'ignore'),
            'message': message.encode('utf-8', 'replace')[:FAULT_MESSAGE_BYTES].decode('utf-8', 'ignore'),
            'errno': exc.errno if isinstance(exc, OSError) and type(exc.errno) is int else None}


def fault_identity(manifest, binding):
    """Validate the diagnostic authority; source bytes were checked by checked_binding."""
    fields = {'schema_version', 'job_id', 'image_id', 'argv', 'inputs', 'outputs', 'resources', 'required_device'}
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] not in (1, 2)
            or set(manifest) != fields | ({'checkpoint'} if manifest['schema_version'] == 2 else set())):
        raise ValueError('Invalid diagnostic manifest')
    if not isinstance(binding, dict) or set(binding) != {'nonce', 'manifest_sha256', 'supervisor_sha256'}:
        raise ValueError('Invalid diagnostic binding')
    for value, length in [(manifest['job_id'], 32), (binding['nonce'], 32),
                          (binding['manifest_sha256'], 64), (binding['supervisor_sha256'], 64)]:
        if not isinstance(value, str) or re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is None:
            raise ValueError('Invalid diagnostic identity')
    if binding['manifest_sha256'] != digest(canonical(manifest)):
        raise ValueError('Diagnostic manifest hash mismatch')
    if not isinstance(manifest['image_id'], str) or not re.fullmatch('sha256:[0-9a-f]{64}', manifest['image_id']) or manifest['required_device'] != 'cpu':
        raise ValueError('Invalid diagnostic image/device')
    argv = manifest['argv']
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or any(not isinstance(x, str) or not x or len(x) > 4096 or '\x00' in x for x in argv) or sum(map(len, argv)) > 32768:
        raise ValueError('Invalid diagnostic argv')
    limits = {'wall_seconds': (1, 3600), 'retention_seconds': (5, 3600), 'memory_bytes': (64 * 1024**2, 8 * 1024**3),
              'cpu_millis': (100, 16000), 'pids': (16, 512), 'work_bytes': (1024**2, 256 * 1024**2),
              'tmp_bytes': (1024**2, 64 * 1024**2), 'max_log_bytes': (1, 1024**2), 'max_output_bytes': (1, 16 * 1024**2)}
    resources = manifest['resources']
    if not isinstance(resources, dict) or set(resources) != set(limits) or any(type(resources[k]) is not int or not lo <= resources[k] <= hi for k, (lo, hi) in limits.items()):
        raise ValueError('Invalid diagnostic resources')
    if any(resources[k] % (1024**2) for k in ('memory_bytes', 'work_bytes', 'tmp_bytes')):
        raise ValueError('Invalid diagnostic resource granularity')
    if not isinstance(manifest['inputs'], list) or len(manifest['inputs']) > 32 or not isinstance(manifest['outputs'], list) or not 1 <= len(manifest['outputs']) <= 32:
        raise ValueError('Invalid diagnostic file lists')
    def relative(name):
        if (not isinstance(name, str) or not name or len(name) > 512 or any(c in name for c in ('\\', '\x00', '\n', '\r'))
                or PurePosixPath(name).is_absolute() or str(PurePosixPath(name)) != name
                or any(p in ('', '.', '..', '.ssh', '.aws', '.git', '.codex', '.collection.json', '.logs') or p == '.env' or p.startswith('.env.') for p in name.split('/'))
                or re.match('[A-Za-z]:', name)):
            raise ValueError('Invalid diagnostic file name')
        return PurePosixPath(name)
    names = []
    for item in manifest['inputs']:
        if not isinstance(item, dict) or set(item) != {'source', 'destination', 'sha256'} or not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError('Invalid diagnostic input')
        relative(item['source']); names.append(relative(item['destination']))
    names += [relative(name) for name in manifest['outputs']]
    if len(names) != len(set(names)) or any(a != b and a in b.parents for a in names for b in names):
        raise ValueError('Invalid diagnostic file overlap')
    if manifest['schema_version'] == 2:
        cp = manifest['checkpoint']
        if not isinstance(cp, dict) or set(cp) != {'directory', 'max_bytes', 'max_files'} or type(cp['max_bytes']) is not int or not 1 <= cp['max_bytes'] <= 16 * 1024**2 or type(cp['max_files']) is not int or not 1 <= cp['max_files'] <= 32:
            raise ValueError('Invalid diagnostic checkpoint')
        directory = PurePosixPath('/'.join(_checkpoint_parts(cp['directory'])).casefold())
        if any(directory == x or directory in x.parents or x in directory.parents for x in (PurePosixPath(str(n).casefold()) for n in names)):
            raise ValueError('Invalid diagnostic checkpoint overlap')


def validate_fault(value, manifest, binding):
    fault_identity(manifest, binding)
    fields = {'schema_version', 'kind', 'job_id', 'nonce', 'manifest_sha256', 'supervisor_sha256',
              'primary', 'secondary', 'termination_basis', 'intended_exit_code', 'observed_at', 'expires_at'}
    if not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'supervisor_fault':
        raise ValueError('Invalid supervisor fault schema')
    for key, expected in [('job_id', manifest['job_id']), *binding.items()]:
        if value.get(key) != expected:
            raise ValueError('Supervisor fault binding mismatch')
    if value['termination_basis'] not in ('never_launched', 'namespace_cleanup_confirmed') or type(value['intended_exit_code']) is not int or value['intended_exit_code'] != 2:
        raise ValueError('Invalid supervisor fault termination proof')
    for key in ('observed_at', 'expires_at'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or value[key] < 0:
            raise ValueError('Invalid supervisor fault time')
    if not 0 <= value['expires_at'] - value['observed_at'] <= manifest['resources']['retention_seconds']:
        raise ValueError('Supervisor fault retention exceeds manifest')
    for item in (value['primary'], value['secondary']):
        if item is None and item is value['secondary']:
            continue
        if not isinstance(item, dict) or set(item) != {'phase', 'exception_type', 'message', 'errno'}:
            raise ValueError('Invalid supervisor fault error fields')
        if not isinstance(item['phase'], str) or item['phase'] not in FAULT_PHASES or not isinstance(item['exception_type'], str) or not 1 <= len(item['exception_type'].encode('utf-8')) <= 128 or not isinstance(item['message'], str) or len(item['message'].encode('utf-8')) > FAULT_MESSAGE_BYTES or item['errno'] is not None and (type(item['errno']) is not int or not -(2**31) <= item['errno'] < 2**31):
            raise ValueError('Invalid supervisor fault error bounds')
    if value['primary'] is None or len(canonical(value)) > FAULT_BYTES:
        raise ValueError('Supervisor fault packet byte limit')
    return value


def read_fault(manifest, binding):
    path = CONTROL / FAULT_FILE
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if before.st_uid != 0 or stat.S_IMODE(before.st_mode) != 0o600:
        raise ValueError('Supervisor fault file ownership/mode changed')
    raw = regular_bytes(path, FAULT_BYTES)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite fault')))
    return validate_fault(value, manifest, binding)


def emit_fault_error(primary, secondary=None):
    try:
        packet = {'supervisor_error': primary, 'secondary_error': secondary}
        raw = canonical(packet)
        if len(raw) > FAULT_BYTES - 1:
            packet = {key: {**value, 'message': value['message'].encode('utf-8')[:256].decode('utf-8', 'ignore')}
                      if value is not None else None for key, value in packet.items()}
            raw = canonical(packet)
        if len(raw) > FAULT_BYTES - 1:
            raw = b'{"supervisor_error":"Bounded diagnostic serialization unavailable"}'
        print(raw.decode('utf-8'), file=sys.stderr, flush=True)
    except Exception:
        pass  # No recursive error formatter or false publication claim.


def retain_fault(manifest, binding, context, exc):
    primary = context.get('primary') or error_detail(exc, context['phase'])
    secondary = error_detail(exc, context['phase']) if context.get('primary') else None
    emit_fault_error(primary, secondary)
    if sys.platform != 'linux' or os.getpid() != 1 or os.getuid() != 0:
        return 2
    if context['launch_attempted'] and not context['cleanup_confirmed']:
        return 2
    try:
        fault_identity(manifest, binding)
        now = time.monotonic()
        if context['phase'] == 'retention':
            context['retention_deadline'] = now  # A failed retention sleep never enters another wait cycle.
        if context['retention_deadline'] is None:
            context['retention_deadline'] = now + manifest['resources']['retention_seconds']
        remaining = max(0.0, min(manifest['resources']['retention_seconds'], context['retention_deadline'] - now))
        observed = time.time()
        packet = {'schema_version': 1, 'kind': 'supervisor_fault', 'job_id': manifest['job_id'], **binding,
                  'primary': primary, 'secondary': secondary,
                  'termination_basis': 'namespace_cleanup_confirmed' if context['launch_attempted'] else 'never_launched',
                  'intended_exit_code': 2, 'observed_at': observed, 'expires_at': observed + remaining}
        validate_fault(packet, manifest, binding)
        path = CONTROL / FAULT_FILE
        directory = CONTROL.lstat()
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or stat.S_IMODE(directory.st_mode) != 0o700:
            raise ValueError('Supervisor fault directory ownership/mode changed')
        if path.exists() or path.is_symlink():
            raise ValueError('Supervisor fault already published; no replacement')
        atomic(path, packet)
        while time.monotonic() < context['retention_deadline']:
            time.sleep(min(0.1, max(0.0, context['retention_deadline'] - time.monotonic())))
    except Exception as secondary_exc:
        emit_fault_error(primary, error_detail(secondary_exc, 'retention' if (CONTROL / FAULT_FILE).exists() else 'receipt_publish'))
    return 2


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ValueError('Duplicate JSON key')
        out[k] = v
    return out


def load(path, limit=1024 * 1024):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('JSON byte limit')
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def atomic(path, value):
    fd, temp = tempfile.mkstemp(prefix='.receipt-', dir=Path(path).parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            raw = canonical(value)
            if stream.write(raw) != len(raw):
                raise OSError('Short receipt write')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def confined(root, name):
    if not isinstance(name, str) or not name or len(name) > 512 or '\\' in name or '\x00' in name:
        raise ValueError('Invalid output name')
    p = PurePosixPath(name)
    if p.is_absolute() or str(p) != name or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('Invalid relative path')
    target = Path(root)
    for part in p.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError('Symlink forbidden')
    return target


def regular_bytes(path, maximum):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise ValueError('Regular non-hardlinked bounded file required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        actual = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size) != (actual.st_dev, actual.st_ino, actual.st_size) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValueError('File changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        if len(raw) > maximum or (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Changed/oversized file')
        return raw
    finally:
        os.close(fd)


def effective_limits(resources):
    cg = Path('/sys/fs/cgroup')
    memory = (cg / 'memory.max').read_text().strip()
    swap = (cg / 'memory.swap.max').read_text().strip()
    pids = (cg / 'pids.max').read_text().strip()
    quota, period = (cg / 'cpu.max').read_text().split()
    if memory != str(resources['memory_bytes']) or swap != '0' or pids != str(resources['pids']):
        raise ValueError('Effective memory/swap/PID limits differ; refusing task')
    if quota == 'max' or int(quota) * 1000 != resources['cpu_millis'] * int(period):
        raise ValueError('Effective CPU quota differs; refusing task')
    status = Path('/proc/self/status').read_text()
    if 'NoNewPrivs:\t1' not in status:
        raise ValueError('no-new-privileges missing')
    readonly = {}
    for name in ('/rw-rootfs-probe', '/etc/hosts', '/etc/hostname', '/etc/resolv.conf'):
        try:
            fd = os.open(name, os.O_WRONLY | (os.O_CREAT if name == '/rw-rootfs-probe' else 0), 0o600)
        except OSError as exc:
            if exc.errno != errno.EROFS:
                raise ValueError('Readonly filesystem probe failed: ' + name) from exc
            readonly[name] = True
        else:
            os.close(fd)
            if name == '/rw-rootfs-probe':
                os.unlink(name)
            raise ValueError('Writable root/metadata mount: ' + name)
    scratch = {}
    for name, budget in (('/work', resources['work_bytes']), ('/tmp', resources['tmp_bytes']), ('/control', 4 * 1024**2), ('/dev/shm', 1024**2)):
        fs = os.statvfs(name)
        size = fs.f_blocks * fs.f_frsize
        if not 0 < size <= budget:
            raise ValueError('Effective scratch filesystem byte limit differs: ' + name)
        scratch[name] = {'bytes': size, 'inodes': fs.f_files}
    return {'scratch_filesystems': scratch, 'read_only_checks': readonly, 'memory_bytes': int(memory), 'swap_bytes': int(swap), 'pids': int(pids),
            'cpu_quota': int(quota), 'cpu_period': int(period), 'cpu_millis': resources['cpu_millis'],
            'cpu_semantics': 'rate_not_total_time'}


def counters():
    out = {}
    for name in ('memory.events', 'cpu.stat', 'pids.events'):
        try:
            out[name] = dict(line.split() for line in (Path('/sys/fs/cgroup') / name).read_text().splitlines())
        except (OSError, ValueError):
            out[name] = None
    return out


def drop_task():
    os.setgroups([]); os.setgid(65534); os.setuid(65534)
    # Linux setuid from UID0 clears permitted/effective/ambient capabilities.
    status = Path('/proc/self/status').read_text()
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    if int(fields['CapEff'].strip(), 16) or int(fields['CapPrm'].strip(), 16) or int(fields['CapAmb'].strip(), 16) or fields['NoNewPrivs'].strip() != '1':
        raise ValueError('Task privilege drop failed')
    os.umask(0o077)


def stop_namespace(child=None):
    # Fail before any signal unless this really is Linux namespace init.
    if sys.platform != 'linux' or os.getpid() != 1 or os.getuid() != 0:
        raise ValueError('Namespace cleanup requires container root PID1')
    try:
        os.kill(-1, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if child is not None:
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Namespace task did not stop') from exc
    deadline = time.monotonic() + 3
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                if time.monotonic() >= deadline:
                    raise ValueError('Namespace descendants did not reap')
                time.sleep(0.01)
        except ChildProcessError:
            return


def cancel_signal(_signum, _frame):
    global _CANCEL
    _CANCEL = True


def record(manifest, binding, state, **extra):
    return {'schema_version': 1, 'job_id': manifest['job_id'], 'nonce': binding['nonce'],
            'manifest_sha256': binding['manifest_sha256'], 'state': state, 'exit_code': None,
            'reason': None, 'effective_limits': {}, 'artifacts': [],
            'missing_outputs': list(manifest['outputs']), 'logs': {}, **extra}


def checked_binding():
    manifest, binding = load(RUNNER / 'manifest.json'), load(RUNNER / 'binding.json')
    if binding['manifest_sha256'] != digest(canonical(manifest)):
        raise ValueError('Manifest binding changed')
    if binding['supervisor_sha256'] != digest(regular_bytes(RUNNER / 'linux_supervisor.py', 128 * 1024)):
        raise ValueError('Supervisor binding changed')
    return manifest, binding


def finalize_files(manifest, result):
    resources = manifest['resources']
    artifacts, missing, total = [], [], 0
    for name in manifest['outputs']:
        path = confined(WORK, name)
        if not path.exists():
            missing.append(name); continue
        raw = regular_bytes(path, resources['max_output_bytes'] - total)
        total += len(raw)
        artifacts.append({'name': name, 'sha256': digest(raw), 'size': len(raw)})
    result.update(artifacts=artifacts, missing_outputs=missing)
    if missing and result['state'] == 'succeeded':
        result.update(state='failed', reason='Declared output missing')
    logs = {}
    for name in ('stdout', 'stderr'):
        raw = regular_bytes(CONTROL / (name + '.log'), resources['max_log_bytes'])
        logs[name] = {'name': name + '.log', 'sha256': digest(raw), 'size': len(raw)}
    result['logs'] = logs


def run():
    if sys.platform != 'linux' or os.getpid() != 1 or os.getuid() != 0:
        raise ValueError('Run is allowed only as Linux root container PID1')
    manifest, binding = checked_binding()
    context = {'phase': 'setup', 'launch_attempted': False, 'cleanup_attempted': False,
               'cleanup_confirmed': False, 'retention_deadline': None, 'primary': None}
    try:
        return run_bound(manifest, binding, context)
    except Exception as exc:
        return retain_fault(manifest, binding, context, exc)


def run_bound(manifest, binding, context):
    """Internal orchestration; entry is exclusively the guarded run() path."""
    resources = manifest['resources']
    signal.signal(signal.SIGTERM, cancel_signal)
    signal.signal(signal.SIGINT, cancel_signal)
    result = record(manifest, binding, 'running')
    child = None
    logs = {}
    try:
        CONTROL.chmod(0o700)
        result['effective_limits'] = effective_limits(resources)
        for name in ('stdout', 'stderr'):
            logs[name] = (CONTROL / (name + '.log')).open('xb')
        for entry in manifest['inputs']:
            raw = regular_bytes(confined(Path('/inputs'), entry['destination']), 8 * 1024 * 1024)
            if digest(raw) != entry['sha256']:
                raise ValueError('Staged input hash changed')
            target = confined(WORK, entry['destination'])
            target.parent.mkdir(parents=True, exist_ok=True)
            # Root-owned sticky directories allow output siblings while protecting root-owned inputs.
            current = target.parent
            while current != WORK:
                current.chmod(0o1777); current = current.parent
            with target.open('xb') as stream:
                stream.write(raw)
            target.chmod(0o444)
        atomic(CONTROL / 'status.json', result)
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': '/tmp',
               'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': str(max(1, resources['cpu_millis'] // 1000)),
               'OPENBLAS_NUM_THREADS': str(max(1, resources['cpu_millis'] // 1000))}
        started = time.monotonic()
        context['phase'] = 'task_launch'
        context['launch_attempted'] = True  # Popen can raise without returning a child handle.
        child = subprocess.Popen(manifest['argv'], cwd=WORK, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                 start_new_session=True, preexec_fn=drop_task, close_fds=True)
        context['phase'] = 'task_io'
        selector = selectors.DefaultSelector()
        kept = {'stdout': 0, 'stderr': 0}
        truncated = {'stdout': False, 'stderr': False}
        for name in kept:
            pipe = getattr(child, name); os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while True:
            if _CANCEL:
                result.update(state='cancelled', reason='PID1 received cancellation'); break
            if time.monotonic() - started >= resources['wall_seconds']:
                result.update(state='timed_out', reason='Independent wall deadline exceeded'); break
            for key, _ in selector.select(0.03):
                try:
                    raw = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                name = key.data
                if not raw:
                    selector.unregister(key.fileobj); key.fileobj.close(); continue
                room = resources['max_log_bytes'] - kept[name]
                logs[name].write(raw[:room]); kept[name] += min(room, len(raw))
                if len(raw) > room:
                    truncated[name] = True
            if child.poll() is not None:
                result.update(state='succeeded' if child.returncode == 0 else 'failed',
                              exit_code=child.returncode, reason=None if child.returncode == 0 else 'Task exited nonzero')
                break
        context.update(phase='namespace_cleanup', cleanup_attempted=True)
        stop_namespace(child)
        context['cleanup_confirmed'] = True
        context['phase'] = 'task_io'
        # Drain any final bytes after every writer has stopped, without blocking.
        for key in list(selector.get_map().values()):
            name = key.data
            while True:
                try:
                    raw = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    break
                if not raw:
                    break
                room = resources['max_log_bytes'] - kept[name]
                logs[name].write(raw[:room]); kept[name] += min(room, len(raw))
                if len(raw) > room:
                    truncated[name] = True
            key.fileobj.close()
        selector.close()
        result['exit_code'] = child.returncode
        result['log_truncated'] = truncated
    except Exception as exc:
        context['primary'] = error_detail(exc, context['phase'])
        result.update(state='failed', reason=type(exc).__name__ + ': ' + str(exc)[:1000])
        if context['cleanup_attempted'] and not context['cleanup_confirmed']:
            raise  # Do not retry uncertain namespace termination or retain live work.
        if child is not None and not context['cleanup_confirmed']:
            context.update(phase='namespace_cleanup', cleanup_attempted=True)
            stop_namespace(child)
            context['cleanup_confirmed'] = True
        if context['launch_attempted'] and not context['cleanup_confirmed']:
            raise  # Missing Popen handle is not evidence that no task was launched.
    finally:
        previous_phase = context['phase']
        context['phase'] = 'log_close'
        for stream in logs.values():
            stream.close()
        context['phase'] = previous_phase
    context['phase'] = 'artifact_finalize'
    try:
        finalize_files(manifest, result)
    except Exception as exc:
        result.update(state='failed', reason='Unsafe/unavailable outputs: ' + str(exc)[:1000], artifacts=[])
    context['phase'] = 'counters'
    result['cgroup_counters'] = counters()
    result['finished_at'] = time.time()
    result['expires_at'] = time.time() + resources['retention_seconds']
    context['phase'] = 'receipt_publish'
    context['retention_deadline'] = time.monotonic() + resources['retention_seconds']
    atomic(CONTROL / 'status.json', result)
    context['phase'] = 'retention'
    expires = context['retention_deadline']
    while time.monotonic() < expires:
        time.sleep(min(0.1, max(0.0, expires - time.monotonic())))
    return 0 if result['state'] == 'succeeded' else 1


def report(include_files=False):
    manifest, binding = checked_binding()
    fault = read_fault(manifest, binding)
    if fault is not None:
        if include_files:
            raise ValueError('Supervisor fault cannot be collected as task artifacts')
        packet = {'schema_version': 1, 'job_id': manifest['job_id'], 'nonce': binding['nonce'],
                  'manifest_sha256': binding['manifest_sha256'], 'state': 'artifacts_unavailable',
                  'supervisor_fault': fault}
        sys.stdout.buffer.write(canonical(packet) + b'\n')
        return 0
    result = load(CONTROL / 'status.json')
    if any(result[k] != expected for k, expected in (
        ('job_id', manifest['job_id']), ('nonce', binding['nonce']),
        ('manifest_sha256', binding['manifest_sha256']))):
        raise ValueError('Receipt identity mismatch')
    if include_files:
        if result['state'] not in TERMINAL:
            raise ValueError('Only terminal receipts can be collected')
        total = 0
        for entry in result['artifacts']:
            raw = regular_bytes(confined(WORK, entry['name']), manifest['resources']['max_output_bytes'] - total)
            total += len(raw)
            if digest(raw) != entry['sha256'] or len(raw) != entry['size']:
                raise ValueError('Output changed after receipt')
            entry['data_base64'] = base64.b64encode(raw).decode('ascii')
        for name, entry in result['logs'].items():
            raw = regular_bytes(CONTROL / (name + '.log'), manifest['resources']['max_log_bytes'])
            if digest(raw) != entry['sha256'] or len(raw) != entry['size']:
                raise ValueError('Log changed after receipt')
            entry['data_base64'] = base64.b64encode(raw).decode('ascii')
    raw = canonical(result)
    if len(raw) > MAX_RPC:
        raise ValueError('Receipt RPC limit')
    sys.stdout.buffer.write(raw + b'\n')
    return 0


def _checkpoint_parts(name):
    if not isinstance(name, str) or not name or len(name) > 512 or any(c in name for c in ('\\', '\x00', '\n', '\r')):
        raise ValueError('Bounded confined checkpoint path required')
    p = PurePosixPath(name)
    if p.is_absolute() or str(p) != name or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('Normalized checkpoint path required')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10)), *(f'COM{i}' for i in '¹²³'), *(f'LPT{i}' for i in '¹²³')}
    if name != unicodedata.normalize('NFC', name):
        raise ValueError('Checkpoint path requires NFC Unicode')
    for part in p.parts:
        low = part.casefold()
        if any(ord(c) < 32 or ord(c) == 127 or c in '<>:"|?*' for c in part) or part.endswith(('.', ' ')) or part.split('.')[0].upper() in reserved or low in ('.ssh', '.aws', '.git', '.codex', '.checkpoint.json', '.collection.json', '.logs') or low == '.env' or low.startswith('.env.'):
            raise ValueError('Nonportable/configuration checkpoint path forbidden')
    return p.parts


def _checkpoint_dir(parent_fd, parts):
    # Every component is opened relative to an already held directory. A task
    # can rename its directories, but cannot replace this anchor with a symlink.
    fd = os.dup(parent_fd)
    try:
        for part in parts:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = new
        return fd
    except Exception:
        os.close(fd); raise


def _checkpoint_read(parent_fd, name, maximum):
    parts = _checkpoint_parts(name)
    directory = _checkpoint_dir(parent_fd, parts[:-1])
    fd = None
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError('Bounded regular non-hardlinked checkpoint file required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        if len(raw) > maximum or identity(before) != identity(after):
            raise ValueError('Checkpoint file changed while reading')
        return raw, identity(after)
    finally:
        if fd is not None: os.close(fd)
        os.close(directory)


def checkpoint():
    """Read an application-published immutable generation without pausing work."""
    manifest, binding = checked_binding()
    if read_fault(manifest, binding) is not None:
        raise ValueError('Supervisor fault cannot supply a checkpoint')
    if manifest.get('schema_version') != 2:
        raise ValueError('Checkpoint capture requires opt-in manifest schema2')
    cp = manifest['checkpoint']
    if not isinstance(cp, dict) or set(cp) != {'directory', 'max_bytes', 'max_files'} or type(cp['max_bytes']) is not int or not 1 <= cp['max_bytes'] <= 16 * 1024**2 or type(cp['max_files']) is not int or not 1 <= cp['max_files'] <= 32:
        raise ValueError('Checkpoint configuration bounds invalid')
    work_fd = os.open(WORK, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    cp_fd = gen_fd = None
    try:
        cp_fd = _checkpoint_dir(work_fd, _checkpoint_parts(cp['directory']))
        before, before_identity = _checkpoint_read(cp_fd, 'ready.json', 64 * 1024)
        ready = json.loads(before, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite checkpoint JSON')))
        if not isinstance(ready, dict) or set(ready) != {'schema_version', 'checkpoint_id', 'application', 'files'} or type(ready['schema_version']) is not int or ready['schema_version'] != 1:
            raise ValueError('Exact checkpoint declaration schema1 required')
        import re
        identity = ready['checkpoint_id']
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
            raise ValueError('Checkpoint generation must be32lowercasehex')
        app = ready['application']
        if not isinstance(app, dict) or set(app) != {'format', 'version', 'resume_notes'}:
            raise ValueError('Exact checkpoint application fields required')
        for name in ('format', 'version'):
            if not isinstance(app[name], str) or not app[name].strip() or len(app[name]) > 128 or any(c in app[name] for c in ('\x00', '\n', '\r')):
                raise ValueError('Bounded checkpoint application format/version required')
        if not isinstance(app['resume_notes'], str) or len(app['resume_notes'].encode('utf-8')) > 8192 or '\x00' in app['resume_notes']:
            raise ValueError('Bounded checkpoint notes required')
        if not isinstance(ready['files'], list) or not 1 <= len(ready['files']) <= cp['max_files']:
            raise ValueError('Checkpoint file count invalid')
        names, total = [], 0
        for item in ready['files']:
            if not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256'}:
                raise ValueError('Exact checkpoint file declaration fields required')
            _checkpoint_parts(item['path'])
            if type(item['size']) is not int or not 0 <= item['size'] <= 8 * 1024**2 or not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
                raise ValueError('Checkpoint size/hash invalid')
            names.append(PurePosixPath(unicodedata.normalize('NFC', item['path'].casefold()))); total += item['size']
        if total > cp['max_bytes'] or len(names) != len(set(names)) or any(a != b and a in b.parents for a in names for b in names):
            raise ValueError('Checkpoint total or aliased inventory invalid')
        gen_fd = _checkpoint_dir(cp_fd, (identity,))
        files = []
        for item in ready['files']:
            raw, _ = _checkpoint_read(gen_fd, item['path'], item['size'])
            if len(raw) != item['size'] or digest(raw) != item['sha256']:
                raise ValueError('Checkpoint content differs from declaration')
            files.append({**item, 'data_base64': base64.b64encode(raw).decode('ascii')})
        after, after_identity = _checkpoint_read(cp_fd, 'ready.json', 64 * 1024)
        if before != after or before_identity != after_identity:
            raise ValueError('Checkpoint declaration changed during capture')
        result = {'schema_version': 1, 'job_id': manifest['job_id'], 'nonce': binding['nonce'],
                  'manifest_sha256': binding['manifest_sha256'], 'checkpoint_id': identity,
                  'application': app, 'files': files, 'consistency': 'application_declared_not_automatically_verified'}
        raw = canonical(result)
        if len(raw) > MAX_RPC:
            raise ValueError('Checkpoint capture exceeds RPC byte bound')
        sys.stdout.buffer.write(raw + b'\n')
        return 0
    finally:
        if gen_fd is not None: os.close(gen_fd)
        if cp_fd is not None: os.close(cp_fd)
        os.close(work_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('run', 'status', 'collect', 'checkpoint'))
    args = parser.parse_args()
    try:
        return run() if args.operation == 'run' else checkpoint() if args.operation == 'checkpoint' else report(args.operation == 'collect')
    except Exception as exc:
        detail = error_detail(exc, 'setup')
        try:
            print(json.dumps({'error': detail['exception_type'] + ': ' + detail['message']}, ensure_ascii=False), file=sys.stderr)
        except Exception:
            pass
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
