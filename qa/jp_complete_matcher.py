"""INERT JP exact-pixel caption evidence; no OCR substitution or device API.

The two reviewed, retained actual JP PNGs are the only reference source.
Matching is exact RGB at the original resolution, with a global uniqueness
search and whole-modal equality. Template evidence never has OCR confidence.
The chooser reference has a clipped regular-Light radio: observation only.
This source has no integration with GL, CI, Android, or feature approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image

PACKAGE = 'com.klab.lovelive.allstars'
FRAME = (720, 1280)
SURFACE = (0, 0, *FRAME)
EVIDENCE = 'exact-RGB-whole-modal-retained-actual-JP-template'
ROOT = Path(__file__).parent / 'fixtures'
NATIVE_WINDOW_SHA256 = '0db787384c9aa3dfb953d722357210e12e49e7acfb15cffbe7ec5ab5a00dde22'

# Absolute reference boxes are ONLY used to extract reviewed original pixels.
# Current match and target coordinates are computed from the current image.
REFERENCES = (
    {'id': 'jp-settings-full-selected-clipped', 'phase': 'settings',
     'file': 'actual-jp-chooser.png',
     'sha256': 'd6c8dc4d8326a8e0e9771decc6b0da3d1fe2bcb23a0e657f5e0f63f2b4c4ed7c',
     'modal': (107, 450, 613, 829),
     'captions': (
         ('header', 'データダウンロード設定', (265, 455, 459, 480)),
         ('full', '一括ダウンロード [15416.53 MB]', (184, 636, 425, 658)),
     ), 'target': None},
    {'id': 'jp-download-complete', 'phase': 'download_wait',
     'file': 'jp-download-complete.png',
     'sha256': '769f9154020463be696a8d11d54af1d941c50f64a4dfe41867c54edb7a6afa33',
     'modal': (107, 497, 613, 782),
     'captions': (
         ('header', 'ダウンロード完了', (284, 502, 436, 528)),
         ('full-message', 'ダウンロードが完了しました', (252, 620, 468, 653)),
         ('close', 'とじる', (334, 748, 385, 769)),
     ), 'target': (252, 744, 468, 772)},
)


class Refusal(ValueError):
    """No input is permitted after any template or freshness mismatch."""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _png(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 4 * 1024**2:
        raise Refusal('PNG bytes absent or outside bounded size')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != 'PNG' or source.size != FRAME or source.mode not in ('RGB', 'RGBA'):
                raise Refusal('Only original-size opaque RGB/RGBA PNG frames are supported')
            source.load()
            if source.mode == 'RGBA' and source.getchannel('A').getextrema() != (255, 255):
                raise Refusal('Transparent screenshot pixels are not supported')
            return source.convert('RGB')
    except (OSError, Image.DecompressionBombError) as error:
        raise Refusal('Invalid PNG') from error


@dataclass(frozen=True)
class Template:
    identifier: str
    phase: str
    source_sha256: str
    modal_box: tuple
    size: tuple
    pixels: bytes
    captions: tuple
    target: tuple | None


def load_references():
    """Recheck original PNG hashes; no supplied/precomputed matches are loaded."""
    templates = []
    for row in REFERENCES:
        raw = (ROOT / row['file']).read_bytes()
        if digest(raw) != row['sha256']:
            raise Refusal('Original actual JP reference digest changed')
        image = _png(raw)
        box = row['modal']
        modal = image.crop(box)
        captions = tuple((role, text, tuple(value - box[index % 2]
            for index, value in enumerate(bounds))) for role, text, bounds in row['captions'])
        target = row['target']
        if target is not None:
            target = tuple(value - box[index % 2] for index, value in enumerate(target))
        templates.append(Template(row['id'], row['phase'], row['sha256'], box,
            modal.size, modal.tobytes(), captions, target))
    return tuple(templates)


def _locations(image, template):
    """Global exact search. An anchor only filters; the entire modal must equal."""
    width, height = image.size
    tw, th = template.size
    stride, row_size = width * 3, tw * 3
    rows = [template.pixels[y * row_size:(y + 1) * row_size] for y in range(th)]
    anchor_y = max(range(th), key=lambda y: len(set(rows[y])))
    anchor = rows[anchor_y]
    pixels = image.tobytes()
    position = 0
    locations = []
    candidates = 0
    while True:
        position = pixels.find(anchor, position)
        if position < 0:
            return locations
        location = position
        position += 1
        if location % 3:
            continue
        x, y = (location % stride) // 3, location // stride - anchor_y
        if not (0 <= x <= width - tw and 0 <= y <= height - th):
            continue
        candidates += 1
        if candidates > 4096:
            raise Refusal('Ambiguous or excessive template anchor candidates')
        if all(pixels[(y + dy) * stride + x * 3:(y + dy) * stride + x * 3 + row_size]
               == row for dy, row in enumerate(rows)):
            locations.append((x, y, x + tw, y + th))
            if len(locations) > 1:
                return locations


def _native_window(raw):
    """Validate the CURRENT whole native content Surface and focused Game view."""
    if type(raw) is not bytes or not 0 < len(raw) <= 128 * 1024:
        raise Refusal('Current native window XML absent or too large')
    # The complete actual tree is byte-identical at early chooser and retained
    # late game captures. Pinning it also rejects same-package native overlays
    # that could intercept input while the underlying Game view stays focused.
    if digest(raw) != NATIVE_WINDOW_SHA256:
        raise Refusal('Complete native window differs from the actual retained JP tree')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise Refusal('Native window XML declarations rejected')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise Refusal('Malformed native window XML') from error
    if root.tag != 'hierarchy' or root.get('rotation') != '3':
        raise Refusal('Native window rotation differs from the actual JP reference')
    nodes = list(root.iter('node'))
    if not nodes or any(node.get('package') != PACKAGE for node in nodes):
        raise Refusal('Native window belongs to another package or overlay')
    bounds = '[0,0][720,1280]'
    surfaces = [node for node in nodes if node.get('class', '').endswith('SurfaceView')]
    if not surfaces:
        surfaces = [node for node in nodes if node.get('resource-id') == 'android:id/content']
    focus = [node for node in nodes if node.get('focused') == 'true']
    if (len(surfaces) != 1 or surfaces[0].get('bounds') != bounds
            or surfaces[0].get('enabled') != 'true' or len(focus) != 1
            or focus[0].get('content-desc') != 'Game view'
            or focus[0].get('enabled') != 'true' or focus[0].get('bounds') != bounds):
        raise Refusal('No unique full native Surface and focused Game view')
    return SURFACE


def _identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'start_ticks'}
            or type(value['pid']) is not int or value['pid'] <= 0
            or type(value['start_ticks']) is not str
            or re.fullmatch(r'[1-9][0-9]{0,19}', value['start_ticks']) is None):
        raise Refusal('Missing exact owned PID/startticks identity')
    return value


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise Refusal('Nonfinite or invalid monotonic timestamp')
    return value


def observe(capture, phase, *, templates):
    """Recompute evidence from raw PNG and current XML; accept no external hits."""
    allowed = {'id', 'png_bytes', 'png_sha256', 'native_xml', 'native_xml_sha256',
        'captured_at', 'native_captured_at', 'identity_before', 'identity_after'}
    if type(capture) is not dict or set(capture) != allowed:
        raise Refusal('Capture schema rejected; precomputed matches are not accepted')
    if not isinstance(capture['id'], str) or re.fullmatch(r'[A-Za-z0-9_-]{1,96}', capture['id']) is None:
        raise Refusal('Invalid fresh capture ID')
    if phase not in ('settings', 'download_wait', 'home_wait'):
        raise Refusal('Unknown native phase')
    raw, native = capture['png_bytes'], capture['native_xml']
    if type(raw) is not bytes or digest(raw) != capture['png_sha256']:
        raise Refusal('Current PNG digest mismatch')
    if type(native) is not bytes or digest(native) != capture['native_xml_sha256']:
        raise Refusal('Current native XML digest mismatch')
    surface = _native_window(native)
    image = _png(raw)
    hits = [(template, box) for template in templates for box in _locations(image, template)]
    if len(hits) != 1:
        raise Refusal('Whole modal absent, altered, clipped, colliding, or ambiguous')
    template, box = hits[0]
    if template.phase != phase:
        raise Refusal('Whole modal belongs to a different native phase')
    offset = box[:2]
    translate = lambda bounds: [value + offset[index % 2] for index, value in enumerate(bounds)]
    return {'evidence_kind': EVIDENCE, 'template_id': template.identifier,
        'reference_original_png_sha256': template.source_sha256,
        'current_png_sha256': capture['png_sha256'], 'modal_bounds': list(box),
        'surface': list(surface), 'phase': phase,
        'captions': [{'role': role, 'transcription': text, 'bounds': translate(bounds),
            'evidence_kind': EVIDENCE} for role, text, bounds in template.captions],
        'target_bounds': translate(template.target) if template.target else None,
        'scope': 'Pixel-template evidence only; no OCR confidence or feature qualification',
        'settings_regular_light_actionable': False}


def _within_fixed_ends(starts, now):
    if type(starts) is not dict or set(starts) != {'overall_started', 'bulk_started'}:
        raise Refusal('Original overall and bulk start times are mandatory')
    overall, bulk = _time(starts['overall_started']), _time(starts['bulk_started'])
    if not (overall <= bulk <= now < min(overall + 2400, bulk + 1800)):
        raise Refusal('Original1800second bulk or2400second overall bound reached')


def plan_pair(first, second, *, phase, now, owned_identity, current_identity, fixed_starts):
    """Mandatory final gate: BOTH independent captures and current lifetime.

    Load pinned references afresh and recompute both raw image matches here.
    The caller cannot pass matches/templates/target coordinates into this gate.
    """
    now = _time(now)
    _within_fixed_ends(fixed_starts, now)
    owned = _identity(owned_identity)
    if _identity(current_identity) != owned:
        raise Refusal('Owned game lifetime changed before input')
    templates = load_references()
    evidence = [observe(frame, phase, templates=templates) for frame in (first, second)]
    for frame in (first, second):
        before, after = _identity(frame['identity_before']), _identity(frame['identity_after'])
        captured, native = _time(frame['captured_at']), _time(frame['native_captured_at'])
        if before != owned or after != owned:
            raise Refusal('Capture crossed a changed process lifetime')
        if not (0 <= now - captured <= 8 and 0 <= now - native <= 8 and native <= captured):
            raise Refusal('Both current native trees and PNG captures must be fresh within8seconds')
    if not (first['id'] != second['id']
            and first['captured_at'] < second['native_captured_at'] <= second['captured_at']):
        raise Refusal('Two independent ordered captures are required')
    if any(evidence[0][key] != evidence[1][key] for key in
           ('template_id', 'modal_bounds', 'surface', 'phase', 'captions', 'target_bounds')):
        raise Refusal('Independent whole-modal captures disagree')
    if phase != 'download_wait' or evidence[1]['target_bounds'] is None:
        raise Refusal('Retained chooser is clipped; no regular-Light input is authorized')
    bounds = evidence[1]['target_bounds']
    return {'kind': 'close-download', 'caption': 'とじる', 'bounds': bounds,
        'center': [(bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2],
        'evidence_kind': EVIDENCE, 'captures': [first['id'], second['id']],
        'owned_identity': dict(owned), 'checked_at': now, 'evidence': evidence,
        'fixed_starts': dict(fixed_starts),
        'original_bulk_end': fixed_starts['bulk_started'] + 1800,
        'original_overall_end': fixed_starts['overall_started'] + 2400,
        'scope': 'Ordinary Close intent only; no Home/Bootstrap/MV qualification'}


def guarded_close(*, capture, lifetime, clock, send_input, fixed_starts):
    """Source-only adapter with mandatory fresh callbacks, tested using fakes.

    No cached frames, identities, templates, hits, or coordinates are arguments.
    No device function is provided here. Production wiring remains unapproved.
    """
    if type(fixed_starts) is not dict:
        raise Refusal('Original fixed start times absent')
    fixed_starts = dict(fixed_starts)
    owned = dict(_identity(lifetime()))
    frames = []
    for _ in range(2):
        before = dict(_identity(lifetime()))
        frame = capture()
        after = dict(_identity(lifetime()))
        if type(frame) is not dict:
            raise Refusal('Fresh capture callback returned no record')
        frame = dict(frame, identity_before=before, identity_after=after)
        frames.append(frame)
    current = dict(_identity(lifetime()))
    plan = plan_pair(*frames, phase='download_wait', now=clock(),
        owned_identity=owned, current_identity=current, fixed_starts=fixed_starts)
    # A second immediate check also covers time/lifetime spent matching pixels.
    if _identity(lifetime()) != owned:
        raise Refusal('Owned lifetime changed at input boundary')
    final = _time(clock())
    if final < plan['checked_at']:
        raise Refusal('Monotonic clock regressed before input')
    _within_fixed_ends(fixed_starts, final)
    if any(not (0 <= final - frame[key] <= 8) for frame in frames
           for key in ('captured_at', 'native_captured_at')):
        raise Refusal('Capture expired at input boundary')
    send_input(*plan['center'])
    return plan
