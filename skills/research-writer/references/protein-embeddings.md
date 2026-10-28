# Optional small protein representations

The original `scripts/protein_tools.py` adapter runs one pinned ESM-2 checkpoint:
`facebook/esm2_t6_8M_UR50D`, revision
`c731040fcd8d73dceaa04b0a8e6329b345b0f5df`. The official model card explicitly
labels these weights MIT. This does not license every ESM checkpoint, training
dataset, related ESMFold/ESM3 model or hosted service. The original adapter is MIT;
PyTorch, Transformers and other dependencies retain their own terms. No engine
source, weights or training data are shipped in the skill.

## Prepare a selected device

Use a separate Python environment compatible with your OS and selected backend.
Do not combine Meta `fair-esm` and Biohub `esm` packages. This adapter instead uses
Transformers' ESM implementation and safetensors; neither `esm` package is needed.
The release's isolated CPU control used Python 3.12, torch 2.14.1,
transformers 5.21.0, safetensors 0.8.0 and numpy 2.5.4. These versions are an
observed combination, not a universal OS/GPU lockfile. Consult official PyTorch
installation instructions for your device, then test that actual runtime.

Model preparation is a separate explicit network action:

```sh
python PATH_TO_SKILL/scripts/protein_tools.py prepare-model --directory PROJECT/models/esm2-small --allow-download
```

The parent directory must already exist. The command downloads six fixed files
from the official model revision (about 31.4 MB total), with fixed size and SHA-256
checks for every file. Requests carry no authentication token; redirects are
restricted to Hugging Face HTTPS model hosts. Existing model directories are
preserved. A failed preparation removes its staged data rather than leaving a
partially accepted model. Do not put the model in the installed skill or publish
it with your research repository. Reusing a directory requires exactly the six regular, nonsymlink
verified files; extra tokenizer/configuration sidecars are rejected. Use another path for a different checkpoint or modification.

## Run locally without a download

```sh
python PATH_TO_SKILL/scripts/protein_tools.py embed --input PROJECT/input.fasta --model-dir PROJECT/models/esm2-small --device cpu --output PROJECT/run.json --embedding-output PROJECT/embeddings.json --timeout 60 --threads 1
```

Use that environment's Python executable, including its full path when needed.
On Windows it is normally `ENV\Scripts\python.exe`; on Linux/macOS `ENV/bin/python`.
Optional user profiles can record the selected interpreter and a `model_dirs`
entry for `meta-esm`, but this command's explicit arguments select the actual
runtime and model. A profile never switches interpreters or provisions assets.

The adapter accepts at most 16 sequences, each 1–512 uppercase canonical amino
acids, with unique FASTA IDs. It rejects ambiguous/noncanonical symbols and long
sequences rather than silently truncating or mapping them. It produces 320 finite
values per sequence by averaging final-layer residue representations, excluding
BOS/EOS. Model inference uses `eval()` and inference mode, local files only,
verified safetensors and no custom remote code or pickle checkpoint. Inputs,
model revision/weight hash, artifact hash, runtime versions, platform, actual
device and pooling method are retained.

`cpu` is the conservative default and `auto` currently selects CPU. Explicit
`cuda` or `mps` requires the actual backend to be available; failure does not
silently fall back. CUDA on ROCm builds is currently rejected rather than relabeled
as tested CUDA. Accelerator presence alone does not establish model compatibility
or numerical quality. GPU/ROCm support needs separate task-sized testing.

Inference runs in a bounded subprocess (1–120 seconds, 1–8 CPU threads), with
input/report size and sequence-count limits. New report/artifact paths are
required; there is no force-overwrite inference flag. Failures report nonzero and
preserve a failure report when possible. Investigate partial outputs before any
retry; the adapter never resubmits a job automatically. Worker logs and result sizes are polled during execution; exceeding 1 MiB
terminates the worker, with possible transient overshoot between polls. Diagnostics
are bounded when copied into the failure report. Temporary worker files are removed.

These are representations, not structures, contact predictions, docking scores,
activity estimates or measurements of protein function. No novel chemistry,
cofactor compatibility, fitness or biological success is established. The small
canonical control checks execution and pooling; a licensed reference dataset and
task-specific benchmark are required before a scientific performance claim.

## Reproduce tests

From the repository, `python evals/protein_checks.py` runs offline contracts and
explicitly skips the optional real inference test. To require actual CPU inference:

```sh
python evals/protein_checks.py --protein --model-dir PROJECT/models/esm2-small
```

The real control checks finite dimensions, artifact identity, repeated-sequence
consistency, a contrasting sequence and an independently invoked masked-LM
hidden-state reference. This does not promise bitwise identity across builds or
backends.

Primary sources: [pinned official model card](https://huggingface.co/facebook/esm2_t6_8M_UR50D/blob/c731040fcd8d73dceaa04b0a8e6329b345b0f5df/README.md),
[official model files](https://huggingface.co/facebook/esm2_t6_8M_UR50D/tree/c731040fcd8d73dceaa04b0a8e6329b345b0f5df),
[Transformers ESM documentation](https://huggingface.co/docs/transformers/model_doc/esm),
[PyTorch device installation](https://pytorch.org/get-started/locally/).
