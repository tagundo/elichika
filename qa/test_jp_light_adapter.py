"""Host-only source checks. Synthetic selected pixels are never actual proof."""
import io
import unittest

from PIL import Image

import jp_complete_matcher as exact
import jp_light_adapter as light


IDENTITY = {'pid': 1895, 'start_ticks': '49349'}


def png(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def frame(image=None, identifier='first', native=10.0, captured=10.5):
    raw = light.SOURCE.read_bytes() if image is None else png(image)
    xml = (light.SOURCE.parent / 'jp-game-window.xml').read_bytes()
    return {'id': identifier, 'png_bytes': raw, 'png_sha256': exact.digest(raw),
        'native_xml': xml, 'native_sha256': exact.digest(xml),
        'native_at': native, 'captured_at': captured,
        'identity_before': dict(IDENTITY), 'identity_after': dict(IDENTITY)}


def synthetic_style_transfer():
    """Unit-only expected-style example; explicitly not a selected original.

    All replacement colors and complete radio specimens come from actual044.
    Choosing colors here demonstrates the compositional gate contract only.
    """
    source = light._source()
    image = source.copy()
    for name, row in light.ROWS.items():
        other = light.ROWS['light' if name == 'bulk' else 'bulk']
        palette = light._palette(source, other)
        box, radio = row['box'], row['radio']
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                if light._inside(x, y, radio):
                    continue
                red = source.getpixel((x, y))[0]
                colors = palette.get(red)
                if not colors:
                    raise AssertionError('Actual044 palette cannot compose this red value; selected-style gate requires review')
                image.putpixel((x, y), sorted(colors)[0])
        image.paste(source.crop(other['radio']), radio[:2])
    return image


def synthetic_content_translation(image,dy):
    """Unit-only scroll composition; never an original runtime reference."""
    image=image.copy();box=(145,507,562,770);content=image.crop(box)
    image.paste((255,255,255),box);image.paste(content,(box[0],box[1]+dy))
    return image


class LightAdapterTest(unittest.TestCase):
    def plan(self, a=None, b=None, state='bulk', **overrides):
        args = dict(state=state, now=12.0, owned_identity=IDENTITY,
            current_identity=IDENTITY, overall_started=0.0, settings_started=1.0)
        args.update(overrides)
        return light.plan_pair(a or frame(), b or frame(identifier='second', native=11.0, captured=11.5), **args)

    def test_actual044_authorizes_only_one_light_intent(self):
        result = self.plan()
        self.assertEqual(result['kind'], 'choose-light')
        self.assertEqual(result['center'], [176, 725])
        self.assertFalse(result['evidence'][0]['selected_light_actual_reference_exists'])
        with self.assertRaises(light.Refusal):
            self.plan(state='light')

    def test_expected_style_composition_requires_both_current_radios(self):
        image = synthetic_style_transfer()
        a, b = frame(image), frame(image, 'second', 11.0, 11.5)
        result = self.plan(a, b, state='light')
        self.assertEqual(result['kind'], 'confirm-light')
        self.assertEqual(result['caption'], 'OK')
        self.assertFalse(result['evidence'][0]['bulk_checked'])
        self.assertTrue(result['evidence'][0]['light_checked'])
        image.paste(light._source().crop(light.ROWS['bulk']['radio']), light.ROWS['bulk']['radio'][:2])
        with self.assertRaises(light.Refusal):
            light.observe(frame(image), 'light')

    def test_full_light_title_description_border_and_footer_changes_refuse(self):
        for point in ((196, 692), (204, 727), (158, 700), (489, 805), (360, 467)):
            with self.subTest(point=point):
                image = light._source()
                image.putpixel(point, (0, 0, 0))
                with self.assertRaises(light.Refusal):
                    light.observe(frame(image))

    def test_clipped_or_duplicate_full_light_caption_refuses(self):
        image = light._source()
        box = light.ROWS['light']['text']
        image.paste(image.crop(box), (190, 900))
        with self.assertRaises(light.Refusal):
            light.observe(frame(image))
        image = light._source()
        image.paste((255, 255, 255), (158, 759, 562, 770))
        with self.assertRaises(light.Refusal):
            light.observe(frame(image))

    def test_wrong_native_overlay_and_changed_raw_digest_refuse(self):
        a = frame()
        a['native_xml'] = a['native_xml'].replace(b'focused="true"', b'focused="false"')
        a['native_sha256'] = exact.digest(a['native_xml'])
        with self.assertRaises(light.Refusal):
            light.observe(a)
        a = frame()
        a['png_sha256'] = '0' * 64
        with self.assertRaises(light.Refusal):
            light.observe(a)

    def test_freshness_identity_independence_and_fixed_ends(self):
        for overrides in ({'now': 20.0}, {'current_identity': {'pid': 1896, 'start_ticks': '49349'}},
                          {'now': 121.0}, {'settings_started': 20.0}):
            with self.subTest(overrides=overrides), self.assertRaises(light.Refusal):
                self.plan(**overrides)
        a, b = frame(), frame(identifier='second', native=11.0, captured=11.5)
        b['identity_after'] = {'pid': 1895, 'start_ticks': '49350'}
        with self.assertRaises(light.Refusal):
            self.plan(a, b)
        with self.assertRaises(light.Refusal):
            self.plan(frame(), frame())

    def test_unit_only_content_translation_moves_radio_while_modal_OK_stays_fixed(self):
        image=synthetic_content_translation(light._source(),-10)
        a,b=frame(image),frame(image,'second',11.0,11.5)
        plan=self.plan(a,b)
        self.assertEqual(plan['center'],[176,715])
        self.assertEqual(plan['evidence'][0]['modal_offset'],[0,0])
        self.assertEqual(plan['evidence'][0]['content_offset'],[0,-10])
        selected=synthetic_content_translation(synthetic_style_transfer(),-10)
        plan=self.plan(frame(selected),frame(selected,'second',11.0,11.5),state='light')
        self.assertEqual(plan['center'],[490,804])
        self.assertEqual(plan['evidence'][0]['content_offset'],[0,-10])

    def test_unit_only_notice_and_option_rows_cannot_have_independent_offsets(self):
        for box in (light.NOTICE,light.ROWS['bulk']['text']):
            with self.subTest(box=box):
                image=light._source();piece=image.crop(box)
                image.paste((255,255,255),box);image.paste(piece,(box[0],box[1]-3))
                with self.assertRaises(light.Refusal):light.observe(frame(image))
        image=light._source();box=(145,507,562,770);piece=image.crop(box)
        image.paste((255,255,255),box);image.paste(piece,(box[0]+3,box[1]))
        with self.assertRaisesRegex(light.Refusal,'content scroll geometry'):
            light.observe(frame(image))

    def test_unit_only_full_Light_row_past_footer_refuses_even_inside_frame(self):
        image=synthetic_content_translation(light._source(),15)
        with self.assertRaisesRegex(light.Refusal,'viewport/footer'):
            light.observe(frame(image))

    def test_actual_partial_038_039_never_authorize_full_Light_input(self):
        for suffix in ('038','039'):
            raw=(light.SOURCE.parent/('actual-jp-home-v1-'+suffix+'.png')).read_bytes()
            capture=frame();capture.update(png_bytes=raw,png_sha256=exact.digest(raw))
            with self.subTest(actual=suffix),self.assertRaises(light.Refusal):light.observe(capture)


if __name__ == '__main__':
    unittest.main()
