#!/usr/bin/env python3
"""Original MIT regression checks. Run --molecular in an RDKit/OpenMM environment."""
import argparse
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'research-writer'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--molecular', action='store_true')
ARGS, REMAINING = parser.parse_known_args()
spec = importlib.util.spec_from_file_location('evidence_tools', SKILL / 'scripts' / 'evidence_tools.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

class IntegrityChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def fixture(self):
        context = dict(run='r1', condition='control', dataset='D', metric='signal', unit='mM', seed='1', statistic='mean', value='0.5')
        path = self.root / 'results.csv'
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=E.CONTEXT)
            writer.writeheader(); writer.writerow(context)
        return dict(artifacts=[dict(id='a', path='results.csv', sha256=hashlib.sha256(path.read_bytes()).hexdigest())],
                    measurements=[dict(id='m', artifact_id='a', row=1, **context)],
                    claims=[dict(id='c', evidence_id='m', **context)])
    def test_identifiers_and_provenance(self):
        a=E.normalize_records([{'doi':'https://doi.org/10.1000/EXAMPLE'}, {'doi':'doi:10.1000/example'}, {'arxiv':'arXiv:2605.20025v1'}, {'arxiv':'https://arxiv.org/abs/2605.20025v2'}, {'pmid':'https://pubmed.ncbi.nlm.nih.gov/12345/'}])
        self.assertEqual(a['status'],'success');self.assertEqual(len(a['records']),3)
        self.assertEqual(len(a['records'][0]['provenance']),2)
        self.assertEqual({x.get('version') for x in a['records'][1]['identifier_variants']},{'v1','v2'})
        self.assertFalse(E.normalize_identifier('not-a-doi','doi')['valid'])
    def test_context_and_corruption(self):
        data=self.fixture();self.assertTrue(E.verify_evidence(data,self.root)['passed'])
        for key in ('run','condition','dataset','metric','unit','seed','statistic','value'):
            changed=copy.deepcopy(data);changed['claims'][0][key]='0.7' if key=='value' else 'different'
            self.assertFalse(E.verify_evidence(changed,self.root)['passed'],key)
        (self.root/'results.csv').write_text('corrupt')
        self.assertFalse(E.verify_evidence(data,self.root)['passed'])
    def test_empty_and_nonfinite(self):
        self.assertEqual(E.verify_evidence({},self.root)['status'],'not_checked')
        data=self.fixture();data['measurements'][0]['value']='NaN'
        self.assertFalse(E.verify_evidence(data,self.root)['passed'])
    def test_metadata_is_not_fulltext(self):
        data=dict(sources=[dict(id='s',access='metadata',locator='DOI record',identity_status='identity_verified')],
                  source_claims=[dict(id='c',source_id='s',required_access='full_text',locator='Results')])
        self.assertFalse(E.verify_evidence(data,self.root)['passed'])
    def test_project_preserves_edits(self):
        E.init_project(self.root); p=self.root/'research-project.json';p.write_text('{"edited":true}')
        E.init_project(self.root);self.assertEqual(p.read_text(),'{"edited":true}')
    def test_network_failure_not_absence(self):
        import urllib.error
        with patch.object(E.urllib.request,'urlopen',side_effect=urllib.error.URLError('offline')):
            self.assertEqual(E.search_crossref('test',1)['status'],'unavailable')
    def test_profile_and_plan_do_not_execute(self):
        p=self.root/'remote.json';p.write_text(json.dumps(dict(schema_version=1,mode='remote',remote_host='unconfigured',accelerator='cuda')))
        out=self.root/'doctor.json'
        result=subprocess.run([sys.executable,str(SKILL/'scripts/research_tools.py'),'doctor','--profile',str(p),'--output',str(out)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        d=json.loads(out.read_text());self.assertTrue(all(x['status']=='remote_unprobed' for x in d['engines']))
        self.assertEqual(d['gpu']['status'],'not_probed')
        input_file=self.root/'input.yaml';input_file.write_text('version: 1\n')
        out=self.root/'plan.json';result=subprocess.run([sys.executable,str(SKILL/'scripts/research_tools.py'),'plan','--tool','boltz','--input',str(input_file),'--profile',str(p),'--output',str(out)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(out.read_text())['status'],'planned_not_executed')
    @unittest.skipUnless(ARGS.molecular,'Optional RDKit/OpenMM environment not requested')
    def test_actual_molecular_controls(self):
        out=self.root/'rdkit.json';script=str(SKILL/'scripts/research_tools.py')
        result=subprocess.run([sys.executable,script,'rdkit-descriptors','--smiles','CCO','--output',str(out)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);d=json.loads(out.read_text())
        self.assertAlmostEqual(d['descriptors']['MolWt'],46.069,places=3);self.assertEqual(d['formula'],'C2H6O')
        out=self.root/'energy.json';result=subprocess.run([sys.executable,script,'openmm-smoke','--output',str(out)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);d=json.loads(out.read_text())
        self.assertAlmostEqual(d['energy'],0.5,places=8);self.assertEqual(d['platform'],'Reference')

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]]+REMAINING)
