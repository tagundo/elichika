#!/usr/bin/env python3
"""Verify one pinned candidate ZIP and split unchanged bytes; no network/signing."""
import argparse, hashlib, json, pathlib, re, stat, zipfile
CHUNK = 1024 * 1024
MAX_METADATA = 8 * CHUNK


def require(ok, message):
    if not ok: raise ValueError(message)


def split(source, output, recipe, provenance):
    pin = recipe['source_artifact']; expected = {r['name']: r for r in recipe['candidates']}
    require(len(expected) == 5 and len(recipe['candidates']) == 5, 'Expected exactly five distinct candidates')
    require(all(re.fullmatch(r'[A-Za-z0-9_.-]+', n) for n in expected) and all(re.fullmatch(r'[a-z0-9-]+', r['directory']) for r in expected.values()) and len({r['directory'] for r in expected.values()}) == 5, 'Unsafe/conflicting output names')
    require(provenance == {'repository':recipe['repository'], 'run_id':recipe['source_run_id'], 'source_commit':recipe['source_commit'], 'run_status':'completed', 'run_conclusion':'success', 'artifact':pin}, 'Successful source run/artifact provenance differs')
    require(source.is_file() and not source.is_symlink() and source.stat().st_size == pin['bytes'], 'Pinned artifact length/type mismatch')
    with source.open('rb') as stream: require(hashlib.file_digest(stream, 'sha256').hexdigest() == pin['sha256'], 'Pinned artifact SHA256 mismatch')
    require(not output.exists() and output.parent.is_dir() and not output.parent.is_symlink(), 'Fresh output directory required')
    metadata_names = {'SHA256SUMS', 'build-receipt.json'} | {n+'.proof.json' for n in expected}
    with zipfile.ZipFile(source) as archive:
        rows = archive.infolist(); names = [r.filename for r in rows]
        require(len(rows) == 12 and len(set(names)) == 12 and set(names) == set(expected) | metadata_names, 'Unexpected/duplicate/path-containing artifact entries')
        require(sum(r.file_size for r in rows) <= 1024 * CHUNK and all(not r.flag_bits & 1 and not stat.S_ISLNK(r.external_attr >> 16) and not r.is_dir() for r in rows), 'Oversized/encrypted/link/directory artifact entry')
        metadata_bytes = sum(archive.getinfo(n).file_size for n in metadata_names)
        print(json.dumps({'input_metadata_bytes':metadata_bytes,'metadata_budget_bytes':MAX_METADATA}), flush=True)
        require(metadata_bytes <= MAX_METADATA-16384, f'Metadata input {metadata_bytes} bytes exceeds allowed {MAX_METADATA-16384} bytes (total budget {MAX_METADATA})')
        metadata = {n:archive.read(n) for n in metadata_names}
        sums = {}
        for line in metadata['SHA256SUMS'].decode('ascii').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
            require(match is not None and match[2] not in sums, 'Malformed/duplicate SHA256SUMS')
            sums[match[2]] = match[1]
        require(set(sums) == set(expected), 'SHA256SUMS candidate set differs')
        receipt = json.loads(metadata['build-receipt.json']); outputs = {r['name']:r for r in receipt['outputs']}
        require(len(receipt['outputs']) == 5 and set(outputs) == set(expected) and receipt['status'] == 'CANDIDATES_BUILT_NO_UPLOAD_OR_RELEASE' and receipt['build'] == recipe['build'] and receipt['source_lock_sha256'] == recipe['source_lock_sha256'], 'Build receipt/source lock differs')
        for name, row in expected.items():
            proof = json.loads(metadata[name+'.proof.json']); item = outputs[name]
            require(proof['output'] == item and item['name'] == name and type(item['bytes']) is int and 0 < item['bytes'] <= 100 * CHUNK and archive.getinfo(name).file_size == item['bytes'] and item['sha256'] == sums[name], 'Candidate proof/receipt/hash/length conflict: '+name)
            require(proof['build'] == recipe['build'] and proof['platform'] == row['platform'] and proof.get('region' if row['platform']=='android' else 'variant') == row['variant'] and proof.get('native_binaries_byte_identical' if row['platform']=='android' else 'V5_executable_byte_identical') is True and isinstance(proof.get('members'), list), 'Candidate identity/native preservation proof differs: '+name)
        output.mkdir(mode=0o700); records = []
        for name, row in expected.items():
            directory = output/row['directory']; directory.mkdir(); destination = directory/name; digest = hashlib.sha256(); count = 0
            with archive.open(name) as incoming, destination.open('xb') as outgoing:
                while block := incoming.read(CHUNK):
                    count += len(block); require(count <= outputs[name]['bytes'], 'Candidate byte bound exceeded'); digest.update(block); outgoing.write(block)
            require(count == outputs[name]['bytes'] and digest.hexdigest() == sums[name], 'Candidate SHA256 mismatch: '+name)
            records.append({**row, 'bytes':count, 'sha256':digest.hexdigest()})
    metadata['source-provenance.json'] = (json.dumps(provenance,sort_keys=True,indent=2)+'\n').encode()
    metadata['export-manifest.json'] = (json.dumps({'schema':1,'build':recipe['build'],'status':'UNCHANGED_CANDIDATES_VERIFIED_NOT_SIGNED_OR_RELEASED','source_artifact':pin,'candidates':records},sort_keys=True,indent=2)+'\n').encode()
    metadata_bytes = sum(map(len, metadata.values()))
    require(metadata_bytes <= MAX_METADATA, f'Final metadata {metadata_bytes} bytes exceeds budget {MAX_METADATA} bytes')
    directory = output/'metadata'; directory.mkdir()
    for name, content in metadata.items(): (directory/name).write_bytes(content)
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=pathlib.Path);p.add_argument('output',type=pathlib.Path);p.add_argument('--recipe',type=pathlib.Path,default=pathlib.Path(__file__).with_name('export-recipe.json'));p.add_argument('--provenance',type=pathlib.Path,required=True);a=p.parse_args()
    records=split(a.source,a.output,json.loads(a.recipe.read_bytes()),json.loads(a.provenance.read_bytes()))
    print(json.dumps({'verified_candidates':len(records),'metadata_bytes':sum(p.stat().st_size for p in (a.output/'metadata').iterdir()),'metadata_limit_bytes':MAX_METADATA,'rebuilt_or_signed':False}))

if __name__=='__main__': main()
