"""Real source-bound thumbnail staging and the existing install adapter.

Only the final DB installer/process controller are replaced. Shared plan,
receipt verification, PNG validation and ZIP surgery execute unchanged. Actual
WebGL rendering is covered by the paired browser integration check.
"""
import ast
import base64
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "modtools")]
from PIL import Image
from adminui import i18n
from adminui.tools import costume_thumbnail, installers, registry
from webtools.core import viewer_thumbnails


class Job:
    def __init__(self):
        self.logs, self.progresses, self.cancelled = [], [], False
    def log(self, line): self.logs.append(line)
    def progress(self, done, total): self.progresses.append((done, total))
    def should_stop(self): return self.cancelled


class InstallerThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="installer-thumbnail-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.library = self.root / "library"
        (self.library / "suit").mkdir(parents=True)
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        environment.start(); self.addCleanup(environment.stop)
        jail = patch("webtools.filebrowser.is_within_allowed", lambda value: Path(value).resolve().is_relative_to(self.root))
        jail.start(); self.addCleanup(jail.stop)
        self.addCleanup(viewer_thumbnails._PLANS.clear)
        self.body = (ROOT / "modtools/tests/fixtures/viewer_persistence.unity").read_bytes()
        self.png = self.image("red")
        self.job = Job()
        self.source = self.package("first.zip")
        self.original = self.source.read_bytes()
        self.params = {"addon": [self.source.name], "auto_thumbnail": True, "thumbnail_fit_full": False,
                       "backup": False, "stop_server": True}
        self.events = []

    @staticmethod
    def image(color):
        stream = io.BytesIO(); Image.new("RGBA", (256, 256), color).save(stream, format="PNG")
        return stream.getvalue()

    def package(self, name, *, dynamic=False):
        path = self.library / "suit" / name
        manifest = "chara_id = 6\ncostume_file = 'body.unity'\nthumbnail_file = 'old.png'\n"
        if dynamic: manifest += "__import__('pathlib').Path(" + repr(str(self.root / "SHOULD_NOT_EXIST")) + ").touch()\n"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("modinstall.txt", manifest)
            archive.writestr("body.unity", self.body)
            archive.writestr("old.png", self.image("blue"))
            archive.writestr("opaque.bin", b"keep all settings/assets unchanged")
        return path

    def render(self, params=None, *, only_first=False):
        params = dict(params or self.params)
        plan = costume_thumbnail.plan(params)
        for item in plan["items"][:1] if only_first else plan["items"]:
            viewer_thumbnails.store({"token": plan["token"], "item_id": item["id"],
                "cache_key": item["cacheKey"], "profile_digest": plan["profileDigest"],
                "png": "data:image/png;base64," + base64.b64encode(self.png).decode(),
                "render": {"quality": {"enabled": True, "ready": True}, "subjectPixels": 400, "triangles": 8}})
        params["thumbnail_plan"] = plan["token"]
        return params, plan

    @contextmanager
    def server(self, *args, **kwargs):
        self.events.append("stop")
        yield SimpleNamespace(restart_allowed=False, restart_pending=False, restarted=False)
        self.events.append("finish")

    def run_install(self, params, callback=None):
        with patch.object(installers, "installation_server", self.server), \
                patch.object(installers, "_install_one", side_effect=callback or (lambda *a, **k: True)) as install:
            result = installers.run_costume(self.job, params)
        return result, install

    def test_form_defaults_and_all_labels_are_localized(self):
        tool = registry.get_tool("install_costume")
        fields = {row["name"]: row for row in tool["fields"]}
        self.assertIs(fields["auto_thumbnail"]["default"], True)
        self.assertIs(fields["thumbnail_fit_full"]["default"], False)
        for language in ("ko", "ja"):
            strings = i18n.all_strings(language)
            for key in ("auto_thumbnail", "thumbnail_fit_full"):
                for text in (fields[key]["label"], fields[key]["help"]):
                    self.assertNotEqual(strings.get(text), text)
                    self.assertTrue(strings.get(text))

    def test_plan_uses_shared_hq_no_rim_upper_body_member_template(self):
        params, plan = self.render()
        self.assertEqual(plan["quality"]["subject"], "head-and-upper-body-v1")
        self.assertIs(plan["quality"]["highQuality"], True)
        self.assertIs(plan["quality"]["rimlight"], False)
        self.assertEqual(plan["items"][0]["characterId"], 6)
        self.assertEqual(plan["profileUrl"], "/static/thumbnail-sdk/profile.json")
        full = costume_thumbnail.plan(dict(self.params, thumbnail_fit_full=True))
        self.assertEqual(full["quality"]["subject"], "full-character-v1")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_install_consumes_exact_new_png_zip_and_preserves_original_assets(self):
        params, plan = self.render()
        staged_paths = []
        def install(job, key, spec, chosen, do_backup, **bound):
            self.assertEqual(self.events, ["stop"])
            target = Path(bound["source_path"]); staged_paths.append(target)
            self.assertNotEqual(target, self.source)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), bound["expected_sha256"])
            with zipfile.ZipFile(target) as archive, zipfile.ZipFile(self.source) as original:
                values = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(archive.read("modinstall.txt")).body}
                self.assertEqual(archive.read(values["thumbnail_file"]), self.png)
                for name in ("body.unity", "old.png", "opaque.bin"):
                    self.assertEqual(archive.read(name), original.read(name))
            return True
        summary, called = self.run_install(params, install)
        self.assertEqual(called.call_count, 1)
        self.assertIn("installed 1/1", summary)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(all(not p.exists() for p in staged_paths))
        self.assertTrue(any("COSTUME_INSTALL_THUMBNAIL" in line for line in self.job.logs))

    def test_off_preserves_original_zip_flow_without_any_renderer(self):
        with patch.object(costume_thumbnail, "install_inputs", side_effect=AssertionError("renderer must not run")):
            _, called = self.run_install(dict(self.params, auto_thumbnail=False))
        self.assertEqual(called.call_args.args[3], self.source.name)
        self.assertNotIn("source_path", called.call_args.kwargs)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_missing_render_receipt_stops_before_server_or_installer(self):
        plan = costume_thumbnail.plan(self.params)
        with self.assertRaisesRegex(ValueError, "first.zip.*completed automatic thumbnail"):
            self.run_install(dict(self.params, thumbnail_plan=plan["token"]))
        self.assertEqual(self.events, [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_changed_zip_cannot_reuse_rendered_thumbnail(self):
        params, _ = self.render()
        with zipfile.ZipFile(self.source, "a") as archive: archive.writestr("changed.txt", "new bytes")
        with self.assertRaisesRegex(ValueError, "changed after preparing"):
            self.run_install(params)
        self.assertEqual(self.events, [])

    def test_changed_fit_or_selection_cannot_reuse_plan(self):
        params, _ = self.render()
        second = self.package("second.zip")
        for changed in ({"thumbnail_fit_full": True}, {"addon": [second.name]}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "settings changed"):
                self.run_install(dict(params, **changed))
        self.assertEqual(self.events, [])

    def test_incomplete_batch_is_rejected_before_any_install(self):
        second = self.package("second.zip")
        params, _ = self.render(dict(self.params, addon=[self.source.name, second.name]), only_first=True)
        with self.assertRaisesRegex(ValueError, "second.zip.*completed automatic thumbnail"):
            self.run_install(params)
        self.assertEqual(self.events, [])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(any((self.library / ".installer-thumbnails").iterdir()))

    def test_cancelled_preparation_starts_no_server_or_install(self):
        params, _ = self.render(); self.job.cancelled = True
        summary, called = self.run_install(params)
        self.assertIn("cancelled", summary)
        called.assert_not_called(); self.assertEqual(self.events, [])

    def test_cancel_during_final_digest_pass_never_stops_server(self):
        params, _ = self.render()
        original_hash = installers._file_sha256
        def cancel_during_hash(path):
            value = original_hash(path)
            if Path(path) == self.source:
                self.job.cancelled = True
            return value
        with patch.object(installers, "_file_sha256", side_effect=cancel_during_hash):
            summary, called = self.run_install(params)
        self.assertIn("cancelled", summary)
        called.assert_not_called()
        self.assertEqual(self.events, [])

    def test_earlier_source_or_staging_changed_during_later_preparation_never_stops_server(self):
        from webtools.core import mod_thumbnail_replace
        second = self.package("second.zip")
        original_replace = mod_thumbnail_replace.replace
        for target in ("source", "staging"):
            with self.subTest(target=target):
                self.source.write_bytes(self.original)
                params, _ = self.render(dict(self.params, addon=[self.source.name, second.name]))
                earlier = {}
                def replace(path, *args, **kwargs):
                    result = original_replace(path, *args, **kwargs)
                    if Path(path) == self.source:
                        earlier.update(result)
                    else:
                        changed = self.source if target == "source" else Path(earlier["output_path"])
                        with changed.open("ab") as handle:
                            handle.write(b"changed while a later ZIP was preparing")
                    return result
                with patch.object(mod_thumbnail_replace, "replace", side_effect=replace), \
                        self.assertRaisesRegex(ValueError, "changed.*first.zip"):
                    self.run_install(params)
                self.assertEqual(self.events, [])

    def test_dynamic_zip_reports_filename_without_executing_manifest(self):
        source = self.package("dynamic.zip", dynamic=True)
        with self.assertRaisesRegex(ValueError, "dynamic.zip.*not executed"):
            costume_thumbnail.plan(dict(self.params, addon=[source.name]))
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_input_names_are_bounded_installer_choices(self):
        for name in ("../outside.zip", "/tmp/outside.zip", "folder\\outside.zip", "patch.sql"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "installer list"):
                costume_thumbnail.plan(dict(self.params, addon=[name]))


if __name__ == "__main__":
    unittest.main()
