#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit immutable SQLite backups over authenticated SSH; no execution clearance."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
if 'C' not in globals():
    _spec = importlib.util.spec_from_file_location('rw_backup_checkpoint', ROOT / 'checkpoint_tools.py')
    C = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(C)
if __name__ != 'backup_receiver':
    _spec = importlib.util.spec_from_file_location('rw_backup_remote', ROOT / 'remote_tools.py')
    R = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(R)

MAX_BACKUP = 64 * 1024**2
MAX_WIRE = 96 * 1024**2
MAX_SMALL = 1024**2
BOOTSTRAP = ("import sys,json,types; raw=sys.stdin.buffer.read(100663297); "
             "assert len(raw)<=100663296,'Backup envelope exceeds bound'; "
             "e=json.loads(raw,object_pairs_hook=lambda p: dict(p) if len(dict(p))==len(p) else (_ for _ in ()).throw(ValueError('Duplicate JSON key')),parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON'))); "
             "c=types.ModuleType('checkpoint_tools'); c.__file__='<checkpoint_tools.py>'; "
             "exec(compile(e['checkpoint_source'],c.__file__,'exec'),c.__dict__); "
             "g={'__name__':'backup_receiver','__file__':'<backup_tools.py>','C':c}; "
             "exec(compile(e['backup_source'],g['__file__'],'exec'),g); "
             "g['receiver_main'](e['request'])")


def canonical(value):
    return C.canonical(value)


def decode(raw, maximum=MAX_SMALL):
    if len(raw) > maximum:
        raise ValueError('Backup JSON exceeds byte bound')
    return json.loads(raw, object_pairs_hook=C.pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def cap(value):
    if type(value) is not int or not 1024**2 <= value <= MAX_BACKUP or value % 1024**2:
        raise ValueError('Explicit backup cap must be whole MiB in 1..64MiB')
    return value


def profile(value):
    if not isinstance(value, dict): raise ValueError('Backup profile must be an object')
    extras = {'vault_id', 'max_backup_bytes', 'rpc_timeout_seconds'}
    if set(value) != R.PROFILE_FIELDS | extras:
        raise ValueError('Exact backup profile fields required; no credentials')
    p = R.profile({k: v for k, v in value.items() if k not in extras})
    for name in ('expected_hostname', 'expected_user'):
        R.text(p[name], name)
    C.identifier(value['vault_id']); cap(value['max_backup_bytes'])
    if type(value['rpc_timeout_seconds']) is not int or not 5 <= value['rpc_timeout_seconds'] <= 300:
        raise ValueError('RPC timeout must be explicit 5..300 seconds')
    p.update({k: value[k] for k in extras})
    return p


def private_directory(path):
    path = C.outside_skill(path)
    if not path.is_dir(): raise ValueError('Existing private directory required')
    st = path.stat()
    if os.name == 'posix' and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        raise ValueError('Directory must be current-user private')
    return path


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            count = stream.write(raw)
            if count != len(raw): raise OSError('Short backup write')
            stream.flush(); os.fsync(fd)
    finally: os.close(fd)


def fsync_file(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try: os.fsync(fd)
    finally: os.close(fd)


def publish_report(path, raw):
    """A failed flush/publication must not leave a new success report behind."""
    path = C.outside_skill(path); private_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix='.rw-backup-report-', dir=path.parent)
    os.close(fd); stage = Path(name); stage.unlink(); published = False
    try:
        write_new(stage, raw)
        identity = stage.stat()
        C.rename_new(stage, path); published = True
        C.fsync_directory(path.parent)
    except Exception:
        if published:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino): path.unlink()
            except OSError: pass
        raise
    finally:
        if stage.exists(): stage.unlink()


def descriptor(value):
    if not isinstance(value, dict) or set(value) != {'schema_version','backup_id','size','sha256','logical_sha256'}:
        raise ValueError('Exact backup descriptor fields required')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unknown backup descriptor version')
    C.identifier(value['backup_id']); C.sha(value['sha256']); C.sha(value['logical_sha256'])
    if type(value['size']) is not int or not 1 <= value['size'] <= MAX_BACKUP:
        raise ValueError('Backup size outside absolute bound')
    return value


def drill_store(store):
    """Verify every generation, restore each separately, re-read all payload bytes."""
    result = C.verify_store(store)
    with tempfile.TemporaryDirectory(prefix='rw-backup-drill-') as directory:
        work = Path(directory).resolve()
        for item in result['checkpoints']:
            target = work / item['checkpoint_id']
            C.restore(store, item['checkpoint_id'], target, True)
            receipt = C.read_json(target / '.checkpoint.json', C.MAX_RPC)
            if receipt != item:
                raise ValueError('Restore metadata does not match checkpoint')
            for entry in item['files']:
                raw = C.regular(target / entry['path'], C.MAX_FILE)
                if len(raw) != entry['size'] or C.digest(raw) != entry['sha256']:
                    raise ValueError('Restored file mismatch')
    logical = {'policy': result['policy'], 'checkpoints': result['checkpoints']}
    return {'logical_sha256': C.digest(canonical(logical)),
            'store_id': result['policy']['store_id'], 'generations': len(result['checkpoints']),
            'full_restore_drill': True}


def checked_artifact(store, expected, maximum):
    descriptor(expected)
    if expected['size'] > cap(maximum): raise ValueError('Backup exceeds selected cap')
    raw = C.regular(Path(store) / C.DB_NAME, maximum)
    if len(raw) != expected['size'] or C.digest(raw) != expected['sha256']:
        raise ValueError('Backup bytes do not match immutable intent')
    drill = drill_store(store)
    if drill['logical_sha256'] != expected['logical_sha256']:
        raise ValueError('Backup logical inventory mismatch')
    if C.regular(Path(store) / C.DB_NAME, maximum) != raw:
        raise ValueError('Closed backup changed during verification')
    return raw, drill


def new_parent(destination):
    destination = C.outside_skill(destination)
    if destination.exists(): raise ValueError('Destination must be new; no overwrite')
    private_directory(destination.parent)
    return destination


def prepare(p, store, backup_id, state_dir):
    p = profile(p); C.identifier(backup_id); state_dir = new_parent(state_dir)
    source = C.no_symlinks(store)
    if source == state_dir or source in state_dir.parents or state_dir in source.parents:
        raise ValueError('State must be separate from checkpoint source')
    stage = Path(tempfile.mkdtemp(prefix='.rw-backup-prepare-', dir=state_dir.parent))
    try:
        C.backup(source, stage / 'snapshot', True, max_backup_bytes=p['max_backup_bytes'])
        raw = C.regular(stage / 'snapshot' / C.DB_NAME, p['max_backup_bytes'])
        if not raw: raise ValueError('Empty database is not a backup')
        drill = drill_store(stage / 'snapshot')
        d = {'schema_version': 1, 'backup_id': backup_id, 'size': len(raw),
             'sha256': C.digest(raw), 'logical_sha256': drill['logical_sha256']}
        descriptor(d); fsync_file(stage / 'snapshot' / C.DB_NAME)
        intent = {'schema_version': 1, 'profile_sha256': C.digest(canonical(p)), 'descriptor': d}
        write_new(stage / 'intent.json', canonical(intent)); C.fsync_directory(stage)
        C.rename_new(stage, state_dir); C.fsync_directory(state_dir.parent)
        return result('prepared', d, drill)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def load_intent(p, state_dir):
    p = profile(p); root = private_directory(state_dir)
    if set(x.name for x in root.iterdir()) - {'intent.json', 'snapshot', 'attempt.json'}:
        raise ValueError('Unexpected state entry')
    value = decode(C.regular(root / 'intent.json', MAX_SMALL))
    if not isinstance(value, dict) or set(value) != {'schema_version','profile_sha256','descriptor'} or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid immutable backup intent')
    if value['profile_sha256'] != C.digest(canonical(p)):
        raise ValueError('Profile changed since preparation')
    d = descriptor(value['descriptor'])
    if d['size'] > p['max_backup_bytes']: raise ValueError('Intent exceeds selected cap')
    return root, d


def result(state, d=None, drill=None):
    out = {'state': state, 'execution_clearance': 'not_granted',
           'failure_domain': 'unverified_no_topology_attestation',
           'durability': 'storage_flush_dependent_no_physical_failure_attestation'}
    if d is not None: out['descriptor'] = d
    if drill is not None: out['verification'] = drill
    return out


def request(p, operation, d=None):
    return {'schema_version': 1, 'operation': operation,
            'remote_root': p['remote_root'], 'vault_id': p['vault_id'],
            'expected_hostname': p['expected_hostname'], 'expected_user': p['expected_user'],
            'max_backup_bytes': p['max_backup_bytes'], 'descriptor': d}


def rpc(p, req):
    """One SSH call, bounded request/output/deadline; never automatically retries."""
    import shlex
    sources = {'checkpoint_source': C.regular(ROOT / 'checkpoint_tools.py', MAX_SMALL).decode(),
               'backup_source': C.regular(ROOT / 'backup_tools.py', MAX_SMALL).decode(), 'request': req}
    payload = canonical(sources)
    if len(payload) > MAX_WIRE: raise ValueError('Backup request exceeds wire bound')
    argv = R.ssh_argv(p)
    argv[-1] = shlex.join([p['remote_python'], '-c', BOOTSTRAP])
    with tempfile.TemporaryDirectory(prefix='rw-backup-rpc-') as directory:
        folder = Path(directory).resolve()
        inp, out, err = [folder / n for n in ('input', 'output', 'error')]
        write_new(inp, payload)
        with inp.open('rb') as source, out.open('wb') as stdout, err.open('wb') as stderr:
            child = subprocess.Popen(argv, stdin=source, stdout=stdout, stderr=stderr,
                                     shell=False, start_new_session=os.name == 'posix')
            deadline = time.monotonic() + p['rpc_timeout_seconds']
            reason = None
            while child.poll() is None:
                if time.monotonic() > deadline: reason = 'SSH deadline; outcome uncertain'; break
                if out.stat().st_size > MAX_WIRE or err.stat().st_size > MAX_SMALL:
                    reason = 'SSH output limit; outcome uncertain'; break
                time.sleep(.025)
            if reason:
                if os.name == 'posix':
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                else: child.kill()
                child.wait(timeout=5)
                raise R.TransportError(reason)
            child.wait()
        if child.returncode:
            raise R.TransportError('SSH failed; outcome uncertain: ' + C.regular(err, MAX_SMALL).decode('utf-8', 'replace')[-1000:])
        response = decode(C.regular(out, MAX_WIRE), MAX_WIRE)
    if not isinstance(response, dict) or response.get('schema_version') != 1 or response.get('hostname') != p['expected_hostname'] or response.get('user') != p['expected_user'] or response.get('vault_id') != p['vault_id'] or response.get('remote_root') != p['remote_root']:
        raise R.TransportError('Receiver identity/protocol mismatch; outcome uncertain')
    if response.get('ok') is not True:
        raise ValueError('Receiver rejected: ' + str(response.get('error', 'unknown'))[:1000])
    return response


def init_remote(p, allow_transfer=False):
    p = profile(p)
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required for remote initialization')
    reply = rpc(p, request(p, 'init'))
    return {**result('vault_ready'), 'vault_id': reply['vault_id']}


def push(p, state_dir, allow_transfer=False):
    p = profile(p)
    if not allow_transfer: raise ValueError('Explicit --allow-transfer required')
    root, d = load_intent(p, state_dir)
    if (root / 'attempt.json').exists():
        raise ValueError('Upload already attempted; use read-only verify/fetch, never blind replay')
    raw, _ = checked_artifact(root / 'snapshot', d, p['max_backup_bytes'])
    # Durable one-shot intent precedes all network mutation. A failed marker flush
    # sends nothing; a partial/complete marker blocks blind replay conservatively.
    write_new(root / 'attempt.json', canonical({'schema_version': 1, 'descriptor': d}))
    C.fsync_directory(root)
    q = request(p, 'put', d); q['data_base64'] = base64.b64encode(raw).decode('ascii')
    try:
        rpc(p, q)
        return verify(p, root)
    except Exception as exc:
        raise R.TransportError('Backup outcome uncertain; reconcile with verify/fetch: ' + str(exc)[:1000]) from exc


def received(p, state_dir):
    root, d = load_intent(p, state_dir)
    reply = rpc(p, request(p, 'get', d))
    if reply.get('descriptor') != d: raise ValueError('Readback descriptor mismatch')
    encoded = reply.get('data_base64')
    if not isinstance(encoded, str) or len(encoded) != 4 * ((d['size'] + 2) // 3):
        raise ValueError('Readback encoding length mismatch')
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) != d['size'] or C.digest(raw) != d['sha256']:
        raise ValueError('Readback bytes do not match immutable intent')
    return d, raw


def materialize(raw, d, destination, maximum):
    destination = new_parent(destination)
    stage = Path(tempfile.mkdtemp(prefix='.rw-backup-fetch-', dir=destination.parent))
    try:
        write_new(stage / C.DB_NAME, raw)
        _, drill = checked_artifact(stage, d, maximum)
        fsync_file(stage / C.DB_NAME); C.fsync_directory(stage)
        C.rename_new(stage, destination); C.fsync_directory(destination.parent)
        return drill
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(p, state_dir):
    p = profile(p); d, raw = received(p, state_dir)
    with tempfile.TemporaryDirectory(prefix='rw-backup-readback-') as directory:
        drill = materialize(raw, d, Path(directory).resolve() / 'store', p['max_backup_bytes'])
    return result('verified', d, {**drill, 'fresh_ssh_readback': True})


def fetch(p, state_dir, destination, allow_restore=False):
    p = profile(p)
    if not allow_restore: raise ValueError('Explicit --allow-restore required')
    destination = new_parent(destination)
    root, _ = load_intent(p, state_dir)
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError('Fetch destination must be separate from intent state')
    d, raw = received(p, root)
    drill = materialize(raw, d, destination, p['max_backup_bytes'])
    return {**result('fetched', d, {**drill, 'fresh_ssh_readback': True}), 'destination': str(destination)}


@contextmanager
def vault_lock(root):
    import fcntl
    root = private_directory(root)
    fd = os.open(root / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        a, b = os.fstat(fd), (root / '.lock').lstat()
        if not stat.S_ISREG(a.st_mode) or a.st_nlink != 1 or (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino) or a.st_uid != os.getuid() or a.st_mode & 0o077:
            raise ValueError('Unsafe vault lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    finally: os.close(fd)


def vault(root, vault_id):
    root = private_directory(root)
    names = {x.name for x in root.iterdir()}
    if names - {'vault.json', '.lock', 'backups'} - {n for n in names if n.startswith('.stage-') and len(n) == 39}:
        raise ValueError('Unexpected vault entries')
    value = decode(C.regular(root / 'vault.json', MAX_SMALL))
    if value != {'schema_version': 1, 'vault_id': vault_id}:
        raise ValueError('Vault identity mismatch')
    private_directory(root / 'backups')
    return root


def init_vault(root, vault_id):
    root = C.outside_skill(root)
    if root.exists():
        with vault_lock(root): vault(root, vault_id)
        return result('vault_ready')
    root = new_parent(root)
    stage = Path(tempfile.mkdtemp(prefix='.rw-vault-init-', dir=root.parent))
    try:
        (stage / 'backups').mkdir(mode=0o700)
        write_new(stage / 'vault.json', canonical({'schema_version': 1, 'vault_id': vault_id}))
        write_new(stage / '.lock', b'0')
        C.fsync_directory(stage / 'backups'); C.fsync_directory(stage)
        C.rename_new(stage, root); C.fsync_directory(root.parent)
        return result('vault_ready')
    finally:
        if stage.exists(): shutil.rmtree(stage)


def read_archive(root, d, maximum):
    target = private_directory(root / 'backups' / d['backup_id'])
    if {x.name for x in target.iterdir()} != {'descriptor.json', 'store'}:
        raise ValueError('Unexpected archive entry')
    if decode(C.regular(target / 'descriptor.json', MAX_SMALL)) != d:
        raise ValueError('Immutable backup ID has different descriptor')
    raw, drill = checked_artifact(target / 'store', d, maximum)
    return raw, drill


def put_archive(root, d, raw, maximum):
    destination = root / 'backups' / d['backup_id']
    if destination.exists():
        old, drill = read_archive(root, d, maximum)
        if old != raw: raise ValueError('Immutable backup ID conflict')
        return result('already_present', d, drill)
    # Recognizable, inert UUID stages survive process death without blocking
    # reads of earlier archives. They are never treated as published backups.
    stage = root / ('.stage-' + uuid.uuid4().hex); stage.mkdir(mode=0o700)
    try:
        (stage / 'store').mkdir(mode=0o700)
        write_new(stage / 'store' / C.DB_NAME, raw)
        _, drill = checked_artifact(stage / 'store', d, maximum)
        write_new(stage / 'descriptor.json', canonical(d))
        fsync_file(stage / 'store' / C.DB_NAME)
        C.fsync_directory(stage / 'store'); C.fsync_directory(stage)
        C.rename_new(stage, destination)
        # A failure here means a published but unconfirmed backup; caller must
        # reconcile by immutable ID. Never remove a published destination.
        C.fsync_directory(root / 'backups'); C.fsync_directory(root)
        return result('stored', d, drill)
    finally:
        if stage.exists(): shutil.rmtree(stage)


def receiver(req):
    if os.name != 'posix': raise ValueError('Backup receiver requires POSIX local filesystem')
    fields = {'schema_version','operation','remote_root','vault_id','expected_hostname','expected_user','max_backup_bytes','descriptor'}
    if not isinstance(req, dict) or set(req) not in (fields, fields | {'data_base64'}):
        raise ValueError('Exact receiver request fields required')
    if type(req['schema_version']) is not int or req['schema_version'] != 1 or req['operation'] not in ('init','put','get'):
        raise ValueError('Unknown receiver protocol')
    if req['expected_hostname'] != socket.gethostname() or req['expected_user'] != getpass.getuser():
        raise ValueError('Receiver host/user mismatch')
    C.identifier(req['vault_id']); maximum = cap(req['max_backup_bytes'])
    root = C.outside_skill(req['remote_root'])
    if not isinstance(req['remote_root'],str) or not Path(req['remote_root']).is_absolute() or len(root.parts) < 3 or '..' in root.parts or str(root) != req['remote_root']:
        raise ValueError('Absolute dedicated vault root required')
    # The receiver runs from uploaded source, so its synthetic __file__ cannot
    # identify another installed skill. Conservatively reject skill ancestors.
    if any((p / 'SKILL.md').is_file() for p in (root, *root.parents)):
        raise ValueError('Remote backup vault must be outside any skill folder')
    if req['operation'] == 'init':
        if req['descriptor'] is not None or 'data_base64' in req: raise ValueError('Invalid init payload')
        return init_vault(root, req['vault_id'])
    d = descriptor(req['descriptor'])
    if d['size'] > maximum: raise ValueError('Backup exceeds selected cap before decoding')
    raw = None
    if req['operation'] == 'put':
        encoded = req.get('data_base64')
        if not isinstance(encoded, str) or len(encoded) != 4 * ((d['size'] + 2) // 3):
            raise ValueError('Backup encoding length mismatch')
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != d['size'] or C.digest(raw) != d['sha256']:
            raise ValueError('Backup transfer checksum mismatch')
    elif 'data_base64' in req: raise ValueError('Read-only request must contain no upload')
    with vault_lock(root):
        vault(root, req['vault_id'])
        if req['operation'] == 'put': return put_archive(root, d, raw, maximum)
        raw, drill = read_archive(root, d, maximum)
        return {**result('verified', d, drill), 'data_base64': base64.b64encode(raw).decode('ascii')}


def receiver_main(req):
    identity = {'schema_version': 1, 'hostname': socket.gethostname(), 'user': getpass.getuser(),
                'vault_id': req.get('vault_id') if isinstance(req, dict) else None,
                'remote_root': req.get('remote_root') if isinstance(req, dict) else None}
    try: reply = {**identity, 'ok': True, **receiver(req)}
    except Exception as exc:
        reply = {**identity, 'ok': False, 'state': 'failed_or_uncertain', 'error': str(exc)[:1500],
                 'execution_clearance': 'not_granted'}
    raw = canonical(reply)
    if len(raw) > MAX_WIRE: raise ValueError('Receiver response exceeds wire bound')
    sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for op in ('init-remote','prepare','push','verify','fetch'):
        cmd = sub.add_parser(op); cmd.add_argument('--profile', required=True); cmd.add_argument('--report', required=True)
        if op != 'init-remote': cmd.add_argument('--state-dir', required=True)
        if op == 'prepare': cmd.add_argument('--store', required=True); cmd.add_argument('--backup-id', required=True)
        if op in ('push','init-remote'): cmd.add_argument('--allow-transfer', action='store_true')
        if op == 'fetch': cmd.add_argument('--destination', required=True); cmd.add_argument('--allow-restore', action='store_true')
    args = parser.parse_args(argv)
    report = None; report_safe = False
    try:
        report = C.outside_skill(args.report)
        if report.exists(): raise ValueError('Report destination must be new')
        private_directory(report.parent)
        for name in ('store', 'state_dir', 'destination'):
            if getattr(args, name, None) is not None:
                protected = C.no_symlinks(getattr(args, name))
                if report == protected or protected in report.parents:
                    raise ValueError('Report must be separate from checkpoint, intent and restore directories')
        report_safe = True
        p = profile(decode(C.regular(args.profile, MAX_SMALL)))
        if args.operation == 'init-remote': reply = init_remote(p, args.allow_transfer)
        elif args.operation == 'prepare': reply = prepare(p, args.store, args.backup_id, args.state_dir)
        elif args.operation == 'push': reply = push(p, args.state_dir, args.allow_transfer)
        elif args.operation == 'verify': reply = verify(p, args.state_dir)
        else: reply = fetch(p, args.state_dir, args.destination, args.allow_restore)
        publish_report(report, canonical({'schema_version': 1, 'ok': True, **reply}) + b'\n')
        return 0
    except Exception as exc:
        reply = {'schema_version': 1, 'ok': False, 'state': 'failed_or_uncertain',
                 'error': str(exc)[:1500], 'execution_clearance': 'not_granted'}
        try:
            if report_safe and report is not None and not report.exists(): write_new(report, canonical(reply) + b'\n')
        except Exception: pass
        print(json.dumps(reply), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
