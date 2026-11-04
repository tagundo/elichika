"""Independent readiness uses the established service routes, without bodies."""
import json
import ast
import inspect
import textwrap
import unittest
from unittest import mock
import urllib.error

import mod_loss_control as qa


NATIVE = "c" * 64


class ReadinessTests(unittest.TestCase):
    def test_endpoint_contract_matches_existing_release_smoke_helper(self):
        syntax = ast.parse(textwrap.dedent(inspect.getsource(qa.release.Android.start)))
        contracts = [ast.literal_eval(node.iter) for node in ast.walk(syntax) if isinstance(node, ast.For)
                     and isinstance(node.target, ast.Tuple) and
                     [getattr(value, "id", None) for value in node.target.elts] == ["port", "path"]]
        self.assertEqual(contracts, [qa.READINESS_ENDPOINTS])

    def android(self):
        result = mock.Mock()
        result.shell.side_effect = ["123", NATIVE + " /proc/123/exe"]
        return result

    def test_all_three_known_routes_are_checked_without_root_go_probe(self):
        urls = []
        def open_request(request, timeout):
            urls.append(request.full_url)
            return mock.Mock(status=200)
        opener, evidence = mock.Mock(), {}
        opener.open.side_effect = open_request
        with mock.patch.object(qa.urllib.request, "build_opener", return_value=opener):
            result = qa.running_target(self.android(), NATIVE, evidence)
        self.assertEqual(urls, ["http://127.0.0.1:18080/webui/admin/", "http://127.0.0.1:18770/", "http://127.0.0.1:18772/"])
        self.assertEqual(result["readiness"], {"18080": 200, "18770": 200, "18772": 200})
        self.assertEqual(evidence["readiness_probes"][0], {"port": 18080, "path": "/webui/admin/", "status": 200})

    def test_every_service_must_still_be_http200_without_redirects(self):
        for failed_port, status in ((18080, 302), (18770, 503), (18772, 404)):
            with self.subTest(port=failed_port):
                evidence = {}
                def open_request(request, timeout):
                    if request.full_url.startswith(f"http://127.0.0.1:{failed_port}/"):
                        raise urllib.error.HTTPError(request.full_url, status, "private-session-material", {"Location": "private-token"}, None)
                    return mock.Mock(status=200)
                opener = mock.Mock()
                opener.open.side_effect = open_request
                with mock.patch.object(qa.urllib.request, "build_opener", return_value=opener), \
                     self.assertRaisesRegex(qa.policy.ModLossControlError, "negative_server_readiness_failed"):
                    qa.running_target(self.android(), NATIVE, evidence)
                self.assertEqual(evidence["readiness_probes"][-1]["status"], status)
                self.assertNotIn("private-", json.dumps(evidence))

    def test_transport_failure_records_only_fixed_type_and_route(self):
        opener, evidence = mock.Mock(), {}
        opener.open.side_effect = RuntimeError("private-auth-material")
        with mock.patch.object(qa.urllib.request, "build_opener", return_value=opener), \
             self.assertRaisesRegex(qa.policy.ModLossControlError, "negative_server_readiness_failed"):
            qa.running_target(self.android(), NATIVE, evidence)
        self.assertEqual(evidence["readiness_probes"], [{"port": 18080, "path": "/webui/admin/", "error_type": "RuntimeError"}])
        self.assertNotIn("private-auth-material", json.dumps(evidence))

    def test_native_identity_or_multiprocess_failure_precedes_any_network(self):
        for outputs in (["123 456"], ["123", "wrong-native"]):
            with self.subTest(outputs=outputs):
                android = mock.Mock()
                android.shell.side_effect = outputs
                with mock.patch.object(qa.urllib.request, "build_opener") as opener, self.assertRaises(qa.policy.ModLossControlError):
                    qa.running_target(android, NATIVE)
                opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
