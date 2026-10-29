# Original tool commands

These helpers are installed with the complete skill folder. Run them with Python 3.10+ from that folder, replacing `PROJECT` with the user-selected project directory. Store reports and profiles outside the installed skill. Inspect `--help` before a new operation. Reports preserve existing files unless `--force` is explicit. No command installs packages, downloads weights, invokes an LLM or launches a remote engine.

## Environment and optional dependencies

The standard-library tools need no API key. Molecular commands require a compatible, separately installed RDKit/OpenMM environment. Use that environment's Python, not merely a profile pointing at it. Keep conflicting heavy engines in separate environments. An optional user-owned `~/.local/share/research-writer/runtime.json` can record this device's interpreter and paths; a project-specific profile overrides that convenience. Never bundle this private file or treat it as permission.

For a fresh, user-authorized CPU environment, create a virtual environment in a chosen user directory, then install `rdkit` and `openmm` from their documented package sources. Record the actual resolved versions. `pip install` is a setup action, not performed by these helpers. Python/package wheels and GPU backends vary by device; consult the catalog and run the same small controls before using a different environment.

```sh
python scripts/research_tools.py profile --output PROJECT/device.json
python scripts/research_tools.py doctor --profile PROJECT/device.json --output PROJECT/inventory.json
python scripts/research_tools.py plan --tool boltz --input PROJECT/complex.yaml --profile PROJECT/device.json --output PROJECT/boltz-plan.json
```

The plan's command is an upstream example with unresolved placeholders, not an executable job. It does not validate the input using the engine. For API-based tools or multi-input operations without a generic CLI, the command is null and the catalog's interfaces/prerequisites govern preparation. Remote profiles are unprobed; authorized remote inspection and execution occur separately. `--probe-gpu` adds a bounded local NVIDIA inventory when available; it does not test all accelerators or models. See [device profiles](device-profiles.md).

## Source records

```sh
python scripts/evidence_tools.py init-project --directory PROJECT
python scripts/evidence_tools.py bibliography --input PROJECT/references-input.json --output PROJECT/references-normalized.json
python scripts/evidence_tools.py search --query "evidence synthesis reporting" --limit 5 --output PROJECT/search.json
python scripts/evidence_tools.py lookup-doi --doi 10.1371/journal.pcbi.1003149 --output PROJECT/doi.json
```

Bibliography input is a list, for example `[{"doi":"https://doi.org/10.1371/journal.pcbi.1003149","title":"Supplied title"}]`. Original records and identifier/version variants remain available after deduplication. Conflicting metadata fails for review rather than silently overwriting it. Search and lookup are the only network commands: public query/DOI goes to Crossref, results are metadata, and transport failure is not scholarly absence. Full-text claim verification still requires reading.

## Local molecular utilities

```sh
python scripts/research_tools.py fasta --input PROJECT/sequences.fasta --output PROJECT/sequence-check.json
python scripts/research_tools.py rdkit-descriptors --smiles CCO --output PROJECT/ethanol.json
python scripts/research_tools.py rdkit-conformer --smiles CCO --seed 481516 --sdf PROJECT/ethanol.sdf --output PROJECT/geometry.json
python scripts/research_tools.py openmm-smoke --output PROJECT/energy-check.json
```

FASTA inspection reports identity, lengths and nonstandard symbols; it is not a chemistry or folding validation. Descriptors include molecular weight, exact mass, logP, heavy atoms, donors, acceptors and formal charge. Generated coordinates use ETKDGv3/MMFF with seed and convergence status; a nonconverged optimization exits unsuccessfully and remains visible. The OpenMM command uses two artificial particles on Reference with analytic expected energy 0.5 kJ/mol. It is an installation/unit test, not a biological MD study.

Descriptor and energy commands also write a context-labelled `.measurements.csv` beside the JSON report, with its SHA-256. Conformer reports link the SDF hash. Neither output demonstrates biological function, measured binding or a unique physical conformation.

## Integrity manifest

`verify-evidence` takes this shape; use an actual artifact hash and exact CSV data, not the placeholder below:

```json
{
  "artifacts": [{"id":"a1","path":"ethanol.measurements.csv","sha256":"ACTUAL_64_HEX_DIGEST"}],
  "measurements": [{"id":"m1","artifact_id":"a1","row":1,"run":"rdkit-descriptors","condition":"CCO","dataset":"explicit_local_input","metric":"MolWt","unit":"g/mol","seed":"not_applicable","statistic":"single_deterministic_calculation","value":"46.069"}],
  "claims": [{"id":"c1","evidence_id":"m1","run":"rdkit-descriptors","condition":"CCO","dataset":"explicit_local_input","metric":"MolWt","unit":"g/mol","seed":"not_applicable","statistic":"single_deterministic_calculation","value":"46.069"}],
  "sources": [],
  "source_claims": []
}
```

```sh
python scripts/evidence_tools.py verify-evidence --input PROJECT/evidence.json --output PROJECT/integrity.json
```

Use the actual CSV row: rows start at 1 after its header, and all context fields must agree. Exact comparison deliberately performs no hidden rounding, unit conversion or tolerance matching; explicitly document derived/rounded quantities separately. A claim citing a different run or unit fails even if its number appears elsewhere. Empty manifests are not checked. Source access declarations cannot turn metadata into full text; recorded access and locators remain assertions needing inspection. A passing integrity report checks traceability and declared consistency, not source entailment, experimental truth or scientific usefulness.

### Verified backup transport

Use `scripts/backup_tools.py` only for an explicitly selected authorized SSH backup destination. Its separate `init-remote`, `prepare`, `push`, `verify` and `fetch` operations preserve uncertain outcomes and immutable identity. See [the full contract](off-device-backups.md). It transfers a consistent whole SQLite store with an explicit 1–64 MiB cap; it does not execute saved application notes.

### Streaming and profile migration

Use `scripts/stream_backup_tools.py` for optional binary whole-store backups and explicit `migrate-profile` verification through changed client connection settings. Select transfer limits and preserve immutable destination/data pins. See [the contract](streaming-backups.md). The legacy JSON route remains available.
