#!/usr/bin/env bash
# Pinned tooling for the disposable native ARM64 GL QA job only.
set -euo pipefail
QA_PYTHON_ENV=$1
QA_TOOLS_DIR=$2
QA_SERIAL=$3
QA_REPORT=$4
QA_DOWNLOADS="$QA_TOOLS_DIR/downloads"
mkdir -p "$QA_DOWNLOADS" "$QA_TOOLS_DIR/package/dist" "$(dirname "$QA_REPORT")"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python >=3.11 is required for this pinned no-dependency wheel"'
python3 -m venv "$QA_PYTHON_ENV"

QA_WHEEL="$QA_DOWNLOADS/frida-17.25.2-cp37-abi3-manylinux_2_17_aarch64.whl"
curl --fail --location --retry 2 --output "$QA_WHEEL" \
  https://files.pythonhosted.org/packages/9e/a1/9b6217b1e367bdc1c4c93ef13a889b131f0d07a85681c43f97298f8c8fbd/frida-17.25.2-cp37-abi3-manylinux_2_17_aarch64.whl
printf '%s  %s\n' ba69324c16b3ea018241519621d69f75896adbdce07f1afb1f60d7a322d17175 "$QA_WHEEL" | sha256sum --check
"$QA_PYTHON_ENV/bin/python" -m pip install --no-deps --no-index "$QA_WHEEL"
"$QA_PYTHON_ENV/bin/python" -c 'import frida; assert frida.__version__ == "17.25.2"'

QA_SERVER_XZ="$QA_DOWNLOADS/frida-server-17.25.2-android-arm64.xz"
QA_SERVER="$QA_DOWNLOADS/frida-server-17.25.2"
curl --fail --location --retry 2 --output "$QA_SERVER_XZ" \
  https://github.com/frida/frida/releases/download/17.25.2/frida-server-17.25.2-android-arm64.xz
printf '%s  %s\n' 08d7b7f02256621c9089cecd6495a5eb43861bf560a7ed86ad376e75d16a1fb6 "$QA_SERVER_XZ" | sha256sum --check
xz --decompress --stdout "$QA_SERVER_XZ" > "$QA_SERVER"
python3 - "$QA_SERVER" <<'PY'
import struct, sys
with open(sys.argv[1], 'rb') as f:
    header = f.read(64)
assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183
PY

QA_BRIDGE="$QA_DOWNLOADS/frida-il2cpp-bridge-0.14.0.tgz"
curl --fail --location --retry 2 --output "$QA_BRIDGE" \
  https://registry.npmjs.org/frida-il2cpp-bridge/-/frida-il2cpp-bridge-0.14.0.tgz
printf '%s  %s\n' 7329b73839edc1c7dadb407a4267d036fced4eff78ebf5a6840193111203731b "$QA_BRIDGE" | sha256sum --check
tar --extract --gzip --file "$QA_BRIDGE" --directory "$QA_TOOLS_DIR" package/dist/index.js
printf '%s  %s\n' 2f22205e47ab2992dd484cdc40991a76c2530e9243f8f0c73443b07a2544aa1c "$QA_TOOLS_DIR/package/dist/index.js" | sha256sum --check

[[ $(adb -s "$QA_SERIAL" shell id) == uid=0* ]]
adb -s "$QA_SERIAL" push "$QA_SERVER" /data/local/tmp/frida-server-17.25.2
adb -s "$QA_SERIAL" shell chmod 755 /data/local/tmp/frida-server-17.25.2
test "$(adb -s "$QA_SERIAL" shell /data/local/tmp/frida-server-17.25.2 --version | tr -d '\r')" = 17.25.2
QA_SERVER_SHA=$(sha256sum "$QA_SERVER" | cut -d ' ' -f 1)
test "$(adb -s "$QA_SERIAL" shell sha256sum /data/local/tmp/frida-server-17.25.2 | cut -d ' ' -f 1)" = "$QA_SERVER_SHA"
# Keep both the server and its host forward on loopback. The ADB subprocess is
# attached to this disposable job and is cleaned up with its Redroid container.
adb -s "$QA_SERIAL" shell /data/local/tmp/frida-server-17.25.2 -l 127.0.0.1:27042 \
  > "$QA_DOWNLOADS/frida-server.log" 2>&1 &
adb -s "$QA_SERIAL" forward tcp:27043 tcp:27042
"$QA_PYTHON_ENV/bin/python" - <<'PY'
import frida, time
for attempt in range(15):
    try:
        frida.get_device_manager().add_remote_device('127.0.0.1:27043').query_system_parameters()
        break
    except Exception:
        if attempt == 14:
            raise
        time.sleep(1)
PY
adb -s "$QA_SERIAL" forward --remove tcp:27043
"$QA_PYTHON_ENV/bin/python" - "$QA_REPORT" "$QA_TOOLS_DIR" "$QA_SERVER_SHA" <<'PY'
import hashlib, json, sys
from pathlib import Path
target, root, server_sha = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
report = {'status': 'READY', 'frida_version': '17.25.2', 'bridge_version': '0.14.0',
          'python_wheel_sha256': sha(root/'downloads/frida-17.25.2-cp37-abi3-manylinux_2_17_aarch64.whl'),
          'server_xz_sha256': sha(root/'downloads/frida-server-17.25.2-android-arm64.xz'),
          'installed_server_sha256': server_sha, 'bridge_script_sha256': sha(root/'package/dist/index.js'),
          'server_listen': '127.0.0.1:27042', 'host_forward': '127.0.0.1:27043'}
target.write_text(json.dumps(report, indent=2)+'\n')
PY
