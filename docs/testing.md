# Tests and installation checks

Use Python 3.10+ for core tests. No third-party package or live service is needed:

```sh
python evals/toolkit_checks.py
python evals/toolkit_regressions.py
python evals/package_smoke.py
python scripts/build_portable.py --check
```

The first suite has eight methods; one molecular method is explicitly skipped
without its flag. The public regression suite has 19 methods; two molecular
methods are skipped without the flag. Subtests cover several invalid inputs per
method; method counts are not scientific-validation counts. Provider responses
are mocked so failures do not depend on network access. These promoted cases are
known regressions rather than unseen holdouts.

In an isolated environment with compatible RDKit and OpenMM packages, run:

```sh
python evals/toolkit_checks.py --molecular
python evals/toolkit_regressions.py --molecular
python evals/package_smoke.py --molecular
```

Requesting molecular tests requires the packages and real execution; failure to
import or compute fails the tests. Controls check ethanol chemistry, 3D geometry,
convergence, hashes, emitted CSV provenance and analytic OpenMM energy. A seeded
conformer need not have identical bytes across operating systems/builds. These
are CPU installation controls, not GPU, biological or model-accuracy benchmarks.

`evals/package_smoke.py` copies the skill to an isolated temporary installation,
runs its self-check from an unrelated directory, then removes a required catalog
and requires failure. Pass `--skill PATH` to test a different installed folder.
All work happens in temporary directories and is removed afterward.

An installed skill can check itself without the repository:

```sh
python PATH_TO_SKILL/scripts/self_check.py
python PATH_TO_SKILL/scripts/self_check.py --molecular
```

Read the JSON report and exit code. Core-only success explicitly leaves molecular
checks skipped. No network, model download, paid call, remote connection or GPU
probe occurs during this check. Use the selected runtime's Python executable;
recording another interpreter in a profile does not switch the running process.

## Continuous integration

The GitHub Actions workflow runs six core OS/Python combinations and three CPU
molecular combinations, with fail-fast disabled. It uses pinned checkout and
setup-python revisions, read-only contents permissions, no persisted checkout
credentials and bounded job timeouts. The aggregate **Research Writer checks**
passes only when both matrices succeed. The workflow never changes branch rules.

The molecular jobs use Python 3.12 and the selected versions in
`extras/cpu-tested-requirements.txt`; these are selected combinations, not a
universal lockfile. The pins were exercised locally on macOS; each hosted
combination requires its own observed CI result. Wheels must exist for the actual architecture. A missing wheel
fails the job rather than compiling source or hiding a required check behind a
skip. Runners print their observed runtime, and molecular jobs print versions.
`.gitattributes` enforces LF text checkouts because the portable builder hashes
source bytes. Check [validation](validation.md) and actual Actions logs for the
latest executed results; a matrix definition alone establishes no platform pass.

No current matrix covers GPU backends, remote execution, heavy research engines,
all Python versions or all CPU architectures. Source metadata, deterministic
integrity checks and even successful installation tests do not establish source
entailment, research completeness, novelty or scientific validity.
