"""Actual V9 modal positives and narrow Cancel-only unit-negative mutations.

No OCR, input or image artifacts are produced. All unit setup images are closed
before the production capture decoder is called; its images are always closed.
"""
import io
import json
from pathlib import Path
import unittest

from PIL import Image

import jp_complete_matcher as exact
import jp_light_adapter as light


ROOT=Path(__file__).parent/'fixtures'
ANCHORS=dict(light.ANCHORS)
CANCEL=ANCHORS['cancel-caption']


def frame(number='0040',raw=None):
    png=(ROOT/f'actual-jp-home-v9-{number}.png').read_bytes() if raw is None else raw
    xml=(ROOT/f'actual-jp-home-v9-{number}.xml').read_bytes()
    owned={'pid':1911,'start_ticks':'40934'}  # Controlled unit metadata, no lifetime claim.
    return {'id':'actual-v9-'+number,'png_bytes':png,'png_sha256':exact.digest(png),
        'native_xml':xml,'native_sha256':exact.digest(xml),'native_at':10,'captured_at':10.5,
        'identity_before':dict(owned),'identity_after':dict(owned)}


def context(capture):
    image,source,_=light.capture_image(capture)
    try:return light.modal_context(image,source)
    finally:image.close();source.close()


def mutated_frame(change):
    """Unit-only PNG mutation; close setup ownership before production decode."""
    with Image.open(ROOT/'actual-jp-home-v9-0040.png') as original,original.convert('RGB') as image,light._source() as reference,io.BytesIO() as output:
        change(image,reference)
        image.save(output,format='PNG');raw=output.getvalue()
    return frame(raw=raw)


def dark_pixel(reference,box):
    return next((x,y) for y in range(box[1],box[3]) for x in range(box[0],box[2])
        if max(reference.getpixel((x,y)))<200)


class ModalCancelRasterTests(unittest.TestCase):
    def setUp(self):
        manifest=json.loads((ROOT/'actual-jp-home-v9-modal-provenance.json').read_text())
        expected={f'actual-jp-home-v9-{number}.{suffix}' for number in ('0040','0041') for suffix in ('png','xml')}
        self.assertEqual(set(manifest['files']),expected)
        for name,row in manifest['files'].items():
            self.assertEqual(exact.digest((ROOT/name).read_bytes()),row['sha256'],name)

    def assert_actual_context(self,number):
        capture=frame(number);result=context(capture)
        self.assertEqual(result['modal_offset'],[0,0])
        self.assertEqual(result['modal_bounds'],[107,450,613,829])
        bounds=next(row['bounds'] for row in result['anchors'] if row['role']=='cancel-caption')
        self.assertEqual(bounds,list(CANCEL))
        image,reference,_=light.capture_image(capture)
        try:
            with image.crop(tuple(bounds)) as current,reference.crop(CANCEL) as retained:
                self.assertTrue(all(abs(a-b)<=1 for a,b in zip(current.tobytes(),retained.tobytes())))
                self.assertEqual(tuple(light._unique(image,current,'unit-current-Cancel')),tuple(bounds))
        finally:image.close();reference.close()

    def test_actual_V9_0040_accepts_narrow_current_cancel_raster(self):
        self.assert_actual_context('0040')

    def test_actual_V9_0041_accepts_narrow_current_cancel_raster(self):
        self.assert_actual_context('0041')

    def test_Cancel_channel_difference_two_refuses(self):
        def change(image,reference):
            point=dark_pixel(reference,CANCEL);red=reference.getpixel(point)[0]
            color=image.getpixel(point)
            image.putpixel(point,(red+2 if red<=253 else red-2,color[1],color[2]))
        capture=mutated_frame(change)
        with self.assertRaises(light.Refusal):context(capture)

    def test_excised_terminal_Cancel_glyph_refuses(self):
        def change(image,reference):
            right=max(x for y in range(CANCEL[1],CANCEL[3]) for x in range(CANCEL[0],CANCEL[2])
                if max(reference.getpixel((x,y)))<200)
            image.paste((255,255,255),(max(CANCEL[0],right-6),CANCEL[1],right+1,CANCEL[3]))
        capture=mutated_frame(change)
        with self.assertRaises(light.Refusal):context(capture)

    def test_displaced_current_Cancel_refuses(self):
        def change(image,reference):
            with image.crop(CANCEL) as current:
                image.paste((255,255,255),CANCEL)
                image.paste(current,(CANCEL[0]+3,CANCEL[1]))
        capture=mutated_frame(change)
        with self.assertRaises(light.Refusal):context(capture)

    def test_clipped_current_Cancel_refuses(self):
        capture=mutated_frame(lambda image,reference:image.paste((255,255,255),
            (CANCEL[0],CANCEL[1],CANCEL[0]+12,CANCEL[3])))
        with self.assertRaises(light.Refusal):context(capture)

    def test_copied_current_Cancel_collision_refuses(self):
        def change(image,reference):
            with image.crop(CANCEL) as current:image.paste(current,(CANCEL[0],900))
        capture=mutated_frame(change)
        with self.assertRaises(light.Refusal):context(capture)

    def test_header_and_OK_remain_globally_exact_without_Cancel_tolerance(self):
        for role in ('header','ok-caption'):
            def change(image,reference):
                box=ANCHORS[role]
                point=(next((x,y) for y in range(box[1],box[3]) for x in range(box[0],box[2])
                    if min(reference.getpixel((x,y)))>245) if role=='ok-caption' else dark_pixel(reference,box))
                red=reference.getpixel(point)[0]
                color=image.getpixel(point)
                image.putpixel(point,(red+1 if red<255 else red-1,color[1],color[2]))
            capture=mutated_frame(change)
            with self.subTest(role=role),self.assertRaises(light.Refusal):context(capture)


if __name__=='__main__':unittest.main()
