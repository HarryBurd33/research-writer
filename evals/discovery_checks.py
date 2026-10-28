#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline public contracts for bounded discovery; no live network requests."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('discovery_tools', ROOT / 'skills/research-writer/scripts/discovery_tools.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)
ID = '2005.11401v4'
PROSE = ('Results preserve the original participants and their observed outcomes. '
         'The independent sample contains enough detail to explain the measured result. ')


def html(marker=None, body=None, suffix=''):
    marker = '<div id="watermark-tr">arXiv:' + ID + '</div>' if marker is None else marker
    body = '<section id="s1"><h2>Results α</h2><p>' + PROSE + ' café &amp; β.</p></section>' if body is None else body
    return ('<!doctype html><html><body>' + marker + '<article class="ltx_document">' + body + '</article>' + suffix + '</body></html>').encode('utf-8')


def record(wid='W123', doi='https://doi.org/10.1234/test'):
    return {'id': 'https://openalex.org/' + wid, 'doi': doi, 'title': 'A study',
            'referenced_works': ['https://openalex.org/W55'], 'is_retracted': False,
            'open_access': {'is_oa': True, 'oa_url': 'https://publisher.invalid/full'},
            'primary_location': {'license': None, 'pdf_url': 'https://publisher.invalid/file.pdf'}}


def fetched(value):
    raw = json.dumps(value).encode()
    return {'status': 'success', 'body': raw,
            'receipt': {'url': 'fixture', 'retrieved_at': '2026-10-28T00:00:00Z',
                        'http_status': 200, 'sha256': hashlib.sha256(raw).hexdigest()}}


class DiscoveryChecks(unittest.TestCase):
    def test_search_scope_and_no_fulltext_upgrade(self):
        with patch.object(d, 'request', return_value=fetched({'results': [record()], 'meta': {'count': 200, 'cost_usd': 0.001}})) as req:
            result = d.search('quantitative evidence', 2)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(req.call_count, 1)
        self.assertIn('per_page=2', req.call_args.args[0])
        self.assertNotIn('cursor', req.call_args.args[0])
        self.assertFalse(result['exhausted'])
        item = result['records'][0]
        self.assertEqual(item['access'], 'metadata')
        self.assertFalse(item['read_or_reviewed'])
        self.assertFalse(item['full_text_retrieved'])
        self.assertEqual(item['referenced_works'], ['https://openalex.org/W55'])
        self.assertEqual(item['retraction_certification'], 'not_certified')
        self.assertIsNone(item['license'])

    def test_search_empty_is_distinct_from_unavailable(self):
        with patch.object(d, 'request', return_value=fetched({'results': []})):
            self.assertEqual(d.search('x')['status'], 'empty')
        with patch.object(d, 'request', return_value={'status': 'unavailable', 'error': 'TimeoutError', 'receipt': {}}):
            self.assertEqual(d.search('x')['status'], 'unavailable')

    def test_partial_invalid_record_preserves_valid(self):
        with patch.object(d, 'request', return_value=fetched({'results': [record(), {'id': 'broken'}]})):
            result = d.search('x', 2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['errors'][0]['index'], 1)

    def test_meta_counts_invalid_never_report_empty_or_success(self):
        for meta in [None, [], 'bad', {'count': -1}, {'count': True},
                     {'count': 1.5}, {'count': '0'}, {'count': None}]:
            for items in [[], [record()]]:
                with self.subTest(meta=meta, items=len(items)), patch.object(d, 'request', return_value=fetched({'meta': meta, 'results': items})):
                    self.assertEqual(d.search('x')['status'], 'failed')

    def test_meta_count_first_page_consistency(self):
        for count, items in [(0, [record()]), (1, []), (1, [record(), record('W124')])]:
            with self.subTest(count=count, items=len(items)), patch.object(d, 'request', return_value=fetched({'meta': {'count': count}, 'results': items})):
                self.assertEqual(d.search('x')['status'], 'failed')
        for count, items, expected in [(0, [], 'empty'), (1, [record()], 'success'), (99, [record()], 'success')]:
            with self.subTest(count=count), patch.object(d, 'request', return_value=fetched({'meta': {'count': count}, 'results': items})):
                self.assertEqual(d.search('x')['status'], expected)

    def test_missing_meta_and_count_remain_unknown(self):
        for payload in [{'results': []}, {'meta': {}, 'results': []}]:
            with self.subTest(payload=payload), patch.object(d, 'request', return_value=fetched(payload)):
                result = d.search('x')
            self.assertEqual(result['status'], 'empty')
            self.assertIsNone(result['provider_hit_count'])
        self.assertEqual(result['provider_meta'], {})

    def test_malformed_json_and_shape(self):
        for value in [b'{bad', b'[]', b'{"results":{}}', b'{"results":[{},{}]}']:
            with self.subTest(value=value), patch.object(d, 'request', return_value={'status': 'success', 'body': value, 'receipt': {}}):
                self.assertEqual(d.search('x', 1)['status'], 'failed')

    def test_limits_rejected_before_request(self):
        with patch.object(d, 'request') as req:
            for limit in [0, 21, True, 1.5, '2']:
                with self.assertRaises(ValueError):
                    d.search('x', limit)
            for query in ['', '   ', 'x' * 1001, None]:
                with self.assertRaises(ValueError):
                    d.search(query)
        req.assert_not_called()

    def test_exact_work_lookup_and_doi_normalization(self):
        with patch.object(d, 'request', return_value=fetched(record())) as req:
            result = d.work(doi='DOI:10.1234/TEST')
        self.assertEqual(result['identity_status'], 'identity_verified')
        self.assertIn('https%3A%2F%2Fdoi.org%2F10.1234%2Ftest', req.call_args.args[0])
        with patch.object(d, 'request', return_value=fetched(record('W124'))):
            self.assertEqual(d.work(work_id='W123')['status'], 'failed')
        with patch.object(d, 'request', return_value=fetched(record(doi='10.1234/other'))):
            self.assertEqual(d.work(doi='10.1234/test')['status'], 'failed')

    def test_work_bad_identity_and_exclusive_inputs(self):
        with patch.object(d, 'request') as req:
            for kwargs in [{}, {'work_id': 'W1', 'doi': '10.1234/x'}, {'work_id': 'W0'}, {'doi': 'https://evil.invalid/a'}, {'work_id': '../W1'}]:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    d.work(**kwargs)
        req.assert_not_called()

    def test_fixed_endpoint_allowlist(self):
        for url in [d.OPENALEX + '?search=x&per_page=20', d.OPENALEX + '/W123', d.ARXIV + ID,
                    d.ARXIV + 'hep-th/9901001v2']:
            self.assertTrue(d.allowed_url(url), url)
        for url in ['http://arxiv.org/html/' + ID, 'https://evil.invalid/html/' + ID,
                    'https://arxiv.org/abs/' + ID, d.ARXIV + ID + '?x=1',
                    'https://user@arxiv.org/html/' + ID, 'https://arxiv.org:444/html/' + ID,
                    d.OPENALEX + '?search=x&per_page=1&api_key=secret',
                    d.OPENALEX + '?search=x&per_page=1&cursor=*',
                    d.OPENALEX + '?search=x&per_page=1&page=2',
                    d.OPENALEX + '?search=x&search=y&per_page=1',
                    d.ARXIV + '2005.11401', d.OPENALEX + '/W1?api_key=x']:
            self.assertFalse(d.allowed_url(url), url)

    def test_transport_timeout_429_and_no_redirect(self):
        timeout = urllib.error.URLError(TimeoutError())
        rate = urllib.error.HTTPError(d.OPENALEX + '/W1', 429, 'limited', {'Retry-After': '8'}, None)
        for error in [timeout, rate]:
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with patch.object(d.urllib.request, 'build_opener', return_value=opener):
                result = d.request(d.OPENALEX + '/W1')
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
            self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(result['receipt']['http_status'], 429)
        self.assertEqual(result['receipt']['retry_after'], '8')
        self.assertIsNone(d.RestrictedRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))

    def test_transport_body_bound_and_hash(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {}
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        for raw, expected in [(b'hello', 'success'), (b'x' * (d.MAX_BYTES + 1), 'failed')]:
            response.read.return_value = raw
            with patch.object(d.urllib.request, 'build_opener', return_value=opener):
                result = d.request(d.OPENALEX + '/W1')
            self.assertEqual(result['status'], expected)
            response.read.assert_called_with(d.MAX_BYTES + 1)
            self.assertEqual(result['receipt']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_arxiv_serial_start_spacing(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status, response.headers, response.read.return_value = 200, {}, b'html'
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch.object(d, '_last_arxiv_start', None), patch.object(d.time, 'monotonic', side_effect=[100.0, 100.5, 103.0]), patch.object(d.time, 'sleep') as sleep, patch.object(d.urllib.request, 'build_opener', return_value=opener):
            d.request(d.ARXIV + ID)
            d.request(d.ARXIV + ID)
        sleep.assert_called_once_with(2.5)

    def test_unicode_extraction_hashes_and_offsets(self):
        raw = html()
        result = d.parse_arxiv_html(raw, ID)
        self.assertEqual(result['status'], 'success')
        self.assertIn('café & β.', result['text'])
        self.assertEqual(result['raw_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['text_sha256'], hashlib.sha256(result['text'].encode()).hexdigest())
        self.assertEqual(result['version_identifier'], 'arxiv:' + ID)
        self.assertFalse(result['read_or_reviewed'])
        for section in result['sections']:
            self.assertEqual(section['text'], result['text'][section['start']:section['end']])
        self.assertEqual(result, d.parse_arxiv_html(raw, ID))

    def test_legacy_identity_and_header_only(self):
        identifier = 'hep-th/9901001v2'
        marker = '<header><a class="header-button" href="https://arxiv.org/pdf/' + identifier + '">PDF</a></header>'
        result = d.parse_arxiv_html(html(marker=marker), identifier)
        self.assertEqual(result['status'], 'success')

    def test_wrong_identity_bibliography_and_asset_traps(self):
        for marker in ['', '<div id="watermark-tr">arXiv:2005.11401v3</div>',
                       '<div class="ltx_page_logo">arXiv:' + ID + '</div>',
                       '<script>arXiv:' + ID + '</script>',
                       '<img src="' + ID + '.png">',
                       '<a href="/abs/' + ID + '">Article</a>']:
            raw = html(marker=marker, body='<section><p>' + PROSE + 'Bibliography: arXiv:' + ID + '</p></section>')
            self.assertEqual(d.parse_arxiv_html(raw, ID)['status'], 'failed', marker)

    def test_identity_inside_or_after_article_not_accepted(self):
        for raw in [html(marker='', body='<div id="watermark-tr">arXiv:' + ID + '</div><p>' + PROSE + '</p>'),
                    html(marker='', suffix='<div id="watermark-tr">arXiv:' + ID + '</div>')]:
            self.assertEqual(d.parse_arxiv_html(raw, ID)['status'], 'failed')

    def test_conflicting_structural_signals_fail(self):
        marker = '<div id="watermark-tr">arXiv:' + ID + '</div><a class="header-button" href="/abs/2005.11401v3">Abs</a>'
        self.assertEqual(d.parse_arxiv_html(html(marker=marker), ID)['status'], 'failed')

    def test_duplicate_title_is_presentation_only_first_wins(self):
        marker = '<div id="watermark-tr">arXiv:' + ID + '</div><a title="First tooltip" title="Second tooltip">Report issue</a>'
        result = d.parse_arxiv_html(html(marker=marker), ID)
        self.assertEqual(result['status'], 'success')
        parser = d._HTML()
        parser.feed('<a title="First tooltip" title="Second tooltip">Report issue</a>')
        self.assertEqual(parser.nodes[0].attrs['title'], 'First tooltip')

    def test_duplicate_structural_or_visibility_attributes_fail(self):
        for attribute, first, second in [
                ('id', 'watermark-tr', 'other'), ('class', 'ltx_document', 'other'),
                ('href', '/abs/' + ID, '/abs/2005.11401v3'),
                ('hidden', '', ''), ('aria-hidden', 'false', 'true'),
                ('style', '', 'display:none'), ('data-target', 'a', 'b')]:
            marker = '<div id="watermark-tr">arXiv:' + ID + '</div><a ' + attribute + '="' + first + '" ' + attribute + '="' + second + '">Link</a>'
            with self.subTest(attribute=attribute):
                self.assertEqual(d.parse_arxiv_html(html(marker=marker), ID)['status'], 'failed')

    def test_duplicate_titles_do_not_override_wrong_identity_trap(self):
        marker = '<div id="watermark-tr" title="One" title="Two">arXiv:2005.11401v3</div>'
        body = '<section><p>' + PROSE + ' Bibliography: arXiv:' + ID + '</p></section>'
        self.assertEqual(d.parse_arxiv_html(html(marker=marker, body=body), ID)['status'], 'failed')

    def test_script_navigation_and_assets_are_removed(self):
        body = '<section><h2>Results</h2><nav>navigation_secret</nav><script>script_secret</script><style>style_secret</style><iframe>iframe_secret</iframe><svg>asset_secret</svg><p>' + PROSE + '</p></section>'
        result = d.parse_arxiv_html(html(body=body), ID)
        self.assertEqual(result['status'], 'success')
        for token in ['navigation_secret', 'script_secret', 'style_secret', 'iframe_secret', 'asset_secret']:
            self.assertNotIn(token, result['text'])

    def test_missing_body_abstract_only_and_broken_utf8(self):
        for raw in [b'<div id="watermark-tr">arXiv:2005.11401v4</div>',
                    html(body='<p>Only metadata.</p>'),
                    html(body='<div class="ltx_abstract"><p>' + PROSE + '</p></div>'),
                    html()[:-70], b'\xff\xfe']:
            self.assertEqual(d.parse_arxiv_html(raw, ID)['status'], 'failed')

    def test_arxiv_unavailable_has_no_atom_or_pdf_dependency(self):
        with patch.object(d, 'request', return_value={'status': 'unavailable', 'error': 'http_error', 'receipt': {'http_status': 404}}) as req:
            result = d.arxiv_fulltext(ID)
        req.assert_called_once_with(d.ARXIV + ID)
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['full_text_retrieved'])

    def test_cli_preflights_both_paths_before_network(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            base = Path(folder)
            old = base / 'old.txt'
            old.write_text('preserve', encoding='utf-8')
            cases = [(base / 'new.json', old), (old, base / 'new.txt'),
                     (base / 'same', base / 'same'), (base / 'missing' / 'report.json', base / 'text')]
            with patch.object(d, 'request') as req:
                for output, text in cases:
                    self.assertEqual(d.main(['arxiv-fulltext', '--arxiv-id', ID, '--output', str(output), '--text-output', str(text)]), 2)
            req.assert_not_called()
            self.assertEqual(old.read_text(encoding='utf-8'), 'preserve')

    def test_cli_success_text_matches_hash_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            base = Path(folder)
            output, text = base / 'report.json', base / 'paper.txt'
            args = ['arxiv-fulltext', '--arxiv-id', ID, '--output', str(output), '--text-output', str(text)]
            with patch.object(d, 'request', return_value={'status': 'success', 'body': html(), 'receipt': {}}) as req:
                self.assertEqual(d.main(args), 0)
                self.assertEqual(d.main(args), 2)
            self.assertEqual(req.call_count, 1)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertNotIn('text', report)
            self.assertEqual(report['text_sha256'], hashlib.sha256(text.read_bytes()).hexdigest())
            self.assertNotIn(b'\r', text.read_bytes())

    def test_failed_fetch_writes_report_without_fake_text(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            base = Path(folder)
            output, text = base / 'report.json', base / 'paper.txt'
            with patch.object(d, 'request', return_value={'status': 'unavailable', 'error': 'TimeoutError', 'receipt': {}}):
                self.assertEqual(d.main(['arxiv-fulltext', '--arxiv-id', ID, '--output', str(output), '--text-output', str(text)]), 2)
            self.assertFalse(text.exists())
            self.assertEqual(json.loads(output.read_text())['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
