"""Small read-only guards for the native-only download-choice diagnostic."""
import hashlib
import math
from pathlib import Path
import re
import signal
import time


class NativeDeadlines:
    """Phase alarms share the original immutable overall deadline."""
    overall_reason='Native overall wall bound reached; remaining cases are unobserved'

    def __init__(self,started,max_seconds,error_type,*,clock=time.monotonic,timer=signal.setitimer):
        self.overall_deadline=started+max_seconds
        self.error_type=error_type;self.clock=clock;self.timer=timer
        self.reason=self.overall_reason

    def arm(self,seconds,reason=None):
        remaining=self.overall_deadline-self.clock()
        if remaining<=0:raise self.error_type(self.overall_reason)
        self.reason=self.overall_reason
        if seconds is not None:
            assert isinstance(seconds,(int,float)) and 0<seconds<=45
            if seconds<remaining:self.reason=reason or 'Native phase deadline reached'
            remaining=min(remaining,seconds)
        self.timer(signal.ITIMER_REAL,remaining)

    def handle(self,signum,frame):
        raise self.error_type(self.reason)

    def arm_until(self,deadline,reason):
        """A fixed phase end may shorten, but never renew, the overall end."""
        assert isinstance(deadline,(int,float)) and math.isfinite(deadline)
        now=self.clock()
        if now>=self.overall_deadline:raise self.error_type(self.overall_reason)
        if now>=deadline:raise self.error_type(reason)
        self.reason=reason if deadline<self.overall_deadline else self.overall_reason
        self.timer(signal.ITIMER_REAL,min(deadline,self.overall_deadline)-now)


def _settings_identity(observed):
    info=observed.get('observations') or {}
    full,light=info.get('full_caption'),info.get('light_caption')
    action=observed.get('action') or {}
    if not full or not light or action.get('kind') not in ('scroll-download','choose-light','confirm-light'):
        return None
    return (action['kind'],info.get('selected_radio'),tuple(full['bounds']),tuple(light['bounds']))


class SettingsProgress:
    """A missing caption never extends the deadline; pixel animation is ignored."""
    def __init__(self,now,*,idle_seconds=45):
        if type(idle_seconds) is not int or idle_seconds not in (45,120):
            raise ValueError('Chooser idle budget must be default45 or explicit manual120seconds')
        self.idle_seconds=idle_seconds
        self.absolute_deadline=now+120
        self.stagnant_deadline=now+idle_seconds
        self.identity=None

    def observe(self,observed,now):
        current=_settings_identity(observed)
        changed=current is not None and (self.identity is None or current[:2]!=self.identity[:2] or
            any(abs(a-b)>4 for before,after in zip(self.identity[2:],current[2:]) for a,b in zip(before,after)))
        if changed:self.identity=current;self.stagnant_deadline=now+self.idle_seconds
        remaining=min(self.absolute_deadline,self.stagnant_deadline)-now
        if remaining<=0:raise RuntimeError('Native download settings made no safe semantic progress within'+str(self.idle_seconds)+'seconds or exceeded120seconds total')
        return min(self.idle_seconds,remaining)


class BulkDownloadProgress:
    """Record UI estimates under one fixed1800second initial-download bound.

    Progress does not reset this bound or authorize completion. In particular,
    the settings45second stagnant and120second total limits never apply here.
    """
    def __init__(self,now):
        self.started=now;self.deadline=now+1800
        self.samples=0;self.visible_progress_samples=0;self.first=None;self.latest=None
        self.changed_samples=0;self.last_state=None

    def observe(self,observed,now):
        self.samples+=1;self.last_state=observed['state']
        progress=observed.get('observations',{}).get('download_progress')
        if progress and progress.get('valid_metrics'):
            self.visible_progress_samples+=1
            sample={'elapsed_seconds':round(now-self.started,3),'estimate':progress}
            if self.first is None:self.first=sample
            if self.latest is None or self.latest['estimate']['metrics']!=progress['metrics']:
                self.changed_samples+=1
            self.latest=sample
        if now>=self.deadline:
            raise RuntimeError('Initial regular-Light download did not show guarded Download Complete/Close within1800seconds; last state='+str(self.last_state)+'; UI progress estimates do not imply completion')
        return self.summary(now)

    def summary(self,now):
        return {'phase_limit_seconds':1800,'elapsed_seconds':round(now-self.started,3),
            'samples':self.samples,'visible_progress_samples':self.visible_progress_samples,
            'changed_estimate_samples':self.changed_samples,'first_estimate':self.first,
            'latest_estimate':self.latest,'last_state':self.last_state,
            'scope':'Current native UI estimates only; no exact transferred bytes/rate or bulk-completion claim. Progress never renews the absolute phase or overall bound.'}


class SuccessfulAssetStarts:
    """Observe only fresh complete successful asset GET lines after ordinary OK."""
    pattern=re.compile(rb'^\[GIN\].*?\|\s*(\d{3})\s*\|.*?\|\s*GET\s+"(/static/[A-Za-z0-9_-]{1,160})"\s*$')

    def __init__(self,path):
        self.path=Path(path)
        stat=self.path.stat()
        self.device_inode=(stat.st_dev,stat.st_ino)
        self.offset=stat.st_size
        self.baseline_bytes=self.offset
        self.pending=b''
        self.pending_offset=self.offset

    def read(self):
        stat=self.path.stat()
        if (stat.st_dev,stat.st_ino)!=self.device_inode or stat.st_size<self.offset:
            raise RuntimeError('Owned asset log rotated or truncated during download-start observation')
        if stat.st_size-self.offset>1024*1024:raise RuntimeError('Download-start log growth exceeded the bounded read')
        with self.path.open('rb') as source:
            source.seek(self.offset);data=source.read(1024*1024+1)
        if len(data)>1024*1024:raise RuntimeError('Download-start log read exceeded bound')
        if not self.pending:self.pending_offset=self.offset
        self.offset+=len(data);self.pending+=data
        while b'\n' in self.pending:
            line,self.pending=self.pending.split(b'\n',1);start=self.pending_offset;self.pending_offset+=len(line)+1
            match=self.pattern.fullmatch(line)
            if match and int(match[1])==200:
                return {'path':match[2].decode('ascii'),'status':int(match[1]),
                    'source_byte_offset':start,'source_baseline_bytes':self.baseline_bytes,
                    'raw_line':line.decode('ascii'),'raw_line_sha256':hashlib.sha256(line).hexdigest(),
                    'source_log_name':self.path.name,
                    'scope':'First new completed successful ordinary asset GET after verified regular Light and OK; not bulk-download completion or exact transfer bytes'}
        if len(self.pending)>16384:raise RuntimeError('Owned asset log has an oversize incomplete line')
        return None
