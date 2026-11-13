"""Exact GL modal recognition and one bounded ordinary-input plan.

No ADB, process execution, network access, or observer in this pure module.
Host tests on retained evidence do not qualify any actual client feature.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

MIN_CONFIDENCE = 75
BODY = ('Download', 'error', 'has', 'occurred.', 'Will', 'you', 'retry?')


class NativeDownloadError(RuntimeError):
    pass


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _center(bounds):
    return ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)


def exact_error(metadata, png_bytes, frame):
    """Match only the complete retained English Error/No/Yes modal.

    Missing, ambiguous, malformed, low-confidence, or differently positioned
    captions cannot authorize a retry. Coordinates come from this capture.
    """
    try:
        width, height = frame
        if type(width) is not int or type(height) is not int or min(frame) <= 0:
            return None
        surface = {'left': 0, 'top': 0, 'right': width, 'bottom': height}
        if metadata['surface'] != surface:
            return None
        digest = hashlib.sha256(png_bytes).hexdigest()
        if metadata['screenshot_sha256'] != digest:
            return None

        def one(words, text):
            matches = [word for word in words if word.get('text') == text]
            if len(matches) != 1:
                raise ValueError('Missing or ambiguous exact caption')
            word = matches[0]
            score, box = word['confidence'], word['bounds']
            if not _number(score) or not MIN_CONFIDENCE <= score <= 100:
                raise ValueError('Low or invalid confidence')
            if len(box) != 4 or not all(_number(value) for value in box):
                raise ValueError('Malformed bounds')
            if not (0 <= box[0] < box[2] <= width and
                    0 <= box[1] < box[3] <= height):
                raise ValueError('Caption outside current Surface')
            return {'text': text, 'bounds': list(box), 'confidence': score}

        words = metadata['words']
        title = one(words, 'Error')
        body = [one(words, text) for text in BODY]
        no = one(words, 'No')
        yes = one(metadata['button_words'], 'Yes')
        body_height = max(word['bounds'][3] - word['bounds'][1] for word in body)
        baseline = _center(body[0]['bounds'])[1]
        for word in body:
            if abs(_center(word['bounds'])[1] - baseline) > body_height * .65:
                return None
        for left, right in zip(body, body[1:]):
            gap = right['bounds'][0] - left['bounds'][2]
            if not 0 <= gap <= body_height * 3:
                return None
        title_box, no_box, yes_box = (item['bounds'] for item in (title, no, yes))
        body_top = min(word['bounds'][1] for word in body)
        body_bottom = max(word['bounds'][3] for word in body)
        button_heights = [no_box[3] - no_box[1], yes_box[3] - yes_box[1]]
        if max(button_heights) > 2 * min(button_heights):
            return None
        button_height = min(button_heights)
        if not (title_box[3] < body_top < body_bottom < min(no_box[1], yes_box[1])):
            return None
        if not (no_box[2] < yes_box[0] and
                abs(_center(no_box)[1] - _center(yes_box)[1]) <= button_height * .65):
            return None
        if not (body[0]['bounds'][0] < _center(title_box)[0] < body[-1]['bounds'][2]):
            return None
        return {'kind': 'native-game-download-error', 'caption': 'Download error has occurred. Will you retry?',
                'surface': surface, 'screenshot_sha256': digest,
                'title': title, 'body': body, 'no': no, 'yes': yes,
                'action': None, 'scope': 'Actual rendered error; underlying exception is not inferred.'}
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def fail_for_error(match):
    """Fail specifically after saving an actual error; never infer its cause."""
    if match is not None:
        raise NativeDownloadError(
            'Game download error before Home: exact Error / '
            '"Download error has occurred. Will you retry?" / No / Yes modal; '
            'inspect the retained capture and PID-scoped network diagnostics. '
            'No download completion or MV case was observed.')


@dataclass(frozen=True)
class FixedEnds:
    overall_started: float
    bulk_started: float
    overall_end: float
    bulk_end: float

    def valid(self, now):
        return (all(_number(value) for value in (self.overall_started, self.bulk_started,
                                                self.overall_end, self.bulk_end, now)) and
                self.overall_started <= self.bulk_started <= now and
                self.overall_end == self.overall_started + 2400 and
                self.bulk_end == self.bulk_started + 1800 and
                now < min(self.overall_end, self.bulk_end))


class OptionalOneNativeRetry:
    """Default disabled. Produces one plan; never performs input.

    Future integration must persist+flush the intent before an ordinary native
    tap, recheck PID/start_ticks immediately before input, then recheck outcome.
    The spent intent remains spent even if the tap or later observation fails.
    """
    def __init__(self, *, explicitly_enabled=False):
        self.enabled = explicitly_enabled is True
        self.spent = False

    def plan(self, first, second, *, now, owned_identity, fixed_ends):
        if not self.enabled or self.spent:
            raise NativeDownloadError('Ordinary retry is disabled or already spent')
        if not fixed_ends.valid(now):
            raise NativeDownloadError('Original fixed download/overall end was reached or invalid')
        if (not isinstance(owned_identity, dict) or set(owned_identity) != {'pid', 'start_ticks'} or
                type(owned_identity['pid']) is not int or owned_identity['pid'] <= 0 or
                not str(owned_identity['start_ticks']).isdigit()):
            raise NativeDownloadError('Missing exact owned game lifetime')
        verified = []
        for capture in (first, second):
            if capture.get('identity') != owned_identity:
                raise NativeDownloadError('Game lifetime changed')
            # Revalidate original capture inputs here; a caller-supplied match
            # dictionary, shortened body, or mutated bounds is never trusted.
            match = exact_error(capture.get('metadata', {}), capture.get('png_bytes', b''),
                                capture.get('frame', ()))
            if match is None:
                raise NativeDownloadError('Full exact error capture is missing or invalid')
            verified.append(match)
            if not _number(capture.get('captured_at')):
                raise NativeDownloadError('Missing monotonic capture time')
        if not (first['label'] != second['label'] and
                first['captured_at'] < second['captured_at'] <= now and
                now - first['captured_at'] <= 8):
            raise NativeDownloadError('Retry requires two distinct fresh captures within eight seconds')
        a, b = verified
        if a['surface'] != b['surface'] or a['caption'] != b['caption']:
            raise NativeDownloadError('Error modal Surface or exact caption changed')
        for role in ('title', 'no', 'yes'):
            if any(abs(x-y) > 3 for x, y in zip(a[role]['bounds'], b[role]['bounds'])):
                raise NativeDownloadError('Error modal geometry changed')
        if any(any(abs(x-y) > 3 for x, y in zip(left['bounds'], right['bounds']))
               for left, right in zip(a['body'], b['body'])):
            raise NativeDownloadError('Error body geometry changed')
        x, y = map(int, _center(b['yes']['bounds']))
        surface = b['surface']
        if not (surface['left'] <= x < surface['right'] and surface['top'] <= y < surface['bottom']):
            raise NativeDownloadError('Current Yes caption center is outside Surface')
        self.spent = True
        return {'kind': 'one-ordinary-native-Yes-retry-intent', 'center': [x, y],
                'identity': dict(owned_identity), 'captures': [first['label'], second['label']],
                'original_error': a, 'confirmed_error': b, 'retry_index': 1,
                'original_bulk_end': fixed_ends.bulk_end, 'original_overall_end': fixed_ends.overall_end,
                'input_performed': False, 'scope': 'Inert input plan only; no feature qualification.'}
