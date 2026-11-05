#!/usr/bin/env python3
"""Exercise the bundled interpreter/codecs with no host Python or runtime pip."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
from common import require, write_json


PROBE = r'''
import ast, importlib, importlib.util, io, json, os, pathlib, platform, socket, subprocess, sys, tempfile
resources = pathlib.Path(sys.argv[1]).resolve()
private = resources / 'runtime/arm64'
python = private / 'python'
sys.path.insert(0, str(resources / 'python-app'))
assert platform.machine() == 'arm64'
assert pathlib.Path(sys.executable).resolve().is_relative_to(python)
assert pathlib.Path(sys.prefix).resolve() == python
assert not importlib.util.find_spec('pip'), 'Runtime package installer must not be bundled'
assert sys.dont_write_bytecode and sys.flags.isolated
assert all(not entry or pathlib.Path(entry).resolve().is_relative_to(resources) for entry in sys.path)
real_run = subprocess.run
def guarded_run(args, *rest, **kwargs):
    assert not any(str(arg) in ('pip', 'pip3') for arg in args), 'Runtime dependency install attempted'
    return real_run(args, *rest, **kwargs)
subprocess.run = guarded_run
def refuse_network(*args, **kwargs):
    raise AssertionError('Dependency import tried to access the network')
socket.create_connection = refuse_network
packages = ['numpy','PIL.Image','lz4.frame','brotli','attrs','fsspec','certifi',
            'fmod_toolkit','texture2ddecoder','etcpak','astc_encoder','UnityPy']
loaded = {name:importlib.import_module(name) for name in packages}
import numpy as np
assert np.array_equal(np.array([[1.,2.,3.]]) @ np.array([[1.],[2.],[3.]]), np.array([[14.]]))
assert np.array_equal(np.ones((64,64)) @ np.ones((64,64)), np.full((64,64),64.))
assert np.allclose(np.linalg.inv(np.eye(4)*2), np.eye(4)*.5)
from PIL import Image
image = Image.new('RGBA', (8,8), (31,151,73,255))
buffer=io.BytesIO(); image.save(buffer, format='PNG'); buffer.seek(0)
assert Image.open(buffer).getpixel((0,0)) == (31,151,73,255)
import lz4.frame, brotli
assert lz4.frame.decompress(lz4.frame.compress(b'elichika-private-runtime')) == b'elichika-private-runtime'
assert brotli.decompress(brotli.compress(b'elichika-private-runtime')) == b'elichika-private-runtime'
from webtools.core.tkstub import ensure_tk_stub
ensure_tk_stub()
modules=['sukusta_paths','adminui.server','webtools.server','webtools.tools.registry',
         'sifas_node_scaling','sifas_mesh_baker','sifas_breast_tuner','skirt_length_changer',
         'hips_size_changer','Upleg_SwingCollider_changer','sifas_accessory_unclip',
         'costume_transplant','costume_part_transplant','lower_body_swap',
         'unity_costumemod_packer','skin_tone_changer','texture_importer',
         'assetbundle_IosApk_batch_import_plus','fix_sifas_bundle_export',
         'database_backup','database_restore',
         'llas_asset_extractor','elichika_macos']
for name in modules: importlib.import_module(name)
# These original installer CLIs deliberately execute their interaction/job at
# module scope. Their registered adapters load them only during an explicit job.
# Validate packaged source without running an installation during import QA.
script_files=['card_addon_installer.py','live_addon_installer.py']
for name in script_files:
    path=resources/'python-app'/name
    assert path.is_file()
    compile(ast.parse(path.read_text()),str(path),'exec')
import ssl, certifi
assert pathlib.Path(certifi.where()).resolve().is_relative_to(python)
context=ssl.create_default_context(cafile=certifi.where())
assert context.cert_store_stats()['x509_ca'] > 0
with tempfile.TemporaryDirectory(prefix='elichika-codec-test-') as directory:
    directory=pathlib.Path(directory); source=directory/'source.png'; image.save(source)
    encoded=directory/'encoded.astc'; decoded=directory/'decoded.png'
    encoder=private/'bin/astcenc'
    real_run([str(encoder),'-cl',str(source),str(encoded),'4x4','-fast'],check=True,stdout=subprocess.DEVNULL)
    real_run([str(encoder),'-dl',str(encoded),str(decoded)],check=True,stdout=subprocess.DEVNULL)
    assert Image.open(decoded).size == (8,8)
    import texture2ddecoder
    rgba=texture2ddecoder.decode_astc(encoded.read_bytes()[16:],8,8,4,4)
    assert len(rgba) == 8*8*4 and any(rgba)
print('ELICHIKA_RUNTIME_PROBE=' + json.dumps({'status':'PASS','arch':platform.machine(),
    'python':platform.python_version(),'packages':packages,'registered_modules':modules,
    'interactive_installer_sources_compiled_not_executed':script_files,
    'private_prefix':True,'no_runtime_pip':True,'offline_imports':True,
    'numpy_blas':True,'pillow_png':True,'lz4_brotli':True,'astc_encode_decode':True,
    'certificate_roots':context.cert_store_stats()['x509_ca']}))
'''


def private_environment(resources):
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith("DYLD_") or name in {"PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX"}:
            environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONDONTWRITEBYTECODE="1")
    environment["SSL_CERT_FILE"] = str(resources / "runtime/arm64/python/lib/python3.12/site-packages/certifi/cacert.pem")
    environment["REQUESTS_CA_BUNDLE"] = environment["SSL_CERT_FILE"]
    return environment


def check(app, report, *, network=False):
    app, report = Path(app).resolve(), Path(report)
    resources = app / "Contents/Resources"
    python = resources / "runtime/arm64/python/bin/python3"
    result = subprocess.run([str(python), "-I", "-B", "-c", PROBE, str(resources)],
                            cwd=report.parent, env=private_environment(resources), capture_output=True,
                            text=True, timeout=180)
    (report.parent / "runtime-probe.stdout.txt").write_text(result.stdout)
    (report.parent / "runtime-probe.stderr.txt").write_text(result.stderr)
    require(result.returncode == 0, "Private runtime probe failed; see runtime-probe logs")
    lines = [line for line in result.stdout.splitlines() if line.startswith("ELICHIKA_RUNTIME_PROBE=")]
    require(len(lines) == 1, "Private runtime probe did not produce exactly one report")
    value = json.loads(lines[0].split("=", 1)[1])
    if network:
        # Use the bundled CA roots and stdlib HTTPS client, not host certificates
        # or a package-manager certificate installation helper.
        source = "import json,urllib.request; r=urllib.request.urlopen('https://archive.org/metadata/llsifas-elichika-static-data',timeout=45); assert r.status==200; d=json.load(r); assert d.get('metadata',{}).get('identifier')=='llsifas-elichika-static-data'; print('ARCHIVE_HTTPS_PASS')"
        https = subprocess.run([str(python), "-I", "-B", "-c", source],
                               env=private_environment(resources), capture_output=True, text=True, timeout=60)
        (report.parent / "runtime-https.txt").write_text(https.stdout + https.stderr)
        require(https.returncode == 0 and "ARCHIVE_HTTPS_PASS" in https.stdout,
                "Bundled Python Archive.org HTTPS/CA check failed")
        value["archive_https"] = "PASS bundled certifi CA roots"
    write_json(report, value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    check(args.app, args.report, network=args.network)
