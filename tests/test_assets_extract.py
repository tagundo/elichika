"""Costume extraction naming regressions, using disposable SQLite DBs and packs.

Run: python3 -m unittest discover -s tests -p test_assets_extract.py -v
"""
import csv
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from adminui.jobs import Job
from adminui.tools import assets_extract as extract
import llas_asset_extractor as extractor


class CostumeOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        db_dir = self.root / "assets" / "db" / "gl"
        db_dir.mkdir(parents=True)
        self.models = {"model/ch0102_co0001": "Riko", "model/ch0107_co0001": "Hanamaru"}
        with sqlite3.connect(db_dir / "masterdata.db") as md:
            md.execute("CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, "
                       "name TEXT, model_asset_path TEXT, thumbnail_image_asset_path TEXT, "
                       "display_order INTEGER)")
            for cid in (102, 107):
                model = f"model/ch{cid:04}_co0001"
                md.execute("INSERT INTO m_suit VALUES (?, ?, ?, ?, ?, ?)",
                           (cid, cid, f"k.suit_{cid}", model, model, cid))
        with sqlite3.connect(db_dir / "dictionary_en_k.db") as dc:
            dc.execute("CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)")
            dc.executemany("INSERT INTO m_dictionary VALUES (?, ?)",
                           [("suit_102", "Shared Song"), ("suit_107", "Shared Song")])

        # Packs are encrypted with the real extractor's symmetric XOR routine;
        # extraction below exercises the normal file naming and manifest path.
        packs = self.root / "packs"
        packs.mkdir()
        self.payload = b"UnityFS\x00synthetic costume bundle"
        with sqlite3.connect(db_dir / "asset_a_en.db") as asset:
            asset.execute("CREATE TABLE member_model (asset_path TEXT, pack_name TEXT, "
                          "head INTEGER, size INTEGER, key1 INTEGER, key2 INTEGER)")
            for i, model in enumerate(self.models):
                pack = f"costume_pack_{i}"
                encrypted = bytearray(self.payload)
                extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, 7, 11)
                (packs / pack).write_bytes(encrypted)
                asset.execute("INSERT INTO member_model VALUES (?, ?, 0, ?, 7, 11)",
                              (model, pack, len(encrypted)))

        old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old_cwd)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "sukusta"),
                                "SIFAS_LANG": "en"}).start()
        patch.object(extractor, "COPIED_PACKS_DIR", str(packs)).start()
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "build_pack_roots", return_value=[]).start()

    def assert_outputs(self, expected_models):
        output = self.root / "sukusta" / "extracted" / "3d_model"
        expected = {
            f"{self.models[model]}_{model.split('/')[-1]}_Shared Song.unity"
            for model in expected_models
        }
        self.assertEqual({p.name for p in output.iterdir()}, expected)
        for p in output.iterdir():
            self.assertEqual(p.read_bytes(), self.payload)

    def test_search_pick_uses_costume_owner_instead_of_character_filter(self):
        model = "model/ch0102_co0001"
        extract.run_extract(Job("single", "extract_assets"), {
            "character": "101", "search": "Shared Song", "costume": model,
            "cdn": False, "recolour_variant": False,
        })
        self.assert_outputs([model])

    def test_multiple_search_picks_use_each_costume_owner(self):
        extract.run_extract(Job("multiple", "extract_assets"), {
            "character": "101", "search": "Shared Song", "costume": list(self.models),
            "cdn": False, "recolour_variant": False,
        })
        self.assert_outputs(self.models)

    def test_extract_all_matches_uses_each_costume_owner(self):
        extract.run_extract(Job("batch", "extract_assets"), {
            "character": "101", "search": "Shared Song", "batch": True,
            "cdn": False, "recolour_variant": False,
        })
        self.assert_outputs(self.models)

    def test_model_owner_is_recovered_with_empty_character_filter(self):
        cid, label = extract._resolve_cid_and_label(
            extractor, ".", "model/ch0107_co0001", "")
        self.assertEqual(cid, "107")
        self.assertTrue(label.startswith("Hanamaru_"), label)

    def test_unknown_model_retains_character_fallback(self):
        cid, label = extract._resolve_cid_and_label(extractor, ".", "unknown/model", "101")
        self.assertEqual((cid, label), ("101", "Chika"))

    def add_shared_model_clone(self):
        # Matches costume_clone.clone_costume(): a new member/title, but the
        # donor's existing model path and thumbnail are reused.
        with sqlite3.connect("assets/db/gl/masterdata.db") as md:
            md.execute("INSERT INTO m_suit VALUES (999,101,'k.suit_102_cloned',"
                       "'model/ch0102_co0001','model/ch0102_co0001',999)")
        with sqlite3.connect("assets/db/gl/dictionary_en_k.db") as dc:
            dc.execute("INSERT INTO m_dictionary VALUES ('suit_102_cloned','Shared Song clone')")

    def test_options_keep_distinct_suit_ids_when_models_are_shared(self):
        self.add_shared_model_clone()
        options = extract.costume_options({"character": "107", "search": "Shared Song", "lang": "en"})
        values = {option["value"] for option in options}
        self.assertEqual(values, {"suit:102", "suit:107", "suit:999"})
        shared = [option for option in options if option["model_path"] == "model/ch0102_co0001"]
        self.assertEqual({option["value"] for option in shared}, {"suit:102", "suit:999"})
        self.assertEqual(extract.costume_options({"character": "101", "lang": "en"}), [
            {"value": "suit:999", "label": "Shared Song clone", "model_path": "model/ch0102_co0001"}
        ])

    def test_search_selected_clone_uses_clone_owner_and_title(self):
        self.add_shared_model_clone()
        options = extract.costume_options({"character": "107", "search": "Chika", "lang": "en"})
        self.assertEqual(len(options), 1)
        self.assertTrue(options[0]["label"].startswith("Chika Takami —"))
        extract.run_extract(Job("clone", "extract_assets"), {
            "character": "107", "search": "Chika", "costume": options[0]["value"],
            "cdn": False, "recolour_variant": False,
        })
        output = self.root / "sukusta/extracted"
        files = list((output / "3d_model").iterdir())
        self.assertEqual([p.name for p in files], ["Chika_ch0102_co0001_Shared Song clone.unity"])
        self.assertEqual(files[0].read_bytes(), self.payload)
        with (output / "_extract_manifest.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["asset_path"], "model/ch0102_co0001")
        self.assertEqual(rows[0]["status"], "OK")

    def test_selected_donor_and_clone_both_extract_in_one_job(self):
        self.add_shared_model_clone()
        result = extract.run_extract(Job("shared-model", "extract_assets"), {
            "character": "107", "costume": ["suit:102", "suit:999"],
            "cdn": False, "recolour_variant": False,
        })
        files = list((self.root / "sukusta/extracted/3d_model").iterdir())
        self.assertEqual({p.name for p in files}, {
            "Riko_ch0102_co0001_Shared Song.unity", "Chika_ch0102_co0001_Shared Song clone.unity"})
        self.assertIn("2/2", result)
        self.assertTrue(all(p.read_bytes() == self.payload for p in files))

    def test_batch_does_not_collapse_clone_and_donor_sharing_model(self):
        self.add_shared_model_clone()
        result = extract.run_extract(Job("clone-batch", "extract_assets"), {
            "character": "107", "search": "Shared Song", "batch": True,
            "cdn": False, "recolour_variant": False,
        })
        files = list((self.root / "sukusta/extracted/3d_model").iterdir())
        self.assertEqual({p.name for p in files}, {
            "Riko_ch0102_co0001_Shared Song.unity", "Hanamaru_ch0107_co0001_Shared Song.unity",
            "Chika_ch0102_co0001_Shared Song clone.unity"})
        self.assertIn("3/3", result)
        self.assertTrue(all(p.read_bytes() == self.payload for p in files))

    def test_stale_invalid_and_model_less_suit_selections_fail_before_output(self):
        with sqlite3.connect("assets/db/gl/masterdata.db") as md:
            md.execute("INSERT INTO m_suit VALUES (1000,101,'k.empty',NULL,NULL,1000)")
        for selection, message in (("suit:99999", "no longer exists"),
                                   ("suit:bad", "Invalid costume selection"),
                                   ("suit:1000", "no model asset")):
            with self.subTest(selection=selection), self.assertRaisesRegex(ValueError, message):
                extract.run_extract(Job(selection, "extract_assets"), {
                    "character": "101", "costume": selection, "cdn": False,
                })
        self.assertFalse((self.root / "sukusta/extracted").exists())


if __name__ == "__main__":
    unittest.main()
