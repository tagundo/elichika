"""Bounded diagnostic-only deadlines for the separate Simulator probe.

Progress never proves readiness. The native, encrypted-protocol, persistence
and signed-bundle gates remain independent mandatory checks in run_simulator.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

from common import require

ABSOLUTE_SECONDS = 600
FIRST_PROGRESS_SECONDS = 60
STAGE_SECONDS = {
    'native_start': 240,
    'native_health': 20,
    'tls': 30,
    'tools': 60,
    'go_stop': 30,
    'config_read': 90,
    'go_restart': 90,
    'python_complete': 10,
    'web_admin': 45,
    'web_tools': 45,
    'complete': 5,
}
DETAILS = {
    'native_start': {'payload_prepare', 'go_start', 'tool_dependencies'},
    'native_backend': {'go_start', 'tool_dependencies'},
    'tools': {'dependencies', 'registries', 'texture_codecs', 'model_glb'},
}
FIELDS = {'schema', 'probe_kind', 'launch_number', 'sequence', 'stage', 'detail',
          'elapsed_seconds', 'stage_elapsed_seconds', 'stage_budget_seconds', 'status',
          'start_uptime_seconds', 'stage_enter_uptime_seconds', 'sample_uptime_seconds'}


def stage_budgets(require_parity_ui=False):
    # Historical full/core paths retain their exact original ordered phases.
    if not require_parity_ui:
        return dict(STAGE_SECONDS)
    budgets = {}
    for name, budget in STAGE_SECONDS.items():
        budgets[name] = budget
        # Actual A first install spent216.234s in data preparation; Go began
        # at224.618s, leaving only15.382s of240 for its separate DB startup.
        # B retains the data cap and adds a real go_start boundary, not a
        # heartbeat extension. The600s absolute cap remains unchanged.
        if name == 'native_start':
            budgets['native_backend'] = 90
        if name == 'web_tools':
            budgets['management_ui'] = 120
    return budgets


def read_progress(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8192,
            'Simulator progress must be a bounded regular JSON file')
    return json.loads(path.read_text())


class ProbeWatchdog:
    def __init__(self, launch_number, started, *, require_parity_ui=False):
        require(launch_number in (1, 2), 'Invalid probe cold-launch number')
        self.launch_number = launch_number
        self.started = started
        self.last = None
        self.stage_deadline = None
        self.events = []
        self.budgets = stage_budgets(require_parity_ui)
        self.rank = {name: position for position, name in enumerate(self.budgets)}

    def observe(self, value, now):
        # A late first heartbeat or transition cannot revive an expired stage.
        self.check(now)
        require(isinstance(value, dict) and set(value).issubset(FIELDS)
                and FIELDS - {'detail'} <= set(value), 'Simulator progress JSON contract differs')
        require(type(value['schema']) is int and value['schema'] == 1
                and value['probe_kind'] == 'native-simulator-progress'
                and type(value['launch_number']) is int and value['launch_number'] == self.launch_number,
                'Simulator progress belongs to a different probe/launch')
        stage, sequence = value['stage'], value['sequence']
        require(stage in self.budgets and type(sequence) is int and 1 <= sequence <= len(self.budgets),
                'Simulator progress stage/sequence is invalid')
        require(value.get('detail', '') in {'', stage, *DETAILS.get(stage, set())},
                'Simulator progress detail is not a reviewed fixed label')
        require(value['status'] in ('running', 'failed', 'complete')
                and (value['status'] != 'complete' or stage == 'complete'),
                'Simulator progress status/stage differs')
        elapsed, stage_elapsed, budget = (value[key] for key in
            ('elapsed_seconds', 'stage_elapsed_seconds', 'stage_budget_seconds'))
        require(all(type(number) in (int, float) and math.isfinite(number) and number >= 0
                    for number in (elapsed, stage_elapsed, budget))
                and budget == self.budgets[stage] and stage_elapsed <= elapsed + .1
                and elapsed <= max(0, now-self.started) + 5,
                'Simulator progress clocks/budget are invalid')
        start, entered, sample = (value[key] for key in
            ('start_uptime_seconds', 'stage_enter_uptime_seconds', 'sample_uptime_seconds'))
        require(all(type(number) in (int, float) and math.isfinite(number) and number >= 0
                    for number in (start, entered, sample))
                and start <= entered <= sample
                and abs(sample-start-elapsed) <= .1 and abs(sample-entered-stage_elapsed) <= .1,
                'Simulator progress monotonic uptime evidence differs')
        require(elapsed < ABSOLUTE_SECONDS and stage_elapsed < budget,
                'Simulator progress actual phase age exceeded its fixed budget: ' + stage)
        changed = self.last is None or stage != self.last['stage']
        if self.last is not None:
            require(elapsed >= self.last['elapsed_seconds']
                    and start == self.last['start_uptime_seconds']
                    and sample >= self.last['sample_uptime_seconds'], 'Simulator progress clock regressed')
            if changed:
                require(self.rank[stage] > self.rank[self.last['stage']]
                        and sequence > self.last['sequence']
                        and entered >= self.last['stage_enter_uptime_seconds'], 'Simulator progress stage order regressed')
            else:
                require(sequence == self.last['sequence'] and stage_elapsed >= self.last['stage_elapsed_seconds']
                        and entered == self.last['stage_enter_uptime_seconds'],
                        'Simulator progress heartbeat changed its stage entrance')
        if changed:
            # Native timestamps can shorten a late-observed budget. They never
            # move its entrance earlier than Popen or reset an existing stage.
            observed_age = min(stage_elapsed, max(0, now-self.started))
            self.stage_deadline = min(self.started + ABSOLUTE_SECONDS,
                                      now + self.budgets[stage] - observed_age)
            self.events.append({'stage': stage, 'sequence': sequence,
                'host_observed_elapsed_seconds': round(max(0, now-self.started), 3),
                'native_elapsed_seconds': elapsed, 'stage_elapsed_seconds': stage_elapsed,
                'stage_budget_seconds': self.budgets[stage]})
        self.last = dict(value)
        require(value['status'] != 'failed', 'Native Simulator progress reported failure in stage: ' + stage)

    def check(self, now):
        self.remaining(now)
        if self.last is None:
            require(now-self.started < FIRST_PROGRESS_SECONDS,
                    'Simulator probe did not produce initial progress within 60 seconds')
        else:
            require(now < self.stage_deadline, 'Simulator probe stage exceeded its fixed budget: ' + self.last['stage'])

    def remaining(self, now):
        remaining = self.started + ABSOLUTE_SECONDS - now
        require(remaining > 0, 'Simulator probe exceeded its absolute 600-second cap')
        return remaining

    def can_read_receipt(self, now):
        self.check(now)
        return bool(self.last and self.last['stage'] == 'complete' and self.last['status'] == 'complete')

    def snapshot(self, now):
        return {'schema': 1, 'diagnostic_only_not_readiness': True,
                'launch_number': self.launch_number, 'absolute_cap_seconds': ABSOLUTE_SECONDS,
                'first_progress_budget_seconds': FIRST_PROGRESS_SECONDS,
                'stage_budgets_seconds': self.budgets,
                'host_elapsed_seconds': round(max(0, now-self.started), 3),
                'last_progress': self.last, 'observed_transitions': self.events,
                'same_stage_heartbeats_extend_deadline': False}
