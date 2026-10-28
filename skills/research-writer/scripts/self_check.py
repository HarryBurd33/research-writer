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
import math
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
            'scripts/literature_tools.py', 'scripts/support_tools.py',
            'scripts/conversion_tools.py', 'scripts/protein_tools.py',
            'scripts/remote_tools.py', 'scripts/remote_worker.py',
            'scripts/discovery_tools.py', 'scripts/claim_audit.py',
            'templates/research-record.md', 'references/tool-catalog.json',
            *('references/' + name + '.md' for name in (
                'argument-and-synthesis', 'computational-research', 'delivery',
                'device-profiles', 'modes', 'prewriting', 'publication-workflow',
                'question-development', 'research-and-sources', 'standards',
                'tool-usage', 'testing', 'literature-retrieval', 'source-support',
                'molecular-conversion', 'protein-embeddings', 'remote-execution',
                'deeper-retrieval', 'claim-audit')))


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
    # These help calls import both optional tools without any HTTP request.
    run_cli(work, 'literature_tools.py', ['--help'])
    run_cli(work, 'support_tools.py', ['--help'])
    run_cli(work, 'conversion_tools.py', ['--help'])
    run_cli(work, 'protein_tools.py', ['--help'])
    run_cli(work, 'remote_tools.py', ['--help'])
    source = work / 'source.txt'
    text = 'Fictional control: the observed signal was zero.'
    source.write_text(text, encoding='utf-8')
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    packet = {'schema_version': 1,
              'sources': [{'id': 's', 'version': 'fixture-v1', 'access': 'full_text',
                           'identity_status': 'identity_verified', 'path': source.name,
                           'sha256': sha, 'locator': 'fictional control'}],
              'reviews': [{'id': 'r', 'claim': 'The fictional signal was zero.',
                           'source_id': 's', 'source_version': 'fixture-v1', 'source_sha256': sha,
                           'start': 0, 'end': len(text), 'passage': text, 'locator': 'control sentence',
                           'judgment': 'supports', 'rationale': 'Explicit zero in this fictional control.',
                           'reviewer': 'installation-control', 'reviewed_at': '2026-01-01T00:00:00Z'}]}
    packet_path = work / 'support.json'
    write(packet_path, packet)
    support_report = work / 'support-pass.json'
    run_cli(work, 'support_tools.py', ['review-support', '--input', packet_path, '--output', support_report])
    require(load(support_report)['passed'] and
            load(support_report)['semantic_entailment'] == 'not_automatically_verified',
            'Support record integrity/semantic boundary failed')
    packet['reviews'][0]['passage'] = 'Invented source text'
    write(packet_path, packet)
    support_fail = work / 'support-fail.json'
    run_cli(work, 'support_tools.py', ['review-support', '--input', packet_path, '--output', support_fail], expected=2)
    require(not load(support_fail)['passed'], 'Invented passage accepted')


def deeper_check(work):
    # Loading the optional discovery CLI must make no network request.
    run_cli(work, 'discovery_tools.py', ['--help'])
    run_cli(work, 'claim_audit.py', ['--help'])
    source = work / 'audit-source.txt'
    text = 'Synthetic installation control: the signal was zero.'
    source.write_text(text, encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    claim = 'The synthetic control signal was zero.'
    packet = {'schema_version': 1,
              'sources': [{'id': 's', 'version': 'control-v1', 'access': 'full_text',
                           'identity_status': 'identity_verified', 'path': source.name,
                           'sha256': digest, 'locator': 'synthetic control',
                           'study_family': 'control-family', 'publication_status': 'current'}],
              'claims': [{'id': 'c1', 'text': claim, 'required_source_ids': ['s'],
                          'required_access': 'full_text'}],
              'reviews': [{'id': 'r', 'claim_id': 'c1', 'claim': claim,
                           'source_id': 's', 'source_version': 'control-v1',
                           'source_sha256': digest, 'start': 0, 'end': len(text),
                           'passage': text, 'locator': 'synthetic control',
                           'judgment': 'supports', 'rationale': 'Explicit statement in fictional control.',
                           'reviewer': 'installation-control', 'reviewed_at': '2026-01-01T00:00:00Z'}]}
    manifest, report = work / 'claims.json', work / 'claim-audit.json'
    write(manifest, packet)
    run_cli(work, 'claim_audit.py', ['audit-claims', '--input', manifest, '--output', report])
    result = load(report)
    require(result['status'] == 'records_valid' and
            result['semantic_entailment'] == 'not_automatically_verified' and
            result['drafting_clearance'] == 'not_granted',
            'Claim audit confused record integrity with drafting clearance')
    packet['claims'].append({'id': 'c2', 'text': 'An additional unreviewed claim.',
                             'required_source_ids': ['s'], 'required_access': 'full_text'})
    write(manifest, packet)
    incomplete = work / 'claim-audit-incomplete.json'
    run_cli(work, 'claim_audit.py', ['audit-claims', '--input', manifest,
                                  '--output', incomplete], expected=2)
    require(load(incomplete)['status'] == 'incomplete', 'Missing declared review was accepted')


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


def conversion_check(work, executable):
    source, output, report = work / 'conversion.smi', work / 'conversion.sdf', work / 'conversion.json'
    source.write_text('C[C@H](O)C(=O)O chiral_control\nF/C=C/F trans_control\n', encoding='utf-8')
    run_cli(work, 'conversion_tools.py', ['convert', '--executable', executable,
            '--input', source, '--input-format', 'smi', '--output', output,
            '--output-format', 'sdf', '--report', report])
    require(load(report)['passed'], 'Conversion identity control failed')
    from rdkit import Chem
    molecules = list(Chem.SDMolSupplier(str(output)))
    expected = [Chem.MolFromSmiles(s) for s in ('C[C@H](O)C(=O)O', 'F/C=C/F')]
    require(len(molecules) == 2 and all(m is not None for m in molecules) and
            [Chem.MolToSmiles(m, isomericSmiles=True) for m in molecules] ==
            [Chem.MolToSmiles(m, isomericSmiles=True) for m in expected],
            'Independent stereo conversion parse failed')


def protein_check(work, python, model_dir):
    source, report, artifact = work / 'protein.fa', work / 'protein.json', work / 'embeddings.json'
    source.write_text('>canonical_control\nACDEFGHIKLMNPQRSTVWY\n', encoding='utf-8')
    result = subprocess.run([python, str(ROOT / 'scripts' / 'protein_tools.py'), 'embed',
            '--input', str(source), '--model-dir', model_dir, '--device', 'cpu',
            '--output', str(report), '--embedding-output', str(artifact), '--timeout', '120'],
            cwd=work, capture_output=True, text=True, timeout=180,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1'})
    require(result.returncode == 0, 'Protein control failed: ' + result.stderr[-1000:])
    metadata, data = load(report), load(artifact)
    values = data['records'][0]['embedding']
    require(metadata['dimension'] == 320 and data['device'] == 'cpu' and len(values) == 320 and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values),
            'Protein vector dimension/finite/device control failed')
    require(hashlib.sha256(artifact.read_bytes()).hexdigest() == metadata['artifact']['sha256'],
            'Protein output hash mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--molecular', action='store_true', help='Require, execute and validate optional CPU controls')
    parser.add_argument('--obabel', help='Explicit Open Babel executable; require actual independently checked conversion')
    parser.add_argument('--protein-python', help='Separate protein runtime interpreter')
    parser.add_argument('--protein-model-dir', help='Verified local small ESM-2 assets; paired with --protein-python')
    args = parser.parse_args()
    if bool(args.protein_python) != bool(args.protein_model_dir):
        parser.error('--protein-python and --protein-model-dir must be supplied together')
    checks = []
    try:
        package_check()
        checks.append({'name': 'package', 'status': 'passed'})
        with tempfile.TemporaryDirectory(prefix='research-writer-check-') as directory:
            work = Path(directory)
            core_check(work)
            checks.append({'name': 'core', 'status': 'passed'})
            deeper_check(work)
            checks.append({'name': 'deeper_retrieval_and_claim_inventory', 'status': 'passed'})
            if args.molecular:
                molecular_check(work)
                checks.append({'name': 'molecular', 'status': 'passed'})
            else:
                checks.append({'name': 'molecular', 'status': 'skipped', 'reason': 'not requested'})
            if args.obabel:
                conversion_check(work, args.obabel)
                checks.append({'name': 'conversion', 'status': 'passed'})
            else:
                checks.append({'name': 'conversion', 'status': 'skipped', 'reason': 'not requested'})
            if args.protein_python:
                protein_check(work, args.protein_python, args.protein_model_dir)
                checks.append({'name': 'protein', 'status': 'passed'})
            else:
                checks.append({'name': 'protein', 'status': 'skipped', 'reason': 'not requested'})
    except Exception as exc:
        print(json.dumps({'passed': False, 'checks': checks, 'error': f'{type(exc).__name__}: {exc}'}))
        return 1
    print(json.dumps({'passed': True, 'checks': checks, 'scope': 'offline installation/control checks; no scientific validation'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
