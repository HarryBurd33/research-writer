# Research Writer

A reusable agent skill for researching an idea and turning it into the finished work you want.

**It has no default output target or destination.** When either is missing, it asks what you want to produce and where it should go: in chat, a Google Doc, a local document, or another supported location.

## What it supports

- Exploratory research briefs and literature syntheses.
- Systematic reviews and quantitative meta-analyses when the evidence and tools support them.
- Theory papers and conceptual arguments.
- Experimental protocols and engineering/design proposals.
- Humanities, historical and interpretive analyses.
- Other research-informed writing and combinations of these forms.

The workflow checks the idea's premises, chooses an appropriate method, verifies sources, develops the argument, writes the artifact and audits its claims. It distinguishes evidence, interpretation, hypotheses and proposed work. It does not invent citations, experimental results or statistical analyses to make a draft look complete.

## Start using it

The installable skill is in [`skills/research-writer`](skills/research-writer). Use your agent's supported skill installer to install that complete folder, keeping its references and template together. The entry point is [`SKILL.md`](skills/research-writer/SKILL.md). This repository does not automatically install or activate it.

If your agent cannot install skills, supply [`portable/research-writer.md`](portable/research-writer.md) as instructions along with your task. The portable file contains the workflow and its supporting guidance. Skill Forge is not required to use either version.

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
- [`skills/research-writer/references`](skills/research-writer/references): writing modes, source handling, delivery and methodological sources.
- [`skills/research-writer/templates/research-record.md`](skills/research-writer/templates/research-record.md): optional record for sustained projects.
- [`portable/research-writer.md`](portable/research-writer.md): single-file version.
- [`docs/validation.md`](docs/validation.md): test evidence and limitations.
- [`evals`](evals): synthetic requests used for the behavioral checks.

## Status and rights

Version 0.2.0. Created with Skill Forge. The validation report distinguishes executed checks from untested capabilities; a small test set does not establish research quality across every discipline.

The workflow text is original. Referenced methodological sources retain their own rights; their text is not redistributed. No public-distribution license has been selected. Project-specific research and private development notes are excluded from this repository.
