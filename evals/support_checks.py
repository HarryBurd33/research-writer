#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline source-support record regressions using explicitly fictional text."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'research-writer'
spec = importlib.util.spec_from_file_location('support_checked', SKILL / 'scripts' / 'support_tools.py')
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class SupportChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Fictional fixture; no external empirical finding is asserted.
        self.text = 'Fictional study: the lamp was blue. No temperature was measured.\n'
        p = self.root / 'source.txt'
        p.write_bytes(self.text.encode('utf-8'))
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'schema_version': 1,
            'sources': [{'id': 's', 'version': 'fixture-v1', 'access': 'full_text',
                         'identity_status': 'verified', 'path': p.name, 'sha256': sha, 'locator': 'fictional fixture'}],
            'reviews': [{'id': 'r', 'claim': 'The fixture lamp was blue.', 'source_id': 's',
                         'source_version': 'fixture-v1', 'source_sha256': sha, 'start': 0,
                         'end': len(self.text), 'passage': self.text, 'locator': 'sentence 1',
                         'judgment': 'supports', 'rationale': 'Explicit statement in fictional text.',
                         'reviewer': 'fixture reviewer', 'reviewed_at': '2026-10-27T12:00:00+00:00'}]}

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, manifest=None):
        return S.verify_support(self.manifest if manifest is None else manifest, self.root)

    def test_valid_zero_offset_and_explicit_semantic_limit(self):
        report = self.verify()
        self.assertTrue(report['passed'])
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['review_status'], 'review_records_valid')
        self.assertEqual(report['semantic_entailment'], 'not_automatically_verified')
        self.assertEqual(report['scientific_validity'], 'not_checked')
        self.assertEqual(report['recorded_judgments'][0]['access'], 'full_text')

    def test_three_judgments_are_records_not_automatic_truth(self):
        for judgment in ('supports', 'contradicts', 'uncertain'):
            with self.subTest(judgment=judgment):
                self.manifest['reviews'][0]['judgment'] = judgment
                self.assertTrue(self.verify()['passed'])
        self.manifest['reviews'][0]['claim'] = 'An obviously unrelated fictional claim.'
        self.manifest['reviews'][0]['judgment'] = 'supports'
        report = self.verify()
        self.assertTrue(report['passed'])
        self.assertEqual(report['semantic_entailment'], 'not_automatically_verified')

    def test_empty_not_checked_and_schema_invalid(self):
        report = self.verify({'schema_version': 1, 'sources': [], 'reviews': []})
        self.assertFalse(report['passed']); self.assertEqual(report['status'], 'not_checked')
        for value in (None, [], {}, {'schema_version': True}, {'schema_version': 2},
                      {'schema_version': 1, 'reviews': 'not-array'}):
            with self.subTest(value=value):
                self.assertFalse(S.verify_support(value, self.root)['passed'])

    def test_wrong_hash_version_quote_and_identity_fail(self):
        for array, field, value in [('sources', 'sha256', '0' * 64),
                                    ('sources', 'identity_status', 'unresolved'),
                                    ('reviews', 'source_sha256', '0' * 64),
                                    ('reviews', 'source_version', 'wrong-v2'),
                                    ('reviews', 'source_id', 'missing'),
                                    ('reviews', 'passage', 'Invented quotation.')]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest); changed[array][0][field] = value
                self.assertFalse(self.verify(changed)['passed'])

    def test_missing_required_fields_rejected(self):
        for category in ('sources', 'reviews'):
            for key in self.manifest[category][0]:
                with self.subTest(category=category, key=key):
                    changed = copy.deepcopy(self.manifest); del changed[category][0][key]
                    self.assertFalse(self.verify(changed)['passed'])

    def test_offsets_are_exact_integers_and_unicode_characters(self):
        for start, end in ((True, 10), (0, False), (-1, 2), (0, len(self.text)+1),
                           (3, 2), (0.0, 10), (0, 0), (None, 10)):
            with self.subTest(start=start, end=end):
                changed = copy.deepcopy(self.manifest); changed['reviews'][0].update(start=start, end=end)
                self.assertFalse(self.verify(changed)['passed'])
        text = 'é → blue'
        (self.root / 'source.txt').write_bytes(text.encode())
        sha = hashlib.sha256(text.encode()).hexdigest()
        self.manifest['sources'][0]['sha256'] = sha
        self.manifest['reviews'][0].update(source_sha256=sha, start=4, end=8, passage='blue')
        self.assertTrue(self.verify()['passed'])

    def test_metadata_insufficient_and_abstract_remains_labeled(self):
        self.manifest['sources'][0]['access'] = 'metadata'
        self.assertFalse(self.verify()['passed'])
        self.manifest['sources'][0]['access'] = 'abstract'
        report = self.verify(); self.assertTrue(report['passed'])
        self.assertEqual(report['recorded_judgments'][0]['access'], 'abstract')

    def test_duplicate_ids_and_invalid_time_or_judgment(self):
        for category in ('sources', 'reviews'):
            changed = copy.deepcopy(self.manifest); changed[category].append(copy.deepcopy(changed[category][0]))
            self.assertFalse(self.verify(changed)['passed'])
        for field, value in [('reviewed_at', '2026-10-27'), ('reviewed_at', 'never'),
                             ('judgment', 'proven'), ('rationale', ''), ('reviewer', '')]:
            changed = copy.deepcopy(self.manifest); changed['reviews'][0][field] = value
            self.assertFalse(self.verify(changed)['passed'])

    def test_traversal_absolute_and_escaping_symlink(self):
        for path in ('../source.txt', '..\\source.txt', str(self.root / 'source.txt'), 'C:\\outside.txt'):
            changed = copy.deepcopy(self.manifest); changed['sources'][0]['path'] = path
            self.assertFalse(self.verify(changed)['passed'])
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'source.txt'; target.write_text(self.text)
            link = self.root / 'escape.txt'
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('OS does not permit symlink creation')
            changed = copy.deepcopy(self.manifest); changed['sources'][0]['path'] = link.name
            self.assertFalse(self.verify(changed)['passed'])

    def test_json_rejects_duplicate_keys_nonfinite_and_oversize(self):
        path = self.root / 'input.json'
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{'):
            path.write_text(text)
            with self.assertRaises(ValueError): S.read_json(path)
        path.write_bytes(b' ' * (S.MAX_BYTES+1))
        with self.assertRaises(ValueError): S.read_json(path)
        (self.root / 'source.txt').write_bytes(b'a' * (S.MAX_BYTES+1))
        self.assertFalse(self.verify()['passed'])

    def test_cli_success_empty_failure_and_no_overwrite(self):
        source, output = self.root / 'reviews.json', self.root / 'output.json'
        source.write_text(json.dumps(self.manifest))
        command = [sys.executable, str(SKILL / 'scripts/support_tools.py'), 'review-support',
                   '--input', str(source), '--output', str(output)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        output.write_text('customized')
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2); self.assertEqual(output.read_text(), 'customized')
        source.write_text(json.dumps({'schema_version': 1, 'sources': [], 'reviews': []}))
        result = subprocess.run(command+['--force'], cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(output.read_text())['status'], 'not_checked')


if __name__ == '__main__':
    unittest.main()
