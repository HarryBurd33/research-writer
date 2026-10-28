#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline SSH client/state/collection contracts; no service is contacted."""
import base64
import copy
import hashlib
import importlib.util
import json
import time
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts/remote_tools.py'
spec=importlib.util.spec_from_file_location('remote_client',SCRIPT)
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)

class ClientChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.p=C.profile({'schema_version':1,'ssh_alias':'chosen-alias','remote_python':'python3',
            'remote_root':'/tmp/research-jobs','expected_hostname':'chosen-host','expected_user':'chosen-user'})
        self.m={'schema_version':1,'job_id':'a'*32,'argv':['python3','task.py'],
            'inputs':[],'outputs':['result.txt'],'required_device':'cpu',
            'resources':{'wall_seconds':10,'max_output_bytes':1024,'max_log_bytes':1024,'threads':1}}
        self.manifest=self.root/'task.json';self.manifest.write_text(json.dumps(self.m),encoding='utf-8')
        self.states=self.root/'state'
    def tearDown(self):self.temp.cleanup()
    def response(self,status='prepared',ok=True):
        return {'protocol':1,'ok':ok,'status':status,'identity':{'hostname':'chosen-host','user':'chosen-user'},
            'job_id':self.m['job_id'],'manifest_sha256':C.digest(C.canonical(self.m))}
    def prepare(self):
        with patch.object(C,'rpc',return_value=self.response()):
            return C.prepare(self.p,self.manifest,self.states,True)
    def test_profile_alias_unknown_fields_and_pins(self):
        for field,value in [('ssh_alias','-oProxyCommand=bad'),('ssh_alias','host; touch X'),
                            ('ssh_alias','user@host'),('password','secret'),('remote_python','python3; bad'),
                            ('remote_root','/'),('connect_timeout_seconds',True)]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                C.profile({**self.p,field:value})
        p={**self.p,'expected_hostname':None}
        with self.assertRaises(ValueError):C.prepare(p,self.manifest,self.states,True)
    def test_strict_ssh_short_command_data_not_interpolated(self):
        args=C.ssh_argv(self.p)
        self.assertIn('BatchMode=yes',args);self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertIn('ClearAllForwardings=yes',args);self.assertNotIn('-n',args)
        self.assertEqual(shlex.split(args[-1]),['python3','-c',C.BOOTSTRAP])
        self.assertLess(len(args[-1]),2048)
        self.assertNotIn('def ',args[-1]);self.assertNotIn('job_id',args[-1])
        spaced={**self.p,'remote_python':"/tmp/python's directory/python3"}
        self.assertEqual(shlex.split(C.ssh_argv(spaced)[-1])[0],spaced['remote_python'])
    def test_bootstrap_long_source_uses_bounded_stdin_not_command_line(self):
        source = '# padding\n' * 10000 + 'import json,sys; print(json.dumps(json.load(sys.stdin.buffer)))'
        request = {'literal': "a quote ' and $(not-executed)", 'protocol': 1}
        envelope = C.canonical({'source': source, 'request': request})
        args = [sys.executable, '-c', C.BOOTSTRAP]
        self.assertLess(len(args[-1]), 2048)
        self.assertNotIn(source, args)
        result = subprocess.run(args, input=envelope, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), request)

    def test_json_and_manifest_invalid_values(self):
        for raw in ['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}']:
            with self.assertRaises(ValueError):C.decode_json(raw)
        for change in [{'required_device':'cuda'},{'job_id':'../bad'}, {'outputs':['../outside']},
                       {'outputs':['/outside']},{'outputs':['.collection.json']}, {'outputs':['x','x/y']}]:
            with self.subTest(change=change),self.assertRaises(ValueError):C.validate_manifest({**self.m,**change})
        m=copy.deepcopy(self.m);m['resources']['wall_seconds']=True
        with self.assertRaises(ValueError):C.validate_manifest(m)
    def test_explicit_transfer_and_execute_required(self):
        with patch.object(C,'rpc',side_effect=AssertionError('No connection')):
            with self.assertRaises(ValueError):C.prepare(self.p,self.manifest,self.states,False)
        self.prepare()
        with patch.object(C,'rpc',side_effect=AssertionError('No connection')):
            with self.assertRaises(ValueError):C.operate(self.p,'submit','a'*32,self.states)
            with self.assertRaises(ValueError):C.operate(self.p,'cancel','a'*32,self.states)
    def test_inputs_hash_path_credential_and_symlink(self):
        path=self.root/'input.txt';path.write_bytes(b'payload')
        m=copy.deepcopy(self.m);m['inputs']=[{'source':'input.txt','destination':'input.txt','sha256':C.digest(b'payload')}]
        self.assertEqual(base64.b64decode(C.input_files(m,self.root)[0]['data']),b'payload')
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):C.input_files(m,self.root)
        for value in ['../escape','C:/escape','folder/../../escape','.ssh/key','.env','x\\..\\escape']:
            with self.subTest(value=value),self.assertRaises(ValueError):C.relative(value)
    def test_prepare_intent_before_transport_and_no_second_prepare(self):
        def fail(p,request):
            self.assertTrue((self.states/('a'*32+'.json')).exists())
            raise C.TransportError('255 after remote accepted')
        with patch.object(C,'rpc',side_effect=fail) as call:
            with self.assertRaises(C.TransportError):C.prepare(self.p,self.manifest,self.states,True)
            with self.assertRaises(FileExistsError):C.prepare(self.p,self.manifest,self.states,True)
        self.assertEqual(call.call_count,1)
        self.assertEqual(C.read_json(self.states/('a'*32+'.json'))['status'],'uncertain')
    def test_submit_loss_restart_status_never_resubmits(self):
        self.prepare()
        def fail(p,request):
            state=C.read_json(self.states/('a'*32+'.json'))
            self.assertTrue(state['submit_attempted']);raise C.TransportError('lost accepted reply')
        with patch.object(C,'rpc',side_effect=fail) as call:
            with self.assertRaises(C.TransportError):C.operate(self.p,'submit','a'*32,self.states,True)
            with self.assertRaises(ValueError):C.operate(self.p,'submit','a'*32,self.states,True)
        self.assertEqual(call.call_count,1)
        with patch.object(C,'rpc',return_value=self.response('running')) as call:
            result=C.operate(self.p,'status','a'*32,self.states)
        self.assertEqual(result['status'],'running');self.assertEqual(call.call_args.args[1]['operation'],'status')
        with patch.object(C,'rpc',side_effect=AssertionError('No resubmit')):
            with self.assertRaises(ValueError):C.operate(self.p,'submit','a'*32,self.states,True)
    def test_controller_source_bound_before_submission(self):
        self.prepare()
        state_file=self.states/('a'*32+'.json')
        state=C.read_json(state_file)
        self.assertEqual(state['worker_sha256'],C.digest(C.read_bytes(C.ROOT/'remote_worker.py')))
        state['worker_sha256']='0'*64;C.save(state_file,state)
        with patch.object(C,'rpc',side_effect=AssertionError('Changed controller must not execute')):
            with self.assertRaises(ValueError):C.operate(self.p,'submit','a'*32,self.states,True)

    def test_response_identity_hash_and_protocol_must_match(self):
        request=C.base_request(self.p,'status','a'*32,C.digest(C.canonical(self.m)))
        good=self.response('running');C.validate_response(good,self.p,request)
        variants=[{**good,'protocol':True},{**good,'job_id':'b'*32},{**good,'manifest_sha256':'0'*64},
                  {**good,'status':'invented'},{**good,'identity':{'hostname':'other','user':'chosen-user'}}]
        for result in variants:
            with self.subTest(result=result),self.assertRaises(C.TransportError):C.validate_response(result,self.p,request)
    def test_concurrent_and_changed_profile_refused(self):
        with C.local_lock(self.states,'a'*32):
            with self.assertRaises(ValueError):C.prepare(self.p,self.manifest,self.states,True)
        self.prepare()
        with self.assertRaises(ValueError):C.operate({**self.p,'ssh_alias':'other'},'status','a'*32,self.states)
    def test_abrupt_client_death_releases_lock_but_never_submission_intent(self):
        self.prepare()
        state_file=self.states/('a'*32+'.json')
        state=C.read_json(state_file);state.update(submit_attempted=True,status='uncertain');C.save(state_file,state)
        ready=self.root/'lock-ready'
        code=("import importlib.util,sys,time;from pathlib import Path;"
              "s=importlib.util.spec_from_file_location('client',sys.argv[1]);"
              "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
              "ctx=m.local_lock(sys.argv[2],'a'*32);ctx.__enter__();"
              "Path(sys.argv[3]).write_text('held');time.sleep(60)")
        child=subprocess.Popen([sys.executable,'-c',code,str(SCRIPT),str(self.states),str(ready)])
        try:
            deadline=time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(ready.exists(),'child failed to acquire lock')
            with self.assertRaises(ValueError):
                with C.local_lock(self.states,'a'*32):pass
            child.kill();child.wait(timeout=5)
            with patch.object(C,'rpc',return_value=self.response('running')):
                self.assertEqual(C.operate(self.p,'status','a'*32,self.states)['status'],'running')
            with patch.object(C,'rpc',side_effect=AssertionError('No repeat submission')):
                with self.assertRaises(ValueError):C.operate(self.p,'submit','a'*32,self.states,True)
            self.assertTrue((self.states/('.'+'a'*32+'.lock')).is_file())
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)

    def artifact_result(self,status='succeeded',raw=b'result',partial=False):
        return {**self.response(status),'partial':partial,'missing':[],
                'files':[{'path':'result.txt','sha256':C.digest(raw),'data':base64.b64encode(raw).decode()}]}
    def test_collection_hash_confinement_no_overwrite_and_atomic_stage(self):
        result=self.artifact_result();destination=self.root/'collected'
        summary=C.collect_files(result,self.m,destination)
        self.assertFalse(summary['partial']);self.assertEqual((destination/'result.txt').read_bytes(),b'result')
        with self.assertRaises(FileExistsError):C.collect_files(result,self.m,destination)
        for bad in [dict(result,files=[{**result['files'][0],'sha256':'0'*64}]),
                    dict(result,files=[{**result['files'][0],'path':'../escape'}]),
                    dict(result,files=[]),dict(result,status='running')]:
            target=self.root/'rejected'
            with self.assertRaises(ValueError):C.collect_files(bad,self.m,target)
            self.assertFalse(target.exists())
    def test_large_collection_preserves_restart_state_without_raw_payload(self):
        self.prepare()
        state_file=self.states/('a'*32+'.json')
        state=C.read_json(state_file);state['manifest']['resources']['max_output_bytes']=2*1024*1024
        state['manifest_sha256']=C.digest(C.canonical(state['manifest']));C.save(state_file,state)
        raw=b'x'*(900*1024)
        result={**self.artifact_result(raw=raw),'manifest_sha256':state['manifest_sha256'],
                'logs':{'stdout.log':{'data':base64.b64encode(raw).decode(),'sha256':C.digest(raw)}}}
        with patch.object(C,'rpc',return_value=result):
            C.operate(self.p,'collect','a'*32,self.states,destination=self.root/'large')
        self.assertLess(state_file.stat().st_size,64*1024)
        saved=C.load_state(state_file,self.p,'a'*32)
        self.assertNotIn('data',saved['last_remote']['files'][0])
        self.assertNotIn('data',saved['last_remote']['logs']['stdout.log'])
        with patch.object(C,'rpc',return_value={**self.response('succeeded'),'manifest_sha256':state['manifest_sha256']}):
            self.assertEqual(C.operate(self.p,'status','a'*32,self.states)['status'],'succeeded')

    def test_failed_partial_artifacts_remain_honest(self):
        result={**self.artifact_result('failed',partial=True),'files':[]}
        summary=C.collect_files(result,self.m,self.root/'partial')
        self.assertTrue(summary['partial']);self.assertEqual(summary['status'],'failed')
        self.assertEqual(summary['missing'],['result.txt'])
    def test_status_does_not_execute(self):
        self.prepare()
        with patch.object(C,'rpc',return_value=self.response('prepared')) as call:
            C.operate(self.p,'status','a'*32,self.states)
        self.assertEqual(call.call_args.args[1]['operation'],'status')

if __name__=='__main__':unittest.main()
