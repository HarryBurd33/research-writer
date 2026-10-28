# Device profiles and capability checks

The catalog records source-audited interfaces, not installed tools. Discover the actual interpreter, package versions, command paths and platform on the machine that will run the work. Keep source revision, detected dependency presence, optional probe results, smoke results and scientific validation as separate evidence. A declared CUDA/MPS/remote setting is not a successful capability probe.

From the skill directory, replace `PROJECT` with the selected project/configuration directory outside the installed skill:

```sh
python scripts/research_tools.py profile --output PROJECT/device-profile.json
python scripts/research_tools.py doctor --output PROJECT/doctor.json
python scripts/research_tools.py doctor --profile PROJECT/device-profile.json --output PROJECT/doctor.json
python scripts/research_tools.py doctor --profile PROJECT/device-profile.json --probe-gpu --output PROJECT/doctor-gpu.json
python scripts/research_tools.py plan --tool boltz --input PROJECT/complex.yaml --profile PROJECT/device-profile.json --output PROJECT/boltz-plan.json
```

`plan` prepares a reviewable recipe; it does not execute the engine, install dependencies, download weights, generate MSAs or submit sequences. Check its unresolved prerequisites and limitations before proceeding. The helper also provides bounded local `fasta`, `rdkit-descriptors`, `rdkit-conformer` and `openmm-smoke` operations; use the helper's help for their exact arguments. A conformer or artificial OpenMM energy check is not a validated research study.

Keep the profile in a user-owned research project/configuration directory **outside the installed skill**. Reuse only isolated runtime paths supplied in that user's configuration. Do not embed the skill author's machine paths or copy credentials into profiles, notes or reports.

Profile fields:

| Field | Value |
| --- | --- |
| `schema_version` | `1` |
| `mode` | `"local"` or `"remote"` |
| `python` | Optional interpreter path string |
| `remote_host` | Optional remote-host string; no passwords/tokens |
| `accelerator` | `"auto"`, `"cpu"`, `"cuda"`, `"mps"`, `"rocm"` or `"unknown"` |
| `executables` | Object mapping catalog engine IDs to user-supplied executable/script paths |
| `model_dirs` | Object mapping catalog engine IDs to user-supplied model directories |
| `notes` | String with nonsecret compatibility context |

A minimal declaration is:

```json
{
  "schema_version": 1,
  "mode": "local",
  "accelerator": "auto",
  "executables": {},
  "model_dirs": {},
  "notes": ""
}
```

A profile is data and grants **no authority** to install, execute remotely, spend money, upload inputs or accept terms. Default doctor checks describe current-interpreter packages/platform and command paths. They do not establish that a different declared interpreter contains those packages. Invoke the helper using the intended environment's interpreter to examine that environment. GPU probing is an explicit extra check; detected hardware still needs a compatible engine build/kernel and a task-sized acceptance run. Remote profiles remain **unprobed**: doctor does not SSH, authenticate or execute there. Obtain remote evidence only through a separately authorized workflow.

Use separate environments where dependencies conflict. In particular, Meta `fair-esm` and Biohub `esm` share the `esm` import namespace and need separate environments. DeepChem, DiffDock and REINVENT4 have materially different Python/Torch/numpy requirements. Do not install every catalog package into one environment.

CUDA, ROCm and Apple MPS are different backends; one detected accelerator does not imply support by every engine. CPU fallback is useful only where the selected interface/build supports it and the runtime is acceptable. Check Windows/WSL, macOS architecture and Linux support per engine; no universal portability is promised. AF3 source exposes CPU/MPS paths beyond older installation prose, while GNINA's runtime CPU flag does not remove its source-build CUDA dependency. OpenMM's small diagnostic should select Reference explicitly; real simulations need parameters and a protocol.

Before heavy work, verify exact runtime/model versions and hashes, input chemistry and provenance, compatible topology/tokenization/parameters, licenses and service terms, model/database/cache/temp storage, RAM/VRAM, elapsed-time/output limits and spending boundaries. Missing prerequisites remain explicit. Never add automatic API fallback, checkpoint/dataset download, MSA generation, sequence/structure upload or all-package installation. Preserve failed runs and report what was actually measured.


## Executable adapter runtimes

Keep one compatible runtime per selected dependency stack. Open Babel conversion
can run its supplied executable in one environment while RDKit validates outputs
in another. The small ESM-2 adapter uses Transformers in a separate interpreter;
it does not require either shared `esm` namespace. Use project profiles for each
runtime: `python` identifies its interpreter, `executables.openbabel` the converter,
and `model_dirs.meta-esm` the selected verified local model directory. These are
user-owned paths, not shared defaults. The traditional catalog doctor is an
inventory of its named distributions, not proof that an alternative adapter works.
The adapter's own report records its actual runtime and observed execution.

CPU is the conservative embedding default. An explicit unavailable CUDA/MPS
request fails; hardware detection does not establish broader engine support.
Moving a profile cannot move its packages or weights. Reinstall compatible
versions and repeat controls on each device. No remote host is contacted by
these adapters. See the two execution guides for exact supported inputs/limits.
