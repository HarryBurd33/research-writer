#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Original synthetic molecular/parser contracts; not real docking evidence."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--require-rdkit',action='store_true')
ARGS,REST=parser.parse_known_args()
spec=importlib.util.spec_from_file_location('docking_contract',ROOT/'skills/research-writer/scripts/docking_tools.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)
HAS_RDKIT=importlib.util.find_spec('rdkit') is not None
if ARGS.require_rdkit and not HAS_RDKIT:raise SystemExit('Required RDKit unavailable; not a passing skip')


def atom(index,element,x,y=0,z=0,residue='UNL'):
    a=list(' '*80);a[:6]='ATOM  ';a[6:11]=f'{index:5d}';a[12:16]=f'{element:>4s}';a[17:20]=residue
    a[22:26]=f'{1:4d}'
    for start,value in [(30,x),(38,y),(46,z)]:a[start:start+8]=f'{value:8.3f}'
    a[70:76]=f'{0.:6.3f}';a[77:]=element
    return ''.join(a)


def molecule(shift=0):
    return ('REMARK SMILES CCO\nREMARK SMILES IDX 1 1 2 2 3 3\nROOT\n'+
            '\n'.join([atom(1,'C',shift),atom(2,'C',shift+1.5),atom(3,'O',shift+2.8)])+'\nENDROOT\nTORSDOF 0\n').encode()


def output(raw):return b'MODEL 1\nREMARK VINA RESULT: -1.0 0.0 0.0\n'+raw+b'ENDMDL\n'


class Basic(unittest.TestCase):
    def test_nonfinite_bool_and_limits(self):
        for value in [True,float('nan'),float('inf'),-1,9]:
            with self.assertRaises(ValueError):D.number(value,0,8,True)
        self.assertEqual(D.number(0,0,8,True),0)

    def test_duplicate_json_and_durable_failure(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'spec';p.write_text('{"schema_version":1,"schema_version":1}')
            r=D.execute(p,root/'result');self.assertFalse(r['passed']);self.assertIn('Duplicate',r['error'])
            self.assertFalse(json.loads((root/'result/report.json').read_text())['passed'])
            with self.assertRaises(ValueError):D.execute(p,root/'result')

    def test_artifact_hash_and_oversize(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'data';p.write_bytes(b'abcd')
            with self.assertRaises(ValueError):D.artifact({'path':str(p),'sha256':'0'*64})
            with self.assertRaises(ValueError):D.read_file(p,3)

    @unittest.skipUnless(os.name=='posix','POSIX link/pipe check')
    def test_symlink_fifo_refused(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'a').write_text('x');(r/'link').symlink_to(r/'a');os.mkfifo(r/'pipe')
            for p in [r/'link',r/'pipe']:
                with self.assertRaises(ValueError):D.read_file(p)

    def test_unsupported_receptor_chemistry(self):
        with self.assertRaises(ValueError):D.parse_atoms(atom(1,'C',0,residue='HEM'),receptor=True)
        self.assertEqual(len(D.parse_atoms(atom(1,'C',0,residue='ALA'),receptor=True)),1)


@unittest.skipUnless(HAS_RDKIT,'RDKit not selected; molecular contracts unexecuted')
class Molecular(unittest.TestCase):
    def setUp(self):
        self.original=D.ligand(molecule());self.settings={'center':[5,0,0],'size':[30,20,20],'num_modes':2}

    def test_fixed_frame_metric_does_not_align_away_translation(self):
        result=D.poses(output(molecule(10)),self.original,self.settings,self.original)
        self.assertAlmostEqual(result[0]['reference_rmsd_angstrom'],10.,places=12)
        self.assertEqual(result[0]['vina_intermode_rmsd_lower'],0.)

    def test_complete_pose_identity(self):
        r=D.poses(output(molecule()),self.original,self.settings,self.original)
        self.assertEqual(r[0]['heavy_atoms'],3);self.assertEqual(r[0]['reference_rmsd_angstrom'],0.)

    def test_same_count_element_substitution(self):
        changed=molecule().replace(atom(3,'O',2.8).encode(),atom(3,'N',2.8).encode())
        with self.assertRaises(ValueError):D.poses(output(changed),self.original,self.settings)

    def test_incomplete_atom_map(self):
        for raw in [molecule().replace(b'3 3',b''),molecule().replace(b'3 3',b'3 2')]:
            with self.assertRaises(ValueError):D.ligand(raw)

    def test_bad_geometry_truncation_and_nonfinite_score(self):
        wrong=molecule().replace(atom(3,'O',2.8).encode(),atom(3,'O',9).encode())
        for raw in [output(wrong),output(molecule()).replace(b'ENDMDL\n',b''),output(molecule()).replace(b'-1.0',b'NaN')]:
            with self.assertRaises(ValueError):D.poses(raw,self.original,self.settings)

    def test_box_and_mode_count(self):
        with self.assertRaises(ValueError):D.poses(output(molecule(50)),self.original,self.settings)
        with self.assertRaises(ValueError):D.poses(output(molecule()),self.original,{**self.settings,'num_modes':0})


if __name__=='__main__':unittest.main(argv=[sys.argv[0],*REST])
