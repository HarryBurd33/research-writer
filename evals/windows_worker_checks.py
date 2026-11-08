#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native Windows lifecycle checks; portable path checks do not claim runtime proof."""
import base64
import getpass
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/research-writer/scripts'
sys.path.insert(0,str(SCRIPTS))
import windows_worker as w


class Paths(unittest.TestCase):
    def test_rejected_aliases(self):
        for path in ('../x','C:foo','C:/foo','//server/share','\\\\?\\C:\\x','a:stream','NUL','con.txt','COM1.csv','COM¹.txt','LPT²','CONIN$','trailing.','trail ','a\\b','.env.secret'):
            with self.subTest(path=path),self.assertRaises(ValueError): w.relative(path)

    def test_unsupported_roots(self):
        for path in ('//server/share/jobs',r'\\?\C:\jobs',r'\\.\C:\jobs','C:relative'):
            with self.subTest(path=path),self.assertRaises(ValueError):w.root_path(path)

    def test_unicode_spaces(self):
        self.assertEqual(w.relative('some space/研究.txt'),'some space/研究.txt')

    def test_casefold_and_parent_collisions(self):
        for outputs in (['A','a'],['A','a/b']):
            m=manifest(['ignored']);m['outputs']=outputs
            with self.assertRaises(ValueError): w.validate_manifest(m)


def manifest(argv,wall=10):
    return {'schema_version':1,'job_id':uuid.uuid4().hex,'argv':argv,'inputs':[],
            'outputs':['result.txt'],'resources':{'wall_seconds':wall,'max_output_bytes':4096,
            'max_log_bytes':4096,'threads':1},'required_device':'cpu'}


@unittest.skipUnless(os.name=='nt','requires native Windows; no platform mocking')
class NativeWindows(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rw windows 研究 ');self.root=Path(self.temp.name)/'jobs'
        self.jobs=[]

    def tearDown(self):
        for identity in self.jobs:
            child=w._LOCAL_CONTROLLERS.pop(identity,None)
            if child and child.poll() is None:
                child.kill();child.wait(timeout=5)
        self.temp.cleanup()

    def request(self,m,op):
        return {'protocol':1,'operation':op,'remote_root':str(self.root),
                'expected_hostname':socket.gethostname(),'expected_user':getpass.getuser(),
                'job_id':m['job_id'],'manifest_sha256':w.digest(w.canonical(m))}

    def prepare(self,code,wall=10):
        m=manifest([sys.executable,'-c',code],wall);r=self.request(m,'prepare')
        r.update(manifest=m,files=[],worker_source=Path(w.__file__).read_text(encoding='utf-8'))
        result=w.handle(r);self.assertTrue(result['ok'],result);self.jobs.append(m['job_id']);return m

    def call(self,m,op):
        result=w.handle(self.request(m,op));self.assertTrue(result['ok'],result);return result

    def terminal(self,m):
        end=time.monotonic()+20
        while time.monotonic()<end:
            result=self.call(m,'status')
            if result['status'] in w.TERMINAL: return result
            time.sleep(.1)
        self.fail('No terminal state: '+str(result))

    def test_roundtrip_and_restart_and_no_duplicate(self):
        m=self.prepare("from pathlib import Path; Path('result.txt').write_text('研究',encoding='utf-8')")
        self.call(m,'submit');self.assertTrue(self.call(m,'submit')['already_submitted'])
        self.assertEqual(self.terminal(m)['status'],'succeeded')
        # A fresh interpreter obtains status from immutable filesystem state.
        result=subprocess.run([sys.executable,str(SCRIPTS/'windows_worker.py')],input=w.canonical(self.request(m,'recover')),
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True)
        self.assertEqual(w.parse(result.stdout)['status'],'succeeded')
        collected=self.call(m,'collect');raw=base64.b64decode(collected['files'][0]['data'])
        self.assertEqual(raw.decode(),'研究');self.assertEqual(w.digest(raw),collected['files'][0]['sha256'])
        path=self.root/m['job_id']/'work/result.txt';path.write_text('tampered')
        self.assertFalse(w.handle(self.request(m,'collect'))['ok'])

    def test_nonzero_and_output_bound(self):
        for code in ('raise SystemExit(7)',"from pathlib import Path;Path('result.txt').write_bytes(b'x'*8192)"):
            m=self.prepare(code);self.call(m,'submit');self.assertEqual(self.terminal(m)['status'],'failed')

    def test_timeout_and_cancel_kill_grandchild(self):
        for cancel in (False,True,True,True):
            code="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',\"import time;from pathlib import Path;time.sleep(3);Path('escaped.txt').write_text('bad')\"]);time.sleep(10)"
            m=self.prepare(code,wall=1 if not cancel else 10);self.call(m,'submit')
            if cancel:
                end=time.monotonic()+5
                while self.call(m,'status')['status']!='running' and time.monotonic()<end: time.sleep(.05)
                self.call(m,'cancel')
            terminal=self.terminal(m)
            self.assertEqual(terminal['status'],'cancelled' if cancel else 'timed_out',terminal)
            time.sleep(3.2);self.assertFalse((self.root/m['job_id']/'work/escaped.txt').exists())

    def test_controller_loss_stays_uncertain_and_kills_tree(self):
        m=self.prepare("import time;from pathlib import Path;time.sleep(3);Path('result.txt').write_text('bad')")
        self.call(m,'submit')
        end=time.monotonic()+5
        while self.call(m,'status')['status']!='running' and time.monotonic()<end: time.sleep(.05)
        child=w._LOCAL_CONTROLLERS.pop(m['job_id']);child.kill();child.wait(timeout=5)
        time.sleep(5.5)
        self.assertEqual(self.call(m,'recover')['status'],'uncertain')
        self.assertFalse((self.root/m['job_id']/'work/result.txt').exists())
        self.assertTrue(self.call(m,'submit')['already_submitted'])

    def test_junction_rejection(self):
        outside=Path(self.temp.name)/'outside';outside.mkdir();self.root.mkdir()
        junction=self.root/'jump'
        subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],check=True,capture_output=True)
        try:
            with self.assertRaises(ValueError): w.root_path(str(junction))
        finally: junction.rmdir()


if __name__=='__main__': unittest.main()
