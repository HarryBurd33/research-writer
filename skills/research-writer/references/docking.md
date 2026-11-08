# Optional AutoDock Vina docking

Use `scripts/docking_tools.py` with an explicitly selected trusted **AutoDock Vina 1.2.7** executable and an RDKit-capable Python interpreter. The adapter downloads nothing, prepares no chemistry and uploads nothing. Supply prepared PDBQT files, a search box and a new output directory. The ligand must include one `REMARK SMILES` and a complete `REMARK SMILES IDX` heavy-atom mapping. Unsupported residues, cofactors, isotopes, atom types, malformed geometry or incomplete mappings are rejected. Only standard protein receptor residues plus HID/HIE/HIP/CYX are accepted. This narrow route does not represent every Vina capability.

Create a JSON specification with exactly these fields (replace paths and digest placeholders with the actual selected files):

```json
{
  "schema_version": 1,
  "engine": {"path": "/absolute/vina", "sha256": "actual executable SHA-256", "version": "1.2.7"},
  "receptor": {"path": "/absolute/receptor.pdbqt", "sha256": "actual receptor SHA-256"},
  "ligand": {"path": "/absolute/ligand.pdbqt", "sha256": "actual ligand SHA-256"},
  "center": [15.190, 53.903, 16.917],
  "size": [20.0, 20.0, 20.0],
  "seed": 20261108,
  "cpu": 2,
  "exhaustiveness": 32,
  "num_modes": 9,
  "timeout_seconds": 1800,
  "max_output_bytes": 1048576
}
```

```sh
python /absolute/skill/scripts/docking_tools.py --spec /absolute/request.json --output-dir /absolute/new-run
```

Limits are 1–16 CPU threads, exhaustiveness 1–64, 1–20 modes, 1–3600 seconds and 1 KiB–64 MiB per output/log. Coordinates and charges must be finite. Inputs are regular, nonsymlink files with matching hashes. The executable also must report the pinned version. Local hashing records the selected binary identity; it does not prove publisher authentication when an upstream checksum is unavailable. Obtain trusted binaries through the official release channel.

The report records exact settings, hashes, executable/version, command, elapsed time, pose scores, atom identities and output hash. Complete poses retain atom mapping, types, charges and covalent geometry. Failures retain their report and available partial files; an existing destination is never overwritten. Timeout/process-group handling is accepted on the tested POSIX route. The Windows docking process-tree lifecycle has not been separately accepted. Polling limits can overshoot; this trusted-binary wrapper is not an OS sandbox, a hard CPU/RAM quota or network isolation.

For a frozen reference test, add `reference` with `path`, `sha256` and `maximum_rmsd_angstrom`. It uses the same mapped PDBQT format. The metric compares all heavy atoms by fixed SMILES index **without rigid alignment or symmetry minimization**, preserving the receptor coordinate frame. The Vina output's own RMSD columns compare poses against its best pose; they are not crystallographic error. Freeze receptor/ligand/reference, box, seed, exhaustiveness, mode count and threshold before execution, and retain failures.

Observed engineering fixture: official 1IEP example at source revision `8eb40404f4f45608acb3b01427587ac049f27c1f`, independently mapped to crystallographic ligand STI A201 (37 heavy atoms). On macOS arm64 CPU, seed 20261108/exhaustiveness32/CPU2 yielded six checked poses; top pose RMSD was **0.9067858146 Å** against a predeclared 2 Å threshold, with predicted score −13.197 kcal/mol. An independent raw-coordinate implementation confirmed the result and rejected a displaced negative control. This single known-reference case does not establish general docking accuracy, measured affinity, biological activity or clinical usefulness.

The wrapper and tests are original MIT code. Upstream [AutoDock Vina](https://github.com/ccsb-scripps/AutoDock-Vina/tree/8eb40404f4f45608acb3b01427587ac049f27c1f) is separately [Apache-2.0 licensed](https://github.com/ccsb-scripps/AutoDock-Vina/blob/8eb40404f4f45608acb3b01427587ac049f27c1f/LICENSE). No binary or example structure is bundled. See the [official release](https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7), [basic docking instructions](https://autodock-vina.readthedocs.io/en/latest/docking_basic.html) and [1IEP archive](https://www.rcsb.org/structure/1IEP) for acquisition and provenance.
