# Validation — Research Writer 0.8.0

Updated: 2026-10-27 UTC. Historical checks below retain their original dates.

## Phase 4: bounded SSH lifecycle — 2026-10-28

v0.8.0 adds optional inspect/prepare/submit/status/collect/cancel operations over an existing SSH connection and a POSIX Python controller. Profiles declare an alias, selected interpreter/root and expected host/user; they contain no credentials and confer no execution authority. Strict host-key verification, a short quoted bootstrap and bounded JSON stdin keep SSH shell quoting separate from task arguments. User authorization for this acceptance was explicitly isolated loopback SSH, not an external machine.

Local public checks pass: 16 client methods, 13 worker methods and six actual loopback SSH methods, plus all 74 prior methods with applicable selected engines. Worker jobs and the real SSH fixture use disposable directories. The fixture binds only 127.0.0.1 with private temporary host/client keys, its own config/known-hosts file and an owned foreground daemon; cleanup removes them. Actual controls cover success and verified collection, host-key/identity refusal, duplicate-submit guard, timeout, cancellation and altered outputs. No global SSH configuration or permanent service is changed. Default tests explicitly skip the real-server fixture.

Independent criteria and fresh job/failure cases were frozen before source review. The final gate passes 65/65 checks: 25 worker, 26 client and 14 actual reserved loopback controls. A real SSH submit was accepted, then its reply deliberately discarded at the client boundary: the state became uncertain, a second submit was refused, and fresh-process status/collection recovered the exact reserved values and hash. This is fault injection around a real accepted request, not a claim of simulated network-packet loss. Review was separate and nonblind; exact executing model/effort was unknown.

Three prepublication defects were reproduced and corrected without changing the acceptance rules. Exceptional artifact validation could bypass final log truncation; cleanup now bounds available logs in finally without following replaced symlinks. Directory locks could survive client death; stable kernel file locks now release on death while durable submission intent remains. Persisting base64 collection payloads could exceed the saved-state reader's bound; only receipt metadata and hashes now persist, and a 900 KB artifact plus 900 KB log recovery regression passes. Initial reproductions and final controls remain private evidence.

The worker uses atomic submission receipts, a live owning controller for child cancellation, wall-time and log bounds, input/work-tree/output checks and confined hash-verified collection. Failed/timed-out/cancelled jobs retain their state and partial-artifact/missing lists. Unknown transport outcomes never authorize automatic resubmission. Thread settings are environment hints, not hard CPU quotas. Limits are cooperative for trusted tasks, not an OS/filesystem sandbox; controller/host failure or escaped malicious descendants can require operator investigation. The RPC never signals a stored PID as proof of ownership.

Metadata validation passes 31 installed-skill files/55 links and portable generation/consistency passes. Existing local-engine self-checks remain intact; loading the remote client during an installed check makes no connection. The workflow adds actual loopback acceptance on selected Linux/macOS runners and client contracts on the core matrix. The release pull request records actual hosted results and final installation/file identities; an unexecuted job is not counted as passing.

Remaining limitations: no production external host, Windows remote server, scheduler, remote GPU engine, paid service or hard resource isolation was validated. A real target still needs an existing trusted connection, compatible runtime/assets, explicit file/task authorization and a bounded host-specific test. No remote profile is installed by default. Local research, literature retrieval and selected CPU adapters remain usable without SSH. The prior v0.7.0 package and managed hash provide rollback.

## Phase 3 selected execution adapters — 2026-10-28

v0.7.0 implements two selected routes: Open Babel conversion independently checked by RDKit, and bounded short canonical-sequence ESM-2 embeddings through Transformers. It does not install every catalog engine or validate docking, folding or biological performance. Official package/model interfaces, immutable assets and distinct rights were renewed. The original MIT wrappers do not bundle external GPL Open Babel binaries, Transformers/PyTorch source or model weights.

Local macOS arm64/Python 3.12 validation passed all 9 conversion methods and 14 protein methods with actual engines, plus all 51 prior public methods with applicable molecular controls. The conversion runtime uses official Open Babel 3.2.1 separately from the RDKit 2026.09.1 validator. Chiral/E-Z/aromatic/charge/count/order checks and positive roundtrips passed. An initial default zero-coordinate stereo route failed independent parsing and was rejected; the selected SMILES-to-SDF route now explicitly generates 2D depictions and retains identity checks. No 3D pose/property preservation is claimed.

The protein runtime uses torch 2.14.1, transformers 5.21.0, safetensors 0.8.0 and numpy 2.5.4. All six immutable official model assets were explicitly prepared and hash-verified (31,387,085 bytes total). Actual CPU embeddings are finite 320-value vectors with input/model/output provenance; pooling excludes BOS/EOS. Inference uses local-only safetensors, bounded subprocess execution and no silent truncation or unsupported-residue mapping. Prepublication hardening rejected extra tokenizer sidecars and symlink assets as well as wrong hashes. Explicit unavailable backends fail, and auto conservatively selects CPU.

Independent review passed 31/31 checks (14 conversion, 17 protein). Its fresh molecule/sequence cases were frozen before constructor inspection. Reserved molecular output was independently re-parsed, and an independent native CPU model forward matched both 320-value embedding vectors exactly in this environment. That is a numerical execution control, not biological validation or a performance benchmark. Review was separate and nonblind; exact model/effort was not exposed. No inference-cost or broad research-quality improvement is claimed.

Combined copied-install self-check passed with the base molecular environment, separately supplied Open Babel executable, separate protein interpreter and verified model directory. Metadata validation passed 28 skill files/52 links, and portable generation/consistency passed. The workflow extends the existing matrix with actual conversion controls and three CPU protein jobs, retaining the stable aggregate and read-only permissions. Hosted outcomes and final release/install identities are recorded in the release pull request; a matrix definition alone is not a passing job.

Timeouts, output limits, non-overwrite, wrong-identity output, invalid inputs, missing/changed assets, exact-six-file loading and unavailable device requests receive negative controls. Available bounded diagnostics are retained; an error before execution may have an error report without process logs. Earlier unrelated reference-document and live literature results remain historical, not newly repeated scientific studies.

Remaining limitations: selected CPU engines and bounded inputs only; no universal OS/Python/backend support, MPS/CUDA/ROCm execution guarantee, benchmarked affinity/function, biological experiment or large-model/docking route. Larger engines need separately compatible assets, licenses, task and resource limits. Existing research-writing, literature/source-support and evidence boundaries remain. User runtime/model paths and assets stay outside the shared package. Prior v0.6.2 and managed installation hashes provide rollback.

## Phase 2: literature retrieval and source-support records — 2026-10-27

v0.6.2 adds original standard-library Crossref/Europe PMC adapters and an offline source-support record checker. Official interface/rights documentation and actual public responses were inspected; no paper text, credentials or private research is redistributed. The old evidence/research utility algorithms remain unchanged. Query/filter/date/cursor receipts, source versions, update notices, actual access levels and coverage limits remain separate from scientific interpretation.

Local checks passed: 13 literature methods, 11 support-record methods, the original 8 toolkit methods and 19 prior regression methods with molecular dependencies, copied-install molecular smoke, metadata (24 files/46 links) and portable consistency. Provider/error/XML branches are offline mocks; they are not claims of live completeness. The installed smoke also checks the new tools load without network access and accepts a consistent fictional support record while rejecting an invented passage.

Live public controls succeeded: Crossref returned four records across two bounded pages; an exact DOI update lookup verified identity and returned no deposited notices, which does not certify no corrections; Europe PMC resolved the matching article; its OA XML full text verified PMCID, body, license, section locators and text-artifact SHA-256. Retrieval remains read_or_reviewed:false. A final prepublication audit found the first internal-DTD regex missed a subset after a quoted greater-than sign; a quote-aware scanner and regression corrected it without permitting entity definitions or external resource loading. The XML hash identifies retrieved content; observed publisher version and unknown fields are retained honestly. Actual JATS external DOCTYPE declarations work without fetching their resources; internal DTD/entity definitions are rejected.

Independent review used separately frozen criteria and a primary-text three-claim packet, with source hashes frozen before evaluation. Its 21 source-support checks passed, including actual CLI, exact offsets/version/hash mutations and primary-source comparison. Review was separate and nonblind; exact model/effort was unknown. Support, contradiction and uncertainty are reviewer judgments; valid records explicitly retain semantic_entailment:not_automatically_verified. No broad research-quality superiority or automatic truth verification is claimed. The final independent gate and hosted matrix result are recorded in the release pull request; this initial publication record does not count an unexecuted matrix as passing.

Coverage remains limited to public deposited metadata and Europe PMC's principally life-science corpus and accessible OA XML. Paid/paywalled sources, all publisher corrections, every discipline and exhaustive novelty discovery are not covered. Identity and access declarations in user-authored support records need separate establishment. Important semantic judgments still require inspection and independent review. Later computational/remote roadmap phases remain outside this release. Prior v0.6.1 source and managed-install hashes provide rollback.

## Phase 1: portable checks and installed self-check — 2026-10-27

This infrastructure release retains the v0.6.0 evidence/research utility algorithms and research-writing workflow. It adds a packaged offline self-check, an isolated copied-install smoke, 19 public regression methods promoted from known edge cases, and a pinned GitHub Actions matrix. These are regression and installation checks, not a new held-out demonstration of research quality.

Local macOS arm64 checks passed: Python 3.12.14 with RDKit 2026.09.1/OpenMM 8.6.1 ran the original eight methods and all 19 added methods, including real molecular controls. System Python 3.15 ran seven original methods plus 17 added methods, explicitly skipping one and two optional molecular methods respectively. Copied installs from unrelated directories passed with both interpreters; the missing-catalog negative control failed as required. Independent review also removed a required script and SKILL.md, confirmed nonzero failures, verified stale-bundle detection, and tested managed-install customization refusal. Explicitly requested molecular checks failed with a nonzero status when dependencies were absent, rather than silently skipping.

The first local self-check run exposed an incorrect catalog wrapper key in the newly authored check; it was corrected before acceptance. No production utility algorithm changed. The first hosted Windows/Python 3.10 run found two false failures: a blanket test subprocess mock intercepted Python's local OS-version lookup. The tests now isolate that OS metadata while retaining unconditional engine/remote subprocess prohibition; production inventory code remains unchanged. The other eight matrix jobs passed that run. The corrected revision must pass a fresh full matrix before promotion. Metadata validation passed for 20 skill files and 41 links; portable generation/consistency passed. Independent review and construction used separate contexts but were not blinded. Exact model/effort and task inference cost were not exposed. No writing-behavior comparison is claimed for this test-focused patch.

The CI workflow defines six core jobs across Linux, Windows and macOS/Python 3.10 and 3.12, plus three selected Python 3.12 CPU molecular jobs. The stable aggregate is **Research Writer checks**. Current official action interfaces, immutable pins, runner labels and package wheel inventories were inspected. A matrix definition and available wheels do not establish execution success. At initial publication, hosted results are pending; consult the [Actions runs](https://github.com/HarryBurd33/research-writer/actions) for actual per-job outcomes. Existing branch protection is preserved and not reconfigured by this patch. See [commands and limits](testing.md).

GPU backends, remote jobs, heavyweight models, literature-provider expansion, semantic support review and broad scientific performance remain outside phase 1. Later roadmap phases remain planned. No secrets, private source documents, personal paths, weights or paid services are added to the public package. The prior v0.6.0 directory and managed installation marker provide the rollback base.

## Device-adaptive research tools — 2026-10-27

The v0.6.0 update adds original executable utilities rather than treating a list of repositories as installed capability. All 13 supplied repositories and the AutoResearchClaw paper were assessed using primary code, interface, packaging and rights files. The [catalog](../skills/research-writer/references/tool-catalog.json) retains inspected revisions and evidence URLs. It distinguishes source-audited interfaces, detected dependencies, executed smoke tests and scientific validation. No upstream code, paper text, model weights or training datasets are bundled. A separate independent primary-source review checked all 13 entries and material licensing/interpretation distinctions.

Skill Forge used a 90-minute effort bound, a maximum of three candidates and six staged workers: three repository auditors, two of whom also constructed separately owned resources, an independent reviewer, and separate fresh baseline/candidate executors. One candidate was constructed. The source arms, input requests and independent evaluator were frozen before behavioral execution; the evaluator's reserved request remained unseen by the parent and constructors until both executions completed. Independent review was not blinded; exact underlying active model/effort was not exposed. Workers inherited the same settings. No paid API or remote inference route was used.

### Actually executed checks

- **54 independent code/API/runtime checks passed.** They covered identifier normalization/dedup/version provenance, mocked provider unavailable/error/empty/metadata/mismatch states, all eight context-field mismatches, wrong hashes/rows/nonfinite values, traversal/duplicate IDs, source access/identity distinctions, remote profiles remaining unprobed, nonexecuting plans, registry structure, and actual molecular outputs.
- **Eight public test methods passed** with the optional molecular environment enabled: run `python evals/toolkit_checks.py --molecular`. Without those packages, omit the flag; molecular checks are explicitly skipped, not counted as executed. These are developer tests, separate from the independently authored 54 checks.
- **RDKit 2026.09.1, Python 3.12.14, macOS arm64:** actual ethanol (`CCO`) formula C2H6O, molecular weight 46.069 g/mol, exact mass 46.041864812 Da, three heavy atoms, one donor and one acceptor. A seeded ETKDGv3/MMFF conformer had nine atoms including hydrogens, 3D coordinates, optimizer status 0, and independently verified artifact hash. Repeating the same seed produced identical SDF bytes in this environment. This does not guarantee byte identity across builds or validate a bound pose.
- **OpenMM 8.6.1:** actual Reference-platform two-particle harmonic energy was 0.5000000000000001 kJ/mol, within 1e-8 of the analytic 0.5. Units, observed platform, CSV provenance and artifact hashes were checked independently. This is an artificial installation/unit test, not a biological MD study or a GPU benchmark.
- **Live Crossref:** a public DOI lookup resolved the requested identity with the expected title, and a bounded generic search returned two metadata records. Results remained metadata-only. Offline/denied/invalid responses were also tested with mocks. Neither a live metadata response nor a successful empty lookup establishes full-text support, peer review or scholarly absence.

Core deterministic checks reject a correct number attached to the wrong run, condition, dataset, metric, unit, seed or statistic, and bind it to the actual CSV row and artifact SHA-256. Empty claim sets report not_checked. Identity lookup is separate from declared source access, and the validator explicitly does not check semantic entailment or scientific truth. Exact comparison performs no hidden rounding or unit conversion.

### Fresh paired execution and observed benefit

Both v0.5.0 and v0.6.0 executed eight matched first-response requests, two added frozen regression controls (punctuation-only and unavailable/incompatible meta-analysis), and one independently authored held-out practical task. Public requests are in [computational-inputs.json](../evals/computational-inputs.json). The eight developmental requests were non-browsing fictional fixtures; real local utilities were permitted in the held-out practical task. No real external engine, remote service or paid call was allowed.

Both arms passed the response fixtures and held-out scientific requirements. Minor candidate length misses were disclosed (121 words for a 120-word target and 254 for 250); this was not claimed as exact length compliance. The candidate reused packaged commands to produce bibliography/device/evidence records and real molecular artifacts, including eight computed claims checked against their CSV/hash context and three deliberately wrong-context fixture claims rejected. The baseline accomplished the task using more custom algorithms and scientific glue. Independently measured task glue was 275 lines/16,587 bytes for the baseline versus 118 lines/12,493 bytes for the candidate. These figures exclude the reusable toolkit's implementation and are a code-authoring proxy, not a time, token, financial-cost or broad quality estimate. The baseline had a documented assertion-count repair; no candidate repair was observed in that task. The narrow observed benefit is reusable executed tooling with less per-task glue, not superior molecular science.

The reserved request is now known regression evidence. Small single runs, shared host settings and nonblind grading do not establish population reliability. Independent review recomputed artifact hashes and checked the actual SDF chemistry/3D coordinates and analytic energy; a self-reported success or exit code alone was insufficient. Prior prewriting, target/destination, humanities/source-only and meta-analysis boundaries remain preserved.

### What was not executed

AutoResearchClaw, Beeblio and the heavyweight prediction/docking/design/ML engines were source-audited; they were **not installed or run** in this validation. No AlphaFold, Boltz, ESM, DiffDock, GNINA, REINVENT or DeepChem inference/training, biological simulation, remote GPU job, model/database download or hosted sequence upload occurred. Open Babel conversion also remains an optional source-audited route. Windows, Linux, CUDA, MPS, ROCm and remote operation are supported as profile/preparation concepts, not universally tested runtime combinations. Device-specific engine setup and task-sized acceptance remain necessary.

Beeblio's PolyForm Noncommercial code is not a bundled MIT dependency. AlphaFold code, weights and output rights differ; other tools also have separate or unverified checkpoint/data/service terms. Current Biohub ESM was assessed separately from the archived Meta ESM. See the catalog for current pin-level qualifications and recheck selected releases before setup. User-owned profiles and local environments are excluded from this public repository.

Metadata, the 18-file skill and its 38 local links passed static validation. The portable builder includes fenced original Python/JSON sources, not automatic execution, and regeneration/consistency checks pass. The prior package and Git revision are retained for rollback. Local package versions are recorded in [optional tested requirements](../extras/cpu-tested-requirements.txt); [device setup](runtime-setup.md) explains adapting them without assuming universal wheels or hardware.

- Evaluated v0.5.0 baseline directory SHA-256: `381666300a1889cf60593370e4240329136c0c9d4d47eb53a51d407f04486ced`.
- Evaluated v0.6.0 candidate directory SHA-256: `3be5fb937f192dd8165e6efcce7013af0cfacddf007642310b4f58ab0e3fea20`.

## Prewriting gate comparison — 2026-10-26

This update makes the user's requested order explicit: establish actual readers and paper type; identify the publication venue type/readership or no-journal/provisional status; audit the dated search record and renew affected searches; compare the nearest published work; then test the proposed contribution before substantive drafting. Tutorial articles receive a teaching route. The one-sentence prior-to-proposed increment is a gap hypothesis, not proof of novelty.

Skill Forge used a 45-minute effort limit, at most three candidates and four workers: a bounded finder/constructor, independent evaluator, and separate fresh baseline/candidate executors. One candidate was constructed. Criteria and eight development requests were frozen before candidate execution; the independently authored reserved request remained unseen by the constructor and parent until both source arms were frozen. No source, input or criterion changed during execution.

| Development case | Required behavior |
|---|---|
| Old hospital-only search, revised community-setting question, tools unavailable | Recognize stale/mismatched coverage, plan renewal and admit unperformed searches; no invented current review |
| Unclear article purpose/readers | Clarify paper type, readership and consequential venue context before drafting; retain Google Docs destination |
| Closest paper already performed the proposed design | Reject unsupported gap, frame replication or revise; connect value to readers and assess feasibility |
| City-change novelty claim | Test substantive difference, importance, conceptual evidence, venue value and practical limits |
| Fresh adequate same-scope search | Review and reuse it without an identical redundant search |
| Supplied-only humanities interpretation | Honor corpus boundary and interpretive genre; no forced journal or empirical novelty claim |
| Practitioner tutorial | Compare existing teaching, plan learner goals and worked examples; label toy data |
| Punctuation-only correction | Exclude the full research workflow |

Inputs are in [prewriting-inputs.json](../evals/prewriting-inputs.json); all source packets and scenarios are fictional. The eight paired requests ran with the same access restrictions: no browsing or external document creation. They test prewriting decisions, source-bound reasoning, honest limitations and appropriate drafting; they do not demonstrate actual live search renewal. The development literature search did run through available web tools, as described below, but that is separate from these behavioral fixtures.

Independent evaluation found the candidate passes every material requirement: **208/208 material points across 9/9 cases**, including the reserved request, plus **32/32 resource-review points**. The baseline scored **206/208** material points across 8/9 passing cases. The baseline was strong and passed seven public cases and the reserved case. In the direct-duplication case, its publication/readership-value and feasibility assessments were partial. The candidate made replication's conditional value to the specified readers explicit and identified missing recruitment, observation, analysis and uncertainty details before promising an adequate study. This is a narrow observed gain on one request, not evidence of general superiority. No critical failure or regression was identified in the candidate.

The evaluator was separate from construction/execution but knew arm labels and inspected their diff; grading was not blinded. Executors inherited the same host/model configuration; the exact underlying model version was not exposed. Each arm ran eight requests in one fresh context, followed by the reserved request in that arm's context. Small single executions do not estimate population reliability or prove research depth across disciplines. The reserved case is now known regression evidence, not a future untouched holdout.

### Foundation renewal, source handling and package checks

A new bounded search used five recorded queries across relevant GitHub skills and primary methodological/editorial resources. The strongest three inspected resources were the ai-skill-scholar literature-review instructions/license, Pautasso's literature-review guidance, and Nature's publication criteria. No upstream code or source prose was adopted and no dependency was added. An inaccessible Nature article and an unverified GitHub immutable revision are recorded as limits; their discovery snippets were not evidence. See [methodological attribution](../skills/research-writer/references/standards.md). The supplied writing-process diagram was read as reference material; its image and source wording are excluded from the package. General reading, planning, revision, style and reference principles were preserved without requiring every pictured section.

The final skill contains 12 files. Metadata and 24 relative links passed static validation, the canonical portable instructions were regenerated and checked, and source/criterion/output bindings were retained privately. Existing MIT notices, source-only and destination boundaries, publication-fact handling, and statistical/interpretive standards are preserved. No claim is made that this round repeated the prior real-data analysis or Google Docs integration tests; those remain historical evidence below.

- Evaluated installed v0.4.0 baseline SHA-256: `aaebc6c91400cc57fb221014140b5f83f78ea11d4a1e0af61cf35534342228d0`.
- Evaluated v0.5.0 candidate SHA-256: `381666300a1889cf60593370e4240329136c0c9d4d47eb53a51d407f04486ced`.

Private baseline snapshots and prior Git revisions permit rollback. Managed updates compare the installed recorded base and preserve any customization conflict rather than force-overwriting it. Raw executions, the reserved scenario and private development records are not published.

## Earlier v0.4.0 release and comparison — 2026-10-26

Version 0.4.0 supersedes the earlier preview. The update used a 60-minute effort limit and at most three candidates. Two candidates were constructed; the first was rejected. Acceptance criteria and request inputs were frozen before evaluation. Fresh execution contexts read only their skill arm and requests, without the grading rubric. Independent grading evaluated the resulting outputs and inspected the behavior-bearing resources.

| Arm | Required checks | Target question/publication checks | Decision |
|---|---:|---:|---|
| Installed v0.3.0 baseline | 52/56 | 30/34 | Retained for comparison/rollback |
| First v0.4 candidate | 53/56 | 31/34 | Rejected: missing required handoff items |
| Final v0.4.0 candidate | 56/56 | 34/34 | Adopted: all required checks pass |

Eight cases covered exploratory questions, empirical manuscripts with incomplete facts, theory without participant data, venue-dependent preparation, humanities work, intake/destination behavior and a reserved case. Public fictional development requests are in [publication-inputs.json](../evals/publication-inputs.json). Improvements were concrete: better exploratory method alternatives and explicit coverage of missing authorship/approval, funding/conflicts, ethics and permissions, data/code/material availability, and venue-dependent cover-letter work. No critical failures or regressions were identified. The final resource inspection passed.

Initial baseline/candidate grading used masked A/B labels. The second revision was identifiable as C. Executors inherited the same model settings; exact underlying model version was not exposed. An independently authored reserved case remained unseen by the constructor before both candidate freezes, but was reused for the second comparison: it provides regression/generalization evidence, not a second independent fresh holdout. These are small single executions, not a population estimate of quality.

### Real evidence review and meta-analytic reanalysis

A fresh executor completed a **corpus-restricted review of Many Labs 1 gain/loss framing**, including bounded searches, screening, original-paper/correction inspection, source-data reconciliation, extraction, appraisal, computation and writing. This was not a field-wide systematic review. The protocol was frozen after feasibility scoping and before numerical extraction; it was not externally preregistered.

Eighteen search records were screened: 16 outside the prespecified corpus, one duplicate or mismatched attachment, and one erratum consulted. The primary paper was obtained through source following. The analysis included 36 study sites from one coordinated replication project, not 36 independent publications. The spreadsheet's gain/loss headers were reversed and one column label duplicated. The codebook and original records established the correct orientation, and all site counts were checked against those records. Two aggregate rows were excluded.

The analysis used 6,271 observed responses from 6,344 session identifiers (73 missing; identifiers do not independently prove unique people). The DerSimonian–Laird random-effects odds ratio was **3.3245 (95% normal CI 2.9677–3.7242)**, with Q=37.0116, df=35, and I²=5.4351%. Common-effect OR=3.3113; leave-one-site-out estimates ranged 3.2536–3.3726. Odds ratios are not risk ratios. The simple estimator and interval are disclosed, not prescribed universally.

An independent checker reextracted all 36 count vectors from the original data and recomputed the main results. The original extraction used Python 3.12.14 and openpyxl 3.1.5; the public standard-library reproduction also passed under Python 3.15.0. An independently implemented high-precision calculation corroborated the arithmetic. The 2019 correction was inspected and concerns other tasks, not this framing result. This checks one real research pipeline, not exhaustive correction/retraction discovery across the literature.

Run the original public script, with only aggregate site counts:

```sh
python3 evals/real-evidence/reproduce.py
```

See [source and method details](../evals/real-evidence/README.md). No participant records, downloaded papers or upstream analysis code are redistributed.

### Native Google Docs delivery and complex scientific writing

One native Google Doc was created in the user's requested workspace folder, populated with the complete real-evidence report and a separate scientific research brief, and read back through the document API. Verification matched all 43 nonempty body paragraphs, 15 named headings and three native tables containing 57 cells. A scoped text replacement changed exactly one occurrence; full before/after comparison confirmed preservation of unrelated content. The document remained private. This verifies create, placement, structured content and scoped editing in one integration, not every external destination.

A separate bounded live research pass developed the user's complex biological idea through premise correction, source inspection, closest-prior comparison, candidate contributions, feasibility and prospective design. Seven recorded searches and six primary sources informed the brief; one source was available only as a publisher abstract and was treated accordingly. Independent review reopened the sources and checked central claims. A close prior study already covered much of the broad initial idea, so the proposed novelty was narrowed and qualified. No biological experiment, novel protein or world-wide novelty claim was validated. The private idea, report, raw outputs and destination URL are excluded from this repository.

### Method sources, integrity and rollback

All eight pages of the two newly supplied methodological PDFs were read; relevant visual pages were inspected. General ideas about question formation and article preparation were implemented as original instructions with attribution. Fixed paragraph rules, a blanket ban on citations in Results, blanket ethics-approval claims, and an erroneous odds-to-risk interpretation were excluded. Reference documents were treated as source material, not instructions to override the user.

The final skill contains ten files and passed metadata/local-link validation. The standalone portable bundle was regenerated and checked against the canonical source. Baseline and final evaluated directory hashes are listed below. Private snapshots and the prior Git revision support rollback. Public files contain no supplied PDFs, participant-level records, private ideas, account credentials or evaluation transcripts.

## Historical checks

The following records describe earlier versions and the capabilities that were still untested at those dates. The 2026-10-26 results above supersede their pending live-delivery and real-data checks.

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

At the time of the earlier preview checks, no stable promotion occurred and main remained v0.2.0. The explicit installation of preview v0.3.0 was distinct from automatic promotion. These historical statements do not describe the current v0.4.0 release.

## File bindings

- Prior v0.2.0 skill directory SHA-256: `b52bfe8cfdfdfc3b6f962494cbc159cd0d8ecd045e6766cfd1e91e44e0196a45`.
- Candidate v0.3.0 skill directory SHA-256: `96e7449fb229b8fb182a6415482547e8fca69ad087dd24d43d19058b9aa9e365`.

Directory hashes identify the files evaluated; they do not authenticate model execution or prove research quality. Raw transcripts, rubric bindings, source coverage and the development brief remain private. Public synthetic requests are in `evals/`.

- Final v0.4.0 skill directory SHA-256: `47c4399676e29ab0b3442f254d265166576473365d45f35b77d5e3bf511d6363`.
