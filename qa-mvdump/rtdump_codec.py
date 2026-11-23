"""Shared helpers for the `sifas-mv-runtime-dump/1` documents (game producer side).

Stdlib only, Python 3.11+. Used by mvdump_sampler.py on the CI host and by the offline
tests; the editor comparator (modtools tests/mv_runtime_compare.py) reads the same format.

- validate(doc) / check(doc): structural check of the schema (envelope, header, records,
  trailer, matrix layout sanity: a perspective projection has e[11] == -1 and e[15] == 0).
- encode_doc / decode_blob: deterministic gzip JSON (mtime 0) so a decoded blob re-encodes
  to the identical bytes.
- split_for_log(doc, cap): the two job-log documents, rtdump-core (header, frame records,
  trailer; never dropped) and rtdump-full (header, full records, trailer), dropping full
  parts in the fixed order particles -> springs -> stageNodes -> census -> materials.
- emit_blob(name, data, printer): @@RTDUMP-INDEX / @@RTDUMP-BEGIN / @@<2000 chars> /
  @@RTDUMP-END lines, the same shape as the module's @@SHOT lines.
- fit_probe(probe, cap): the probe document (class / field / method inventory, the third
  job-log blob rtdump-probe) reduced until its base64 fits `cap`, or None. The probe is not a
  dump subset: load() and merge() never mix it into the dump; extract writes it separately.
- extract_from_log(path_or_text): strips the GitHub `YYYY-MM-DDTHH:MM:SS.fffffffZ ` prefix,
  joins each blob and verifies the INDEX byte count and sha256.
- merge(docs): joins documents with identical headers by record id.
- decode_fmov_word(word): FovMod.imm8ToFloat((word >> 13) & 255) (VFPExpandImm).

CLI:
  python3 rtdump_codec.py extract JOB.log OUTDIR
  python3 rtdump_codec.py verify DUMP.json[.gz]|JOB.log
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

SCHEMA = 'sifas-mv-runtime-dump/1'
SIDES = ('game', 'editor')
CONVENTIONS = {
    'game': {'space': 'unity-lh', 'matrixLayout': 'column-major', 'angles': 'degrees', 'quaternion': 'xyzw',
             'color': 'raw', 'time': 'director-seconds'},
    'editor': {'space': 'three-rh-mirror-x', 'matrixLayout': 'column-major', 'angles': 'degrees', 'quaternion': 'xyzw',
               'color': 'raw', 'time': 'director-seconds'},
}
KINDS = ('frame', 'full')
PARTS = ('census', 'quality', 'fovmodNative', 'renderers', 'materials', 'lightingRefs', 'members', 'springs',
         'stageNodes', 'particles', 'post', 'propertyBlocks')
# Schema section 7: parts dropped from rtdump-full, in this order, when the log cap is hit.
DROP_ORDER = ('particles', 'springs', 'stageNodes', 'census', 'materials')
STOP_REASONS = ('mv-ended', 'scene-changed', 'director-missing', 'wall-cap', 'observer-errors', 'observer-lost',
                'game-lost', 'error')
LINE_CHARS = 2000
CORE, FULL = 'rtdump-core', 'rtdump-full'
# Third blob: the probe document (mvruntimeprobe chunks: classes, fields with types and
# offsets, resolved candidates, method availability, layout self-check). Not a dump subset.
PROBE = 'rtdump-probe'
PROBE_LEVELS = ('full', 'fields-trimmed', 'fields-dropped', 'summary')
TIMESTAMP = re.compile(r'^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ')
CHUNK = re.compile(r'^@@([A-Za-z0-9+/=]+)$')


class DumpError(ValueError):
    """A document, blob or log that does not follow sifas-mv-runtime-dump/1."""


# ---------------------------------------------------------------- validation
def _number_or_none(value):
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))


def _check_matrix(problems, where, matrix, perspective):
    if matrix is None:
        return
    if not isinstance(matrix, list) or len(matrix) != 16 or not all(_number_or_none(v) for v in matrix):
        problems.append(f'{where}: matrix must be 16 numbers (column-major)')
        return
    if perspective and matrix[11] is not None and matrix[15] is not None:
        if abs(matrix[11] + 1) > 1e-4 or abs(matrix[15]) > 1e-6:
            problems.append(f'{where}: perspective projection must have e[11] == -1 and e[15] == 0 '
                            f'(got {matrix[11]}, {matrix[15]}); matrices are column-major')


def validate(doc):
    """Problems (list of strings) of a dump document; [] means valid."""
    problems = []
    if not isinstance(doc, dict):
        return ['document is not a JSON object']
    for key in ('schema', 'side', 'header', 'records', 'trailer'):
        if key not in doc:
            problems.append(f'missing envelope key {key!r}')
    if problems:
        return problems
    if doc['schema'] != SCHEMA:
        problems.append(f'unknown schema {doc["schema"]!r} (expected {SCHEMA})')
        return problems
    if doc['side'] not in SIDES:
        problems.append(f'side must be one of {SIDES}, got {doc["side"]!r}')
        return problems
    header, records, trailer = doc['header'], doc['records'], doc['trailer']
    if not isinstance(header, dict):
        problems.append('header is not an object')
    else:
        conventions = header.get('conventions')
        if conventions != CONVENTIONS[doc['side']]:
            problems.append(f'header.conventions must be {CONVENTIONS[doc["side"]]} for side {doc["side"]}')
        if not isinstance(header.get('createdAt'), str):
            problems.append('header.createdAt must be an ISO string')
        if not isinstance(header.get('producer'), dict):
            problems.append('header.producer must be an object')
    if not isinstance(trailer, dict):
        problems.append('trailer is not an object')
    if not isinstance(records, list):
        problems.append('records is not a list')
        return problems
    seen = set()
    for index, record in enumerate(records):
        where = f'records[{index}]'
        if not isinstance(record, dict):
            problems.append(f'{where}: not an object')
            continue
        rid = record.get('id')
        if not isinstance(rid, str) or not rid:
            problems.append(f'{where}: id must be a non-empty string')
        elif rid in seen:
            problems.append(f'{where}: duplicate id {rid!r}')
        seen.add(rid)
        kind = record.get('kind')
        if kind not in KINDS:
            problems.append(f'{where}: kind must be frame or full, got {kind!r}')
            continue
        clock = record.get('clock')
        if not isinstance(clock, dict) or 'directorTime' not in clock or not _number_or_none(clock.get('directorTime')):
            problems.append(f'{where}: clock.directorTime must be present (number or null)')
        if doc['side'] == 'editor' and not isinstance(record.get('sourceRecord'), str):
            problems.append(f'{where}: editor records need sourceRecord')
        if kind == 'full':
            if record.get('part') not in PARTS:
                problems.append(f'{where}: unknown part {record.get("part")!r}')
            for key in ('pass', 'chunk'):
                if not isinstance(record.get(key), int) or isinstance(record.get(key), bool):
                    problems.append(f'{where}: {key} must be an integer')
        cameras = record.get('cameras')
        if isinstance(cameras, list):
            for ci, camera in enumerate(cameras):
                if not isinstance(camera, dict):
                    continue
                perspective = camera.get('orthographic') is not True
                _check_matrix(problems, f'{where}.cameras[{ci}].projection', camera.get('projection'), perspective)
                _check_matrix(problems, f'{where}.cameras[{ci}].worldToCamera', camera.get('worldToCamera'), False)
    try:
        json.dumps(doc, allow_nan=False)
    except ValueError as error:
        problems.append(f'non-finite number in document ({error}); use null and record.nonFinite')
    return problems


def check(doc):
    problems = validate(doc)
    if problems:
        raise DumpError('; '.join(problems[:12]) + (f' (+{len(problems) - 12} more)' if len(problems) > 12 else ''))
    return doc


# ---------------------------------------------------------------- encoding
def dumps(doc):
    return json.dumps(doc, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def encode_doc(doc):
    """Deterministic gzip JSON bytes (mtime 0, level 9)."""
    return gzip.compress(dumps(doc), compresslevel=9, mtime=0)


def decode_blob(data):
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    return json.loads(data.decode())


def b64_len(size):
    return 4 * ((size + 2) // 3)


def load(path):
    """A document from .json, .json.gz or a job log (both blobs merged)."""
    path = Path(path)
    data = path.read_bytes()
    if data[:2] == b'\x1f\x8b':
        return decode_blob(data)
    text = data.decode('utf-8', 'replace')
    if '@@RTDUMP-BEGIN ' in text:
        blobs = {name: blob for name, blob in extract_from_log(text).items() if name != PROBE}
        if not blobs:
            raise DumpError(f'{path}: no complete @@RTDUMP dump blob')
        return merge([decode_blob(blob) for blob in blobs.values()])
    return json.loads(text)


def subset(doc, records, truncation=None):
    out = {'schema': doc['schema'], 'side': doc['side'], 'header': doc['header'], 'records': records,
           'trailer': dict(doc['trailer'], truncation=truncation)}
    return out


def split_for_log(doc, cap):
    """(core_doc, full_doc_or_None, truncation) whose base64 total fits `cap` when possible.

    The core document (header, every frame record, trailer) is never reduced. Full parts are
    dropped in DROP_ORDER; if the full document still does not fit it is dropped entirely."""
    frames = [r for r in doc['records'] if r.get('kind') == 'frame']
    fulls = [r for r in doc['records'] if r.get('kind') == 'full']
    dropped = []

    def sizes(truncation, keep):
        core = subset(doc, frames, truncation)
        full = subset(doc, keep, truncation) if keep is not None else None
        total = b64_len(len(encode_doc(core))) + (b64_len(len(encode_doc(full))) if full is not None else 0)
        return core, full, total

    truncation = None
    keep = fulls
    core, full, total = sizes(truncation, keep)
    for part in DROP_ORDER:
        if total <= cap:
            break
        if not any(r.get('part') == part for r in keep):
            continue
        dropped.append(part)
        keep = [r for r in keep if r.get('part') != part]
        truncation = {'dropped': list(dropped), 'reason': f'log cap {cap} base64 bytes'}
        core, full, total = sizes(truncation, keep)
    if total > cap and keep is not None:
        remaining = sorted({r.get('part') for r in keep})
        dropped.extend(p for p in remaining if p not in dropped)
        dropped.append('rtdump-full')
        truncation = {'dropped': list(dropped), 'reason': f'log cap {cap} base64 bytes; full blob omitted'}
        core, full, total = sizes(truncation, None)
    if truncation is None:
        core, full, total = sizes(None, keep)
    return core, full, truncation


# ---------------------------------------------------------------- probe document
def _probe_level(probe, level):
    """A copy of the probe document reduced to PROBE_LEVELS[level]."""
    if level == 0:
        return probe
    out = {k: v for k, v in probe.items() if k != 'chunks'}
    if level >= 3:
        out['chunks'] = []
    else:
        chunks = []
        for chunk in probe.get('chunks') or []:
            chunk = dict(chunk)
            classes = []
            for item in chunk.get('classes') or []:
                item = dict(item)
                fields = item.get('fields')
                if isinstance(fields, list):
                    if level == 1:
                        item['fields'] = [{'name': f.get('name'), 'type': f.get('type'), 'offset': f.get('offset')}
                                          for f in fields[:32] if isinstance(f, dict)]
                        if len(fields) > 32:
                            item['fieldsTotal'] = len(fields)
                    else:
                        item.pop('fields', None)
                        item['fieldsTotal'] = len(fields)
                classes.append(item)
            chunk['classes'] = classes
            chunks.append(chunk)
        out['chunks'] = chunks
    out['reduced'] = PROBE_LEVELS[level]
    return out


def fit_probe(probe, cap):
    """(gzip bytes, document, level name) of the probe reduced until its base64 fits `cap`;
    (None, None, 'omitted') when even the summary does not fit."""
    for level in range(len(PROBE_LEVELS)):
        doc = _probe_level(probe, level)
        data = encode_doc(doc)
        if b64_len(len(data)) <= cap:
            return data, doc, PROBE_LEVELS[level]
    return None, None, 'omitted'


# ---------------------------------------------------------------- job-log transport
def emit_blob(name, data, printer=print, records=None, schema=SCHEMA):
    """Print one blob as @@RTDUMP lines; returns its INDEX entry."""
    text = base64.b64encode(data).decode()
    chunks = [text[i:i + LINE_CHARS] for i in range(0, len(text), LINE_CHARS)]
    index = {'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'chunks': len(chunks),
             'records': records, 'schema': schema, 'b64': len(text)}
    printer('@@RTDUMP-INDEX ' + json.dumps(index, separators=(',', ':')))
    printer('@@RTDUMP-BEGIN ' + name)
    for chunk in chunks:
        printer('@@' + chunk)
    printer('@@RTDUMP-END ' + name)
    return index


def _log_lines(path_or_text):
    if isinstance(path_or_text, (bytes, bytearray)):
        text = path_or_text.decode('utf-8', 'replace')
    elif isinstance(path_or_text, Path) or (isinstance(path_or_text, str) and '\n' not in path_or_text
                                            and len(path_or_text) < 4096 and Path(path_or_text).is_file()):
        text = Path(path_or_text).read_text('utf-8', 'replace')
    else:
        text = path_or_text
    for line in text.splitlines():
        yield TIMESTAMP.sub('', line.rstrip('\r'))


def extract_from_log(path_or_text):
    """{name: bytes} of every complete, verified blob (the last one wins for a repeated name)."""
    indexes, out, current, parts = {}, {}, None, []
    for line in _log_lines(path_or_text):
        if line.startswith('@@RTDUMP-INDEX '):
            try:
                entry = json.loads(line[len('@@RTDUMP-INDEX '):])
                indexes[entry['name']] = entry
            except (ValueError, KeyError, TypeError):
                pass
        elif line.startswith('@@RTDUMP-BEGIN '):
            current, parts = line[len('@@RTDUMP-BEGIN '):].strip(), []
        elif line.startswith('@@RTDUMP-END '):
            name = line[len('@@RTDUMP-END '):].strip()
            if current == name:
                data = base64.b64decode(''.join(parts))
                entry = indexes.get(name)
                if entry is None:
                    raise DumpError(f'blob {name}: no @@RTDUMP-INDEX line before it')
                if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                    raise DumpError(f'blob {name}: {len(data)} bytes / sha mismatch against its INDEX')
                out[name] = data
            current, parts = None, []
        elif current is not None:
            found = CHUNK.match(line)
            if found:
                parts.append(found[1])
    return out


def merge(docs):
    docs = [d for d in docs if d]
    if not docs:
        raise DumpError('nothing to merge')
    base = docs[0]
    for other in docs[1:]:
        if other['schema'] != base['schema'] or other['side'] != base['side'] or other['header'] != base['header']:
            raise DumpError('documents with different schema/side/header cannot be merged')
    records, seen = [], set()
    for doc in docs:
        for record in doc['records']:
            if record.get('id') not in seen:
                seen.add(record.get('id'))
                records.append(record)
    records.sort(key=lambda r: (r.get('seq') if isinstance(r.get('seq'), int) else 1 << 30, str(r.get('id'))))
    trailer = dict(base['trailer'])
    for doc in docs[1:]:
        if (doc['trailer'] or {}).get('truncation'):
            trailer['truncation'] = doc['trailer']['truncation']
    return {'schema': base['schema'], 'side': base['side'], 'header': base['header'], 'records': records,
            'trailer': trailer}


# ---------------------------------------------------------------- FOVMOD words
def imm8_to_float(imm8):
    """FovMod.imm8ToFloat (FovMod.java): the VFPExpandImm single-precision value of imm8."""
    imm8 &= 255
    b6 = (imm8 >> 6) & 1
    high = 31 if b6 == 1 else 0
    bits = ((imm8 & 15) << 19) | (((imm8 >> 7) & 1) << 31) | ((((high << 2) | ((1 - b6) << 7)) | ((imm8 >> 4) & 3)) << 23)
    return struct.unpack('<f', struct.pack('<I', bits & 0xFFFFFFFF))[0]


def decode_fmov_word(word):
    """The float an FMOV Sd,#imm word loads (FovMod.getMinWord/getMaxWord prefs), or None."""
    if word is None:
        return None
    try:
        word = int(word, 16) if isinstance(word, str) else int(word)
    except (TypeError, ValueError):
        return None
    return imm8_to_float((word >> 13) & 255)


# ---------------------------------------------------------------- CLI
def _main(argv):
    if len(argv) >= 3 and argv[0] == 'extract':
        out = Path(argv[2])
        out.mkdir(parents=True, exist_ok=True)
        blobs = extract_from_log(Path(argv[1]))
        for name, data in blobs.items():
            (out / f'{name}.json.gz').write_bytes(data)
            doc = decode_blob(data)
            if name == PROBE:
                chunks = doc.get('chunks') or []
                print(json.dumps({'name': name, 'bytes': len(data), 'classesFound': len(doc.get('classesFound') or []),
                                  'classesMissing': len(doc.get('classesMissing') or []), 'chunks': len(chunks),
                                  'reduced': doc.get('reduced')}))
                continue
            print(json.dumps({'name': name, 'bytes': len(data), 'records': len(doc['records']),
                              'problems': validate(doc)[:5]}))
        blobs = {name: data for name, data in blobs.items() if name != PROBE}
        if blobs:
            merged = merge([decode_blob(b) for b in blobs.values()])
            (out / 'mv-runtime-dump.json.gz').write_bytes(encode_doc(merged))
            print(json.dumps({'merged': str(out / 'mv-runtime-dump.json.gz'), 'records': len(merged['records'])}))
        return 0 if blobs else 1
    if len(argv) >= 2 and argv[0] in ('verify', 'validate'):
        doc = load(argv[1])
        problems = validate(doc)
        kinds = {}
        for record in doc.get('records') or []:
            key = record.get('part') or record.get('kind')
            kinds[key] = kinds.get(key, 0) + 1
        print(json.dumps({'file': argv[1], 'schema': doc.get('schema'), 'side': doc.get('side'),
                          'records': len(doc.get('records') or []), 'kinds': kinds,
                          'stopReason': (doc.get('trailer') or {}).get('stopReason'), 'problems': problems[:20]}))
        return 0 if not problems else 1
    print(__doc__.split('CLI:')[1].strip())
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
