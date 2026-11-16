"""Observe bootstrap costs without exposing paths or changing installer semantics."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import elichika_ios_runtime as runtime


class PreparationTimingTests(unittest.TestCase):
    def test_observer_records_stages_without_source_paths_or_current_file_names(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            data, seed = base / 'data', base / 'resources/payload'
            seed.mkdir(parents=True)
            (seed / 'publickey.pem').write_bytes(b'fixture-public-key')
            calls = []
            def install(resources, target, **kwargs):
                calls.append('payload')
                kwargs['progress']('copying_data', 1, 2, 'private-file-name')
                for name in ('config.json', 'assets/db/gl/masterdata.db', 'assets/db/jp/masterdata.db', 'privatekey.pem'):
                    p = target / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('{}')
                (target / 'publickey.pem').write_bytes(b'fixture-public-key')
                kwargs['progress']('verifying', 2, 2, str(base))
            payload = types.SimpleNamespace(install_payload=install,
                install_tool_data=lambda *a: calls.append('tool-data'),
                ensure_config=lambda *a: calls.append('config'))
            with patch.dict('sys.modules', {'elichika_ios.payload': payload}), \
                    patch.object(runtime, '_native', None), patch.object(runtime, '_state', {}):
                self.assertEqual(runtime._prepare_data({'data_root': str(data), 'seed_root': str(seed),
                    'payload_root': str(base / 'python-app'), 'packs_root': str(base / 'library/packs')}), data)
                timings = runtime._state['preparation_timings']
                self.assertEqual(calls, ['payload', 'tool-data', 'config'])
                self.assertEqual(set(timings['payload_stages_seconds']), {'copying_data', 'verifying'})
                for key in ('payload_seconds', 'tool_data_seconds', 'configuration_seconds', 'total_seconds'):
                    self.assertGreaterEqual(timings[key], 0)
                self.assertGreaterEqual(timings['total_seconds'], timings['payload_seconds'])
                text = json.dumps(timings)
                self.assertNotIn(str(base), text)
                self.assertNotIn('private-file-name', text)


if __name__ == '__main__':
    unittest.main()
