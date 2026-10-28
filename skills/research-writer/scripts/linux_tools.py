#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional explicit local-Docker Linux/cgroup-v2 CPU lifecycle. Profiles are not permission."""
from __future__ import annotations
import argparse
import base64
import ctypes
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
MAX_RPC = 32 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_INPUT = 16 * 1024 * 1024
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
LIMITS = {'wall_seconds': (1, 3600), 'retention_seconds': (5, 3600),
          'memory_bytes': (64 * 1024**2, 8 * 1024**3), 'cpu_millis': (100, 16000),
          'pids': (16, 512), 'work_bytes': (1024**2, 256 * 1024**2),
          'tmp_bytes': (1024**2, 64 * 1024**2), 'max_log_bytes': (1, 1024**2),
          'max_output_bytes': (1, 16 * 1024**2)}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('Duplicate JSON key: ' + key)
        out[key] = value
    return out


def decode(raw):
    if len(raw) > MAX_RPC:
        raise ValueError('JSON exceeds RPC bound')
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def regular(path, limit=MAX_RPC):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise ValueError('Bounded regular non-hardlinked file required: ' + str(path))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    try:
        actual = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValueError('File identity changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        if len(raw) > limit or (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Input changed/oversized')
        return raw
    finally:
        os.close(fd)


def read_json(path):
    return decode(regular(path))


def fsync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def save(path, value, exclusive=False):
    path = Path(path)
    raw = canonical(value) + b'\n'
    if exclusive:
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        fsync_directory(path.parent)
        return
    if path.is_symlink():
        raise ValueError('State symlink forbidden')
    fd, name = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path); fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def line(value, name):
    if not isinstance(value, str) or not value or any(x in value for x in ('\x00', '\n', '\r')) or len(value) > 4096:
        raise ValueError('Invalid single-line ' + name)
    return value


def relative(value):
    line(value, 'path')
    p, w = PurePosixPath(value), PureWindowsPath(value)
    if len(value) > 512 or p.is_absolute() or w.drive or '\\' in value or str(p) != value or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('Confined normalized POSIX relative path required')
    if any(x in ('.ssh', '.aws', '.git', '.codex', '.collection.json', '.logs') or x == '.env' or x.startswith('.env.') for x in p.parts):
        raise ValueError('Credential/configuration/reserved path forbidden')
    return value


def no_symlinks(path):
    path = Path(path).absolute()
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError('Symlink path component forbidden: ' + str(parent))
    return path


def profile(value):
    fields = {'schema_version', 'docker_executable', 'context', 'expected_engine_id', 'container_python'}
    if not isinstance(value, dict) or set(value) != fields or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Exact profile schema1 fields required; no credentials')
    p = dict(value)
    binary = Path(line(p['docker_executable'], 'docker_executable'))
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Explicit existing absolute Docker executable required')
    if not isinstance(p['context'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', p['context']):
        raise ValueError('Explicit existing plain context name required')
    if p['expected_engine_id'] is not None:
        line(p['expected_engine_id'], 'expected_engine_id')
    python = line(p['container_python'], 'container_python')
    if not PurePosixPath(python).is_absolute() or '..' in PurePosixPath(python).parts:
        raise ValueError('Absolute container Python path required')
    return p


def validate_manifest(m):
    fields = {'schema_version', 'job_id', 'image_id', 'argv', 'inputs', 'outputs', 'resources', 'required_device'}
    if not isinstance(m, dict) or set(m) != fields or type(m['schema_version']) is not int or m['schema_version'] != 1:
        raise ValueError('Exact manifest schema1 fields required')
    if not isinstance(m['job_id'], str) or not re.fullmatch('[0-9a-f]{32}', m['job_id']):
        raise ValueError('32 lowercase hexadecimal job_id required')
    if not isinstance(m['image_id'], str) or not re.fullmatch('sha256:[0-9a-f]{64}', m['image_id']):
        raise ValueError('Existing immutable local image ID required, not a tag')
    argv = m['argv']
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or any(not isinstance(a, str) or not a or len(a) > 4096 or '\x00' in a for a in argv) or sum(map(len, argv)) > 32768:
        raise ValueError('Bounded explicit argv array required')
    if m['required_device'] != 'cpu':
        raise ValueError('Only CPU is accepted by this backend')
    r = m['resources']
    if not isinstance(r, dict) or set(r) != set(LIMITS):
        raise ValueError('Exact resource bounds required')
    for name, (low, high) in LIMITS.items():
        if type(r[name]) is not int or not low <= r[name] <= high:
            raise ValueError('Resource outside integer bounds: ' + name)
    if any(r[name] % (1024**2) for name in ('memory_bytes', 'work_bytes', 'tmp_bytes')):
        raise ValueError('Memory/work/tmp byte budgets must be whole MiB to avoid kernel rounding')
    if not isinstance(m['inputs'], list) or len(m['inputs']) > 32 or not isinstance(m['outputs'], list) or not 1 <= len(m['outputs']) <= 32:
        raise ValueError('Explicit bounded input/output lists required')
    names = []
    for entry in m['inputs']:
        if not isinstance(entry, dict) or set(entry) != {'source', 'destination', 'sha256'}:
            raise ValueError('Exact input fields required')
        relative(entry['source']); names.append(relative(entry['destination']))
        if not isinstance(entry['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise ValueError('Input SHA256 required')
    outputs = [relative(x) for x in m['outputs']]
    all_names = names + outputs
    if len(all_names) != len(set(all_names)):
        raise ValueError('Duplicate/overlapping paths')
    paths = list(map(PurePosixPath, all_names))
    if any(a != b and a in b.parents for a in paths for b in paths):
        raise ValueError('Parent/child file conflict')
    return m


def bounded_run(argv, timeout=30, maximum=MAX_RPC):
    """Capture each pipe under a hard byte cap, including on Windows clients."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            shell=False, close_fds=True)
    buffers = {'out': bytearray(), 'err': bytearray()}
    overflow = threading.Event()
    def drain(pipe, name):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                room = maximum - len(buffers[name])
                buffers[name].extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break
        finally:
            pipe.close()
    threads = [threading.Thread(target=drain, args=(proc.stdout, 'out'), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, 'err'), daemon=True)]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(timeout=5)
        raise ValueError('Docker reply timed out; reconcile existing intent, never resubmit')
    finally:
        for thread in threads:
            thread.join(timeout=5)
    if overflow.is_set() or any(t.is_alive() for t in threads):
        raise ValueError('Docker reply exceeded byte bound or pipe failed to close')
    return proc.returncode, bytes(buffers['out']), bytes(buffers['err'])


def docker(p, args, timeout=30, allow_missing=False):
    code, out, err = bounded_run([p['docker_executable'], '--context', p['context'], *args], timeout)
    if code:
        message = err.decode('utf-8', errors='replace')[:1500]
        if allow_missing and ('No such object' in message or 'No such container' in message):
            return None
        raise ValueError('Docker operation failed: ' + message)
    return out


def inspect_engine(p):
    # Explicit context overrides DOCKER_HOST; never use an implicit selected remote daemon.
    raw = docker(p, ['context', 'inspect', p['context'], '--format', '{{json .Endpoints.docker.Host}}'])
    endpoint = decode(raw)
    if not isinstance(endpoint, str) or not endpoint.startswith(('unix://', 'npipe://')):
        raise ValueError('Only explicit local unix/npipe Docker contexts are supported')
    fmt = '{"id":{{json .ID}},"os":{{json .OSType}},"cgroup_version":{{json .CgroupVersion}},"architecture":{{json .Architecture}},"version":{{json .ServerVersion}},"security_options":{{json .SecurityOptions}}}'
    info = decode(docker(p, ['info', '--format', fmt]))
    if info.get('os') != 'linux' or str(info.get('cgroup_version')) != '2' or not isinstance(info.get('id'), str) or not info['id']:
        raise ValueError('Selected engine must be Linux with cgroupv2 and a stable ID')
    if any('rootless' in str(v).lower() for v in info.get('security_options', [])):
        raise ValueError('Rootless engine is not accepted by this tested configuration')
    if p['expected_engine_id'] is not None and p['expected_engine_id'] != info['id']:
        raise ValueError('Pinned engine identity mismatch')
    return info


def inspect_image(p, image_id):
    fmt = '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},"volumes":{{json .Config.Volumes}}}'
    image = decode(docker(p, ['image', 'inspect', image_id, '--format', fmt]))
    if image.get('id') != image_id or image.get('os') != 'linux' or image.get('volumes'):
        raise ValueError('Image identity/OS mismatch or declared writable volumes')
    return image


def staged_paths(state):
    root = Path(state['state_directory'])
    return root / 'runner', root / 'inputs'


def labels(state):
    return {'rw.job_id': state['manifest']['job_id'], 'rw.nonce': state['binding']['nonce'],
            'rw.manifest_sha256': state['binding']['manifest_sha256'],
            'rw.supervisor_sha256': state['binding']['supervisor_sha256']}


def run_arguments(state):
    p, m = state['profile'], state['manifest']
    r = m['resources']; runner, inputs = staged_paths(state)
    args = ['run', '--detach', '--pull=never', '--name', state['container_name'], '--restart=no',
            '--init=false', '--read-only', '--network=none', '--ipc=private', '--cgroupns=private',
            '--cap-drop=ALL', '--cap-add=SETUID', '--cap-add=SETGID', '--cap-add=KILL', '--cap-add=DAC_OVERRIDE',
            '--security-opt=no-new-privileges', '--log-driver=none', '--no-healthcheck', '--user=0:0',
            '--workdir=/work', '--entrypoint', p['container_python'], '--memory', str(r['memory_bytes']),
            '--memory-swap', str(r['memory_bytes']), '--cpus', format(r['cpu_millis'] / 1000, '.3f'),
            '--pids-limit', str(r['pids']), '--shm-size', str(1024**2)]
    for target, size, mode in [('/work', r['work_bytes'], '1777'), ('/tmp', r['tmp_bytes'], '1777'), ('/control', 4 * 1024**2, '0700')]:
        args += ['--tmpfs', f'{target}:rw,nosuid,nodev,size={size},mode={mode},nr_inodes={128 if target == "/control" else 1024}']
    mounts = [(runner, '/runner'), (inputs, '/inputs')]
    mounts += [(runner / name, '/etc/' + name) for name in ('hosts', 'hostname', 'resolv.conf')]
    for source, target in mounts:
        value = str(source)
        if any(x in value for x in (',', '\n', '\r', '\x00')):
            raise ValueError('Bind paths may not contain comma/newline/NUL')
        args += ['--mount', f'type=bind,source={value},target={target},readonly']
    for key, value in labels(state).items():
        args += ['--label', key + '=' + value]
    return args + [m['image_id'], '/runner/linux_supervisor.py', 'run']


def normalize_capabilities(values):
    """Accept Docker's legacy/plain or CAP_ inspect spelling, without extras."""
    if not isinstance(values, list):
        raise ValueError('Capabilities must be an explicit string list')
    normalized = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,63}', value):
            raise ValueError('Invalid capability representation')
        name = value[4:] if value.startswith('CAP_') else value
        if not name or name.startswith('CAP_') or name == 'ALL' and value != 'ALL':
            raise ValueError('Invalid repeated/special capability prefix')
        normalized.append(name)
    if len(set(normalized)) != len(normalized):
        raise ValueError('Duplicate capability representation')
    return set(normalized)


def check_container(state, obj):
    p, m, r = state['profile'], state['manifest'], state['manifest']['resources']
    if not re.fullmatch('[0-9a-f]{64}', obj.get('Id', '')) or state.get('container_id') and obj['Id'] != state['container_id']:
        raise ValueError('Immutable container ID mismatch')
    config, host = obj['Config'], obj['HostConfig']
    if obj.get('Name') != '/' + state['container_name'] or obj.get('Image') != m['image_id'] or config.get('Labels') != labels(state):
        # Image-supplied labels can coexist, but every requested binding must match.
        if obj.get('Name') != '/' + state['container_name'] or obj.get('Image') != m['image_id'] or any(config.get('Labels', {}).get(k) != v for k, v in labels(state).items()):
            raise ValueError('Container name/image/ownership binding mismatch')
    if config.get('User') != '0:0' or config.get('WorkingDir') != '/work' or config.get('Entrypoint') != [p['container_python']] or config.get('Cmd') != ['/runner/linux_supervisor.py', 'run'] or config.get('Volumes') or config.get('Healthcheck', {}).get('Test') != ['NONE']:
        raise ValueError('Container executable/config changed')
    expected = {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'IpcMode': 'private', 'CgroupnsMode': 'private',
                'Memory': r['memory_bytes'], 'MemorySwap': r['memory_bytes'], 'PidsLimit': r['pids'],
                'NanoCpus': r['cpu_millis'] * 1000000, 'ShmSize': 1024**2, 'Privileged': False,
                'PidMode': '', 'AutoRemove': False}
    if any(host.get(k) != v for k, v in expected.items()) or host.get('Init') not in (False, None):
        raise ValueError('Effective isolation configuration changed')
    if host.get('RestartPolicy', {}).get('Name') != 'no' or host.get('LogConfig', {}).get('Type') != 'none' or host.get('Devices') or host.get('DeviceRequests'):
        raise ValueError('Unexpected restart/log/device configuration')
    drop = normalize_capabilities(host.get('CapDrop'))
    added = normalize_capabilities(host.get('CapAdd'))
    if drop != {'ALL'} or added != {'SETUID', 'SETGID', 'KILL', 'DAC_OVERRIDE'}:
        # Only validated bounded capability names enter diagnostics, never env/config.
        raise ValueError('Capabilities changed: add=' + repr(sorted(added)) + ', drop=' + repr(sorted(drop)))
    if set(host.get('SecurityOpt') or []) != {'no-new-privileges'}:
        raise ValueError('Security options changed')
    expected_tmpfs = {target: f'rw,nosuid,nodev,size={size},mode={mode},nr_inodes={128 if target == "/control" else 1024}' for target, size, mode in (
        ('/work', r['work_bytes'], '1777'), ('/tmp', r['tmp_bytes'], '1777'), ('/control', 4 * 1024**2, '0700'))}
    if host.get('Tmpfs') != expected_tmpfs:
        raise ValueError('Temporary filesystem bounds changed')
    runner, inputs = staged_paths(state)
    expected_mounts = {'/runner': str(runner), '/inputs': str(inputs), **{'/etc/' + n: str(runner / n) for n in ('hosts', 'hostname', 'resolv.conf')}}
    observed = {x['Destination']: x for x in obj.get('Mounts', []) if x.get('Type') != 'tmpfs'}
    if set(observed) != set(expected_mounts) or any(observed[d].get('Type') != 'bind' or observed[d].get('RW') is not False or observed[d].get('Source') != source for d, source in expected_mounts.items()):
        raise ValueError('Unexpected writable/mismatched host mount')
    return obj


def inspect_container(state):
    name = state.get('container_id') or state['container_name']
    # Avoid fetching image environment variables or daemon credentials.
    fmt = '{"Id":{{json .Id}},"Image":{{json .Image}},"Name":{{json .Name}},"State":{{json .State}},"Mounts":{{json .Mounts}},"HostConfig":{{json .HostConfig}},"Config":{"Labels":{{json .Config.Labels}},"User":{{json .Config.User}},"WorkingDir":{{json .Config.WorkingDir}},"Entrypoint":{{json .Config.Entrypoint}},"Cmd":{{json .Config.Cmd}},"Volumes":{{json .Config.Volumes}},"Healthcheck":{{json .Config.Healthcheck}}}}'
    raw = docker(state['profile'], ['container', 'inspect', name, '--format', fmt], allow_missing=True)
    if raw is None and state.get('container_id'):
        # A changed/stale saved ID must not hide a differently identified object
        # still occupying the permanently bound name. Reconcile reads only.
        raw = docker(state['profile'], ['container', 'inspect', state['container_name'], '--format', fmt], allow_missing=True)
    return None if raw is None else check_container(state, decode(raw))


@contextmanager
def state_lock(root):
    root = no_symlinks(root)
    if not root.is_dir():
        raise ValueError('Existing prepared state directory required')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    lock = root / '.lock'
    if lock.is_symlink():
        raise ValueError('Lock symlink forbidden')
    fd = os.open(lock, flags, 0o600)
    stream = os.fdopen(fd, 'r+b')
    acquired = False
    try:
        st = os.fstat(fd)
        now = lock.lstat()
        if lock.is_symlink() or (st.st_dev, st.st_ino) != (now.st_dev, now.st_ino):
            raise ValueError('Lock path identity changed')
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or os.name == 'posix' and st.st_uid != os.getuid():
            raise ValueError('Lock ownership/type changed')
        if st.st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                raise ValueError('Unsupported client lock platform')
            acquired = True
        except OSError as exc:
            raise ValueError('Another live client owns state; do not replace lock') from exc
        yield root
    finally:
        if acquired:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt
                stream.seek(0); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        stream.close()


def checked_state(root):
    state = read_json(root / 'state.json')
    state['profile'] = profile(state['profile']); validate_manifest(state['manifest'])
    if state['state_directory'] != str(root) or not re.fullmatch('[0-9a-f]{32}', state['binding']['nonce']):
        raise ValueError('State location/token changed')
    if digest(canonical(state['manifest'])) != state['binding']['manifest_sha256']:
        raise ValueError('State manifest hash changed')
    runner, inputs = staged_paths(state)
    if state['binding']['supervisor_sha256'] != digest(regular(no_symlinks(runner / 'linux_supervisor.py'), 128 * 1024)) or read_json(runner / 'manifest.json') != state['manifest'] or read_json(runner / 'binding.json') != state['binding']:
        raise ValueError('Prepared controller/manifest/binding changed')
    total = 0
    for entry in state['manifest']['inputs']:
        raw = regular(no_symlinks(inputs / entry['destination']), MAX_FILE)
        total += len(raw)
        if digest(raw) != entry['sha256'] or total > MAX_INPUT:
            raise ValueError('Staged input hash/size changed')
    inspect_engine(state['profile'])
    return state


def prepare(p, manifest_path, state_path, allow_stage=False):
    if not allow_stage:
        raise ValueError('Explicit --allow-stage required for approved files')
    if p['expected_engine_id'] is None:
        raise ValueError('Inspect and pin engine ID before staging')
    engine = inspect_engine(p)
    manifest_path = no_symlinks(manifest_path)
    m = validate_manifest(read_json(manifest_path))
    image = inspect_image(p, m['image_id'])
    # Native architecture only. Docker info uses x86_64/aarch64 on some versions.
    aliases = {'x86_64': 'amd64', 'aarch64': 'arm64'}
    if aliases.get(engine['architecture'], engine['architecture']) != image['architecture']:
        raise ValueError('Image/engine architecture mismatch; emulation is unvalidated')
    root = no_symlinks(state_path)
    if root.exists():
        raise ValueError('State destination must be new')
    if any(c in str(root) for c in (',', '\n', '\r', '\x00')):
        raise ValueError('State bind path contains unsupported delimiter')
    files, total = [], 0
    for entry in m['inputs']:
        source = no_symlinks(manifest_path.parent / entry['source'])
        if not source.is_relative_to(manifest_path.parent):
            raise ValueError('Input escaped manifest directory')
        raw = regular(source, MAX_FILE); total += len(raw)
        if digest(raw) != entry['sha256'] or total > MAX_INPUT:
            raise ValueError('Approved input hash/size mismatch')
        files.append((entry['destination'], raw))
    if total + 65536 > m['resources']['work_bytes']:
        raise ValueError('Work tmpfs has insufficient input headroom')
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    try:
        runner, inputs = root / 'runner', root / 'inputs'
        runner.mkdir(mode=0o755); inputs.mkdir(mode=0o755)
        code = regular(ROOT / 'linux_supervisor.py', 128 * 1024)
        binding = {'nonce': uuid.uuid4().hex, 'manifest_sha256': digest(canonical(m)), 'supervisor_sha256': digest(code)}
        (runner / 'linux_supervisor.py').write_bytes(code)
        save(runner / 'manifest.json', m, True); save(runner / 'binding.json', binding, True)
        for name, data in [('hosts', b'127.0.0.1 localhost\n::1 localhost\n'), ('hostname', b'research-writer\n'), ('resolv.conf', b'# network disabled\n')]:
            (runner / name).write_bytes(data)
        for name, raw in files:
            target = inputs / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        for folder in (runner, inputs):
            for child in folder.rglob('*'):
                child.chmod(0o555 if child.is_dir() else 0o444)
            folder.chmod(0o555)
        state = {'schema_version': 1, 'profile': p, 'manifest': m, 'binding': binding,
                 'state_directory': str(root), 'container_name': 'rw-' + m['job_id'] + '-' + binding['nonce'],
                 'container_id': None, 'submit_attempted': False, 'status': 'prepared', 'prepared_at': time.time()}
        save(root / 'state.json', state, True)
        return {'schema_version': 1, 'state': 'prepared', 'job_id': m['job_id'], 'engine': engine, 'image': image}
    except Exception:
        # Do not silently delete a partially staged state; it cannot be submitted without complete receipts.
        raise


def receipt(state, operation):
    raw = docker(state['profile'], ['exec', '--user', '0:0', state['container_id'], state['profile']['container_python'], '/runner/linux_supervisor.py', operation])
    result = decode(raw)
    for key, value in [('schema_version', 1), ('job_id', state['manifest']['job_id']),
                       ('nonce', state['binding']['nonce']), ('manifest_sha256', state['binding']['manifest_sha256'])]:
        if result.get(key) != value:
            raise ValueError('Supervisor receipt binding mismatch')
    if result.get('state') not in TERMINAL | {'running'}:
        raise ValueError('Unknown supervisor state')
    return result


def reconcile(root, state):
    obj = inspect_container(state)
    if obj is None:
        return {'schema_version': 1, 'state': 'uncertain' if state['submit_attempted'] else 'prepared',
                'job_id': state['manifest']['job_id'], 'reason': 'No bound container found; no relaunch performed', 'reexecuted': False}
    state['container_id'] = obj['Id']; save(root / 'state.json', state)
    if not obj['State'].get('Running'):
        return {'schema_version': 1, 'state': 'artifacts_unavailable', 'job_id': state['manifest']['job_id'],
                'container_id': obj['Id'], 'reason': 'Container stopped/expired; tmpfs artifacts are unavailable',
                'container_exit_code': obj['State'].get('ExitCode'), 'oom_killed': obj['State'].get('OOMKilled'), 'reexecuted': False}
    result = receipt(state, 'status')
    return {**result, 'container_id': obj['Id'], 'reexecuted': False}


def rename_new(source, destination):
    """Atomic publication without replacing even an existing empty directory."""
    if os.name == 'nt':
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    a, b = os.fsencode(source), os.fsencode(destination)
    if sys.platform == 'linux' and hasattr(libc, 'renameat2'):
        call = libc.renameat2
        call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        code = call(-100, a, -100, b, 1)  # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        call = libc.renamex_np
        call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        code = call(a, b, 4)  # RENAME_EXCL
    else:
        raise ValueError('Atomic no-replace directory publication unavailable')
    if code != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(destination))


def collect_files(root, state, result, destination):
    if result.get('state') not in TERMINAL:
        raise ValueError('Only a verified terminal receipt can be collected')
    destination = no_symlinks(destination)
    if destination.exists():
        raise ValueError('Collection destination must be new')
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError('Collection must be separate from state')
    m = state['manifest']; artifacts = result.get('artifacts')
    missing = result.get('missing_outputs')
    if not isinstance(artifacts, list) or not isinstance(missing, list) or len(artifacts) > len(m['outputs']) or len(missing) != len(set(missing)):
        raise ValueError('Malformed artifact inventory')
    expected = set(m['outputs']); found = set(); total = 0; decoded = []
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {'name', 'sha256', 'size', 'data_base64'}:
            raise ValueError('Invalid artifact record')
        name = relative(item['name'])
        if name not in expected or name in found or not isinstance(item['data_base64'], str) or len(item['data_base64']) > 4 * (m['resources']['max_output_bytes'] // 3 + 2):
            raise ValueError('Unexpected/duplicate/oversized artifact')
        raw = base64.b64decode(item['data_base64'], validate=True); total += len(raw)
        if type(item['size']) is not int or item['size'] != len(raw) or digest(raw) != item['sha256'] or total > m['resources']['max_output_bytes']:
            raise ValueError('Artifact hash/size mismatch')
        found.add(name); decoded.append((name, raw))
    if found & set(missing) or found | set(missing) != expected or result['state'] == 'succeeded' and missing:
        raise ValueError('Incomplete/misrepresented artifact inventory')
    logs = result.get('logs')
    if not isinstance(logs, dict) or set(logs) != {'stdout', 'stderr'}:
        raise ValueError('Missing bounded diagnostics')
    for key, item in logs.items():
        if not isinstance(item, dict) or set(item) != {'name', 'sha256', 'size', 'data_base64'} or item['name'] != key + '.log' or not isinstance(item['data_base64'], str) or len(item['data_base64']) > 4 * (m['resources']['max_log_bytes'] // 3 + 2):
            raise ValueError('Malformed log')
        raw = base64.b64decode(item['data_base64'], validate=True)
        if type(item['size']) is not int or len(raw) != item['size'] or len(raw) > m['resources']['max_log_bytes'] or digest(raw) != item['sha256']:
            raise ValueError('Log hash/size mismatch')
        decoded.append(('.logs/' + key + '.log', raw))
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.collection-', dir=destination.parent))
    try:
        for name, raw in decoded:
            path = stage / name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        summary = {**result, 'partial': result['state'] != 'succeeded' or bool(missing)}
        summary['artifacts'] = [{k: v for k, v in item.items() if k != 'data_base64'} for item in artifacts]
        summary['logs'] = {key: {k: v for k, v in item.items() if k != 'data_base64'} for key, item in logs.items()}
        save(stage / '.collection.json', summary, True)
        # Nonempty stage cannot replace an existing nonempty destination; protect empty dirs too.
        if destination.exists():
            raise ValueError('Destination appeared during collection')
        rename_new(stage, destination); fsync_directory(destination.parent)
        return summary
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def operate(operation, state_path, allow_execute=False, allow_cancel=False, allow_remove=False, destination=None):
    with state_lock(state_path) as root:
        state = checked_state(root)
        if operation == 'submit':
            if not allow_execute:
                raise ValueError('Explicit --allow-execute required')
            if state['submit_attempted']:
                return reconcile(root, state)
            if state.get('removed'):
                raise ValueError('Removed job cannot be resubmitted')
            inspect_image(state['profile'], state['manifest']['image_id'])
            if inspect_container(state) is not None:
                raise ValueError('Unexpected container predates permanent submission intent')
            state.update(submit_attempted=True, attempted_at=time.time(), status='uncertain')
            save(root / 'state.json', state)  # fsynced before any execution mutation
            try:
                raw = docker(state['profile'], run_arguments(state), timeout=45)
                identifier = raw.decode('ascii').strip()
                if not re.fullmatch('[0-9a-f]{64}', identifier):
                    raise ValueError('Invalid container create/start reply; recover by binding')
                state['container_id'] = identifier; save(root / 'state.json', state)
            except Exception as exc:
                state['last_error'] = str(exc)[:1500]; save(root / 'state.json', state)
                raise
            # Task may still be initializing; identity/config validation is mandatory.
            obj = inspect_container(state)
            return {'schema_version': 1, 'state': 'submitted', 'job_id': state['manifest']['job_id'],
                    'container_id': obj['Id'], 'reexecuted': False}
        if operation in ('status', 'recover'):
            return reconcile(root, state)
        if operation == 'collect':
            status = reconcile(root, state)
            if status.get('state') not in TERMINAL:
                return {**status, 'collected': False}
            result = receipt(state, 'collect')
            summary = collect_files(root, state, result, destination)
            state['collection'] = {'destination': str(Path(destination).absolute()), 'state': result['state'], 'collected_at': time.time()}
            save(root / 'state.json', state)
            return {**summary, 'collected': True, 'destination': str(Path(destination).absolute())}
        if operation == 'cancel':
            if not allow_cancel:
                raise ValueError('Explicit --allow-cancel required')
            obj = inspect_container(state)
            if obj is None:
                return reconcile(root, state)
            state['container_id'] = obj['Id']; save(root / 'state.json', state)
            if obj['State'].get('Running'):
                # Signal owned namespace PID1, never a saved host PID.
                docker(state['profile'], ['kill', '--signal=TERM', obj['Id']])
            return {'schema_version': 1, 'state': 'cancel_requested', 'container_id': obj['Id'], 'reexecuted': False}
        if operation == 'cleanup':
            if not allow_remove:
                raise ValueError('Explicit --allow-remove required')
            obj = inspect_container(state)
            if obj is not None:
                docker(state['profile'], ['rm', '--force', obj['Id']])
            state['removed'] = True; save(root / 'state.json', state)
            return {'schema_version': 1, 'state': 'removed', 'reexecuted': False}
        raise ValueError('Unknown operation')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for operation in ('inspect', 'prepare', 'submit', 'status', 'recover', 'collect', 'cancel', 'cleanup'):
        cmd = commands.add_parser(operation); cmd.add_argument('--report', required=True)
        if operation in ('inspect', 'prepare'):
            cmd.add_argument('--profile', required=True)
        if operation != 'inspect':
            cmd.add_argument('--state', required=True)
        if operation == 'prepare':
            cmd.add_argument('--manifest', required=True); cmd.add_argument('--allow-stage', action='store_true')
        if operation == 'submit':
            cmd.add_argument('--allow-execute', action='store_true')
        if operation == 'cancel':
            cmd.add_argument('--allow-cancel', action='store_true')
        if operation == 'cleanup':
            cmd.add_argument('--allow-remove', action='store_true')
        if operation == 'collect':
            cmd.add_argument('--destination', required=True)
    args = parser.parse_args(argv)
    report = None
    try:
        report = no_symlinks(args.report)
        if report.exists():
            raise ValueError('Report destination must be new')
        if args.operation == 'inspect':
            result = {'schema_version': 1, 'state': 'inspected', 'engine': inspect_engine(profile(read_json(args.profile)))}
        elif args.operation == 'prepare':
            result = prepare(profile(read_json(args.profile)), args.manifest, args.state, args.allow_stage)
        else:
            result = operate(args.operation, args.state, getattr(args, 'allow_execute', False),
                             getattr(args, 'allow_cancel', False), getattr(args, 'allow_remove', False),
                             getattr(args, 'destination', None))
        save(report, result, True)
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        error = {'schema_version': 1, 'state': 'uncertain', 'error': str(exc)[:1800], 'reexecuted': False}
        try:
            if report is not None and not report.exists() and not report.is_symlink():
                no_symlinks(report)
                save(report, error, True)
        except OSError:
            pass
        print(json.dumps(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
