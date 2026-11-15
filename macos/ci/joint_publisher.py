"""Revised joint release validation. All publication/tag paths remain explicit.

Client evidence uses schema 3 and literal user/automation observations, exact final static
receipts, disclosed device limits, and resolved actual issue history. Server CI validation
stays in the unchanged pinned base publisher. Source preparation activates none.

The existing schema-1 publisher remains unchanged. A token-created lightweight
release tag and a reviewed helper attestation are mandatory for publication.
"""
from __future__ import annotations
import base64
import copy
import stat
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import zipfile

import os
BASE_PATH = Path(os.environ.get('ELICHIKA_BASE_PUBLISHER_PATH','/workspace/elichika/macos/ci/publish_validated_apps.py'))
BASE_SHA256 = '9d2624a809a597bf4da52f6715fabe5a020c80b35cd772fb7f095a205dcef027'
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA256:
    raise RuntimeError('Base publisher differs from the reviewed unchanged schema-1 implementation')
spec = importlib.util.spec_from_file_location('elichika_base_publisher', BASE_PATH)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
ValidationError, require = base.ValidationError, base.require
SERVER_REPOSITORY = base.REPOSITORY
PRIVATE_REPOSITORY = 'tagundo/SIFAS-Client'
QA_REPOSITORIES = {SERVER_REPOSITORY}
SLOTS = {'android-gl':('android','GL','.apk'), 'android-jp':('android','JP','.apk'),
         'ios-gl':('ios','GL','.ipa'), 'ios-jp':('ios','JP','.ipa'), 'ios-local-gl':('ios','GL_LOCAL','.ipa')}
TAG_WORKFLOW = '.github/workflows/joint-validated-release.yml'
TAG_WORKFLOW_NAME = 'Joint validated release gate'
TAG_BRANCH = 'codex/joint-tag-20261115-v4'
HELPER_PATHS = frozenset({TAG_WORKFLOW,'macos/ci/joint_publisher.py','macos/ci/test_joint_publisher.py','macos/ci/joint_server_manifest.json','macos/ci/joint_client_manifest.json'})
MAX_REPORT = 4 * 1024 * 1024
MAX_EVIDENCE = 2 * 1024 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(value): return hashlib.sha256(value).hexdigest()


def commit(value, label):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value),label+' must be an exact commit SHA')
    return value


def exact(value, fields, label):
    require(isinstance(value,dict) and set(value)==set(fields),label+' fields differ from the approved contract')


def member_path(value):
    require(isinstance(value,str) and value and '\\' not in value and ':' not in value and '\0' not in value,'Unsafe evidence path')
    path=PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and str(path)==value,'Unsafe evidence path')
    return value


# Finite Root-authorized schema3: exact final products and honest scope.
STATIC_CHECKS = frozenset({'archive','signature','abi','patch','unchanged_payload'})
C11_SOURCE = '02f659d707997e03218be231e8a675fb0358a6c8'
ANDROID_CERT = '5ccf5b5f73dcebad61255f6bfca848eb2022eedb741515d16ac84f94c405a9e3'
ANDROID_RECIPE = '7f1d584a7de9d6ab10bbdc58d9166a60024e007c4ff136150f4e03375e479bce'
LOCAL_REQUIRED_CASES = frozenset({'mv_duplicate_same_costume','material_lighting','eyes_mouth_expression','loading_playback_stability'})
RUNTIME_CASES = LOCAL_REQUIRED_CASES | {'fov_actual','orientation_controls','intro_timing'}
LIMITATIONS = (
    'Android game-client MV, lighting, FOV and orientation behaviour have not been tested on an Android device for this build.',
    'The GL and JP IPA variants and SideStore installation were not tested on devices; actual MacBook/PlayCover MV verification used the GL Local IPA.',
    'FOV, orientation-lock and intro-speed controls have static implementation checks; their device behaviour was not separately verified in this release test.',
)
FINAL_BINDINGS = {'android-gl': {'receipt_sha256': 'e7f044e5316afa58b310463183288a7eb7832d282ea4f3e39e82dd9ac8b28585', 'output_sha256': '157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738', 'output_bytes': 83535736, 'input_sha256': '0294debfe433dabfedc9489a63ba15d87b19f35309b0803cd3c2bc8d28837f4d', 'native_member': 'lib/arm64-v8a/libil2cpp.so', 'native_sha256': '39e7af6865c71debdfd696e22a8aa4332ee994e936ecef100d7e4d51364f8f0a', 'feature_member': 'lib/arm64-v8a/libfovmod.so', 'feature_sha256': '570fde1e5d74840c85210c6de233e9379219e5d1d8f65c38069244be727d2cc4', 'patch_plan_sha256': '57a2b5ff6962ae9351140fa3bbbdcf9a84fd52bfee2a4527fb0ed706123489a9'}, 'android-jp': {'receipt_sha256': 'd2556bfc5822d750296ce7eebbb928f06e3a077f83f7fe9a7b073c9be294c42c', 'output_sha256': '488d727001bbc125fc1c16f83f6bd29482384359b9bee0c22e7c6f7664742220', 'output_bytes': 79691554, 'input_sha256': 'c9d6555acd71605ae4b4aa083021932ec398b9b83d312c14c8f385c98a0e816f', 'native_member': 'lib/arm64-v8a/libil2cpp.so', 'native_sha256': '6be5676373f48057bafa7cf431cbdbe07d682d5065ebb1a01e7b7ffa5956ba2d', 'feature_member': 'lib/arm64-v8a/libfovmod.so', 'feature_sha256': '570fde1e5d74840c85210c6de233e9379219e5d1d8f65c38069244be727d2cc4', 'patch_plan_sha256': '57a2b5ff6962ae9351140fa3bbbdcf9a84fd52bfee2a4527fb0ed706123489a9'}, 'ios-gl': {'receipt_sha256': '87121ab34ef4610228e9870b33993a4d0cfafefaa2799d15681dc30890cc5984', 'output_sha256': 'f5580ed0c1bf4dde10228dd658a589e5c25593a61a467330e05cec69f1df7b2f', 'output_bytes': 66142875, 'input_sha256': 'fe1d2715e673fd896620f713dd7bfff451f0b40e52cc126bec0cb3a94c55e378', 'native_member': 'Payload/global.app/global', 'native_sha256': '071607a0b7e4d4e080af68ce9ce7c84cf279bf8e73e70ec9dc8cf1f3be1cd4dd', 'feature_member': 'Payload/global.app/Frameworks/SIFASFeatures.dylib', 'feature_sha256': 'bc27ed2cdab364f0fd23e6c59a0043892a3a33fb14a1c5f6f9968aad3488774e', 'patch_plan_sha256': '57fdc2ed8a8a5c61d8c11e4c430eb611dac536e88bae7655db02610e881d8ed5'}, 'ios-jp': {'receipt_sha256': '3f290cfdf89ab6e5250e312f30178b928bd7c0e7c72848e6077aa33878508370', 'output_sha256': 'cc1e0c8d4c0d573b61351bac066832d07e4cb1aa776594a9ba525e21ccfbe6cb', 'output_bytes': 63222269, 'input_sha256': '3e3af0dfdda588f8688dffab2f4adfc5a62cd7483818586ab72483e3fc0cff38', 'native_member': 'Payload/allstars.app/allstars', 'native_sha256': '32177423acdecfa39fce1c7ed9d4f18d6ad57ed980b39d5967229a5c56221e6a', 'feature_member': 'Payload/allstars.app/Frameworks/SIFASFeatures.dylib', 'feature_sha256': 'bc27ed2cdab364f0fd23e6c59a0043892a3a33fb14a1c5f6f9968aad3488774e', 'patch_plan_sha256': '57fdc2ed8a8a5c61d8c11e4c430eb611dac536e88bae7655db02610e881d8ed5'}, 'ios-local-gl': {'receipt_sha256': '6acf2852dea8c0b204449f0e9d953c111a37afe0400672134e72612f1af145d1', 'output_sha256': 'a3631c3aba709e09017f2d90599be334f21a001d4a7996864b53422fe643b6dc', 'output_bytes': 66457109, 'input_sha256': '568f0c0ad9c2ca7f42de3f9cef21cf5581987d7f49482da7b2233f965dc94923', 'native_member': 'Payload/global.app/global', 'native_sha256': '071607a0b7e4d4e080af68ce9ce7c84cf279bf8e73e70ec9dc8cf1f3be1cd4dd', 'feature_member': 'Payload/global.app/Frameworks/SIFASFeatures.dylib', 'feature_sha256': 'bc27ed2cdab364f0fd23e6c59a0043892a3a33fb14a1c5f6f9968aad3488774e', 'patch_plan_sha256': '57fdc2ed8a8a5c61d8c11e4c430eb611dac536e88bae7655db02610e881d8ed5'}}

def parse_clients(value, server):
    exact(value,{'schema_version','original_repository','original_release_id','candidate_repository','candidate_release_id','private_original_sha256s','clients','readiness','server_version_binding'},'Client manifest')
    require(type(value['schema_version']) is int and value['schema_version']==3,'Client schema must be integer3')
    require(value['original_repository']==PRIVATE_REPOSITORY and value['candidate_repository']==SERVER_REPOSITORY,'Unexpected original/candidate repository')
    for key in ('original_release_id','candidate_release_id'):base.positive_int(value[key],key)
    private=value['private_original_sha256s']
    require(isinstance(private,list) and private and len(private)==len(set(private)),'Missing/duplicate private original hashes')
    for h in private:base.digest_value(h,'Original input SHA256')
    rows=value['clients'];require(isinstance(rows,list) and len(rows)==5 and {c.get('id') for c in rows if isinstance(c,dict)}==set(SLOTS),'Exactlyfive current clients required')
    names=set();assets=set()
    for c in rows:
        exact(c,{'id','name','original','candidate','static'},'Client')
        platform,region,extension=SLOTS[c['id']];bound=FINAL_BINDINGS[c['id']]
        require(isinstance(c['name'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}',c['name']) and c['name'].endswith(extension),'Unsafe client filename')
        require(c['name'] not in names,'Duplicate client filename');names.add(c['name'])
        for key in ('original','candidate'):
            a=c[key];exact(a,{'asset_id','sha256','bytes','name'},key+' asset');base.positive_int(a['asset_id'],'Asset ID');base.digest_value(a['sha256'],'Asset SHA256')
            require(type(a['bytes']) is int and 0<a['bytes']<=base.MAX_FILE,'Invalid asset size')
            require(isinstance(a['name'],str) and '/' not in a['name'] and a['name'].endswith(extension),'Unsafe asset name')
        require(c['original']['sha256'] in private and c['candidate']['sha256'] not in private,'Original cannot be published')
        require(c['candidate']['asset_id'] not in assets,'Duplicate candidate asset');assets.add(c['candidate']['asset_id'])
        require((c['candidate']['sha256'],c['candidate']['bytes'])==(bound['output_sha256'],bound['output_bytes']),'Candidate differs from exact final product')
        s=c['static'];exact(s,{'receipt_json','receipt_sha256','reused_main_receipt','input_sha256','patch_plan_sha256','native_member','native_sha256','feature_member','feature_sha256','checks'},'Static evidence')
        for k in ('receipt_sha256','input_sha256','patch_plan_sha256','native_member','native_sha256','feature_member','feature_sha256'):require(s[k]==bound[k],'Actual final binding differs: '+k)
        member_path(s['native_member']);member_path(s['feature_member'])
        require(s['reused_main_receipt'] is None,'Final receipts already contain exact signed-main validation')
        require(isinstance(s['receipt_json'],str) and 0<len(s['receipt_json'].encode())<=MAX_REPORT and sha(s['receipt_json'].encode())==s['receipt_sha256'],'Raw actual receipt differs')
        exact(s['checks'],STATIC_CHECKS,'Static checks');require(all(x=='PASS' for x in s['checks'].values()),'Incomplete static checks')
        r=json.loads(s['receipt_json']);require(r.get('status')=='STATIC_PACKAGE_VALIDATED_RUNTIME_NOT_PERFORMED','Incomplete actual package receipt')
        require((r.get('output',{}).get('sha256'),r.get('output',{}).get('bytes'))==(bound['output_sha256'],bound['output_bytes']),'Receipt output differs')
        source=r.get('source',{}).get('apk_sha256') if platform=='android' else r.get('source_sha256')
        require(source==bound['input_sha256'],'Actual final input differs')
        if platform=='android':
            require(r.get('recipe_sha256')==ANDROID_RECIPE,'Unknown final native/material recipe')
            signed=r.get('signing',{});require(signed.get('certificate_sha256')==ANDROID_CERT and all(signed.get(k) is True for k in ('signature_v1_v2_v3_verified','zipalign_verified','unsigned_entry_bytes_preserved')),'Android signing/payload proof incomplete')
            require(r.get('exact_signature')=={'certificate_sha256':ANDROID_CERT,'signer_count':1,'schemes':[1,2,3]},'Android exact signer differs')
            entries={x['name']:x for x in r.get('signed_preservation',{}).get('entries',[])}
            require(entries.get(bound['native_member'],{}).get('sha256')==bound['native_sha256'] and entries.get(bound['feature_member'],{}).get('sha256')==bound['feature_sha256'],'Actual signed native/helper proof differs')
            require(r.get('helper_sha256')==bound['feature_sha256'] and r.get('unsigned_cleanup',{}).get('completed') is True,'Helper/final verification incomplete')
        else:
            require(r.get('native_patch_plan_sha256')==bound['patch_plan_sha256'],'IPA material hook plan differs')
            require(r.get('signed_main_sha256')==bound['native_sha256'] and r.get('signed_library_sha256')==bound['feature_sha256'],'IPA signed payload differs')
            for key,header in [('main_signature','main_header'),('library_signature','library_header')]:
                signatures=r.get(key,[]);h=r.get(header,{})
                require(signatures and all(x.get('verified') is True and x.get('code_limit')==h.get('signature',[None])[0] for x in signatures),'IPA CodeDirectory proof incomplete')
            if c['id'] in ('ios-gl','ios-jp'):
                require(r.get('local_v5_receipt_sha256')==FINAL_BINDINGS['ios-local-gl']['receipt_sha256'] and r.get('local_v5_archive_sha256')==FINAL_BINDINGS['ios-local-gl']['output_sha256'],'Shared signed helper/main provenance differs')
    binding=value['server_version_binding'];exact(binding,{'source_sha','source_version','packaged_version'},'Server version binding')
    require(binding=={'source_sha':C11_SOURCE,'source_version':'2026.11.13.1','packaged_version':'2026.11.14.1'} and server['source_sha']==C11_SOURCE and server['version']=='2026.11.14.1','Exact reviewed C11 version/source binding required')
    for limit in value['readiness'].get('limitations',[]):require(isinstance(limit,str) and limit and limit in server['notes'],'Release notes omit recorded limitations')
    require(set(LIMITATIONS)<=set(value['readiness'].get('limitations',[])),'Actual device limits must be explicit')
    return value

def validate_readiness(clients, server_sha):
    r=clients['readiness'];exact(r,{'schema_version','observations','historical_clients','issues','history','limitations','validation_scope'},'Readiness')
    require(type(r['schema_version']) is int and r['schema_version']==3,'Readiness schema must be integer3')
    for k in ('observations','historical_clients','issues','history','limitations','validation_scope'):require(isinstance(r[k],list),'Readiness list required: '+k)
    require(set(LIMITATIONS)<=set(r['limitations']) and r['history'],'Limits and historical errors must be retained')
    current={c['id']:c for c in clients['clients']};identities={(c['id'],c['candidate']['sha256']) for c in current.values()}
    for h in r['historical_clients']:
        exact(h,{'id','sha256'},'Historical client');require(h['id'] in SLOTS,'Unknown historical client');base.digest_value(h['sha256'],'Historical client SHA');identities.add((h['id'],h['sha256']))
    observations={}
    for o in r['observations']:
        exact(o,{'id','client_id','client_sha256','case','status','provenance','description','server_source_sha','evidence'},'Observation')
        require(isinstance(o['id'],str) and o['id'] and o['id'] not in observations,'Duplicate/empty observation ID')
        require((o['client_id'],o['client_sha256']) in identities and o['case'] in RUNTIME_CASES,'Unknown observed client/case')
        require(o['status'] in ('PASS','FAIL','UNKNOWN') and o['provenance'] in ('user-reported','automation'),'Unknown observation status/provenance')
        require(isinstance(o['description'],str) and o['description'],'Observation scope absent');commit(o['server_source_sha'],'Observed server source')
        e=o['evidence'];require(isinstance(e,dict) and isinstance(e.get('reference'),str) and e['reference'],'Evidence reference absent')
        if o['status']!='UNKNOWN':
            if o['provenance']=='user-reported':require(e.get('kind')=='conversation' and isinstance(e.get('quote'),str) and e['quote'],'Literal user quote absent')
            else:require(e.get('kind')=='file','Automation evidence must identify a real file');base.digest_value(e.get('sha256'),'Actual automation evidence SHA')
        if o['status']=='FAIL' and o['client_sha256']==current[o['client_id']]['candidate']['sha256']:raise ValidationError('Known actual current product failure: '+o['description'])
        observations[o['id']]=o
    for issue in r['issues']:
        exact(issue,{'id','status','case','description','affected_client_id','affected_client_sha256','resolved_by'},'Known issue')
        require((issue['affected_client_id'],issue['affected_client_sha256']) in identities,'Unknown affected client')
        require(issue['status']=='RESOLVED','Known actual issue is still open: '+issue['description'])
        resolved=observations.get(issue['resolved_by'],{});cid=issue['affected_client_id']
        require(resolved.get('status')=='PASS' and resolved.get('case')==issue['case'] and resolved.get('client_id')==cid and resolved.get('client_sha256')==current[cid]['candidate']['sha256'] and resolved.get('server_source_sha')==server_sha,'Known issue lacks same-variant/current-product matching resolution')
    scopes=r['validation_scope'];require(len(scopes)==5 and {s.get('id') for s in scopes}==set(SLOTS),'Explicit scope for every current client required')
    coverage={}
    for scope in scopes:
        exact(scope,{'id','static_status','observed_cases','not_device_tested_cases'},'Validation scope');cid=scope['id'];c=current[cid]
        require(scope['static_status']=='STATIC_VERIFIED','Actual static checks incomplete')
        yes=scope['observed_cases'];no=scope['not_device_tested_cases']
        require(isinstance(yes,list) and isinstance(no,list) and len(yes)==len(set(yes)) and len(no)==len(set(no)) and not set(yes)&set(no) and set(yes)|set(no)==RUNTIME_CASES,'Runtime scope must be explicit and disjoint')
        for case in yes:
            require(any(o['client_id']==cid and o['client_sha256']==c['candidate']['sha256'] and o['case']==case and o['status']=='PASS' and o['server_source_sha']==server_sha for o in observations.values()),'Runtime PASS cannot be inferred from another product/platform/static check')
        coverage[cid]={'static_status':'STATIC_VERIFIED','observed_cases':yes,'not_device_tested_cases':no}
    require(LOCAL_REQUIRED_CASES<=set(coverage['ios-local-gl']['observed_cases']),'Actual LocalV5 MV/material/face/performance result required')
    require(any(i['affected_client_id']=='ios-local-gl' and i['case']=='material_lighting' for i in r['issues']),'Actual material issue history must be retained and resolved')
    return {'status':'READY_WITH_DISCLOSED_RUNTIME_LIMITS','coverage':coverage,'history':r['history'],'limitations':r['limitations'],'observations':r['observations'],'issues':r['issues']}

def verify_client_archive(c,path):
    """Re-read every member for ZIP CRC and hash actual native/feature payloads."""
    s=c['static'];platform=SLOTS[c['id']][0]
    with zipfile.ZipFile(path) as z:
        rows=z.infolist();names=[r.filename for r in rows]
        require(len(names)==len(set(names)) and len(names)<=25000,'Duplicate/excessive client archive members')
        require(sum(r.file_size for r in rows)<=MAX_EVIDENCE,'Oversize expanded client archive')
        for row in rows:
            mode=(row.external_attr>>16)&0o170000
            if mode==stat.S_IFLNK:
                # Original IPA content has one exact framework-local alias.
                # Never extract or resolve it through the host filesystem.
                app='allstars.app' if c['id']=='ios-jp' else 'global.app'
                parent='Payload/'+app+'/Frameworks/CydiaSubstrate.framework/Libraries/'
                require(platform=='ios' and row.filename==parent+'SubstrateInjection.dylib' and row.file_size==24,'Unexpected client archive link')
                regular=copy.copy(row)
                regular.external_attr=(row.external_attr&~(0o170000<<16))|(stat.S_IFREG<<16)
                base.safe_outer_member(regular) # Same path/compression/encryption/bounds guards.
                require(parent+'SubstrateBootstrap.dylib' in names,'Framework link target absent')
                target=z.getinfo(parent+'SubstrateBootstrap.dylib')
                require(not target.is_dir(),'Framework link target is not a file')
                base.safe_outer_member(target) # Target itself must be a regular ZIP member.
                payload=z.read(row)
                require(payload==b'SubstrateBootstrap.dylib' and sha(payload)=='47afc82c893ca708f3aca1450c1a4638ab2dc191251f5cc05f4a9bddf44e1429','Framework link target differs')
            else:
                base.safe_outer_member(row)
            with z.open(row) as f:
                h=hashlib.sha256();prefix=f.read(32);h.update(prefix)
                for block in iter(lambda:f.read(base.CHUNK),b''):h.update(block)
            if row.filename==s['native_member']:
                require(h.hexdigest()==s['native_sha256'],'Actual native payload differs')
                if platform=='android':require(prefix[:5]==b'\x7fELF\x02' and prefix[5]==1 and int.from_bytes(prefix[18:20],'little')==183,'Android native ABI differs')
                else:require(prefix[:4]==bytes.fromhex('cffaedfe') and int.from_bytes(prefix[4:8],'little')==0x100000c and int.from_bytes(prefix[12:16],'little')==2,'IPA native ABI differs')
            if row.filename==s['feature_member']:require(h.hexdigest()==s['feature_sha256'],'Feature module differs')
        require(s['native_member'] in names and s['feature_member'] in names,'Required native/feature payload absent')


class ReadOnlyRepositoryAPI:
    """Read only the reviewed Elichika metadata and candidate assets."""
    def __init__(self, token): self.transport=base.GitHubAPI(token)
    def json(self,repository,suffix):
        try:return self._json(repository,suffix)
        except urllib.error.HTTPError as error:raise ValidationError('Read-only metadata failed with HTTP'+str(error.code)) from None
        except urllib.error.URLError:raise ValidationError('Read-only metadata connection failed') from None
    def _json(self, repository, suffix):
        require(repository in QA_REPOSITORIES and (suffix=='' or suffix.startswith('/')),'Read outside approved repositories')
        with self.transport._open('https://api.github.com/repos/'+repository+suffix,
                headers={'Accept':'application/vnd.github+json'},authenticated=True) as response:
            require(response.status==200,'Read-only GitHub metadata request failed')
            raw=response.read(16*1024*1024+1);require(len(raw)<=16*1024*1024,'Oversize metadata')
            return json.loads(raw)
    def download(self,repository,suffix,destination,size,artifact=False):
        try:return self._download(repository,suffix,destination,size,artifact)
        except urllib.error.HTTPError as error:raise ValidationError('Read-only binary download failed with HTTP'+str(error.code)) from None
        except urllib.error.URLError:raise ValidationError('Read-only binary download connection failed') from None
    def _download(self, repository, suffix, destination, size, artifact=False):
        require(repository in QA_REPOSITORIES and suffix.startswith('/'),'Download outside approved repositories')
        url='https://api.github.com/repos/'+repository+suffix;auth=True;h=hashlib.sha256();count=0
        out=Path(destination).open('xb') if destination else None
        try:
            for _ in range(6):
                with self.transport._open(url,headers={'Accept':'application/json' if artifact and auth else 'application/octet-stream'},authenticated=auth) as response:
                    if response.status in (301,302,303,307,308):
                        target=urllib.parse.urljoin(url,response.headers.get('Location',''));parsed=urllib.parse.urlsplit(target);host=parsed.hostname or ''
                        require(parsed.scheme=='https' and not parsed.username and not parsed.password and (host.endswith('.blob.core.windows.net') or host.endswith('.actions.githubusercontent.com') or host in {'objects.githubusercontent.com','release-assets.githubusercontent.com'}),'Unsafe client download redirect')
                        url,auth=target,False;continue
                    require(response.status==200,'Client download failed')
                    for chunk in iter(lambda:response.read(base.CHUNK),b''):
                        count+=len(chunk);require(count<=size,'Client download exceeded approved size');h.update(chunk)
                        if out:out.write(chunk)
                    require(count==size,'Client download size differs');return count,h.hexdigest()
            raise ValidationError('Too many client redirects')
        finally:
            if out:out.close()


class GuardedServerAPI:
    """No tag creation, retagging, deletion, or cross-repository writes."""
    def __init__(self, api):self.api,self.allowed,self.publisher=api,False,None
    def json(self,method,path,payload=None,allow_missing=False):
        prefix='/repos/'+SERVER_REPOSITORY
        require(path.startswith(prefix+'/'),'Server API outside Elichika')
        if method!='GET':
            require(self.allowed,'Joint QA validation has not completed')
            suffix=path[len(prefix):]
            if method=='POST':
                require(suffix=='/releases' and payload.get('draft') is True and payload.get('tag_name')==self.publisher.tag and payload.get('target_commitish')==self.publisher.source_sha,'Only an owned Elichika draft may be created; git refs writes are forbidden')
            else:
                require(method=='PATCH' and self.publisher.release_id is not None and suffix=='/releases/'+str(self.publisher.release_id) and payload=={'draft':False,'prerelease':False,'make_latest':'true'},'Only final publication of the verified owned release is allowed')
        return self.api.json(method,path,payload,allow_missing=allow_missing)
    def download_artifact(self,*args):return self.api.download_artifact(*args)
    def hash_release_asset(self,*args):return self.api.hash_release_asset(*args)
    def upload(self,release_id,file):
        require(self.allowed and release_id==self.publisher.release_id,'Upload before joint validation or outside owned release')
        return self.api.upload(release_id,file)


class JointPublisher(base.Publisher):
    def __init__(self,api,reads,manifest,clients,repository,source_sha,version_text,work_dir,*,publisher_source_sha=None,tag_gate=None):
        self.clients=parse_clients(clients,manifest);self.reads=reads;self.tag_gate=tag_gate;self.publication_requested=False
        self.client_manifest_sha256=sha(canonical(clients))
        require('<!-- elichika-joint-clients:'+self.client_manifest_sha256+' -->' in manifest['notes'],'Server notes do not bind the exact five-client manifest')
        guarded=GuardedServerAPI(api)
        binding=self.clients['server_version_binding']
        require(version_text.strip()==binding['source_version'],'Source VERSION differs from explicit binding')
        super().__init__(guarded,manifest,repository,source_sha,binding['packaged_version'],work_dir,publisher_source_sha=publisher_source_sha)
        self.result['server_version_binding']=binding
        guarded.publisher=self
        self.result['client_manifest_sha256']=self.client_manifest_sha256
        self.result['base_publisher_sha256']=BASE_SHA256
        self.result['private_original_binding']='Root-reviewed manifest and hash-bound QA source receipt; private repository is never accessed or mutated'

    def _read(self,repository,suffix):return self.reads.json(repository,suffix)
    def _jobs(self,repository,run_id):
        jobs=[]
        for page in range(1,11):
            data=self._read(repository,f'/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}')
            require(type(data.get('total_count')) is int and isinstance(data.get('jobs'),list),'Malformed QA jobs')
            jobs+=data['jobs']
            if len(jobs)>=data['total_count']:return jobs
        raise ValidationError('Too many QA jobs')
    def _workflow_source(self,repository,path,source_sha,expected):
        value=self._read(repository,'/contents/'+path+'?ref='+source_sha)
        require(value.get('path')==path and value.get('encoding')=='base64' and value.get('type')=='file','Wrong workflow source')
        raw=base64.b64decode(value.get('content',''),validate=False)
        require(len(raw)<=1024*1024 and sha(raw)==expected,'QA workflow source hash differs')
    def check_runs(self):
        # Exact same-source server Android/Mac/general checks are unchanged.
        super().check_runs()



    def _release_input(self,c,key,repository,release_id,destination):
        expected=c[key];release=self._read(repository,'/releases/'+str(release_id))
        require(release.get('id')==release_id and release.get('draft') is True,'Original and QA releases must remain unpublished drafts')
        assets=[a for a in release.get('assets',[]) if a.get('id')==expected['asset_id']]
        require(len(assets)==1,'Missing exact client input asset')
        asset=assets[0]
        require(asset.get('name')==expected['name'] and asset.get('state')=='uploaded' and asset.get('size')==expected['bytes'] and asset.get('digest')=='sha256:'+expected['sha256'],'Client input asset metadata differs')
        count,digest=self.reads.download(repository,'/releases/assets/'+str(expected['asset_id']),destination,expected['bytes'])
        require(count==expected['bytes'] and digest==expected['sha256'],'Client input bytes differ from approved SHA256')
        if destination:
            require(base.file_digest(destination)==digest,'Staged client bytes differ')
            if key=='candidate':verify_client_archive(c,Path(destination))

    def _qa_report(self,c):
        # Root-reviewed literal static receipts; human runtime need not be CI.
        s=c['static']
        return {'id':c['id'],'static_receipt_sha256':s['receipt_sha256'],'native_sha256':s['native_sha256'],'feature_sha256':s['feature_sha256']}


    def check_release(self):
        ref=self._api('GET','/git/ref/tags/'+self.tag,missing=True)
        require(ref is not None and ref.get('object',{}).get('type')=='commit' and ref['object'].get('sha')==self.source_sha,'Joint publication requires an existing exact lightweight token-created tag')
        return super().check_release()

    def check_artifacts(self):
        self.result['client_readiness']=validate_readiness(self.clients,self.source_sha)
        client_files,receipts={},[]
        for c in sorted(self.clients['clients'],key=lambda row:row['id']):
            # Original private inputs are bound by the root-reviewed client
            # manifest and source receipt fields in the actual QA report. The
            # same-repository GITHUB_TOKEN never reads or mutates private SIFAS.
            receipts.append(self._qa_report(c))
            destination=self.work_dir/c['name']
            self._release_input(c,'candidate',self.clients['candidate_repository'],self.clients['candidate_release_id'],destination)
            client_files[c['id']]={'name':c['name'],'path':str(destination),'bytes':c['candidate']['bytes'],'sha256':c['candidate']['sha256']}
        files=super().check_artifacts()
        require(not ({f['name'] for f in files.values()} & {f['name'] for f in client_files.values()}),'Client and server asset name collision')
        files.update(client_files)
        installables=[files[k] for k in ['android','macos']+sorted(SLOTS)]
        require(len(installables)==7,'Exactly seven installables are mandatory')
        content=''.join(f['sha256']+'  '+f['name']+'\n' for f in installables).encode()
        checksum=self.work_dir/'SHA256SUMS';checksum.write_bytes(content)
        files['checksums']={'name':'SHA256SUMS','path':str(checksum),'bytes':len(content),'sha256':sha(content)}
        approval={'schema_version':1,'server_manifest_sha256':sha(canonical(self.manifest)),'client_manifest_sha256':self.client_manifest_sha256,'source_sha':self.source_sha,'tag':self.tag,'installables':[{k:f[k] for k in ['name','bytes','sha256']} for f in installables],'client_static':receipts,'client_readiness':self.result['client_readiness']}
        self.approval_sha256=sha(canonical(approval));self.result['joint_approval']=approval;self.result['joint_approval_sha256']=self.approval_sha256
        if self.publication_requested:
            self.check_tag_gate(self.approval_sha256)
            self.api.allowed=True
        return files

    def validate(self):
        self.check_publisher_source();self.check_runs();files=self.check_artifacts()
        self.result.update(status='PASS_JOINT_PREFLIGHT_NO_MUTATIONS',mutation_started=False,assets=[{k:f[k] for k in ['name','bytes','sha256']} for f in files.values()])
        (self.work_dir/'joint-preflight.json').write_text(json.dumps(self.result,indent=2)+'\n')
        return self.result

    def run(self):
        self.publication_requested=True
        return super().run()

    def check_tag_gate(self,approval_sha256):
        gate=self.tag_gate
        exact(gate,{'run_id','source_sha','workflow_sha256','artifact_id','zip_sha256','report_sha256'},'Tag gate')
        commit(gate['source_sha'],'Tag helper source')
        for key in ['run_id','artifact_id']:base.positive_int(gate[key],key)
        for key in ['workflow_sha256','zip_sha256','report_sha256']:base.digest_value(gate[key],key)
        self._workflow_source(SERVER_REPOSITORY,TAG_WORKFLOW,gate['source_sha'],gate['workflow_sha256'])
        workflow=self._api('GET','/actions/workflows/'+TAG_WORKFLOW.rsplit('/',1)[1])
        require(workflow.get('path')==TAG_WORKFLOW and workflow.get('name')==TAG_WORKFLOW_NAME and workflow.get('state')=='active','Wrong tag helper workflow')
        run=self._api('GET','/actions/runs/'+str(gate['run_id']))
        require(run.get('id')==gate['run_id'] and run.get('head_sha')==gate['source_sha'] and run.get('head_branch')==TAG_BRANCH and run.get('event')=='push' and run.get('name')==TAG_WORKFLOW_NAME and run.get('workflow_id')==workflow.get('id') and run.get('status')=='completed' and run.get('conclusion')=='success' and run.get('repository',{}).get('full_name')==SERVER_REPOSITORY and run.get('head_repository',{}).get('full_name')==SERVER_REPOSITORY,'Wrong/failed tag helper run')
        jobs=self._jobs(SERVER_REPOSITORY,gate['run_id'])
        require({j.get('name') for j in jobs}=={'tag','publish'} and all(j.get('status')=='completed' for j in jobs) and next(j for j in jobs if j.get('name')=='tag').get('conclusion')=='success' and next(j for j in jobs if j.get('name')=='publish').get('conclusion')=='skipped','Only the completed preflight/tag phase may attest publication')
        self.check_helper_source(gate['source_sha'])
        artifact=self._api('GET','/actions/artifacts/'+str(gate['artifact_id']))
        require(artifact.get('id')==gate['artifact_id'] and artifact.get('name')=='joint-tag-attestation' and artifact.get('expired') is False and artifact.get('digest')=='sha256:'+gate['zip_sha256'] and artifact.get('workflow_run',{}).get('id')==gate['run_id'] and artifact.get('workflow_run',{}).get('head_sha')==gate['source_sha'],'Wrong tag attestation artifact')
        size=artifact.get('size_in_bytes');require(type(size) is int and 0<size<=MAX_REPORT,'Invalid tag attestation size')
        archive=self.work_dir/'tag-attestation.zip';count,digest=self.api.download_artifact(gate['artifact_id'],archive,size)
        require(count==size and digest==gate['zip_sha256'] and base.file_digest(archive)==digest,'Tag attestation ZIP bytes differ')
        destination=self.work_dir/'joint-tag-attestation.json'
        base.extract_single_file(archive,'joint-tag-attestation.json',destination,gate['report_sha256'])
        report=json.loads(destination.read_text())
        exact(report,{'schema_version','status','run_id','helper_source_sha','helper_branch','source_sha','tag','tag_type','approval_sha256','created'},'Tag attestation')
        require(type(report['schema_version']) is int and report['schema_version']==1 and report['status']=='PASS' and report['run_id']==gate['run_id'] and report['helper_source_sha']==gate['source_sha'] and report['helper_branch']==TAG_BRANCH and report['source_sha']==self.source_sha and report['tag']==self.tag and report['tag_type']=='commit' and report['approval_sha256']==approval_sha256 and type(report['created']) is bool,'Tag attestation does not bind exact joint approval')
        self.result['tag_gate']={'run_id':gate['run_id'],'helper_source_sha':gate['source_sha'],'approval_sha256':approval_sha256}

    def check_helper_source(self,helper_sha):
        commit(helper_sha,'Release helper source')
        comparison=self._api('GET','/compare/'+self.source_sha+'...'+helper_sha)
        require(comparison.get('status')=='ahead' and comparison.get('ahead_by')==1 and comparison.get('behind_by')==0 and comparison.get('total_commits')==1 and comparison.get('base_commit',{}).get('sha')==self.source_sha and comparison.get('merge_base_commit',{}).get('sha')==self.source_sha,'Tag helper must directly descend from validated server')
        commits=comparison.get('commits',[]);changes=comparison.get('files',[])
        require(len(commits)==1 and commits[0].get('sha')==helper_sha and [p.get('sha') for p in commits[0].get('parents',[])]==[self.source_sha] and len(changes)==len(HELPER_PATHS) and {change.get('filename') for change in changes}==HELPER_PATHS and all(change.get('status')=='added' and 'previous_filename' not in change for change in changes),'Tag helper may only add the approved isolated CI files')
        def tree(commit_sha):
            meta=self._api('GET','/git/commits/'+commit_sha)
            require(meta.get('sha')==commit_sha,'Wrong helper/source commit identity')
            tree_sha=commit(meta.get('tree',{}).get('sha'),'Helper/source tree')
            data=self._api('GET','/git/trees/'+tree_sha+'?recursive=1')
            require(data.get('sha')==tree_sha and data.get('truncated') is False and isinstance(data.get('tree'),list),'Incomplete tag helper source tree')
            rows={}
            for row in data['tree']:
                require(row.get('path') not in rows,'Duplicate source tree path');rows[row['path']]=(row.get('mode'),row.get('type'),row.get('sha'))
            return rows
        old,new=tree(self.source_sha),tree(helper_sha)
        require(set(new)==set(old)|HELPER_PATHS and all(new[name][:2]==('100644','blob') for name in HELPER_PATHS),'Unexpected tag helper source additions/modes')
        require(all(old[name][:2]==new[name][:2] for name in old),'Tag helper changes source modes or types')
        require(all(old[name]==new[name] for name in old if old[name][1]!='tree'),'Tag helper changes app bytes or gitlinks')
        ancestors={'.github','.github/workflows','macos','macos/ci'}
        require({name for name in old if old[name][1]=='tree' and old[name]!=new[name]}<=ancestors,'Tag helper changes unrelated source directories')
        self.result['helper_source_guard']={'status':'PASS_APPROVED_CI_ADDITIONS_ONLY','source_sha':helper_sha,'paths':sorted(HELPER_PATHS)}


def tag_gate_for_run(api,reads,run_id,directory):
    """Resolve an explicit root-approved completed preflight run; never guess latest."""
    base.positive_int(run_id,'Approved preflight run')
    prefix='/repos/'+SERVER_REPOSITORY
    run=api.json('GET',prefix+'/actions/runs/'+str(run_id))
    require(run.get('status')=='completed' and run.get('conclusion')=='success' and run.get('head_branch')==TAG_BRANCH and run.get('event')=='push','Approved preflight run is not a successful tag phase')
    source=commit(run.get('head_sha'),'Approved helper source')
    data=api.json('GET',prefix+f'/actions/runs/{run_id}/artifacts?per_page=100')
    matches=[a for a in data.get('artifacts',[]) if a.get('name')=='joint-tag-attestation']
    require(len(matches)==1 and data.get('total_count',0)<=100,'Missing or ambiguous tag attestation')
    artifact=matches[0];require(artifact.get('expired') is False,'Tag attestation expired')
    digest=artifact.get('digest','').removeprefix('sha256:');base.digest_value(digest,'Tag ZIP digest')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    archive=directory/'approved-tag-attestation.zip'
    count,actual=api.download_artifact(artifact['id'],archive,artifact['size_in_bytes'])
    require(count==artifact['size_in_bytes'] and actual==digest and base.file_digest(archive)==digest,'Approved tag ZIP bytes differ')
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist();require(len(entries)==1 and entries[0].filename=='joint-tag-attestation.json' and entries[0].file_size<=MAX_REPORT,'Unexpected tag receipt members')
        base.safe_outer_member(entries[0]);raw=z.read(entries[0]);receipt=json.loads(raw)
    workflow=reads.json(SERVER_REPOSITORY,'/contents/'+TAG_WORKFLOW+'?ref='+source)
    workflow_sha=sha(base64.b64decode(workflow['content']))
    return {'run_id':run_id,'source_sha':source,'workflow_sha256':workflow_sha,'artifact_id':artifact['id'],'zip_sha256':digest,'report_sha256':sha(raw)},receipt


def assert_workflow_installation_token(api):
    # Installation tokens emit no recursive workflow events. User OAuth/PAT
    # credentials must never create a release tag through this helper.
    require(isinstance(getattr(api,'token',None),str) and api.token.startswith('ghs_'),'Tag creation requires a GitHub App installation token, never user OAuth/PAT')
    try:
        with api._open('https://api.github.com/installation/repositories',headers={'Accept':'application/vnd.github+json'},authenticated=True) as response:
            require(response.status==200,'Could not establish installation-token identity')
            value=json.loads(response.read(1024*1024+1))
            require(any(repo.get('full_name')==SERVER_REPOSITORY for repo in value.get('repositories',[])),'Installation token does not own Elichika')
    except (urllib.error.HTTPError,urllib.error.URLError):
        raise ValidationError('Tag creation token is not an authenticated workflow installation token') from None


def create_token_tag(api,publisher,helper_sha):
    """CI-only tag phase, after full preflight. Never called by validate() or run()."""
    require(os.environ.get('GITHUB_REPOSITORY')==SERVER_REPOSITORY and os.environ.get('GITHUB_EVENT_NAME')=='push' and os.environ.get('GITHUB_REF')=='refs/heads/'+TAG_BRANCH and os.environ.get('GITHUB_SHA')==helper_sha,'Tag creation requires the exact isolated GITHUB_TOKEN CI phase')
    require(publisher.result.get('status')=='PASS_JOINT_PREFLIGHT_NO_MUTATIONS','Tag creation requires completed joint preflight')
    assert_workflow_installation_token(api)
    publisher.check_helper_source(helper_sha)
    prefix='/repos/'+SERVER_REPOSITORY
    version=api.json('GET',prefix+'/contents/macos/VERSION?ref='+publisher.source_sha)
    require(version.get('path')=='macos/VERSION' and version.get('encoding')=='base64' and base64.b64decode(version.get('content','')).decode().strip()==publisher.clients['server_version_binding']['source_version'],'Frozen server version differs')
    ref=api.json('GET',prefix+'/git/ref/tags/'+publisher.tag,allow_missing=True)
    created=ref is None
    if ref is None:
        ref=api.json('POST',prefix+'/git/refs',{'ref':'refs/tags/'+publisher.tag,'sha':publisher.source_sha})
    require(ref.get('object',{}).get('type')=='commit' and ref['object'].get('sha')==publisher.source_sha,'Existing annotated or wrong-source tag is forbidden; no retagging')
    verified=api.json('GET',prefix+'/git/ref/tags/'+publisher.tag)
    require(verified.get('object',{}).get('type')=='commit' and verified['object'].get('sha')==publisher.source_sha,'Token-created tag verification failed')
    report={'schema_version':1,'status':'PASS','run_id':int(os.environ['GITHUB_RUN_ID']),'helper_source_sha':helper_sha,'helper_branch':TAG_BRANCH,'source_sha':publisher.source_sha,'tag':publisher.tag,'tag_type':'commit','approval_sha256':publisher.approval_sha256,'created':created}
    (publisher.work_dir/'joint-tag-attestation.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-manifest',type=Path,required=True)
    parser.add_argument('--client-manifest',type=Path,required=True)
    parser.add_argument('--source-sha',required=True)
    parser.add_argument('--version-file',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--helper-sha',required=True)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--create-token-tag',action='store_true')
    actions.add_argument('--publish',action='store_true')
    parser.add_argument('--approved-preflight-run-id',type=int)
    args=parser.parse_args()
    require(os.environ.get('GITHUB_REPOSITORY')==SERVER_REPOSITORY,'Only Elichika CI may operate this wrapper')
    require(os.environ.get('GITHUB_SHA')==args.helper_sha,'Executing helper commit differs')
    token=os.environ.get('GITHUB_TOKEN','');require(token,'This CI run GITHUB_TOKEN is required')
    api=base.GitHubAPI(token);reads=ReadOnlyRepositoryAPI(token)
    manifest=json.loads(args.server_manifest.read_text());clients=json.loads(args.client_manifest.read_text())
    gate=None
    if args.publish:
        assert_workflow_installation_token(api)
        prefix='refs/heads/codex/joint-publish-20261115-v4-'
        require(os.environ.get('GITHUB_EVENT_NAME')=='push' and os.environ.get('GITHUB_REF')==prefix+str(args.approved_preflight_run_id),'Publication requires a new exact root-approved preflight-run branch')
        gate,receipt=tag_gate_for_run(api,reads,args.approved_preflight_run_id,args.work_dir.parent/'approved-tag')
        require(gate['source_sha']==args.helper_sha,'Publish branch differs from the approved frozen helper commit')
    publisher=JointPublisher(api,reads,manifest,clients,SERVER_REPOSITORY,args.source_sha,args.version_file.read_text(),args.work_dir,tag_gate=gate)
    publisher.check_helper_source(args.helper_sha)
    result=publisher.run() if args.publish else publisher.validate()
    if args.create_token_tag:result=create_token_tag(api,publisher,args.helper_sha)
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':
    import sys
    try:raise SystemExit(main())
    except (ValidationError,ValueError,OSError,zipfile.BadZipFile) as error:
        print('Joint release rejected: '+(str(error) if isinstance(error,ValidationError) else type(error).__name__),file=sys.stderr)
        raise SystemExit(1)
