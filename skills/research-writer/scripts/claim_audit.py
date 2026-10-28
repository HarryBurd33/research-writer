#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline claim/review coverage audit; record validity grants no drafting clearance."""
from __future__ import annotations

import argparse
from decimal import Decimal
import importlib.util
import json
import math
import os
from pathlib import Path, PureWindowsPath
import stat
import sys

MAX_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BYTES = 20 * 1024 * 1024
LIMITS = {'sources': 32, 'claims': 100, 'reviews': 500}
PUBLICATION_STATUS = ('current', 'corrected', 'retracted', 'withdrawn', 'unknown')
JUDGMENTS = ('supports', 'partial', 'contradicts', 'uncertain')
_LEGACY = None


def _legacy():
    """Load the unchanged sibling, including when imported by absolute file path."""
    global _LEGACY
    if _LEGACY is None:
        spec = importlib.util.spec_from_file_location(
            '_research_writer_support_integrity', Path(__file__).with_name('support_tools.py'))
        if spec is None or spec.loader is None:
            raise ImportError('Cannot load local support integrity checker')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEGACY = module
    return _LEGACY


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def read_json(path):
    raw = _read_source(Path(path))
    if len(raw) > MAX_BYTES:
        raise ValueError('Manifest exceeds 10 MiB')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_pairs,
                      parse_float=Decimal, parse_constant=_invalid_constant)


def _validate_json(value):
    """Bound direct API inputs too, rejecting non-JSON/nonfinite values."""
    def visit(item):
        if item is None or type(item) in (str, bool, int):
            return
        if isinstance(item, (float, Decimal)):
            if not (item.is_finite() if isinstance(item, Decimal) else math.isfinite(item)):
                raise ValueError('Nonfinite number in manifest')
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError('JSON object keys must be strings')
                visit(child)
            return
        raise ValueError('Manifest contains a non-JSON value')
    visit(value)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         default=lambda item: str(item) if isinstance(item, Decimal) else item)
    if len(payload.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Manifest exceeds 10 MiB')


def _source_path(root, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Nonempty relative source path required')
    windows = PureWindowsPath(name)
    if (Path(name).is_absolute() or windows.drive or windows.root
            or '..' in Path(name).parts or '..' in windows.parts
            or any(':' in part for part in windows.parts)):
        raise ValueError('Relative source path without traversal or Windows escape required')
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Source resolves outside base directory')
    return path


def _read_source(path):
    """Read bounded regular files, rejecting FIFOs/devices before any read.

    The initial stat rejects known special files. On POSIX, O_NONBLOCK also
    prevents a regular-to-FIFO replacement from blocking open; fstat checks the
    opened object before reading. The legacy checker subsequently reopens paths,
    so callers must use a cooperating filesystem without concurrent replacement.
    This is input validation, not an adversarial filesystem security sandbox.
    """
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Source must be a regular file')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Opened source must be a regular file')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            return stream.read(MAX_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def audit_claims(manifest, base_directory='.'):
    """Validate source/review records and declared claim/source pair coverage.

    Study families and publication status are declarations, not independently
    certified facts. All judgments remain the named reviewer's assertions.
    """
    errors = []
    result = {
        'schema_version': 1, 'status': 'failed', 'passed': False,
        'record_integrity': 'not_checked',
        'semantic_entailment': 'not_automatically_verified',
        'drafting_clearance': 'not_granted',
        'scientific_validity': 'not_checked',
        'study_family_status': 'declared_not_independently_verified',
        'errors': errors, 'claims': [], 'flags': [], 'review_needed': True,
        'declared_pair_coverage': {'required': 0, 'covered': 0, 'missing': []},
    }

    def error(code, record, detail):
        errors.append({'code': code, 'record': record, 'detail': detail})

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def records(name):
        values = manifest.get(name, [])
        if not isinstance(values, list):
            error('invalid_records', name, 'Expected an array')
            return []
        if len(values) > LIMITS[name]:
            error('record_limit', name, 'Maximum ' + str(LIMITS[name]) + ' records')
            return []
        indexed = {}
        for index, item in enumerate(values):
            label = name + '[' + str(index) + ']'
            if not isinstance(item, dict) or not nonempty(item.get('id')):
                error('invalid_record', label, 'Object with nonempty string id required')
            elif item['id'] in indexed:
                error('duplicate_id', label, item['id'])
            else:
                indexed[item['id']] = item
        return list(indexed.values())

    try:
        _validate_json(manifest)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        error('invalid_manifest', 'manifest', str(exc))
        return result
    if not isinstance(manifest, dict):
        error('invalid_manifest', 'manifest', 'Expected an object')
        return result
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        error('invalid_schema', 'manifest', 'schema_version must be integer 1')
    sources, claims, reviews = records('sources'), records('claims'), records('reviews')
    source_index = {item['id']: item for item in sources}
    claim_index = {item['id']: item for item in claims}
    for source in sources:
        label = 'source:' + source['id']
        if not nonempty(source.get('study_family')):
            error('invalid_study_family', label, 'study_family must be a nonempty string')
        if source.get('publication_status') not in PUBLICATION_STATUS:
            error('invalid_publication_status', label, 'Expected a declared publication status')
    required_pairs = []
    for claim in claims:
        label = 'claim:' + claim['id']
        if not nonempty(claim.get('text')):
            error('invalid_claim_text', label, 'text must be a nonempty string')
        if claim.get('required_access') not in ('abstract', 'full_text'):
            error('invalid_required_access', label, 'Expected abstract or full_text')
        ids = claim.get('required_source_ids')
        if (not isinstance(ids, list) or not ids
                or any(not nonempty(sid) for sid in ids)):
            error('invalid_required_sources', label, 'Nonempty array of unique source IDs required')
            continue
        if len(ids) != len(set(ids)):
            error('duplicate_required_source', label, 'Required source IDs must be unique')
        for sid in dict.fromkeys(ids):
            required_pairs.append((claim['id'], sid))
            source = source_index.get(sid)
            if source is None:
                error('unknown_source', label, sid)
            elif (source.get('access') not in ('abstract', 'full_text')
                  or (claim.get('required_access') == 'full_text'
                      and source.get('access') != 'full_text')):
                error('insufficient_access', label, 'Required source ' + sid + ' lacks required access')

    invalid_reviews = set()
    for review in reviews:
        label = 'review:' + review['id']
        before = len(errors)
        cid, sid = review.get('claim_id'), review.get('source_id')
        claim = claim_index.get(cid) if isinstance(cid, str) else None
        source = source_index.get(sid) if isinstance(sid, str) else None
        if claim is None:
            error('unknown_claim', label, 'Review must name a declared claim_id')
        elif review.get('claim') != claim.get('text'):
            error('claim_text_mismatch', label, 'Review claim must exactly equal declared text')
        if source is None:
            error('unknown_source', label, 'Review must name a declared source_id')
        elif claim is not None and (source.get('access') not in ('abstract', 'full_text')
                or (claim.get('required_access') == 'full_text' and source.get('access') != 'full_text')):
            error('insufficient_access', label, 'Reviewed source lacks claim required access')
        if review.get('judgment') not in JUDGMENTS:
            error('invalid_judgment', label, 'Expected supports, partial, contradicts or uncertain')
        if len(errors) != before:
            invalid_reviews.add(review['id'])

    # Enforce confinement and aggregate bytes before handing any path to the
    # unchanged legacy checker. A failed resource/path preflight stops source IO.
    try:
        root = Path(base_directory).resolve()
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        error('invalid_base_directory', 'manifest', str(exc))
        return result
    total_bytes, preflight_ok = 0, True
    for source in sources:
        try:
            path = _source_path(root, source.get('path'))
            raw = _read_source(path)
            if len(raw) > MAX_BYTES:
                raise ValueError('Source exceeds 10 MiB')
            total_bytes += len(raw)
            if total_bytes > MAX_SOURCE_BYTES:
                raise ValueError('Source aggregate exceeds 20 MiB')
            raw.decode('utf-8')
        except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
            error('source_unreadable_or_unsafe', 'source:' + source['id'], str(exc))
            preflight_ok = False
            break
    valid_reviews = []
    if preflight_ok:
        adapted = [dict(review, judgment='uncertain') if review.get('judgment') == 'partial'
                   else dict(review) for review in reviews]
        legacy = _legacy().verify_support(
            {'schema_version': manifest.get('schema_version'), 'sources': sources, 'reviews': adapted}, root)
        result['integrity_check'] = legacy
        errors.extend(legacy['errors'])
        valid_ids = {review['id'] for review in legacy['recorded_judgments']}
        valid_reviews = [review for review in reviews
                         if review['id'] in valid_ids and review['id'] not in invalid_reviews]
        result['record_integrity'] = 'failed' if errors else 'valid'
    else:
        result['record_integrity'] = 'failed'

    covered = {(review['claim_id'], review['source_id']) for review in valid_reviews}
    missing = [{'claim_id': cid, 'source_id': sid}
               for cid, sid in required_pairs if (cid, sid) not in covered]
    result['declared_pair_coverage'] = {
        'required': len(required_pairs),
        'covered': sum(pair in covered for pair in required_pairs),
        'missing': missing, 'complete': not missing,
    }
    global_flags = set()
    source_families = {}
    result['sources'] = []
    for source in sources:
        result['sources'].append({field: source.get(field) for field in (
            'id', 'version', 'access', 'identity_status', 'path', 'sha256',
            'locator', 'study_family', 'publication_status')})
        status = source.get('publication_status')
        if status in PUBLICATION_STATUS and status != 'current':
            global_flags.add('publication_status_' + status)
        family, version = source.get('study_family'), source.get('version')
        if nonempty(family) and nonempty(version):
            source_families.setdefault(family, set()).add(version)
    if any(len(versions) > 1 for versions in source_families.values()):
        global_flags.add('same_family_multiple_versions')
    for claim in claims:
        claim_reviews = [review for review in valid_reviews if review['claim_id'] == claim['id']]
        required_ids = claim.get('required_source_ids', [])
        if not isinstance(required_ids, list):
            required_ids = []
        declared_ids = {sid for sid in required_ids if isinstance(sid, str) and sid in source_index}
        reviewed_ids = {review['source_id'] for review in claim_reviews}
        families, flags = {}, set()
        for sid in sorted(declared_ids | reviewed_ids):
            source = source_index[sid]
            family = source.get('study_family')
            if nonempty(family):
                group = families.setdefault(family, {'study_family': family, 'source_ids': [], 'versions': []})
                group['source_ids'].append(sid)
                version = source.get('version')
                if nonempty(version) and version not in group['versions']:
                    group['versions'].append(version)
            status = source.get('publication_status')
            if status in PUBLICATION_STATUS and status != 'current':
                flags.add('publication_status_' + status)
        for family in families.values():
            if len(family['versions']) > 1:
                flags.add('same_family_multiple_versions')
        for review in claim_reviews:
            if review['judgment'] != 'supports':
                flags.add({'partial': 'partial_judgment', 'contradicts': 'contradiction',
                           'uncertain': 'uncertain_judgment'}[review['judgment']])
        claim_missing = [pair for pair in missing if pair['claim_id'] == claim['id']]
        if claim_missing:
            flags.add('missing_required_reviews')
        judgments = []
        for review in claim_reviews:
            # Preserve actual partial judgments rather than the legacy adapter.
            source = source_index[review['source_id']]
            record = {field: review.get(field) for field in (
                'id', 'claim_id', 'claim', 'source_id', 'source_version',
                'source_sha256', 'passage', 'start', 'end', 'locator',
                'judgment', 'rationale', 'reviewer', 'reviewed_at')}
            judgments.append(dict(record, access=source.get('access'),
                                  study_family=source.get('study_family'),
                                  publication_status=source.get('publication_status'),
                                  judgment_status='recorded_not_automatically_verified'))
        declared_families = {source_index[sid].get('study_family') for sid in declared_ids
                             if nonempty(source_index[sid].get('study_family'))}
        reviewed_families = {source_index[sid].get('study_family') for sid in reviewed_ids
                             if nonempty(source_index[sid].get('study_family'))}
        result['claims'].append({
            'id': claim['id'], 'text': claim.get('text'),
            'required_access': claim.get('required_access'),
            'required_source_ids': required_ids, 'judgments': judgments,
            'declared_family_count': len(declared_families),
            'reviewed_family_count': len(reviewed_families),
            'family_count': len(families), 'families': list(families.values()),
            'missing_required_pairs': claim_missing, 'flags': sorted(flags),
            'review_needed': bool(flags),
        })
        global_flags.update(flags)
    result['flags'] = sorted(global_flags)
    result['counts'] = {'sources': len(sources), 'claims': len(claims),
                        'reviews': len(reviews), 'valid_review_records': len(valid_reviews),
                        'declared_families': len({source['study_family'] for source in sources
                                                 if nonempty(source.get('study_family'))}),
                        'source_bytes': total_bytes}
    if errors:
        result['status'] = 'failed'
    elif not claims:
        result['status'] = 'not_checked'
        result['reason'] = 'no_claims_to_check'
    elif missing:
        result['status'] = 'incomplete'
    else:
        result['status'], result['passed'] = 'records_valid', True
    result['review_needed'] = bool(global_flags) or result['status'] != 'records_valid'
    return result


def _preflight_output(path):
    target = Path(path)
    if os.path.lexists(target):
        raise FileExistsError('Output exists; choose a new output path')
    if not target.parent.is_dir():
        raise FileNotFoundError('Output parent directory does not exist')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    audit = commands.add_parser('audit-claims')
    audit.add_argument('--input', required=True)
    audit.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        target = _preflight_output(args.output)  # Must precede all input IO.
        manifest = read_json(args.input)
        result = audit_claims(manifest, Path(args.input).resolve().parent)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False,
                             default=str) + '\n'
        with target.open('x', encoding='utf-8') as stream:
            stream.write(payload)
        return 0 if result['status'] == 'records_valid' else 2
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, RecursionError) as exc:
        print(json.dumps({'status': 'failed', 'passed': False, 'error': str(exc),
                          'semantic_entailment': 'not_automatically_verified',
                          'drafting_clearance': 'not_granted'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
