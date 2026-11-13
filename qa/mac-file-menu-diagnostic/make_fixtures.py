"""Create only owned, deterministic input fixtures; not executed by the native diagnostic."""
import base64, hashlib, io, json, pathlib, random
import UnityPy
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = pathlib.Path('/workspace/elichika/modtools/tests/fixtures/viewer_persistence.unity')

def png(image):
    result = io.BytesIO(); image.save(result, format='PNG', compress_level=3); return result.getvalue()

def data_url(raw): return 'data:image/png;base64,' + base64.b64encode(raw).decode()

def main():
    result = {'original_fixture_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(), 'phases': {}}
    for prefix, size in [('small', 16), ('large', 1024)]:
        generator = random.Random(8132026 + size)
        pixels = bytearray(generator.randbytes(size * size * 4))
        for offset in range(3, len(pixels), 4): pixels[offset] = 255
        image = Image.frombytes('RGBA', (size, size), bytes(pixels))
        imported = png(image)
        (ROOT / f'fixtures/{prefix}-import.png').write_bytes(imported)
        base = png(Image.new('RGBA', (size, size), (20, 60, 80, 255)))
        project = {'format': 'elichika-texture-project', 'version': 1, 'width': size, 'height': size,
                   'activeLayer': 'qa-overlay', 'layers': [
                       {'id': 'qa-base', 'name': 'QA base', 'visible': True, 'opacity': 1, 'png': data_url(base)},
                       {'id': 'qa-overlay', 'name': 'QA overlay', 'visible': True, 'opacity': .5, 'png': data_url(imported)}]}
        project_raw = (json.dumps(project, separators=(',', ':')) + '\n').encode()
        (ROOT / f'fixtures/{prefix}-layers.json').write_bytes(project_raw)
        bundle = UnityPy.load(SOURCE.read_bytes())
        found = 0
        for obj in bundle.objects:
            if obj.type.name == 'Texture2D':
                texture = obj.read(); texture.image = Image.new('RGBA', (size, size), (80, 130, 190, 255))
                texture.m_Name = 'ch0001_co0001_body'; texture.save(); found += 1
        assert found > 0
        (ROOT / f'fixtures/{prefix}-model.unity').write_bytes(bundle.file.save(packer='original'))
        result['phases'][prefix] = {'width': size, 'height': size, 'png_bytes': len(imported),
                                   'project_bytes': len(project_raw), 'model_texture_RGBA': [80, 130, 190, 255],
                                   'input_contrasts_with_model': image.getpixel((0, 0)) != (80, 130, 190, 255),
                                   'PNG_encoded_POST_bytes': len(json.dumps({'png': data_url(imported)}).encode()),
                                   'project_encoded_POST_bytes': len(json.dumps({'project': project}).encode())}
    assert 1024 * 1024 < result['phases']['large']['PNG_encoded_POST_bytes'] < 12 * 1024 * 1024
    assert 1024 * 1024 < result['phases']['large']['project_encoded_POST_bytes'] < 32 * 1024 * 1024
    (ROOT / 'fixtures/fixture-generation.json').write_text(json.dumps(result, indent=2) + '\n')

if __name__ == '__main__': main()
