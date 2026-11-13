import copy
import json
from pathlib import Path
import tempfile
import unittest

from mv_catalog_audit import SuitCatalogAudit,complete_catalog


def deck():
    return {'screen':{'scene':'LiveMvDeckSelect'},'features':{'mv':{'standingMemberNum':12,
      'deckCells':[{'active':True,'voClass':'LLAS.DeckMemberCustomVO','formationPosition':p,'memberId':p,'suitId':p*100} for p in range(1,13)],'suitCatalogs':[]}}}


def popup(tree,rows):
    result=copy.deepcopy(tree);result['features']['mv']['suitCatalogs']=[{'id':'popup1','active':True,'complete':True,
       'memberId':1,'arrayLength':len(rows),'rows':copy.deepcopy(rows)}];return result


class CatalogAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.audit=SuitCatalogAudit(self.root);self.index=0
    def tearDown(self):self.temporary.cleanup()
    def step(self,tree):
        name=str(self.index)+'.json';self.index+=1;(self.root/name).write_text(json.dumps(tree));return self.audit.step(tree,name,now=self.index)
    def baseline(self,rows):
        action=self.step(deck());self.assertEqual(action['query'],{'role':'suit','formationPosition':1})
        tree=popup(deck(),rows);self.assertEqual(self.step(tree)['kind'],'wait');self.assertEqual(self.step(tree)['kind'],'key')
        self.assertEqual(self.step(deck())['kind'],'audit-ready');self.assertTrue(self.audit.ready)

    def test_complete_catalog_preserves_existing_duplicate_multiplicity(self):
        rows=[{'memberId':1,'suitId':100},{'memberId':1,'suitId':100},{'memberId':1,'suitId':101}]
        self.baseline(rows);self.assertEqual(self.audit.baseline,rows)
        self.audit.start_after();self.assertEqual(self.step(deck())['kind'],'pickmv')
        tree=popup(deck(),list(reversed(rows)));self.step(tree);self.step(tree);self.step(deck())
        self.assertTrue(self.audit.done);self.assertEqual(self.audit.result()['before_count'],3)

    def test_post_mv_extra_clone_entry_does_not_pass_even_when_id_already_exists(self):
        rows=[{'memberId':1,'suitId':100}];self.baseline(rows);self.audit.start_after();self.step(deck())
        tree=popup(deck(),rows*2);self.step(tree)
        with self.assertRaisesRegex(RuntimeError,'multiplicities'):self.step(tree)
        self.assertFalse(self.audit.done)

    def test_catalog_inspection_cannot_silently_change_the_deck(self):
        rows=[{'memberId':1,'suitId':100}];self.step(deck());self.step(popup(deck(),rows));self.step(popup(deck(),rows))
        changed=deck();changed['features']['mv']['deckCells'][1]['suitId']=999
        with self.assertRaisesRegex(RuntimeError,'entire original'):self.step(changed)

    def test_partial_or_wrong_character_catalog_is_never_complete(self):
        tree=popup(deck(),[{'memberId':1,'suitId':100}]);tree['features']['mv']['suitCatalogs'][0]['arrayLength']=2
        self.assertIsNone(complete_catalog(tree,1))
        tree=popup(deck(),[{'memberId':2,'suitId':100}]);self.assertIsNone(complete_catalog(tree,1))


if __name__=='__main__':unittest.main()
