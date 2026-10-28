# Deeper literature retrieval and source-support inventory

Research Writer v0.10.0, evaluated 2026-10-28. This is bounded functional and
content-review evidence, not an exhaustive-search or scientific-validity claim.

## Delivered capabilities

- Anonymous OpenAlex first-page search of up to 20 records, exact work/DOI lookup
  and reference IDs for further investigation. Provider flags remain metadata;
  references are not automatically downloaded or counted as independent studies.
- Official version-pinned arXiv HTML, independent of the Atom API. Structural
  identity/version checks precede access classification. Reports retain raw and
  text hashes, 47 offsets in the actual control, unknown rights and unreviewed
  status. No mirror, latest-version, arbitrary publisher or PDF fallback occurs.
- An offline declared claim/source matrix with required-pair coverage, exact
  source/hash/version/passage bindings, access requirements, partial/contradictory/
  uncertain judgments, declared family counts and publication-status flags.
  `records_valid` grants neither semantic proof nor drafting clearance.

The standard-library additions require Python 3.10+, no new runtime dependency,
API key or device-specific configuration. Existing Crossref, Europe PMC and legacy
source-support code remains byte-identical. Core audience/genre/destination,
search-renewal, nearest-neighbor and device-adaptation rules remain in force.

## Executed acceptance

| Evidence | Observed result | What it establishes |
|---|---|---|
| Frozen independent contracts |38/38 pass| Bounded provider/parser and inventory contracts on reserved cases |
| Additional repair/boundary controls |9/9 pass| Targeted failures fixed, including actual FIFOs and official HTML |
| Public local methods |178 pass: prior 125 + discovery 28 + audit 25| Selected local regressions, with applicable engines and six real loopback SSH cases |
| Writing cases |Both arms 14/14 criteria,28/28 points; zero critical failures/unnecessary questions| Preservation across two fresh supplied-source briefs; no measured prose gain |
| Actual arXiv conversion |HTTP 200, pinned identity,69,881 text characters,47 valid section offsets| This version's HTML was retrieved/extracted, not universally accurate conversion |
| Actual declared-claim CLI |2/2 pairs valid; partial/unknown-status flags retained; missing review1/2 yields `incomplete`| Integrity and coverage, not automatic judgment validity |
| Documentation/contract review |7/7 pass| Guidance matches the tested distinction between access, records and review |
| Copied installation/portable |Full selected-engine smoke, 35 files/66 links and portable consistency pass| Package completeness; final hosted/install identities are recorded in the PR |

The [frozen writing inputs](../evals/deeper-retrieval/inputs.json),
[rubric](../evals/deeper-retrieval/rubric.json),
[results](../evals/deeper-retrieval/results.json) and
[actual outputs](../evals/deeper-retrieval/recorded-outputs.md) are public.
They become known regressions after release. New future improvements require
fresh held-out cases. CI runs deterministic checks, not a language-model grader.

Live search and exact-work controls returned HTTP 200 without a key; the search
returned two records and the lookup retained citation leads. The versioned HTML
control uses Lewis and colleagues, arXiv 2005.11401v4. Actual parent review and a
separate nonblind agent review inspected the bounded qualitative comparison and
additional human-assessment context. The narrow author-report claim was warranted;
a universal error-free guarantee was not established. The record retained unknown
publication status and granted no drafting clearance. Paper text and downloaded
HTML remain private project artifacts and are not redistributed in this package.

The legacy checker correctly validated the one supplied passage record without
checking an undeclared inventory. The new utility, given an explicit two-claim
inventory and just one review, instead reports the missing pair. This is an
expanded capability, not a claim that legacy record integrity was broken.

## Findings and repair history

Three candidates were retained in private evidence. The initial frozen run passed
37/38 contracts; a malformed negative hit count could masquerade as an empty
search. A live official HTML response also failed because an issue-report link
had a duplicate presentation `title` attribute. The repair tolerates that unused
attribute deterministically while refusing duplicated identity/structural fields.
Actual named-pipe controls exposed source and then manifest reads that could
block. Both now require regular files and bounded descriptor reads before strict
JSON/source processing. Each isolated child/temporary fixture was cleaned.

All frozen criteria stayed fixed. One early generic test helper incorrectly
permitted an empty result; it was corrected to enforce the original malformed-
response requirement, and the initial history remains visible in private records.
Final checks reran the 38 contracts and repair variants. Writing cases ran before
the final manifest-I/O-only repair; the writing core was unchanged, and the
final affected I/O, CLI, package and integrity checks were rerun.

## Remaining limits

OpenAlex access is one anonymous page with a shared-IP quota, not full citation-
graph traversal. Cursor/key-enabled or paid access is not configured. Provider
retraction/OA/license fields are not certification or full-text rights. The arXiv
Atom control timed out and is not a dependency of this implementation.

HTML availability and conversion remain incomplete. The parser conservatively
requires 80 characters/12 words outside abstracts/bibliographies; very short or
unusual documents may be refused. Equations, tables, images and reading order
need primary-source inspection when consequential. The ten-second socket timeout
is not a hard wall-time deadline; rate coordination across other processes/devices
remains the operator's responsibility. No scripts or embedded assets are fetched.

The legacy integrity checker reopens paths, so use a cooperating filesystem
without concurrent source replacement; this is not an adversarial filesystem
sandbox. Family, access, identity, publication status and judgments are declarations
that require evidence. The audit cannot discover undeclared claims or missing
contrary sources, authenticate a reviewer or establish scientific truth.

Review was separate, nonblind and agent-based, with unknown inherited model/effort
and no human expert validation or cost comparison. This release used two short
synthetic writing cases and one actual primary-paper pipeline. External production
hosts, GPUs, enforced isolation, larger-engine benchmarks, Windows remote servers
and schedulers remain separate work in [the roadmap](roadmap.md).
