# Computational research and evidence records

First settle the finished work and destination. An empirical paper needs executed evidence; a proposal needs an executable design clearly labelled as proposed. A literature review does not require invented experiments. Keep records in the user's selected project and preserve its existing layout.

## Establish a project

Run from the skill directory, substituting the selected project path:

```sh
python3 scripts/evidence_tools.py init-project --directory /path/to/project
python3 scripts/research_tools.py doctor --output /path/to/project/doctor.json
python3 scripts/research_tools.py profile --output /path/to/project/device.json
python3 scripts/research_tools.py plan --tool researchclaw --profile /path/to/project/device.json --input /path/to/project/research-project.json --output /path/to/project/execution-plan.json
```

The initializer creates only a missing `research-project.json`; `target` and `destination` start as null and must be settled with the user. Existing files remain unchanged. Record scope, decisions, tool capabilities, budgets and paths to sources, data, scripts, runs and drafts. Keep original data separate from derived outputs. Retain dataset versions, licenses and acquisition dates. Never scan credentials or create global memory. Project lessons are reviewable notes, not automatic changes to this skill or other projects.

Edit the generated device profile and select a tool as documented in the [main CLI guide](tool-usage.md) to choose a feasible CPU/GPU plan. The example plan records a possible ResearchClaw setup; it does not execute it. Device availability is not proof that a method or package works on it. Pilot with small data, low memory and short runtime before scaling. Record any CPU fallback, reduced precision, smaller model/data or changed method; assess how it changes the question. No silent simulated measurements.

## Search and normalize sources

```sh
python3 scripts/evidence_tools.py search --query "cross validation small samples" --limit 5 --output /path/to/project/search.json
python3 scripts/evidence_tools.py lookup-doi --doi 10.1038/nrn3241 --output /path/to/project/identity.json
python3 scripts/evidence_tools.py bibliography --input /path/to/project/bibliography-input.json --output /path/to/project/bibliography-normalized.json
```

These network commands use the public Crossref API with a ten-second timeout and bounded responses. Queries/DOIs leave the computer; do not include confidential text. They need no key or model weights. Results are **metadata only**. Status distinguishes success, empty, unavailable and failed; errors are not evidence that a paper does not exist. DOI lookup checks returned identity. Read the actual source before assessing support. Record metadata, abstract or full-text access honestly, with a URL and page/section/table/passage locator. Source identity and access do not establish claim entailment, peer review or methodological quality.

Bibliography input is a JSON list of objects using `doi`, `arxiv` and/or `pmid`; each can also be a list of variants. Other fields are retained. Shared normalized identities merge records; original records, arXiv versions and provenance remain visible. Invalid identifiers and conflicting identities/metadata require review. Do not fabricate missing metadata.

## Run bounded experiments

Before execution, record hypotheses, comparison conditions, baselines, data/splits, metrics/units, seeds, uncertainty estimates, resource limits and a stop rule. Separate exploratory changes from confirmatory plans. Pilot first; diagnose failure from logs; refine implementation within a fixed attempt budget or pivot the question with a recorded reason. Preserve every attempt, failed run, negative finding and protocol amendment. Report selection criteria when highlighting a best run. A successful exit and matching numbers do not establish scientific usefulness: inspect leakage, confounding, identical ablations and whether measurements answer the question.

Human review belongs at direction selection, consequential design changes and claim interpretation. Run critique serially when delegation is unavailable or unauthorized. Do not install dependencies, start cloud jobs, upload private data or publish merely because a workflow suggests them.

## Verify recorded evidence

```sh
python3 scripts/evidence_tools.py verify-evidence --input /path/to/project/evidence.json --output /path/to/project/integrity-report.json
```

Manifest arrays are `artifacts`, `measurements`, `claims`, `sources` and `source_claims`; absent arrays are empty. Every record requires a unique string `id` within its array. Artifacts have a project-relative CSV `path` and actual `sha256`; traversal and escaping symlinks fail. CSV headers include `run,condition,dataset,metric,unit,seed,statistic,value`. Measurement records supply those same fields plus `artifact_id` and `row` (first CSV data row is 1). Context values are nonempty strings, including seeds such as `"42"` or `"not_applicable"`; values are finite decimal numbers or decimal strings. Claims contain the same context/value and link through `evidence_id`. Exact Decimal comparison uses no tolerance or global number whitelist.

Sources declare `access`, `locator` and `identity_status` (`verified` or `identity_verified` for cited sources). Source claims link `source_id`, declare `required_access` and supply their own `locator`. Metadata cannot satisfy full-text access. Passing reports check recorded integrity, **not semantic entailment**. With no numeric or source claims, status is `not_checked`, with reason `no_claims_to_check`, and exit 2. Reports are deterministic, list errors and exit 2 on failed checks; inputs are limited to 10 MiB. Existing outputs require explicit `--force` to replace. Generate final tables from the checked records, then assess meaning and source support before drafting.

Design references: [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw), its [paper](https://arxiv.org/abs/2605.20025v2), and [Beeblio](https://github.com/alharkan7/beeblio). Their performance claims are not reproduced here. This toolkit is original; Beeblio's noncommercial code is not bundled.
