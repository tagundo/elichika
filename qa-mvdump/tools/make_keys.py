"""Local-only generator of qa-mvdump/keys/mvdump-keys-<song>.json (never run in CI).

Inputs:
  --inventory  the expected-key inventory built from the editor importer and the original
               bundles (rtdump/12035-runtime-keys.json: tracks, shader property names, rig
               bones, global candidates)
  --bundles    optional folder with the song's shaderNN.bundle files; the shader property
               TYPES come from each Shader's m_ParsedForm.m_PropInfo.m_Props[].m_Type
               (0 Color, 1 Vector, 2 Float, 3 Range, 4 Texture). Needs UnityPy.

Output (< 20 KB), passed to the agent per part as options.keys subsets:
  globals / vectorArrays   Shader.GetGlobal* names (real globals first, then the negative
                           controls named after editor-driven lighting uniforms)
  shaders                  {shader name: {property: color|vector|float|tex}}
  bindings                 stage AnimationTrack/ActivationTrack binding paths (stageNodes part)
  member                   rig-relative bone paths (<= 24) and the anchor bones
  stageOrigin, lightingClasses, tracks (record only)

    python3 tools/make_keys.py --inventory .../rtdump/12035-runtime-keys.json \\
        --bundles .../rtdump-bundles --out keys/mvdump-keys-12035.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

TYPE_NAMES = {0: 'color', 1: 'vector', 2: 'float', 3: 'float', 4: 'tex'}
REAL_GLOBALS = ['_Beat', '_MusicTime', '_SelfTime', '_ColorsLength', '_RenderTextureResolution', '_Time']
NEGATIVE_CONTROLS = ['_AmbientColor', '_TintColor', '_BlendColor', '_RimlightColor', '_RimlightDirection',
                     '_RimglightIntensity', '_RimglightPower']
BONE_SUFFIXES = ['Reference/Move', 'Hips_Position', 'Hips', 'Hips/Spine', 'Spine1', 'Spine2', 'Neck', 'Neck/Head', 'Head_All',
                 'LeftShoulder', 'LeftArm', 'LeftForeArm', 'LeftHand', 'RightShoulder', 'RightArm', 'RightForeArm',
                 'RightHand', 'LeftUpLeg', 'LeftLeg', 'LeftFoot', 'RightUpLeg', 'RightLeg', 'RightFoot']
ANCHORS = {'Hips': 'Hips', 'Head': 'Neck/Head', 'LeftHand': 'LeftHand', 'RightHand': 'RightHand'}
LIGHTING_CLASSES = ['LiveCoreMemberAmbient', 'LiveCoreMemberRimlight', 'LiveCoreStageAmbient', 'LiveCoreStageModel',
                    'LivePropAmbient', 'LivePropRimlight', 'LiveCoreStagePenlight', 'LiveCoreStageColoring',
                    'LiveCoreStageFlashLight', 'LiveCoreStageDisplay']


def shader_types(bundles):
    import UnityPy  # local only
    out = {}
    for path in sorted(glob.glob(str(Path(bundles) / 'shader*.bundle'))):
        for obj in UnityPy.load(path).objects:
            if obj.type.name != 'Shader':
                continue
            form = obj.read_typetree()['m_ParsedForm']
            props = {p['m_Name']: TYPE_NAMES.get(p['m_Type'], 'float') for p in form['m_PropInfo']['m_Props']}
            if props:
                out[form['m_Name']] = dict(sorted(props.items()))
    return dict(sorted(out.items()))


def pick_bone(bones, suffix):
    found = [b for b in bones if b == suffix or b.endswith('/' + suffix)]
    found.sort(key=len)
    return found[0] if found else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--bundles', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    inv = json.loads(args.inventory.read_text())
    if args.bundles:
        shaders = shader_types(args.bundles)
    else:
        shaders = {name: {p: 'float' for p in entry['properties']} for name, entry in inv['shaders'].items() if entry['properties']}
    bones = inv['member1']['bones']
    chosen = []
    for suffix in BONE_SUFFIXES:
        bone = pick_bone(bones, suffix)
        if bone and bone not in chosen:
            chosen.append(bone)
    candidates = inv.get('shaderGlobalCandidates') or []
    globals_ = [g for g in REAL_GLOBALS if g in candidates or g == '_Time'] + NEGATIVE_CONTROLS
    bindings = sorted({t['binding'] for t in inv['tracks'] if t['nativeClass'] in ('AnimationTrack', 'ActivationTrack')
                       and '/Stages/' in t['binding']})
    keys = {
        'schema': 'mvdump-keys/1', 'song': inv['song'], 'asset': inv['asset'], 'platform': inv['platform'],
        'source': {'inventory': args.inventory.name, 'inventorySha256': hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
                   'shaderTypes': 'm_ParsedForm.m_PropInfo.m_Props[].m_Type' if args.bundles else 'unknown (float)'},
        'globals': globals_[:20], 'vectorArrays': [g for g in ('_Colors',) if g in candidates],
        'shaders': shaders, 'bindings': bindings,
        'member': {'rigRoot': inv['member1']['rigRoot'], 'bones': chosen[:24],
                   'anchors': {name: pick_bone(bones, suffix) for name, suffix in ANCHORS.items()}},
        'stageOrigin': '/EntryPoint/Live/Stages/MainStage',
        'lightingClasses': LIGHTING_CLASSES,
        'tracks': sorted({t['nativeClass'] for t in inv['tracks']}),
    }
    text = json.dumps(keys, indent=1, sort_keys=False) + '\n'
    if len(text.encode()) > 20000:
        raise SystemExit(f'keys file is {len(text.encode())} bytes (> 20 KB)')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(json.dumps({'out': str(args.out), 'bytes': len(text.encode()), 'shaders': len(shaders), 'bones': len(chosen),
                      'bindings': len(bindings), 'globals': len(keys['globals'])}))


if __name__ == '__main__':
    main()
