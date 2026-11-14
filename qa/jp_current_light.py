"""Current JP regular-Light labels and two-radio state; no stored scroll raster.

Only actual per-PNG OCR is cached. A validated pre-input pair can retain its
CURRENT caption red planes across the later style swap; no selected original
is invented. Native freshness/lifetime/end checks still precede every input.
"""
from collections import OrderedDict
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import unicodedata

from PIL import Image
import jp_light_adapter as legacy
import jp_complete_matcher as exact
import jp_current_radio as radio

Refusal = legacy.Refusal
ACTIVITY = 'com.klab.lovelive.allstars.MainActivity'
ROOT = Path(__file__).parent
MODEL_PINS = {'jpn':'1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d',
    'eng':'7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'}
LIGHT = '軽量ダウンロード'
SIZES = {'light':'[5858.95MB]', 'bulk':'[15416.53MB]'}
EVIDENCE = 'current-bilingual-JP-Light-caption-and-complete-two-radio-state'


def _sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def _normal(text):
    return ''.join(unicodedata.normalize('NFKC',text).split())


def _box(words):
    return [min(w['bounds'][0] for w in words),min(w['bounds'][1] for w in words),
        max(w['bounds'][2] for w in words),max(w['bounds'][3] for w in words)]


def parse_tsv(raw, crop):
    """Preserve all tokens, including low-confidence/preceding Extra text."""
    words=[]
    for row in csv.DictReader(io.StringIO(raw),delimiter='\t'):
        text=(row.get('text') or '').strip()
        confidence=float(row.get('conf') or -1)
        if not text or confidence<0:continue
        left,top,width,height=(int(row[k]) for k in ('left','top','width','height'))
        words.append({'text':text,'confidence':confidence,
            'bounds':[crop[0]+left/4,crop[1]+top/4,crop[0]+(left+width)/4,crop[1]+(top+height)/4],
            'line_id':[int(row[k]) for k in ('block_num','par_num','line_num')]})
    return words


def _lines(words):
    lines={}
    for word in words:
        bounds=word.get('bounds');confidence=word.get('confidence')
        if (not isinstance(word.get('text'),str) or not isinstance(bounds,(list,tuple)) or len(bounds)!=4
                or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in bounds)
                or not (bounds[0]<bounds[2] and bounds[1]<bounds[3])
                or not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not math.isfinite(confidence)):
            raise Refusal('Current JP OCR token fields are invalid')
        lines.setdefault(tuple(word['line_id']),[]).append(word)
    return sorted(lines.values(),key=lambda row:(min(w['bounds'][1] for w in row),min(w['bounds'][0] for w in row)))


def _english_size(words, expected):
    matches=[]
    for row in _lines(words):
        for index,word in enumerate(row):
            if not _normal(word['text']).startswith('['):continue
            suffix=row[index:]
            if ''.join(_normal(w['text']) for w in suffix)==expected and min(w['confidence'] for w in suffix)>=75:
                matches.append({'caption':expected,'bounds':_box(suffix),
                    'confidence':min(w['confidence'] for w in suffix),'words':suffix})
    if len(matches)!=1:raise Refusal('Current complete English '+expected+' is absent, low-confidence or ambiguous')
    return matches[0]


def caption_identity(jpn_light, eng_light, eng_bulk):
    """Exact JP whole prefix plus independent same-line complete English size."""
    sizes={name:_english_size(words,SIZES[name]) for name,words in (('light',eng_light),('bulk',eng_bulk))}
    lines=_lines(jpn_light)
    if not lines:raise Refusal('Current JP regular-Light prefix absent')
    # Only the first complete caption line can identify this option. Extra text
    # is retained, not discarded at the confidence floor or repaired afterward.
    row=lines[0];prefix=[]
    for word in row:
        if _normal(word['text']).startswith('['):break
        prefix.append(word)
    if (not prefix or ''.join(_normal(w['text']) for w in prefix)!=LIGHT
            or min(w['confidence'] for w in prefix)<75):
        raise Refusal('Current exact whole JP regular-Light prefix absent, Extra-prefixed or low-confidence')
    pb=_box(prefix);number=sizes['light'];nb=number['bounds'];height=max(pb[3]-pb[1],nb[3]-nb[1])
    if (abs((pb[1]+pb[3]-nb[1]-nb[3])/2)>3 or not 0<=nb[0]-pb[2]<=height*2):
        raise Refusal('Current JP prefix and independent English Light size do not share one caption line')
    # Independent numeric boxes must also agree with the current JP line's
    # trailing numeric glyph positions, even though those JP token texts are unused.
    trailing=row[len(prefix):]
    if not trailing or any(abs(a-b)>3 for a,b in zip(_box(trailing),nb)):
        raise Refusal('Current independent JP/English numeric caption boxes disagree')
    light={'caption':LIGHT+SIZES['light'],'bounds':_box(prefix+number['words']),
        'confidence':min(number['confidence'],min(w['confidence'] for w in prefix))}
    return {'light':light,'bulk':{key:sizes['bulk'][key] for key in ('caption','bounds','confidence')}}


def recognizes_modal(capture):
    image,source,_=legacy.capture_image(capture)
    try:legacy.modal_context(image,source);return True
    except Refusal:return False
    finally:image.close();source.close()


def _red_hash(image,box):
    with image.crop(box) as crop, crop.getchannel('R') as red:return exact.digest(red.tobytes())


def _geometry(image,modal):
    viewport=modal['viewport_bounds']
    try:controls=radio.observe(image,viewport,(modal['modal_bounds'][2]-modal['modal_bounds'][0])*.028)
    except radio.Refusal as error:raise Refusal(str(error)) from error
    ordered=sorted((controls['selected'],controls['unselected']),key=lambda item:item['center'][1])
    gap=ordered[1]['center'][1]-ordered[0]['center'][1]
    if not 50<gap<180 or abs(ordered[0]['center'][0]-ordered[1]['center'][0])>2:
        raise Refusal('Current JP two-radio row geometry disagrees')
    selected='bulk' if ordered[0] is controls['selected'] else 'light'
    pixels=image.load();pale=(255,246,227);pale_rows=[];pale_x=[]
    for y in range(viewport[1],viewport[3]):
        xs=[x for x in range(viewport[0],viewport[2]) if pixels[x,y]==pale]
        if len(xs)>=math.ceil((viewport[2]-viewport[0])*.39):
            pale_rows.append(y);pale_x.extend((min(xs),max(xs)))
    if (not pale_rows or max(pale_rows)-min(pale_rows)<50
            or not min(pale_rows)<controls['selected']['center'][1]<max(pale_rows)):
        raise Refusal('Current selected pale row is absent or not owned by the orange radio')
    selected_top=min(pale_rows)-2;left=min(pale_x)+1;right=max(pale_x)-1
    rows={};crops={};full_radius=max(control['radius'] for control in ordered)
    for index,name in enumerate(('bulk','light')):
        control=ordered[index];top=round(selected_top+(index-(0 if selected=='bulk' else 1))*gap)
        body=[left,top+3,right,min(round(top+gap*.88),viewport[3])]
        if not legacy._within(body,viewport):raise Refusal('Current JP row body leaves the content viewport')
        total=(body[2]-body[0])*(body[3]-body[1]);counts={'pale':0,'white':0}
        for y in range(body[1],body[3]):
            for x in range(body[0],body[2]):
                value=pixels[x,y]
                counts['pale']+=value==pale;counts['white']+=value==(255,255,255)
        expected='pale' if name==selected else 'white';opposite='white' if expected=='pale' else 'pale'
        if counts[expected]/total<.75 or counts[opposite]/total>.02:
            raise Refusal('Current JP '+name+' row background contradicts its radio state')
        crop=[round(control['center'][0]+controls['selected']['radius']+3),top,max(pale_x)-9,min(round(top+gap*.94),viewport[3])]
        if not legacy._within(crop,viewport):raise Refusal('Current JP caption crop is clipped')
        crops[name]=crop
        cx,cy=control['center']
        full_bounds=[cx-full_radius,cy-full_radius,cx+full_radius,cy+full_radius]
        if not legacy._within(full_bounds,viewport):raise Refusal('Current complete JP radio extent is clipped')
        rows[name]={'radio_bounds':full_bounds,'actual_radio_bounds':control['bounds'],'radio_center':control['center'],
            'background_bounds':body,'background':expected,'background_fraction':counts[expected]/total}
    return selected,rows,crops


class CurrentLightPlanner:
    def __init__(self,evidence_path,*,jpn_model=None,eng_model=None):
        self.evidence=Path(evidence_path);self.models={'jpn':Path(jpn_model or ROOT/'fixtures/ocr-models/jpn.traineddata'),
            'eng':Path(eng_model or ROOT/'fixtures/ocr-models/eng.traineddata')}
        if any(_sha(path)!=MODEL_PINS[language] for language,path in self.models.items()):
            raise Refusal('Current JP OCR model digest differs from the pinned actual measurement')
        self._cache=OrderedDict();self._baseline=None

    def _ocr(self,capture,image,crops):
        result={}
        for key,language,name in (('jpn_light','jpn','light'),('eng_light','eng','light'),('eng_bulk','eng','bulk')):
            box=crops[name];stem=self.evidence/(capture['id']+'-'+key+'-ocr')
            prepared=stem.with_suffix('.png')
            with image.crop(box) as crop,crop.convert('L') as gray,gray.resize((gray.width*4,gray.height*4),Image.Resampling.NEAREST) as scaled:
                scaled.save(prepared)
            argv=['tesseract',str(prepared),'stdout','--tessdata-dir',str(self.models[language].parent),'-l',language,'--psm','6','tsv']
            try:run=subprocess.run(argv,capture_output=True,timeout=3,
                env=dict(os.environ,OMP_THREAD_LIMIT='1',OMP_NUM_THREADS='1'))
            except subprocess.TimeoutExpired as error:raise Refusal('Current '+key+' OCR exceeded its bounded call') from error
            if len(run.stdout)>256*1024 or len(run.stderr)>16*1024:raise Refusal('Current JP OCR output exceeded its bound')
            tsv=stem.with_suffix('.tsv');tsv.write_bytes(run.stdout);stem.with_suffix('.stderr').write_bytes(run.stderr)
            transform={'capture':capture['id'],'source_png_sha256':capture['png_sha256'],'crop':box,'scale':4,
                'mode':'grayscale','resample':'NEAREST','psm':6,'language':language,'model_sha256':MODEL_PINS[language],
                'input_sha256':_sha(prepared),'TSV_sha256':_sha(tsv),'exit_code':run.returncode}
            stem.with_suffix('.json').write_text(json.dumps(transform,indent=2)+'\n')
            if run.returncode:raise Refusal('Current '+key+' OCR failed; raw output retained')
            result[key]=parse_tsv(run.stdout.decode(),box)
        return result

    def observe(self,capture,state='bulk'):
        if state not in ('bulk','light'):raise Refusal('Unknown current JP selection state')
        image,source,surface=legacy.capture_image(capture)
        try:
            modal=legacy.modal_context(image,source)
            selected,rows,crops=_geometry(image,modal)
            if selected!=state:raise Refusal('Current JP selected radio is '+selected+', expected '+state)
            # Always derive current state/geometry first. Supplied OCR/hit fields
            # in a capture are never consulted by this runtime factory.
            key=capture['png_sha256']
            if key in self._cache:labels=json.loads(self._cache[key])
            elif state=='light':
                if self._baseline is None:raise Refusal('Selected-Light has no accepted current pre-input caption pair')
                baseline=json.loads(self._baseline)
                same=all(modal[k]==baseline[k] for k in ('modal_bounds','modal_offset','viewport_bounds'))
                # Current orange/neutral masks can put their component envelope
                # one pixel apart. This constrains control geometry only; the
                # accepted current caption boxes/red-plane hashes stay exact.
                same=same and all(all(abs(a-b)<=1 for key in ('radio_bounds','background_bounds')
                    for a,b in zip(rows[name][key],baseline['rows'][name][key])) for name in rows)
                if not same:raise Refusal('Postclick current JP row geometry changed; fresh OCR or refusal required')
                labels={name:{key:baseline['rows'][name][key] for key in ('caption','bounds','confidence','caption_box','caption_r_sha256')} for name in rows}
                if any(_red_hash(image,row['caption_box'])!=row['caption_r_sha256'] for row in labels.values()):
                    raise Refusal('Postclick current JP caption red plane changed; no unchanged-label authority')
                self._cache[key]=json.dumps(labels,sort_keys=True)
            else:
                words=self._ocr(capture,image,crops)
                labels=caption_identity(words['jpn_light'],words['eng_light'],words['eng_bulk'])
                for name,row in labels.items():
                    # Bulk Japanese text is not transcribed as an exact caption.
                    # Retain its CURRENT whole title pixels as an unchanged-label
                    # witness alongside the separately read complete English size.
                    bounds=row['bounds'];crop=crops[name]
                    box=[crop[0],math.floor(bounds[1]),math.ceil(bounds[2]),math.ceil(bounds[3])]
                    row.update(caption_box=box,caption_r_sha256=_red_hash(image,box))
                self._cache[key]=json.dumps(labels,sort_keys=True)
            self._cache.move_to_end(key)
            while len(self._cache)>16:self._cache.popitem(last=False)
            for name,label in labels.items():
                bounds=label['bounds'];cy=sum(bounds[1::2])/2;radio_y=rows[name]['radio_center'][1]
                gap=rows['light']['radio_center'][1]-rows['bulk']['radio_center'][1]
                if not (legacy._within(bounds,modal['viewport_bounds']) and gap*.15<radio_y-cy<gap*.6):
                    raise Refusal('Current JP caption does not belong to its complete radio row')
                rows[name].update(label)
            caption_gap=sum(rows['light']['bounds'][1::2])/2-sum(rows['bulk']['bounds'][1::2])/2
            if abs(caption_gap-gap)>3:raise Refusal('Current JP caption and radio row gaps disagree')
            target=rows['light']['bounds'] if state=='bulk' else list(legacy._shift(legacy.OK,modal['modal_offset']))
            return {'evidence_kind':EVIDENCE,'current_png_sha256':key,'surface':list(surface),**modal,
                'selection':state,'bulk_checked':state=='bulk','light_checked':state=='light','rows':rows,
                'target_bounds':target,'selected_light_actual_reference_exists':False,
                'label_proof':'current-bilingual-OCR' if state=='bulk' else 'accepted-current-caption-red-plane-unchanged',
                'scope':'Native reference only; no Home or feature qualification'}
        finally:image.close();source.close()

    def plan_pair(self,first,second,*,state,now,owned_identity,current_identity,overall_started,settings_started):
        now=exact._time(now);overall=exact._time(overall_started);settings=exact._time(settings_started)
        if not overall<=settings<=now<min(overall+2400,settings+120):raise Refusal('Original current JP settings/overall end reached')
        owned=exact._identity(owned_identity)
        if exact._identity(current_identity)!=owned:raise Refusal('Current owned JP lifetime changed')
        for frame in (first,second):
            if (exact._identity(frame['identity_before'])!=owned or exact._identity(frame['identity_after'])!=owned
                    or frame.get('activity')!=ACTIVITY):raise Refusal('Current JP native lifetime/Activity mismatch')
            native,captured,activity=(exact._time(frame[key]) for key in ('native_at','captured_at','activity_at'))
            if not native<=captured<=activity or any(not 0<=now-value<=8 for value in (native,captured,activity)):
                raise Refusal('Current JP native/PNG/Activity pair is not fresh within8seconds')
        if first['id']==second['id'] or not first['activity_at']<second['native_at']:
            raise Refusal('Independent ordered current JP captures required')
        evidence=[self.observe(frame,state) for frame in (first,second)]
        compare=('surface','modal_bounds','modal_offset','viewport_bounds','selection','rows','target_bounds')
        if any(evidence[0][key]!=evidence[1][key] for key in compare):raise Refusal('Current JP two fresh caption/radio/state proofs disagree')
        if state=='bulk':self._baseline=json.dumps(evidence[1],sort_keys=True)
        bounds=evidence[1]['target_bounds']
        return {'kind':'choose-light' if state=='bulk' else 'confirm-light','caption':LIGHT+SIZES['light'] if state=='bulk' else 'OK',
            'bounds':bounds,'center':[int((bounds[0]+bounds[2])/2),int((bounds[1]+bounds[3])/2)],
            'captures':[first['id'],second['id']],'evidence_kind':EVIDENCE,'evidence':evidence,
            'owned_identity':dict(owned),'checked_at':now,'overall_started':overall,'settings_started':settings,
            'overall_end':overall+2400,'settings_end':settings+120,'scope':'Ordinary native reference input only; all11false'}
