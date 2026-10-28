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
