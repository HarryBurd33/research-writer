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
import threading
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

    def test_native_reader_sharing_denial_then_bounded_atomic_retry(self):
        path=Path(self.temp.name)/'shared-state.json';w.atomic(path,{'value':'old'})
        source=Path(self.temp.name)/'raw-replacement.json';source.write_bytes(w.canonical({'value':'raw'}))
        reader=path.open('rb')
        try:
            try:os.replace(source,path)
            except PermissionError as exc:
                self.assertIn(getattr(exc,'winerror',None),(5,32,33))
                print('OBSERVED_NATIVE_REPLACE_DENIAL',exc.winerror,flush=True)
            else:self.fail('Native runtime did not reproduce reader-sharing denial; causal gate remains unproven')
            self.assertEqual(w.read_json(path),{'value':'old'})
            release=threading.Thread(target=lambda:(time.sleep(.1),reader.close()))
            release.start();started=time.monotonic()
            try:w.atomic(path,{'value':'updated'})
            finally:release.join(timeout=2)
            self.assertLess(time.monotonic()-started,1.5)
            self.assertEqual(w.read_json(path),{'value':'updated'})
            held=path.open('rb');started=time.monotonic()
            try:
                with self.assertRaises(PermissionError):w.atomic(path,{'value':'must-not-replace'})
                self.assertLess(time.monotonic()-started,1.5)
            finally:held.close()
            self.assertEqual(w.read_json(path),{'value':'updated'})
        finally:
            reader.close();source.unlink(missing_ok=True)

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

    def test_native_exclusive_handle_then_bounded_metadata_read(self):
        import ctypes
        from ctypes import wintypes
        path=Path(self.temp.name)/'read-state.json';w.atomic(path,{'value':'retained'})
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                    wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        self.assertNotEqual(handle,wintypes.HANDLE(-1).value)
        closed=threading.Event()
        def release():
            time.sleep(.1);kernel.CloseHandle(handle);closed.set()
        try:
            with self.assertRaises(PermissionError) as denied:path.open('rb')
            self.assertIn(denied.exception.winerror,(5,32,33))
            print('OBSERVED_NATIVE_READ_DENIAL',denied.exception.winerror,flush=True)
            reader_release=threading.Thread(target=release);reader_release.start();started=time.monotonic()
            try:self.assertEqual(w.read_json(path),{'value':'retained'})
            finally:reader_release.join(timeout=2)
            self.assertLess(time.monotonic()-started,1.5)
        finally:
            if not closed.is_set():kernel.CloseHandle(handle)

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
