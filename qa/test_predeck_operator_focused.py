"""Injected host tests of operator capture/input/deadline boundaries only."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from predeck_bridge import Refusal
from predeck_operator import NoInputObserved,PredeckOperator,native_xml_reference

PACKAGE='com.klab.lovelive.allstars.global'
ACTIVITY=PACKAGE+'.GlobalUnsafeMainActivity'
ROW='EntryPoint/Canvas/MusicScrollView/Viewport/Content/cell124'
SCROLL='EntryPoint/Canvas/MusicScrollView'
PNG=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'+struct.pack('>II',720,1280)


class Clock:
    def __init__(self):self.now=100.
    def __call__(self):return self.now
    def sleep(self,seconds):self.now+=seconds


class FakeAPI:
    def __init__(self,*args,**kwargs):self.bound=[];self.closed=0;self.sealed=0
    def __call__(self,*args,**kwargs):raise AssertionError('No transport is allowed in operator unit tests')
    def bind_deadline(self,end):self.bound.append(end)
    def close_window(self):self.closed+=1
    def seal(self):self.sealed+=1


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.clock=Clock();self.identity={'pid':123,'start_ticks':'456'}
        self.song=12074;self.validated=False;self.calls=[]
        flags={'active':True,'visible':True,'enabled':True,'groupsInteractable':True,'blocksRaycasts':True,
               'hit':{'available':True,'hittable':True}}
        self.title=dict(flags,id='title-124',kind='text',name='Title',path=ROW+'/Title',
                        text='Full official song caption',label='Full official song caption')
        self.scroll_node=dict(flags,id='scroll',kind='scroll',name='MusicScrollView',path=SCROLL,
                              scroll={'vertical':True,'horizontal':False})
        self.tree={'screen':{'scene':'LiveMusicSelect','width':720,'height':1280},'truncated':False,
                   'nodes':[self.title,self.scroll_node],
                   'features':{'mv':{'musicRows':[{'liveMasterId':12074,'isPlayable':True,
                     'target':dict(flags,id='row-124',path=ROW)}]}}}
        outer=self
        class Native:
            def __call__(self,label):
                self.last_path=label+'.xml';(outer.root/self.last_path).write_bytes(b'<hierarchy><node package="owned"/></hierarchy>')
                return [{'package':PACKAGE,'class':'android.view.SurfaceView',
                         'bounds':{'left':0,'top':0,'right':720,'bottom':1280}}]
        self.native=Native()
        self.exports=SimpleNamespace(snapshot=lambda options:copy.deepcopy(self.tree),
                                     pickmv=self.pickmv)
        self.context={'args':SimpleNamespace(evidence=self.root,max_seconds=2400),
            'package':PACKAGE,'started':0,'report':{},'lifetime':lambda:dict(self.identity),
            'agent':lambda:SimpleNamespace(exports_sync=self.exports),'native':self.native,
            'device':SimpleNamespace(adb=Mock(return_value=PNG),shell=Mock(return_value=
                'mResumedActivity: ActivityRecord{owned '+PACKAGE+'/.GlobalUnsafeMainActivity}')),
            'absolute_phase_deadline':Mock(),'phase_deadline':Mock()}
        self.pick=Mock();self.tap=Mock(side_effect=self.perform_input);self.scroll=Mock(side_effect=self.perform_input)
        self.intent=Mock()
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'12345','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40}):
            self.operator=PredeckOperator(self.context,rpc=lambda fn,**kwargs:fn(),semantic_pick=self.pick,
                tap=self.tap,scroll=self.scroll,typed_scroll=self.typed_scroll,scope=self.scope,
                on_song_intent=self.intent,clock=self.clock,sleep=self.clock.sleep,api_factory=FakeAPI)
        self.operator.deadline=190.

    def scope(self,tree):
        return {'deck_validated':self.validated,'cases_started':False,'phase':'baseline','stage':'mv',
                'selected_song_intent':self.song}

    def typed_scroll(self,tree,context):
        if context!='music':raise ValueError('Absent typed context')
        return next(node for node in tree['nodes'] if node.get('id')=='scroll')

    def pickmv(self,query):
        self.calls.append(('pickmv',copy.deepcopy(query)))
        return {'screen':self.tree['screen'],'target':self.tree['features']['mv']['musicRows'][0]['target']}

    def perform_input(self,*args,**kwargs):
        self.assertEqual(kwargs['input_deadline'],self.operator.deadline)
        self.assertLess(self.clock(),kwargs['input_deadline'])
        prefix=kwargs['proof_prefix'];name=self.native.last_path;raw=(self.root/name).read_bytes()
        (self.root/(prefix+'-fresh.json')).write_text(json.dumps({'native_xml':name,
            'native_xml_sha256':hashlib.sha256(raw).hexdigest()}))
        (self.root/(prefix+'-result.json')).write_text(json.dumps({'input_returned':True}))
        return True

    def offered_title(self):
        captured=self.operator.capture()
        return next(target for target in captured['targets'] if target['id']=='title-124')

    def test_capture_binds_full_typed_song_caption_and_retains_actual_native_xml(self):
        target=self.offered_title()
        self.assertEqual(json.loads(target['text']),{'liveMasterId':12074,'caption':'Full official song caption'})
        native=[ref for ref in self.operator.last_proofs if ref['path'].endswith('.xml')]
        self.assertEqual(len(native),1)
        self.assertEqual(native[0],native_xml_reference(self.context))
        self.assertEqual(native[0]['sha256'],hashlib.sha256((self.root/native[0]['path']).read_bytes()).hexdigest())
        self.assertEqual(self.operator.targets[(target['id'],target['path'])]['query'],{'role':'music','liveMasterId':12074})

    def test_unrecognized_scroll_descendant_and_unofficial_song_are_not_offered(self):
        self.tree['features']['mv']['musicRows'][0]['liveMasterId']=10001
        self.tree['nodes'].append(dict(self.title,id='unrecognized',path=SCROLL+'/unknown/Title'))
        capture=self.operator.capture()
        self.assertFalse(any(target['id'] in ('title-124','unrecognized') for target in capture['targets']))
        self.assertEqual(capture['targets'][0]['actions'],['scroll_forward','scroll_backward'])

    def test_execute_uses_bridge_capture_without_duplicate_and_retains_final_native_xml(self):
        self.tree['timestampMs']=123456
        target=self.offered_title()
        with patch.object(self.operator,'capture',wraps=self.operator.capture) as capture:
            self.operator.capture()  # Bridge's fresh validated capture.
            sequence=self.operator.sequence
            result=self.operator.execute({'target':{'action':'tap'}},target,deadline=190.)
        capture.assert_called_once()
        self.assertEqual(self.operator.sequence,sequence+1)
        self.assertIs(result['input_returned'],True)
        self.assertEqual(self.calls,[('pickmv',{'role':'music','liveMasterId':12074})])
        self.intent.assert_called_once_with(12074)
        self.assertEqual(self.tap.call_args.kwargs['input_deadline'],190.)
        for ref in result['proof_refs']:
            self.assertEqual(hashlib.sha256((self.root/ref['path']).read_bytes()).hexdigest(),ref['sha256'])
        timing=[ref for ref in result['proof_refs'] if ref['path'].endswith('-timing.json')]
        self.assertEqual(len(timing),1)
        recorded=json.loads((self.root/timing[0]['path']).read_text())
        self.assertIs(recorded['completed'],True);self.assertIsNone(recorded['error_class'])
        self.assertEqual(recorded['deadline'],190.)
        self.assertEqual(recorded['last_observed_snapshot_timestamp_ms'],123456)
        self.assertGreaterEqual(recorded['completed_at']['monotonic'],recorded['started_at']['monotonic'])
        self.assertGreaterEqual(recorded['completed_at']['unix'],recorded['started_at']['unix'])

    def test_recycled_row_id_or_changed_caption_refuses_before_input(self):
        for change in ('song','caption'):
            with self.subTest(change=change):
                self.tree['features']['mv']['musicRows'][0]['liveMasterId']=12074
                self.tree['nodes'][0]['text']='Full official song caption'
                target=self.offered_title()
                if change=='song':self.tree['features']['mv']['musicRows'][0]['liveMasterId']=12096
                else:self.tree['nodes'][0]['text']='Changed full caption'
                self.operator.capture()  # Bridge refreshes before execute.
                with self.assertRaisesRegex(Refusal,'Fresh offered semantics changed'):
                    self.operator.execute({'target':{'action':'tap'}},target,deadline=190.)
        self.tap.assert_not_called();self.intent.assert_not_called()

    def test_semantic_refusal_spends_no_input_and_deadline_is_forwarded_for_scroll(self):
        button=dict(self.title,id='download',name='MvBtnDownloadLabel',path='EntryPoint/MvBtnDownloadLabel',text='Download')
        self.tree['nodes'].append(button)
        capture=self.operator.capture();target=next(t for t in capture['targets'] if t['id']=='download')
        self.pick.return_value=None
        with self.assertRaises(NoInputObserved):self.operator.execute({'target':{'action':'tap'}},target,deadline=190.)
        self.tap.assert_not_called();self.intent.assert_not_called()
        target=next(t for t in self.operator.capture()['targets'] if t['id']=='scroll')
        result=self.operator.execute({'target':{'action':'scroll_backward'}},target,deadline=190.)
        self.assertIs(result['input_returned'],True)
        self.assertEqual(self.scroll.call_args.kwargs['direction'],'backward')
        self.assertEqual(self.scroll.call_args.kwargs['input_deadline'],190.)

    def test_capture_crossing_fixed_end_and_validated_deck_never_inputs(self):
        def late_snapshot(options):self.clock.now=190.;return copy.deepcopy(self.tree)
        self.exports.snapshot=late_snapshot
        with self.assertRaisesRegex(Refusal,'Operator end reached'):self.operator.capture()
        self.tap.assert_not_called();self.context['device'].adb.assert_not_called()
        self.clock.now=100.;self.exports.snapshot=lambda options:copy.deepcopy(self.tree);self.validated=True
        self.assertEqual(self.operator.capture(),{'deck_validated':True})
        self.assertTrue(self.operator.closed);self.assertTrue(self.operator.bridge.closed)
        self.assertEqual(self.operator.api.sealed,1)

    def test_wait_binds_end_before_offer_and_command_wait_does_not_renew_or_signal_progress(self):
        self.operator.deadline=None;events=[]
        bridge=SimpleNamespace(offers=0,end=2400.,consumed=set(),offer=Mock(),poll_once=Mock(),
                               close_offer_without_input=Mock())
        offer=SimpleNamespace(commit='b'*40)
        def offered(*,deadline):
            events.append(('offer',deadline,self.operator.deadline,list(self.operator.api.bound)))
            self.clock.now+=10;return offer
        bridge.offer.side_effect=offered;self.operator.bridge=bridge
        self.operator.capture=Mock(side_effect=lambda:None)
        class Stagnant(RuntimeError):pass
        def observe(tree):raise Stagnant('Original semantic stagnation')
        observe.progressed=False
        with self.assertRaisesRegex(Stagnant,'Original semantic stagnation'):self.operator.wait(observe,Stagnant)
        self.assertEqual(events,[('offer',280.,280.,[280.])])
        self.assertEqual(self.operator.api.bound,[280.]);self.assertEqual(self.operator.api.closed,1)
        self.assertIsNone(self.operator.deadline);bridge.close_offer_without_input.assert_not_called()
        self.assertGreater(bridge.poll_once.call_count,0);self.assertEqual(self.clock(),280.)
        self.context['absolute_phase_deadline'].assert_called_once_with(280.,'Predeck operator fixed window ended')

    def test_wait_polls_before_expensive_capture_can_spend_fixed_window(self):
        self.operator.deadline=None;events=[];offer=SimpleNamespace(commit='b'*40)
        bridge=SimpleNamespace(offers=0,end=2400.,consumed=set(),
            offer=Mock(side_effect=lambda **kwargs:(events.append(('offer',kwargs['deadline'])) or offer)),
            poll_once=Mock(side_effect=lambda offered:events.append(('poll',self.clock()))),
            close_offer_without_input=Mock())
        self.operator.bridge=bridge
        class NativeRunDeadline(BaseException):pass
        class Stagnant(RuntimeError):pass
        def capture():
            events.append(('capture',self.clock()));self.clock.now=280.
            raise NativeRunDeadline('Predeck operator fixed window ended')
        self.operator.capture=Mock(side_effect=capture);observe=Mock()
        with self.assertRaisesRegex(Stagnant,'No semantic predeck progress within the fixed operator window'):
            self.operator.wait(observe,Stagnant)
        self.assertEqual(events,[('offer',280.),('poll',100.),('capture',100.)])
        bridge.poll_once.assert_called_once_with(offer);self.operator.capture.assert_called_once()
        observe.assert_not_called();bridge.close_offer_without_input.assert_not_called()
        self.assertEqual(self.operator.api.bound,[280.]);self.assertEqual(self.operator.api.closed,1)
        self.assertIsNone(self.operator.deadline)

    def test_core_operator_hook_begins_at_fifteen_seconds_and_closes_for_cases(self):
        source=ast.parse((Path(__file__).parent/'native_mv_focus.py').read_text())
        hooks=[node for node in ast.walk(source) if isinstance(node,ast.If) and
               any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
                   isinstance(call.func.value,ast.Name) and call.func.value.id=='operator' and call.func.attr=='wait'
                   for child in node.body for call in ast.walk(child))]
        # The deepest condition owns the trigger, rather than an enclosing stage.
        condition=min(hooks,key=lambda node:len(list(ast.walk(node))))
        code=compile(ast.Expression(condition.test),'<predeck-hook-policy>','eval')
        for elapsed,closed,cases,stage,expected in [(14.999,False,False,'mv',False),
                (15,False,False,'mv',True),(15,True,False,'mv',False),
                (15,False,True,'mv',False),(15,False,False,'Title',False)]:
            value=eval(code,{'operator':SimpleNamespace(closed=closed),
                'progress_guard':SimpleNamespace(elapsed=elapsed),'stage':stage,'tree':{},
                'operator_scope':lambda tree:{'cases_started':cases}})
            self.assertIs(bool(value),expected)


if __name__=='__main__':unittest.main()
