#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded public literature retrieval. Retrieval is never semantic verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

MAX_BYTES = 10 * 1024 * 1024
BASES = {'crossref': 'https://api.crossref.org/v1/works',
         'europepmc': 'https://www.ebi.ac.uk/europepmc/webservices/rest/'}


def now():
    return datetime.now(timezone.utc).isoformat()


def doi(value):
    if not isinstance(value, str):
        raise ValueError('DOI must be a string')
    value = re.sub(r'(?i)^doi:\s*', '', value.strip())
    if re.match(r'(?i)^https?://(?:dx\.)?doi\.org/', value):
        value = urllib.parse.unquote(urllib.parse.urlsplit(value).path.lstrip('/'))
    if not re.fullmatch(r'10\.\d{4,9}/[^\s<>"{}]+', value):
        raise ValueError('Invalid DOI')
    return value.lower()


def pmcid(value):
    if not isinstance(value, str) or not re.fullmatch(r'PMC[1-9]\d*', value.upper()):
        raise ValueError('PMCID must be PMC followed by a positive integer')
    return value.upper()


def allowed_url(url):
    p = urllib.parse.urlsplit(url)
    return (p.scheme == 'https' and not p.username and not p.password and
            p.port in (None, 443) and
            ((p.hostname == 'api.crossref.org' and (p.path == '/v1/works' or p.path.startswith('/v1/works/'))) or
             (p.hostname == 'www.ebi.ac.uk' and p.path.startswith('/europepmc/webservices/rest/'))))


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl) or urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            raise urllib.error.URLError('Redirect outside fixed provider endpoint blocked')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url):
    if not allowed_url(url):
        raise ValueError('Only fixed public provider endpoints are permitted')
    receipt = {'url': url, 'retrieved_at': now(), 'timeout_seconds': 10, 'max_bytes': MAX_BYTES}
    req = urllib.request.Request(url, headers={'User-Agent': 'research-writer-literature-tools/0.6.2',
                                               'Accept': 'application/json, application/xml;q=0.9'})
    try:
        opener = urllib.request.build_opener(RestrictedRedirect())
        with opener.open(req, timeout=10) as response:
            raw = response.read(MAX_BYTES + 1)
            receipt['http_status'] = response.status
        if len(raw) > MAX_BYTES:
            return {'status': 'failed', 'error': 'response_too_large', 'receipt': receipt}
        receipt['sha256'] = hashlib.sha256(raw).hexdigest()
        return {'status': 'success', 'body': raw, 'receipt': receipt}
    except urllib.error.HTTPError as exc:
        receipt.update(http_status=exc.code, retry_after=exc.headers.get('Retry-After') if exc.headers else None)
        return {'status': 'unavailable' if exc.code in (404, 429) or exc.code >= 500 else 'failed',
                'error': 'http_error', 'receipt': receipt}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'status': 'unavailable', 'error': type(exc).__name__, 'receipt': receipt}


def _record(provider, raw):
    if not isinstance(raw, dict):
        raise ValueError('Provider record must be an object')
    if provider == 'crossref':
        identifier = doi(raw.get('DOI'))
        return {'identity': 'doi:' + identifier, 'doi': identifier,
                'title': raw.get('title'), 'version': raw.get('version'),
                'access': 'metadata', 'full_text_retrieved': False,
                'update_to': raw.get('update-to', []), 'relation': raw.get('relation', {}),
                'raw': raw}
    identity, source = raw.get('id'), raw.get('source')
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', identity) or not isinstance(source, str) or not re.fullmatch(r'[A-Z][A-Z0-9]*', source):
        raise ValueError('Invalid Europe PMC identity')
    if source == 'MED' and not re.fullmatch(r'[1-9]\d*', identity):
        raise ValueError('Invalid PMID')
    if source == 'PMC':
        pmcid(identity)
    normalized_doi = doi(raw['doi']) if raw.get('doi') else None
    if raw.get('pmcid'):
        pmcid(raw['pmcid'])
    return {'identity': 'doi:' + normalized_doi if normalized_doi else source + ':' + identity,
            'doi': normalized_doi, 'source': source, 'id': identity,
            'pmcid': raw.get('pmcid'), 'title': raw.get('title'),
            'version': raw.get('versionNumber'), 'access': 'abstract' if raw.get('abstractText') else 'metadata',
            'full_text_retrieved': False, 'license': raw.get('license'),
            'full_text_links': raw.get('fullTextUrlList'), 'raw': raw}


def search(provider, query, pages=1, page_size=10, filters=None):
    if provider not in BASES or not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError('Select crossref/europepmc and a query of 1–1000 characters')
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 5 or isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 20:
        raise ValueError('Pages must be 1–5 and page-size 1–20')
    if filters is not None and (not isinstance(filters, str) or not filters.strip() or len(filters) > 1000):
        raise ValueError('Filter must be 1–1000 characters')
    if provider == 'europepmc' and filters is not None:
        raise ValueError('Europe PMC filters belong in its explicit query syntax')
    result = {'status': 'empty', 'provider': provider, 'query': query, 'filter': filters,
              'started_at': now(), 'page_limit': pages, 'page_size': page_size,
              'pages': [], 'records': [], 'errors': [], 'coverage': 'bounded search; not field-exhaustive',
              'exhausted': False, 'full_text_retrieved': False, 'semantic_verification': 'not_performed',
              'evidence_families': 'not_assessed; identity deduplication is not study independence'}
    cursor, seen = '*', set()
    groups = {}
    for page in range(1, pages + 1):
        params = {'query': query, 'rows': page_size, 'cursor': cursor} if provider == 'crossref' else {
            'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': page_size, 'cursorMark': cursor}
        if filters:
            params['filter'] = filters
        url = (BASES[provider] if provider == 'crossref' else BASES[provider] + 'search') + '?' + urllib.parse.urlencode(params)
        fetched = request(url)
        receipt = {**fetched['receipt'], 'page': page, 'cursor': cursor, 'status': fetched['status']}
        result['pages'].append(receipt)
        if fetched['status'] != 'success':
            result['errors'].append({'page': page, 'error': fetched.get('error'), 'status': fetched['status']})
            result['status'] = 'partial' if groups else fetched['status']
            break
        try:
            payload = json.loads(fetched['body'])
            if provider == 'crossref':
                message = payload['message']
                items, following = message['items'], message.get('next-cursor')
                result['provider_hit_count'] = message.get('total-results')
            else:
                items, following = payload['resultList']['result'], payload.get('nextCursorMark')
                result['provider_hit_count'] = payload.get('hitCount')
            if not isinstance(items, list) or len(items) > page_size or following is not None and not isinstance(following, str):
                raise ValueError('Malformed provider page/cursor')
            for raw in items:
                record = _record(provider, raw)
                key = record['identity']
                if key not in groups:
                    groups[key] = {**record, 'variants': [], 'provenance': []}
                group = groups[key]
                if raw not in group['variants']:
                    group['variants'].append(raw)
                group['provenance'].append({'page': page, 'provider': provider, 'retrieved_at': receipt['retrieved_at']})
                group['conflicting_variants'] = len(group['variants']) > 1
            if len(items) < page_size or not following:
                result['exhausted'] = True
                result['status'] = 'success' if groups else 'empty'
                break
            if following == cursor or following in seen:
                result['errors'].append({'page': page, 'error': 'repeated_cursor'})
                result['status'] = 'partial' if groups else 'failed'
                break
            seen.add(cursor)
            cursor = following
            result['status'] = 'success' if groups else 'empty'
        except (ValueError, TypeError, KeyError) as exc:
            result['errors'].append({'page': page, 'error': 'invalid_provider_response', 'detail': str(exc)})
            result['status'] = 'partial' if groups else 'failed'
            receipt['status'] = 'failed'
            break
    result['records'] = list(groups.values())
    result['next_cursor'] = None if result['exhausted'] else cursor
    result['finished_at'] = now()
    return result


def updates(identifier):
    identifier = doi(identifier)
    fetched = request(BASES['crossref'] + '/' + urllib.parse.quote(identifier, safe=''))
    result = {'status': fetched['status'], 'doi': identifier, 'retrieved_at': now(),
              'lookup_receipt': fetched['receipt'], 'identity_status': 'unresolved',
              'coverage': 'Crossref deposited notices only; absence is not certified',
              'semantic_verification': 'not_performed', 'full_text_retrieved': False}
    if fetched['status'] != 'success':
        result['error'] = fetched.get('error')
        return result
    try:
        record = _record('crossref', json.loads(fetched['body'])['message'])
        if record['doi'] != identifier:
            raise ValueError('DOI identity mismatch')
        result.update(record=record, identity_status='identity_verified')
    except (ValueError, TypeError, KeyError) as exc:
        return {**result, 'status': 'failed', 'error': str(exc)}
    # Reverse lookup matters: a notice's update-to points at the affected article.
    notices = _updates_search(identifier)
    result['notices'] = notices
    result['status'] = 'success' if notices['status'] in ('success', 'empty') else 'partial'
    return result


def _updates_search(identifier):
    # A DOI query is retained alongside the updates filter, making scope explicit.
    return search('crossref', identifier, 1, 20, 'updates:' + identifier)


def fulltext(identifier):
    identifier = pmcid(identifier)
    fetched = request(BASES['europepmc'] + identifier + '/fullTextXML')
    result = {'status': fetched['status'], 'pmcid': identifier, 'receipt': fetched['receipt'],
              'access': 'unavailable', 'full_text_retrieved': False, 'read_or_reviewed': False,
              'semantic_verification': 'not_performed', 'identity_status': 'unresolved'}
    if fetched['status'] != 'success':
        return {**result, 'error': fetched.get('error')}
    try:
        raw = fetched['body']
        decoded = raw.decode('utf-8-sig')
        if re.search(r'<!ENTITY\b', decoded, re.I):
            raise ValueError('Internal DTD/entity definitions are not accepted')
        declaration = re.search(r'<!DOCTYPE\b', decoded, re.I)
        if declaration:
            quote = None
            for character in decoded[declaration.end():]:
                if quote:
                    if character == quote:
                        quote = None
                elif character in ('"', "'"):
                    quote = character
                elif character == '[':
                    raise ValueError('Internal DTD/entity definitions are not accepted')
                elif character == '>':
                    break
        # ElementTree does not retrieve an external DTD. JATS commonly includes
        # an external declaration; accepting it never fetches that resource.
        tree = ET.fromstring(decoded)
        for node in tree.iter():
            node.tag = node.tag.split('}')[-1]
        if tree.tag != 'article':
            raise ValueError('Expected an article XML document')
        meta = tree.find('./front/article-meta')
        if meta is None:
            raise ValueError('Missing article metadata')
        identities = [n.text.strip() for n in meta.findall('article-id')
                      if n.attrib.get('pub-id-type') in ('pmcid', 'pmc') and n.text]
        identities = [x if x.upper().startswith('PMC') else 'PMC' + x for x in identities]
        if identifier not in {pmcid(x) for x in identities}:
            raise ValueError('Returned PMCID does not match requested article')
        body = tree.find('body')
        if body is None or not ''.join(body.itertext()).strip():
            raise ValueError('Article body unavailable; metadata is not full text')
        text = '\n'.join(x.strip() for x in tree.itertext() if x.strip()) + '\n'
        sections = [{'locator': 'body/sec[' + str(i) + ']', 'title': ''.join(n.find('title').itertext()) if n.find('title') is not None else None,
                     'text': '\n'.join(x.strip() for x in n.itertext() if x.strip())} for i, n in enumerate(body.findall('.//sec'), 1)]
        licenses = [{'text': ''.join(n.itertext()).strip(), 'attributes': n.attrib} for n in meta.findall('.//license')]
        versions = [''.join(n.itertext()).strip() for n in meta.findall('article-version')]
        return {**result, 'status': 'success', 'access': 'full_text', 'full_text_retrieved': True,
                'identity_status': 'identity_verified', 'publisher_version': versions or None,
                'identifiers': [{'type': n.attrib.get('pub-id-type'), 'value': ''.join(n.itertext()).strip()}
                                for n in meta.findall('article-id')],
                'title': ''.join(meta.find('title-group/article-title').itertext())
                         if meta.find('title-group/article-title') is not None else None,
                'version_identifier': 'xml-sha256:' + hashlib.sha256(raw).hexdigest(),
                'license': licenses or None, 'reuse_rights': 'article-specific; unknown when no license supplied',
                'copyright': [''.join(n.itertext()).strip() for n in meta.findall('.//copyright-statement')],
                'text': text, 'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'sections': sections}
    except (ValueError, TypeError, ET.ParseError, UnicodeError) as exc:
        return {**result, 'status': 'failed', 'error': str(exc)}


def write_json(path, value, force=False):
    with Path(path).open('w' if force else 'x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('search', 'updates', 'fulltext'):
        command = subs.add_parser(name)
        command.add_argument('--output', required=True)
        command.add_argument('--force', action='store_true')
        if name == 'search':
            command.add_argument('--provider', required=True, choices=tuple(BASES))
            command.add_argument('--query', required=True)
            command.add_argument('--pages', type=int, default=1)
            command.add_argument('--page-size', type=int, default=10)
            command.add_argument('--filter')
        elif name == 'updates':
            command.add_argument('--doi', required=True)
        else:
            command.add_argument('--pmcid', required=True)
            command.add_argument('--text-output', required=True)
    args = parser.parse_args()
    try:
        outputs = [Path(args.output)] + ([Path(args.text_output)] if args.command == 'fulltext' else [])
        if len({p.resolve() for p in outputs}) != len(outputs):
            raise ValueError('Text and JSON outputs must differ')
        if not args.force and any(p.exists() for p in outputs):
            raise FileExistsError('Existing output preserved; use new paths or explicit --force')
        if args.command == 'search':
            result = search(args.provider, args.query, args.pages, args.page_size, args.filter)
        elif args.command == 'updates':
            result = updates(args.doi)
        else:
            result = fulltext(args.pmcid)
            if result['status'] == 'success':
                with Path(args.text_output).open('w' if args.force else 'x', encoding='utf-8', newline='\n') as stream:
                    stream.write(result.pop('text'))
                result['text_path'] = str(Path(args.text_output).resolve())
        write_json(args.output, result, args.force)
        print(json.dumps({'status': result['status'], 'output': args.output}))
        return 0 if result['status'] in ('success', 'empty') else 2
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
