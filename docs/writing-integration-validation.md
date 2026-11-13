# StoryScope and Humanizer integration acceptance

Version 0.19.0, reviewed 2026-11-12. Scope: installed research-writing instructions, licensed pinned reference resources, and an offline taxonomy inspection helper. This report does not claim execution or empirical validation of upstream StoryScope inference/classification.

## Source and package checks

- Inspected both upstream READMEs and MIT licenses; Humanizer's full 4.0.0 skill; StoryScope's taxonomy, extraction/application prompts, requirements and dataset documentation.
- Verified all four bundled upstream files against their Git blob identities at the pinned commit trees. The packaged manifest also records SHA-256. No dataset, human story text, model weights or provider implementation is redistributed.
- Skill frontmatter validation passed. Package validation checked 72 files and 157 relative links. The generated portable bundle matched canonical resources.
- Ten offline writing tests passed: feature counts/selections, original-field preservation, invalid selectors, an isolated copy from an unrelated directory with network/process/file mutation blocked, and unchanged/tampered/missing-resource manifest controls. All ten passed under Python 3.15; the initial five CLI controls also passed on Python 3.9 and 3.13. CI supplies Python 3.10/3.12 coverage.
- Copied-install smoke passed, including core tooling, evidence retrieval/inventory and durable checkpoint checks; the missing-resource negative control failed as intended. Molecular/provider execution was not part of that local test.

These checks validate distribution, resource identity and utility behavior. They do not judge the scientific truth of a manuscript or authenticate arbitrary text authorship. A manifest is not protection against an adversary who replaces both the files and trusted reference identities.

## Independent writing exercises

A separate GPT-6.1 Sol / Medium reviewer read the integration and performed two bounded, synthetic exercises. No external source search or upstream provider calls were made.

1. An observational paragraph mixed a 42-adult cohort, an association of −0.3 points (95% CI −0.8 to 0.2), a fictional citation, a participant quotation and an access limitation with unsupported claims of proof and a breakthrough. The revision removed the unsupported causal/promotional language and retained the estimate, interval, citation, quotation, confounding caveat and availability statement. Removing unsupported assertions was reported explicitly.
2. A description of an IMRaD paper reported null findings, causal overstatement in Discussion and missing limitations in the abstract. The reviewer proposed a question→design→result→interpretation trace, retained null findings, and limited its recommendations to the supplied description. It did not invent a study design, estimate or limitation from an unseen manuscript.

The reviewer found no material conflict in evidence preservation, supplied voice/venue conventions, the existing novelty assessment, or the separation of bundled resources from uninstalled inference. These two exercises are qualitative acceptance evidence, not a general performance benchmark, blind comparison or human review.

## Remaining boundaries

The StoryScope taxonomy was built for fiction. Its research-specific questions are an adaptation, not classifier-compatible feature measurements. Unknown and inapplicable observations stay explicit. Humanizer edits require agent judgment and a post-edit evidence check; successful formatting and tests cannot prove semantic preservation on every future document.

Full StoryScope execution requires a selected stage, runtime, model/provider and assets, data permissions, and bounded resources. It remains uninstalled and untested here. No manuscript upload or paid API call is implied. Upstream changes require deliberate pin review. Exact resources and notices are in the [third-party record](../skills/research-writer/references/third-party-notices.md).
