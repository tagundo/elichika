"""R9 intended-row identity tests; optional interfaces never own CellVO."""
import copy
import unittest

from native_music_selection import native_music_hit_blocker,native_music_hit_stability
from test_native_music_selection import modeled_pick


def with_nullable_nonintended(*,containing=False):
    pick=modeled_pick();hit=pick['nativeMusicHit'];entry=copy.deepcopy(hit['orderedCells'][0])
    entry.update(ordinal=0,index=125,rectId='other-rect',rectGameObjectId='other-go',typedRowId=None,
                 typedVOId=None,liveMasterId=None,isPlayable=None,associationQualified=False,
                 optionalInterface={'declaredType':'Jigbox.Components.IScrollSelectCell','resolved':True,
                    'isNull':True,'id':None,'type':None,'error':None})
    if not containing:entry['nativeBounds']={'min':{'x':3,'y':3,'z':90},'max':{'x':4,'y':4,'z':90}}
    hit['orderedCells'][0]['ordinal']=1;hit['intended']['ordinal']=1;hit['firstContaining']['ordinal']=1
    hit['orderedCells'].insert(0,entry)
    return pick


class NativeMusicBindingTests(unittest.TestCase):
    def test_nullable_nonintended_active_entry_keeps_geometry_and_allows_later_first_hit(self):
        pick=with_nullable_nonintended()
        self.assertTrue(pick['nativeMusicHit']['cellsComplete'])
        self.assertEqual(len(pick['nativeMusicHit']['orderedCells']),2)
        self.assertIsNone(native_music_hit_blocker(pick,12096))

    def test_unknown_null_vo_entry_containing_first_is_not_skipped(self):
        pick=with_nullable_nonintended(containing=True)
        self.assertIn('FIRST containing cell differs',native_music_hit_blocker(pick,12096))

    def test_optional_interface_identity_is_separate_from_actual_typed_component(self):
        pick=modeled_pick();hit=pick['nativeMusicHit']
        for cell in [hit['orderedCells'][0],hit['intended'],hit['firstContaining']]:
            cell['optionalInterface']={'resolved':True,'isNull':False,'id':'different-interface',
                'type':'Jigbox.Components.IScrollSelectCell','error':None}
        self.assertNotEqual(hit['intended']['optionalInterface']['id'],pick['catalog']['id'])
        self.assertIsNone(native_music_hit_blocker(pick,12096))

    def test_wrong_gameobject_or_component_is_not_recovered_by_equal_geometry(self):
        for key in ('gameObjectId','id'):
            pick=modeled_pick();pick['catalog'][key]='wrong-current-identity'
            self.assertIn('association is absent or ambiguous',native_music_hit_blocker(pick,12096))

    def test_duplicate_native_go_to_typed_row_association_refuses_even_when_first_is_active(self):
        pick=modeled_pick();hit=pick['nativeMusicHit'];duplicate=copy.deepcopy(hit['orderedCells'][0])
        duplicate.update(ordinal=1,index=127,rectId='another-native-rect')
        hit['orderedCells'].append(duplicate)
        self.assertIn('association is absent or ambiguous',native_music_hit_blocker(pick,12096))
        for enumeration in ({'complete':False,'limit':512,'totalObjects':513,'activeObjects':512},
                            {'complete':True,'limit':128,'totalObjects':129,'activeObjects':128},
                            {'complete':True,'limit':512,'totalObjects':1,'activeObjects':1,'error':'read failed'}):
            pick=modeled_pick();pick['nativeMusicHit']['typedRowsEnumeration']=enumeration
            self.assertIn('enumeration is incomplete',native_music_hit_blocker(pick,12096))

    def test_current_vo_identity_and_playability_are_mandatory(self):
        for key,value in (('voId','different-vo'),('voId',None),('active',False),('isPlayable',False),('liveMasterId',12073)):
            pick=modeled_pick();pick['catalog'][key]=value
            self.assertIsNotNone(native_music_hit_blocker(pick,12096))
        pick=modeled_pick();pick['nativeMusicHit']['orderedCells'][0]['associationQualified']=False
        self.assertIn('association is unqualified',native_music_hit_blocker(pick,12096))

    def test_reported_first_must_independently_match_actual_typed_component_and_go(self):
        for key in ('typedRowId','rectGameObjectId','typedVOId'):
            pick=modeled_pick();pick['nativeMusicHit']['firstContaining'][key]='wrong-reported-first'
            self.assertIn('reported first hit differs',native_music_hit_blocker(pick,12096))

    def test_fresh_actual_vo_rebinding_is_not_hidden_by_same_song_or_rectangles(self):
        old=modeled_pick();fresh=copy.deepcopy(old);fresh['catalog']['voId']='new-actual-vo'
        hit=fresh['nativeMusicHit']
        for cell in (hit['orderedCells'][0],hit['intended'],hit['firstContaining']):cell['typedVOId']='new-actual-vo'
        self.assertIsNone(native_music_hit_blocker(old,12096));self.assertIsNone(native_music_hit_blocker(fresh,12096))
        self.assertIn('identities changed',native_music_hit_stability(old,fresh,12096))


if __name__=='__main__':unittest.main()
