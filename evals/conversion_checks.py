#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline conversion contracts; --molecular requires actual Open Babel/RDKit."""
import argparse
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--molecular', action='store_true')
parser.add_argument('--executable')
ARGS, REST = parser.parse_known_args()
SCRIPT = Path(__file__).resolve().parents[1] / 'skills/research-writer/scripts/conversion_tools.py'
spec = importlib.util.spec_from_file_location('conversion_checks_tool', SCRIPT)
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)


class ConversionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.source = self.root / 'input.smi'; self.source.write_text('CCO\n', encoding='utf-8')
        self.output = self.root / 'output.sdf'; self.report = self.root / 'report.json'
        self.args = argparse.Namespace(input=str(self.source), output=str(self.output), report=str(self.report),
                                       input_format='smi', output_format='sdf', timeout=30,
                                       executable=sys.executable, force=False)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), 'convert', '--executable', ARGS.executable or sys.executable,
                               '--input', str(self.source), '--input-format', 'smi', '--output', str(self.output),
                               '--output-format', 'sdf', '--report', str(self.report), *extra],
                              capture_output=True, text=True, timeout=120)

    def test_help_is_standalone_and_no_implicit_install(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('convert', r.stdout)

    def test_existing_destinations_preserved_before_engine(self):
        for path in (self.output, self.report):
            with self.subTest(path=path.name):
                path.write_text('edited', encoding='utf-8')
                with patch.object(C, 'identities', side_effect=AssertionError('No engine/parse expected')):
                    with self.assertRaises(FileExistsError): C.convert(self.args)
                self.assertEqual(path.read_text(), 'edited'); path.unlink()

    def test_argument_bounds_and_aliases(self):
        for value in (0, -1, 121, float('nan'), True):
            with self.subTest(timeout=value):
                self.args.timeout = value
                with self.assertRaises(ValueError): C.convert(self.args)
        self.args.timeout = 30; self.args.report = self.args.input; self.args.force = True
        with self.assertRaises(ValueError): C.convert(self.args)
        self.assertEqual(self.source.read_text(), 'CCO\n')

    def test_input_byte_limit(self):
        path = self.root / 'large'; path.write_bytes(b'x' * 50)
        with self.assertRaises(ValueError): C.bounded_read(path, maximum=49)
        self.assertEqual(len(C.bounded_read(path, maximum=50)), 50)

    def test_real_process_timeout(self):
        result = C.bounded_process([sys.executable, '-c', 'import time; time.sleep(10)'], self.root, 0.05)
        self.assertIn('timeout', result['error'])
        self.assertLess(result['elapsed_seconds'], 5)

    @unittest.skipUnless(ARGS.molecular, 'Optional Open Babel/RDKit runtime not requested')
    def test_real_conversion_stereo_charge_aromatic_and_roundtrip(self):
        self.assertTrue(ARGS.executable, '--molecular requires --executable')
        self.source.write_text('CCO ethanol\nc1ccccc1 aromatic\nC[C@H](O)C(=O)O chiral\nF/C=C/F geometric\n[NH4+].[Cl-] charged\n', encoding='utf-8')
        r = self.cli(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        result = json.loads(self.report.read_text())
        self.assertTrue(result['passed']); self.assertEqual(result['identity_validation'], 'independent_rdkit_pass')
        self.assertEqual(result['input']['identities'], result['output']['identities'])
        self.assertEqual(len(result['output']['identities']), 5)
        self.assertEqual(hashlib.sha256(self.output.read_bytes()).hexdigest(), result['output']['sha256'])
        self.assertEqual(result['coordinate_operation'], 'generated_2D_depiction_not_3D')
        r = subprocess.run([sys.executable, str(SCRIPT), 'convert', '--executable', ARGS.executable,
                            '--input', str(self.output), '--input-format', 'sdf', '--output', str(self.root / 'roundtrip.smi'),
                            '--output-format', 'smi', '--report', str(self.root / 'roundtrip.json')],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(C.identities(self.source.read_bytes(), 'smi'), C.identities((self.root / 'roundtrip.smi').read_bytes(), 'smi'))

    @unittest.skipUnless(ARGS.molecular, 'Optional Open Babel/RDKit runtime not requested')
    def test_invalid_input_and_oversized_molecule_count_rejected(self):
        from rdkit import Chem  # explicit missing dependency is a failure
        for raw in (b'', b'not-a-smiles\n', b'CCO\n' * 33):
            with self.subTest(raw=raw[:25]):
                self.source.write_bytes(raw)
                with patch.object(C, 'bounded_process', side_effect=AssertionError('Engine must not run')):
                    with self.assertRaises(ValueError): C.convert(self.args)

    @unittest.skipUnless(ARGS.molecular, 'Optional Open Babel/RDKit runtime not requested')
    def test_exit_zero_wrong_identity_and_damaged_stereo_rejected(self):
        self.args.executable = ARGS.executable
        for source, wrong in [('CCO\n', 'CCN\n'), ('F/C=C/F\n', 'FC=CF\n'), ('C[C@H](O)C(=O)O\n', 'CC(O)C(=O)O\n')]:
            self.source.write_text(source, encoding='utf-8'); self.args.output_format = 'smi'
            def fake(argv, directory, timeout, watched=()):
                if '-V' in argv:
                    return {'returncode': 0, 'stdout': 'Open Babel fixture', 'stderr': ''}
                Path(argv[argv.index('-O') + 1]).write_text(wrong, encoding='utf-8')
                return {'returncode': 0, 'stdout': '1 molecule converted', 'stderr': ''}
            with patch.object(C, 'bounded_process', side_effect=fake):
                result, artifact = C.convert(self.args)
            self.assertFalse(result['passed']); self.assertIsNone(artifact)
            self.assertFalse(self.output.exists())

    @unittest.skipUnless(ARGS.molecular, 'Optional Open Babel/RDKit runtime not requested')
    def test_failed_engine_logs_retained(self):
        self.args.executable = ARGS.executable
        def fake(argv, directory, timeout, watched=()):
            return {'returncode': 0, 'stdout': 'Open Babel fixture', 'stderr': ''} if '-V' in argv else {
                'returncode': -9, 'stdout': '', 'stderr': 'recorded failure', 'error': 'Engine timeout'}
        with patch.object(C, 'bounded_process', side_effect=fake): result, artifact = C.convert(self.args)
        self.assertFalse(result['passed']); self.assertIsNone(artifact)
        self.assertEqual(result['execution']['stderr'], 'recorded failure')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *REST])
