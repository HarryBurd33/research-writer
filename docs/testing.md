# Tests and installation checks

Use Python 3.10+ for core tests. No third-party package or live service is needed:

```sh
python evals/toolkit_checks.py
python evals/toolkit_regressions.py
python evals/literature_checks.py
python evals/support_checks.py
python evals/discovery_checks.py
python evals/claim_audit_checks.py
python evals/conversion_checks.py
python evals/protein_checks.py
python evals/remote_client_checks.py
python evals/remote_worker_checks.py
python evals/remote_loopback_checks.py
python evals/workflow_checks.py
python evals/workflow/reproduce_quantitative.py
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

The GitHub Actions workflow runs six core OS/Python combinations, three CPU
molecular combinations, three CPU protein combinations and two POSIX loopback
SSH combinations, with fail-fast disabled. It uses pinned checkout and
setup-python revisions, read-only contents permissions, no persisted checkout
credentials and bounded job timeouts. The aggregate **Research Writer checks**
passes only when all four matrices succeed. The workflow never changes branch rules.

The molecular jobs use Python 3.12 and the selected versions in
`extras/cpu-tested-requirements.txt`; these are selected combinations, not a
universal lockfile. The pins were exercised locally on macOS; each hosted
combination requires its own observed CI result. Wheels must exist for the actual architecture. A missing wheel
fails the job rather than compiling source or hiding a required check behind a
skip. Runners print their observed runtime, and molecular jobs print versions.
`.gitattributes` enforces LF text checkouts because the portable builder hashes
source bytes. Check [validation](validation.md) and actual Actions logs for the
latest executed results; a matrix definition alone establishes no platform pass.

The remote matrix covers disposable loopback SSH on Linux and macOS. It does
not establish external-host support. No current matrix covers GPU backends,
production remote hosts, heavy research engines, all Python versions or all CPU
architectures. Source metadata, deterministic
integrity checks and even successful installation tests do not establish source
entailment, research completeness, novelty or scientific validity.

## Literature and source-support checks

The added offline suites exercise bounded pagination, provider failures and
malformed responses, correction/identity/access distinctions, and exact source
hash/version/passage/reviewer records. Network responses are mocked in CI.
Local live public-source controls are separate evidence, not claims that every
provider result or all literature has been reviewed. Record integrity does not
validate the meaning of a source-support judgment. See the new tool guides and
[validation](validation.md) for executed counts and coverage.

## Optional executable engine controls

Core tests run the conversion and protein contract suites without installing
engines; optional actual-engine methods are explicitly skipped. To require actual
execution, run the conversion suite with the RDKit environment's Python and
`--molecular --executable PATH_TO_OBABEL`, and the protein suite with its separate
runtime's Python and `--protein --model-dir VERIFIED_MODEL_DIRECTORY`.

The copied-install smoke and installed `scripts/self_check.py` also accept
`--obabel PATH_TO_OBABEL` and the paired `--protein-python PATH_TO_PYTHON
--protein-model-dir VERIFIED_MODEL_DIRECTORY`. These require the selected engines;
missing packages/assets or failed controls produce nonzero results rather than
silently skipping. Standard checks still need no model/network access.

The extended workflow retains six core and three molecular combinations, adds
three CPU protein jobs and keeps the stable aggregate check. Molecular jobs use a
separate Open Babel environment; protein jobs use the official CPU PyTorch index,
an explicit small-model preparation command and actual local-only inference.
No GPU, remote service or arbitrary model is tested. See [engine setup](engine-setup.md),
actual CI logs and [validation](validation.md) for observed outcomes.

## Remote execution controls

Client contract tests use mocked SSH responses, including lost acknowledgments;
worker tests use disposable local POSIX controller jobs. The optional loopback
suite requires explicit `--run-ssh` and an available OpenSSH server/client/keygen.
It creates private temporary host/client keys, binds only 127.0.0.1 on an
unprivileged port, uses its own known-hosts file and SSH config, and removes the
owned daemon and files afterward. It does not change the user's SSH configuration
or install a permanent service. Default execution skips the real server fixture.

Run `python evals/remote_loopback_checks.py --run-ssh` only on a selected compatible
POSIX test host. Hosted Linux fixtures may need the standard ephemeral runner's
sshd privilege-separation directory. Windows clients receive contract tests;
Windows remote servers, GPU dispatch and schedulers need separate acceptance.
Resource limits are cooperative bounds for trusted jobs, not an OS security sandbox.
See [the remote guide](../skills/research-writer/references/remote-execution.md).

## End-to-end research/writing evaluation

The ten public [workflow cases](../evals/workflow/inputs.json) cover intake,
quantitative synthesis and refusal, conflicting/corrected evidence, theory,
tutorials, close reading, a prospective proposal, duplication and a bounded
primary-source review. See the [execution protocol](../evals/workflow/README.md).
The source notes in the review packet are evaluator-inspected paraphrases;
executors must not describe them as personal full-text access.

`python evals/workflow_checks.py` runs sixteen deterministic fixture/arithmetic
methods. They include an independently frozen numerical reference, report-order
invariance, effect shifts, uncertainty scaling, family-conflict refusal and
missing/invalid data. These CI checks never execute or grade a language model.
Behavioral results require saved actual model outputs and separate review under
a frozen rubric; live retrieval and destination integrations are separate gates.
Published cases are known regressions for future work, not permanently held-out
benchmarks or proof of scientific validity.


## Deeper retrieval and declared-claim inventory

The added discovery and audit suites run offline using synthetic provider/HTML
fixtures, temporary text artifacts and actual CLI invocations. They cover
provider errors and malformed counts, exact work/version identity, metadata-only
access, structural HTML identity traps, partial/conflicting reviews, required-pair
coverage, publication/family declarations, tampering and no-overwrite behavior.
POSIX named-pipe controls use bounded child processes and cleanup; those specific
controls explicitly skip where named pipes are unavailable. Other contracts run
across the core OS/Python matrix.

The installed self-check loads discovery without HTTP and executes a fictional
complete audit plus a missing-review refusal. Live anonymous OpenAlex and pinned
arXiv retrieval, source interpretation and writing behavior remain separate
acceptance records. See [the detailed validation](deeper-literature-validation.md).
No deterministic test semantically verifies a paper or authenticates a reviewer.


## v0.11 Linux isolation and recovery

Portable/offline contracts (no engine probe, no image download):

```sh
python evals/controller_recovery_checks.py
python evals/linux_checks.py
```

Actual integration requires an explicitly selected existing Docker Linux/cgroup-v2
engine and immutable compatible local image. It fails if the requested engine is
unavailable; there is no skip-as-success fallback:

```sh
python evals/linux_integration_checks.py --docker /usr/bin/docker --context default --image-id sha256:ACTUAL_64_HEX_IMAGE_ID
```

CI separately provisions an official Python image on a disposable Ubuntu runner,
records its resolved local ID/digest, and passes the immutable ID to this command.
The runtime tool itself never pulls. The stable required aggregate now depends
on this job as well as every earlier matrix. See [observed validation](linux-isolation-validation.md)
and the [runtime/threat model](../skills/research-writer/references/linux-isolation.md).


## v0.12 durable checkpoints

Portable tests run actual local SQLite transactions and subprocess failure controls:

```sh
python evals/checkpoint_checks.py
python evals/package_smoke.py --checkpoints
```

The core CI matrix requires these controls on Linux, Windows and macOS with the
selected Python versions. Existing optional-engine and source-support tests remain.
The required Linux job runs both the existing isolation suite and the separate
durable integration suite against an explicitly provisioned immutable image:

```sh
python evals/durable_integration_checks.py --docker /usr/bin/docker --context default --image-id sha256:ACTUAL_64_HEX_IMAGE_ID
```

This explicit suite must fail when its requested engine is unavailable. It tests
checkpoint data surviving removal of the original container and client state,
then an explicitly prepared new application job continuing from restored bytes.
No kernel-memory snapshot, production external host, GPU, physical power cycle or
network filesystem is inferred. See [observed validation](durable-checkpoint-validation.md).

## v0.13 verified SSH backups and storage failures

```bash
python evals/backup_checks.py
python evals/backup_loopback_checks.py --run-ssh
python evals/package_smoke.py --checkpoints
```

Core CI requires the backup contracts on all six OS/Python rows; POSIX loopback
jobs require actual transfer/recovery. Existing Linux resource and durable
checkpoint tests remain required. Storage fault injection is deterministic adapter
testing, separate from the existing actual SQLITE_FULL/hot-journal/process-kill
controls and from unexecuted physical power/device-loss validation. The installed
self-check remains offline. See [observed results](off-device-backup-validation.md).
