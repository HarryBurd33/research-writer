# Research Writer — version 0.14.0

A reusable research-and-writing skill with no default finished-work target or output destination. It asks what you want to produce and where it should go when either is missing, then selects methods suited to the work. Exploratory briefs, scholarly drafts and publication-oriented manuscripts are all valid targets. Delivery can be in chat, a Google Doc, a local document or another supported location.

It also helps develop the research question itself. It maps the territory, investigates possible niches, compares contribution options against the closest prior work and helps decide how to occupy the niche. It revises the question as evidence changes and distinguishes possible novelty from a verified difference within the inspected literature.

Publication-oriented work also uses a conditional [preparation guide](references/publication-workflow.md): it checks aim–method–result alignment, venue fit, tables and abstract consistency, and missing authorship or declaration facts. Exploratory work need not invent a hypothesis, and journal conventions do not become universal writing rules.

Before substantive writing, it establishes readers, paper type and publication context, reviews the actual search record and renews affected searches, then tests the proposed contribution against the closest published neighbor. A one-sentence increment is checked for duplication, importance, venue fit and feasibility. Tutorials have their own teaching route. Supplied-source boundaries and explicit no-journal choices are respected.

## Optional tools and device adaptation

The original Python utilities provide bibliography normalization and public metadata lookup, project records, artifact/context-linked evidence checks, FASTA inspection, and RDKit/OpenMM CPU utilities when installed. [Computational guidance](references/computational-research.md) explains use; [device profiles](references/device-profiles.md) adapt local or remote environments. The [13-engine catalog](references/tool-catalog.json) records inspected revisions, inputs/outputs, dependencies, distinct rights and scientific limits.

No heavy engine, model weights, paid API, remote compute service or external app is bundled or automatically enabled. An inventory is not a successful inference run. The standard-library tools run with Python 3.10+; molecular utilities require separate compatible RDKit/OpenMM packages. Use a project environment or user-owned runtime profile outside this skill.

## Literature and source support

Use [bounded retrieval](references/literature-retrieval.md) for public literature metadata, recorded correction relationships and accessible open text. Use [source-support records](references/source-support.md) to connect each claim to the inspected source version, passage and reviewer rationale. Record integrity never establishes that a judgment is correct.

## Deeper discovery and claim inventory

[Deeper retrieval](references/deeper-retrieval.md) adds anonymous first-page
OpenAlex search, exact-work/reference-ID lookup and version-pinned official
arXiv HTML. [Claim audit](references/claim-audit.md) checks declared claim/source
coverage and preserves partial, contradictory and uncertain judgments, versions,
status and family declarations. Neither retrieval nor record validity establishes
scientific truth or drafting clearance. No new runtime dependency is required.

## Selected executable engines

[Open Babel conversion](references/molecular-conversion.md) uses a separately supplied executable and independent RDKit checks. [Small ESM-2 embeddings](references/protein-embeddings.md) use a separate compatible interpreter and pinned local model assets. Model preparation is explicit; inference is local-only. Device availability is measured at execution, and unsupported explicit accelerators fail rather than silently change device. These routes do not establish docking, folding or biological function.

## Optional remote execution

[Remote execution](references/remote-execution.md) separates host inspection, approved transfer, one submission attempt, status reconciliation, verified collection and controller-owned cancellation. It requires an explicitly selected existing SSH connection and compatible POSIX Python host. Local work needs none of these. Profile data is not authorization, and uncertain state never means that no job started.

## Installation checks

Run `python scripts/self_check.py` from this folder (or use its absolute path from any directory). Add `--molecular` in a compatible RDKit/OpenMM environment to require the CPU controls. See [testing guidance](references/testing.md); skipped checks are not validated capabilities.

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

## Optional Linux isolation and recovery

[Linux isolation](references/linux-isolation.md) adds an explicitly selected
existing Docker Linux/cgroup-v2 CPU route. It bounds memory, CPU rate, processes,
wall time and writable scratch, separates the unprivileged task from its
supervisor, and reconciles the original container after a lost client. Recovery
never resubmits work. Outputs live in temporary filesystems and must be collected
before the finite retention deadline. No engine, image, remote host or GPU is
installed or selected automatically. Legacy SSH recovery is read-only and retains
its cooperative trusted-task limits.

## Durable file and application checkpoints

[Durable checkpoints](references/durable-checkpoints.md) save approved files into
an explicitly selected, bounded SQLite store outside containers and this skill.
Local research artifacts need no Docker. An optional schema-2 Linux job can
publish cooperative checkpoint generations for read-only capture. Verified backup
and restore keep committed files usable after the original container/client state
is removed. Restore never executes a saved command; a continuation needs a new
explicit job and compatible application. Process-crash recovery is tested separately
from filesystem/device power-loss assumptions. Use `self_check.py --checkpoints`
to require actual local SQLite installation controls.

## Verified SSH backups

[Optional SSH backups](references/off-device-backups.md) add bounded transfer, immutable publication, readback and a restore drill for a consistent whole-store backup. Select a trusted existing destination and explicit limits; credentials stay in the existing SSH configuration. No source deletion, automatic replication or job execution occurs. Loopback acceptance does not establish recovery on a second physical device.

## Streaming and connection migration

[Streaming backups](references/streaming-backups.md) use bounded binary transfer buffers with an explicit whole-store cap up to 512 MiB. Temporary disk still scales with the backup. An explicit migration verifies the same immutable backup through new client settings and creates new read-only recovery state; the old state and destination identity remain intact.
