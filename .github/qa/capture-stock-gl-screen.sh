#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
import csv
from PIL import Image
import xml.etree.ElementTree as ET
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


serial, destination, mode = sys.argv[1:]
destination = Path(destination)
adb = ['adb', '-s', serial]
stock_title = re.compile(r'\b(?:tap|touch|press) (?:the screen |screen )?to start\b|\btap (?:the )?screen\b')
light = re.compile(r'\b(?:light|lightness) download\b')
full = re.compile(r'\b(?:full download|download all)\b')


def screen(path):
    data = subprocess.check_output([*adb, 'exec-out', 'screencap', '-p'], timeout=30)
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('The Android screenshot is not a complete PNG.')
    path.write_bytes(data)
    output = subprocess.check_output(['tesseract', str(path), 'stdout', '--psm', '11', 'tsv'],
                                     text=True, stderr=subprocess.DEVNULL, timeout=12)
    groups = {}
    for word in csv.DictReader(output.splitlines(), delimiter='\t'):
        text = word['text'] or ''
        if text.strip() and float(word['conf']) >= 40:
            key = tuple(word[name] for name in ('block_num', 'par_num', 'line_num'))
            groups.setdefault(key, []).append(word)
    lines = []
    for words in groups.values():
        coords = [(int(w['left']), int(w['top']), int(w['width']), int(w['height'])) for w in words]
        left = min(x for x, y, width, height in coords)
        top = min(y for x, y, width, height in coords)
        right = max(x + width for x, y, width, height in coords)
        bottom = max(y + height for x, y, width, height in coords)
        text = ' '.join(w['text'].casefold() for w in words)
        lines.append((text, (left + right) // 2, (top + bottom) // 2))
    return data, lines


def native_game_bounds():
    tree = subprocess.check_output([*adb, 'exec-out', 'uiautomator', 'dump', '/dev/tty'],
                                   text=True, timeout=15)
    start, end = tree.find('<?xml'), tree.rfind('</hierarchy>')
    if min(start, end) < 0:
        return None
    tree = ET.fromstring(tree[start:end + len('</hierarchy>')])
    app = 'com.klab.lovelive.allstars.global'
    nodes = [node for node in tree.iter('node') if node.get('package') == app]
    surface = next((node for node in nodes if node.get('content-desc') == 'Game view'), None)
    if surface is None:
        surface = next((node for node in nodes if node.get('class') == 'android.view.SurfaceView'), None)
    if surface is None:
        return None
    return tuple(map(int, re.findall(r'\d+', surface.get('bounds', ''))))


def tap_at(bounds, x_offset, y_offset, action):
    left, top, right, bottom = bounds
    x = left + round((right - left) * x_offset)
    y = top + round((bottom - top) * y_offset)
    subprocess.run([*adb, 'shell', 'input', 'tap', str(x), str(y)], check=True, timeout=15)
    print(f'Tapped {action} at {x},{y}', flush=True)


def english_chooser(frame, bounds, output):
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    # Unity exposes one Game view. Check the English label at its fixed
    # top-left choice using the Game view's live Android bounds.
    box = (left + round(width*.315), top + round(height*.401),
           left + round(width*.419), top + round(height*.463))
    image = Image.open(frame).convert('RGB').crop(box)
    image.getchannel('G').point(lambda value: 0 if value > 195 else 255).resize((940, 268)).save(output)
    label = subprocess.check_output(['tesseract', str(output), 'stdout', '--psm', '7'],
                                    text=True, stderr=subprocess.DEVNULL, timeout=12)
    return label.strip().casefold() == 'english'


with tempfile.TemporaryDirectory(prefix='stock-gl-screen-') as directory:
    path = Path(directory) / 'working.png'
    tapped_title = False
    selected_language = False
    confirmed_language = False
    data = b''
    text = ''
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            data, lines = screen(path)
        except subprocess.TimeoutExpired:
            continue
        title = next((line for line in lines if stock_title.search(line[0])), None)
        text = '\n'.join(line[0] for line in lines)
        if light.search(text) and full.search(text):
            (destination / 'stock-download-choices.png').write_bytes(data)
            (destination / 'download-dialog-ocr.txt').write_text(text + '\n')
            stock_dialog = 'Light and Full detected'
            break
        english_confirmation = ("select language" in text and "display language to english" in text
                                and "return to the title screen" in text)
        if not selected_language or (english_confirmation and not confirmed_language) or (title and not tapped_title):
            try:
                bounds = native_game_bounds()
            except subprocess.TimeoutExpired:
                bounds = None
            if bounds and not selected_language and english_chooser(path, bounds, Path(directory) / 'label.png'):
                (destination / 'stock-language.png').write_bytes(data)
                tap_at(bounds, .366, .435, 'English')
                selected_language = True
            elif bounds and english_confirmation and not confirmed_language:
                (destination / 'stock-language-confirmation.png').write_bytes(data)
                tap_at(bounds, .652, .791, 'the English selection confirmation')
                confirmed_language = True
                deadline = max(deadline, time.monotonic() + 180)
            elif bounds and title and not tapped_title:
                (destination / 'stock-title.png').write_bytes(data)
                tap_at(bounds, .5, .5, 'the title screen')
                tapped_title = True
        time.sleep(2)
    else:
        (destination / 'last-stock-screen.png').write_bytes(data)
        (destination / 'last-stock-screen-ocr.txt').write_text(text + '\n')
        stock_dialog = 'Download dialogue not visually verified'
    (destination / 'download-dialog-state.txt').write_text(stock_dialog + '\n')
    print(stock_dialog, flush=True)
    if stock_dialog != 'Light and Full detected':
        raise SystemExit(3)
    if mode == 'assets':
        # The first disposable run determines the actual Unity coordinates. An
        # optional QA-only continuation can consume the live disposable serial.
        # Leave Full and Light untouched until that route has been calibrated.
        import os
        plan = os.environ.get('ELICHIKA_GAME_QA_ASSET_PLAN')
        if plan:
            subprocess.run(['bash', plan, serial, str(destination)], check=True, timeout=1400)
        else:
            print('Asset mode reached its current calibrated boundary.', flush=True)
PY
