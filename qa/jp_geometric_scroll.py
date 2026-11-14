"""Current known chooser viewport navigation only; no option-text template.

The fixed actual modal anchors locate the viewport. Current orange/pale upper
row, cut lower outline, vertical scrollbar and white gutter permit only a35px
upward gutter swipe. This module grants no Light/OK/label identity authority.
"""
import math
import jp_complete_matcher as exact
import jp_light_adapter as light
import jp_current_radio as radio

Refusal=exact.Refusal
ACTIVITY='com.klab.lovelive.allstars.MainActivity'
EVIDENCE='current-native-chooser-selected-row-clipped-content-scrollbar-blank-gutter'


def _runs(values):
    result=[]
    for value in values:
        if result and value==result[-1][-1]+1:result[-1].append(value)
        else:result.append([value])
    return result


def observe(capture):
    image,source,surface=light.capture_image(capture)
    try:
        modal=light.modal_context(image,source);view=modal['viewport_bounds'];pixels=image.load()
        markers=radio._orange_circles(pixels,view,(modal['modal_bounds'][2]-modal['modal_bounds'][0])*.028)
        if len(markers)!=1:raise Refusal('Navigation requires one current orange selected control')
        selected=markers[0]
        if not light._within(selected['bounds'],view):raise Refusal('Navigation selected control is clipped')
        pale_rows=[];pale_x=[]
        for y in range(view[1],view[3]):
            xs=[x for x in range(view[0],view[2]) if pixels[x,y]==(255,246,227)]
            if len(xs)>=math.ceil((view[2]-view[0])*.39):pale_rows.append(y);pale_x.extend((min(xs),max(xs)))
        if not pale_rows:raise Refusal('Navigation current selected pale row is absent')
        row=[min(pale_x),min(pale_rows),max(pale_x)+1,max(pale_rows)+1]
        if (not 70<=row[3]-row[1]<=110 or not light._within(row,view)
                or not row[1]<selected['center'][1]<row[3] or row[3]+16>=view[3]):
            raise Refusal('Navigation requires the complete selected upper row with lower content visible')
        # Only the FIRST continuous next-row outline may reach the footer.
        # A later third-row tail must never extend a closed second row.
        edge_left,edge_right=row[0]-1,row[2]
        lower=[y for y in range(row[3]+3,view[3])
            if min(pixels[edge_left,y])<245 and min(pixels[edge_right,y])<245]
        runs=_runs(lower);lower=runs[0] if runs else []
        if (len(lower)<12 or lower[-1]<view[3]-2
                or sum(y in lower for y in range(view[3]-12,view[3]))<10):
            raise Refusal('Navigation current lower row does not visibly continue through the viewport footer')
        top,bottom=view[1]+12,view[3]-12
        scan_left=math.ceil((row[2]+modal['modal_bounds'][2])/2)
        scan_right=modal['modal_bounds'][2]-8
        bar_cols=[x for x in range(scan_left,scan_right)
            if sum(min(pixels[x,y])<245 for y in range(top,bottom))>=(bottom-top)*.30]
        bars=_runs(bar_cols)
        if len(bars)!=1 or not 1<=len(bars[0])<=12:
            raise Refusal('Navigation current right vertical scrollbar is absent or ambiguous')
        bar=[bars[0][0],top,bars[0][-1]+1,bottom]
        left,right=row[2]+5,bar[0]-3
        if not view[0]<left<right<view[2]:raise Refusal('Navigation current row/scrollbar leave no safe gutter')
        white=[x for x in range(left,right) if all(min(pixels[x,y])>=245 for y in range(top,bottom))]
        gutters=[run for run in _runs(white) if len(run)>=8]
        if len(gutters)!=1:raise Refusal('Navigation current blank gutter is absent or ambiguous')
        gutter=gutters[0];x=(gutter[0]+gutter[-1])//2
        start=[x,bottom-18];end=[x,start[1]-35]
        if not top+18<end[1]<start[1]<bottom:raise Refusal('Navigation35px gesture leaves the current blank gutter')
        return {'evidence_kind':EVIDENCE,'current_png_sha256':capture['png_sha256'],'surface':list(surface),
            'modal_offset':modal['modal_offset'],'modal_bounds':modal['modal_bounds'],'viewport_bounds':view,
            'selected_upper_row':{'pale_bounds':row,'orange_control':selected},
            'clipped_lower_rails':{'left':edge_left,'right':edge_right,'top':min(lower),'bottom':max(lower)+1},
            'scrollbar_bounds':bar,'gutter':[gutter[0],gutter[-1]+1],'gutter_bounds':[left,top,right,bottom],
            'start':start,'end':end,'distance_pixels':35,'duration_ms':500,
            'Light_label_identity_authorized':False,'Light_radio_input_authorized':False,
            'scope':'Viewport navigation only; no Light/OK/download/feature authority'}
    finally:image.close();source.close()


def plan_pair(first,second,*,now,owned_identity,current_identity,overall_started,settings_started):
    now=exact._time(now);overall=exact._time(overall_started);settings=exact._time(settings_started)
    if not overall<=settings<=now<min(overall+2400,settings+120):raise Refusal('Original JP settings/overall navigation end reached')
    owned=exact._identity(owned_identity)
    if exact._identity(current_identity)!=owned:raise Refusal('Owned JP lifetime changed before viewport navigation')
    for frame in (first,second):
        if exact._identity(frame['identity_before'])!=owned or exact._identity(frame['identity_after'])!=owned:
            raise Refusal('JP navigation capture crossed a changed lifetime')
        native,captured,activity=(exact._time(frame.get(key)) for key in ('native_at','captured_at','activity_at'))
        if frame.get('activity')!=ACTIVITY or not native<=captured<=activity<=now:
            raise Refusal('Current original JP MainActivity navigation proof missing')
        if any(not 0<=now-value<=8 for value in (native,captured,activity)):raise Refusal('JP navigation PNG/native/Activity captures are not fresh within8seconds')
    if first['id']==second['id'] or not first['activity_at']<second['native_at']:
        raise Refusal('Independent ordered JP navigation captures required')
    evidence=[observe(frame) for frame in (first,second)]
    keys=('surface','modal_offset','modal_bounds','viewport_bounds','selected_upper_row',
        'clipped_lower_rails','scrollbar_bounds','gutter','gutter_bounds','start','end','duration_ms')
    if any(evidence[0][key]!=evidence[1][key] for key in keys):raise Refusal('Current JP navigation geometry changed across fresh pair')
    return {'kind':'diagnostic-chooser-upward-scroll','center':evidence[1]['start'],'start':evidence[1]['start'],
        'end':evidence[1]['end'],'duration_ms':500,'captures':[first['id'],second['id']],
        'owned_identity':dict(owned),'checked_at':now,'evidence_kind':EVIDENCE,'evidence':evidence,
        'settings_started':settings,'overall_started':overall,'settings_end':settings+120,'overall_end':overall+2400,
        'scope':'One35px viewport gutter navigation intent only; no label/Light/OK/feature authority'}


class ChooserScrollBudget:
    def __init__(self):self.attempts=0

    def reserve(self,first,second,*,owned_identity,current_identity,now,overall_started,settings_started,persist):
        if self.attempts>=2:raise Refusal('Two diagnostic chooser scroll attempts exhausted')
        plan=plan_pair(first,second,now=now,owned_identity=owned_identity,current_identity=current_identity,
            overall_started=overall_started,settings_started=settings_started)
        self.attempts+=1;intent=dict(plan,attempt=self.attempts)
        persist(intent)  # Spent before any input, including persistence ambiguity.
        return intent
