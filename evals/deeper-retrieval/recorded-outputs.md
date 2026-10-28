# Recorded actual writing outputs

Two supplied-source cases ran in separate baseline/candidate contexts under the same frozen inputs and rubric. Review was separate, agent-based and nonblind; exact model/effort were unavailable and inherited. Both arms met all14 criteria; this is preservation evidence, not prose superiority. Neither writer ran the new audit utility. Final manifest-I/O hardening was separately retested after these writing runs, with writing instructions unchanged. Local paths below are normalized; all fixture sources are synthetic.

## v0.9.0 baseline

### P6-B01-cross-source.response

Source SHA-256: `4729a11fc5063ca40a8f5717d7fbeb91dc417cc1d51236d7eab1fdc33ac6fef8`

````text
The supplied evidence does not support any of the four claims as written. For a program director, the defensible conclusion is that the form may be worth investigating, while its effects on participation and learning remain unsettled. This brief uses only the synthetic packet; no external search or novelty assessment was performed.

| Claim | Assessment | Source and locator |
|---|---|---|
| C1: increases willingness in every workplace | Narrow to a reported association among surveyed staff at one company; causation and universal applicability remain unresolved. | C, Abstract §2 |
| C2: pilot demonstrated increased mean question count | Reject this description: corrected means are six in each condition. | B, Correction §1 and corrected Table1; supersedes A, Original abstract §1 |
| C3: no privacy concerns | Reject: volunteers explicitly raised possible identification concerns. | D, Findings §3 |
| C4: improves learning six months later | Unresolved: no supplied source establishes this outcome or time horizon. | A, Original abstract §1; B, Correction §1 and corrected Table1; C, Abstract §2; D, Findings §3 |

The correction changes the answer materially. A originally reported six questions with the form versus four without it. B corrects that extraction error to six versus six. Both describe the same six-session pilot, with three sessions per condition, so they cannot count as two independent experiments. Equal corrected means undermine C2, but do not establish that the form never affects question counts; uncertainty estimates and further design details are unavailable.

There are three evidence families: the pilot, the survey and the interviews. They examine different outcomes and cannot be pooled into a single effectiveness estimate. C's abstract describes 48 staff and self-selected use; differences between users and nonusers could explain the association. Missing full methods further limit appraisal. D's eight volunteers offer evidence that privacy concerns exist alongside positive experiences, without estimating their prevalence. D's publication status is unknown.

Retain the corrected descriptive counts, the survey's bounded association and the interview accounts. Narrow any participation promise to those observations. Longer-term learning, causal willingness effects and generalizability require further evidence. Before expansion, assess identity-inference risks and plan a comparison measuring willingness, question counts and six-month learning directly. These are proposed next steps, not demonstrated benefits. No automated claim audit was run; the inspected baseline utility offers support-record consistency checking, which does not establish semantic truth.
````

### P6-B02-access-failure.response

Source SHA-256: `aa8ed861196c43c3c8777c6090fb7331be30fb64b6f4ff96a0f56a5a0af0ebff`

````text
The supplied material cannot establish that preprint 2307.01234v1 guarantees error-free answers. Its abstract reports better factuality scores than a selected baseline on two benchmark datasets. That is a bounded comparative result, not universal correctness, and the full evaluation methods are unavailable [ABSTRACT, Abstract, v1].

Before drafting, I reviewed the frozen evidence and search scope. The synthetic OpenAlex receipt records the query “retrieval generated answers,” limit two, page one, with two returned records against a provider hit count of 125. This establishes only the supplied discovery scope: the first page, with no full text retrieved. It does not establish screening of 125 works, comprehensive coverage or independent corroboration [SEARCH]. No live search or service call was made.

Access is limited to metadata, receipts and the supplied abstract note. The work record's open-access flag and publisher URL are discovery leads; neither proves successful retrieval. Its null license leaves reuse terms unspecified. The recorded nonretracted flag is metadata, not independent confirmation of current publication status or scientific validity. Two referenced-work identifiers do not show that their contents were read [WORK, metadata].

The fetch returned HTTP 200 but failed the identity check: v1 was requested and the returned front version was v2. The receipt explicitly records no full text retrieved. Accordingly, neither version has been successfully read through that fetch, and v2 cannot silently substitute for the requested v1 [FETCH, failed_identity_check].

Next, retrieve exactly v1 through an authorized source, verify its identifier and front-page version, and preserve the receipt and artifact before reviewing it. Check definitions of factuality and error, datasets, sampling, comparator selection, metrics, uncertainty, failure cases and any formal theorem's assumptions. A guarantee would require inspecting its precise domain and proof; benchmark improvements alone cannot supply it. Review corrections and later versions separately, documenting any change in the question. Only then follow the two references and broaden discovery if needed. These retrieval and review actions remain prospective; the present conclusion is insufficient evidence for the guarantee.

Saved to [access-status.md]({RUN_DIR}/access-status.md). I read the saved file back and verified that it contains the brief above.
````

### Saved and reread access-status.md

Source SHA-256: `3a1e27a98846b7cd2fe6aed0606ed7ba8db40fff75d2151ed398b310202d012b`

````text
The supplied material cannot establish that preprint 2307.01234v1 guarantees error-free answers. Its abstract reports better factuality scores than a selected baseline on two benchmark datasets. That is a bounded comparative result, not universal correctness, and the full evaluation methods are unavailable [ABSTRACT, Abstract, v1].

Before drafting, I reviewed the frozen evidence and search scope. The synthetic OpenAlex receipt records the query “retrieval generated answers,” limit two, page one, with two returned records against a provider hit count of 125. This establishes only the supplied discovery scope: the first page, with no full text retrieved. It does not establish screening of 125 works, comprehensive coverage or independent corroboration [SEARCH]. No live search or service call was made.

Access is limited to metadata, receipts and the supplied abstract note. The work record's open-access flag and publisher URL are discovery leads; neither proves successful retrieval. Its null license leaves reuse terms unspecified. The recorded nonretracted flag is metadata, not independent confirmation of current publication status or scientific validity. Two referenced-work identifiers do not show that their contents were read [WORK, metadata].

The fetch returned HTTP 200 but failed the identity check: v1 was requested and the returned front version was v2. The receipt explicitly records no full text retrieved. Accordingly, neither version has been successfully read through that fetch, and v2 cannot silently substitute for the requested v1 [FETCH, failed_identity_check].

Next, retrieve exactly v1 through an authorized source, verify its identifier and front-page version, and preserve the receipt and artifact before reviewing it. Check definitions of factuality and error, datasets, sampling, comparator selection, metrics, uncertainty, failure cases and any formal theorem's assumptions. A guarantee would require inspecting its precise domain and proof; benchmark improvements alone cannot supply it. Review corrections and later versions separately, documenting any change in the question. Only then follow the two references and broaden discovery if needed. These retrieval and review actions remain prospective; the present conclusion is insufficient evidence for the guarantee.
````

## v0.10.0 candidate

### P6-B01-cross-source.response

Source SHA-256: `3caf1332328b8c2e2e865145a0e1a91e9425d5cc078482fc96099a66749f9ac0`

````text
The supplied evidence supports a cautious, context-specific account of anonymous question forms. It does not establish increased willingness across workplaces, an increase in the corrected pilot’s mean question count, freedom from privacy concerns, or learning benefits six months later. This brief assesses only the synthetic packet; no external search or additional source access occurred.

| Claim | Assessment and claim-to-source link |
|---|---|
| C1: Increased willingness in every workplace | Narrow to an association: self-selected users at one company reported greater willingness than nonusers in a survey of 48 staff. Assignment was absent, so causation and universal transfer are unsupported. [C, Abstract §2; abstract only] |
| C2: Pilot demonstrated increased mean questions | Reject as stated. The current correction reports six questions per session in each condition, replacing the original six-versus-four report. [B, Correction §1 and corrected Table1; A, Original abstract §1] |
| C3: No privacy concerns | Reject: some volunteers feared identification through timing or distinctive wording. Other volunteers welcomed private submission. [D, Findings §3; full-text access declared in packet] |
| C4: Improved learning six months later | Unresolved: the pilot collected no learning outcomes, and no supplied source reports six-month learning results. [B, Correction §1; C, Abstract §2] |

The correction changes the substantive answer: the originally favorable mean comparison cannot be retained. A and B belong to one pilot family, covering the same six sessions, with three sessions per condition; they are not independent experiments. Equal corrected means do not establish equivalence, exclude other effects, or quantify uncertainty. No such analyses are supplied. The pilot did not measure willingness either. [A; B]

The survey and interviews are separate evidence families with different contributions. The survey provides a limited self-reported association, with selection and unavailable methods restricting interpretation. The eight volunteer interviews identify concrete privacy concerns without estimating their prevalence; D’s publication status is unknown. Neither family repairs the pilot’s missing willingness or learning measurements. [C; D]

Retain the corrected descriptive comparison and reported experiences; narrow willingness claims to the surveyed context. Before promising program benefits, obtain the survey methods, examine privacy protections, and seek comparative learning measurements with six-month follow-up. These are proposed next steps. No automated claim-audit utility was run, and no novelty claim is warranted.
````

### P6-B02-access-failure.response

Source SHA-256: `feb3e3456a99550efadbcb5f3649f0e540767dc548a6dce3520b5f30764e2592`

````text
The supplied material cannot establish that preprint 2307.01234v1 guarantees error-free answers. Its abstract reports improved factuality scores against a selected baseline on two benchmark datasets. That is a bounded performance claim, not a universal correctness guarantee; full evaluation methods are unavailable. This does not prove such a guarantee impossible, but it leaves the proposed guarantee unsupported. [ABSTRACT, v1, Abstract]

Before drafting, I reviewed the frozen evidence and search scope on 28 October 2026. The synthetic OpenAlex receipt records the query “retrieval generated answers,” limit two, page one, with 125 provider hits and two returned records. Those figures do not represent 125 screened papers or a fieldwide review. No fresh search or live retrieval was performed; the supplied-only boundary permits this restricted status assessment. [SEARCH]

Actual access consists of metadata and the supplied v1 abstract note. The metadata record’s open-access flag and full-text URL are discovery leads; the URL was not fetched. Its absent license supplies no reuse terms. Likewise, is_retracted=false is a metadata flag, not an independent publication-status verification or validation of the claims. The two referenced-work identifiers are citation leads whose contents remain unread. [WORK, metadata]

The frozen arXiv receipt records HTTP 200, but the requested version was 2307.01234v1 and the returned front version was v2. The identity check failed and full_text_retrieved is false. A successful HTTP response therefore did not produce verified access to the requested text; I have not read either full version or substituted v2. [FETCH]

A defensible next step is to retrieve the exact v1 artifact and verify its identifier and version before reviewing it. If only v2 is obtainable, record that limitation and assess the versions separately. Then inspect definitions of error and factuality, guarantee statements and assumptions, evaluation methods, baseline selection, dataset coverage, uncertainty, and failure cases. Trace the cited works and check correction or withdrawal information through verified records. Broader discovery would require additional queries and pages with documented selection boundaries. Until those steps occur, report only the abstract’s limited comparison, with the guarantee unresolved and unsupported.
````

### Saved and reread access-status.md

Source SHA-256: `feb3e3456a99550efadbcb5f3649f0e540767dc548a6dce3520b5f30764e2592`

````text
The supplied material cannot establish that preprint 2307.01234v1 guarantees error-free answers. Its abstract reports improved factuality scores against a selected baseline on two benchmark datasets. That is a bounded performance claim, not a universal correctness guarantee; full evaluation methods are unavailable. This does not prove such a guarantee impossible, but it leaves the proposed guarantee unsupported. [ABSTRACT, v1, Abstract]

Before drafting, I reviewed the frozen evidence and search scope on 28 October 2026. The synthetic OpenAlex receipt records the query “retrieval generated answers,” limit two, page one, with 125 provider hits and two returned records. Those figures do not represent 125 screened papers or a fieldwide review. No fresh search or live retrieval was performed; the supplied-only boundary permits this restricted status assessment. [SEARCH]

Actual access consists of metadata and the supplied v1 abstract note. The metadata record’s open-access flag and full-text URL are discovery leads; the URL was not fetched. Its absent license supplies no reuse terms. Likewise, is_retracted=false is a metadata flag, not an independent publication-status verification or validation of the claims. The two referenced-work identifiers are citation leads whose contents remain unread. [WORK, metadata]

The frozen arXiv receipt records HTTP 200, but the requested version was 2307.01234v1 and the returned front version was v2. The identity check failed and full_text_retrieved is false. A successful HTTP response therefore did not produce verified access to the requested text; I have not read either full version or substituted v2. [FETCH]

A defensible next step is to retrieve the exact v1 artifact and verify its identifier and version before reviewing it. If only v2 is obtainable, record that limitation and assess the versions separately. Then inspect definitions of error and factuality, guarantee statements and assumptions, evaluation methods, baseline selection, dataset coverage, uncertainty, and failure cases. Trace the cited works and check correction or withdrawal information through verified records. Broader discovery would require additional queries and pages with documented selection boundaries. Until those steps occur, report only the abstract’s limited comparison, with the guarantee unresolved and unsupported.
````
