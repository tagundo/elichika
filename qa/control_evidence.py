"""Conservative evaluators for measured, read-only game control traces."""
import math


def measured_fades(trace):
    groups = {}
    for sample in trace.get('samples', []):
        at = sample.get('timestampMs')
        if not isinstance(at, (int, float)):
            continue
        for splash in sample.get('splashScreens', []):
            tween = splash.get('tween') or {}
            duration, position = tween.get('duration'), tween.get('position')
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (duration, position)):
                continue
            if duration <= 0 or position < 0 or position > duration + .001:
                continue
            key = (splash.get('id'), tween.get('id'), duration, tween.get('completedLoops'))
            groups.setdefault(key, []).append((at, position))
    result = []
    for key, points in groups.items():
        points.sort()
        for first_index, first in enumerate(points):
            for last in points[first_index + 1:]:
                elapsed = (last[0] - first[0]) / 1000
                progress = last[1] - first[1]
                if elapsed >= .025 and progress >= .025 and .65 <= progress / elapsed <= 1.4:
                    result.append({'splash_id': key[0], 'tween_id': key[1], 'duration': key[2],
                                   'first_ms': first[0], 'last_ms': last[0], 'elapsed_seconds': elapsed,
                                   'position_delta': progress})
    return result


def intro_pair_evidence(off, on):
    """Require actual tween progress, rendered frames and elapsed time both ways."""
    for trace, expected in ((off, False), (on, True)):
        if (trace.get('profile') or {}).get('fast_intro') is not expected:
            return None
        samples = [s for s in trace.get('samples', []) if s.get('splashScreens')]
        if len(samples) < 2 or not any((s.get('config') or {}).get('fastIntro') == int(expected) for s in samples):
            return None
        frames = [s.get('screen', {}).get('frame') for s in samples]
        if not all(type(frame) is int for frame in frames) or frames[-1] <= frames[0]:
            return None
    off_fades = [x for x in measured_fades(off) if x['duration'] > .125 + .001]
    on_fades = [x for x in measured_fades(on) if abs(x['duration'] - .125) < .0001]
    comparisons = [(a, b) for a in off_fades for b in on_fades
                   if a['elapsed_seconds'] > b['elapsed_seconds'] * 1.2]
    if not comparisons:
        return None
    normal, fast = max(comparisons, key=lambda pair: pair[0]['elapsed_seconds'])
    return {'normal': normal, 'fast': fast,
            'proof': 'The real splash tween advances over measured time; fast mode uses .125 seconds and normal mode retains its longer game duration.'}
