"""Pure conservative geometry for SHORT JP screenshots, never download choice."""
import hashlib
import io
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image
from native_capture_support import parse_native_nodes, unity_surface_bounds

PACKAGE = 'com.klab.lovelive.allstars'
REFERENCE_SHA = 'd6c8dc4d8326a8e0e9771decc6b0da3d1fe2bcb23a0e657f5e0f63f2b4c4ed7c'
CASES = ('native_load', 'fov_actual', 'portrait', 'landscape', 'auto', 'intro_timing',
    'mv_same_suit', 'mv_different_suits', 'mv_max_slots', 'mv_restore', 'no_new_costume_entries')
MISSING = "スクスタ won't run without Google Play services, which are not supported by your device."
CHOOSER_HEADER = (107, 450, 613, 488)
CHOOSER_FOOTER = (107, 780, 613, 829)


class StopCapture(RuntimeError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def image_of(raw):
    if type(raw) is not bytes or len(raw) > 5 * 1024**2:
        raise StopCapture('Screenshot exceeds bounded raw PNG size')
    with Image.open(io.BytesIO(raw)) as source:
        if (source.format != 'PNG' or source.mode not in ('RGB', 'RGBA')
                or min(source.size) < 300 or max(source.size) > 1920 or source.width*source.height > 2500000):
            raise StopCapture('Unsupported screenshot frame')
        source.load()
        if source.mode == 'RGBA' and source.getchannel('A').getextrema() != (255,255):
            raise StopCapture('Screenshot transparency rejected')
        return source.convert('RGB')


def native_surface(raw, frame):
    if type(raw) is not bytes or len(raw) > 128 * 1024 or b'<!' in raw:
        raise StopCapture('Unsupported current native XML')
    nodes = parse_native_nodes(raw)
    if not nodes or any(node['package'] != PACKAGE for node in nodes):
        raise StopCapture('Current native window has another package')
    focused = [node for node in ET.fromstring(raw).iter('node') if node.get('focused') == 'true']
    if (len(focused) != 1 or focused[0].get('content-desc') != 'Game view'
            or focused[0].get('enabled') != 'true'
            or focused[0].get('bounds') != f'[0,0][{frame[0]},{frame[1]}]'
            or any(node['text'] or node['clickable'] for node in nodes)):
        raise StopCapture('Native dialog/overlay or no unique focused Game view')
    return unity_surface_bounds(nodes, {'width': frame[0], 'height': frame[1]})


def missing_services(nodes):
    messages = [node for node in nodes if node.get('name') == 'android:id/message'
        and node.get('package') == PACKAGE and node.get('text') == MISSING]
    buttons = [node for node in nodes if node.get('name') == 'android:id/button1'
        and node.get('package') == PACKAGE and node.get('text') == 'OK'
        and node.get('class')=='android.widget.Button' and node.get('enabled') and node.get('clickable')]
    panels=[node for node in nodes if node.get('name')=='android:id/parentPanel' and node.get('enabled')]
    if (len(messages)!=1 or len(buttons)!=1 or len(panels)!=1
            or any(node.get('package')!=PACKAGE for node in nodes)
            or [node for node in nodes if node.get('clickable')]!=buttons
            or sorted(node['text'] for node in nodes if node.get('text'))!=sorted([MISSING,'OK'])):
        return None
    message,button,panel=messages[0],buttons[0],panels[0]['bounds']
    if not message.get('enabled') or message.get('class')!='android.widget.TextView':return None
    for node in (message,button):
        box=node['bounds']
        if not (panel['left']<=box['left']<box['right']<=panel['right']
                and panel['top']<=box['top']<box['bottom']<=panel['bottom']):return None
    return button if message['bounds']['bottom']<=button['bounds']['top'] else None


def asset_get_seen(raw):
    return bool(re.search(rb'^\[GIN\].*\|\s*GET\s+"/static/',raw,re.M))


def require_JP_settings(nodes):
    if not nodes or any(node.get('package')!=PACKAGE for node in nodes):
        raise StopCapture('Native settings window includes an unexpected package/overlay')


def _locations(image, template):
    """Globally search exact RGB; verify every strip pixel after anchor filter."""
    w,h = image.size; tw,th = template.size
    if tw > w or th > h:
        return []
    raw, expected = image.tobytes(), template.tobytes()
    stride, row_size = w*3, tw*3
    rows = [expected[y*row_size:(y+1)*row_size] for y in range(th)]
    ay = max(range(th), key=lambda y:len(set(rows[y])))
    pos=0; hits=[]; count=0
    while True:
        pos=raw.find(rows[ay],pos)
        if pos < 0:
            return hits
        found=pos;pos+=1
        if found%3:
            continue
        x,y=(found%stride)//3,found//stride-ay
        if not (0<=x<=w-tw and 0<=y<=h-th):
            continue
        count+=1
        if count>4096:
            raise StopCapture('Too many static chooser strip candidates')
        if all(raw[(y+dy)*stride+x*3:(y+dy)*stride+x*3+row_size] == row for dy,row in enumerate(rows)):
            hits.append([x,y,x+tw,y+th])
            if len(hits)>1:
                return hits


def chooser_geometry(raw):
    """Static header/footer identify a diagnostic scroll area, never a radio."""
    image=image_of(raw)
    reference=(Path(__file__).parent/'fixtures/actual-jp-chooser.png').read_bytes()
    if digest(reference)!=REFERENCE_SHA:
        raise StopCapture('Actual retained JP chooser reference changed')
    original=image_of(reference)
    headers=_locations(image,original.crop(CHOOSER_HEADER))
    footers=_locations(image,original.crop(CHOOSER_FOOTER))
    if len(headers)!=1 or len(footers)!=1:
        return None
    head,foot=headers[0],footers[0]
    if not (head[0]==foot[0] and head[2]==foot[2] and 150<=foot[1]-head[3]<=500):
        return None
    left,top,right,bottom=head[0],head[3]+12,head[2],foot[1]-12
    # Search current pixels for a blank gutter left of the scrollbar and right
    # of the colored option panels. No old radio, footer, or gesture coordinates.
    candidates=[]
    for x in range(left+int((right-left)*.86),right-8):
        if all(min(image.getpixel((x,y)))>=245 for y in range(top,bottom)):
            candidates.append(x)
    runs=[]
    for x in candidates:
        if runs and x==runs[-1][-1]+1:runs[-1].append(x)
        else:runs.append([x])
    runs=[run for run in runs if len(run)>=8]
    if len(runs)!=1:
        return None
    gutter=runs[0];x=(gutter[0]+gutter[-1])//2
    distance=min((bottom-top)//5,(foot[3]-head[1])//10,48)
    start_y=bottom-18;end_y=start_y-distance
    if not (20<=distance<=48 and top+18<end_y<start_y<bottom):
        return None
    return {'source':'current-exact-JP-static-header-footer-and-blank-gutter-pixels',
        'scope':'Diagnostic scroll geometry only; no caption/radio identity or download authorization',
        'modal_bounds':[head[0],head[1],foot[2],foot[3]],
        'content_bounds':[left,top,right,bottom], 'gutter':[gutter[0],gutter[-1]+1],
        'start':[x,start_y], 'end':[x,end_y], 'duration_ms':500,
        'content_sha256':digest(image.crop((left,top,right,bottom)).tobytes())}


def has_large_pale_panel(raw):
    image=image_of(raw);w,h=image.size
    pixels=image.crop((w//5,h*35//100,w*4//5,h*75//100)).getdata()
    return sum(min(pixel)>=235 for pixel in pixels)/len(pixels)>.80


def fresh_pair(first, second, *, identity, now, require_surface=True):
    if type(now) not in (int,float) or not math.isfinite(now):
        raise StopCapture('Invalid monotonic clock')
    if first['id']==second['id'] or not (first['captured_at']<second['native_at']<=second['captured_at']):
        raise StopCapture('Independent ordered captures required')
    for frame in (first,second):
        if frame['identity_before']!=identity or frame['identity_after']!=identity:
            raise StopCapture('Owned game lifetime changed during capture')
        if frame['png_sha256']!=digest(frame['png_bytes']) or frame['native_sha256']!=digest(frame['native_xml']):
            raise StopCapture('Capture bytes changed')
        if not all(type(frame[key]) in (int,float) and math.isfinite(frame[key])
                and 0<=now-frame[key]<=8 for key in ('captured_at','native_at')):
            raise StopCapture('Both PNG and native captures must be within8seconds')
        if frame['native_at']>frame['captured_at']:
            raise StopCapture('Native tree was not captured before PNG')
        if require_surface:
            actual=native_surface(frame['native_xml'],image_of(frame['png_bytes']).size)
            if actual!=frame['surface']:
                raise StopCapture('Supplied native Surface does not match current XML')
    if first['surface']!=second['surface']:
        raise StopCapture('Current native Surfaces disagree')


class ScrollBudget:
    """Two attempts total; reservation is durable before any gesture send."""
    def __init__(self):
        self.attempts=0

    def reserve(self, first, second, *, identity, current_identity, now, persist):
        if current_identity!=identity:
            raise StopCapture('Owned game lifetime changed before scroll')
        if self.attempts>=2:
            raise StopCapture('Two diagnostic scroll attempts exhausted')
        fresh_pair(first,second,identity=identity,now=now)
        a,b=chooser_geometry(first['png_bytes']),chooser_geometry(second['png_bytes'])
        keys=('modal_bounds','content_bounds','gutter','start','end','duration_ms')
        if not a or not b or any(a[key]!=b[key] for key in keys):
            raise StopCapture('No stable safe current chooser gutter')
        self.attempts+=1
        intent={'kind':'diagnostic-chooser-upward-scroll','attempt':self.attempts,
            'captures':[first['id'],second['id']],'identity':dict(identity),**b}
        persist(intent)
        return intent
