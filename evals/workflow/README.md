# End-to-end research/writing evaluation fixtures

`inputs.json` contains ten prompts and source packets frozen before phase-5
candidate changes. `followup-inputs.json` adds two separately frozen design
contrasts after an omission in the original proposal case was observed. Their
criteria are in `rubric.json` and `followup-rubric.json`; keep the executor blind
to these expected outcomes. The original P5-08 case became a development case
for that focused repair; it is no longer held out for that change. All sources except P5-10 are invented test material, not
scientific evidence. P5-10 contains original evaluator notes from two specified
primary papers; executors receive those notes, not verified full-text access.
The paired comparison is supplied-only. Fresh browsing is a separate integration
check, never silently credited to the supplied-only arms.

Run the arithmetic control and deterministic fixture checks with Python 3.10+:

```sh
python evals/workflow/reproduce_quantitative.py
python evals/workflow_checks.py
```

The helper is a narrow teaching-fixture calculation, **not a general
meta-analysis engine**. For P5-02, four reports represent three declared
independent families. S2b repeats S2, so F2 contributes once. The explicit model
is a common-effect inverse-variance weighted mean: weight = 1/SE², estimate =
sum(weight × effect)/sum(weight), pooled SE = sqrt(1/sum(weight)), normal 95%
interval = estimate ± 1.959963984540054 × pooled SE. Expected estimate is
1.7777777777777777 seconds saved, SE 0.6666666666666666, interval
[0.4711351214177417, 3.0844204341378134]. These values were independently frozen
before this implementation. A conflicting effect or SE within a family refuses
pooling; the helper cannot resolve primary-report conflicts or authenticate
independence. Positive effects mean seconds saved by B relative to A. Zero and
negative effects remain valid; missing/nonfinite effects or nonpositive SEs fail.
At most 100 reports are accepted. No dependence correction, missing-value
imputation, heterogeneity model, bias appraisal or scientific validation is done.

## Behavioral execution requires separate work

Passing the Python checks establishes fixture/arithmetic integrity. It does not
run a model, test its writing, retrieve literature or deliver an external document.
To perform a comparable behavior test:

1. Before changing the candidate, freeze source inputs, rubric, critical failures
   and independent reference calculations outside candidate-controlled files.
2. Assign the previous and candidate skill to separate execution contexts using
   identical case packets, tools and model/effort settings where observable.
   Give executors the relevant skill and prompt, without expected answers or
   the grader's rubric. Replace only `{RUN_DIR}` with each assigned output folder.
3. Save actual outputs, calculations, tool receipts and delivered-file readbacks.
   Record refusals, unanswered intake, unavailable capabilities and failures.
4. A reviewer separate from construction evaluates the saved artifacts against
   the frozen criteria. Disclose whether review was blind, human or agent-based,
   and any mismatched settings. Critical failures cannot be averaged away.
5. Preserve the baseline and candidate hashes, per-case outcomes, calculations,
   limitations and rollback decision. Publish only reviewed nonprivate material.

These prompts become public regressions after publication. A future improvement
needs fresh held-out cases. CI does not execute an LLM or independently grade prose.
The private frozen acceptance records govern adoption; editable public tests do
not replace them. Local Markdown readback demonstrates local delivery only, not
Google Docs or other service acceptance.

The two followups contrast shared people/facilitators/materials with isolated
individual tasks. The desired behavior is a design-specific account of possible
exposure and dependence, not an automatic requirement for cluster assignment.
Review per-case criteria and critical failures individually; summed points cannot
excuse a critical failure. The installed skill's runtime tools are unchanged by
these evaluation-only Python files.
