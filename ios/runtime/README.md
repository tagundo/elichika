# Private iOS Python runtime

`provision.py --target device|simulator --output DIR --cache DIR --core-only`
prepares the pinned BeeWare CPython 3.13-b18 support package for a native SDK
probe. The output is app-shaped: `Frameworks/*.framework`,
`ElichikaResources/python/lib/python3.13`, and
`ElichikaResources/python-app`. The simulator Python framework is thinned to
arm64. Every native extension becomes an audited, signed framework with the
CPython iOS `.fwork` and `.origin` mappings; no macOS framework is substituted.

For the complete registered tool closure, first install the pinned build-host
requirements with `pip install --require-hashes -r build-requirements.txt`, then
run `build_wheels.py --target TARGET --output WHEELS --cache CACHE` and
`build_codecs.py --target TARGET --output CODECS`. Full provisioning additionally
requires `--built-lock WHEELS/built-lock.json --codec-frameworks CODECS` and omits
`--core-only`. The wheel lock covers actual iOS NumPy, Pillow and Brotli wheels;
the missing lz4, texture2ddecoder, etcpak and ASTC bindings are cross-compiled
from SHA256-pinned sources. UnityPy retains the same bounded Python parser used
on Android/macOS. Build and runtime never invoke pip inside the installed app.

The registered audio routes use the vendored ISC HCA decoder and the standard
ADX decoder in `ios/python/elichika_ios/adx.py`. FMOD is an incidental optional
UnityPy import: no existing registered tool uses AudioClip.samples/FSB export,
and the existing packer already rejects that operation. No FMOD stub or host
FMOD binary is added by this port. ASTC/ETC/BC codecs remain real native Python
extensions. The bounded Crunch library retains all authored mip levels,
straight alpha and exact source pixels without applying texture resampling.

The complete runtime preserves the existing production archive publication
guard. `archive-hosted-catalog.json` must describe the verified COMPLETE set of
42,830 files before full provisioning can succeed. An incomplete source config
is copied unchanged only into an explicitly labelled core SDK probe. A core
probe cannot be packaged as a complete game/tools candidate.

The host installs the official payload through the existing journal, recovery,
merge and owner-preserving update engine. Per-module adapters resolve relative
file IO under the explicit data root, preserve lexical Path operations, and
retain the existing HTTPS streaming/progress/cancellation using bundled CA
certificates. They never change the Unity process cwd or environment. The
native Go server drains before a job obtains the shared database maintenance
lease; failed/cancelled jobs stay stopped. Same-root bootstrap retries reuse
the initialized interpreter after the prior worker and Go operation finish.

Portable verification:

```sh
PYTHONPATH=ios/python python -B -m unittest discover -s ios/python/tests -v
node ios/python/tests/test_ios_platform.js
```

`ELICHIKA_TEST_CODEC_DIR` enables the compiled-host Crunch golden tests.
`integration_routes.py --codec-frameworks DIR` additionally uses real host
UnityPy/NumPy/Pillow and the compiled codec libraries to exercise both
authenticated tool registries and a textured neutral model to GLB. These are
host proofs. Actual iOS compilation, Simulator execution, memory behaviour,
device game playback and full feature parity require the separate native/IPA
validation gates and are never inferred from these tests.
