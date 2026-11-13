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


def _tween_progress_pair_evidence(off, on):
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


def measured_splash_spans(trace, expected_fast):
    """Bound real active-object windows between observed absent frames.

    This supports Jigbox tweens that have duration but no DOTween position.
    Before/after absence gives a conservative upper bound; no preference alone
    or configured duration alone can establish the measured behavior.
    """
    if (trace.get('profile') or {}).get('fast_intro') is not expected_fast:
        return []
    samples = trace.get('samples') or []
    if len(samples) < 5:
        return []
    times = [s.get('timestampMs') for s in samples]
    if not all(type(t) in (int, float) and math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        return []
    ids = []
    for sample in samples:
        for splash in sample.get('splashScreens', []):
            if splash.get('id') is not None and splash['id'] not in ids:
                ids.append(splash['id'])
    result = []
    for ordinal, identity in enumerate(ids):
        indices = [i for i, sample in enumerate(samples) if any(s.get('id') == identity for s in sample.get('splashScreens', []))]
        first, last = indices[0], indices[-1]
        if first == 0 or last == len(samples)-1 or len(indices) < 3 or indices != list(range(first, last + 1)):
            continue
        frames = [samples[i].get('screen', {}).get('frame') for i in indices]
        if not all(type(frame) is int for frame in frames) or any(b < a for a, b in zip(frames, frames[1:])) or frames[-1] - frames[0] < 2:
            continue
        if any(samples[i].get('screen', {}).get('scene') != 'Splash' or
               (samples[i].get('config') or {}).get('fastIntro') != int(expected_fast) for i in indices):
            continue
        durations = [s.get('tween', {}).get('duration') for i in indices for s in samples[i].get('splashScreens', []) if s.get('id') == identity]
        durations = [d for d in durations if type(d) in (int, float) and math.isfinite(d)]
        if len(durations) < 2 or (expected_fast and any(abs(d-.125) > .0001 for d in durations)) or (not expected_fast and any(d <= .126 for d in durations)):
            continue
        lower = (times[last] - times[first]) / 1000
        upper = (times[last+1] - times[first-1]) / 1000
        if lower < .1 or upper <= lower:
            continue
        result.append({'ordinal': ordinal, 'splash_id': identity, 'first_ms': times[first], 'last_ms': times[last],
                       'before_absent_ms': times[first-1], 'after_absent_ms': times[last+1],
                       'active_seconds_lower_bound': lower, 'active_seconds_upper_bound': upper,
                       'first_frame': frames[0], 'last_frame': frames[-1], 'rendered_frame_advance': frames[-1]-frames[0],
                       'samples': len(indices), 'observed_tween_durations': sorted(set(durations))})
    return result


def intro_pair_evidence(off, on):
    progress = _tween_progress_pair_evidence(off, on)
    if progress:
        return progress
    normal, fast = measured_splash_spans(off, False), measured_splash_spans(on, True)
    pairs = [(a, b) for a in normal for b in fast if a['ordinal'] == b['ordinal'] and
             a['active_seconds_lower_bound'] > b['active_seconds_upper_bound'] * 1.2]
    if not pairs:
        return None
    ordinary, accelerated = max(pairs, key=lambda pair: pair[0]['active_seconds_lower_bound'] / pair[1]['active_seconds_upper_bound'])
    return {'normal': ordinary, 'fast': accelerated, 'measurement': 'bounded_actual_splash_active_windows',
            'proof': 'Across ordinary OFF/ON launches, the same ordinal actual Splash object renders advancing frames and is absent before/after its measured active window. Normal observed lower bound exceeds fast conservative upper bound; real tween duration changes to .125 seconds. No configuration-only inference.'}
