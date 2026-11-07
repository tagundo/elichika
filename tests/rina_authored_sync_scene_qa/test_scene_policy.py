"""Test scientific policy boundaries, without claiming original-game execution."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("authored_sync_scene_policy", Path(__file__).with_name("audit_scenes.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def initial_swing(length=0.06):
    return {"isInitialized": True, "springLength": length,
            "currentTipPosition": [1.0, 2.0, 3.06], "previousTipPosition": [1.0, 2.0, 3.06],
            "childWorldPosition": [1.0, 2.0, 3.06],
            "transform": {"worldPosition": [1.0, 2.0, 3.0], "localRotation": [0.0, 0.0, 0.0, 1.0]}}


def model_values():
    return {name: {"localScale": list(scale), "worldScale": list(scale),
                   "localPosition": [0.0, 0.0, 0.0], "worldPosition": [1.0, 2.0, 3.0],
                   "localRotation": [0.0, 0.0, 0.0, 1.0], "worldRotation": [0.0, 0.0, 0.0, 1.0]}
            for name, scale in audit.TARGET.items()}


class AuthoredSyncPolicyTests(unittest.TestCase):
    def test_shared_aliases_alone_cannot_hide_different_actual_db_routes(self):
        keys = {"board": "private-board", "unmasked": "private-bare", "navi_board": "private-board", "mv_board": "private-board"}
        resources = {p: {"board": {"pack_name": p + "-one-board"}} for p in ("android", "ios")}
        for family in resources.values():
            family["navi_board"] = family["mv_board"] = family["board"]
        routes = [{"database": path, "suit_id": audit.SINGLE, "member_id": 209,
                   "base_model_asset_path": keys["board"], "main_and_view1_same_model": True,
                   "view_rows": [{"view_status": 1, "model_asset_path": keys["board"]},
                                 {"view_status": 2, "model_asset_path": keys["unmasked"]}]}
                  for path in ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db")]
        catalogs = [{"path": path, "platform": platform, "main_and_view1_same_asset_path": keys["board"],
                     "main_and_view1_same_pack": resources[platform]["board"]["pack_name"]}
                    for path, platform in audit.CATALOGS.items()]
        value = {"single_model_shared_board": True, "asset_keys": keys, "resources": resources,
                 "validation": {"main_view1_shared_board_verified_all_catalogs": True,
                                "actual_master_routes": routes, "catalogs": catalogs}}
        audit.shared_board_routes(value)
        for kind in ("master", "catalog", "missing-catalog"):
            wrong = copy.deepcopy(value)
            if kind == "master":
                wrong["validation"]["actual_master_routes"][0]["view_rows"][0]["model_asset_path"] = "different-board"
            elif kind == "catalog":
                wrong["validation"]["catalogs"][0]["main_and_view1_same_pack"] = "different-pack"
            else:
                wrong["validation"]["catalogs"].pop()
            with self.subTest(kind=kind), self.assertRaises(audit.Incomplete):
                audit.shared_board_routes(wrong)

    def test_changed_cache_is_accepted_when_it_matches_actual_d_size(self):
        self.assertAlmostEqual(audit.consistent_swing(initial_swing()), 0.06)
        # Retaining the old smaller length with new world endpoints is wrong;
        # equality to a historical baseline is not the acceptance criterion.
        with self.assertRaisesRegex(audit.Incomplete, "ACTUAL_WORLD_DISTANCE"):
            audit.consistent_swing(initial_swing(length=0.04))

    def test_invalid_initial_physics_is_rejected(self):
        for mutate in (
            lambda v: v.update(isInitialized=False),
            lambda v: v.update(springLength=float("nan")),
            lambda v: v.update(currentTipPosition=[1.0, 2.0, 3.0]),
            lambda v: v["transform"].update(localRotation=[0.0, 0.0, 0.0, 0.0]),
        ):
            value = initial_swing()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(audit.Incomplete):
                audit.consistent_swing(value)

    def test_absolute_d_is_distinguished_from_squared_scale(self):
        values = model_values()
        self.assertTrue(audit.scales_match(values, audit.TARGET))
        for name in values:
            values[name]["localScale"] = [v * v for v in audit.TARGET[name]]
        self.assertFalse(audit.scales_match(values, audit.TARGET))

    def test_camera_or_quaternion_sign_does_not_prove_bone_motion(self):
        first = model_values()
        last = copy.deepcopy(first)
        self.assertFalse(audit.moved_world(first, last))
        for value in last.values():
            value["worldRotation"] = [0.0, 0.0, 0.0, -1.0]
        self.assertFalse(audit.moved_world(first, last))
        last["HipsSize"]["worldPosition"][1] += 0.002
        self.assertTrue(audit.moved_world(first, last))

    def test_nonfinite_or_invalid_rotation_fails_before_motion_claim(self):
        for field, value in (("worldPosition", [1.0, float("nan"), 3.0]),
                             ("localRotation", [0.0, 0.0, 0.0, 0.0])):
            sample = model_values()
            sample["BreastSize"][field] = value
            with self.subTest(field=field), self.assertRaises(audit.Incomplete):
                audit.valid_trs(sample)

    def test_preview_requires_its_own_typed_scene_count(self):
        counts = {name: 0 for name in ("LLAS.Scene.EntryPoint.LiveMvScene", "LLAS.Scene.Live.Mv.LiveMvCoreScene",
                                      "LLAS.Scene.Live.Mv.LiveMvManager")}
        counts.update({name: 1 for name in ("LLAS.Scene.EntryPoint.HomeScene", "LLAS.Scene.Home.HomeMenu",
                                           "LLAS.Scene.Home.HomeMenuButtonsController")})
        def tree():
            return {"semanticState": {"sceneContexts": [{"className": name, "activeOwners": count, "status": "COUNTED"}
                                                        for name, count in counts.items()]}}
        self.assertEqual(audit.logical_ui_kind(tree()), "unverified")
        counts["LLAS.Scene.EntryPoint.CostumePreviewScene"] = 0
        self.assertEqual(audit.logical_ui_kind(tree()), "navi")
        counts["LLAS.Scene.EntryPoint.CostumePreviewScene"] = 1
        self.assertEqual(audit.logical_ui_kind(tree()), "preview")
        counts["LLAS.Scene.EntryPoint.CostumePreviewScene"] = 2
        self.assertEqual(audit.logical_ui_kind(tree()), "other_or_ambiguous")


if __name__ == "__main__":
    unittest.main()
