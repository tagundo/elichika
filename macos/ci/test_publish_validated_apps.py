"""Publisher contract tests: real small ZIPs, source guards and draft-only failures."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

MODULE_PATH = Path(__file__).with_name('publish_validated_apps.py')
spec = importlib.util.spec_from_file_location('publish_validated_apps', MODULE_PATH)
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
SHA = 'a' * 40
OTHER = 'b' * 40
VERSION = '2026.11.12.2'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def make_zip(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in entries:
            z.writestr(name, raw)
    return output.getvalue()


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.downloads = []
        self.uploads = []
        self.remote_hashes = []
        self.tag = None
        self.release = None
        self.next_asset = 1000
        self.asset_bytes = {}
        self.fail_upload_at = None
        self.corrupt_upload = False
        self.raw = {'android': b'actual-apk-fixture-bytes', 'macos': b'actual-app-archive-fixture-bytes'}
        self.manifest = {'schema_version': 1, 'version': VERSION, 'source_sha': SHA,
                         'notes': 'Validated APK and Mac test release.'}
        self.workflow, self.runs, self.jobs, self.artifacts, self.zip_bytes = {}, {}, {}, {}, {}
        for index, (kind, (filename, name, required)) in enumerate(pub.WORKFLOWS.items(), 1):
            run_id, artifact_id = 100 + index, 200 + index
            self.workflow[filename] = {'id': index, 'name': name, 'path': '.github/workflows/' + filename, 'state': 'active'}
            self.runs[run_id] = {'id': run_id, 'workflow_id': index, 'name': name, 'event': 'workflow_dispatch',
                'repository': {'full_name': pub.REPOSITORY}, 'head_repository': {'full_name': pub.REPOSITORY},
                'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'}
            self.jobs[run_id] = [{'name': n, 'status': 'completed', 'conclusion': 'success'} for n in sorted(required)]
            if kind == 'android':
                self.jobs[run_id].append({'name': 'publish', 'status': 'completed', 'conclusion': 'skipped'})
            if kind == 'macos':
                self.jobs[run_id].append({'name': 'publish-validated-apps', 'status': 'completed', 'conclusion': 'skipped'})
            if kind == 'general':
                raw = make_zip([('report.json', b'{"status":"PASS"}')])
            else:
                file = 'elichika-' + VERSION + '.apk' if kind == 'android' else 'Elichika-' + VERSION + '-AppleSilicon.app.zip'
                entries = [(file, self.raw[kind])]
                if kind == 'macos':
                    entries.append(('SHA256SUMS', (digest(self.raw[kind]) + '  ' + file + '\n').encode()))
                raw = make_zip(entries)
            self.zip_bytes[artifact_id] = raw
            self.artifacts[artifact_id] = {'id': artifact_id, 'name': pub.ARTIFACT_NAMES[kind], 'expired': False,
                'digest': 'sha256:' + digest(raw), 'size_in_bytes': len(raw),
                'workflow_run': {'id': run_id, 'head_sha': SHA}}
            self.manifest[kind] = {'run_id': run_id, 'artifact_id': artifact_id, 'zip_sha256': digest(raw)}
            if kind != 'general':
                self.manifest[kind]['file_sha256'] = digest(self.raw[kind])

    @property
    def mutations(self):
        return [x for x in self.calls if x[0] != 'GET']

    def json(self, method, path, payload=None, allow_missing=False):
        self.calls.append((method, path, deepcopy(payload)))
        prefix = '/repos/' + pub.REPOSITORY
        assert path.startswith(prefix + '/')
        suffix = path[len(prefix):]
        if method == 'GET':
            if suffix.startswith('/actions/workflows/'):
                return deepcopy(self.workflow[suffix.rsplit('/', 1)[1]])
            if suffix.startswith('/actions/runs/'):
                run_id = int(suffix.split('/')[3])
                if '/jobs?' in suffix:
                    return {'total_count': len(self.jobs[run_id]), 'jobs': deepcopy(self.jobs[run_id])}
                return deepcopy(self.runs[run_id])
            if suffix.startswith('/actions/artifacts/'):
                return deepcopy(self.artifacts[int(suffix.rsplit('/', 1)[1])])
            if suffix.startswith('/git/ref/tags/'):
                return None if self.tag is None else {'object': {'type': 'commit', 'sha': self.tag}}
            if suffix.startswith('/releases/tags/') or suffix == '/releases/999':
                return deepcopy(self.release)
        if method == 'POST' and suffix == '/git/refs':
            assert self.tag is None
            self.tag = payload['sha']
            return {'ref': payload['ref'], 'object': {'sha': self.tag, 'type': 'commit'}}
        if method == 'POST' and suffix == '/releases':
            assert self.release is None
            self.release = dict(deepcopy(payload), id=999, html_url='https://github.com/' + pub.REPOSITORY + '/releases/tag/v' + VERSION, assets=[])
            return deepcopy(self.release)
        if method == 'PATCH' and suffix == '/releases/999':
            assert len(self.release['assets']) == 3
            self.release.update(payload)
            return deepcopy(self.release)
        raise AssertionError((method, suffix))

    def download_artifact(self, artifact_id, destination, size):
        self.downloads.append(artifact_id)
        raw = self.zip_bytes[artifact_id]
        Path(destination).write_bytes(raw)
        return len(raw), digest(raw)

    def upload(self, release_id, file):
        self.calls.append(('UPLOAD', str(release_id), file['name']))
        if self.fail_upload_at == len(self.uploads) + 1:
            raise pub.ValidationError('Simulated upload failure')
        self.uploads.append(file['name'])
        raw = Path(file['path']).read_bytes()
        if self.corrupt_upload:
            raw = raw[:-1] + bytes([raw[-1] ^ 1])
        self.next_asset += 1
        asset = {'id': self.next_asset, 'name': file['name'], 'size': len(raw), 'state': 'uploaded',
                 'digest': 'sha256:' + digest(raw), 'browser_download_url': 'https://github.com/example/' + file['name']}
        self.asset_bytes[asset['id']] = raw
        self.release['assets'].append(asset)
        return deepcopy(asset)

    def hash_release_asset(self, asset_id, size):
        self.remote_hashes.append(asset_id)
        raw = self.asset_bytes[asset_id]
        return len(raw), digest(raw)


class PublisherContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='publisher-contract-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.counter = 0
        self.api = FakeAPI()

    def publisher(self, manifest=None):
        self.counter += 1
        return pub.Publisher(self.api, manifest or self.api.manifest, pub.REPOSITORY, SHA, VERSION + '\n', self.base / str(self.counter))

    def rejected_before_write(self, mutate):
        mutate()
        with self.assertRaises(pub.ValidationError):
            self.publisher().run()
        self.assertEqual(self.api.mutations, [])
        self.assertIsNone(self.api.release)
        self.assertIsNone(self.api.tag)

    def replace_zip(self, kind, entries):
        entry = self.api.manifest[kind]
        raw = make_zip(entries)
        self.api.zip_bytes[entry['artifact_id']] = raw
        entry['zip_sha256'] = digest(raw)
        self.api.artifacts[entry['artifact_id']].update(digest='sha256:' + digest(raw), size_in_bytes=len(raw))

    def test_publishes_exact_three_assets_only_after_all_checks(self):
        result = self.publisher().run()
        self.assertEqual(result['status'], 'PASS_PUBLISHED_VALIDATED_APPS')
        self.assertEqual(self.api.tag, SHA)
        self.assertFalse(self.api.release['draft'])
        self.assertEqual(len(self.api.downloads), 3)
        self.assertEqual(len(self.api.uploads), 3)
        self.assertEqual(len(self.api.remote_hashes), 3)
        checksums = next(a for a in self.api.release['assets'] if a['name'] == 'SHA256SUMS')
        expected = ''.join(digest(self.api.raw[k]) + '  ' + ('elichika-' + VERSION + '.apk' if k == 'android' else 'Elichika-' + VERSION + '-AppleSilicon.app.zip') + '\n' for k in ['android','macos'])
        self.assertEqual(self.api.asset_bytes[checksums['id']], expected.encode())
        self.assertEqual([x[0] for x in self.api.mutations], ['POST','POST','UPLOAD','UPLOAD','UPLOAD','PATCH'])

    def test_identical_publication_is_read_only_and_never_overwrites(self):
        self.publisher().run()
        mutations = list(self.api.mutations)
        result = self.publisher().run()
        self.assertEqual(result['status'], 'PASS_ALREADY_PUBLISHED_IDENTICAL_BYTES')
        self.assertEqual(self.api.mutations, mutations)

    def test_failed_upload_leaves_owned_draft_and_resumes_without_overwrite(self):
        self.api.fail_upload_at = 2
        with self.assertRaises(pub.ValidationError):
            self.publisher().run()
        self.assertTrue(self.api.release['draft'])
        first_name = self.api.uploads[0]
        self.api.fail_upload_at = None
        self.assertEqual(self.publisher().run()['status'], 'PASS_PUBLISHED_VALIDATED_APPS')
        self.assertEqual(self.api.uploads.count(first_name), 1)

    def test_remote_rehash_failure_never_publishes(self):
        self.api.corrupt_upload = True
        with self.assertRaises(pub.ValidationError):
            self.publisher().run()
        self.assertTrue(self.api.release['draft'])
        self.assertFalse(any(x[0] == 'PATCH' for x in self.api.mutations))

    def test_every_required_native_job_must_pass(self):
        for kind, (_,_,required) in pub.WORKFLOWS.items():
            for name in required:
                with self.subTest(kind=kind, job=name):
                    self.api = FakeAPI()
                    rid = self.api.manifest[kind]['run_id']
                    self.rejected_before_write(lambda: next(j for j in self.api.jobs[rid] if j['name'] == name).update(conclusion='skipped'))

    def test_failed_run_wrong_source_or_repository_is_rejected(self):
        for field,value in [('conclusion','failure'),('status','in_progress'),('head_sha',OTHER),('event','pull_request'),('workflow_id',999),('head_repository',{'full_name':'other/fork'})]:
            with self.subTest(field=field):
                self.api = FakeAPI()
                self.rejected_before_write(lambda: self.api.runs[101].update({field:value}))

    def test_workflow_identity_and_unknown_failed_job_are_rejected(self):
        self.rejected_before_write(lambda: self.api.workflow['macos.yml'].update(path='.github/workflows/other.yml'))
        self.api = FakeAPI()
        self.rejected_before_write(lambda: self.api.jobs[102].append({'name':'extra','status':'completed','conclusion':'failure'}))

    def test_expired_wrong_name_head_run_and_digest_artifacts_are_rejected(self):
        for field,value in [('expired',True),('name','elichika-macos-unvalidated-candidate'),('digest','sha256:'+'0'*64),('workflow_run',{'id':999,'head_sha':SHA})]:
            with self.subTest(field=field):
                self.api = FakeAPI()
                self.rejected_before_write(lambda: self.api.artifacts[202].update({field:value}))

    def test_downloaded_zip_and_raw_file_hashes_are_both_enforced(self):
        self.rejected_before_write(lambda: self.api.zip_bytes.__setitem__(201, self.api.zip_bytes[201]+b'tampered'))
        self.api = FakeAPI()
        self.rejected_before_write(lambda: self.api.manifest['android'].update(file_sha256='0'*64))

    def test_outer_zip_extra_files_traversal_and_wrong_embedded_checksum_are_rejected(self):
        apk = 'elichika-' + VERSION + '.apk'
        for entries in [[(apk,self.api.raw['android']),('extra.txt',b'extra')],[('../'+apk,self.api.raw['android'])],[('/'+apk,self.api.raw['android'])]]:
            with self.subTest(entries=[x[0] for x in entries]):
                self.api = FakeAPI()
                self.rejected_before_write(lambda: self.replace_zip('android',entries))
        self.api = FakeAPI()
        mac = 'Elichika-' + VERSION + '-AppleSilicon.app.zip'
        self.rejected_before_write(lambda:self.replace_zip('macos',[(mac,self.api.raw['macos']),('SHA256SUMS',b'wrong\n')]))

    def test_outer_symlink_and_size_limits_are_rejected(self):
        apk = 'elichika-' + VERSION + '.apk'
        link = zipfile.ZipInfo(apk)
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.rejected_before_write(lambda:self.replace_zip('android',[(link,self.api.raw['android'])]))
        self.api = FakeAPI()
        with patch.object(pub,'MAX_FILE',5):
            self.rejected_before_write(lambda:None)

    def test_existing_tag_or_release_mismatch_never_mutates(self):
        self.api.tag = OTHER
        with self.assertRaises(pub.ValidationError):
            self.publisher().run()
        self.assertEqual(self.api.mutations,[])
        self.api = FakeAPI();self.api.tag = SHA
        self.api.release = {'tag_name':'v'+VERSION,'prerelease':False,'body':'someone else','draft':True}
        with self.assertRaises(pub.ValidationError):
            self.publisher().run()
        self.assertEqual(self.api.mutations,[])

    def test_manifest_requires_fixed_repo_source_version_hashes_and_unique_runs(self):
        good = self.api.manifest
        for mutate in [lambda d:d.update(source_sha=OTHER),lambda d:d.update(version='2026.02.31.2'),lambda d:d.update(schema_version=True),lambda d:d['android'].update(run_id=True),lambda d:d['macos'].update(run_id=d['android']['run_id']),lambda d:d['android'].update(file_sha256='SHA256:bad')]:
            with self.subTest(mutate=mutate):
                data=deepcopy(good);mutate(data)
                with self.assertRaises(pub.ValidationError):
                    pub.parse_manifest(data,pub.REPOSITORY,SHA,VERSION)
        with self.assertRaises(pub.ValidationError):
            pub.parse_manifest(good,'other/repo',SHA,VERSION)
        with self.assertRaises(pub.ValidationError):
            pub.parse_manifest(good,pub.REPOSITORY,SHA,'2026.11.12.1')

    def test_workflow_publication_is_separate_from_normal_build_and_job_scoped(self):
        workflow = MODULE_PATH.parents[2] / '.github/workflows/macos.yml'
        text=workflow.read_text()
        self.assertIn('  apple-silicon:\n    if: ${{ !inputs.validated_release }}',text)
        self.assertIn("  publish-validated-apps:\n    if: ${{ github.event_name == 'workflow_dispatch' && inputs.validated_release != '' }}",text)
        self.assertEqual(text.count('contents: write'),1)
        self.assertIn('permissions:\n  contents: read',text)
        build=text.split('  publish-validated-apps:')[0]
        self.assertNotIn('contents: write',build)
        self.assertIn('--manifest-env VALIDATED_RELEASE_JSON',text)


class DownloadCredentialTests(unittest.TestCase):
    class Response:
        def __init__(self,status,headers=None,raw=b''):
            self.status=status;self.headers=headers or {};self.stream=io.BytesIO(raw)
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def read(self,size=-1):return self.stream.read(size)

    def test_blob_redirect_never_receives_api_authorization(self):
        api=pub.GitHubAPI('private-test-token');requests=[]
        responses=[self.Response(302,{'Location':'https://productiontest.blob.core.windows.net/private?sig=secret'}),self.Response(200,raw=b'zip')]
        def opened(req,timeout):requests.append(req);return responses.pop(0)
        api.opener.open=opened
        self.assertEqual(api._download('/repos/'+pub.REPOSITORY+'/actions/artifacts/1/zip',None,3),(3,digest(b'zip')))
        self.assertEqual(requests[0].get_header('Authorization'),'Bearer private-test-token')
        self.assertIsNone(requests[1].get_header('Authorization'))

    def test_untrusted_redirect_and_oversized_download_are_rejected(self):
        api=pub.GitHubAPI('private-test-token')
        api.opener.open=lambda req,timeout:self.Response(302,{'Location':'https://evil.example/leak'})
        with self.assertRaises(pub.ValidationError):api._download('/repos/'+pub.REPOSITORY+'/actions/artifacts/1/zip',None,3)
        api.opener.open=lambda req,timeout:self.Response(200,raw=b'too large')
        with self.assertRaises(pub.ValidationError):api._download('/repos/'+pub.REPOSITORY+'/actions/artifacts/1/zip',None,3)


if __name__ == '__main__':
    unittest.main()
