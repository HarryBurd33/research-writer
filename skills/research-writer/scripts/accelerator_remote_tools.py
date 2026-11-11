#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the fixed accelerator acceptance control on a pinned existing SSH host."""
from __future__ import annotations

import argparse
import base64
import binascii
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import uuid

import accelerator_remote_worker as wire
import accelerator_tools as accelerator
import protein_tools as protein
from transport_common import CaptureError, run_bounded, save_state

ROOT = Path(__file__).resolve().parent
MAX_REPLY = ((wire.MAX_RESULT + 2) // 3) * 4 + wire.MAX_REQUEST
SSH_FIELDS = {'host', 'port', 'identity_file', 'ed25519_host_key', 'connect_timeout_seconds'}
STATUSES = {
    'prepare': {'prepared'}, 'submit': {'launching'},
    'status': wire.TERMINAL | {'prepared', 'launching', 'running', 'uncertain', 'not_found'},
    'recover': wire.TERMINAL | {'prepared', 'launching', 'running', 'uncertain', 'not_found'},
    'cancel': wire.TERMINAL | {'launching', 'running', 'uncertain'},
    'collect': {'succeeded'},
}


class RPCError(RuntimeError):
    """The authenticated response could not be accepted."""


def source_pins():
    return {name: wire.digest(wire.read_file(ROOT / name, wire.MAX_SOURCE))
            for name in sorted(wire.SOURCE_NAMES)}


def profile(path):
    p = wire.load_json(path)
    wire.exact_fields(p, {'contract', 'ssh', 'target', 'workload', 'source_pins'}, 'profile')
    if p['contract'] != wire.CONTRACT:
        raise ValueError('Expected the remote accelerator profile contract')
    ssh = p['ssh']
    wire.exact_fields(ssh, SSH_FIELDS, 'SSH profile')
    if not isinstance(ssh['host'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', ssh['host']):
        raise ValueError('Expected a plain SSH hostname or IPv4 address')
    for key, low, high in (('port', 1, 65535), ('connect_timeout_seconds', 1, 30)):
        if type(ssh[key]) is not int or not low <= ssh[key] <= high:
            raise ValueError('Invalid SSH ' + key)
    key = ssh['ed25519_host_key']
    prefix = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'
    if not isinstance(key, str) or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{68}', key):
        raise ValueError('Pin exactly one OpenSSH Ed25519 public host key')
    raw = base64.b64decode(key.split()[1], validate=True)
    if len(raw) != len(prefix) + 32 or not raw.startswith(prefix):
        raise ValueError('Invalid Ed25519 host key')
    key_path = ssh['identity_file']
    if not isinstance(key_path, str) or '%' in key_path or '$' in key_path or any(ord(c) < 32 for c in key_path):
        raise ValueError('Select an explicit existing SSH identity file path')
    wire.checked_path(key_path)
    wire.validate_target(p['target'])
    wire.validate_workload(p['workload'], p['target'])
    wire.check_source_pins(p['source_pins'])
    if p['source_pins'] != source_pins():
        raise ValueError('Local reviewed source pins differ')
    return p


def envelope(p, operation, binding=None):
    return {'contract': wire.CONTRACT, 'operation': operation, 'target': p['target'],
            'source_pins': p['source_pins'], 'binding': binding}


def ssh_argv(p, known_hosts):
    ssh = p['ssh']
    binary = shutil.which('ssh')
    if not binary:
        raise ValueError('OpenSSH client is required')
    path = str(known_hosts)
    if '%' in path or '$' in path or any(ord(c) < 32 for c in path):
        raise ValueError('Choose a temporary directory without SSH expansion tokens')
    quoted_path = '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'
    options = [
        'BatchMode=yes', 'IdentitiesOnly=yes', 'IdentityAgent=none',
        'PreferredAuthentications=publickey', 'HostKeyAlgorithms=ssh-ed25519',
        'HostKeyAlias=rw-accelerator-pin', f'UserKnownHostsFile={quoted_path}',
        'GlobalKnownHostsFile=none', 'StrictHostKeyChecking=yes', 'UpdateHostKeys=no',
        'VerifyHostKeyDNS=no', 'ClearAllForwardings=yes', 'ForwardAgent=no',
        'ForwardX11=no', 'ControlMaster=no', 'ControlPath=none', 'ConnectionAttempts=1',
        f"ConnectTimeout={ssh['connect_timeout_seconds']}",
    ]
    argv = [binary, '-F', '/dev/null', '-T', '-p', str(ssh['port']), '-l', p['target']['user'],
            '-i', ssh['identity_file']]
    for item in options:
        argv.extend(['-o', item])
    command = shlex.join([p['target']['python'], '-I', '-S', '-B', '-c', wire.BOOTSTRAP, 'rpc'])
    return [*argv, '--', ssh['host'], command]


def validate_reply(response, req):
    op = req['operation']
    if op == 'inspect':
        expected = {'contract': wire.CONTRACT, 'status': 'verified', 'runtime': req['target']['runtime'],
                    'source_pins': req['source_pins'], 'executed': False}
        if response != expected:
            raise ValueError('Inspection reply differs from selected pins')
        return response
    if not isinstance(response, dict) or not isinstance(response.get('status'), str):
        raise ValueError('Missing remote job status')
    wire.check_state(req, response)
    status = response['status']
    if status not in STATUSES[op]:
        raise ValueError('Unexpected remote job status')
    extra = {'executed'} if status == 'prepared' else set()
    if status in {'launching', 'running'}:
        extra.add('heartbeat')
    if status == 'succeeded':
        extra.update(('result_sha256', 'result_bytes', 'comparison', 'elapsed_seconds'))
    if status in {'failed', 'timed_out', 'cancelled', 'uncertain'}:
        extra.add('reason')
    optional = {'elapsed_seconds', 'heartbeat'} if status == 'uncertain' else set()
    if status in {'failed', 'timed_out', 'cancelled'}:
        optional.add('elapsed_seconds')
    if op == 'cancel' and status in {'launching', 'running', 'uncertain'}:
        extra.add('cancel_requested')
    if op == 'collect':
        extra.add('result_base64')
    required = set(wire.state_for(req, status)) | extra
    if not required <= response.keys() or response.keys() - required - optional:
        raise ValueError('Unexpected remote job reply fields')
    if status == 'prepared' and response['executed'] is not False:
        raise ValueError('Prepare response claims inference')
    if 'cancel_requested' in response and response['cancel_requested'] is not True:
        raise ValueError('Invalid cancellation receipt')
    if status == 'succeeded':
        pin = response['result_sha256']
        size = response['result_bytes']
        if (not isinstance(pin, str) or not wire.SHA256.fullmatch(pin) or type(size) is not int
                or not 0 < size <= req['binding']['workload']['max_result_bytes']):
            raise ValueError('Invalid remote result receipt')
    return response


def rpc(p, req):
    wire.validate_envelope(req)
    with tempfile.TemporaryDirectory(prefix='rw-accelerator-ssh-') as directory:
        known_hosts = Path(directory) / 'known_hosts'
        wire.publish_bytes(known_hosts, ('rw-accelerator-pin ' + p['ssh']['ed25519_host_key'] + '\n').encode())
        try:
            completed = run_bounded(ssh_argv(p, known_hosts), wire.canonical(req),
                                    timeout=p['ssh']['connect_timeout_seconds'] + 10,
                                    max_input=wire.MAX_REQUEST, max_stdout=MAX_REPLY, max_stderr=16384)
        except CaptureError as exc:
            raise RPCError(str(exc)) from exc
    if completed.returncode:
        raise RPCError('SSH worker exit ' + str(completed.returncode) + ': '
                       + completed.stderr.decode('utf-8', errors='replace')[-1500:].strip())
    try:
        return validate_reply(wire.decode(completed.stdout), req)
    except (TypeError, KeyError, ValueError) as exc:
        raise RPCError('Invalid authenticated reply: ' + str(exc)) from exc


def uncertain(req, error):
    return wire.state_for(req, 'uncertain', reason=str(error)[:1536])


def pin_profile(p):
    return wire.digest(wire.canonical(p))


def load_job(p, directory):
    root = wire.private_dir(directory)
    local = wire.load_json(root / 'job.json')
    wire.exact_fields(local, {'profile_sha256', 'binding'}, 'local job')
    if local['profile_sha256'] != pin_profile(p):
        raise ValueError('Prepared local job profile differs')
    return root, local['binding']


def prepare(p, directory, input_path):
    control = wire.read_file(input_path, 128)
    if control != accelerator.CONTROL:
        raise ValueError('Only the exact frozen accelerator control can be transferred')
    binding = {
        'job_id': uuid.uuid4().hex, 'workload': p['workload'],
        'control': base64.b64encode(control).decode('ascii'),
        'assets': {name: {'bytes': spec[0], 'sha256': spec[1]} for name, spec in protein.FILES.items()},
    }
    wire.checked_path(directory.parent, directory=True)
    directory.mkdir(mode=0o700)
    save_state(directory / 'job.json', {'profile_sha256': pin_profile(p), 'binding': binding}, exclusive=True)
    req = envelope(p, 'prepare', binding)
    try:
        return rpc(p, req)
    except RPCError as exc:
        return uncertain(req, exc)


def collect(req, response, destination):
    raw = base64.b64decode(response['result_base64'], validate=True)
    if len(raw) != response['result_bytes'] or wire.digest(raw) != response['result_sha256']:
        raise ValueError('Collected accelerator checksum differs')
    request = wire.workload_request(req, accelerator, protein)
    comparison = wire.validate_result(req, request, accelerator, raw)
    if comparison != response['comparison']:
        raise ValueError('Collected numerical comparison differs from remote receipt')
    wire.checked_path(destination.parent, directory=True)
    with tempfile.TemporaryDirectory(prefix='.rw-accelerator-collect-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result.json'
        wire.publish_bytes(staged, raw)
        os.link(staged, destination)
    return {key: value for key, value in response.items() if key != 'result_base64'}


def operate(p, op, directory, destination=None):
    root, binding = load_job(p, directory)
    req = envelope(p, op, binding)
    attempt_path = root / 'submit-intent.json'
    if op == 'submit':
        if attempt_path.exists() or attempt_path.is_symlink():
            raise ValueError('Local submit already attempted. Use recover. Never resubmit an uncertain job.')
        # Read-only preflight keeps a known unprepared job from consuming its
        # one dispatch. The remote reservation separately serializes mutations.
        ready = rpc(p, envelope(p, 'status', binding))
        if ready['status'] != 'prepared':
            raise ValueError('Remote job is unavailable for its one submission')
        save_state(attempt_path, wire.state_for(req, 'dispatch_intent'), exclusive=True)
    try:
        response = rpc(p, req)
    except RPCError as exc:
        if op == 'collect':
            raise
        return uncertain(req, exc)
    if op in {'status', 'recover'} and attempt_path.exists() and response['status'] in {'prepared', 'not_found'}:
        return uncertain(req, 'Local dispatch intent exists without a reconciled remote outcome')
    if op == 'collect':
        return collect(req, response, destination)
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='operation', required=True)
    subs.add_parser('source-pins').add_argument('--output', required=True, type=Path)
    for op in sorted(wire.OPERATIONS):
        command = subs.add_parser(op)
        command.add_argument('--profile', required=True, type=Path)
        command.add_argument('--output', required=True, type=Path)
        if op != 'inspect':
            command.add_argument('--directory', required=True, type=Path)
        if op == 'prepare':
            command.add_argument('--input', required=True, type=Path)
            command.add_argument('--allow-transfer', required=True, action='store_true')
        elif op == 'submit':
            command.add_argument('--allow-execute', required=True, action='store_true')
        elif op == 'cancel':
            command.add_argument('--allow-cancel', required=True, action='store_true')
        elif op == 'collect':
            command.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    op = args.operation
    try:
        if os.name != 'posix':
            raise ValueError('This accelerator client requires POSIX OpenSSH')
        output = args.output.absolute()
        wire.checked_path(output.parent, directory=True)
        if output.exists() or output.is_symlink():
            raise FileExistsError('Output report already exists')
        if op == 'source-pins':
            result = source_pins()
        else:
            p = profile(args.profile.absolute())
            if op == 'inspect':
                result = rpc(p, envelope(p, op))
            elif op == 'prepare':
                result = prepare(p, args.directory.absolute(), args.input.absolute())
            elif op == 'collect':
                destination = args.destination.absolute()
                if destination == output or destination.exists() or destination.is_symlink():
                    raise FileExistsError('Collection requires distinct new destination and report paths')
                result = operate(p, op, args.directory.absolute(), destination=destination)
            else:
                result = operate(p, op, args.directory.absolute())
        save_state(output, result, exclusive=True)
        return 2 if result.get('status') in {'failed', 'timed_out', 'uncertain', 'not_found'} else 0
    except (OSError, ValueError, RPCError, binascii.Error) as exc:
        print(wire.canonical({'contract': wire.CONTRACT, 'error': str(exc)[:1536]}).decode(), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
