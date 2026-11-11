#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional, explicit local AutoDock Vina execution; no asset downloader.

Input is a versioned JSON specification. Only prepared, mapped PDBQT ligands and
standard protein receptors are supported. Scores are predictions, not affinity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import time

MAX_INPUT = 16 * 1024**2
ATOM_TYPES = {'C':'C','A':'C','N':'N','NA':'N','O':'O','OA':'O','S':'S','SA':'S',
              'P':'P','F':'F','Cl':'Cl','Br':'Br','I':'I','H':'H','HD':'H'}
RESIDUES = set('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL HID HIE HIP CYX'.split())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON field: ' + key)
        result[key] = value
    return result


def read_file(path, maximum=MAX_INPUT):
    path = Path(path).expanduser()
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Input must be a regular, non-symlink file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('File exceeds explicit byte limit')
    return raw


def load_spec(path):
    return json.loads(read_file(path, 65536), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def number(value, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected finite numeric setting')
    if integer and not isinstance(value, int):
        raise ValueError('Expected integer setting')
    if not low <= value <= high:
        raise ValueError('Setting outside supported bounds')
    return value


def artifact(record):
    if not isinstance(record, dict) or set(record) != {'path','sha256'}:
        raise ValueError('Artifact requires exactly path and sha256')
    if not isinstance(record['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', record['sha256']):
        raise ValueError('Explicit SHA256 required')
    raw = read_file(record['path'])
    if digest(raw) != record['sha256']:
        raise ValueError('Input artifact hash mismatch')
    return raw


def parse_atoms(text, receptor=False):
    atoms = {}
    for line in text.splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        try:
            serial = int(line[6:11]); xyz = [float(line[i:i+8]) for i in (30,38,46)]
            atom_type = line[77:].strip(); charge = float(line[70:76])
        except (ValueError, IndexError) as exc:
            raise ValueError('Malformed PDBQT atom') from exc
        if serial in atoms or serial <= 0 or atom_type not in ATOM_TYPES:
            raise ValueError('Duplicate atom identity or unsupported atom type')
        if not all(math.isfinite(x) and abs(x) < 1e5 for x in xyz) or not math.isfinite(charge):
            raise ValueError('Nonfinite/unbounded molecular coordinate or charge')
        if receptor and line[17:20].strip() not in RESIDUES:
            raise ValueError('Only explicitly supported standard protein receptor residues are accepted')
        atoms[serial] = {'xyz':xyz, 'type':atom_type, 'element':ATOM_TYPES[atom_type], 'charge':charge}
    if not atoms or len(atoms) > (100000 if receptor else 256):
        raise ValueError('Empty or oversized molecule')
    return atoms


def ligand(raw):
    from rdkit import Chem
    text = raw.decode('utf-8'); atoms = parse_atoms(text)
    smiles = [line[len('REMARK SMILES '):] for line in text.splitlines()
              if line.startswith('REMARK SMILES ') and not line.startswith('REMARK SMILES IDX ')]
    if len(smiles) != 1:
        raise ValueError('One explicit ligand SMILES and complete atom map are required')
    mol = Chem.MolFromSmiles(smiles[0])
    if mol is None or len(Chem.GetMolFrags(mol)) != 1 or mol.GetNumHeavyAtoms() > 128:
        raise ValueError('Invalid, disconnected or oversized ligand graph')
    if any(a.GetIsotope() or a.GetSymbol() not in set(ATOM_TYPES.values()) for a in mol.GetAtoms()):
        raise ValueError('Unsupported isotope or ligand element')
    mapping = {}
    for line in text.splitlines():
        if line.startswith('REMARK SMILES IDX '):
            values = [int(x) for x in line.split()[3:]]
            if len(values) % 2:
                raise ValueError('Incomplete ligand atom mapping')
            for index, serial in zip(values[::2], values[1::2]):
                if index in mapping or serial in mapping.values():
                    raise ValueError('Duplicate ligand atom mapping')
                mapping[index] = serial
    heavy = {serial for serial,a in atoms.items() if a['element'] != 'H'}
    if set(mapping) != set(range(1,mol.GetNumAtoms()+1)) or set(mapping.values()) != heavy:
        raise ValueError('Atom mapping does not cover the complete heavy-atom graph')
    for index,serial in mapping.items():
        if mol.GetAtomWithIdx(index-1).GetSymbol() != atoms[serial]['element']:
            raise ValueError('Mapped element mismatch')
    for bond in mol.GetBonds():
        a = atoms[mapping[bond.GetBeginAtomIdx()+1]]['xyz']
        b = atoms[mapping[bond.GetEndAtomIdx()+1]]['xyz']
        if not 0.65 <= math.dist(a,b) <= 2.5:
            raise ValueError('Mapped covalent bond has implausible length')
    return {'smiles':smiles[0], 'canonical':Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True),
            'formal_charge':Chem.GetFormalCharge(mol), 'mapping':mapping, 'atoms':atoms}


def validate(spec):
    required = {'schema_version','engine','receptor','ligand','center','size','seed','cpu',
                'exhaustiveness','num_modes','timeout_seconds','max_output_bytes'}
    if not isinstance(spec, dict) or set(spec) not in (required, required|{'reference'}):
        raise ValueError('Unsupported docking specification fields')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('Unsupported docking specification version')
    engine = spec['engine']
    if not isinstance(engine, dict) or set(engine) != {'path','sha256','version'} or engine['version'] != '1.2.7':
        raise ValueError('This route requires explicitly pinned AutoDock Vina1.2.7')
    binary = read_file(engine['path'], 64*1024**2)
    if digest(binary) != engine['sha256'] or not os.access(engine['path'], os.X_OK):
        raise ValueError('Engine digest/executable check failed')
    receptor = artifact(spec['receptor']); parse_atoms(receptor.decode('utf-8'), receptor=True)
    ligand_raw = artifact(spec['ligand']); identity = ligand(ligand_raw)
    for field,low,high in [('center',-10000,10000),('size',1,126)]:
        if not isinstance(spec[field], list) or len(spec[field]) != 3:
            raise ValueError('Binding box requires three coordinates and dimensions')
        for value in spec[field]: number(value,low,high)
    for field,low,high in [('seed',0,2147483647),('cpu',1,16),('exhaustiveness',1,64),
                            ('num_modes',1,20),('timeout_seconds',1,3600),('max_output_bytes',1024,64*1024**2)]:
        number(spec[field],low,high,True)
    reference = None
    if 'reference' in spec:
        ref = spec['reference']
        if not isinstance(ref,dict) or set(ref) != {'path','sha256','maximum_rmsd_angstrom'}:
            raise ValueError('Reference needs path/hash and a frozen RMSD threshold')
        number(ref['maximum_rmsd_angstrom'],0.01,20)
        reference = ligand(artifact({k:ref[k] for k in ('path','sha256')}))
        if reference['smiles'] != identity['smiles'] or reference['canonical'] != identity['canonical']:
            raise ValueError('Fixed-map reference requires the same explicit SMILES atom order')
    return receptor,ligand_raw,identity,reference


def identity_signature(item):
    return (item['smiles'],item['canonical'],item['formal_charge'],item['mapping'],
            {k:(a['type'],a['charge']) for k,a in item['atoms'].items()})


def poses(raw, original, spec, reference=None):
    text = raw.decode('utf-8'); blocks=[]; current=None; expected=1
    for line in text.splitlines():
        if line.startswith('MODEL '):
            if current is not None or int(line.split()[1]) != expected:
                raise ValueError('Malformed or unordered pose models')
            current=[]
        elif line == 'ENDMDL':
            if current is None: raise ValueError('Unmatched pose terminator')
            blocks.append('\n'.join(current)+'\n');current=None;expected+=1
        elif current is not None: current.append(line)
        elif line.strip(): raise ValueError('Unexpected content outside pose models')
    if current is not None or not 1 <= len(blocks) <= spec['num_modes']:
        raise ValueError('Truncated, empty or excessive pose count')
    result=[]
    for block in blocks:
        item=ligand(block.encode())
        if identity_signature(item) != identity_signature(original):
            raise ValueError('Output ligand atom/type/charge/graph mapping changed')
        scores=[line.split()[3:] for line in block.splitlines() if line.startswith('REMARK VINA RESULT:')]
        if len(scores)!=1 or len(scores[0])!=3:
            raise ValueError('Exactly one complete Vina score record per pose required')
        values=[float(x) for x in scores[0]]
        if not all(math.isfinite(x) for x in values) or values[1]<0 or values[2]<values[1]:
            raise ValueError('Invalid score or intermode distances')
        coords=[item['atoms'][serial]['xyz'] for serial in item['mapping'].values()]
        centroid=[sum(c[j] for c in coords)/len(coords) for j in range(3)]
        if any(abs(centroid[j]-spec['center'][j])>spec['size'][j]/2 for j in range(3)):
            raise ValueError('Ligand centroid outside declared search box')
        entry={'mode':len(result)+1,'score_kcal_per_mol':values[0],
               'vina_intermode_rmsd_lower':values[1],'vina_intermode_rmsd_upper':values[2],
               'heavy_atoms':len(coords),'centroid_angstrom':centroid}
        if reference is not None:
            distances=[math.dist(item['atoms'][serial]['xyz'],reference['atoms'][reference['mapping'][idx]]['xyz'])**2
                       for idx,serial in item['mapping'].items()]
            entry['reference_rmsd_angstrom']=math.sqrt(sum(distances)/len(distances))
        result.append(entry)
    return result


def bounded_probe(argv, directory, timeout, maximum=65536):
    """Bound version-probe logs while running, preserving them on refusal."""
    stdout,stderr=directory/'version.stdout.log',directory/'version.stderr.log'
    process=None;started=time.monotonic()
    try:
        with stdout.open('xb') as out,stderr.open('xb') as err:
            process=subprocess.Popen(argv,cwd=directory,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                     shell=False,start_new_session=os.name=='posix')
            while process.poll() is None:
                if time.monotonic()-started>timeout:raise TimeoutError('Version probe deadline exceeded')
                if stdout.stat().st_size>maximum or stderr.stat().st_size>maximum:
                    raise ValueError('Version probe output limit exceeded')
                time.sleep(0.02)
        return process.returncode,read_file(stdout,maximum)+read_file(stderr,maximum)
    finally:
        if process is not None and process.poll() is None:
            if os.name=='posix':
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            else:process.kill()
            process.wait(timeout=10)


def execute(spec_path, output):
    output=Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('Choose a new output directory under an existing parent')
    output.mkdir(mode=0o700)
    report={'schema_version':1,'status':'failed','passed':False,'scientific_validity':'not_established',
            'network':'No download/upload requested; process networking is not sandboxed',
            'runtime':{'python':platform.python_version(),'platform':platform.platform()},
            'limits':['Prepared standard-protein receptor and mapped ligand only; no chemistry preparation.',
                      'Scores are predictions, not measured binding affinity.',
                      'PDBQT graph declarations/atom mappings and geometry are checked; no electronic validation.',
                      'Trusted local binary; polling bounds can overshoot and are not OS resource isolation.']}
    process=None;started=time.monotonic()
    try:
        spec=load_spec(spec_path); receptor,ligand_raw,identity,reference=validate(spec)
        report.update(spec_sha256=digest(read_file(spec_path,65536)),settings=spec,
                      identity={'canonical_smiles':identity['canonical'],'formal_charge':identity['formal_charge']})
        (output/'receptor.pdbqt').write_bytes(receptor);(output/'ligand.pdbqt').write_bytes(ligand_raw)
        binary=str(Path(spec['engine']['path']).expanduser().resolve())
        probe_code,probe_text=bounded_probe([binary,'--version'],output,min(10,spec['timeout_seconds']))
        if probe_code or b'AutoDock Vina v1.2.7' not in probe_text:
            raise ValueError('Pinned Vina version probe failed')
        argv=[binary,'--receptor','receptor.pdbqt','--ligand','ligand.pdbqt','--out','poses.pdbqt',
              '--seed',str(spec['seed']),'--cpu',str(spec['cpu']),'--exhaustiveness',str(spec['exhaustiveness']),
              '--num_modes',str(spec['num_modes'])]
        for label in ('center','size'):
            for axis,value in zip('xyz',spec[label]):argv.extend(['--'+label+'_'+axis,str(value)])
        report['argv']=argv
        with (output/'stdout.log').open('xb') as out,(output/'stderr.log').open('xb') as err:
            process=subprocess.Popen(argv,cwd=output,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                     shell=False,start_new_session=os.name=='posix')
            deadline=time.monotonic()+spec['timeout_seconds']
            while process.poll() is None:
                if time.monotonic()>deadline:raise TimeoutError('Docking engine deadline exceeded')
                if any(p.is_file() and p.stat().st_size>spec['max_output_bytes'] for p in output.iterdir()
                       if p.name not in ('receptor.pdbqt','ligand.pdbqt')):raise ValueError('Engine output/log limit exceeded')
                time.sleep(0.05)
        report['returncode']=process.returncode
        if process.returncode:raise ValueError('Nonzero docking engine exit')
        for name in ('stdout.log','stderr.log'):read_file(output/name,spec['max_output_bytes'])
        raw=read_file(output/'poses.pdbqt',spec['max_output_bytes']);result=poses(raw,identity,spec,reference)
        report.update(status='docked_output_checked',passed=True,poses=result,output_sha256=digest(raw),
                      backend='local_cpu',version_probe=probe_text.decode(errors='replace').strip())
        if reference:
            report['benchmark']={'metric':'heavy_atom_fixed_SMILES_index_RMSD_without_alignment_or_symmetry_minimization',
                                 'reference_sha256':spec['reference']['sha256'],
                                 'threshold_angstrom':spec['reference']['maximum_rmsd_angstrom'],
                                 'first_ranked_pose_passed':result[0]['reference_rmsd_angstrom']<=spec['reference']['maximum_rmsd_angstrom']}
    except (OSError,ValueError,KeyError,TypeError,ImportError,TimeoutError,subprocess.SubprocessError) as exc:
        report.update(error=str(exc),error_type=type(exc).__name__)
    finally:
        if process is not None and process.poll() is None:
            if os.name=='posix':
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            else:process.kill()
            process.wait(timeout=10)
        report['elapsed_seconds']=time.monotonic()-started
        report['partial_artifacts_retained']=not report['passed']
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    try:
        result=execute(args.spec,args.output_dir)
        print(json.dumps({'status':result['status'],'report':str(Path(args.output_dir)/'report.json')}))
        return 0 if result['passed'] else 2
    except (OSError,ValueError) as exc:
        print(json.dumps({'status':'refused','error':str(exc)}));return 2


if __name__=='__main__':
    raise SystemExit(main())
