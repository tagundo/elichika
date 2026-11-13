import argparse,hashlib,json,pathlib,shutil,subprocess

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('--checkout',type=pathlib.Path,required=True);p.add_argument('--qa',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);a=p.parse_args()
commit=subprocess.check_output(['git','-C',str(a.checkout),'rev-parse','HEAD'],text=True).strip();assert commit=='28b80a8b43898ef9544d8452fef76181839eec6e'
frozen=json.loads((a.qa/'source-manifest.json').read_text());proposal=json.loads((a.qa/'proposed-C5/proposal-manifest-v3.json').read_text())
for row in frozen['files']:assert sha(a.checkout/row['path'])==row['sha256'],row['path']
for row in proposal['files']:assert sha(a.qa/'proposed-C5'/row['path'])==row['sha256'],row['path']
receipt={'status':'SOURCE_BOUND_EXPERIMENT_NOT_RELEASE_CANDIDATE','baseline_commit':commit,'frozen_six':frozen['files'],'proposed_delta':proposal['files'],'variants':{},'prior44_reused_for_changed_source':False}
for label in ['C4-negative','proposed-positive']:
 root=a.output/label;mac=root/'macos';mac.mkdir(parents=True)
 for directory in ['App','Tests']:shutil.copytree(a.checkout/'macos'/directory,mac/directory)
 shutil.copyfile(a.checkout/'macos/Package.swift',mac/'Package.swift');(mac/'runtime').mkdir();shutil.copyfile(a.checkout/'macos/runtime/elichika_macos.py',mac/'runtime/elichika_macos.py')
 shutil.copyfile(a.qa/'proposed-C5/macos/Tests/ConsoleWrappedScrollTests.swift',mac/'Tests/ConsoleWrappedScrollTests.swift')
 if label=='proposed-positive':shutil.copyfile(a.qa/'proposed-C5/macos/App/ElichikaApp.swift',mac/'App/ElichikaApp.swift')
 projection=root/'probe-sources';shutil.copytree(mac/'App',projection)
 app=projection/'ElichikaApp.swift';s=app.read_text();exact='@main\nstruct ElichikaMacApp: App {';assert s.count(exact)==1;app.write_text(s.replace(exact,'struct ElichikaMacApp: App {',1))
 receipt['variants'][label]={'source_files':[{'path':str(x.relative_to(root)),'sha256':sha(x)} for x in sorted(mac.rglob('*.swift'))],'python_sha256':sha(mac/'runtime/elichika_macos.py'),'app_entrypoint_only_projection_sha256':sha(app)}
a.evidence.mkdir(parents=True,exist_ok=True);(a.evidence/'anchor-preview-source-inputs.json').write_text(json.dumps(receipt,indent=2)+'\n')
