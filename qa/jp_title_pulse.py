"""Pure bounded Title-pulse pairing; hidden captions never authorize input."""
import math

from jp_capture_guard import StopCapture, digest, fresh_pair, has_large_pale_panel
from native_capture_support import title_caption

ACTIVITY='com.klab.lovelive.allstars.MainActivity'


def _time(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise StopCapture('Invalid Title monotonic timestamp')
    return value


class TitleCandidates:
    """One visible candidate, without renewing its captures or original ends."""
    def __init__(self,*,owned_identity,overall_started,title_started):
        self.owned=dict(owned_identity)
        self.overall_started=_time(overall_started);self.title_started=_time(title_started)
        if self.overall_started>self.title_started:
            raise StopCapture('Original Title start precedes overall start')
        self.fixed_end=min(self.overall_started+2400,self.title_started+180)
        self.last_now=self.title_started;self.candidate=None;self.last_observation={}

    def clear(self,reason):
        previous=self.candidate['frame']['id'] if self.candidate else None
        self.candidate=None
        self.last_observation={'reason':reason,'discarded_candidate':previous,
            'original_Title_end':self.title_started+180,'original_overall_end':self.overall_started+2400}

    def _fresh(self,frame,now):
        if frame['identity_before']!=self.owned or frame['identity_after']!=self.owned:
            raise StopCapture('Owned Title PID/startticks changed')
        if frame.get('activity')!=ACTIVITY:
            raise StopCapture('Current original JP MainActivity missing for Title')
        times=[_time(frame[key]) for key in ('native_at','captured_at','activity_at')]
        if not times[0]<=times[1]<=times[2]<=now:
            raise StopCapture('Current Title native/PNG/Activity timestamps are not ordered')
        if digest(frame['png_bytes'])!=frame['png_sha256'] or digest(frame['native_xml'])!=frame['native_sha256']:
            raise StopCapture('Current Title capture bytes changed')
        return all(now-value<=8 for value in times)

    def observe(self,frame,words,*,now):
        now=_time(now)
        if now<self.last_now:raise StopCapture('Title monotonic clock regressed')
        self.last_now=now
        if now>=self.fixed_end:
            raise StopCapture('Original fixed Title180second or overall2400second end reached')
        previous=self.candidate['frame']['id'] if self.candidate else None
        expired=None
        if self.candidate and not self._fresh(self.candidate['frame'],now):
            expired=previous;self.candidate=None
        event={'capture':frame['id'],'raw':frame['id']+'.png','candidate_before':previous,
            'expired_candidate':expired,'checked_at':now,
            'original_Title_end':self.title_started+180,'original_overall_end':self.overall_started+2400}
        self.last_observation=event
        if not self._fresh(frame,now):
            self.candidate=None;event['reason']='stale-current-refused';return None
        action=title_caption(words)
        if action is None:
            event['reason']='hidden-or-unrecognized-caption';return None
        box=action['bounds'];width,height=frame['frame']
        if (len(box)!=4 or any(type(value) not in (int,float) or not math.isfinite(value) for value in box)
                or not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height)):
            raise StopCapture('Current Title caption bounds leave the current frame')
        if has_large_pale_panel(frame['png_bytes']):
            self.candidate=None;event['reason']='pale-visible-caption-refused';return None
        current={'frame':frame,'action':action}
        if self.candidate is None:
            self.candidate=current;event['reason']='visible-candidate-retained';return None
        first=self.candidate
        if first['frame']['frame']!=frame['frame'] or first['frame']['surface']!=frame['surface']:
            raise StopCapture('Current Title frame/Surface changed between visible captions')
        if any(abs(a-b)>3 for a,b in zip(first['action']['bounds'],box)):
            self.candidate=current;event['reason']='visible-bounds-mismatch'
            event['refused_captures']=[first['frame']['id'],frame['id']];return None
        fresh_pair(first['frame'],frame,identity=self.owned,now=now,require_surface=True)
        self.candidate=None;event['reason']='ready-visible-pair'
        event['captures']=[first['frame']['id'],frame['id']]
        return {'frames':(first['frame'],frame),'action':action,
            'point':[(int(box[0])+int(box[2]))//2,(int(box[1])+int(box[3]))//2],
            'captures':event['captures'],'scope':'Two current visible Title captions only; no Light/OK/Home or feature authority'}
