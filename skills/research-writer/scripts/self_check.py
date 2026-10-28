#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline installed-skill smoke; use --molecular to require RDKit and OpenMM.

Writes only to a disposable temporary directory. No models, downloads, remote
connections or GPU probes. A pass is an installation check, not research validation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ('run', 'condition', 'dataset', 'metric', 'unit', 'seed', 'statistic', 'value')
REQUIRED = ('SKILL.md', 'LICENSE', 'README.md', 'scripts/evidence_tools.py',
            'scripts/research_tools.py', 'scripts/self_check.py',
            'templates/research-record.md', 'references/tool-catalog.json',
            *('references/' + name + '.md' for name in (
                'argument-and-synthesis', 'computational-research', 'delivery',
                'device-profiles', 'modes', 'prewriting', 'publication-workflow',
                'question-development', 'research-and-sources', 'standards',
                'tool-usage', 'testing')))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def package_check():
    for name in REQUIRED:
        p = ROOT / name
        require(p.is_file() and p.resolve().is_relative_to(ROOT), 'Missing/escaping resource: ' + name)
    for folder in ('references', 'templates', 'scripts'):
        for p in (ROOT / folder).rglob('*'):
            if p.suffix == '.py':
                compile(p.read_text(encoding='utf-8'), str(p), 'exec')
    # README includes repository-facing installation links; bundled resources
    # and entry point must resolve inside the independently installed skill.
    for p in [ROOT / 'SKILL.md', *(ROOT / 'references').glob('*.md'), *(ROOT / 'templates').glob('*.md')]:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', p.read_text(encoding='utf-8')):
            if target.startswith('#') or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target):
                continue
            linked = (p.parent / target.split('#')[0]).resolve()
            require(linked.is_relative_to(ROOT) and linked.is_file(), 'Broken/escaping link: ' + target)
    text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    require(re.search(r'^name: research-writer$', text, re.M), 'Skill discovery name differs')
    entries = json.loads((ROOT / 'references/tool-catalog.json').read_text(encoding='utf-8'))
    engines = entries.get('engines') if isinstance(entries, dict) else None
    require(isinstance(engines, list) and len(engines) == 13, 'Incomplete engine catalog')


def run_cli(work, script, arguments, expected=0):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *map(str, arguments)],
                            cwd=work, text=True, capture_output=True, timeout=60,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    require(result.returncode == expected,
            f'{script} {arguments[0]} exited {result.returncode}: {result.stderr[-1000:]}')
    return result


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def core_check(work):
    run_cli(work, 'evidence_tools.py', ['init-project', '--directory', work])
    project = work / 'research-project.json'
    require(load(project)['target'] is None and load(project)['destination'] is None, 'Invented intake default')
    project.write_text('{"customized": true}', encoding='utf-8')
    run_cli(work, 'evidence_tools.py', ['init-project', '--directory', work])
    require(load(project) == {'customized': True}, 'Project customization overwritten')
    bibliography = work / 'input.json'
    write(bibliography, [{'doi': 'doi:10.1234/SAMPLE'}, {'doi': 'https://doi.org/10.1234/sample'}])
    bib_out = work / 'bibliography.json'
    run_cli(work, 'evidence_tools.py', ['bibliography', '--input', bibliography, '--output', bib_out])
    records = load(bib_out)['records']
    require(len(records) == 1 and len(records[0]['provenance']) == 2, 'Bibliography identity/provenance failed')
    before = bib_out.read_bytes()
    run_cli(work, 'evidence_tools.py', ['bibliography', '--input', bibliography, '--output', bib_out], expected=2)
    require(before == bib_out.read_bytes(), 'Existing output overwritten')
    profile = work / 'device.json'
    run_cli(work, 'research_tools.py', ['profile', '--output', profile])
    inventory = work / 'inventory.json'
    run_cli(work, 'research_tools.py', ['doctor', '--profile', profile, '--output', inventory])
    observed = load(inventory)
    require(observed['gpu']['status'] == 'not_probed' and
            all(not x['execution_tested'] for x in observed['engines']), 'Inventory invented execution')
    fasta = work / 'input.fa'
    fasta.write_text('>control\nACDX\n', encoding='utf-8')
    output = work / 'fasta.json'
    run_cli(work, 'research_tools.py', ['fasta', '--input', fasta, '--output', output])
    record = load(output)['records'][0]
    require(record['length'] == 4 and record['nonstandard_count'] == 1, 'FASTA identity failed')
    row = dict(zip(CONTEXT, ('control', 'baseline', 'toy', 'signal', 'mM', '0', 'single', '0')))
    table = work / 'control.csv'
    with table.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=CONTEXT)
        writer.writeheader(); writer.writerow(row)
    manifest = {'artifacts': [{'id': 'a', 'path': table.name, 'sha256': hashlib.sha256(table.read_bytes()).hexdigest()}],
                'measurements': [{'id': 'm', 'artifact_id': 'a', 'row': 1, **row}],
                'claims': [{'id': 'c', 'evidence_id': 'm', **row}]}
    input_file, report = work / 'evidence.json', work / 'verified.json'
    write(input_file, manifest)
    run_cli(work, 'evidence_tools.py', ['verify-evidence', '--input', input_file, '--output', report])
    require(load(report)['passed'], 'Valid zero evidence rejected')
    manifest['claims'][0]['unit'] = 'M'
    write(input_file, manifest)
    failed = work / 'rejected.json'
    run_cli(work, 'evidence_tools.py', ['verify-evidence', '--input', input_file, '--output', failed], expected=2)
    require(not load(failed)['passed'], 'Wrong-unit claim accepted')


def molecular_check(work):
    output = work / 'ethanol.json'
    run_cli(work, 'research_tools.py', ['rdkit-descriptors', '--smiles', 'CCO', '--output', output])
    descriptor = load(output)
    require(descriptor['formula'] == 'C2H6O' and abs(descriptor['descriptors']['MolWt'] - 46.069) < 0.001,
            'Ethanol descriptor control failed')
    sdf, conf = work / 'ethanol.sdf', work / 'conformer.json'
    run_cli(work, 'research_tools.py', ['rdkit-conformer', '--smiles', 'CCO', '--seed', '481516',
                                     '--sdf', sdf, '--output', conf])
    conformer = load(conf)
    require(conformer['converged'] and conformer['optimizer_status'] == 0 and
            hashlib.sha256(sdf.read_bytes()).hexdigest() == conformer['artifact']['sha256'], 'Conformer integrity failed')
    from rdkit import Chem
    mol = Chem.SDMolSupplier(str(sdf), removeHs=False)[0]
    require(mol is not None and mol.GetNumAtoms() == 9 and mol.GetConformer().Is3D() and
            Chem.MolToSmiles(Chem.RemoveHs(mol)) == 'CCO', 'Conformer is not 3D ethanol')
    energy = work / 'energy.json'
    run_cli(work, 'research_tools.py', ['openmm-smoke', '--output', energy])
    observed = load(energy)
    require(observed['platform'] == 'Reference' and observed['unit'] == 'kJ/mol' and
            abs(observed['energy'] - 0.5) < 1e-8, 'Analytic OpenMM control failed')
    for obj in (descriptor, observed):
        artifact = obj['measurement_artifact']
        require(hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() == artifact['sha256'],
                'Molecular measurement hash mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--molecular', action='store_true', help='Require, execute and validate optional CPU controls')
    args = parser.parse_args()
    checks = []
    try:
        package_check()
        checks.append({'name': 'package', 'status': 'passed'})
        with tempfile.TemporaryDirectory(prefix='research-writer-check-') as directory:
            work = Path(directory)
            core_check(work)
            checks.append({'name': 'core', 'status': 'passed'})
            if args.molecular:
                molecular_check(work)
                checks.append({'name': 'molecular', 'status': 'passed'})
            else:
                checks.append({'name': 'molecular', 'status': 'skipped', 'reason': 'not requested'})
    except Exception as exc:
        print(json.dumps({'passed': False, 'checks': checks, 'error': f'{type(exc).__name__}: {exc}'}))
        return 1
    print(json.dumps({'passed': True, 'checks': checks, 'scope': 'offline installation/control checks; no scientific validation'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
