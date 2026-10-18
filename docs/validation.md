# Validation — Research Writer 0.3.0 preview

Updated: 2026-10-18 UTC. Earlier comparison and live research check: 2026-10-17 (America/Denver).

## Status

The question-development expansion is published for review on `research-question-development`; version 0.2.0 remains stable on `main`. The earlier v0.2.0/v0.3.0 comparison passed both versions without demonstrating a performance gain, so automatic promotion was inconclusive. Subsequently, v0.3.0 was installed by explicit user request. The latest round therefore evaluates the actual installed v0.3.0 baseline.

This round adds validation assets and a usage guide. It makes no changes to the skill instructions or version; the portable file only refreshes its generated notice for the current builder. It makes no claim of improved model behavior. Independent grading found no failure warranting a targeted behavioral patch.

## 2026-10-18 evidence reliability check

Skill Forge used a 30-minute effort limit and a maximum of three candidates. An independent audit and bounded Skill Finder review proposed a narrow focus on source-family reconciliation, corrections, internal discrepancies and conclusion strength. Acceptance criteria and evaluator were fixed before execution. No behavioral candidate was needed or evaluated: the installed baseline passed all eight requests, all **28/28 required checks** and **10/10 critical reconciliation checks**.

| Executed baseline case | Result |
|---|---|
| Six reports from one trial, including interim, subgroup and corrected results | Pass: one evidence family; corrected results control the conclusion |
| Three-trial quantitative synthesis with a shared comparator | Pass: combined active arms, control counted once, retained Python calculations |
| Convergent observational evidence for a causal policy claim | Pass: shared confounding and selection limits survive into the recommendation |
| A paper's headline claim conflicts with its outcome counts | Pass: discrepancy detected; no invented authoritative correction |
| Missing finished-work target | Pass: asks for target and destination |
| Known target but missing destination | Pass: asks for delivery choice without reopening the target |
| Humanities proposal with fictional course logistics in reference notes | Pass: genre and source boundaries preserved; class logistics excluded |
| Fresh reserved engineering-report discrepancy | Pass: arithmetic conflict detected; procurement conclusion remains conditional |

The reserved input and rubric were independently created and remained unavailable to the builder until the baseline verdict and decision to preserve instructions. It is now a known regression, not a future fresh holdout. Inputs are in [evidence-reconciliation-inputs.json](../evals/evidence-reconciliation-inputs.json); their sources, people, technologies and results are fictional fixtures.

Fresh execution contexts read the baseline and input requests without the rubric. The seven exposed requests were run in one context as separate tasks; the reserved request used a separate context. The independent grader inspected actual outputs and retained calculation files. It knew the baseline label and designed the criteria. Exact executor model version/settings were not exposed. This small single-run assurance check is not a blinded comparison or a demonstration of improvement.

### Reproduce the quantitative fixture

Run with Python 3.9 or later and the standard library:

```sh
python3 evals/quantitative/analysis.py
```

The [script](../evals/quantitative/analysis.py) reads [inputs.json](../evals/quantitative/inputs.json), checks simple invariants and prints the calculation. [expected.json](../evals/quantitative/expected.json) retains the executed reference output; the runtime version may differ when rerun. This is a fixture calculator, not a general meta-analysis tool or a universally recommended estimator.

North's combined active arm has n=120, mean=77 and SD=11.991594. The pooled mean difference is 3.062718 points. A common-effect normal interval is [0.849897, 5.275539]; the executed DerSimonian–Laird calculation with a modified Hartung–Knapp interval gives [−1.795025, 7.920461]. Two independent reference calculations verified the combined variance and pooled arithmetic; the grader additionally checked the small-sample interval. The uncertainty method materially affects the conclusion and is disclosed in the actual answer. Three fictional trials with bias concerns establish no real intervention effect.

This checks one suitable supplied-data synthesis. It does not test end-to-end searching, screening, extraction, appraisal and analysis of a real review. Live correction/retraction discovery and Google Docs delivery remain untested in this round. The skill hash remains `96e7449fb229b8fb182a6415482547e8fca69ad087dd24d43d19058b9aa9e365`.

## Portable packaging verification — 2026-10-18

An original repository-specific builder, [`scripts/build_portable.py`](../scripts/build_portable.py), now generates the portable instructions using Python 3.9+ and its standard library. It corrects the generic Skill Forge header, includes canonical `SKILL.md` and reference/template resources, translates their relative file links to bundled anchors, and records a deterministic source digest. This changes packaging text only; the included substantive resource body is byte-for-byte unchanged.

Both generation and `--check` passed. In a temporary repository copy, appending a canonical-source change caused `--check` to fail without modifying the bundle; regeneration then incorporated that change and passed the check. No canonical skill instructions changed. Earlier statements about the generated portable file refer to the earlier Skill Forge-format check; current bundle verification uses this project-specific builder. Run `python3 scripts/build_portable.py --check` from the repository root.

## Earlier comparative behavioral evidence

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

The executor contexts inherited the same host/model settings, but the exact underlying model version was not exposed. Grading was separate from execution but non-blind to baseline/candidate filenames. Small synthetic cases and one bounded live pass do not establish quality across every discipline. Google Docs creation/editing and an end-to-end real-data systematic review/meta-analysis remain untested. The later fictional calculation check is described separately above.

No stable promotion occurred. `main` remains v0.2.0; the prior version is retained in a private local snapshot. The subsequent explicit installation of preview v0.3.0 is distinct from automatic evidence-gated promotion. This validation/documentation update leaves installed v0.3.0 unchanged. Prior repository files are retained locally for reversing the documentation update.

## File bindings

- Prior v0.2.0 skill directory SHA-256: `b52bfe8cfdfdfc3b6f962494cbc159cd0d8ecd045e6766cfd1e91e44e0196a45`.
- Candidate v0.3.0 skill directory SHA-256: `96e7449fb229b8fb182a6415482547e8fca69ad087dd24d43d19058b9aa9e365`.

Directory hashes identify the files evaluated; they do not authenticate model execution or prove research quality. Raw transcripts, rubric bindings, source coverage and the development brief remain private. Public synthetic requests are in `evals/`.
