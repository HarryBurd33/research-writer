#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Public offline contracts for claim audit records, coverage and CLI safety."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts/claim_audit.py'
spec = importlib.util.spec_from_file_location('public_claim_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ClaimAuditChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.text = 'A bounded review found mixed results. More work is required.\n'
        self.source_bytes = self.text.encode('utf-8')
        (self.root / 'source.txt').write_bytes(self.source_bytes)
        self.digest = hashlib.sha256(self.source_bytes).hexdigest()
        self.manifest = {
            'schema_version': 1,
            'sources': [self.source('s1')],
            'claims': [self.claim('c1')],
            'reviews': [self.review('r1')],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, sid, **changes):
        return dict({'id': sid, 'version': 'v1', 'access': 'full_text',
                     'identity_status': 'verified', 'path': 'source.txt',
                     'sha256': self.digest, 'locator': 'local passage',
                     'study_family': 'declared-family-A', 'publication_status': 'current'}, **changes)

    def claim(self, cid, **changes):
        return dict({'id': cid, 'text': 'The recorded results are mixed.',
                     'required_source_ids': ['s1'], 'required_access': 'full_text'}, **changes)

    def review(self, rid, **changes):
        return dict({'id': rid, 'claim_id': 'c1', 'claim': 'The recorded results are mixed.',
                     'source_id': 's1', 'source_version': 'v1', 'source_sha256': self.digest,
                     'passage': self.text[:36], 'start': 0, 'end': 36,
                     'locator': 'characters 0:36', 'judgment': 'supports',
                     'rationale': 'A named reviewer compared this exact passage.',
                     'reviewer': 'Public fixture reviewer', 'reviewed_at': '2026-10-28T12:00:00Z'}, **changes)

    def run_audit(self):
        return audit.audit_claims(self.manifest, self.root)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), 'audit-claims', *arguments],
                              capture_output=True, text=True, timeout=15)

    def test_valid_and_no_semantic_or_drafting_clearance(self):
        result = self.run_audit()
        self.assertEqual(result['status'], 'records_valid')
        self.assertEqual(result['record_integrity'], 'valid')
        self.assertEqual(result['declared_pair_coverage']['covered'], 1)
        self.assertEqual(result['semantic_entailment'], 'not_automatically_verified')
        self.assertEqual(result['drafting_clearance'], 'not_granted')

    def test_fixture_bytes_and_declared_hashes_are_platform_exact(self):
        raw = (self.root / 'source.txt').read_bytes()
        self.assertEqual(raw, self.text.encode('utf-8'))
        self.assertTrue(raw.endswith(b'\n'))
        self.assertNotIn(b'\r\n', raw)
        actual = hashlib.sha256(raw).hexdigest()
        self.assertEqual(actual, self.manifest['sources'][0]['sha256'])
        self.assertEqual(actual, self.manifest['reviews'][0]['source_sha256'])

    def test_missing_pair_is_specific_to_each_claim(self):
        self.manifest['claims'].append(self.claim('c2'))
        result = self.run_audit()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['declared_pair_coverage']['missing'],
                         [{'claim_id': 'c2', 'source_id': 's1'}])

    def test_partial_and_contradiction_remain_valid_and_visible(self):
        self.manifest['reviews'][0]['judgment'] = 'partial'
        self.manifest['reviews'].append(self.review('r2', judgment='contradicts'))
        result = self.run_audit()
        self.assertEqual(result['status'], 'records_valid')
        self.assertEqual([item['judgment'] for item in result['claims'][0]['judgments']],
                         ['partial', 'contradicts'])
        self.assertTrue(result['review_needed'])
        self.assertIn('contradiction', result['flags'])

    def test_additional_nonrequired_contrary_source_is_visible(self):
        self.manifest['sources'].append(self.source('s2', study_family='family-B'))
        self.manifest['reviews'].append(self.review('r2', source_id='s2', judgment='contradicts'))
        result = self.run_audit()
        self.assertEqual(result['status'], 'records_valid')
        self.assertEqual(len(result['claims'][0]['judgments']), 2)
        self.assertEqual(result['claims'][0]['declared_family_count'], 1)
        self.assertEqual(result['claims'][0]['reviewed_family_count'], 2)

    def test_family_versions_are_not_counted_as_separate_studies(self):
        self.manifest['sources'].append(self.source('s2', version='v2'))
        self.manifest['claims'][0]['required_source_ids'].append('s2')
        self.manifest['reviews'].append(self.review('r2', source_id='s2', source_version='v2'))
        result = self.run_audit()
        self.assertEqual(result['status'], 'records_valid')
        self.assertEqual(result['claims'][0]['family_count'], 1)
        self.assertIn('same_family_multiple_versions', result['flags'])

    def test_publication_status_and_uncertainty_flags(self):
        for status in ('corrected', 'retracted', 'withdrawn', 'unknown'):
            with self.subTest(status=status):
                self.manifest['sources'][0]['publication_status'] = status
                self.manifest['reviews'][0]['judgment'] = 'uncertain'
                result = self.run_audit()
                self.assertEqual(result['status'], 'records_valid')
                self.assertIn('publication_status_' + status, result['flags'])
                self.assertIn('uncertain_judgment', result['flags'])

    def test_unknown_claim_source_and_exact_claim_text_binding(self):
        for field, value in (('claim_id', 'absent'), ('source_id', 'absent'),
                             ('claim', 'The recorded results are mixed. ')):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest['reviews'][0][field] = value
                self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')

    def test_reviewless_declaration_does_not_pass(self):
        self.manifest['reviews'] = []
        self.assertEqual(self.run_audit()['status'], 'incomplete')

    def test_no_claims_is_not_checked(self):
        self.manifest['claims'], self.manifest['reviews'] = [], []
        self.assertEqual(self.run_audit()['status'], 'not_checked')

    def test_access_thresholds(self):
        self.manifest['sources'][0]['access'] = 'abstract'
        self.assertEqual(self.run_audit()['status'], 'failed')
        self.manifest['claims'][0]['required_access'] = 'abstract'
        self.assertEqual(self.run_audit()['status'], 'records_valid')
        self.manifest['sources'][0]['access'] = 'metadata'
        self.assertEqual(self.run_audit()['status'], 'failed')

    def test_hash_version_passage_and_bool_offset_tampering(self):
        for field, value in (('source_sha256', '0' * 64), ('source_version', 'v2'),
                             ('passage', 'fabricated passage'), ('start', False)):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest['reviews'][0][field] = value
                self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')
        (self.root / 'source.txt').write_text('Changed source', encoding='utf-8')
        self.assertEqual(self.run_audit()['status'], 'failed')

    def test_confined_paths_and_windows_escapes(self):
        for path in ('../source.txt', '/tmp/source.txt', 'C:\\source.txt',
                     'C:source.txt', '\\source.txt', '\\\\host\\share\\source.txt',
                     '..\\source.txt', 'source.txt:stream'):
            with self.subTest(path=path):
                self.manifest['sources'][0]['path'] = path
                self.assertEqual(self.run_audit()['status'], 'failed')

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'outside.txt'
            target.write_bytes(self.source_bytes)
            try:
                (self.root / 'link.txt').symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks unavailable on this platform')
            self.manifest['sources'][0]['path'] = 'link.txt'
            self.assertEqual(self.run_audit()['status'], 'failed')

    def test_directory_source_rejected_and_regular_source_unchanged(self):
        self.manifest['sources'][0]['path'] = '.'
        result = self.run_audit()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(any('regular file' in item['detail'] for item in result['errors']))
        self.manifest['sources'][0]['path'] = 'source.txt'
        self.assertEqual(self.run_audit()['status'], 'records_valid')

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'mkfifo'),
                         'Actual FIFO creation requires POSIX')
    def test_actual_fifo_source_rejected_without_blocking(self):
        fifo = self.root / 'source.fifo'
        os.mkfifo(fifo)
        self.manifest['sources'][0]['path'] = fifo.name
        source = self.root / 'fifo-manifest.json'
        source.write_text(json.dumps(self.manifest), encoding='utf-8')
        output = self.root / 'fifo-audit.json'
        child = subprocess.Popen(
            [sys.executable, '-B', str(SCRIPT), 'audit-claims',
             '--input', str(source), '--output', str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            try:
                stdout, stderr = child.communicate(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.fail('Actual FIFO source blocked instead of being rejected')
            self.assertEqual(child.returncode, 2, stdout + stderr)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(any('regular file' in item['detail'] for item in result['errors']))
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_array_bounds_and_schema_bool(self):
        for name, count in (('sources', 33), ('claims', 101), ('reviews', 501)):
            manifest = copy.deepcopy(self.manifest)
            manifest[name] *= count
            self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')
        self.manifest['schema_version'] = True
        self.assertEqual(self.run_audit()['status'], 'failed')

    def test_exact_record_limits_are_accepted(self):
        self.manifest['sources'] = [self.source('s' + str(n)) for n in range(32)]
        self.manifest['claims'] = [self.claim('c' + str(n)) for n in range(100)]
        self.manifest['reviews'] = [self.review('r' + str(n), claim_id='c' + str(n % 100))
                                    for n in range(500)]
        result = self.run_audit()
        self.assertEqual(result['status'], 'records_valid')
        self.assertEqual(result['counts']['valid_review_records'], 500)
        self.assertEqual(result['declared_pair_coverage']['covered'], 100)

    def test_required_ids_and_family_status_types(self):
        for ids in ([], ['s1', 's1'], [False], ['absent']):
            manifest = copy.deepcopy(self.manifest)
            manifest['claims'][0]['required_source_ids'] = ids
            self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')
        for field, value in (('study_family', ''), ('study_family', True),
                             ('publication_status', 'certified'), ('publication_status', False)):
            manifest = copy.deepcopy(self.manifest)
            manifest['sources'][0][field] = value
            self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')

    def test_invalid_utf8_and_nonfinite_api_inputs(self):
        (self.root / 'source.txt').write_bytes(b'\xff')
        self.assertEqual(self.run_audit()['status'], 'failed')
        for value in (float('nan'), float('inf')):
            manifest = copy.deepcopy(self.manifest)
            manifest['extra'] = value
            self.assertEqual(audit.audit_claims(manifest, self.root)['status'], 'failed')

    def test_source_and_aggregate_byte_limits(self):
        # Sparse ASCII files make the actual byte boundaries inexpensive to test.
        large = self.root / 'large.txt'
        large.write_bytes(b'x' * (audit.MAX_BYTES + 1))
        self.manifest['sources'][0]['path'] = 'large.txt'
        self.assertEqual(self.run_audit()['status'], 'failed')
        large.write_bytes(b'x' * (8 * 1024 * 1024))
        self.manifest['sources'] = [self.source('s' + str(n), path='large.txt') for n in range(3)]
        self.assertTrue(any('aggregate' in item['detail'] for item in self.run_audit()['errors']))

    def test_cli_valid_nonoverwrite_and_input_preflight(self):
        source = self.root / 'manifest.json'
        source.write_text(json.dumps(self.manifest), encoding='utf-8')
        output = self.root / 'audit.json'
        first = self.cli('--input', str(source), '--output', str(output))
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = output.read_bytes()
        second = self.cli('--input', str(self.root / 'missing.json'), '--output', str(output))
        self.assertEqual(second.returncode, 2)
        self.assertIn('Output exists', second.stderr)
        self.assertNotIn('missing.json', second.stderr)
        self.assertEqual(output.read_bytes(), saved)
        forced = self.cli('--input', str(source), '--output', str(output), '--force')
        self.assertEqual(forced.returncode, 2)
        self.assertEqual(output.read_bytes(), saved)

    def test_cli_manifest_directory_rejected_without_output(self):
        output = self.root / 'directory-manifest-output.json'
        result = self.cli('--input', str(self.root), '--output', str(output))
        self.assertEqual(result.returncode, 2)
        self.assertIn('regular file', result.stderr)
        self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'mkfifo'),
                         'Actual FIFO creation requires POSIX')
    def test_actual_fifo_manifest_rejected_without_blocking(self):
        fifo = self.root / 'manifest.fifo'
        os.mkfifo(fifo)
        output = self.root / 'fifo-manifest-output.json'
        child = subprocess.Popen(
            [sys.executable, '-B', str(SCRIPT), 'audit-claims',
             '--input', str(fifo), '--output', str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            try:
                stdout, stderr = child.communicate(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.fail('Actual FIFO manifest blocked instead of being rejected')
            self.assertEqual(child.returncode, 2, stdout + stderr)
            self.assertIn('regular file', stderr)
            self.assertFalse(output.exists())
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_cli_strict_duplicate_keys_nonfinite_and_manifest_bound(self):
        source = self.root / 'bad.json'
        for number, text in enumerate(('{"schema_version":1,"schema_version":1}',
                                       '{"schema_version":1,"extra":NaN}',
                                       ' ' * (audit.MAX_BYTES + 1))):
            source.write_text(text, encoding='utf-8')
            output = self.root / ('bad-output-' + str(number) + '.json')
            result = self.cli('--input', str(source), '--output', str(output))
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_cli_incomplete_and_failed_exit_nonzero(self):
        source = self.root / 'manifest.json'
        for number, reviews in enumerate(([], [self.review('r1', source_version='wrong')])):
            self.manifest['reviews'] = reviews
            source.write_text(json.dumps(self.manifest), encoding='utf-8')
            output = self.root / ('result-' + str(number) + '.json')
            result = self.cli('--input', str(source), '--output', str(output))
            self.assertEqual(result.returncode, 2)
            self.assertIn(json.loads(output.read_text())['status'], ('incomplete', 'failed'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
