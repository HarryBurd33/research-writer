# Optional scientific figures

Use when the user requests a figure or a concrete explanatory need warrants one. Keep the main writing task useful without figure tools. A diagram can explain a proposal; it cannot turn proposed work into observed evidence. Use [the figure specification](../templates/figure-specification.md) proportionately, outside the installed skill.

## 1. Specify facts before appearance

State the figure's purpose, intended claim, readers and manuscript location. Link the relevant inspected source passages, protocol version, claim/result IDs, data and analysis code. Specify the permitted entities, relationships, ordering and uncertainty; distinguish an illustrative analogy from a measured mechanism. Resolve consequential factual gaps before drawing. Do not treat an attractive reference image as factual evidence or permission to reuse it.

Choose **quantitative plot** or **conceptual illustration** explicitly; mixed panels must preserve that distinction. Record labels, units, scales, uncertainty definition, sample size/denominators, necessary legends, caption/alt text, intended display size and output format. Check current venue requirements when a venue is chosen. Preserve a useful legend; no blanket removal or NeurIPS style rule applies to every venue.

Proposed default: one candidate and at most two correction cycles. Set any tool/runtime/spending/upload limits before execution. Stop sooner when evidence is missing, a tool fails or acceptance is reached. An expanded budget needs current authority, not a saved suggestion.

## 2. Render through an appropriate route

**Quantitative:** use inspected data and rerunnable plotting code. Preserve originals, input hashes, exclusions/transformations, variable-to-axis mappings, analysis outputs and the uncertainty calculation. Independently reproduce consequential values or compare them with a trusted calculation before plotting. Preserve valid zero, negative values, missingness, units and nonmonotonic relationships. Do not silently replace missing values with zero, smooth away a null result, or interchange SD, SE and CI. Use honest scales and disclose exclusions or truncation.

Use available supported local plotting tools, such as an existing Matplotlib/R environment or a suitable original SVG script, after reviewing the code and its file/network effects. Record the command, runtime/dependencies and artifacts needed to rerun it. A generated numerical image is not a source of measurements; do not use image generation to invent or render evidentiary values. Missing real data permits a specification or conspicuously labeled synthetic demonstration, never a fabricated result presented as observation.

**Conceptual:** render a source-grounded structure with an appropriate available tool. Prefer editable SVG, diagram syntax or layout source when supported. Authorized image generation can help suitable conceptual imagery, but retain its specification/prompt and inspect every scientific relationship. Generated icons and textures do not establish mechanisms, anatomy or measurements. If only PNG/JPEG is available, state that it is raster artwork; a prompt is not an editable vector source, and wrapping it in SVG/PDF does not change that.

Do not auto-install PaperBanana or execute its generated code. Any direct provider/API execution requires an explicitly authorized provider and spending boundary. Any external transmission of manuscript, data, images or reference material requires appropriate authorization for those files and destination. An existing subscription, configured key, public repository or tool availability is not that authority. Use existing authorized tools within their scope; never read credentials to create a fallback.

## 3. Review the exported result, then revise

Keep three checks separate and record actual evidence:

1. **Numerical reproduction, when applicable:** verify plotted values and transformations against data/code, including uncertainty, denominators and row inclusion. A hash establishes byte identity, not correctness of the scientific interpretation.
2. **Factual fidelity:** compare the exported figure with the protocol/passages/results. Check entities, sequence, arrow direction, labels, equations, quantities, scales and implied causality. A plausible drawing can still reverse a critical step. Resolve a discrepancy from the authoritative material; never silently change data to match the picture.
3. **Visual inspection:** open the actual exported file, at its intended size where possible. Check text/legend readability, arrow endpoints, overlaps, clipping, contrast, distinguishability without color alone, and agreement with caption/alt text. A valid SVG, successful command or source-code inspection does not establish visual quality.

Use a separate reviewer when available and proportionate. Treat automated/model critique as advisory and record its limits. Missing images, unavailable review, malformed critique or a failed renderer mean **unverified/pending**, never "no changes needed" or passed. Keep any earlier verified artifact only if its source/specification still applies; distinguish it from an unverified replacement.

Revise only the identified faults within the bound, then recheck affected facts and visual output. Changing labels, data, layout or caption can invalidate an earlier pass. Keep versions and brief correction notes. Unresolved factual defects prevent calling a figure verified, however attractive it looks.

## 4. Deliver and fall back honestly

Deliver the figure, caption/alt text, editable source when supported (otherwise its exact format limit), data/protocol/source provenance and rerun command where applicable. State numerical, factual and visual status separately, including reviewer/tool limitations and remaining issues. Reconcile figure claims with abstract, text and tables using [publication preparation](publication-workflow.md).

If tools, provider authority or rendering are unavailable, finish the warranted writing and deliver a usable figure specification and saveable local source when practical. Mark rendering and visual checks pending. Do not claim that a code block rendered, let an optional figure block core writing, upload private material or silently spend money.

Workflow reference: [PaperBanana](https://github.com/dwzhu-pku/PaperBanana/tree/dafc2d41c10395c8bc37faad26836070fef0add8), inspected 2026-11-08, informs plan → render → critique. The inspected code requires provider configuration and substantial optional dependencies; its plot executor runs generated Python and is not a demonstrated security sandbox. Its malformed-critique default can prematurely accept an image. This original workflow does not reuse that executor, acceptance rule, prompts or implementation. Core source is Apache-2.0; its skill's MIT-0 metadata does not relicense the code. No upstream code, model or dataset is bundled; current provider capability and rights need verification before any optional integration.
