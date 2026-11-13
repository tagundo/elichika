import copy
import unittest

from feature_client_smoke import CLIENT, semantic_match, successful_game_requests, title_start_target, title_start_visible, unity_surface_bounds


class SemanticTargetTests(unittest.TestCase):
    def test_custom_components_share_one_actual_language_button(self):
        target = {"name": "EnglishButton", "path": "PopupLanguageSetting/GridButtons/EnglishButton", "text": "",
                  "bounds": {"left": 241, "top": 278, "right": 632, "bottom": 348}, "center": {"x": 437, "y": 313}}
        nodes = [{**copy.deepcopy(target), "id": str(index), "type": component} for index, component in enumerate(
            ("ProductButton", "ButtonConcept", "ButtonTransition", "ProductButtonSound"))]
        picked, expression = semantic_match(nodes, [r"^English$"])
        self.assertEqual(picked["id"], "0")
        self.assertEqual(expression, r"^English$")

    def test_separate_controls_remain_ambiguous(self):
        first = {"name": "OKButton", "path": "DialogOne/OKButton", "center": {"x": 100, "y": 100}}
        second = {**first, "path": "DialogTwo/OKButton", "center": {"x": 200, "y": 100}}
        self.assertEqual(semantic_match([first, second], [r"^OK$"]), (None, None))

    def test_same_path_different_geometry_is_not_collapsed(self):
        first = {"name": "EnglishButton", "path": "Popup/EnglishButton", "center": {"x": 100, "y": 100}}
        second = {**first, "center": {"x": 200, "y": 100}}
        self.assertEqual(semantic_match([first, second], [r"^English$"]), (None, None))

    def test_pascal_case_button_name_keeps_its_semantic_words(self):
        target = {"name": "UnitedStatesButton", "path": "Countries/UnitedStatesButton"}
        self.assertEqual(semantic_match([target], [r"^United States$"])[0], target)
        self.assertEqual(semantic_match([{**target, "name": "Button_OK"}], [r"^OK$"])[0]["name"], "Button_OK")

    def test_api34_content_root_matches_the_live_unity_dimensions(self):
        bounds = {"left": 0, "top": 0, "right": 1280, "bottom": 720}
        nodes = [{"package": CLIENT, "class": "android.widget.FrameLayout", "name": "android:id/content", "bounds": bounds},
                 {"package": CLIENT, "class": "android.view.View", "bounds": bounds}]
        self.assertEqual(unity_surface_bounds(nodes, {"width": 1280, "height": 720}), bounds)

    def test_content_root_requires_the_actual_client_package_and_exact_geometry(self):
        node = {"package": CLIENT, "class": "android.widget.FrameLayout", "name": "android:id/content",
                "bounds": {"left": 0, "top": 0, "right": 1280, "bottom": 720}}
        for nodes, screen in (([{**node, "package": "another.app"}], {"width": 1280, "height": 720}),
                              ([node], {"width": 720, "height": 1280}), ([node, node], {"width": 1280, "height": 720})):
            with self.assertRaises(ValueError):
                unity_surface_bounds(nodes, screen)

    def test_a_real_surface_view_must_match_even_if_the_content_root_is_larger(self):
        nodes = [{"package": CLIENT, "class": "android.view.SurfaceView", "bounds": {"left": 20, "top": 0, "right": 1280, "bottom": 720}},
                 {"package": CLIENT, "name": "android:id/content", "bounds": {"left": 0, "top": 0, "right": 1280, "bottom": 720}}]
        with self.assertRaises(ValueError):
            unity_surface_bounds(nodes, {"width": 1280, "height": 720})

    def test_gin_quoted_successful_post_paths_are_actual_request_proof(self):
        log = b'[GIN] 2026/11/09 - 10:32:04 | 200 | 51.489us | 127.0.0.1 | POST "/login/login"\n[GIN] 2026/11/09 - 10:32:05 | 200 | 3ms | 127.0.0.1 | POST "/bootstrap/fetchBootstrap?request_id=synthetic"\n'
        result = successful_game_requests(log)
        self.assertTrue(result["/login/login"])
        self.assertTrue(result["/bootstrap/fetchBootstrap"])
        self.assertFalse(result["/liveMv/start"])

    def test_failed_login_gets_diagnostics_and_prefix_paths_are_not_success(self):
        log = b'POST "/login/startup"\n[GIN-debug] POST "/login/startup"\n[GIN] now | 401 | 1ms | 127.0.0.1 | POST "/login/login"\n[GIN] now | 200 | 1ms | 127.0.0.1 | GET "/bootstrap/fetchBootstrap"\n[GIN] now | 200 | 1ms | 127.0.0.1 | POST "/liveMv/startAnother"\n'
        self.assertFalse(any(successful_game_requests(log).values()))

    def test_title_start_needs_the_actual_scene_and_visible_start_caption(self):
        text = {"kind": "text", "active": True, "visible": True, "text": "Tap to Start"}
        self.assertTrue(title_start_visible({"screen": {"scene": "Title"}, "nodes": [text]}))
        self.assertFalse(title_start_visible({"screen": {"scene": "Home"}, "nodes": [text]}))
        self.assertFalse(title_start_visible({"screen": {"scene": "Title"}, "nodes": [{**text, "visible": False}]}))
        self.assertFalse(title_start_visible({"screen": {"scene": "Title"}, "nodes": [{**text, "text": "Loading"}]}))

    def test_title_caption_point_must_hit_the_unique_start_button(self):
        caption = {"kind": "text", "name": "TapTextView", "text": "Tap to Start", "active": True, "visible": True,
                   "center": {"x": 640, "y": 610}, "hit": {"available": True, "firstName": "ScreenButton", "firstPath": "EntryPoint/Canvas/ScreenButton"}}
        button = {"kind": "button", "name": "ScreenButton", "path": "EntryPoint/Canvas/ScreenButton", "active": True, "visible": True,
                  "bounds": {"left": 0, "top": 0, "right": 1280, "bottom": 720}, "hit": {"hittable": False, "firstName": "BackKeyHandler"}}
        tree = {"screen": {"scene": "Title", "width": 1280, "height": 720}, "nodes": [caption, button]}
        self.assertEqual(title_start_target(tree)["center"], {"x": 640, "y": 610})
        for changed in [{**caption, "hit": {"available": True, "firstName": "BackKeyHandler", "firstPath": "Other"}},
                        {**caption, "center": {"x": 1281, "y": 610}}]:
            self.assertIsNone(title_start_target({**tree, "nodes": [changed, button]}))


class FeatureEvidenceTests(unittest.TestCase):
    def test_actual_prior_terms_modal_resolves_only_hittable_positive_button(self):
        import json
        from pathlib import Path
        from feature_client_smoke import terms_accept_target
        tree = json.loads((Path(__file__).parent / "fixtures/prior-terms-modal.json").read_text())
        target = terms_accept_target(tree)
        self.assertEqual(target["name"], "ButtonPositiveM")
        self.assertTrue(target["hit"]["hittable"])
        self.assertEqual(tree["provenance"]["run_id"], 42607675623)
        for change in ("caption_hidden", "wrong_hit", "wrong_scene", "wrong_context"):
            altered = copy.deepcopy(tree)
            if change == "caption_hidden":
                for node in altered["nodes"]:
                    if node.get("text") == "Agree": node["visible"] = False
            elif change == "wrong_hit":
                for node in altered["nodes"]:
                    if node.get("text") == "Agree": node["hit"]["firstPath"] = "Unrelated/Positive"
            elif change == "wrong_scene": altered["screen"]["scene"] = "Shop"
            else:
                for node in altered["nodes"]: node["path"] = node["path"].replace("PopupTermsGL", "OtherModal")
            self.assertIsNone(terms_accept_target(altered), change)

    def test_configuration_and_intro_flag_alone_cannot_pass_behavior(self):
        from feature_client_smoke import feature_observations
        tree = {"screen": {"width": 720, "height": 1280}, "features": {"native": {
            "bridgeLoaded": True, "gameLoaded": True, "requestedOrientation": 1,
            "config": {"magic": "SFOVRW22", "version": 1, "size": 32, "writable": True,
                       "executable": False, "min": 2., "max": 2., "orientation": 1, "fastIntro": 1}}}}
        checks = feature_observations(tree, "portrait", 2.)
        self.assertEqual(checks, {"native_load": "PASS", "portrait": "PASS"})
        tree["features"]["aspectCorrectors"] = [{"active": True, "mode": 0, "correction": 2.}]
        self.assertNotIn("fov_actual", feature_observations(tree, "portrait", 2.))
        tree["features"]["aspectCorrectors"][0]["mode"] = 1
        self.assertEqual(feature_observations(tree, "portrait", 2.)["fov_actual"], "PASS")
        tree["features"]["native"]["requestedOrientation"] = 0
        self.assertNotIn("portrait", feature_observations(tree, "portrait", 2.))

    def test_all_required_cases_need_executed_pass_and_hashed_artifact_evidence(self):
        from feature_client_smoke import REQUIRED_CASES, case_overall
        cases = {key: {"status": "NOT_RUN", "evidence": []} for key in REQUIRED_CASES}
        self.assertEqual(case_overall(cases), "NOT_RUN")
        cases["native_load"] = {"status": "PASS", "evidence": [{"path": "observed.json", "sha256": "a" * 64}]}
        self.assertEqual(case_overall(cases), "PARTIAL")
        complete = {key: copy.deepcopy(cases["native_load"]) for key in REQUIRED_CASES}
        self.assertEqual(case_overall(complete), "PASS")
        complete["mv_same_suit"]["evidence"] = []
        self.assertEqual(case_overall(complete), "FAIL")
        complete["mv_same_suit"] = {"status": "NOT_RUN", "evidence": []}
        self.assertEqual(case_overall(complete), "PARTIAL")


class NativeSettingsViewportTests(unittest.TestCase):
    def recorded(self, region="GL"):
        from pathlib import Path
        from feature_client_smoke import parse_native_nodes
        return parse_native_nodes((Path(__file__).parent / "fixtures" / ("settings-start-" + region + ".xml")).read_bytes())

    def state(self):
        return {"language": True, "min": False, "max": False, "orientation": False, "intro": False}

    def test_actual_gl_and_jp_initial_viewport_selects_english_only_once_then_scrolls(self):
        from feature_client_smoke import native_profile_plan
        for region in ("GL", "JP"):
            nodes = self.recorded(region)
            self.assertFalse(any(n["class"] == "android.widget.SeekBar" for n in nodes))
            state = self.state(); state["language"] = False
            self.assertEqual(native_profile_plan(nodes, state, "portrait", False)["kind"], "language")
            state["language"] = True
            plan = native_profile_plan(nodes, state, "portrait", False)
            self.assertEqual(plan["kind"], "scroll")
            self.assertEqual(plan["node"]["bounds"], next(n["bounds"] for n in nodes if n["class"] == "android.widget.ScrollView"))
            # The visible footer is not permission to launch before controls.
            self.assertTrue(any(n["text"] == "Start game" for n in nodes))

    def synthetic_scrolled_slider(self, role, clipped=False):
        # Synthetic follow-up view tests complement the real initial capture;
        # they are not represented as proof of a completed Android action.
        nodes = self.recorded()
        view = next(n for n in nodes if n["class"] == "android.widget.ScrollView")
        heading = next(n for n in nodes if n["text"].startswith("MinAspect"))
        parent = heading["parent_path"]
        viewport = view["bounds"]
        height = viewport["bottom"] - viewport["top"]
        first = 5 if role == "min" else 8
        label = {**heading, "text": role.title() + "Aspect = 0.75000", "child_index": first}
        bounds = {"left": viewport["left"] + 20, "right": viewport["right"] - 20,
                  "top": int(viewport["top"] + height * .45), "bottom": int(viewport["top"] + height * .65)}
        if clipped: bounds["bottom"] = viewport["bottom"]
        bar = {**label, "text": "", "class": "android.widget.SeekBar", "child_index": first + 1,
               "layout_path": parent + "/" + str(first + 1), "bounds": bounds, "scroll_bounds": viewport,
               "center": {"x": (bounds["left"] + bounds["right"]) // 2, "y": (bounds["top"] + bounds["bottom"]) // 2}}
        return [view, label, bar]

    def test_one_labeled_slider_per_snapshot_is_sufficient_for_sequential_progress(self):
        from feature_client_smoke import native_profile_plan
        state = self.state()
        plan = native_profile_plan(self.synthetic_scrolled_slider("min"), state, "portrait", False)
        self.assertEqual((plan["kind"], plan["role"]), ("slider", "min"))
        state["min"] = True
        plan = native_profile_plan(self.synthetic_scrolled_slider("max"), state, "portrait", False)
        self.assertEqual((plan["kind"], plan["role"]), ("slider", "max"))
        self.assertTrue(state["language"])

    def test_clipped_slider_sliver_requires_another_live_bounds_scroll(self):
        from feature_client_smoke import native_profile_plan
        plan = native_profile_plan(self.synthetic_scrolled_slider("min", clipped=True), self.state(), "portrait", False)
        self.assertEqual(plan["kind"], "scroll")

    def test_observed_complete_profile_can_use_actual_always_visible_footer(self):
        from feature_client_smoke import native_profile_plan
        state = dict.fromkeys(("language", "min", "max", "orientation", "intro"), True)
        plan = native_profile_plan(self.recorded(), state, "portrait", False)
        self.assertEqual(plan["kind"], "launch")
        self.assertEqual(plan["node"]["text"], "Start game")


if __name__ == "__main__":
    unittest.main()
