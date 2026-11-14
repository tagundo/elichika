"""Pure music-pick agreement tests grounded in retained R6 row observations."""
import copy
import ast
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from predeck_music_stability import music_target_stability
from mv_driver import validated_pick
import feature_client_smoke as semantics


FIXTURES = Path(__file__).parent / 'fixtures' / 'actual-gl-music-stability'
QUERY = {'role': 'music', 'liveMasterId': 12074}


class MusicTargetStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {name: json.loads((FIXTURES / (name + '.json')).read_text())
                     for name in ('mv-ui-027', 'mv-ui-031')}

    def pick(self, name='mv-ui-027'):
        tree = self.trees[name]
        rows = [row for row in tree['features']['mv']['musicRows'] if row.get('liveMasterId') == 12074]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        return {'screen': copy.deepcopy(tree['screen']), 'target': copy.deepcopy(row['target']),
                'catalog': copy.deepcopy(row),
                'musicSelection': copy.deepcopy(tree['features']['mv']['musicSelection'])}

    def assert_refused(self, original, fresh, reason, query=QUERY):
        result = music_target_stability(original, fresh, query)
        self.assertFalse(result['stable'])
        self.assertIn(reason, result['reason'])
        self.assertNotIn('input_performed', result)
        return result

    def test_actual_fixture_bytes_and_scope_match_recorded_provenance(self):
        provenance = json.loads((FIXTURES / 'provenance.json').read_text())
        self.assertEqual(provenance['run'], 43577464048)
        self.assertIn('do not prove the exact geometry', provenance['interpretation'])
        for member in provenance['fixtures']:
            with self.subTest(fixture=member['fixture']):
                raw = (FIXTURES / member['fixture']).read_bytes()
                self.assertEqual(len(raw), member['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), member['sha256'])

    def test_actual_same_row_instance_and_vo_with_changed_geometry_is_refused(self):
        before, after = self.pick('mv-ui-027'), self.pick('mv-ui-031')
        self.assertEqual(before['target']['id'], after['target']['id'])
        self.assertEqual(before['target']['path'], after['target']['path'])
        self.assertEqual(before['catalog']['liveMasterId'], after['catalog']['liveMasterId'])
        result = self.assert_refused(before, after, 'projected row is still moving')
        self.assertEqual(result['deltas_px']['center.x'], 65)
        self.assertEqual(result['deltas_px']['center.y'], 235)

    def test_stable_actual_row_and_two_pixel_boundary_do_not_assert_selection_readiness(self):
        before = self.pick()
        after = copy.deepcopy(before)
        after['screen']['frame'] += 100
        after['musicSelection'] = copy.deepcopy(self.trees['mv-ui-031']['features']['mv']['musicSelection'])
        self.assertEqual(before['musicSelection'][0]['currentSelectedCellVO']['liveMasterId'], 12058)
        self.assertEqual(after['musicSelection'][0]['currentSelectedCellVO']['liveMasterId'], 12059)
        self.assertIsNone(after['musicSelection'][0]['decidedCellVO']['liveMasterId'])
        result = music_target_stability(before, after, QUERY)
        self.assertTrue(result['stable'])
        self.assertTrue(all(delta == 0 for delta in result['deltas_px'].values()))
        self.assertFalse(any('ready' in key or 'selected' in key or 'decided' in key for key in result))

        before = self.pick()
        for group, keys in [('center', ('x', 'y')), ('bounds', ('left', 'top', 'right', 'bottom')),
                            ('visibleBounds', ('left', 'top', 'right', 'bottom'))]:
            for key in keys:
                with self.subTest(group=group, coordinate=key):
                    after = copy.deepcopy(before)
                    after['target'][group][key] += 2
                    accepted = music_target_stability(before, after, QUERY)
                    self.assertTrue(accepted['stable'])
                    self.assertEqual(accepted['deltas_px'][group + '.' + key], 2)
                    after['target'][group][key] += .001
                    self.assert_refused(before, after, 'projected row is still moving')

    def test_changed_identity_surface_or_unavailable_geometry_is_refused(self):
        before = self.pick()
        for group, key, value in [('target', 'id', 'another-instance'),
                                  ('target', 'path', 'Canvas/OtherCell'),
                                  ('screen', 'scene', 'Home'),
                                  ('screen', 'width', 1280), ('screen', 'height', 720)]:
            with self.subTest(group=group, field=key):
                after = copy.deepcopy(before)
                after[group][key] = value
                self.assert_refused(before, after, 'scene/path/instance/surface changed')
        for key in ('id', 'path'):
            invalid = copy.deepcopy(before)
            invalid['target'].pop(key)
            self.assert_refused(invalid, copy.deepcopy(invalid), 'scene/path/instance/surface changed')
        for group, key in [('center', 'x'), ('bounds', 'right'), ('visibleBounds', 'top')]:
            for value in (None, True, '1', float('nan'), float('inf'), float('-inf')):
                with self.subTest(group=group, coordinate=key, value=value):
                    after = copy.deepcopy(before)
                    after['target'][group][key] = value
                    self.assert_refused(before, after, 'projected geometry unavailable')
        for group in ('center', 'bounds'):
            after = copy.deepcopy(before)
            after['target'].pop(group)
            self.assert_refused(before, after, 'projected geometry unavailable')

    def test_exact_music_query_and_both_playable_vo_bindings_are_required(self):
        before = self.pick()
        for query in ({}, {'role': 'suit', 'liveMasterId': 12074},
                      {'role': 'music', 'liveMasterId': 12074.0},
                      {'role': 'music', 'liveMasterId': True}):
            with self.subTest(query=query):
                self.assert_refused(before, copy.deepcopy(before), 'Missing exact typed music query', query)
        for side in ('original', 'fresh'):
            for key, value in [('liveMasterId', 12096), ('liveMasterId', None),
                               ('isPlayable', False), ('isPlayable', 1)]:
                with self.subTest(side=side, field=key, value=value):
                    original, fresh = copy.deepcopy(before), copy.deepcopy(before)
                    (original if side == 'original' else fresh)['catalog'][key] = value
                    self.assert_refused(original, fresh, 'Typed music VO changed')

    def test_visible_bounds_are_optional_only_when_both_picks_omit_them(self):
        before = self.pick()
        after = copy.deepcopy(before)
        before['target'].pop('visibleBounds')
        after['target'].pop('visibleBounds')
        result = music_target_stability(before, after, QUERY)
        self.assertTrue(result['stable'])
        self.assertFalse(any(key.startswith('visibleBounds.') for key in result['deltas_px']))
        after['target']['visibleBounds'] = copy.deepcopy(after['target']['bounds'])
        self.assert_refused(before, after, 'projected geometry unavailable')


class ActualTapBoundaryTests(unittest.TestCase):
    """Execute the actual nested tap and intent branch with host-only boundaries."""
    @classmethod
    def setUpClass(cls):
        source=ast.parse((Path(__file__).parent/'native_mv_focus.py').read_text())
        tap=next(node for node in ast.walk(source) if isinstance(node,ast.FunctionDef) and node.name=='tap_picked')
        branch=next(node for node in ast.walk(source) if isinstance(node,ast.If) and
            isinstance(node.test,ast.Call) and isinstance(node.test.func,ast.Name) and node.test.func.id=='tap_picked' and
            any(isinstance(arg,ast.Constant) and arg.value=='select-official-twelve-standing-song' for arg in node.test.args))
        cls.tap_code=compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(tap)],type_ignores=[])),
                             '<actual-R7-tap>','exec')
        cls.intent_code=compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(branch)],type_ignores=[])),
                                '<actual-R7-intent>','exec')

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.now=100.;self.wall=1800000000.;self.events=[]
        target={'id':'typed-row','path':'Observed/MusicScrollView/cell124','active':True,'enabled':True,
            'visible':True,'groupsInteractable':True,'blocksRaycasts':True,
            'hit':{'available':True,'hittable':True},'center':{'x':150,'y':700},
            'bounds':{'left':100,'top':650,'right':200,'bottom':750},
            'visibleBounds':{'left':100,'top':650,'right':200,'bottom':750}}
        self.original={'timestampMs':self.wall*1000,'screen':{'scene':'LiveMusicSelect','width':720,'height':1280},
                       'target':target,'catalog':{'liveMasterId':12074,'isPlayable':True}}
        self.fresh=copy.deepcopy(self.original)
        self.native=SimpleNamespace(last_path=None)
        self.report={'actions':[]};self.identity={'pid':123,'start_ticks':'456'}
        self.context={'native':self.native,'args':SimpleNamespace(evidence=self.root),
            'lifetime':lambda:dict(self.identity),'save':Mock(),'overall_deadline':2400.}
        self.device=SimpleNamespace(shell=Mock(side_effect=self.input))
        self.env={'validated_pick':validated_pick,'music_target_stability':music_target_stability,
            'semantics':semantics,'context':self.context,'evidence':self.root,'report':self.report,
            'pid':'123','before_ticks':'456','device':self.device,
            'fresh_native_geometry':self.native_geometry,'rpc':lambda fn,**kwargs:fn(),
            'agent':SimpleNamespace(exports_sync=SimpleNamespace(pickmv=self.pick)),
            'time':SimpleNamespace(time=self.wall_time,monotonic=lambda:self.now),
            'picked':self.original,'query':dict(QUERY),'index':27,'selected_song':None}
        exec(self.tap_code,self.env)

    def wall_time(self):return self.wall+self.now-100.

    def native_geometry(self,screen,index):
        self.events.append('native');self.now+=.125
        self.native.last_path='mv-native-%03d.xml'%index
        (self.root/self.native.last_path).write_bytes(b'<hierarchy><node class="android.view.SurfaceView"/></hierarchy>')
        return semantics.unity_surface_bounds([{'package':'com.klab.lovelive.allstars.global',
            'class':'android.view.SurfaceView','bounds':{'left':0,'top':0,'right':720,'bottom':1280}}],screen)

    def pick(self,query):
        self.events.append('pick');self.assertEqual(query,QUERY)
        self.fresh['timestampMs']=self.wall_time()*1000
        return self.fresh

    def input(self,*args,**kwargs):self.events.append('tap');self.now+=.002

    def intent(self):
        with patch('mv_driver.time.time',side_effect=self.wall_time):exec(self.intent_code,self.env)

    def test_moving_row_retains_both_picks_and_refuses_input_and_intent(self):
        self.fresh['target']['center']['x']+=3
        self.intent()
        self.assertEqual(self.events,['native','pick']);self.device.shell.assert_not_called()
        self.assertIsNone(self.env['selected_song']);self.assertEqual(self.report['actions'],[])
        before=json.loads((self.root/'operator-auto-music-027-fresh.json').read_text())
        result=json.loads((self.root/'operator-auto-music-027-result.json').read_text())
        self.assertEqual(before['original_pick']['catalog']['liveMasterId'],12074)
        self.assertEqual(before['fresh_pick']['catalog']['liveMasterId'],12074)
        self.assertEqual(before['music_stability']['deltas_px']['center.x'],3)
        self.assertEqual(before['native_xml_sha256'],hashlib.sha256((self.root/before['native_xml']).read_bytes()).hexdigest())
        self.assertIs(result['input_returned'],False);self.assertIs(result['input_performed'],False)
        self.context['save'].assert_called_once()

    def test_stable_row_sets_intent_only_after_input_and_keeps_actual_timestamps(self):
        self.intent()
        self.assertEqual(self.events,['native','pick','tap']);self.assertEqual(self.env['selected_song'],12074)
        self.device.shell.assert_called_once_with('input','tap','150','700')
        before=json.loads((self.root/'operator-auto-music-027-fresh.json').read_text())
        result=json.loads((self.root/'operator-auto-music-027-result.json').read_text())
        self.assertTrue(before['music_stability']['stable'])
        self.assertGreater(before['fresh_pick']['timestampMs'],before['original_pick']['timestampMs'])
        self.assertEqual(before['native_xml_sha256'],hashlib.sha256((self.root/before['native_xml']).read_bytes()).hexdigest())
        self.assertIs(result['input_returned'],True)
        self.assertEqual(result['input_invoked_at']['monotonic'],100.125)
        self.assertGreaterEqual(result['input_returned_at']['monotonic'],result['input_invoked_at']['monotonic'])
        self.assertGreaterEqual(result['input_returned_at']['unix'],result['input_invoked_at']['unix'])
        self.assertEqual(len(self.report['actions']),1)

    def test_final_absolute_deadline_refuses_even_a_stable_post_native_pick(self):
        with patch('mv_driver.time.time',side_effect=self.wall_time):
            with self.assertRaisesRegex(RuntimeError,'Operator input end reached before tap'):
                self.env['tap_picked'](self.original,'operator-typed-music',27,dict(QUERY),input_deadline=100.05)
        self.device.shell.assert_not_called();self.assertIsNone(self.env['selected_song'])
        before=json.loads((self.root/'operator-auto-music-027-fresh.json').read_text())
        self.assertTrue(before['music_stability']['stable']);self.assertEqual(before['input_deadline'],100.05)


if __name__ == '__main__':unittest.main()
