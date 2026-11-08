# Local accelerator workload acceptance, version 1

`accelerator_tools.py` adds a separate `research-writer.accelerator-acceptance/1` contract. It does not change v1 CPU remote manifests or their CPU-only validators. A local GPU result is not external-host transport/lifecycle acceptance. Neither a configured device nor a mocked device proves GPU execution.

The one fixed control is a short synthetic canonical-amino-acid sequence. The workload uses the same six exact local ESM-2 assets, model ID `facebook/esm2_t6_8M_UR50D`, revision `c731040fcd8d73dceaa04b0a8e6329b345b0f5df`, as `protein_tools.py`. Every pinned asset is verified before/after computation. No model download, arbitrary user command, pickle weights, custom model code, token or external API is used. Existing compatible PyTorch/Transformers/safetensors must be present in the selected runtime; runtime versions are recorded rather than inferred from the host hardware.

## Select an existing host and device

First run `python accelerator_tools.py inspect --output NEW_inspection.json` on the selected host. Pin its actual hostname and user in a local profile with exactly these fields:

```json
{
  "contract": "research-writer.accelerator-acceptance/1",
  "expected_hostname": "explicit-selected-host",
  "expected_user": "explicit-selected-account",
  "device": "mps",
  "wall_seconds": 120,
  "max_log_bytes": 1048576,
  "max_result_bytes": 1048576,
  "max_accelerator_memory_bytes": 1073741824,
  "threads": 1
}
```

Devices are explicitly `mps` (Apple Metal; observed tensor identity `mps:0`) or `cuda:0` through `cuda:15` (native NVIDIA CUDA). `auto`, CPU fallback, ROCm and a missing selected device are rejected. CUDA runtime, device identity/index, model/input/output tensors and synchronization are recorded. MPS uses actual model/input/output MPS tensors and `torch.mps.synchronize`; `PYTORCH_ENABLE_MPS_FALLBACK=0` is set before importing PyTorch. A failing unsupported GPU operation stays a failure. The CPU reference is a separate intentional forward pass and does not substitute for GPU work.

No secrets belong in the profile. Configuration is not authorization to provision or access a host. Run on the already authorized machine/account. Symlinks/reparse points in acceptance paths and their ancestors are rejected; use native resolved paths (e.g. `/private/tmp` rather than the macOS `/tmp` symlink).

## Explicit bounded CLI

```sh
python accelerator_tools.py fixture --output NEW_control.fasta
python accelerator_tools.py prepare --profile selected-host.json --model-dir EXISTING_PINNED_MODEL --input NEW_control.fasta --directory NEW_JOB_DIRECTORY --output NEW_preparation.json
python accelerator_tools.py run --directory NEW_JOB_DIRECTORY --allow-execute --output NEW_run.json
python accelerator_tools.py status --directory NEW_JOB_DIRECTORY --output NEW_status.json
python accelerator_tools.py recover --directory NEW_JOB_DIRECTORY --output NEW_recovery.json
python accelerator_tools.py collect --directory NEW_JOB_DIRECTORY --output NEW_collected.json
python accelerator_tools.py cancel --directory NEW_JOB_DIRECTORY --allow-cancel --output NEW_cancel.json
```

Use the exact reviewed script path and the selected runtime's Python. Preparation binds the frozen input, host/user/device profile, model asset identities, source hashes and unique job ID. It performs no inference and creates a new private acceptance directory. Existing output reports and collection paths are preserved.

`run` fsyncs dispatch intent before launching its one fixed worker. A run is attempted once; a repeated call is refused even after timeout/failure/uncertainty. A live controller serializes mutations, polls resource bounds and services an explicit cancellation request using its own live process handle/group. It never signals a stored PID. A stale controller state becomes uncertain, and read-only recovery never relaunches. Collection requires successful parent validation and unchanged raw output checksum. The worker's private `_worker` entrypoint requires matching durable dispatch intent.

The whole worker has a 1–120 second deadline, logs at most 1 MiB, result at most 1 MiB, threads 1–8, one fixed short sequence and a declared accelerator allocator budget from 128 MiB to 2 GiB. These bound this particular workload; they are not a general security sandbox, network restriction, CPU RSS cap or physical GPU memory guarantee. PyTorch CUDA's allocator fraction restricts its caching allocator and reports exact allocated/reserved peaks. MPS's fraction restricts its allocator relative to recommended device working-set memory; MPS reports terminal tensor/driver allocations, not an exact historical peak. Non-PyTorch driver/kernel resources may exceed allocator accounting. Use an independent OS/job resource boundary if a strict process-memory guarantee is needed. Controller death does not establish cancellation proof; the original worker may finish and its result must be reconciled without retry.

## Numerical evidence and acceptance limits

Both CPU and GPU execute the pinned float32 ESM model in evaluation/inference mode with deterministic algorithms and a fixed seed. CUDA TF32 overrides are disabled. Raw full last-hidden-state tensors are retained, including special tokens, with shape `1 × (residue count + 2) × 320`. This is an ESM representation diagnostic, not folding or affinity prediction.

Before execution the comparison rule is fixed: every corresponding float must satisfy `abs(gpu - cpu) <= 0.0001 + 0.001 * abs(cpu)`. No threshold is widened after observing a failing run. Empty/wrong-shaped/nonfinite tensors, incorrect identity/device, missing synchronization, absent allocator evidence and raw checksum/comparison mismatches fail. The worker reports raw CPU/GPU tensors, and the controlling process independently checks every value, checksum, shape and immutable binding. It repeats validation during collection. This is independent numerical recomputation of the comparison, not an independent model implementation or proof of biological accuracy.

`python evals/accelerator_checks.py` provides portable schema/no-fallback/tensor-integrity controls; synthetic records explicitly supply no runtime acceptance. Actual local MPS/CUDA acceptance requires the selected runtime to execute this command and retain request, state, bounded diagnostics and collected raw tensors bound to the exact source. CUDA results remain unverified until tested on CUDA even when MPS passes.

Full external GPU acceptance additionally requires authenticated selected-host transport/host-key pins, real prepare/single-submit/status/checksummed collection/cancellation/timeout, client/controller restart and an induced ambiguous submission reconciled without duplicate dispatch. The current CPU remote route deliberately hides accelerators and cannot be treated as a GPU transport. A local Mac MPS run or Windows hosted CPU run does not close that external-host gate.

Primary API sources: [PyTorch CUDA allocator fraction](https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.set_per_process_memory_fraction.html), [MPS allocator fraction](https://docs.pytorch.org/docs/stable/generated/torch.mps.set_per_process_memory_fraction.html), [MPS synchronization](https://docs.pytorch.org/docs/stable/generated/torch.mps.synchronize.html), [MPS memory observations](https://docs.pytorch.org/docs/stable/mps.html), [Transformers ESM outputs](https://huggingface.co/docs/transformers/model_doc/esm).
