#!/usr/bin/env python3
"""Download only pinned QA fixtures; strip credentials at every cross-host redirect."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, target):
        parsed = urllib.parse.urlsplit(target)
        assert parsed.scheme == 'https' and not parsed.username and not parsed.password
        assert parsed.hostname in ('api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com') or parsed.hostname.endswith('.blob.core.windows.net')
        redirected = super().redirect_request(request, fp, code, message, headers, target)
        if parsed.hostname != 'api.github.com':
            for mapping in (redirected.headers, redirected.unredirected_hdrs):
                for name in list(mapping):
                    if name.lower() in ('authorization', 'cookie', 'proxy-authorization'):
                        del mapping[name]
        return redirected

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--region', choices=['GL', 'JP'], required=True)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--skip-server-apk', action='store_true', help='Source-built Go mode: download only client and readonly observer')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    assert manifest['schema_version'] == 1
    token = os.environ.get('GITHUB_TOKEN')
    assert token, 'GitHub Actions repository token missing'
    opener = urllib.request.build_opener(SafeRedirect())
    args.destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    args.evidence.mkdir(parents=True, exist_ok=True)
    receipts = {}
    selected = [('client', manifest['clients'][args.region])]
    if not args.skip_server_apk:
        selected.append(('server', manifest['server']))
    selected.append(('frida', manifest['frida']))
    for kind, fixture in selected:
        destination = args.destination / ('frida-server.xz' if kind == 'frida' else kind+'.apk')
        request = urllib.request.Request(f"https://api.github.com/repos/{fixture['repository']}/releases/assets/{fixture['asset_id']}?download_nonce={time.time_ns()}",
            headers={'Authorization':'Bearer '+token, 'Accept':'application/octet-stream', 'User-Agent':'SIFAS-private-client-QA', 'X-GitHub-Api-Version':'2022-11-28'})
        maximum = fixture.get('bytes', fixture.get('bytes_limit'))
        count = 0
        digest = hashlib.sha256()
        try:
            with opener.open(request, timeout=120) as response, destination.open('xb') as output:
                assert response.status == 200
                while True:
                    part = response.read(min(1048576, maximum-count+1))
                    if not part: break
                    count += len(part)
                    assert count <= maximum, 'Fixture exceeds its declared bound'
                    digest.update(part)
                    output.write(part)
            assert count == fixture.get('bytes', count)
            assert digest.hexdigest() == fixture['sha256'], 'Fixture SHA256 differs from frozen manifest'
        except Exception as error:
            raise SystemExit(f"{kind} fixture failed: {type(error).__name__}; HTTP {getattr(error,'code',None)}") from None
        receipts[kind] = {'repository':fixture['repository'], 'asset_id':fixture['asset_id'], 'bytes':count, 'sha256':digest.hexdigest()}
        print(f"Verified pinned {kind} fixture: {count} bytes")
    (args.evidence/'fixture-downloads.json').write_text(json.dumps(receipts,indent=2)+'\n')

if __name__ == '__main__': main()
