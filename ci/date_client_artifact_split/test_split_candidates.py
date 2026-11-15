import copy,hashlib,json,pathlib,struct,tempfile,unittest,zipfile
from unittest import mock
import split_candidates as s
RECIPE=json.loads(pathlib.Path(__file__).with_name('export-recipe.json').read_bytes())

class SplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
    def fixture(self,change=None):
        recipe=copy.deepcopy(RECIPE);objects={};outputs=[]
        for row in recipe['candidates']:
            name=row['name'];payload=('unchanged payload '+name).encode();item={'name':name,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()};outputs.append(item);objects[name]=payload
            proof={'build':recipe['build'],'platform':row['platform'],'output':item,'members':[{'name':'native','sha256':'a'*64}],('region' if row['platform']=='android' else 'variant'):row['variant'],('native_binaries_byte_identical' if row['platform']=='android' else 'V5_executable_byte_identical'):True}
            objects[name+'.proof.json']=json.dumps(proof).encode()
        objects['SHA256SUMS']=''.join(o['sha256']+'  '+o['name']+'\n' for o in outputs).encode()
        objects['build-receipt.json']=json.dumps({'build':recipe['build'],'status':'CANDIDATES_BUILT_NO_UPLOAD_OR_RELEASE','source_lock_sha256':recipe['source_lock_sha256'],'outputs':outputs}).encode()
        if change:change(objects)
        path=self.root/'source.zip'
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for name,body in objects.items():z.writestr(name,body)
        self.repin(recipe,path);return recipe,path,objects
    def repin(self,recipe,path):
        recipe['source_artifact']['bytes']=path.stat().st_size;recipe['source_artifact']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    def provenance(self,r):return {'repository':r['repository'],'run_id':r['source_run_id'],'source_commit':r['source_commit'],'run_status':'completed','run_conclusion':'success','artifact':r['source_artifact']}
    def test_streamed_payloads_and_original_metadata_preserved(self):
        r,p,b=self.fixture();out=self.root/'export';records=s.split(p,out,r,self.provenance(r));self.assertEqual(len(records),5)
        for row in records:self.assertEqual((out/row['directory']/row['name']).read_bytes(),b[row['name']])
        for name,body in b.items():
            if name not in {v['name'] for v in r['candidates']}:self.assertEqual((out/'metadata'/name).read_bytes(),body)
        self.assertLess(sum(f.stat().st_size for f in (out/'metadata').iterdir()),s.MAX_METADATA)
    def test_rejects_outer_digest_and_size_mismatch(self):
        r,p,b=self.fixture();r['source_artifact']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SHA256'):s.split(p,self.root/'bad',r,self.provenance(r))
        r['source_artifact']['bytes']+=1
        with self.assertRaisesRegex(ValueError,'length'):s.split(p,self.root/'bad-size',r,self.provenance(r))
    def test_rejects_wrong_run_source_or_status(self):
        r,p,b=self.fixture()
        for key,value in [('run_id',1),('source_commit','0'*40),('run_conclusion','failure')]:
            with self.subTest(key=key):
                prov=self.provenance(r);prov[key]=value
                with self.assertRaisesRegex(ValueError,'provenance'):s.split(p,self.root/'bad',r,prov)
    def test_rejects_path_member(self):
        def change(b):b['../escape']=b'x'
        r,p,b=self.fixture(change)
        with self.assertRaisesRegex(ValueError,'entries'):s.split(p,self.root/'bad',r,self.provenance(r))
        self.assertFalse((self.root/'escape').exists())
    def test_rejects_duplicate_zip_member(self):
        r,p,b=self.fixture();name=r['candidates'][0]['name']
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(p,'a') as z:z.writestr(name,b[name])
        self.repin(r,p)
        with self.assertRaisesRegex(ValueError,'duplicate'):s.split(p,self.root/'bad',r,self.provenance(r))
    def test_rejects_sum_duplicate_and_conflict(self):
        for duplicate in (True,False):
            with self.subTest(duplicate=duplicate):
                if (self.root/'source.zip').exists():(self.root/'source.zip').unlink()
                def change(b):
                    if duplicate:b['SHA256SUMS']+=b['SHA256SUMS'].splitlines(keepends=True)[0]
                    else:b['SHA256SUMS']=b['SHA256SUMS'].replace(b['SHA256SUMS'][:64],b'0'*64,1)
                r,p,b=self.fixture(change)
                with self.assertRaisesRegex(ValueError,'SHA256SUMS|conflict'):s.split(p,self.root/('bad-'+str(duplicate)),r,self.provenance(r))
    def test_rejects_corrupt_payload_even_when_outer_zip_repinned(self):
        def change(b):b[RECIPE['candidates'][0]['name']]=b'x'*len(b[RECIPE['candidates'][0]['name']])
        r,p,b=self.fixture(change)
        with self.assertRaisesRegex(ValueError,'Candidate SHA256'):s.split(p,self.root/'bad',r,self.provenance(r))
    def test_rejects_proof_native_or_receipt_conflict(self):
        for native in (True,False):
            with self.subTest(native=native):
                if (self.root/'source.zip').exists():(self.root/'source.zip').unlink()
                def change(b):
                    name=RECIPE['candidates'][0]['name']+'.proof.json';proof=json.loads(b[name]);proof['native_binaries_byte_identical']=False if native else True
                    if not native:proof['output']['sha256']='0'*64
                    b[name]=json.dumps(proof).encode()
                r,p,b=self.fixture(change)
                with self.assertRaisesRegex(ValueError,'preservation|conflict'):s.split(p,self.root/('bad-'+str(native)),r,self.provenance(r))
    def test_rejects_wrong_build_source_lock(self):
        def change(b):receipt=json.loads(b['build-receipt.json']);receipt['source_lock_sha256']='0'*64;b['build-receipt.json']=json.dumps(receipt).encode()
        r,p,b=self.fixture(change)
        with self.assertRaisesRegex(ValueError,'source lock'):s.split(p,self.root/'bad',r,self.provenance(r))
    def test_rejects_encrypted_and_symlink_outer_entry(self):
        for link in (False,True):
            with self.subTest(link=link):
                if (self.root/'source.zip').exists():(self.root/'source.zip').unlink()
                r,p,b=self.fixture()
                with zipfile.ZipFile(p) as z:at=z.start_dir
                raw=bytearray(p.read_bytes())
                if link:struct.pack_into('<I',raw,at+38,0o120777<<16)
                else:struct.pack_into('<H',raw,at+8,struct.unpack_from('<H',raw,at+8)[0]|1)
                p.write_bytes(raw);self.repin(r,p)
                with self.assertRaisesRegex(ValueError,'encrypted/link'):s.split(p,self.root/('bad-'+str(link)),r,self.provenance(r))
    def test_refuses_overwrite_and_output_path_conflicts(self):
        r,p,b=self.fixture();out=self.root/'exists';out.mkdir();(out/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'Fresh'):s.split(p,out,r,self.provenance(r))
        self.assertEqual((out/'keep').read_bytes(),b'keep');r['candidates'][0]['directory']='../outside'
        with self.assertRaisesRegex(ValueError,'output names'):s.split(p,self.root/'bad',r,self.provenance(r))

    def test_preserves_metadata_above_old_one_mib_limit(self):
        def change(objects):
            name=RECIPE['candidates'][0]['name']+'.proof.json';proof=json.loads(objects[name]);proof['notes']='p'*(s.CHUNK+1);objects[name]=json.dumps(proof).encode()
        recipe,path,objects=self.fixture(change);output=self.root/'large-proof-export'
        s.split(path,output,recipe,self.provenance(recipe))
        size=sum(p.stat().st_size for p in (output/'metadata').iterdir());self.assertGreater(size,s.CHUNK);self.assertLessEqual(size,s.MAX_METADATA)
        for name,body in objects.items():
            if name not in {row['name'] for row in recipe['candidates']}:self.assertEqual((output/'metadata'/name).read_bytes(),body)
    def test_rejects_metadata_over_explicit_budget_before_body_reads(self):
        recipe,path,objects=self.fixture();metadata_bytes=sum(len(body) for name,body in objects.items() if name not in {row['name'] for row in recipe['candidates']})
        with mock.patch.object(s,'MAX_METADATA',16384+metadata_bytes-1):
            with self.assertRaisesRegex(ValueError,rf'Metadata input {metadata_bytes} bytes exceeds allowed {metadata_bytes-1} bytes'):
                s.split(path,self.root/'over-limit',recipe,self.provenance(recipe))
        self.assertFalse((self.root/'over-limit').exists())
    def test_final_metadata_budget_still_checked_with_actual_size(self):
        recipe,path,objects=self.fixture()
        original_dumps=s.json.dumps
        def large_report(value,*args,**kwargs):
            # Only make the generated export manifest big; original proofs stay exact.
            if isinstance(value,dict) and value.get('status')=='UNCHANGED_CANDIDATES_VERIFIED_NOT_SIGNED_OR_RELEASED':
                return original_dumps({**value,'extra':'x'*25000},*args,**kwargs)
            return original_dumps(value,*args,**kwargs)
        metadata_bytes=sum(len(body) for name,body in objects.items() if name not in {row['name'] for row in recipe['candidates']})
        with mock.patch.object(s,'MAX_METADATA',metadata_bytes+16384),mock.patch.object(s.json,'dumps',side_effect=large_report):
            with self.assertRaisesRegex(ValueError,r'Final metadata [0-9]+ bytes exceeds budget [0-9]+ bytes'):
                s.split(path,self.root/'final-over-limit',recipe,self.provenance(recipe))

if __name__=='__main__':unittest.main()
