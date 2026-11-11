# Remote accelerator execution

`accelerator_remote_tools.py` uses the `research-writer.accelerator-remote/1` protocol to run the fixed synthetic ESM-2 comparison on a selected accelerator over authenticated SSH. The client and remote worker require POSIX. The selected device must be `mps` or `cuda:0` through `cuda:15`. The only CPU pass is the numerical reference. The original CPU remote protocol has its own entry point and schema.

## Select an existing installation

Use an authorized OpenSSH endpoint with a POSIX login shell, an existing public-key login, and an Ed25519 server key obtained from a trusted administrator or local host inventory. Use the exact reviewed skill scripts and an existing CPython 3.11 or later installation with wheel-installed PyTorch, Transformers and safetensors. The selected model directory must already contain the six pinned files for `facebook/esm2_t6_8M_UR50D` at revision `c731040fcd8d73dceaa04b0a8e6329b345b0f5df`. See [local accelerator acceptance](accelerator-acceptance.md) for the asset, workload and allocator contracts.

Select absolute paths for the existing Python executable, site-packages, scripts, model and remote job directory. The job directory must already exist, belong to the selected account and exclude group and other access. Its ancestors and the other selected directory paths must be free of symlinks. For a virtual environment select its literal `bin/python` executable, which can itself be a symlink. The selected site-packages directory must work without `.pth` processing, user-site packages, or editable package loaders.

Gather the following two JSON objects independently on the trusted sides. Inventory inspects the selected interpreter and package metadata without importing those packages or testing the device.

```sh
# Run in the reviewed local installation.
python3 accelerator_remote_tools.py source-pins --output source-pins.json

# Run on the selected remote machine with the reviewed installed script.
EXISTING_VENV/bin/python -I -S -B EXISTING_SCRIPTS/accelerator_remote_worker.py \
  --inventory --site-packages ABSOLUTE_SITE_PACKAGES > runtime-inventory.json
```

Build a profile with the following shape. Replace each placeholder with a selected value. Replace the `target.runtime` and `source_pins` placeholder objects in their entirety with the two JSON objects. `target.hostname` is the inventory hostname and may differ from the SSH address. `target.user` and the workload host and user must also match inventory. Keep private key contents out of the profile. The path under `identity_file` is a local OpenSSH identity file path.

```json
{
  "contract": "research-writer.accelerator-remote/1",
  "ssh": {
    "host": "selected.example.org",
    "port": 22,
    "identity_file": "/local/private/ssh-identity",
    "ed25519_host_key": "ssh-ed25519 REPLACE_WITH_TRUSTED_PUBLIC_HOST_KEY",
    "connect_timeout_seconds": 10
  },
  "target": {
    "hostname": "selected-host",
    "user": "selected-account",
    "python": "/remote/venv/bin/python",
    "site_packages": "/remote/venv/lib/python3.12/site-packages",
    "scripts": "/remote/reviewed/research-writer/scripts",
    "model": "/remote/existing/esm2_t6_8M_UR50D",
    "jobs": "/remote/private/accelerator-jobs",
    "runtime": {}
  },
  "workload": {
    "contract": "research-writer.accelerator-acceptance/1",
    "expected_hostname": "selected-host",
    "expected_user": "selected-account",
    "device": "mps",
    "wall_seconds": 120,
    "max_log_bytes": 65536,
    "max_result_bytes": 1048576,
    "max_accelerator_memory_bytes": 1073741824,
    "threads": 1
  },
  "source_pins": {}
}
```

SSH uses a temporary known-hosts file containing only the pinned key, public-key batch authentication, and one new direct connection per operation. It starts isolated Python with site initialization disabled. The reviewed bootstrap verifies the exact bytes of the installed worker before executing them. The worker compares the effective account, hostname, platform, literal interpreter path and binary digest, virtual-environment configuration digest when present, and installed distribution versions and metadata and RECORD digests before importing the checked skill sources. It loads the selected site-packages only in the compute child. These pins identify a trusted installation. Installed wheel metadata does not attest every installed dependency byte, the base Python standard library, drivers, or the remote operating system. A trusted remote account must keep the installation and job root under its control throughout execution. [OpenSSH client](https://man.openbsd.org/ssh.1), [OpenSSH options](https://man.openbsd.org/ssh_config.5), [CPython command-line isolation](https://docs.python.org/3/using/cmdline.html), [Python distribution metadata](https://docs.python.org/3/library/importlib.metadata.html).

## Run and recover one job

```sh
python3 accelerator_tools.py fixture --output new-control.fasta
python3 accelerator_remote_tools.py inspect --profile selected.json --output inspect.json
python3 accelerator_remote_tools.py prepare --profile selected.json --directory new-local-job \
  --input new-control.fasta --allow-transfer --output prepare.json
python3 accelerator_remote_tools.py submit --profile selected.json --directory new-local-job \
  --allow-execute --output submit.json
python3 accelerator_remote_tools.py status --profile selected.json --directory new-local-job \
  --output status.json
python3 accelerator_remote_tools.py recover --profile selected.json --directory new-local-job \
  --output recovery.json
python3 accelerator_remote_tools.py collect --profile selected.json --directory new-local-job \
  --destination new-raw-tensors.json --output collection-receipt.json
python3 accelerator_remote_tools.py cancel --profile selected.json --directory new-local-job \
  --allow-cancel --output cancellation.json
```

Use new report paths and keep the local job directory and selected profile for recovery. Preparation transfers the exact public fixture and its fixed request. Reviewed sources, runtime, credentials and model assets remain at their pre-existing locations. The worker verifies the exact six asset hashes before accepting preparation and during compute and collection. Inspection checks identity pins without running the model. No operation provisions the host, fetches a model or invokes a caller-selected command.

The client fsyncs and exclusively publishes the local submit intent before attempting submission. The remote side likewise commits an exclusive intent before launching a detached controller. A new client can use `recover` to reconcile a lost preparation or submission acknowledgement. Recovery reads state without dispatching. A stale heartbeat or an unreachable outcome stays uncertain, including when a local submit intent exists and the remote record cannot be found. There is no resubmission of that job. State publication covers ordinary process restart. Power-loss persistence depends on the filesystem and storage.

The controller owns the live compute process and responds to the job's cancellation marker or wall deadline using that process handle. A cancellation receipt can report a pending request. An expired controller heartbeat cannot establish process termination. The compute child also has its own POSIX wall alarm. Status can establish a terminal outcome only from the controller's committed record. The client never signals a stored PID. Treat the job directory as private to the selected account and preserve it until outcomes are reconciled.

The compute streams are bounded before retaining bytes. Logs and the raw result each have independent caps, and the request, SSH capture and collection payload have protocol limits. These bounds cover the fixed control, not whole-process memory or arbitrary process trees. The controller, the remote collection handler and the client check the result identity, actual model/input/output device, synchronization, allocator evidence, raw float32 arrays and SHA-256. They recompute the original elementwise tolerance on both raw arrays. The final result is a new byte-exact file and collection refuses existing destinations. One report stores its checksum and comparison metrics.

## Evidence and pending hosts

Run `python3 evals/accelerator_remote_checks.py` from the repository for the portable contract tests on POSIX. To run the actual Apple Silicon MPS loopback tests, provide `--run-ssh --python ABSOLUTE_VENV_PYTHON --site-packages ABSOLUTE_SITE_PACKAGES --model-dir ABSOLUTE_MODEL --evidence-dir NEW_ABSOLUTE_DIRECTORY`. This opt-in fixture starts a disposable local listener using temporary keys. It requires permission to bind a loopback port and execute the selected runtime.

Loopback evidence applies to the tested Mac, interpreter, model assets, reviewed code and OpenSSH. Independent physical-host accelerator execution and actual CUDA execution require separate acceptance on selected hosts. Allocator observations apply to the backend's accounting described in [local accelerator acceptance](accelerator-acceptance.md). The numerical control measures agreement on the fixed ESM representation and makes no biological performance claim.
