# Research Writer — version 0.6.0

A reusable research-and-writing skill with no default finished-work target or output destination. It asks what you want to produce and where it should go when either is missing, then selects methods suited to the work. Exploratory briefs, scholarly drafts and publication-oriented manuscripts are all valid targets. Delivery can be in chat, a Google Doc, a local document or another supported location.

It also helps develop the research question itself. It maps the territory, investigates possible niches, compares contribution options against the closest prior work and helps decide how to occupy the niche. It revises the question as evidence changes and distinguishes possible novelty from a verified difference within the inspected literature.

Publication-oriented work also uses a conditional [preparation guide](references/publication-workflow.md): it checks aim–method–result alignment, venue fit, tables and abstract consistency, and missing authorship or declaration facts. Exploratory work need not invent a hypothesis, and journal conventions do not become universal writing rules.

Before substantive writing, it establishes readers, paper type and publication context, reviews the actual search record and renews affected searches, then tests the proposed contribution against the closest published neighbor. A one-sentence increment is checked for duplication, importance, venue fit and feasibility. Tutorials have their own teaching route. Supplied-source boundaries and explicit no-journal choices are respected.

## Optional tools and device adaptation

The original Python utilities provide bibliography normalization and public metadata lookup, project records, artifact/context-linked evidence checks, FASTA inspection, and RDKit/OpenMM CPU utilities when installed. [Computational guidance](references/computational-research.md) explains use; [device profiles](references/device-profiles.md) adapt local or remote environments. The [13-engine catalog](references/tool-catalog.json) records inspected revisions, inputs/outputs, dependencies, distinct rights and scientific limits.

No heavy engine, model weights, paid API, remote compute service or external app is bundled or automatically enabled. An inventory is not a successful inference run. The standard-library tools run with Python 3.10+; molecular utilities require separate compatible RDKit/OpenMM packages. Use a project environment or user-owned runtime profile outside this skill.

## Use

Install the complete `research-writer` folder as a skill using your agent's supported skill installation process; preserve its internal folders. The entry point is [SKILL.md](SKILL.md). Skill Forge is not required. Installation is a separate action from creating this package.

For an agent without skill installation, supply the companion portable Markdown file as instructions, then state your task. The portable version includes the core instructions, methods, source guidance and blank research record.

Example requests:

- “Use Research Writer to help develop my idea about public libraries and social connection. Ask me what finished work I want and where it should go.”
- “Use Research Writer to help turn my idea into a research question. Investigate the territory, help me identify a worthwhile niche, and compare ways I could contribute. Produce a question-development brief here in chat.”
- “Use Research Writer to write a scholarly synthesis of this literature, then propose a theory in a new Google Doc. My audience is organizational researchers. Show which claims are established and which are new.”
- “Use Research Writer to assess whether these studies support a meta-analysis. If they do not, give me a useful synthesis and identify the missing data.”
- “Use Research Writer to write a 1,500-word humanities essay from these texts, engaging a competing interpretation.”

“Fix this comma,” “define meta-analysis in one sentence,” and “format these references” should not trigger the full workflow.

## Capabilities and limits

Browsing or a scholarly connector enables live discovery and verification. Full texts may require user-provided access. Statistical meta-analysis requires suitable extracted data and an execution environment; the skill never promises valid pooling from citations alone. With supplied materials only, it can still analyze and write within that boundary. File persistence is optional; it can provide a research record as text.

Research quality depends on accessible evidence, tool capabilities and expert judgment. A polished draft is not evidence that a hypothesis is true or that a manuscript meets all requirements for publication.

All workflow text in this package is newly authored. Referenced methodological sources retain their own rights. No third-party source text is redistributed. This original skill package is licensed under the [MIT License](LICENSE).
