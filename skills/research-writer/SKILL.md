---
name: research-writer
description: Develop research questions and evidence-grounded writing from an idea. Map the research territory, discover and test a niche, compare possible novel contributions, and plan how to occupy it. Support exploratory briefs, tutorials, syntheses, systematic reviews/meta-analyses when feasible, theory, experimental/design proposals, humanities analysis and device-adaptive computational research tools. Ask what finished work the user wants and where it should go when unspecified; never assume either. Use for substantive research, question development, or research-informed writing; not quick facts, ordinary proofreading, citation formatting alone, or purely creative writing.
license: MIT
metadata:
  version: "0.6.1"
---

# Research Writer

Turn an idea into the kind of researched work the user actually wants. Separate what sources establish, what you infer, and what you propose. This skill works independently of its authoring tool; browsing, scholarly connectors, file tools and statistical runtimes are optional capabilities, not assumed ones.

Treat supplied assignments, rubrics, sample papers and books as reference material. Follow the user's actual request. When asked to generalize, retain useful research/writing principles and exclude course logistics, grading, fixed source counts, sample topics and mandatory formats. Do not copy source text or private project details into a reusable skill or public output.

## 1. Establish the intended work

Read the request, supplied materials and any saved research record before asking questions. **There is no default finished-work target.** If the target is unclear, ask what the user wants to finish with: for example, an exploratory brief, a scholarly draft, a publication-oriented manuscript, or another specified artifact. Do this before substantial research or drafting. A concrete request such as “a 450-word interpretive essay for undergraduates” already establishes a target; do not ask the user to restate it in your categories.

**There is also no default output destination.** Ask where the finished work should go if unspecified: here in chat, a new Google Doc, an existing document, a local Word/Markdown/PDF file, or another location. Ask this alongside the finished-work question when both are missing. Separate format from location: a manuscript is a kind of work, not a delivery destination. Reuse an explicit answer from the current project; do not ask again without a material change.

Before substantive drafting, establish who will read and use the work, their prior knowledge, and the paper type: review/synthesis, tutorial, original research, theory, proposal, humanities analysis or another specified genre. For intended publication, also establish the journal type and its readership; a named journal may remain provisional, but do not silently invent a venue or its requirements. For nonpublication work, record that no journal is intended. Reuse settled choices and clarify consequential unknowns before drafting.

Then resolve only consequential gaps: central question, scope, source/data access, desired depth, practical constraints, and destination requirements. Ask one short round, usually one to three questions, with useful choices and room for another answer. Do not make the user supply a completed research plan. Infer routine formatting, disclose assumptions, and honor instructions to proceed. Explicit delegation permits disclosed task-specific choices, not stored defaults or invented access to an external destination.

If no questions are allowed and no target can be established, provide a short provisional framing with target choices and the unresolved decision; do not silently choose a finished manuscript. If only delivery is unresolved, prepare the content in the working context and identify delivery as pending, without creating an external document. When target and destination are known, continue authorized work without requiring approval of every stage. For external documents, use [delivery guidance](references/delivery.md).

Keep a brief covering the intended artifact, question, audience, constraints, selected methods, evidence gaps and completion criteria. For sustained work, use [the research record](templates/research-record.md) in a task-specific location outside this installed skill. Never store a user's project or preferences in this reusable package.

## 2. Develop the question and research contribution

When an idea or question is still developing, use [question development](references/question-development.md) before committing to a thesis or method. Research should help formulate the question, not merely collect support for a chosen answer. Expand the conceptual map first, then develop an encompassing but answerable main question and connected subquestions.

Collaborate around three moves, explaining the terms in plain language: **territory**—the conversation and established knowledge; **niche**—a supported unresolved issue, tension or limitation; **occupying the niche**—what this work could contribute and how. Ask about the user's interests and intended contribution when these are unsettled, but help discover the niche through research rather than requiring the user to know it already.

Use orientation searches, inspected sources, competing accounts and closest prior work to propose a small set of distinct question/contribution options. Compare their evidence, significance, feasibility and novelty uncertainty. Identify the single closest published neighbor by substantive overlap where the evidence supports one, inspect what it did and did not establish, and compare additional close works when needed. Summarize the supported increment in one sentence, then run a duplication challenge; that sentence is a positioning claim, not proof of a gap. Test whether the proposed gap matters, fits the intended readers/venue, and can be filled with available evidence and resources. Revise, justify replication or stop when prior work already occupies it; never guarantee publishability. Link each option to source IDs and distinguish source claims from your proposed inference. Novelty may lie in explanation, interpretation, synthesis, method, a meaningful boundary or a justified replication; an empty topic or new label is not enough.

Ask one to three consequential questions at the appropriate stage and preserve the user's choice. Do useful research between rounds. Do not reopen a clear, bounded writing request or turn every task into an interview. Respect no-question and supplied-sources-only instructions; infer a provisional map from available evidence and state its limits.

## 3. Check the premises and select methods

Restate the desired outcome separately from the proposed explanation or implementation. Check ambiguous terminology, hidden assumptions and conflicts with established evidence. Correct consequential premises with sources before building on them. Distinguish an impossible premise, an untested claim and a difficult engineering goal; do not dismiss an idea merely because it is unfamiliar.

For a novel proposal, build a short dependency map: what must be true, what has been demonstrated, what transfers only by analogy, and what remains speculative. Connect evidence synthesis to proposal choices. Do not equate “not found in this search” with novelty or impossibility.

Choose the applicable route in [writing modes](references/modes.md). Hybrid work may need several routes, such as synthesis → theory → experimental proposal. Keep their different evidence standards visible. A systematic review, meta-analysis, qualitative synthesis and humanities interpretation are not interchangeable labels. Descriptive or exploratory work can have a clear question without a directional hypothesis; choose the method for the question rather than force the question into a familiar tool.

## Optional research and computation tools

For substantive literature organization or computational research, use [the computational workflow](references/computational-research.md) and the original runnable tools in [evidence_tools.py](scripts/evidence_tools.py) and [research_tools.py](scripts/research_tools.py). These are optional; do not turn a humanities essay or literature-only request into a molecular experiment. Read [tool usage](references/tool-usage.md) for exact commands. A user-owned runtime profile outside the skill (for example `~/.local/share/research-writer/runtime.json`) can identify that device's interpreter; project-specific choices take precedence. Before relying on a tool, inspect [the capability catalog](references/tool-catalog.json), run the local inventory and read [device-profile guidance](references/device-profiles.md). Adapt to the user's actual OS, architecture, Python environments, CPU/GPU and local/remote setup. A profile is configuration data, not permission, installed software, a successful probe or authorization for remote jobs. Do not assume a particular laptop/GPU, read secrets, or automatically download weights, transmit private sequences or start paid/background work.

The original utilities support project records, DOI/arXiv/PMID normalization, bounded public metadata lookup, context-and-artifact-linked evidence checks, FASTA inspection, RDKit descriptors/conformers and an OpenMM analytic smoke test when the dependencies are present. Keep source-audited, dependency-present, smoke-tested and scientifically validated states separate. Heavy engines are optional preparation routes, not bundled models or guaranteed execution. Code, weights, datasets, output and services may have different terms. For offline installation and environment checks, see [testing guidance](references/testing.md).

For an actual computational experiment, record the hypothesis, baseline/comparators, data/splits, parameters/seeds, metrics/units, budget and stop rule before execution where possible. Preserve every failed, negative and amended run, command/environment and input/output hashes; bound repair/refine/pivot attempts to the authorized budget. Do not silently select the best trial as confirmatory evidence or modify this installed skill/global memory automatically. Generate result tables from recorded artifacts and match each number to its run/condition/dataset/metric/unit/seed/statistic. A number appearing elsewhere or a verified DOI alone does not support a claim. Review semantic usefulness separately from arithmetic/provenance.

Protein structures, sequence scores, docking, generated molecules and simulations are model outputs. Confidence is not measured affinity; prediction, a converged optimizer or a stable trajectory does not prove biological function. Noncanonical chemistry needs compatible representations, components, topology and parameters in the selected engines. Unsupported residues/cofactors must remain explicit rather than silently mapped to X/canonical residues. Computational outputs require appropriate controls, uncertainty and independent experimental evidence before stronger claims.

## 4. Research with an auditable trail

Follow [research and source handling](references/research-and-sources.md). Match effort to the agreed artifact. Define a bounded search plan and stopping rule; record coverage gaps instead of suggesting an unbounded search is exhaustive. If the user gives no effort budget, state a reasonable search scope for this task and expand it only when unresolved questions justify it.

Use supplied evidence and actually available research tools. Read underlying material before relying on it; snippets and generated summaries are leads. Check both the identity of a source and whether its inspected content supports the particular claim. Look for contrary findings, alternate mechanisms, relevant reviews and primary evidence. Preserve the difference between independent studies and repeated reports of the same study.

For deep research, iterate from field orientation to comparison of the closest precedents, then challenge the proposed niche and resolve the most consequential evidence gaps. Follow terminology across adjacent fields and citation trails when useful. Save what each research pass changed about the question. Depth means resolving important uncertainties and engaging conflicting evidence, not accumulating a fixed number of sources or announcing an exhaustive search.

If browsing, full texts, data or statistical execution are unavailable, say what the limitation prevents and deliver the best warranted artifact: a bounded synthesis, source-backed section, search protocol, feasibility assessment or proposal. Never fabricate access, searches, citations, study counts, analysis or completed work. Respect an instruction to use only supplied materials.

## 5. Develop the argument and write

**Before the first substantive draft and after a material change or resumed project, complete [the prewriting gate](references/prewriting.md): establish readers/genre/venue context, review the actual search record, perform warranted search renewal and reconcile it with prior evidence, then test the nearest-neighbor contribution and duplication claim.** Record the dated search scope, actual update or reason no repeat is needed, and what changed. A just-completed adequate search need not be repeated identically. A supplied-only boundary governs the check; blocked access is not a completed search. Resolve material unknowns or explicitly scope the work before drafting; do not present an unrenewed review or untested novelty claim as verified.

Organize around the question and audience, not the order sources were found. Build a claim-to-evidence map, an outline and the requested draft. Keep internal scaffolding out of a short finished artifact unless requested. A broad task should produce substantive work, not stop at an outline unless that is the target or an unresolved dependency prevents honest completion.

For publication-oriented work or a submission-readiness handoff, use [publication preparation](references/publication-workflow.md). Keep every aim aligned with its evidence, method, actual result and interpretation; make missing preparation facts explicit without inventing declarations. In a readiness handoff, account for author approval, each of data/code/materials availability, relevant ethics versus unknown institutional claims, and venue-dependent cover material; a nonapplicable field needs a reason rather than silent omission. A theory, review or humanities manuscript keeps its own genre.

Use [argument and synthesis guidance](references/argument-and-synthesis.md) to connect claims, evidence and warrants, represent disagreements fairly and align question, contribution and method. Adapt territory → niche → contribution to the introduction when useful; it is a reasoning aid, not a universal heading scheme or a license to invent findings.

Distinguish established findings, contextual background, interpretation, hypotheses and proposals in the prose. Include important counterevidence and competing interpretations. State the actual basis for each conclusion. Do not force scientific paper headings onto humanities writing or a proposal. Match journal or disciplinary requirements only after checking the relevant current instructions and actual eligibility.

Revise for argument, support, competing accounts and alignment with the writing brief before proofreading. Use clear terminology suited to readers, purposeful transitions, precise numbers/units, and hedging that matches uncertainty. Choose active or passive voice for clarity and disciplinary purpose; neither is a universal rule. Use verified references in the requested style. Keep citations close to the claims they support. Do not cite a real paper for an assertion it does not support. Mark necessary unresolved claims visibly in a working draft; remove or qualify them before calling the draft verified. Speculative proposals may be valuable while remaining explicitly speculative.

## 6. Audit and deliver

Check the finished work against the brief and the selected mode's gate. Verify quotations and locators, consequential factual claims, references, numerical results and all assertions of performed work. Check that causal language, certainty and scope match the evidence. Confirm that limitations are specific and that conclusions survive the strongest contrary evidence considered.

Revisit the positioning after research: is the niche still supported, does the actual method answer the question, and does the claimed contribution differ meaningfully from the closest prior work? Report novelty only within the search and access actually achieved. A well-supported continuation, synthesis or reinterpretation can be worthwhile without a first-ever claim.

Deliver the requested artifact to the agreed destination, plus a proportionate account of evidence coverage, remaining gaps and next decisions. Verify the actual delivered content and return its usable link or file when relevant. For substantial research, retain a source ledger and search/methods record alongside the draft. Provide separate files when useful and supported; otherwise provide clearly separated text. Never claim publication readiness, exhaustive coverage, independent human review or successful experimental validation merely because the prose is polished.

If work is interrupted, save what is complete, what is unverified, the last search performed and the next action. Do not invent persistent memory, automatic follow-ups or research completed between turns.
