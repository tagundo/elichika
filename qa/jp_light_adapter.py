"""Pure current-frame JP Light chooser proof, derived from original 044.

No selected-Light original has been retained.  The selected-state recognizer
therefore composes two actual radio specimens and the two actual row styles;
it never labels a generated image as an actual selected-Light reference.
Every glyph pixel is checked.  Any unobserved rendering difference refuses.
There is no device, OCR, observer, feature, or network API in this module.
"""
from pathlib import Path
import re

import jp_complete_matcher as exact


Refusal = exact.Refusal
SOURCE_SHA256 = '632772da704152eb0232f869106894cc7edc54797f1026ee0754529fc6746acb'
SOURCE = Path(__file__).parent / 'fixtures' / 'jp-full-light-044.png'
EVIDENCE = 'current-exact-JP-044-glyph-geometry-and-observed-radio-style-composition'
MODAL = (107, 450, 613, 829)
ANCHORS = (
    ('header', (144, 455, 576, 481)),
    ('full-notice', (145, 507, 525, 548)),
    ('cancel-caption', (197, 797, 265, 814)),
    ('ok-caption', (478, 797, 501, 814)),
)
ROWS = {
    'bulk': {'box': (158, 580, 562, 671),
             'text': (190, 586, 544, 650),
             'radio': (166, 616, 186, 636),
             'caption': '一括ダウンロード [15416.53 MB]'},
    'light': {'box': (158, 680, 562, 770),
              'text': (190, 685, 544, 749),
              'radio': (166, 715, 186, 735),
              'caption': '軽量ダウンロード [5858.95 MB]'},
}
OK = (429, 790, 551, 819)
REQUIRED = frozenset(('id', 'png_bytes', 'png_sha256', 'native_xml',
    'native_sha256', 'native_at', 'captured_at', 'identity_before', 'identity_after'))


def _shift(box, offset):
    return tuple(value + offset[index % 2] for index, value in enumerate(box))


def _template(image, identifier):
    return exact.Template(identifier, 'settings', SOURCE_SHA256, (0, 0, *image.size),
        image.size, image.tobytes(), (), None)


def _unique(image, specimen, label):
    locations = exact._locations(image, _template(specimen, label))
    if len(locations) != 1:
        raise Refusal('JP Light ' + label + ' absent, altered, clipped, or colliding')
    return locations[0]


def _source():
    raw = SOURCE.read_bytes()
    if exact.digest(raw) != SOURCE_SHA256:
        raise Refusal('Original actual JP044 reference digest changed')
    return exact._png(raw)


def _inside(x, y, box):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def _palette(source, row):
    """Only exact RGB colors actually present in this retained row style.

    Both actual backgrounds have red=255 and the common text red=60, so the
    complete red plane preserves the full glyph shape during a style change.
    The separate palette check also constrains every green and blue value.
    Row borders/corners are included; an unexpected border raster refuses.
    """
    result = {}
    box, radio = row['box'], row['radio']
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            if not _inside(x, y, radio):
                pixel = source.getpixel((x, y))
                result.setdefault(pixel[0], set()).add(pixel)
    return result


def _rows(image, source, offset, state):
    styles = {'bulk': _palette(source, ROWS['bulk']),
              'light': _palette(source, ROWS['light'])}
    for name, row in ROWS.items():
        selected = name == state
        style_name = 'bulk' if selected else 'light'
        palette = styles[style_name]
        box, radio = row['box'], row['radio']
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                if _inside(x, y, radio):
                    continue
                original = source.getpixel((x, y))
                current = image.getpixel((x + offset[0], y + offset[1]))
                # Before choosing Light the retained original044 already has
                # the required state, so require all three channels exactly.
                # Composition is needed only for the unretained post-click
                # state, whose two actual captures must independently match.
                if state == 'bulk' and current != original:
                    raise Refusal('JP Light full original044 ' + name + ' row RGB differs')
                if current[0] != original[0] or current not in palette.get(original[0], ()):
                    raise Refusal('JP Light full ' + name + ' row glyph/style/border differs')
        # Whole RGB specimens, including their actual selected/unselected
        # backing colors, are independently located and must sit in this row.
        specimen_row = ROWS[style_name]
        found = _unique(image, source.crop(specimen_row['radio']), name + '-radio')
        if found != _shift(radio, offset):
            raise Refusal('JP Light checked/unchecked radio is outside its full row')


def observe(capture, state='bulk'):
    """Recompute current proof from PNG/XML bytes; supplied matches are unused.

    `bulk` requires the actual044 selected-Bulk/unselected-Light state before
    one Light input. `light` requires fresh observed checked-Light AND
    unchecked-Bulk pixels before ordinary OK. A click result is never proof.
    """
    if state not in ('bulk', 'light'):
        raise Refusal('Unknown JP Light selection state')
    if type(capture) is not dict or not REQUIRED.issubset(capture):
        raise Refusal('JP Light raw capture fields absent')
    if not isinstance(capture['id'], str) or re.fullmatch(r'[A-Za-z0-9_-]{1,96}', capture['id']) is None:
        raise Refusal('Invalid JP Light capture ID')
    raw, native = capture['png_bytes'], capture['native_xml']
    if type(raw) is not bytes or exact.digest(raw) != capture['png_sha256']:
        raise Refusal('JP Light PNG raw digest mismatch')
    if type(native) is not bytes or exact.digest(native) != capture['native_sha256']:
        raise Refusal('JP Light native XML raw digest mismatch')
    surface = exact._native_window(native)
    image, source = exact._png(raw), _source()
    offsets = []
    for label, box in ANCHORS:
        found = _unique(image, source.crop(box), label)
        offsets.append((found[0] - box[0], found[1] - box[1]))
    # The entire title plus all description lines are globally unique under
    # the exact red-plane comparison. No character or caption is omitted.
    for name, row in ROWS.items():
        box = row['text']
        found = _unique(image.getchannel('R').convert('RGB'),
            source.crop(box).getchannel('R').convert('RGB'), name + '-full-caption-description')
        offsets.append((found[0] - box[0], found[1] - box[1]))
    if any(offset != offsets[0] for offset in offsets):
        raise Refusal('JP Light header/notice/footer/full-row geometry disagrees')
    offset = offsets[0]
    modal = _shift(MODAL, offset)
    if not (0 <= modal[0] < modal[2] <= image.width
            and 0 <= modal[1] < modal[3] <= image.height):
        raise Refusal('JP Light modal or full Light row is clipped')
    _rows(image, source, offset, state)
    target = _shift(ROWS['light']['radio'] if state == 'bulk' else OK, offset)
    return {'evidence_kind': EVIDENCE, 'source_original_png_sha256': SOURCE_SHA256,
        'current_png_sha256': capture['png_sha256'], 'surface': list(surface),
        'modal_bounds': list(modal), 'selection': state,
        'bulk_checked': state == 'bulk', 'light_checked': state == 'light',
        'rows': {name: {'caption': row['caption'], 'bounds': list(_shift(row['box'], offset)),
                        'radio_bounds': list(_shift(row['radio'], offset))}
                 for name, row in ROWS.items()},
        'target_bounds': list(target), 'selected_light_actual_reference_exists': False,
        'scope': 'Current observed native pixels only; no Home or feature qualification'}


def plan_pair(first, second, *, state, now, owned_identity, current_identity,
              overall_started, settings_started):
    """Two new current captures and the exact owned lifetime precede input."""
    now = exact._time(now)
    overall, settings = exact._time(overall_started), exact._time(settings_started)
    if not (overall <= settings <= now < min(overall + 2400, settings + 120)):
        raise Refusal('Original JP settings120second or overall2400second end reached')
    owned = exact._identity(owned_identity)
    if exact._identity(current_identity) != owned:
        raise Refusal('Owned JP lifetime changed before chooser input')
    evidence = [observe(frame, state) for frame in (first, second)]
    for frame in (first, second):
        if exact._identity(frame['identity_before']) != owned or exact._identity(frame['identity_after']) != owned:
            raise Refusal('JP Light capture crossed a changed process lifetime')
        native, captured = exact._time(frame['native_at']), exact._time(frame['captured_at'])
        if not (native <= captured and 0 <= now - native <= 8 and 0 <= now - captured <= 8):
            raise Refusal('JP Light native XML and PNG must both be fresh within8seconds')
    if not (first['id'] != second['id']
            and first['captured_at'] < second['native_at'] <= second['captured_at']):
        raise Refusal('JP Light independent ordered captures required')
    compare = ('surface', 'modal_bounds', 'selection', 'bulk_checked', 'light_checked', 'rows', 'target_bounds')
    if any(evidence[0][key] != evidence[1][key] for key in compare):
        raise Refusal('JP Light independent current state captures disagree')
    bounds = evidence[1]['target_bounds']
    return {'kind': 'choose-light' if state == 'bulk' else 'confirm-light',
        'caption': ROWS['light']['caption'] if state == 'bulk' else 'OK',
        'bounds': bounds, 'center': [(bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2],
        'evidence_kind': EVIDENCE, 'captures': [first['id'], second['id']],
        'owned_identity': dict(owned), 'checked_at': now, 'evidence': evidence,
        'settings_started': settings, 'overall_started': overall,
        'settings_end': settings + 120, 'overall_end': overall + 2400,
        'scope': 'Ordinary native Light/OK intent only; no Home or feature qualification'}
