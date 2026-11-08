#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Portable fail-closed contracts; fabricated records/mocks are never GPU acceptance."""
import copy
import getpass
import math
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts'
sys.path.insert(0,str(SCRIPTS))
import accelerator_tools as a


def profile(device='cuda:0'):
    return {'contract':a.CONTRACT,'expected_hostname':socket.gethostname(),'expected_user':getpass.getuser(),
            'device':device,'wall_seconds':30,'max_log_bytes':65536,'max_result_bytes':a.MAX_BYTES,
            'max_accelerator_memory_bytes':512*1024**2,'threads':1}


def request(device='cuda:0'):
    return {'contract':a.CONTRACT,'job_id':'1'*32,'profile':profile(device),'model_dir':'/not-executed',
            'input_sha256':a.protein.sha(a.CONTROL),'source_hashes':a.source_hashes(),
            'model_assets':{k:{'bytes':v[0],'sha256':v[1]} for k,v in a.protein.FILES.items()}}


def synthetic_result(r):
    shape=[1,len(a.protein.fasta(a.CONTROL)[0]['sequence'])+2,320];values=[0.125]*math.prod(shape)
    device='mps:0' if r['profile']['device']=='mps' else r['profile']['device'];backend='mps' if device=='mps:0' else 'cuda'
    return {k:r[k] for k in ('contract','job_id','input_sha256','model_assets','source_hashes')} | {
        'request_sha256':a.common.digest(a.common.canonical(r)),'model':a.protein.MODEL,'revision':a.protein.REVISION,
        'identity':a.identity(),'shape':shape,'dtype':'float32','device_observed':device,
        'model_tensor_devices':[device],'input_tensor_devices':{'input_ids':device},'cpu_reference_device':'cpu',
        'accelerator':{'backend':backend,'index':None if backend=='mps' else int(device.split(':')[1]),
            'synchronized':True,'cpu_fallback_enabled':False,'allocated_bytes':1000,
            'allocator_budget_bytes':r['profile']['max_accelerator_memory_bytes']},
        'accelerator_values':values,'cpu_reference_values':values[:],
        'accelerator_tensor_sha256':a.tensor_digest(values),'cpu_reference_tensor_sha256':a.tensor_digest(values),
        'comparison':a.compare(values,values)}


class AcceleratorContracts(unittest.TestCase):
    def test_selected_devices_only(self):
        for device in ('cuda:0','cuda:15','mps'):self.assertEqual(a.profile(profile(device))['device'],device)
        for device in ('auto','cpu','cuda','cuda:16','rocm:0','mps:0'):
            with self.subTest(device=device),self.assertRaises(ValueError):a.profile(profile(device))
    def test_identity_unknown_secret_and_bounds_rejected(self):
        for key,value in (('password','forbidden'),('expected_hostname','other'),('max_accelerator_memory_bytes',0),('threads',True)):
            with self.subTest(key=key),self.assertRaises(ValueError):a.profile({**profile(),key:value})
    def test_missing_cuda_and_rocm_no_fallback(self):
        for available,hip,count in ((False,None,0),(True,'6.0',1),(True,None,0)):
            torch=SimpleNamespace(version=SimpleNamespace(hip=hip),cuda=SimpleNamespace(is_available=lambda:available,device_count=lambda:count))
            with self.assertRaises(ValueError):a.require_cuda(torch,'cuda:0')
    def test_v1_remote_gpu_still_rejected(self):
        manifest={'schema_version':1,'job_id':'1'*32,'argv':['python'],'inputs':[],'outputs':['out'],
            'resources':{'wall_seconds':1,'max_output_bytes':1,'max_log_bytes':1,'threads':1},'required_device':'cuda'}
        with self.assertRaises(ValueError):a.storage.validate_manifest(manifest)
        with self.assertRaises(ValueError):a.common.validate_manifest(manifest)
    def test_frozen_tolerance_nonfinite_shape(self):
        self.assertEqual(a.compare([1.0005],[1.0])['elements'],1)
        for actual,reference in (([1.1],[1.0]),([float('nan')],[1.0]),([True],[1.0]),([],[]),([1],[1,2])):
            with self.assertRaises(ValueError):a.compare(actual,reference)
    def test_synthetic_record_contract_not_runtime_evidence(self):
        for device in ('cuda:0','mps'):
            r=request(device);result=synthetic_result(r)
            self.assertEqual(a.validate_result(result,r)['elements'],len(result['accelerator_values']))
    def test_cpu_output_or_input_or_model_cannot_pass(self):
        r=request()
        for key,value in (('device_observed','cpu'),('model_tensor_devices',['cpu']),('input_tensor_devices',{'input_ids':'cpu'}),('cpu_reference_device','cuda:0')):
            result=synthetic_result(r);result[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):a.validate_result(result,r)
    def test_tamper_and_reference_failure_rejected(self):
        r=request()
        for change in ('tensor','reference','comparison','input','memory','sync','fallback'):
            result=synthetic_result(r)
            if change=='tensor':result['accelerator_values'][0]=float('inf')
            elif change=='reference':result['cpu_reference_values'][0]=1.0
            elif change=='comparison':result['comparison']['max_absolute_difference']=99
            elif change=='input':result['input_sha256']='f'*64
            elif change=='memory':result['accelerator']['allocated_bytes']=2**40
            elif change=='sync':result['accelerator']['synchronized']=False
            else:result['accelerator']['cpu_fallback_enabled']=True
            with self.subTest(change=change),self.assertRaises(ValueError):a.validate_result(result,r)
    def test_exact_fixture_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'control.fasta'
            self.assertEqual(a.main(['fixture','--output',str(out)]),0);self.assertEqual(out.read_bytes(),a.CONTROL)
            self.assertEqual(a.main(['fixture','--output',str(out)]),2);self.assertEqual(out.read_bytes(),a.CONTROL)
    def test_stale_controller_uncertain_no_pid_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();a.common.save(root/'state.json',{'status':'running','heartbeat':1,'pid':12345})
            self.assertEqual(a.snapshot(root)['status'],'uncertain')
    def test_worker_requires_prepared_durable_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(a.main(['_worker','--directory',directory]),2)
    def test_run_permission_before_asset_or_process_access(self):
        with patch.object(a,'prepared',side_effect=AssertionError('must not inspect assets')):
            with self.assertRaises(ValueError):a.run('/unused',False)


if __name__=='__main__':unittest.main()
