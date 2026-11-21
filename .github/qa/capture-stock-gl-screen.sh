#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
import csv
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


def tap(line):
    text = line[0]
    # The native title accepts a tap anywhere in the main Unity surface.
    # Android provides that surface's position through its accessibility tree.
    tree = subprocess.check_output([*adb, 'exec-out', 'uiautomator', 'dump', '/dev/tty'],
                                   text=True, timeout=15)
    start, end = tree.find('<?xml'), tree.rfind('</hierarchy>')
    if min(start, end) < 0:
        raise RuntimeError('Android did not expose the title UI bounds.')
    tree = ET.fromstring(tree[start:end + len('</hierarchy>')])
    app = 'com.klab.lovelive.allstars.global'
    nodes = [node for node in tree.iter('node') if node.get('package') == app]
    surface = next((node for node in nodes if node.get('class') == 'android.view.SurfaceView'), None)
    if surface is None:
        surface = next(iter(nodes), None)
    if surface is None:
        raise RuntimeError('Unity title was not in the active game window.')
    x1, y1, x2, y2 = map(int, re.findall(r'\d+', surface.get('bounds', '')))
    x, y = (x1+x2)//2, (y1+y2)//2
    subprocess.run([*adb, 'shell', 'input', 'tap', str(x), str(y)], check=True, timeout=10)
    print(f'Tapped verified title prompt at {x},{y}: {text}', flush=True)


with tempfile.TemporaryDirectory(prefix='stock-gl-screen-') as directory:
    path = Path(directory) / 'working.png'
    tapped_title = False
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
        if title and not tapped_title:
            (destination / 'stock-title.png').write_bytes(data)
            tap(title)
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
