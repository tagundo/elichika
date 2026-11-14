"""Narrow actual GL portrait Home anchors; OCR never qualifies a feature."""
import math
from PIL import Image

PROFILE='gl-portrait-left-navigation-v19-reference'
MIN_CONFIDENCE=75
RECIPES=(('navigation',(32,1213,206,1270),6,11,'neutral-dark'),
         ('school',(46,1246,85,1258),8,7,'normal'),
         ('shop',(149,1211,197,1234),6,7,'normal'))
ANCHORS={'Shop':'shop','School':'school','Idols':'navigation','Exchange':'navigation'}


def crop_box(reference,width,height):
    return [round(reference[0]*width/720),round(reference[1]*height/1280),
            round(reference[2]*width/720),round(reference[3]*height/1280)]


def targeted_metadata(image,metadata,reader):
    width,height=image.size
    surface={'left':0,'top':0,'right':width,'bottom':height}
    if metadata.get('surface')!=surface or width*16!=height*9:return None
    regions=[]
    for name,reference,scale,psm,mode in RECIPES:
        box=crop_box(reference,width,height);region=image.crop(box).convert('RGB')
        if mode=='neutral-dark':
            mask=Image.new('L',region.size)
            mask.putdata([0 if max(pixel)<180 and max(pixel)-min(pixel)<35 else 255 for pixel in region.getdata()])
            region=mask
        words,raw=reader(region,scale=scale,psm=psm)
        mapped=[{**word,'bounds':[word['bounds'][0]+box[0],word['bounds'][1]+box[1],
                                  word['bounds'][2]+box[0],word['bounds'][3]+box[1]]} for word in words]
        regions.append({'id':name,'words':mapped,'transform':{'crop':box,'reference_size':[720,1280],
            'reference_crop':list(reference),'scale':scale,'psm':psm,'language':'eng','mode':mode,
            'threshold':'max(R,G,B)<180 AND max-min<35' if mode=='neutral-dark' else None,
            'resize':'PIL BICUBIC','rotation_degrees':0,
            'inverse':'original_x=crop_left+TSV_x/scale; original_y=crop_top+TSV_y/scale',
            'source_png_sha256':metadata.get('screenshot_sha256'),'raw_tsv':raw['tsv']}})
    return {'profile':PROFILE,'surface':surface,'source_png_sha256':metadata.get('screenshot_sha256'),'regions':regions}


def _valid_word(word,box):
    try:
        score=word['confidence'];bounds=word['bounds']
        return (type(score) in (int,float) and math.isfinite(score) and MIN_CONFIDENCE<=score<=100 and
            len(bounds)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in bounds) and
            box[0]<=bounds[0]<bounds[2]<=box[2] and box[1]<=bounds[1]<bounds[3]<=box[3])
    except (KeyError,TypeError):return False


def recognize(metadata,width,height):
    data=metadata.get('home_targeted_ocr')
    if data is None:return None
    observation={'home_profile':PROFILE,'home_anchors':{},'accepted':False,
                 'scope':'Visible native candidate only; real bootstrap and native-TID-bound managed Home verification remain required.'}
    surface={'left':0,'top':0,'right':width,'bottom':height}
    if (not isinstance(data,dict) or data.get('profile')!=PROFILE or width*16!=height*9 or
        data.get('surface')!=surface or metadata.get('surface')!=surface or
        data.get('source_png_sha256')!=metadata.get('screenshot_sha256')):return observation
    regions=data.get('regions')
    if not isinstance(regions,list) or len(regions)!=len(RECIPES):return observation
    by_id={region.get('id'):region for region in regions if isinstance(region,dict)}
    if len(by_id)!=len(RECIPES):return observation
    for name,reference,scale,psm,mode in RECIPES:
        region=by_id.get(name);box=crop_box(reference,width,height)
        if not region:return observation
        transform=region.get('transform') or {}
        expected={'crop':box,'scale':scale,'psm':psm,'mode':mode,
                  'source_png_sha256':metadata.get('screenshot_sha256')}
        if any(transform.get(key)!=value for key,value in expected.items()):return observation
        if not isinstance(region.get('words'),list):return observation
        for text,owner in ANCHORS.items():
            if owner!=name:continue
            found=[word for word in region['words'] if word.get('text')==text]
            if len(found)!=1 or not _valid_word(found[0],box):return observation
            observation['home_anchors'][text]=found[0]
    # Reject recognized modal captions; this is not a blanket proof that no
    # possible popup exists. The later native/managed Home checks still apply.
    buttons=metadata.get('button_words') or []
    modal=[word['text'] for word in buttons if _valid_word(word,[0,0,width,height]) and
           word.get('text') in {'OK','Close','Yes','No','Cancel','Next','Skip'}]
    observation['recognized_blocking_modal_captions']=modal
    if modal or metadata.get('action') is not None:return observation
    b={name:word['bounds'] for name,word in observation['home_anchors'].items()}
    center=lambda box:((box[0]+box[2])/2,(box[1]+box[3])/2)
    school,idols,shop,exchange=(b[name] for name in ('School','Idols','Shop','Exchange'))
    if not (shop[3]<school[1] and school[3]<=idols[1]+height/1280 and
            school[2]<shop[0] and idols[2]<exchange[0] and
            abs(center(school)[0]-center(idols)[0])<=max(school[2]-school[0],idols[2]-idols[0])*.35 and
            abs(center(shop)[0]-center(exchange)[0])<=max(shop[2]-shop[0],exchange[2]-exchange[0])*.35 and
            school[1]<=center(exchange)[1]<=idols[3]):return observation
    observation['accepted']=True
    return observation
