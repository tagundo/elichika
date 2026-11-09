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
                ("bodyOpen", "siblings", "separate", "motionOwnedByPose", "editingOwnedByBody")),
            "Actual WebKit must start Pose collapsed and expose independent pose and body controls")
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
    inspect_accessory_export(app, output, label, report)
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
