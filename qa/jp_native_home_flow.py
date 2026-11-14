"""Inert original-JP native reference flow. No observer or feature approval.

The control adapters always re-read current original pixels. The selected-Light
composition is an expected control style, never an actual selected reference.
Only future actual post-click captures can satisfy it. Home is never classified.
"""
from pathlib import Path
from collections import deque
import hashlib
import re

from jp_capture_guard import StopCapture, JP_BOOTSTRAP_DATABASES, image_of
import jp_light_adapter as light
import jp_complete_matcher as complete
from native_download_guard import SettingsProgress, BulkDownloadProgress


class NativeLog:
    """Bounded incremental owned-log evidence; content is legal only after OK.

    Complete successful GET records carry their original byte offsets. Partial
    writer records remain pending and do not become fabricated request evidence.
    """
    # Positive Go Duration.String forms: scalar subsecond units or h/m/s
    # compounds with fractional seconds. Units remain ordered and mandatory.
    duration = rb'(?:\d+(?:\.\d+)?(?:ns|\xc2\xb5s|ms)|(?:\d+h)?(?:\d+m)?\d+(?:\.\d+)?s)'
    line = re.compile(rb'^\[GIN\] \d{4}/\d{2}/\d{2} - \d{2}:\d{2}:\d{2}\s*\|\s*([1-5]\d{2})\s*\|\s*'+duration+rb'\s*\|\s*127\.0\.0\.1\s*\|\s*([A-Z]+)\s+"([^"\s]+)"\s*$')

    def __init__(self, path):
        self.path=Path(path);self.offset=0;self.inode=None;self.pending=b''
        self.pending_offset=0;self.after_ok=False;self.ok_baseline=None;self.sealed_ok_offset=None
        self.bootstrap={};self.assets=0;self.asset_examples=[]

    def seal_ok_boundary(self):
        if self.after_ok or self.sealed_ok_offset is not None:
            raise StopCapture('Ordinary OK source-log boundary is single-use')
        if self.pending:raise StopCapture('Partial owned log record at ordinary OK boundary; no crossing request authority')
        if not self.path.is_file() or self.path.stat().st_size!=self.offset:
            raise StopCapture('Owned source log grew before sealed ordinary OK boundary')
        self.sealed_ok_offset=self.offset
        return {'source_byte_offset':self.offset,'source_log_name':self.path.name,
            'pending_bytes':0,'bootstrap_only_checked_before_input':True}

    def authorize_after_validated_ok(self):
        if self.sealed_ok_offset is None or self.offset!=self.sealed_ok_offset or self.pending:
            raise StopCapture('Exact sealed pre-input ordinary OK source offset missing')
        self.after_ok=True;self.ok_baseline=self.sealed_ok_offset

    def read(self):
        if not self.path.exists():return []
        with self.path.open('rb') as source:
            # fstat avoids a path replacement race with an active owned writer.
            import os
            stat=os.fstat(source.fileno());identity=(stat.st_dev,stat.st_ino)
            if self.inode is not None and (identity!=self.inode or stat.st_size<self.offset):
                raise StopCapture('Owned JP log rotated or truncated')
            if stat.st_size>64*1024**2:raise StopCapture('Owned JP native-reference log exceeded64MiB')
            self.inode=identity;source.seek(self.offset);raw=source.read(1024*1024+1)
        if len(raw)>1024*1024:raise StopCapture('Owned JP log growth exceeded1MiB bounded read')
        if not self.pending:self.pending_offset=self.offset
        self.offset+=len(raw);self.pending+=raw;events=[]
        while b'\n' in self.pending:
            row,self.pending=self.pending.split(b'\n',1)
            offset=self.pending_offset;self.pending_offset+=len(row)+1
            row=row.rstrip(b'\r')
            if not row.startswith(b'[GIN]'):continue
            match=self.line.fullmatch(row)
            if not match:raise StopCapture('Malformed current owned Gin record; request target unproven')
            status,method,path=int(match[1]),match[2],match[3]
            if not path.startswith(b'/static/'):
                # An encoded RPC query grants no asset authority. Keep the
                # path itself strict so encoded/escaped static aliases refuse.
                route=path.split(b'?',1)[0]
                if b'%' in route or b'\\' in route:raise StopCapture('Encoded or escaped owned request path refused')
                continue
            if method!=b'GET' or re.fullmatch(rb'/static/[A-Za-z0-9_./-]{1,256}',path) is None or b'..' in path:
                raise StopCapture('Unsupported current static request target')
            bootstrap=path in JP_BOOTSTRAP_DATABASES
            if not bootstrap and not self.after_ok:
                raise StopCapture('Non-bootstrap static request before validated ordinary Light OK')
            if not bootstrap and offset<self.ok_baseline:
                raise StopCapture('Content record predates sealed ordinary OK boundary')
            if status>=400:
                raise StopCapture('Current native static request failed with HTTP'+str(status)+'; no retry input')
            if status!=200:continue
            item={'source_byte_offset':offset,'bytes':len(row)+1,'status':status,
                'path':path.decode('ascii'),'raw_line_sha256':hashlib.sha256(row).hexdigest(),
                'source_log_name':self.path.name,'kind':'bootstrap-database' if bootstrap else 'post-OK-content',
                'post_OK_source_baseline':self.ok_baseline,
                'scope':'Completed successful source-log GET; no transferred-byte or completion claim'}
            if bootstrap:self.bootstrap[item['path']]=self.bootstrap.get(item['path'],0)+1
            else:
                self.assets+=1
                if len(self.asset_examples)<8:self.asset_examples.append(item)
            events.append(item)
        if len(self.pending)>16384:raise StopCapture('Oversize incomplete owned Gin record')
        return events

    def summary(self):
        return {'bootstrap_database_successful_GET_counts':dict(sorted(self.bootstrap.items())),
            'bootstrap_database_unique_successful_GETs':len(self.bootstrap),
            'all11_bootstrap_databases_observed_successfully':len(self.bootstrap)==11,
            'post_OK_successful_content_GET_count':self.assets,
            'post_OK_content_examples':self.asset_examples,'source_offset':self.offset,
            'post_OK_source_baseline':self.ok_baseline,'pending_bytes':len(self.pending),
            'ordinary_content_authorized_after_validated_OK':self.after_ok}


def complete_frame(frame):
    """Translate only V5 raw-capture field names into the pinned native gate."""
    return {key:frame[key] for key in ('id','png_bytes','png_sha256','native_xml',
        'captured_at','identity_before','identity_after')} | {
        'native_xml_sha256':frame['native_sha256'],'native_captured_at':frame['native_at']}


def complete_observation(frame, phase='download_wait'):
    try:return complete.observe(complete_frame(frame),phase,templates=complete.load_references(),
        complete_interior=True)
    except complete.Refusal as error:
        if str(error)=='Whole modal absent, altered, clipped, colliding, or ambiguous':return None
        raise


def pale_modal_candidate(raw):
    """Conservative STOP-only panel evidence, never authority to click.

    Search a current150-scaled-row window for at least120 pale rows, permitting
    the actual modal's text-line gaps. Altered-message or animated-edge variants
    can therefore stop even when strict input matching refuses.
    A false positive retains a raw candidate and stops; it cannot authorize input.
    """
    image=image_of(raw);width,height=image.size
    xs=range(width*15//100,width*85//100,4);required=(len(xs)*75+99)//100
    span=max(1,150*height//1280);minimum=(120*height+1279)//1280
    rows=deque();count=0
    for y in range(height):
        pale=sum(min(image.getpixel((x,y)))>=220 for x in xs)>=required
        rows.append(pale);count+=pale
        if len(rows)>span:count-=rows.popleft()
        if len(rows)==span and count>=minimum:return True
    return False


class NativeReferenceFlow:
    """Minimal callback-driven chooser→download→raw post-close capture adapter."""
    def __init__(self, *, capture, send, lifetime, clock, pause, report, save,
            persist, log, overall_started, progress=lambda frame:{},prechooser_started=None,
            light_planner=None,manual_label_review=False):
        self.capture=capture;self.send=send;self.lifetime=lifetime;self.clock=clock
        self.pause=pause;self.report=report;self.save=save;self.persist=persist
        self.log=log;self.started=overall_started;self.settings=None
        self.progress=progress
        self.light=light if light_planner is None else light_planner
        self.recollect_light=light_planner is not None
        if type(manual_label_review) is not bool:raise ValueError('Manual native label review must be explicit boolean')
        self.chooser_idle_seconds=120 if manual_label_review else 45
        self.report['chooser_wait_budget']={'idle_seconds':self.chooser_idle_seconds,
            'absolute_settings_seconds':120,'manual_review_enabled':manual_label_review,
            'native_label_offer_max_seconds':90,'overall_seconds':2400,
            'scope':'Explicit manual review waiting allowance only; Git I/O is not semantic progress and cannot extend original absolute ends'}
        self.settings_started=None;self.bulk=None;self.post_close_end=None
        self.prechooser_started=complete._time(clock() if prechooser_started is None else prechooser_started)
        self.prechooser_end=min(overall_started+2400,self.prechooser_started+180)
        self.report['original_Title_prechooser_started']=self.prechooser_started
        self.report['original_Title_prechooser_end']=self.prechooser_end
        self.owned=dict(lifetime())

    def begin_settings(self):
        if self.settings is None:
            self.settings_started=self.clock();self.settings=SettingsProgress(self.settings_started,idle_seconds=self.chooser_idle_seconds)
            self.report['original_settings_started']=self.settings_started

    def phase_end(self):
        end=self.started+2400
        if self.post_close_end is not None:return min(end,self.post_close_end)
        if self.bulk is not None:return min(end,self.bulk.deadline)
        if self.settings is not None:return min(end,self.settings.absolute_deadline,self.settings.stagnant_deadline)
        return min(end,self.prechooser_end)

    def settings_progress(self, frame, *, state, action):
        """Only grounded caption/state geometry is semantic settings progress."""
        self.begin_settings()
        if frame is None:observed={}
        else:
            evidence=self.light.observe(frame,state=state)
            observed={'action':{'kind':action},'observations':{
                'full_caption':{'bounds':evidence['rows']['bulk']['bounds']},
                'light_caption':{'bounds':evidence['rows']['light']['bounds']},'selected_radio':state}}
        self.settings.observe(observed,self.clock())

    def light_plan(self, first, second, state):
        return self.light.plan_pair(first,second,state=state,now=self.clock(),
            owned_identity=self.owned,current_identity=self.lifetime(),
            overall_started=self.started,settings_started=self.settings_started)

    def collect_light_pair(self,state,first=None):
        """Recollect read-only proof under the original ends; never retry input."""
        pending=first
        action='choose-light' if state=='bulk' else 'confirm-light'
        reason='full-Light-choice' if state=='bulk' else 'actual-selected-Light-after-click'
        while True:
            if self.clock()>=self.phase_end():
                raise StopCapture('Original JP Light settings/overall end reached while collecting '+state+' proof')
            frames=(pending if pending is not None else self.capture(reason),
                self.capture(reason+'-recheck'))
            pending=None
            try:
                plan=self.light_plan(*frames,state)
                self.settings_progress(frames[1],state=state,action=action)
            except light.Refusal as error:
                self.report.setdefault('current_Light_pair_refusals',[]).append({
                    'state':state,'captures':[frame['id'] for frame in frames],
                    'PNG_sha256':[frame.get('png_sha256') for frame in frames],
                    'reason':str(error),'at':self.clock(),'original_phase_end':self.phase_end(),
                    'read_only':True,'after_single_Light_input':state=='light',
                    'input_will_not_be_retried':True})
                self.save()
                self.settings_progress(None,state=state,action=action)
                self.pause(.2)
                continue
            return frames,plan

    def run(self, first):
        self.begin_settings();self.report['phase']='ordinary_Light_selection';self.save()
        if self.recollect_light:
            frames,plan=self.collect_light_pair('bulk',first)
            first,second=frames
        else:
            self.settings_progress(first,state='bulk',action='choose-light')
            second=self.capture('full-Light-choice-recheck')
            plan=self.light_plan(first,second,'bulk')
        # Exactly one send call. Any input-boundary or ambiguous send failure
        # escapes; recollection above never repeats an attempted Light input.
        self.send(plan['kind'],plan['center'],(first,second),
            verifier=lambda:self.light_plan(first,second,'bulk'))
        if self.recollect_light:
            selected,selected_plan=self.collect_light_pair('light')
        else:
            selected=[self.capture('actual-selected-Light-after-click'),
                self.capture('actual-selected-Light-after-click-recheck')]
            selected_plan=self.light_plan(*selected,'light')
            self.settings_progress(selected[1],state='light',action='confirm-light')
        selected_evidence={'actual_capture_ids':[item['id'] for item in selected],
            'evidence':selected_plan,'actual_selected_reference_preexisted':False,
            'scope':'Fresh actual post-click selected-Light and unchecked-Bulk proof from the active planner; no feature qualification'}
        self.persist('actual-selected-Light-state.json',selected_evidence)
        self.report['actual_selected_Light_state']=selected_evidence;self.save()
        # The original bulk start is fixed once, before this one ordinary OK.
        self.bulk=BulkDownloadProgress(self.clock())
        self.report['original_bulk_started']=self.bulk.started
        self.report['phase']='ordinary_OK';self.save()
        self.send(selected_plan['kind'],selected_plan['center'],tuple(selected),
            verifier=lambda:self.light_plan(*selected,'light'))
        self.log.authorize_after_validated_ok()
        self.report['ordinary_OK_returned']=True;self.report['phase']='download_wait';self.save()
        fixed={'overall_started':self.started,'bulk_started':self.bulk.started}
        while True:
            self.pause(.5)
            frame=self.capture('native-real-Light-download')
            match=complete_observation(frame)
            if match is not None:
                other=self.capture('current-native-Complete-close-recheck')
                def close_plan():
                    return complete.plan_pair(complete_frame(frame),complete_frame(other),
                        phase='download_wait',now=self.clock(),owned_identity=self.owned,
                        current_identity=self.lifetime(),fixed_starts=fixed,complete_interior=True)
                close=close_plan()
                self.send(close['kind'],close['center'],(frame,other),verifier=close_plan)
                self.report['native_Complete_close_evidence']=close
                self.report['phase']='raw_post_close_candidates';self.post_close_end=min(self.started+2400,self.clock()+180)
                self.report['original_post_close_end']=self.post_close_end;self.save();break
            if pale_modal_candidate(frame['png_bytes']):
                raise StopCapture('Unknown, altered or unmatched native download modal captured; no grounded input')
            progress=self.progress(frame)
            self.report['bulk_progress']=self.bulk.observe({'state':'download_wait',
                'observations':{'download_progress':progress}},self.clock());self.save()
        candidates=[]
        self.pause(.5)
        while self.phase_end()-self.clock()>20:
            frame=self.capture('raw-post-validated-Close-candidate')
            candidates.append(frame['id']);self.report['raw_post_close_candidate_ids']=list(candidates);self.save()
            if not frame['surface']:
                raise StopCapture('Unknown native window after validated Close; raw candidate retained')
            if frame.get('activity')!='com.klab.lovelive.allstars.MainActivity':
                raise StopCapture('Unexpected native Activity after validated Close; raw candidate retained')
            if complete_observation(frame) is not None:
                raise StopCapture('Native Complete remained after one ordinary Close; no repeated input')
            if pale_modal_candidate(frame['png_bytes']):
                raise StopCapture('Unknown pale native modal after validated Close; raw candidate retained, no guessed Home input')
            self.pause(min(5,max(0,self.phase_end()-self.clock()-20)))
        if not candidates:raise StopCapture('No raw candidate captured within original post-Close/overall bound')
        self.report['status']='RAW_POST_CLOSE_CANDIDATES_CAPTURED'
        self.report['scope']='Original JP native reference candidates only; ROOT visual review required; Home and all11 features remain unqualified'
        self.save()
