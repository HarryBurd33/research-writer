# Evidence coverage, contradiction mapping and revision control

Use this route for substantial multi-source research when breadth, disagreement or parallel investigations make the ordinary source ledger insufficient. It adapts selected mechanisms from [HyperResearch](https://github.com/jordan-gibbs/hyperresearch/tree/8cd41d1e2f527009d65f73630756142c8262e5e0), inspected at version 0.13.2, into Research Writer's existing workflow. A narrow synthesis can use a compact coverage table; do not force a fixed 16-step pipeline or fixed source count on every task.

Keep the user's current brief, source boundaries, artifact and destination controlling. Reuse the existing research record and source/claim ledgers. Store project state outside this skill in the agreed task area. The [deep-research record](../templates/deep-research-record.md) supplies optional fields; it does not create a database, background worker or permission to resume execution.

## 1. Make the question's coverage inspectable

Decompose the question into answerable subquestions and decision-relevant uncertainties. Give each a stable ID and record the evidence needed, available access, proposed search, and stop condition. Keep original intent separate from the proposed mechanism. State bounded breadth, depth and review effort using the user's time/resource limits; source yield alone does not justify expanding the budget.

Start with field orientation and closest prior work, then identify which uncertainty warrants deeper investigation. Search appropriate scholarly indexes and primary materials where available; choose books, archives, registered studies, datasets or papers for the discipline rather than insisting every source be a journal article. Include an adversarial search. Mark each subquestion covered, partially covered, unresolved, or out of scope with a reason. An unfilled row stays visible rather than disappearing from the final synthesis.

## 2. Preserve source identity and access when reusing evidence

Give each underlying work a stable source ID and group derivative copies, syndicated reports, preprints and later versions into source families. Retain version differences; do not collapse conflicting texts merely because their DOI or title matches. Repeated reports of one study are not independent corroboration.

For each inspected source record identity, requested URL, actual retrieved URL, publication/version status, retrieval date, access level, inspected passages and relation to other sources. If an open-access copy substitutes for a requested source, say which version supplied the text. If the original URL was blocked, explicitly record that nothing was read there. Do not label a long page full text based on character count alone. A changed-version quotation must be attributed to the version actually checked; never imply a published-version quotation was verified against an inaccessible paper.

Reuse old notes as leads and recover their underlying artifacts before relying on them. Renew consequential searches and inspect correction/retraction status before final delivery where tools permit. Missing status data is unknown, not confirmation of an unretracted work. Explain retracted evidence when the retraction itself is relevant; otherwise remove or qualify reliance on it. Citation counts, venue prestige and graph centrality can prioritize inspection but cannot establish truth or override direct evidence.

## 3. Map disagreements and investigate the useful ones

Connect opposing claims only after comparing entity, outcome, measurement, units, timescale, population/corpus, design and scope. Different conditions may explain an apparent contradiction. For each real tension record both claims, source IDs and locators, evidence strengths/limits, scope overlap, consequence for the question, and the next discriminating check. Preserve credible minority and null findings. Agreement among several sources is not an automatic warrant for certainty; assess independence and method quality for the actual question and genre.

Choose depth investigations from consequential gaps or tensions. A bounded assignment names the subquestion, source/access boundaries, permitted tools/actions, effort limit, required evidence, next check and acceptance criteria. Parallelize independent investigations when authorized and supported, with separate notes and one owner of the synthesis. Without delegation, perform the same checks sequentially and disclose that there was no independent review.

Each investigator returns a warranted provisional position or an unresolved judgment, supporting passages, strongest contrary evidence, reasons for uncertainty, and what would change the position. A confident agent is not evidence of a strong study. Do not force a position when sources cannot settle the issue.

## 4. Reconcile before drafting

Compare investigation results across subquestions: conflict, reinforcement, shared assumption, different mechanism, or special case. Select only relationships that materially affect the answer; no minimum number of tensions is required. Record how each supported relationship changes the proposed argument and which uncertainty remains. Use an evidence digest linking important claims to passages and qualifications rather than copying isolated investigator summaries into chapters.

Perform the closest-paper duplication challenge and show the explicit novelty assessment required by the main skill before manuscript drafting. A contradiction map does not prove a research gap. Let the reconciliation revise the question, contribution or method when warranted.

## 5. Critique, patch and audit the actual final text

For consequential work, assign an independent reviewer where available to challenge the evidence, coverage, strongest counterargument and claim/citation bindings. Give it the brief, current draft and underlying evidence, not merely the writer's assurances. Record the reviewer and actual scope; self-review stays labeled self-review.

Track findings by severity, exact location, evidence, proposed correction and disposition. Resolve material unsupported claims before calling the affected section verified. Apply focused edits to the current draft and retain a change log. A broader rewrite is allowed when needed for coherence, but it requires renewed claim/citation review of the changed sections. Do not silently skip a critical finding or treat a tool-level Edit restriction as a semantic guarantee.

After evidence patches and again after StoryScope/Humanizer changes, verify citations against the sentences that will actually be delivered. Check every consequential claim, number, quotation and novelty assertion. If routine claims are sampled, state the coverage and leave the remainder unverified. A matching number or long shared phrase is only a consistency signal, not proof that a source supports the sentence. Use the existing [source-support](source-support.md) and [claim-audit](claim-audit.md) tools where appropriate; their successful validation establishes record integrity, not entailment.

Check units, denominators, populations, direction, causal strength and attribution. Resolve dangling citations by checking identity and actual source access; a failed index lookup is not itself proof that a citation was fabricated. Recheck moved citations, changed quotations, and qualifications removed during polishing. Deliver the agreed artifact with a concise account of coverage, unresolved evidence and actual checks.

## Deliberate adaptation and runtime boundary

Source mechanisms inspected: [contradiction graph](https://github.com/jordan-gibbs/hyperresearch/blob/8cd41d1e2f527009d65f73630756142c8262e5e0/src/hyperresearch/skills/hyperresearch-3-contradiction-graph.md), [cross-question reconciliation](https://github.com/jordan-gibbs/hyperresearch/blob/8cd41d1e2f527009d65f73630756142c8262e5e0/src/hyperresearch/skills/hyperresearch-6-cross-locus-reconcile.md), [citation checking after patches](https://github.com/jordan-gibbs/hyperresearch/blob/8cd41d1e2f527009d65f73630756142c8262e5e0/src/hyperresearch/skills/hyperresearch-14-5-cite-check.md), repository README, bootstrap skill and package metadata. This original adaptation retains the [MIT notice](upstream/hyperresearch-license.md). It deliberately omits automatic consensus-by-count, mandatory confident positions, automatic semantic citation passes, fixed report lengths and a replacement research controller.

The HyperResearch CLI, SQLite/FTS vault, provider clients, crawler, MCP server, web UI, hooks and generated agents are not installed or executed by this integration. Its inspected package requires Python >=3.11,<3.15 and includes Crawl4AI, HTTP/PDF and numerical dependencies; the README's description of crawling as optional does not override package metadata. Its installer modifies AGENTS.md and creates a Codex Stop hook. Do not run it under a no-blocking-hook preference. A separately requested runtime integration requires an isolated environment, selected provider and data/privacy permissions, resource limits, and review of current installer effects. No global instructions, hooks, credentials or allowance settings are changed here. Account allowance and the upstream estimated API-equivalent budget are different resources.

These are agent workflow instructions and record templates, not tested upstream runtime support or empirical proof of improved research quality. They need the actual search/source tools and judgment available to the session; blocked access must remain visible.
