"""Exact V19 ordinary native/OCR helper functions; JP constant selected explicitly."""
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps
CLIENT = "com.klab.lovelive.allstars"


def center(node):
    value = node.get("center")
    if isinstance(value, dict):
        return int(value["x"]), int(value["y"])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    bounds = node.get("bounds")
    if isinstance(bounds, dict):
        if all(key in bounds for key in ("left", "right", "top", "bottom")):
            return int((bounds["left"] + bounds["right"]) / 2), int((bounds["top"] + bounds["bottom"]) / 2)
        if all(key in bounds for key in ("x", "y", "width", "height")):
            return int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2)
    raise ValueError("The UI tree target has no screen bounds.")


def parse_native_nodes(raw):
    """Preserve live layout ancestry/index so clipped sibling controls can be associated."""
    root = ET.fromstring(raw)
    result = []
    def visit(node, path, parent, scroll_bounds):
        points = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
        bounds = dict(zip(("left", "top", "right", "bottom"), points)) if len(points) == 4 else None
        index = int(node.get("index", "0"))
        own_path = path + "/" + str(index)
        if bounds:
            record = {"text": node.get("text", ""), "name": node.get("resource-id", ""), "label": node.get("content-desc", ""),
                      "class": node.get("class", ""), "package": node.get("package", ""), "checked": node.get("checked") == "true",
                      "scrollable": node.get("scrollable") == "true", "clickable": node.get("clickable") == "true", "enabled": node.get("enabled") == "true",
                      "bounds": bounds, "center": {"x": (points[0] + points[2]) // 2, "y": (points[1] + points[3]) // 2},
                      "layout_path": own_path, "parent_path": parent, "child_index": index, "scroll_bounds": scroll_bounds}
            result.append(record)
        child_scroll = bounds if node.get("class") == "android.widget.ScrollView" and bounds else scroll_bounds
        for child in node.findall("node"):
            visit(child, own_path, own_path, child_scroll)
    for node in root.findall("node"):
        visit(node, "", "", None)
    return result


def control_fully_visible(node):
    bounds = node.get("bounds") or {}
    if bounds.get("right", 0) <= bounds.get("left", 0) or bounds.get("bottom", 0) <= bounds.get("top", 0):
        return False
    viewport = node.get("scroll_bounds")
    # Bounds are clipped by accessibility. A control touching a viewport edge
    # is re-searched after scrolling rather than dragging its clipped sliver.
    return not viewport or (bounds["top"] > viewport["top"] + 1 and bounds["bottom"] < viewport["bottom"] - 1)


def slider_caption_value(nodes, role):
    values = []
    for node in nodes:
        match = re.fullmatch(role + r"Aspect\s*=\s*([0-9.]+)", node.get("text", ""), re.I)
        if match:
            values.append(float(match[1]))
    return values[0] if len(set(values)) == 1 else None


def native_profile_plan(nodes, state, orientation, fast_intro):
    """Choose one action from fresh geometry; language selection happens once."""
    usable = [n for n in nodes if n.get("enabled") and control_fully_visible(n)]
    if not state.get("language"):
        english = [n for n in usable if n.get("clickable") and n.get("text") == "English"]
        if len(english) == 1:
            return {"kind": "language", "node": english[0]}
        raise ValueError("Initial English setting is not uniquely visible")
    catalog = state.setdefault("label_catalog", {})
    for node in nodes:
        match = re.match(r"^(Min|Max)Aspect(?:\b|\s*=)", node.get("text", ""), re.I)
        if match:
            catalog[(node.get("parent_path"), node.get("child_index"))] = match[1].lower()
    for bar in sorted([n for n in usable if n.get("class") == "android.widget.SeekBar"], key=lambda n: n["bounds"]["top"]):
        index = bar.get("child_index")
        preceding = [(key[1], value) for key, value in catalog.items() if key[0] == bar.get("parent_path") and isinstance(index, int) and isinstance(key[1], int) and 0 < index - key[1] <= 2]
        if not preceding:
            continue
        role = max(preceding)[1]
        if not state.get(role):
            return {"kind": "slider", "role": role, "node": bar}
    if not state.get("orientation"):
        choices = [n for n in usable if n.get("class") == "android.widget.RadioButton" and n.get("text", "").casefold() == orientation]
        if len(choices) == 1:
            return {"kind": "orientation", "node": choices[0], "needs_tap": not choices[0].get("checked")}
    if not state.get("intro"):
        checks = [n for n in usable if n.get("class") == "android.widget.CheckBox"]
        if len(checks) == 1:
            return {"kind": "intro", "node": checks[0], "needs_tap": checks[0].get("checked") != fast_intro}
    if all(state.get(key) for key in ("min", "max", "orientation", "intro")):
        launch = [n for n in usable if n.get("text", "").casefold() == "start game" and n.get("clickable")]
        if len(launch) == 1:
            return {"kind": "launch", "node": launch[0]}
    scrolls = [n for n in nodes if n.get("class") == "android.widget.ScrollView" and n.get("scrollable") and n.get("bounds", {}).get("bottom", 0) > n.get("bounds", {}).get("top", 0)]
    if len(scrolls) != 1:
        raise ValueError("No unique live ScrollView to re-search missing feature controls")
    return {"kind": "scroll", "node": scrolls[0]}


def unity_surface_bounds(nodes, screen):
    surfaces = [node for node in nodes if node.get("package") == CLIENT and node.get("class", "").endswith("SurfaceView")]
    if not surfaces:
        # API 34 accessibility exposes Unity's SurfaceView as android.view.View.
        # The actual game's content root still supplies its live screen rect.
        surfaces = [node for node in nodes if node.get("package") == CLIENT and node.get("name") == "android:id/content"]
    if len(surfaces) != 1:
        raise ValueError("The live Unity UI geometry has no unique Android content surface")
    bounds = surfaces[0].get("bounds") or {}
    if (bounds.get("left"), bounds.get("top"), bounds.get("right"), bounds.get("bottom")) != (0, 0, screen.get("width"), screen.get("height")):
        raise ValueError("Unity and Android UI tree coordinate spaces differ")
    return bounds


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ocr_words(image, *, crop=None, scale=1, mode='normal', psm=11, language='eng'):
    """Return actual OCR boxes in original screenshot coordinates plus raw TSV."""
    crop = crop or (0, 0, image.width, image.height)
    region = image.crop(crop).convert('RGB')
    if mode == 'title':
        selected = [0 if r > 180 and b > 100 and (g < 180 or min(r,g,b)>220) else 255
                    for r,g,b in region.getdata()]
        mask = Image.new('L', region.size); mask.putdata(selected); region = mask
    elif mode == 'pink':
        region = ImageOps.invert(region.getchannel('G'))
    if scale != 1:
        region = region.resize((region.width*scale, region.height*scale))
    with tempfile.TemporaryDirectory(prefix='fresh-native-ocr-') as temporary:
        source = Path(temporary)/'input.png'; region.save(source)
        env = dict(os.environ, OMP_THREAD_LIMIT='1')
        raw = subprocess.check_output(['tesseract',str(source),'stdout','-l',language,
              '--psm',str(psm),'tsv'],env=env,stderr=subprocess.DEVNULL,timeout=15).decode()
    words = []
    for row in csv.DictReader(io.StringIO(raw),delimiter='\t'):
        text = (row.get('text') or '').strip()
        confidence = float(row.get('conf') or -1)
        if not text or confidence < 75: continue
        left,top,width,height = (int(row[k]) for k in ('left','top','width','height'))
        words.append({'text':text,'confidence':confidence,
            'bounds':[crop[0]+left/scale,crop[1]+top/scale,
                      crop[0]+(left+width)/scale,crop[1]+(top+height)/scale]})
    return words, {'crop':list(crop),'scale':scale,'mode':mode,'psm':psm,'language':language,'tsv':raw}


def exact_word(words, caption):
    targets=[w for w in words if w['text'].casefold()==caption.casefold()]
    return targets[0] if len(targets)==1 else None


def union_box(words):
    return [min(w['bounds'][0] for w in words),min(w['bounds'][1] for w in words),
            max(w['bounds'][2] for w in words),max(w['bounds'][3] for w in words)]


def title_caption(words):
    title=[exact_word(words,word) for word in ('TAP','TO','START')]
    if all(title) and all(w.get('confidence',-1)>=75 for w in title):
        centers=[(w['bounds'][0]+w['bounds'][2])/2 for w in title]
        ys=[(w['bounds'][1]+w['bounds'][3])/2 for w in title]
        if centers==sorted(centers) and max(ys)-min(ys)<10:
            return {'kind':'title-start','bounds':union_box(title),'caption':'TAP TO START',
                    'confidence':min(w['confidence'] for w in title)}
    return None
