"""Pure, fail-closed native OCR/pixel plans for the owned GL QA run.

No input is executed here. The caller must validate two fresh screenshots,
current native Surface, process lifetime and age before executing any plan.
The real reference covers only the initial Full-selected clipped chooser.
English completion and Home recognition remain runtime-unverified candidates.
"""
from __future__ import annotations

import math
import re


MIN_CONFIDENCE = 75


def _box(words):
    return [min(w['bounds'][0] for w in words), min(w['bounds'][1] for w in words),
            max(w['bounds'][2] for w in words), max(w['bounds'][3] for w in words)]


def _center(box):
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)


def _text(word):
    return word['text'].casefold().strip('.,:;!?')


def _usable(words, width, height):
    result=[]
    for word in words:
        bounds=word.get('bounds') or []
        score=word.get('confidence',-1)
        if not isinstance(score,(int,float)) or not math.isfinite(score) or score<MIN_CONFIDENCE:continue
        if len(bounds)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in bounds):continue
        if not (0<=bounds[0]<bounds[2]<=width and 0<=bounds[1]<bounds[3]<=height):continue
        if isinstance(word.get('text'),str) and word['text'].strip():result.append(word)
    return result


def _phrase_matches(words, first, second):
    """Exact ordered adjacent pairs on actual OCR baselines; never deduplicate."""
    matches=[]
    for a in words:
        if a['text'].casefold()!=first.casefold():continue
        for b in words:
            if b['text'].casefold()!=second.casefold():continue
            ab,bb=a['bounds'],b['bounds'];h=max(ab[3]-ab[1],bb[3]-bb[1])
            if (ab[2]<=bb[0]<=ab[2]+h*3 and abs(_center(ab)[1]-_center(bb)[1])<=h*.65):
                matches.append({'text':first+' '+second,'bounds':_box([a,b]),
                                'confidence':min(a['confidence'],b['confidence'])})
    return matches


def phrase(words, first, second):
    """One exact ordered adjacent pair on one actual OCR baseline."""
    matches=_phrase_matches(words,first,second)
    return matches[0] if len(matches)==1 else None


def _light_options(words):
    """Identify regular Light by its immediate numeric-size suffix.

    The actual chooser has THREE alternatives.  The Auto-delete variant also
    starts with the exact words Light Download, so that prefix alone cannot
    authorize selecting or confirming the regular Light option.  Missing or
    low-confidence suffixes remain unclassified rather than guessed.
    """
    options=[]
    for match in _phrase_matches(words,'Light','Download'):
        box=match['bounds'];h=box[3]-box[1];cy=_center(box)[1]
        tail=sorted((w for w in words if w['bounds'][0]>=box[2] and
                     abs(_center(w['bounds'])[1]-cy)<=h*.65),key=lambda w:w['bounds'][0])
        suffix=[];right=box[2]
        for word in tail:
            if word['bounds'][0]-right>h*1.5:break
            suffix.append(word);right=word['bounds'][2]
        variant='unclassified'
        if suffix and suffix[0]['text'].casefold()=='(auto-delete':
            variant='auto-delete'
        elif (len(suffix)>=2 and re.fullmatch(r'\(\d+(?:\.\d+)?',suffix[0]['text']) and
              suffix[1]['text'].casefold()=='mb)'):
            variant='regular'
            match['confidence']=min(match['confidence'],suffix[0]['confidence'],suffix[1]['confidence'])
        options.append({**match,'variant':variant,'suffix_words':suffix})
    regular=[option for option in options if option['variant']=='regular']
    identified=(len(regular)==1 and all(option['variant']!='unclassified' for option in options)
                and sum(option['variant']=='auto-delete' for option in options)<=1)
    return options,regular[0] if identified else None


def _exact(words, text):
    matches=[w for w in words if w['text'].casefold()==text.casefold()]
    return matches[0] if len(matches)==1 else None


def download_progress(words):
    """Read footer labels only; they never authorize any native input."""
    caption=phrase([{**w,'text':w['text'].rstrip('.')} for w in words],'Downloading','data')
    if caption is None:return None
    rows=[]
    for word in sorted(words,key=lambda w:(_center(w['bounds'])[1],w['bounds'][0])):
        cy=_center(word['bounds'])[1];height=word['bounds'][3]-word['bounds'][1]
        row=next((row for row in rows if abs(row['cy']-cy)<=max(row['height'],height)*.65),None)
        if row is None:row={'cy':cy,'height':height,'words':[]};rows.append(row)
        row['words'].append(word)
    texts=[' '.join(w['text'] for w in sorted(row['words'],key=lambda w:w['bounds'][0])) for row in rows]
    number=r'\d{1,9}(?:\.\d{1,4})?';metrics=[]
    for text in texts:
        sizes=list(re.finditer(r'(?<![\d.+-])('+number+r')\s*MB\s*/\s*('+number+r')\s*MB\b',text,re.I))
        counts=list(re.finditer(r'\(\s*(\d{1,9})\s*/\s*(\d{1,9})\s*\)',text))
        percents=list(re.finditer(r'(?<![\d.+-])('+number+r')\s*%',text))
        if len(sizes)>1 or len(counts)>1 or len(percents)>1:continue
        row={}
        if sizes:
            done,total=map(float,sizes[0].groups())
            if 0<=done<=total and total>0:row['displayed_MB']={'done':done,'total':total}
        if counts:
            done,total=map(int,counts[0].groups())
            if 0<=done<=total and total>0:row['displayed_files']={'done':done,'total':total}
        if percents:
            value=float(percents[0][1])
            if 0<=value<=100:row['displayed_percent']=value
        if row:metrics.append(row)
    return {'caption':caption,'metrics':metrics,'valid_metrics':bool(metrics),
        'scope':'Rendered native footer labels are UI estimates, not actual transferred bytes, throughput or completion proof.'}


def _orange_circles(image, region, text_height):
    """Current saturated orange annulus/dot; never remembered screen positions."""
    width,height=image.size;left,top,right,bottom=map(int,region)
    left=max(0,left);top=max(0,top);right=min(width,right);bottom=min(height,bottom)
    pixels=image.convert('RGB').load()
    points=set()
    for y in range(top,bottom):
        for x in range(left,right):
            r,g,b=pixels[x,y]
            if r>=230 and 70<=g<=210 and b<=80 and r-g>=30:points.add((x,y))
    parts=[]
    while points:
        initial=points.pop();pending=[initial];members=[initial]
        while pending:
            x,y=pending.pop()
            for near in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if near in points:points.remove(near);pending.append(near);members.append(near)
        parts.append({'bounds':[min(x for x,y in members),min(y for x,y in members),
                                max(x for x,y in members)+1,max(y for x,y in members)+1],
                      'pixels':len(members)})
    # The ring and inner disk are distinct components of one radio control.
    groups=[]
    for part in sorted(parts,key=lambda p:p['pixels'],reverse=True):
        b=part['bounds'];related=[]
        for index,group in enumerate(groups):
            g=group['bounds']
            if min(b[2],g[2])>max(b[0],g[0]) and min(b[3],g[3])>max(b[1],g[1]):related.append(index)
        if not related:groups.append(part);continue
        merged=[part]+[groups[index] for index in related]
        for index in reversed(related):groups.pop(index)
        groups.append({'bounds':[min(p['bounds'][0] for p in merged),min(p['bounds'][1] for p in merged),
                                  max(p['bounds'][2] for p in merged),max(p['bounds'][3] for p in merged)],
                       'pixels':sum(p['pixels'] for p in merged)})
    circles=[]
    for group in groups:
        b=group['bounds'];w,h=b[2]-b[0],b[3]-b[1]
        if (text_height*.5<=w<=text_height*1.8 and text_height*.5<=h<=text_height*1.8
                and .65<=w/h<=1.55 and .12<=group['pixels']/(w*h)<=.85):
            circles.append({**group,'center':list(_center(b))})
    return circles


def _gray_annulus(image, center, radius):
    """Verify an actually visible unselected circle in at least six octants."""
    pixels=image.convert('RGB').load();width,height=image.size;cx,cy=center
    sectors=set();count=0
    for y in range(max(0,int(cy-radius*1.35)),min(height,int(cy+radius*1.35)+1)):
        for x in range(max(0,int(cx-radius*1.35)),min(width,int(cx+radius*1.35)+1)):
            distance=math.hypot(x-cx,y-cy)
            if not radius*.65<=distance<=radius*1.25:continue
            values=pixels[x,y]
            if 130<=min(values) and max(values)<=245 and max(values)-min(values)<=18:
                sectors.add(int((math.atan2(y-cy,x-cx)+math.pi)/(math.pi/4))%8);count+=1
    return {'present':len(sectors)>=6 and count>=radius*2,'covered_octants':len(sectors),'gray_pixels':count}


def _plan(kind, caption, bounds, confidence, **extra):
    return {'kind':kind,'caption':caption,'bounds':bounds,'confidence':confidence,**extra}


def analyze(image, metadata, phase):
    """Return state, optional ordinary-input plan, and read-only observations.

    Phases: settings, download_wait, home_wait. Completion/Home rules have no
    real GL reference yet and remain candidates until independently observed.
    """
    if phase not in ('settings','download_wait','home_wait'):raise ValueError('Unknown native download phase')
    width,height=image.size
    surface=metadata.get('surface') or {}
    if surface!={'left':0,'top':0,'right':width,'bottom':height}:
        raise ValueError('Native Surface does not match the current screenshot')
    words=_usable(metadata.get('words') or [],width,height)
    buttons=_usable(metadata.get('button_words') or [],width,height)
    result={'state':'unrecognized','action':None,'observations':{
        'phase':phase,'surface':surface,'source_screenshot_sha256':metadata.get('screenshot_sha256'),
        'minimum_confidence':MIN_CONFIDENCE}}
    observation=result['observations']
    if phase=='settings':
        full=phrase(words,'Full','Download');light_options,light=_light_options(words)
        ok=_exact(buttons,'OK');cancel=_exact(words,'Cancel')
        observation.update({'full_caption':full,'light_caption':light,'light_options':light_options,
                            'ok_caption':ok,'cancel_caption':cancel})
        if light_options and light is None:
            result['state']='blocked-settings-regular-light-identity';return result
        if not all((full,light,ok,cancel)):
            result['state']='blocked-settings-caption-context';return result
        fb,lb=full['bounds'],light['bounds'];h=max(fb[3]-fb[1],lb[3]-lb[1])
        fcy,lcy=_center(fb)[1],_center(lb)[1];gap=lcy-fcy
        footer=min(ok['bounds'][1],cancel['bounds'][1]);content_bottom=footer-h*1.2
        if not (h*2<gap<h*20 and abs(fb[0]-lb[0])<=h and footer>lb[3]+h):
            result['state']='blocked-settings-row-layout';return result
        # Both alternatives and the footer must belong to one visible modal.
        context_words={_text(w) for w in words if w['bounds'][3]<fb[1]}
        if not ('data' in context_words and 'settings' in context_words):
            result['state']='blocked-settings-header-context';return result
        left=min(fb[0],lb[0]);region=[left-h*4,fb[1]-h*.5,left-h*.2,content_bottom]
        circles=_orange_circles(image,region,h)
        observation.update({'orange_radio_markers':circles,'content_bottom':content_bottom})
        if len(circles)!=1:
            result['state']='blocked-radio-not-unique';return result
        marker=circles[0];mx,my=marker['center'];radius=max(marker['bounds'][2]-marker['bounds'][0],marker['bounds'][3]-marker['bounds'][1])/2
        selected=[]
        for name,cy in (('full',fcy),('light',lcy)):
            if h*.5<my-cy<min(gap*.8,h*6):selected.append((name,cy))
        if len(selected)!=1:
            result['state']='blocked-marker-not-owned-by-one-row';return result
        selected_name,selected_cy=selected[0];offset=my-selected_cy
        centers={'full':[mx,fcy+offset],'light':[mx,lcy+offset]}
        full_visible=all(center[1]-radius>fb[1]-h and center[1]+radius<content_bottom for center in centers.values())
        observation.update({'selected_radio':selected_name,'derived_radio_centers':centers,
                            'radio_radius':radius,'both_radio_extents_visible':full_visible})
        if not full_visible:
            # Actual V15r2's whole-row swipe moved content about190px and hid
            # Full. Reveal only the measured clipping deficit plus one text
            # height, capped at a quarter of the CURRENT row gap. Runtime
            # must re-observe both captions/radios; this never assumes motion.
            deficit=max(center[1]+radius-content_bottom for center in centers.values())
            distance=min(math.floor(gap*.25),math.ceil(max(0,deficit)+h))
            start=[int(_center(lb)[0]),int(lcy)];end=[start[0],start[1]-distance]
            if not (fb[1]-gap<end[1]<start[1]<footer-h):
                result['state']='blocked-scroll-geometry';return result
            observation['scroll_visibility']={'clipping_deficit':max(0,deficit),'text_height_margin':h,
                'maximum_distance_from_current_row_gap':gap*.25,'requested_distance':distance,
                'scope':'Small visibility-recovery request only; actual post-scroll geometry must be captured afresh'}
            result['state']='settings-radio-clipped'
            result['action']=_plan('scroll-download','Full Download / Light Download',_box([full,light]),
                min(full['confidence'],light['confidence']),start=start,end=end,duration_ms=650)
            return result
        other='light' if selected_name=='full' else 'full'
        gray=_gray_annulus(image,centers[other],radius)
        observation['unselected_radio']={'row':other,**gray}
        if not gray['present']:
            result['state']='blocked-unselected-radio-not-observed';return result
        if selected_name=='full':
            result['state']='settings-full-selected'
            result['action']=_plan('choose-light','Light Download',lb,light['confidence'])
        else:
            result['state']='settings-light-exclusively-selected'
            result['action']=_plan('confirm-light','OK',ok['bounds'],ok['confidence'])
        return result
    if phase=='download_wait':
        complete=phrase(words,'Download','Complete')
        close=_exact(buttons,'Close')
        observation['completion_reference_status']='No real GL completion reference yet; runtime must retain the actual matching captures'
        observation.update({'completion_caption':complete,'close_caption':close})
        progress_words=_usable(metadata.get('download_progress_words') or [],width,height)
        progress=download_progress(progress_words)
        observation['download_progress']=progress
        if complete and close and complete['bounds'][3]<close['bounds'][1]:
            result['state']='download-complete-candidate'
            result['action']=_plan('close-complete','Close',close['bounds'],close['confidence'])
        elif complete:result['state']='blocked-complete-without-exact-close'
        elif progress:result['state']='downloading-observed-progress' if progress['valid_metrics'] else 'downloading-progress-text-unreadable'
        else:result['state']='unrecognized-download-wait-screen'
        return result
    footer=[w for w in words if w['bounds'][1]>=height*.70]
    rank=_exact([w for w in words if w['bounds'][3]<=height*.35],'Rank')
    home=_exact(footer,'Home');captions={}
    for name in ('Story','Scouting','Shop'):
        found=_exact(footer,name)
        if found:captions[name]=found['bounds']
    for name,pair in (('School Idols',('School','Idols')),('Live Shows',('Live','Shows'))):
        found=phrase(footer,*pair)
        if found:captions[name]=found['bounds']
    observation.update({'home_reference_status':'Native visual candidate only; actual Unity Home scene must be verified after independent native-TID-bound read-only attach',
                        'home_caption':home,'rank_caption':rank,'other_footer_captions':captions})
    if home and rank and len(captions)>=2:result['state']='native-home-candidate'
    else:result['state']='waiting-for-native-home-candidate'
    return result
