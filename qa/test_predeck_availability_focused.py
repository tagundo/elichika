"""Focused host boundary tests; no Frida or app runtime is loaded."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from predeck_availability import (classified_semantic_refusal,music_selection_blocker,
    music_selection_witness,semantic_pick_refusal)


class InjectedRPCException(Exception):
    """The actual RPC type is an injected boundary, never a message heuristic."""


class InjectedDeadline(BaseException):
    pass


QUERY={'kind':'text','id':'251586','path':'EntryPoint/Canvas/SafeArea/RightArea/Info/ButtonContainer/MvBtnDownload/MvBtnDownloadLabel',
       'text':'Download','requireHitTest':True}


def payload(error='No active semantic UI target',**changes):
    result={'error':error,'query':copy.deepcopy(QUERY),'matches':[],
            'screen':{'scene':'LiveMusicSelect','frame':13548},
            'hitTest':{'available':True},'diagnostics':[]}
    result.update(changes)
    return result


def rpc_error(value,suffix='\n    at choose (/script1.js:4508)\n    at deliver (/script1.js:3542)'):
    return InjectedRPCException('Error: '+json.dumps(value,separators=(',',':'))+suffix)


class RefusalClassificationTests(unittest.TestCase):
    def classify(self,error,**changes):
        options={'rpc_exception_type':InjectedRPCException,'predeck':True};options.update(changes)
        return classified_semantic_refusal(error,QUERY,**options)

    def test_exact_legacy_rpc_refusal_and_new_error_code_are_observation_only(self):
        fixtures=Path(__file__).parent/'fixtures'/'actual-gl-pick-refusal'
        provenance=json.loads((fixtures/'provenance.json').read_text())
        for member in provenance['members']:
            self.assertEqual(hashlib.sha256((fixtures/member['name']).read_bytes()).hexdigest(),member['sha256'])
        actual=json.loads((fixtures/'pick-refusal.json').read_text())
        observed=self.classify(InjectedRPCException(actual['error_message']))
        self.assertEqual(observed['pick_snapshot']['screen']['frame'],13548)
        previous=json.loads((fixtures/'mv-ui-028.json').read_text())
        self.assertNotEqual(previous['screen']['frame'],observed['pick_snapshot']['screen']['frame'])
        for changes in ({},{'errorCode':'SEMANTIC_TARGET_UNAVAILABLE'}):
            result=self.classify(rpc_error(payload(**changes)))
            self.assertEqual(result['query'],QUERY)
            self.assertEqual(result['pick_snapshot']['matches'],[])
            self.assertIs(result['input_performed'],False)
            self.assertNotIn('input',result)

    def test_ambiguity_requires_nonempty_matches_and_matching_error_code(self):
        data=payload('Ambiguous active semantic UI targets',matches=[{'id':'one'},{'id':'two'}],
                     errorCode='SEMANTIC_TARGET_AMBIGUOUS')
        self.assertIsNotNone(self.classify(rpc_error(data)))
        for changed in (dict(data,matches=[]),dict(data,errorCode='SEMANTIC_TARGET_UNAVAILABLE'),
                        payload(matches=[{'id':'impossible'}])):
            self.assertIsNone(self.classify(rpc_error(changed)))

    def test_type_and_predeck_gate_reject_valid_looking_other_exceptions(self):
        valid=rpc_error(payload())
        for error in (RuntimeError(str(valid)),TimeoutError(str(valid)),InjectedDeadline(str(valid))):
            self.assertIsNone(self.classify(error))
        self.assertIsNone(self.classify(valid,predeck=False))

    def test_unknown_malformed_or_mismatched_payload_cannot_be_availability(self):
        variants=[payload(error=value) for value in ([],{},None,True,'Dispatcher failed')]
        variants += [payload(query=dict(QUERY,id='reused')),payload(matches={}),payload(screen=[]),
                     payload(hitTest=[]),payload(diagnostics={}),{'error':'No active semantic UI target'}]
        for data in variants:
            with self.subTest(data=data):self.assertIsNone(self.classify(rpc_error(data)))
        for raw in ('No active semantic UI target','Error: invalid JSON','Error: '+json.dumps(payload())+'\nnot a stack',
                    'TypeError: '+json.dumps(payload()),'Error: '+('x'*(512*1024))):
            with self.subTest(prefix=raw[:50]):self.assertIsNone(self.classify(InjectedRPCException(raw)))


class MusicSelectionWitnessTests(unittest.TestCase):
    def row(self,current=12074,decided=12096,**changes):
        value={'active':True,'currentSelectedCellVO':{'liveMasterId':current},
               'decidedCellVO':{'liveMasterId':decided}}
        value.update(changes);return value

    def test_current_and_decided_are_independent_without_readiness_inference(self):
        witness=music_selection_witness([self.row()],12074)
        self.assertEqual(witness['observed_current_selected_song_id'],12074)
        self.assertEqual(witness['observed_decided_song_id'],12096)
        self.assertIs(witness['current_selected_matches_requested'],True)
        self.assertFalse(any(key in witness for key in ('ready','downloaded','complete','pass','status')))
        tree={'screen':{'scene':'LiveMusicSelect'},'features':{'mv':{'musicSelection':[self.row()]}}}
        self.assertIsNone(music_selection_blocker(tree,12074))
        self.assertIn('currentSelectedCellVO',music_selection_blocker(tree,12096))

    def test_missing_ambiguous_malformed_or_boolean_witness_never_matches(self):
        variants=[None,[],[self.row(active=False)],[self.row(),self.row()],
                  [self.row(currentSelectedCellVO=[])],[self.row(currentSelectedCellVO='bad')],
                  [self.row(current=None)],[self.row(current=True)]]
        for values in variants:
            with self.subTest(values=values):
                result=music_selection_witness(values,12074)
                self.assertIs(result['current_selected_matches_requested'],False)
        self.assertIsNone(music_selection_blocker({'screen':{'scene':'Home'}},12074))
        self.assertIsNone(music_selection_blocker({'screen':{'scene':'LiveMusicSelect'}},None))


if __name__=='__main__':unittest.main()
