# Check this installation

Use the device's actual selected Python 3.10+ interpreter to run the installed
`scripts/self_check.py`. The check creates and removes its own temporary files;
it makes no network requests, model downloads, remote connections or GPU probes.

```sh
python PATH_TO_SKILL/scripts/self_check.py
```

It checks required resources and internal links, runs the packaged bibliography,
project, device-inventory, FASTA and evidence commands, preserves edits/outputs,
accepts a valid zero and rejects the same number with a wrong unit. Its JSON
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
