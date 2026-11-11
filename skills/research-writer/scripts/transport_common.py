# SPDX-License-Identifier: MIT
"""Bounded subprocess byte capture and atomic JSON state for remote clients."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class CaptureError(RuntimeError):
    """Local launch, deadline, I/O or byte limit failure."""


def _pipe_reader():
    if os.name != 'nt':
        def read(pipe, count):
            try:
                return os.read(pipe.fileno(), count)
            except BlockingIOError:
                return None
        return read

    import ctypes
    import msvcrt
    from ctypes import wintypes

    peek = ctypes.WinDLL('kernel32', use_last_error=True).PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                     ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    peek.restype = wintypes.BOOL

    def read(pipe, count):
        # The helper is the only reader of this anonymous pipe. Reading at
        # most the reported available byte count cannot wait for new input.
        available = wintypes.DWORD()
        handle = msvcrt.get_osfhandle(pipe.fileno())
        if not peek(handle, None, 0, None, ctypes.byref(available), None):
            code = ctypes.get_last_error()
            if code in (109, 232, 233):  # pipe writer closed
                return b''
            raise ctypes.WinError(code)
        if not available.value:
            return None
        return os.read(pipe.fileno(), min(count, available.value))

    return read


def _capture(child, deadline, max_stdout, max_stderr):
    read = _pipe_reader()
    stdout, stderr = bytearray(), bytearray()
    streams = {
        child.stdout: ('stdout', stdout, max_stdout),
        child.stderr: ('stderr', stderr, max_stderr),
    }
    if os.name != 'nt':
        for pipe in streams:
            os.set_blocking(pipe.fileno(), False)
    while streams:
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise CaptureError('Subprocess deadline expired')
        progressed = False
        for pipe, (label, retained, limit) in tuple(streams.items()):
            remaining_bytes = limit - len(retained)
            # A one-byte probe distinguishes exact-cap EOF from overflow.
            # The probe is never added to the retained capture.
            chunk = read(pipe, min(64 * 1024, remaining_bytes) or 1)
            if chunk is None:
                continue
            progressed = True
            if not chunk:
                del streams[pipe]
            elif len(chunk) > remaining_bytes:
                raise CaptureError(f'Subprocess {label} exceeds {limit} bytes')
            else:
                retained.extend(chunk)
        if not progressed:
            time.sleep(min(0.01, remaining_time))
    returncode = child.wait(timeout=max(0, deadline - time.monotonic()))
    return subprocess.CompletedProcess(child.args, returncode, bytes(stdout), bytes(stderr))


def _stop(child):
    try:
        if os.name == 'posix':
            # Popen created this session and group specifically for the RPC.
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
    except ProcessLookupError:
        pass
    child.wait(timeout=2)


def run_bounded(argv, payload, *, timeout, max_input, max_stdout, max_stderr):
    """Run argv without a shell and return byte streams at the specified caps.

    Only the size-checked input is spooled. Output stays in the two pipes and
    capped in-memory captures. No background reader or writer threads are used.
    A timeout terminates the owned local child (or private POSIX process group).
    It does not establish the outcome of any remote operation.
    """
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError('Expected a nonempty argument array')
    if any(type(limit) is not int or limit < 0 for limit in (max_input, max_stdout, max_stderr)):
        raise ValueError('Expected nonnegative integer byte limits')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Expected a positive, finite timeout')
    if not isinstance(payload, bytes):
        raise TypeError('Expected bytes for subprocess stdin')
    if len(payload) > max_input:
        raise CaptureError(f'Subprocess stdin exceeds {max_input} bytes')
    deadline = time.monotonic() + timeout
    try:
        with tempfile.TemporaryFile() as stdin:
            stdin.write(payload)
            stdin.seek(0)
            if time.monotonic() >= deadline:
                raise CaptureError('Subprocess deadline expired before launch')
            child = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, shell=False, bufsize=0,
                                     start_new_session=os.name == 'posix')
            try:
                return _capture(child, deadline, max_stdout, max_stderr)
            except BaseException:
                try:
                    _stop(child)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise CaptureError(f'Could not confirm local subprocess cleanup: {exc}') from exc
                raise
            finally:
                child.stdout.close()
                child.stderr.close()
    except subprocess.TimeoutExpired as exc:
        raise CaptureError('Subprocess deadline expired') from exc
    except OSError as exc:
        raise CaptureError(f'Subprocess launch or I/O failed: {exc}') from exc


def save_state(path, value, *, exclusive=False):
    """Fsync JSON file data and publish it atomically on the local filesystem.

    The parent must exist. Exclusive publication never overwrites an existing
    name. The contract covers restart after process loss, with no guarantee
    about the storage hardware or persistence of the directory entry.
    """
    path = Path(path)
    data = json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
    fd, name = tempfile.mkstemp(prefix='.rw-state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            os.replace(name, path)
        elif os.name == 'nt':
            os.rename(name, path)  # Windows rename fails when the target exists.
        else:
            os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
