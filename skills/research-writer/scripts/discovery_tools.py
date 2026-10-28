#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded no-key OpenAlex discovery and version-pinned arXiv HTML retrieval.

Python 3.10+, standard library only. Requests are serialized in this process and
arXiv request starts are spaced by at least three seconds. Operators must also
coordinate other processes and all machines they control; this is no global
rate-limit service. No retries, pagination, PDF fallback, scripts or asset fetches.
Retrieval and provider flags never establish reading, scientific truth or rights.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT = 10
ARXIV_SPACING = 3.0
OPENALEX = 'https://api.openalex.org/works'
ARXIV = 'https://arxiv.org/html/'
_NETWORK_LOCK = threading.Lock()
_last_arxiv_start = None
_ARXIV_PATTERN = r'(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})v[1-9]\d*'
_ARXIV_RE = re.compile(_ARXIV_PATTERN)


def now():
    return datetime.now(timezone.utc).isoformat()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def arxiv_id(value):
    if not isinstance(value, str) or not re.fullmatch(_ARXIV_PATTERN, value):
        raise ValueError('arXiv ID must be a bare modern or legacy ID with an explicit positive vN')
    return value


def work_id(value):
    if not isinstance(value, str):
        raise ValueError('Invalid OpenAlex work ID')
    value = value.removeprefix('https://openalex.org/')
    if not re.fullmatch(r'W[1-9]\d*', value):
        raise ValueError('OpenAlex work ID must be W followed by a positive integer')
    return value


def normalize_doi(value):
    if not isinstance(value, str):
        raise ValueError('DOI must be a string')
    value = re.sub(r'(?i)^doi:\s*', '', value.strip())
    if re.match(r'(?i)^https?://(?:dx\.)?doi\.org/', value):
        parts = urllib.parse.urlsplit(value)
        if parts.query or parts.fragment:
            raise ValueError('DOI URL must not include a query or fragment')
        value = urllib.parse.unquote(parts.path.lstrip('/'))
    if len(value) > 1000 or not re.fullmatch(r'10\.\d{4,9}/[^\s<>"{}\\]+', value):
        raise ValueError('Invalid DOI')
    return value.lower()


def allowed_url(url):
    """Validate even direct request() callers; query parameters cannot enable keys/pages."""
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment:
            return False
        if p.hostname == 'arxiv.org' and not p.query and p.path.startswith('/html/'):
            arxiv_id(p.path[len('/html/'):])
            return True
        if p.hostname != 'api.openalex.org':
            return False
        if p.path == '/works':
            q = urllib.parse.parse_qs(p.query, keep_blank_values=True, strict_parsing=True)
            return (set(q) == {'search', 'per_page'} and all(len(v) == 1 for v in q.values())
                    and bool(q['search'][0].strip()) and len(q['search'][0]) <= 1000
                    and re.fullmatch(r'(?:[1-9]|1\d|20)', q['per_page'][0]) is not None)
        if p.query or not p.path.startswith('/works/'):
            return False
        suffix = urllib.parse.unquote(p.path[len('/works/'):])
        if suffix.startswith('https://doi.org/'):
            normalize_doi(suffix)
        else:
            work_id(suffix)
        return True
    except (ValueError, TypeError):
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even same-provider redirects may silently change a requested version.
        return None


def request(url):
    """Return status/body/receipt; never follow redirects or retry failures."""
    global _last_arxiv_start
    if not allowed_url(url):
        raise ValueError('Only fixed no-key OpenAlex and pinned arXiv HTML endpoints are permitted')
    receipt = {'url': url, 'timeout_seconds': TIMEOUT, 'max_bytes': MAX_BYTES,
               'http_status': None, 'sha256': None, 'redirects_followed': False}
    req = urllib.request.Request(url, headers={
        'User-Agent': 'research-writer-discovery-tools/0.10.0',
        'Accept': 'text/html' if url.startswith(ARXIV) else 'application/json',
        'Accept-Encoding': 'identity'})
    with _NETWORK_LOCK:
        if url.startswith(ARXIV):
            if _last_arxiv_start is not None:
                time.sleep(max(0.0, ARXIV_SPACING - (time.monotonic() - _last_arxiv_start)))
            _last_arxiv_start = time.monotonic()
        receipt['retrieved_at'] = now()
        try:
            opener = urllib.request.build_opener(RestrictedRedirect())
            with opener.open(req, timeout=TIMEOUT) as response:
                receipt['http_status'] = response.status
                receipt['content_type'] = response.headers.get('Content-Type')
                receipt['content_encoding'] = response.headers.get('Content-Encoding')
                raw = response.read(MAX_BYTES + 1)
            receipt['bytes'] = len(raw)
            receipt['sha256'] = _sha(raw)
            if len(raw) > MAX_BYTES:
                receipt['hash_scope'] = 'bounded prefix; response rejected'
                return {'status': 'failed', 'error': 'response_too_large', 'receipt': receipt}
            receipt['hash_scope'] = 'complete response bytes'
            if receipt['content_encoding'] not in (None, '', 'identity'):
                return {'status': 'failed', 'error': 'unsupported_content_encoding', 'receipt': receipt}
            return {'status': 'success', 'body': raw, 'receipt': receipt}
        except urllib.error.HTTPError as exc:
            receipt.update(http_status=exc.code,
                           retry_after=exc.headers.get('Retry-After') if exc.headers else None)
            exc.close()
            return {'status': 'unavailable' if exc.code in (404, 429) or exc.code >= 500 else 'failed',
                    'error': 'http_error', 'receipt': receipt}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {'status': 'unavailable', 'error': type(exc).__name__, 'receipt': receipt}


def _record(raw):
    if not isinstance(raw, dict):
        raise ValueError('OpenAlex record must be an object')
    wid = work_id(raw.get('id'))
    doi = normalize_doi(raw['doi']) if raw.get('doi') is not None else None
    refs = raw.get('referenced_works', [])
    if not isinstance(refs, list) or any(not isinstance(x, str) for x in refs):
        raise ValueError('Invalid referenced_works')
    for ref in refs:
        work_id(ref)
    retracted = raw.get('is_retracted')
    if retracted is not None and not isinstance(retracted, bool):
        raise ValueError('Invalid is_retracted flag')
    location = raw.get('primary_location')
    if location is not None and not isinstance(location, dict):
        raise ValueError('Invalid primary_location')
    return {'identity': 'openalex:' + wid, 'id': raw['id'], 'work_id': wid, 'doi': doi,
            'title': raw.get('title'), 'version': raw.get('version'), 'access': 'metadata',
            'full_text_retrieved': False, 'read_or_reviewed': False,
            'referenced_works': refs, 'reference_access': 'citation leads; not retrieved or read',
            'is_retracted': retracted, 'retraction_certification': 'not_certified',
            'license': location.get('license') if location else None,
            'reuse_rights': 'article-specific; unknown unless independently established',
            'open_access': raw.get('open_access'), 'primary_location': location, 'raw': raw}


def search(query, limit=10):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError('Query must contain 1–1000 characters')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError('Limit must be an integer from 1 to 20')
    result = {'status': 'failed', 'provider': 'openalex', 'query': query, 'limit': limit,
              'started_at': now(), 'records': [], 'errors': [], 'page_limit': 1,
              'coverage': 'bounded no-key first page; not exhaustive', 'exhausted': False,
              'full_text_retrieved': False, 'read_or_reviewed': False,
              'semantic_verification': 'not_performed', 'study_independence': 'not_assessed'}
    fetched = request(OPENALEX + '?' + urllib.parse.urlencode({'search': query, 'per_page': limit}))
    result['receipt'] = fetched['receipt']
    if fetched['status'] != 'success':
        return {**result, 'status': fetched['status'], 'error': fetched.get('error')}
    try:
        payload = json.loads(fetched['body'])
        items = payload['results']
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError('Invalid or oversized OpenAlex results')
        meta = payload.get('meta')
        if 'meta' in payload and not isinstance(meta, dict):
            raise ValueError('OpenAlex meta must be an object when supplied')
        count = meta.get('count') if meta is not None else None
        if meta is not None and 'count' in meta:
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError('OpenAlex meta.count must be a nonnegative integer')
            if count < len(items) or count > 0 and not items:
                raise ValueError('OpenAlex meta.count conflicts with first-page results')
        result['provider_meta'] = meta
        result['provider_hit_count'] = count
        for index, raw in enumerate(items):
            try:
                result['records'].append(_record(raw))
            except (ValueError, TypeError, KeyError) as exc:
                result['errors'].append({'index': index, 'error': str(exc)})
        result['status'] = ('partial' if result['records'] else 'failed') if result['errors'] else (
            'success' if result['records'] else 'empty')
    except (ValueError, TypeError, KeyError) as exc:
        result['error'] = 'invalid_provider_response: ' + str(exc)
    result['finished_at'] = now()
    return result


def work(work_id=None, doi=None):
    if (work_id is None) == (doi is None):
        raise ValueError('Supply exactly one work ID or DOI')
    wid = globals()['work_id'](work_id) if work_id is not None else None
    normalized = normalize_doi(doi) if doi is not None else None
    suffix = wid or urllib.parse.quote('https://doi.org/' + normalized, safe='')
    fetched = request(OPENALEX + '/' + suffix)
    result = {'status': fetched['status'], 'provider': 'openalex', 'requested_work_id': wid,
              'requested_doi': normalized, 'receipt': fetched['receipt'],
              'identity_status': 'unresolved', 'full_text_retrieved': False,
              'read_or_reviewed': False, 'semantic_verification': 'not_performed',
              'coverage': 'one exact metadata lookup; references remain citation leads'}
    if fetched['status'] != 'success':
        return {**result, 'error': fetched.get('error')}
    try:
        record = _record(json.loads(fetched['body']))
        if wid is not None and record['work_id'] != wid or normalized is not None and record['doi'] != normalized:
            raise ValueError('Returned work identity does not match request')
        return {**result, 'record': record, 'identity_status': 'identity_verified'}
    except (ValueError, TypeError, KeyError) as exc:
        return {**result, 'status': 'failed', 'error': str(exc)}


class _Node:
    def __init__(self, tag, attrs, parent, order):
        self.tag, self.attrs, self.parent, self.order = tag, dict(attrs), parent, order
        self.children, self.closed = [], False

    def classes(self):
        return set(self.attrs.get('class', '').split())


_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP = {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'iframe', 'object', 'embed', 'svg', 'canvas', 'form', 'button', 'template'}
_BLOCK = {'article', 'section', 'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'table', 'tr', 'blockquote', 'br'}


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('root', [], None, 0)
        self.stack, self.nodes = [self.root], []

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 200000 or len(self.stack) > 512:
            raise ValueError('HTML structure limit exceeded')
        normalized = {}
        for key, value in attrs:
            if key in normalized:
                # Some official HTML duplicates presentation-only tooltips.
                # First title wins; identity, visibility and URL duplicates fail.
                if key == 'title':
                    continue
                raise ValueError('Duplicate HTML attributes')
            normalized[key] = value or ''
        node = _Node(tag, normalized.items(), self.stack[-1], len(self.nodes) + 1)
        self.nodes.append(node)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)
        else:
            node.closed = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _ancestors(node):
    while node.parent is not None:
        node = node.parent
        yield node


def _skip(node):
    return node.tag in _SKIP or 'ltx_page_logo' in node.classes() or node.attrs.get('aria-hidden') == 'true' or 'hidden' in node.attrs


def _plain(node):
    if _skip(node):
        return ''
    return ' '.join(c if isinstance(c, str) else _plain(c) for c in node.children)


def _extract(article):
    pieces, spans, size = [], [], 0

    def append(value):
        nonlocal size
        pieces.append(value)
        size += len(value)

    def newline():
        if pieces and not pieces[-1].endswith('\n'):
            append('\n')

    def visit(node):
        if _skip(node):
            return
        if node.tag in _BLOCK:
            newline()
        start = size
        for child in node.children:
            if isinstance(child, str):
                value = re.sub(r'\s+', ' ', child).strip()
                if value:
                    if pieces and not pieces[-1].endswith(('\n', ' ')):
                        append(' ')
                    append(value)
            else:
                visit(child)
        end = size
        if node.tag == 'section':
            spans.append((node, start, end))
        if node.tag in _BLOCK:
            newline()

    visit(article)
    text = ''.join(pieces).rstrip() + '\n'
    sections = []
    for number, (node, start, end) in enumerate(sorted(spans, key=lambda x: x[1]), 1):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        title_node = next((n for n in node.children if isinstance(n, _Node) and n.tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}), None)
        sections.append({'locator': 'article/section[' + str(number) + ']', 'id': node.attrs.get('id'),
                         'title': re.sub(r'\s+', ' ', _plain(title_node)).strip() if title_node else None,
                         'start': start, 'end': end, 'text': text[start:end]})
    return text, sections


def parse_arxiv_html(raw_bytes, identifier):
    identifier = arxiv_id(identifier)
    result = {'status': 'failed', 'provider': 'arxiv', 'arxiv_id': identifier,
              'version': identifier.rsplit('v', 1)[1], 'version_identifier': 'arxiv:' + identifier,
              'access': 'unavailable', 'full_text_retrieved': False, 'read_or_reviewed': False,
              'identity_status': 'unresolved', 'license': None, 'reuse_rights': 'unknown; article-specific',
              'semantic_verification': 'not_performed',
              'conversion_limits': 'HTML conversion may omit or alter equations, tables and other content'}
    try:
        if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_BYTES:
            raise ValueError('HTML must be bytes within the 10 MiB limit')
        result['raw_sha256'] = _sha(raw_bytes)
        parser = _HTML()
        parser.feed(raw_bytes.decode('utf-8-sig'))
        parser.close()
        articles = [n for n in parser.nodes if n.tag == 'article' and 'ltx_document' in n.classes()]
        if len(articles) != 1 or not articles[0].closed:
            raise ValueError('One complete article.ltx_document body is required')
        article = articles[0]
        signals = []
        for node in parser.nodes:
            ancestors = list(_ancestors(node))
            if node.order >= article.order or article in ancestors or any(_skip(n) and n.tag != 'header' for n in ancestors):
                continue
            if node.tag == 'div' and node.attrs.get('id') == 'watermark-tr':
                marker = _plain(node)
                found = re.findall(r'arXiv:\s*(' + _ARXIV_PATTERN + r')(?![\w./])', marker, flags=re.I)
                signals.extend({'kind': 'watermark-tr', 'id': x} for x in found)
            if node.tag == 'a' and 'header-button' in node.classes():
                href = urllib.parse.urlsplit(node.attrs.get('href', ''))
                if href.scheme not in ('', 'https') or href.netloc not in ('', 'arxiv.org') or href.query or href.fragment:
                    continue
                match = re.fullmatch(r'/(?:abs|pdf)/(' + _ARXIV_PATTERN + r')(?:\.pdf)?', href.path)
                if match:
                    signals.append({'kind': 'header-button', 'id': match.group(1)})
        result['identity_signals'] = signals
        if not signals or {s['id'] for s in signals} != {identifier}:
            raise ValueError('Missing, mismatched or conflicting structural article identity/version')
        substantive = []
        for node in parser.nodes:
            if node.tag != 'p' or article not in list(_ancestors(node)):
                continue
            chain = [node, *list(_ancestors(node))]
            if any(_skip(n) or {'ltx_abstract', 'ltx_bibliography'} & n.classes() or n.attrs.get('id') == 'abstract' for n in chain):
                continue
            substantive.append(_plain(node))
        prose = re.sub(r'\s+', ' ', ' '.join(substantive)).strip()
        if len(prose) < 80 or len(prose.split()) < 12:
            raise ValueError('Substantive article prose unavailable; metadata/abstract is not full text')
        text, sections = _extract(article)
        return {**result, 'status': 'success', 'identity_status': 'identity_verified',
                'access': 'full_text', 'full_text_retrieved': True, 'text': text,
                'text_sha256': _sha(text.encode('utf-8')), 'sections': sections,
                'offset_unit': 'Unicode code points in LF-normalized extracted text'}
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        return {**result, 'error': str(exc)}


def arxiv_fulltext(identifier):
    identifier = arxiv_id(identifier)
    fetched = request(ARXIV + identifier)
    if fetched['status'] != 'success':
        return {'status': fetched['status'], 'provider': 'arxiv', 'arxiv_id': identifier,
                'access': 'unavailable', 'identity_status': 'unresolved', 'full_text_retrieved': False,
                'read_or_reviewed': False, 'error': fetched.get('error'), 'receipt': fetched['receipt'],
                'license': None, 'reuse_rights': 'unknown; article-specific'}
    return {**parse_arxiv_html(fetched['body'], identifier), 'receipt': fetched['receipt']}


def _preflight(paths):
    resolved = [os.path.normcase(str(p.resolve())) for p in paths]
    if len(set(resolved)) != len(paths):
        raise ValueError('Text and report outputs must differ')
    for path in paths:
        if os.path.lexists(path):
            raise FileExistsError('Existing output preserved; choose a new path')
        if not path.parent.is_dir():
            raise ValueError('Output parent directory must already exist')
        if not os.access(path.parent, os.W_OK):
            raise PermissionError('Output parent is not writable')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('search', 'work', 'arxiv-fulltext'):
        command = subs.add_parser(name)
        command.add_argument('--output', required=True)
        if name == 'search':
            command.add_argument('--query', required=True)
            command.add_argument('--limit', type=int, default=10)
        elif name == 'work':
            identity = command.add_mutually_exclusive_group(required=True)
            identity.add_argument('--work-id')
            identity.add_argument('--doi')
        else:
            command.add_argument('--arxiv-id', required=True)
            command.add_argument('--text-output', required=True)
    args = parser.parse_args(argv)
    created = []
    try:
        output = Path(args.output)
        paths = [output] + ([Path(args.text_output)] if args.command == 'arxiv-fulltext' else [])
        _preflight(paths)
        if args.command == 'search':
            result = search(args.query, args.limit)
        elif args.command == 'work':
            result = work(args.work_id, args.doi)
        else:
            result = arxiv_fulltext(args.arxiv_id)
            if result['status'] == 'success':
                text_path = paths[1]
                with text_path.open('x', encoding='utf-8', newline='\n') as stream:
                    created.append(text_path)
                    stream.write(result.pop('text'))
                result['text_path'] = str(text_path.resolve())
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            created.append(output)
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps({'status': result['status'], 'output': str(output)}))
        return 0 if result['status'] in ('success', 'empty') else 2
    except (ValueError, TypeError, OSError) as exc:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        print(json.dumps({'status': 'failed', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
