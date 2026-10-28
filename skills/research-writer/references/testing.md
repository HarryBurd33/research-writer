# Check this installation

Use the device's actual selected Python 3.10+ interpreter to run the installed
`scripts/self_check.py`. The check creates and removes its own temporary files;
it makes no network requests, model downloads, remote connections or GPU probes.

```sh
python PATH_TO_SKILL/scripts/self_check.py
```

It checks required resources and internal links, runs the packaged bibliography,
project, device-inventory, FASTA and evidence commands, preserves edits/outputs,
accepts a valid zero and rejects the same number with a wrong unit. It also loads
the literature tool without network access and checks a fictional source-support
record, rejecting an invented passage while preserving the semantic-review limit. Its JSON
report distinguishes passed checks from the optional molecular checks skipped
by default. This verifies installation and controls, not writing quality or truth.

To require RDKit and OpenMM controls in an already compatible environment:

```sh
python PATH_TO_SKILL/scripts/self_check.py --molecular
```

This executes ethanol descriptors, a seeded converged 3D conformer and an
analytic OpenMM Reference energy, checking chemistry and artifact hashes. Missing
dependencies or failed controls produce a nonzero exit and `passed: false`;
requesting molecular checks never silently skips them. There is no requirement
for identical conformer bytes across platforms/builds. GPU/backend performance,
heavy engines, remote execution and biological predictions need separate tests.

Run this check after installing/updating, changing Python/dependencies or moving
devices. Read the actual error before continuing. Never treat dependency presence,
a successful smoke or an unexecuted CI matrix as scientific validation.

## Require selected engines

Supply `--obabel PATH` to require independently checked chiral/E/Z conversion.
The current interpreter needs RDKit; Open Babel can live in a separate runtime.
For protein representations, supply both `--protein-python PATH` and
`--protein-model-dir PATH` to require local CPU inference in that separate
interpreter. No model preparation happens in this self-check. Missing runtime or
assets fails rather than silently skipping. Default runs mark these optional
checks skipped. Successful installation controls are not scientific benchmarks.

The default installed check also loads the remote client without connecting or
transferring anything. Remote host/job acceptance is separate and requires an
explicitly selected profile and bounded test; local package success is not proof
that a remote host or GPU is configured.

## Evaluate research and writing separately

The repository's [workflow evaluation](https://github.com/HarryBurd33/research-writer/tree/main/evals/workflow)
provides supplied-source cases for intake, study-family decisions, quantitative
synthesis or refusal, source conflict, theory, tutorials, close reading, proposals
and contribution duplication. A bounded primary-paper case uses original
paraphrased notes; receiving those notes is not personal full-text access.

For a new improvement, freeze fresh cases and review criteria before changing
instructions. Run the prior and candidate copies in separate contexts with
comparable tools and settings; retain actual outputs, calculations and saved-file
readbacks. Have a reviewer separate from construction inspect both usefulness
and claim support, and disclose agent-based or nonblind review. Fabrication,
violated source restrictions and incorrect destinations cannot be averaged away.
Public cases become known regressions after release; a future held-out test needs
new material. Deterministic fixture arithmetic and package checks do not execute
a writing agent, establish semantic truth or replace domain review.
