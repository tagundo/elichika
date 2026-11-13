import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from mv_driver import MVDriver, deck_layout, independent_live_members, standing_count, validated_pick, successful_live_start_count


def deck():
    return {'screen': {'scene': 'LiveMvDeckSelect'}, 'features': {'mv': {
        'standingMemberNum': 3, 'liveMasterId': 1001,
        'deckCells': [{'active': True, 'voClass': 'DeckMemberCustomVO', 'formationPosition': p,
                       'memberId': p * 10, 'suitId': p * 100} for p in (1, 2, 3)]}}}


def live(expected):
    return {'screen': {'scene': 'LiveMvCore'}, 'features': {'mv': {'liveMembers': [
        {'active': True, 'id': str(10 + p), 'gameObjectId': str(100 + p), 'formationPosition': p,
         'memberId': v['memberId'], 'suitId': v['suitId'], 'position': {'x': p * 2., 'y': 0., 'z': 0.}}
        for p, v in expected.items()]}}}


class EvidenceTests(unittest.TestCase):
    def test_live_start_counter_rejects_routes_failures_and_other_methods(self):
        log = b'POST "/liveMv/start"\n[GIN] now | 200 | 1ms | peer | POST "/liveMv/start"\n[GIN] now | 201 | 1ms | peer | POST "/liveMv/start?synthetic=yes"\n[GIN] now | 401 | 1ms | peer | POST "/liveMv/start"\n[GIN] now | 200 | 1ms | peer | GET "/liveMv/start"\n[GIN] now | 200 | 1ms | peer | POST "/liveMv/startAnother"\n'
        self.assertEqual(successful_live_start_count(log), 2)

    def test_duplicates_preserved_and_ambiguous_slots_rejected(self):
        tree = deck(); cells = tree['features']['mv']['deckCells']; cells[1]['memberId'] = cells[0]['memberId']
        self.assertEqual(len(deck_layout(tree)), 3)
        cells.append(copy.deepcopy(cells[0]))
        self.assertIsNone(deck_layout(tree))

    def test_capacity_is_actual_song_metadata_not_visible_count(self):
        tree = deck(); self.assertEqual(standing_count(tree), 3)
        for value in (None, True, 0, 13, '12'):
            tree['features']['mv']['standingMemberNum'] = value
            self.assertIsNone(standing_count(tree))

    def test_live_requires_exact_character_costume_instances_and_formations(self):
        wanted = deck_layout(deck()); tree = live(wanted)
        self.assertEqual(len(independent_live_members(tree, wanted)), 3)
        for change in ('same_id', 'same_go', 'same_transform', 'wrong_suit', 'no_suit', 'wrong_scene', 'extra_slot'):
            bad = copy.deepcopy(tree); members = bad['features']['mv']['liveMembers']
            if change == 'same_id': members[1]['id'] = members[0]['id']
            elif change == 'same_go': members[1]['gameObjectId'] = members[0]['gameObjectId']
            elif change == 'same_transform': members[1]['position'] = members[0]['position']
            elif change == 'wrong_suit': members[1]['suitId'] = 999
            elif change == 'no_suit': del members[1]['suitId']
            elif change == 'wrong_scene': bad['screen']['scene'] = 'Home'
            elif change == 'extra_slot': members.append(copy.deepcopy(members[0]))
            with self.subTest(change=change): self.assertIsNone(independent_live_members(bad, wanted))

    def test_pick_rejects_stale_obscured_wrong_identity_and_off_surface(self):
        query = {'role': 'suitPicker', 'memberId': 10, 'suitId': 100}
        target = {'active': True, 'enabled': True, 'visible': True, 'groupsInteractable': True,
                  'blocksRaycasts': True, 'hit': {'available': True, 'hittable': True},
                  'center': {'x': 50, 'y': 50}, 'bounds': {'left': 10, 'top': 10, 'right': 90, 'bottom': 90}}
        response = {'timestampMs': 1000, 'target': target, 'screen': {'width': 100, 'height': 100}, 'catalog': {'memberId': 10, 'suitId': 100}}
        self.assertEqual(validated_pick(response, query, now_ms=1100), (50, 50))
        for change in ('old', 'future', 'blocked', 'wrong_suit', 'outside'):
            bad = copy.deepcopy(response)
            if change == 'old': bad['timestampMs'] = -1000
            elif change == 'future': bad['timestampMs'] = 1200
            elif change == 'blocked': bad['target']['hit']['hittable'] = False
            elif change == 'wrong_suit': bad['catalog']['suitId'] = 200
            elif change == 'outside': bad['target']['center']['x'] = 101
            with self.subTest(change=change), self.assertRaises(ValueError): validated_pick(bad, query, now_ms=1100)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mv-adapter-tests-')
        self.root = Path(self.temporary.name)
        self.driver = MVDriver(self.root, required_capacity=3)
        self.sequence = 0

    def tearDown(self): self.temporary.cleanup()

    def snapshot(self, tree):
        self.sequence += 1
        path = f'snapshot-{self.sequence}.json'
        (self.root / path).write_text(json.dumps(tree))
        return path

    def step(self, tree, now=0, count=0):
        return self.driver.step(tree, self.snapshot(tree), now=now, live_start_count=count)

    def test_real_selection_plans_use_typed_ids_then_verify_observed_deck(self):
        tree = deck()
        action = self.step(tree)
        self.assertEqual(action['query'], {'role': 'member', 'formationPosition': 2})
        tree['features']['mv']['pickerCells'] = [{'active': True, 'memberId': 10, 'target': {'visible': True, 'hit': {'hittable': True}}}]
        action = self.step(tree, 5)
        self.assertEqual(action['query'], {'role': 'picker', 'memberId': 10})
        tree['features']['mv']['pickerCells'] = []
        tree['features']['mv']['deckCells'][1].update(memberId=10, suitId=100)
        self.assertEqual(self.step(tree, 10)['kind'], 'video_start')
        self.assertEqual(self.step(tree, 11)['kind'], 'semantic')
        expected = self.driver.expected
        playing = live(expected)
        self.assertIsNone(self.step(playing, 12, count=0))
        self.assertEqual(self.driver.cases['mv_same_suit']['status'], 'NOT_RUN')
        self.assertEqual(self.step(playing, 13, count=1)['kind'], 'wait')
        self.assertEqual(self.step(playing, 17, count=1)['kind'], 'video_stop')
        self.assertEqual(self.driver.cases['mv_same_suit']['status'], 'NOT_RUN')
        self.assertIn('mv_same_suit', self.driver.proofs)
        proof = json.loads((self.root / self.driver.proofs['mv_same_suit']).read_text())
        self.assertEqual(proof['standingMemberNum'], 3)
        self.assertIn('global12', proof['scope'])

    def test_full_case_transition_restores_after_same_different_and_all_slots(self):
        tree = deck(); self.step(tree)
        for case_index, name in enumerate(('mv_same_suit', 'mv_different_suits', 'mv_max_slots')):
            self.assertEqual(self.driver.case, name)
            if name == 'mv_different_suits': self.driver.other_suit = 101
            desired = self.driver._desired()
            for cell in tree['features']['mv']['deckCells']: cell.update(desired[cell['formationPosition']])
            self.step(tree, 20 + case_index * 20, count=case_index)
            self.step(tree, 21 + case_index * 20, count=case_index)
            playing = live(desired)
            self.step(playing, 22 + case_index * 20, count=case_index + 1)
            action = self.step(playing, 26 + case_index * 20, count=case_index + 1)
            self.assertEqual(action['kind'], 'video_stop')
            self.assertIn(name, self.driver.proofs)
            if name == 'mv_max_slots':
                self.assertEqual(len(set(v['memberId'] for v in desired.values())), 1)
                self.assertEqual(len(desired), self.driver.capacity)
            self.step(tree, 27 + case_index * 20, count=case_index + 1)
        self.assertEqual(self.driver.case, 'mv_restore')
        for cell in tree['features']['mv']['deckCells']: cell.update(self.driver.baseline[cell['formationPosition']])
        self.step(tree, 90, count=3)
        self.step({'screen': {'scene': 'LiveMusicSelect'}}, 91, count=3)
        self.step(tree, 92, count=3)
        self.assertEqual(self.driver.phase, 'done')
        self.assertEqual(self.driver.cases['mv_restore']['status'], 'PASS')
        self.assertTrue(all(self.driver.cases[name]['status'] == 'NOT_RUN' for name in ('mv_same_suit', 'mv_different_suits', 'mv_max_slots')))

    def test_missing_candidate_researches_actual_scroll_popup(self):
        tree = deck(); self.step(tree)
        tree['features']['mv']['pickerCells'] = [{'active': True, 'memberId': 90, 'target': {'visible': True, 'hit': {'hittable': True}}}]
        self.assertEqual(self.step(tree, 5)['kind'], 'scroll')

    def test_default_final_gate_requires_actual_twelve_standing_song(self):
        final_driver = MVDriver(self.root)
        tree = deck()
        self.assertIsNone(final_driver.step(tree, self.snapshot(tree)))
        self.assertIsNone(final_driver.baseline)
        self.assertIn('required=12', final_driver.blocked_reason)

    def test_missing_metadata_or_geometry_never_awards_a_pass(self):
        tree = deck(); del tree['features']['mv']['standingMemberNum']
        self.assertIsNone(self.step(tree))
        self.assertTrue(all(c['status'] == 'NOT_RUN' for c in self.driver.results()['cases'].values()))
        with self.assertRaises(ValueError): self.driver.step(tree, '../outside.json')

    def test_restore_needs_leave_reopen_and_same_song_entire_deck(self):
        tree = deck(); self.step(tree)
        self.driver.case, self.driver.phase = 'mv_restore', 'restore'
        self.assertEqual(self.step(tree, 5)['key'], 'KEYCODE_BACK')
        self.assertIsNone(self.step(tree, 6))
        self.assertEqual(self.driver.cases['mv_restore']['status'], 'NOT_RUN')
        self.step({'screen': {'scene': 'LiveMusicSelect'}}, 7)
        self.step(tree, 12)
        self.assertEqual(self.driver.cases['mv_restore']['status'], 'PASS')

    def test_restore_changed_costume_after_reopen_is_failure(self):
        tree = deck(); self.step(tree)
        self.driver.case, self.driver.phase = 'mv_restore', 'restore'; self.step(tree, 5)
        self.step({'screen': {'scene': 'LiveMusicSelect'}}, 7)
        tree['features']['mv']['deckCells'][1]['suitId'] = 999
        self.step(tree, 12)
        self.assertEqual(self.driver.cases['mv_restore']['status'], 'FAIL')

    def test_startup_only_video_that_ends_before_mv_observation_is_rejected(self):
        (self.root / 'short.mp4').write_bytes(b'0000ftyp' + b'0' * 64)
        proof = self.driver._write('timed-playback', {'video_requested_monotonic': 10, 'last_observed_monotonic': 40})
        self.driver.proofs['mv_same_suit'] = proof
        media = {'streams': [{'width': 1280, 'height': 720, 'nb_read_frames': '150'}], 'format': {'duration': '10'}}
        with patch('mv_driver.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(media))):
            with self.assertRaisesRegex(ValueError, 'ended before'): self.driver.record_video('mv_same_suit', 'short.mp4')
        self.assertEqual(self.driver.cases['mv_same_suit']['status'], 'NOT_RUN')

    def test_video_container_only_or_no_matching_actual_playback_is_not_pass(self):
        (self.root / 'fake.mp4').write_bytes(b'0000ftyp' + b'0' * 64)
        with self.assertRaises(ValueError): self.driver.record_video('mv_same_suit', 'fake.mp4')
        proof = self.driver._write('test-playback', {'test': 'not real-game proof'})
        self.driver.proofs['mv_same_suit'] = proof
        for duration, frames in (('0.1', '100'), ('5', '0'), ('NaN', '100')):
            media = {'streams': [{'width': 1280, 'height': 720, 'nb_read_frames': frames}], 'format': {'duration': duration}}
            with patch('mv_driver.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(media))):
                with self.assertRaises(ValueError): self.driver.record_video('mv_same_suit', 'fake.mp4')
        self.assertEqual(self.driver.cases['mv_same_suit']['status'], 'NOT_RUN')


if __name__ == '__main__': unittest.main()
