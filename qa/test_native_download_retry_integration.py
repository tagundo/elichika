"""Host-only integration tests: retained modal -> durable intent -> one tap."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import native_download_driver as driver
from native_download_errors import NativeDownloadError, OptionalOneNativeRetry, FixedEnds, exact_error

ROOT=Path(__file__).parent


class RetryIntegrationTests(unittest.TestCase):
    def setup_context(self,evidence,*,enabled=True):
        clock=SimpleNamespace(now=300.,monotonic=lambda:clock.now)
        identity={'pid':1921,'start_ticks':'46403'}
        metadata=json.loads((ROOT/'fixtures/actual-v18-native-ocr-031.json').read_text())
        png=(ROOT/'fixtures/actual-v18-native-ocr-031.png').read_bytes()
        state={'identity':dict(identity),'clock':clock,'second_metadata':copy.deepcopy(metadata),
               'tap_error':False,'commands':[],'diagnostics':[],'save':0,'capture_count':0}
        def write(label,meta):
            (evidence/(label+'.json')).write_text(json.dumps(meta))
            (evidence/(label+'.png')).write_bytes(png)
        write('first',metadata)
        def capture():
            state['capture_count']+=1;clock.now+=.2
            write('second',state['second_metadata'])
            match=exact_error(state['second_metadata'],png,(720,1280))
            return ({'state':'native-game-download-error','observations':{'game_download_error':match}},
                    metadata['surface'],'second',clock.now)
        def shell(*args):
            # The persisted, fully flushed intent must precede any input.
            intent=json.loads((evidence/'native-download-retry-intent.json').read_text())
            self.assertFalse(intent['input_performed'])
            self.assertEqual(intent['identity'],identity)
            self.assertTrue((evidence/'native-download-error-001.json').is_file())
            self.assertTrue(policy.spent)
            state['commands'].append(args)
            if state['tap_error']:raise RuntimeError('host model input failure')
        def save():state['save']+=1
        diagnostics=SimpleNamespace(sample=lambda **kwargs:state['diagnostics'].append(kwargs))
        context={'args':SimpleNamespace(evidence=evidence),'report':{'actions':[]},'lifetime':lambda:state['identity'],
            'identity':lambda label:{**state['identity'],'maps_sha256':'not-lifetime-identity'},
            'save':save,'device':SimpleNamespace(shell=shell),'started':0.,'network_diagnostics':diagnostics}
        match=exact_error(metadata,png,(720,1280))
        first=({'state':'native-game-download-error','observations':{'game_download_error':match}},
               metadata['surface'],'first',clock.now)
        policy=OptionalOneNativeRetry(explicitly_enabled=enabled)
        ends=FixedEnds(0.,170.,2400.,1970.)
        return context,first,capture,policy,ends,state

    def test_one_tap_only_after_synced_intent_and_original_error(self):
        with tempfile.TemporaryDirectory() as folder:
            context,first,capture,policy,ends,state=self.setup_context(Path(folder))
            calls=[];real_fsync=driver.os.fsync
            def fsync(fd):calls.append(fd);return real_fsync(fd)
            with patch.object(driver,'time',state['clock']),patch.object(driver.os,'fsync',fsync):
                driver.handle_download_error(context,first,capture,policy,ends)
            self.assertEqual(state['commands'],[('input','tap','489','758')])
            self.assertGreaterEqual(len(calls),6)
            self.assertEqual(state['diagnostics'],[{'force':True,'reason':'download-error'}])
            self.assertTrue(context['report']['native_download_retry']['ordinary_input_returned'])
            intent=json.loads((Path(folder)/'native-download-retry-intent.json').read_text())
            self.assertEqual((intent['original_bulk_end'],intent['original_overall_end']),(1970.,2400.))
            before=(Path(folder)/'native-download-retry-intent.json').read_bytes()
            # A recurring modal is a specific failure; no second pair or input.
            with patch.object(driver,'time',state['clock']),self.assertRaisesRegex(NativeDownloadError,'recurred'):
                driver.handle_download_error(context,first,capture,policy,ends)
            self.assertEqual(len(state['commands']),1)
            self.assertEqual(state['capture_count'],1)
            self.assertEqual((Path(folder)/'native-download-retry-intent.json').read_bytes(),before)
            self.assertTrue((Path(folder)/'native-download-error-002.json').is_file())

    def test_disabled_and_wrong_second_caption_never_tap(self):
        for mode in ('disabled','wrong-caption','old-capture'):
            with tempfile.TemporaryDirectory() as folder:
                context,first,capture,policy,ends,state=self.setup_context(Path(folder),enabled=mode!='disabled')
                if mode=='wrong-caption':state['second_metadata']['button_words'][0]['text']='Confirm'
                if mode=='old-capture':state['clock'].now+=9
                with patch.object(driver,'time',state['clock']),self.assertRaises(NativeDownloadError):
                    driver.handle_download_error(context,first,capture,policy,ends)
                self.assertEqual(state['commands'],[])
                self.assertFalse((Path(folder)/'native-download-retry-intent.json').exists())
                self.assertTrue((Path(folder)/'native-download-error-001.json').exists())

    def test_existing_intent_never_overwritten_or_tapped(self):
        with tempfile.TemporaryDirectory() as folder:
            context,first,capture,policy,ends,state=self.setup_context(Path(folder))
            path=Path(folder)/'native-download-retry-intent.json';path.write_bytes(b'EXISTING')
            with patch.object(driver,'time',state['clock']),self.assertRaises(FileExistsError):
                driver.handle_download_error(context,first,capture,policy,ends)
            self.assertTrue(policy.spent);self.assertEqual(path.read_bytes(),b'EXISTING')
            self.assertEqual(state['commands'],[])

    def test_lifetime_or_freshness_changed_after_flush_never_taps(self):
        for mode in ('lifetime','freshness','fixed-end'):
            with tempfile.TemporaryDirectory() as folder:
                context,first,capture,policy,ends,state=self.setup_context(Path(folder))
                original_record=driver.durable_record
                def record(path,payload):
                    original_record(path,payload)
                    if Path(path).name=='native-download-retry-intent.json':
                        if mode=='lifetime':state['identity']={'pid':1921,'start_ticks':'999'}
                        elif mode=='freshness':state['clock'].now+=9
                        else:state['clock'].now=ends.bulk_end
                with patch.object(driver,'time',state['clock']),patch.object(driver,'durable_record',record),self.assertRaises(NativeDownloadError):
                    driver.handle_download_error(context,first,capture,policy,ends)
                self.assertTrue(policy.spent)
                self.assertTrue((Path(folder)/'native-download-retry-intent.json').exists())
                self.assertEqual(state['commands'],[])

    def test_failed_input_preserves_spent_intent_and_specific_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            context,first,capture,policy,ends,state=self.setup_context(Path(folder));state['tap_error']=True
            with patch.object(driver,'time',state['clock']),self.assertRaisesRegex(NativeDownloadError,'spent intent'):
                driver.handle_download_error(context,first,capture,policy,ends)
            receipt=json.loads((Path(folder)/'native-download-retry-input-result.json').read_text())
            self.assertTrue(receipt['ordinary_input_attempted'])
            self.assertFalse(receipt['ordinary_input_returned'])
            self.assertEqual(receipt['error_class'],'RuntimeError')
            self.assertTrue(policy.spent)
            self.assertEqual(len(state['commands']),1)


if __name__=='__main__':unittest.main()
