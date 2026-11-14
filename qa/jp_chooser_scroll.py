"""Exact current clipped-chooser evidence for bounded diagnostic gutter input.

Original038/039 supply complete visible notice/Bulk/title specimens. Their
clipped Light radio is never a specimen or input target. Modal anchors come
from the separately pinned044 reference. There is no device or feature API.
"""
from pathlib import Path

import jp_complete_matcher as exact
import jp_light_adapter as light


Refusal=exact.Refusal
ACTIVITY='com.klab.lovelive.allstars.MainActivity'
ROOT=Path(__file__).parent/'fixtures'
SOURCES=(('actual-jp-home-v1-038.png','7f3c87354027e45aee1eb43cb5405269e9a8365eca5b3b3b5c788c9e10541e92'),
    ('actual-jp-home-v1-039.png','0c62b0aecf47bc341dd6862b2c4e6aef6dafc704005d5195f5abbd08e56393a9'))
REGIONS=(('full-notice',(145,562,525,605)),
    ('bulk-full-row',(158,635,562,727)),
    ('bulk-full-caption-description',(190,638,544,708)),
    ('bulk-checked-radio',(166,671,186,691)),
    ('Light-full-title',(190,738,544,758)))
LIGHT_ROW=(158,735,562,825)
LIGHT_RADIO=(166,770,186,790)  # Clipping estimate only: never matched or targeted.
EVIDENCE='current-exact-JP-038-039-visible-context-and-044-modal-gutter-only'


def _source():
    images=[]
    for name,pin in SOURCES:
        raw=(ROOT/name).read_bytes()
        if exact.digest(raw)!=pin:raise Refusal('Actual clipped JP chooser reference changed')
        images.append(exact._png(raw))
    for label,box in REGIONS:
        if images[0].crop(box).tobytes()!=images[1].crop(box).tobytes():
            raise Refusal('Retained JP visible '+label+' specimen is not stable')
    return images[0]


def _unique(image,specimen,label):
    template=exact.Template(label,'settings',SOURCES[0][1],(0,0,*specimen.size),
        specimen.size,specimen.tobytes(),(),None)
    hits=exact._locations(image,template)
    if len(hits)!=1:
        raise Refusal('Visible JP chooser '+label+' absent, altered, clipped or colliding')
    return tuple(hits[0])


def _shift(box,offset):
    return tuple(value+offset[index%2] for index,value in enumerate(box))


def _contained(box,viewport):
    return viewport[0]<=box[0]<box[2]<=viewport[2] and viewport[1]<=box[1]<box[3]<=viewport[3]


def observe(capture):
    """Recognize only the current selected-Bulk, clipped-Light chooser context."""
    image,source044,surface=light.capture_image(capture)
    try:modal=light.modal_context(image,source044)
    finally:source044.close()  # Only scalar anchor geometry is needed below.
    source=_source();offsets=[];bounds={}
    for label,box in REGIONS:
        found=_unique(image,source.crop(box),label);bounds[label]=list(found)
        offsets.append((found[0]-box[0],found[1]-box[1]))
    offset=offsets[0]
    if any(value!=offset for value in offsets) or offset[0]!=modal['modal_offset'][0]:
        raise Refusal('Visible JP chooser regions do not share one content offset')
    viewport=tuple(modal['viewport_bounds'])
    if any(not _contained(tuple(box),viewport) for box in bounds.values()):
        raise Refusal('Visible JP notice/Bulk/full-Light-title leaves the content viewport')
    row=_shift(LIGHT_ROW,offset);radio=_shift(LIGHT_RADIO,offset)
    if not (row[0]>=viewport[0] and row[2]<=viewport[2]
            and row[1]<viewport[3]<row[3] and radio[3]>viewport[3]):
        raise Refusal('Only a chooser with Light row/radio clipped below the footer permits diagnostic scroll')
    left=bounds['bulk-full-row'][2]+4;right=modal['modal_bounds'][2]-16
    top=viewport[1]+12;bottom=viewport[3]-12
    if not (viewport[0]<left<right<viewport[2] and top<bottom):
        raise Refusal('Current JP chooser has no bounded gutter search area')
    runs=[]
    for x in range(left,right):
        if all(min(image.getpixel((x,y)))>=245 for y in range(top,bottom)):
            if runs and x==runs[-1][-1]+1:runs[-1].append(x)
            else:runs.append([x])
    runs=[run for run in runs if len(run)>=8]
    if len(runs)!=1:raise Refusal('Current JP blank gutter absent or ambiguous')
    gutter=runs[0];x=(gutter[0]+gutter[-1])//2
    anchors=modal['anchors']
    header=next(row for row in anchors if row['role']=='header')['bounds']
    footer_bottom=max(row['bounds'][3] for row in anchors if row['role'] in ('cancel-caption','ok-caption'))
    distance=min((bottom-top)//5,(footer_bottom-header[1])//10,48)
    start=[x,bottom-18];end=[x,start[1]-distance]
    if not (20<=distance<=48 and top+18<end[1]<start[1]<bottom):
        raise Refusal('Current JP gutter cannot provide one bounded upward gesture')
    return {'evidence_kind':EVIDENCE,'source_original_png_sha256':[pin for name,pin in SOURCES],
        'current_png_sha256':capture['png_sha256'],'surface':list(surface),
        'modal_offset':list(modal['modal_offset']),'modal_bounds':list(modal['modal_bounds']),
        'viewport_bounds':list(viewport),'content_offset':list(offset),'visible_regions':bounds,
        'bulk_checked':True,'Light_full_title':'軽量ダウンロード [5858.95 MB]',
        'Light_row_estimated_bounds':list(row),'Light_radio_clipping_estimate':list(radio),
        'Light_radio_matched':False,'Light_radio_input_authorized':False,
        'gutter':[gutter[0],gutter[-1]+1],'gutter_bounds':[left,top,right,bottom],
        'start':start,'end':end,'distance_pixels':distance,'duration_ms':500,
        'scope':'Diagnostic blank-gutter scroll only; no Light/OK/download/feature authority'}


def plan_pair(first,second,*,now,owned_identity,current_identity,overall_started,settings_started):
    """Recompute raw current proof; no supplied coordinates or stored matches."""
    now=exact._time(now);overall=exact._time(overall_started);settings=exact._time(settings_started)
    if not overall<=settings<=now<min(overall+2400,settings+120):
        raise Refusal('Original JP settings120second or overall2400second end reached')
    owned=exact._identity(owned_identity)
    if exact._identity(current_identity)!=owned:raise Refusal('Owned JP lifetime changed before diagnostic scroll')
    evidence=[observe(frame) for frame in (first,second)]
    for frame in (first,second):
        if exact._identity(frame['identity_before'])!=owned or exact._identity(frame['identity_after'])!=owned:
            raise Refusal('JP diagnostic capture crossed a changed lifetime')
        native=exact._time(frame['native_at']);captured=exact._time(frame['captured_at'])
        activity=exact._time(frame.get('activity_at'))
        if frame.get('activity')!=ACTIVITY or not native<=captured<=activity<=now:
            raise Refusal('Current original JP MainActivity proof missing')
        if any(not 0<=now-value<=8 for value in (native,captured,activity)):
            raise Refusal('JP diagnostic PNG/native/Activity captures must all be fresh within8seconds')
    if not (first['id']!=second['id'] and first['activity_at']<second['native_at']<=second['captured_at']):
        raise Refusal('Independent ordered JP diagnostic captures required')
    keys=('surface','modal_offset','modal_bounds','viewport_bounds','content_offset',
        'visible_regions','gutter','gutter_bounds','start','end','distance_pixels','duration_ms')
    if any(evidence[0][key]!=evidence[1][key] for key in keys):
        raise Refusal('Current JP diagnostic chooser captures disagree')
    return {'kind':'diagnostic-chooser-upward-scroll','center':list(evidence[1]['start']),
        'start':list(evidence[1]['start']),'end':list(evidence[1]['end']),'duration_ms':500,
        'captures':[first['id'],second['id']],'owned_identity':dict(owned),'checked_at':now,
        'evidence_kind':EVIDENCE,'evidence':evidence,'settings_started':settings,
        'overall_started':overall,'settings_end':settings+120,'overall_end':overall+2400,
        'scope':'One diagnostic gutter intent only; no Light/OK/download/feature authority'}


class ChooserScrollBudget:
    """At most two durable reservations; final verification uses pureplan_pair."""
    def __init__(self):self.attempts=0

    def reserve(self,first,second,*,owned_identity,current_identity,now,overall_started,settings_started,persist):
        if self.attempts>=2:raise Refusal('Two diagnostic chooser scroll attempts exhausted')
        plan=plan_pair(first,second,now=now,owned_identity=owned_identity,
            current_identity=current_identity,overall_started=overall_started,settings_started=settings_started)
        self.attempts+=1
        intent=dict(plan,attempt=self.attempts)
        persist(intent)  # Spent before input, including a persistence exception.
        return intent
