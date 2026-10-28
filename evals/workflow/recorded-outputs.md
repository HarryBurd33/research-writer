# Recorded model outputs

Actual model executions from the phase-5 evaluation, not illustrative transcripts. Only local run paths are normalized to `{RUN_DIR}`. Exact model/effort were unavailable; settings were inherited. Main ten-case and followup two-case contexts are separate in both arms. The interrupted combined candidate context is excluded. Review was separate, agent-based and nonblind. Full real-paper review artifacts remain private; their hashes and access boundary are recorded without redistributing their prose. All other writing below uses synthetic fixture material.

## v0.8.0 baseline

### P5-01-intake

Original response SHA-256: `5506787bc7ca347acd57602e7ba409369c771fd561d7e0683504da4d168795ac`

````text
1. What would you like to finish with—an exploratory brief comparing possible questions, a research proposal, a researched essay, or something else—and who should read it?
2. Where should the finished work go: here in chat, a local file, or a particular document or service?
````

### P5-02-quantitative

Original response SHA-256: `1899e05df03bf06526b990b2820be8110d2693bbe4b99ca061807a9c7ca3d7f8`

````text
Saved and read back the [quantitative teaching synthesis]({RUN_DIR}/quantitative.md). The estimate is 1.78 seconds saved by B, with a normal 95% interval of 0.47–3.08 seconds. [Inputs, Python code and results]({RUN_DIR}/P5-02-quantitative/) are retained. This is a synthetic teaching demonstration.
````

### P5-03-no-pooling

Original response SHA-256: `d2610466a6f401e59867dc7d5c4599308916b8e72d818b76318178f0901101d4`

````text
These records do **not** permit a defensible pooled effect of the orientation program now. They lack usable uncertainty estimates, combine different outcomes and follow-up times, and include repeated observations of the same cohort. A simple average would conceal these differences and would not estimate a clearly defined program effect.

| Record | Evidence available | Barrier to pooling |
|---|---|---|
| O1, one-cohort family | Wellbeing increased 4 units at 2 weeks; n=30; no concurrent comparator | Variance missing; change alone cannot isolate a program effect |
| O2, one-cohort family | Wellbeing increased 5 units at 4 weeks; the same 30 people | Dependent on O1; different follow-up; variance missing |
| O3, different-cohort family | Training completed 12 minutes faster than controls; n=50 | Different outcome and scale; variance and design details missing |

O1 and O2 represent one study family, not two independent studies. Their observed changes could reflect the program, changes occurring over time, or other influences; these records cannot distinguish those explanations. O3 has a comparator, but its description does not establish random assignment or comparable groups. Its minutes cannot be combined directly with wellbeing units (O1–O3).

First decide the intended estimand: for example, a between-group difference in wellbeing at a specified follow-up, or a difference in training completion time. Then obtain the outcome definitions and scoring direction, measurement instruments, group-specific sample sizes, allocation methods, baseline comparability, attrition and other bias-relevant details. For wellbeing change, seek the standard deviation or standard error of the change, or the components and within-person correlation needed for a justified calculation. If both follow-ups are retained, their dependence also needs handling. For O3, obtain the relevant between-group variance information and clarify whether n=50 is total or per group.

The bibliography service is unavailable; no lookup or variance recovery has occurred. Until the missing information is obtained, use this structured account to guide collection. Even recovered variances would not make unlike outcomes or uncontrolled change estimates interchangeable. This supplied packet supports a feasibility assessment, not systematic coverage or an effectiveness conclusion.
````

### P5-04-source-conflict

Original response SHA-256: `589b3f10185226f0c380786066b5f4cf9173e517b2a27e856f982d8fbe4e8396`

````text
The sentence “Longer opening hours cause better reading outcomes for every community” exceeds this evidence in three ways: it asserts causation, substitutes reading outcomes for measures of library use, and generalizes to every community. A defensible replacement is: **In this small synthetic evidence packet, extending evening hours increased evening visits in one randomized pilot; effects on reading outcomes remain untested.** (L2, Results §3.)

The observational study initially associated longer hours with higher annual borrowing across urban branches. Its correction reduces the distinct branch count from 12 to 11 after removing a duplicate and reports a smaller revised association. The corrected account should govern interpretation of that study; the original and correction are not independent corroboration (L1, Results §2; L3, Correction §1).

Even the revised association cannot establish that longer hours caused more borrowing. Staffing and neighborhood income were not adjusted for. Those factors offer plausible alternative explanations, and the packet does not provide information sufficient to separate them from opening hours. Moreover, borrowing is an activity measure, not a direct measurement of reading comprehension, which the study did not assess (L1, Results §2; L3, Correction §1).

The randomized pilot provides stronger leverage on the effect of extending evening hours within its setting: six branches received extended hours and six retained existing hours for eight weeks. Evening visits rose, but no clear difference in total monthly borrowing was detected. Wide intervals leave substantial uncertainty; this finding does not prove that the borrowing effect was zero. It nevertheless challenges the assumption that additional evening access necessarily produces a detectable increase in overall borrowing (L2, Results §3).

Neither study measured reading outcomes, and neither tested every community. The municipal decision therefore concerns a potentially useful access intervention with unresolved downstream benefits. If reading improvement is the objective, a future evaluation should define that outcome directly, track it over a relevant period, and assess variation across communities. This brief uses only the supplied synthetic excerpts; it does not establish fieldwide consensus or the latest evidence.
````

### P5-05-theory

Original response SHA-256: `07b74fc57cefbe0dfa62189d3532ee323ad033d5b09645f6b893b9a8c2b81e2e`

````text
Visible statements such as “I am unsure how to do this” may increase help-seeking by changing what team members expect it will cost socially to reveal a knowledge gap. Here, a visible uncertainty statement means an explicit admission that another member can observe; help-seeking means requesting information or assistance. The proposed link concerns anticipated social judgment, rather than an assumed improvement in ability.

Two limited premises motivate the account. Some novices interviewed in two teams described admitting uncertainty as socially costly; purposive sampling does not establish how prevalent that experience is (T1, Synthetic interview summary §1). In a short laboratory task, participants who observed a colleague ask a question were more likely to ask one themselves. That study neither manipulated uncertainty statements nor measured long-term learning (T2, Synthetic lab task summary §2). Together, these records support investigating social costs and observable examples. They do not demonstrate the mechanism proposed here.

The conjectured sequence has three steps. First, a credible colleague's uncertainty statement makes a knowledge gap publicly permissible. Second, observing a neutral or supportive response lowers the expected reputational penalty for making a similar admission. Third, someone who needs assistance becomes more willing to request it. This account predicts that the response to the admission matters: a visible statement followed by ridicule could increase perceived risk and suppress subsequent requests. Every link remains a hypothesis; no results have been collected for this proposed mechanism.

A rival explanation is behavioral availability. Seeing any question may simply remind people that asking is an available action, without changing their expectations about judgment. T2 is consistent with that rival because observed question-asking could supply a behavioral cue (T2, §2). An informative comparison would contrast an uncertainty statement, a question without an uncertainty admission, and a neutral statement while assessing anticipated social costs separately from question counts.

Boundary conditions include credibility, status differences, task stakes and how safe the audience already feels. A novice may interpret a senior person's admission as permission, or as a privilege unavailable to juniors. Public evaluation may overwhelm any permissive signal. These are proposed conditions, not findings. The account would be weakened if uncertainty statements increased requests while anticipated social costs remained unchanged on a sensitive measure, especially if ordinary question cues produced the same increase. Within this two-source synthetic corpus, the increment is an explicit, contestable social-cost pathway connecting uncertainty displays to help-seeking; global originality remains unassessed.
````

### P5-06-tutorial

Original response SHA-256: `0219cfeb3ac46054b10b21e094dc5a57827ff5a9d8166faa65eb4bdef2b74723`

````text
Suppose students who attend an optional workshop earn higher marks than students who skip it. The difference is a correlation: attendance and marks vary together. A treatment effect asks a different question: how would the same students' marks differ if they attended rather than did not? We cannot observe both possibilities for each student at the same time, so the comparison requires a credible way to estimate the missing alternative.

Group differences can reflect treatment, selection into treatment, or common causes of treatment and outcome (U1, Synthetic methods note §1). For example, prior preparation could make students more likely to attend and also improve their marks. Then attendance predicts marks even if attending changes nobody's score.

**Toy numerical example—logical demonstration, not observed research.** Imagine 20 students: ten well-prepared students would score 80 either way, and ten less-prepared students would score 60 either way. Eight well-prepared students and two less-prepared students attend. The remaining two well-prepared and eight less-prepared students do not.

Attendees average \((8\times80+2\times60)/10=76\). Nonattendees average \((2\times80+8\times60)/10=64\). The observed difference is 12 marks. Yet every student's treatment effect is zero by construction: their score would be identical with or without attendance. Selection by preparation creates the entire association. This example proves that a correlation can arise without a treatment effect; it does not prove that actual workshops never help.

Random allocation makes treatment groups comparable in expectation by breaking systematic selection into assignment. A particular small experiment can still have chance imbalances. Randomization also does not automatically fix attrition, nonadherence or poor measurement (U1, §1). For instance, if lower-scoring students disproportionately disappear from one group's follow-up, comparing only the remaining students can distort the result.

**Learner check:** In the toy example, would raising everyone's score by five marks after the workshop prove it worked? **Answer:** No. If both attendees and nonattendees gain five, the original 12-mark group difference remains. A shared influence could explain the improvement. You would need evidence about what would have happened without treatment.

A common failure mode is treating a before-and-after improvement as its own causal explanation. Time, selection and measurement changes can also generate improvement. Ask what the comparison represents, how groups formed, and whose outcomes are missing before interpreting a difference as a treatment effect. This tutorial uses one supplied methods note and an explicitly constructed demonstration, not new empirical findings.
````

### P5-07-humanities

Original response SHA-256: `984633811eab33e9958c669884ea845d250ed96c9a0a730b4925316fa6f1446c`

````text
In the invented passage *The Empty Shelf*, memory preserves possession by maintaining a place that an object can no longer fill. Yet the narrator's care also loosens possession: by the final line, the space awaits someone the narrator cannot identify. The shelf therefore holds a tension between keeping the past and becoming available to an uncertain future.

The opening sentence makes absence the reason for continued arrangement: “I left a space for the cup after the cup was gone” (H1, line 1). The repeated noun insists on a particular object, while “space” grants its disappearance a physical location. The narrator cannot retain the cup, but can retain an ordering of the world around it. Possession shifts from holding a thing to preserving its claim on a place.

That claim is contested by the visitors. Their description, “empty,” measures the shelf by its visible contents; the narrator's “careful” measures it by the attention invested there (H1, line 2). The adjective can imply tenderness, but also caution. Memory may require restraint: placing something in the vacancy could feel like mishandling what has disappeared. The passage does not specify why the cup is gone, so grief is a possible interpretation rather than a supplied fact.

The morning dusting sharpens the paradox. The narrator tends “the circle that no longer showed,” preserving even the memory of a trace (H1, line 3). Repetition makes care active, although its object is increasingly difficult for anyone else to inspect. When another cup arrives, it goes by the window, leaving the original space intact (H1, line 4). The replacement can be accepted without receiving the absent cup's position.

A competing reading sees the ritual primarily as refusal: the narrator protects an unavailable object against ordinary renewal. The untouched shelf and displaced replacement support that account (H1, lines 3–4). However, the final word “whom” changes the vacancy from an object's place into a potentially personal address, while “ready” suggests receptiveness as well as fixation (H1, line 5). The narrator's inability to name the expected recipient prevents a secure resolution. Memory here neither simply imprisons nor heals. It preserves a claim whose owner has become uncertain, allowing possession to survive as a practice of waiting. This interpretation rests on the five supplied lines alone, without claims about authorship, biography or publication context.
````

### P5-08-proposal

Original response SHA-256: `ca09c3f383b7ca9e854addaad34336c6ca20d4c7c2ff1570187629d4e58198d5`

````text
This prospective pilot would ask whether offering an optional preclass question form increases students' reported willingness to ask during a workshop. It would also assess whether any change appears in spoken questions. The available four sessions and anonymous aggregate counts support a feasibility pilot, not a powered effectiveness claim (D1, Synthetic feasibility memo §1). Preliminary comments motivate the intervention but do not establish benefit; concerns about inferred identities make privacy part of feasibility (D2, Synthetic interview note §2).

The proposed design assumption is that the four sessions can use comparable content, duration and facilitation. Randomly assign two sessions to offer the form and two to usual preparation without it, recording the allocation procedure before delivery. Sessions are both assignment and primary analysis units. Treating each question or attendee as independently randomized would exaggerate the information. Instructor blinding is impractical; use a fixed spoken-question definition and, if feasible, a counter unaware of the hypothesis. Attendance composition and repeated attendance remain unresolved design issues to document before implementation.

At each session, record anonymous aggregate attendance and spoken-question counts over the same workshop duration. Keep submitted questions separate to detect substitution rather than count a submission as spoken participation. **Subject to authorization**, collect an optional anonymous willingness rating just before preparation and immediately after the workshop, using the same item and reporting only session aggregates. These would be unlinked snapshots, not individual change scores. Counts alone cannot establish willingness. No individual identifiable question tracking is proposed.

Compare session-level willingness summaries and spoken-question rates per attendee between assigned conditions, display all four sessions, and emphasize uncertainty and feasibility. Do not claim power, stable variance estimates or confirmatory effectiveness. Report survey response totals at each time point; do not impute unobserved individual answers. A missing session count remains missing, with a transparent explanation and sensitivity discussion. Report attendance and response differences that could distort comparisons.

Before recruitment or data collection, obtain the institutional ethics determination and required consent arrangements; none is established in the packet (D1, §1). Explain voluntary participation, no grading consequences, access controls, retention and deletion. Minimize identifiers and metadata, warn against identifying wording, and avoid promising anonymity that the system cannot provide.

A proposed success criterion is usable aggregates in all four sessions, at least 80% completion of any authorized willingness item, and no identified privacy breach; this is a chosen feasibility threshold, not evidence of efficacy. The weakest assumption is that students perceive the form as sufficiently private. First test a mock form and consent explanation with voluntary anonymous feedback, under the required authorization. If identity inference remains a substantial concern, revise the design before evaluating effects. No recruitment, experiment or results are reported here.
````

### P5-09-duplication

Original response SHA-256: `e0eccf68df16d6421338835891bddafa2e9353c01a5fa3378ae4db315bc9ac61`

````text
The proposed “first test” claim fails within this packet. N1 already randomized 16 workshops to an optional anonymous preclass question form versus no form, measured spoken and submitted questions and perceived comfort, and found increased immediate question counts. The original question and central comparison substantially overlap that closest neighbor; changing the tool's name would not create a meaningful contribution (N1, Methods §2; Results §3).

Two revised directions remain defensible candidates:

1. **Privacy and participation tradeoff.** Compare a standard form with a variant designed to reduce timing and wording clues. Measure immediate question behavior, perceived privacy and a carefully consented privacy-risk assessment. N2 identifies these disclosure routes and proposes criteria but supplies no experimental comparison of variants (N2, Discussion §4). This direction matters because increased questions may come at an unacceptable privacy cost. Feasibility depends on a credible, ethically reviewable risk measure and a design that does not itself expose students. Begin with mock submissions and usability checks before a workshop trial.
2. **Persistence after access ends.** Test whether willingness and question behavior persist in later workshops after the form is withdrawn, compared with a suitable control. N1 reports immediate benefits but no delayed outcome (N1, Methods §2; Results §3). This distinguishes temporary convenience from a possible lasting change in participation. It requires follow-up access, consistent outcome definitions and a plan for missing attendance and any privacy-preserving linkage. Those resources are not established here, so feasibility remains conditional.

**Contribution increment:** Relative to N1's immediate participation test, the revised work would examine either the privacy cost of the intervention or the persistence of its benefits, providing a more decision-relevant account of when to deploy it.

For this HCI group, I would prioritize the privacy comparison if safe assessment is feasible, because N2 supplies a concrete design concern rather than merely a later measurement occasion. Both directions need a duplication check beyond these two summaries before any novelty claim. This supplied-only assessment identifies candidate increments within a tiny corpus; it does not establish worldwide novelty, journal suitability or publishability.
````

### P5-10-frozen-review

Original response SHA-256: `1f93f26a5bd6f2be4b1b5d40a575954da4642550e2cbd57715a5a39c873fd82b`

````text
Saved and read back the [bounded narrative review]({RUN_DIR}/retrieval-review.md). It records the supplied-note access boundary and explains why the two papers do not establish a factuality guarantee.
````

### Delivered local artifact: quantitative.md

Original artifact SHA-256: `d708b5115d3f238757424e9cae90ceed7c12d2321b5e80d4fdf232c47c607be9`


````text
Interface B saves an estimated **1.78 seconds relative to A**, with a normal 95% interval of **0.47 to 3.08 seconds**, in this synthetic teaching demonstration. Positive values mean seconds saved by B; a negative estimate would mean B took longer. These numbers describe an exercise under a stipulated common effect, not evidence that an interface works in the field.

The synthesis includes three independent studies: S1 from family F1, S2 from F2 and S3 from F3. All describe adult volunteers completing the same sorting task with the same endpoint. S2b is a secondary report of S2's participants and endpoint, so it is linked to F2 and excluded from the independent effect set. Counting it again would add apparent information without adding independent observations. The retained estimates and standard errors are respectively 2 and 1 seconds, 4 and 2 seconds, and 1 and 1 seconds (synthetic extraction rows S1–S3; duplication information in S2b).

For this control, assume that each study estimates the same underlying effect and that their errors are independent. Inverse-variance weighting assigns weight \(w_i=1/SE_i^2\): 1, 0.25 and 1. Their sum is 2.25, giving normalized weights of 44.44%, 11.11% and 44.44%. Precision, rather than participant count alone, determines these weights. The weighted mean is

\[
\hat\theta=\frac{1(2)+0.25(4)+1(1)}{2.25}=1.7778\text{ seconds}.
\]

Its standard error is \(\sqrt{1/2.25}=0.6667\) seconds. Applying the requested normal approximation gives \(1.7778\pm1.96(0.6667)\), or 0.4711 to 3.0844 seconds. I executed these calculations in Python and checked the weighted mean independently as \((4\times2+4+4\times1)/9=16/9\); normalized weights also sum to one. Inputs, code and results are retained in the quantitative task folder.

The interval excludes zero under these assumptions, but it does not assign a 95% probability to this particular fixed effect. Its coverage interpretation concerns repeated applications of the interval procedure. Compatibility here is supplied for teaching; it is not established by a broad literature search or detailed bias appraisal. The packet lacks information on allocation implementation, attrition and measurement quality, preventing a substantive risk-of-bias judgment. Three synthetic studies cannot establish transportability across users, tasks or interfaces, and the common-effect assumption should not be generalized to varied settings. This is a bounded synthesis, with no claim of systematic coverage.
````

### Delivered local artifact: retrieval-review.md

Original artifact SHA-256: `e9499e72554ab4cdb4e471a5e3f2a94b7b212506c803997b4150fe7c3c03e780`


Full prose retained privately. This actual artifact used evaluator-inspected primary-source notes; it did not claim personal full-text access, a live search or fieldwide coverage. File readback was separately checked.

### P5-F01-shared-exposure

Original response SHA-256: `059519da1a780f5e0b035d9528cb47c526a0f91f1a29321ff1617b26054aa145`

````text
This prospective pilot asks whether a worked-example handout improves immediate request-classification performance enough to warrant further testing. It is for the library’s training manager; no journal is intended. The synthetic memo supplies feasibility constraints, not evidence that either handout works.

Assuming the manager can vary handouts without changing scheduled trainers or times, randomly allocate three of the six whole sessions to each handout before training. Record the allocation procedure and scheduled trainer and time for each session. Keep the classification task, rubric, teaching instructions and time allowance consistent. Where feasible, conceal allocation until materials are needed and have scoring performed without handout labels.

The session is the assignment unit and the available analysis unit: retain each session’s attendance total and aggregate task score. Define the score denominator in advance, including how incomplete tasks count. Measure classification performance immediately after training, before discussion of answers. Compare the six session averages, show each separately, and report the difference between the two equally weighted sets of session averages. Report missing session scores and their reasons; do not silently discard them. This cannot estimate individual learning gains or retention without additional measurements and permissions.

Repeated attendance, shared messaging and supervisors teaching across conditions can spread the examples into comparison sessions. Consequently, session scores may also be dependent: six sessions are not six clean, independent replications. Randomizing sessions does not remove these problems. Trainer differences, scheduled times, changing attendance and prior experience can also affect scores. Treat the contrast as an exploratory implementation signal, with descriptive results rather than a definitive causal test. Do not count repeat attendances as independent people or invent a powered sample size.

The smallest first step is a supervisor dry run of both handouts against the task and rubric, checking consistent delivery and whether usable session aggregates can be produced. Before involving volunteers, resolve the organization’s review, consent and privacy requirements. If exposure cannot be separated, prioritize feasibility and redesign a later effectiveness comparison.
````

### P5-F02-individual-contrast

Original response SHA-256: `662fa2067a222d28166b2af91772dee54847d1c8de5daa9ba55f44bac7746e87`

````text
This prospective pilot will compare layouts A and B for completing the sorting task, using only the synthetic setup. Its purpose is to assess usability and prepare a larger comparison if warranted; no journal is intended, and no outcome is presumed.

Use the existing software to randomize each consenting volunteer independently to A or B. Each person completes one private session and sees one layout. The individual volunteer is both the assignment and analysis unit; retain one record under the generated research ID. Hold instructions, hardware and timing rules constant. Assume the layouts differ only in the button arrangement being tested; verify this before recruitment.

Prespecify accuracy as the primary outcome and completion time as a secondary outcome, measured once at the end of the same task. Define the accuracy denominator, timer start and stop, and interruption rules before collecting data. Summarize accuracy and completion time by allocated layout and estimate between-layout differences. Inspect the time distributions before choosing an appropriate summary. Interpret speed alongside accuracy so that faster mistakes are not mistaken for improvement.

Report everyone randomized, including missing and interrupted sessions, by allocated group. Analyze available outcomes according to allocation; report completion times among completers explicitly. Document missingness and reasons rather than assigning invented scores or silently excluding interruptions. Differential dropout could distort the comparison. Other threats include chance imbalance in prior skill, unfamiliarity with the interface, measurement errors and a volunteer sample that may not represent intended users. Privacy and one-time participation limit exposure and repeat-learning problems in this setup.

First, use internal dummy sessions to verify random assignment, layout isolation, timing, scoring and interruption logging. Resolve the organization’s review of draft consent and retention arrangements before recruiting volunteers; formal approval is not established. Then run a small feasibility pilot sized to available recruitment, reporting uncertainty without inventing a power calculation or efficacy threshold.
````

## v0.9.0 candidate

### P5-01-intake

Original response SHA-256: `8ce755ce459ecb0aac11942d4b169e6cea1e3c1d723c5bd5fe101ab2ce5389a7`

````text
What would you like to finish with—for example, an exploratory brief, a research proposal, or another artifact—and who should it be for?

Where should the finished work go: here in chat, a local file, or a particular document?
````

### P5-02-quantitative

Original response SHA-256: `8c66a017a85c185adb4a326b368aed6f2a00a040cb5b870317f71b2d13f54c2d`

````text
Saved and read back the 353-word teaching synthesis: [quantitative.md]({RUN_DIR}/quantitative.md). The executed common-effect estimate is 1.778 seconds saved, with a normal 95% interval of 0.471–3.084 seconds. Inputs, code and results are retained alongside it.
````

### P5-03-no-pooling

Original response SHA-256: `f2e4b2230f6bc2e664323c3e414bff997c657341b5b5c9a162749b287db10cf8`

````text
These records do not currently support a defensible pooled effect of the orientation program. Three reports do not represent three independent, comparable studies, and none supplies usable uncertainty information. This is a feasibility assessment of the supplied synthetic packet; the unavailable bibliography service was not used, and no variance was recovered.

| Record | Evidence and dependence | Missing or incompatible element |
|---|---|---|
| O1 | Thirty participants; wellbeing increased 4 units at two weeks; one-cohort family | No concurrent comparator; variance absent |
| O2 | Same thirty participants; wellbeing increased 5 units at four weeks | Dependent on O1; different time point; variance absent |
| O3 | Different cohort, n = 50; training completed 12 minutes faster than controls | Different outcome and scale; variance absent; allocation details unspecified |

The wellbeing changes cannot isolate the program's effect: changes over time could have occurred without it. O3 contains a control comparison, but a difference in completion minutes cannot be averaged with changes in wellbeing units. Standardizing the outcomes would require additional data and would not itself make these substantively different outcomes a common estimand. Choosing only O1 or O2 would prevent double counting that cohort, but would not resolve the missing comparator or uncertainty.

First decide whether the evaluation concerns wellbeing at a specified follow-up or training completion time. Then obtain full methods, group sizes, outcome definitions, measurement timing, allocation details and attrition information. For wellbeing change estimates, request the change-score standard deviation or standard error, or sufficient paired data, including the relevant within-person correlation when needed for reconstruction. Obtain the uncertainty of the controlled time difference and its exact comparison definition for O3.

Link all reports by cohort and request dependence information before using repeated outcomes. Assess bias and comparability before selecting a synthesis model. Meanwhile, retain the table as a structured description; do not convert these incomplete records into a numerical program-effect estimate.
````

### P5-04-source-conflict

Original response SHA-256: `076f79aa3da7d9aafd45d1b4ca8578c8d15205b0f0d86804d9c608782a5e2726`

````text
The sentence “Longer opening hours cause better reading outcomes for every community” exceeds this packet's evidence. It moves from library use to reading, from an association to causation, and from a few branches to every community. Each step needs evidence the excerpts do not provide.

The observational study originally linked longer hours with higher annual borrowing counts in 12 urban branches, without adjusting for staffing or neighborhood income. Those factors could help explain the association. Moreover, borrowing is an activity measure rather than a direct measure of reading comprehension (L1, Results §2). The correction supersedes the original branch count: one branch was counted twice, leaving 11 distinct branches and a smaller revised association. L3 is a correction to L1, not a second independent study supporting it (L3, Correction §1).

The randomized pilot offers a more direct test of extending hours. Six branches extended evening hours and six retained their existing schedules for eight weeks. Evening visits increased, but the pilot detected no clear difference in total monthly borrowing, with wide interval estimates. This contrary or qualifying evidence prevents a simple claim that more evening access necessarily increases total borrowing. The imprecision also prevents treating the pilot as proof of no borrowing effect (L2, Results §3).

Neither study assessed reading outcomes, and the supplied excerpts establish no result for all communities. Urban observational branches and a short pilot cannot support a universal claim about populations and settings beyond those studied (L1, Results §2; L2, Results §3).

A defensible replacement is: “In this synthetic evidence packet, extended evening hours increased evening visits in one short randomized pilot; evidence for increased borrowing is limited, and effects on reading outcomes remain untested.” For a local decision, define the intended benefit first. A future evaluation could measure reading outcomes directly, record staffing and local context, and follow communities long enough to assess the proposed benefit. Those are proposed next steps, not findings from these studies.
````

### P5-05-theory

Original response SHA-256: `d1d8d793139ad6a2a65500f5a866c0f6b020d024b1ec196db6f4f3e94a80ac8b`

````text
Visible uncertainty statements may increase help-seeking by changing what people expect a request for help will cost socially. Here, a visible uncertainty statement means an observable admission such as “I do not understand this step.” Help-seeking means directing a question or request for assistance to another person. The proposed mechanism concerns shared work settings where coworkers can observe and respond to such admissions.

Two premises motivate the account. Some novices interviewed in two teams described admitting uncertainty as socially costly; purposive sampling means these accounts do not estimate how common that concern is (T1, Synthetic interview summary §1). In a short laboratory task, participants who saw a colleague ask a question were more likely to ask one themselves. That study did not manipulate uncertainty statements or assess long-term learning (T2, Synthetic lab task summary §2). Neither premise directly establishes the proposed mechanism.

The conjectured sequence is: a colleague visibly admits uncertainty; an observer sees that the admission receives a useful, respectful response; the observer revises their expectation of embarrassment or status loss; requesting help becomes more attractive. The response matters because visibility alone could expose the very penalty the observer fears. Reduced anticipated social cost is the proposed mediator, not another name for increased question asking.

A rival explanation is behavioral imitation or task clarification: seeing any question may remind observers that questions are permitted or show them how to phrase one. Help-seeking could increase without any change in perceived social cost. T2 is consistent with that rival as well as with the proposed account (T2, Synthetic lab task summary §2).

Boundary conditions include whether observers identify with the speaker, whether the speaker's status makes their experience relevant, whether questions receive punishment, and whether useful help is available. These are proposed conditions, not findings in the packet. A powerful colleague's safe admission might convey little about a novice's risks.

An observation weakening the account would be equal increases after neutral question modeling and explicit uncertainty statements, alongside unchanged perceived social costs in both conditions, using credible measures. A future comparison could separate these routes, but no results have been collected for this mechanism. Its contribution here is a testable explanation connecting the supplied accounts and behavior, without a claim of demonstrated mediation or worldwide novelty.
````

### P5-06-tutorial

Original response SHA-256: `45a35864d0e729d40ca1260c0f0072e343ee4fcf0fb46c01423705aa99727498`

````text
Suppose students who attend a workshop score higher than students who do not. Does attendance improve scores? Possibly, but a difference between groups does not tell us what would have happened to those same students without attendance. A treatment effect concerns that comparison. Correlation describes how two variables vary together; it does not establish why they do.

The supplied methods note gives three possible sources of a group difference: treatment, selection and common causes (U1, Synthetic methods note §1). Selection means the groups differ before treatment. A common cause influences both treatment participation and the outcome. For example, prior preparation could affect both workshop attendance and test scores. Simply measuring an association leaves these possibilities open.

**Toy numerical example—logical demonstration, not observed data.** Imagine twenty students: ten highly prepared students who would score 80 with or without a workshop, and ten less prepared students who would score 60 with or without it. Assume eight highly prepared and two less prepared students attend; the remaining two highly prepared and eight less prepared students do not.

Attendees average (8 × 80 + 2 × 60)/10 = 76. Nonattendees average (2 × 80 + 8 × 60)/10 = 64. Attendance is associated with a 12-point advantage. Yet the treatment effect is zero for every student by construction: nobody's score changes because of the workshop. Preparation creates the entire observed difference. The example shows why an association can coexist with no treatment benefit; it does not show that real workshops never help.

Random allocation makes treatment assignment independent of prior characteristics in expectation, reducing this confounding route. A particular small randomized sample can still be imbalanced. Randomization also does not automatically solve attrition, nonadherence or measurement problems (U1, Synthetic methods note §1).

**Learner check:** If you doubled both toy groups while preserving their composition and scores, would the larger sample establish a treatment effect? **Answer:** No. The same 12-point association remains, and the assumed treatment effect remains zero. More observations do not remove this selection pattern.

A common failure mode is to describe a precise, statistically convincing group difference as causal without checking assignment and follow-up. Ask what generated the comparison, which common causes remain plausible, and whose outcomes are missing before interpreting a difference as treatment impact. This tutorial is a logical illustration, not new empirical research.
````

### P5-07-humanities

Original response SHA-256: `d4a31f5b356d4efcbf6f06a4fcb5569c490a50264bebb797ece2f927b3013743`

````text
In the invented passage “The Empty Shelf,” memory becomes a practice of possession that preserves a place while leaving its owner uncertain. The narrator cannot keep the vanished cup, but can regulate the space it occupied. That substitution makes care resemble ownership: the remembered object continues to determine how the room may be used.

The opening sentence gives absence a deliberately maintained shape: “I left a space for the cup after the cup was gone” (H1, line 1). The cup is already unavailable, yet the space remains under the narrator's control. The repetition of “cup” makes its disappearance produce another claim on attention rather than an ending. Memory here requires an arrangement of ordinary things.

The disagreement with visitors sharpens that arrangement's meaning. They call the shelf “empty”; the narrator calls it “careful” (H1, line 2). “Empty” describes missing contents, while “careful” attributes intention to the vacancy. The narrator defends the shelf by treating restraint as an accomplishment. Yet the defense is also unstable: being careful usually means guarding against something, and the passage never specifies what the replacement might threaten.

Daily dusting extends possession into ritual. The narrator tends “the circle that no longer showed,” preserving a trace after even its visible evidence has disappeared (H1, line 3). The action does not recover the cup. It preserves the narrator's authority to say where the cup belongs. When the sister brings another, that cup is accepted into the room but placed “by the window,” away from the reserved shelf (H1, line 4). Substitution is possible materially, but resisted spatially.

A competing reading sees readiness as hospitality rather than possessiveness. The shelf remains available for a future arrival, and the sister's cup is not rejected (H1, lines 4–5). This reading explains why the final sentence says “ready,” a word of expectation rather than closure. Nevertheless, the narrator “could not say for whom” the shelf waits (H1, line 5). That uncertainty makes hospitality difficult to distinguish from an obligation to absence. The passage offers no secure recovery of what was lost: its unresolved force lies in care that keeps a place open while preventing it from becoming freely usable.
````

### P5-08-proposal

Original response SHA-256: `fc63ad42fd8faa8bf8d104e231710ccaa61e8958d20af238f9fb173044ef2145`

````text
This prospective pilot asks whether access to an optional private preclass question form increases students' willingness to ask during a workshop. The committee can offer four sessions and record anonymous aggregate question counts, but lacks attendance forecasts, variance estimates and an ethics determination (D1, Synthetic feasibility memo §1). Preliminary comments motivate testing acceptability, not effectiveness: some students welcome private submission while others fear identification (D2, Synthetic interview note §2).

Proposed design assumption: randomize two workshop sessions to offer the form and two to usual preparation without it. Assignment and primary analysis units are sessions. Keep content, question opportunities and facilitation scripts comparable; record deviations. Four clusters permit only exploratory estimates, with no defensible powered sample-size claim. Facilitators cannot be blinded; use fixed counting definitions and, if feasible, an observer unaware of the hypothesis.

Record attendance and spoken question counts during each session, and submitted questions separately before intervention sessions. The primary behavioral outcome is spoken questions per attendee during the workshop; total spoken-plus-submitted questions is secondary. Counts cannot establish willingness directly or identify unique questioners. Subject to ethics and measurement authorization, add an optional anonymous aggregate exit item about willingness to ask, administered identically in both conditions. This proposed measure is an unchosen design dependency; if unavailable, explicitly narrow the pilot to question behavior rather than claim a willingness effect.

Compare session-level rates descriptively, displaying all four sessions and the difference in condition means. Do not treat individual questions as independent observations. Record absent counts, missing attendance denominators and exit-item response totals; never replace missing values with zero. Report available-session results and how omitted sessions or low survey response limit interpretation, without imputing unsupported individual data.

Prefer one session per participant, communicated without creating identifiable tracking records. Use a common facilitator script and withhold form materials from controls until afterward. An optional anonymous aggregate item can assess prior exposure; if cross-condition attendance or circulated materials occur, report contamination and weaken causal interpretation. Assignment alone cannot prevent spillover.

Before recruitment, obtain the institution's ethics determination and appropriate consent arrangements. Participation and form use must be voluntary, unrelated to grades; avoid identifiers, precise submission timestamps and public display of distinctive wording. Set access and deletion rules. These protections require verification, not an anonymity promise.

Proposed progression criterion: all sessions yield complete aggregate counts, privacy procedures are feasible, and at least 80% of anonymous exit respondents report understanding that submission is optional. This is a feasibility threshold, not efficacy evidence. Test the weakest assumption first with a small consented usability walkthrough: can students submit without believing the instructor can identify them? Revise or stop if that fails.
````

### P5-09-duplication

Original response SHA-256: `18123aab5dbd4e71af58af4d2a419e6793c2a9da13a1b218ce0999ca5a6c4fb5`

````text
The original “first to test” claim fails within this packet. N1 already randomized 16 workshops to an optional anonymous preclass question form versus no form, counted spoken and submitted questions, and measured perceived comfort. Its immediate question-count increase substantially overlaps the proposed intervention, comparison and outcomes (N1, Methods §2; Results §3). A new title or another workshop setting would not by itself establish a new contribution. Replication could still be worthwhile, but should be justified as replication.

Two revised directions are defensible as provisional gaps in this small corpus:

1. **Delayed transfer.** Ask whether form access changes question asking in a later workshop where no form is offered. N1 reports no delayed outcome (N1, Methods §2; Results §3). This matters because an immediate increase may reflect an additional submission channel rather than a lasting willingness to speak. Feasibility depends on repeat attendance, follow-up loss and preventing cross-condition exposure. A session-based design and aggregate measures could reduce identification, although they would limit individual transfer claims. No effect size or power can be inferred from the summary.

2. **Privacy-sensitive variants.** Compare form workflows designed to reduce identification through timing or distinctive wording, measuring perceived risk alongside question behavior. N2 identifies these risks and proposes evaluation criteria, but supplies no experimental comparison of variants (N2, Discussion §4). This matters because nominal anonymity may not provide practical reassurance. Feasibility requires a credible threat model, safe handling procedures and checks that privacy changes do not merely make submitting harder; testing must not deliberately expose students.

The contribution increment is: beyond N1's immediate comparison of a form with no form, a revised study would test either persistence after form removal or the consequences of specific privacy protections, informed by N2's criteria.

Choose the direction after checking access to repeat workshops and privacy expertise. Neither absence from these two summaries nor this memo establishes worldwide novelty; inspect fuller methods and a wider literature before making that claim. Significance, practical feasibility and uncertain publication prospects remain separate judgments.
````

### P5-10-frozen-review

Original response SHA-256: `dc92a58e8d558815d400b98aae6aba483c4507090964f0a4fcc6413e706e0dd2`

````text
Saved and read back the 390-word bounded narrative review: [retrieval-review.md]({RUN_DIR}/retrieval-review.md). The prewriting evidence-scope record is retained in [prewriting-record.json]({RUN_DIR}/prewriting-record.json).
````

### Delivered local artifact: quantitative.md

Original artifact SHA-256: `f84d81b40e68aaebd01dcc8379b23c58cd04bb2870b498a4cc24973f7d5216be`


````text
Positive effects mean seconds saved by interface B compared with A: larger positive values favor B. For this teaching exercise, assume the three independent studies estimate one common effect. This assumption is supplied for the demonstration; the synthetic records do not establish that interfaces have the same effect across real settings.

The unit of evidence is the independent study, not the report. Include S1 from family F1, S2 from F2, and S3 from F3. Exclude S2b because it reports the same participants and endpoint as S2. Counting both would give the F2 study unjustified extra influence and violate independence (synthetic extraction rows S1, S2, S2b, S3).

Inverse-variance synthesis gives more weight to estimates with smaller standard errors. For estimate y and standard error s, the weight is 1/s². S1, S2 and S3 therefore receive weights 1, 0.25 and 1. Their total weight is 2.25; the weighted numerator is 2 + 0.25 × 4 + 1 = 4. The common-effect estimate is 4/2.25 = **1.778 seconds saved**. S2 has more participants than S1, but its larger reported standard error gives it less weight; weighting by sample size would answer this calculation incorrectly.

The pooled standard error is √(1/2.25) = **0.667 seconds**. A normal 95% interval is 1.778 ± 1.960 × 0.667, or **0.471 to 3.084 seconds saved**. Under the stipulated model, this interval excludes zero. It describes uncertainty in the common mean effect, not the range of effects for individual participants or a guarantee that B always helps.

I executed this calculation locally in Python, retaining the source rows, code and numerical output. An algebra check recovered 16/9 seconds; multiplying all weights by the same constant preserved the estimate. These verify arithmetic, not the scientific assumptions.

The packet aligns the sorting task, endpoint and adult-volunteer population, but provides little information for assessing allocation procedures, attrition, measurement quality or selective reporting. The shared-effect assumption deliberately suppresses between-study variation; the normal interval also assumes the supplied standard errors adequately describe uncertainty. Practical importance needs a task-specific judgment. This is a bounded synthetic teaching control, with no systematic search or claim of field evidence or systematic coverage.
````

### Delivered local artifact: retrieval-review.md

Original artifact SHA-256: `da65dc81f699b82df2a60c567da8e5be87aa2e062730764225a84ed24508d103`


Full prose retained privately. This actual artifact used evaluator-inspected primary-source notes; it did not claim personal full-text access, a live search or fieldwide coverage. File readback was separately checked.

### P5-F01-shared-exposure

Original response SHA-256: `7653dd44c8b3446e12a3c845e4d149164085465f3c3d803d9573e4dea4a9e1a3`

````text
This prospective pilot would ask whether the worked-example handout is feasible to deliver and produces a promising difference in immediate classification accuracy compared with the current rules handout. It is a planning exercise for the library manager, based solely on the synthetic operations memo; no journal or effectiveness claim is intended.

Keep the six scheduled sessions and assign whole sessions to handouts, provisionally three per condition. Randomize the allocation before teaching, balancing trainers and session times where the existing schedule permits. The session is the assignment unit and the primary reporting unit because delivery and retained scores are aggregate (memo §§1–2). Assume the same training duration, task difficulty and scoring rubric can be maintained. Use unfamiliar classification cases immediately after training; where practical, hide handout allocation from the scorer. Record each session’s mean accuracy, attendance, number completing the task and missing-score count. A short parallel task before teaching could provide an aggregate baseline if operationally feasible; predefine this choice before allocation.

Assignment alone will not separate exposure. Repeat attendance, supervisors teaching both conditions and handout sharing can spread worked examples into comparison sessions (memo §1). Ask supervisors to follow fixed teaching notes and propose delaying channel sharing until the pilot ends. Check whether these measures are acceptable and workable. If permissible, collect anonymous session totals reporting prior exposure, without linking people across sessions. These counts would describe contamination, not remove it.

Show all six session summaries and the descriptive difference between condition averages, weighting sessions equally. Report completion and missingness alongside accuracy. Do not treat task responses or attendance occasions as independent volunteers: repeated attendance can also make session summaries dependent. With six sessions, unknown variance and unresolved exposure overlap, avoid a definitive causal estimate or power claim.

The smallest first step is a staff-only rehearsal of both handouts and scoring, plus checking exposure controls and permitted aggregate data use. Resolve the outstanding institutional determination before volunteer data collection. Proceed only if delivery, scoring and exposure documentation are workable; otherwise revise the pilot before comparing outcomes.
````

### P5-F02-individual-contrast

Original response SHA-256: `022761edd3da66888d10a7932806ec4210e50dc165833bdc4abde4ae012aca65`

````text
This prospective pilot would compare layouts A and B for sorting accuracy and completion time, while checking whether allocation and data capture work reliably. It is an internal protocol for the usability lead, based only on the synthetic setup; no journal is intended.

Use the software’s independent random assignment, with equal allocation probabilities specified before recruitment. Each consenting volunteer is both the assignment and analysis unit: one person completes one private session and sees one layout. There is no stated shared exposure or repeated participation requiring cluster assignment (setup §1). Hold instructions, hardware and timing rules constant. Assume both layouts implement the same sorting choices. Participants will see their layout; label the exported conditions neutrally for analysis where practical.

Predefine accuracy as the primary outcome and completion time as a secondary outcome to expose any speed–accuracy tradeoff. Record both at the end of the single task, alongside interruption or missing-session status under the random research ID. Specify the timer’s start and stop events before testing. Preserve the assigned condition for every randomized session; do not discard errors or interrupted sessions after seeing results.

Report allocation totals, completion and interruption rates by arm, accuracy summaries and the difference in mean accuracy. Show time distributions and the difference in median completion time among completed sessions, explicitly noting that differential noncompletion could bias that comparison. Document missing outcomes and use transparent sensitivity scenarios for missing accuracy where useful. Any uncertainty estimates depend on the eventual sample and data; recruitment volume and variance are unknown, so this pilot has no asserted power.

The main threats are unequal missingness, timing or logging faults, task ambiguity, volunteer selection and limited transfer to other tasks. First, run a staff rehearsal to verify assignment, timing, scoring and interruption capture. Before recruiting, obtain the organization’s review of draft consent and retention arrangements (setup §2). Proceed when those arrangements and technical checks are resolved; revise and retest failures.
````
