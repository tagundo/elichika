"""Small local fixtures; no credentials, socket, payload or account writes."""
import concurrent.futures
from collections import Counter
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import individual_uploader as u
import owned_publisher as p
import owned_layout as scope
import layout_review as layout

DATA=b'original'
SHA=hashlib.sha256(DATA).hexdigest(); MD5=hashlib.md5(DATA).hexdigest()

REAL_SLEEP=time.sleep
class Clock:
    def __init__(self): self.now=1000; self.lock=threading.Lock()
    def monotonic(self):
        with self.lock: return self.now
    def sleep(self,n):
        with self.lock: self.now+=n
        REAL_SLEEP(0)

class Harness:
    def __init__(self,directory,count=20,workers=4,release=0,fail=None,seed_ack=0):
        self.lock=threading.RLock(); self.puts=[]; self.order=[]; self.live=self.maxlive=self.maxunseen=0
        self.observed=set(); self.remote={i:{} for i in layout.ITEMS}; self.release=release; self.fail=fail; self.failed=False
        self.queries=0
        names=['f%04d'%n for n in range(count)]
        objects={n:{'path':'packs/'+n,'size':len(DATA),'sha256':SHA,'profiles':[u.PROFILES[0]],
                    'source':{'part':'part'}} for n in names}
        placements={n:layout.ITEMS[i%5] for i,n in enumerate(names)}
        self.work=u.Work(directory)
        self.pub=p.OwnedPublisher.__new__(p.OwnedPublisher)
        pub=self.pub
        pub.args=types.SimpleNamespace(workers=workers)
        pub.inputs=types.SimpleNamespace(objects=objects,pins={'part':{}},inventory_sha='e'*64)
        pub.plan={'layout':{'placements':placements}}
        pub.work=self.work; pub.journal=u.Journal(self.work,{'fixture':True})
        pub.public=self; pub.s3=self; pub.progress=u.Progress();pub.budget=u.ByteBudget(96,workers)
        pub.counted=set();pub.stop_admission=threading.Event();pub.state_lock=threading.Lock();pub.owner_cache={};pub.cooldown_until=0
        pub.check_source=lambda:None
        pub.files=self.files
        for n in names[:seed_ack]:
            rec=self.record(n,'PUT_ACKNOWLEDGED');pub.journal.record(n,rec);self.remote[rec['item']][rec['path']]={'size':str(len(DATA)),'md5':MD5}
    def record(self,name,status):
        return {'size':len(DATA),'sha256':SHA,'md5':MD5,'item':self.pub.plan['layout']['placements'][name],
                'path':'packs/'+name,'status':status}
    def files(self,item):
        with self.lock:
            self.queries+=1
            visible=self.release==0 or (self.release>0 and len(self.puts)>=self.release) or (self.release<0 and self.queries>=-self.release)
            result=copy.deepcopy(self.remote[item]) if visible else {}
            self.observed.update((item,k) for k in result)
            self.pub.owner_cache[item]=(p.time.monotonic(),result)
            return result
    def stage(self,public,work,name,obj,pin,progress,attempts=5):
        path,out=work.tempfile()
        with out:out.write(DATA)
        return path,MD5
    def put(self,item,key,path,size,sha,md5,headers,progress):
        self.assert_no_headers(headers)
        with self.lock:
            self.live+=1; self.maxlive=max(self.maxlive,self.live);self.order.append(item)
        try:
            REAL_SLEEP(.001)
            with self.lock:
                if self.fail and not self.failed:
                    self.failed=True;self.summary=self.fail
                    return False,37
                if key in self.remote[item]: raise AssertionError('duplicate PUT')
                self.remote[item][key]={'size':str(size),'md5':md5};self.puts.append((item,key))
                self.maxunseen=max(self.maxunseen,len(self.puts)-len(self.observed))
            return True,0
        finally:
            with self.lock:self.live-=1
    def assert_no_headers(self,headers):
        if headers:raise AssertionError('Metadata/create headers')
    def last_response_summary(self):return self.summary
    def last_failure_category(self):return 'HTTP503'
    def close(self):self.pub.journal.close();self.work.close()

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.addCleanup(self.dir.cleanup)
        network=patch.object(socket,'create_connection',side_effect=AssertionError('live socket forbidden'));network.start();self.addCleanup(network.stop)
        self.clock=Clock()
        self.fake=types.SimpleNamespace(monotonic=self.clock.monotonic,sleep=self.clock.sleep)
    def run_harness(self,h):
        with patch.object(p,'time',self.fake),patch.object(u,'stage_object',h.stage),contextlib.redirect_stdout(__import__('io').StringIO()):
            h.pub.data()
    def make(self,**kwargs):
        h=Harness(Path(self.dir.name)/'work',**kwargs);self.addCleanup(h.close);return h
    def test_five_contexts_fair_four_global_tasks_and_actual_md5(self):
        h=self.make(count=30);self.run_harness(h)
        self.assertEqual(len(h.puts),30);self.assertLessEqual(h.maxlive,4)
        self.assertEqual(set(h.order[:5]),set(layout.ITEMS))
        self.assertTrue(all(r['status']=='REMOTE_METADATA_VERIFIED' for r in h.pub.records().values()))
    def test_global128_admission_reserved_while_visibility_is_held(self):
        h=self.make(count=145,release=128);self.run_harness(h)
        self.assertEqual(len(h.puts),145);self.assertLessEqual(h.maxunseen,128);self.assertLessEqual(h.maxlive,4)
        self.assertGreater(h.queries,5)
    def test_invisible_seed_ack_is_never_demoted_or_reput(self):
        h=self.make(count=10,seed_ack=10,release=-16);self.run_harness(h)
        self.assertFalse(h.puts);self.assertEqual(len(h.pub.counted),10)
    def test_spam_and_unknown_503_stop_admission(self):
        for report in ({'http_status':503,'xml_code':'SlowDown','spam_refusal':True},
                       {'http_status':503,'xml_code':'UNKNOWN','spam_refusal':False}):
            with self.subTest(report=report),tempfile.TemporaryDirectory() as directory:
                h=Harness(Path(directory)/'work',count=30,fail=report)
                try:
                    with self.assertRaises(u.Failure):self.run_harness(h)
                    self.assertTrue(h.pub.stop_admission.is_set());self.assertLessEqual(len(h.order),4)
                finally:h.close()
    def test_known_congestion_defers_globally_refreshes_then_resumes(self):
        h=self.make(count=10,fail={'http_status':503,'xml_code':'SlowDown','spam_refusal':False})
        self.run_harness(h)
        self.assertEqual(len(h.puts),10);self.assertGreaterEqual(self.clock.now,1037);self.assertGreaterEqual(h.queries,10)
    def test_missing_ack_metadata_blocks_completion_without_new_put(self):
        h=self.make(count=2,seed_ack=2,release=-999999)
        with self.assertRaises(u.Failure):self.run_harness(h)
        self.assertFalse(h.puts)
        self.assertTrue(all(r['status']=='PUT_ACKNOWLEDGED' for r in h.pub.records().values()))
    def test_metadata_mismatch_is_fatal_and_ack_preserved(self):
        h=self.make(count=1,seed_ack=1)
        item=h.pub.plan['layout']['placements']['f0000'];h.remote[item]['packs/f0000']['md5']='0'*32
        with self.assertRaises(u.Failure):self.run_harness(h)
        self.assertFalse(h.puts);self.assertEqual(h.pub.records()['f0000']['status'],'PUT_ACKNOWLEDGED')
    def test_only_five_fixed_items_and_no_extra_headers(self):
        h=self.make(count=1)
        self.assertEqual(p.OwnedPublisher.headers(h.pub,layout.ITEMS[0],123),{})
        with self.assertRaises(u.Failure):p.OwnedPublisher.headers(h.pub,layout.PREFIX+'-index',123)
    def test_pending_reservation_counts_single_snapshot(self):
        h=self.make(count=2,seed_ack=1)
        self.assertEqual(h.pub.outstanding(['f0000','f0001']),2)

    def test_retained_original_ack_and_new_diagnostic_cannot_be_forgotten_or_demoted(self):
        h=self.make(count=1,seed_ack=1);pub=h.pub
        old=copy.deepcopy(pub.records()['f0000']);pub.plan['layout']['retained_acknowledged']={'f0000':old}
        rec={'item':p.diagnostic.ITEM,'path':'packs/'+p.diagnostic.NAME,'size':p.diagnostic.SIZE,
             'sha256':p.diagnostic.SHA256,'md5':p.diagnostic.MD5,'status':'PUT_ACKNOWLEDGED'}
        pub.journal.record(p.diagnostic.NAME,rec);pub.validate_retained_seed()
        pub.journal.record('f0000',{**old,'status':'STAGED'})
        with self.assertRaises(u.Failure):pub.validate_retained_seed()
        pub.journal.record('f0000',old)
        pub.journal.record(p.diagnostic.NAME,{**rec,'status':'STAGED'})
        with self.assertRaises(u.Failure):pub.validate_retained_seed()

    def test_direct_fatal_transport_failure_stops_global_admission(self):
        h=self.make(count=30)
        def fatal(*args):raise u.Failure('synthetic forbidden HTTP response')
        h.put=fatal
        with self.assertRaises(u.Failure):self.run_harness(h)
        self.assertTrue(h.pub.stop_admission.is_set());self.assertFalse(h.puts)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.addCleanup(self.dir.cleanup)
        self.h=Harness(Path(self.dir.name)/'work',count=2,seed_ack=2);self.addCleanup(self.h.close)
        self.pub=self.h.pub; self.events=[]; self.docs={}
        i=self.pub.inputs
        i.expected=i.target_expected=i.objects;i.target_reconciled=i.complete_source=True;i.requested_total=42830
        i.target_manifest_sha='e536';i.catalog_sha='0aa';i.effective_catalog_sha='e536';i.metadata_sha='metadata';i.supplement=None
        i.audit={'missing':[],'conflicts':[]};i.catalog={'databases':[]};i.summary=lambda prefix:{'inventory_sha256':i.inventory_sha}
        self.pub.prefix=layout.PREFIX
        for n,r in self.pub.records().items():self.pub.journal.record(n,{**r,'status':'REMOTE_METADATA_VERIFIED'})
        self.pub.files=lambda item:{}
        self.real_stage=self.pub.stage_document
        def stage(header,names=None):
            self.docs[header['document_type']+':'+header.get('profile','')]=copy.deepcopy(header)
            return self.real_stage(header,names)
        self.pub.stage_document=stage
        def put(item,key,path,size,sha,md5,existing):
            self.events.append(('put',key))
            self.pub.journal.record(key,{'size':size,'sha256':sha,'md5':md5,'item':item,'path':key,'status':'PUT_ACKNOWLEDGED'},True)
        self.pub.put_index_document=put
        def verify(item,keys,index=False):
            for key in keys:
                rec=self.pub.journal.value['index_objects'][key]
                self.pub.journal.record(key,{**rec,'status':'REMOTE_METADATA_VERIFIED'},True)
        self.pub.verify_batch=verify
        def verifysha(item,key):
            self.events.append(('sha',key));rec=self.pub.journal.value['index_objects'][key]
            self.pub.journal.record(key,{**rec,'status':'REMOTE_SHA256_VERIFIED'},True)
        self.pub.verify_index_sha256=verifysha
    def publish(self):
        with patch.object(p.diagnostic,'validate_complete_inputs'),contextlib.redirect_stdout(__import__('io').StringIO()):self.pub.publish_index()
    def test_profiles_remote_sha_before_catalog_and_truthful_qa_pending(self):
        self.publish();key=layout.INDEX_PREFIX+'/catalog.json';at=self.events.index(('put',key))
        self.assertEqual(sum(kind=='sha' for kind,_ in self.events[:at]),8)
        self.assertEqual(self.events[-1],('sha',key));self.assertEqual(len([e for e in self.events if e[0]=='put']),9)
        catalog=self.docs['catalog:'];self.assertEqual(catalog['qa_status'],'PENDING');self.assertEqual(catalog['publication_layout'],scope.PUBLICATION_LAYOUT)
        receipt=json.loads((self.h.work.path/'publication.json').read_bytes())
        self.assertEqual(receipt['qa_status'],'PENDING');self.assertEqual(receipt['index_documents_full_remote_sha256_verified'],9)
        self.assertIn('/elichika-selective-five-v1/catalog.json',receipt['index_url']);self.assertEqual(receipt['index_sha256'],self.pub.journal.value['index_objects'][key]['sha256'])
    def test_missing_data_remote_md5_blocks_every_document(self):
        r=self.pub.records()['f0000'];self.pub.journal.record('f0000',{**r,'status':'PUT_ACKNOWLEDGED'})
        with self.assertRaises(u.Failure):self.publish()
        self.assertFalse(self.events)
    def test_one_profile_remote_sha_failure_prevents_catalog(self):
        def fail(item,key):raise u.Failure('synthetic wrong remote SHA')
        self.pub.verify_index_sha256=fail
        with self.assertRaises(u.Failure):self.publish()
        self.assertFalse(any(key.endswith('/catalog.json') for _,key in self.events));self.assertFalse((self.h.work.path/'publication.json').exists())

if __name__=='__main__':unittest.main()
