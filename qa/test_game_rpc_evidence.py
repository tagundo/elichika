import unittest
from feature_client_smoke import game_request_counts, game_request_evidence, successful_game_requests


class FullLogEvidenceTests(unittest.TestCase):
    def test_real_login_and_mv_lines_survive_more_than_two_megabytes_of_asset_traffic(self):
        early=b"".join(b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "'+path+b'?request_id=synthetic"\n'
            for path in (b"/login/startup",b"/login/login",b"/bootstrap/fetchBootstrap",b"/liveMv/start"))
        assets=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | GET "/static/official-asset"\n'*40000
        log=early+assets
        self.assertGreater(len(assets),2*1024*1024)
        self.assertFalse(any(successful_game_requests(log[-2*1024*1024:]).values()))
        proof=game_request_evidence(log)
        self.assertEqual(proof,early)
        self.assertEqual(game_request_counts(proof),game_request_counts(log))
        self.assertTrue(all(successful_game_requests(proof).values()))

    def test_failed_rpc_is_retained_as_failure_unknown_paths_and_registrations_are_excluded(self):
        failed=b'[GIN] timestamp | 401 | 1ms | 127.0.0.1 | POST "/login/login"\n'
        noise=b'[GIN-debug] POST "/login/login"\n[GIN] timestamp | 200 | 1ms | 127.0.0.1 | GET "/login/login"\n[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "/liveMv/startAnother"\n'
        proof=game_request_evidence(failed+noise)
        self.assertEqual(proof,failed)
        self.assertFalse(any(successful_game_requests(proof).values()))




class StreamingOwnedEvidenceTests(unittest.TestCase):
    def test_compaction_preserves_exact_lines_offsets_source_hash_and_bounded_tail(self):
        import hashlib,json,tempfile
        from pathlib import Path
        from rpc_log_evidence import compact_owned_log
        early=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "/login/login?request_id=synthetic"\n'
        assets=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | GET "/static/asset"\n'*40000
        end=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "/liveMv/start"\n'
        original=early+assets+end
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'owned.log';path.write_bytes(original)
            receipt=compact_owned_log(path,root)
            self.assertEqual(receipt['source_sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(),original[-2*1024*1024:])
            proof=(root/'genuine-rpc-evidence.log').read_bytes();self.assertEqual(proof,early+end)
            for entry in receipt['entries']:
                raw=original[entry['source_byte_offset']:entry['source_byte_offset']+entry['bytes']]
                self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                self.assertEqual(proof[entry['proof_byte_offset']:entry['proof_byte_offset']+entry['bytes']],raw)
            self.assertEqual(receipt['entries'][0]['source_line'],1)
            self.assertEqual(receipt['entries'][1]['source_line'],40002)
            self.assertEqual(game_request_counts(proof),game_request_counts(original))

    def test_incremental_reader_waits_partial_line_and_never_rescans_or_duplicates_prior_rpc(self):
        import tempfile
        from pathlib import Path
        from rpc_log_evidence import IncrementalRpcEvidence
        first=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "/login/login"\n'
        second=b'[GIN] timestamp | 200 | 1ms | 127.0.0.1 | POST "/bootstrap/fetchBootstrap"'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'owned.log';p.write_bytes(first);reader=IncrementalRpcEvidence(p)
            self.assertEqual(reader.read(),first);self.assertEqual(reader.offset,len(first))
            with p.open('ab') as f:f.write(second)
            self.assertEqual(reader.read(),first);self.assertEqual(reader.offset,len(first))
            with p.open('ab') as f:f.write(b'\n')
            self.assertEqual(reader.read(),first+second+b'\n')
            self.assertEqual(reader.read(),first+second+b'\n')
            p.write_bytes(b'')
            with self.assertRaisesRegex(ValueError,'rotated or truncated'):reader.read()

    def test_fixture_never_compacts_while_process_or_log_writer_is_live(self):
        import tempfile
        from pathlib import Path
        from host_go_fixture import HostGoFixture,FixtureError
        with tempfile.TemporaryDirectory() as d:
            fixture=object.__new__(HostGoFixture);fixture.evidence=Path(d);fixture.log_path=Path(d)/'owned.log'
            fixture.log_path.write_bytes(b'owned line\n');fixture._final_log_receipt=None;fixture._stopped=False
            fixture.process=None;fixture._thread=None
            with self.assertRaises(FixtureError):fixture.finalize_log_evidence()
            fixture._stopped=True;fixture._thread=type('Writer',(),{'is_alive':lambda self:True})()
            with self.assertRaises(FixtureError):fixture.finalize_log_evidence()
            fixture._thread=None
            self.assertTrue(fixture.finalize_log_evidence()['source_compacted_only_after_owned_writer_stopped'])


if __name__=="__main__":unittest.main()
