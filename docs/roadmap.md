# Research Writer: remaining work and acceptance plan

Plan dated 2026-10-27. This is a roadmap, not a claim that its proposed features or tests have run. The starting release is v0.6.0; see [validation](validation.md), [runtime setup](runtime-setup.md) and [tool catalog](../skills/research-writer/references/tool-catalog.json). Preserve the user's device-adaptable design, genre/audience/destination intake, renewed literature search before substantive writing, and tested prior behavior.

## Phase 1 implementation status

v0.6.1 adds the CI workflow, public regressions and installed-package self-check described below. Local executed checks and hosted-matrix status are recorded in [validation](validation.md); defined matrix jobs are not automatically passing jobs. Later phases remain planned.

## Starting point

Verified in the v0.6.0 evaluation: 54 independent checks, eight public test methods with molecular dependencies enabled, paired research-writing cases, one held-out computational task, live Crossref metadata lookup/search, RDKit descriptors/conformers, and an artificial OpenMM Reference control. The tested runtime was macOS arm64/Python 3.12.14. Earlier versions also have bounded real-evidence and Google Docs delivery evidence; these are historical checks, not fresh v0.6 service tests.

Heavy engines are source-audited preparation routes. A profile does not install dependencies, probe a remote host, accept model terms, authorize uploads or submit jobs. Numeric provenance checks do not establish scientific truth or whether a paper supports a sentence. Crossref metadata is not full text. Predictions are not experiments.

## Ordered work packages

### 1. Complete the current release and make tests portable

First reconcile the installed package and PR contents with the reviewed release. Promote through the protected pull request only with the required merge authorization and GitHub checks. Preserve a verified prior version and managed-install customizations.

Next add public CI for supported Linux, Windows and macOS runners. Use Python 3.10 and a currently supported newer version for standard-library utilities; select molecular combinations only after checking actual wheel availability. Add an installed-package smoke and portable-bundle check. Promote the private independent edge cases into sanitized public regressions without exposing private research or calling them new held-out tests.

Acceptance: fresh-checkout and installed-copy execution; all identifier, provider-error, eight-context-field, malformed-input, path-boundary and no-overwrite controls pass. Missing optional dependencies explicitly skip molecular tests; skips never imply backend support. Reproduce ethanol chemistry and analytic energy within defined tolerances, allowing build-dependent conformer bytes. Verify the distribution contains its scripts, catalog, references and license. Keep required CI check names stable and avoid weakening branch protection.

### 2. Strengthen literature retrieval and source support

v0.6.2 implements bounded public-index adapters and source-support record integrity checks. See [validation](validation.md) for actual executed coverage and remaining semantic-review limits. Broader provider coverage, exhaustive discovery and automatic scientific truth verification are not claimed.

Implement optional adapters one at a time for suitable scholarly indexes, open full-text sources and correction/retraction information after checking current official interfaces and terms. Record query, date, filters, pagination, database coverage, source identity, versions and actual access level. Search renewal must follow the question's changed scope rather than a fixed age rule. Preserve supplied-only restrictions.

Add a separate claim-to-passage review record with source version, page/section, supporting passage locator, support/contradiction/uncertain judgment and reviewer rationale. This supplements the numeric verifier; it must not relabel deterministic checks as semantic proof. Respect access rights and quotation limits; do not bypass paywalls.

Acceptance: frozen mock responses for rate limits, timeouts, pagination, malformed IDs, corrections and conflicting versions; public live controls; metadata-only and inaccessible full text never count as read. Duplicate reports remain one evidence family. An independent reviewer checks supported, contradicted and ambiguous claims against accessible primary text. Report retrieval coverage and unresolved evidence rather than promising exhaustive search or universal novelty.

### 3. Turn selected preparation routes into optional executable adapters

Start with a small CPU conversion control for Open Babel, then one useful engine selected for a real task. Do not install every engine into one environment. Before each adapter, recheck its pinned interface and separate code, weights, data, output and service terms. Inspect the user's actual device, memory, storage, backend and available environment. Do not promise CUDA, ROCm or MPS support based on a profile declaration.

Suggested sequence after the CPU control: one protein prediction/representation route, one docking route, then task-justified DeepChem or REINVENT workflows. AlphaFold, Boltz and the two ESM implementations require separate compatibility decisions; DiffDock and GNINA scores require separate interpretation. AutoResearchClaw and Beeblio integration remain optional projects with their own provider, license and compute requirements, not mandatory runtime dependencies.

Acceptance per adapter: isolated environment; version and asset hashes; input validation; explicit transfer/download disclosure; exact bounded invocation; timeout/failure handling; independent parsing of output chemistry/identity; an official small example plus a negative control; and recorded observed backend. Benchmark with a licensed reference dataset and task-specific metrics before claiming scientific performance. A smoke test permits only an execution claim. Never equate docking confidence with affinity or a predicted structure with biological function.

### 4. Add bounded remote/device execution only when needed

Keep local planning usable on ordinary devices. If remote execution is requested, introduce inspect, prepare, submit, status, collect and cancel as distinct operations. Use existing authenticated connections, a user-selected host and output directory, data-transfer consent and explicit resource limits. Credentials must remain outside profiles and published artifacts. Paid services require an explicit spending boundary.

Acceptance: mocked transport first, then an authorized disposable real job. Test remote identity, unsupported backend, insufficient space, connection loss after submission, duplicate-resume prevention, cancellation, partial outputs, checksums and restart recovery. A dropped connection must become an uncertain job requiring reconciliation, not an automatic resubmission. No remote hardware is required to use the core skill.

### 5. Expand end-to-end research and writing evaluation

Create new held-out cases in separate contexts before changing behavior. Cover a real bounded literature review, a feasible quantitative synthesis, theory, tutorial, humanities interpretation, experimental/design proposal and a duplication case that invalidates the original gap. Include ambiguous audience/genre/destination, conflicting source families, supplied-only work and an unavailable-service case.

Acceptance: freeze protocol, sources, rubric and exclusions before evaluation; compare against v0.6; assign review independently from construction; report nonblind review and sample limits. For synthesis, verify screening, extraction, dependencies, effect-size calculations, uncertainty and conclusions with an independent reference calculation. Renew searches and test the nearest-neighbor gap before drafting. For delivery, re-read a newly created document and verify formatting, references and destination; never publish or message others merely to test. Prior delivery evidence can be reused as regression history, not claimed as a new integration run.

## Review, release and stop rules

For each implementation package, use a maximum of three candidates and an initial 30-minute investigation/build bound; establish a separate realistic bound before any large engine or benchmark run. The active agent owns integration. Assign independent review to a fresh evaluator when available, with frozen criteria and no edits to the candidate; otherwise disclose that review was not independent. Do not claim a model, token, time or cost improvement without actual measurements.

Adopt only after relevant regressions and the package-specific gate pass. Version behavior changes separately, regenerate the portable bundle, check licenses and public content, upload to a protected PR, update a managed installation only when its base/customizations reconcile, and verify the installed bytes and selected runtime. Report source-audited, dependency-detected, smoke-tested and benchmark-validated states separately. Publish test commands, failures, skipped combinations and rollback instructions. No unattended service or background research is implied.

## Decisions needed at the point of execution

- Select a concrete task and engine before large downloads or GPU setup. There is no mandatory device or engine default.
- Supply a remote connection only if remote execution is selected; ordinary CPU and writing workflows need none.
- Establish a spending/download/compute boundary before paid calls, assets or long jobs.
- Approve the exact protected-main merge when required. Uploading a branch and installing it are distinct from promoting main.

## Limits that cannot be eliminated by packaging

No finite search guarantees novelty or completeness. Statistical pooling depends on suitable evidence and methods; insufficient data may require a review or proposal instead. Prediction scores, simulations and generated candidates need task-specific validation and often experiments. External availability, access rights, model licenses and hardware limits remain real constraints. The appropriate response is a documented evidence boundary or alternative workflow, not a claim that every limitation has been solved.
