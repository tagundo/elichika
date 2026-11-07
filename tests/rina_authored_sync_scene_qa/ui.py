"""Normal UI-only live10001 navigation for the disposable Rina scene lane.

This reuses the proven default-song driver; scene/native/SQL verdicts belong to
separate auditors. No forced scene callbacks, gameplay hooks, filters or scrolls.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/gl_ui_runtime"))
import android_gl_visual_smoke as smoke
from gl_ui_runtime.followup import snapshot, select_widget, rectangle

LIVE = 10001
MEMBERS = [209, 1, 2, 3, 4, 5, 6, 7, 8]
ALLOWED_RINA_SUITS = {912093017, 912093018, 912093019}
PREFIX = "LLAS.Scene.GlobalMenu.GlobalMenuButtonsController."
PLAY = "LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot.playButton"
VIDEO = "LLAS.Scene.LiveMusicSelect.LiveMusicSelectController.enableMvBtn"
CUSTOM = "LLAS.Components.UI.LiveMvDeckTabGroup.customTab"
SUIT_BUTTON = "LLAS.Components.UI.LiveMvDeckMemberParts.suitButton[member=209,position=1]"
SUIT_TOGGLE = "LLAS.SuitChangePopup.toggle.button"
POSITIVE = "LLAS.BasicPopupFrame.positiveButton"
HOME = ("LLAS.Scene.EntryPoint.HomeScene", "LLAS.Scene.Home.HomeMenu", "LLAS.Scene.Home.HomeMenuButtonsController")
MV = ("LLAS.Scene.EntryPoint.LiveMvScene", "LLAS.Scene.Live.Mv.LiveMvCoreScene", "LLAS.Scene.Live.Mv.LiveMvManager")
MOVIE = "LLAS.Scene.Live.Mv.LiveMvMovieScene"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def context_counts(tree):
    rows = tree.get("semanticState", {}).get("sceneContexts", [])
    counts = {}
    for name in (*HOME, *MV, MOVIE):
        found = [r for r in rows if r.get("className") == name]
        assert len(found) == 1 and found[0].get("status") == "COUNTED"
        n = found[0].get("activeOwners")
        assert type(n) is int and n >= 0
        counts[name] = n
    return counts


def mv_contexts(tree):
    counts = context_counts(tree)
    assert all(counts[n] == 1 for n in MV) and all(counts[n] == 0 for n in HOME) and counts[MOVIE] == 0
    return counts


def stopped_contexts(tree):
    try:
        counts = context_counts(tree)
    except AssertionError:
        return False
    return all(counts[n] == 0 for n in (*MV, MOVIE))


def deck(tree, expected_suits):
    assert isinstance(expected_suits, list) and len(expected_suits) == 9
    state = tree.get("semanticState", {})
    tabs = state.get("mvDeck", [])
    assert len(tabs) == 1 and tabs[0].get("currentDeckType") == 2
    assert not state.get("suitPopup"), "Suit modal remains active over the deck"
    slots = state.get("mvSlots", [])
    assert len(slots) == 9 and {r.get("position") for r in slots} == set(range(1, 10))
    slots = sorted(slots, key=lambda r: r["position"])
    assert all(r.get("liveId") == LIVE for r in slots)
    assert [r.get("memberId") for r in slots] == MEMBERS
    assert [r.get("suitId") for r in slots] == expected_suits
    return {"live_id": LIVE, "deck_type": 2, "slots": slots}


def active_context(tree, name):
    return any(row.get("className") == name and row.get("status") == "COUNTED" and row.get("activeOwners") == 1
               for row in tree.get("semanticState", {}).get("sceneContexts", []))

def choose(tree, *, ref=None, label=None):
    candidates = [row for row in tree.get("widgets", []) if row.get("active") is True
                  and (ref is None or ref in row.get("semantic_refs", []))
                  and (label is None or label in row.get("labels", []))
                  and (row.get("clickable") is True or row.get("interactable") is True)]
    # A ProductButton and its nested BasicButton can both inherit one caption.
    # Prefer the one original public ProductButton only when unique.
    products = [row for row in candidates if row.get("class") == "LLAS.Components.UI.ProductButton"]
    if len(products) == 1:
        candidates = products
    assert len(candidates) == 1, "Fresh normal input target is missing or ambiguous"
    row = candidates[0]
    command = {"widget_id": row["id"], "expected_class": row["class"],
               "expected_bounds": row["inputDiagnostics"]["raycastArea"]["geometry"]["bounds"]}
    if label:
        command["expected_label"] = label
    return select_widget(tree, command)

def choose_settings_light(tree, label):
    """Use the visible public label; the observed full-button center is masked."""
    selected = choose(tree, label=label)
    button = next(row for row in tree["widgets"] if row.get("id") == selected["widget_id"])
    texts = [row for row in tree.get("texts", []) if row.get("label") == label and row.get("active") is True
             and button.get("gameObjectId") in row.get("ancestorIds", [])]
    assert len(texts) == 1, "Settings Light label ancestry is missing or ambiguous"
    text = texts[0]
    assert not text.get("geometryRefusal") and isinstance(text.get("geometry"), dict)
    scrolls = [row for row in tree.get("scrollViews", []) if row.get("active") is True and row.get("verified") is True
               and row.get("viewport", {}).get("gameObjectId") in button.get("ancestorIds", [])
               and row.get("viewport", {}).get("gameObjectId") in text.get("ancestorIds", [])]
    assert len(scrolls) == 1, "Settings Light verified viewport ancestry is missing or ambiguous"
    viewport = scrolls[0]["viewport"]
    clip = viewport.get("clipping", {})
    assert viewport.get("active") is True and clip.get("verified") is True
    masks, groups = clip.get("masks"), clip.get("groups")
    assert isinstance(masks, list) and len(masks) == 1 and masks[0].get("class") == "UnityEngine.UI.RectMask2D"
    assert isinstance(groups, list) and groups and all(group.get("alpha") == 1 and group.get("interactable") is True and group.get("blocksRaycasts") is True for group in groups)
    canvas = button["geometry"]["canvasId"]
    geometries = [text["geometry"], viewport["geometry"], masks[0]["geometry"]]
    assert all(geometry.get("canvasId") == canvas for geometry in geometries), "Settings Light label canvas differs"
    bounds = rectangle(text["geometry"].get("bounds"))
    containers = [selected["bounds"], rectangle(tree.get("gameViewBounds")),
                  *(rectangle(geometry.get("bounds")) for geometry in geometries[1:])]
    assert all(outer[0] <= bounds[0] < bounds[2] <= outer[2] and outer[1] <= bounds[1] < bounds[3] <= outer[3] for outer in containers), "Settings Light public label is outside its button or known mask"
    point = [round((bounds[0] + bounds[2]) / 2), round((bounds[1] + bounds[3]) / 2)]
    assert all(outer[0] <= point[0] < outer[2] and outer[1] <= point[1] < outer[3] for outer in [bounds, *containers])
    selected.update(coordinates=point, source="fresh public settings label center within button and verified ancestor mask",
        public_label_bounds=bounds, verified_viewport_id=viewport["id"], known_mask_ids=[masks[0]["id"]],
        descendant_masks_exhaustively_enumerated=False, original_raycast_invoked=False)
    return selected


class Flow:
    def __init__(self, args, report, android):
        self.args, self.report, self.android = args, report, android
        self.sequence = 0
        self.language_choice_requested = False
        self.language_choice_completed = False
        self.download_settings_choice = None
        self.download_settings_choice_tree = None
        self.download_settings_completed = False
        self.expected_suits = None
        self.last_reference = None
        self.last_tree = None
        self.report.setdefault("captures", [])

    def capture(self, phase):
        self.sequence += 1
        label = f"{self.sequence:03d}-{phase}"
        requested = time.time()
        before = self.android.shell("sh", "-c", "pidof -s " + smoke.GAME + " || true").strip()
        tree = snapshot(self.android, self.args, self.report, label, required=False)
        after = self.android.shell("sh", "-c", "pidof -s " + smoke.GAME + " || true").strip()
        received = time.time()
        self.last_reference = None
        self.last_tree = tree
        if tree is not None:
            assert before.isdecimal() and after == before
            if self.report.get("game_pid"):
                assert int(before) == self.report["game_pid"]
            path = self.args.evidence / (label + "-ui/unity-ui-tree.json")
            captured = datetime.strptime(tree["captured_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            assert requested - 2 <= captured <= received + 2
            self.last_reference = {"file": str(path.relative_to(self.args.evidence)), "sha256": sha(path),
                                   "pid_before": int(before), "pid_after": int(after),
                                   "requested_unix_seconds": requested, "received_unix_seconds": received,
                                   "captured_unix_seconds": captured,
                               "actualtree_path": str(path),
                               "screen_path": str(self.args.evidence / (label + ".png")) if (self.args.evidence / (label + ".png")).is_file() else None}
        self.report.setdefault("steps", []).append({"label": label, "snapshot": label + "-ui/unity-ui-tree.json",
                                                     "reference": self.last_reference, "available": tree is not None})
        self.save()
        return tree

    def tap(self, tree, *, ref=None, label=None, settings_light=False):
        assert tree is self.last_tree and self.last_reference and time.time() - self.last_reference["received_unix_seconds"] <= 15
        selection = choose_settings_light(tree, label) if settings_light else choose(tree, ref=ref, label=label)
        point = list(map(str, selection["coordinates"]))
        self.android.shell("input", "touchscreen", "swipe", *(point + point), "240")
        self.report.setdefault("inputs", []).append({"selection": selection, "semantic_ref": ref,
                                                     "public_label": label, "source_snapshot": self.last_reference,
                                                     "unix_seconds": time.time()})
        self.save()
        time.sleep(2)

    def common_dialog(self, tree):
        labels = {row.get("label") for row in tree.get("texts", [])}
        popups = [row for row in tree.get("widgets", []) if row.get("active") is True
                  and "LLAS.BasicPopupFrame.positiveButton" in row.get("semantic_refs", [])]
        if self.language_choice_requested and not self.language_choice_completed:
            # In 42354099457 the background language-picker surface remained
            # visible behind the confirmation. Never tap its English row again.
            if {"Select Language", "OK", "Cancel", "English", "한국어"} <= labels and len(popups) == 1:
                self.tap(tree, ref="LLAS.BasicPopupFrame.positiveButton", label="OK")
                self.language_choice_completed = True
                self.report["language_selection"] = {"normal_English_choice": True,
                    "normal_confirmation_OK": True, "direct_PlayerPrefs_write": False}
                return True
            if popups or {"OK", "Cancel"} <= labels:
                raise AssertionError("Unrecognized active language confirmation; background input refused")
            return False
        if "Data Download Settings" in labels:
            # Exact observed 42357055166 settings surface. The standard Light
            # radio is visible; its separate auto-delete option is clipped.
            assert {"OK", "Cancel"} <= labels and len(popups) == 1
            assert not self.download_settings_completed, "Download settings confirmation was already sent"
            modes = {}
            for mode in ("Full", "Light"):
                rows = [row for row in tree.get("widgets", []) if row.get("active") is True
                        and row.get("class") == "LLAS.Components.UI.ProductButton"
                        and len(row.get("labels", [])) == 1
                        and re.fullmatch(mode + r" Download \([0-9]{1,12}(?:\.[0-9]{1,3})? MB\)", row["labels"][0])
                        and row["labels"][0] in labels]
                assert len(rows) == 1, "Observed standard download radio is missing or ambiguous"
                row = rows[0]
                modes[mode] = row
            light, full = modes["Light"], modes["Full"]
            if self.download_settings_choice is None:
                assert light.get("clickable") is True and full.get("clickable") is False
                self.tap(tree, label=light["labels"][0], settings_light=True)
                self.download_settings_choice = {"mode": "Light Download", "light_label": light["labels"][0],
                    "full_label": full["labels"][0], "choice_snapshot": self.last_reference,
                    "normal_UI": True, "direct_PlayerPrefs_write": False}
                self.download_settings_choice_tree = tree
                self.report["download_settings_selection"] = self.download_settings_choice
            else:
                assert tree is not self.download_settings_choice_tree, "Download radio confirmation requires a fresh tree"
                assert light["labels"][0] == self.download_settings_choice["light_label"] and full["labels"][0] == self.download_settings_choice["full_label"]
                assert light.get("clickable") is False and full.get("clickable") is True, "Normal Light download radio selection did not flip"
                self.tap(tree, ref="LLAS.BasicPopupFrame.positiveButton", label="OK")
                self.download_settings_completed = True
                self.download_settings_choice.update(radio_flip_observed=True, confirmation_snapshot=self.last_reference)
            return True
        if {"Agree", "No"} <= labels:
            self.tap(tree, label="Agree")
        elif {"Song Download Confirmation", "OK", "Cancel"} <= labels or {"Download Confirmation", "OK", "Cancel"} <= labels:
            self.tap(tree, label="OK")
        elif "Download Complete" in labels and any("Close" in row.get("labels", []) for row in tree.get("widgets", [])):
            self.tap(tree, label="Close")
        elif popups:
            raise AssertionError("Unrecognized active popup; background language/title input refused")
        elif (not self.language_choice_requested and not self.language_choice_completed
              and {"English", "한국어"} <= labels and not {"OK", "Cancel"}.intersection(labels)
              and len([row for row in tree.get("widgets", []) if row.get("active") is True
                       and row.get("class") == "LLAS.Components.UI.ProductButton"]) == 3):
            self.tap(tree, label="English")
            self.language_choice_requested = True
        elif labels.intersection(smoke.TITLE_LABELS):
            # Reuse the existing independently measured three-control title input.
            assert smoke.tap_ready_title(self.android, self.args, self.report, phase=f"stage-{self.sequence}")
        else:
            return False
        return True

    def home(self, phase):
        # The unchanged player can show one exact Android Play-services warning
        # before IL2CPP maps. A passive native snapshot must not dismiss it.
        smoke.capture(self.android, self.args.evidence, phase + "-android-dialog", self.report)
        until = time.monotonic() + 1500
        while time.monotonic() < until:
            if self.report.get("play_services_warning_dismissed") is not True:
                self.sequence += 1
                smoke.capture(self.android, self.args.evidence, f"{phase}-system-{self.sequence:03d}", self.report)
            tree = self.capture(phase)
            if tree is not None:
                if all(active_context(tree, name) for name in HOME):
                    return tree
                self.common_dialog(tree)
            time.sleep(10)
        raise AssertionError("Normal first-home input/download did not complete within25minutes")

    def save(self):
        temporary = self.args.evidence / ".scene-report.pending"
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.args.evidence / "scene-report.json")

    def expect_deck(self, suits):
        assert isinstance(suits, list) and len(suits) == 9
        assert all(type(x) is int and x > 0 for x in suits)
        assert suits[0] in ALLOWED_RINA_SUITS
        self.expected_suits = list(suits)

    def get_deck(self, phase="deck", home_tree=None):
        assert self.expected_suits is not None, "Bind the exact fixture suit roster first"
        if home_tree is not None:
            assert all(active_context(home_tree, name) for name in HOME)
            self.tap(home_tree, ref=PREFIX + "liveButton")
        until = time.monotonic() + 600
        previous_action = None
        while time.monotonic() < until:
            tree = self.capture(phase)
            if tree is None:
                time.sleep(3)
                continue
            state = tree.get("semanticState", {})
            if state.get("mvDeck"):
                assert stopped_contexts(tree)
                if len(state["mvDeck"]) == 1 and state["mvDeck"][0].get("currentDeckType") != 2:
                    self.tap(tree, ref=CUSTOM)
                    continue
                deck(tree, self.expected_suits)
                return tree
            if self.common_dialog(tree):
                previous_action = None
                continue
            music = state.get("musicSelect", [])
            if music:
                assert len(music) == 1 and music[0].get("selectedLiveId") == LIVE
                assert music[0].get("decidedLiveId") in (None, LIVE)
                self.report.setdefault("music_selection", []).append({"phase": phase, **music[0]})
                video = [r for r in tree.get("widgets", []) if VIDEO in r.get("semantic_refs", []) and r.get("clickable") is True]
                action = "video" if video else "download"
                if action == previous_action:
                    time.sleep(8)
                    continue
                self.tap(tree, ref=VIDEO) if video else self.tap(tree, label="Download Song")
                previous_action = action
            else:
                basic = [r for r in tree.get("widgets", []) if PREFIX + "basicLiveButton" in r.get("semantic_refs", [])]
                if basic and previous_action != "basic":
                    self.tap(tree, ref=PREFIX + "basicLiveButton")
                    previous_action = "basic"
            time.sleep(3)
        raise AssertionError("Normal live10001 custom deck not reached within10minutes")

    def _popup(self, phase, expected_on=None):
        until = time.monotonic() + 20
        while time.monotonic() < until:
            tree = self.capture(phase)
            if tree is not None:
                rows = tree.get("semanticState", {}).get("suitPopup", [])
                if len(rows) == 1:
                    assert type(rows[0].get("isOn")) is bool and rows[0].get("clickable") is True
                    if expected_on is None or rows[0]["isOn"] is expected_on:
                        return tree, rows[0]
            time.sleep(1)
        raise AssertionError("Actual owned Rina suit popup unavailable")

    def select_rina(self, suit_id, view_status, phase="select-rina"):
        assert type(suit_id) is int and suit_id in ALLOWED_RINA_SUITS
        assert type(view_status) is int and view_status in (1, 2)
        tree = self.get_deck(phase + "-deck")
        before = deck(tree, self.expected_suits)
        self.tap(tree, ref=SUIT_BUTTON)
        tree, popup = self._popup(phase + "-popup")
        if suit_id != self.expected_suits[0]:
            cells = [r for r in tree["semanticState"].get("suitCells", []) if r.get("memberId") == 209 and r.get("suitId") == suit_id]
            assert len(cells) == 1, "Requested owned Rina tile missing or ambiguous"
            self.tap(tree, ref=f"LLAS.SuitChangePopupSuitTileViewCell.button[suit={suit_id}]")
            tree, popup = self._popup(phase + "-tile-selected")
        desired = view_status == 1
        initial = popup["isOn"]
        if popup["isOn"] != desired:
            self.tap(tree, ref=SUIT_TOGGLE)
            tree, popup = self._popup(phase + "-toggle-selected", expected_on=desired)
            assert popup["isOn"] is desired, "Actual board toggle did not change to requested state"
        reviewed = dict(self.last_reference)
        assert popup["isOn"] is desired
        self.tap(tree, ref=POSITIVE, label="OK")
        expected = [suit_id, *self.expected_suits[1:]]
        until = time.monotonic() + 20
        while time.monotonic() < until:
            tree = self.capture(phase + "-confirmed")
            if tree is not None and not tree.get("semanticState", {}).get("suitPopup"):
                try:
                    actual = deck(tree, expected)
                except AssertionError:
                    time.sleep(1)
                    continue
                self.expected_suits = expected
                self.report.setdefault("rina_selections", []).append({"suit_id": suit_id, "view_status": view_status,
                    "toggle_before": initial, "toggle_after": desired, "toggle_review": reviewed,
                    "before_deck": before, "after_deck": actual, "confirmed_capture": self.last_reference})
                self.save()
                return tree
            time.sleep(1)
        raise AssertionError("Confirmed suit/view did not return to exact nine-member deck")

    def play(self, label):
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", label)
        tree = self.last_tree
        ui_deck = deck(tree, self.expected_suits)
        assert stopped_contexts(tree)
        before = dict(self.last_reference)
        started = time.time()
        self.tap(tree, ref=PLAY)
        attempt = {"case": label, "play_unix_seconds": started, "deck_capture": before,
                   "ui_deck": ui_deck, "scope": "Actual normal input/context only; native/route/SQL verdict separate"}
        self.report.setdefault("attempts", []).append(attempt)
        self.save()
        # A real Play transition gets the proven60-second observation; shorter
        # menu waits never stand in for native-scene or renderer readiness.
        smoke.observe_live_ui(self.android, self.args, self.report, label + "-after-play", seconds=60)
        until = time.monotonic() + 90
        while time.monotonic() < until:
            current = self.capture(label + "-mv")
            if current is not None:
                try:
                    counts = mv_contexts(current)
                except AssertionError:
                    self.common_dialog(current)
                else:
                    attempt.update(contexts=counts, mv_capture=dict(self.last_reference),
                                   first_context_unix_seconds=time.time())
                    self.save()
                    return attempt
            time.sleep(2)
        raise AssertionError("Normal MV typed contexts not reached after actual Play")

    def _completion(self, phase):
        until = time.monotonic() + 300
        while time.monotonic() < until:
            tree = self.capture(phase)
            if tree is not None and stopped_contexts(tree):
                state = tree.get("semanticState", {})
                if state.get("musicSelect") or state.get("mvDeck"):
                    return tree
            time.sleep(10)
        raise AssertionError("Natural MV completion not observed within5minutes")

    def warm_deck(self, phase="warm-deck"):
        self._completion(phase + "-natural-completion")
        return self.get_deck(phase)

    def return_home(self, phase="return-home"):
        tree = self._completion(phase + "-natural-completion")
        music = tree.get("semanticState", {}).get("musicSelect", [])
        assert len(music) == 1 and music[0].get("selectedLiveId") == LIVE
        assert not tree.get("semanticState", {}).get("mvDeck"), "Back is allowed only from observed MusicSelect"
        assert not tree.get("semanticState", {}).get("suitPopup")
        assert tree is self.last_tree and self.last_reference and time.time() - self.last_reference["received_unix_seconds"] <= 15
        source = dict(self.last_reference)
        self.android.shell("input", "keyevent", "KEYCODE_BACK")
        self.report.setdefault("inputs", []).append({"normal_keyevent": "KEYCODE_BACK", "source_snapshot": source,
                                                     "unix_seconds": time.time(), "source_context": "live10001 MusicSelect after natural completion"})
        self.save()
        until = time.monotonic() + 60
        while time.monotonic() < until:
            tree = self.capture(phase)
            if tree is not None:
                counts = context_counts(tree)
                if all(counts[n] == 1 for n in HOME) and all(counts[n] == 0 for n in (*MV, MOVIE)):
                    self.report["home_return"] = {"contexts": counts, "capture": dict(self.last_reference)}
                    self.save()
                    return tree
            time.sleep(2)
        raise AssertionError("Actual HOME contexts unavailable after normal MusicSelect Back")
