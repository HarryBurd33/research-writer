#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Versioned local accelerator workload acceptance; separate from the v1 CPU remote protocol."""
from __future__ import annotations
import argparse
import getpass
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import protein_tools as protein
import remote_tools as common
import remote_worker as storage

CONTRACT='research-writer.accelerator-acceptance/1'
CONTROL=b'>accelerator-acceptance-control\nMKTIIALSYIFCLVFADYKDDDDK\n'
ATOL=0.0001
RTOL=0.001
MAX_BYTES=1024*1024
PROFILE_FIELDS={'contract','expected_hostname','expected_user','device','wall_seconds',
                'max_log_bytes','max_result_bytes','max_accelerator_memory_bytes','threads'}
SOURCE=Path(__file__).resolve()


def identity():
    return {'hostname':socket.gethostname(),'user':getpass.getuser(),'os':platform.system(),
            'machine':platform.machine(),'python':sys.executable,'python_version':platform.python_version()}


def profile(p):
    if not isinstance(p,dict) or set(p)!=PROFILE_FIELDS or p.get('contract')!=CONTRACT:
        raise ValueError('Exact accelerator workload profile required; store no secrets')
    if p['expected_hostname']!=socket.gethostname() or p['expected_user']!=getpass.getuser():
        raise ValueError('Selected host/user mismatch')
    if not isinstance(p['device'],str) or not re.fullmatch(r'(?:cuda:(?:[0-9]|1[0-5])|mps)',p['device']):
        raise ValueError('An explicit cuda:N or mps device is required; CPU/auto fallback forbidden')
    bounds={'wall_seconds':(1,120),'max_log_bytes':(1024,MAX_BYTES),
            'max_result_bytes':(65536,MAX_BYTES),'max_accelerator_memory_bytes':(128*1024**2,2*1024**3),'threads':(1,8)}
    for k,(low,high) in bounds.items():
        if type(p[k]) is not int or not low<=p[k]<=high:raise ValueError('Invalid bounded '+k)
    return p


def source_hashes():
    return {p.name:protein.sha(p.read_bytes()) for p in (SOURCE,Path(protein.__file__).resolve())}


def checked_path(path,directory=False):
    p=Path(path).absolute()
    for item in (p,*p.parents):
        if item.is_symlink() or (os.name=='nt' and item.exists() and item.lstat().st_file_attributes & 0x400):
            raise ValueError('Symlink/reparse acceptance path forbidden')
    if not (p.is_dir() if directory else p.is_file()):raise ValueError('Missing regular acceptance path')
    return p


def prepared(directory):
    root=checked_path(directory,True)
    request=common.read_json(checked_path(root/'request.json'))
    if set(request)!={'contract','job_id','profile','model_dir','input_sha256','source_hashes','model_assets'} or request['contract']!=CONTRACT:
        raise ValueError('Unknown accelerator request schema')
    common.job_id(request['job_id']);profile(request['profile'])
    if request['source_hashes']!=source_hashes():raise ValueError('Accepted workload source changed')
    if request['input_sha256']!=protein.sha(CONTROL) or checked_path(root/'control.fasta').read_bytes()!=CONTROL:
        raise ValueError('Frozen control input differs')
    if request['model_assets']!={k:{'bytes':v[0],'sha256':v[1]} for k,v in protein.FILES.items()}:
        raise ValueError('Pinned model asset identity differs')
    protein.verify_model(checked_path(request['model_dir'],True))
    pin=common.read_json(checked_path(root/'binding.json'))
    if pin!={'request_sha256':common.digest(common.canonical(request))}:
        raise ValueError('Immutable acceptance request binding differs')
    return root,request


def prepare(p,model_dir,input_path,directory):
    p=profile(p)
    if checked_path(input_path).read_bytes()!=CONTROL:raise ValueError('Use the exact frozen synthetic control fixture')
    model=protein.verify_model(checked_path(model_dir,True))
    target=Path(directory).absolute()
    if target.exists() or target.is_symlink():raise FileExistsError('Acceptance directory must be new')
    checked_path(target.parent,True)
    request={'contract':CONTRACT,'job_id':uuid.uuid4().hex,'profile':p,'model_dir':str(model),
             'input_sha256':protein.sha(CONTROL),'source_hashes':source_hashes(),
             'model_assets':{k:{'bytes':v[0],'sha256':v[1]} for k,v in protein.FILES.items()}}
    with tempfile.TemporaryDirectory(prefix='.accelerator-prepare-',dir=target.parent) as temp:
        stage=Path(temp)/'job';stage.mkdir()
        common.save(stage/'request.json',request,exclusive=True)
        common.save(stage/'binding.json',{'request_sha256':common.digest(common.canonical(request))},exclusive=True)
        (stage/'control.fasta').write_bytes(CONTROL)
        common.save(stage/'state.json',{'status':'prepared','job_id':request['job_id'],'contract':CONTRACT},exclusive=True)
        stage.rename(target)
    return {'status':'prepared','contract':CONTRACT,'job_id':request['job_id'],'directory':str(target),
            'request_sha256':common.digest(common.canonical(request)),'executed':False}


def require_cuda(torch,device):
    if getattr(torch.version,'hip',None) or not torch.cuda.is_available():
        raise ValueError('Actual NVIDIA CUDA required; no CPU/ROCm fallback')
    index=int(device.split(':')[1])
    if index>=torch.cuda.device_count():raise ValueError('Selected CUDA index does not exist')
    return index


def tensor_digest(values):
    return protein.sha(b''.join(struct.pack('<f',v) for v in values))


def compare(actual,reference):
    if not isinstance(actual,list) or not isinstance(reference,list) or len(actual)!=len(reference) or not actual:
        raise ValueError('Independent tensor shape/count mismatch')
    max_abs=0.0;max_ratio=0.0
    for x,y in zip(actual,reference):
        if type(x) not in (float,int) or type(y) not in (float,int) or not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Nonfinite/malformed numerical result')
        difference=abs(x-y);threshold=ATOL+RTOL*abs(y)
        max_abs=max(max_abs,difference);max_ratio=max(max_ratio,difference/threshold)
        if difference>threshold:raise ValueError('Frozen CUDA/CPU numerical tolerance exceeded')
    return {'atol':ATOL,'rtol':RTOL,'max_absolute_difference':max_abs,'max_tolerance_ratio':max_ratio,'elements':len(actual)}


def compute(request,directory):
    p=profile(request['profile'])
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
                      PYTORCH_ENABLE_MPS_FALLBACK='0',CUBLAS_WORKSPACE_CONFIG=':4096:8',
                      TORCH_ALLOW_TF32_CUBLAS_OVERRIDE='0',PYTORCH_NO_CUDA_MEMORY_CACHING='0',
                      PYTORCH_ALLOC_CONF='backend:native',PYTORCH_CUDA_ALLOC_CONF='backend:native')
    root=protein.verify_model(request['model_dir'])
    import torch
    import transformers
    from transformers import EsmModel,EsmTokenizer
    backend='mps' if p['device']=='mps' else 'cuda'
    if backend=='cuda':
        index=require_cuda(torch,p['device']);torch.cuda.set_device(index)
        props=torch.cuda.get_device_properties(index)
        total_memory=props.total_memory
        torch.cuda.set_per_process_memory_fraction(p['max_accelerator_memory_bytes']/total_memory,index)
        torch.cuda.reset_peak_memory_stats(index)
        synchronize=lambda:torch.cuda.synchronize(index)
        accelerator={'backend':'cuda','name':props.name,'index':index,
                     'capability':list(torch.cuda.get_device_capability(index)),
                     'uuid':str(getattr(props,'uuid','not_exposed')),'memory_measurement':'torch_cuda_allocator_exact_peaks'}
    else:
        if not hasattr(torch.backends,'mps') or not torch.backends.mps.is_available():
            raise ValueError('Actual Apple MPS required; no CPU fallback')
        if os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK')!='0':raise ValueError('MPS CPU fallback must be disabled')
        total_memory=torch.mps.recommended_max_memory()
        torch.mps.set_per_process_memory_fraction(p['max_accelerator_memory_bytes']/total_memory)
        synchronize=torch.mps.synchronize
        accelerator={'backend':'mps','name':platform.machine()+' Apple Metal MPS','index':None,
                     'memory_measurement':'mps_allocator_limit_and_terminal_observation_not_exact_peak'}
    if total_memory<p['max_accelerator_memory_bytes']:
        raise ValueError('Selected accelerator memory is below declared allocator budget')
    accelerator['total_memory_bytes']=total_memory
    torch.set_num_threads(p['threads']);torch.manual_seed(0)
    if backend=='cuda':torch.cuda.manual_seed_all(0)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.use_deterministic_algorithms(True)
    tokenizer=EsmTokenizer.from_pretrained(str(root),local_files_only=True,token=False)
    model=EsmModel.from_pretrained(str(root),local_files_only=True,token=False,use_safetensors=True,
                                  trust_remote_code=False,add_pooling_layer=False,attn_implementation='eager')
    model.eval();model=model.float()
    source=protein.fasta(CONTROL)[0];sequence=source['sequence']
    cpu_tokens=tokenizer(sequence,return_tensors='pt',truncation=False)
    shape=[1,len(sequence)+2,320]
    if list(cpu_tokens['input_ids'].shape)!=shape[:2]:raise ValueError('Tokenizer control length differs')
    # Independently execute the reference forward on the same pinned float32 model.
    with torch.inference_mode():cpu_states=model(**cpu_tokens).last_hidden_state
    if str(cpu_states.device)!='cpu' or list(cpu_states.shape)!=shape:raise ValueError('CPU reference device/shape mismatch')
    cpu_values=cpu_states.detach().flatten().tolist()
    expected_observed='mps:0' if p['device']=='mps' else p['device']
    model.to(p['device'])
    encoded={k:v.to(p['device']) for k,v in cpu_tokens.items()}
    observed_model=sorted({str(v.device) for v in [*model.parameters(),*model.buffers()]})
    observed_inputs={k:str(v.device) for k,v in encoded.items()}
    if observed_model!=[expected_observed] or set(observed_inputs.values())!={expected_observed}:
        raise ValueError('Model/input tensors did not reach the required actual CUDA device')
    synchronize()
    with torch.inference_mode():states=model(**encoded).last_hidden_state
    synchronize()
    observed_output=str(states.device)
    if observed_output!=expected_observed or list(states.shape)!=shape or states.dtype!=torch.float32:
        raise ValueError('Output tensor is not expected float32 CUDA hidden states')
    if not bool(torch.isfinite(states).all().item()):raise ValueError('CUDA output contains nonfinite values')
    values=states.detach().cpu().flatten().tolist()
    # This comparison is repeated independently by the controlling process from raw arrays.
    comparison=compare(values,cpu_values)
    peak_allocated=torch.cuda.max_memory_allocated(index) if backend=='cuda' else torch.mps.current_allocated_memory()
    peak_reserved=torch.cuda.max_memory_reserved(index) if backend=='cuda' else torch.mps.driver_allocated_memory()
    if peak_allocated>p['max_accelerator_memory_bytes'] or (backend=='cuda' and peak_reserved>p['max_accelerator_memory_bytes']):
        raise ValueError('CUDA allocator peak exceeded declared budget')
    accelerator.update(allocated_bytes=peak_allocated,reserved_or_driver_bytes=peak_reserved,synchronized=True,
                       allocator_budget_bytes=p['max_accelerator_memory_bytes'],cpu_fallback_enabled=False)
    protein.verify_model(root)
    return {'contract':CONTRACT,'job_id':request['job_id'],'input_sha256':request['input_sha256'],
        'request_sha256':common.digest(common.canonical(request)),'model':protein.MODEL,'revision':protein.REVISION,
        'model_assets':request['model_assets'],'source_hashes':request['source_hashes'],'identity':identity(),
        'device_requested':p['device'],'device_observed':observed_output,'model_tensor_devices':observed_model,
        'input_tensor_devices':observed_inputs,'cpu_reference_device':str(cpu_states.device),
        'accelerator':accelerator,
        'versions':{'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'transformers':transformers.__version__},
        'dtype':'float32','shape':shape,'accelerator_values':values,'cpu_reference_values':cpu_values,
        'accelerator_tensor_sha256':tensor_digest(values),'cpu_reference_tensor_sha256':tensor_digest(cpu_values),
        'comparison':comparison,'scientific_accuracy':'not_evaluated','transport_acceptance':'not_evaluated'}


def validate_result(result,request):
    p=request['profile'];expected={'contract':CONTRACT,'job_id':request['job_id'],
        'input_sha256':request['input_sha256'],'request_sha256':common.digest(common.canonical(request)),
        'model':protein.MODEL,'revision':protein.REVISION,'model_assets':request['model_assets'],'source_hashes':request['source_hashes']}
    if not isinstance(result,dict) or any(result.get(k)!=v for k,v in expected.items()):raise ValueError('Worker result immutable identity differs')
    ident=result.get('identity',{})
    if ident.get('hostname')!=p['expected_hostname'] or ident.get('user')!=p['expected_user']:raise ValueError('Worker host/user differs')
    shape=[1,len(protein.fasta(CONTROL)[0]['sequence'])+2,320]
    if result.get('shape')!=shape or result.get('dtype')!='float32':raise ValueError('Worker tensor representation differs')
    expected_observed='mps:0' if p['device']=='mps' else p['device']
    if result.get('device_observed')!=expected_observed or result.get('model_tensor_devices')!=[expected_observed] or result.get('cpu_reference_device')!='cpu':
        raise ValueError('No actual selected-device tensor evidence')
    devices=result.get('input_tensor_devices')
    if not isinstance(devices,dict) or 'input_ids' not in devices or set(devices.values())!={expected_observed}:raise ValueError('CUDA input tensor evidence missing')
    observed=result.get('accelerator',{})
    backend='mps' if p['device']=='mps' else 'cuda'
    if observed.get('synchronized') is not True or observed.get('backend')!=backend or observed.get('cpu_fallback_enabled') is not False:
        raise ValueError('Synchronized selected accelerator evidence missing')
    if backend=='cuda' and observed.get('index')!=int(p['device'].split(':')[1]):raise ValueError('CUDA index differs')
    if type(observed.get('allocated_bytes')) is not int or not 0<observed['allocated_bytes']<=p['max_accelerator_memory_bytes']:
        raise ValueError('Invalid accelerator allocator evidence')
    if observed.get('allocator_budget_bytes')!=p['max_accelerator_memory_bytes']:raise ValueError('Allocator budget differs')
    actual,reference=result.get('accelerator_values'),result.get('cpu_reference_values')
    if not isinstance(actual,list) or len(actual)!=math.prod(shape):raise ValueError('Hidden tensor element count differs')
    comparison=compare(actual,reference)
    if tensor_digest(actual)!=result.get('accelerator_tensor_sha256') or tensor_digest(reference)!=result.get('cpu_reference_tensor_sha256'):
        raise ValueError('Raw tensor checksum differs')
    if comparison!=result.get('comparison'):raise ValueError('Reported comparison differs from independently recomputed reference')
    return comparison


def stop(child):
    if child.poll() is None:
        if os.name=='posix':
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        else:child.kill()
    child.wait(timeout=5)


def snapshot(root):
    state=common.read_json(checked_path(root/'state.json'))
    if state['status']=='running' and time.time()-state.get('heartbeat',0)>5:
        return {**state,'status':'uncertain','reason':'Controller lost; never signal a saved PID or retry'}
    return state


def run(directory,allow_execute=False):
    if not allow_execute:raise ValueError('Explicit --allow-execute required')
    root,request=prepared(directory);p=request['profile']
    with common.local_lock(root,request['job_id']):
        if (root/'attempt.json').exists() or snapshot(root)['status']!='prepared':raise ValueError('Execution already attempted/not prepared: never retry uncertainty')
        # fsync durable dispatch intent before creating the workload process.
        storage.atomic(root/'attempt.json',{'job_id':request['job_id'],'request_sha256':common.digest(common.canonical(request))})
        state={'status':'running','job_id':request['job_id'],'heartbeat':time.time(),'contract':CONTRACT}
        storage.atomic(root/'state.json',state)
        child=None;started=time.monotonic()
        try:
            with (root/'worker.log').open('xb') as log:
                child=subprocess.Popen([sys.executable,str(SOURCE),'_worker','--directory',str(root)],stdin=subprocess.DEVNULL,
                    stdout=log,stderr=log,shell=False,start_new_session=os.name=='posix',
                    env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','PYTHONDONTWRITEBYTECODE':'1'})
                while child.poll() is None:
                    if (root/'cancel.request').exists():state.update(status='cancelled',reason='Owned controller observed cancellation');break
                    if time.monotonic()-started>p['wall_seconds']:state.update(status='timed_out',reason='Whole worker deadline exceeded');break
                    if (root/'worker.log').stat().st_size>p['max_log_bytes']:raise ValueError('Worker log budget exceeded')
                    if (root/'result.json').exists() and (root/'result.json').stat().st_size>p['max_result_bytes']:raise ValueError('Worker result budget exceeded')
                    state['heartbeat']=time.time();storage.atomic(root/'state.json',state);time.sleep(.05)
                if (root/'worker.log').stat().st_size>p['max_log_bytes']:raise ValueError('Worker log budget exceeded')
                if state['status']=='running':
                    if child.returncode:raise ValueError('CUDA worker exited nonzero; inspect bounded diagnostics')
                    raw=common.read_bytes(checked_path(root/'result.json'),p['max_result_bytes'])
                    result=common.decode_json(raw.decode());comparison=validate_result(result,request)
                    state.update(status='succeeded',result_sha256=protein.sha(raw),comparison=comparison)
        except Exception as exc:state.update(status='failed',reason=str(exc)[:1500])
        finally:
            if child is not None:
                try:stop(child)
                except Exception as exc:state.update(status='uncertain',reason='Live worker termination unproven: '+str(exc)[:500])
            log=root/'worker.log'
            if log.exists():
                with log.open('r+b') as stream:stream.truncate(min(log.stat().st_size,p['max_log_bytes']))
            state.update(finished_at=time.time(),elapsed_seconds=time.monotonic()-started)
            storage.atomic(root/'state.json',state)
        return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='operation',required=True)
    for op in ('fixture','inspect','prepare','run','status','recover','cancel','collect','_worker'):
        c=subs.add_parser(op)
        if op not in ('fixture','inspect'):c.add_argument('--directory',required=True)
        if op not in ('_worker',):c.add_argument('--output',required=True)
        if op=='prepare':
            for k in ('profile','input','model-dir'):c.add_argument('--'+k,required=True)
        if op=='run':c.add_argument('--allow-execute',action='store_true')
        if op=='cancel':c.add_argument('--allow-cancel',action='store_true')
    a=parser.parse_args(argv)
    try:
        if a.operation=='fixture':
            with Path(a.output).open('xb') as stream:stream.write(CONTROL)
            return 0
        if a.operation!='_worker' and (Path(a.output).exists() or Path(a.output).is_symlink()):raise ValueError('Output report exists')
        if a.operation=='inspect':result={'contract':CONTRACT,'identity':identity(),'execution_attempted':False,'gpu_acceptance':'not_tested'}
        elif a.operation=='prepare':result=prepare(common.read_json(a.profile),a.model_dir,a.input,a.directory)
        elif a.operation=='run':result=run(a.directory,a.allow_execute)
        else:
            root,request=prepared(a.directory)
            if a.operation=='_worker':
                attempt=common.read_json(checked_path(root/'attempt.json'))
                if attempt!={'job_id':request['job_id'],'request_sha256':common.digest(common.canonical(request))}:
                    raise ValueError('Missing/mismatched durable dispatch intent')
                result=compute(request,root);raw=common.canonical(result)+b'\n'
                if len(raw)>request['profile']['max_result_bytes']:raise ValueError('Tensor result budget exceeded')
                with (root/'result.json').open('xb') as stream:stream.write(raw)
                return 0
            result=snapshot(root)
            if a.operation=='cancel':
                if not a.allow_cancel:raise ValueError('Explicit --allow-cancel required')
                if result['status'] in ('prepared','running','uncertain'):
                    with (root/'cancel.request').open('ab'):pass
                if result['status']=='prepared':
                    result={**result,'status':'cancelled'};storage.atomic(root/'state.json',result)
                elif result['status'] in ('running','uncertain'):
                    with (root/'cancel.request').open('ab'):pass
                    result={**result,'cancel_requested':True}
            elif a.operation=='collect':
                if result['status']!='succeeded':raise ValueError('Only accepted checksummed GPU output can be collected')
                raw=common.read_bytes(checked_path(root/'result.json'),request['profile']['max_result_bytes'])
                if protein.sha(raw)!=result['result_sha256']:raise ValueError('Collected result changed')
                result=common.decode_json(raw.decode());validate_result(result,request)
        common.save(a.output,result,exclusive=True)
        return 0 if result.get('status') not in ('failed','uncertain','timed_out') else 2
    except Exception as exc:
        print(json.dumps({'contract':CONTRACT,'status':'failed','gpu_acceptance':False,'error':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
