"""Genuine MV duplicate-selection adapter. Produces UI actions; never executes game code.

The caller executes typed pickmv queries through the read-only observer and taps
its newly returned live bounds, or resolves semantic patterns from a fresh tree.
Call step only after other control round trips finish. No player data is written
except by those ordinary app UI actions. Missing observations remain NOT_RUN.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

CASES = ('mv_same_suit', 'mv_different_suits', 'mv_max_slots', 'mv_restore')
PLAY_SCENES = {'LiveMv', 'LiveMvCore'}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _positive(value):
    return type(value) is int and value > 0 or type(value) is float and value.is_integer() and value > 0


def _mv(tree):
    return (tree.get('features') or {}).get('mv') or tree.get('mv') or {}


def _scene(tree):
    return (tree.get('screen') or {}).get('scene')


def successful_live_start_count(log):
    if isinstance(log, str):
        log = log.encode()
    pattern = rb'^\[GIN\].*?\|\s*(\d{3})\s*\|.*?\|\s*POST\s+"([^"\r\n]+)"\s*$'
    return sum(1 for match in re.finditer(pattern, log, re.M)
               if 200 <= int(match[1]) < 300 and match[2].split(b'?', 1)[0] == b'/liveMv/start')


def deck_layout(tree):
    """Read every active custom slot; do not collapse repeated members or suits."""
    result = {}
    for cell in _mv(tree).get('deckCells', []):
        if not cell.get('active') or not re.search(r'(?:^|\.)DeckMemberCustomVO$', cell.get('voClass') or ''):
            continue
        position, member, suit = (cell.get(k) for k in ('formationPosition', 'memberId', 'suitId'))
        if not all(_positive(v) for v in (position, member, suit)) or int(position) in result:
            return None
        result[int(position)] = {'memberId': int(member), 'suitId': int(suit)}
    return result or None


def standing_count(tree):
    value = _mv(tree).get('standingMemberNum')
    return int(value) if _positive(value) and value <= 12 else None


def independent_live_members(tree, expected):
    """Bind actual 3D instances to the requested member/suit and slot identities."""
    if _scene(tree) not in PLAY_SCENES or not expected:
        return None
    groups = {}
    for member in _mv(tree).get('liveMembers', []):
        if member.get('active') is not True:
            continue
        position = member.get('formationPosition')
        if not _positive(position) or int(position) not in expected:
            continue
        groups.setdefault(int(position), []).append(member)
    if set(groups) != set(expected) or any(len(values) != 1 for values in groups.values()):
        return None
    values = [groups[position][0] for position in sorted(expected)]
    ids = [str(v.get('id') or '') for v in values]
    game_ids = [str(v.get('gameObjectId') or '') for v in values]
    if '' in ids or '' in game_ids or len(set(ids)) != len(ids) or len(set(game_ids)) != len(game_ids):
        return None
    for position, member in zip(sorted(expected), values):
        actual = {name: member.get(name) for name in ('memberId', 'suitId')}
        if actual != expected[position]:
            return None
        if not all(_number((member.get('position') or {}).get(axis)) for axis in ('x', 'y', 'z')):
            return None
    # Duplicate characters must have different actual formation transforms.
    transforms = [tuple(v['position'][axis] for axis in ('x', 'y', 'z')) for v in values]
    if len(set(transforms)) != len(transforms):
        return None
    return {position: {'id': str(groups[position][0]['id']),
                       'gameObjectId': str(groups[position][0]['gameObjectId']),
                       'memberId': expected[position]['memberId'], 'suitId': expected[position]['suitId'],
                       'position': groups[position][0]['position']} for position in sorted(expected)}


def validated_pick(picked, query, *, max_age_ms=1500, now_ms=None):
    """Validate the fresh observer response before caller issues its adb tap."""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    timestamp = picked.get('timestampMs')
    target, screen = picked.get('target') or {}, picked.get('screen') or {}
    if not _number(timestamp) or not 0 <= now_ms - timestamp <= max_age_ms:
        raise ValueError('MV tap requires a fresh read-only pick response')
    if not all(target.get(key) is True for key in ('active', 'enabled', 'visible', 'groupsInteractable', 'blocksRaycasts')):
        raise ValueError('MV target is not currently actionable')
    hit, center = target.get('hit') or {}, target.get('center') or {}
    if hit.get('available') is not True or hit.get('hittable') is not True:
        raise ValueError('MV target has no successful current raycast')
    x, y = center.get('x'), center.get('y')
    bounds = target.get('visibleBounds') or target.get('bounds') or {}
    if not all(_number(v) for v in (x, y, screen.get('width'), screen.get('height'))) or not (0 <= x < screen['width'] and 0 <= y < screen['height']):
        raise ValueError('MV tap is outside its live Unity surface')
    if not (bounds.get('left', x + 1) <= x < bounds.get('right', x) and bounds.get('top', y + 1) <= y < bounds.get('bottom', y)):
        raise ValueError('MV tap is outside current clipped bounds')
    catalog = picked.get('catalog') or {}
    if query['role'] in ('member', 'suit') and catalog.get('formationPosition') != query.get('formationPosition'):
        raise ValueError('MV pick returned another formation slot')
    if query['role'] == 'picker' and catalog.get('memberId') != query.get('memberId'):
        raise ValueError('MV pick returned another character')
    if query['role'] == 'suitPicker' and (catalog.get('suitId') != query.get('suitId') or catalog.get('memberId') != query.get('memberId')):
        raise ValueError('MV pick returned another costume')
    return int(round(x)), int(round(y))


class MVDriver:
    def __init__(self, evidence_root, *, required_capacity=12):
        if type(required_capacity) is not int or not 2 <= required_capacity <= 12:
            raise ValueError('Required MV capacity must be an actual2..12 standing count')
        self.required_capacity = required_capacity
        self.root = Path(evidence_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cases = {name: {'status': 'NOT_RUN', 'evidence': []} for name in CASES}
        self.phase, self.case = 'baseline', CASES[0]
        self.baseline = self.expected = None
        self.positions, self.member, self.suit, self.other_suit = [], None, None, None
        self.live_master_id = self.capacity = None
        self.proofs, self.videos = {}, {}
        self.video_requested_at = {}
        self.first_live = None
        self.request_before = 0
        self.retry_key, self.retry_at, self.retry_count = None, 0, 0
        self.blocked_reason = None
        self.baseline_snapshot = self.restored_snapshot = None
        self.saw_outside_deck = False

    def _path(self, relative):
        path = self.root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(self.root):
            raise ValueError('MV evidence must stay inside this run artifact')
        return path

    def _reference(self, relative):
        path = self._path(relative)
        if not path.is_file():
            raise ValueError('Actual MV evidence artifact is absent')
        return {'path': str(relative), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def _write(self, name, value):
        relative = 'mv-' + name + '.json'
        self._path(relative).write_text(json.dumps(value, indent=2) + '\n')
        return relative

    def _action(self, action, now):
        key = json.dumps([self.case, self.phase, action], sort_keys=True)
        if key == self.retry_key and now - self.retry_at < 4:
            return {'kind': 'wait', 'seconds': .3, 'reason': 'Await actual UI state transition'}
        if key != self.retry_key:
            self.retry_key, self.retry_count = key, 0
        self.retry_count += 1
        self.retry_at = now
        if self.retry_count > 3:
            self._fail('Genuine MV UI action did not produce its expected observed transition')
            return None
        return action

    def _fail(self, reason):
        self.blocked_reason = reason
        self.cases[self.case] = {'status': 'FAIL', 'evidence': self.cases[self.case]['evidence'], 'detail': reason}
        self.phase = 'failed'

    def _desired(self):
        expected = {p: dict(v) for p, v in self.baseline.items()}
        selected = self.positions if self.case == 'mv_max_slots' else self.positions[:2]
        for position in selected:
            expected[position] = {'memberId': self.member, 'suitId': self.suit}
        if self.case == 'mv_different_suits':
            if self.other_suit is None:
                return None
            expected[self.positions[1]]['suitId'] = self.other_suit
        return expected

    def _choose_cell(self, tree, role, wanted):
        cells = _mv(tree).get('pickerCells' if role == 'picker' else 'suitPickerCells', [])
        return [c for c in cells if c.get('active') is True and all(c.get(k) == v for k, v in wanted.items())
                and (c.get('target') or {}).get('visible') is True and ((c.get('target') or {}).get('hit') or {}).get('hittable') is True]

    def _edit(self, tree, desired, now):
        layout = deck_layout(tree)
        if layout is None:
            return None
        for position in self.positions:
            actual, wanted = layout.get(position), desired[position]
            if actual is None:
                self.blocked_reason = 'Actual editable formation slot is absent from the observer'
                return None
            if actual['memberId'] != wanted['memberId']:
                cells = self._choose_cell(tree, 'picker', {'memberId': wanted['memberId']})
                if len(cells) != 1 and any(c.get('active') is True for c in _mv(tree).get('pickerCells', [])):
                    return self._action({'kind': 'scroll', 'context': 'mv_member_picker', 'direction': 'forward', 'reason': 'Re-search actual popup ScrollRect for requested character'}, now)
                query = {'role': 'picker', 'memberId': wanted['memberId']} if len(cells) == 1 else {'role': 'member', 'formationPosition': position}
                return self._action({'kind': 'pickmv', 'query': query, 'reason': 'Select actual duplicate character through MV picker'}, now)
            if actual['suitId'] != wanted['suitId']:
                cells = self._choose_cell(tree, 'suitPicker', {'memberId': wanted['memberId'], 'suitId': wanted['suitId']})
                if len(cells) != 1 and any(c.get('active') is True for c in _mv(tree).get('suitPickerCells', [])):
                    return self._action({'kind': 'scroll', 'context': 'mv_suit_picker', 'direction': 'forward', 'reason': 'Re-search actual popup ScrollRect for requested costume'}, now)
                query = {'role': 'suitPicker', 'memberId': wanted['memberId'], 'suitId': wanted['suitId']} if len(cells) == 1 else {'role': 'suit', 'formationPosition': position}
                return self._action({'kind': 'pickmv', 'query': query, 'reason': 'Select actual costume through MV suit picker'}, now)
        return {'kind': 'edit_complete'}

    def step(self, tree, snapshot_relative, *, now=None, live_start_count=0):
        """Return one UI plan. Caller must re-snapshot after executing each plan."""
        if type(live_start_count) is not int or live_start_count < 0:
            raise ValueError('MV case requires actual successful request count, not an aggregate Boolean')
        now = time.monotonic() if now is None else now
        self._reference(snapshot_relative)  # Never award evidence for an absent snapshot.
        scene, mv = _scene(tree), _mv(tree)
        if self.phase in ('done', 'failed'):
            return None
        if self.phase == 'baseline':
            layout, capacity = deck_layout(tree), standing_count(tree)
            if scene == 'LiveMvDeckSelect' and not layout:
                self.blocked_reason = 'Waiting for actual editable custom MV tab; never start Original formation as duplicate proof'
                return self._action({'kind': 'semantic', 'patterns': ['^Custom$', '^Custom\\s+(?:Formation|Lineup)$', '^カスタム$'], 'reason': 'Select actual custom MV formation tab'}, now)
            if scene != 'LiveMvDeckSelect' or capacity is None:
                self.blocked_reason = 'Waiting for actual custom MV deck and StandingMemberNum'
                return None
            if capacity != self.required_capacity:
                self.blocked_reason = 'Choose the official requested standing capacity song before duplicate QA; observed=' + str(capacity) + ', required=' + str(self.required_capacity)
                return None
            if capacity < 2 or len(layout) != capacity:
                self.blocked_reason = 'Choose a song with at least two standing slots; require all actual song slots observed'
                return None
            self.baseline, self.capacity = layout, capacity
            self.positions = sorted(layout)
            self.member, self.suit = (layout[self.positions[0]][k] for k in ('memberId', 'suitId'))
            self.live_master_id = mv.get('liveMasterId')
            if not _positive(self.live_master_id):
                self.baseline = None
                self.blocked_reason = 'Actual song LiveMasterId is absent'
                return None
            self.baseline_snapshot = snapshot_relative
            self._write('baseline', {'deck': layout, 'standingMemberNum': capacity, 'liveMasterId': self.live_master_id,
                                         'snapshot': self._reference(snapshot_relative), 'scope': 'All slots of this selected official song; no global12 claim'})
            self.phase = 'edit'
        if self.phase == 'edit':
            # Costume candidates are actual rendered picker cells. A visible,
            # hittable button plus resulting deck ID transition proves selection;
            # no fabricated unlock field or closet-row collapsing is used.
            if self.case == 'mv_different_suits' and self.other_suit is None:
                candidates = [c for c in mv.get('suitPickerCells', []) if c.get('memberId') == self.member and
                              _positive(c.get('suitId')) and c['suitId'] != self.suit and c.get('active') is True and
                              (c.get('target') or {}).get('visible') is True and ((c.get('target') or {}).get('hit') or {}).get('hittable') is True]
                if candidates:
                    self.other_suit = int(sorted(candidates, key=lambda c: c['suitId'])[0]['suitId'])
                else:
                    if any(c.get('active') is True for c in mv.get('suitPickerCells', [])):
                        return self._action({'kind': 'scroll', 'context': 'mv_suit_picker', 'direction': 'forward', 'reason': 'Re-search actual popup ScrollRect for a second selectable costume'}, now)
                    return self._action({'kind': 'pickmv', 'query': {'role': 'suit', 'formationPosition': self.positions[1]},
                                         'reason': 'Inspect actual available costume choices for same character'}, now)
            self.expected = self._desired()
            action = self._edit(tree, self.expected, now)
            if not action or action['kind'] != 'edit_complete':
                return action
            self.selected_snapshot = snapshot_relative
            self.request_before = live_start_count
            self.phase = 'start_video'
        if self.phase == 'start_video':
            self.video_requested_at[self.case] = now
            self.phase = 'launch'
            return {'kind': 'video_start', 'case': self.case, 'reason': 'Record actual independent MV objects and playback'}
        if self.phase == 'launch':
            if scene in PLAY_SCENES:
                self.phase, self.first_live = 'watch', None
            else:
                return self._action({'kind': 'semantic', 'patterns': ['^PlayButton$'], 'reason': 'Start this actual selected MV deck'}, now)
        if self.phase == 'watch':
            if live_start_count <= self.request_before:
                self.blocked_reason = 'Await a new actual successful /liveMv/start request for this case'
                return None
            actual = independent_live_members(tree, self.expected)
            if actual is None:
                self.blocked_reason = 'Await actual independent LiveCoreMember IDs/formations/member/suit identities'
                return None
            if self.first_live is None:
                self.first_live = (now, actual, snapshot_relative)
                return {'kind': 'wait', 'seconds': .3, 'reason': 'Observe actual independent MV instances over at least3seconds'}
            first_time, first, first_path = self.first_live
            if now - first_time < 3:
                return {'kind': 'wait', 'seconds': .3, 'reason': 'Bounded actual MV playback observation'}
            if any(first[p]['id'] != actual[p]['id'] or first[p]['gameObjectId'] != actual[p]['gameObjectId'] for p in self.positions):
                self._fail('Actual MV member instance identity changed across playback proof')
                return None
            proof = {'case': self.case, 'liveMasterId': self.live_master_id, 'standingMemberNum': self.capacity,
                     'filled_slots': len(self.expected), 'instantiated_slots': len(actual), 'expected_deck': self.expected,
                     'first_instances': first, 'last_instances': actual, 'elapsed_seconds': now - first_time,
                     'video_requested_monotonic': self.video_requested_at[self.case],
                     'first_observed_monotonic': first_time, 'last_observed_monotonic': now,
                     'fresh_live_start_count_before': self.request_before, 'fresh_live_start_count_after': live_start_count,
                     'snapshots': [self._reference(self.selected_snapshot), self._reference(first_path), self._reference(snapshot_relative)],
                     'scope': 'Selected official song maximum; global12 coverage is not inferred'}
            self.proofs[self.case] = self._write(self.case + '-playback', proof)
            self.phase = 'exit'
            return {'kind': 'video_stop', 'case': self.case, 'reason': 'Preserve per-case genuine playback clip'}
        if self.phase == 'exit':
            if scene == 'LiveMvDeckSelect':
                index = CASES.index(self.case)
                self.case = CASES[index + 1]
                self.phase, self.first_live = ('restore' if self.case == 'mv_restore' else 'edit'), None
                self.retry_key = None
                return self.step(tree, snapshot_relative, now=now, live_start_count=live_start_count)
            if scene == 'LiveMusicSelect':
                return self._action({'kind': 'semantic', 'patterns': ['^EnableMvBtn$', '^MvBtnDownload$'], 'reason': 'Reopen the selected official MV deck'}, now)
            nodes = [n for n in tree.get('nodes', []) if n.get('active') and n.get('visible')]
            quit_targets = [n for n in nodes if re.fullmatch(r'(?:QuitButton|RetireButton|ReturnToSongSelectButton|BackToMusicSelectButton)', n.get('name') or '') and re.search(r'Pause|LiveMv|LiveMV', n.get('path') or '')]
            if quit_targets:
                return self._action({'kind': 'semantic', 'patterns': ['^(?:QuitButton|RetireButton|ReturnToSongSelectButton|BackToMusicSelectButton)$'], 'reason': 'Leave only the actual MV playback through its normal pause UI'}, now)
            if not getattr(self, 'back_sent_' + self.case, False):
                setattr(self, 'back_sent_' + self.case, True)
                return {'kind': 'key', 'key': 'KEYCODE_BACK', 'reason': 'Open ordinary MV pause/back UI'}
            self.blocked_reason = 'Await observed safe MV pause/return action; do not invent a tap or callback'
            return None
        if self.phase == 'restore':
            if scene != 'LiveMvDeckSelect':
                return None
            action = self._edit(tree, self.baseline, now)
            if not action or action['kind'] != 'edit_complete':
                return action
            self.restored_snapshot = snapshot_relative
            self.phase = 'restore_reopen'
            return {'kind': 'key', 'key': 'KEYCODE_BACK', 'reason': 'Leave restored MV deck through ordinary navigation before persistence check'}
        if self.phase == 'restore_reopen':
            if scene != 'LiveMvDeckSelect':
                self.saw_outside_deck = True
                if scene == 'LiveMusicSelect':
                    return self._action({'kind': 'semantic', 'patterns': ['^EnableMvBtn$', '^MvBtnDownload$'], 'reason': 'Reopen same MV through normal UI to prove restored persistence'}, now)
                return None
            if not self.saw_outside_deck:
                return None
            if mv.get('liveMasterId') != self.live_master_id or deck_layout(tree) != self.baseline:
                self._fail('Restored MV deck did not persist after ordinary UI leave/reopen')
                return None
            path = self._write('mv_restore', {'baseline': self.baseline, 'reopened': deck_layout(tree),
                'liveMasterId': self.live_master_id, 'standingMemberNum': self.capacity,
                'left_deck_before_reopen': True, 'snapshots': [self._reference(p) for p in (self.baseline_snapshot, self.restored_snapshot, snapshot_relative)]})
            self.cases['mv_restore'] = {'status': 'PASS', 'evidence': [self._reference(path)], 'detail': 'Entire original MV custom deck restored and persisted through ordinary leave/reopen UI'}
            self.phase = 'done'
        return None

    def record_video(self, case, relative):
        """Called only after caller stops/pulls that case's real screenrecord clip."""
        if case not in CASES[:3] or case not in self.proofs or self.cases[case]['status'] == 'FAIL':
            raise ValueError('MV video has no matching actual playback proof')
        path = self._path(relative)
        if not path.is_file() or path.stat().st_size < 32:
            raise ValueError('Actual MV video artifact is absent')
        with path.open('rb') as stream:
            if b'ftyp' not in stream.read(32):
                raise ValueError('MV video artifact is not an actual MP4 container')
        result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,nb_read_frames:format=duration', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=30, check=True)
        media = json.loads(result.stdout)
        streams = media.get('streams') or []
        duration = float((media.get('format') or {}).get('duration', 0))
        if len(streams) != 1 or int(streams[0].get('nb_read_frames', 0)) < 3 or not math.isfinite(duration) or duration < 3 or not all(int(streams[0].get(k, 0)) > 0 for k in ('width', 'height')):
            raise ValueError('MV clip lacks actual decoded frames and at least3seconds of playback')
        playback = json.loads(self._path(self.proofs[case]).read_text())
        requested, observed = playback.get('video_requested_monotonic'), playback.get('last_observed_monotonic')
        if not _number(requested) or not _number(observed) or observed <= requested or duration + .5 < observed - requested:
            raise ValueError('Actual clip ended before the observed MV playback proof; a startup-only video is insufficient')
        video_proof = self._write(case + '-video', {'video': self._reference(relative), 'ffprobe': media,
            'playback': self._reference(self.proofs[case]), 'duration_seconds': duration})
        reference = self._reference(relative)
        if any(self._reference(json.loads(self._path(existing).read_text())['video']['path'])['sha256'] == reference['sha256'] for existing in self.videos.values()):
            raise ValueError('Each MV case requires its own actual playback clip, not reused video bytes')
        self.videos[case] = video_proof
        self.cases[case] = {'status': 'PASS', 'evidence': [self._reference(self.proofs[case]), self._reference(video_proof), self._reference(relative)],
                            'detail': 'Actual selected duplicate deck, fresh MV request, independent3D instances/formations over time, and decoded per-case video'}
        return self.cases[case]

    def results(self):
        return {'phase': self.phase, 'cases': self.cases, 'blocked_reason': self.blocked_reason,
                'standingMemberNum': self.capacity, 'requiredStandingMemberNum': self.required_capacity, 'scope': 'All actual standing slots of the selected official song; global12 not inferred',
                'video_required': list(CASES[:3]), 'no_new_costume_entries': 'Owned by parent: compare before/after master+owned suit counts after all actual MV cases/restore pass'}
