#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""CI-only bounded live Docker observer; never launches or signals a workload."""
from __future__ import annotations
import os
import re
import selectors
import subprocess
import threading
import time

STREAM_BYTES = 8192
LIFETIME_SECONDS = 20


def bounded_text(value, maximum=512):
    return str(value).encode('utf-8', errors='replace')[:maximum].decode('utf-8', errors='ignore')


def container_state(value):
    """Only explicitly selected, bounded diagnostic fields; no configuration/env."""
    return {**{key: bounded_text(value.get(key, ''), 512 if key == 'Error' else 128)
               for key in ('StartedAt', 'FinishedAt', 'Error')},
            'Running': value.get('Running') if type(value.get('Running')) is bool else None,
            'OOMKilled': value.get('OOMKilled') if type(value.get('OOMKilled')) is bool else None,
            'ExitCode': value.get('ExitCode') if type(value.get('ExitCode')) is int else None}


class QueryChronology:
    def __init__(self):
        self.started = time.monotonic()
        self.entries = []
        self.truncated = False
        self.used_bytes = 0

    def add(self, event, value):
        message = bounded_text(value)
        size = len(message.encode('utf-8'))
        if len(self.entries) >= 32 or self.used_bytes + size > 8192:
            self.truncated = True
            return
        self.entries.append({'offset_seconds': round(time.monotonic() - self.started, 6),
                             'event': event, 'value': message})
        self.used_bytes += size

    def report(self):
        return {'entries': list(self.entries), 'truncated': self.truncated}


class LiveObserver:
    """Attach once to an ID already checked by production container validation.

    The independent validated ID must equal the submitted state's pinned ID.
    The attach starts after submission: earlier output is irretrievably absent
    with log-driver=none, and an empty capture never disproves an early failure.
    """
    def __init__(self, docker_executable, context, container_id, validated_id):
        if (not isinstance(container_id, str) or not re.fullmatch('[0-9a-f]{64}', container_id)
                or validated_id != container_id):
            raise ValueError('Observer requires the validated immutable container ID')
        self.container_id = container_id
        self.started_at = time.time()
        self.started = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self._truncated = {'stdout': False, 'stderr': False}
        self._errors = []
        self._deadline_reached = False
        self._ended_at = None
        self._process = subprocess.Popen(
            [docker_executable, '--context', context, 'attach', '--no-stdin',
             '--sig-proxy=false', container_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, start_new_session=True, close_fds=True)
        self._thread = threading.Thread(target=self._capture, name='rw-ci-attach', daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._stop_process()
            self._close_pipes()
            raise

    def _error(self, exc):
        with self._lock:
            if len(self._errors) < 4:
                self._errors.append(bounded_text(type(exc).__name__ + ': ' + str(exc)))

    def _keep(self, name, raw):
        with self._lock:
            room = STREAM_BYTES - len(self._buffers[name])
            self._buffers[name].extend(raw[:room])
            if len(raw) > room:
                self._truncated[name] = True

    def _stop_process(self):
        # This is the owned local attach CLI handle, never a container ID/PID or
        # process group. Signal forwarding was explicitly disabled on creation.
        try:
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait(timeout=1)
        except Exception as exc:
            self._error(exc)

    def _close_pipes(self):
        for stream in (self._process.stdout, self._process.stderr):
            try:
                stream.close()
            except Exception as exc:
                self._error(exc)

    def _capture(self):
        selector = None
        deadline = self.started + LIFETIME_SECONDS
        try:
            selector = selectors.DefaultSelector()
            for name in ('stdout', 'stderr'):
                stream = getattr(self._process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._deadline_reached = True
                    break
                if self._stop.is_set():
                    break
                for key, _ in selector.select(min(0.05, remaining)):
                    try:
                        raw = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if raw:
                        self._keep(key.data, raw)
                    else:
                        selector.unregister(key.fileobj)
        except Exception as exc:
            self._error(exc)
        finally:
            self._stop_process()
            # The CLI has stopped. Preserve already-buffered error bytes without
            # waiting for EOF or allocating an unbounded communicate() result.
            drain_until = time.monotonic() + 0.25
            for key in list(selector.get_map().values()) if selector is not None else []:
                while time.monotonic() < drain_until:
                    try:
                        raw = os.read(key.fileobj.fileno(), 65536)
                    except (BlockingIOError, OSError):
                        break
                    if not raw:
                        break
                    self._keep(key.data, raw)
            try:
                if selector is not None:
                    selector.close()
            except Exception as exc:
                self._error(exc)
            finally:
                self._close_pipes()
                self._ended_at = time.time()

    def finish(self):
        self._stop.set()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            self._stop_process()
            self._thread.join(timeout=2)
        with self._lock:
            return {'container_id': self.container_id, 'started_at': self.started_at,
                    'ended_at': self._ended_at, 'exit_code': self._process.poll(),
                    'deadline_reached': self._deadline_reached,
                    'cleanup_verified': not self._thread.is_alive() and self._process.poll() is not None,
                    'stream_limit_bytes': STREAM_BYTES,
                    'stdout': bytes(self._buffers['stdout']).decode('utf-8', errors='replace'),
                    'stderr': bytes(self._buffers['stderr']).decode('utf-8', errors='replace'),
                    'stdout_bytes': len(self._buffers['stdout']),
                    'stderr_bytes': len(self._buffers['stderr']),
                    'truncated': dict(self._truncated), 'errors': list(self._errors),
                    'coverage': 'live_only_after_submit; earlier_output_unavailable'}
