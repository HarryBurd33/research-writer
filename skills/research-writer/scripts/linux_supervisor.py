#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Linux container PID1 supervisor; never run `run` outside the selected container."""
from __future__ import annotations
import argparse
import base64
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

CONTROL = Path('/control')
WORK = Path('/work')
RUNNER = Path('/runner')
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
MAX_RPC = 32 * 1024 * 1024
_CANCEL = False


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
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
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
        child = subprocess.Popen(manifest['argv'], cwd=WORK, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                 start_new_session=True, preexec_fn=drop_task, close_fds=True)
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
        stop_namespace(child)
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
        result.update(state='failed', reason=type(exc).__name__ + ': ' + str(exc)[:1000])
        if child is not None:
            stop_namespace(child)
    finally:
        for stream in logs.values():
            stream.close()
    try:
        finalize_files(manifest, result)
    except Exception as exc:
        result.update(state='failed', reason='Unsafe/unavailable outputs: ' + str(exc)[:1000], artifacts=[])
    result['cgroup_counters'] = counters()
    result['finished_at'] = time.time()
    result['expires_at'] = time.time() + resources['retention_seconds']
    atomic(CONTROL / 'status.json', result)
    expires = time.monotonic() + resources['retention_seconds']
    while time.monotonic() < expires:
        time.sleep(min(0.1, max(0.0, expires - time.monotonic())))
    return 0 if result['state'] == 'succeeded' else 1


def report(include_files=False):
    manifest, binding = checked_binding()
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('run', 'status', 'collect'))
    args = parser.parse_args()
    try:
        return run() if args.operation == 'run' else report(args.operation == 'collect')
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__ + ': ' + str(exc)[:1000]}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
