#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline structure contracts; real Boltz inference requires --actual-spec and --reference."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]/'skills/research-writer/scripts/structure_tools.py'
LOADER = importlib.util.spec_from_file_location('structure_contract', SCRIPT)
S = importlib.util.module_from_spec(LOADER); LOADER.loader.exec_module(S)
PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--actual-spec'); PARSER.add_argument('--reference')
ARGS, REST = PARSER.parse_known_args()
CRAMBIN = 'TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN'


def pdb_text(sequence='AAAA'):
    reverse = {v:k for k,v in S.AA3.items()}; lines=[]; serial=0
    for index, aa in enumerate(sequence, 1):
        for name, xyz in [('N',(0,0,0)),('CA',(1.45,0,0)),('C',(2.5,0,0)),('O',(2.5,1.2,0))]:
            serial+=1; x,y,z=xyz; x+=(index-1)*3.8
            lines.append(f'ATOM  {serial:5d} {name:^4s} {reverse[aa]} A{index:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 90.00           {name[0]:>2s}')
    return '\n'.join(lines)+'\nEND\n'


class StructureChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir()
        self.assets=self.root/'assets';self.assets.mkdir()
        self.spec={'schema':S.SCHEMA,'python':str(Path(sys.executable).resolve()),
                   'boltz_source':str(self.source),'assets_dir':str(self.assets),'output_dir':str(self.root/'run'),
                   'sequence':'AAAA','chain_id':'A','device':'cpu','seed':20261108,'threads':1,
                   'timeout_seconds':30,'recycling_steps':1,'sampling_steps':20,
                   'max_output_bytes':8*1024*1024,'max_log_bytes':4096,'memory_budget_bytes':8*1024**3}
        self.pdb=self.root/'structure.pdb';self.pdb.write_text(pdb_text())
        self.conf=self.root/'confidence.json';self.conf.write_text(json.dumps({'confidence_score':0.8,'ptm':0.7,'complex_plddt':0.9}))
    def tearDown(self): self.temp.cleanup()
    def test_spec_fixed_version_cpu_and_chemistry(self):
        S.validate_spec(self.spec)
        mutations=[('schema','v2'),('sequence','AAAA*'),('sequence','aaaa'),('sequence','AAA'),
                   ('sequence','A'*129),('chain_id','B'),('sequence',['AAAA']),('device','gpu'),
                   ('seed',True),('threads',0),('timeout_seconds',3601),('memory_budget_bytes',11*1024**3)]
        for key,value in mutations:
            with self.subTest(key=key,value=value):
                item={**self.spec,key:value}
                with self.assertRaises(ValueError):S.validate_spec(item)
        with self.assertRaises(ValueError):S.validate_spec({**self.spec,'extra':'ignored?'})
    def test_no_output_source_overlap(self):
        for root in (self.source,self.assets):
            with self.assertRaises(ValueError):S.validate_spec({**self.spec,'output_dir':str(root/'run')})
    def test_run_overlap_rejection_never_mutates_protected_roots(self):
        for root in (self.source,self.assets):
            marker=root/'retained';marker.write_bytes(b'original')
            snapshot={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for destination in (root/'unwanted-output',root):
                spec_path=self.root/'overlap.json';spec_path.write_text(json.dumps({**self.spec,'output_dir':str(destination)}))
                with self.assertRaises(ValueError):S.run(spec_path)
                self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()},snapshot)
                self.assertFalse((root/'unwanted-output').exists())
    def test_selected_venv_launcher_path_is_preserved(self):
        launcher=self.root/'venv-python';launcher.symlink_to(Path(sys.executable).resolve())
        paths=S.validate_spec({**self.spec,'python':str(launcher)})
        self.assertEqual(paths['python'],launcher)
    def msa_spec(self, raw=b'>query\nAAAA\n>homolog\nAAa-A\n'):
        path=self.root/'local.a3m';path.write_bytes(raw)
        return {**self.spec,'schema':S.SCHEMA_V2,'msa':{
            'mode':'local_a3m','path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest()}}
    def test_v2_closed_modes_preserve_v1_empty_input(self):
        empty={**self.spec,'schema':S.SCHEMA_V2,'msa':{'mode':'empty'}}
        S.validate_spec(empty)
        self.assertEqual(S.sequence_input(empty,self.root),S.sequence_input(self.spec,self.root))
        for value in (None,{}, {'mode':'server'}, {'mode':'empty','path':'unused'}):
            with self.subTest(msa=value),self.assertRaises(ValueError):
                S.validate_spec({**empty,'msa':value})
        with self.assertRaises(ValueError):S.validate_spec({**self.spec,'msa':{'mode':'empty'}})
    def test_local_a3m_query_width_alphabet_and_sequence_bound(self):
        item=self.msa_spec();S.validate_spec(item)
        raw,evidence=S.msa_bytes(item)
        self.assertEqual(evidence['sequences'],2);self.assertEqual(evidence['alignment_columns'],4)
        for bad in (b'>query\nAAAT\n',b'AAAA\n',b'>query\nAAAA\n>h\nAAA\n',
                    b'>query\nAAAA\n>h\nAAXA\n',b'>\nAAAA\n',b'>query\nAAAA\n>h\n',
                    b'>query\nAAAA\n>h\nAAAA\x00\n'):
            with self.subTest(raw=bad),self.assertRaises(ValueError):S.validate_spec(self.msa_spec(bad))
        valid=b'>query\nAAAA\n'+b'>h\nAAAA\n'*1023
        self.assertEqual(S.msa_bytes(self.msa_spec(valid))[1]['sequences'],1024)
        with self.assertRaises(ValueError):S.validate_spec(self.msa_spec(valid+b'>extra\nAAAA\n'))
        with self.assertRaises(ValueError):S.validate_spec(self.msa_spec(b'x'*(S.MAX_MSA+1)))
    def test_local_a3m_hash_staging_and_overlap_before_launch(self):
        item=self.msa_spec();raw,evidence=S.msa_bytes(item)
        destination=Path(item['output_dir']);destination.mkdir()
        (destination/'input.a3m').write_bytes(raw)
        self.assertEqual(S.staged_msa(item,destination),evidence)
        (destination/'input.a3m').write_bytes(raw.replace(b'AAAA',b'AAAT',1))
        with self.assertRaises(ValueError):S.staged_msa(item,destination)
        Path(item['msa']['path']).write_bytes(raw+b'\n')
        with self.assertRaises(ValueError):S.msa_bytes(item)
        original=self.msa_spec();nested=self.root/'msa-parent';nested.mkdir()
        nested_msa=nested/'input.a3m';nested_msa.write_bytes(raw)
        overlap={**original,'output_dir':str(nested),'msa':{**original['msa'],'path':str(nested_msa.resolve())}}
        path=self.root/'overlap-msa.json';path.write_text(json.dumps(overlap))
        with patch.object(S,'bounded_process') as launch:
            with self.assertRaises(ValueError):S.run(path)
            launch.assert_not_called()
        self.assertEqual(list(nested.iterdir()),[nested_msa])
    def test_invalid_msa_does_not_reserve_output(self):
        item=self.msa_spec();item['msa']['sha256']='0'*64
        path=self.root/'invalid-msa.json';path.write_text(json.dumps(item))
        with patch.object(S,'bounded_process') as launch:
            with self.assertRaises(ValueError):S.run(path)
            launch.assert_not_called()
        self.assertFalse(Path(item['output_dir']).exists())
    def test_msa_symlink_ancestor_refused_before_output(self):
        item=self.msa_spec();alias=self.root/'alias'
        alias.symlink_to(self.root.resolve(),target_is_directory=True)
        item['msa']['path']=str(alias.absolute()/'local.a3m')
        path=self.root/'alias-msa.json';path.write_text(json.dumps(item))
        with patch.object(S,'bounded_process') as launch:
            with self.assertRaises(ValueError):S.run(path)
            launch.assert_not_called()
        self.assertFalse(Path(item['output_dir']).exists())
    def test_source_tree_content_and_injected_module_detection(self):
        files={'src/boltz/main.py':b'# source fixture\n','pyproject.toml':b'version="2.2.1"\n'}
        rows=[]
        for rel,raw in files.items():
            p=self.source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            rows.append(('100644 blob '+oid+'\t'+rel).encode()+b'\0')
        def fake_git(source,*args):
            return (S.REVISION+'\n').encode() if args[0]=='rev-parse' else b''.join(rows)
        with patch.object(S,'git',side_effect=fake_git):
            self.assertEqual(S.verify_source(self.source)['file_count'],2)
            injected=self.source/'src/boltz/injected.py';injected.write_text('untracked')
            with self.assertRaises(ValueError):S.verify_source(self.source)
            injected.unlink();(self.source/'src/boltz/main.py').write_text('modified')
            with self.assertRaises(ValueError):S.verify_source(self.source)
    def test_valid_backbone_and_confidence(self):
        result=S.validate_structure(self.pdb,'AAAA')
        self.assertEqual(result['residues'],4);self.assertEqual(result['atoms'],16)
        self.assertEqual(result['sha256'],hashlib.sha256(self.pdb.read_bytes()).hexdigest())
        self.assertEqual(S.validate_confidence(self.conf)['fields']['complex_plddt'],0.9)
    def test_structural_identity_empty_truncated_missing_atom(self):
        for text in ['',pdb_text().replace('END\n',''),pdb_text().replace('ALA A','ALA B'),
                     pdb_text().replace('ALA A   2','CYS A   2'),
                     '\n'.join(l for l in pdb_text().splitlines() if not (l.startswith('ATOM') and l[12:16].strip()=='O'))+'\n']:
            self.pdb.write_text(text)
            with self.assertRaises(ValueError):S.validate_structure(self.pdb,'AAAA')
    def test_duplicate_nonfinite_and_disconnected_backbone(self):
        lines=pdb_text().splitlines(); duplicate='\n'.join(lines[:-1]+[lines[0],lines[-1]])+'\n'
        self.pdb.write_text(duplicate)
        with self.assertRaises(ValueError):S.validate_structure(self.pdb,'AAAA')
        for value in ['     nan','     inf','99999.00','   0.000']:
            edited=pdb_text().splitlines()
            edited[1]=edited[1][:30]+value+edited[1][38:]
            self.pdb.write_text('\n'.join(edited)+'\n')
            with self.assertRaises(ValueError):S.validate_structure(self.pdb,'AAAA')
    def test_mmcif_actual_atom_loop_and_truncation(self):
        tags=['group_PDB','label_asym_id','label_seq_id','label_comp_id','label_atom_id','Cartn_x','Cartn_y','Cartn_z']
        rows=[]
        for chain,index,res,atom,xyz in S.parse_atoms(self.pdb):
            rows.append(' '.join(['ATOM',chain,str(index),res,atom,*map(str,xyz)]))
        cif=self.root/'structure.cif'; text='data_fixture\nloop_\n'+'\n'.join('_atom_site.'+t for t in tags)+'\n'+'\n'.join(rows)+'\n#\n'
        cif.write_text(text);self.assertEqual(S.validate_structure(cif,'AAAA')['atoms'],16)
        cif.write_text(text.replace(rows[-1],rows[-1].rsplit(' ',1)[0]))
        with self.assertRaises(ValueError):S.validate_structure(cif,'AAAA')
    def test_bad_confidence_values_and_duplicate_keys(self):
        for val in [True,-1,1.001,'0.8',None]:
            self.conf.write_text(json.dumps({'confidence_score':val,'ptm':0.7,'complex_plddt':0.9}))
            with self.assertRaises(ValueError):S.validate_confidence(self.conf)
        for text in ['{"confidence_score":NaN}','{"x":1,"x":2}',
                     '{"confidence_score":0.8,"ptm":0.8,"complex_plddt":0.8,"iptm":2}']:
            self.conf.write_text(text)
            with self.assertRaises(ValueError):S.validate_confidence(self.conf)
    def test_asset_checks_fail_closed_and_detect_corruption(self):
        with self.assertRaises(ValueError):S.verify_assets(self.assets)
        for name in S.ASSETS:(self.assets/name).write_bytes(b'fixture')
        with self.assertRaises(ValueError):S.verify_assets(self.assets)
        fake={name:hashlib.sha256(b'fixture').hexdigest() for name in S.ASSETS}
        with patch.object(S,'ASSETS',fake):
            self.assertEqual(len(S.verify_assets(self.assets)),2)
            (self.assets/'extra').write_text('injected')
            with self.assertRaises(ValueError):S.verify_assets(self.assets)
            (self.assets/'extra').unlink();(self.assets/'ccd.pkl').unlink()
            (self.assets/'ccd.pkl').symlink_to(self.pdb)
            with self.assertRaises(ValueError):S.verify_assets(self.assets)
    def test_pins_are_explicit(self):
        self.assertEqual(S.REVISION,'b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc')
        self.assertEqual(S.ASSETS['boltz1_conf.ckpt'],'fea245d912c570ec117b2277c2719f312a6fc109c07b6f6ef741690ee775c2f5')
        with self.assertRaises(ValueError):S.verify_source(self.source)
    def test_invalid_spec_durable_before_source_or_launch(self):
        spec_path=self.root/'spec.json';spec_path.write_text(json.dumps({**self.spec,'sequence':'AAAX'}))
        with patch.object(S,'verify_source',side_effect=AssertionError('No source access')),patch.object(S,'bounded_process',side_effect=AssertionError('No child')):
            result=S.run(spec_path)
        report=json.loads((self.root/'run/report.json').read_text())
        self.assertEqual(result,report);self.assertFalse(report['engine_started'])
        self.assertEqual(report['status'],'failed');self.assertFalse(report['accepted'])
    def test_existing_output_never_modified(self):
        destination=self.root/'run';destination.mkdir(); marker=destination/'report.json';marker.write_text('preserve')
        spec_path=self.root/'spec.json';spec_path.write_text(json.dumps(self.spec))
        with self.assertRaises(FileExistsError):S.run(spec_path)
        self.assertEqual(marker.read_text(),'preserve')
    def test_started_nonzero_and_interruption_remain_partial(self):
        for name,error in [('nonzero',None),('interrupt',KeyboardInterrupt())]:
            item={**self.spec,'output_dir':str(self.root/name)}
            spec_path=self.root/(name+'.json');spec_path.write_text(json.dumps(item))
            def failed_process(*args):
                args[-1]()
                if error: raise error
                return {'returncode':7,'failure_kind':None}
            with patch.object(S,'verify_source',return_value={'revision':S.REVISION}),patch.object(S,'verify_assets',return_value={}),\
                 patch.object(S,'bounded_process',side_effect=failed_process):
                result=S.run(spec_path)
            self.assertTrue(result['engine_started']);self.assertFalse(result['accepted'])
            self.assertFalse(result['actual_runtime_verified'])
            self.assertEqual(result['status'],'partial' if name=='nonzero' else 'interrupted')
    def test_argv_requires_cpu_no_msa_server_and_explicit_settings(self):
        args=S.boltz_argv({'spec':self.spec,'output_dir':str(self.root),'assets_dir':str(self.assets)})
        self.assertNotIn('--use_msa_server',args);self.assertIn('--no_kernels',args)
        self.assertEqual(args[args.index('--model')+1],'boltz1')
        self.assertEqual(args[args.index('--accelerator')+1],'cpu')
    def test_output_validation_cli_is_not_runtime_claim(self):
        done=subprocess.run([sys.executable,str(SCRIPT),'validate-output','--structure',str(self.pdb),
                            '--confidence',str(self.conf),'--sequence','AAAA'],capture_output=True,text=True,timeout=10)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertFalse(json.loads(done.stdout)['actual_runtime_verified'])
    def test_actual_process_timeout_logs_and_memory_monitor(self):
        try:import psutil
        except ImportError:self.skipTest('Controller psutil unavailable; process monitor not executed')
        for label,code,timeout,expected in [
            ('timeout','import time; time.sleep(10)',0.15,'timed_out'),
            ('logs','print("x"*200000)',5,'log_limit')]:
            directory=self.root/label;directory.mkdir()
            result=S.bounded_process([sys.executable,'-c',code],directory,timeout,1024,1024*1024,1024**3)
            self.assertEqual(result['failure_kind'],expected)
            self.assertLessEqual(result['log_bytes'],1024)
    @unittest.skipUnless(ARGS.actual_spec,'Real Boltz assets/runtime not selected; scientific inference pending')
    def test_real_boltz_crambin_and_independent_reference_metric(self):
        self.assertTrue(ARGS.reference,'--reference must identify the independently acquired 1CRN PDB')
        spec=json.loads(Path(ARGS.actual_spec).read_text())
        self.assertEqual(spec['sequence'],CRAMBIN)
        self.assertEqual(spec['seed'],20261108)
        self.assertEqual(spec['recycling_steps'],3);self.assertEqual(spec['sampling_steps'],200)
        completed=subprocess.run([sys.executable,str(SCRIPT),'run','--spec',ARGS.actual_spec],
                                 capture_output=True,text=True,timeout=spec['timeout_seconds']+180)
        self.assertEqual(completed.returncode,0,completed.stderr+'\n'+completed.stdout[-2000:])
        report=json.loads((Path(spec['output_dir'])/'report.json').read_text())
        self.assertTrue(report['actual_runtime_verified']);self.assertEqual(report['workload']['observed']['device'],'cpu')
        # Independent parser/alignment path; no dependence on adapter atom parser.
        import numpy as np
        from Bio.PDB import PDBParser, Superimposer
        from Bio.SeqUtils import seq1
        parser=PDBParser(QUIET=True)
        pred=parser.get_structure('prediction',str(Path(spec['output_dir'])/'engine/boltz_results_input/predictions/input/input_model_0.pdb'))
        ref=parser.get_structure('reference',ARGS.reference)
        p=list(pred[0]['A'].get_residues());r=list(ref[0]['A'].get_residues())
        self.assertEqual(''.join(seq1(x.resname) for x in p),CRAMBIN)
        self.assertEqual(''.join(seq1(x.resname) for x in r),CRAMBIN)
        fit=Superimposer();fit.set_atoms([x['CA'] for x in r],[x['CA'] for x in p])
        metric={'fixture':'1CRN:A','reference_sha256':S.digest(ARGS.reference),'prediction_sha256':report['structure']['sha256'],
                'mapping':'46 residues by exact sequence index; C-alpha only; least-squares rigid alignment',
                'rmsd_angstrom':float(fit.rms),'threshold_angstrom':2.0,'passed':bool(fit.rms<=2.0),
                'scope':'known-reference engineering check; not held-out generalization'}
        S.atomic_json(Path(spec['output_dir'])/'reference-metric.json',metric)
        # A rigid translation is a positive control; a local internal deformation is negative.
        moved=copy.deepcopy(r)
        for x in moved:x['CA'].coord=x['CA'].coord+np.array([7.,-4.,3.])
        fit.set_atoms([x['CA'] for x in r],[x['CA'] for x in moved]);self.assertLess(fit.rms,1e-5)
        moved[10]['CA'].coord += np.array([50.,0.,0.])
        fit.set_atoms([x['CA'] for x in r],[x['CA'] for x in moved]);self.assertGreater(fit.rms,2.0)
        self.assertTrue(metric['passed'],f'Frozen known-reference threshold failed: {metric}')


if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+REST)
