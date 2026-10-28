# Research Writer

A reusable agent skill for researching an idea and turning it into the finished work you want.

**Version 0.6.0** adds executable evidence/bibliography utilities, device-adaptive tool profiles, and optional computational-research guidance while retaining the prewriting workflow. It includes original local RDKit/OpenMM utilities and a source-audited catalog of all 13 requested engines. See the [tool guide](skills/research-writer/references/tool-usage.md), [capability catalog](skills/research-writer/references/tool-catalog.json) and [validation](docs/validation.md).

**It has no default output target or destination.** When either is missing, it asks what you want to produce and where it should go: in chat, a Google Doc, a local document, or another supported location.

## Develop the research question

Bring a rough idea as well as a finished question. The skill helps map the **territory** (the conversation and established knowledge), investigate a **niche** (a supported unresolved issue), and decide how to **occupy the niche** (a worthwhile contribution and a way to investigate it).

It researches before fixing the thesis, offers distinct question/contribution options, compares them with the closest prior work, and asks about the choices that matter to you. It expands the conceptual picture before converging on a precise main question and connected subquestions. If the first idea is already well studied, it helps revise the niche instead of manufacturing a novelty claim.

Novelty is assessed within the literature actually inspected. Replication, synthesis, reinterpretation, explanation, meaningful comparisons and feasible design validation may all be worthwhile contributions. A confident first-ever claim is not a requirement.

Try:

> Use Research Writer to develop my idea into a research question. Investigate the territory, help identify a worthwhile niche, and compare ways I could contribute. Produce a question-development brief here in chat and ask me about the choices that would change its direction.

## Before substantive writing

The skill first establishes the readers, their prior knowledge and intended use; the paper type (including tutorials); and the journal type/readership when publication is intended. A named journal can remain provisional, and nonpublication work does not need one. It then reviews the dated search record, renews affected searches and reconciles new evidence before drafting. An adequate fresh search can be reused; supplied-source restrictions and access limits remain explicit.

For a proposed contribution, it identifies the closest published neighbor, checks what that paper actually established, and states the proposed increment in one sentence. It then challenges duplication and assesses importance, readership/venue value and practical feasibility. A well-phrased gap is a hypothesis to investigate, not proof of novelty or a promise of publication.

## What it supports

- Exploratory research briefs and literature syntheses.
- Tutorials and instructional articles with explicit learners and worked examples.
- Systematic reviews and quantitative meta-analyses when the evidence and tools support them.
- Theory papers and conceptual arguments.
- Experimental protocols and engineering/design proposals.
- Humanities, historical and interpretive analyses.
- Other research-informed writing and combinations of these forms.

The workflow checks the idea's premises, chooses an appropriate method, verifies sources, develops the argument, writes the artifact and audits its claims. It distinguishes evidence, interpretation, hypotheses and proposed work. It does not invent citations, experimental results or statistical analyses to make a draft look complete.

For an article intended for a journal, the skill also checks venue fit, alignment between aims and evidence, and missing authorship, funding, ethics, availability and submission information. It preserves the chosen genre and never invents results or declarations.

## Executable tools and device adaptation

The complete skill contains original Python scripts for DOI/arXiv/PMID normalization with retained provenance, bounded Crossref search and DOI metadata lookup, project initialization, exact context-and-artifact-linked evidence checks, FASTA inspection, RDKit descriptors/seeded conformers, and an OpenMM analytic Reference-platform energy check. Standard-library commands require Python 3.10+; the two molecular packages are optional isolated dependencies.

Device profiles describe local or remote environments without embedding anyone's hardware, paths or credentials in the shared package. Inventory, declared configuration, successful smoke tests and scientific validation are distinct. Heavy engines are not bundled or auto-launched, and no paid API, model weights, remote machine or external sequence service is assumed. See [device guidance](skills/research-writer/references/device-profiles.md) and [setup/use](skills/research-writer/references/tool-usage.md).

The catalog covers AutoResearchClaw, Beeblio, AlphaFold 3, Boltz, Meta ESM, Biohub ESM, OpenMM, RDKit, DeepChem, DiffDock, REINVENT4, Open Babel and GNINA. These tools do different jobs; code, weights, data, outputs and service terms are assessed separately. No upstream source or weights are redistributed. A prediction is not an experiment, docking confidence is not measured affinity, and a provenance check does not prove semantic support or scientific usefulness.

## Start using it

See the [usage guide](docs/usage.md) for prompts covering question development, synthesis, theory, proposals and humanities writing. The [validation report](docs/validation.md) includes executed behavioral comparisons, native Google Docs delivery, a complex scientific proposal, and a reproducible review and meta-analytic reanalysis of 36 real study sites.


The installable skill is in [`skills/research-writer`](skills/research-writer). Use your agent's supported skill installer to install that complete folder, keeping its references and template together. The entry point is [`SKILL.md`](skills/research-writer/SKILL.md). This repository does not automatically install or activate it.

If your agent cannot install skills, supply [`portable/research-writer.md`](portable/research-writer.md) as instructions along with your task. The portable file contains the workflow, guidance, catalog and original tool source. To execute tools, review and save the named Python/JSON resources as files with their folder layout; a pasted prompt alone cannot install dependencies or execute code. Skill Forge is not required to use either version. Regenerate it with `python3 scripts/build_portable.py`; verify it with `python3 scripts/build_portable.py --check` (Python 3.9+, standard library only).

Try:

> Use Research Writer to develop my idea about public libraries and social connection. Ask me what finished work I want and where it should go.

Or specify the choices directly:

> Use Research Writer to write a scholarly synthesis and a conceptual research proposal for organizational researchers. Put it in a new Google Doc. Distinguish established findings from the new hypothesis and identify the evidence needed to test it.

Quick definitions, ordinary proofreading and reference-formatting requests do not need this workflow.

## Delivery and tool access

Google Docs and other external destinations require a working integration and appropriate access. The skill distinguishes creating a new document from editing an existing one, checks the actual saved result and returns its link. If delivery is blocked, it preserves the draft and explains what is missing rather than claiming success or silently substituting a different destination.

Live research requires browsing or suitable research tools. Full texts may require supplied access. Quantitative meta-analysis additionally requires suitable extracted data and a statistical runtime. Without those capabilities, the skill produces an honestly scoped alternative such as a source-bounded synthesis or a research protocol.

## Files

- [`skills/research-writer/SKILL.md`](skills/research-writer/SKILL.md): main workflow and discovery metadata.
- [`skills/research-writer/references/question-development.md`](skills/research-writer/references/question-development.md): iterative territory, niche, contribution and novelty workflow.
- [`skills/research-writer/references/argument-and-synthesis.md`](skills/research-writer/references/argument-and-synthesis.md): source roles, claims, evidence, warrants and fair counterarguments.
- [`skills/research-writer/references`](skills/research-writer/references): writing modes, source handling, delivery and methodological sources.
- [`skills/research-writer/templates/research-record.md`](skills/research-writer/templates/research-record.md): optional record for sustained projects.
- [`portable/research-writer.md`](portable/research-writer.md): single-file version.
- [`docs/usage.md`](docs/usage.md): practical prompts and ways to guide a sustained project.
- [`docs/validation.md`](docs/validation.md): test evidence and limitations.
- [`evals`](evals): synthetic requests used for the behavioral checks.

## Status and rights

Version 0.6.0. Created with Skill Forge. The validation report distinguishes executed checks from untested capabilities; a small test set does not establish research quality across every discipline.

The workflow text is original. Referenced methodological sources retain their own rights; their text is not redistributed. Original code, workflow instructions and documentation are licensed under the [MIT License](LICENSE). The aggregate example data retains its documented CC0 provenance. Project-specific research and private development notes are excluded from this repository.
