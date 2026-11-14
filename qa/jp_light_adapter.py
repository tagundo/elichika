"""Pure current-frame JP Light chooser proof, derived from original 044.

No selected-Light original has been retained.  The selected-state recognizer
therefore composes two actual radio specimens and the two actual row styles;
it never labels a generated image as an actual selected-Light reference.
Header and OK glyph pixels remain exact.  Cancel alone permits one RGB level
per channel at the bounds those exact anchors derive; its current whole crop
must itself occur exactly once in the frame.  Other rendering differences refuse.
There is no device, OCR, observer, feature, or network API in this module.
"""
from pathlib import Path
import re

import jp_complete_matcher as exact


Refusal = exact.Refusal
SOURCE_SHA256 = '632772da704152eb0232f869106894cc7edc54797f1026ee0754529fc6746acb'
SOURCE = Path(__file__).parent / 'fixtures' / 'jp-full-light-044.png'
# Stable legacy kind; cancel_caption_comparison explicitly qualifies Cancel.
EVIDENCE = 'current-exact-JP-044-glyph-geometry-and-observed-radio-style-composition'
MODAL = (107, 450, 613, 829)
CONTENT_VIEWPORT = (107, 488, 613, 780)
ANCHORS = (
    ('header', (144, 455, 576, 481)),
    ('cancel-caption', (197, 797, 265, 814)),
    ('ok-caption', (478, 797, 501, 814)),
)
NOTICE = (145, 507, 525, 548)
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


def capture_image(capture):
    """Check only current original bytes/window; accept no supplied pixel hits."""
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
    return exact._png(raw), _source(), surface


def modal_context(image, source):
    """The fixed header/footer determine the modal, independently of its scroll."""
    offsets=[];anchors={}
    for label, box in (ANCHORS[0], ANCHORS[2]):
        with source.crop(box) as specimen:
            found = _unique(image, specimen, label)
        offsets.append((found[0] - box[0], found[1] - box[1]))
        anchors[label]={'role':label,'bounds':list(found)}
    if any(offset != offsets[0] for offset in offsets):
        raise Refusal('JP Light fixed header/footer geometry disagrees')
    modal = _shift(MODAL, offsets[0])
    if not (0 <= modal[0] < modal[2] <= image.width
            and 0 <= modal[1] < modal[3] <= image.height):
        raise Refusal('JP Light modal is clipped')
    label, box = ANCHORS[1]
    bounds = _shift(box, offsets[0])
    with image.crop(bounds) as current, source.crop(box) as specimen:
        if any(abs(a-b)>1 for a,b in zip(current.tobytes(),specimen.tobytes())):
            raise Refusal('JP Light Cancel caption differs by more than one RGB level')
        if _unique(image,current,'current-cancel-caption') != bounds:
            raise Refusal('JP Light current Cancel caption is outside its derived bounds')
    anchors[label]={'role':label,'bounds':list(bounds)}
    return {'modal_offset':list(offsets[0]),'modal_bounds':list(modal),
        'viewport_bounds':list(_shift(CONTENT_VIEWPORT,offsets[0])),
        'anchors':[anchors[label] for label, _ in ANCHORS],
        'cancel_caption_comparison':{
            'source_max_RGB_channel_difference':1,
            'bounds_derived_from_exact_header_and_OK':True,
            'current_crop_globally_exact_unique':True}}


def _within(box, viewport):
    return (viewport[0] <= box[0] < box[2] <= viewport[2]
        and viewport[1] <= box[1] < box[3] <= viewport[3])


def observe(capture, state='bulk'):
    """Require complete current content under one independent scroll offset.

    `bulk` requires the original044 state before Light. `light` requires actual
    fresh checked-Light AND unchecked-Bulk pixels before OK; a click is no proof.
    The radio follows content, while OK follows the independently fixed modal.
    """
    if state not in ('bulk', 'light'):
        raise Refusal('Unknown JP Light selection state')
    image, source, surface = capture_image(capture)
    modal = modal_context(image,source)
    notice = _unique(image,source.crop(NOTICE),'full-notice')
    offsets=[(notice[0]-NOTICE[0],notice[1]-NOTICE[1])]
    # The entire title plus all description lines are globally unique under
    # the exact red-plane comparison. No character or caption is omitted.
    for name, row in ROWS.items():
        box = row['text']
        found = _unique(image.getchannel('R').convert('RGB'),
            source.crop(box).getchannel('R').convert('RGB'), name + '-full-caption-description')
        offsets.append((found[0] - box[0], found[1] - box[1]))
    if (any(offset != offsets[0] for offset in offsets)
            or offsets[0][0] != modal['modal_offset'][0]):
        raise Refusal('JP Light notice/full-row content scroll geometry disagrees')
    offset = offsets[0]
    if (not _within(notice,modal['viewport_bounds']) or any(
            not _within(_shift(row['box'],offset),modal['viewport_bounds'])
            for row in ROWS.values())):
        raise Refusal('JP Light full notice or option row is clipped by the content viewport/footer')
    _rows(image, source, offset, state)
    target = _shift(ROWS['light']['radio'],offset) if state=='bulk' else _shift(OK,modal['modal_offset'])
    return {'evidence_kind': EVIDENCE, 'source_original_png_sha256': SOURCE_SHA256,
        'current_png_sha256': capture['png_sha256'], 'surface': list(surface),
        'modal_bounds':modal['modal_bounds'],'modal_offset':modal['modal_offset'],
        'cancel_caption_comparison':modal['cancel_caption_comparison'],
        'content_offset':list(offset),'viewport_bounds':modal['viewport_bounds'],'selection':state,
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
    compare = ('surface', 'modal_bounds', 'modal_offset', 'content_offset', 'viewport_bounds',
        'selection', 'bulk_checked', 'light_checked', 'rows', 'target_bounds')
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
