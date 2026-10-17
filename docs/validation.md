# Validation — Research Writer 0.3.0 preview

Date: 2026-10-17 (America/Denver).

## Status

The requested question-development expansion is published for review on `research-question-development`. Version 0.2.0 remains stable on `main` and in the active local source. The candidate passes the cases, but comparative testing did not demonstrate a performance gain. Skill Forge's frozen adoption gate is therefore inconclusive and the candidate is not automatically promoted.

## Executed behavioral evidence

Fresh executor contexts ran prior v0.2.0 and candidate v0.3.0 on the same four new requests, using identical fictional source packets and tool restrictions. An independent evaluator graded actual outputs against criteria frozen before the patch and execution.

| Case | Prior v0.2.0 | Candidate v0.3.0 |
|---|---|---|
| Develop an initial design-research idea through supplied literature | Pass, 8/8 | Pass, 8/8 |
| Revise a novelty claim already addressed by close prior work | Pass, 8/8 | Pass, 8/8 |
| Generalize useful principles from fictional course notes for a humanities proposal | Pass, 8/8 | Pass, 8/8 |
| Held-out museum/design-history question with contested voice, translation and privacy | Pass, 38/38 | Pass, 38/38 |

The held-out scenario and rubric were created independently and withheld from the builder until the candidate was written. They are now included with the synthetic cases for reproducibility; reuse in future is regression evidence, not a new holdout.

The candidate also passed all eight original cases: activation/non-activation, insufficient-data meta-analysis, close reading, experiment proposal, theory outline, unspecified target intake, missing-destination intake and explicit-destination delivery in chat. A second independent evaluator confirmed these regression judgments. There were no critical failures. The requested 250-, 450- and 150-word artifacts matched those lengths by whitespace counting.

These are twelve offline cases, not twelve tests of live literature retrieval. The paired results do not establish that the new instructions outperform the prior skill, and shorter responses alone are not counted as benefit.

## Bounded live research smoke test

A separate fresh executor used the candidate on a public community-garden research idea. It performed a bounded search (23 exact query strings recorded), inspected accessible primary studies and relevant versioned materials, compared close prior work and challenged the original and narrowed gaps. The closest predecessor already addressed the initial idea, so the output shifted toward two qualified contribution directions. The brief retained user choice and separated source findings, method proposals and uncertainty.

The independent evaluator reopened source records at their reported access levels and corroborated central claims and original search references. The parent separately checked three main primary texts. This passes a bounded live integration check, not a comprehensive review, universal novelty test or comparison with a live baseline. Abstract-only sources, inaccessible final texts and an unverified recent lead were disclosed; the unverified lead received no evidence credit. No new empirical study or statistical pooling occurred.

## Static checks and source handling

Metadata, nine skill files and eleven local links passed static validation. The generated portable file matches the canonical candidate. Frozen criterion/input hashes were unchanged. A package integrity check found nine skill files and no corrupt ZIP entries.

All thirteen supplied references were accounted for in the private source record. Most were inspected through complete relevant extracted text; the four-page image-only CARS handout was rendered and inspected visually. The 571-page rhetoric book was searched and selected relevant complete chapters/sections were inspected, not read cover to cover. The implementation contains original general instructions and high-level attribution. User documents, extraction files, private project examples and course-specific requirements are excluded from the repository.

## Limits and rollback

The executor contexts inherited the same host/model settings, but the exact underlying model version was not exposed. Grading was separate from execution but non-blind to baseline/candidate filenames. Small synthetic cases and one bounded live pass do not establish quality across every discipline. Google Docs creation/editing and valid statistical meta-analysis remain untested end to end.

No stable adoption occurred, so rollback is unnecessary. The stable source and `main` remain v0.2.0; the complete prior version is also retained in a private local snapshot. The preview branch can be reviewed without changing that version.

## File bindings

- Prior v0.2.0 skill directory SHA-256: `b52bfe8cfdfdfc3b6f962494cbc159cd0d8ecd045e6766cfd1e91e44e0196a45`.
- Candidate v0.3.0 skill directory SHA-256: `96e7449fb229b8fb182a6415482547e8fca69ad087dd24d43d19058b9aa9e365`.

Directory hashes identify the files evaluated; they do not authenticate model execution or prove research quality. Raw transcripts, rubric bindings, source coverage and the development brief remain private. Public synthetic requests are in `evals/`.
