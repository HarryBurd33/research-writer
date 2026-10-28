#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded local SQLite file/application checkpoints. Saved notes never authorize execution."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import uuid
import unicodedata

MAX_FILE = 8 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_RPC = 32 * 1024**2
MAX_META = 64 * 1024
MAX_DB = 512 * 1024**2
APP_ID = 0x52574350
CONSISTENCY = 'application_declared_not_automatically_verified'
DB_NAME = 'checkpoint.sqlite'
SCHEMA = {
    'policy': 'CREATE TABLE policy(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,fingerprint TEXT NOT NULL)',
    'snapshots': 'CREATE TABLE snapshots(id TEXT PRIMARY KEY,metadata TEXT NOT NULL,fingerprint TEXT NOT NULL,created_at REAL NOT NULL)',
    'files': 'CREATE TABLE files(checkpoint_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,path TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,data BLOB NOT NULL,PRIMARY KEY(checkpoint_id,path))'
}
SKILL_ROOT = Path(__file__).resolve().parent.parent


def outside_skill(path):
    path = no_symlinks(path)
    if (SKILL_ROOT / 'SKILL.md').is_file() and (path == SKILL_ROOT or SKILL_ROOT in path.parents):
        raise ValueError('Checkpoint storage/publication must be outside installed skill')
    return path


def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def decode(raw):
    if len(raw) > MAX_RPC:
        raise ValueError('JSON exceeds byte bound')
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def no_symlinks(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('Symlink component forbidden')
    return path


def regular(path, maximum):
    path = no_symlinks(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise ValueError('Bounded regular non-hardlinked file required')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        actual = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino) or not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise ValueError('File changed during open')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        if len(raw) > maximum or (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('File changed or exceeds bound')
        return raw
    finally:
        os.close(fd)


def read_json(path, maximum=MAX_META):
    return decode(regular(path, maximum))


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(c in value for c in ('\x00', '\n', '\r', '\\')):
        raise ValueError('Confined bounded relative path required')
    p, w = PurePosixPath(value), PureWindowsPath(value)
    if p.is_absolute() or w.drive or str(p) != value or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('Normalized confined relative path required')
    if value != unicodedata.normalize('NFC', value):
        raise ValueError('Portable checkpoint names require NFC Unicode')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10)), *(f'COM{i}' for i in '¹²³'), *(f'LPT{i}' for i in '¹²³')}
    for part in p.parts:
        if any(ord(c) < 32 or ord(c) == 127 or c in '<>:"|?*' for c in part) or part.endswith(('.', ' ')) or part.split('.')[0].upper() in reserved:
            raise ValueError('Nonportable/reserved filename forbidden')
    if any(x.casefold() in ('.ssh', '.aws', '.git', '.codex', '.checkpoint.json', '.collection.json', '.logs') or x.casefold() == '.env' or x.casefold().startswith('.env.') for x in p.parts):
        raise ValueError('Credential/configuration/reserved path forbidden')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('32 lowercase hexadecimal checkpoint ID required')
    return value


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Lowercase SHA-256 required')
    return value


def application(value):
    if not isinstance(value, dict) or set(value) != {'format', 'version', 'resume_notes'}:
        raise ValueError('Exact application fields required')
    for name in ('format', 'version'):
        x = value[name]
        if not isinstance(x, str) or not x.strip() or len(x) > 128 or any(c in x for c in ('\x00', '\n', '\r')):
            raise ValueError('Bounded application format/version required')
    if not isinstance(value['resume_notes'], str) or len(value['resume_notes'].encode('utf-8')) > 8192 or '\x00' in value['resume_notes']:
        raise ValueError('Bounded resume notes required; notes are not commands')
    return value


def provenance(value):
    if not isinstance(value, dict):
        raise ValueError('Provenance object required')
    if value.get('kind') == 'local' and set(value) == {'kind', 'manifest_sha256'}:
        sha(value['manifest_sha256'])
    elif value.get('kind') == 'linux' and set(value) == {'kind', 'job_id', 'manifest_sha256', 'image_id', 'supervisor_sha256', 'container_id', 'engine_id'}:
        identifier(value['job_id']); sha(value['manifest_sha256']); sha(value['supervisor_sha256']); sha(value['container_id'])
        if not isinstance(value['image_id'], str) or not re.fullmatch('sha256:[0-9a-f]{64}', value['image_id']):
            raise ValueError('Immutable image identity required')
        if not isinstance(value['engine_id'], str) or not value['engine_id'] or len(value['engine_id']) > 4096 or any(c in value['engine_id'] for c in ('\x00', '\n', '\r')):
            raise ValueError('Bounded engine identity required')
    else:
        raise ValueError('Unknown provenance fields/kind')
    return value


def inventory(files, payload=True):
    if not isinstance(files, list) or not 1 <= len(files) <= 32:
        raise ValueError('One to32 checkpoint files required')
    names, total, decoded = [], 0, []
    for item in files:
        fields = {'path', 'size', 'sha256'} | ({'data_base64'} if payload else set())
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError('Exact checkpoint file fields required')
        name = relative(item['path']); names.append(name); sha(item['sha256'])
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_FILE:
            raise ValueError('Invalid checkpoint size')
        total += item['size']
        if total > MAX_TOTAL:
            raise ValueError('Checkpoint total exceeds16MiB')
        if payload:
            if not isinstance(item['data_base64'], str) or len(item['data_base64']) > 4 * (MAX_FILE // 3 + 2):
                raise ValueError('Bounded base64 required')
            raw = base64.b64decode(item['data_base64'], validate=True)
            if len(raw) != item['size'] or digest(raw) != item['sha256']:
                raise ValueError('Checkpoint data size/hash mismatch')
            decoded.append((name, raw))
    normalized = [unicodedata.normalize('NFC', x.casefold()) for x in names]
    if len(set(normalized)) != len(normalized):
        raise ValueError('Duplicate/aliased checkpoint paths')
    paths = list(map(PurePosixPath, normalized))
    if any(a != b and a in b.parents for a in paths for b in paths):
        raise ValueError('Checkpoint file/directory conflict')
    return decoded


def validate_packet(packet):
    fields = {'schema_version', 'checkpoint_id', 'application', 'provenance', 'files', 'consistency'}
    if not isinstance(packet, dict) or set(packet) != fields or type(packet['schema_version']) is not int or packet['schema_version'] != 1:
        raise ValueError('Exact checkpoint packet schema1 required')
    identifier(packet['checkpoint_id']); application(packet['application']); provenance(packet['provenance'])
    if packet['consistency'] != CONSISTENCY:
        raise ValueError('Application consistency is not automatically verified')
    decoded = inventory(packet['files'])
    meta = {**packet, 'files': [{k: v for k, v in x.items() if k != 'data_base64'} for x in packet['files']]}
    meta['files'].sort(key=lambda x: x['path'])
    raw = canonical(meta)
    if len(raw) > MAX_META:
        raise ValueError('Checkpoint metadata exceeds64KiB')
    return meta, decoded, digest(raw)


def local_packet(manifest_path):
    manifest_path = no_symlinks(manifest_path)
    raw_manifest = regular(manifest_path, MAX_META); m = decode(raw_manifest)
    if not isinstance(m, dict) or set(m) != {'schema_version', 'checkpoint_id', 'application', 'files'} or type(m['schema_version']) is not int or m['schema_version'] != 1:
        raise ValueError('Exact local checkpoint manifest schema1 required')
    identifier(m['checkpoint_id']); application(m['application'])
    if not isinstance(m['files'], list) or not 1 <= len(m['files']) <= 32:
        raise ValueError('Bounded checkpoint files required')
    declared = []
    for x in m['files']:
        if not isinstance(x, dict) or set(x) != {'source', 'path', 'size', 'sha256'}:
            raise ValueError('Exact local source fields required')
        relative(x['source'])
        declared.append({k: x[k] for k in ('path', 'size', 'sha256')})
    inventory(declared, payload=False)  # Enforce aggregate bounds before reading any file.
    files = []
    for x in m['files']:
        if not isinstance(x, dict) or set(x) != {'source', 'path', 'size', 'sha256'}:
            raise ValueError('Exact local source fields required')
        source = manifest_path.parent / relative(x['source'])
        data = regular(source, x['size'])
        if len(data) != x['size'] or digest(data) != x['sha256']:
            raise ValueError('Local checkpoint source size/hash mismatch')
        files.append({'path': x['path'], 'size': x['size'], 'sha256': x['sha256'], 'data_base64': base64.b64encode(data).decode('ascii')})
    packet = {'schema_version': 1, 'checkpoint_id': m['checkpoint_id'], 'application': m['application'],
              'provenance': {'kind': 'local', 'manifest_sha256': digest(raw_manifest)},
              'files': files, 'consistency': CONSISTENCY}
    validate_packet(packet)
    if regular(manifest_path, MAX_META) != raw_manifest:
        raise ValueError('Input manifest changed during capture')
    return packet


def policy(value):
    if not isinstance(value, dict) or set(value) != {'schema_version', 'store_id', 'max_store_bytes', 'max_generations'} or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid store policy')
    identifier(value['store_id'])
    if type(value['max_store_bytes']) is not int or not 4 * 1024**2 <= value['max_store_bytes'] <= MAX_DB or value['max_store_bytes'] % 1024**2:
        raise ValueError('Store byte cap must be4..512 wholeMiB')
    if type(value['max_generations']) is not int or not 1 <= value['max_generations'] <= 128:
        raise ValueError('Store generation cap must be1..128')
    return value


def safe_store(root):
    root = outside_skill(root)
    if not root.is_dir():
        raise ValueError('Existing dedicated store required')
    st = root.stat()
    if os.name == 'posix' and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        raise ValueError('Store must be current-user private directory')
    allowed = {DB_NAME, '.lock', DB_NAME + '-journal'}
    for path in root.iterdir():
        if path.name not in allowed:
            raise ValueError('Unexpected store entry; nothing deleted')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * MAX_DB + 1024**2:
            raise ValueError('Unsafe store entry')
        if os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('Store files must remain private and current-user owned')
    return root


@contextmanager
def store_lock(root):
    root = safe_store(root)
    path = root / '.lock'
    if path.is_symlink():
        raise ValueError('Lock symlink forbidden')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    stream = os.fdopen(fd, 'r+b'); acquired = False
    try:
        actual, named = os.fstat(fd), path.lstat()
        if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError('Lock identity changed')
        if actual.st_size == 0:
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
                raise ValueError('Unsupported lock platform')
            acquired = True
        except OSError as exc:
            raise ValueError('Another live process owns store lock; no lock is stolen') from exc
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


def configure(conn, p=None):
    for pragma, expected in [('journal_mode=DELETE', 'delete'), ('synchronous=EXTRA', 3), ('foreign_keys=ON', 1), ('temp_store=MEMORY', 2), ('trusted_schema=OFF', 0)]:
        name = pragma.split('=')[0]
        conn.execute('PRAGMA ' + pragma)
        row = conn.execute('PRAGMA ' + name).fetchone()
        if row is None or row[0] != expected:
            raise ValueError('Required SQLite pragma unavailable: ' + name)
    if sys.platform == 'darwin':
        conn.execute('PRAGMA fullfsync=ON')
        if conn.execute('PRAGMA fullfsync').fetchone() != (1,):
            raise ValueError('SQLite fullfsync request unavailable')
    if conn.execute('PRAGMA page_size').fetchone() != (4096,):
        raise ValueError('Expected SQLite4096byte pages')
    if p is not None:
        maximum = p['max_store_bytes'] // 4096
        got = conn.execute('PRAGMA max_page_count=' + str(maximum)).fetchone()
        if got != (maximum,):
            raise ValueError('Database already exceeds cap or max_page_count unavailable')


def raw_connection(db):
    return sqlite3.connect(db.as_uri() + '?mode=rw', uri=True, isolation_level=None, timeout=0.2)


def connect_store(root):
    """Call under store_lock. Reapply the nonpersistent page ceiling on every open."""
    root = safe_store(root); db = root / DB_NAME
    st = db.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_DB:
        raise ValueError('Invalid bounded store database')
    conn = raw_connection(db)
    try:
        if conn.execute('PRAGMA application_id').fetchone() != (APP_ID,) or conn.execute('PRAGMA user_version').fetchone() != (1,):
            raise ValueError('Unknown checkpoint database format')
        if conn.execute("SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone() != (3,):
            raise ValueError('Unexpected database schema object count')
        if conn.execute("SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND (length(CAST(name AS BLOB))>32 OR length(CAST(type AS BLOB))>16)").fetchone() != (0,):
            raise ValueError('Invalid bounded schema object names')
        tables = conn.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if set(tables) != {('policy', 'table'), ('snapshots', 'table'), ('files', 'table')}:
            raise ValueError('Unexpected database schema objects')
        for name, expected in SCHEMA.items():
            row = conn.execute('SELECT length(CAST(sql AS BLOB)),typeof(sql) FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if row is None or row[0] > 4096 or row[1] != 'text':
                raise ValueError('Invalid bounded table schema')
            actual = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
            if ' '.join(actual.split()).casefold() != ' '.join(expected.split()).casefold():
                raise ValueError('Store columns/keys/constraints changed')
        row = conn.execute('SELECT length(CAST(body AS BLOB)),typeof(body),length(CAST(fingerprint AS BLOB)),typeof(fingerprint) FROM policy WHERE id=1').fetchone()
        if row is None or row[0] > MAX_META or row[1] != 'text' or row[2] != 64 or row[3] != 'text' or conn.execute('SELECT count(*) FROM policy').fetchone() != (1,):
            raise ValueError('Invalid bounded store policy record')
        body, fingerprint = conn.execute('SELECT body,fingerprint FROM policy WHERE id=1').fetchone()
        p = policy(decode(body))
        if canonical(p).decode('utf-8') != body or digest(canonical(p)) != fingerprint:
            raise ValueError('Store policy fingerprint changed')
        if st.st_size > p['max_store_bytes']:
            raise ValueError('Store database exceeds configured cap')
        configure(conn, p)
        if conn.execute('PRAGMA page_count').fetchone()[0] * 4096 > p['max_store_bytes']:
            raise ValueError('Database page count exceeds cap')
        return conn, p
    except Exception:
        conn.close(); raise


def fsync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(fd)
        finally: os.close(fd)


def init_store(root, max_store_bytes, max_generations):
    p = policy({'schema_version': 1, 'store_id': uuid.uuid4().hex, 'max_store_bytes': max_store_bytes, 'max_generations': max_generations})
    root = outside_skill(root)
    if root.exists():
        raise ValueError('Store destination must be new')
    root.parent.mkdir(parents=True, exist_ok=True); root.mkdir(mode=0o700)
    fd = os.open(root / DB_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    with store_lock(root):
        conn = raw_connection(root / DB_NAME)
        try:
            configure(conn, p)
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('PRAGMA application_id=' + str(APP_ID)); conn.execute('PRAGMA user_version=1')
            for statement in SCHEMA.values(): conn.execute(statement)
            conn.execute('INSERT INTO policy VALUES(1,?,?)', (canonical(p).decode(), digest(canonical(p))))
            conn.execute('COMMIT')
        finally: conn.close()
    fsync_directory(root); fsync_directory(root.parent)
    return {'state': 'initialized', 'policy': p, 'durability': 'process_crash_testable_storage_flush_dependent'}


def snapshot_packet(conn, identity):
    identifier(identity)
    row = conn.execute('SELECT length(CAST(metadata AS BLOB)),typeof(metadata),length(CAST(fingerprint AS BLOB)),typeof(fingerprint) FROM snapshots WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise ValueError('Checkpoint not found')
    if row[0] > MAX_META or row[1] != 'text' or row[2] != 64 or row[3] != 'text':
        raise ValueError('Invalid bounded checkpoint metadata')
    meta_text, fingerprint = conn.execute('SELECT metadata,fingerprint FROM snapshots WHERE id=?', (identity,)).fetchone()
    meta = decode(meta_text)
    if not isinstance(meta, dict) or 'files' not in meta:
        raise ValueError('Invalid checkpoint metadata')
    count = conn.execute('SELECT count(*) FROM files WHERE checkpoint_id=?', (identity,)).fetchone()[0]
    if not 1 <= count <= 32:
        raise ValueError('Invalid checkpoint file count')
    invalid = conn.execute("SELECT count(*) FROM files WHERE checkpoint_id=? AND NOT (typeof(path)='text' AND length(CAST(path AS BLOB))<=2048 AND typeof(size)='integer' AND size BETWEEN 0 AND 8388608 AND typeof(sha256)='text' AND length(CAST(sha256 AS BLOB))=64 AND typeof(data)='blob' AND length(data)=size)", (identity,)).fetchone()[0]
    if invalid:
        raise ValueError('Invalid bounded stored file fields')
    file_rows = conn.execute('SELECT path,size,sha256,length(data),typeof(data) FROM files WHERE checkpoint_id=? ORDER BY path', (identity,)).fetchall()
    if not 1 <= len(file_rows) <= 32 or any(type(r[1]) is not int or not 0 <= r[1] <= MAX_FILE or r[1] != r[3] or r[4] != 'blob' for r in file_rows) or sum(r[1] for r in file_rows) > MAX_TOTAL:
        raise ValueError('Invalid bounded stored file inventory')
    files = []
    for name, size, checksum, _, _ in file_rows:
        relative(name); sha(checksum)
        raw = conn.execute('SELECT data FROM files WHERE checkpoint_id=? AND path=?', (identity, name)).fetchone()[0]
        files.append({'path': name, 'size': size, 'sha256': checksum, 'data_base64': base64.b64encode(raw).decode('ascii')})
    if meta.get('checkpoint_id') != identity or meta['files'] != [{k: v for k, v in f.items() if k != 'data_base64'} for f in files]:
        raise ValueError('Stored inventory differs from checkpoint declaration')
    packet = {**meta, 'files': files}
    actual_meta, _, actual_fingerprint = validate_packet(packet)
    if fingerprint != actual_fingerprint or canonical(actual_meta).decode() != meta_text:
        raise ValueError('Stored checkpoint metadata fingerprint mismatch')
    return packet


def summary(packet):
    return {**packet, 'files': [{k: v for k, v in f.items() if k != 'data_base64'} for f in packet['files']], 'execution_clearance': 'not_granted'}


def save_packet(root, packet, allow_save=False):
    if not allow_save:
        raise ValueError('Explicit --allow-save required')
    meta, decoded, fingerprint = validate_packet(packet)
    with store_lock(root) as root:
        conn, p = connect_store(root)
        try:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT 1 FROM snapshots WHERE id=?', (packet['checkpoint_id'],)).fetchone()
            if old is not None:
                existing = snapshot_packet(conn, packet['checkpoint_id'])
                existing_meta, _, existing_fingerprint = validate_packet(existing)
                if existing_fingerprint != fingerprint:
                    raise ValueError('Checkpoint ID already has different contents/provenance')
                conn.execute('ROLLBACK')
                return {'state': 'already_saved', **summary(existing)}
            if conn.execute('SELECT count(*) FROM snapshots').fetchone()[0] >= p['max_generations']:
                raise ValueError('Generation cap reached; explicit deletion required, no automatic pruning')
            conn.execute('INSERT INTO snapshots VALUES(?,?,?,?)', (packet['checkpoint_id'], canonical(meta).decode(), fingerprint, time.time()))
            expected = {x['path']: x for x in meta['files']}
            for name, raw in decoded:
                x = expected[name]
                conn.execute('INSERT INTO files VALUES(?,?,?,?,?)', (packet['checkpoint_id'], name, x['size'], x['sha256'], sqlite3.Binary(raw)))
            conn.execute('COMMIT')
            return {'state': 'saved', **summary({**meta, 'files': packet['files']})}
        except Exception:
            if conn.in_transaction: conn.execute('ROLLBACK')
            raise
        finally: conn.close()


def verify_store(root, checkpoint_id=None):
    with store_lock(root) as root:
        conn, p = connect_store(root)
        try:
            if conn.execute('PRAGMA integrity_check(1)').fetchone() != ('ok',):
                raise ValueError('SQLite integrity check failed')
            count = conn.execute('SELECT count(*) FROM snapshots').fetchone()[0]
            if count > p['max_generations']:
                raise ValueError('Stored generation count exceeds cap')
            if conn.execute("SELECT count(*) FROM snapshots WHERE typeof(id)!='text' OR length(CAST(id AS BLOB))!=32").fetchone() != (0,):
                raise ValueError('Invalid bounded checkpoint IDs')
            ids = [x[0] for x in conn.execute('SELECT id FROM snapshots ORDER BY id').fetchall()]
            if checkpoint_id is not None:
                identifier(checkpoint_id)
                if checkpoint_id not in ids: raise ValueError('Checkpoint not found')
                ids = [checkpoint_id]
            summaries = [summary(snapshot_packet(conn, identity)) for identity in ids]
            if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Orphan checkpoint file record')
            return {'state': 'verified', 'policy': p, 'checkpoints': summaries,
                    'sqlite_version': sqlite3.sqlite_version, 'max_page_count': conn.execute('PRAGMA max_page_count').fetchone()[0],
                    'durability': 'process_crash_testable_storage_flush_dependent'}
        finally: conn.close()


def list_store(root):
    return verify_store(root)


def rename_new(source, destination):
    if os.name == 'nt':
        os.rename(source, destination); return
    libc = ctypes.CDLL(None, use_errno=True); a, b = os.fsencode(source), os.fsencode(destination)
    if sys.platform == 'linux' and hasattr(libc, 'renameat2'):
        call = libc.renameat2; call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = call(-100, a, -100, b, 1)
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        call = libc.renamex_np; call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = call(a, b, 4)
    else: raise ValueError('Atomic no-replace publication unavailable')
    if result:
        number = ctypes.get_errno(); raise OSError(number, os.strerror(number), str(destination))


def write_new(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def restore(root, checkpoint_id, destination, allow_restore=False):
    if not allow_restore: raise ValueError('Explicit --allow-restore required')
    destination = outside_skill(destination)
    source = no_symlinks(root)
    if destination.exists() or destination == source or source in destination.parents or destination in source.parents:
        raise ValueError('New restore destination separate from store required')
    with store_lock(source):
        conn, _ = connect_store(source)
        try: packet = snapshot_packet(conn, checkpoint_id)
        finally: conn.close()
    _, decoded, _ = validate_packet(packet)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.checkpoint-restore-', dir=destination.parent))
    try:
        for name, raw in decoded:
            target = stage / name; target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, raw)
        receipt = summary(packet); write_new(stage / '.checkpoint.json', canonical(receipt) + b'\n')
        for folder in sorted([p for p in stage.rglob('*') if p.is_dir()], key=lambda p: len(p.parts), reverse=True): fsync_directory(folder)
        fsync_directory(stage); rename_new(stage, destination); fsync_directory(destination.parent)
        return {'state': 'restored', 'destination': str(destination), **receipt}
    finally:
        if stage.exists(): shutil.rmtree(stage)


def backup(root, destination, allow_copy=False):
    if not allow_copy: raise ValueError('Explicit --allow-copy required')
    destination = outside_skill(destination); source = no_symlinks(root)
    if destination.exists() or destination == source or source in destination.parents or destination in source.parents:
        raise ValueError('New backup destination separate from store required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.checkpoint-backup-', dir=destination.parent))
    try:
        fd = os.open(stage / DB_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
        with store_lock(source):
            conn, p = connect_store(source)
            target = raw_connection(stage / DB_NAME)
            try:
                configure(target, p); conn.backup(target); configure(target, p)
            finally: target.close(); conn.close()
        result = verify_store(stage)
        fsync_directory(stage); rename_new(stage, destination); fsync_directory(destination.parent)
        return {'state': 'backed_up', 'destination': str(destination), 'policy': result['policy'], 'checkpoints': len(result['checkpoints'])}
    finally:
        if stage.exists(): shutil.rmtree(stage)


def delete(root, checkpoint_id, allow_delete=False):
    if not allow_delete: raise ValueError('Explicit --allow-delete required')
    identifier(checkpoint_id)
    with store_lock(root) as root:
        conn, _ = connect_store(root)
        try:
            conn.execute('BEGIN IMMEDIATE')
            snapshot_packet(conn, checkpoint_id)
            conn.execute('DELETE FROM snapshots WHERE id=?', (checkpoint_id,)); conn.execute('COMMIT')
            return {'state': 'deleted', 'checkpoint_id': checkpoint_id, 'physical_erasure': 'not_guaranteed'}
        except Exception:
            if conn.in_transaction: conn.execute('ROLLBACK')
            raise
        finally: conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ('init', 'save', 'list', 'verify', 'restore', 'backup', 'delete'):
        cmd = sub.add_parser(name); cmd.add_argument('--store', required=True); cmd.add_argument('--report', required=True)
        if name == 'init':
            cmd.add_argument('--max-store-bytes', type=int, required=True); cmd.add_argument('--max-generations', type=int, required=True)
        if name == 'save': cmd.add_argument('--manifest', required=True); cmd.add_argument('--allow-save', action='store_true')
        if name in ('verify', 'restore', 'delete'): cmd.add_argument('--checkpoint-id', required=name != 'verify')
        if name in ('restore', 'backup'): cmd.add_argument('--destination', required=True)
        if name == 'restore': cmd.add_argument('--allow-restore', action='store_true')
        if name == 'backup': cmd.add_argument('--allow-copy', action='store_true')
        if name == 'delete': cmd.add_argument('--allow-delete', action='store_true')
    args = parser.parse_args(argv); report = None
    try:
        report = no_symlinks(args.report)
        if report.exists(): raise ValueError('Report destination must be new')
        if args.operation == 'init': result = init_store(args.store, args.max_store_bytes, args.max_generations)
        elif args.operation == 'save': result = save_packet(args.store, local_packet(args.manifest), args.allow_save)
        elif args.operation == 'list': result = list_store(args.store)
        elif args.operation == 'verify': result = verify_store(args.store, args.checkpoint_id)
        elif args.operation == 'restore': result = restore(args.store, args.checkpoint_id, args.destination, args.allow_restore)
        elif args.operation == 'backup': result = backup(args.store, args.destination, args.allow_copy)
        else: result = delete(args.store, args.checkpoint_id, args.allow_delete)
        write_new(report, canonical({'schema_version': 1, 'ok': True, **result}) + b'\n'); return 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        result = {'schema_version': 1, 'ok': False, 'state': 'failed', 'error': str(exc)[:1500], 'execution_clearance': 'not_granted'}
        try:
            if report is not None and not report.exists():
                no_symlinks(report); write_new(report, canonical(result) + b'\n')
        except (OSError, ValueError): pass
        print(json.dumps(result), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
