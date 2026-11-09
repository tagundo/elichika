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
import ast, hashlib, importlib, importlib.util, io, json, os, pathlib, platform, socket, subprocess, sys, tempfile
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
         'webtools.core.model_accessory_unclip','webtools.core.model_edits',
         'webtools.core.model_outlines',
         'webtools.core.viewer_physics_runtime',
         'sifas_node_scaling','sifas_mesh_baker','sifas_breast_tuner','skirt_length_changer',
         'hips_size_changer','Upleg_SwingCollider_changer','sifas_accessory_unclip',
         'costume_transplant','costume_part_transplant','lower_body_swap',
         'unity_costumemod_packer','skin_tone_changer','texture_importer',
         'assetbundle_IosApk_batch_import_plus','fix_sifas_bundle_export',
         'database_backup','database_restore','costume_scene_installer','costume_scene_clones','costume_scene_sources',
         'llas_asset_extractor','sifas_asset_crypto','payload_upgrade_progress','elichika_macos_memory','elichika_macos']
for name in modules: importlib.import_module(name)
from webtools.core import cri_audio_decode
hca_library=private/'bin/libelichika_hca.dylib'
assert pathlib.Path(os.environ['ELICHIKA_HCA_LIBRARY']).resolve()==hca_library
assert hca_library.is_file()
hca_native=cri_audio_decode._native_library()
assert hca_native is not None, 'The packaged HCA decoder must load without host FFmpeg'
hca_state=hca_native.clHCA_new()
assert hca_state
hca_native.clHCA_delete(hca_state)
from payload_upgrade_progress import ProgressReporter
payload_progress=[]
report_progress=ProgressReporter(lambda raw: payload_progress.append(json.loads(raw)))
report_progress('merging',1,2,'asset_a_ko.db')
report_progress('publishing',1,1,'')
assert [item['percent'] for item in payload_progress] == [60,99]
report_progress('complete',1,1,'')
assert payload_progress[-1]['percent'] == 100
from elichika_macos_memory import fresh_macos_memory_env, available_macos_memory_bytes
memory_bytes=available_macos_memory_bytes()
assert isinstance(memory_bytes,int) and memory_bytes>0
memory_environment=fresh_macos_memory_env({'ELICHIKA_CLIENTDB_MEMORY_BYTES':'invalid-parent-value'})
assert memory_environment['ELICHIKA_CLIENTDB_MEMORY_BYTES'].isdigit()
assert int(memory_environment['ELICHIKA_CLIENTDB_MEMORY_BYTES'])>0
# Exercise the actual packaged arm64 NumPy path across its block boundary.
# The scalar extractor is an independent byte-for-byte oracle; no game files
# or installed data are used. Cache counters prove this is not the fallback.
from costume_clone_assets import _crypt_section, _lcg_coefficients
from llas_asset_extractor import _decrypt_section_scalar, decrypt_section, FIXED_KEY0
import sifas_asset_crypto as shared_crypto
crypto_input=bytes((index*37+11)&255 for index in range(65537))
crypto_keys=(FIXED_KEY0,-2147483648,-1)
crypto_expected=bytearray(crypto_input)
_decrypt_section_scalar(crypto_expected,*crypto_keys)
crypto_actual=bytearray(crypto_input)
crypto_before=_lcg_coefficients.cache_info()
_crypt_section(crypto_actual,*crypto_keys)
crypto_after=_lcg_coefficients.cache_info()
assert crypto_after.hits+crypto_after.misses > crypto_before.hits+crypto_before.misses
assert crypto_actual==crypto_expected
crypto_coefficients=_lcg_coefficients()
assert all(array.dtype==np.dtype('uint32') and len(array)==65536
           and not array.flags.writeable for array in crypto_coefficients[:2])
_crypt_section(crypto_actual,*crypto_keys)
assert crypto_actual==crypto_input
from live_install_core import manipulate_file
from costume_scene_installer import _encrypt
crypto_scalar=shared_crypto.decrypt_section_scalar
def refuse_shared_scalar(*args):
    raise AssertionError('Packaged common crypto unexpectedly used scalar fallback')
shared_before=_lcg_coefficients.cache_info()
try:
    shared_crypto.decrypt_section_scalar=refuse_shared_scalar
    for crypto_consumer in (decrypt_section,manipulate_file):
        crypto_actual=bytearray(crypto_input)
        assert crypto_consumer(crypto_actual,*crypto_keys) is None
        assert crypto_actual==crypto_expected
        crypto_consumer(crypto_actual,*crypto_keys)
        assert crypto_actual==crypto_input
    scene_expected=bytearray(crypto_input)
    _decrypt_section_scalar(scene_expected,12345,0,0)
    assert _encrypt(crypto_input)==bytes(scene_expected)
    assert _encrypt(scene_expected)==crypto_input
finally:
    shared_crypto.decrypt_section_scalar=crypto_scalar
shared_after=_lcg_coefficients.cache_info()
shared_calls=shared_after.hits+shared_after.misses-shared_before.hits-shared_before.misses
assert shared_calls==6
crypto_probe={'status':'PASS_ACCELERATED_SCALAR_EQUIVALENCE','bytes':len(crypto_input),
    'signed_distinct_keys':True,'block_boundary_crossed':True,'accelerated_path_observed':True,
    'immutable_coefficients':True,'round_trip':True,
    'ciphertext_sha256':hashlib.sha256(crypto_expected).hexdigest(),
    'shared_consumers':['asset-extractor','live-installer','scene-installer'],
    'shared_coefficient_calls':shared_calls}
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
    'hca_decoder':{'native_loaded':True,'bundled_library':True},
    'numpy_blas':True,'clone_crypto':crypto_probe,'pillow_png':True,'lz4_brotli':True,'astc_encode_decode':True,
    'clientdb_memory_bridge':{'fresh_snapshot':True,'available_bytes':memory_bytes,
                            'environment_bytes':int(memory_environment['ELICHIKA_CLIENTDB_MEMORY_BYTES'])},
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
    environment["ELICHIKA_HCA_LIBRARY"] = str(resources / "runtime/arm64/bin/libelichika_hca.dylib")
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
