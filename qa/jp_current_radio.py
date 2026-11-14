"""Pure current-pixel radio observations; never authorizes native input.

Orange grouping and the gray-annulus predicate are derived from the accepted
GL native_download_flow.py. No radio location or selected-Light image is stored.
The caller must associate both returned controls with its current exact labels
and retain the native Surface, fresh-pair and owned-lifetime checks.
"""
import math


class Refusal(ValueError):
    pass


def _center(bounds):
    return [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]


def _components(points):
    parts = []
    while points:
        initial = min(points, key=lambda point: (point[1], point[0]))
        points.remove(initial)
        pending = [initial]
        members = {initial}
        while pending:
            x, y = pending.pop()
            for near in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if near in points:
                    points.remove(near)
                    pending.append(near)
                    members.add(near)
        parts.append({'bounds': [min(x for x, y in members), min(y for x, y in members),
                                 max(x for x, y in members) + 1, max(y for x, y in members) + 1],
                      'pixels': len(members), 'members': members})
    return parts


def _orange_circles(pixels, region, text_height):
    left, top, right, bottom = region
    points = set()
    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b = pixels[x, y]
            if r >= 230 and 70 <= g <= 210 and b <= 80 and r - g >= 30:
                points.add((x, y))
    groups = []
    # GL's ring and inner disk may be separate connected components. Merge
    # overlapping component envelopes, without joining neighboring controls.
    for part in sorted(_components(points), key=lambda value: value['pixels'], reverse=True):
        bounds = part['bounds']
        related = [index for index, group in enumerate(groups)
                   if min(bounds[2], group['bounds'][2]) > max(bounds[0], group['bounds'][0])
                   and min(bounds[3], group['bounds'][3]) > max(bounds[1], group['bounds'][1])]
        merged = [part] + [groups[index] for index in related]
        for index in reversed(related):
            groups.pop(index)
        groups.append({'bounds': [min(value['bounds'][0] for value in merged),
                                  min(value['bounds'][1] for value in merged),
                                  max(value['bounds'][2] for value in merged),
                                  max(value['bounds'][3] for value in merged)],
                       'pixels': sum(value['pixels'] for value in merged)})
    circles = []
    for group in groups:
        left, top, right, bottom = group['bounds']
        width, height = right - left, bottom - top
        if (text_height * .5 <= width <= text_height * 1.8
                and text_height * .5 <= height <= text_height * 1.8
                and .65 <= width / height <= 1.55
                and .12 <= group['pixels'] / (width * height) <= .85):
            circles.append({**group, 'center': _center(group['bounds']),
                            'radius': max(width, height) / 2})
    return circles


def _gray(values):
    return 130 <= min(values) and max(values) <= 245 and max(values) - min(values) <= 18


def _gray_annulus(pixels, center, radius, viewport):
    """Exact GL neutral-gray annulus predicate, within the current viewport."""
    left, top, right, bottom = viewport
    cx, cy = center
    sectors = set()
    count = 0
    for y in range(max(top, int(cy - radius * 1.35)), min(bottom, int(cy + radius * 1.35) + 1)):
        for x in range(max(left, int(cx - radius * 1.35)), min(right, int(cx + radius * 1.35) + 1)):
            distance = math.hypot(x - cx, y - cy)
            if radius * .65 <= distance <= radius * 1.25 and _gray(pixels[x, y]):
                sectors.add(int((math.atan2(y - cy, x - cx) + math.pi) / (math.pi / 4)) % 8)
                count += 1
    return {'present': len(sectors) >= 6 and count >= radius * 2,
            'covered_octants': len(sectors), 'gray_pixels': count}


def _closed_ring(members, bounds, center):
    """A connected arc or clipped component cannot stand in for a full ring."""
    left, top, right, bottom = bounds
    seed = (int(center[0]), int(center[1]))
    if seed in members:
        return False
    pending = [seed]
    seen = {seed}
    while pending:
        x, y = pending.pop()
        if x <= left or x >= right - 1 or y <= top or y >= bottom - 1:
            return False
        for near in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if near not in members and near not in seen:
                seen.add(near)
                pending.append(near)
    return True


def observe(image, viewport, text_height):
    """Return one current selected control and one complete unselected control.

    ``viewport`` is the current modal content viewport, never the full screen.
    Role names Bulk/Light deliberately remain the current-label caller's job.
    """
    width, height = image.size
    if (not isinstance(viewport, (tuple, list)) or len(viewport) != 4
            or any(type(value) is not int for value in viewport)
            or not (0 <= viewport[0] < viewport[2] <= width
                    and 0 <= viewport[1] < viewport[3] <= height)
            or not isinstance(text_height, (int, float)) or isinstance(text_height, bool)
            or not math.isfinite(text_height) or text_height <= 0):
        raise Refusal('Current JP radio viewport or measured caption height is invalid')
    with image.convert('RGB') as rgb:
        pixels = rgb.load()
        orange = _orange_circles(pixels, viewport, text_height)
        if len(orange) != 1:
            raise Refusal('Current JP selected orange radio is absent, altered or not unique')
        selected = orange[0]
        sx, sy = selected['center']
        radius = selected['radius']
        left, top, right, bottom = viewport
        if not (left < sx - radius and sx + radius < right
                and top < sy - radius and sy + radius < bottom):
            raise Refusal('Current JP selected radio is clipped by the content viewport')
        # Search only the current selected control's x/radius column. Every
        # candidate center comes from a present neutral-gray component envelope.
        column_left = max(left, math.floor(sx - radius * 1.5))
        column_right = min(right, math.ceil(sx + radius * 1.5))
        points = {(x, y) for y in range(top, bottom) for x in range(column_left, column_right)
                  if _gray(pixels[x, y])}
        gray = []
        for part in _components(points):
            bounds = part['bounds']
            component_width, component_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            center = _center(bounds)
            candidate_radius = max(component_width, component_height) / 2
            if not (radius * 1.5 <= component_width <= radius * 2.5
                    and radius * 1.5 <= component_height <= radius * 2.5
                    and .65 <= component_width / component_height <= 1.55
                    and abs(center[0] - sx) <= radius * .25
                    and abs(center[1] - sy) > radius * 4
                    and abs(candidate_radius - radius) <= radius * .25):
                continue
            if not (left < center[0] - candidate_radius and center[0] + candidate_radius < right
                    and top < center[1] - candidate_radius and center[1] + candidate_radius < bottom):
                continue
            if not _closed_ring(part['members'], bounds, center):
                continue
            annulus = _gray_annulus(pixels, center, candidate_radius, viewport)
            if annulus['present']:
                gray.append({'bounds': bounds, 'center': center, 'radius': candidate_radius,
                             'pixels': part['pixels'], 'annulus': annulus})
        if len(gray) != 1:
            raise Refusal('Current JP unselected gray radio is absent, clipped, fragmented or not unique')
        return {'selected': selected, 'unselected': gray[0], 'viewport': list(viewport),
                'both_radio_extents_visible': True,
                'scope': 'Current pixels only; caller must establish exact current labels and fresh native pair'}
