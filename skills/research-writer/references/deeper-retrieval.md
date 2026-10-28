# Broader discovery and version-pinned full text

The optional `scripts/discovery_tools.py` uses Python 3.10+ standard library.
Run it explicitly in a user-owned project. Search terms and requested identifiers
are sent to the selected public service; honor supplied-only and confidentiality
boundaries. No API key, account registration or paid fallback is provided.

```sh
python PATH_TO_SKILL/scripts/discovery_tools.py search --query "retrieval augmented generation" --limit 5 --output PROJECT/discovery.json
python PATH_TO_SKILL/scripts/discovery_tools.py work --work-id W3027879771 --output PROJECT/work.json
python PATH_TO_SKILL/scripts/discovery_tools.py arxiv-fulltext --arxiv-id 2005.11401v4 --text-output PROJECT/article.txt --output PROJECT/article.json
```

`work` also accepts `--doi DOI` instead of `--work-id`. IDs are validated and the
returned work/DOI must match the request. Search is one OpenAlex page, at most
20 records. A returned hit count is provider metadata, not screened evidence;
a small first page is never fieldwide coverage. Reference IDs are citation-trail
leads, not papers retrieved or read. Keep multiple reports/versions and study
families distinct. Existing Crossref/Europe PMC routes remain available through
[literature retrieval](literature-retrieval.md).

Anonymous OpenAlex requests use a shared-IP free quota. Rate limits and service
availability can change; failures, quota exhaustion and missing records remain
visible. This tool does not acquire a key, enable cursor paging or purchase more
capacity. Provider OA links, license fields and `is_retracted` flags do not prove
full-text access, article reuse rights or certified publication status. Check
relevant primary versions and notices before relying on affected findings.

The arXiv command requires an explicit version, including for legacy IDs. It
fetches only the fixed official HTML route, independently of the Atom API.
A recognized front identity/version signal and a substantive article body are
required; a matching ID in a bibliography, asset or footer is insufficient.
Wrong versions, abstract/error pages and unavailable conversions are not full
text. No silent latest-version substitution, mirror, PDF fallback, asset fetch
or script execution occurs. Each response is capped at 10 MiB and uses a ten-second socket timeout; this is
not a hard end-to-end wall-time deadline. Existing output paths are preserved
before any network request. The parser requires at least 80 characters and
12 words of prose outside abstracts/bibliographies; very short or differently
structured documents may be unavailable through this conservative route.

Keep arXiv operations sequential and at least three seconds apart across all
processes and machines under your control. The utility's local serialization
cannot coordinate other programs/devices; do not run parallel crawls. The HTML
route does not establish availability for every paper. Mathematical notation,
tables, images, reading order and conversion errors may require inspection of
the original; extracted text is a separate versioned artifact.

Reports retain request/time/HTTP and raw-byte/extraction hashes, pinned identity,
access and locators. Successful retrieval keeps reading and semantic review
unperformed. Store source artifacts in the project, inspect the relevant text
and contrary evidence, then use [claim audit](claim-audit.md) for a declared
claim inventory. A content hash pins bytes, not the truth of their claims.
Unknown article rights remain unknown; downloaded paper text is not part of
this MIT skill and must not be redistributed automatically.

Official references inspected for this route: [OpenAlex API](https://help.openalex.org/api/),
[authentication](https://help.openalex.org/api/authentication/),
[arXiv API terms](https://info.arxiv.org/help/api/tou.html), and
[HTML guidance](https://info.arxiv.org/about/accessible_HTML.html).
