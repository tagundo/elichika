from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import elichika_ios_runtime as runtime


class StartupOverlapTests(unittest.TestCase):
    """Fake native barriers verify scheduling, never real server readiness."""
    @contextmanager
    def bootstrap(self, *, core_only=False):
        from elichika_ios import codecs, dependencies, management
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            root = Path(directory).resolve()
            source, data = root / "source", root / "data"
            source.mkdir(); data.mkdir()
            state = {"state": "stopped", "phase": "stopped", "ready": False}
            native = types.SimpleNamespace(report_event=Mock())
            native.go_status = Mock(side_effect=lambda: json.dumps(state))
            def start(raw):
                state.update(state="starting", phase="starting", ready=False)
                return json.dumps(state)
            native.go_start = Mock(side_effect=start)
            native.go_stop = Mock(side_effect=lambda: state.update(state="stopping", ready=False))
            probe = patches.enter_context(patch.object(dependencies, "probe", return_value={"ready": True, "failures": {}}))
            codec = patches.enter_context(patch.object(codecs, "install", return_value={"codec": "checked"}))
            patches.enter_context(patch.object(management, "Management", return_value=object()))
            fake_admin = types.ModuleType("adminui"); fake_admin.__path__ = []
            modules = {"_elichika_ios": native, "adminui": fake_admin,
                       "adminui.serverctl": types.SimpleNamespace(register_controller=Mock()),
                       "adminui.jobs": types.SimpleNamespace(MANAGER=types.SimpleNamespace(
                           _lock=threading.Lock(), _jobs={}))}
            patches.enter_context(patch.dict(sys.modules, modules))
            imported = []
            original_import = runtime.importlib.import_module
            def import_module(name, *args, **kwargs):
                if name in ("adminui.server", "webtools.server"):
                    self.assertTrue(state["ready"], "DB-dependent servers imported before Go readiness")
                    imported.append(name)
                    return types.SimpleNamespace()
                return original_import(name, *args, **kwargs)
            patches.enter_context(patch.object(runtime.importlib, "import_module", side_effect=import_module))
            for name, value in (("_native", native), ("_scope", None), ("_bootstrap_thread", None),
                                ("_state", {"phase": "stopped", "ready": False}), ("_cancel", threading.Event()),
                                ("_servers", []), ("_threads", []), ("_management", None)):
                patches.enter_context(patch.object(runtime, name, value))
            for name, value in (("_configure_mime", None), ("_prepare_data", data), ("_bind_managers", None),
                                ("_mv_audio_dispose", None), ("_close_servers", None), ("GoController", object()),
                                ("bind_panels", []), ("panel_urls", ("http://127.0.0.1:8770/", "http://127.0.0.1:8772/"))):
                patches.enter_context(patch.object(runtime, name, return_value=value))
            stages = []
            patches.enter_context(patch.object(runtime, "_probe_stage", side_effect=stages.append))
            configuration = {"payload_root": str(source), "data_root": str(data), "core_only": core_only,
                             "token": "a"*64, "ready_token": "b"*64, "startup_timeout": 30}
            before = list(sys.path)
            context = types.SimpleNamespace(native=native, state=state, probe=probe, codec=codec,
                                            imported=imported, stages=stages, configuration=configuration)
            try:
                yield context
            finally:
                runtime._cancel.set()
                if runtime._bootstrap_thread:
                    runtime._bootstrap_thread.join(timeout=3)
                    self.assertFalse(runtime._bootstrap_thread.is_alive(), "Bootstrap worker leaked from lifecycle test")
                if runtime._scope:
                    runtime._scope.uninstall()
                sys.path[:] = before

    def launch(self, context):
        runtime.start(json.dumps(context.configuration))

    def finish(self):
        runtime._bootstrap_thread.join(timeout=3)
        self.assertFalse(runtime._bootstrap_thread.is_alive())
        return json.loads(runtime.status())

    def test_dependencies_overlap_starting_go_on_bootstrap_thread_without_early_ready(self):
        entered, release = threading.Event(), threading.Event()
        with self.bootstrap() as context:
            def probe():
                self.assertIs(threading.current_thread(), runtime._bootstrap_thread)
                self.assertEqual(context.state["state"], "starting")
                entered.set()
                self.assertTrue(release.wait(2), "Dependency barrier was not released")
                return {"ready": True, "failures": {}}
            context.probe.side_effect = probe
            self.launch(context)
            try:
                self.assertTrue(entered.wait(2), "Dependencies waited for Go instead of overlapping")
                self.assertFalse(json.loads(runtime.status())["ready"])
                self.assertEqual(context.imported, [])
                context.state.update(state="ready", phase="running", ready=True)
                self.assertFalse(json.loads(runtime.status())["ready"])
            finally:
                release.set()
            self.assertTrue(self.finish()["ready"])
            self.assertEqual(context.stages, ["payload_prepare", "go_start", "tool_dependencies"])
            self.assertEqual(context.imported, ["adminui.server", "webtools.server"])
            context.codec.assert_called_once()

    def test_go_failure_remains_specific_after_successful_dependency_checks(self):
        with self.bootstrap() as context:
            def probe():
                context.state.update(state="failed", phase="failed", ready=False,
                                     error={"code": "DATABASE_FAILED", "message": "The database could not open"})
                return {"ready": True, "failures": {}}
            context.probe.side_effect = probe
            self.launch(context)
            result = self.finish()
            self.assertFalse(result["ready"])
            self.assertIn("DATABASE_FAILED: The database could not open", result["error"])
            self.assertEqual(context.imported, [])
            context.native.go_stop.assert_called_once()

    def test_dependency_failure_stops_async_go_before_codec_or_server_binding(self):
        with self.bootstrap() as context:
            context.probe.return_value = {"ready": False, "failures": {"numpy": "Missing signed extension"}}
            self.launch(context)
            result = self.finish()
            self.assertIn("Bundled iOS dependencies failed", result["error"])
            self.assertIn("Missing signed extension", result["error"])
            self.assertFalse(result["ready"])
            context.codec.assert_not_called()
            self.assertEqual(context.imported, [])
            context.native.go_stop.assert_called_once()

    def test_codec_failure_stops_async_go_without_publishing_ready(self):
        with self.bootstrap() as context:
            context.codec.side_effect = RuntimeError("Signed HCA framework missing")
            self.launch(context)
            result = self.finish()
            self.assertIn("Signed HCA framework missing", result["error"])
            self.assertFalse(result["ready"])
            self.assertEqual(context.imported, [])
            context.native.go_stop.assert_called_once()

    def test_core_only_waits_for_go_and_never_loads_tool_dependencies(self):
        waiting = threading.Event()
        with self.bootstrap(core_only=True) as context:
            def status():
                if context.state["state"] == "starting": waiting.set()
                return json.dumps(context.state)
            context.native.go_status.side_effect = status
            self.launch(context)
            self.assertTrue(waiting.wait(2))
            self.assertFalse(json.loads(runtime.status())["ready"])
            context.state.update(state="ready", phase="running", ready=True)
            self.assertEqual(self.finish()["phase"], "core_ready")
            context.probe.assert_not_called(); context.codec.assert_not_called()
            self.assertEqual(context.imported, [])

    def test_dependency_work_consumes_original_startup_deadline_even_if_go_is_ready(self):
        clock = [1000.0]
        with self.bootstrap() as context, patch.object(runtime.time, "monotonic", side_effect=lambda: clock[0]):
            def probe():
                clock[0] += context.configuration["startup_timeout"]+1
                context.state.update(state="ready", phase="running", ready=True)
                return {"ready": True, "failures": {}}
            context.probe.side_effect = probe
            self.launch(context)
            result = self.finish()
            self.assertIn("Embedded Go server did not become ready", result["error"])
            self.assertFalse(result["ready"])
            self.assertEqual(context.imported, [])
            context.native.go_stop.assert_called_once()

    def test_cancel_during_dependency_work_stops_go_and_retry_waits_for_existing_worker(self):
        entered, release = threading.Event(), threading.Event()
        with self.bootstrap() as context:
            def probe():
                entered.set()
                self.assertTrue(release.wait(2))
                return {"ready": True, "failures": {}}
            context.probe.side_effect = probe
            self.launch(context)
            try:
                self.assertTrue(entered.wait(2))
                worker = runtime._bootstrap_thread
                runtime.stop()
                result = json.loads(runtime.start(json.dumps(context.configuration)))
                self.assertIn("previous startup is still finishing", result["error"])
                self.assertIs(runtime._bootstrap_thread, worker)
                self.assertEqual(context.native.go_start.call_count, 1)
            finally:
                release.set()
            result = self.finish()
            self.assertEqual(result["phase"], "cancelled")
            self.assertFalse(result["ready"])
            context.codec.assert_not_called()
            self.assertEqual(context.imported, [])
            self.assertEqual(context.state["state"], "stopping")


class RetryTests(unittest.TestCase):
    def test_stage_callback_is_absent_for_device_and_core_runtime(self):
        stages = []
        native = types.SimpleNamespace(probe_stage=stages.append)
        for simulator, core in ((False, False), (False, True), (True, True)):
            with self.subTest(simulator=simulator, core=core), patch.object(runtime, "_native", native), \
                 patch.object(runtime, "_state", {"simulator_probe_only": simulator, "core_only": core}):
                runtime._probe_stage("tls")
        self.assertEqual(stages, [])
        with patch.object(runtime, "_native", native), \
             patch.object(runtime, "_state", {"simulator_probe_only": True, "core_only": False}):
            runtime._probe_stage("tls")
            with self.assertRaisesRegex(ValueError, "Unknown Simulator diagnostic stage"):
                runtime._probe_stage("not-an-allowed-stage")
        self.assertEqual(stages, ["tls"])

    def test_failed_probe_does_not_emit_later_success_stages(self):
        from elichika_ios.probes import run
        stages = []
        result = run([], "a" * 64, Path("/unused-library"), progress=stages.append)
        self.assertFalse(result["ready"])
        self.assertEqual(stages, ["registries"])
        self.assertEqual(set(result["timings_seconds"]), {"registries"})
        self.assertIn("unavailable", result["error"])

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
        stages = []
        with patch.dict(sys.modules, modules):
            result = lifecycle(native, progress=stages.append)
        self.assertTrue(result["ready"], result)
        self.assertEqual(native.commands, ["stop", "config_read", "start"])
        self.assertEqual(result["generation_after"], 4)
        self.assertEqual(stages, ["go_stop", "config_read", "go_restart"])
        self.assertEqual(set(result["timings_seconds"]), set(stages))
        self.assertNotIn("private", json.dumps(result))

    def test_failed_maintenance_does_not_report_restart_or_completion(self):
        from elichika_ios.probes import lifecycle
        state = {"state": "ready", "ready": True}
        stages, calls = [], []
        native = types.SimpleNamespace(go_status=lambda: json.dumps(state))
        def stop():
            calls.append("stop")
            state.update(state="stopped", ready=False)
            return json.dumps(state)
        def command(raw):
            calls.append(json.loads(raw)["command"])
            return json.dumps({**state, "error": {"code": "READ_FAILED", "message": "Probe read failed"}})
        native.go_stop, native.go_command = stop, command
        modules = {"adminui": types.ModuleType("adminui"),
                   "adminui.serverctl": types.SimpleNamespace(_controller=types.SimpleNamespace(options={})),
                   "adminui.jobs": types.SimpleNamespace(MANAGER=types.SimpleNamespace(_active=0))}
        modules["adminui"].__path__ = []
        with patch.dict(sys.modules, modules):
            result = lifecycle(native, progress=stages.append)
        self.assertFalse(result["ready"])
        self.assertEqual(stages, ["go_stop", "config_read"])
        self.assertEqual(calls, ["stop", "config_read"])
        self.assertNotIn("restarted", result)
        self.assertIn("READ_FAILED", result["error"])

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
