"""Pure actual-fixture and adverse-input tests; no adb, Go, OCR, or network."""
import copy
import io
import json
from pathlib import Path
import subprocess
import unittest

from PIL import Image
import jp_capture_guard as guard
import jp_short_capture as driver
from native_capture_support import parse_native_nodes, title_caption

ROOT=Path(__file__).parent
PNG=(ROOT/'fixtures/actual-jp-chooser.png').read_bytes()
XML=(ROOT/'fixtures/actual-jp-game-window.xml').read_bytes()
SERVICES=(ROOT/'fixtures/actual-jp-services-dialog.xml').read_bytes()
IDENTITY={'pid':1234,'start_ticks':'987654'}


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def frame(*,identifier='capture-1',at=95,native_at=94.9,raw=PNG,native=XML):
    image=guard.image_of(raw)
    return {'id':identifier,'png_bytes':raw,'png_sha256':guard.digest(raw),
        'native_xml':native,'native_sha256':guard.digest(native),'native_at':native_at,
        'captured_at':at,'identity_before':dict(IDENTITY),'identity_after':dict(IDENTITY),
        'surface':guard.native_surface(native,image.size),'frame':list(image.size)}


def pair():
    return frame(),frame(identifier='capture-2',at=96,native_at=95.9)


class GeometryTests(unittest.TestCase):
    def test_actual_header_footer_and_current_blank_gutter(self):
        value=guard.chooser_geometry(PNG)
        self.assertIsNotNone(value)
        self.assertEqual(value['modal_bounds'],[107,450,613,829])
        self.assertEqual(value['start'][0],value['end'][0])
        self.assertTrue(20<=value['start'][1]-value['end'][1]<=48)
        self.assertLess(value['end'][1],value['start'][1])
        self.assertNotIn('confidence',value)

    def test_translated_geometry_has_current_coordinates(self):
        image=Image.new('RGB',(720,1280),'black')
        image.paste(guard.image_of(PNG).crop((107,450,613,829)),(50,300))
        value=guard.chooser_geometry(png(image))
        self.assertEqual(value['modal_bounds'],[50,300,556,679])
        self.assertEqual(value['start'][0],guard.chooser_geometry(PNG)['start'][0]-57)

    def test_altered_header_or_footer_or_inconsistent_alignment_rejected(self):
        for box in (guard.CHOOSER_HEADER,guard.CHOOSER_FOOTER):
            image=guard.image_of(PNG);image.putpixel((box[0]+1,box[1]+1),(0,0,0))
            self.assertIsNone(guard.chooser_geometry(png(image)))
        image=guard.image_of(PNG);footer=image.crop(guard.CHOOSER_FOOTER)
        image.paste((0,0,0),guard.CHOOSER_FOOTER);image.paste(footer,(108,780))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_duplicate_strips_rejected(self):
        image=guard.image_of(PNG)
        image.paste(image.crop(guard.CHOOSER_HEADER),(107,10))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_ambiguous_or_covered_gutter_rejected(self):
        image=guard.image_of(PNG)
        geometry=guard.chooser_geometry(PNG);left,right=geometry['gutter']
        top,bottom=geometry['content_bounds'][1::2]
        image.paste((0,0,0),(left,top,right,bottom))
        self.assertIsNone(guard.chooser_geometry(png(image)))

    def test_changed_body_does_not_pretend_to_recognize_captions(self):
        image=guard.image_of(PNG);image.paste((255,255,255),(184,636,425,658))
        result=guard.chooser_geometry(png(image))
        self.assertIsNotNone(result)
        self.assertEqual(result['scope'],'Diagnostic scroll geometry only; no caption/radio identity or download authorization')

    def test_current_native_surface_accepts_new_rotation_but_not_overlay(self):
        native=XML.replace(b'rotation="3"',b'rotation="0"')
        self.assertEqual(guard.native_surface(native,(720,1280)),dict(left=0,top=0,right=720,bottom=1280))
        for raw in (XML.replace(b'Game view',b'Other view'),
                XML.replace(b'enabled="true" focusable="true" focused="true"',b'enabled="false" focusable="true" focused="true"'),
                XML.replace(b'focused="true" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][720,1280]"',
                    b'focused="true" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[1,1][10,10]"'),
                XML.replace(b'clickable="false"',b'clickable="true"',1),
                XML.replace(guard.PACKAGE.encode(),b'other.package')):
            with self.subTest(raw=raw[:30]),self.assertRaises(guard.StopCapture):guard.native_surface(raw,(720,1280))

    def test_clipped_or_mismatched_surface_rejected(self):
        with self.assertRaises(guard.StopCapture):guard.native_surface(XML,(1280,720))


class FreshnessBudgetTests(unittest.TestCase):
    def reserve(self,frames=None,budget=None,persist=None,**changes):
        options=dict(identity=IDENTITY,current_identity=IDENTITY,now=100,persist=persist or (lambda intent:None))
        options.update(changes)
        return (budget or guard.ScrollBudget()).reserve(*(frames or pair()),**options)

    def test_two_only_durable_reservations(self):
        budget=guard.ScrollBudget();records=[]
        self.reserve(budget=budget,persist=records.append);self.reserve(budget=budget,persist=records.append)
        with self.assertRaises(guard.StopCapture):self.reserve(budget=budget,persist=records.append)
        self.assertEqual([item['attempt'] for item in records],[1,2])
        self.assertTrue(all(item['kind']=='diagnostic-chooser-upward-scroll' for item in records))

    def test_persist_failure_spends_attempt_and_never_returns_intent(self):
        budget=guard.ScrollBudget()
        def fail(intent):raise OSError('cannot persist')
        with self.assertRaises(OSError):self.reserve(budget=budget,persist=fail)
        self.assertEqual(budget.attempts,1)

    def test_oldest_native_png_future_nonfinite_and_repeated_captures_rejected(self):
        for key,value in (('native_at',91.9),('captured_at',91.9),('native_at',101),
                ('captured_at',float('nan')),('captured_at',True),('id','capture-2')):
            frames=pair();frames[0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(guard.StopCapture):self.reserve(frames)

    def test_changed_lifetime_or_digest_rejected(self):
        for key,value in (('identity_after',{'pid':1234,'start_ticks':'987655'}),
                ('png_sha256','0'*64),('native_sha256','0'*64),
                ('surface',dict(left=0,top=0,right=719,bottom=1280))):
            frames=pair();frames[0][key]=value
            with self.subTest(key=key),self.assertRaises(guard.StopCapture):self.reserve(frames)
        with self.assertRaises(guard.StopCapture):self.reserve(current_identity={'pid':1235,'start_ticks':'987654'})

    def test_geometry_changed_between_fresh_captures_rejected(self):
        frames=pair();image=guard.image_of(PNG)
        image.paste((0,0,0),(108,452,110,454));raw=png(image)
        frames[1].update(png_bytes=raw,png_sha256=guard.digest(raw))
        with self.assertRaises(guard.StopCapture):self.reserve(frames)


class BindingAndNativeTests(unittest.TestCase):
    def binding(self):
        return (json.loads((ROOT/'frozen-fixtures.json').read_text()),
            json.loads((ROOT/'jp-capture-profile.json').read_text()),
            {'fixture_region':'JP','fixture_language':'ja','server_fixture':{'source_sha':driver.SOURCE}})

    def test_source_selected_JP_and_C10_only(self):
        driver.validate_binding(*self.binding())
        for key,value in (('fixture_region','GL'),('fixture_language','en')):
            fixture,profile,receipt=self.binding();receipt[key]=value
            with self.assertRaises(guard.StopCapture):driver.validate_binding(fixture,profile,receipt)
        fixture,profile,receipt=self.binding();fixture['clients']['GL']=fixture['clients']['JP']
        with self.assertRaises(guard.StopCapture):driver.validate_binding(fixture,profile,receipt)

    def test_exact_actual_JP_services_dialog_only(self):
        nodes=parse_native_nodes(SERVICES)
        self.assertEqual(guard.missing_services(nodes)['name'],'android:id/button1')
        for mutation in ('wrong-message','foreign-overlay','extra-button','outside-panel'):
            changed=copy.deepcopy(nodes)
            if mutation=='wrong-message':next(node for node in changed if node['name']=='android:id/message')['text']='other'
            elif mutation=='foreign-overlay':changed.append(dict(changed[0],package='other.package'))
            elif mutation=='extra-button':changed.append(dict(guard.missing_services(nodes),name='android:id/button2',text='No'))
            else:next(node for node in changed if node['name']=='android:id/button1')['bounds']['right']=1000
            with self.subTest(mutation=mutation):self.assertIsNone(guard.missing_services(changed))

    def test_native_settings_foreign_package_overlay_rejected(self):
        nodes=parse_native_nodes(XML)
        guard.require_JP_settings(nodes)
        nodes.append(dict(nodes[0],package='other.package',text='English',clickable=True))
        with self.assertRaises(guard.StopCapture):guard.require_JP_settings(nodes)

    def test_no_asset_GET_including_failed_requests(self):
        self.assertTrue(guard.asset_get_seen(b'[GIN] 2026 | 200 | 1ms | GET "/static/asset"\n'))
        self.assertTrue(guard.asset_get_seen(b'[GIN] 2026 | 404 | 1ms | GET "/static/asset"\n'))
        self.assertFalse(guard.asset_get_seen(b'[GIN] 2026 | 200 | POST "/login/login"\n'))
        self.assertFalse(guard.asset_get_seen(b'[GIN] 2026 | 200 | GET "/staticology/test"\n'))

    def test_actual_JP_title_grounds_English_caption_not_coordinates(self):
        original=json.loads((ROOT/'fixtures/actual-jp-title-caption.json').read_text())
        self.assertTrue(any(node.get('text')=='TAP TO START' for node in original['nodes']))
        words=[{'text':text,'confidence':95,'bounds':[x,100,x+10,110]}
            for text,x in [('TAP',10),('TO',25),('START',40)]]
        self.assertEqual(title_caption(words)['caption'],'TAP TO START')
        words[1]['confidence']=74
        self.assertIsNone(title_caption(words))

    def test_absent_pidof_is_an_explicit_normal_result(self):
        class Device:
            def shell(self,*args,**kwargs):
                raise subprocess.CalledProcessError(1,args,output=b'',stderr=b'')
        self.assertEqual(driver.pidof(Device()),'')

    def test_unknown_cleanup_lifetime_needs_positive_absence(self):
        import tempfile
        class Device:
            def __init__(self,pid):self.pid=pid
            def shell(self,*args,**kwargs):return self.pid
        with tempfile.TemporaryDirectory(prefix='owned-jp-capture-test-') as temporary:
            evidence=Path(temporary)
            with self.assertRaises(guard.StopCapture):
                driver.stop_owned_game(Device('1234'),None,evidence,launch_attempted=True)
            proof=driver.stop_owned_game(Device(''),None,evidence,launch_attempted=True)
            self.assertEqual(proof['status'],'NO_JP_PID_AFTER_LAUNCH_ATTEMPT')
            self.assertTrue((evidence/'owned-game-stop-proof.json').is_file())

    def test_requested_settings_need_actual_captions_and_checked_nodes(self):
        nodes=[{'text':text,'class':klass,'enabled':True,'checked':checked,
            'bounds':dict(left=1,top=1,right=100,bottom=50),'scroll_bounds':None}
            for text,klass,checked in [('MinAspect = 2.00000','android.widget.TextView',False),
                ('MaxAspect = 2.00000','android.widget.TextView',False),
                ('Portrait','android.widget.RadioButton',True),
                ('Speed up logos on launch','android.widget.CheckBox',True)]]
        state={key:True for key in ('min','max','orientation','intro')};confirmed={}
        driver.confirm_requested_settings(nodes,state,confirmed)
        self.assertEqual(confirmed,dict(min=2.0,max=2.0,orientation='portrait',intro=True))
        nodes[0]['text']='MinAspect = 1.00000'
        with self.assertRaises(guard.StopCapture):driver.confirm_requested_settings(nodes,state,{})


if __name__=='__main__':unittest.main(verbosity=2)
