# Set up selected engines on your device

The installable skill contains original wrappers and guidance, not upstream
executables, model weights or a universal environment. Start with a user-owned
runtime directory outside the skill. Use separate environments when dependencies
differ. Do not install the entire catalog together.

## Molecular conversion

Create an isolated compatible Python environment and install the official Open
Babel package from its documented channel. The release selected `openbabel==3.2.1`
with available Python 3.12 wheels. Its executable is commonly `ENV/bin/obabel` on
Linux/macOS or `ENV\Scripts\obabel.exe` on Windows; verify the actual path/version.
Open Babel retains GPL-2.0-only terms and is not bundled or relicensed by this MIT
wrapper. No pretrained model is needed for conversion.

Run `scripts/conversion_tools.py` with the separate RDKit environment's Python,
supplying the Open Babel executable explicitly. Read [the conversion guide](../skills/research-writer/references/molecular-conversion.md)
for supported formats, independent identity checks and 2D coordinate handling.
Other metadata, properties and coordinate accuracy are outside the identity gate.

## Small protein representations

Create another Python environment compatible with PyTorch and Transformers. The
tested local combination is Python 3.12, torch 2.14.1, transformers 5.21.0,
safetensors 0.8.0 and numpy 2.5.4. Consult current official PyTorch installation
instructions for the selected OS/backend. CPU-only Linux/Windows packages can use
the official `https://download.pytorch.org/whl/cpu` index; do not install CUDA
packages merely because a profile declares a GPU. Selected requirements are in
`extras/protein-tested-requirements.txt`, not a universal lockfile.

Model preparation requires an explicit command and `--allow-download`. It fetches
about 31.4 MB from one official, immutable, MIT-licensed small ESM-2 model revision
and verifies every asset. No token or paid provider is needed. Keep the verified
directory outside this repository and the installed skill. See [the protein guide](../skills/research-writer/references/protein-embeddings.md)
for exact commands and accepted sequence/device limits. Inference uses local files
only and safetensors; missing or changed assets fail. Other model/checkpoint rights
are not established by this checkpoint's license.

## Adapt and verify

Record the actual interpreter, executable and model paths in user/project profiles
as described in [device guidance](../skills/research-writer/references/device-profiles.md).
Profiles do not create environments, move files or establish execution. Use the
selected interpreter explicitly. Run positive and negative controls after moving
devices or changing versions, and preserve the report and hashes.

The installed self-check can require both engines using explicit paths; see
[tests](testing.md). CPU success does not validate CUDA, MPS, ROCm, docking, folding,
scientific accuracy or biological function. Larger/docking engines require their
own compatible assets, task, resource bounds and independent acceptance.
