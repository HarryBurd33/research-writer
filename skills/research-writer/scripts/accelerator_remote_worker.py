#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Authenticated POSIX worker for the fixed remote accelerator control."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

CONTRACT = 'research-writer.accelerator-remote/1'
MAX_REQUEST = 65536
MAX_SOURCE = 512 * 1024
MAX_RESULT = 1024 * 1024
HEARTBEAT_SECONDS = 1
STALE_SECONDS = 8
SOURCE_NAMES = {
    'accelerator_remote_worker.py', 'accelerator_tools.py', 'protein_tools.py',
    'remote_tools.py', 'remote_worker.py', 'transport_common.py',
}
OPERATIONS = {'inspect', 'prepare', 'submit', 'status', 'recover', 'collect', 'cancel'}
TERMINAL = {'succeeded', 'failed', 'timed_out', 'cancelled'}
SHA256 = re.compile(r'[0-9a-f]{64}')

# SSH sends a fixed isolated Python launcher. It verifies the exact bytes it
# executes before the worker loads any other skill module or site packages.
BOOTSTRAP = """import hashlib,json,stat,sys
from pathlib import Path
def start():
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError('Bootstrap request exceeds bound')
    req = json.loads(raw)
    path = Path(req['target']['scripts']) / 'accelerator_remote_worker.py'
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid worker source path')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Worker source symlink refused')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Worker source must be a regular file')
    with path.open('rb') as stream:
        source = stream.read(524289)
    if len(source) > 524288 or hashlib.sha256(source).hexdigest() != req['source_pins'][path.name]:
        raise ValueError('Installed worker source hash differs')
    name = 'accelerator_remote_worker'
    spec = __import__('importlib.util', fromlist=['spec_from_loader']).spec_from_loader(name, loader=None)
    module = __import__('types').ModuleType(name)
    module.__file__ = str(path)
    module.__spec__ = spec
    sys.modules[name] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
    module.entry(raw, sys.argv[1])
start()
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def refuse_constant(token):
    raise ValueError('Invalid JSON constant: ' + token)


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=refuse_constant)


def exact_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'Invalid {name} fields')


def posix_path(value):
    # The executable may itself be a venv symlink. All directory paths must be
    # spelled literally so an installation cannot silently move between calls.
    if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid absolute POSIX path')
    from pathlib import PurePosixPath
    path = PurePosixPath(value)
    if (not path.is_absolute() or len(path.parts) < 3 or '..' in path.parts
            or str(path) != value or value.startswith('//')):
        raise ValueError('An exact absolute POSIX path is required')
    return value


def checked_path(value, directory=False, executable_link=False):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('An exact absolute path is required')
    ancestors = path.parents if executable_link else (path, *path.parents)
    if any(item.is_symlink() for item in ancestors):
        raise ValueError('Symlink in selected path: ' + str(path))
    mode = path.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError('Wrong file type at selected path: ' + str(path))
    return path


def read_file(path, limit):
    with checked_path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds bound: ' + path.name)
    return data


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity():
    import pwd
    return {'hostname': socket.gethostname(), 'user': pwd.getpwuid(os.geteuid()).pw_name,
            'os': platform.system(), 'machine': platform.machine()}


def inventory(site_path):
    if os.name != 'posix' or platform.python_implementation() != 'CPython' or sys.version_info < (3, 11):
        raise ValueError('Remote worker requires POSIX CPython 3.11 or later')
    executable = checked_path(sys.executable, executable_link=True)
    site_dir = checked_path(posix_path(site_path), directory=True)
    distributions = {}
    for dist in importlib.metadata.distributions(path=[str(site_dir)]):
        name = re.sub(r'[-_.]+', '-', dist.metadata.get('Name', '')).lower()
        metadata = dist.read_text('METADATA')
        record = dist.read_text('RECORD')
        if not name or not metadata or not record or name in distributions:
            raise ValueError('Site packages require distinct wheel metadata and RECORD files')
        distributions[name] = {'version': dist.version, 'metadata_sha256': digest(metadata.encode('utf-8')),
                               'record_sha256': digest(record.encode('utf-8'))}
    if not {'torch', 'transformers', 'safetensors'} <= distributions.keys():
        raise ValueError('Selected site-packages must already contain torch, transformers and safetensors')
    venv_config = executable.parent.parent / 'pyvenv.cfg'
    return {
        'identity': identity(), 'python': str(executable), 'python_version': platform.python_version(),
        'python_sha256': file_sha(executable), 'site_packages': str(site_dir),
        'pyvenv_cfg_sha256': digest(read_file(venv_config, 65536)) if venv_config.exists() else None,
        'distributions': distributions,
    }


def validate_target(target):
    exact_fields(target, {'hostname', 'user', 'python', 'site_packages', 'scripts', 'model', 'jobs', 'runtime'}, 'target')
    for key in ('python', 'site_packages', 'scripts', 'model', 'jobs'):
        posix_path(target[key])
    for key in ('hostname', 'user'):
        if not isinstance(target[key], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,252}', target[key]):
            raise ValueError('Invalid selected host or user')
    runtime = target['runtime']
    exact_fields(runtime, {'identity', 'python', 'python_version', 'python_sha256', 'site_packages',
                           'pyvenv_cfg_sha256', 'distributions'}, 'runtime pin')
    exact_fields(runtime['identity'], {'hostname', 'user', 'os', 'machine'}, 'runtime identity')
    if any(runtime['identity'][key] != target[key] for key in ('hostname', 'user')) or any(
            runtime[key] != target[key] for key in ('python', 'site_packages')):
        raise ValueError('Target differs from runtime pin')
    for key in ('python_sha256', 'pyvenv_cfg_sha256'):
        value = runtime[key]
        if not (key == 'pyvenv_cfg_sha256' and value is None) and (
                not isinstance(value, str) or not SHA256.fullmatch(value)):
            raise ValueError('Invalid runtime digest')
    distributions = runtime['distributions']
    if not isinstance(distributions, dict) or not {'torch', 'transformers', 'safetensors'} <= distributions.keys():
        raise ValueError('Runtime pin requires selected package identities')
    for package in distributions.values():
        exact_fields(package, {'version', 'metadata_sha256', 'record_sha256'}, 'distribution pin')
        for key in ('metadata_sha256', 'record_sha256'):
            if not isinstance(package[key], str) or not SHA256.fullmatch(package[key]):
                raise ValueError('Invalid distribution digest')


class PinnedSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Load only the reviewed source bytes, without sibling pyc or sys.path."""
    def __init__(self, root, pins):
        self.root = root
        self.sources = {}
        for name, pin in pins.items():
            path = root / name
            raw = read_file(path, MAX_SOURCE)
            if digest(raw) != pin:
                raise ValueError('Installed skill source hash differs: ' + name)
            self.sources[path.stem] = raw

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.sources:
            return None
        return importlib.util.spec_from_file_location(fullname, self.root / (fullname + '.py'), loader=self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = self.sources[module.__name__]
        exec(compile(source, module.__file__, 'exec'), module.__dict__)


def check_source_pins(pins):
    exact_fields(pins, SOURCE_NAMES, 'source pins')
    if any(not isinstance(pin, str) or not SHA256.fullmatch(pin) for pin in pins.values()):
        raise ValueError('Invalid source digest')


def validate_workload(profile, target):
    exact_fields(profile, {'contract', 'expected_hostname', 'expected_user', 'device', 'wall_seconds',
                           'max_log_bytes', 'max_result_bytes', 'max_accelerator_memory_bytes', 'threads'},
                 'workload profile')
    if profile['contract'] != 'research-writer.accelerator-acceptance/1':
        raise ValueError('Invalid workload contract')
    if profile['expected_hostname'] != target['hostname'] or profile['expected_user'] != target['user']:
        raise ValueError('Workload host/user differs from target')
    if not isinstance(profile['device'], str) or not re.fullmatch(r'(?:mps|cuda:(?:[0-9]|1[0-5]))', profile['device']):
        raise ValueError('An explicit mps or cuda:N device is required')
    bounds = {'wall_seconds': (1, 120), 'max_log_bytes': (1024, MAX_RESULT),
              'max_result_bytes': (65536, MAX_RESULT), 'max_accelerator_memory_bytes': (128*1024**2, 2*1024**3),
              'threads': (1, 8)}
    for name, (low, high) in bounds.items():
        if type(profile[name]) is not int or not low <= profile[name] <= high:
            raise ValueError('Invalid workload bound: ' + name)


def validate_envelope(req, internal=False):
    exact_fields(req, {'contract', 'operation', 'target', 'source_pins', 'binding'}, 'request')
    if req['contract'] != CONTRACT:
        raise ValueError('Unknown accelerator remote contract')
    ops = {'controller', 'compute'} if internal else OPERATIONS
    if not isinstance(req['operation'], str) or req['operation'] not in ops:
        raise ValueError('Unexpected operation')
    validate_target(req['target'])
    check_source_pins(req['source_pins'])
    binding = req['binding']
    if req['operation'] == 'inspect':
        if binding is not None:
            raise ValueError('Inspect must be job-free')
        return
    exact_fields(binding, {'job_id', 'workload', 'control', 'assets'}, 'job binding')
    if not isinstance(binding['job_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', binding['job_id']):
        raise ValueError('Invalid job ID')
    if not isinstance(binding['control'], str) or len(binding['control']) > 128:
        raise ValueError('Invalid fixed control')
    validate_workload(binding['workload'], req['target'])


def binding_pin(req):
    return digest(canonical({key: req[key] for key in ('contract', 'target', 'source_pins', 'binding')}))


def workload_request(req, accelerator, protein):
    binding = req['binding']
    control = base64.b64decode(binding['control'], validate=True)
    if control != accelerator.CONTROL or base64.b64encode(control).decode('ascii') != binding['control']:
        raise ValueError('Exact frozen accelerator control required')
    assets = {name: {'bytes': spec[0], 'sha256': spec[1]} for name, spec in protein.FILES.items()}
    if binding['assets'] != assets:
        raise ValueError('Frozen accelerator assets differ')
    return {
        'contract': accelerator.CONTRACT, 'job_id': binding['job_id'], 'profile': binding['workload'],
        'model_dir': req['target']['model'], 'input_sha256': digest(control), 'model_assets': assets,
        'source_hashes': {name: req['source_pins'][name] for name in ('accelerator_tools.py', 'protein_tools.py')},
    }


def private_dir(path):
    result = checked_path(path, directory=True)
    info = result.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Job directory must be owned by the selected account and private')
    return result


def load_json(path):
    return decode(read_file(path, MAX_REQUEST))


def state_for(req, status, **extra):
    return {'contract': CONTRACT, 'job_id': req['binding']['job_id'], 'binding_sha256': binding_pin(req),
            'status': status, **extra}


def check_state(req, state):
    expected = state_for(req, state['status'])
    if any(state.get(key) != value for key, value in expected.items()):
        raise ValueError('Saved state has a different job binding')
    return state


def snapshot(req, job):
    state = check_state(req, load_json(job / 'state.json'))
    if state['status'] == 'prepared' and (job / 'attempt.json').exists():
        return state_for(req, 'uncertain', reason='Dispatch intent exists without a launch state')
    if state['status'] in {'launching', 'running'} and time.time() - state['heartbeat'] > STALE_SECONDS:
        return {**state, 'status': 'uncertain', 'reason': 'Controller heartbeat expired'}
    return state


@contextmanager
def mutation_lock(job):
    import fcntl
    with (job / '.mutation.lock').open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def child_process(req, operation, **kwargs):
    payload = canonical({**req, 'operation': operation})
    with tempfile.TemporaryFile() as stdin:
        stdin.write(payload)
        stdin.seek(0)
        return subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', BOOTSTRAP, operation],
                                stdin=stdin, shell=False, start_new_session=True, **kwargs)


def publish_bytes(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepared_job(req, job):
    job = private_dir(job)
    saved = load_json(job / 'binding.json')
    if binding_pin(saved) != binding_pin(req):
        raise ValueError('Prepared job binding differs')
    control = read_file(job / 'control.fasta', 128)
    if control != base64.b64decode(req['binding']['control'], validate=True):
        raise ValueError('Prepared accelerator control differs')
    return job


def validate_result(req, request, accelerator, raw):
    result = decode(raw)
    try:
        comparison = accelerator.validate_result(result, request)
    except (AttributeError, KeyError, OverflowError, TypeError) as exc:
        raise ValueError('Malformed accelerator tensor result') from exc
    runtime = req['target']['runtime']
    expected_identity = {**runtime['identity'], 'python': runtime['python'],
                         'python_version': runtime['python_version']}
    if result.get('identity') != expected_identity or result.get('device_requested') != request['profile']['device']:
        raise ValueError('Accelerator result runtime or selected device differs')
    versions = result.get('versions')
    exact_fields(versions, {'torch', 'transformers', 'cuda_runtime'}, 'workload versions')
    if any(versions[name] != runtime['distributions'][name]['version'] for name in ('torch', 'transformers')):
        raise ValueError('Actual imported workload versions differ from runtime pin')
    observed = result['accelerator']
    budget = request['profile']['max_accelerator_memory_bytes']
    for key, minimum in (('total_memory_bytes', budget), ('reserved_or_driver_bytes', observed['allocated_bytes'])):
        if type(observed.get(key)) is not int or observed[key] < minimum:
            raise ValueError('Missing or invalid accelerator memory observation')
    if observed['backend'] == 'cuda':
        if not isinstance(versions['cuda_runtime'], str) or not versions['cuda_runtime']:
            raise ValueError('CUDA runtime evidence missing')
        if (observed.get('memory_measurement') != 'torch_cuda_allocator_exact_peaks'
                or observed['reserved_or_driver_bytes'] > budget):
            raise ValueError('Invalid CUDA allocator evidence')
    elif (observed.get('index') is not None
          or observed.get('memory_measurement') != 'mps_allocator_limit_and_terminal_observation_not_exact_peak'):
        raise ValueError('Invalid MPS allocator evidence')
    return comparison


def handle(req, request, accelerator, protein, save_state):
    op = req['operation']
    if op == 'inspect':
        return {'contract': CONTRACT, 'status': 'verified', 'runtime': req['target']['runtime'],
                'source_pins': req['source_pins'], 'executed': False}

    root = private_dir(req['target']['jobs'])
    job = root / req['binding']['job_id']
    if op == 'prepare':
        protein.verify_model(checked_path(request['model_dir'], directory=True))
        # Reserve the final ID atomically. Interrupted preparation remains
        # visible as an incomplete reservation and cannot be repurposed.
        job.mkdir(mode=0o700)
        save_state(job / 'binding.json', req, exclusive=True)
        publish_bytes(job / 'control.fasta', accelerator.CONTROL)
        state = state_for(req, 'prepared', executed=False)
        save_state(job / 'state.json', state, exclusive=True)
        return state
    if op in {'status', 'recover'} and not job.exists() and not job.is_symlink():
        return state_for(req, 'not_found')
    job = prepared_job(req, job)
    if op in {'status', 'recover'}:
        return snapshot(req, job)
    if op == 'collect':
        state = snapshot(req, job)
        if state['status'] != 'succeeded':
            raise ValueError('Collection requires successful remote validation')
        protein.verify_model(checked_path(request['model_dir'], directory=True))
        raw = read_file(job / 'result.json', request['profile']['max_result_bytes'])
        if len(raw) != state['result_bytes'] or digest(raw) != state['result_sha256']:
            raise ValueError('Remote result checksum differs')
        if validate_result(req, request, accelerator, raw) != state['comparison']:
            raise ValueError('Remote numerical comparison differs from terminal receipt')
        return {**state, 'result_base64': base64.b64encode(raw).decode('ascii')}

    with mutation_lock(job):
        state = snapshot(req, job)
        if op == 'cancel':
            if state['status'] == 'prepared':
                state = state_for(req, 'cancelled', reason='Cancelled before dispatch')
                save_state(job / 'state.json', state)
            elif state['status'] in {'launching', 'running', 'uncertain'}:
                cancel = job / 'cancel.request'
                if not cancel.exists():
                    save_state(cancel, state_for(req, 'cancel_requested'), exclusive=True)
                state = {**state, 'cancel_requested': True}
            return state

        if op != 'submit' or state['status'] != 'prepared' or (job / 'attempt.json').exists():
            raise ValueError('Remote job already attempted or unavailable; never retry uncertainty')
        save_state(job / 'attempt.json', state_for(req, 'dispatch_intent'), exclusive=True)
        launching = state_for(req, 'launching', heartbeat=time.time())
        save_state(job / 'state.json', launching)
        try:
            child_process(req, 'controller', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=job)
        except OSError:
            # The durable one-attempt boundary remains in place.
            save_state(job / 'state.json', state_for(req, 'uncertain', reason='Controller launch unconfirmed'))
            raise
        return launching


def drain_worker(child, req, job, profile, save_state):
    stdout, stderr = bytearray(), bytearray()
    deadline = time.monotonic() + profile['wall_seconds']
    heartbeat = time.monotonic()
    with selectors.DefaultSelector() as channels:
        channels.register(child.stdout, selectors.EVENT_READ, (stdout, profile['max_result_bytes']))
        channels.register(child.stderr, selectors.EVENT_READ, (stderr, profile['max_log_bytes']))
        status, reason = 'running', ''
        while True:
            if (job / 'cancel.request').exists():
                status, reason = 'cancelled', 'Owning controller received cancellation'
                break
            now = time.monotonic()
            if now >= deadline:
                status, reason = 'timed_out', 'Whole compute worker deadline exceeded'
                break
            if not channels.get_map() and child.poll() is not None:
                break
            if now >= heartbeat:
                save_state(job / 'state.json', state_for(req, 'running', heartbeat=time.time()))
                heartbeat = now + HEARTBEAT_SECONDS
            for key, _ in channels.select(timeout=min(0.1, deadline - now)):
                buffer, limit = key.data
                chunk = os.read(key.fd, min(65536, limit - len(buffer) + 1))
                if not chunk:
                    channels.unregister(key.fileobj)
                    continue
                available = limit - len(buffer)
                buffer.extend(chunk[:available])
                if len(chunk) > available:
                    status, reason = 'failed', 'Compute output or diagnostic exceeded its byte cap'
                    break
            if status != 'running':
                break
    if stderr:
        publish_bytes(job / 'worker.stderr', stderr)
    return status, reason, bytes(stdout)


def controller(req, request, accelerator, save_state):
    root = private_dir(req['target']['jobs'])
    job = prepared_job(req, root / request['job_id'])
    with mutation_lock(job):
        if check_state(req, load_json(job / 'attempt.json')) != state_for(req, 'dispatch_intent'):
            raise ValueError('No matching remote attempt')
        if load_json(job / 'state.json')['status'] != 'launching':
            raise ValueError('Controller requires a launching reservation')
        save_state(job / 'controller.json', state_for(req, 'controller_claimed'), exclusive=True)
        save_state(job / 'state.json', state_for(req, 'running', heartbeat=time.time()))

    child = None
    state = state_for(req, 'failed', reason='Compute worker failed')
    started = time.monotonic()
    try:
        if (job / 'cancel.request').exists():
            state = state_for(req, 'cancelled', reason='Cancelled before compute launch')
        else:
            child = child_process(req, 'compute', stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=job)
            status, reason, raw = drain_worker(child, req, job, request['profile'], save_state)
            if status != 'running':
                state = state_for(req, status, reason=reason)
            elif child.returncode == 0:
                comparison = validate_result(req, request, accelerator, raw)
                state = state_for(req, 'succeeded', result_sha256=digest(raw), result_bytes=len(raw),
                                  comparison=comparison)
    except Exception as exc:
        state = state_for(req, 'failed', reason=str(exc)[:1024])
    finally:
        if child is not None:
            try:
                accelerator.stop(child)
            except (OSError, subprocess.TimeoutExpired):
                state = state_for(req, 'uncertain', reason='Compute worker termination unproven')
            finally:
                child.stdout.close()
                child.stderr.close()
        with mutation_lock(job):
            if state['status'] == 'succeeded':
                if (job / 'cancel.request').exists():
                    state = state_for(req, 'cancelled', reason='Cancellation arrived before terminal commit')
                else:
                    publish_bytes(job / 'result.json', raw)
            save_state(job / 'state.json', {**state, 'elapsed_seconds': time.monotonic() - started})


def entry(raw, mode):
    os.umask(0o077)
    req = decode(raw)
    validate_envelope(req, internal=mode in {'controller', 'compute'})
    if mode != 'rpc' and mode != req['operation']:
        raise ValueError('Invalid bootstrap mode')
    if mode == 'compute':
        # The dedicated child also has a wall alarm if its controller dies.
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(req['binding']['workload']['wall_seconds'])
    target = req['target']
    if identity() != target['runtime']['identity']:
        raise ValueError('Selected host, platform or account differs')
    if inventory(target['site_packages']) != target['runtime']:
        raise ValueError('Selected Python runtime pin differs')
    sources = PinnedSources(checked_path(target['scripts'], directory=True), req['source_pins'])
    sys.meta_path.insert(0, sources)
    accelerator = importlib.import_module('accelerator_tools')
    protein = importlib.import_module('protein_tools')
    save_state = importlib.import_module('transport_common').save_state
    os.environ.update({key: target['user'] for key in ('LOGNAME', 'USER', 'LNAME', 'USERNAME')})
    request = workload_request(req, accelerator, protein) if req['binding'] is not None else None

    if mode == 'controller':
        controller(req, request, accelerator, save_state)
        return
    if mode == 'compute':
        job = prepared_job(req, private_dir(target['jobs']) / request['job_id'])
        with mutation_lock(job):
            if (check_state(req, load_json(job / 'controller.json')) != state_for(req, 'controller_claimed')
                    or snapshot(req, job)['status'] != 'running' or (job / 'cancel.request').exists()):
                raise ValueError('Compute requires a matching live controller claim')
            save_state(job / 'compute.json', state_for(req, 'compute_claimed'), exclusive=True)
        checked_path(target['model'], directory=True)
        sys.path.append(target['site_packages'])
        # Keep incidental dependency output on the bounded diagnostic stream.
        from contextlib import redirect_stdout
        with redirect_stdout(sys.stderr):
            result = accelerator.compute(request, job)
        raw = canonical(result)
        if len(raw) > request['profile']['max_result_bytes']:
            raise ValueError('Compute result exceeds bound')
        sys.stdout.buffer.write(raw)
        return
    sys.stdout.buffer.write(canonical(handle(req, request, accelerator, protein, save_state)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', action='store_true', required=True)
    parser.add_argument('--site-packages', required=True)
    args = parser.parse_args()
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        parser.error('Run inventory with the selected Python and -I -S -B')
    sys.stdout.buffer.write(canonical(inventory(args.site_packages)) + b'\n')


if __name__ == '__main__':
    main()
