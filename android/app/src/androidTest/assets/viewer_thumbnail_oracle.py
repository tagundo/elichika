"""Independent PNG/archive/source/template binding oracle for native thumbnail QA.

Runs inside either app's private Python. It reads real output files and SDK
assets; it does not call thumbnail rendering, composition or packaging code.
"""
import ast
import base64
import hashlib
import io
import json
import math
import pathlib
import zipfile

from PIL import Image


def full_character(render, profile, size, fit_full=False):
    framing, camera, source = render['framing'], render['camera'], profile['camera']
    assert framing['mode'] == ('full-character' if fit_full else 'head-and-upper-body') and framing['fitFullCharacter'] is fit_full
    assert framing['sourceCamera'] == source and framing['camera'] == camera
    assert framing['vertices'] > 0 and framing['padding'] > 0
    assert all(row['role'] == 'dependency' for row in render['excludedMeshes'])
    bounds = render['subjectBounds']
    assert 0 < bounds['left'] <= bounds['right'] < size - 1 and 0 < bounds['top'] <= bounds['bottom'] < size
    if fit_full:
        assert bounds['bottom'] < size - 1
    assert camera['near'] == source['near'] and camera['far'] >= source['far']
    assert camera['right'] - camera['left'] >= source['right'] - source['left']
    assert camera['top'] - camera['bottom'] >= source['top'] - source['bottom']
    dot = lambda a,b: sum(x*y for x,y in zip(a,b))
    cross = lambda a,b: [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    unit = lambda a: [v/math.sqrt(dot(a,a)) for v in a]
    direction = unit(source['direction']); right = unit(cross(direction,source['up'])); up = unit(cross(right,direction))
    assert all(abs(a-b)<1e-9 for a,b in zip(camera['direction'],direction)) and camera['up'] == source['up']
    low, high = framing['minimum'], framing['maximum']
    assert all(math.isfinite(v) for v in low+high+camera['position'])
    assert framing['maximum'] == framing['wholeMaximum']
    assert low[0] == framing['wholeMinimum'][0] and low[2] == framing['wholeMinimum'][2]
    if fit_full:
        assert low == framing['wholeMinimum']
    else:
        expected = max(framing['wholeMinimum'][1], high[1] - max(source['top']-source['bottom'], (high[1]-framing['wholeMinimum'][1])*.65))
        assert abs(low[1]-expected)<1e-8
    for axis,vector,start,end in [(0,right,camera['left'],camera['right']),(1,up,camera['bottom'],camera['top'])]:
        centre = dot(camera['position'],vector)
        assert start < low[axis]-centre <= high[axis]-centre < end
    assert camera['near'] < low[2]-dot(camera['position'],direction) <= high[2]-dot(camera['position'],direction) < camera['far']


def inspect_json(encodedReport, sdkDirectory, sourcePath, sourceSHA):
    observed = json.loads(encodedReport)
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    canonical=lambda value:json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()
    receipt=observed['receipt'];response=observed['response'];pack=response['mod_package'];before=observed['before']
    recipe=json.loads(pathlib.Path(response['recipe_path']).read_text());assert recipe==response['recipe']
    assert recipe['state']['edits'] == before['authoring']['edits']
    assert before==observed['after']
    assert sha(pathlib.Path(sourcePath).read_bytes())==sourceSHA
    originals=[[path,sha(pathlib.Path(path).read_bytes())] for path in before['paths']]
    assert receipt['sources']==[{'name':pathlib.Path(path).name,'sha256':digest} for path,digest in originals]
    assert [row['sha256'] for row in recipe['originals']]==[digest for _,digest in originals]
    for row in recipe['sources']:
        path=pathlib.Path(before['paths'][row['container']]);raw=path.read_bytes()
        if row['member'] is not None:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:raw=archive.read(row['member'])
        assert sha(raw)==row['sha256']
    assets=pathlib.Path(sdkDirectory)
    profile=json.loads((assets/'profile.json').read_text());assert profile==observed['profile']
    files=sorted(path for path in assets.iterdir() if path.is_file() and path.suffix in ('.png','.json'))
    asset_hashes=[[path.name,sha(path.read_bytes())] for path in files]
    profile_digest=sha(canonical(asset_hashes));assert profile_digest==receipt['profileDigest']==pack['thumbnail']['profileDigest']
    for name,value in profile['provenance']['derivedAssets'].items():
        raw=(assets/name).read_bytes();assert sha(raw)==value['sha256'] and len(raw)==value['bytes']
    fit_full=before.get('thumbnailFitFull',False);assert type(fit_full) is bool
    quality={'renderer':'SifasMaterial','highQuality':True,'animation':False,'supersample':2,'rimlight':False,'subject':'full-character-v1' if fit_full else 'head-and-upper-body-v1'}
    assert receipt['quality']==pack['thumbnail']['quality']==quality
    binding={'token':before['editingToken'],'state':recipe['state'],'sources':recipe['sources'],
             'character_id':before['characterId'],'counterpart_path':before['counterpartPath'],'selected_variant':before['variant']}
    include_face_edits=before.get('include_face_edits')
    if include_face_edits is not None:
        assert type(include_face_edits) is bool
        binding['include_face_edits']=include_face_edits
    cache=sha(canonical({'kind':'viewer','binding':binding,'source':originals,'targetMember':before['characterId'],
                        'profile':profile_digest,'size':receipt['size'],'quality':quality}))
    faces=receipt.get('faceSources',[])
    assert faces==observed['render'].get('faceSources',[]) and len(faces)<=4
    for face in faces:
        assert set(face)=={'name','sha256'} and isinstance(face['name'],str) and pathlib.Path(face['name']).name==face['name']
        assert len(face['sha256'])==64 and all(c in '0123456789abcdef' for c in face['sha256'])
    if faces:
        cache=sha(canonical({'plan':cache,'faces':sorted([face['name'],face['sha256']] for face in faces)}))
    assert cache==receipt['cacheKey']==pack['thumbnail']['cacheKey']
    full_character(observed['render'],profile,receipt['size'],fit_full);assert len(profile['memberColors'])==30
    assert observed['render']['pose']=='source-rest' and observed['render']['animation'] is False
    assert observed['render']['material']['rimlightEnabled'] is False
    preview=observed['previewPNG'];assert preview.startswith('data:image/png;base64,')
    png=base64.b64decode(preview.split(',',1)[1],validate=True)
    assert sha(png)==receipt['sha256']==pack['thumbnail']['sha256'] and len(png)==receipt['bytes']
    with Image.open(io.BytesIO(png)) as image:
        assert image.format=='PNG' and image.size==(receipt['size'],receipt['size'])
        assert image.convert('RGBA').getchannel('A').getextrema()[1]>0
    with Image.open(io.BytesIO(png)) as image:image.verify()
    raw=pathlib.Path(pack['package_path']).read_bytes();assert sha(raw)==pack['sha256'] and len(raw)==pack['bytes']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.namelist();assert len(entries)==len(set(entries))
        assert all(not pathlib.PurePosixPath(name).is_absolute() and '..' not in pathlib.PurePosixPath(name).parts for name in entries)
        manifests=[name for name in entries if pathlib.PurePosixPath(name).name=='modinstall.txt'];assert len(manifests)==1
        manifest={}
        for node in ast.parse(archive.read(manifests[0]).decode('utf-8-sig')).body:
            assert isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            key=node.targets[0].id;assert key not in manifest;manifest[key]=ast.literal_eval(node.value)
        assert manifest['chara_id']==before['characterId']==receipt['characterId']==pack['character_id']
        assert all(manifest[name]==before['name'] for name in ('costume_name_en','costume_name_ko','costume_name_zh','costume_name_ja','costume_description'))
        member=manifest['thumbnail_file'];assert member==pack['thumbnail']['member'] and archive.read(member)==png
        saved=pathlib.Path(response['preview_paths'][0]).read_bytes()
        if zipfile.is_zipfile(io.BytesIO(saved)):
            with zipfile.ZipFile(io.BytesIO(saved)) as model:
                members=[name for name in model.namelist() if not name.endswith('/')];assert len(members)==1;saved=model.read(members[0])
        assert archive.read(manifest['costume_file'])==saved
    value={'status':'PASS','actual_zip_preview_png_byte_identical':True,
           'png_sha256':sha(png),'png_bytes':len(png),'png_size':receipt['size'],'character_id':receipt['characterId'],
           'thumbnail_member':member,'source_files_unchanged':True,'source_recipe_hashes_match':True,'saved_model_bytes_match':True,
           'profile_digest':profile_digest,'profile_assets':asset_hashes,'profile_assets_independently_hashed':True,
           'binding_cache_key':cache,'normalized_state_sources_member_template_quality_bound':True,
           'package_sha256':sha(raw),'safe_installer_structure':True}
    return json.dumps(value,ensure_ascii=False)
