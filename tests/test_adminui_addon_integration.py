"""Tiny shared-schema and actual Mac authorization-wrapper streaming contracts."""
import ast
import contextlib
from email.message import Message
from http.cookies import SimpleCookie
import io
from pathlib import Path
import secrets
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def addon_function(path):
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_addon")
    values = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), values)
    return values["_addon"]


def mac_wrapper():
    path = ROOT / "macos/runtime/elichika_macos.py"
    nodes = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef) and node.name in ("_host_matches", "_matches", "secure_ui_handler")]
    values = {"secrets": secrets, "SimpleCookie": SimpleCookie, "COOKIE_NAME": "fixture-session", "urlsplit": urlsplit,
              "_json": lambda handler, body, status=200: setattr(handler, "reply", (status, body))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), values)
    return values["secure_ui_handler"]


class BoundedReader:
    def __init__(self, remaining):
        self.remaining, self.calls = remaining, []

    def read(self, size=-1):
        raise AssertionError("The native wrapper must not buffer an upload body")

    def read1(self, size=-1):
        if not 0 < size <= 64 * 1024:
            raise AssertionError("File body must be streamed in at most64KiB chunks")
        self.calls.append(size)
        count = min(size, self.remaining)
        self.remaining -= count
        return b"a" * count


class NativeWrapperTests(unittest.TestCase):
    def handler(self, path, length=2 * 1024 * 1024):
        class StreamBase:
            def do_POST(self):
                self.streamed = 0
                while block := self.rfile.read1(64 * 1024):
                    self.streamed += len(block)
        runtime = SimpleNamespace(ui_token="fixture-token", _lock=threading.Lock(), _console_job=None)
        handler = mac_wrapper()(StreamBase, runtime)()
        handler.server = SimpleNamespace(server_port=18770)
        handler.path = path
        handler.headers = Message()
        for key, value in (("Host", "127.0.0.1:18770"), ("Origin", "http://127.0.0.1:18770"),
                           ("Content-Length", str(length)), ("Content-Type", "application/octet-stream"),
                           ("X-Elichika-Session", "fixture-token")):
            handler.headers[key] = value
        handler.rfile = BoundedReader(length)
        return handler

    def test_exact_six_raw_routes_pass_above_one_mib_without_body_buffering(self):
        for tool in ("costume", "live", "card", "tower", "camera", "db"):
            handler = self.handler("/api/addon-files/install_" + tool)
            handler.do_POST()
            self.assertEqual(handler.streamed, 2 * 1024 * 1024)
            self.assertTrue(all(size <= 64 * 1024 for size in handler.rfile.calls))

    def test_unknown_routes_and_oversize_ticket_metadata_keep_small_limits(self):
        for path, length in (("/api/run/install_live", 2 * 1024 * 1024),
                             ("/api/addon-files/restore", 2 * 1024 * 1024),
                             ("/api/addon-files/install_live/not-a-route", 2 * 1024 * 1024),
                             ("/api/addon-files/install_live/batch", 65537),
                             ("/api/addon-files/install_live", 512 * 1024 * 1024 + 1)):
            handler = self.handler(path, length); handler.do_POST()
            self.assertEqual(handler.reply[0], 413)
            self.assertEqual(handler.rfile.calls, [])

    def test_foreign_origin_missing_capability_and_chunked_body_never_reach_reader(self):
        for header, value, status in (("Origin", "https://external.invalid", 403),
                                      ("X-Elichika-Session", "wrong-token", 401),
                                      ("Transfer-Encoding", "chunked", 413)):
            handler = self.handler("/api/addon-files/install_live")
            if header in handler.headers: del handler.headers[header]
            handler.headers[header] = value
            handler.do_POST()
            self.assertEqual(handler.reply[0], status)
            self.assertEqual(handler.rfile.calls, [])


class SharedSchemaTests(unittest.TestCase):
    def test_original_single_multi_defaults_and_paths_are_preserved_for_all_six(self):
        current = ROOT / "adminui/tools/registry.py"
        before = ROOT.parent / "before/adminui/tools/registry.py"
        old, new = addon_function(before), addon_function(current)
        for folder, multi in (("suit", True), ("live", False), ("card", False), ("tower", False), ("livetimeline", True), ("sql", False)):
            result = new(folder, multi)
            metadata = result.pop("file_add")
            self.assertEqual(result, old(folder, multi))
            self.assertEqual(metadata["extensions"], ["sql" if folder == "sql" else "zip"])
            self.assertEqual(metadata["max_files"], 128)
            self.assertEqual(metadata["max_bytes"], 512 * 1024 * 1024)
            self.assertEqual(metadata["max_total_bytes"], 8 * 1024 * 1024 * 1024)

    def test_buttons_and_manual_override_hint_have_ko_ja_translations(self):
        path = ROOT / "adminui/i18n.py"
        node = next(node for node in ast.parse(path.read_text()).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_ADDON_FILE_STRINGS" for target in node.targets))
        table = ast.literal_eval(node.value)
        self.assertEqual(table["Add files"], ["파일 추가", "ファイル追加"])
        self.assertIn("선택한 {count}개 파일만", table["Using only the {count} added files."][0])
        self.assertTrue(all("{count}" in value for value in table["Using only the {count} added files."]))

    def test_actual_batch_runner_consumes_only_imported_names_with_one_lease_and_one_backup(self):
        from adminui import addon_files
        from adminui.tools import installers
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); drop, legacy = root / 'addons', root / 'old-default'
            legacy.mkdir(); (legacy / 'existing.zip').write_bytes(b'leave default untouched')
            records, choices = [], []
            def installed(job, key, spec, chosen, do_backup, **kwargs):
                records.append((chosen, Path(installers._locate(key, chosen)).read_bytes(), do_backup))
                return True
            server = SimpleNamespace(restart_allowed=False, restart_pending=False, restarted=False)
            job = SimpleNamespace(log=lambda *_: None, progress=lambda *_: None, should_stop=lambda: False)
            with patch.object(installers, '_candidate_dirs', return_value=[str(drop), str(legacy)]):
                for name, content in [('one.zip', b'first chosen bytes'), ('two.zip', b'second chosen bytes')]:
                    choices.append(addon_files.store_upload('live', name, io.BytesIO(content), len(content))['file']['value'])
                with patch.object(installers, '_install_one', side_effect=installed), patch.object(installers, 'installation_server', return_value=contextlib.nullcontext(server)) as lease:
                    result = installers.run_live(job, {'addon': choices, 'backup': True, 'stop_server': False})
                    lease.assert_called_once()
            self.assertIn('installed 2/2', result)
            self.assertEqual(records, [('one.zip', b'first chosen bytes', True), ('two.zip', b'second chosen bytes', False)])
            self.assertEqual((legacy / 'existing.zip').read_bytes(), b'leave default untouched')


if __name__ == "__main__": unittest.main()
