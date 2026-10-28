#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline source-support review records. Integrity is not semantic entailment."""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import tempfile

MAX_BYTES = 10 * 1024 * 1024
ACCESS = ('metadata', 'abstract', 'full_text')
JUDGMENTS = ('supports', 'contradicts', 'uncertain')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def _bytes(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Input exceeds 10 MiB')
    return raw


def read_json(path):
    return json.loads(_bytes(path).decode('utf-8'), object_pairs_hook=_pairs,
                      parse_float=Decimal, parse_constant=_invalid_constant)


def _write(path, value, force=False):
    target = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if not force:
        with target.open('x', encoding='utf-8') as stream:
            stream.write(payload)
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.support-record-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(payload)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_support(manifest, base_directory='.'):
    """Check recorded source identity, exact passage and reviewer fields only.

    A valid judgment remains its reviewer's assertion. This function cannot
    determine whether the passage actually supports, contradicts or answers a claim.
    """
    errors, recorded = [], []
    result = {'status': 'fail', 'passed': False, 'record_integrity': 'checked',
              'semantic_entailment': 'not_automatically_verified',
              'scientific_validity': 'not_checked', 'errors': errors,
              'recorded_judgments': recorded,
              'scope': 'local source hash/version, exact text offsets and review-record completeness'}
    def error(code, record, detail):
        errors.append({'code': code, 'record': record, 'detail': detail})
    def string(record, field, label):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            error('missing_string', label, field + ' must be a nonempty string')
            return False
        return True
    def records(name):
        values = manifest.get(name, [])
        if not isinstance(values, list):
            error('invalid_records', name, 'Expected an array')
            return []
        indexed = {}
        for n, value in enumerate(values):
            label = name + '[' + str(n) + ']'
            if not isinstance(value, dict):
                error('invalid_record', label, 'Expected an object')
                continue
            if not string(value, 'id', label):
                continue
            if value['id'] in indexed:
                error('duplicate_id', label, value['id'])
                continue
            indexed[value['id']] = value
        return list(indexed.values())
    if not isinstance(manifest, dict):
        error('invalid_manifest', 'manifest', 'Expected an object')
        return result
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        error('invalid_schema', 'manifest', 'schema_version must be integer 1')
    sources = records('sources')
    reviews = records('reviews')
    root = Path(base_directory).resolve()
    verified = {}
    for source in sources:
        label = 'source:' + source['id']
        before = len(errors)
        for field in ('version', 'access', 'identity_status', 'path', 'sha256', 'locator'):
            string(source, field, label)
        if source.get('access') not in ACCESS:
            error('invalid_access', label, 'Expected metadata, abstract or full_text')
        if source.get('identity_status') not in ('verified', 'identity_verified'):
            error('unverified_identity', label, 'Source identity must be verified separately')
        expected = source.get('sha256')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
            error('invalid_hash', label, 'Expected SHA-256 hex')
        name = source.get('path')
        try:
            if not isinstance(name, str) or not name or Path(name).is_absolute() or PureWindowsPath(name).drive or '..' in Path(name).parts or '..' in PureWindowsPath(name).parts:
                raise ValueError('Relative artifact path without traversal required')
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Artifact resolves outside manifest directory')
            raw = _bytes(path)
            if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected.lower():
                error('hash_mismatch', label, 'Source bytes differ from recorded SHA-256')
            text = raw.decode('utf-8')
            if not text.strip():
                error('empty_source', label, 'Source text is empty')
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            error('source_unreadable_or_unsafe', label, str(exc))
            continue
        if before == len(errors):
            verified[source['id']] = (source, text)
    for review in reviews:
        label = 'review:' + review['id']
        before = len(errors)
        for field in ('claim', 'source_id', 'source_version', 'source_sha256', 'passage',
                      'locator', 'judgment', 'rationale', 'reviewer', 'reviewed_at'):
            string(review, field, label)
        if review.get('judgment') not in JUDGMENTS:
            error('invalid_judgment', label, 'Expected supports, contradicts or uncertain')
        try:
            stamp = review.get('reviewed_at')
            if not isinstance(stamp, str):
                raise ValueError('Timestamp must be a string')
            observed = datetime.fromisoformat(stamp[:-1] + '+00:00' if stamp.endswith('Z') else stamp)
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError('Timestamp requires timezone')
        except (ValueError, TypeError) as exc:
            error('invalid_review_time', label, str(exc))
        sid = review.get('source_id')
        source_data = verified.get(sid) if isinstance(sid, str) else None
        if source_data is None:
            error('unverified_source', label, 'Source ID is missing or its integrity failed')
            continue
        source, text = source_data
        if source['access'] == 'metadata':
            error('insufficient_access', label, 'Metadata is not an inspected abstract or full-text passage')
        if review.get('source_version') != source['version']:
            error('version_mismatch', label, 'Review version differs from recorded source')
        if not isinstance(review.get('source_sha256'), str) or review['source_sha256'].lower() != source['sha256'].lower():
            error('review_hash_mismatch', label, 'Review is not bound to the recorded source bytes')
        start, end = review.get('start'), review.get('end')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            error('invalid_offsets', label, 'Expected 0 <= start < end <= text length; booleans forbidden')
        elif review.get('passage') != text[start:end]:
            error('passage_mismatch', label, 'Passage does not equal source text at recorded offsets')
        if len(errors) == before:
            recorded.append({'id': review['id'], 'claim': review['claim'], 'source_id': sid,
                             'source_version': source['version'], 'source_sha256': source['sha256'],
                             'access': source['access'], 'judgment': review['judgment'],
                             'reviewer': review['reviewer'], 'reviewed_at': review['reviewed_at'],
                             'rationale': review['rationale'], 'locator': review['locator'],
                             'judgment_status': 'recorded_not_automatically_verified'})
    result['counts'] = {'sources': len(sources), 'reviews': len(reviews), 'valid_review_records': len(recorded)}
    if not reviews and not errors:
        result['status'] = 'not_checked'
        result['reason'] = 'no_reviews_to_check'
    elif not errors:
        result['status'], result['passed'] = 'pass', True
        result['review_status'] = 'review_records_valid'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    review = commands.add_parser('review-support')
    review.add_argument('--input', required=True)
    review.add_argument('--output', required=True)
    review.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        if Path(args.output).exists() and not args.force:
            raise FileExistsError('Output exists; use a new path or explicit --force')
        manifest = read_json(args.input)
        result = verify_support(manifest, Path(args.input).resolve().parent)
        _write(args.output, result, args.force)
        return 0 if result['passed'] else 2
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({'status': 'failed', 'passed': False, 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
