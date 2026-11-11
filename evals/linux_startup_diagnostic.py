#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Opt-in startup capture: three fresh symlink fixtures, never a production repair."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import threading
import time
import uuid

import linux_integration_checks as integration
from linux_observer import QueryChronology, bounded_text, container_state

mod = integration.mod
MAX_SAMPLES = 3
WORK_SECONDS, RPC_SECONDS, CLEANUP_SECONDS, TOTAL_SECONDS = 60, 54, 80, 90
ADMISSION_SECONDS, OBSERVE_SECONDS, FINISH_SECONDS, RPC_TAIL_SECONDS = 30, 20, 6, 15
STREAM_BYTES, RECORD_BYTES, REPORT_BYTES, MAX_RECORDS = 8192, 128 * 1024, 1024 * 1024, 32
CODE = "import os;os.symlink('/etc/hosts','result.json')"
EXPECTED_REASON = 'Unsafe/unavailable outputs: Symlink forbidden'
RESOURCES = {'wall_seconds': 8, 'retention_seconds': 30, 'memory_bytes': 128 * 1024**2,
             'cpu_millis': 500, 'pids': 32, 'work_bytes': 2 * 1024**2, 'tmp_bytes': 1024**2,
             'max_log_bytes': 1024, 'max_output_bytes': 65536}


class BudgetExhausted(RuntimeError):
    """Not ValueError: original transient read-query recovery must not swallow it."""


class EvidenceError(RuntimeError):
    pass


class LaunchUncertain(RuntimeError):
    pass


def error(exc):
    return {'kind': type(exc).__name__, 'text': bounded_text(exc, 4096)}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Budget:
    def __init__(self, clock=time.monotonic):
        self.clock, self.origin = clock, clock()  # Before journaling, filesystem setup and Docker.
        self.phase = 'work'
        self.exhausted = self.uncertain = False
        self.clamps = 0

    def elapsed(self):
        return self.clock() - self.origin

    def refuse(self, message):
        self.exhausted = True
        raise BudgetExhausted(message)

    def admit(self):
        if self.exhausted or self.uncertain or WORK_SECONDS - self.elapsed() < ADMISSION_SECONDS:
            self.refuse('No new fixture: permanent stop or fewer than 30 work seconds remain')

    def launch(self):
        if self.exhausted or self.uncertain or WORK_SECONDS - self.elapsed() < OBSERVE_SECONDS + FINISH_SECONDS:
            self.refuse('No launch: 20 second observation plus 6 second finish cannot fit')

    def rpc(self, runner, argv, timeout=30, maximum=mod.MAX_RPC):
        end = CLEANUP_SECONDS if self.phase == 'cleanup' else RPC_SECONDS
        available = end - self.elapsed() - RPC_TAIL_SECONDS
        if available <= 0:
            self.refuse('No RPC wait plus existing 15 second runner tail remains in ' + self.phase)
        wait = min(timeout, available)
        self.clamps += int(wait < timeout)
        try:
            result = runner(argv, timeout=wait, maximum=maximum)
            if self.elapsed() > end:
                self.refuse('RPC exceeded absolute phase deadline including runner tail')
            return result
        except BaseException:
            if len(argv) > 3 and argv[3] in ('run', 'rm'):
                self.uncertain = True
            raise

    @contextmanager
    def transport(self):
        original = mod.bounded_run
        mod.bounded_run = lambda argv, timeout=30, maximum=mod.MAX_RPC: self.rpc(original, argv, timeout, maximum)
        try:
            yield
        finally:
            mod.bounded_run = original


def check_payload(value, remaining):
    remaining[0] -= 1
    if remaining[0] < 0:
        raise EvidenceError('Evidence object count limit')
    if isinstance(value, str):
        if len(value) > 65536 or len(value.encode('utf-8')) > 65536:
            raise EvidenceError('Evidence text field limit')
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise EvidenceError('Evidence key limit')
            check_payload(item, remaining)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_payload(item, remaining)
    elif value is not None and type(value) not in (bool, int, float):
        raise EvidenceError('Unsupported evidence value')


class Journal:
    def __init__(self, path, output=None):
        self.path = mod.no_symlinks(path)
        self.stream = self.path.open('x', encoding='utf-8')
        try:
            os.chmod(self.path, 0o600)
            mod.fsync_directory(self.path.parent)
        except BaseException:
            self.stream.close()
            raise
        self.output = sys.stdout if output is None else output
        self.bytes = self.records = 0

    def emit(self, kind, value, *, final=False):
        record = {'record': kind, **value}
        check_payload(record, [8192])
        raw = bytearray()
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(record):
            part = chunk.encode('utf-8')
            if len(raw) + len(part) + 1 > RECORD_BYTES:
                raise EvidenceError('Evidence record byte cap')
            raw.extend(part)
        raw.extend(b'\n')
        if (self.records >= MAX_RECORDS - (0 if final else 1)
                or self.bytes + len(raw) + (0 if final else RECORD_BYTES) > REPORT_BYTES):
            raise EvidenceError('Evidence aggregate cap; summary reserved')
        line = raw.decode('utf-8')
        self.stream.write(line); self.stream.flush(); os.fsync(self.stream.fileno())
        self.records += 1; self.bytes += len(raw)
        self.output.write(line); self.output.flush()

    def close(self):
        self.stream.close()


class CIDFile:
    """A creation hint only; no mutation is authorized by these bytes."""
    def __init__(self, directory):
        self.directory = mod.no_symlinks(directory)
        self.directory.mkdir(mode=0o700)
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.anchor = os.fstat(self.fd)
            if self.anchor.st_uid != os.getuid() or stat.S_IMODE(self.anchor.st_mode) != 0o700:
                raise ValueError('CID directory owner/mode mismatch')
            self.path = self.directory / 'container.cid'
            self.inode = None
            self.identifier = None
            self.validate_directory()
            try:
                os.stat(self.path.name, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise ValueError('CID leaf must be absent before the single launch')
        except BaseException:
            os.close(self.fd)
            raise

    def validate_directory(self):
        mod.no_symlinks(self.directory)
        current = self.directory.stat(follow_symlinks=False)
        opened = os.fstat(self.fd)
        for value in (current, opened):
            if ((value.st_dev, value.st_ino) != (self.anchor.st_dev, self.anchor.st_ino)
                    or value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) != 0o700
                    or not stat.S_ISDIR(value.st_mode)):
                raise ValueError('CID directory identity changed')

    @staticmethod
    def signature(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                value.st_uid, value.st_nlink, value.st_mode)

    def read(self):
        self.validate_directory()
        try:
            before = os.stat(self.path.name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            if self.inode is not None:
                raise ValueError('CID file disappeared after observation')
            return None
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_size > 65):
            raise ValueError('CID must be a bounded owned regular single-link file')
        identity = (before.st_dev, before.st_ino)
        if self.inode not in (None, identity):
            raise ValueError('CID inode replacement')
        self.inode = identity
        fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            opened = os.fstat(fd)
            raw = os.read(fd, 65)
            after = os.fstat(fd)
            final = os.stat(self.path.name, dir_fd=self.fd, follow_symlinks=False)
            if any(self.signature(x) != self.signature(before) for x in (opened, after, final)):
                raise ValueError('CID changed during anchored read')
        finally:
            os.close(fd)
        self.validate_directory()
        if self.identifier is not None and raw not in (self.identifier.encode(), self.identifier.encode() + b'\n'):
            raise ValueError('CID contents changed after immutable binding')
        if re.fullmatch(b'[0-9a-f]{0,63}', raw):
            return None  # Stable empty/partial publication; read-only polling only.
        if not re.fullmatch(b'[0-9a-f]{64}\n?', raw):
            raise ValueError('Malformed completed CID')
        identifier = raw[:64].decode('ascii')
        if self.identifier not in (None, identifier):
            raise ValueError('CID contents changed after immutable binding')
        self.identifier = identifier
        return identifier

    def close(self):
        os.close(self.fd)


def foreground_arguments(profile, state, supplied, cid_path):
    expected = [profile['docker_executable'], '--context', profile['context'], *mod.run_arguments(state)]
    if supplied != expected or profile != state['profile'] or supplied.count('--detach') != 1:
        raise ValueError('Only the complete production run argv for this state may be intercepted')
    if supplied[-3:] != [state['manifest']['image_id'], '/runner/linux_supervisor.py', 'run']:
        raise ValueError('Unexpected image/command boundary')
    result = supplied[:-3]
    result.remove('--detach')
    return result + ['--attach=stdout', '--attach=stderr', '--sig-proxy=false', '--cidfile', str(cid_path)] + supplied[-3:]


def start_proof(obj):
    state = obj['State']
    def timestamp(key):
        value = state.get(key)
        if (not isinstance(value, str) or len(value) > 64
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z', value)):
            raise ValueError('Missing/malformed ' + key)
        parsed = datetime.fromisoformat(value[:-1] + '+00:00')
        fraction = value[:-1].partition('.')[2].ljust(9, '0')
        # Docker timestamps have nanoseconds; datetime alone truncates at microseconds.
        return (*parsed.timetuple()[:6], int(fraction)) if parsed.year > 1 else None
    started = timestamp('StartedAt')
    if started is None:
        return False
    if state.get('Running') is True:
        return True
    finished = timestamp('FinishedAt')
    return state.get('Running') is False and finished is not None and finished >= started


class Capture:
    """One foreground CLI, pre-start pipes, 20s lifetime, <=6s owned-handle finish."""
    def __init__(self, argv, clock=time.monotonic):
        self.argv, self.clock = argv, clock
        self.process = self.thread = None
        self.stop = threading.Event(); self.lock = threading.Lock()
        self.buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self.truncated = {'stdout': False, 'stderr': False}
        self.errors = []
        self.deadline_reached = False
        self.started = self.ended = None
        self.closed = False

    def note(self, exc):
        with self.lock:
            if len(self.errors) < 4:
                self.errors.append(error(exc))

    def keep(self, name, raw):
        with self.lock:
            room = STREAM_BYTES - len(self.buffers[name])
            self.buffers[name].extend(raw[:room])
            self.truncated[name] |= len(raw) > room

    def start(self):
        if self.started is not None:
            raise LaunchUncertain('A capture object cannot launch twice')
        self.started = self.clock()
        self.process = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, start_new_session=True, close_fds=True)
        try:
            self.thread = threading.Thread(target=self.drain, name='rw-startup-capture', daemon=True)
            self.thread.start()
        except BaseException as exc:
            self.note(exc); self.stop_process(); self.close_pipes()
            self.thread = None
            raise

    def stop_process(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.process.kill()  # Only this Popen handle; --sig-proxy=false, no group/PID/container signal.
            self.process.wait(timeout=1)
        except Exception as exc:
            self.note(exc)

    def close_pipes(self):
        self.closed = True
        for stream in (self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except Exception as exc:
                self.closed = False; self.note(exc)

    def drain(self):
        selector = None
        try:
            selector = selectors.DefaultSelector()
            for name in self.buffers:
                stream = getattr(self.process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() and not self.stop.is_set():
                remaining = self.started + OBSERVE_SECONDS - self.clock()
                if remaining <= 0:
                    self.deadline_reached = True
                    break
                for key, _ in selector.select(min(0.05, remaining)):
                    try:
                        raw = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if raw:
                        self.keep(key.data, raw)
                    else:
                        selector.unregister(key.fileobj)
        except Exception as exc:
            self.note(exc)
        finally:
            self.stop_process()
            drain_until = self.clock() + 0.25
            try:
                for key in list(selector.get_map().values()) if selector is not None else []:
                    while self.clock() < drain_until:
                        try:
                            raw = os.read(key.fileobj.fileno(), 65536)
                        except (BlockingIOError, OSError):
                            break
                        if not raw:
                            break
                        self.keep(key.data, raw)
            except Exception as exc:
                self.note(exc)
            try:
                if selector is not None:
                    selector.close()
            except Exception as exc:
                self.note(exc)
            self.close_pipes(); self.ended = self.clock()

    def snapshot(self):
        """Pure bounded byte snapshot: never polls, joins, closes or signals a process."""
        with self.lock:
            streams = {name: {'bytes': len(raw), 'sha256': sha(raw),
                        'base64': base64.b64encode(raw).decode('ascii'), 'truncated': self.truncated[name]}
                       for name, raw in self.buffers.items()}
            return {'streams': streams, 'errors': list(self.errors), 'started_monotonic': self.started,
                    'ended_monotonic': self.ended, 'deadline_reached': self.deadline_reached,
                    'cli_exit_code': None, 'cleanup_verified': False,
                    'coverage': 'foreground run pipes before container start; altered launch transport'}

    def finish(self):
        failure = None
        try:
            self.stop.set()
            if self.thread is not None:
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    self.stop_process(); self.thread.join(timeout=2)
            elif self.process is not None:
                self.stop_process(); self.close_pipes()
        except Exception as exc:
            failure = error(exc); self.note(exc)
        # Obtain process facts separately. A late poll/join/close error must not
        # prevent serialization of the already-retained exact byte prefixes.
        code = None; thread_finished = False
        try:
            code = self.process.poll() if self.process is not None else None
            thread_finished = self.thread is None or not self.thread.is_alive()
        except Exception as exc:
            if failure is None:
                failure = error(exc)
            self.note(exc)
        result = self.snapshot()
        result.update(cli_exit_code=code, cleanup_verified=failure is None and not result['errors']
            and self.process is not None and code is not None and thread_finished and self.closed)
        if failure is not None:
            result['finish_error'] = failure
        return result


class Batch:
    def __init__(self, config, journal, budget):
        self.config, self.journal, self.budget = config, journal, budget
        self.root = journal.path.parent / ('rw-startup-diagnostic-' + uuid.uuid4().hex)
        self.completed = []; self.seen_ids = set(); self.seen_jobs = set()
        self.current = None

    def emit(self, kind, value):
        if self.budget.elapsed() >= TOTAL_SECONDS:
            self.budget.refuse('Evidence deadline reached')
        self.journal.emit(kind, {'elapsed': round(self.budget.elapsed(), 6), **value})

    def setup(self):
        if sys.platform != 'linux':
            raise RuntimeError('Actual Linux runner required; no passing skip')
        self.root.mkdir(mode=0o700)  # Retained always; no automatic unresolved-state deletion.
        self.p = mod.profile({'schema_version': 1, 'docker_executable': self.config.docker,
            'context': self.config.context, 'expected_engine_id': None, 'container_python': '/usr/local/bin/python'})
        engine = mod.inspect_engine(self.p); self.p['expected_engine_id'] = engine['id']
        version = mod.docker(self.p, ['version', '--format', '{{.Client.Version}}'])
        if len(version) > 256:
            raise EvidenceError('CLI version response oversized')
        if self.config.image_id is None:
            raw = mod.docker(self.p, ['image', 'inspect', '--format', '{{.Id}}', 'python:3.12-slim-bookworm'])
            self.config.image_id = raw.decode('ascii').strip()
        image = mod.inspect_image(self.p, self.config.image_id)
        integration.CONFIG = self.config
        self.emit('engine', {'engine': engine, 'image': image, 'image_id': self.config.image_id,
                             'cli_version': version.decode('ascii').strip()})

    def inspect(self, local, entry, event):
        obj = mod.inspect_container(local)  # Unchanged full production validator, excludes environment.
        observation = {'event': event, 'elapsed': round(self.budget.elapsed(), 6), 'host_time': time.time(),
                       'container_id': obj['Id'] if obj else None,
                       'state': container_state(obj['State']) if obj else None}
        if len(entry['inspections']) < 12:
            entry['inspections'].append(observation)
        else:
            entry['inspections_truncated'] = True
        if obj:
            entry['container_id'] = obj['Id']
            entry['start_proven'] = start_proof(obj)
            entry['last_container_state'] = container_state(obj['State'])
        return obj

    def retain_validated_identity(self, local, entry, obj):
        """Fsync independent evidence before production submit can overwrite its local state."""
        if obj is None:
            return
        signature = {'container_id': obj['Id'], 'start_proven': entry.get('start_proven') is True}
        if entry.get('identity_journaled_state') == signature:
            return  # At most created and started observations for this one immutable ID.
        self.emit('validated_identity', {'index': entry['index'], 'job_id': entry['job_id'],
            'container_id': obj['Id'], 'container_name': local['container_name'], 'binding': local['binding'],
            'image_id': local['manifest']['image_id'], 'engine_id': local['profile']['expected_engine_id'],
            'state_path': entry['state_path'], 'start_proven': signature['start_proven'],
            'container_state': container_state(obj['State']), 'host_time': time.time(),
            'submit_acknowledged': False, 'uncertainty_not_cleared_by_observation': True})
        entry['identity_journaled_state'] = signature

    def foreground(self, original, profile, args, timeout=30, allow_missing=False):
        if not args or args[0] != 'run':
            return original(profile, args, timeout=timeout, allow_missing=allow_missing)
        entry = self.current
        if entry is None or entry.get('popen_attempted'):
            raise LaunchUncertain('Unexpected or duplicate run refused')
        local = mod.checked_state(Path(entry['state_path']))
        if (local['submit_attempted'] is not True or local['status'] != 'uncertain'
                or local['binding'] != entry['binding'] or local['manifest']['job_id'] != entry['job_id']
                or local.get('container_id') is not None):
            raise LaunchUncertain('Production durable intent/binding missing before foreground launch')
        full = [profile['docker_executable'], '--context', profile['context'], *args]
        command = foreground_arguments(profile, local, full, entry['cid'].path)
        self.emit('dispatch_intent', {'index': entry['index'], 'job_id': entry['job_id'],
            'container_name': local['container_name'], 'binding': local['binding'],
            'original_argv': full, 'diagnostic_argv': command, 'original_argv_sha256': sha(mod.canonical(full)),
            'diagnostic_argv_sha256': sha(mod.canonical(command)), 'durable_submit_attempted': True})
        # The last check is immediately before Popen. A refusal has no new process mutation.
        try:
            self.budget.launch()
        except BudgetExhausted:
            self.budget.uncertain = True
            entry['launch_refused'] = {'popen_attempted': False, 'work_remaining': WORK_SECONDS - self.budget.elapsed(),
                                       'reason': 'Durable intent retained; observation plus finish cannot fit'}
            raise
        entry['popen_attempted'] = True
        entry['launch_elapsed'] = self.budget.elapsed()
        entry['launch_host_time'] = time.time()
        entry['capture'] = Capture(command)
        try:
            entry['capture'].start()
            until = entry['capture'].started + OBSERVE_SECONDS
            while time.monotonic() < until:
                identifier = entry['cid'].read()
                early = entry['capture'].process.poll() is not None
                if identifier is not None:
                    if identifier in self.seen_ids:
                        raise LaunchUncertain('Duplicate immutable ID')
                    pinned = {**local, 'container_id': identifier}
                    obj = self.inspect(pinned, entry, 'start_proof')
                    self.retain_validated_identity(pinned, entry, obj)
                    if obj is not None:
                        local['container_id'] = identifier
                        mod.save(Path(entry['state_path']) / 'state.json', local)
                    if obj is not None and entry.get('start_proven'):
                        self.seen_ids.add(identifier)
                        if (early or entry['capture'].process.poll() is not None
                                or time.monotonic() >= until or not obj['State'].get('Running')):
                            raise LaunchUncertain('Container/CLI exited before normal submit acknowledgment')
                        if entry['capture'].errors:
                            raise LaunchUncertain('Capture reader/setup failed before acknowledgment')
                        entry['submit_confirmed'] = True
                        return identifier.encode('ascii')
                if early:
                    # A name query is read-only and retains production binding validation.
                    obj = self.inspect(local, entry, 'early_cli_exit_discovery')
                    self.retain_validated_identity(local, entry, obj)
                    raise LaunchUncertain('CLI exited before CID/start acknowledgment')
                if entry['capture'].errors:
                    raise LaunchUncertain('Capture reader/setup failed')
                time.sleep(0.05)
            raise LaunchUncertain('Startup acknowledgment missing inside fixed observer lifetime')
        except BaseException:
            self.budget.uncertain = True
            raise

    def cleanup(self, entry):
        if entry.get('state_path') is None:
            return {'verified': not entry.get('popen_attempted'), 'container_created': False}
        with mod.state_lock(entry['state_path']) as root:
            local = mod.checked_state(root)
            if entry.get('container_id'):
                local['container_id'] = entry['container_id']
            obj = self.inspect(local, entry, 'cleanup_validation')
            if obj is None:
                return {'verified': not entry.get('popen_attempted'), 'absent_before_remove': True}
            identifier = obj['Id']
            if not re.fullmatch('[0-9a-f]{64}', identifier):
                raise LaunchUncertain('No validated immutable cleanup ID')
            local['container_id'] = identifier; mod.save(root / 'state.json', local)
        self.emit('cleanup_intent', {'index': entry['index'], 'job_id': entry['job_id'], 'container_id': identifier})
        try:
            removed = mod.operate('cleanup', entry['state_path'], allow_remove=True)
            if removed.get('state') != 'removed':
                raise LaunchUncertain('Removal acknowledgment missing')
        except BaseException:
            self.budget.uncertain = True
            raise  # No retry or name mutation, even if later absence might be discoverable.
        raw = mod.docker(local['profile'], ['container', 'inspect', identifier, '--format', '{{json .Id}}'], allow_missing=True)
        if raw is not None:
            raise LaunchUncertain('Exact immutable ID absence not verified')
        return {'verified': True, 'container_id': identifier, 'removed_acknowledged': True, 'absence_verified': True}

    @staticmethod
    def finish_capture(capture):
        try:
            return capture.finish()
        except Exception as exc:
            try:
                result = capture.snapshot()
            except Exception as snapshot_exc:
                result = {'snapshot_error': error(snapshot_exc)}
            return {**result, 'cleanup_verified': False, 'finish_error': error(exc)}

    def sample(self, index):
        entry = {'index': index, 'admitted_elapsed': self.budget.elapsed(), 'inspections': [],
                 'inspections_truncated': False, 'state_path': None, 'capture': None, 'cid': None,
                 'popen_attempted': False, 'submit_confirmed': False}
        self.current = entry
        primary = None; observer = None; terminal = None; cleanup = None
        chronology = QueryChronology()
        case = integration.LinuxActual('test_08_actual_unsafe_and_oversized_outputs')
        case.root, case.p, case.states = self.root, self.p, []
        self.emit('fixture_admitted', {'index': index})
        try:
            state = case.job(CODE, {'memory_bytes': 128 * 1024**2}, submit=False)
            entry['state_path'] = str(state)
            local = mod.read_json(state / 'state.json')
            if (local['manifest']['resources'] != RESOURCES or local['manifest']['argv'][-1] != CODE
                    or local['submit_attempted'] or local['manifest']['job_id'] in self.seen_jobs):
                raise LaunchUncertain('Fixture or initial durable intent differs from frozen contract')
            self.seen_jobs.add(local['manifest']['job_id'])
            entry.update(job_id=local['manifest']['job_id'], binding=local['binding'], container_name=local['container_name'])
            entry['cid'] = CIDFile(self.root / ('cid-' + str(index)))
            self.emit('fixture_prepared', {key: entry[key] for key in ('index', 'state_path', 'job_id', 'binding', 'container_name')}
                      | {'resources': local['manifest']['resources'], 'manifest_sha256': sha(mod.canonical(local['manifest']))})
            original = mod.docker
            mod.docker = lambda p, args, timeout=30, allow_missing=False: self.foreground(original, p, args, timeout, allow_missing)
            try:
                submitted = mod.operate('submit', state, allow_execute=True)
            except Exception:
                self.budget.uncertain = True
                raise
            finally:
                mod.docker = original
            case.assertEqual(submitted['state'], 'submitted')
            terminal = case.terminal(state, chronology=chronology)
            observer = self.finish_capture(entry['capture'])
            if entry['cid'].read() != entry.get('container_id'):
                raise LaunchUncertain('CID publication missing/changed after terminal observation')
            case.assertEqual(terminal['state'], 'failed'); case.assertEqual(terminal['artifacts'], [])
            case.assertEqual(terminal['reason'], EXPECTED_REASON)
            with case.assertRaises(ValueError):
                case.collected(state)
            entry['original_assertions'] = {'failed_receipt': True, 'empty_artifacts': True, 'collection_refused': True,
                                            'expected_symlink_reason': True}
            with mod.state_lock(state) as root:
                self.inspect(mod.checked_state(root), entry, 'final_work_inspect')
        except BaseException as exc:
            primary = error(exc)
        finally:
            if entry['capture'] is not None and observer is None:
                observer = self.finish_capture(entry['capture'])
            if self.budget.elapsed() >= WORK_SECONDS:
                self.budget.exhausted = True
            self.budget.phase = 'cleanup'
            try:
                cleanup = self.cleanup(entry)
            except Exception as exc:
                cleanup = {'verified': False, 'error': error(exc)}
            finally:
                self.budget.phase = 'work'
                if entry['cid'] is not None:
                    try:
                        entry['cid'].close()
                    except Exception as exc:
                        cleanup['cid_close_error'] = error(exc); cleanup['verified'] = False
            capture_ok = (observer is not None and observer.get('cleanup_verified') is True
                and not observer.get('errors') and not observer.get('deadline_reached')
                and set(observer.get('streams', {})) == {'stdout', 'stderr'}
                and all(not v['truncated'] for v in observer.get('streams', {}).values()))
            good = (primary is None and capture_ok and cleanup.get('verified') is True
                    and not self.budget.exhausted and not self.budget.uncertain and not entry['inspections_truncated'])
            record = {key: value for key, value in entry.items() if key not in ('capture', 'cid')}
            record.update(accepted=good, primary_failure=primary, observer=observer, terminal_result=terminal,
                          status_queries=chronology.report(), cleanup=cleanup, budget_exhausted=self.budget.exhausted,
                          uncertain_launch_or_remove=self.budget.uncertain)
            self.current = record  # Survives emission failure in reserved summary, including raw retained bytes.
            self.completed.append({'index': index, 'accepted': good, 'job_id': entry.get('job_id'),
                                   'container_id': entry.get('container_id')})
            self.emit('fixture_result', record)
            self.current = None
        return good

    def run(self):
        failure = None
        with self.budget.transport():
            try:
                root = Path(__file__).resolve().parents[1]
                files = [Path(__file__), Path(__file__).with_name('linux_startup_diagnostic_checks.py'),
                         Path(integration.__file__), Path(__file__).with_name('linux_observer.py'), integration.SCRIPTS / 'linux_tools.py',
                         integration.SCRIPTS / 'linux_supervisor.py', root / '.github/workflows/research-writer-ci.yml']
                pins = {str(path.relative_to(root)): sha(path.read_bytes()) for path in files}
                self.emit('batch', {'batch_id': self.root.name, 'state_root': str(self.root), 'planned_samples': MAX_SAMPLES,
                    'source_sha256': pins, 'fixture_code': CODE, 'resources': RESOURCES,
                    'limits': {'work': WORK_SECONDS, 'rpc': RPC_SECONDS, 'cleanup': CLEANUP_SECONDS, 'total': TOTAL_SECONDS,
                               'admission_floor': ADMISSION_SECONDS, 'observer': OBSERVE_SECONDS, 'finish': FINISH_SECONDS,
                               'rpc_tail': RPC_TAIL_SECONDS, 'stream_bytes': STREAM_BYTES, 'record_bytes': RECORD_BYTES,
                               'report_bytes': REPORT_BYTES, 'records': MAX_RECORDS},
                    'coverage': 'changed foreground transport; original detached acceptance remains separate'})
                self.setup()
                for index in range(1, MAX_SAMPLES + 1):
                    self.budget.admit()
                    if not self.sample(index):
                        break
            except BaseException as exc:
                failure = error(exc)
            finally:
                accepted = (failure is None and len(self.completed) == MAX_SAMPLES and all(x['accepted'] for x in self.completed)
                            and not self.budget.exhausted and not self.budget.uncertain and self.budget.elapsed() < TOTAL_SECONDS)
                self.journal.emit('summary', {'classification': 'not_reproduced_in_3' if accepted else 'failed_or_incomplete',
                    'samples': self.completed, 'failure': failure, 'elapsed': self.budget.elapsed(),
                    'budget_exhausted': self.budget.exhausted, 'uncertain_launch_or_remove': self.budget.uncertain,
                    'rpc_clamp_count': self.budget.clamps, 'unwritten_sample': self.current,
                    'state_retained_at': str(self.root), 'historical_exit_2_resolved': False}, final=True)
        return 0 if accepted else 1


def main(argv=None):
    budget = Budget()  # Also precedes CLI parsing and report opening.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--image-id', help='Optional existing immutable image; otherwise inspect the fixed provisioned official tag')
    parser.add_argument('--report', required=True)
    config = parser.parse_args(argv)
    journal = None
    try:
        journal = Journal(config.report)
        return Batch(config, journal, budget).run()
    except Exception as exc:
        print(json.dumps({'classification': 'failed_or_incomplete', 'error': error(exc)}), file=sys.stderr, flush=True)
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
