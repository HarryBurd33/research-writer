# Windows laptop acceptance

The hosted Windows acceptance passed 11 worker-suite methods (7 native, 4 portable) and 18 SSH-suite methods (9 native, 9 portable) with zero skips at the source revision pinned below. The [accepted hosted run](https://github.com/HarryBurd33/research-writer/actions/runs/42989786719) also verified metadata coordination across Windows sessions, uncertainty recovery and cleanup. This guide checks your actual laptop using public code and synthetic fixtures. Signing into the same Codex account does not transfer the Mac's local research, runtimes, model weights, SSH keys or profiles. None of those private files is needed for the first stage.

## Start in Codex on the laptop

Open a new local folder for this acceptance. Paste this instruction into Codex:

> Continue the Research Writer Windows laptop acceptance. Read https://github.com/HarryBurd33/research-writer/pull/17 and clone the public repository into a new directory. Check out exact accepted Windows source commit `f675c2937d3ab5e9533d676a2ba1c4747606a82e`; verify the full commit and inspect the worker and acceptance harness before running them. Use the accepted hosted run https://github.com/HarryBurd33/research-writer/actions/runs/42989786719 as the evidence for this pin; its recorded six source hashes match the pinned PR head, while its GitHub merge checkout is `a6d790c1e1c7a1f7b7df0d8dd9764c2180666f5f`. The historical validation document inside the pinned checkout predates that acceptance. Read `evals/PLATFORM-CI.md`, `skills/research-writer/references/windows-worker.md` and `skills/research-writer/references/windows-remote-execution.md`. Use an existing Python 3.10+ interpreter to run the native acceptance below. Keep logs and return code. Inventory GPU model, Python, Git and available SSH client/service without reading credential contents. Use only synthetic fixtures; do not resume held research experiments, install persistent services, change firewall/access settings or spend on APIs. Record failures and missing prerequisites explicitly. Stop after producing the acceptance report and the exact next action; do not infer external transport, CUDA or independent-backup acceptance from these CPU tests.

If Git or Python is absent, have Codex identify the missing prerequisite before choosing an installation method. Run in ordinary PowerShell; the worker tests do not require administrator privileges. Use a new destination name if the example already exists.

```powershell
$acceptanceRoot = Join-Path (Get-Location).Path 'research-writer-acceptance'
$acceptedCommit = 'f675c2937d3ab5e9533d676a2ba1c4747606a82e'
if (Test-Path -LiteralPath $acceptanceRoot) { throw 'Choose a new, absent checkout directory' }
Get-Command git -CommandType Application -ErrorAction Stop | Out-Null
git clone https://github.com/HarryBurd33/research-writer.git $acceptanceRoot
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; do not enter an existing checkout' }
Set-Location -LiteralPath $acceptanceRoot -ErrorAction Stop
git rev-parse --verify --quiet "$acceptedCommit^{commit}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    git fetch origin refs/pull/17/head:refs/remotes/origin/research-writer-acceptance-pr17
    if ($LASTEXITCODE -ne 0) { throw 'Fetching the explicit PR source failed' }
}
git checkout --detach $acceptedCommit
if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed; do not use a different revision' }
$actualCommit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $acceptedCommit) { throw 'Source mismatch' }
$python = (Get-Command python -CommandType Application -ErrorAction Stop).Source
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'; print(sys.executable)"
if ($LASTEXITCODE -ne 0) { throw 'Select an existing compatible Python interpreter' }
& $python evals/package_smoke.py --checkpoints
if ($LASTEXITCODE -ne 0) { throw 'Copied-package controls failed' }
& $python evals/windows_remote_checks.py
if ($LASTEXITCODE -ne 0) { throw 'Portable SSH contracts failed' }
$savedErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $python evals/run_platform_acceptance.py windows *> windows-acceptance.log
    $acceptanceExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedErrorPreference
}
Get-Content windows-acceptance.log -ErrorAction Stop
if ($acceptanceExitCode -ne 0) { throw "Acceptance failed: $acceptanceExitCode" }
```

`$python` must name the compatible interpreter selected by Codex; assign its full path if needed. The `& $python` form also handles paths containing spaces. The copied-package check creates a temporary independent copy and tests it from an unrelated directory; it does not install the skill globally. Passing requires exit code 0 and a final `PLATFORM_ACCEPTANCE` record with `passed: true`, at least 11 methods, zero skipped methods, zero failures and zero errors. The preceding `PLATFORM_PROVENANCE` record captures OS, Python and source hashes. Preserve both records even on failure; an exit code alone is insufficient.

## Report back

Keep a local `WINDOWS-ACCEPTANCE.md` containing the exact commit, OS/Python, acceptance result, log path, GPU model and available backend, and whether an existing authenticated connection and independent backup destination are available. Record the local path to this checkout. No credentials or private key contents belong in the report.

If an NVIDIA GPU is available, the next bounded step is the explicit CUDA control in [accelerator acceptance](../skills/research-writer/references/accelerator-acceptance.md). It requires an isolated compatible runtime and six pinned public ESM-2 assets, approximately 31 MB, verified before and after execution. Select `cuda:0` explicitly, retain actual model/input/output device evidence and compare all raw values against the frozen CPU tolerance. A GPU inventory or successful CPU test is not CUDA acceptance. Codex should prepare the exact dependency/download plan before that step.

## Work that remains separate

The Windows native worker and its separate [SSH client](../skills/research-writer/references/windows-remote-execution.md) are implemented. Actual cross-device acceptance needs a selected authenticated endpoint, independently verified host key, existing native Python and a dedicated account-owned job directory. The generic POSIX CPU client is a different protocol. Do not enable an SSH service or alter firewall rules merely to run the native tests above. If no connection exists, report that prerequisite and propose the exact setup for user approval. The hosted `evals/setup_windows_ssh_ci.py` fixture is restricted to disposable GitHub runners and must not be run on the laptop.

External acceptance must exercise prepare, single submission, status, checksummed collection, cancellation, timeout, disconnect/restart and lost-acknowledgement recovery without duplicate dispatch. Verify host keys and actual host/user identity; never automatically accept a changed host key. Transfer only the reviewed adapters and synthetic fixtures over the selected authorized connection.

The POSIX accelerator SSH adapter does not target a native Windows endpoint. Local Windows CUDA acceptance is separate; external CUDA transport needs a selected POSIX CUDA host or a separately reviewed Windows accelerator transport extension. Do not treat the CPU Windows SSH client as GPU transport.

The existing backup adapter requires an authorized POSIX SSH destination; the native Windows CPU worker is not that backup protocol. A physical backup check requires an independent destination, full checksummed readback/restore and a fresh recovery directory without the original source/staging files. Preserve the original data. Do not induce power loss or destroy source files. Loopback tests cannot prove physical device independence or power-loss durability.

## Keep the acceptance report useful

Record each stage separately: copied-package smoke, portable contracts, native CPU worker, selected cross-device SSH, local CUDA and independent backup. Use `passed`, `failed`, `not run` or `blocked` with the observed reason. Retain the full commit, exact Python executable, command, exit code, test count/skips and raw log path. For remote tests include host-key fingerprint and host/user identities, never key contents or tokens. Preserve uncertain jobs and their immutable IDs; do not resubmit to obtain a cleaner result.

Return the report and nonsecret receipt files to this chat using an explicit transfer. Same-account sign-in alone does not copy files. Keep original outputs and do not run held experiments.
