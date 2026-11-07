#!/usr/bin/env python3
"""Bind public original/private Unity models and dependency closure to native A/B."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

GAME_SHA = '8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e'
PROPERTIES = ['_AmbientColor', '_RimlightColor']


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inspect(path, model=False):
    import UnityPy
    assert UnityPy.__version__ == '1.25.0', 'Use the pinned fixture reader'
    env = UnityPy.load(str(path))
    serialized = [sf for bundle in env.files.values() for sf in bundle.files.values() if hasattr(sf, 'externals')]
    assert len(serialized) == 1 and int(serialized[0].target_platform) == 13
    sf = serialized[0]
    objects = {obj.path_id: obj for obj in env.objects}
    result = {'cab': sf.name, 'platform': 13,
              'externals': [external.path.rsplit('/', 1)[-1].lower() for external in sf.externals]}
    if model:
        arrays = {}
        for obj in objects.values():
            if obj.type.name != 'MonoBehaviour':
                continue
            script = obj.read().m_Script.read()
            if script.m_ClassName in ('LiveCoreMemberAmbient', 'LiveCoreMemberRimlight'):
                assert script.m_ClassName not in arrays
                refs = obj.read_typetree()['materials']
                assert len(refs) == 2 and all(ref['m_FileID'] == 0 for ref in refs), 'Mutable lighting material must be internal'
                arrays[script.m_ClassName] = [ref['m_PathID'] for ref in refs]
        assert len(arrays) == 2 and len({tuple(value) for value in arrays.values()}) == 1
        materials = []
        for path_id in arrays['LiveCoreMemberAmbient']:
            obj = objects[path_id]
            assert obj.type.name == 'Material'
            tree = obj.read_typetree()
            colors = dict(tree['m_SavedProperties']['m_Colors'])
            assert all(prop in colors for prop in PROPERTIES)
            colors = {prop: [colors[prop][axis] for axis in 'rgba'] for prop in PROPERTIES}
            shader = tree['m_Shader']
            assert shader['m_FileID'] > 0
            shader_cab = sf.externals[shader['m_FileID'] - 1].path.rsplit('/', 1)[-1].lower()
            materials.append({'name': tree['m_Name'], 'path_id': str(path_id), 'colors': colors,
                              'shader_cab': shader_cab, 'shader_path_id': str(shader['m_PathID'])})
        result['materials'] = materials
    else:
        result['shaders'] = [str(obj.path_id) for obj in objects.values() if obj.type.name == 'Shader']
        exports = []
        for key, pointer in env.container.items():
            if pointer.type.name != 'Shader':
                continue
            assert pointer.m_FileID == 0 and str(pointer.path_id) in result['shaders']
            tree = pointer.read_typetree()
            name = tree.get('m_Name') or tree.get('m_ParsedForm', {}).get('m_Name')
            assert isinstance(name, str) and name
            exports.append({'container_key': key, 'file_id': 0, 'path_id': str(pointer.path_id),
                            'class': 'UnityEngine.Shader', 'name': name, 'named_asset_count': 1})
        assert len(exports) == (1 if result['shaders'] else 0), 'Expected exact public Shader container export'
        result['shader_exports'] = exports
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clones', type=Path, required=True)
    p.add_argument('--dependencies', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    assert not args.output.exists(), 'Output directory must be fresh'
    producer = json.loads(args.clones.read_text())
    dependency = json.loads(args.dependencies.read_text())
    assert producer['unitypy'] == dependency['unitypy'] == '1.25.0'
    args.output.mkdir(parents=True)
    fixtures = []
    def copy_item(source, item):
        source = Path(source)
        assert source.is_file() and digest(source) == item['sha256']
        target = args.output / item['file']
        assert not target.exists()
        shutil.copyfile(source, target)
        assert digest(target) == item['sha256']
        item['bytes'] = target.stat().st_size
        fixtures.append(item)
    nodes = {node['asset_path']: node for node in dependency['nodes']}
    loaded_cabs = {}
    details_by_asset = {asset: inspect(nodes[asset]['path']) for asset in dependency['topological_assets']}
    assert len({details['cab'].lower() for details in details_by_asset.values()}) == len(details_by_asset)
    all_cabs = {details['cab'].lower() for details in details_by_asset.values()}
    assert all(external in all_cabs for details in details_by_asset.values() for external in details['externals'])
    # Catalog dependencies and SerializedFile externals differ for facedynamic.
    # LoadAllAssets is immediate in this probe, so use actual CAB dependencies.
    pending = list(dependency['topological_assets'])
    native_order = []
    while pending:
        ready = [asset for asset in pending if all(external in loaded_cabs for external in details_by_asset[asset]['externals'])]
        assert ready, 'Native dependency cycle or unresolved serialized external'
        for asset in ready:
            native_order.append(asset)
            loaded_cabs[details_by_asset[asset]['cab'].lower()] = details_by_asset[asset]
            pending.remove(asset)
    loaded_cabs = {}
    for index, asset in enumerate(native_order):
        node = nodes[asset]
        assert digest(node['pack_path']) == node['encrypted_pack_sha256']
        details = details_by_asset[asset]
        assert details['cab'] in node['serialized_files']
        assert details['cab'].lower() not in loaded_cabs
        assert all(external in loaded_cabs for external in details['externals']), 'Dependency-first CAB closure incomplete'
        loaded_cabs[details['cab'].lower()] = details
        copy_item(node['path'], {'id': 'dependency_' + str(index), 'kind': 'dependency',
            'asset_path': asset, 'file': 'dependency_' + str(index) + '.unity', 'sha256': node['plain_sha256'],
            'descriptor': node['descriptor'], 'encrypted_pack_sha256': node['encrypted_pack_sha256'], **details})
    assert sum(bool(value['shaders']) for value in loaded_cabs.values()) >= 2
    for role in ('board', 'unmasked'):
        originals = [item for item in producer['items'] if Path(item['source']).name == 'a_' + role + '.unity']
        assert len(originals) == 2 and {item['clone'] for item in originals} == {'clone_a', 'clone_b'}
        source = Path(originals[0]['source'])
        assert all(item['source_sha256'] == originals[0]['source_sha256'] for item in originals)
        base = inspect(source, model=True)
        for material in base['materials']:
            assert material['shader_cab'] in loaded_cabs, 'Missing exact controlled shader dependency'
            assert material['shader_path_id'] in loaded_cabs[material['shader_cab']]['shaders']
            assert any(export['path_id'] == material['shader_path_id'] for export in loaded_cabs[material['shader_cab']]['shader_exports']), 'Controlled shader must bind exact container export'
        assert all(external in loaded_cabs for external in base['externals']), 'Incomplete native externals'
        copy_item(source, {'id': 'source_' + role, 'kind': 'model', 'role': role,
            'file': 'source_' + role + '.unity', 'sha256': originals[0]['source_sha256'], **base})
        cabs = {base['cab'].lower()}
        for item in sorted(originals, key=lambda item: item['clone']):
            assert item['platform'] == 13 and item['nonidentity_raw_object_and_resource_invariants'] == 'passed'
            details = inspect(item['path'], model=True)
            assert details['cab'] == item['private_cab'] and details['materials'] == base['materials']
            assert details['externals'] == base['externals']
            assert details['cab'].lower() not in cabs
            cabs.add(details['cab'].lower())
            identity = item['clone'] + '_' + role
            copy_item(item['path'], {'id': identity, 'kind': 'model', 'role': role,
                'file': identity + '.unity', 'sha256': item['sha256'], 'source_sha256': item['source_sha256'],
                'reproduction_namespace': item.get('namespace'), **details})
    cases = []
    for role in ('board', 'unmasked'):
        sequence = ['source_' + role, 'clone_a_' + role, 'clone_b_' + role]
        cases.extend([{'id': role + '_shared_control', 'expect': 'shared', 'sequence': sequence[:1]},
                      {'id': role + '_private_forward', 'expect': 'isolated', 'sequence': sequence},
                      {'id': role + '_private_reverse', 'expect': 'isolated', 'sequence': sequence[::-1]}])
    shutil.copyfile(args.clones, args.output / 'producer-manifest.json')
    shutil.copyfile(args.dependencies, args.output / 'dependency-manifest.json')
    report = {'schema': 1, 'scope': 'owned-original-unity-material-ab', 'game_sha256': GAME_SHA,
        'properties': PROPERTIES, 'producer_manifest_sha256': digest(args.clones),
        'dependency_manifest_sha256': digest(args.dependencies),
        'catalog_sha256': dependency['source_catalog_sha256'], 'source_cdn': dependency['source_cdn'],
        'producer_source_commit': producer.get('implementation_commit', producer.get('source_commit')),
        'producer_implementation_file_sha256': producer.get('implementation_file_sha256'),
        'producer_isolation_function_sha256': producer.get('isolation_function_sha256'),
        'native_dependency_assets': native_order, 'fixtures': fixtures, 'cases': cases}
    (args.output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'READY', 'fixtures': len(fixtures), 'cases': len(cases),
                      'manifest': str(args.output / 'manifest.json'), 'sha256': digest(args.output / 'manifest.json')}))


if __name__ == '__main__':
    main()
