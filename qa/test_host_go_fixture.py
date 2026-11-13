import copy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from host_go_fixture import (FixtureError, HostGoFixture, file_sha256, fixture_binding,
                             owned_child_environment, ready_response, redacted_log)

SOURCE = '1' * 40


def binding():
    return {'kind': 'source-build', 'source_sha': SOURCE, 'binary_sha256': '2' * 64,
            'toolchain': 'go1.22.12', 'build_args': ['CGO_ENABLED=0', 'go', 'build', '-trimpath'],
            'submodule_refs': {'assets': '3' * 40, 'modtools': '4' * 40}}


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class BindingTests(unittest.TestCase):
    def test_exact_source_build_binding_accepts_only_approved_toolchain_shape(self):
        receipt = {'schema_version': 1, 'server_fixture': binding()}
        self.assertEqual(fixture_binding(receipt, SOURCE), binding())
        for field, value in [('kind', 'delivered-artifact'), ('source_sha', '5' * 40),
                             ('binary_sha256', 'bad'), ('toolchain', 'go1.23.0'),
                             ('build_args', ['go', 'build']), ('submodule_refs', {'assets': '3' * 40})]:
            bad = copy.deepcopy(receipt)
            bad['server_fixture'][field] = value
            with self.subTest(field=field), self.assertRaises(FixtureError):
                fixture_binding(bad, SOURCE)
        for schema in (True, '1', 2):
            with self.subTest(schema=schema), self.assertRaises(FixtureError):
                fixture_binding({**receipt, 'schema_version': schema}, SOURCE)

    def test_readiness_nonce_is_not_a_privileged_child_capability(self):
        private = {'GH_TOKEN': 'oauth', 'GITHUB_TOKEN': 'ci', 'ELICHIKA_LOCAL_WEBUI_TOKEN': 'admin',
                   'ELICHIKA_TEST_FIXTURE_PASSWORD': 'password', 'ELICHIKA_READY_TOKEN': 'old'}
        with patch.dict(os.environ, private):
            environment = owned_child_environment('a' * 32)
        self.assertEqual(environment['ELICHIKA_READY_TOKEN'], 'a' * 32)
        for name in private:
            if name != 'ELICHIKA_READY_TOKEN': self.assertNotIn(name, environment)

    def test_sanitized_logs_keep_only_request_paths_and_no_secrets(self):
        self.assertNotIn('password', redacted_log('AdminPassword: password\n'))
        result = redacted_log('POST "/bootstrap/fetchBootstrap?key=private" nonce=secret pass=hidden\n', 'secret', 'hidden')
        self.assertIn('/bootstrap/fetchBootstrap?[redacted-query]', result)
        for value in ('private', 'secret', 'hidden'): self.assertNotIn(value, result)


# This tiny authored executable only tests process ownership/readiness transport.
# It contains no game or Elichika code and supplies no application-feature proof.
TEST_SERVER = r'''
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
int main(void) {
    int fd=socket(AF_INET,SOCK_STREAM,0), opt=1;
    setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,&opt,sizeof(opt));
    struct sockaddr_in addr={0}; addr.sin_family=AF_INET;
    addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    addr.sin_port=htons(atoi(getenv("HOST_FIXTURE_TEST_PORT")));
    if(bind(fd,(void*)&addr,sizeof(addr)) || listen(fd,4)) return 2;
    const char *nonce=getenv("ELICHIKA_READY_TOKEN");
    if(getenv("HOST_FIXTURE_WRONG_NONCE")) nonce="00000000000000000000000000000000";
    printf("AdminPassword: must-not-export\nnonce=%s GET /path?secret=value\n",nonce); fflush(stdout);
    for(;;) {
      int peer=accept(fd,NULL,NULL); if(peer<0) return 3;
      char request[4096],body[256],response[512]; read(peer,request,sizeof(request));
      snprintf(body,sizeof(body),"{\"ready\":true,\"token\":\"%s\"}",nonce);
      snprintf(response,sizeof(response),"HTTP/1.1 200 OK\r\nContent-Length: %zu\r\nConnection: close\r\n\r\n%s",strlen(body),body);
      write(peer,response,strlen(response));close(peer);
    }
}
'''


class OwnedLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):
            raise unittest.SkipTest('authored transport executable needs host C compiler')
        cls.compiled = tempfile.TemporaryDirectory(prefix='host-transport-compiled-')
        root = Path(cls.compiled.name)
        source = root / 'transport-test.c'; source.write_text(TEST_SERVER)
        cls.binary = root / 'transport-test'
        subprocess.run(['cc', '-O2', '-o', str(cls.binary), str(source)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.compiled.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='owned-host-fixture-test-')
        self.root = Path(self.temporary.name)
        self.port = free_port()
        (self.root / 'config.json').write_text(json.dumps({'server_address': f'127.0.0.1:{self.port}', 'tutorial': False, 'cdn_cache': True}))
        self.private = self.root / 'synthetic-account.private.json'
        self.private.write_text(json.dumps({'user_id': 123456789, 'password': 'AbCd0123456789XY'}))
        self.private.chmod(0o600)
        self.receipt = self.root / 'host-go-fixture.json'
        bound = {**binding(), 'binary_sha256': file_sha256(self.binary)}
        self.receipt.write_text(json.dumps({'schema_version': 1, 'server_fixture': bound,
            'runtime_root': str(self.root), 'binary_path': str(self.binary),
            'private_account_file': str(self.private), 'config_sha256': file_sha256(self.root / 'config.json')}))
        self.fixture = None

    def tearDown(self):
        if self.fixture: self.fixture.stop()
        self.temporary.cleanup()

    def construct(self):
        self.fixture = HostGoFixture(self.root, self.receipt, SOURCE, self.root / 'evidence', port=self.port)
        return self.fixture

    def test_actual_owned_executable_nonce_reverse_and_clean_stop(self):
        calls = []
        class Device:
            def adb(self, *args): calls.append(args)
        fixture = self.construct()
        with patch.dict(os.environ, {'HOST_FIXTURE_TEST_PORT': str(self.port)}):
            record = fixture.start(Device(), timeout=3)
        nonce = fixture._nonce
        self.assertTrue(ready_response(self.port, nonce))
        self.assertFalse(ready_response(self.port, 'f' * 32))
        self.assertEqual(record['binary_sha256'], file_sha256(self.binary))
        self.assertFalse(record['server_app_installed_by_qa'])
        self.assertFalse(record['management_started_by_qa'])
        self.assertNotIn(nonce, json.dumps(record))
        fixture.stop(Device())
        self.assertIsNotNone(fixture.process.poll())
        self.assertEqual(fixture._nonce, '')
        log = fixture.server_log().decode()
        for value in (nonce, 'must-not-export', '?secret=value'): self.assertNotIn(value, log)
        self.assertEqual(calls, [('reverse', f'tcp:{self.port}', f'tcp:{self.port}'),
                                 ('reverse', '--remove', f'tcp:{self.port}')])

    def test_occupied_port_is_left_untouched_and_no_child_is_launched(self):
        fixture = self.construct()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', self.port)); occupied.listen()
            with patch('host_go_fixture.subprocess.Popen') as launch:
                with self.assertRaisesRegex(FixtureError, 'owner was left untouched'): fixture.start(timeout=.3)
                launch.assert_not_called()
            self.assertGreater(occupied.fileno(), 0)

    def test_wrong_nonce_child_never_passes_and_is_stopped(self):
        fixture = self.construct()
        with patch.dict(os.environ, {'HOST_FIXTURE_TEST_PORT': str(self.port), 'HOST_FIXTURE_WRONG_NONCE': '1'}):
            with self.assertRaisesRegex(FixtureError, 'matching readiness nonce'): fixture.start(timeout=.4)
        self.assertIsNotNone(fixture.process.poll())
        self.assertFalse((fixture.evidence / 'host-go-runtime.json').exists())
        self.assertEqual(fixture._nonce, '')

    def test_changed_config_or_binary_and_public_credentials_are_rejected(self):
        original = (self.root / 'config.json').read_bytes()
        (self.root / 'config.json').write_bytes(original + b' ')
        with self.assertRaisesRegex(FixtureError, 'configuration changed'): self.construct()
        (self.root / 'config.json').write_bytes(original)
        self.private.chmod(0o644)
        with self.assertRaisesRegex(FixtureError, 'must remain private'): self.construct()
        self.private.chmod(0o600)
        value = json.loads(self.receipt.read_text()); value['server_fixture']['binary_sha256'] = '0' * 64
        self.receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(FixtureError, 'executable differs'): self.construct()

    def test_child_exit_before_cleanup_is_a_hard_failure(self):
        fixture = self.construct()
        with patch.dict(os.environ, {'HOST_FIXTURE_TEST_PORT': str(self.port)}):
            fixture.start(timeout=3)
        fixture.process.terminate()
        fixture.process.wait(timeout=2)
        with self.assertRaisesRegex(FixtureError, 'exited before QA cleanup'):
            fixture.stop()
        self.assertEqual(fixture._nonce, '')

    def test_database_observation_cannot_escape_runtime(self):
        fixture = self.construct()
        (self.root / 'userdata.db').write_bytes(b'readonly-observation')
        self.assertEqual(fixture.read_database('userdata.db'), b'readonly-observation')
        with self.assertRaisesRegex(FixtureError, 'escaped'): fixture.read_database('../outside.db')

    def test_spawn_failure_clears_nonce_without_printing_environment(self):
        fixture = self.construct()
        with patch('host_go_fixture.subprocess.Popen', side_effect=OSError('test failed to spawn')):
            with self.assertRaises(OSError): fixture.start(timeout=.2)
        self.assertEqual(fixture._nonce, '')
        self.assertIsNone(fixture.process)


if __name__ == '__main__':
    unittest.main()
