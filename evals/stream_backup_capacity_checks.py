#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit real 512 MiB SQLite/loopback SSH acceptance; no fake-size positive fixture."""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import sqlite3
import sys
import time
import tracemalloc
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-ssh',action='store_true')
parser.add_argument('--report',type=Path)
parser.add_argument('--budget-seconds',type=int,default=720)
ARGS,REST=parser.parse_known_args()
saved=sys.argv;sys.argv=[str(ROOT/'evals/stream_backup_loopback_checks.py'),'--run-ssh']
try:
    spec=importlib.util.spec_from_file_location('capacity_fixture',ROOT/'evals/stream_backup_loopback_checks.py')
    F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)
finally:sys.argv=saved
S,C=F.S,F.C
CAP=536870912
GENERATION_BYTES=16*1024**2
GENERATION_COUNT=31


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for raw in iter(lambda:stream.read(1024**2),b''):h.update(raw)
    return h.hexdigest()


def packet(index):
    """Two distinct deterministic state payloads, each independently recoverable."""
    files=[]
    for name in ('first','second'):
        seed=f'research-writer-capacity-v1:generation={index}:artifact={name}'.encode()
        raw=hashlib.shake_256(seed).digest(8*1024**2)
        files.append({'path':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                      'data_base64':base64.b64encode(raw).decode()})
    files.append({'path':'zero','size':0,'sha256':hashlib.sha256(b'').hexdigest(),'data_base64':''})
    return {'schema_version':1,'checkpoint_id':uuid.uuid5(uuid.NAMESPACE_URL,f'rw-capacity-v1:{index}').hex,
            'application':{'format':'deterministic-state-fixture','version':'1','resume_notes':'Synthetic capacity fixture; not research data'},
            'provenance':{'kind':'local','manifest_sha256':hashlib.sha256(f'generation:{index}'.encode()).hexdigest()},
            'consistency':C.CONSISTENCY,'files':files}


def exact_sqlite_capacity(path):
    """Allocate real SQLite pages, then free only residual allocation, never pad bytes."""
    conn=sqlite3.connect(path,isolation_level=None)
    try:
        conn.execute('PRAGMA journal_mode=DELETE')
        conn.execute('PRAGMA auto_vacuum=NONE')
        conn.execute('PRAGMA max_page_count='+str(CAP//4096))
        before=conn.execute('PRAGMA page_count').fetchone()[0]
        if not 496*1024**2 <= path.stat().st_size < CAP:raise AssertionError('Need substantial stored payload before residual allocation')
        # These temporary rows allocate actual B-tree pages. Autocommit keeps a
        # near-cap SQLITE_FULL refusal from rolling back earlier allocations.
        # MEMORY journal/synchronous OFF apply only to this disposable allocator;
        # the production store configuration is reapplied before any backup.
        conn.execute('PRAGMA journal_mode=MEMORY')
        conn.execute('PRAGMA synchronous=OFF')
        conn.execute('CREATE TABLE capacity_allocation(payload BLOB)')
        attempts=0
        while CAP//4096-conn.execute('PRAGMA page_count').fetchone()[0]>=4:
            conn.execute('INSERT INTO capacity_allocation VALUES(zeroblob(4000))')
            attempts+=1
            if attempts>10000:raise AssertionError('Residual allocation exceeded bounded rows')
        while conn.execute('PRAGMA page_count').fetchone()[0]<CAP//4096:
            attempts+=1
            try:
                conn.execute('INSERT INTO capacity_allocation VALUES(zeroblob(4000))')
            except sqlite3.OperationalError as exc:
                if 'full' not in str(exc).lower():raise
                # Turning an existing inline cell into a 5000-byte record needs
                # one overflow page while freeing inline cell room: no split.
                row=conn.execute('SELECT rowid FROM capacity_allocation WHERE length(payload)=4000 LIMIT 1').fetchone()
                if row is None:raise AssertionError('No bounded overflow-page allocation candidate') from exc
                conn.execute('UPDATE capacity_allocation SET payload=zeroblob(5000) WHERE rowid=?',row)
            if attempts>10010:raise AssertionError('Exact target allocation did not converge')
        allocated=conn.execute('PRAGMA page_count').fetchone()[0]
        conn.execute('DROP TABLE capacity_allocation')
        conn.execute('PRAGMA journal_mode=DELETE')
        conn.execute('PRAGMA synchronous=EXTRA')
        metrics={'page_size':conn.execute('PRAGMA page_size').fetchone()[0],
                 'page_count':conn.execute('PRAGMA page_count').fetchone()[0],
                 'freelist_pages':conn.execute('PRAGMA freelist_count').fetchone()[0],
                 'integrity_check':conn.execute('PRAGMA integrity_check').fetchall(),
                 'before_residual_allocation_pages':before,'allocation_attempts':attempts,
                 'allocated_pages_before_drop':allocated}
    finally:conn.close()
    if path.stat().st_size!=CAP or metrics['page_count']*metrics['page_size']!=CAP or metrics['integrity_check']!=[('ok',)]:
        raise AssertionError('Positive fixture is not an exact, valid 512 MiB database')
    metrics['serialized_bytes']=path.stat().st_size
    metrics['allocated_filesystem_bytes']=getattr(path.stat(),'st_blocks',0)*512
    metrics['residual_freelist_note']='SQLite-allocated overflow/root pages freed by DROP TABLE after 496 MiB retained payload; no file padding/truncation/sparse placeholder'
    return metrics


@unittest.skipUnless(ARGS.run_ssh,'Explicit real 512 MiB loopback test not requested')
class CapacityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):F.StreamLoopback.setUpClass.__func__(cls)
    cleanup=classmethod(F.StreamLoopback.cleanup.__func__)
    @classmethod
    def tearDownClass(cls):cls.cleanup()

    def test_exact_512_mib_transfer_restore_and_failure_preservation(self):
        if ARGS.report is None or not ARGS.report.is_absolute():self.fail('--report requires an absolute private destination')
        if not 1<=ARGS.budget_seconds<=720:self.fail('Actual runtime budget must be1..720seconds')
        if ARGS.report.exists():self.fail('Refuse to overwrite capacity evidence')
        report={'schema_version':1,'state':'running','scope':'real disposable loopback SSH; one physical failure domain',
                'positive_database_target_bytes':CAP,'retained_payload_bytes':GENERATION_COUNT*GENERATION_BYTES,
                'generations_expected':GENERATION_COUNT,'generations':[],'phases':[],'failures':[],
                'script_sha256':sha(__file__),
                'source_sha256':{name:sha(F.SCRIPTS/name) for name in ('stream_backup_tools.py','checkpoint_tools.py','backup_tools.py')}}
        started=time.monotonic();local=self.root/('capacity-'+uuid.uuid4().hex);local.mkdir(mode=0o700)
        initial_cpu={who:resource.getrusage(who) for who in (resource.RUSAGE_SELF,resource.RUSAGE_CHILDREN)}
        disk={'sampled_fixture_file_bytes_high_water':0,'sampled_fixture_allocated_bytes_high_water':0,'samples':0,
              'scope':'Phase-boundary fixture files only; excludes transient RPC spool/drill dirs; allocated bytes sum per-file st_blocks, not unique physical extents'}
        def sample_disk():
            stats=[path.stat() for path in local.rglob('*') if path.is_file()]
            disk['samples']+=1
            disk['sampled_fixture_file_bytes_high_water']=max(disk['sampled_fixture_file_bytes_high_water'],sum(x.st_size for x in stats))
            disk['sampled_fixture_allocated_bytes_high_water']=max(disk['sampled_fixture_allocated_bytes_high_water'],sum(getattr(x,'st_blocks',0)*512 for x in stats))
            report['disk_cost']=disk
        def persist():
            report['wall_seconds']=round(time.monotonic()-started,3)
            temp=ARGS.report.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n');os.replace(temp,ARGS.report)
        def phase(name):
            sample_disk()
            report['phases'].append({'name':name,'elapsed_seconds':round(time.monotonic()-started,3)})
            persist();print('CAPACITY_PHASE '+name,flush=True)
        def expired(*unused):raise TimeoutError('Bounded capacity test exceeded actual runtime budget')
        prior_handler=signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,ARGS.budget_seconds)
        metrics={'chunk_bytes':65536,'largest_copy_read':0,'copy_calls':0,'copy_bytes':0,'copy_peak_python_bytes':0,
                 'successful_rpc_body_bytes_uploaded':0,'successful_rpc_body_bytes_downloaded':0,'rpc_operations':[]}
        original_copy=S.copy_body;original_rpc=S.rpc;original_regular=C.regular
        class Reader:
            def __init__(self,stream):self.stream=stream
            def read(inner,count):
                self.assertLessEqual(count,metrics['chunk_bytes'])
                metrics['largest_copy_read']=max(metrics['largest_copy_read'],count)
                raw=inner.stream.read(count);metrics['copy_bytes']+=len(raw);return raw
        def measured(source,target,count,chunk_bytes,expected=None):
            metrics['copy_calls']+=1;tracemalloc.start()
            try:
                return original_copy(Reader(source),target,count,chunk_bytes,expected)
            finally:
                metrics['copy_peak_python_bytes']=max(metrics['copy_peak_python_bytes'],tracemalloc.get_traced_memory()[1]);tracemalloc.stop()
        def no_whole_db(path,maximum):
            if Path(path).name==C.DB_NAME:raise AssertionError('Transfer may not read whole SQLite artifact through regular()')
            return original_regular(path,maximum)
        def rpc(p,req,upload=None,download=None):
            item={'operation':req['operation'],'upload':upload is not None,'download':download is not None,'state':'started'}
            metrics['rpc_operations'].append(item)
            try:
                answer=original_rpc(p,req,upload,download);item['state']='succeeded'
                if upload is not None:metrics['successful_rpc_body_bytes_uploaded']+=req['descriptor']['size']
                if download is not None:metrics['successful_rpc_body_bytes_downloaded']+=req['descriptor']['size']
                return answer
            except BaseException as exc:item.update(state='failed_or_uncertain',error_type=type(exc).__name__,error=str(exc)[:2000]);raise
        try:
            phase('create_31_meaningful_generations')
            store=local/'source';C.init_store(store,CAP,64)
            expected={}
            for index in range(GENERATION_COUNT):
                value=packet(index);C.save_packet(store,value,True)
                summary={k:v for k,v in value.items() if k!='files'}
                summary['files']=[{k:v for k,v in item.items() if k!='data_base64'} for item in value['files']]
                expected[value['checkpoint_id']]=summary;report['generations'].append(summary)
                del value
            db=store/C.DB_NAME
            report['sqlite']=exact_sqlite_capacity(db);source_hash=sha(db);report['source_database_sha256']=source_hash
            self.assertEqual(len(C.verify_store(store)['checkpoints']),GENERATION_COUNT)
            phase('prepare_exact_snapshot')
            p=json.loads(self.profile.read_text());p.update(schema_version=2,vault_id=uuid.uuid4().hex,
                remote_root=str(local/'vault'),max_backup_bytes=CAP,rpc_timeout_seconds=300,chunk_bytes=65536)
            state=local/'state';S.prepare(p,store,uuid.uuid4().hex,state);_,descriptor=S.load_intent(p,state)
            self.assertEqual(descriptor['size'],CAP);report['descriptor']=descriptor
            with patch.object(S,'copy_body',side_effect=measured),patch.object(S,'rpc',side_effect=rpc),patch.object(C,'regular',side_effect=no_whole_db):
                S.init_remote(p,True);phase('actual_ssh_push_and_fresh_readback')
                answer=S.push(p,state,True);self.assertTrue(answer['verification']['fresh_ssh_readback'])
                self.assertEqual(answer['verification']['generations'],GENERATION_COUNT);report['push']=answer
                phase('fresh_ssh_fetch_and_restore_every_generation')
                fetched=local/'fetched';report['fetch']=S.fetch(p,state,fetched,True)
                self.assertEqual(sha(fetched/C.DB_NAME),descriptor['sha256'])
                verified=C.verify_store(fetched);self.assertEqual(len(verified['checkpoints']),GENERATION_COUNT)
                restored_bytes=0
                for identity,item in expected.items():
                    destination=local/('restored-'+identity);C.restore(fetched,identity,destination,True)
                    for file in item['files']:
                        actual=destination/file['path'];self.assertEqual(actual.stat().st_size,file['size'])
                        self.assertEqual(sha(actual),file['sha256']);restored_bytes+=actual.stat().st_size
                    shutil.rmtree(destination)
                self.assertEqual(restored_bytes,GENERATION_COUNT*GENERATION_BYTES)
                report['restore']={'generations':GENERATION_COUNT,'files':GENERATION_COUNT*3,'zero_byte_artifacts':GENERATION_COUNT,
                                   'verified_payload_bytes':restored_bytes,'all_expected_hashes_verified':True}
                phase('full_512_mib_received_then_staging_process_dies')
                second=local/'interrupted-state';S.prepare(p,store,uuid.uuid4().hex,second);_,d2=S.load_intent(p,second)
                fault_marker=local/'received-before-death.json'
                old="drill=checked_artifact(stage/'store',d,maximum,chunk_bytes)"
                new=("Path("+repr(str(fault_marker))+").write_bytes(canonical({'received_bytes':(stage/'store'/C.DB_NAME).stat().st_size,'sha256':hash_file(stage/'store'/C.DB_NAME,maximum,chunk_bytes)[1]}))\n            os._exit(73)\n            "+old)
                def injected(path,maximum):
                    raw=no_whole_db(path,maximum)
                    if Path(path)==F.SCRIPTS/'stream_backup_tools.py':
                        self.assertIn(old.encode(),raw);return raw.replace(old.encode(),new.encode(),1)
                    return raw
                with patch.object(C,'regular',side_effect=injected):
                    with self.assertRaises(S.R.TransportError):S.push(p,second,True)
                received=json.loads(fault_marker.read_text());self.assertEqual(received,{'received_bytes':CAP,'sha256':d2['sha256']})
                before=len(metrics['rpc_operations'])
                with self.assertRaisesRegex(ValueError,'already attempted'):S.push(p,second,True)
                self.assertEqual(len(metrics['rpc_operations']),before)
                self.assertFalse((Path(p['remote_root'])/'backups'/d2['backup_id']).exists())
                self.assertEqual(S.verify(p,state)['state'],'verified')
                self.assertEqual(len(list((Path(p['remote_root'])/'backups').iterdir())),1)
                self.assertEqual(sha(db),source_hash)
                report['interruption']={**received,'prior_archive_verified_by_fresh_ssh':True,
                                        'source_database_unchanged':True,'retry_rpc_calls':0,'new_archive_published':False}
                phase('actual_cap_plus_one_file_rejected_before_ssh')
                over=local/'cap-plus-one.sqlite';shutil.copyfile(state/'snapshot'/C.DB_NAME,over)
                with over.open('ab') as stream:stream.write(b'X')
                self.assertEqual(over.stat().st_size,CAP+1);sample_disk()
                with patch.object(S.subprocess,'Popen',side_effect=AssertionError('Overflow must fail before SSH launch')):
                    with self.assertRaisesRegex(ValueError,'Bounded regular non-hardlinked database required'):
                        original_rpc(p,S.request(p,'put',d2),upload=over)
                self.assertEqual(len(list((Path(p['remote_root'])/'backups').iterdir())),1)
                report['cap_plus_one']={'actual_bytes':over.stat().st_size,'ssh_launched':False,'published':False}
                over.unlink()
            self.assertEqual(metrics['successful_rpc_body_bytes_uploaded'],CAP)
            self.assertEqual(metrics['successful_rpc_body_bytes_downloaded'],3*CAP)
            self.assertEqual(metrics['copy_bytes'],5*CAP)
            self.assertLess(metrics['copy_peak_python_bytes'],4*metrics['chunk_bytes'])
            metrics['verified_full_received_fault_upload_bytes']=CAP
            metrics['total_verified_ssh_artifact_body_bytes']=5*CAP
            metrics['wire_scope']='Artifact bodies verified end to end; excludes SSH encryption/protocol and metadata overhead'
            metrics['memory_scope']='tracemalloc only during client copy_body; not SQLite, restore or total process memory'
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            metrics['controller_peak_rss_bytes']=rss if sys.platform=='darwin' else rss*1024
            metrics['cpu_seconds']={}
            for label,who in (('controller',resource.RUSAGE_SELF),('reaped_ssh_clients',resource.RUSAGE_CHILDREN)):
                current=resource.getrusage(who);initial=initial_cpu[who]
                metrics['cpu_seconds'][label]={'user':round(current.ru_utime-initial.ru_utime,6),'system':round(current.ru_stime-initial.ru_stime,6)}
            metrics['cpu_scope']='Actual controller and reaped SSH-client CPU during test body; excludes server-side CPU and fixture setup/cleanup' 
            report['metrics']=metrics;report['state']='passed'
            phase('passed')
        except BaseException as exc:
            report.update(state='failed',error_type=type(exc).__name__,error=str(exc),metrics=metrics)
            persist();raise
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,prior_handler)
            report['wall_seconds']=round(time.monotonic()-started,3);persist()


if __name__=='__main__':unittest.main(argv=[sys.argv[0],*REST])
