# Bounded literature retrieval

`scripts/literature_tools.py` is an original MIT Python 3.10+ standard-library
adapter. Network requests occur only when one of its explicit commands runs.
Queries are sent to the selected public provider. Respect supplied-only boundaries
and do not submit private research details without authorization.

```sh
python PATH_TO_SKILL/scripts/literature_tools.py search --provider crossref --query "literature review" --pages 2 --page-size 5 --output PROJECT/crossref.json
python PATH_TO_SKILL/scripts/literature_tools.py search --provider europepmc --query "OPEN_ACCESS:Y AND malaria" --pages 2 --page-size 5 --output PROJECT/europepmc.json
python PATH_TO_SKILL/scripts/literature_tools.py updates --doi 10.1371/journal.pcbi.1003149 --output PROJECT/updates.json
python PATH_TO_SKILL/scripts/literature_tools.py fulltext --pmcid PMC3715443 --text-output PROJECT/article.txt --output PROJECT/article.json
```

Choose a user-owned project directory. Existing outputs are preserved unless
`--force` is explicitly selected. Search bounds are one to five pages and one to
20 records per page. Crossref accepts optional `--filter` using its documented
syntax; Europe PMC filters belong in its explicit query syntax. Requests are
sequential, time out after ten seconds and cap each response at 10 MiB. A 429
stops the run and preserves Retry-After; it never causes unbounded retries.

Reports retain the actual query/filter, provider, date, page/cursor receipts,
raw record variants and identity provenance. Identical DOI records are grouped
while conflicting versions remain visible. Grouping canonical IDs is not evidence
that separate studies are independent or that different reports belong to a single
study. Reconcile evidence families separately. `exhausted` describes the provider
traversal only; a bounded search is never a comprehensive field review. Partial
failures retain the successful records and identify the failed request. Missing
records, failed requests and empty results do not establish scholarly absence.

The updates command retrieves an exact DOI record and reverse Crossref
`updates:DOI` notices. A notice's `update-to` points toward the affected article;
its own DOI is separate. Deposited relations and raw correction/retraction signals
are retained, not transformed into an assurance that the source is unretracted.
Inspect relevant notices and publisher corrections before using affected findings.

Search results provide metadata or returned abstracts. Full-text links and an
open-access flag do not mean the article has been retrieved or read. Full text is
requested only through Europe PMC's official OA XML endpoint using a valid PMCID.
The adapter verifies the returned article identity and nonempty body, retains
license/copyright and section locators, and writes a UTF-8 text artifact with its
SHA-256. Its XML-content hash identifies the retrieved revision; missing publisher
version information stays missing. External JATS DOCTYPE declarations are accepted
without fetching their resources; internal DTD/entity definitions are rejected.
Redirects outside fixed provider endpoints are blocked. No arbitrary publisher
URL, HTML scraping, API key, paid access or paywall bypass is provided.

Successful retrieval is access, not reading or semantic review. The report keeps
`read_or_reviewed: false` and `semantic_verification: not_performed`. To prepare a
source-support record, use a project-relative text path and `text_sha256`, the
observed PMCID as source identity, the retrieved `version_identifier` as a content
revision identifier (or an explicitly established publisher version), and the actual
passage/section locator. Review the passage against the claim separately; metadata
must not be upgraded into full-text support.

Full texts and abstracts retain article-specific rights. Unknown license means
unknown reuse rights, never MIT. Preserve attribution and inspect the article's
license before redistribution, figures or substantial reuse. This package contains
no downloaded papers. Service coverage is limited: Crossref spans registered
scholarly metadata, while Europe PMC primarily covers life-science sources. Neither
provides every discipline, article, correction, translation or inaccessible text.

Official interface and rights references: [Crossref cursor guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/),
[Crossref access](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/),
[update filters](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/),
[Crossref metadata schema](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md),
[Europe PMC REST](https://europepmc.org/RestfulWebService),
[Europe PMC copyright](https://europepmc.org/Copyright).
