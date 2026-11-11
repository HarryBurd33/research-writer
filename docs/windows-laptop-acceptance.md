# Windows laptop acceptance

The hosted native Windows worker passed 11 acceptance methods with zero skips. The 0.17 candidate also contains a Windows SSH client; use its separate exact-revision acceptance evidence before relying on transport. This guide checks your actual laptop using public code and synthetic fixtures. Signing into the same Codex account does not transfer the Mac's local research, runtimes, model weights, SSH keys or profiles. None of those private files is needed for the first stage.

## Start in Codex on the laptop

Open a new local folder for this acceptance. Paste this instruction into Codex:

> Continue the Research Writer Windows laptop acceptance. Read https://github.com/HarryBurd33/research-writer/pull/17 and clone the public repository into a new directory. Check out exact candidate source commit `1177a14b3dc95d2a67c6eeb7eb3fc3f0800445f6`; verify the full commit and inspect the worker and acceptance harness before running them. Read `docs/capability-validation.md`, `evals/PLATFORM-CI.md`, `skills/research-writer/references/windows-worker.md` and `skills/research-writer/references/windows-remote-execution.md`. Use an existing Python 3.10+ interpreter to run the native acceptance below. Keep logs and return code. Inventory GPU model, Python, Git and available SSH client/service without reading credential contents. Use only synthetic fixtures; do not resume held research experiments, install persistent services, change firewall/access settings or spend on APIs. Record failures and missing prerequisites explicitly. Stop after producing the acceptance report and the exact next action; do not infer external transport, CUDA or independent-backup acceptance from these CPU tests.

If Git or Python is absent, have Codex identify the missing prerequisite before choosing an installation method. Run in ordinary PowerShell; the worker tests do not require administrator privileges. Use a new destination name if the example already exists.

```powershell
git clone https://github.com/HarryBurd33/research-writer.git research-writer-acceptance
Set-Location research-writer-acceptance
git checkout --detach 1177a14b3dc95d2a67c6eeb7eb3fc3f0800445f6
if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed' }
$actualCommit = (git rev-parse HEAD).Trim()
if ($actualCommit -ne '1177a14b3dc95d2a67c6eeb7eb3fc3f0800445f6') { throw 'Source mismatch' }
python --version
python skills/research-writer/scripts/self_check.py --checkpoints
if ($LASTEXITCODE -ne 0) { throw 'Installation controls failed' }
python evals/windows_remote_checks.py
if ($LASTEXITCODE -ne 0) { throw 'Portable SSH contracts failed' }
python evals/run_platform_acceptance.py windows *> windows-acceptance.log
$acceptanceExitCode = $LASTEXITCODE
Get-Content windows-acceptance.log
if ($acceptanceExitCode -ne 0) { throw "Acceptance failed: $acceptanceExitCode" }
```

`python` must resolve to the compatible interpreter selected by Codex; substitute its full path if needed. Passing requires exit code 0 and a final `PLATFORM_ACCEPTANCE` record with `passed: true`, at least 11 methods, zero skipped methods, zero failures and zero errors. The preceding `PLATFORM_PROVENANCE` record captures OS, Python and source hashes. Preserve both records even on failure; an exit code alone is insufficient.

## Report back

Keep a local `WINDOWS-ACCEPTANCE.md` containing the exact commit, OS/Python, acceptance result, log path, GPU model and available backend, and whether an existing authenticated connection and independent backup destination are available. Record the local path to this checkout. No credentials or private key contents belong in the report.

If an NVIDIA GPU is available, the next bounded step is the explicit CUDA control in [accelerator acceptance](../skills/research-writer/references/accelerator-acceptance.md). It requires an isolated compatible runtime and six pinned public ESM-2 assets, approximately 31 MB, verified before and after execution. Select `cuda:0` explicitly, retain actual model/input/output device evidence and compare all raw values against the frozen CPU tolerance. A GPU inventory or successful CPU test is not CUDA acceptance. Codex should prepare the exact dependency/download plan before that step.

## Work that remains separate

The Windows native worker and its separate [SSH client](../skills/research-writer/references/windows-remote-execution.md) are implemented. Actual cross-device acceptance needs a selected authenticated endpoint, independently verified host key, existing native Python and a dedicated account-owned job directory. The generic POSIX CPU client is a different protocol. Do not enable an SSH service or alter firewall rules merely to run the native tests above. If no connection exists, report that prerequisite and propose the exact setup for user approval. The hosted `evals/setup_windows_ssh_ci.py` fixture is restricted to disposable GitHub runners and must not be run on the laptop.

External acceptance must exercise prepare, single submission, status, checksummed collection, cancellation, timeout, disconnect/restart and lost-acknowledgement recovery without duplicate dispatch. Verify host keys and actual host/user identity; never automatically accept a changed host key. Transfer only the reviewed adapters and synthetic fixtures over the selected authorized connection.

The POSIX accelerator SSH adapter does not target a native Windows endpoint. Local Windows CUDA acceptance is separate; external CUDA transport needs a selected POSIX CUDA host or a separately reviewed Windows accelerator transport extension. Do not treat the CPU Windows SSH client as GPU transport.

The existing backup adapter requires an authorized POSIX SSH destination; the native Windows CPU worker is not that backup protocol. A physical backup check requires an independent destination, full checksummed readback/restore and a fresh recovery directory without the original source/staging files. Preserve the original data. Do not induce power loss or destroy source files. Loopback tests cannot prove physical device independence or power-loss durability.

## Keep the acceptance report useful

Record each stage separately: copied installation, portable contracts, native CPU worker, selected cross-device SSH, local CUDA and independent backup. Use `passed`, `failed`, `not run` or `blocked` with the observed reason. Retain the full commit, exact Python executable, command, exit code, test count/skips and raw log path. For remote tests include host-key fingerprint and host/user identities, never key contents or tokens. Preserve uncertain jobs and their immutable IDs; do not resubmit to obtain a cleaner result.

Return the report and nonsecret receipt files to this chat using an explicit transfer. Same-account sign-in alone does not copy files. Keep original outputs and do not run held experiments.
