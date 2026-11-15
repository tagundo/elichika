import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import elichika_ios_runtime as runtime


class RetryTests(unittest.TestCase):
    def test_simulator_maintenance_sequence_redacts_config_result(self):
        from elichika_ios.probes import lifecycle
        native = types.SimpleNamespace(state={"state": "ready", "ready": True, "generation": 1}, commands=[])
        native.go_status = lambda: json.dumps(native.state)
        def stop():
            native.commands.append("stop")
            native.state.update(state="stopped", ready=False, generation=2)
            return json.dumps(native.state)
        def command(raw):
            self.assertEqual(json.loads(raw)["command"], "config_read")
            native.commands.append("config_read")
            native.state.update(generation=3, job={"id": 3, "state": "succeeded", "result": {"admin_password": "private-password"}})
            return json.dumps(native.state)
        def start(raw):
            self.assertEqual(json.loads(raw)["web_token"], "private-token")
            native.commands.append("start")
            native.state.update(state="ready", ready=True, generation=4)
            return json.dumps(native.state)
        native.go_stop, native.go_command, native.go_start = stop, command, start
        modules = {"adminui": types.ModuleType("adminui"),
                   "adminui.serverctl": types.SimpleNamespace(_controller=types.SimpleNamespace(options={"web_token": "private-token"})),
                   "adminui.jobs": types.SimpleNamespace(MANAGER=types.SimpleNamespace(_active=0))}
        modules["adminui"].__path__ = []
        with patch.dict(sys.modules, modules):
            result = lifecycle(native)
        self.assertTrue(result["ready"], result)
        self.assertEqual(native.commands, ["stop", "config_read", "start"])
        self.assertEqual(result["generation_after"], 4)
        self.assertNotIn("private", json.dumps(result))

    def test_rejected_native_start_fails_without_waiting_for_unchanged_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = root / "source", root / "data"
            source.mkdir()
            data.mkdir()
            native = types.SimpleNamespace(
                go_status=lambda: json.dumps({"state": "stopped", "phase": "stopped", "ready": False}),
                go_start=lambda config: json.dumps({"error": {"code": "OPTIONS_INVALID", "message": "The selected region is invalid"}}),
                go_stop=lambda: None, report_event=lambda event: None)
            paths_before = list(sys.path)
            with patch.object(runtime, "_native", native), patch.object(runtime, "_scope", None), \
                 patch.object(runtime, "_bootstrap_thread", None), \
                 patch.object(runtime, "_state", {"phase": "stopped", "ready": False}), \
                 patch.object(runtime, "_prepare_data", return_value=data), \
                 patch.dict(sys.modules, {"_elichika_ios": native}):
                try:
                    runtime.start(json.dumps({"payload_root": str(source), "data_root": str(data), "core_only": True,
                                              "token": "a" * 64, "ready_token": "b" * 64, "startup_timeout": 60}))
                    runtime._bootstrap_thread.join(timeout=2)
                    self.assertFalse(runtime._bootstrap_thread.is_alive())
                    result = json.loads(runtime.status())
                    self.assertFalse(result["ready"])
                    self.assertEqual(result["phase"], "failed")
                    self.assertIn("OPTIONS_INVALID: The selected region is invalid", result["error"])
                finally:
                    if runtime._scope:
                        runtime._scope.uninstall()
                    sys.path[:] = paths_before

    def test_same_root_restart_reuses_scope_and_cross_root_is_refused(self):
        """Unit-test lifecycle boundaries; this fake native is not server proof."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data, other = root / "source", root / "data", root / "other"
            for path in (source, data, other):
                path.mkdir()
            native = types.SimpleNamespace(server={"state": "stopped", "phase": "stopped", "ready": False})
            native.go_status = lambda: json.dumps(native.server)
            native.go_start = lambda config: native.server.update(state="ready", phase="running", ready=True)
            native.go_stop = lambda: native.server.update(state="stopped", phase="stopped", ready=False)
            native.report_event = lambda event: None
            configuration = {"payload_root": str(source), "data_root": str(data), "core_only": True,
                             "token": "a" * 64, "ready_token": "b" * 64}
            paths_before = list(sys.path)
            with patch.object(runtime, "_native", native), patch.object(runtime, "_scope", None), \
                 patch.object(runtime, "_bootstrap_thread", None), \
                 patch.object(runtime, "_state", {"phase": "stopped", "ready": False}), \
                 patch.object(runtime, "_prepare_data", return_value=data), \
                 patch.dict(sys.modules, {"_elichika_ios": native}):
                try:
                    runtime.start(json.dumps(configuration))
                    runtime._bootstrap_thread.join(timeout=2)
                    self.assertEqual(json.loads(runtime.status())["phase"], "core_ready")
                    original_scope = runtime._scope
                    runtime.stop()
                    runtime.start(json.dumps(configuration))
                    runtime._bootstrap_thread.join(timeout=2)
                    self.assertEqual(json.loads(runtime.status())["phase"], "core_ready")
                    self.assertIs(runtime._scope, original_scope)
                    runtime.stop()
                    with self.assertRaisesRegex(RuntimeError, "Close and reopen"):
                        runtime.start(json.dumps(dict(configuration, data_root=str(other))))
                finally:
                    if runtime._scope:
                        runtime._scope.uninstall()
                    sys.path[:] = paths_before

    def test_probe_evidence_omits_private_capabilities(self):
        native = types.SimpleNamespace(
            go_status=lambda: json.dumps({"ready": True, "phase": "running", "ready_token": "private-ready", "local_webui_token": "private-web"}),
            https_request=lambda *args: {"status": 200})
        with patch.object(runtime, "_native", native), \
             patch.object(runtime, "_state", {"phase": "ready", "ready": True, "tools_url": "private-url"}), \
             patch("elichika_ios.dependencies.probe", return_value={"ready": True}):
            result = runtime.probe()
        self.assertNotIn("private", result)
        self.assertTrue(json.loads(result)["tls_probe"])


if __name__ == "__main__":
    unittest.main()
