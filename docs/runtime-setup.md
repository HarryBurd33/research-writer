# Adapt the tools to your device

Install the complete `skills/research-writer` folder. Python 3.10+ can run the standard-library evidence tools and inventory/planning helpers. The molecular commands additionally require compatible RDKit and OpenMM packages. The skill does not install a GPU suite or models automatically.

Choose a user-owned project or runtime directory outside the installed skill. Create an isolated environment with your device's compatible Python, for example:

```sh
python -m venv .venv-research
```

On Linux/macOS use `.venv-research/bin/python`; on Windows use `.venv-research\Scripts\python.exe`. Use that executable for subsequent commands. An existing compatible environment may be reused instead.

For the narrow CPU utilities, install RDKit and OpenMM from their official documented package channels. The optional [tested requirements](../extras/cpu-tested-requirements.txt) record the exact versions used for this release's macOS arm64/Python 3.12.14 checks. They are not a promise that those wheels exist for every OS, architecture or Python. Inspect current supported wheels before installing; choose a compatible environment/version and repeat the controls when a different device requires a change.

From the repository, substituting the chosen environment's Python:

```sh
python -m pip install --only-binary=:all: -r extras/cpu-tested-requirements.txt
python evals/toolkit_checks.py --molecular
python evals/toolkit_regressions.py --molecular
python evals/package_smoke.py --molecular
python scripts/build_portable.py --check
```

The package install is a deliberate setup action. It uses the network and disk, but downloads no pretrained models. The toolkit never executes it itself. No bare system/global package installation is needed.

From the installed skill folder, create a device profile and inspect the environment:

```sh
python scripts/research_tools.py profile --output PROJECT/device.json
python scripts/research_tools.py doctor --profile PROJECT/device.json --output PROJECT/inventory.json
```

Replace `PROJECT` with the selected user-owned project path. Set `python` in the profile to the actual environment executable. The doctor still inspects the interpreter executing it: pointing at another Python is not a probe of that environment. User-owned `~/.local/share/research-writer/runtime.json` is an optional discoverable profile convention; it is never included in the reusable skill. A project-specific profile takes precedence.

Use local, remote, CPU, CUDA, MPS or ROCm declarations to plan; test the actual engine/backend separately. A remote profile does not connect or authenticate, and no credential belongs in it. Obtain user authorization and inspect the remote runtime before submitting any job. For heavyweight engines, resolve the selected release, compatible dependencies, weights/data terms, input chemistry, storage/RAM/VRAM and explicit compute/spending limits. A GPU alone does not make all catalog engines runnable. Keep the two ESM distributions and other conflicting ML stacks in separate environments.

Run `rdkit-descriptors`, a seeded `rdkit-conformer`, and `openmm-smoke` as small controls before relying on that environment. Preserve versions, input/output hashes and failures. These checks demonstrate local functionality only; neither a structure, docking score, generated molecule nor short simulation establishes biological success. See [commands and schemas](../skills/research-writer/references/tool-usage.md) and [device guide](../skills/research-writer/references/device-profiles.md).

After installing or moving the skill, run its `scripts/self_check.py` with the actual selected interpreter. Add `--molecular` to require CPU controls rather than skip them. See [test commands and matrix limits](testing.md).


For optional enforced Linux CPU execution, follow the separate
[Linux engine/image profile and lifecycle](../skills/research-writer/references/linux-isolation.md).
It uses an existing selected Docker Linux/cgroup-v2 engine and immutable local
image. It never installs a daemon, pulls an image or chooses a remote host.
The ordinary runtime above remains usable without it. Treat selected virtual
environment interpreter paths as executables; resolving their symlinks to a bare
Python binary can bypass the environment and its installed packages.


## Durable checkpoint storage

The optional [checkpoint helper](../skills/research-writer/references/durable-checkpoints.md)
uses Python's SQLite module and a trusted local filesystem. No extra PyPI package,
Docker engine or cloud account is needed for local file checkpoints. Set an explicit
store path, database byte ceiling and generation limit. Keep journals intact for
SQLite recovery. Database quota excludes rollback-journal and backup/restore space;
choose adequate disk headroom. Use consistent backups for authorized transfers.
Power-loss behavior depends on the actual OS/VFS/storage; no shared/network/cloud
filesystem locking or device-failure guarantee is assumed.
