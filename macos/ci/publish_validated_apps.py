"""Publish exact, already-validated APK/Mac artifacts; never rebuild an app.

Called only by the manifest mode of the existing macos.yml workflow. The job's
GITHUB_TOKEN creates the tag, so publishing does not start a recursive tag build.
No release mutation is allowed until every source/run/artifact/file check passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'tagundo/elichika'
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_FILE = 1024 * 1024 * 1024
CHUNK = 1024 * 1024
WORKFLOWS = {
    'android': ('android.yml', 'Build Android APK', {
        'build', 'native-compatibility / native-16k',
        'apk-audit / audit', 'android-upgrade / android'}),
    'macos': ('macos.yml', 'Build standalone macOS Apple Silicon app', {'apple-silicon'}),
    'general': ('tests.yml', 'Server regression tests', {'tests', 'windows-upgrades', 'viewer-webgl'}),
}
ARTIFACT_NAMES = {
    'android': 'elichika-release-apk',
    'macos': 'elichika-macos-apple-silicon',
    'general': 'viewer-webgl-evidence',
}


class ValidationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def positive_int(value, label):
    require(type(value) is int and 0 < value < 10**16, f'{label} must be a positive integer')
    return value


def digest_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), f'{label} must be a lowercase SHA256')
    return value


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_manifest(value, repository, source_sha, version_text):
    require(repository == REPOSITORY, 'Only the configured repository may publish')
    require(isinstance(value, dict), 'The release manifest must be an object')
    require(set(value) == {'schema_version', 'version', 'source_sha', 'android', 'macos', 'general', 'notes'}, 'Unexpected or missing manifest fields')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'Unsupported manifest schema')
    version = value['version']
    require(isinstance(version, str) and re.fullmatch(r'20[0-9]{2}\.[0-9]{2}\.[0-9]{2}(?:\.[1-9][0-9]*)?', version), 'Invalid release version')
    parts = version.split('.')
    try:
        dt.date(*map(int, parts[:3]))
    except ValueError as exc:
        raise ValidationError('Invalid release date') from exc
    require(version_text.strip() == version, 'Manifest version differs from checked-out macos/VERSION')
    require(isinstance(source_sha, str) and re.fullmatch(r'[0-9a-f]{40}', source_sha), 'Invalid checked-out source SHA')
    require(value['source_sha'] == source_sha, 'Manifest source differs from this workflow commit')
    require(isinstance(value['notes'], str) and len(value['notes']) <= 20000, 'Invalid release notes')
    for kind in WORKFLOWS:
        entry = value[kind]
        fields = {'run_id', 'artifact_id', 'zip_sha256'}
        if kind != 'general':
            fields |= {'file_sha256'}
        require(isinstance(entry, dict) and set(entry) == fields, f'Invalid {kind} manifest fields')
        positive_int(entry['run_id'], kind + ' run')
        positive_int(entry['artifact_id'], kind + ' artifact')
        digest_value(entry['zip_sha256'], kind + ' artifact digest')
        if kind != 'general':
            digest_value(entry['file_sha256'], kind + ' file digest')
    require(len({value[k]['run_id'] for k in WORKFLOWS}) == 3, 'Each platform must have its own workflow run')
    require(len({value[k]['artifact_id'] for k in WORKFLOWS}) == 3, 'Artifact IDs must be distinct')
    return value


def safe_outer_member(info):
    name = info.filename
    require(getattr(info, 'orig_filename', name) == name, 'Truncated artifact member name')
    require(name and '\\' not in name and '\0' not in name, 'Unsafe artifact member name')
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and ':' not in name, 'Unsafe artifact member path')
    mode = (info.external_attr >> 16) & 0o170000
    require(mode in ((0, stat.S_IFDIR) if info.is_dir() else (0, stat.S_IFREG)), 'Artifact contains a link or non-regular member')
    require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unexpected artifact compression method')
    require(not (info.flag_bits & 1), 'Encrypted artifacts are not supported')
    require(0 <= info.file_size <= MAX_FILE, 'Artifact member is too large')


def extract_single_file(archive, expected_name, destination, expected_sha, allow_checksum=False):
    require(Path(archive).stat().st_size <= MAX_ARCHIVE, 'Artifact archive is too large')
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        require(len(entries) <= 8, 'Unexpected artifact member count')
        for entry in entries:
            safe_outer_member(entry)
        files = [entry for entry in entries if not entry.is_dir()]
        expected_names = {expected_name, 'SHA256SUMS'} if allow_checksum else {expected_name}
        require(len(files) == len(expected_names) and {f.filename for f in files} == expected_names, 'Artifact must contain exactly the expected installable and approved checksum files')
        if allow_checksum:
            checksum = z.getinfo('SHA256SUMS')
            require(checksum.file_size <= 1024 and z.read(checksum) == (expected_sha + '  ' + expected_name + '\n').encode(), 'Embedded Mac checksum differs from the approved file')
        info = z.getinfo(expected_name)
        require(info.file_size > 0, 'Installable file is empty')
        h = hashlib.sha256()
        size = 0
        with z.open(info) as src, Path(destination).open('xb') as out:
            for chunk in iter(lambda: src.read(CHUNK), b''):
                size += len(chunk)
                require(size <= MAX_FILE and size <= info.file_size, 'Expanded artifact exceeds its declared size')
                h.update(chunk)
                out.write(chunk)
        require(size == info.file_size, 'Installable file size differs from the ZIP directory')
        require(h.hexdigest() == expected_sha, 'Installable file hash differs from the approved manifest')
    return {'name': expected_name, 'path': str(destination), 'bytes': size, 'sha256': h.hexdigest()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    def __init__(self, token):
        require(bool(token), 'GITHUB_TOKEN is required')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def _open(self, url, *, method='GET', data=None, headers=None, authenticated=False):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password, 'Unsafe API/download URL')
        all_headers = {'User-Agent': 'Elichika-validated-app-publisher', 'Accept-Encoding': 'identity'}
        all_headers.update(headers or {})
        if authenticated:
            require(parsed.hostname in {'api.github.com', 'uploads.github.com'}, 'Credentials may only be sent to GitHub API hosts')
            all_headers['Authorization'] = 'Bearer ' + self.token
            all_headers['X-GitHub-Api-Version'] = '2022-11-28'
        req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
        try:
            return self.opener.open(req, timeout=180)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                return exc
            raise

    def json(self, method, path, payload=None, allow_missing=False):
        require(path.startswith('/repos/' + REPOSITORY + '/'), 'API path is outside the configured repository')
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        try:
            response = self._open('https://api.github.com' + path, method=method, data=data,
                                  headers={'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}, authenticated=True)
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            raise ValidationError(f'GitHub API request failed with HTTP{exc.code}') from None
        except urllib.error.URLError:
            raise ValidationError('GitHub API connection failed') from None
        with response:
            require(response.status < 300, 'Unexpected API redirect')
            raw = response.read(16 * 1024 * 1024 + 1)
            require(len(raw) <= 16 * 1024 * 1024, 'GitHub metadata response is too large')
            return json.loads(raw) if raw else None

    def _download(self, path, destination, limit):
        require(path.startswith('/repos/' + REPOSITORY + '/'), 'Download path is outside the configured repository')
        url = 'https://api.github.com' + path
        authenticated = True
        h, count = hashlib.sha256(), 0
        out = Path(destination).open('xb') if destination else None
        try:
            for attempt in range(6):
                try:
                    response = self._open(url, headers={'Accept': 'application/octet-stream'}, authenticated=authenticated)
                except urllib.error.HTTPError as exc:
                    raise ValidationError(f'GitHub binary download failed with HTTP{exc.code}') from None
                except urllib.error.URLError:
                    raise ValidationError('GitHub binary download connection failed') from None
                with response:
                    if response.status in (301, 302, 303, 307, 308):
                        target = urllib.parse.urljoin(url, response.headers.get('Location', ''))
                        parsed = urllib.parse.urlsplit(target)
                        host = parsed.hostname or ''
                        allowed = host.endswith('.blob.core.windows.net') or host.endswith('.actions.githubusercontent.com') or host in {'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}
                        require(parsed.scheme == 'https' and allowed and not parsed.username and not parsed.password, 'Unsafe binary redirect host')
                        # Do not forward GitHub credentials to signed artifact/blob URLs.
                        url, authenticated = target, False
                        continue
                    require(response.status == 200, 'Unexpected binary download status')
                    for chunk in iter(lambda: response.read(CHUNK), b''):
                        count += len(chunk)
                        require(count <= limit, 'Binary download exceeds its approved size')
                        h.update(chunk)
                        if out:
                            out.write(chunk)
                    return count, h.hexdigest()
            raise ValidationError('Too many binary redirects')
        finally:
            if out:
                out.close()

    def download_artifact(self, artifact_id, destination, size):
        return self._download(f'/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip', destination, size)

    def hash_release_asset(self, asset_id, size):
        return self._download(f'/repos/{REPOSITORY}/releases/assets/{asset_id}', None, size)

    def upload(self, release_id, file):
        url = f'https://uploads.github.com/repos/{REPOSITORY}/releases/{release_id}/assets?name=' + urllib.parse.quote(file['name'], safe='')
        with Path(file['path']).open('rb') as stream:
            try:
                response = self._open(url, method='POST', data=stream,
                                      headers={'Content-Type': 'application/octet-stream', 'Content-Length': str(file['bytes'])}, authenticated=True)
            except urllib.error.HTTPError as exc:
                raise ValidationError(f'GitHub asset upload failed with HTTP{exc.code}') from None
            except urllib.error.URLError:
                raise ValidationError('GitHub asset upload connection failed') from None
            with response:
                require(response.status == 201, 'Unexpected asset upload status')
                return json.loads(response.read())


class Publisher:
    def __init__(self, api, manifest, repository, source_sha, version_text, work_dir):
        self.api = api
        self.manifest = parse_manifest(manifest, repository, source_sha, version_text)
        self.source_sha = source_sha
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.tag = 'v' + manifest['version']
        self.marker = '<!-- elichika-validated-apps:' + hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest() + ' -->'
        self.release_id = None
        self.result = {'status': 'VALIDATION_PENDING', 'version': manifest['version'], 'source_sha': source_sha,
                       'run_ids': {kind: manifest[kind]['run_id'] for kind in WORKFLOWS}, 'mutation_started': False}

    def _api(self, method, suffix, payload=None, missing=False):
        return self.api.json(method, '/repos/' + REPOSITORY + suffix, payload, allow_missing=missing)

    def tag_commit(self):
        ref = self._api('GET', '/git/ref/tags/' + self.tag, missing=True)
        if ref is None:
            return None
        obj, seen = ref.get('object', {}), set()
        for _ in range(8):
            kind, sha = obj.get('type'), obj.get('sha')
            require(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha), 'Invalid tag object')
            if kind == 'commit':
                return sha
            require(kind == 'tag' and sha not in seen, 'Invalid or recursive release tag')
            seen.add(sha)
            obj = self._api('GET', '/git/tags/' + sha).get('object', {})
        raise ValidationError('Release tag nesting is too deep')

    def check_runs(self):
        repo = self.api.json('GET', '/repos/' + REPOSITORY + '/actions/workflows/android.yml')
        require(repo.get('path') == '.github/workflows/android.yml', 'Unexpected Android workflow identity')
        for kind, (filename, name, required_jobs) in WORKFLOWS.items():
            meta = repo if kind == 'android' else self._api('GET', '/actions/workflows/' + filename)
            require(meta.get('path') == '.github/workflows/' + filename and meta.get('name') == name and meta.get('state') == 'active', f'Unexpected {kind} workflow identity')
            entry = self.manifest[kind]
            run = self._api('GET', '/actions/runs/' + str(entry['run_id']))
            require(run.get('workflow_id') == meta.get('id') and run.get('name') == name, f'Wrong {kind} workflow run')
            require(run.get('event') == 'workflow_dispatch', f'{kind} must be a reviewed dispatch run')
            require(run.get('repository', {}).get('full_name') == REPOSITORY and run.get('head_repository', {}).get('full_name') == REPOSITORY, f'Unexpected {kind} run repository')
            require(run.get('head_sha') == self.source_sha, f'{kind} source mismatch')
            require(run.get('status') == 'completed' and run.get('conclusion') == 'success', f'{kind} run is not successful')
            jobs, page = [], 1
            while True:
                value = self._api('GET', f"/actions/runs/{entry['run_id']}/jobs?filter=latest&per_page=100&page={page}")
                jobs.extend(value.get('jobs', []))
                if len(jobs) >= value.get('total_count', 0):
                    break
                page += 1
                require(page <= 10, 'Too many workflow jobs')
            for job_name in required_jobs:
                matches = [j for j in jobs if j.get('name') == job_name]
                require(len(matches) == 1 and matches[0].get('status') == 'completed' and matches[0].get('conclusion') == 'success', f'{kind} required job did not pass: {job_name}')
            require(all(j.get('status') == 'completed' and j.get('conclusion') in {'success', 'skipped'} for j in jobs), f'{kind} has an incomplete or failed job')

    def check_artifacts(self):
        files = {}
        for kind in WORKFLOWS:
            entry = self.manifest[kind]
            artifact = self._api('GET', '/actions/artifacts/' + str(entry['artifact_id']))
            require(artifact.get('id') == entry['artifact_id'] and artifact.get('name') == ARTIFACT_NAMES[kind], f'Unexpected {kind} artifact identity')
            run = artifact.get('workflow_run', {})
            require(run.get('id') == entry['run_id'] and run.get('head_sha') == self.source_sha, f'{kind} artifact source mismatch')
            require(artifact.get('expired') is False and artifact.get('digest') == 'sha256:' + entry['zip_sha256'], f'{kind} artifact expired or digest mismatch')
            size = artifact.get('size_in_bytes')
            require(type(size) is int and 0 < size <= MAX_ARCHIVE, f'Invalid {kind} artifact size')
            archive = self.work_dir / (kind + '-artifact.zip')
            actual_size, digest = self.api.download_artifact(entry['artifact_id'], archive, size)
            require(actual_size == size and digest == entry['zip_sha256'] and file_digest(archive) == digest, f'{kind} artifact bytes differ from approved digest')
            if kind != 'general':
                name = ('elichika-' + self.manifest['version'] + '.apk') if kind == 'android' else ('Elichika-' + self.manifest['version'] + '-AppleSilicon.app.zip')
                files[kind] = extract_single_file(archive, name, self.work_dir / name, entry['file_sha256'], allow_checksum=kind == 'macos')
        sums = ''.join(files[k]['sha256'] + '  ' + files[k]['name'] + '\n' for k in ['android', 'macos']).encode()
        path = self.work_dir / 'SHA256SUMS'
        with path.open('xb') as f:
            f.write(sums)
        files['checksums'] = {'name': 'SHA256SUMS', 'path': str(path), 'bytes': len(sums), 'sha256': hashlib.sha256(sums).hexdigest()}
        return files

    def check_release(self):
        tag = self.tag_commit()
        require(tag is None or tag == self.source_sha, 'Existing release tag points to another commit')
        release = self._api('GET', '/releases/tags/' + self.tag, missing=True)
        if release:
            require(release.get('tag_name') == self.tag and not release.get('prerelease') and self.marker in release.get('body', ''), 'Existing release belongs to another publication manifest')
            require(tag == self.source_sha, 'Existing release tag is missing or mismatched')
        return release

    def verify_uploaded(self, release, expected):
        assets = release.get('assets', [])
        require(len(assets) == len(expected) and {a.get('name') for a in assets} == set(expected), 'Release assets are missing, duplicated, or unexpected')
        verified = []
        for asset in assets:
            file = expected[asset['name']]
            require(asset.get('state') == 'uploaded' and asset.get('size') == file['bytes'], 'Uploaded asset is incomplete or has a wrong size')
            if asset.get('digest'):
                require(asset['digest'] == 'sha256:' + file['sha256'], 'Uploaded asset metadata hash differs')
            count, digest = self.api.hash_release_asset(positive_int(asset.get('id'), 'release asset'), file['bytes'])
            require(count == file['bytes'] and digest == file['sha256'], 'Downloaded release asset hash differs from validated bytes')
            verified.append({'id': asset['id'], 'name': file['name'], 'bytes': count, 'sha256': digest,
                             'browser_download_url': asset.get('browser_download_url')})
        return verified

    def run(self):
        try:
            self.check_runs()
            existing = self.check_release()
            files = self.check_artifacts()
            expected = {file['name']: file for file in files.values()}
            if existing and not existing.get('draft'):
                verified = self.verify_uploaded(existing, expected)
                self.result.update(status='PASS_ALREADY_PUBLISHED_IDENTICAL_BYTES', release_id=existing['id'], release_url=existing['html_url'], assets=verified)
                return self.result
            # Establish the exact lightweight tag with this job's GITHUB_TOKEN.
            # Draft-release APIs may defer creating a missing tag until publish.
            tag = self.tag_commit()
            require(tag is None or tag == self.source_sha, 'Release tag changed before draft creation')
            if tag is None:
                self.result['mutation_started'] = True
                self._api('POST', '/git/refs', {'ref': 'refs/tags/' + self.tag, 'sha': self.source_sha})
                self.result['created_tag'] = self.tag
            require(self.tag_commit() == self.source_sha, 'Release tag was not created on the validated source')
            body = self.manifest['notes'].rstrip() + '\n\n' + 'Source: `' + self.source_sha + '`\n\n' + self.marker
            if existing:
                release = existing
            else:
                self.result['mutation_started'] = True
                release = self._api('POST', '/releases', {'tag_name': self.tag, 'target_commitish': self.source_sha,
                                    'name': 'Elichika ' + self.manifest['version'], 'body': body,
                                    'draft': True, 'prerelease': False})
            self.release_id = positive_int(release.get('id'), 'release')
            self.result['release_id'] = self.release_id
            self.result['release_url'] = release.get('html_url')
            require(release.get('draft') is True and self.marker in release.get('body', ''), 'Expected an owned draft release')
            require(self.tag_commit() == self.source_sha, 'Release tag changed before upload')
            # Resume only exact, owned draft assets. Never overwrite or delete one.
            for asset in release.get('assets', []):
                require(asset.get('name') in expected, 'Existing draft has an unexpected asset')
            require(len({a['name'] for a in release.get('assets', [])}) == len(release.get('assets', [])), 'Duplicate draft asset names')
            for file in expected.values():
                present = [a for a in release.get('assets', []) if a.get('name') == file['name']]
                if present:
                    self.verify_uploaded({'assets': present}, {file['name']: file})
                else:
                    self.result['mutation_started'] = True
                    self.api.upload(self.release_id, file)
            current = self._api('GET', '/releases/' + str(self.release_id))
            require(current.get('draft') is True and self.marker in current.get('body', ''), 'Draft ownership changed during upload')
            verified = self.verify_uploaded(current, expected)
            require(self.tag_commit() == self.source_sha, 'Release tag changed before publication')
            self.result['mutation_started'] = True
            published = self._api('PATCH', '/releases/' + str(self.release_id), {'draft': False, 'prerelease': False, 'make_latest': 'true'})
            require(published.get('draft') is False and published.get('tag_name') == self.tag, 'Publication did not complete')
            self.result.update(status='PASS_PUBLISHED_VALIDATED_APPS', release_id=self.release_id, release_url=published['html_url'], assets=verified)
            return self.result
        except Exception:
            self.result.update(status='FAILED_NOT_APPROVED_FOR_PUBLICATION', owned_draft_release_id=self.release_id)
            raise
        finally:
            output = self.work_dir / 'publish-result.json'
            with output.open('w') as f:
                json.dump(self.result, f, indent=2)
                f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-env', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--version-file', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = os.environ.get(args.manifest_env, '')
        require(0 < len(raw.encode()) <= 60000, 'Invalid release manifest length')
        manifest = json.loads(raw)
        publisher = Publisher(GitHubAPI(os.environ.get('GITHUB_TOKEN', '')), manifest, args.repository,
                              args.source_sha, args.version_file.read_text(), args.work_dir)
        result = publisher.run()
        print(json.dumps(result, indent=2))
        return 0
    except (ValidationError, ValueError, OSError, zipfile.BadZipFile) as exc:
        print('Validated publication failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
