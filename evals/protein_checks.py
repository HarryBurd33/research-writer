#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline contracts by default; --protein --model-dir PATH requires real CPU inference."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts/protein_tools.py'
spec=importlib.util.spec_from_file_location('protein_tested',SCRIPT)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--protein',action='store_true');parser.add_argument('--model-dir')
ARGS,REST=parser.parse_known_args()

class ProteinChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_fasta_identity_bounds_and_no_mapping(self):
        good=P.fasta(b'>one\nACD\nEF\n>two\nW\n')
        self.assertEqual([r['sequence'] for r in good],['ACDEF','W'])
        self.assertEqual(good[0]['sequence_sha256'],hashlib.sha256(b'ACDEF').hexdigest())
        for raw in [b'',b'ACD',b'>x\n',b'>x\nACX\n',b'>x\nac\n',b'>x\nUO\n',b'>x\nA\n>x\nC',b'>x\n'+b'A'*513,b'>x\nA C']:
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):P.fasta(raw)
        with self.assertRaises(ValueError):P.fasta((''.join('>'+str(i)+'\nA\n' for i in range(17))).encode())
    def test_prepare_requires_explicit_network_choice(self):
        with patch.object(P.urllib.request,'build_opener',side_effect=AssertionError('No HTTP')):
            with self.assertRaises(ValueError):P.prepare_model(self.root/'new',False)
        self.assertFalse((self.root/'new').exists())
    def test_pinned_model_and_missing_hash_corruption(self):
        self.assertEqual(P.REVISION,'c731040fcd8d73dceaa04b0a8e6329b345b0f5df')
        self.assertEqual(P.FILES['model.safetensors'],(31384292,'24c5fa474c48f3b754b86efe752d5f189d2bcd88190fa2270fc92b2ef3034189'))
        with self.assertRaises(ValueError):P.verify_model(self.root)
        config=json.dumps({'hidden_size':320,'num_hidden_layers':6,'model_type':'esm'}).encode()
        (self.root/'config.json').write_bytes(config)
        with patch.object(P,'FILES',{'config.json':(len(config),P.sha(config))}):
            self.assertEqual(P.verify_model(self.root),self.root.resolve())
            (self.root/'config.json').write_bytes(b'X'*len(config))
            with self.assertRaises(ValueError):P.verify_model(self.root)
    def test_extra_sidecar_and_symlink_assets_rejected(self):
        config=json.dumps({'hidden_size':320,'num_hidden_layers':6,'model_type':'esm'}).encode()
        config_path=self.root/'config.json';config_path.write_bytes(config)
        with patch.object(P,'FILES',{'config.json':(len(config),P.sha(config))}):
            P.verify_model(self.root)
            extra=self.root/'added_tokens.json';extra.write_text('{}')
            with self.assertRaises(ValueError):P.verify_model(self.root)
            extra.unlink();config_path.unlink()
            target=self.root/'target';target.write_bytes(config)
            try:config_path.symlink_to(target)
            except OSError:self.skipTest("OS refused symlink creation; extra-sidecar rejection was exercised")
            # Keep only the expected name in the directory; the symlink itself
            # must fail even if its content hash is pinned and target is inside.
            with patch.object(Path,'iterdir',return_value=iter([config_path])):
                with self.assertRaises(ValueError):P.verify_model(self.root)
    def test_no_clobber_and_distinct_outputs(self):
        output=self.root/'existing.json';output.write_text('customized')
        args=types.SimpleNamespace(timeout=30,threads=1,output=str(output),embedding_output=str(self.root/'new.json'))
        with patch.object(P,'verify_model',side_effect=AssertionError('Should fail before model access')):
            with self.assertRaises(FileExistsError):P.embed(args)
        self.assertEqual(output.read_text(),'customized')
        with self.assertRaises(FileExistsError):P.prepare_model(self.root,True)
    def test_timeout_no_unbounded_worker(self):
        source=self.root/'x.fa';source.write_text('>x\nACD\n')
        args=types.SimpleNamespace(timeout=1,threads=1,output=str(self.root/'report.json'),embedding_output=str(self.root/'emb.json'),input=str(source),model_dir=str(self.root),device='cpu')
        with patch.object(P,'verify_model',return_value=self.root),patch.object(P,'run_worker',side_effect=subprocess.TimeoutExpired('fixture',1)) as call:
            with self.assertRaises(subprocess.TimeoutExpired):P.embed(args)
        self.assertEqual(call.call_args.args[2],1)
        self.assertFalse((self.root/'emb.json').exists())
    def test_actual_worker_timeout_and_log_limit(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            P.run_worker([sys.executable,'-c','import time; time.sleep(10)'],self.root,0.1)
        (self.root/'worker.log').unlink()
        with self.assertRaises(ValueError):
            P.run_worker([sys.executable,'-c','import sys;sys.stdout.write("x"*2097152)'],self.root,5)
    def test_internal_worker_revalidates_bounds(self):
        with self.assertRaises(ValueError):P.compute({'records':[],'threads':1,'device':'cpu'})
        with self.assertRaises(ValueError):P.compute({'records':[{'id':'x','sequence':'X','sequence_sha256':'fake'}],'threads':1,'device':'cpu'})
    def test_devices_no_silent_fallback(self):
        torch=types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda:False),version=types.SimpleNamespace(hip=None),backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda:False)))
        self.assertEqual(P.select_device(torch,'auto'),'cpu')
        for request in ['cuda','mps']:
            with self.assertRaises(ValueError):P.select_device(torch,request)
    def test_worker_values_identity_dimension_and_boolean_rejection(self):
        source=P.fasta(b'>x\nACD\n')
        result={'device':'cpu','records':[{'id':'x','sequence_sha256':source[0]['sequence_sha256'],'length':3,'embedding':[0.0]*320}]}
        P.validate_result(result,source)
        for vector in [[0.0]*319,[float('nan')]*320,[True]*320]:
            result['records'][0]['embedding']=vector
            with self.assertRaises(ValueError):P.validate_result(result,source)
        result['records'][0]['embedding']=[0.0]*320;result['records'][0]['id']='other'
        with self.assertRaises(ValueError):P.validate_result(result,source)
    def test_download_boundaries(self):
        for url in ['http://huggingface.co/file','https://evil.invalid/model','https://huggingface.co.evil.invalid/model','https://user:pass@huggingface.co/model','https://127.0.0.1/model']:
            self.assertFalse(P.allowed_download(url),url)
        self.assertTrue(P.allowed_download('https://cas-bridge.xethub.hf.co/model'))
    def test_cli_invalid_chemistry_failure_is_retained(self):
        source=self.root/'bad.fa';source.write_text('>bad\nACX\n')
        report=self.root/'failure.json';artifact=self.root/'absent.json'
        result=subprocess.run([sys.executable,str(SCRIPT),'embed','--input',str(source),'--model-dir',str(self.root/'unprovisioned'),'--output',str(report),'--embedding-output',str(artifact)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertFalse(json.loads(report.read_text())['executed_successfully'])
        self.assertFalse(artifact.exists())
    def test_help_without_model_or_torch(self):
        result=subprocess.run([sys.executable,str(SCRIPT),'--help'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
    @unittest.skipUnless(ARGS.protein,'Optional provisioned protein environment not requested')
    def test_actual_cpu_embedding_and_independent_masked_lm_reference(self):
        self.assertTrue(ARGS.model_dir,'--protein requires --model-dir')
        model_dir=P.verify_model(ARGS.model_dir)
        source=self.root/'input.fa';sequence='ACDEFGHIKLMNPQRSTVWY'
        source.write_text('>control\n'+sequence+'\n>repeat\n'+sequence+'\n>contrast\nAAAAACCCCC\n')
        report=self.root/'report.json';artifact=self.root/'embedding.json'
        result=subprocess.run([sys.executable,str(SCRIPT),'embed','--input',str(source),'--model-dir',str(model_dir),'--device','cpu','--output',str(report),'--embedding-output',str(artifact),'--timeout','120'],capture_output=True,text=True,timeout=135)
        self.assertEqual(result.returncode,0,result.stderr)
        d=json.loads(report.read_text());a=json.loads(artifact.read_text())
        self.assertEqual(d['device'],'cpu');self.assertEqual(d['scientific_validation'],'not_performed')
        self.assertEqual(d['artifact']['sha256'],hashlib.sha256(artifact.read_bytes()).hexdigest())
        vectors=[r['embedding'] for r in a['records']]
        self.assertTrue(all(len(v)==320 and all(math.isfinite(x) for x in v) for v in vectors))
        self.assertLess(max(abs(x-y) for x,y in zip(vectors[0],vectors[1])),1e-6)
        self.assertGreater(max(abs(x-y) for x,y in zip(vectors[0],vectors[2])),1e-5)
        # A separately invoked official masked-LM path supplies a reference;
        # pool only residue positions, not the model's BOS representation.
        import torch
        from transformers import EsmForMaskedLM,EsmTokenizer
        torch.set_num_threads(1)
        tokenizer=EsmTokenizer.from_pretrained(str(model_dir),local_files_only=True,token=False)
        model=EsmForMaskedLM.from_pretrained(str(model_dir),local_files_only=True,token=False,use_safetensors=True)
        model.eval()
        with torch.inference_mode():
            out=model(**tokenizer(sequence,return_tensors='pt'),output_hidden_states=True)
            reference=out.hidden_states[-1][0,1:len(sequence)+1].mean(dim=0).tolist()
        self.assertLess(max(abs(x-y) for x,y in zip(vectors[0],reference)),1e-5)

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+REST)
