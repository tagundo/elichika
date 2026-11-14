"""One fixed, read-only OCR heading supplement for current download settings.

This module performs no OCR, I/O, native input or game calls. Its source rule is
the single before015/after023 probe; it does not authorize a Light prefix alone.
The caller retains two fresh captures, native Surface/lifetime and fixed guards.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re

from PIL import Image, ImageOps

from native_download_flow import (_box, _center, _exact, _light_options,
                                  _orange_circles, _usable,
                                  _text, phrase)


_SCOPE = 'SAME_FRAME_FIXED_LIGHT_HEADING_SUPPLEMENT'
_TSV_FIELDS = ['level', 'page_num', 'block_num', 'par_num', 'line_num',
               'word_num', 'left', 'top', 'width', 'height', 'conf', 'text']


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _frame(metadata, size=None):
    if not isinstance(metadata, dict):
        raise ValueError('Heading metadata must be a current capture object')
    surface = metadata.get('surface')
    if not isinstance(surface, dict):
        raise ValueError('Heading native Surface is unavailable')
    width, height = surface.get('right'), surface.get('bottom')
    if (type(surface.get('left')) is not int or type(surface.get('top')) is not int or
            type(width) is not int or type(height) is not int or not
            (0 < width <= 4096 and 0 < height <= 4096) or
            surface != {'left': 0, 'top': 0, 'right': width, 'bottom': height} or
            (size is not None and tuple(size) != (width, height))):
        raise ValueError('Heading Surface does not match the current image')
    if (not _sha(metadata.get('screenshot_sha256')) or
            not isinstance(metadata.get('native_tree'), str) or
            not metadata['native_tree'].endswith('.xml') or
            not isinstance(metadata.get('words'), list)):
        raise ValueError('Heading capture identity/words are unavailable')
    return width, height


def _words(metadata, width, height):
    words = metadata['words']
    if len(words) > 4096 or any(not isinstance(word, dict) for word in words):
        raise ValueError('Heading word inventory is malformed or exceeds bound')
    return _usable(words, width, height)


def runtime_heading_eligible(metadata):
    """Supplement missing captions only; never override any existing option."""
    try:
        width, height = _frame(metadata)
        if 'download_heading_transform' in metadata:
            return False
        options, regular = _light_options(_words(metadata, width, height))
        return regular is None and options == []
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def _same_baseline(word, reference, height):
    return abs(_center(word['bounds'])[1] - _center(reference['bounds'])[1]) <= height * .65


def _header(words, full):
    above = [word for word in words if word['bounds'][3] < full['bounds'][1]]
    # Use the existing known-modal context predicate, not an additional OCR
    # requirement for the title's middle word. The regular Light caption still
    # requires the complete exact Download word and immediate numeric MB suffix.
    context = {_text(word) for word in above}
    if not {'data', 'settings'} <= context:
        return None
    return _box([word for word in above if _text(word) in ('data', 'settings')])


def _numeric_suffix(words, light, height):
    line = sorted((word for word in words if word['bounds'][0] >= light['bounds'][2]
                   and _same_baseline(word, light, height)),
                  key=lambda word: word['bounds'][0])
    pairs = []
    for index, number in enumerate(line[:-1]):
        unit = line[index + 1]
        if (re.fullmatch(r'\(\d+(?:\.\d+)?', number['text']) and
                unit['text'].casefold() == 'mb)' and
                0 <= unit['bounds'][0] - number['bounds'][2] <= height * 1.5):
            pairs.append([number, unit])
    return pairs[0] if len(pairs) == 1 else None


def _checked_plan(plan):
    if not isinstance(plan, dict) or not _sha(plan.get('plan_sha256')):
        raise ValueError('Heading plan identity is unavailable')
    original = {key: value for key, value in plan.items() if key != 'plan_sha256'}
    if _digest(original) != plan['plan_sha256']:
        raise ValueError('Heading plan was modified')
    if (plan.get('scope') != _SCOPE or plan.get('scale') != 4 or
            plan.get('psm') != 7 or plan.get('language') != 'eng' or
            plan.get('resample') != 'BICUBIC'):
        raise ValueError('Heading transform differs from the single fixed rule')
    return plan


def derive_heading_plan(image, metadata):
    """Derive one heading-only crop; CI may call this on a qualified control."""
    width, height = _frame(metadata, image.size)
    words = _words(metadata, width, height)
    full = phrase(words, 'Full', 'Download')
    lights = [word for word in words if word['text'].casefold() == 'light']
    options, regular = _light_options(words)
    if not full or len(lights) != 1:
        return None
    # An already qualified regular control is permitted for the CI comparison.
    # Unknown/competing alternatives can never be repaired by deleting them.
    if options and not (len(options) == 1 and regular is not None):
        return None
    light = lights[0]
    h = max(light['bounds'][3] - light['bounds'][1],
            full['bounds'][3] - full['bounds'][1])
    header = _header(words, full)
    suffix = _numeric_suffix(words, light, h)
    buttons = _usable(metadata.get('button_words') or [], width, height)
    ok, cancel = _exact(buttons, 'OK'), _exact(words, 'Cancel')
    if not all((header, suffix, ok, cancel)):
        return None
    fb, lb = full['bounds'], light['bounds']
    fcy, lcy = _center(fb)[1], _center(lb)[1]
    gap = lcy - fcy
    footer = min(ok['bounds'][1], cancel['bounds'][1])
    if not (h * 2 < gap < h * 20 and abs(fb[0] - lb[0]) <= h and
            footer > lb[3] + h):
        return None
    content_bottom = footer - h * 1.2
    left = min(fb[0], lb[0])
    region = [left - h * 4, fb[1] - h * .5, left - h * .2, content_bottom]
    markers = _orange_circles(image, region, h)
    if len(markers) != 1:
        return None
    marker = markers[0]
    selected = [name for name, cy in (('full', fcy), ('light', lcy))
                if h * .5 < marker['center'][1] - cy < min(gap * .8, h * 6)]
    if selected not in (['full'], ['light']):
        return None
    full_line = [word for word in words if _same_baseline(word, full, h)]
    scan_x = math.ceil(max(word['bounds'][2] for word in full_line) + h)
    scan_y = int(marker['center'][1])
    if not (0 <= scan_x < width and 0 <= scan_y < height):
        return None
    rgb = image.convert('RGB')
    pixels = rgb.load()
    background = pixels[scan_x, scan_y]
    boundary = next((x for x in range(scan_x + 1, width)
                     if pixels[x, scan_y] != background), None)
    if boundary is None or boundary <= suffix[-1]['bounds'][2]:
        return None
    padding = math.ceil(h / 2)
    margin = math.ceil(h / 4)
    crop = [math.floor(lb[0] - padding), math.floor(lb[1] - margin),
            boundary, math.ceil(lb[3] + margin)]
    if not (0 <= crop[0] < crop[2] <= width and
            0 <= crop[1] < crop[3] <= height):
        return None
    # Every high-confidence description line must remain outside this crop.
    if any(word['bounds'][1] >= lb[3] and word['bounds'][1] < crop[3]
           for word in words):
        return None
    plan = {'scope': _SCOPE, 'source_screenshot_sha256': metadata['screenshot_sha256'],
            'source_native_tree': metadata['native_tree'],
            'source_metadata_sha256': _digest(metadata),
            'source_pixel_sha256': hashlib.sha256(rgb.tobytes()).hexdigest(),
            'image_size': [width, height], 'crop_box': crop,
            'padding_source_pixels': padding, 'scale': 4, 'psm': 7,
            'language': 'eng', 'resample': 'BICUBIC',
            'light_token': copy.deepcopy(light), 'full_caption': copy.deepcopy(full),
            'current_suffix_words': copy.deepcopy(suffix), 'header_bounds': header,
            'orange_marker': marker, 'selected_marker_row': selected[0],
            'marker_search_region': region,
            'row_boundary_scan': {'start': [scan_x, scan_y],
                                  'background_RGB': list(background),
                                  'first_change_x': boundary}}
    plan['plan_sha256'] = _digest(plan)
    return plan


def render_heading(image, plan):
    """Render the one prescribed crop, padding and BICUBIC scale."""
    _checked_plan(plan)
    rgb = image.convert('RGB')
    if (list(image.size) != plan['image_size'] or
            hashlib.sha256(rgb.tobytes()).hexdigest() != plan['source_pixel_sha256']):
        raise ValueError('Heading image differs from the planned current frame')
    crop = rgb.crop(tuple(plan['crop_box']))
    padded = ImageOps.expand(crop, border=plan['padding_source_pixels'], fill='white')
    return padded.resize((padded.width * 4, padded.height * 4), Image.Resampling.BICUBIC)


def parse_heading_tsv(raw, plan):
    """Keep every nonempty word token, including low confidence, with geometry."""
    _checked_plan(plan)
    if not isinstance(raw, str) or len(raw.encode()) > 131072:
        raise ValueError('Heading TSV is malformed or exceeds bound')
    reader = csv.DictReader(io.StringIO(raw), delimiter='\t')
    if reader.fieldnames != _TSV_FIELDS:
        raise ValueError('Heading TSV header is malformed')
    tokens = []
    crop, pad, scale = plan['crop_box'], plan['padding_source_pixels'], plan['scale']
    rendered = [(crop[2] - crop[0] + 2 * pad) * scale,
                (crop[3] - crop[1] + 2 * pad) * scale]
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Heading TSV row is malformed')
        text = row['text'].strip()
        if not text:
            continue
        try:
            level = int(row['level'])
            left, top, width, height = (int(row[key]) for key in ('left', 'top', 'width', 'height'))
            confidence = float(row['conf'])
        except (ValueError, TypeError):
            raise ValueError('Heading TSV token values are malformed') from None
        if (level != 5 or len(text) > 256 or not math.isfinite(confidence) or not -1 <= confidence <= 100 or
                not (0 <= left < left + width <= rendered[0] and
                     0 <= top < top + height <= rendered[1]) or len(tokens) >= 512):
            raise ValueError('Heading TSV token geometry/confidence exceeds bound')
        tokens.append({'text': text, 'confidence': confidence,
                       'OCR_bounds': [left, top, left + width, top + height],
                       'bounds': [crop[0] + left / scale - pad,
                                  crop[1] + top / scale - pad,
                                  crop[0] + (left + width) / scale - pad,
                                  crop[1] + (top + height) / scale - pad],
                       'heading_plan_sha256': plan['plan_sha256'],
                       'source_screenshot_sha256': plan['source_screenshot_sha256']})
    return tokens


def _overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def merge_heading_metadata(metadata, plan, tokens):
    """Merge exact same-row overlap only after complete regular-MB proof."""
    _checked_plan(plan)
    width, height = _frame(metadata, plan['image_size'])
    if (_digest(metadata) != plan['source_metadata_sha256'] or
            metadata['screenshot_sha256'] != plan['source_screenshot_sha256'] or
            metadata['native_tree'] != plan['source_native_tree'] or
            'download_heading_transform' in metadata):
        raise ValueError('Heading metadata is stale, changed or already supplemented')
    if not isinstance(tokens, list) or not 1 <= len(tokens) <= 512:
        raise ValueError('Heading token inventory is incomplete')
    crop = plan['crop_box']
    pad, scale = plan['padding_source_pixels'], plan['scale']
    rendered = [(crop[2] - crop[0] + 2 * pad) * scale,
                (crop[3] - crop[1] + 2 * pad) * scale]
    for token in tokens:
        if (not isinstance(token, dict) or
                token.get('heading_plan_sha256') != plan['plan_sha256'] or
                token.get('source_screenshot_sha256') != plan['source_screenshot_sha256']):
            raise ValueError('Heading token frame/plan does not match')
        score, text = token.get('confidence'), token.get('text')
        original_bounds = token.get('OCR_bounds') or []
        if (not isinstance(text, str) or not text.strip() or len(text) > 256 or
                type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 100 or
                len(original_bounds) != 4 or any(type(value) is not int for value in original_bounds) or
                not (0 <= original_bounds[0] < original_bounds[2] <= rendered[0] and
                     0 <= original_bounds[1] < original_bounds[3] <= rendered[1])):
            raise ValueError('Heading token values/original geometry are malformed')
        bounds = token.get('bounds') or []
        if (len(bounds) != 4 or not all(type(value) in (int, float) and math.isfinite(value) for value in bounds) or
                not (crop[0] <= bounds[0] < bounds[2] <= crop[2] and
                     crop[1] <= bounds[1] < bounds[3] <= crop[3])):
            raise ValueError('Heading token backprojection escaped the heading crop')
        projected = [crop[0] + original_bounds[0] / scale - pad,
                     crop[1] + original_bounds[1] / scale - pad,
                     crop[0] + original_bounds[2] / scale - pad,
                     crop[1] + original_bounds[3] / scale - pad]
        if bounds != projected:
            raise ValueError('Heading token backprojection does not match its raw OCR geometry')
    current = _words(metadata, width, height)
    original_options, original_regular = _light_options(current)
    if original_options and not (len(original_options) == 1 and original_regular is not None):
        raise ValueError('Existing competing or unknown Light option cannot be suppressed')
    usable = _usable(tokens, width, height)
    options, regular = _light_options(usable)
    if len(options) != 1 or regular is None or regular['variant'] != 'regular':
        raise ValueError('Heading lacks one exact high-confidence regular numeric-MB Light caption')
    light = plan['light_token'];h = light['bounds'][3] - light['bounds'][1]
    if any(abs(a - b) > 3 for a, b in zip(regular['bounds'][:2], light['bounds'][:2])):
        raise ValueError('Heading Light caption differs from the current measured row')
    recovered_suffix = regular['suffix_words'][:2]
    for actual, expected in zip(recovered_suffix, plan['current_suffix_words']):
        if (actual['text'] != expected['text'] or
                any(abs(a - b) > 3 for a, b in zip(actual['bounds'], expected['bounds']))):
            raise ValueError('Heading numeric-MB suffix differs from the current same-frame row')
    kept, removed = [], []
    for word in metadata['words']:
        bounds = word.get('bounds') or []
        same_row = (len(bounds) == 4 and all(type(v) in (int, float) and math.isfinite(v) for v in bounds)
                    and _same_baseline(word, light, h))
        if same_row and any(_overlap(bounds, token['bounds']) for token in tokens):
            removed.append(copy.deepcopy(word))
        else:
            kept.append(copy.deepcopy(word))
    merged_words = kept + copy.deepcopy(tokens)
    merged_options, merged_regular = _light_options(_usable(merged_words, width, height))
    if len(merged_options) != 1 or merged_regular is None:
        raise ValueError('Merged words retain competing or ambiguous Light options')
    result = copy.deepcopy(metadata)
    result['words'] = merged_words
    result['download_heading_transform'] = {
        'scope': _SCOPE, 'plan': copy.deepcopy(plan), 'every_token': copy.deepcopy(tokens),
        'removed_words': removed, 'qualified_regular_light': merged_regular,
        'replacement_rule': 'Only original same-baseline tokens with positive overlap with a current heading token are replaced; all other rows are retained.'}
    return result
