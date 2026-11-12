# Optional local structure prediction

The original `scripts/structure_tools.py` adapter runs **Boltz-1 through Boltz 2.2.1**, on a selected local CPU interpreter. It accepts one canonical protein chain. It is separate from the existing ESM-2 embedding route. Source implementation and offline contract checks do not establish actual folding execution, model accuracy, GPU support or external-host availability. Consult the run receipt and current validation record before claiming any of those states.

## Explicit resources and provenance

The caller supplies an existing Python 3.10–3.12 executable, a clean Boltz checkout, a two-file asset directory and a new output directory. The controller interpreter requires `psutil`; the worker interpreter requires the pinned Boltz source's dependencies installed without the CUDA extra. The adapter does not install packages, acquire models, connect to another machine or call an MSA service.

- Boltz source commit: `b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc` ([pyproject](https://github.com/jwohlwend/boltz/blob/b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc/pyproject.toml)). Every file under `src/boltz` and `pyproject.toml` is checked against this git tree; extra files, symlinks, changed files and cached bytecode in that source tree are refused. Use an isolated clean checkout and `PYTHONDONTWRITEBYTECODE=1` during environment preparation.
- Model distribution revision: `7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1` of [boltz-community/boltz-1](https://huggingface.co/boltz-community/boltz-1/tree/7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1).
- `boltz1_conf.ckpt`, approximately 3.6 GB, SHA256 `fea245d912c570ec117b2277c2719f312a6fc109c07b6f6ef741690ee775c2f5`.
- `ccd.pkl`, approximately 346 MB, SHA256 `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4`.

Those are rounded decimal download sizes, not a complete installation/disk/RAM budget. Asset checks permit at most 4 GiB per file and 5 GiB total, and require the exact published hashes. The directory must contain exactly those two files. CPU time is input- and hardware-dependent and has not been promised. A 16 GiB machine should start with an 8 GiB sampled process-tree memory limit and a bounded small fixture; model loading may exceed that limit and fail legitimately.

## Version 1 request

Create a JSON file with exactly these fields; all paths are explicit absolute paths. Sequence text remains in the private request/input files, so do not publish the output directory indiscriminately.

```json
{
  "schema": "research-writer.structure.v1",
  "python": "/absolute/boltz-env/bin/python",
  "boltz_source": "/absolute/clean-boltz-checkout",
  "assets_dir": "/absolute/boltz1-assets",
  "output_dir": "/absolute/new-structure-run",
  "sequence": "TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN",
  "chain_id": "A",
  "device": "cpu",
  "seed": 20261108,
  "threads": 2,
  "timeout_seconds": 3600,
  "recycling_steps": 1,
  "sampling_steps": 20,
  "max_output_bytes": 67108864,
  "max_log_bytes": 1048576,
  "memory_budget_bytes": 8589934592
}
```

Supported limits: 4–128 uppercase canonical amino acids; exactly chain A; CPU only; seed 0–2147483647; threads 1–8; walltime 1–3600 seconds; recycling steps 1–3; sampling steps 1–200; output 1–256 MiB; logs 1 KiB–4 MiB; memory 1–10 GiB. Unknown fields/versions, noncanonical residues, multiple chains, booleans masquerading as integers and silent device fallback are refused.

```text
python /absolute/research-writer/scripts/structure_tools.py run --spec /absolute/request.json
```

The controller can use a different interpreter from `python` in the request, but must have `psutil`. The current process-tree monitor requires POSIX process groups and non-reaping process-status inspection; native Windows is pending. Output is reserved exclusively. Existing directories are never reused or overwritten; changing parameters requires a new directory. Output may not overlap the source checkout or asset cache.

The adapter creates single-sequence YAML (`msa: empty`), selects `--model boltz1 --accelerator cpu --no_kernels`, one diffusion sample, zero data-loader workers and one preprocessing thread. Its isolated worker invokes the audited Click entry point with explicit argv. The upstream downloader is replaced with local hash verification, and Python socket connect calls are denied. These measures prevent accidental in-process download/service use; they do not constrain arbitrary native-library networking, escaped subprocesses or malicious dependencies. This is an authorized trusted-code runner, not a universal network/filesystem sandbox.

## Results and bounds

`report.json` persists preflight, running and final evidence. A failure after reserving the output directory retains a structured report; invalid JSON or an invalid/unreservable destination can only produce stderr. `failed` means preflight did not launch; `partial` means the worker started but did not produce an accepted result; `interrupted` records a human interrupt. `succeeded` requires successful child completion, matching model/source/interpreter provenance, observed model-forward computation on CPU, and independent structure/confidence validation. `actual_runtime_verified` stays false for rejected output. A standalone validator never claims engine execution.

The worker records model-forward call count, parameter/output device checks, output tensor shapes, Python/library versions, the interpreter hash and the CPU Torch library hash. GPU/MPS is rejected, not represented by configured inventory. CPU evidence does not close any external GPU requirement.

Captured logs are hard-capped. A POSIX per-file limit and repeated aggregate-output checks stop excess output; short aggregate bursts can exceed a sampled cap before termination. `psutil` samples the owned process tree's RSS, so transient peaks and deliberately detached processes are not a hard memory-isolation guarantee. The monitor records peak sampled RSS and terminates the owned session on timeout/observed bounds. If a host prohibits process-group signaling, it falls back to tracked owned process IDs after identity checks, and records that narrower cleanup mode. Unobserved/detached descendants are outside that fallback's guarantee. The leader remains unreaped until cleanup, preserving PID ownership. Partial files remain explicitly unaccepted. Results report walltime and observed retained/log sizes.

The expected prediction is `engine/boltz_results_input/predictions/input/input_model_0.pdb`, alongside `confidence_input_model_0.json`. The adapter independently checks exact chain and residue sequence/numbering, one nonempty model, finite coordinates, unique atoms, complete N/CA/C/O backbone, within-residue backbone distances and consecutive peptide bonds. This rejects missing/truncated or wrong-sequence output, but is not a full steric, sidechain or chemistry validation. The standalone validator also accepts a constrained standard atom-site mmCIF representation.

```text
python /absolute/research-writer/scripts/structure_tools.py validate-output --structure /absolute/model.pdb --confidence /absolute/confidence.json --sequence TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN
```

Boltz `confidence_score`, `ptm` and `complex_plddt` must be finite numbers in [0,1]. Their definitions come from the pinned [prediction specification](https://github.com/jwohlwend/boltz/blob/b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc/docs/prediction.md). They are model confidence, not measured physical accuracy, affinity or biological validity. Single-sequence/reduced-step settings can reduce prediction quality; valid output from such a smoke is not equivalent to default-quality inference.

## Optional local alignment input

Existing `research-writer.structure.v1` requests retain their exact fields and
single-sequence behavior. To supply a local alignment, use
`"schema": "research-writer.structure.v2"`, retain every other v1 field, and add
exactly one `msa` object:

```json
{"msa": {"mode": "local_a3m", "path": "/absolute/alignment.a3m", "sha256": "64 lowercase hexadecimal characters"}}
```

Use `{"msa":{"mode":"empty"}}` for explicit single-sequence v2 execution.
Other modes, missing fields and unknown fields are refused. There is no automatic
alignment download or MSA-server request. The path must identify an existing
nonsymlink `.a3m` file, outside the output directory, with a matching SHA-256.
Its ancestors must also be free of symlinks/reparse points; use the canonical
physical path rather than a directory alias.

The alignment is limited to 1 MiB and 1,024 sequences. Its first sequence must
exactly equal the requested uppercase canonical query. Every row must have the
same aligned width after lowercase insertions are removed; uppercase canonical
amino acids, lowercase canonical insertions and `-` gaps are supported. Headers
are bounded to 256 ASCII characters and each sequence row to 8,192 characters.
Ambiguous residues and other alphabets are refused by this limited adapter.

Validated bytes are copied to the new run directory. The worker checks the staged
and original checksums before and after prediction, and the parent checks the
binding again before accepting the result. Reports retain the alignment checksum,
byte count, sequence count and aligned width. A changed input fails acceptance.
Format validation cannot establish homology, input rights or scientific quality;
the user must supply a scientifically suitable alignment with appropriate rights.
The alignment and its metadata remain local run data, outside the installable skill.

Upstream documents precomputed A3M input and warns that single-sequence prediction
can reduce accuracy. This input option removes the adapter's forced-empty-MSA
restriction; it does not guarantee that any alignment improves a prediction.
A query-only A3M execution validates this input path and is not evidence of
improved structural accuracy. The original frozen benchmark below is unchanged.

## Explicit optional Boltz-2 route

`research-writer.structure.v3` is a separate, closed request: retain every v2
field, including explicit `msa`, and add exactly `"model":"boltz2"`. Existing
v1/v2 requests continue to select Boltz-1; there is no implicit default-model
upgrade. V3 accepts the same canonical single-chain inputs, with tighter ceilings:
2 CPU threads, 8 GiB sampled process-tree RSS, 64 MiB output, 1 MiB logs and
3600 seconds. It uses the pinned source already listed above and its official
model-2 defaults, including CPU `bf16-mixed` precision, 64 Pairformer blocks,
step scale 1.5, paired-MSA features and one diffusion sample. No affinity,
template, constraints, modifications, method override, MSA service or silent
precision/device fallback is exposed. A configuration accepted by source does
not establish that a particular CPU supports every operation or fits the limit.

Prepare a **separate fresh cache** with exactly these previously acquired files
from [official model revision
6fdef46d763fee7fbb83ca5501ccceff43b85607](https://huggingface.co/boltz-community/boltz-2/tree/6fdef46d763fee7fbb83ca5501ccceff43b85607):

| File | Exact bytes | SHA-256 |
| --- | ---: | --- |
| `boltz2_conf.ckpt` | 2286561469 | `090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1` |
| `mols.tar` | 1855662080 | `39e076d96dbec6b4e86982bbda16f3a53a2a60c9bdc17828d88f6f9a0c7d1fd7` |

The adapter never downloads these assets. Run the explicit offline preparation
command once before supplying that cache as `assets_dir`:

```text
python /absolute/research-writer/scripts/structure_tools.py prepare-boltz2-assets --assets-dir /absolute/fresh-boltz2-assets
```

Preparation hashes both files, validates the complete raw tar stream, and
extracts only the 21 source-defined canonical protein molecule files to `mols/`.
It permits at most 100000 headers, 3 GiB declared regular payload, bounded PAX
metadata (16 KiB per extension, 1 MiB total), 4 MiB per selected molecule and
64 MiB selected payload. Paths must be unambiguous ASCII paths under `mols/`;
links, devices, traversal, duplicate/case-aliased paths, unsupported extensions,
invalid checksums and non-padding appended content are refused. Every output
file is new. Existing prepared caches are not overwritten or repaired in place;
partial preparation remains unaccepted and needs explicit reconciliation.

`boltz2-assets.json` records the archive-derived inventory. Runtime verification
re-derives that inventory from the publisher-pinned tar and hashes the actual
molecules; editing a molecule and its receipt together cannot authorize altered
bytes. Unknown or missing cache entries and file/ancestor aliases are refused.
No pickle is loaded during preparation. The required canonical molecule files
are deserialized only by the trusted scientific runtime after verification.
The unused affinity checkpoint is neither required nor represented by a fake
file. The upstream automatic downloader is replaced by the offline verifier.

V3 validates the request, source and prepared assets before reserving output.
Its worker guards the upstream dataset's recursive error fallback, preserving
the first error instead of retrying another input. Receipts bind the actual
checkpoint, CPU input/parameter/output devices, CPU BF16 autocast state, route
settings and exactly one forward. Mixed precision does not imply every model
parameter has BF16 dtype. Afterward source/assets are reverified and PDB output
must contain every canonical heavy atom with its correct element, in addition
to the existing sequence, finite-coordinate and backbone checks. For the frozen
crambin query this means 326 heavy atoms and all 46 C-alpha atoms, with no OXT;
the reference's terminal OXT remains outside the unchanged C-alpha metric.

Offline checks use synthetic data and do not run prediction:

```text
python /absolute/package/evals/structure_boltz2_checks.py -v
```

The 0.18 candidate independently passed the fixed 1CRN chain A fixture at
0.5903 Å RMSD across all 46 Cα atoms, with all 326 typed heavy atoms present.
The Mac CPU worker took 111.631 seconds and peaked at 4.12 GiB sampled RSS.
The run used a separately verified Python 3.12.14 environment, PyTorch 2.15.0
and verified local assets. For a new environment, verify the actual interpreter,
source, model assets and feature inputs before relying on a prediction. This
result covers the pinned fixture and settings. The earlier Boltz-1 failures
remain recorded. The publisher's
MIT grant covers code and weights; auxiliary molecule generation lineage is not
independently established, and no model/molecule assets are redistributed by
this skill. Cite Passaro et al., *Boltz-2: Towards Accurate and Efficient Binding
Affinity Prediction* (2025), DOI 10.1101/2025.06.14.659707.

## Frozen reference protocol

The first optional scientific fixture is **1CRN chain A**, 46-residue crambin, using the sequence above and independently acquired [PDB archive coordinates](https://files.rcsb.org/download/1CRN.pdb). Record its exact downloaded hash and [entry identity](https://www.rcsb.org/structure/1CRN). For the reference gate, use seed 20261108, 3 recycles, 200 sampling steps and one diffusion sample. The threshold is C-alpha RMSD <=2.0 Å across all 46 sequence-matched residues after least-squares rigid alignment. Freeze this rule before any inference; retain failure if it is not met. This is a known-reference engineering check, possibly overlapping training data, not a held-out general-accuracy result.

The optional test parses with Bio.PDB independently of the adapter parser, verifies both exact sequences and records RMSD, threshold, source/output hashes and result. Positive metric control: a translated reference aligns to nearly zero. Negative metric control: displace one internal C-alpha by 50 Å; aligned RMSD must exceed 2 Å. Offline malformed-identity, truncated-backbone, nonfinite-coordinate and confidence controls remain required.

```text
python /absolute/package/evals/structure_checks.py -v
python /absolute/package/evals/structure_checks.py --actual-spec /absolute/default-settings-request.json --reference /absolute/1CRN.pdb -v
```

The first command does not fold anything. It reports separate skips if `psutil` or the real runtime/assets are absent. The second explicitly runs the actual engine and needs NumPy/Biopython in the test interpreter. An output-valid prediction can pass execution while failing the scientific RMSD gate; keep those outcomes separate.

## Rights and attribution

The adapter/tests are original MIT-licensed code. Boltz's [MIT license](https://github.com/jwohlwend/boltz/blob/b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc/LICENSE) names Jeremy Wohlwend, Gabriele Corso and Saro Passaro; its [README](https://github.com/jwohlwend/boltz/blob/b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc/README.md) explicitly covers code and model weights. Retain notices with copied material and cite Wohlwend et al., *Boltz-1: Democratizing Biomolecular Interaction Modeling* (2024), DOI 10.1101/2024.11.19.624167.

Model terms do not automatically relicense training datasets or external services. The CCD pickle is used as the official local dependency; its generation lineage/file-specific data grant was not established in this audit, and it is not redistributed by the skill. Original PDB archive coordinates are separately [CC0](https://www.rcsb.org/pages/policies). Keep models, fixtures and private requests out of the distributed skill. No ColabFold service, private-data upload or paid API is authorized by this recipe.
