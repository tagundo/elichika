"""Pure current-source regressions. Synthetic translations are unit-only."""
import io
import unittest

import jp_chooser_scroll as scroll
import jp_light_adapter as light
import jp_complete_matcher as exact


OWNED={'pid':1911,'start_ticks':'40934'}


def png(image):
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


def frame(name='actual-jp-home-v1-038.png',*,image=None,identifier='first',native=10,captured=10.5,activity=10.6):
    raw=(scroll.ROOT/name).read_bytes() if image is None else png(image)
    xml_name=name.replace('.png','.xml') if name.startswith('actual-jp-home-v1-') else 'jp-game-window.xml'
    xml=(scroll.ROOT/xml_name).read_bytes()
    return {'id':identifier,'png_bytes':raw,'png_sha256':exact.digest(raw),
        'native_xml':xml,'native_sha256':exact.digest(xml),'native_at':native,
        'captured_at':captured,'identity_before':dict(OWNED),'identity_after':dict(OWNED),
        'activity':scroll.ACTIVITY,'activity_at':activity}


def pair(image=None):
    return (frame(image=image),frame('actual-jp-home-v1-039.png',image=image,
        identifier='second',native=11,captured=11.5,activity=11.6))


class ChooserScrollTests(unittest.TestCase):
    def plan(self,frames=None,**changes):
        options={'now':12,'owned_identity':OWNED,'current_identity':OWNED,
            'overall_started':0,'settings_started':1};options.update(changes)
        return scroll.plan_pair(*(frames or pair()),**options)

    def test_actual038_and039_allow_only_one_current_gutter_intent(self):
        plan=self.plan();self.assertEqual(plan['kind'],'diagnostic-chooser-upward-scroll')
        self.assertEqual(plan['center'],plan['start']);self.assertEqual(plan['end'][1],plan['start'][1]-35)
        self.assertEqual(plan['duration_ms'],500)
        for evidence in plan['evidence']:
            self.assertTrue(evidence['bulk_checked']);self.assertFalse(evidence['Light_radio_matched'])
            self.assertFalse(evidence['Light_radio_input_authorized'])
            self.assertGreater(evidence['Light_radio_clipping_estimate'][3],evidence['viewport_bounds'][3])
            self.assertGreater(plan['center'][0],evidence['visible_regions']['bulk-full-row'][2])
        for original in pair():
            with self.assertRaises(light.Refusal):light.observe(original,'bulk')

    def test_actual044_full_visible_row_has_no_partial_scroll_authority(self):
        with self.assertRaises(scroll.Refusal):scroll.observe(frame('jp-full-light-044.png'))

    def test_duplicate_and_altered_visible_glyphs_refuse(self):
        source=scroll._source()
        image=source.copy();image.paste(source.crop(dict(scroll.REGIONS)['Light-full-title']),(190,900))
        with self.assertRaises(scroll.Refusal):scroll.observe(frame(image=image))
        for point in ((200,748),(202,650),(175,680),(360,468),(490,805)):
            with self.subTest(point=point):
                image=source.copy();image.putpixel(point,(0,0,0))
                with self.assertRaises(scroll.Refusal):scroll.observe(frame(image=image))

    def test_unchecked_bulk_is_not_an_eligible_partial_context(self):
        with scroll._source() as image,light._source() as reference:
            with reference.crop(light.ROWS['light']['radio']) as unchecked:
                image.paste(unchecked,dict(scroll.REGIONS)['bulk-checked-radio'][:2])
            current=frame(image=image)
        # Release all synthetic setup images before decoding the current PNG.
        with self.assertRaises(scroll.Refusal):scroll.observe(current)

    def test_nonblank_or_ambiguous_current_gutter_refuses(self):
        source=scroll._source();current=scroll.observe(frame())
        left,top,right,bottom=current['gutter_bounds']
        image=source.copy();image.paste((0,0,0),(left,top,right,bottom))
        with self.assertRaises(scroll.Refusal):scroll.observe(frame(image=image))
        image=source.copy();split=(current['gutter'][0]+current['gutter'][1])//2
        image.paste((0,0,0),(split,top,split+1,bottom))
        with self.assertRaises(scroll.Refusal):scroll.observe(frame(image=image))

    def test_synthetic_unit_only_content_translation_is_independent_of_modal(self):
        source=scroll._source();image=source.copy();offset=-3
        # Unit-only construction: shift complete current viewport content,
        # keeping all modal header/footer pixels fixed. Never actual evidence.
        box=(107,488,613,780)
        image.paste((255,255,255),box)
        image.paste(source.crop((107,491,613,780)),(107,488))
        result=scroll.observe(frame(image=image))
        self.assertEqual(result['modal_offset'],[0,0]);self.assertEqual(result['content_offset'],[0,offset])
        image=source.copy();box=dict(scroll.REGIONS)['Light-full-title']
        image.paste((255,255,255),box);image.paste(source.crop(box),(box[0],box[1]-1))
        with self.assertRaises(scroll.Refusal):scroll.observe(frame(image=image))

    def test_freshness_pid_activity_order_and_fixed_ends_refuse(self):
        for options in ({'now':20},{'current_identity':{'pid':1912,'start_ticks':'40934'}},
                {'now':121},{'settings_started':20}):
            with self.subTest(options=options),self.assertRaises(scroll.Refusal):self.plan(**options)
        for key,value in (('activity','another.MainActivity'),('activity_at',20),
                ('identity_after',{'pid':1911,'start_ticks':'40935'}),('id','first')):
            frames=pair();frames[1][key]=value
            with self.subTest(key=key),self.assertRaises(scroll.Refusal):self.plan(frames)

    def test_two_attempt_budget_is_spent_and_persisted_before_input(self):
        budget=scroll.ChooserScrollBudget();events=[]
        args={'owned_identity':OWNED,'current_identity':OWNED,'now':12,
            'overall_started':0,'settings_started':1,'persist':lambda value:events.append(('persist',value['attempt']))}
        for expected in (1,2):
            intent=budget.reserve(*pair(),**args);self.assertEqual(intent['attempt'],expected)
            events.append(('input',expected))
        self.assertEqual(events,[('persist',1),('input',1),('persist',2),('input',2)])
        with self.assertRaises(scroll.Refusal):budget.reserve(*pair(),**args)
        self.assertEqual(budget.attempts,2)
        # Pure final boundary verification never spends another reservation.
        self.plan();self.assertEqual(budget.attempts,2)

    def test_persistence_failure_still_spends_the_single_reservation(self):
        budget=scroll.ChooserScrollBudget()
        def fail(value):raise OSError('Unit-only failed durable write')
        with self.assertRaises(OSError):budget.reserve(*pair(),owned_identity=OWNED,
            current_identity=OWNED,now=12,overall_started=0,settings_started=1,persist=fail)
        self.assertEqual(budget.attempts,1)


if __name__=='__main__':unittest.main()
