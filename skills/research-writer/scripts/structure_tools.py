#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional, local-only explicitly versioned Boltz adapter; this is a trusted-code runner, not a sandbox."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shlex
import signal
import stat
import subprocess
import sys
import threading
import time

SCHEMA = 'research-writer.structure.v1'
SCHEMA_V2 = 'research-writer.structure.v2'
SCHEMA_V3 = 'research-writer.structure.v3'
MODEL2_REVISION = '6fdef46d763fee7fbb83ca5501ccceff43b85607'
ASSETS2 = {
    'boltz2_conf.ckpt': (2286561469, '090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1'),
    'mols.tar': (1855662080, '39e076d96dbec6b4e86982bbda16f3a53a2a60c9bdc17828d88f6f9a0c7d1fd7'),
}
CANONICAL_MOLS = tuple('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL UNK'.split())
REVISION = 'b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc'
MODEL_REVISION = '7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1'
ASSETS = {
    'boltz1_conf.ckpt': 'fea245d912c570ec117b2277c2719f312a6fc109c07b6f6ef741690ee775c2f5',
    'ccd.pkl': '2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4',
}
AA3 = dict(zip('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split(),
               'ARNDCQEGHILKMFPSTWYV'))
BACKBONE = {'N', 'CA', 'C', 'O'}
# Canonical heavy-atom names from pinned Boltz const.ref_atoms (MIT).
HEAVY_ATOMS = {'ALA': ['N', 'CA', 'C', 'O', 'CB'], 'ARG': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD', 'NE', 'CZ', 'NH1', 'NH2'], 'ASN': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'OD1', 'ND2'], 'ASP': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'OD1', 'OD2'], 'CYS': ['N', 'CA', 'C', 'O', 'CB', 'SG'], 'GLN': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD', 'OE1', 'NE2'], 'GLU': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD', 'OE1', 'OE2'], 'GLY': ['N', 'CA', 'C', 'O'], 'HIS': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'ND1', 'CD2', 'CE1', 'NE2'], 'ILE': ['N', 'CA', 'C', 'O', 'CB', 'CG1', 'CG2', 'CD1'], 'LEU': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD1', 'CD2'], 'LYS': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD', 'CE', 'NZ'], 'MET': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'SD', 'CE'], 'PHE': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD1', 'CD2', 'CE1', 'CE2', 'CZ'], 'PRO': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD'], 'SER': ['N', 'CA', 'C', 'O', 'CB', 'OG'], 'THR': ['N', 'CA', 'C', 'O', 'CB', 'OG1', 'CG2'], 'TRP': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD1', 'CD2', 'NE1', 'CE2', 'CE3', 'CZ2', 'CZ3', 'CH2'], 'TYR': ['N', 'CA', 'C', 'O', 'CB', 'CG', 'CD1', 'CD2', 'CE1', 'CE2', 'CZ', 'OH'], 'VAL': ['N', 'CA', 'C', 'O', 'CB', 'CG1', 'CG2']}
REQUIRED = {'schema', 'python', 'boltz_source', 'assets_dir', 'output_dir', 'sequence',
            'chain_id', 'device', 'seed', 'threads', 'timeout_seconds', 'recycling_steps',
            'sampling_steps', 'max_output_bytes', 'max_log_bytes', 'memory_budget_bytes'}
MAX_INPUT = 65536
MAX_STRUCTURE = 8 * 1024 * 1024
MAX_MSA = 1024 * 1024
MAX_MSA_SEQUENCES = 1024


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def regular(path, maximum=None):
    p = Path(path)
    if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode):
        raise ValueError('Require a regular nonsymlink file: ' + p.name)
    if maximum is not None and p.stat().st_size > maximum:
        raise ValueError('File exceeds byte limit: ' + p.name)
    return p


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode_json(raw):
    def bad(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=bad)


def read_json(path, maximum=MAX_INPUT):
    return decode_json(regular(path, maximum).read_text(encoding='utf-8'))


def atomic_json(path, value):
    target = Path(path)
    payload = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    if len(payload) > 1024 * 1024:
        raise ValueError('Report exceeds 1 MiB')
    temp = target.with_name(target.name + '.tmp')
    with temp.open('xb') as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, target)


def absolute(value, label):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(label + ' must be an explicit absolute path')
    return Path(value).resolve()


def validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError('Structure request must be an object')
    expected = REQUIRED if spec.get('schema') == SCHEMA else REQUIRED | {'msa'}
    if spec.get('schema') == SCHEMA_V3:
        expected |= {'model'}
    if spec.get('schema') not in (SCHEMA, SCHEMA_V2, SCHEMA_V3) or set(spec) != expected:
        raise ValueError('Require exact structure.v1, structure.v2 or structure.v3 fields')
    if spec.get('schema') == SCHEMA_V3 and spec['model'] != 'boltz2':
        raise ValueError('structure.v3 requires explicit model boltz2')
    sequence = spec['sequence']
    if (not isinstance(sequence, str) or not 4 <= len(sequence) <= 128 or
            set(sequence) - set(AA3.values()) or spec['chain_id'] != 'A'):
        raise ValueError('Require one chain A of 4–128 uppercase canonical amino acids')
    if spec['device'] != 'cpu':
        raise ValueError('This contract supports CPU only; GPU/MPS real execution remains pending')
    limits = {'seed': (0, 2147483647), 'threads': (1, 8), 'timeout_seconds': (1, 3600),
              'recycling_steps': (1, 3), 'sampling_steps': (1, 200),
              'max_output_bytes': (1024 * 1024, 256 * 1024 * 1024),
              'max_log_bytes': (1024, 4 * 1024 * 1024),
              'memory_budget_bytes': (1024 ** 3, 10 * 1024 ** 3)}
    for name, (lo, hi) in limits.items():
        if type(spec[name]) is not int or not lo <= spec[name] <= hi:
            raise ValueError(name + ' is outside its integer bound')
    if spec.get('schema') == SCHEMA_V3:
        for name in ('boltz_source', 'assets_dir', 'output_dir'):
            no_alias_path(spec[name], allow_missing=name == 'output_dir')
        for name, maximum in {'threads': 2, 'memory_budget_bytes': 8*1024**3,
                              'max_output_bytes': 64*1024**2, 'max_log_bytes': 1024**2}.items():
            if spec[name] > maximum:
                raise ValueError('structure.v3 exceeds fixed bound: ' + name)
    paths = {name: absolute(spec[name], name) for name in
             ('python', 'boltz_source', 'assets_dir', 'output_dir')}
    # Preserve a venv launcher path: resolving its symlink before execution would
    # silently select the base interpreter and lose the chosen environment.
    paths['python'] = Path(spec['python'])
    for name in ('boltz_source', 'assets_dir'):
        if not paths[name].is_dir():
            raise ValueError(name + ' must be an existing directory')
        if paths['output_dir'].is_relative_to(paths[name]) or paths[name].is_relative_to(paths['output_dir']):
            raise ValueError('Output must not overlap source or assets')
    regular(paths['python'].resolve())
    if not os.access(paths['python'], os.X_OK):
        raise ValueError('Selected Python is not executable')
    msa_bytes(spec)
    return paths


def msa_bytes(spec):
    """Validate an explicitly supplied alignment; this does not establish homology."""
    msa = {'mode': 'empty'} if spec.get('schema') == SCHEMA else spec.get('msa')
    if not isinstance(msa, dict):
        raise ValueError('structure.v2 requires an explicit msa object')
    if msa == {'mode': 'empty'}:
        return None, {'mode': 'empty'}
    if set(msa) != {'mode', 'path', 'sha256'} or msa.get('mode') != 'local_a3m':
        raise ValueError('MSA must be empty or a checksummed local_a3m')
    expected = msa['sha256']
    if not isinstance(expected, str) or len(expected) != 64 or set(expected) - set('0123456789abcdef'):
        raise ValueError('MSA requires a lowercase SHA-256')
    source = Path(msa['path']) if isinstance(msa['path'], str) else None
    if source is None or not source.is_absolute() or source.suffix.lower() != '.a3m':
        raise ValueError('MSA requires an absolute .a3m file path')
    for component in (source, *source.parents):
        info = component.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise ValueError('MSA input and ancestors must not be symlinks or reparse points')
    regular(source, MAX_MSA)
    source = source.resolve()
    output = absolute(spec['output_dir'], 'output_dir')
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Output must not overlap the MSA input')
    with source.open('rb') as stream:
        raw = stream.read(MAX_MSA + 1)
    if len(raw) > MAX_MSA or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('MSA exceeds its bound or checksum changed')
    try:
        text = raw.decode('ascii')
    except UnicodeError as exc:
        raise ValueError('MSA must use ASCII A3M text') from exc
    rows, parts = [], None
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith('>'):
            if not line[1:].strip() or len(line) > 256:
                raise ValueError('MSA header must be nonempty and bounded')
            if parts is not None:
                rows.append(''.join(parts))
            parts = []
            if len(rows) >= MAX_MSA_SEQUENCES:
                raise ValueError('MSA sequence count exceeds bound')
        elif parts is None or set(line) - (set(AA3.values()) | set(''.join(AA3.values()).lower()) | {'-'}):
            raise ValueError('MSA sequence or header is malformed')
        else:
            parts.append(line)
    if parts is not None:
        rows.append(''.join(parts))
    if not rows or rows[0] != spec['sequence']:
        raise ValueError('First MSA sequence must exactly match the requested query')
    for row in rows:
        aligned = ''.join(c for c in row if not c.islower())
        if len(row) > 8192 or len(aligned) != len(spec['sequence']):
            raise ValueError('MSA alignment width or insertion bound differs')
    return raw, {'mode': 'local_a3m', 'sha256': expected, 'bytes': len(raw),
                 'sequences': len(rows), 'alignment_columns': len(spec['sequence']),
                 'quality': 'format checked; homology and accuracy not established'}


def staged_msa(spec, root):
    raw, evidence = msa_bytes(spec)
    if raw is not None:
        path = regular(Path(root) / 'input.a3m', MAX_MSA)
        with path.open('rb') as stream:
            staged = stream.read(MAX_MSA + 1)
        if staged != raw:
            raise ValueError('Staged MSA differs from the pinned original input')
    return evidence


def sequence_input(spec, root):
    use_local = spec.get('schema') in (SCHEMA_V2, SCHEMA_V3) and spec['msa'].get('mode') == 'local_a3m'
    return {'version': 1, 'sequences': [{'protein': {
        'id': 'A', 'sequence': spec['sequence'],
        'msa': str(Path(root) / 'input.a3m') if use_local else 'empty'}}]}


def git(source, *args):
    completed = subprocess.run(['git', '-C', str(source), *args], capture_output=True, timeout=15)
    if completed.returncode or len(completed.stdout) > 2 * 1024 * 1024:
        raise ValueError('Cannot verify pinned Boltz source checkout')
    return completed.stdout


def verify_source(source):
    """Bind the source tree to a known git commit; reject ignored injected modules too."""
    source = Path(source).resolve()
    if git(source, 'rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('Boltz checkout is not the pinned source revision')
    rows = git(source, 'ls-tree', '-r', '--full-tree', '-z', 'HEAD', '--', 'src/boltz', 'pyproject.toml')
    expected, hashes = set(), {}
    for row in rows.split(b'\0'):
        if not row:
            continue
        head, relative = row.split(b'\t', 1)
        mode, kind, oid = head.decode().split()
        rel = relative.decode(); p = source / rel
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Source contains unsupported git object')
        regular(p, 8 * 1024 * 1024)
        if any(parent.is_symlink() for parent in p.parents if parent != source and parent.is_relative_to(source)):
            raise ValueError('Source directory symlink refused')
        data = p.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != oid:
            raise ValueError('Pinned source content mismatch: ' + rel)
        expected.add(rel); hashes[rel] = hashlib.sha256(data).hexdigest()
    if 'src/boltz/main.py' not in expected or 'pyproject.toml' not in expected:
        raise ValueError('Incomplete pinned source tree')
    actual = {str(p.relative_to(source)) for p in (source / 'src/boltz').rglob('*') if p.is_file() or p.is_symlink()}
    if actual != expected - {'pyproject.toml'}:
        raise ValueError('Untracked/ignored source files or cached bytecode refused')
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {'revision': REVISION, 'file_count': len(hashes), 'tree_sha256': fingerprint,
            'main_sha256': hashes['src/boltz/main.py']}


def verify_assets(directory):
    root = Path(directory).resolve()
    if {p.name for p in root.iterdir()} != set(ASSETS):
        raise ValueError('Assets directory must contain exactly boltz1_conf.ckpt and ccd.pkl')
    result = {}
    total = 0
    for name, expected in ASSETS.items():
        p = regular(root / name, 4 * 1024 ** 3)
        size = p.stat().st_size; total += size
        if size <= 0 or digest(p) != expected:
            raise ValueError('Pinned asset hash mismatch: ' + name)
        result[name] = {'sha256': expected, 'bytes': size}
    if total > 5 * 1024 ** 3:
        raise ValueError('Asset total exceeds fixed 5 GiB budget')
    return result


def selected_model(spec):
    return 'boltz2' if spec.get('schema') == SCHEMA_V3 else 'boltz1'


def no_alias_path(value, allow_missing=False):
    p = Path(value)
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError('Require absolute nontraversing resource path')
    for entry in (p, *p.parents):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            if allow_missing and entry == p:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('Resource path or ancestor is an alias')
    return p


def scan_mols_archive(path, expected_sha, retain=False):
    """Bounded raw tar reader: no tarfile extension parser or deserialization.

    All bytes, including extensions and trailing padding, participate in the hash.
    Only canonical member bytes can be retained (<=64 MiB aggregate).
    """
    canonical = {f'mols/{name}.pkl' for name in CANONICAL_MOLS}
    inventory, contents, seen, path_types, parents_seen = {}, {}, set(), {}, set()
    if regular(path).stat().st_size % 512:
        raise ValueError('Tar length must contain complete 512-byte blocks')
    total = selected = entries = extensions = 0
    pending = {}; global_pax = {}
    hasher = hashlib.sha256()
    def octal(raw):
        if raw and raw[0] & 128:
            raise ValueError('Base-256 tar numbers unsupported')
        value = raw.rstrip(b'\0 ').lstrip(b' ')
        if not value or set(value) - set(b'01234567'):
            raise ValueError('Malformed tar numeric field')
        return int(value, 8)
    def text_field(raw):
        value, _, rest = raw.partition(b'\0')
        if rest.strip(b'\0'):
            raise ValueError('Hidden content after tar string terminator')
        return value.decode('utf-8', errors='strict')
    def pax(raw):
        result = {}; at = 0
        while at < len(raw):
            space = raw.find(b' ', at, at + 12)
            digits = raw[at:space] if space >= 0 else b''
            if not digits.isdigit() or len(digits) > 8:
                raise ValueError('Malformed PAX record length')
            length = int(digits); end = at + length
            if length <= space-at+2 or end > len(raw) or raw[end-1:end] != b'\n':
                raise ValueError('Truncated PAX record')
            key, sep, value = raw[space+1:end-1].partition(b'=')
            key = key.decode('ascii'); value = value.decode('utf-8')
            if not sep or key in result or key not in {'path','size','mtime','atime','ctime','uid','gid','uname','gname'} or '\0' in value:
                raise ValueError('Unsupported or duplicate PAX attribute')
            result[key] = value; at = end
        return result
    with regular(path).open('rb') as stream:
        def read_exact(count):
            data = stream.read(count); hasher.update(data)
            if len(data) != count:
                raise ValueError('Truncated tar archive')
            return data
        while True:
            header = read_exact(512)
            if header == bytes(512):
                if pending or read_exact(512) != bytes(512):
                    raise ValueError('Malformed tar end markers')
                trailing = 0
                while True:
                    block = stream.read(65536); hasher.update(block)
                    if not block: break
                    trailing += len(block)
                    if trailing > 1024*1024 or any(block):
                        raise ValueError('Nonpadding or excessive trailing tar content')
                break
            entries += 1
            if entries > 100000:
                raise ValueError('Tar header count exceeds bound')
            if octal(header[148:156]) != sum(header[:148]) + 8*32 + sum(header[156:]):
                raise ValueError('Tar header checksum mismatch')
            if header[257:263] not in (b'ustar\0', b'ustar '):
                raise ValueError('Require explicit USTAR/GNU tar header')
            size = octal(header[124:136]); kind = header[156:157]
            name = text_field(header[:100]); prefix = text_field(header[345:500])
            if prefix:
                if header[257:263] != b'ustar\0':
                    raise ValueError('Unsupported GNU header extension fields')
                name = prefix + '/' + name
            if kind in (b'x', b'g'):
                extensions += size
                if size > 16384 or extensions > 1024*1024:
                    raise ValueError('Tar metadata extension exceeds bound')
                values = pax(read_exact(size))
                if any(read_exact((-size) % 512)):
                    raise ValueError('Nonzero tar extension padding')
                if kind == b'g':
                    if {'path','size'} & set(values):
                        raise ValueError('Global PAX path/size refused')
                    global_pax.update(values)
                else:
                    if pending:
                        raise ValueError('Stacked per-file PAX extensions refused')
                    pending = values
                continue
            if kind not in (b'0', b'\0', b'5'):
                raise ValueError('Tar links/devices/unsupported extensions refused')
            attributes = {**global_pax, **pending}; pending = {}
            name = attributes.get('path', name)
            if 'size' in attributes:
                value = attributes['size']
                if not value.isascii() or not value.isdigit() or len(value) > 12:
                    raise ValueError('Invalid PAX size')
                size = int(value)
            name = name[:-1] if kind == b'5' and name.endswith('/') else name
            components = name.split('/')
            if (not name or not name.isascii() or len(name) > 4096 or '\\' in name or ':' in name or
                    any(c in ('', '.', '..') for c in components) or components[0] != 'mols' or
                    any(ord(c) < 32 for c in name)):
                raise ValueError('Unsafe tar member path')
            alias = name.casefold()
            if alias in seen:
                raise ValueError('Duplicate or case-aliased tar path')
            ancestors = ['/'.join(components[:i]).casefold() for i in range(1, len(components))]
            if any(a in path_types and path_types[a] != b'5' for a in ancestors) or (kind != b'5' and alias in parents_seen):
                raise ValueError('Conflicting file/directory tar path')
            seen.add(alias)
            path_types[alias] = kind
            parents_seen.update(ancestors)
            if kind == b'5' and size:
                raise ValueError('Directory tar payload refused')
            if kind != b'5':
                total += size
                if total > 3*1024**3:
                    raise ValueError('Tar declared payload exceeds bound')
            wanted = name in canonical and kind != b'5'
            if wanted:
                selected += size
                if not 0 < size <= 4*1024**2 or selected > 64*1024**2:
                    raise ValueError('Canonical molecule payload exceeds bound')
            member = hashlib.sha256(); chunks = []
            remaining = size
            while remaining:
                chunk = read_exact(min(65536, remaining)); remaining -= len(chunk)
                if wanted:
                    member.update(chunk)
                    if retain: chunks.append(chunk)
            if any(read_exact((-size) % 512)):
                raise ValueError('Nonzero tar member padding')
            if wanted:
                inventory[name] = {'bytes': size, 'sha256': member.hexdigest()}
                if retain: contents[name] = b''.join(chunks)
    if hasher.hexdigest() != expected_sha:
        raise ValueError('Scanned tar differs from publisher pin')
    if set(inventory) != canonical:
        raise ValueError('Tar must contain exactly all 21 canonical molecule members')
    return {'archive_sha256': expected_sha, 'members': inventory,
            'header_count': entries, 'declared_payload_bytes': total,
            'canonical_payload_bytes': selected}, contents


def verify_boltz2_raw(directory):
    root = no_alias_path(directory)
    result = {}
    for name, (size, expected) in ASSETS2.items():
        path = regular(root/name, size)
        if path.stat().st_nlink != 1 or path.stat().st_size != size or digest(path) != expected:
            raise ValueError('Pinned model-2 asset mismatch: ' + name)
        result[name] = {'bytes': size, 'sha256': expected}
    return root, result


def prepare_boltz2_assets(directory):
    """Explicit offline preparation; never downloads or deserializes model data."""
    root = no_alias_path(directory)
    if {p.name for p in root.iterdir()} != set(ASSETS2):
        raise ValueError('Preparation requires fresh two-file model-2 asset directory')
    root, assets = verify_boltz2_raw(root)
    inventory, contents = scan_mols_archive(root/'mols.tar', ASSETS2['mols.tar'][1], retain=True)
    target = root/'mols'; target.mkdir(mode=0o700)
    for name, raw in contents.items():
        path = target/Path(name).name
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    receipt = {'schema': 'research-writer.boltz2-assets.v1', 'model_revision': MODEL2_REVISION,
               'assets': assets, 'inventory': inventory}
    atomic_json(root/'boltz2-assets.json', receipt)
    return {'status': 'prepared_assets', 'actual_runtime_verified': False,
            'assets': verify_boltz2_assets(root)}


def verify_boltz2_assets(directory):
    root, assets = verify_boltz2_raw(directory)
    if {p.name for p in root.iterdir()} != set(ASSETS2) | {'mols', 'boltz2-assets.json'}:
        raise ValueError('Unexpected model-2 asset-root entry')
    # A mutable receipt is never the authority: rederive from pinned archive bytes.
    inventory, _ = scan_mols_archive(root/'mols.tar', ASSETS2['mols.tar'][1])
    expected = {'schema': 'research-writer.boltz2-assets.v1', 'model_revision': MODEL2_REVISION,
                'assets': assets, 'inventory': inventory}
    if read_json(root/'boltz2-assets.json') != expected:
        raise ValueError('Molecule receipt differs from publisher-derived inventory')
    moldir = no_alias_path(root/'mols')
    if not moldir.is_dir() or {p.name for p in moldir.iterdir()} != {n+'.pkl' for n in CANONICAL_MOLS}:
        raise ValueError('Canonical molecule directory membership differs')
    for name, evidence in inventory['members'].items():
        path = regular(root/name, 4*1024**2)
        if path.stat().st_nlink != 1 or path.stat().st_size != evidence['bytes'] or digest(path) != evidence['sha256']:
            raise ValueError('Canonical molecule bytes differ from pinned tar: ' + name)
    return expected


def verify_for_spec(spec, directory):
    return verify_boltz2_assets(directory) if selected_model(spec) == 'boltz2' else verify_assets(directory)


def no_recursive_fallback(original):
    active = set()
    def guarded(self, index):
        identity = id(self)
        if identity in active:
            cause = sys.exc_info()[1]
            raise RuntimeError('Model-2 dataset fallback refused; original error: ' + repr(cause)) from cause
        active.add(identity)
        try:
            return original(self, index)
        finally:
            active.remove(identity)
    return guarded


def validate_heavy_atoms(path, sequence):
    reverse = {v:k for k,v in AA3.items()}
    expected = {(i, reverse[aa], name, name[0]) for i, aa in enumerate(sequence, 1)
                for name in HEAVY_ATOMS[reverse[aa]]}
    actual = []
    for line in regular(path, MAX_STRUCTURE).read_text().splitlines():
        if line.startswith('ATOM  '):
            actual.append((int(line[22:26]), line[17:20].strip(), line[12:16].strip(), line[76:78].strip()))
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Model-2 typed heavy-atom inventory differs from pinned canonical residues')
    return {'atoms': len(actual), 'CA_count': len(sequence),
            'typed_inventory_sha256': hashlib.sha256(json.dumps(sorted(expected)).encode()).hexdigest()}


def install_model2_guards(main, model_class, boltz1_class, paths, spec, observed):
    """Bind the real checkpoint/class/settings, and refuse the affinity route."""
    load = model_class.load_from_checkpoint
    observed['checkpoint_loads'] = 0
    def guarded_load(cls, checkpoint, *args, **kwargs):
        expected = paths['assets_dir']/'boltz2_conf.ckpt'
        if (Path(checkpoint) != expected or observed['checkpoint_loads'] or args or
                kwargs.get('strict') is not True or kwargs.get('map_location') != 'cpu'):
            raise RuntimeError('Unexpected model-2 checkpoint load')
        if kwargs.get('msa_args', {}).get('use_paired_feature') is not True or kwargs.get('pairformer_args', {}).get('num_blocks') != 64 or kwargs.get('diffusion_process_args', {}).get('step_scale') != 1.5:
            raise RuntimeError('Model-2 official route settings differ')
        observed.update(checkpoint_loads=1, checkpoint_sha256=ASSETS2['boltz2_conf.ckpt'][1],
                        checkpoint_path=str(expected), predict_args=kwargs['predict_args'],
                        diffusion_process_args=kwargs['diffusion_process_args'],
                        pairformer_args=kwargs['pairformer_args'], msa_args=kwargs['msa_args'])
        # Explicitly constrain construction, not only a later affinity forward.
        kwargs.update(affinity_prediction=False, affinity_ensemble=False)
        return load(checkpoint, **kwargs)
    model_class.load_from_checkpoint = classmethod(guarded_load)
    def forbidden(*args, **kwargs):
        raise RuntimeError('Nonselected model/affinity route refused')
    boltz1_class.load_from_checkpoint = classmethod(forbidden)
    original_process = main.process_inputs
    def process(*args, **kwargs):
        if kwargs.get('boltz2') is not True or kwargs.get('use_msa_server'):
            raise RuntimeError('Model-2 offline preprocessing contract differs')
        result = original_process(*args, **kwargs)
        manifest = read_json(kwargs['out_dir']/'processed/manifest.json')
        records = manifest.get('records', [])
        if len(records) != 1 or records[0].get('affinity'):
            raise RuntimeError('Require one structure-only manifest record')
        for record in records:
            chains = record.get('chains', [])
            if (record.get('id') != 'input' or len(chains) != 1 or chains[0].get('chain_id') != 0 or
                    chains[0].get('chain_name') != 'A' or chains[0].get('mol_type') != 0 or
                    chains[0].get('num_residues') != len(spec['sequence']) or record.get('md')):
                raise RuntimeError('Model-2 processed chain/record differs')
            options = record.get('inference_options')
            if options and any(options.get(k) for k in ('pocket_constraints', 'contact_constraints')):
                raise RuntimeError('Unexpected model-2 conditioning constraints')
            if record.get('templates'):
                raise RuntimeError('Unexpected model-2 template')
        observed['processed_manifest_sha256'] = digest(kwargs['out_dir']/'processed/manifest.json')
        observed['affinity'] = False
        return result
    main.process_inputs = process


def cif_tokens(text):
    """Tokenize the constrained text mmCIF syntax without executing CIF content."""
    multiline = None
    for line in text.splitlines():
        if line.startswith(';'):
            if multiline is None:
                multiline = [line[1:]]
            else:
                yield '\n'.join(multiline); multiline = None
            continue
        if multiline is not None:
            multiline.append(line); continue
        lexer = shlex.shlex(line, posix=True); lexer.whitespace_split = True; lexer.commenters = '#'
        yield from lexer
    if multiline is not None:
        raise ValueError('Unterminated CIF multiline field')


def parse_atoms(path):
    text = regular(path, MAX_STRUCTURE).read_text(encoding='utf-8')
    atoms = []
    if Path(path).suffix.lower() == '.pdb':
        models, ended = 0, False
        for line in text.splitlines():
            if line.startswith('MODEL '):
                models += 1
                if models > 1:
                    raise ValueError('Only one structure model accepted')
            if line.startswith('ENDMDL') or line.strip() == 'END':
                ended = True
            if line.startswith(('ATOM  ', 'HETATM')):
                if ended or line.startswith('HETATM') or len(line) < 54 or line[16:17].strip():
                    raise ValueError('Unsupported/truncated PDB atom record')
                if line[26:27].strip():
                    raise ValueError('Insertion codes unsupported')
                atoms.append((line[21:22], int(line[22:26]), line[17:20].strip(), line[12:16].strip(),
                              tuple(float(line[s:s+8]) for s in (30, 38, 46))))
        if not ended:
            raise ValueError('Truncated PDB: terminal END/ENDMDL required')
    elif Path(path).suffix.lower() in ('.cif', '.mmcif'):
        tokens = list(cif_tokens(text)); i = 0
        while i < len(tokens):
            if tokens[i] != 'loop_':
                i += 1; continue
            i += 1; tags = []
            while i < len(tokens) and tokens[i].startswith('_'):
                tags.append(tokens[i]); i += 1
            values = []
            while i < len(tokens) and not (tokens[i] in ('loop_', 'stop_') or tokens[i].startswith(('_', 'data_', 'save_'))):
                values.append(tokens[i]); i += 1
            if not tags or len(values) % len(tags):
                raise ValueError('Truncated/malformed CIF loop')
            if not any(t.startswith('_atom_site.') for t in tags):
                continue
            if len(set(tags)) != len(tags):
                raise ValueError('Duplicate CIF atom columns')
            required = ['group_PDB', 'label_asym_id', 'label_seq_id', 'label_comp_id',
                        'label_atom_id', 'Cartn_x', 'Cartn_y', 'Cartn_z']
            if any('_atom_site.' + k not in tags for k in required):
                raise ValueError('Missing CIF atom identity/coordinate columns')
            for start in range(0, len(values), len(tags)):
                row = dict(zip(tags, values[start:start+len(tags)]))
                get = lambda key, default='?': row.get('_atom_site.' + key, default)
                if (get('group_PDB') != 'ATOM' or get('label_alt_id') not in ('.', '?') or
                        get('pdbx_PDB_ins_code') not in ('.', '?') or get('pdbx_PDB_model_num', '1') != '1'):
                    raise ValueError('Unsupported CIF hetero/alternate/model atom')
                atoms.append((get('label_asym_id'), int(get('label_seq_id')), get('label_comp_id'),
                              get('label_atom_id'), tuple(float(get(k)) for k in ('Cartn_x', 'Cartn_y', 'Cartn_z'))))
    else:
        raise ValueError('Structure must be PDB or mmCIF')
    return atoms


def validate_structure(path, sequence):
    atoms = parse_atoms(path); residues = {}
    if not atoms:
        raise ValueError('Empty structure')
    for chain, index, name, atom, xyz in atoms:
        if chain != 'A' or not 1 <= index <= len(sequence) or name not in AA3 or AA3[name] != sequence[index-1]:
            raise ValueError('Structure chain/residue identity differs from requested sequence')
        if not atom or not all(math.isfinite(x) and abs(x) <= 1e5 for x in xyz):
            raise ValueError('Invalid or nonfinite coordinates')
        row = residues.setdefault(index, {})
        if atom in row:
            raise ValueError('Duplicate atom identity')
        row[atom] = xyz
    if set(residues) != set(range(1, len(sequence)+1)):
        raise ValueError('Missing residue coverage')
    for row in residues.values():
        if not BACKBONE <= set(row):
            raise ValueError('Missing N/CA/C/O backbone atom')
        for a, b, lo, hi in [('N', 'CA', 1.0, 1.9), ('CA', 'C', 1.0, 1.9), ('C', 'O', 0.9, 1.7)]:
            if not lo <= math.dist(row[a], row[b]) <= hi:
                raise ValueError('Implausible backbone bond geometry')
    for index in range(1, len(sequence)):
        if not 1.0 <= math.dist(residues[index]['C'], residues[index+1]['N']) <= 2.0:
            raise ValueError('Disconnected peptide backbone')
    return {'format': Path(path).suffix.lower(), 'chains': ['A'], 'residues': len(residues),
            'atoms': len(atoms), 'backbone_atoms_per_residue': 4, 'backbone_geometry': 'checked',
            'sha256': digest(path), 'sequence_sha256': hashlib.sha256(sequence.encode()).hexdigest()}


def validate_confidence(path):
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError('Confidence must be an object')
    required = ('confidence_score', 'ptm', 'complex_plddt')
    for name in required:
        if type(value.get(name)) not in (float, int) or not math.isfinite(value[name]) or not 0 <= value[name] <= 1:
            raise ValueError('Missing/out-of-range Boltz confidence: ' + name)
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in ('iptm', 'ligand_iptm', 'protein_iptm', 'complex_iplddt'):
                    if type(child) not in (float, int) or not math.isfinite(child) or not 0 <= child <= 1:
                        raise ValueError('Out-of-range optional confidence')
                walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
        elif type(item) is float and not math.isfinite(item):
            raise ValueError('Nonfinite confidence value')
    walk(value)
    return {'sha256': digest(path), 'fields': {name: value[name] for name in required},
            'meaning': 'Model confidence in [0,1], not measured structural accuracy or biological validity'}


def output_size(root):
    total = 0
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Output symlink refused')
        if p.is_file():
            regular(p); total += p.stat().st_size
        elif not p.is_dir():
            raise ValueError('Nonregular output refused')
    return total


def bounded_process(argv, directory, timeout, max_log, max_output, memory_budget, on_start=None):
    """Captured logs are hard-capped; aggregate output is monitored, not disk isolation."""
    if os.name != 'posix':
        raise ValueError('Process-tree bounds require POSIX; other hosts pending')
    import resource
    import psutil
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output, max_output))
    log_path = directory / 'worker.log'; overflow = threading.Event()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1',
           'NUMBA_CACHE_DIR': str(directory / 'numba-cache'),
           'TRANSFORMERS_OFFLINE': '1', 'WANDB_MODE': 'disabled', 'HF_HUB_DISABLE_TELEMETRY': '1'}
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, preexec_fn=limits, env=env)
    if on_start is not None:
        try: on_start()
        except BaseException:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except PermissionError: proc.kill()
            proc.wait(timeout=5); proc.stdout.close(); raise
    owner = psutil.Process(proc.pid); tracked = {proc.pid: owner}
    def capture():
        written = 0
        with log_path.open('xb') as stream:
            while True:
                raw = proc.stdout.read(65536)
                if not raw: break
                keep = raw[:max(0, max_log-written)]; stream.write(keep); written += len(keep)
                if len(keep) < len(raw): overflow.set()
    thread = threading.Thread(target=capture, daemon=True); thread.start()
    start = time.monotonic(); reason = None; peak_rss = 0; termination_mode='owned_process_group'
    try:
        while True:
            # Status inspection does not reap the child. This also works on
            # Python builds without os.waitid (some macOS distributions).
            if owner.status() == psutil.STATUS_ZOMBIE:
                break
            for child in owner.children(recursive=True): tracked[child.pid] = child
            rss = 0
            for child in list(tracked.values()):
                try:
                    if child.is_running(): rss += child.memory_info().rss
                except psutil.NoSuchProcess: pass
            peak_rss = max(peak_rss, rss)
            if rss > memory_budget: reason = 'memory_limit'; break
            if overflow.is_set(): reason = 'log_limit'; break
            if time.monotonic()-start >= timeout: reason = 'timed_out'; break
            if output_size(directory) > max_output: reason = 'output_limit'; break
            time.sleep(0.05)
    except BaseException:
        reason = 'interrupted'
        raise
    finally:
        # The group is owned by this still-unreaped session leader. Kill descendants
        # even if the leader exited; never reuse a historical PID as kill authority.
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        except PermissionError:
            # Some hosts permit signaling owned PIDs but prohibit killpg.
            # psutil retains creation identity and is_running checks PID reuse.
            termination_mode='tracked_owned_pids'
            for child in reversed(list(tracked.values())):
                try:
                    if child.is_running() and child.status() != psutil.STATUS_ZOMBIE: child.kill()
                except psutil.NoSuchProcess: pass
        proc.wait(timeout=5); thread.join(timeout=5)
        if proc.stdout: proc.stdout.close()
    if thread.is_alive():
        raise RuntimeError('Log capture did not terminate')
    if overflow.is_set(): reason = 'log_limit'
    if output_size(directory) > max_output: reason = 'output_limit'
    return {'returncode': proc.returncode, 'failure_kind': reason,
            'wall_seconds': round(time.monotonic()-start, 3), 'peak_tree_rss_bytes':peak_rss,
            'memory_budget_bytes':memory_budget, 'termination_mode':termination_mode,
            'memory_measurement':'psutil sampled owned process tree; transient peaks may be missed',
            'log_sha256': digest(log_path),
            'log_bytes': log_path.stat().st_size, 'output_bytes': output_size(directory)}


def boltz_argv(request):
    s = request['spec']; root = Path(request['output_dir'])
    return ['predict', str(root/'input.yaml'), '--model', selected_model(s), '--accelerator', 'cpu',
            '--devices', '1', '--cache', request['assets_dir'], '--out_dir', str(root/'engine'),
            '--no_kernels', '--num_workers', '0', '--preprocessing-threads', '1',
            '--recycling_steps', str(s['recycling_steps']), '--sampling_steps', str(s['sampling_steps']),
            '--diffusion_samples', '1', '--seed', str(s['seed']), '--output_format', 'pdb']


def worker(request_path):
    request = read_json(request_path); spec = request['spec']; paths = validate_spec(spec)
    if (set(request) != {'spec', *paths} or
            any(request[name] != str(value) for name, value in paths.items()) or
            Path(request_path).resolve().parent != paths['output_dir']):
        raise ValueError('Internal request paths differ from declared resources')
    expected_input = sequence_input(spec, paths['output_dir'])
    if read_json(paths['output_dir']/'input.yaml') != expected_input:
        raise ValueError('Staged sequence input differs from declared request')
    msa_evidence = staged_msa(spec, paths['output_dir'])
    state = read_json(paths['output_dir']/'report.json')
    # The child may start before the parent has atomically recorded Popen success.
    if (state.get('status') not in ('starting', 'running') or
            state.get('worker_request_sha256') != digest(request_path)):
        raise ValueError('Internal request lacks matching active launch evidence')
    # Guards prevent accidental in-process service or downloader use. They do not
    # turn trusted Python dependencies into an adversarial security sandbox.
    import socket
    def no_network(*args, **kwargs):
        raise RuntimeError('Network disabled by structure adapter')
    socket.socket.connect = no_network; socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    source = Path(request['boltz_source']); source_evidence = verify_source(source)
    asset_evidence = verify_for_spec(spec, request['assets_dir'])
    sys.dont_write_bytecode = True; sys.path.insert(0, str(source/'src'))
    os.environ.update(OMP_NUM_THREADS=str(spec['threads']), MKL_NUM_THREADS=str(spec['threads']),
                      OPENBLAS_NUM_THREADS=str(spec['threads']), WANDB_MODE='disabled')
    if selected_model(spec) == 'boltz2':
        os.environ.update(NUMBA_NUM_THREADS=str(spec['threads']), VECLIB_MAXIMUM_THREADS=str(spec['threads']),
                          NUMEXPR_NUM_THREADS=str(spec['threads']))
    import torch
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError('Pinned Boltz requires Python 3.10–3.12')
    torch.set_num_threads(spec['threads']); torch.set_num_interop_threads(1)
    import boltz.main as main
    from boltz.model.models.boltz1 import Boltz1
    model_name = selected_model(spec)
    model_class = Boltz1
    if model_name == 'boltz2':
        from boltz.model.models.boltz2 import Boltz2
        from boltz.data.module.inferencev2 import PredictionDataset
        model_class = Boltz2
        PredictionDataset.__getitem__ = no_recursive_fallback(PredictionDataset.__getitem__)
    observed = {'forward_calls': 0, 'device': None, 'output_tensor_shapes': []}
    original = model_class.forward
    def tensor_list(item):
        if isinstance(item, torch.Tensor): return [item]
        if isinstance(item, dict): return [t for value in item.values() for t in tensor_list(value)]
        if isinstance(item, (list, tuple)): return [t for value in item for t in tensor_list(value)]
        return []
    def forward(self, *args, **kwargs):
        if model_name == 'boltz2':
            if observed['forward_calls'] or self.affinity_prediction:
                raise RuntimeError('Model-2 duplicate or affinity forward refused')
            incoming = tensor_list((args, kwargs))
            if not incoming or any(t.device.type != 'cpu' for t in incoming):
                raise RuntimeError('Model-2 input tensors must be CPU')
            if not torch.is_autocast_enabled('cpu') or torch.get_autocast_dtype('cpu') != torch.bfloat16:
                raise RuntimeError('Model-2 requires official CPU BF16 mixed precision')
            observed.update(cpu_autocast_enabled=True, cpu_autocast_dtype=str(torch.get_autocast_dtype('cpu')),
                            parameter_dtypes=sorted({str(p.dtype) for p in self.parameters()}),
                            input_dtypes=sorted({str(t.dtype) for t in incoming}), input_device='cpu')
        if {str(p.device) for p in self.parameters()} != {'cpu'}:
            raise RuntimeError('Model parameter device differs from required CPU')
        result = original(self, *args, **kwargs)
        tensors = tensor_list(result)
        if not tensors or any(t.device.type != 'cpu' for t in tensors):
            raise RuntimeError('Forward output device evidence unavailable or incorrect')
        observed.update(forward_calls=observed['forward_calls']+1, device='cpu',
                        output_tensor_shapes=[list(t.shape) for t in tensors[:16]])
        return result
    model_class.forward = forward
    if model_name == 'boltz2':
        install_model2_guards(main, model_class, Boltz1, paths, spec, observed)
    # Do not invoke the upstream downloader, even with a complete cache.
    main.download_boltz1 = lambda cache: verify_assets(cache)
    main.download_boltz2 = (lambda cache: verify_boltz2_assets(cache)) if model_name == 'boltz2' else no_network
    runtime_libraries = {}
    for name in ('libtorch_cpu.dylib', 'libtorch_cpu.so'):
        library = Path(torch.__file__).resolve().parent/'lib'/name
        if library.is_file(): runtime_libraries[name] = digest(regular(library, 1024**3))
    if not runtime_libraries:
        raise RuntimeError('CPU runtime library hash could not be recorded')
    receipt = {'source': source_evidence, 'assets': asset_evidence, 'observed': observed,
               'msa': msa_evidence,
               'python': platform.python_version(), 'python_sha256': digest(Path(sys.executable).resolve()),
               'torch': torch.__version__, 'platform': platform.platform(), 'model': model_name,
               'runtime_library_sha256':runtime_libraries,
               'versions':{name:importlib.metadata.version(name) for name in
                           ('torch','numpy','pytorch-lightning','rdkit','biopython')},
               'network_policy': 'in-process sockets denied; trusted dependencies, not sandbox'}
    try:
        main.cli.main(args=boltz_argv(request), prog_name='boltz', standalone_mode=False)
        if staged_msa(spec, paths['output_dir']) != msa_evidence:
            raise ValueError('MSA identity changed during prediction')
        if observed['forward_calls'] < 1:
            raise RuntimeError('No observed Boltz forward workload')
        if model_name == 'boltz2':
            if verify_source(source) != source_evidence or verify_boltz2_assets(paths['assets_dir']) != asset_evidence:
                raise RuntimeError('Model-2 source/assets changed during use')
            if observed['forward_calls'] != 1 or observed.get('checkpoint_loads') != 1:
                raise RuntimeError('Model-2 workload cardinality differs')
        receipt['completed'] = True
    except BaseException as exc:
        receipt.update(completed=False, error_type=type(exc).__name__, error=str(exc)[:2000])
        raise
    finally:
        atomic_json(Path(request['output_dir'])/'worker-receipt.json', receipt)


def run(spec_path):
    raw = regular(spec_path, MAX_INPUT).read_bytes(); spec = decode_json(raw)
    if not isinstance(spec, dict): raise ValueError('Spec must be an object')
    destination = absolute(spec.get('output_dir'), 'output_dir')
    # Destination guards precede *all* writes, including failure receipts. A
    # diagnostic directory inside the pinned cache would itself corrupt it.
    for name in ('boltz_source', 'assets_dir'):
        protected = absolute(spec.get(name), name)
        if destination.is_relative_to(protected) or protected.is_relative_to(destination):
            raise ValueError('Output must not overlap source or assets')
    if not destination.parent.is_dir(): raise ValueError('Output parent must exist')
    # Reject an overlapping or malformed alignment before reserving any output.
    if spec.get('schema') in (SCHEMA_V2, SCHEMA_V3):
        msa_bytes(spec)
    if spec.get('schema') == SCHEMA_V3:
        checked = validate_spec(spec)
        verify_source(checked['boltz_source'])
        verify_boltz2_assets(checked['assets_dir'])
    destination.mkdir()  # exclusive reservation: never modify an existing output
    report = {'schema': spec.get('schema'), 'status': 'preflight', 'accepted': False, 'engine_started': False,
              'actual_runtime_verified': False, 'scientific_accuracy': 'not_evaluated',
              'spec_sha256': hashlib.sha256(raw).hexdigest(), 'model': selected_model(spec),
              'source_revision': REVISION, 'model_revision': MODEL2_REVISION if spec.get('schema') == SCHEMA_V3 else MODEL_REVISION}
    target = destination/'report.json'; atomic_json(target, report)
    try:
        paths = validate_spec(spec)
        report['source'] = verify_source(paths['boltz_source'])
        report['assets'] = verify_for_spec(spec, paths['assets_dir'])
        report['python_sha256'] = digest(paths['python'])
        report['sequence_sha256'] = hashlib.sha256(spec['sequence'].encode()).hexdigest()
        msa_raw, report['msa'] = msa_bytes(spec)
        if msa_raw is not None:
            with (destination/'input.a3m').open('xb') as stream:
                stream.write(msa_raw); stream.flush(); os.fsync(stream.fileno())
        report['settings'] = {k: spec[k] for k in ('device','seed','threads','timeout_seconds',
                            'recycling_steps','sampling_steps','max_output_bytes','max_log_bytes','memory_budget_bytes')}
        request = {'spec': spec, **{key: str(value) for key, value in paths.items()}}
        atomic_json(destination/'request.json', request)
        report['worker_request_sha256'] = digest(destination/'request.json')
        # JSON is a strict subset of YAML; no string interpolation in YAML values.
        atomic_json(destination/'input.yaml', sequence_input(spec, destination))
        argv = [str(paths['python']), '-I', '-B', str(Path(__file__).resolve()), '_worker',
                '--request', str(destination/'request.json')]
        report.update(status='starting'); atomic_json(target, report)
        def started():
            report.update(status='running', engine_started=True); atomic_json(target, report)
        execution = bounded_process(argv, destination, spec['timeout_seconds'],
                                    spec['max_log_bytes'], spec['max_output_bytes'], spec['memory_budget_bytes'], started)
        report['execution'] = execution
        if execution['failure_kind'] or execution['returncode']:
            report['failure_kind'] = execution['failure_kind'] or 'child_nonzero'
            raise RuntimeError('Structure worker did not complete successfully')
        receipt = read_json(destination/'worker-receipt.json')
        if (receipt.get('completed') is not True or receipt.get('source') != report['source'] or
                receipt.get('assets') != report['assets'] or receipt.get('python_sha256') != report['python_sha256'] or
                receipt.get('model') != selected_model(spec) or receipt.get('observed',{}).get('device') != 'cpu' or
                receipt.get('msa') != report['msa'] or staged_msa(spec, destination) != report['msa'] or
                type(receipt.get('observed',{}).get('forward_calls')) is not int or receipt['observed']['forward_calls'] < 1 or
                not receipt.get('runtime_library_sha256')):
            raise ValueError('Worker provenance or workload evidence mismatch')
        pred = destination/'engine/boltz_results_input/predictions/input'
        report['structure'] = validate_structure(pred/'input_model_0.pdb', spec['sequence'])
        if spec.get('schema') == SCHEMA_V3:
            report['structure']['heavy_atom_inventory'] = validate_heavy_atoms(pred/'input_model_0.pdb', spec['sequence'])
            if verify_boltz2_assets(paths['assets_dir']) != report['assets']:
                raise ValueError('Model-2 assets changed during prediction')
            observation = receipt.get('observed', {})
            if (observation.get('forward_calls') != 1 or observation.get('checkpoint_loads') != 1 or
                    observation.get('cpu_autocast_dtype') != 'torch.bfloat16' or
                    observation.get('cpu_autocast_enabled') is not True or observation.get('input_device') != 'cpu' or
                    observation.get('affinity') is not False or
                    observation.get('checkpoint_sha256') != ASSETS2['boltz2_conf.ckpt'][1]):
                raise ValueError('Model-2 single-forward/precision evidence mismatch')
        report['confidence'] = validate_confidence(pred/'confidence_input_model_0.json')
        report['workload'] = receipt
        report.update(status='succeeded', accepted=True, actual_runtime_verified=True)
    except BaseException as exc:
        report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else
                      ('partial' if report['engine_started'] else 'failed'), accepted=False,
                      error_type=type(exc).__name__, error=str(exc)[:2000])
        report['actual_runtime_verified'] = False
    finally:
        atomic_json(target, report)
        if report['accepted'] and output_size(destination) > spec['max_output_bytes']:
            report.update(status='partial', accepted=False, actual_runtime_verified=False,
                          failure_kind='output_limit', error='Final retained output exceeds declared byte budget')
            atomic_json(target, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run_parser = sub.add_parser('run'); run_parser.add_argument('--spec', required=True)
    validate = sub.add_parser('validate-output')
    validate.add_argument('--structure', required=True); validate.add_argument('--confidence', required=True)
    validate.add_argument('--sequence', required=True)
    internal = sub.add_parser('_worker', help=argparse.SUPPRESS); internal.add_argument('--request', required=True)
    prepare = sub.add_parser('prepare-boltz2-assets')
    prepare.add_argument('--assets-dir', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == '_worker': worker(args.request); return 0
        if args.command == 'prepare-boltz2-assets':
            result = prepare_boltz2_assets(args.assets_dir)
        elif args.command == 'run':
            result = run(args.spec)
        else:
            if not 4 <= len(args.sequence) <= 128 or set(args.sequence)-set(AA3.values()):
                raise ValueError('Canonical sequence length 4–128 required')
            result = {'status':'validated_output_only', 'actual_runtime_verified':False,
                      'scientific_accuracy':'not_evaluated',
                      'structure':validate_structure(args.structure,args.sequence),
                      'confidence':validate_confidence(args.confidence)}
        print(json.dumps(result,allow_nan=False)); return 0 if result.get('status') in ('succeeded','validated_output_only','prepared_assets') else 2
    except Exception as exc:
        print(json.dumps({'status':'failed','accepted':False,'actual_runtime_verified':False,
                          'error_type':type(exc).__name__,'error':str(exc)[:2000]}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
