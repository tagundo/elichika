"""Build-output transaction and raw-repeatability gates, using isolated SQLite."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deterministic_serverdata',
    ROOT / 'android/ci/build_deterministic_serverdata.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def database(path, value):
    assert not path.exists()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE official(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        connection.execute('INSERT INTO official VALUES(1,?)', (value,))
        connection.commit()


class DeterministicServerdataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='serverdata-build-test-')
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.runtime = self.parent / 'runtime'
        self.runtime.mkdir()
        (self.runtime / build.BUILD_MARKER).write_text(build.BUILD_MARKER_CONTENT)
        for name in ('assets/db/gl/masterdata.db', 'assets/db/jp/masterdata.db',
                     'server init jsons/gacha.json', 'webui/index.html', 'privatekey.pem', 'publickey.pem'):
            path = self.runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'public build input')
        self.binary = self.parent / 'host-binary'
        self.binary.write_bytes(b'fixed synthetic generator')
        self.output = self.runtime / 'serverdata.db'
        database(self.output, 'previous generated output')
        self.original = self.output.read_bytes()
        self.original_inode = self.output.stat().st_ino
        self.report = self.parent / 'proof.json'
        self.first = self.parent / 'first.db'
        self.calls = 0

    def generate(self, runtime, binary):
        self.assertEqual(runtime, self.runtime)
        self.assertEqual(binary, self.binary)
        self.assertFalse(self.output.exists(), 'Every generation must start from a new file')
        self.calls += 1
        database(self.output, 'final official rows')

    def run_build(self, runner=None, **kwargs):
        return build.build(self.runtime, self.binary, self.report, build_only=True,
                           first_output=kwargs.pop('first_output', self.first),
                           runner=runner or self.generate, **kwargs)

    def assert_original(self):
        self.assertEqual(self.output.read_bytes(), self.original)
        self.assertEqual(self.output.stat().st_ino, self.original_inode)
        self.assertFalse(self.report.exists())
        self.assertFalse(any(self.runtime.glob('.serverdata-repeatability-*')))

    def test_two_fresh_equal_images_publish_exact_second_and_bounded_proof(self):
        source = build.inputs(self.runtime)
        result = self.run_build()
        self.assertEqual(self.calls, 2)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['raw_output_equal'])
        self.assertEqual(result['fresh_generations'], 2)
        self.assertEqual(result['outputs'][0], result['outputs'][1])
        self.assertEqual(self.output.read_bytes(), self.first.read_bytes())
        self.assertNotEqual(self.output.read_bytes(), self.original)
        self.assertEqual(result['outputs'][1]['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(result['outputs'][1]['table_rows'], {'official': 1})
        self.assertEqual(result['input_sha256'], hashlib.sha256(build.canonical(source)).hexdigest())
        self.assertEqual(build.inputs(self.runtime), source)
        self.assertEqual(json.loads(self.report.read_text()), result)
        self.assertFalse(any(self.runtime.glob('.serverdata-repeatability-*')))

    def test_requires_explicit_build_opt_in_before_any_write(self):
        with self.assertRaisesRegex(build.BuildError, 'BUILD_ONLY_OPT_IN_REQUIRED'):
            build.build(self.runtime, self.binary, self.report, runner=self.generate)
        self.assert_original()
        self.assertEqual(self.calls, 0)

    def test_rejects_unmarked_app_like_runtime_even_with_opt_in(self):
        (self.runtime / build.BUILD_MARKER).unlink()
        with self.assertRaisesRegex(build.BuildError, 'EXPLICIT_BUILD_RUNTIME_REQUIRED'):
            self.run_build()
        self.assert_original()

    def test_existing_sidecar_refuses_without_discarding_it(self):
        sidecar = self.output.with_name('serverdata.db-wal')
        sidecar.write_bytes(b'not owned by this build helper')
        with self.assertRaisesRegex(build.BuildError, 'GENERATED_DATABASE_HAS_SIDECARS'):
            self.run_build()
        self.assert_original()
        self.assertEqual(sidecar.read_bytes(), b'not owned by this build helper')

    def test_nondeterministic_raw_images_refuse_and_restore_prior_output(self):
        def changing(runtime, binary):
            self.calls += 1
            database(self.output, str(self.calls))
        with self.assertRaisesRegex(build.BuildError, 'SERVERDATA_NOT_REPRODUCIBLE'):
            self.run_build(changing)
        self.assert_original()
        self.assertEqual(self.calls, 2)
        self.assertFalse(self.first.exists())

    def test_changed_final_client_input_refuses_and_restores_prior_output(self):
        def changed(runtime, binary):
            self.generate(runtime, binary)
            (runtime / 'assets/db/gl/masterdata.db').write_bytes(b'changed after final migration')
        with self.assertRaisesRegex(build.BuildError, 'FINAL_BUILD_INPUTS_CHANGED'):
            self.run_build(changed)
        self.assert_original()
        self.assertEqual(self.calls, 1)

    def test_changed_binary_refuses_and_restores_prior_output(self):
        def changed(runtime, binary):
            self.generate(runtime, binary)
            binary.write_bytes(b'new executable during repeat-build')
        with self.assertRaisesRegex(build.BuildError, 'BUILD_BINARY_CHANGED'):
            self.run_build(changed)
        self.assert_original()

    def test_generator_error_after_creating_output_restores_prior_and_cleans_new_sidecar(self):
        def failed(runtime, binary):
            self.generate(runtime, binary)
            self.output.with_name('serverdata.db-journal').write_bytes(b'new incomplete output')
            raise RuntimeError('synthetic generator error')
        with self.assertRaises(RuntimeError):
            self.run_build(failed)
        self.assert_original()
        self.assertFalse(self.output.with_name('serverdata.db-journal').exists())

    def test_corrupt_generated_output_is_not_published(self):
        def corrupt(runtime, binary):
            self.output.write_bytes(b'not a SQLite database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_build(corrupt)
        self.assert_original()

    def test_generated_directory_is_parked_without_losing_prior_output(self):
        def directory(runtime, binary):
            self.output.mkdir()
            (self.output / 'new-child').write_text('owned invalid generator output')
        with self.assertRaisesRegex(build.BuildError, 'GENERATED_DATABASE_MISSING_OR_LINKED'):
            self.run_build(directory)
        self.assert_original()

    def test_generated_symlink_does_not_follow_or_remove_external_file(self):
        external = self.parent / 'external-public-fixture'
        external.write_bytes(b'keep this file')
        def linked(runtime, binary):
            self.output.symlink_to(external)
        try:
            with self.assertRaisesRegex(build.BuildError, 'GENERATED_DATABASE_MISSING_OR_LINKED'):
                self.run_build(linked)
        except OSError as error:
            self.skipTest(f'Symlink creation not available: {type(error).__name__}')
        self.assert_original()
        self.assertEqual(external.read_bytes(), b'keep this file')

    def test_reports_and_retained_output_cannot_mutate_inputs_or_clobber_existing_files(self):
        existing = self.parent / 'existing-first.db'
        existing.write_bytes(b'keep prior evidence')
        with self.assertRaisesRegex(build.BuildError, 'FIRST_OUTPUT_MUST_BE_NEW_OUTSIDE_RUNTIME'):
            self.run_build(first_output=existing)
        self.assertEqual(existing.read_bytes(), b'keep prior evidence')
        with self.assertRaisesRegex(build.BuildError, 'REPORT_MUST_BE_NEW_OUTSIDE_RUNTIME'):
            build.build(self.runtime, self.binary, self.runtime / 'assets/proof.json',
                        build_only=True, runner=self.generate)
        self.assert_original()

    def test_linked_inputs_are_rejected_before_any_generation(self):
        target = self.runtime / 'webui/index.html'
        contents = self.parent / 'external-input'
        contents.write_bytes(target.read_bytes())
        target.unlink()
        try:
            target.symlink_to(contents)
        except OSError as error:
            self.skipTest(f'Symlink creation not available: {type(error).__name__}')
        with self.assertRaisesRegex(build.BuildError, 'BUILD_INPUT_SYMLINK'):
            self.run_build()
        self.assert_original()
        self.assertEqual(self.calls, 0)


if __name__ == '__main__':
    unittest.main()
