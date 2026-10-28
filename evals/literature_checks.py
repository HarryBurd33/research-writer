#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline literature adapter regressions; all public services are mocked."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts/literature_tools.py'
spec = importlib.util.spec_from_file_location('literature', SCRIPT)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def fetched(payload, raw=False):
    return {'status': 'success', 'body': payload if raw else json.dumps(payload).encode(),
            'receipt': {'url': 'https://fixture.invalid/not-requested', 'retrieved_at': 'fixture-date'}}


def page(items, cursor=None):
    return fetched({'message': {'items': items, 'next-cursor': cursor, 'total-results': 3}})


ARTICLE = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "https://external.invalid/never-fetch.dtd">
<article><front><article-meta><article-id pub-id-type="pmcid">PMC1234</article-id>
<title-group><article-title>Fixture paper</article-title></title-group>
<permissions><copyright-statement>Fixture author</copyright-statement>
<license license-type="CC-BY"><license-p>Creative Commons Attribution</license-p></license></permissions>
</article-meta></front><body><sec><title>Results</title><p>The control signal was zero.</p></sec></body></article>'''


class LiteratureChecks(unittest.TestCase):
    def test_pagination_and_bounded_coverage(self):
        with patch.object(L, 'request', side_effect=[page([{'DOI': '10.1234/A'}], 'next'), page([], None)]) as get:
            result = L.search('crossref', 'topic', 2, 1, 'type:journal-article')
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['exhausted'])
        self.assertEqual(len(result['pages']), 2)
        self.assertIn('cursor=next', get.call_args.args[0])
        self.assertIn('filter=type%3Ajournal-article', get.call_args.args[0])
        with patch.object(L, 'request', return_value=page([{'DOI': '10.1234/A'}], 'next')):
            bounded = L.search('crossref', 'topic', 1, 1)
        self.assertFalse(bounded['exhausted'])
        self.assertEqual(bounded['next_cursor'], 'next')

    def test_repeated_cursor_and_partial_failure(self):
        with patch.object(L, 'request', return_value=page([{'DOI': '10.1234/A'}], '*')):
            self.assertEqual(L.search('crossref', 'topic', 5, 1)['status'], 'partial')
        failure = {'status': 'unavailable', 'error': 'http_error', 'receipt': {'http_status': 429, 'retry_after': '120'}}
        with patch.object(L, 'request', side_effect=[page([{'DOI': '10.1234/A'}], 'next'), failure]) as get:
            result = L.search('crossref', 'topic', 5, 1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(get.call_count, 2)
        self.assertFalse(result['exhausted'])
        self.assertEqual(result['pages'][1]['retry_after'], '120')

    def test_conflicting_versions_and_provenance_retained(self):
        a = {'DOI': '10.1234/A', 'title': ['first'], 'version': 'v1'}
        b = {'DOI': '10.1234/a', 'title': ['second'], 'version': 'v2'}
        with patch.object(L, 'request', return_value=page([a, b])):
            result = L.search('crossref', 'topic', 1, 2)
        record = result['records'][0]
        self.assertEqual(len(result['records']), 1)
        self.assertTrue(record['conflicting_variants'])
        self.assertEqual(record['variants'], [a, b])
        self.assertEqual(len(record['provenance']), 2)
        self.assertEqual(record['access'], 'metadata')
        self.assertFalse(record['full_text_retrieved'])
        self.assertIn('not_assessed', result['evidence_families'])

    def test_provider_malformed_id_and_json(self):
        for response in [page([{'DOI': 'bad'}]), fetched({'message': {'items': 'bad'}}),
                         fetched(b'not json', True), fetched({'message': {'items': [], 'next-cursor': 4}})]:
            with self.subTest(response=response), patch.object(L, 'request', return_value=response):
                self.assertEqual(L.search('crossref', 'topic')['status'], 'failed')

    def test_europepmc_abstract_is_not_full_text(self):
        response = {'hitCount': 1, 'resultList': {'result': [{'id': '1234', 'source': 'MED',
                    'doi': '10.1234/A', 'abstractText': 'A short abstract',
                    'fullTextUrlList': {'fullTextUrl': [{'url': 'https://publisher.invalid/paper'}]}}]}}
        with patch.object(L, 'request', return_value=fetched(response)):
            result = L.search('europepmc', 'topic')
        self.assertEqual(result['records'][0]['access'], 'abstract')
        self.assertFalse(result['records'][0]['full_text_retrieved'])
        response['resultList']['result'][0]['id'] = '../invalid'
        with patch.object(L, 'request', return_value=fetched(response)):
            self.assertEqual(L.search('europepmc', 'topic')['status'], 'failed')

    def test_search_input_bounds(self):
        for args in [('crossref', '', 1, 1), ('private', 'x', 1, 1), ('crossref', 'x', 6, 1),
                     ('crossref', 'x', True, 1), ('crossref', 'x', 1, 21), ('crossref', 'x', 1, False)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                L.search(*args)
        with self.assertRaises(ValueError):
            L.search('europepmc', 'x', filters='private')

    def test_correction_notice_direction_and_identity(self):
        update = {'DOI': '10.1234/NOTICE', 'update-to': [{'DOI': '10.1234/A', 'type': 'retraction'}],
                  'relation': {'is-correction-of': [{'id': '10.1234/A', 'id-type': 'doi'}]}}
        with patch.object(L, 'request', side_effect=[fetched({'message': {'DOI': '10.1234/A'}}), page([update])]) as get:
            result = L.updates('10.1234/A')
        self.assertEqual(result['identity_status'], 'identity_verified')
        self.assertEqual(result['notices']['records'][0]['update_to'], update['update-to'])
        self.assertIn('updates%3A10.1234%2Fa', get.call_args.args[0])
        self.assertIn('absence is not certified', result['coverage'])
        with patch.object(L, 'request', return_value=fetched({'message': {'DOI': '10.1234/WRONG'}})) as get:
            self.assertEqual(L.updates('10.1234/A')['status'], 'failed')
            self.assertEqual(get.call_count, 1)

    def test_http_unavailable_failed_and_retry_after(self):
        for code, status in [(429, 'unavailable'), (503, 'unavailable'), (403, 'failed'), (404, 'unavailable')]:
            err = urllib.error.HTTPError('https://api.crossref.org/v1/works', code, 'fixture', {'Retry-After': '30'}, None)
            with self.subTest(code=code), patch.object(L.urllib.request.OpenerDirector, 'open', side_effect=err):
                result = L.request('https://api.crossref.org/v1/works')
                self.assertEqual(result['status'], status)
                self.assertEqual(result['receipt']['retry_after'], '30')
        for err in (TimeoutError(), urllib.error.URLError('offline')):
            with patch.object(L.urllib.request.OpenerDirector, 'open', side_effect=err):
                self.assertEqual(L.request('https://api.crossref.org/v1/works')['status'], 'unavailable')

    def test_redirect_and_endpoint_boundary(self):
        for target in ['http://api.crossref.org/v1/works', 'https://localhost/x', 'https://127.0.0.1/x',
                       'https://api.crossref.org:444/v1/works', 'https://evil.invalid/v1/works',
                       'https://api.crossref.org/private', 'https://user:pw@api.crossref.org/v1/works']:
            with self.subTest(target=target), self.assertRaises(ValueError):
                L.request(target)
        handler = L.RestrictedRedirect()
        req = urllib.request.Request('https://api.crossref.org/v1/works')
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(req, None, 302, 'Moved', {}, 'https://127.0.0.1/private')

    def test_fulltext_external_dtd_identity_license_and_hash(self):
        with patch.object(L, 'request', return_value=fetched(ARTICLE, True)) as get:
            result = L.fulltext('PMC1234')
        self.assertEqual(get.call_count, 1)  # external DTD is never requested
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['identity_status'], 'identity_verified')
        self.assertTrue(result['full_text_retrieved'])
        self.assertFalse(result['read_or_reviewed'])
        self.assertEqual(result['semantic_verification'], 'not_performed')
        self.assertIsNone(result['publisher_version'])
        self.assertEqual(result['text_sha256'], hashlib.sha256(result['text'].encode()).hexdigest())
        self.assertEqual(result['license'][0]['attributes']['license-type'], 'CC-BY')
        self.assertIn('zero', result['sections'][0]['text'])

    def test_fulltext_entity_mismatch_missing_body_and_unknown_rights(self):
        for raw in [ARTICLE.replace(b'PMC1234', b'PMC9876'), b'<html>unavailable</html>',
                    b'<!DOCTYPE article [<!ENTITY x "expanded">]><article>&x;</article>',
                    ARTICLE.replace(b'<body>', b'<absent>').replace(b'</body>', b'</absent>')]:
            with self.subTest(raw=raw[:100]), patch.object(L, 'request', return_value=fetched(raw, True)):
                result = L.fulltext('PMC1234')
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['full_text_retrieved'])
        raw = ARTICLE.replace(b'<license license-type="CC-BY"><license-p>Creative Commons Attribution</license-p></license>', b'')
        with patch.object(L, 'request', return_value=fetched(raw, True)):
            self.assertIsNone(L.fulltext('PMC1234')['license'])
        for identity in ['../PMC1234', 'https://evil.invalid', 'PMC0']:
            with self.assertRaises(ValueError):
                L.fulltext(identity)

    def test_quoted_doctype_delimiter_cannot_hide_internal_subset(self):
        start = ARTICLE.index(b'<!DOCTYPE')
        end = ARTICLE.index(b'>', start) + 1
        for declaration in (b'<!DOCTYPE article SYSTEM ">" [<!ATTLIST article foo CDATA "bar">]>',
                            b"<!DOCTYPE article SYSTEM '>' [<!ATTLIST article foo CDATA 'bar'>]>"):
            raw = ARTICLE[:start] + declaration + ARTICLE[end:]
            with self.subTest(declaration=declaration), patch.object(L, 'request', return_value=fetched(raw, True)):
                result = L.fulltext('PMC1234')
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['full_text_retrieved'])
            self.assertIn('Internal DTD', result['error'])
        # Quoted brackets in a harmless external identifier are not a subset.
        raw = ARTICLE[:start] + b'<!DOCTYPE article SYSTEM "https://external.invalid/[quoted]>">' + ARTICLE[end:]
        with patch.object(L, 'request', return_value=fetched(raw, True)):
            self.assertEqual(L.fulltext('PMC1234')['status'], 'success')

    def test_cli_no_clobber_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preserve.json'
            path.write_text('user edits', encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), 'search', '--provider', 'crossref',
                                     '--query', 'test', '--output', str(path)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_text(encoding='utf-8'), 'user edits')


if __name__ == '__main__':
    unittest.main()
