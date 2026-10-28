#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded Open Babel conversion with independent RDKit identity validation.

Only explicit local conversion executes an engine. No downloads or network.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

MAX_BYTES = 10 * 1024 * 1024
MAX_MOLECULES = 32
FORMATS = ('smi', 'sdf')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded_read(path, maximum=MAX_BYTES):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('File exceeds byte limit')
    return raw


def identities(raw, format_name):
    """Independently parse every input/output molecule; no Open Babel API used."""
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    if format_name not in FORMATS:
        raise ValueError('Only explicit smi or sdf formats are supported')
    if len(raw) > MAX_BYTES or not raw.strip():
        raise ValueError('Empty or oversized molecular input')
    if format_name == 'smi':
        lines = [line.strip() for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
        if not 1 <= len(lines) <= MAX_MOLECULES:
            raise ValueError('Expected 1–32 molecules')
        molecules = [Chem.MolFromSmiles(line.split()[0]) for line in lines]
    else:
        text = raw.decode('utf-8-sig')
        blocks = text.split('$$$$')
        if blocks[-1].strip() or not 1 <= len(blocks) - 1 <= MAX_MOLECULES:
            raise ValueError('SDF requires 1–32 terminated molecule records')
        molecules = list(Chem.ForwardSDMolSupplier(io.BytesIO(raw), removeHs=False, strictParsing=True))
        if len(molecules) != len(blocks) - 1:
            raise ValueError('SDF record count differs from parsed molecules')
    result = []
    for index, mol in enumerate(molecules, 1):
        if mol is None or mol.GetNumAtoms() == 0:
            raise ValueError('Invalid molecule at position ' + str(index))
        Chem.SanitizeMol(mol)
        mol = Chem.RemoveHs(mol)
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        result.append({'position': index,
                       'canonical_isomeric_smiles': Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True),
                       'formula': rdMolDescriptors.CalcMolFormula(mol),
                       'formal_charge': Chem.GetFormalCharge(mol),
                       'heavy_atom_count': mol.GetNumHeavyAtoms(),
                       'bond_types': sorted(str(b.GetBondType()) for b in mol.GetBonds())})
    return result


def bounded_process(argv, directory, timeout, watched=()):
    """No shell; bound elapsed time and staged output/log file sizes."""
    directory = Path(directory)
    stdout, stderr = directory / 'stdout.log', directory / 'stderr.log'
    with stdout.open('wb') as out, stderr.open('wb') as err:
        process = subprocess.Popen(argv, cwd=directory, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   shell=False)
        start = time.monotonic()
        failure = None
        try:
            while process.poll() is None:
                if time.monotonic() - start > timeout:
                    failure = 'Engine timeout'
                elif any(p.exists() and p.stat().st_size > MAX_BYTES for p in [stdout, stderr, *map(Path, watched)]):
                    failure = 'Engine output exceeds byte limit'
                if failure:
                    process.kill()
                    break
                time.sleep(0.02)
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)
    logs = {'stdout': bounded_read(stdout).decode('utf-8', errors='replace'),
            'stderr': bounded_read(stderr).decode('utf-8', errors='replace')}
    if failure:
        return {'returncode': process.returncode, 'elapsed_seconds': time.monotonic() - start,
                'error': failure, **logs}
    return {'returncode': process.returncode, 'elapsed_seconds': time.monotonic() - start, **logs}


def convert(args):
    if isinstance(args.timeout, bool) or not 0 < args.timeout <= 120:
        raise ValueError('Timeout must be greater than zero and at most 120 seconds')
    if args.input_format not in FORMATS or args.output_format not in FORMATS:
        raise ValueError('Only smi and sdf are supported')
    source, destination, report_path = map(lambda p: Path(p).expanduser().resolve(),
                                         (args.input, args.output, args.report))
    if len({source, destination, report_path}) != 3:
        raise ValueError('Input, molecular output and report must be distinct')
    if not args.force and (destination.exists() or report_path.exists()):
        raise FileExistsError('An output exists; preserve it or explicitly use --force')
    if not destination.parent.is_dir() or not report_path.parent.is_dir():
        raise ValueError('Output/report parent directories must exist')
    raw = bounded_read(source)
    before = identities(raw, args.input_format)
    supplied = os.fspath(args.executable)
    resolved = shutil.which(supplied) or (str(Path(supplied).expanduser().resolve()) if Path(supplied).expanduser().is_file() else None)
    if not resolved or not os.access(resolved, os.X_OK):
        raise ValueError('Provide a compatible executable; none will be installed automatically')
    binary = Path(resolved).resolve()
    # A native binary can exceed the molecular-file limit; hash streaming bytes.
    hasher = hashlib.sha256()
    with binary.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(part)
    result = {'status': 'failed', 'passed': False, 'engine': 'Open Babel',
              'backend': 'local_cpu_conversion', 'input': {'path': str(source), 'sha256': sha(raw),
                                                         'format': args.input_format, 'identities': before},
              'executable': {'path': str(binary), 'sha256': hasher.hexdigest()},
              'runtime': {'python': platform.python_version(), 'platform': platform.platform()},
              'scientific_validity': 'not_checked', 'network_contacted': False,
              'limits': ['Identity conversion only; no 3D pose, coordinate or property preservation claim.',
                         'No affinity, biological function or scientific accuracy benchmark.',
                         'Executable hash does not hash its complete environment or linked libraries.']}
    from rdkit import rdBase
    result['runtime']['rdkit'] = rdBase.rdkitVersion
    with tempfile.TemporaryDirectory(prefix='research-writer-convert-') as temporary:
        work = Path(temporary)
        version_dir = work / 'version'; version_dir.mkdir()
        version = bounded_process([str(binary), '-V'], version_dir, min(args.timeout, 10))
        result['version_probe'] = version
        if version.get('error') or version['returncode'] != 0 or 'Open Babel' not in version['stdout'] + version['stderr']:
            result['error'] = 'Executable version probe failed'
            return result, None
        staged_input, staged_output = work / ('input.' + args.input_format), work / ('output.' + args.output_format)
        staged_input.write_bytes(raw)
        argv = [str(binary), '-i' + args.input_format, str(staged_input), '-o' + args.output_format, '-O', str(staged_output)]
        if args.input_format == 'smi' and args.output_format == 'sdf':
            # Open Babel's 0D stereo extension is not independently understood
            # by RDKit. Generate a 2D depiction so standard bond stereo survives.
            argv.append('--gen2D')
            result['coordinate_operation'] = 'generated_2D_depiction_not_3D'
        else:
            result['coordinate_operation'] = 'no_generation_requested'
        result['argv'] = argv
        run_dir = work / 'run'; run_dir.mkdir()
        execution = bounded_process(argv, run_dir, args.timeout, [staged_output])
        result['execution'] = execution
        if execution.get('error') or execution['returncode'] != 0:
            result['error'] = execution.get('error', 'Nonzero engine exit')
            return result, None
        try:
            converted = bounded_read(staged_output)
            after = identities(converted, args.output_format)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            result['error'] = 'Independent output parsing failed: ' + str(exc)
            return result, None
        result['output'] = {'path': str(destination), 'sha256': sha(converted),
                            'format': args.output_format, 'identities': after}
        if after != before:
            result['error'] = 'Independent molecular count/order/identity/charge/bond/stereochemistry mismatch'
            return result, None
        result.update(status='converted_identity_checked', passed=True, identity_validation='independent_rdkit_pass')
        return result, converted


def write_report(path, result, force=False):
    with Path(path).open('w' if force else 'x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    sub = subs.add_parser('convert')
    sub.add_argument('--executable', required=True)
    sub.add_argument('--input', required=True)
    sub.add_argument('--input-format', required=True, choices=FORMATS)
    sub.add_argument('--output', required=True)
    sub.add_argument('--output-format', required=True, choices=FORMATS)
    sub.add_argument('--report', required=True)
    sub.add_argument('--timeout', type=float, default=30)
    sub.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        result, output = convert(args)
        if result['passed']:
            with Path(args.output).open('wb' if args.force else 'xb') as stream:
                stream.write(output)
        write_report(args.report, result, args.force)
        print(json.dumps({'status': result['status'], 'report': args.report}))
        return 0 if result['passed'] else 2
    except (OSError, UnicodeError, ValueError, RuntimeError, ImportError) as exc:
        failure = {'status': 'unavailable' if isinstance(exc, ImportError) else 'failed',
                   'passed': False, 'error': str(exc), 'scientific_validity': 'not_checked'}
        # Never replace an existing report while handling an exception.
        if not Path(args.report).exists():
            try:
                write_report(args.report, failure)
            except OSError:
                pass
        print(json.dumps(failure), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
