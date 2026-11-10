#!/usr/bin/env python3
"""Run the final signed app, then relaunch it from a space/Unicode path."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from common import require, run, sha256, write_json
from verify_runtime import private_environment


ZIP_FIXTURE = r'''
import hashlib,json,math,pathlib,sys,zipfile
import UnityPy
source=pathlib.Path(sys.argv[1]); output=pathlib.Path(sys.argv[2]); report=pathlib.Path(sys.argv[3])
raw=source.read_bytes(); original_sha=hashlib.sha256(raw).hexdigest()
assert original_sha=='0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1'
environment=UnityPy.load(raw)
names={obj.path_id:obj.read_typetree()['m_Name'] for obj in environment.objects if obj.type.name=='GameObject'}
angle=math.radians(12.34567)/2
changed=[]
for obj in environment.objects:
    if obj.type.name!='Transform': continue
    tree=obj.read_typetree()
    if names.get(tree['m_GameObject']['m_PathID'])!='LeftUpLeg': continue
    tree['m_LocalPosition']['y']=0.1234567
    tree['m_LocalRotation']={'x':math.sin(angle),'y':0.,'z':0.,'w':math.cos(angle)}
    obj.save_typetree(tree); changed.append(obj.path_id)
assert len(changed)==1
modified=environment.file.save()
reloaded=UnityPy.load(modified)
transforms={}
meshes=[]
for obj in reloaded.objects:
    tree=obj.read_typetree()
    if obj.type.name=='Transform':
        transforms[names.get(tree['m_GameObject']['m_PathID'],'')]=tree
    elif obj.type.name=='Mesh':
        meshes.append({'vertices':tree['m_VertexData']['m_VertexCount'],
            'triangles':sum(part['indexCount']//3 for part in tree['m_SubMeshes'])})
assert {'Move','LeftUpLeg','BreastSize'}<=set(transforms)
assert meshes==[{'vertices':6,'triangles':4}]
position=transforms['LeftUpLeg']['m_LocalPosition']
rotation=transforms['LeftUpLeg']['m_LocalRotation']
assert abs(position['y']-0.1234567)<1e-8 and abs(position['y']*10000-round(position['y']*10000))>0.1
assert abs(2*math.degrees(math.atan2(rotation['x'],rotation['w']))-12.34567)<1e-5
assert source.read_bytes()==raw
info=zipfile.ZipInfo('분수 의상.unity',date_time=(2020,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
with zipfile.ZipFile(output,'w') as archive: archive.writestr(info,modified)
with zipfile.ZipFile(output) as archive:
    assert archive.namelist()==[info.filename] and archive.read(info.filename)==modified
value={'status':'PASS_SYNTHETIC_FRACTIONAL_ZIP_INPUT','fixture_source_sha256':original_sha,
    'fixture_source_preserved':True,'zip':str(output),'zip_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
    'unity_member':info.filename,'unity_member_sha256':hashlib.sha256(modified).hexdigest(),
    'fractional_node':'LeftUpLeg','position':position,'rotation_quaternion':rotation,'rotation_x_degrees':12.34567,
    'nodes':sorted(transforms),'meshes':meshes,'scope':'Generated QA geometry; original bundled fixture is immutable'}
report.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(value,ensure_ascii=False))
'''


ACCESSORY_FIXTURE_SHA = "4d59e904442cd75bb70368e16a46c369ad977a3b73677cff581a6fc53d8e043e"
GAME_PHYSICS_FIXTURE_SHA = "d619ef6e956d3b8557660ebbd070e8c998c0c0c82dc2fb97a8755c2a4d74e66e"
DETAIL_FIXTURE_SHA = "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1"
GAZE_FIXTURE_SHA = "4058786fad837b3292bf1fdba0b9181719b7c7e9e756a705c266af146d113129"
LIBRARY_MOTION_SHA = "b512951eaa10cc2cce1d53dca961ad3abbc5e731ce4c58a7b78ee9c4cc2ce7a9"
PART_TARGET_SHA = "fe6f3c7749f116faad61152ee6f76978a4200e409dd5c0c577ce505a33f3a7f8"
PART_DONOR_SHA = "de4e0e267f9435f626b0a1e7d556375f6fe2d12a7da22227ce7dbd373fd42d89"
UPDATER_INPUTS = (("member6", "viewer_thumbnail_member_6.zip", "e60eb0fa3e6e1860bb956e70337c23908faab3f2a9c66192531b645b971538f7", 17405, 6),
                  ("member201", "viewer_thumbnail_member_201.zip", "473fb2c5a57c95b5259ada0c3bf88eaf7db4586f8c662d4f03cfeaceb48fa969", 17421, 201))
THUMBNAIL_ORACLE = r'''
import json,pathlib,runpy,sys
spec,resources,output=(pathlib.Path(value) for value in sys.argv[1:])
assert pathlib.Path(sys.prefix).samefile(resources/'runtime/arm64/python')
observed=json.loads(spec.read_text())
oracle=runpy.run_path(str(resources/'qa/viewer_thumbnail_oracle.py'))
result=json.loads(oracle['inspect_json'](spec.read_text(),str(resources/'python-app/webtools/web/static/thumbnail-sdk'),
                                     observed['source_path'],observed['source_sha256']))
result['private_prefix_samefile']=True;result['python_executable']=sys.executable
output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');print(json.dumps(result,ensure_ascii=False))
'''
DETAIL_OUTLINE_ORACLE = r'''
#!/usr/bin/env python3
"""Independent oracle for NativeDetailQa's actual outline-only Unity export.

Usage with the app's bundled Python (isolated mode is recommended):
  python3 -I -B verify_outline_save.py source.unity saved.unity recipe.json report.json PYTHON_PREFIX

Uses only the standard library and UnityPy. It deliberately imports no Elichika
code and fixes expectations to the audited neutral six-vertex fixture. A passing
report proves exact source identity, source-bound recipe intent, exactly one
changed Mesh object, and exactly one changed raw byte within that Mesh.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import UnityPy


SOURCE_SHA256 = "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1"
SOURCE_SIZE = 72872
MESH_RAW_SHA256 = "e3c64edfd7c34b3c14ae024ed5ec05f02e507f4b1fd231ea3bb2da9fd5e78127"
VERTEX_BUFFER_SHA256 = "1130af5048c8d518e509824633aa9df6d6de6fc4910f75dcb802879646503811"
MESH_ID = 1
VERTEX_COUNT = 6
VERTEX_STRIDE = 56
COLOR_OFFSET = 52
VERTEX_BUFFER_RAW_OFFSET = 404
RAW_RED_OFFSET = VERTEX_BUFFER_RAW_OFFSET + COLOR_OFFSET
ORIGINAL_RGBA = [255, 255, 0, 255]
EXPECTED_SPARSE = [{"id": "0:0:1", "factor": 1.0, "vertices": [{"vertex": 0, "value": 0.25}]}]
EXPECTED_STATE = {"version": 1, "edits": [], "savedSettingsEnabled": True,
                  "unsupported": [], "compensationReference": [], "outlines": EXPECTED_SPARSE}
EXPECTED_TYPES = {1: "Mesh", 2: "GameObject", 3: "Transform", 4: "GameObject", 5: "Transform",
                  6: "GameObject", 7: "Transform", 8: "GameObject", 9: "Transform", 10: "GameObject",
                  11: "Transform", 12: "SkinnedMeshRenderer", 13: "Material", 14: "Texture2D",
                  15: "AnimationClip", 16: "MonoBehaviour", 17: "MonoScript", 18: "Shader"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate recipe JSON key: " + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Non-finite recipe JSON number: " + value)


def exact_json(actual, expected):
    """Require integer IDs/versions; accept int/float widths, never bools."""
    if type(expected) is int:
        return type(actual) is int and actual == expected
    if type(expected) is float:
        return type(actual) in (int, float) and actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(exact_json(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(exact_json(a, e) for a, e in zip(actual, expected))
    return actual == expected


def objects(raw):
    environment = UnityPy.load(raw)
    loaded = list(environment.objects)
    require(len({id(obj.assets_file) for obj in loaded}) == 1, "Expected exactly one serialized file")
    # UnityPy names standalone byte-loaded assets using hash(raw); that name is
    # process-dependent and changes after a legitimate save. Sole-file ordinal
    # zero plus the exact path IDs is the stable identity used by this recipe.
    result = {obj.path_id: obj for obj in loaded}
    require(len(result) == len(loaded) == 18, "Object IDs must be unique and the 18 original objects must remain")
    require({key: obj.type.name for key, obj in result.items()} == EXPECTED_TYPES, "Object IDs or types changed")
    return environment, result


def verify(source_path, saved_path, recipe_path, prefix, *, absolute=False):
    require(os.path.samefile(sys.prefix, prefix), "Oracle must run with the specified bundled Python prefix")
    require(source_path.resolve() != saved_path.resolve(), "Saved model must be a new file")
    source = source_path.read_bytes()
    saved = saved_path.read_bytes()
    require(len(source) == SOURCE_SIZE and digest(source) == SOURCE_SHA256, "Source differs from the audited clean fixture")
    require(saved != source, "Saved model must contain the intended sparse outline edit")

    recipe = json.loads(recipe_path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object,
                        parse_constant=invalid_constant)
    require(type(recipe) is dict and set(recipe) == {"format", "version", "sources", "originals", "state", "nodeIdentities"},
            "Recipe schema changed")
    require(recipe["format"] == "elichika-viewer-body-edit" and type(recipe["version"]) is int and recipe["version"] == 1,
            "Recipe format/version changed")
    expected_sources = [{"name": source_path.name, "sha256": SOURCE_SHA256, "container": 0, "member": None}]
    expected_originals = [{"name": source_path.name, "sha256": SOURCE_SHA256}]
    require(exact_json(recipe["sources"], expected_sources), "Recipe source identity differs from the actual clean input")
    require(exact_json(recipe["originals"], expected_originals), "Recipe original identity differs from the actual clean input")
    expected_state = copy.deepcopy(EXPECTED_STATE)
    if absolute:
        expected_state["outlines"] = [{"id": "0:0:1", "factor": 1.0, "absolute": 37}]
    require(exact_json(recipe["state"], expected_state), "Recipe is not exactly the intended outline-only state")
    require(recipe["nodeIdentities"] == [], "Outline-only recipe must not carry body node identities")

    before_env, before = objects(source)
    after_env, after = objects(saved)
    source_mesh = before[MESH_ID]
    target_mesh = after[MESH_ID]
    source_tree = source_mesh.read_typetree()
    target_tree = target_mesh.read_typetree()
    require(source_tree["m_Name"] == "NeutralRibbon", "Unexpected source mesh")
    source_raw = source_mesh.get_raw_data()
    target_raw = target_mesh.get_raw_data()
    require(len(source_raw) == 960 and digest(source_raw) == MESH_RAW_SHA256, "Original Mesh raw layout differs")
    vd = source_tree["m_VertexData"]
    source_data = bytes(vd["m_DataSize"])
    target_data = bytes(target_tree["m_VertexData"]["m_DataSize"])
    require(vd["m_VertexCount"] == VERTEX_COUNT and len(source_data) == VERTEX_COUNT * VERTEX_STRIDE,
            "Source six-vertex stream differs")
    require(vd["m_Channels"][3] == {"stream": 0, "offset": COLOR_OFFSET, "format": 2, "dimension": 4},
            "Source color channel differs from original four-byte UNorm8 layout")
    require(all(row["stream"] == 0 for row in vd["m_Channels"] if row["dimension"]), "Expected one source vertex stream")
    require(digest(source_data) == VERTEX_BUFFER_SHA256, "Source vertex buffer differs")
    require(source_raw.find(source_data) == VERTEX_BUFFER_RAW_OFFSET
            and source_raw.find(source_data, VERTEX_BUFFER_RAW_OFFSET + 1) == -1, "Source vertex buffer raw location differs")
    require(struct.unpack("<12H", bytes(source_tree["m_IndexBuffer"])) == (0, 1, 2, 1, 3, 2, 2, 3, 4, 3, 5, 4),
            "Source triangle indices differ")

    colors_before = [list(source_data[index * VERTEX_STRIDE + COLOR_OFFSET:index * VERTEX_STRIDE + COLOR_OFFSET + 4])
                     for index in range(VERTEX_COUNT)]
    colors_after = [list(target_data[index * VERTEX_STRIDE + COLOR_OFFSET:index * VERTEX_STRIDE + COLOR_OFFSET + 4])
                    for index in range(VERTEX_COUNT)]
    require(colors_before == [ORIGINAL_RGBA] * VERTEX_COUNT, "Source masks differ from neutral fixture")
    # This is the independent expected result: round(0.25 * 255) = 64.
    expected_buffer = bytearray(source_data)
    changed_vertices = list(range(VERTEX_COUNT)) if absolute else [0]
    expected_red = 37 if absolute else 64
    for vertex in changed_vertices:
        expected_buffer[vertex * VERTEX_STRIDE + COLOR_OFFSET] = expected_red
    require(target_data == bytes(expected_buffer), "Saved vertex stream differs beyond vertex0 red=64")
    expected_tree = copy.deepcopy(source_tree)
    expected_tree["m_VertexData"]["m_DataSize"] = target_tree["m_VertexData"]["m_DataSize"]
    require(target_tree == expected_tree, "Saved mesh has changes outside the one color byte")
    expected_mesh = bytearray(source_raw)
    for vertex in changed_vertices:
        expected_mesh[RAW_RED_OFFSET + vertex * VERTEX_STRIDE] = expected_red
    require(target_raw == bytes(expected_mesh), "Saved raw Mesh must equal source with only raw byte456 changed to64")
    changed = sorted(key for key in before if before[key].get_raw_data() != after[key].get_raw_data())
    require(changed == [MESH_ID], "Objects changed outside the one intended Mesh: " + repr(changed))
    require(source_path.read_bytes() == source, "Actual source file changed while the oracle was reading")

    return {"schemaVersion": 1, "status": "PASS", "source_sha256": digest(source), "output_sha256": digest(saved),
            "source_bytes": len(source), "output_bytes": len(saved), "private_prefix_samefile": True,
            "sourcePreserved": True, "recipeSourceBound": True, "recipeExactSparseOutlineOnly": not absolute, "recipeExactAbsoluteOutlineOnly": absolute,
            "onlyIntendedMeshChanged": True, "exactRawRedByteDelta": True,
            "allOtherRawObjectsByteIdentical": True, "allNonRedMeshDataByteIdentical": True,
            "positionsWeightsIndicesNormalsMaterialsTexturesPreserved": True,
            "serializedFileOrdinal": 0, "objectCount": len(before), "unchangedObjectCount": len(before) - 1,
            "onlyChangedObjectIds": changed, "mesh": {"pathId": str(MESH_ID), "name": "NeutralRibbon", "vertexCount": VERTEX_COUNT,
            "rawBytes": len(source_raw), "vertexStride": VERTEX_STRIDE, "colorOffset": COLOR_OFFSET,
            "changedVertex": None if absolute else 0, "changedVertices": changed_vertices,
            "vertexBufferChangedByteOffsets": [COLOR_OFFSET + vertex * VERTEX_STRIDE for vertex in changed_vertices],
            "rawMeshChangedByteOffsets": [RAW_RED_OFFSET + vertex * VERTEX_STRIDE for vertex in changed_vertices],
            "rgbaBefore": colors_before, "rgbaAfter": colors_after}, "recipeState": recipe["state"],
            "inputPaths": {"source": str(source_path), "saved": str(saved_path), "recipe": str(recipe_path), "pythonPrefix": str(prefix)},
            "oracle": "Independent audited fixture constants and UnityPy raw/typetree reads; no product planner, editor, or export result reuse",
            "scope": "Exact serialized sparse outline Save on original six-vertex neutral fixture; no visible-width pixel claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "saved", "recipe", "report", "python_prefix"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--absolute", action="store_true")
    args = parser.parse_args()
    require(args.report.resolve() not in {args.source.resolve(), args.saved.resolve(), args.recipe.resolve()},
            "Report path must not overwrite an input")
    try:
        value = verify(args.source, args.saved, args.recipe, args.python_prefix, absolute=args.absolute)
    except Exception as error:
        value = {"schemaVersion": 1, "status": "FAIL", "error": type(error).__name__ + ": " + str(error)}
        args.report.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(value), file=sys.stderr)
        return 1
    args.report.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

'''


ACCESSORY_FIXTURE = r'''
import hashlib,importlib.util,json,os,pathlib,sys
app,helper,output,report,prefix=map(pathlib.Path,sys.argv[1:])
assert os.path.samefile(sys.prefix,prefix)
sys.path.insert(0,str(app))
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
spec=importlib.util.spec_from_file_location('native_accessory_fixture',helper)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
raw=module.make_fixture()
digest=hashlib.sha256(raw).hexdigest()
assert digest=='4d59e904442cd75bb70368e16a46c369ad977a3b73677cff581a6fc53d8e043e'
output.write_bytes(raw)
value={'status':'PASS_OWN_SERIALIZED_ACCESSORY_INPUT','fixture_sha256':digest,'bytes':len(raw),
    'path':str(output),'vertices':21,'triangles':7,'private_prefix_samefile':True,
    'scope':'Original generated neutral geometry; no game or user model'}
report.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
'''


ACCESSORY_ORACLE = r'''
import copy,hashlib,json,math,os,pathlib,sys
import UnityPy
prefix,source_path,output_path,report=map(pathlib.Path,sys.argv[1:])
assert os.path.samefile(sys.prefix,prefix)
source=source_path.read_bytes();output=output_path.read_bytes()
assert hashlib.sha256(source).hexdigest()=='4d59e904442cd75bb70368e16a46c369ad977a3b73677cff581a6fc53d8e043e'
def records(raw):
    env=UnityPy.load(raw);objects={obj.path_id:obj for obj in env.objects}
    assert len(objects)==len(env.objects)
    names={obj.path_id:obj.read_typetree()['m_Name'] for obj in env.objects if obj.type.name=='GameObject'}
    transforms={names[obj.read_typetree()['m_GameObject']['m_PathID']]:obj for obj in env.objects if obj.type.name=='Transform'}
    return objects,transforms
before,old_transforms=records(source);after,new_transforms=records(output)
assert before.keys()==after.keys()
anchor=old_transforms['PartsA_Offset'].path_id;body=old_transforms['BreastSize'].path_id
old_position=old_transforms['PartsA_Offset'].read_typetree()['m_LocalPosition']
actual=new_transforms['PartsA_Offset'].read_typetree()['m_LocalPosition']
# Independent original fixture centroid C in identity Spine2 frame.
# Requested uniform2 gives local delta (2-1)*C, without planner/CLI reuse.
expected=(.01+.25166666666666665,.02+.013333333333333334,.02+.025)
for axis,value in zip('xyz',expected):
    assert math.isclose(actual[axis],value,abs_tol=2e-6),(axis,actual[axis],value)
    assert math.isclose(old_position[axis],{'x':.01,'y':.02,'z':.02}[axis],abs_tol=2e-7)
components=[key for key,obj in before.items() if obj.type.name=='MonoBehaviour' and 'scaleValues' in obj.read_typetree()]
assert len(components)==1;component=components[0]
old_settings=before[component].read_typetree();new_settings=after[component].read_typetree()
assert len(old_settings['scaleValues'])==len(new_settings['scaleValues'])==1
old_record,new_record=old_settings['scaleValues'][0],new_settings['scaleValues'][0]
assert old_record['target']['m_PathID']==new_record['target']['m_PathID']==body
assert all(math.isclose(old_record['scaledValue'][axis],1.5,abs_tol=1e-7) for axis in 'xyz')
assert all(math.isclose(new_record['scaledValue'][axis],2.,abs_tol=1e-7) for axis in 'xyz')
expected_settings=copy.deepcopy(old_settings)
expected_settings['scaleValues'][0]['scaledValue']=dict.fromkeys('xyz',2.)
assert new_settings==expected_settings
changed={key for key in before if before[key].get_raw_data()!=after[key].get_raw_data()}
assert changed=={anchor,component},changed
meshes=[key for key,obj in before.items() if obj.type.name=='Mesh']
textures=[key for key,obj in before.items() if obj.type.name=='Texture2D']
assert len(meshes)==len(textures)==1
assert all(before[key].get_raw_data()==after[key].get_raw_data() for key in meshes+textures)
assert source_path.read_bytes()==source
value={'status':'PASS','changedAnchors':1,'sourceAnchor':[old_position[axis] for axis in 'xyz'],
    'savedAnchor':[actual[axis] for axis in 'xyz'],'expectedAnchor':list(expected),
    'allMeshesAndTexturesByteIdentical':True,'otherRawObjectsByteIdentical':True,
    'meshObjects':len(meshes),'textureObjects':len(textures),'onlyChangedObjectIds':sorted(changed),
    'savedAbsoluteBodyScale':[2.,2.,2.],'private_prefix_samefile':True,
    'source_sha256':hashlib.sha256(source).hexdigest(),'output_sha256':hashlib.sha256(output).hexdigest(),
    'oracle':'Independent serialized fixture constants; no production planner or CLI result reuse'}
report.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
'''


def prepare_accessory_fixture(app, output):
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    helper = Path(__file__).resolve().parents[2] / "modtools/tests/test_model_accessory_unclip.py"
    fixture = output / "native-app-data/accessory-overlap.unity"
    report = output / "accessory-input.json"
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", ACCESSORY_FIXTURE,
                             str(resources / "python-app"), str(helper), str(fixture), str(report), str(prefix)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / "accessory-input.stdout.txt").write_text(result.stdout)
    (output / "accessory-input.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0 and report.is_file(), "Accessory input generation failed; see input logs")
    require(sha256(fixture) == ACCESSORY_FIXTURE_SHA, "Generated accessory fixture differs from audited geometry")
    return json.loads(report.read_text())


def inspect_accessory_export(app, output, label, report):
    observed = report.get("native_accessory_unclip", {})
    require(observed.get("status") == "PASS" and all(observed.get(key) is True for key in
                ("source_preserved", "derived_offset_excluded_from_edits", "recipe_flag_preserved"))
            and observed.get("saved_geometry_max_error", 1) < 2e-5,
            "Actual native accessory UI/HTTP/save/reopen assertions did not pass")
    source = Path(observed.get("source_path", ""))
    require(source == output / "native-app-data/accessory-overlap.unity" and sha256(source) == ACCESSORY_FIXTURE_SHA,
            "Native accessory smoke used an unexpected source")
    previews = observed.get("export", {}).get("previewPaths", [])
    require(len(previews) == 1 and Path(previews[0]).is_file(), "Native accessory export is missing")
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    receipt = output / f"{label}-accessory-oracle.json"
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", ACCESSORY_ORACLE,
                             str(prefix), str(source), previews[0], str(receipt)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / f"{label}-accessory-oracle.stdout.txt").write_text(result.stdout)
    (output / f"{label}-accessory-oracle.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0 and receipt.is_file(), "Native accessory serialized oracle failed; see oracle logs")
    observed["serialized_oracle"] = json.loads(receipt.read_text())


def prepare_game_physics_fixture(app, output):
    source = app / "Contents/Resources/qa/viewer_game_physics.unity"
    raw = source.read_bytes()
    require(len(raw) == 78128 and sha256(source) == GAME_PHYSICS_FIXTURE_SHA,
            "Packaged native game-physics fixture differs from its audited input")
    target = output / "native-app-data/game-physics.unity"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(raw)
    require(sha256(target) == GAME_PHYSICS_FIXTURE_SHA, "Native game-physics copy changed its source bytes")
    return {"status": "PASS_OWN_SERIALIZED_GAME_PHYSICS_INPUT", "fixture_sha256": GAME_PHYSICS_FIXTURE_SHA,
            "bytes": len(raw), "path": str(target),
            "scope": "Generated neutral serialized source; no game or user asset"}


def prepare_detail_extended_fixtures(app, output):
    records = {}
    for key, resource, name, digest, size in (
            ("detail", "viewer_persistence.unity", "detail-source.unity", DETAIL_FIXTURE_SHA, 72872),
            ("gaze", "viewer_gaze.unity", "gaze-source.unity", GAZE_FIXTURE_SHA, 87216),
            ("motion", "viewer_library_motion.unity", "library-motion.unity", LIBRARY_MOTION_SHA, 73488)):
        source = app / "Contents/Resources/qa" / resource
        raw = source.read_bytes()
        require(len(raw) == size and sha256(source) == digest, "A packaged extended QA input differs from its audited source: " + resource)
        target = output / "native-app-data" / name
        target.write_bytes(raw)
        require(sha256(target) == digest, "An extended QA input copy changed its source bytes")
        records[key] = {"resource": resource, "bytes": size, "sha256": digest, "path": str(target)}
    return {"status": "PASS_GENERATED_EXTENDED_INPUTS", "inputs": records,
            "scope": "Own neutral serialized QA inputs; no game or user models"}


def prepare_part_fixtures(app, output):
    records = {}
    for key, resource, name, digest in (
            ("target", "viewer_part_target.unity", "part-target.unity", PART_TARGET_SHA),
            ("donor", "viewer_part_donor.unity", "part-donor.unity", PART_DONOR_SHA)):
        source = app / "Contents/Resources/qa" / resource
        raw = source.read_bytes()
        require(len(raw) == 81847 and sha256(source) == digest, "The packaged neutral partial graft source changed: " + resource)
        target = output / "native-app-data" / name
        target.write_bytes(raw)
        require(sha256(target) == digest, "The copied neutral partial graft source changed")
        records[key] = {"resource": resource, "bytes": len(raw), "sha256": digest, "path": str(target)}
    return {"status": "PASS_ORIGINAL_NEUTRAL_PART_INPUTS", "inputs": records,
            "scope": "Own neutral serialized target/donor; no game or user models"}


def prepare_updater_fixtures(app, output):
    records = []
    root = output / "native-app-data/sukusta/native-thumbnail-inputs"
    for folder, name, digest, size, member in UPDATER_INPUTS:
        source = app / "Contents/Resources/qa" / name
        raw = source.read_bytes()
        require(len(raw) == size and sha256(source) == digest, "A packaged member-specific thumbnail updater ZIP changed: " + name)
        target = root / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        require(sha256(target) == digest, "A native updater ZIP copy changed")
        records.append({"resource": name, "path": str(target), "sha256": digest, "bytes": size, "character_id": member})
    return {"status": "PASS_ORIGINAL_NEUTRAL_MEMBER_ZIPS", "inputs": records,
            "scope": "Two own neutral legacy installer ZIPs in separate source folders; original comments/opaque payloads retained"}


def _native_checks(observed, names, label):
    checks = observed.get("checks", {})
    require(observed.get("status") == "PASS" and set(checks) == set(names)
            and all(checks[name] is True for name in names), label + " must pass its exact reviewed check inventory")


def _native_draw(observed, name="probe"):
    frame = observed[name]
    require(frame.get("ready") and frame.get("glError") == 0 and frame.get("nonBackgroundSamples", 0) >= 3,
            "Actual native WebGL must draw the inspected source")


def check_file_lists(files, model_paths, motion_paths):
    import math
    import re
    require(model_paths and files["modelPaths"] == model_paths and files["motionPaths"] == motion_paths
            and files["modelName"] == re.split(r"[\\/]", model_paths[0])[-1]
            and files["modelCount"] == files["modelBadge"] == len(model_paths)
            and files["modelCountHidden"] is (len(model_paths) < 2) and files["modelBadgeHidden"] is (len(model_paths) < 2),
            "Actual model header rows, name and counts must identify only the selected model files")
    require(files["motionCount"] == len(motion_paths) and files["motionHidden"] is (not motion_paths)
            and files["modelListOwned"] is True and files["motionListOwned"] is True
            and files["workspaceCount"] == len(model_paths) and files["workspaceCountHidden"] is (len(model_paths) < 2)
            and files["workspaceBadgePosition"] == "absolute",
            "Imported motions must have an independent accurate count/list inside Pose")
    require(files["badgePosition"] == "absolute" and all(math.isfinite(files[key]) and files[key] >= 0
                for key in ("modelHeaderHeight", "fileActionsHeight")), "Actual model badge and header geometry must remain outside extra flow rows")


def check_fresh_file_header(observed):
    require(observed.get("status") == "PASS" and observed["stateMotionPaths"] == [], "The native fresh header must start without imported motion rows")
    files, layout = observed["files"], observed["layout"]
    check_file_lists(files, observed["statePaths"], observed["stateMotionPaths"])
    require(layout["badgePosition"] == "absolute" and files["fileActionsHeight"] > 0
            and layout["viewport"]["width"] > 0 and layout["viewport"]["height"] > 0,
            "Actual native header controls must occupy measured layout with an absolute count badge")
    if files["compactEmbedded"]:
        require(layout["embeddedInOptions"] and layout["summaryDisplay"] == "none", "Compact model file rows must be embedded in model options")
    else:
        outer, name = layout["summary"], layout["name"]
        require(outer["width"] > 0 and outer["height"] >= 32 and name["width"] > 0 and name["left"] >= outer["left"] - 1 and name["right"] <= outer["right"] + 1
                and layout["nameOverflow"] == "hidden" and layout["nameWhiteSpace"] == "nowrap" and layout["nameTextOverflow"] == "ellipsis",
                "The actual native model filename must remain bounded with the intended overflow policy")


def check_updater_report(observed):
    _native_checks(observed, ("selectedFilesMode", "multipleFilesOnce", "sourcePathsPreserved", "actualToolRun", "twoAutomaticRenders",
                   "manifestRecipients", "qualityCameraTemplate", "previewReceipts", "twoCompletedOutputs", "viewerPreserved"), "Native existing-ZIP thumbnail updater")
    require(observed["before"] == observed["after"] and observed["expectedOwners"] == [6, 201]
            and not observed["before"]["pose"]["playing"] and observed["done"]["status"] == "done"
            and observed["request"]["mode"] == "multi" and observed["request"]["in_paths"] == "\n".join(observed["paths"])
            and observed["request"]["thumbnail_plan"],
            "Actual native updater must run one completed two-ZIP job and preserve the paused source viewer")
    selection = observed["selection"]
    require(selection["kind"] == "native-authorized-result-adapter" and selection["before"] == []
            and selection["after"] == observed["paths"] and len(selection["requests"]) == 1
            and selection["requests"][0]["action"] == "openFiles" and selection["requests"][0]["options"]["multiple"] is True,
            "Actual common native Add files must request multiple:true once and commit the two authorized ZIP paths once; OS dialog is not exercised")
    require(len(observed["receipts"]) == len(observed["renders"]) == len(observed["rendererState"]["receipts"]) == 2
            and not observed["rendererState"]["busy"] and observed["rendererState"]["last"]["count"] == observed["rendererState"]["last"]["total"] == 2,
            "Both source ZIPs must finish actual automatic WebGL renders and completed updater outputs")
    quality = {"renderer": "SifasMaterial", "highQuality": True, "animation": False, "supersample": 2}
    for index, owner in enumerate((6, 201)):
        result, rendered = observed["receipts"][index], observed["renders"][index]
        receipt, render = rendered["receipt"], rendered["render"]
        require(result["source_path"] == observed["paths"][index] and result["output_path"] != result["source_path"]
                and result["character_id"] == receipt["characterId"] == owner
                and result["thumbnail_sha256"] == receipt["sha256"] and result["cache_key"] == receipt["cacheKey"]
                and result["profile_digest"] == receipt["profileDigest"] and receipt["quality"] == quality
                and receipt == observed["rendererState"]["receipts"][index],
                "Each completed updater ZIP must bind its original source, manifest recipient and actual PNG/template/cache")
        require(render["quality"]["enabled"] is True and render["quality"]["ready"] is True and render["material"]["enabled"] is True
                and render["subjectPixels"] > 0 and render["triangles"] > 0 and render["visibleMeshes"] > 0
                and render["pose"] == "source-rest" and render["animation"] is False and render["camera"] == observed["profile"]["camera"]
                and rendered["preview"]["src"] == rendered["png"] and rendered["preview"]["sha256"] == receipt["sha256"],
                "Both real updater previews must contain source-rest SifasMaterial triangles under the SDK orthographic camera")
    require(observed["renders"][0]["receipt"]["sha256"] != observed["renders"][1]["receipt"]["sha256"]
            and observed["renders"][0]["receipt"]["cacheKey"] != observed["renders"][1]["receipt"]["cacheKey"],
            "Different source ZIPs and two genuine manifest recipients must produce distinct actual PNGs and bindings")


def inspect_updater_export(app, output, label, report):
    observed = report.get("native_thumbnail_updater", {})
    check_updater_report(observed)
    root = output / "native-app-data/sukusta/native-thumbnail-inputs"
    expected = [str(root / folder / name) for folder, name, _, _, _ in UPDATER_INPUTS]
    require(observed["paths"] == expected and observed.get("sourcePreserved") is True
            and observed["source_sha256"] == [digest for _, _, digest, _, _ in UPDATER_INPUTS]
            and all(sha256(Path(path)) == record[2] for path, record in zip(expected, UPDATER_INPUTS)),
            "Actual native updater must preserve the two independently pinned member ZIPs in separate source folders")
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    spec = output / f"{label}-thumbnail-updater-spec.json"
    write_json(spec, observed)
    code = """import pathlib,runpy,sys
spec,resources=(pathlib.Path(value) for value in sys.argv[1:])
assert pathlib.Path(sys.prefix).samefile(resources/'runtime/arm64/python')
oracle=runpy.run_path(str(resources/'qa/viewer_thumbnail_updater_oracle.py'))
print(oracle['inspect_json'](spec.read_text(),str(resources/'python-app/webtools/web/static/thumbnail-sdk')))
"""
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", code, str(spec), str(resources)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / f"{label}-thumbnail-updater-oracle.stdout.txt").write_text(result.stdout)
    (output / f"{label}-thumbnail-updater-oracle.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0, "Actual updated installer ZIPs failed the independent private-runtime preservation/PNG/member/cache oracle")
    oracle = json.loads(result.stdout)
    require(oracle["status"] == "PASS" and len(oracle["outputs"]) == 2
            and all(row["original_zip_unchanged"] and row["all_original_payloads_preserved"]
                    and row["manifest_only_thumbnail_literal_changed"] and row["zip_comment_exact"]
                    and row["actual_zip_preview_png_byte_identical"] and row["source_member_template_quality_bound"] for row in oracle["outputs"]),
            "Each actual ZIP must preserve originals, payloads/comment and manifest bytes except the thumbnail literal while binding the exact new PNG")
    for row in oracle["outputs"]:
        actual = Path(row["output_path"])
        copied = output / f"{label}-thumbnail-updated-{row['character_id']}.zip"
        require(sha256(actual) == row["output_sha256"], "The actual updater output changed after its independent inspection")
        shutil.copy2(actual, copied)
        require(sha256(copied) == row["output_sha256"], "The downloadable actual updater ZIP copy changed")
        row["evidence_zip"] = str(copied)
    write_json(output / f"{label}-thumbnail-updater-oracle.json", oracle)
    observed["serialized_oracle"] = oracle
    require((output / "native-app-data/thumbnail-updater-controls.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Native existing-ZIP updater PNG is missing")


def check_thumbnail_report(observed):
    import math
    _native_checks(observed, ("modeControl", "restoredEdits", "freshSave", "sdkCameraTemplate", "highQuality3D",
                   "sourceRestPose", "previewReceipt", "packageThumbnail", "sourceStatePreserved", "noInstallRequested"), "Native automatic 3D thumbnail")
    before, after, receipt, render = (observed[key] for key in ("before", "after", "receipt", "render"))
    require(before == after and before["authoring"]["edits"] and before["sourceFingerprint"]
            and not before["pose"]["playing"] and before["characterId"] == 6,
            "Native automatic thumbnail saving must preserve the source, authored body and paused preview")
    require(observed["options"] == {"characterId": 6, "reeditOriginal": True}
            and observed["persistence"]["thumbnailMode"] == "3d" and observed["jobId"] != observed["previousJob"]
            and not observed["persistence"]["busy"] and observed["persistence"]["status"] == "done",
            "Actual 3D selection must save a new completed installer job after ordinary texture packaging")
    quality = {"renderer": "SifasMaterial", "highQuality": True, "animation": False, "supersample": 2}
    require(receipt["quality"] == quality and render["quality"]["enabled"] is True and render["quality"]["ready"] is True
            and math.isfinite(render["quality"]["actualSamples"]) and render["quality"]["actualSamples"] >= 0
            and render["material"]["enabled"] is True and render["subjectPixels"] > 0 and render["triangles"] > 0
            and render["visibleMeshes"] > 0 and render["pose"] == "source-rest" and render["animation"] is False,
            "Actual WKWebView high-quality source-rest rendering must expose visible SifasMaterial costume triangles")
    pack = observed["response"]["mod_package"]
    require(pack["installable"] is True and pack["character_id"] == receipt["characterId"] == 6
            and pack["thumbnail"]["mode"] == "3d" and pack["thumbnail"]["sha256"] == receipt["sha256"]
            and pack["thumbnail"]["quality"] == quality and pack["thumbnail"]["cacheKey"] == receipt["cacheKey"]
            and pack["thumbnail"]["profileDigest"] == receipt["profileDigest"]
            and observed["preview"]["sha256"] == receipt["sha256"]
            and observed["preview"]["width"] == observed["preview"]["height"] == receipt["size"]
            and 64 <= receipt["size"] <= 1024,
            "The actual preview and authoritative ZIP must identify the same size, PNG, owner and source-bound render")
    require(observed["installRequestsBefore"] == observed["installRequestsAfter"]
            and not observed["response"].get("installed"), "Automatic thumbnail Save must not install a mod")
    _native_draw(observed)


def check_part_report(observed):
    import math
    _native_checks(observed, ("fullHierarchy", "multipleRoots", "exactChildExclusion", "boneSelectionUndoRedo",
                   "trustedModelBonePick", "trustedModelFacePick", "trustedUVPaintErase", "faceSelectionUndoRedo",
                   "sourceBoundSubmission", "actualGraftReopened", "actualGraftUndoRedo", "donorAndTargetRendered"), "Native partial graft controls")
    selected = observed["selected"]
    require(selected["selectedFaces"] == selected["highlightedFaces"] == [0, 5, 19]
            and observed["request"]["triangleIndices"] == [0, 5, 19]
            and observed["request"]["partSelectionMode"] == "triangles"
            and observed["request"]["donorSha256"] == observed["inspected"]["donorSha256"]
            and observed["request"]["donorSelectionFingerprint"] == observed["inspected"]["donorSelectionFingerprint"]
            and observed["request"]["donorRenderer"] == observed["inspected"]["donorRenderer"]
            and observed["request"]["donorMesh"] == observed["inspected"]["donorMesh"],
            "Actual partial graft must submit the exact original donor mesh/renderer/material fingerprint and source faces")
    require(observed["original"]["stats"]["vertices"] == 60 and observed["original"]["stats"]["triangles"] == 20
            and observed["saved"]["stats"]["triangles"] == observed["final"]["stats"]["triangles"] == 23
            and observed["saved"]["loadedPaths"] == observed["final"]["loadedPaths"] == [observed["outputPath"]],
            "Actual saved graft and Redo must reopen exactly the three added source triangles")
    pointers = [observed["bonePointer"], observed["scenePointer"], *observed["texturePointers"]]
    events = observed["nativeEvents"]
    require(len(pointers) == len(events) == 6 and len({row["id"] for row in events}) == 6,
            "Actual native partial selection must send exactly six distinct native pointer strokes")
    for pointer, native in zip(pointers, events):
        request, event = pointer["request"], pointer["event"]
        require(event["trusted"] is True and event["pointerType"] == "mouse" and request["id"] == native["id"]
                and request["target"] == native["target"] and native["method"].startswith("NSApplication.postEvent NSEvent")
                and all(math.isfinite(event[key]) and abs(event[key] - request["point"][axis]) <= 1.1
                        for key, axis in (("clientX", "x"), ("clientY", "y"))),
                "Each actual WebKit donor pointer must be trusted and land on its measured source triangle/UV point")
    donor = observed["donorProbe"]
    require(donor["glError"] == 0 and donor["nonBackgroundSamples"] > 0 and donor["width"] > 0 and donor["height"] > 0,
            "Actual donor WebGL must visibly draw original source triangles")
    _native_draw(observed, "finalProbe")


def preserve_native_output_evidence(output, label, report):
    """Retain only this neutral QA flow's outputs before independent oracles."""
    library = (output / "native-app-data/sukusta").resolve()
    paths = [(f"thumbnail-{index}", path) for index, path in enumerate(
        report["native_thumbnail"]["response"]["output_paths"])]
    paths.append(("part-result", report["native_part_selection"]["outputPath"]))
    for index, receipt in enumerate(report["native_thumbnail_updater"]["receipts"]):
        paths.extend(((f"updater-source-{index}", receipt["source_path"]),
                      (f"updater-output-{index}", receipt["output_path"])))
    copied = []
    for name, value in paths:
        source = Path(value).resolve()
        require(source.is_relative_to(library) and source.is_file()
                and source.suffix.lower() in (".zip", ".json", ".unity"),
                "Raw QA output must be an existing neutral fixture result inside its test library")
        destination = output / (label + "-raw-" + name + source.suffix)
        expected = sha256(source)
        shutil.copy2(source, destination)
        require(sha256(destination) == sha256(source) == expected,
                "The preserved raw QA output must match the actual native result")
        copied.append({"source": str(source), "evidence": str(destination),
                       "sha256": expected, "bytes": destination.stat().st_size})
    write_json(output / (label + "-raw-output-manifest.json"), copied)


def inspect_thumbnail_export(app, output, label, report):
    observed = report.get("native_thumbnail", {})
    check_thumbnail_report(observed)
    require(observed.get("sourcePreserved") is True and Path(observed["source_path"]).samefile(output / "native-app-data/분수 의상.zip")
            and sha256(Path(observed["source_path"])) == observed["source_sha256"], "The native automatic thumbnail must preserve its actual original ZIP")
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    spec = output / f"{label}-thumbnail-spec.json"
    receipt = output / f"{label}-thumbnail-oracle.json"
    write_json(spec, observed)
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", THUMBNAIL_ORACLE,
                             str(spec), str(resources), str(receipt)], env=private_environment(resources), cwd=output,
                            capture_output=True, text=True, timeout=60)
    (output / f"{label}-thumbnail-oracle.stdout.txt").write_text(result.stdout)
    (output / f"{label}-thumbnail-oracle.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0 and receipt.is_file(), "Actual ZIP thumbnail failed the independent private-runtime PNG/source/template binding oracle")
    oracle = json.loads(receipt.read_text())
    require(oracle["status"] == "PASS" and oracle["actual_zip_preview_png_byte_identical"]
            and oracle["profile_assets_independently_hashed"] and oracle["normalized_state_sources_member_template_quality_bound"],
            "Actual PNG bytes, saved model, source hashes and source/state/member/template/quality binding must match")
    observed["serialized_oracle"] = oracle
    require((output / "native-app-data/thumbnail-controls.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Native 3D thumbnail PNG is missing")


def inspect_part_export(app, output, label, report):
    observed = report.get("native_part_selection", {})
    check_part_report(observed)
    paths = {"sourcePath": str(output / "native-app-data/part-target.unity"),
             "donorPath": str(output / "native-app-data/part-donor.unity")}
    require(observed["paths"] == paths and observed.get("sourcePreserved") is True
            and observed["source_path"] == paths["sourcePath"] and observed["donor_path"] == paths["donorPath"]
            and observed["source_sha256"] == sha256(Path(paths["sourcePath"])) == PART_TARGET_SHA
            and observed["donor_sha256"] == sha256(Path(paths["donorPath"])) == PART_DONOR_SHA,
            "Actual native partial graft must preserve the exact independently pinned target and donor files")
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    spec = output / f"{label}-part-spec.json"
    write_json(spec, observed)
    code = """import pathlib,runpy,sys
spec,resources=(pathlib.Path(value) for value in sys.argv[1:])
assert pathlib.Path(sys.prefix).samefile(resources/'runtime/arm64/python')
oracle=runpy.run_path(str(resources/'qa/viewer_part_oracle.py'))
print(oracle['inspect_json'](spec.read_text()))
"""
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", code, str(spec), str(resources)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / f"{label}-part-oracle.stdout.txt").write_text(result.stdout)
    (output / f"{label}-part-oracle.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0, "Actual native saved partial graft failed the independent private-runtime serialized mesh oracle")
    oracle = json.loads(result.stdout)
    require(oracle["status"] == "PASS" and oracle["sourcePreserved"] and oracle["donorPreserved"]
            and oracle["selectedOriginalFaces"] == [0, 5, 19] and oracle["outputVertices"] == 69 and oracle["outputTriangles"] == 23
            and oracle["targetVerticesPreserved"] == 60 and oracle["unrelatedTargetObjectsExact"] == 49
            and oracle["donorUVColorAndSkinExact"] and oracle["originalBindPosesExact"] and oracle["allLocalPPtrsResolve"]
            and oracle["donorTexturesExact"] and oracle["maximumDonorPositionNormalError"] < .00002,
            "Actual serialized partial graft must preserve every target channel and exactly add the selected donor faces/UV/color/skin")
    actual = Path(observed["outputPath"])
    copied = output / f"{label}-part-result.unity"
    require(sha256(actual) == oracle["outputSha256"], "The actual partial graft changed after its independent inspection")
    shutil.copy2(actual, copied)
    require(sha256(copied) == oracle["outputSha256"], "The downloadable actual partial-graft copy changed")
    oracle["evidence_model"] = str(copied)
    write_json(output / f"{label}-part-oracle.json", oracle)
    observed["serialized_oracle"] = oracle
    require((output / "native-app-data/part-selection-controls.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Native partial-selection PNG is missing")


def check_detail_report(observed):
    _native_checks(observed, ("mouthCentroidDepth", "absoluteOutline", "sparseOutline", "outlineUndoRedo", "sourceCataloguePreserved", "outlineSave",
                   "meshZoom", "connectedSelection", "selectionUndoRedo", "viewOnlyPreservedGeometry"), "Native detail controls")
    absolute = [{"id": "0:0:1", "factor": 1, "absolute": 37}]
    require(observed["absolute"] == absolute and observed["absoluteRecipe"]["state"]["outlines"] == absolute
            and observed["absoluteRecipe"]["state"]["edits"] == [], "Native absolute Save must retain compact native red37 for all source vertices")
    sparse = [{"id": "0:0:1", "factor": 1, "vertices": [{"vertex": 0, "value": .25}]}]
    require(observed["sparse"] == sparse and observed["recipe"]["state"]["outlines"] == sparse
            and observed["recipe"]["state"]["edits"] == [] and len(observed["catalogue"]["meshes"]) == 1,
            "Native detail Save must retain the exact source vertex0 quarter-width recipe")
    require(observed["seed"]["selectedVertices"] == [0] and sorted(observed["connected"]["selectedVertices"]) == list(range(6))
            and observed["undone"]["selectedVertices"] == [0], "Native connected selection and Undo must use the actual six source vertices")
    require(not observed["connected"]["edits"]["meshes"] and not observed["finalAuthoring"]["edits"]
            and not observed["finalAuthoring"].get("outlines"), "Inspection and reset must not leave geometry or body edits")
    views = {row["panel"]: row for row in observed["independentViews"]}
    modify, delete = views["viewer-mesh-modify"], views["viewer-mesh-deleter"]
    require(modify["zoom"] == 4 and modify["x"] == modify["y"] == -1.5 and delete["zoom"] == 2,
            "Actual mesh inspectors must retain independent centre-anchored UV views")
    gpu = observed["mouthGpu"]
    require(gpu["status"] == "PASS" and gpu["backendAdaptation"] is True and gpu["originalGameShaderParityEstablished"] is False
        and gpu["fallbackUnchanged"] is True and gpu["viewport"] == [64, 64]
        and gpu["targetPixelTopLeft"] == [32, 32], "Actual native Mouth GPU evidence is incomplete")
    modes = {row["name"]: row for row in gpu["results"]}
    require(set(modes) == {"webgl2-mouth", "webgl2-original", "webgl1-mouth", "webgl1-original"},
        "Native GPU must exercise Mouth and untagged original controls in both actual context versions")
    for name, row in modes.items():
        require(row["actualWebGL2"] is name.startswith("webgl2") and row["samples"] == 4 and row["depthBits"] == 24
            and row["vertices"] == 6 and row["triangles"] == 2 and len(row["observations"]) == 6
            and row["centroidCompiled"] is (name == "webgl2-mouth"),
            "Only the actual WebGL2 Mouth MAIN may compile centroid depth; original/fallback data must remain unchanged")
        for item in row["observations"]:
            require(item["glError"] == 0, "Native centroid/original GPU program must compile without GL errors")
            if name == "webgl2-mouth":
                require(item["compiledMain"] and all(program["version"].startswith("#version 300 es") and program["linked"] is True
                    for program in item["compiledMain"]), "The actual Mouth WebGL2 GLSL300 MAIN must link on the native GPU")
                require(item["rgba"] == ([0, 0, 255, 255] if item["occluder"] == "front" else [255, 0, 0, 255]),
                    "Actual production Mouth shader must preserve opaque front/rear occlusion in both draw orders")
    require(modes["webgl1-mouth"]["observations"] == modes["webgl1-original"]["observations"],
        "Actual WebGL1 Mouth fallback must preserve the original program's complete framebuffer results")
    outline = {row["name"]: row for row in gpu["outlineResults"]}
    require(set(outline) == set(modes) and gpu["outlineFallbackUnchanged"] is True,
        "Actual native GPU must also exercise all four original/marked BackSide OUTLINE paths")
    for name, row in outline.items():
        adapted = name == "webgl2-mouth"
        require(row["actualWebGL2"] is name.startswith("webgl2") and row["samples"] == 4 and row["depthBits"] == 24
            and row["vertices"] == 6 and row["triangles"] == 2 and row["side"] == "BackSide"
            and all(row[key] is True for key in ("depthTest", "depthWrite", "stencilAlways", "mainHidden"))
            and row["nativeVertexColor"] == [0, 1, 1, 1] and row["centroidCompiled"] is adapted
            and (adapted or row["originalProgramUnchanged"] is True) and len(row["observations"]) == 6,
            "Mouth OUTLINE adaptation must retain native geometry, width/color, BackSide, depth and stencil behavior")
        reference = row["frontReferenceRGBA"]
        require(len(reference) == 4 and reference[0] > 0 and reference[1:] == [0, 0, 255],
            "OUTLINE reference must be a real nonblack red pixel from the independently authored front triangle")
        for item in row["observations"]:
            require(item["glError"] == 0 and item["compiledOutline"] and all(program["linked"] is True
                and program["outlinePass"] is True and program["centroidDepth"] is adapted
                and (not adapted or program["version"].startswith("#version 300 es"))
                for program in item["compiledOutline"]), "Actual native OUTLINE programs must compile in the correct scope")
            if adapted:
                require(item["rgba"] == ([0, 0, 255, 255] if item["occluder"] == "front" else reference),
                    "Actual Mouth OUTLINE must preserve the full front reference and independent opaque occlusion in both orders")
    require(outline["webgl1-mouth"]["observations"] == outline["webgl1-original"]["observations"]
        and outline["webgl1-mouth"]["frontReferenceRGBA"] == outline["webgl1-original"]["frontReferenceRGBA"],
        "Actual WebGL1 OUTLINE fallback must preserve original output")
    color = observed["uvColor"]
    require(color["chosen"] == "#14b87a" and color["restored"] == color["before"] == color["persisted"]
        and color["authoringPreserved"] is True and color["viewsPreserved"] is True,
        "UV overlay color must synchronize/persist independently of source textures and mesh edits")
    _native_draw(observed)


def inspect_detail_export(app, output, label, report):
    observed = report.get("native_detail", {})
    check_detail_report(observed)
    source = Path(observed.get("source_path", ""))
    require(observed.get("sourcePreserved") is True and source == output / "native-app-data/detail-source.unity"
            and observed.get("source_sha256") == DETAIL_FIXTURE_SHA and sha256(source) == DETAIL_FIXTURE_SHA,
            "Native detail inspection must preserve the exact clean source")
    saved = observed["saved"]
    require(saved["status"] == "done" and not saved["busy"] and not saved["error"]
            and len(saved["previewPaths"]) == 1, "Native sparse outline export must publish one completed source copy")
    recipe = Path(saved["recipePath"])
    require(json.loads(recipe.read_text()) == observed["recipe"], "Fetched outline recipe must equal the actual saved file")
    resources = app / "Contents/Resources"
    prefix = resources / "runtime/arm64/python"
    receipt = output / f"{label}-detail-oracle.json"
    result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", DETAIL_OUTLINE_ORACLE,
                             str(source), saved["previewPaths"][0], str(recipe), str(receipt), str(prefix)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / f"{label}-detail-oracle.stdout.txt").write_text(result.stdout)
    (output / f"{label}-detail-oracle.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0 and receipt.is_file(), "Actual saved outline bytes failed the independent private-runtime oracle")
    oracle = json.loads(receipt.read_text())
    require(oracle["status"] == "PASS" and oracle["onlyChangedObjectIds"] == [1]
            and oracle["allOtherRawObjectsByteIdentical"] and oracle["allNonRedMeshDataByteIdentical"],
            "Actual sparse outline Save must change only one native red byte")
    observed["serialized_oracle"] = oracle
    absolute = observed["absoluteSaved"]
    absolute_recipe = Path(absolute["recipePath"])
    require(json.loads(absolute_recipe.read_text()) == observed["absoluteRecipe"], "Absolute recipe must equal the actual saved file")
    absolute_receipt = output / f"{label}-absolute-outline-oracle.json"
    absolute_result = subprocess.run([str(prefix / "bin/python3"), "-I", "-B", "-c", DETAIL_OUTLINE_ORACLE,
        str(source), absolute["previewPaths"][0], str(absolute_recipe), str(absolute_receipt), str(prefix), "--absolute"],
        env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / f"{label}-absolute-outline.stdout.txt").write_text(absolute_result.stdout)
    (output / f"{label}-absolute-outline.stderr.txt").write_text(absolute_result.stderr)
    require(absolute_result.returncode == 0 and absolute_receipt.is_file(), "Native absolute red37 Save failed independent raw-byte verification")
    absolute_oracle = json.loads(absolute_receipt.read_text())
    require(absolute_oracle["status"] == "PASS" and absolute_oracle["recipeExactAbsoluteOutlineOnly"]
        and absolute_oracle["mesh"]["changedVertices"] == list(range(6))
        and absolute_oracle["mesh"]["rgbaAfter"] == [[37, 255, 0, 255]] * 6
        and absolute_oracle["allOtherRawObjectsByteIdentical"] and absolute_oracle["allNonRedMeshDataByteIdentical"],
        "Absolute width must change exactly six native red bytes while preserving every other object/channel")
    observed["absolute_serialized_oracle"] = absolute_oracle
    require((output / "native-app-data/detail-controls.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Native detail PNG is missing")


def check_extended_report(observed, paths):
    import math
    import re
    _native_checks(observed, ("physicsFreshOn", "gazeOriginalPoses", "gazePausedAndReset", "poseComponentFilters",
                   "breastAutomaticLimits", "breastDisableRestoresBaseline", "precisePhysicsEditing", "motionSourceSeparation",
                   "motionReloadPreservesEdits", "importedMotionPlays", "modelChangeRetainsLibrary", "explicitClear"), "Extended native controls")
    ui_checks = observed.get("uiChecks", {})
    expected_ui = {"accessoryFreshOpen", "modelOnlyHeader", "motionOnlyPoseList", "modelHeaderUnchangedOnMotionImport",
                   "modelHeaderTracksBodyChange", "modelHeaderRestored", "motionListCleared", "multipleModelCounts"}
    require(set(ui_checks) == expected_ui and all(ui_checks[key] is True for key in expected_ui)
            and observed["freshDefaults"]["accessoryOpen"] is True,
            "Actual fresh accessory, source counts and model/motion UI checks must retain the eight reviewed assertions")
    for key in ("initial", "beforeLibrary", "imported", "played", "other", "rebound", "cleared", "multiple", "final"):
        snapshot = observed[key]
        check_file_lists(snapshot["files"], snapshot["state"]["paths"], snapshot["state"]["motionLibraryPaths"])
    before_files, imported_files = observed["beforeLibrary"]["files"], observed["imported"]["files"]
    require(before_files["modelPaths"] == imported_files["modelPaths"] and before_files["modelName"] == imported_files["modelName"]
            and before_files["modelHeaderHeight"] == imported_files["modelHeaderHeight"]
            and before_files["fileActionsHeight"] == imported_files["fileActionsHeight"],
            "Importing motion must preserve the actual model header and its measured height")
    initial = observed["initial"]["state"]
    require(initial["stats"]["meshes"] == 1 and initial["stats"]["vertices"] == 6 and initial["stats"]["triangles"] == 4
            and initial["rig"]["expressions"] == [] and initial["rig"]["physics"]["swingBone"]
            and initial["rig"]["physics"]["swingCollider"], "Fresh gaze source must retain its neutral mesh and enabled physics")
    def eyes(state):
        rows = [{key: row[key] for key in ("node", "position", "quaternion", "scale")}
                for row in state["rig"]["bones"] if re.search(r"(?:^|/)(?:Left|Right)Eye[12]$", row["name"])]
        require(len(rows) == 4 and all(math.isfinite(value) for row in rows for key in ("position", "quaternion", "scale") for value in row[key]),
                "Four genuine source eye joints must expose finite actual transforms")
        return rows
    front, directed, returned, camera = (observed["gaze"][name] for name in ("front", "directed", "returned", "camera"))
    require(eyes(front) != eyes(directed) and eyes(front) == eyes(returned)
            and front["rig"]["time"] == directed["rig"]["time"] and not directed["rig"]["playing"],
            "Paused source gaze must change actual eye transforms and restore them exactly")
    gaze = directed["rig"]["expressionPanel"]["gaze"]
    require(gaze["available"] and gaze["mode"] == "direction" and gaze["horizontal"] == .5 and gaze["vertical"] == -.25
            and gaze["strength"] == .7 and camera["rig"]["expressionPanel"]["gaze"]["mode"] == "camera",
            "Real source gaze controls must retain their exact numeric and camera settings")
    owner = observed["gaze"]["owner"]
    folds = observed["gaze"]["folds"]
    require(owner == {"pose": True, "expression": False, "body": False, "host": True}
            and len(folds) == 2 and [row["open"] for row in folds] == [False, True],
            "Actual gaze controls must belong only to Pose and its real summary must close then reopen")
    for row in folds:
        require(row["owner"] == owner and row["gaze"] == gaze and row["eyes"] == eyes(directed)
                and row["time"] == directed["rig"]["time"] and row["playing"] == directed["rig"]["playing"]
                and row["authoring"] == observed["gaze"]["foldAuthoring"]
                and all(row["summary"][key] is True for key in ("visible", "withinViewport", "hittable")),
                "Pose folding must preserve exact source eye transforms, gaze, paused time and all authoring")
    breast = observed["breast"]
    record, base, preset, limits = (breast[name] for name in ("record", "baseline", "preset", "limits"))
    require(record["kind"] == "bone" and record["group"] == "breast" and preset["tier"] > 0,
            "Pose filters and automatic limits must use the genuine breast SwingBone")
    automatic = breast["automatic"]["state"]["rig"]["physics"]["breastAutoLimits"]
    tiers = [row for row in automatic["tiers"] if row["id"] == record["id"]]
    require(automatic["enabled"] and len(tiers) == 1 and tiers[0]["applied"] and tiers[0]["tier"] == preset["tier"],
            "Actual original size recommendations must apply the selected tier once")
    require(all(limits[key][0] == base[key][0] for key in ("lowRotationLimit", "highRotationLimit"))
            and all(limits["lowRotationLimit"][axis] == base["lowRotationLimit"][axis] - preset["tier"]
                    and limits["highRotationLimit"][axis] == base["highRotationLimit"][axis] + preset["tier"] for axis in (1, 2)),
            "Breast automatic limits must preserve X and expand Y/Z exactly from the enabled baseline")
    before, imported = observed["beforeLibrary"], observed["imported"]
    physics_edits = [row for row in before["authoring"]["physics"] if row["id"] == record["id"]]
    require(not before["state"]["rig"]["physics"]["breastAutoLimits"]["enabled"] and len(physics_edits) == 1
            and physics_edits[0]["values"] == {"dragForce": .4}, "Disabling auto limits must leave only the precise manually authored drag")
    require(observed["paths"] == paths and imported["state"]["paths"] == imported["state"]["loadedPaths"] == [paths["sourcePath"]]
            and imported["state"]["motionLibraryPaths"] == imported["state"]["loadedMotionPaths"] == [paths["motionPath"]]
            and imported["authoring"] == before["authoring"]
            and imported["state"]["rig"]["expressionPanel"]["gaze"] == before["state"]["rig"]["expressionPanel"]["gaze"],
            "Motion import must remain separate from model sources and preserve same-body edits/manual gaze")
    played = observed["played"]["state"]["rig"]
    require(played["selectedClip"] == "Native library motion" and played["time"] > .2 and not played["playing"],
            "The actual imported motion must really advance and pause")
    other, rebound, cleared = (observed[name]["state"] for name in ("other", "rebound", "cleared"))
    require(other["paths"] == other["loadedPaths"] == [paths["otherBodyPath"]] and other["stats"]["meshes"] == 1
            and other["motionLibraryPaths"] == [paths["motionPath"]] and "Native library motion" in other["rig"]["clipNames"]
            and rebound["loadedMotionPaths"] == [paths["motionPath"]] and rebound["rig"]["expressionPanel"]["gaze"]["available"],
            "Changing and returning the body must retain and rebind the real motion bank")
    require(cleared["paths"] == [paths["sourcePath"]] and not cleared["motionLibraryPaths"] and not cleared["loadedMotionPaths"]
            and "Native library motion" not in cleared["rig"]["clipNames"], "Explicit clear must remove only the imported motion library")
    multiple, final = observed["multiple"]["state"], observed["final"]["state"]
    require(multiple["paths"] == multiple["loadedPaths"] == [paths["sourcePath"], paths["otherBodyPath"]]
            and not multiple["motionLibraryPaths"] and not multiple["loadedMotionPaths"]
            and final["paths"] == final["loadedPaths"] == [paths["sourcePath"]] and not final["motionLibraryPaths"],
            "Actual two-model selection must update all three model counts and restore one model without imported motions")
    _native_draw(observed)


def inspect_extended_workflow(output, report):
    observed = report.get("native_extended", {})
    paths = {"sourcePath": str(output / "native-app-data/gaze-source.unity"),
             "motionPath": str(output / "native-app-data/library-motion.unity"),
             "otherBodyPath": str(output / "native-app-data/game-physics.unity")}
    check_extended_report(observed, paths)
    require(observed.get("sourcePreserved") is True and all(sha256(Path(paths[key])) == digest for key, digest in
                (("sourcePath", GAZE_FIXTURE_SHA), ("motionPath", LIBRARY_MOTION_SHA), ("otherBodyPath", GAME_PHYSICS_FIXTURE_SHA))),
            "Extended native source, motion bank and other-body bytes must remain original")
    require((output / "native-app-data/extended-controls.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Extended native PNG is missing")


def check_game_physics_report(output, report):
    import math
    observed = report.get("native_game_physics", {})
    require(observed.get("status") == "PASS" and observed.get("source_preserved") is True
            and observed.get("sourcePreserved") is True and observed.get("sourceCataloguePreserved") is True,
            "Native game-physics source and catalogue preservation must pass")
    checks = observed.get("checks", {})
    require(all(checks.get(key) is True for key in ("nativeDefault", "singleJobAdvanced", "groupJobAdvanced",
                "pausedDebugPreserved", "seekPreservedParameters", "modeSwitchPreservedParameters", "frameRateRestored30")),
            "All seven actual game-physics lifecycle checks must pass")
    source = Path(observed.get("source_path", ""))
    require(source == output / "native-app-data/game-physics.unity"
            and observed.get("source_sha256") == GAME_PHYSICS_FIXTURE_SHA and sha256(source) == GAME_PHYSICS_FIXTURE_SHA,
            "Native game-physics smoke must bind the exact preserved input")
    initial = observed["initial"]
    require(initial["physics"]["mode"] == "game" and initial["physics"]["frameRate"] == 0
            and initial["controls"]["frameRate"] == "0"
            and initial["physics"]["nativeAvailable"] and not initial["physics"]["nativeMissing"]
            and initial["physics"]["swingBone"] and initial["physics"]["swingCollider"],
            "Complete source inputs must select the original game engine and display refresh cadence")
    for key, job in (("single", "SwingBoneJob"), ("group", "SwingBoneGroupJob")):
        before, after = observed[key]["before"], observed[key]["after"]
        a, b = before["physics"]["solver"], after["physics"]["solver"]
        require(not after["playing"] and a["runtimeProfile"]["job"] == b["runtimeProfile"]["job"] == job
                and b["initialized"] and b["available"] and not b["unsupported"]
                and b["totalNativeSteps"] >= a["totalNativeSteps"] + 3,
                "Actual Play must execute the requested original job")
        require(len(a["bones"]) == len(b["bones"]) > 0, "Original job bone topology must remain stable")
        require(all(len(bone[field]) == 3 and all(math.isfinite(value) for value in bone[field])
                    for bone in b["bones"] for field in ("origin", "tip")), "Actual job vectors must remain finite")
        require(any(abs(left["tip"][axis] - right["tip"][axis]) > 1e-7
                    for left, right in zip(a["bones"], b["bones"]) for axis in range(3)),
                "Actual original-job tip outputs must change while playing")
    paused = observed["paused"]["before"]
    for key in ("debugOn", "held", "debugOff"):
        current = observed["paused"][key]
        require(not current["playing"] and current["time"] == paused["time"]
                and current["bones"] == paused["bones"]
                and current["physics"]["solver"]["bones"] == paused["physics"]["solver"]["bones"],
                "Paused debug toggles must preserve time and actual rig/solver poses")
        require(all(current["physics"]["solver"][field] == paused["physics"]["solver"][field]
                    for field in ("totalNativeSteps", "resets", "initializationGeneration", "dynamicGeneration")),
                "Paused debug toggles must preserve actual native state generations")
    authored, seeked = observed["seek"]["before"], observed["seek"]["after"]
    edits = authored["authoring"]["physics"]
    require(len(edits) == 1 and edits[0]["values"]["dragForce"] == .4
            and seeked["authoring"]["physics"] == edits and seeked["catalogue"] == initial["catalogue"]
            and abs(seeked["time"] - .75) < 1e-7 and not seeked["playing"],
            "Seeking must preserve the actual original catalogue and precise parameter edits")
    enhanced, restored = observed["enhanced"], observed["restored"]
    require(enhanced["physics"]["mode"] == "enhanced" and enhanced["controls"]["frameDisabled"]
            and enhanced["controls"]["profileDisabled"] and enhanced["authoring"]["physics"] == edits
            and restored["physics"]["mode"] == "game" and restored["physics"]["frameRate"] == 30
            and not restored["controls"]["frameDisabled"] and restored["authoring"]["physics"] == edits,
            "Switching additional correction/original mode must preserve edits and game cadence")
    frame = observed["framebuffer"]
    require(frame["ready"] and frame["glError"] == 0 and frame["nonBackgroundSamples"] >= 3,
            "Actual WKWebView must still render the game-physics model")
    require((output / "native-app-data/game-physics.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"),
            "Actual native game-physics screenshot is missing")


def prepare_zip_fixture(app, output):
    """Make one real ZIP input using the shipped interpreter, outside the app."""
    directory = output / "native-app-data"
    directory.mkdir(exist_ok=True)
    resources = app / "Contents/Resources"
    source = resources / "qa/viewer_persistence.unity"
    expected = sha256(source)
    fixture = directory / "분수 의상.zip"
    report = output / "fractional-zip-input.json"
    python = resources / "runtime/arm64/python/bin/python3"
    result = subprocess.run([str(python), "-I", "-B", "-c", ZIP_FIXTURE, str(source), str(fixture), str(report)],
                            env=private_environment(resources), cwd=output, capture_output=True, text=True, timeout=60)
    (output / "fractional-zip-input.stdout.txt").write_text(result.stdout)
    (output / "fractional-zip-input.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0 and report.is_file(), "Fractional ZIP input generation failed; see input logs")
    require(sha256(source) == expected, "Preparing the ZIP changed the signed fixture resource")
    value = json.loads(report.read_text())
    require(value["zip_sha256"] == sha256(fixture), "Generated ZIP receipt differs from actual input")
    return value


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def check_zip_edit_report(report, fixture):
    require(report.get("source_zip_sha256") == fixture["zip_sha256"] and report.get("source_zip_preserved") is True,
            "Actual app must select and preserve the generated ZIP input")
    validation = report.get("fractional_zip_save_validation", {})
    require(all(validation.get(key) is True for key in
                ("selectedZIP", "selectedLeftUpLeg", "saveEnabled", "spinnerStepsPreserved"))
            and validation.get("unsupported") == [],
            "Actual fractional ZIP editor must keep Save enabled with no unsupported edits")
    require(abs(float(validation.get("originalPositionY", 0)) - fixture["position"]["y"]) < 1e-6
            and abs(abs(float(validation.get("originalRotationX", 0))) - fixture["rotation_x_degrees"]) < 1e-4,
            "Actual ZIP editor did not retain the source's fractional position and rotation")
    off_grid = validation.get("offGridInputs", [])
    require({"position", "rotation"} <= {entry.get("kind") for entry in off_grid}
            and any(entry.get("kind") == "scale" and entry.get("axis") == "Y" and entry.get("value") == "1.234567"
                    for entry in off_grid),
            "The real editor must exercise fractional source fields beyond the spinner increments")


def check_pose_body_report(report):
    navigation = report.get("native_editor_navigation", {})
    require(navigation.get("status") == "PASS" and all(navigation.get(key) is True for key in
                ("single_webview", "model_camera_authoring_preserved", "no_extra_prepare", "header_hidden", "texture_previews_inside_tools")),
            "Native asset tools and 3D navigation must retain one WebView and its current model state")
    navigation = report.get("asset_navigation", {})
    require(all(navigation.get(key) is True for key in
                ("same_webview", "same_canvas_and_context", "unsaved_node_mesh_edits_preserved",
                 "page_change_selected_viewer", "late_ready_preserved_native_destination")),
            "Native Tools/3D navigation must preserve the live renderer and unsaved edits")
    structure = report.get("pose_body_panel_structure", {})
    require(structure.get("poseOpen") is False and all(structure.get(key) is True for key in
                ("bodyOpen", "siblings", "separate", "motionOwnedByPose", "editingOwnedByBody", "accessoryOpen")),
            "Actual WebKit must start Pose collapsed and expose independent pose and body controls")
    check_fresh_file_header(report.get("native_file_header", {}))
    panels = report.get("separate_pose_body_panels", {})
    require(panels.get("status") == "PASS" and len(panels.get("toggles", [])) == 4
            and panels.get("both_restored_open") is True
            and panels.get("model_camera_recipe_and_save_preserved") is True,
            "Actual pose/body summary toggles must preserve edits, camera and Save availability")
    invalid = report.get("invalid_body_draft_native_menu_save", {})
    require(invalid.get("status") == "PASS" and all(invalid.get(key) is True for key in
                ("production_command_acknowledged", "no_export_started", "invalid_raw_draft_preserved",
                 "valid_draft_restored", "pose_and_body_restored_open", "valid_body_field_focused_before_real_export")),
            "Native Save must reject an invalid body draft and resume export after correcting it")
    package = report.get("viewer_mod_package_validation", {})
    require(package.get("status") == "PASS" and all(package.get(key) is True for key in
                ("automatic_name_checked", "fresh_job", "no_install_requested", "bundled_python"))
            and package.get("manual_name_characters") == 120 and package.get("character_id") == 6,
            "Actual WebKit must create a fresh named Mod ZIP without installing it")
    inspection = package.get("inspection", {})
    require(inspection.get("status") == "PASS" and inspection.get("character_id") == 6
            and inspection.get("name_characters") == 120
            and inspection.get("expected_name_transport") == "base64-utf8"
            and inspection.get("private_prefix_samefile") is True
            and inspection.get("manifest_names_nfc") is True and all(inspection.get(key) is True for key in
                ("manifest_names_match", "model_bytes_match", "source_preserved", "thumbnail_png",
                 "safe_installer_structure")),
            "The bundled interpreter must verify the actual Mod ZIP and immutable source bytes")
    minimized = report.get("viewer_minimize_validation", {})
    restore = minimized.get("restore_target", {})
    require(minimized.get("status") == "PASS" and minimized.get("direction") == "width"
            and all(minimized.get(key) is True for key in
                    ("source_token_selection_folds_preserved", "model_camera_authoring_preserved",
                     "native_preferences_preserved", "no_additional_prepare", "no_job_mutation"))
            and restore.get("width", 0) >= 44 and restore.get("height", 0) >= 44,
            "Actual WebKit must minimize and restore the model without losing edits or native preferences")


def launch(app, output, label):
    stdout = output / f"{label}.stdout.txt"
    stderr = output / f"{label}.stderr.txt"
    directory = output / "native-app-data"
    directory.mkdir(exist_ok=True)
    report_file = directory / "native-smoke.json"
    report_file.unlink(missing_ok=True)
    with stdout.open("w") as out, stderr.open("w") as err:
        child = subprocess.Popen([str(app / "Contents/MacOS/Elichika"), "--smoke-test", str(directory)],
                                 cwd=output, env=private_environment(app / "Contents/Resources"),
                                 stdout=out, stderr=err, start_new_session=True)
        try:
            code = child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
            raise RuntimeError("Actual app smoke timed out; owned process group was terminated") from None
    require(code == 0, f"Actual app smoke failed ({code}); see {label} logs")
    require(report_file.is_file(), "App did not write its native smoke report")
    report = json.loads(report_file.read_text())
    require(report.get("status") == "PASS" and report.get("runtime_terminated") is True,
            "Actual app integration assertions did not pass")
    require(report.get("normal_app_quit_with_running_server") is True,
            "App did not test ordinary Quit while its game server was running")
    for key in ("python_pid", "go_pid", "go_pid_at_quit"):
        pid = report.get(key)
        deadline = time.monotonic() + 10
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(.2)
        require(not process_alive(pid), f"Owned {key} remained alive after app quit")
    preserve_native_output_evidence(output, label, report)
    inspect_accessory_export(app, output, label, report)
    check_game_physics_report(output, report)
    inspect_detail_export(app, output, label, report)
    inspect_extended_workflow(output, report)
    inspect_thumbnail_export(app, output, label, report)
    inspect_part_export(app, output, label, report)
    inspect_updater_export(app, output, label, report)
    write_json(output / f"{label}.json", report)
    for image in directory.glob("*.png"):
        shutil.copy2(image, output / f"{label}-{image.name}")
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    return report


def check(app, output, relocation):
    app, output, relocation = Path(app).resolve(), Path(output).resolve(), Path(relocation).resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(not relocation.exists() and relocation.suffix == ".app", "Fresh relocation .app path required")
    fixture = prepare_zip_fixture(app, output)
    accessory = prepare_accessory_fixture(app, output)
    game_physics = prepare_game_physics_fixture(app, output)
    detail_extended = prepare_detail_extended_fixtures(app, output)
    part_inputs = prepare_part_fixtures(app, output)
    updater_inputs = prepare_updater_fixtures(app, output)
    first = launch(app, output, "first-launch")
    check_zip_edit_report(first, fixture)
    check_pose_body_report(first)
    require(sha256(Path(fixture["zip"])) == fixture["zip_sha256"], "First app launch changed the input ZIP")
    relocation.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(app), str(relocation))
    require(not app.exists() and relocation.is_dir(), "App relocation must remove the original absolute path")
    second = launch(relocation, output, "relocated-relaunch")
    check_zip_edit_report(second, fixture)
    check_pose_body_report(second)
    first_panel = first.get("viewer_panel_width_persistence", {})
    second_panel = second.get("viewer_panel_width_persistence", {})
    require(240 <= first_panel.get("committed", 0) <= 640
            and first_panel.get("native_stored") == first_panel["committed"]
            and second_panel.get("restored_on_relaunch") is True
            and second_panel.get("previous_expected") == first_panel["committed"],
            "Adjustment panel width must persist through a fresh native WebView and relocated app relaunch")
    first_files = first.get("viewer_files_width_persistence", {})
    second_files = second.get("viewer_files_width_persistence", {})
    require(160 <= first_files.get("committed", 0) <= 360
            and first_files.get("native_stored") == first_files["committed"]
            and second_files.get("restored_on_relaunch") is True
            and second_files.get("previous_expected") == first_files["committed"],
            "File selection width must persist across native WebView origins and app relocation")
    require(sha256(Path(fixture["zip"])) == fixture["zip_sha256"], "Relocated relaunch changed the input ZIP")
    value = {"status": "PASS_FINAL_APP_LAUNCH_RELOCATION_AND_RELAUNCH",
             "app": str(relocation), "no_host_python_or_homebrew_path": True,
             "readonly_app_signature_preserved": True,
             "original_app_path_removed": True,
             "fractional_zip_input": fixture,
             "accessory_input": accessory,
             "game_physics_input": game_physics,
             "detail_extended_inputs": detail_extended,
             "part_selection_inputs": part_inputs,
             "thumbnail_updater_inputs": updater_inputs,
             "viewer_panel_width_persisted_across_relaunch": True,
             "viewer_files_width_persisted_across_relaunch": True,
             "space_and_unicode_path": " " in str(relocation) and any(ord(char) > 127 for char in str(relocation)),
             "first": first, "relocated": second}
    require(value["space_and_unicode_path"], "Relocation test needs spaces and a non-ASCII path")
    write_json(output / "app-smoke-summary.json", value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--relocation", type=Path, required=True)
    args = parser.parse_args()
    check(args.app, args.evidence, args.relocation)
