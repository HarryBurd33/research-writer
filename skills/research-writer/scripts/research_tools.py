#!/usr/bin/env python3
"""Original MIT research utilities. Optional engines are planned, never auto-launched."""
import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT = 10 * 1024 * 1024
CONTEXT = ['run', 'condition', 'dataset', 'metric', 'unit', 'seed', 'statistic', 'value']


def read_bytes(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_INPUT:
        raise ValueError('Input must be a regular file no larger than 10 MiB')
    return p.read_bytes()


def read_json(path):
    return json.loads(read_bytes(path).decode('utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value, force=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with p.open('w' if force else 'x', encoding='utf-8') as f:
        f.write(text)


def profile(path):
    p = {'schema_version': 1, 'mode': 'local', 'python': None,
         'remote_host': None, 'accelerator': 'unknown',
         'executables': {}, 'model_dirs': {}, 'notes': ''}
    if path:
        given = read_json(path)
        if not isinstance(given, dict) or set(given) - set(p):
            raise ValueError('Profile contains unknown fields; store no credentials or readiness claims')
        p.update(given)
    if p['schema_version'] != 1 or p['mode'] not in ('local', 'remote'):
        raise ValueError('Unsupported profile schema or mode')
    if p['accelerator'] not in ('auto', 'unknown', 'cpu', 'cuda', 'mps', 'rocm'):
        raise ValueError('Unsupported accelerator declaration')
    for key in ('executables', 'model_dirs'):
        if not isinstance(p[key], dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in p[key].items()):
            raise ValueError(key + ' must map engine IDs to nonempty paths')
    for key in ('python', 'remote_host'):
        if p[key] is not None and (not isinstance(p[key], str) or not p[key]):
            raise ValueError(key + ' must be a path/host string or null')
    return p


def catalog():
    c = read_json(ROOT / 'references' / 'tool-catalog.json')
    return c['engines']


def version(distribution):
    try:
        return importlib.metadata.version(distribution) if distribution else None
    except importlib.metadata.PackageNotFoundError:
        return None


def executable(path):
    if not path:
        return None
    found = shutil.which(path)
    if found:
        return found
    p = Path(path).expanduser()
    return str(p.resolve()) if p.is_file() else None


def doctor(args):
    p = profile(args.profile)
    remote = p['mode'] == 'remote'
    alternate = bool(p['python'] and Path(p['python']).expanduser().resolve() != Path(sys.executable).resolve())
    engines = []
    for e in catalog():
        v = version(e.get('distribution'))
        cli = executable(p['executables'].get(e['id']) or e.get('cli_name'))
        model = p['model_dirs'].get(e['id'])
        engines.append({'id': e['id'], 'status': 'remote_unprobed' if remote else 'dependency_present_unvalidated' if v or cli else 'not_detected',
                        'local_distribution_version': v, 'local_executable': cli,
                        'declared_model_directory': model,
                        'local_model_directory_exists': bool(model and Path(model).expanduser().is_dir()) if not remote else None,
                        'weights_verified': False, 'license_acceptance_verified': False,
                        'execution_tested': False})
    gpu = {'status': 'not_probed', 'source': None, 'devices': None}
    if args.probe_gpu and not remote:
        binary = shutil.which('nvidia-smi')
        if binary:
            try:
                result = subprocess.run([binary, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'],
                                        capture_output=True, text=True, timeout=3, check=False)
                gpu = {'status': 'observed' if result.returncode == 0 else 'probe_failed',
                       'source': 'local nvidia-smi', 'devices': result.stdout.strip() if result.returncode == 0 else None,
                       'returncode': result.returncode}
            except (OSError, subprocess.TimeoutExpired) as err:
                gpu = {'status': 'probe_failed', 'source': 'local nvidia-smi', 'devices': None, 'error': type(err).__name__}
        else:
            gpu = {'status': 'not_detected', 'source': 'local PATH nvidia-smi lookup', 'devices': None}
    return {'status': 'inventory_only', 'observed_at': datetime.now(timezone.utc).isoformat(),
            'probe_scope': 'current local Python interpreter and PATH; remote never contacted',
            'python': sys.executable, 'python_version': platform.python_version(),
            'os': platform.system(), 'machine': platform.machine(), 'profile': p,
            'profile_python_differs': alternate, 'gpu': gpu, 'engines': engines,
            'limits': ['Configured is not executed or scientifically validated.',
                       'MPS/ROCm/model VRAM adequacy are not established by this inventory.',
                       'Use the profile interpreter on its device to inspect that environment.',
                       'fair-esm and Biohub esm share a namespace: use separate environments.']}


def plan(args):
    p = profile(args.profile)
    e = next((x for x in catalog() if x['id'] == args.tool), None)
    if e is None:
        raise ValueError('Unknown engine ID; use doctor/catalog')
    data = read_bytes(args.input)
    replacements = {'input': str(Path(args.input).resolve()),
                    'output': '<SELECTED_RESULT_DIRECTORY>',
                    'python': p.get('python') or '<DEVICE_PYTHON>',
                    'executable': p['executables'].get(args.tool) or '<CONFIGURED_EXECUTABLE_OR_SCRIPT>',
                    'model_dir': p['model_dirs'].get(args.tool) or '<PROVISIONED_MODEL_DIRECTORY>',
                    'db_dir': '<PROVISIONED_DATABASE_DIRECTORY>'}
    argv = e.get('example_argv')
    if argv:
        for key, value in replacements.items():
            argv = [part.replace('{' + key + '}', value) for part in argv]
    return {'schema_version': 1, 'status': 'planned_not_executed', 'tool': e['id'],
            'repository': e['repository'], 'audited_revision': e['revision'], 'device_profile': p,
            'input': {'path': str(Path(args.input).resolve()), 'sha256': digest(data)},
            'upstream_example_argv': argv, 'argv_is_execution_ready': False,
            'input_schema_validated_by_engine': False, 'remote_contacted': False,
            'code_license': e['code_license'], 'weights_terms': e['weights_terms'],
            'data_service_terms': e['data_service_terms'],
            'required_checks': e['prerequisites'] + [
                'Inspect selected release/runtime and exact input schema on the target device.',
                'Verify model/data terms, checksums, storage/RAM/VRAM and run-time/spending limits.',
                'Provision inputs/models locally; inspect startup download and external-MSA behavior.',
                'Replace placeholders, choose working/result directories, then run a small authorized acceptance test.',
                'Record real command, versions, inputs, all failures, stdout/stderr and outputs before reporting execution.'],
            'scientific_limits': e['limitations']}


def provenance(tool, versions, inputs, settings):
    return {'tool': tool, 'versions': versions, 'python': platform.python_version(),
            'platform': platform.system() + '/' + platform.machine(), 'inputs': inputs,
            'settings': settings, 'executed': True, 'experimental_validation': False}


def rdkit_base(args):
    from rdkit import Chem, rdBase
    if not args.smiles or len(args.smiles) > 4096:
        raise ValueError('SMILES must contain 1..4096 characters')
    mol = Chem.MolFromSmiles(args.smiles)
    if mol is None or mol.GetNumAtoms() == 0 or mol.GetNumAtoms() > 256:
        raise ValueError('Invalid, empty, or oversized SMILES (maximum 256 heavy atoms)')
    canonical = Chem.MolToSmiles(mol, isomericSmiles=True)
    return Chem, rdBase, mol, canonical


def descriptors(args):
    from rdkit.Chem import Descriptors, rdMolDescriptors
    Chem, rdBase, mol, canonical = rdkit_base(args)
    values = {'MolWt': Descriptors.MolWt(mol), 'ExactMolWt': Descriptors.ExactMolWt(mol),
              'MolLogP': Descriptors.MolLogP(mol), 'HeavyAtomCount': mol.GetNumHeavyAtoms(),
              'NumHDonors': Descriptors.NumHDonors(mol), 'NumHAcceptors': Descriptors.NumHAcceptors(mol),
              'FormalCharge': Chem.GetFormalCharge(mol)}
    if not all(math.isfinite(x) for x in values.values()):
        raise ValueError('A descriptor was nonfinite')
    return {'status': 'computed', 'input_smiles': args.smiles, 'canonical_smiles': canonical,
            'formula': rdMolDescriptors.CalcMolFormula(mol), 'fragments': len(Chem.GetMolFrags(mol)),
            'descriptors': values, 'units': {'MolWt': 'g/mol', 'ExactMolWt': 'Da', 'MolLogP': 'dimensionless', 'FormalCharge': 'elementary_charge'},
            'interpretation': 'Calculated molecular properties; not measured potency, safety, solubility or activity.',
            'provenance': provenance('RDKit', {'rdkit': rdBase.rdkitVersion},
                                     {'smiles_sha256': digest(args.smiles.encode())}, {'descriptor_set': list(values)})}


def conformer(args):
    from rdkit.Chem import AllChem
    Chem, rdBase, mol, canonical = rdkit_base(args)
    if mol.GetNumAtoms() > 128 or len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError('Conformer route requires one connected molecule with <=128 heavy atoms')
    if not 0 <= args.seed < 2147483647 or not 1 <= args.max_iters <= 2000:
        raise ValueError('Seed or optimization iteration limit out of range')
    out = Path(args.sdf)
    if out.exists() and not args.force:
        raise FileExistsError('SDF exists; choose another output or explicitly use --force')
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = args.seed
    cid = AllChem.EmbedMolecule(mol, params)
    if cid < 0:
        raise ValueError('RDKit embedding failed; no conformer result')
    if not AllChem.MMFFHasAllMoleculeParams(mol):
        raise ValueError('MMFF parameters unavailable; no silent force-field substitution')
    optimizer = AllChem.MMFFOptimizeMolecule(mol, maxIters=args.max_iters)
    if optimizer < 0:
        raise ValueError('MMFF setup failed')
    mol.SetProp('_Name', 'RDKit generated geometry; not an experimental structure')
    block = (Chem.MolToMolBlock(mol, confId=cid) + '\n$$$$\n').encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('wb' if args.force else 'xb') as f:
        f.write(block)
    return {'status': 'computed' if optimizer == 0 else 'not_converged', 'canonical_smiles': canonical,
            'atom_count_with_hydrogens': mol.GetNumAtoms(), 'embedding_id': cid,
            'optimizer_status': optimizer, 'converged': optimizer == 0,
            'artifact': {'path': str(out.resolve()), 'sha256': digest(block)},
            'interpretation': 'One seeded, locally optimized model geometry; not a measured bound pose or unique physical conformation.',
            'provenance': provenance('RDKit', {'rdkit': rdBase.rdkitVersion},
                                     {'smiles_sha256': digest(args.smiles.encode())},
                                     {'seed': args.seed, 'embedding': 'ETKDGv3', 'force_field': 'MMFF', 'max_iters': args.max_iters})}


def openmm_smoke(args):
    import openmm
    from openmm import unit
    system = openmm.System()
    system.addParticle(12 * unit.dalton)
    system.addParticle(12 * unit.dalton)
    force = openmm.HarmonicBondForce()
    force.addBond(0, 1, 0.1 * unit.nanometer, 100 * unit.kilojoule_per_mole / unit.nanometer**2)
    system.addForce(force)
    integrator = openmm.VerletIntegrator(0.001 * unit.picosecond)
    context = openmm.Context(system, integrator, openmm.Platform.getPlatformByName('Reference'))
    context.setPositions([openmm.Vec3(0, 0, 0), openmm.Vec3(0.2, 0, 0)] * unit.nanometer)
    value = context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    observed = context.getPlatform().getName()
    if not math.isfinite(value) or not math.isclose(value, 0.5, rel_tol=0, abs_tol=1e-8) or observed != 'Reference':
        raise ValueError('Analytic energy or Reference platform acceptance failed')
    return {'status': 'computed', 'kind': 'artificial_two_particle_energy_check', 'energy': value,
            'unit': 'kJ/mol', 'expected': 0.5, 'error': value - 0.5, 'platform': observed,
            'interpretation': 'Installation/unit smoke test only; no biological simulation or validation performed.',
            'provenance': provenance('OpenMM', {'openmm': openmm.__version__}, {},
                                     {'r0_nm': 0.1, 'r_nm': 0.2, 'k_kJ_mol_nm2': 100, 'particles': 2})}


def fasta(args):
    raw = read_bytes(args.input)
    records, current, seq, seen = [], None, [], set()
    def append():
        if current is None:
            return
        sequence = ''.join(seq).upper()
        if not sequence or len(sequence) > 1000000 or any(not (c.isascii() and (c.isalpha() or c in '*-.')) for c in sequence):
            raise ValueError('Invalid or oversized FASTA sequence')
        nonstandard = [{'position_1based': i + 1, 'symbol': c} for i, c in enumerate(sequence) if c not in 'ACDEFGHIKLMNPQRSTVWY']
        records.append({'id': current, 'length': len(sequence), 'sequence_sha256': digest(sequence.encode()),
                        'nonstandard_count': len(nonstandard), 'first_nonstandard_positions': nonstandard[:100],
                        'canonical_sequence_only': not nonstandard})
    for line in raw.decode('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('>'):
            append()
            current = line[1:].strip()
            if not current or current in seen:
                raise ValueError('Missing or duplicate FASTA identifier')
            seen.add(current)
            seq = []
        else:
            if current is None:
                raise ValueError('FASTA sequence before header')
            seq.append(''.join(line.split()))
    append()
    if not records:
        raise ValueError('No FASTA records')
    return {'status': 'inspected', 'input_sha256': digest(raw), 'records': records,
            'interpretation': 'Syntax/identity check only. Residue symbols, including U/O/X, do not establish model support for chemical modifications or cofactors.'}


def measurements(args, result):
    if args.command == 'rdkit-descriptors':
        metrics = result['descriptors']
        units = result['units']
        condition, seed = result['canonical_smiles'], 'not_applicable'
    elif args.command == 'openmm-smoke':
        metrics, units = {'potential_energy': result['energy']}, {'potential_energy': result['unit']}
        condition, seed = 'two_particle_harmonic_reference', 'not_applicable'
    else:
        return
    output = Path(args.output).with_suffix('.measurements.csv')
    if output.resolve() == Path(args.output).resolve():
        raise ValueError('JSON output must not end in .measurements.csv')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=CONTEXT, lineterminator='\n')
    writer.writeheader()
    for name, value in metrics.items():
        writer.writerow({'run': args.run_id or args.command, 'condition': condition, 'dataset': 'explicit_local_input',
                         'metric': name, 'unit': units.get(name, 'count' if isinstance(value, int) else 'dimensionless'),
                         'seed': seed, 'statistic': 'single_deterministic_calculation', 'value': value})
    data = stream.getvalue().encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb' if args.force else 'xb') as f:
        f.write(data)
    result['measurement_artifact'] = {'path': str(output.resolve()), 'sha256': digest(data), 'columns': CONTEXT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'profile', 'plan', 'rdkit-descriptors', 'rdkit-conformer', 'openmm-smoke', 'fasta'):
        sub = subs.add_parser(name)
        sub.add_argument('--output', required=True, help='New JSON report; existing files preserved unless --force')
        sub.add_argument('--force', action='store_true')
        if name in ('doctor', 'plan'):
            sub.add_argument('--profile')
        if name == 'doctor':
            sub.add_argument('--probe-gpu', action='store_true')
        if name in ('plan', 'fasta'):
            sub.add_argument('--input', required=True)
        if name == 'plan':
            sub.add_argument('--tool', required=True)
        if name.startswith('rdkit-'):
            sub.add_argument('--smiles', required=True)
        if name == 'rdkit-conformer':
            sub.add_argument('--sdf', required=True)
            sub.add_argument('--seed', type=int, required=True)
            sub.add_argument('--max-iters', type=int, default=200)
        if name in ('rdkit-descriptors', 'openmm-smoke'):
            sub.add_argument('--run-id')
    args = parser.parse_args()
    try:
        outputs = [Path(args.output)]
        if args.command == 'rdkit-conformer':
            outputs.append(Path(args.sdf))
        if args.command in ('rdkit-descriptors', 'openmm-smoke'):
            outputs.append(Path(args.output).with_suffix('.measurements.csv'))
        if len({p.resolve() for p in outputs}) != len(outputs):
            raise ValueError('Report, SDF and measurement output paths must be distinct')
        if any(p.exists() for p in outputs) and not args.force:
            raise FileExistsError('An output exists; choose new paths or explicitly use --force')
        if args.command == 'profile':
            result = profile(None)
        else:
            function = {'doctor': doctor, 'plan': plan, 'rdkit-descriptors': descriptors,
                        'rdkit-conformer': conformer, 'openmm-smoke': openmm_smoke, 'fasta': fasta}[args.command]
            result = function(args)
            measurements(args, result)
        write_json(args.output, result, args.force)
        print(json.dumps({'status': result.get('status', 'profile_created'), 'output': args.output}, allow_nan=False))
        return 2 if result.get('status') == 'not_converged' else 0
    except (ValueError, TypeError, KeyError, OSError, ImportError, RuntimeError) as err:
        failure = {'status': 'unavailable' if isinstance(err, ImportError) else 'failed',
                   'error': str(err), 'error_type': type(err).__name__, 'executed_successfully': False}
        if not Path(args.output).exists():
            try:
                write_json(args.output, failure)
            except OSError:
                pass
        print(json.dumps(failure), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
