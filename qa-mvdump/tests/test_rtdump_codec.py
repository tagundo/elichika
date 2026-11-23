"""rtdump_codec: schema validation, FMOV decode, log transport, merge, drop order."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rtdump_codec as codec  # noqa: E402

EXAMPLE = json.loads((HERE / 'fixtures' / 'schema.example.json').read_text())


class TestValidate(unittest.TestCase):
    def test_accepts_the_schema_example(self):
        self.assertEqual(codec.validate(EXAMPLE), [])

    def test_rejects_unknown_schema_and_missing_envelope(self):
        doc = copy.deepcopy(EXAMPLE)
        doc['schema'] = 'sifas-mv-runtime-dump/2'
        self.assertTrue(any('unknown schema' in p for p in codec.validate(doc)))
        for key in ('schema', 'side', 'header', 'records', 'trailer'):
            doc = copy.deepcopy(EXAMPLE)
            del doc[key]
            self.assertTrue(any(key in p for p in codec.validate(doc)), key)
        with self.assertRaises(codec.DumpError):
            codec.check({'schema': codec.SCHEMA})

    def test_rejects_row_major_projection_and_bad_conventions(self):
        doc = copy.deepcopy(EXAMPLE)
        cam = doc['records'][0]['cameras'][0]
        p = cam['projection']
        cam['projection'] = [p[(i % 4) * 4 + i // 4] for i in range(16)]  # transposed = row-major
        self.assertTrue(any('column-major' in x for x in codec.validate(doc)))
        doc = copy.deepcopy(EXAMPLE)
        doc['header']['conventions'] = codec.CONVENTIONS['editor']
        self.assertTrue(any('conventions' in x for x in codec.validate(doc)))

    def test_rejects_duplicate_ids_unknown_parts_and_nan(self):
        doc = copy.deepcopy(EXAMPLE)
        doc['records'][1]['id'] = doc['records'][0]['id']
        doc['records'][2]['part'] = 'bogus'
        doc['records'][3]['clock']['directorTime'] = float('nan')
        problems = codec.validate(doc)
        self.assertTrue(any('duplicate id' in p for p in problems))
        self.assertTrue(any('unknown part' in p for p in problems))
        self.assertTrue(any('directorTime' in p for p in problems) and any('non-finite' in p for p in problems))

    def test_editor_records_need_source_record(self):
        doc = copy.deepcopy(EXAMPLE)
        doc['side'] = 'editor'
        doc['header']['conventions'] = codec.CONVENTIONS['editor']
        self.assertTrue(any('sourceRecord' in p for p in codec.validate(doc)))


class TestFmov(unittest.TestCase):
    def test_default_words(self):
        self.assertEqual(codec.decode_fmov_word(0x1E2D1001), 0.75)
        self.assertEqual(codec.decode_fmov_word(0x1E2E1002), 1.0)
        self.assertEqual(codec.decode_fmov_word('1e2d1001'), 0.75)
        self.assertIsNone(codec.decode_fmov_word(None))
        self.assertIsNone(codec.decode_fmov_word('zz'))

    def test_imm8_matches_vfp_expand_imm(self):
        self.assertEqual(codec.imm8_to_float(0x70), 1.0)
        self.assertEqual(codec.imm8_to_float(0x00), 2.0)
        self.assertEqual(codec.imm8_to_float(0xF0), -1.0)
        self.assertEqual(codec.imm8_to_float(0x60), 0.5)


def noise(seed, size):
    """Incompressible text, so blob sizes track the record count."""
    out, h = [], seed.encode()
    while sum(map(len, out)) < size:
        h = hashlib.sha256(h).digest()
        out.append(h.hex())
    return ''.join(out)[:size]


def doc_with(n_frames=5, parts=None):
    doc = copy.deepcopy(EXAMPLE)
    frame = doc['records'][0]
    records = []
    for i in range(n_frames):
        f = copy.deepcopy(frame)
        f['id'], f['seq'] = f'f{i + 1:04d}', len(records) + 1
        records.append(f)
    for part, count, size in parts or []:
        for k in range(count):
            records.append({'id': f'p0-{part}-{k:02d}', 'kind': 'full', 'seq': len(records) + 1, 'pass': 0, 'part': part, 'chunk': k,
                            'clock': {'directorTime': 1.0 + k}, part: [{'blob': noise(f'{part}{k}', size)}]})
    doc['records'] = records
    return doc


class TestTransport(unittest.TestCase):
    def test_emit_extract_round_trip_with_github_prefix_and_noise(self):
        doc = doc_with(20, [('renderers', 3, 4000)])
        core, full, truncation = codec.split_for_log(doc, 10 ** 9)
        self.assertIsNone(truncation)
        lines = ['@@STEP {"x":1}']
        for name, part in ((codec.CORE, core), (codec.FULL, full)):
            codec.emit_blob(name, codec.encode_doc(part), lines.append, records=len(part['records']))
            lines.append('@@SHOT-BEGIN noise')
            lines.append('@@QUJD')
            lines.append('@@SHOT-END noise')
        log = '\n'.join(f'2026-11-23T03:21:{i % 60:02d}.{i:07d}Z {line}' for i, line in enumerate(lines))
        blobs = codec.extract_from_log(log)
        self.assertEqual(codec.decode_blob(blobs[codec.CORE]), core)
        self.assertEqual(codec.decode_blob(blobs[codec.FULL]), full)
        self.assertEqual(codec.merge([codec.decode_blob(b) for b in blobs.values()]), doc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'job.log'
            path.write_text(log)
            self.assertEqual(codec.load(path), doc)
            out = subprocess.run([sys.executable, str(HERE.parent / 'rtdump_codec.py'), 'extract', str(path), str(Path(tmp) / 'out')],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(codec.load(Path(tmp) / 'out' / 'mv-runtime-dump.json.gz'), doc)

    def test_extraction_rejects_a_corrupted_blob(self):
        lines = []
        codec.emit_blob(codec.CORE, codec.encode_doc(doc_with(3)), lines.append)
        lines[3] = '@@' + ('A' if lines[3][2] != 'A' else 'B') + lines[3][3:]
        with self.assertRaises(codec.DumpError):
            codec.extract_from_log('\n'.join(lines))

    def test_encoding_is_deterministic(self):
        doc = doc_with(4)
        self.assertEqual(codec.encode_doc(doc), codec.encode_doc(copy.deepcopy(doc)))

    def test_drop_order_and_core_never_dropped(self):
        doc = doc_with(10, [('particles', 2, 3000), ('springs', 2, 3000), ('stageNodes', 2, 3000), ('census', 2, 3000),
                            ('materials', 2, 3000), ('renderers', 2, 3000)])
        core_only = codec.b64_len(len(codec.encode_doc(codec.subset(doc, [r for r in doc['records'] if r['kind'] == 'frame']))))
        full_size = codec.b64_len(len(codec.encode_doc(codec.subset(doc, [r for r in doc['records'] if r['kind'] == 'full']))))
        core, full, truncation = codec.split_for_log(doc, core_only + full_size // 2)
        self.assertEqual(truncation['dropped'], list(codec.DROP_ORDER[:len(truncation['dropped'])]))
        self.assertEqual(core['records'], [r for r in doc['records'] if r['kind'] == 'frame'])
        self.assertFalse({r['part'] for r in full['records']} & set(truncation['dropped']))
        self.assertIn('renderers', {r['part'] for r in full['records']})
        core, full, truncation = codec.split_for_log(doc, core_only)
        self.assertIsNone(full)
        self.assertEqual(truncation['dropped'][-1], 'rtdump-full')
        self.assertEqual(len(core['records']), 10)

    def test_probe_blob_travels_with_the_dump_but_is_never_merged(self):
        doc = doc_with(5, [('renderers', 1, 500)])
        probe = {'chunks': [{'kind': 'probe', 'chunk': 0, 'classes': [
            {'key': 'CameraAspectCorrector', 'found': True, 'fullName': 'LLAS.Scene.Live.Components.CameraAspectCorrector',
             'fields': [{'name': '<Correction>k__BackingField', 'type': 'System.Single', 'offset': 24, 'static': False}]}]}],
            'classesFound': ['LLAS.Scene.Live.Components.CameraAspectCorrector'], 'classesMissing': [], 'resolved': {}, 'layoutSelfCheck': {'ok': True}}
        core, full, _ = codec.split_for_log(doc, 10 ** 9)
        lines = []
        codec.emit_blob(codec.CORE, codec.encode_doc(core), lines.append, records=len(core['records']))
        codec.emit_blob(codec.PROBE, codec.encode_doc(probe), lines.append)
        codec.emit_blob(codec.FULL, codec.encode_doc(full), lines.append, records=len(full['records']))
        log = '\n'.join(f'2026-11-23T03:21:{i % 60:02d}.{i:07d}Z {line}' for i, line in enumerate(lines))
        blobs = codec.extract_from_log(log)
        self.assertEqual(set(blobs), {codec.CORE, codec.FULL, codec.PROBE})
        self.assertEqual(codec.decode_blob(blobs[codec.PROBE]), probe)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'job.log'
            path.write_text(log)
            self.assertEqual(codec.load(path), doc)
            out = subprocess.run([sys.executable, str(HERE.parent / 'rtdump_codec.py'), 'extract', str(path), str(Path(tmp) / 'out')],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(codec.decode_blob((Path(tmp) / 'out' / 'rtdump-probe.json.gz').read_bytes()), probe)
            self.assertEqual(codec.load(Path(tmp) / 'out' / 'mv-runtime-dump.json.gz'), doc)
            self.assertIn('"classesFound": 1', out.stdout)

    def test_fit_probe_reduces_in_order(self):
        fields = [{'name': hashlib.sha256(str(j).encode()).hexdigest(), 'type': 'System.Single', 'offset': j, 'static': False,
                   'declaredIn': 'LLAS.X', 'valueType': True, 'enum': False} for j in range(64)]
        probe = {'chunks': [{'classes': [{'key': f'K{i}', 'found': True, 'fields': fields} for i in range(10)]}],
                 'classesFound': [f'K{i}' for i in range(10)], 'classesMissing': [], 'resolved': {}}
        sizes = {}
        for cap in (10 ** 9, 1):
            data, doc, level = codec.fit_probe(probe, cap)
            sizes[cap] = level
        self.assertEqual(sizes[10 ** 9], 'full')
        self.assertEqual(sizes[1], 'omitted')
        full_b64 = codec.b64_len(len(codec.encode_doc(probe)))
        data, doc, level = codec.fit_probe(probe, full_b64 - 1)
        self.assertEqual(level, 'fields-trimmed')
        self.assertEqual(len(doc['chunks'][0]['classes'][0]['fields']), 32)
        self.assertEqual(doc['chunks'][0]['classes'][0]['fieldsTotal'], 64)
        self.assertEqual(set(doc['chunks'][0]['classes'][0]['fields'][0]), {'name', 'type', 'offset'})
        self.assertEqual(codec.decode_blob(data), doc)
        self.assertEqual(len(probe['chunks'][0]['classes'][0]['fields']), 64, 'the input is not modified')
        trimmed_b64 = codec.b64_len(len(data))
        data, doc, level = codec.fit_probe(probe, trimmed_b64 - 1)
        self.assertEqual(level, 'fields-dropped')
        self.assertNotIn('fields', doc['chunks'][0]['classes'][0])
        self.assertEqual(doc['classesFound'], probe['classesFound'])

    def test_merge_refuses_different_headers(self):
        a, b = doc_with(2), doc_with(2)
        b['header']['createdAt'] = 'other'
        with self.assertRaises(codec.DumpError):
            codec.merge([a, b])


class TestCli(unittest.TestCase):
    def test_verify_example(self):
        out = subprocess.run([sys.executable, str(HERE.parent / 'rtdump_codec.py'), 'verify', str(HERE / 'fixtures' / 'schema.example.json')],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(json.loads(out.stdout)['problems'], [])


if __name__ == '__main__':
    unittest.main()
