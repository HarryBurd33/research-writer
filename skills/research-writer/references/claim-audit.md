# Audit a declared claim-to-source matrix

Use `scripts/claim_audit.py` when consequential claims depend on multiple sources,
versions or competing findings. It supplements the unchanged legacy
[source-support checker](source-support.md). It makes no network request.

```sh
python PATH_TO_SKILL/scripts/claim_audit.py audit-claims --input PROJECT/claims.json --output PROJECT/claim-audit.json
```

Use a new output path. The manifest has integer `schema_version: 1` and arrays
`sources`, `claims` and `reviews`. The manifest must be a regular UTF-8 JSON file. All source paths are project-relative UTF-8
regular files confined to the manifest directory. Nonregular objects such as
named pipes are rejected before reading. The legacy integrity checker reopens
paths, so use a cooperating filesystem without concurrent source replacement;
this is not an adversarial filesystem sandbox. Retain originals and extraction
provenance; do not edit text after reviewing or hashing it. Bounds are 32 sources,
100 claims, 500 reviews, 10 MiB per manifest/source and 20 MiB aggregate sources.

Each **source** uses the legacy fields `id`, `version`, `access`, `identity_status`,
`path`, `sha256` and `locator`, plus nonempty `study_family` and
`publication_status` (`current`, `corrected`, `retracted`, `withdrawn`, `unknown`).
Access is `metadata`, `abstract` or `full_text`. Establish identity, version,
family and status from inspected evidence; these declarations are not
independently authenticated by the checker. A provider flag alone is not a
status review. Preserve correction notices and replaced versions; do not count
them as new independent experiments.

Each **claim** has `id`, exact `text`, nonempty unique `required_source_ids` and
`required_access` (`abstract` or `full_text`). Declare the relevant source set
before selecting favorable passages. This is an explicit scope, not proof that
all claims or contrary sources have been discovered. Amendments to the inventory
need a recorded reason; deleting difficult sources is not resolution.

Each **review** has legacy `id`, `claim`, `source_id`, `source_version`,
`source_sha256`, `passage`, `start`, `end`, `locator`, `judgment`, `rationale`,
`reviewer`, timezone-bearing `reviewed_at`, plus `claim_id`. Its claim text must
exactly match the declared claim. Offsets count decoded Unicode characters,
start inclusive/end exclusive. Judgment is `supports`, `partial`, `contradicts`
or `uncertain`. Preserve multiple passages/judgments, including additional
contrary reviews beyond the required minimum. The reviewer's rationale must
come from actual reading, not keyword overlap or the integrity check.

Read enough surrounding methods, results and limitations to judge the claim's
population, outcome, time point and causal scope. A passage supporting a narrower
association is partial support for a broader causal claim. Consider correction
and publication status before relying on an earlier result. Look for contrary
evidence and distinguish unavailable methods from negative findings. For a
contested claim, have a reviewer separate from drafting inspect the source;
disclose agent-based/nonblind review and unresolved domain-expertise limits.

The result separates record integrity, coverage of declared claim/source pairs,
recorded judgments, declared family counts and flags needing review. Missing
required reviews yield `incomplete`; unsafe/stale/inconsistent records yield
`failed`; an empty claim inventory is `not_checked`. Only `records_valid` exits
zero. A valid contradiction record may still be `records_valid`: that means the
record is consistent, not that the claim is supported. Partial/contradictory/
uncertain judgments and adverse/unknown status stay visible for revision.

Every report keeps `semantic_entailment: not_automatically_verified` and
`drafting_clearance: not_granted`. Narrow, qualify, omit or investigate claims
through actual evidence review before drafting them as established. A valid
inventory cannot detect undeclared claims, dishonest judgments, undiscovered
corrections or false family declarations, and cannot certify scientific truth.
