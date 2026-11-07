"""Actual missing-geometry regression plus synthetic Square proof boundaries.

The exact118 replay contains NO measured Square raycast geometry. Positive
polygon cases below are synthetic algebra tests, never actual UI hit evidence.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from ui import choose, Refused, smoke

REF = "LLAS.Scene.CommunicationMemberDetail.CommunicationMemberDetailTopMenu.themeListButton"
FIXTURE = Path(__file__).with_name("fixtures") / "preview-detail-118-42396817217.json"
FIXTURE_SHA = "6c7c4c7a80d8af1642a23ae36135a780becc288dd38f60a67136743cf05b36dc"


def synthetic_square():
    geometry = {"bounds": [0, 0, 100, 100], "canvasId": 7, "renderMode": 1,
                "camera": {"id": 8, "orthographic": True}}
    proof = {"kind": "SquareRayCastArea.local-corners-pivot.strict-interior.v1",
             "point": [50, 50], "strictInsideQuadrilateral": True,
             "quadrilateralVertices": [[0, 50], [50, 0], [100, 50], [50, 100]],
             "canvasId": 7, "cameraId": 8, "outerEdgeMarginPx": .25,
             "originalRaycastInvoked": False, "ancestorFiltersChecked": False}
    area = {"class": "LLAS.Components.SquareRayCastArea", "active": True,
            "raycastTarget": True, "geometry": copy.deepcopy(geometry),
            "verifiedSquareHitPoint": proof}
    node = {"id": 1, "class": "LLAS.Components.UI.ProductButton", "active": True,
            "clickable": True, "geometry": geometry, "semantic_refs": [REF],
            "inputDiagnostics": {"raycastArea": area}}
    return {"status": "SNAPSHOT", "game_apk_sha256": smoke.GAME_SHA,
            "gameViewBounds": [0, 0, 100, 100], "widgets": [node]}


class SquareInput(unittest.TestCase):
    def setUp(self):
        self.tree = synthetic_square()
        self.node = self.tree["widgets"][0]
        self.area = self.node["inputDiagnostics"]["raycastArea"]
        self.proof = self.area["verifiedSquareHitPoint"]

    def refuse(self, code):
        with self.assertRaisesRegex(Refused, code):
            choose(self.tree, ref=REF)

    def test_actual118_missing_square_geometry_is_typed_refusal(self):
        data = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), FIXTURE_SHA)
        actual = json.loads(data)
        with self.assertRaisesRegex(Refused, "raycast_target_unverified"):
            choose(actual, ref=REF)

    def test_missing_or_malformed_diagnostics_never_use_outer_button_rect(self):
        for diagnostic in (None, "unavailable", {}, {"raycastArea": "unavailable"},
                           {"raycastArea": {"geometry": "unavailable"}}):
            with self.subTest(diagnostic=diagnostic):
                self.node["inputDiagnostics"] = diagnostic
                self.refuse("raycast_target_unverified")

    def test_synthetic_center_on_native_internal_diagonal_is_valid(self):
        selected = choose(self.tree, ref=REF)
        self.assertEqual(selected["coordinates"], [50, 50])
        self.assertTrue(selected["shape_verification_only"])
        self.assertFalse(selected["proof_original_raycast_invoked"])

    def test_inside_rect_but_outside_diamond_is_refused(self):
        self.proof["point"] = [10, 10]
        self.refuse("square_point_not_strictly_inside")

    def test_outer_edge_and_less_than_quarter_pixel_margin_refused(self):
        for point in ([25, 25], [1, 50]):
            with self.subTest(point=point):
                self.proof["point"] = point
                if point == [1, 50]:
                    self.proof["quadrilateralVertices"] = [[.9, 50], [50, .9], [99.1, 50], [50, 99.1]]
                self.refuse("square_point_not_strictly_inside")

    def test_missing_shape_proof_refused(self):
        del self.area["verifiedSquareHitPoint"]
        self.refuse("square_shape_proof_unavailable")

    def test_original_predicate_or_ancestor_verification_claim_refused(self):
        for field in ("originalRaycastInvoked", "ancestorFiltersChecked"):
            with self.subTest(field=field):
                self.proof[field] = True
                self.refuse("square_shape_proof_unavailable")
                self.proof[field] = False

    def test_wrong_canvas_or_camera_refused(self):
        for field in ("canvasId", "cameraId"):
            with self.subTest(field=field):
                old = self.proof[field]
                self.proof[field] = old + 1
                self.refuse("square_canvas_or_camera_changed")
                self.proof[field] = old

    def test_perspective_or_overlay_refused(self):
        self.area["geometry"]["camera"]["orthographic"] = False
        self.refuse("square_canvas_or_camera_changed")
        self.area["geometry"]["camera"]["orthographic"] = True
        self.area["geometry"]["renderMode"] = 0
        self.refuse("square_canvas_or_camera_changed")

    def test_nonfinite_and_invalid_vertices_refused(self):
        for vertices in ([[0, 50], [50, 0], [float("nan"), 50], [50, 100]], [], [[0, 0]] * 3):
            with self.subTest(vertices=vertices):
                self.proof["quadrilateralVertices"] = vertices
                self.refuse("square_vertices_unavailable")

    def test_self_crossing_or_degenerate_quad_refused(self):
        for vertices in ([[0, 0], [100, 100], [0, 100], [100, 0]], [[50, 50]] * 4):
            with self.subTest(vertices=vertices):
                self.proof["quadrilateralVertices"] = vertices
                self.refuse("square_degenerate_or_nonconvex")

    def test_polygon_outside_measured_bounds_refused(self):
        self.proof["quadrilateralVertices"][0][0] = -1
        self.refuse("square_vertices_outside_measured_bounds")

    def test_inactive_raycast_and_unverified_target_refused(self):
        for field in ("active", "raycastTarget"):
            with self.subTest(field=field):
                self.area[field] = False
                self.refuse("raycast_target_unverified")
                self.area[field] = True


if __name__ == "__main__":
    unittest.main()
