import copy
import unittest
from feature_client_smoke import download_settings_plan
from unity_main_tid import TidProofError, proc_stat_starttime


def sample():
    # Authored unit fixture, not a runtime capture or behavioral approval.
    return {"features":{"downloadSettings":[{"path":"Canvas/DownloadPopup","options":[
        {"role":"lightnessDownloadItemText","path":"Canvas/DownloadPopup/Light/Caption","text":"軽量ダウンロード [5858.95 MB]"}],
        "toggles":[{"path":"Canvas/DownloadPopup/Full","isOn":True},
        {"path":"Canvas/DownloadPopup/Light","isOn":False,"target":{"id":"light","active":True,"visible":True,
            "hit":{"available":True,"hittable":True},"center":{"x":20,"y":40}}}]}]}}


class DownloadSettingsTests(unittest.TestCase):
    def test_selects_only_the_referenced_lightweight_radio(self):
        plan=download_settings_plan(sample())
        self.assertEqual(plan["action"],"select-lightweight")
        self.assertEqual(plan["target"]["id"],"light")

    def test_confirmation_requires_exclusively_observed_lightweight_state(self):
        tree=sample();toggles=tree["features"]["downloadSettings"][0]["toggles"]
        toggles[0]["isOn"]=False;toggles[1]["isOn"]=True
        self.assertEqual(download_settings_plan(tree)["action"],"confirm-lightweight")
        for value in (True,None,1):
            toggles[0]["isOn"]=value
            self.assertEqual(download_settings_plan(tree)["action"],"blocked")

    def test_missing_ambiguous_or_obscured_radio_never_confirms_default_bulk(self):
        for change in ("missing-caption","unrelated-path","duplicate-toggle","hidden","wrong-hit","missing-state"):
            tree=sample();popup=tree["features"]["downloadSettings"][0];light=popup["toggles"][1]
            if change=="missing-caption":popup["options"]=[]
            elif change=="unrelated-path":popup["options"][0]["path"]="Other/Caption"
            elif change=="duplicate-toggle":popup["toggles"].append(copy.deepcopy(light))
            elif change=="hidden":light["target"]["visible"]=False
            elif change=="wrong-hit":light["target"]["hit"]["hittable"]=False
            else:light["isOn"]=None
            with self.subTest(change=change):self.assertEqual(download_settings_plan(tree)["action"],"blocked")

    def test_visible_caption_without_typed_state_blocks_generic_ok(self):
        tree={"nodes":[{"active":True,"visible":True,"text":"データダウンロード設定"}]}
        self.assertEqual(download_settings_plan(tree)["action"],"blocked")
        self.assertIsNone(download_settings_plan({"nodes":[{"active":True,"visible":True,"text":"Other popup"}]}))

    def test_proc_stat_starttime_handles_spaces_and_parentheses_in_comm(self):
        raw="123 (Unity worker (one)) "+" ".join(["S"]+["0"]*18+["98765"]+["0"]*4)
        self.assertEqual(proc_stat_starttime(raw,123),"98765")
        for changed,pid in ((raw,124),("123 malformed",123),("123 (name) S 0",123),(raw.replace("98765","-1"),123)):
            with self.assertRaises(TidProofError):proc_stat_starttime(changed,pid)


if __name__=="__main__":unittest.main()
