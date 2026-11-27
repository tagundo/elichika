#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# != 2 || -e "$2" ]]; then
  echo "Usage: $0 android|playcover NEW_OUTPUT_FILE" >&2
  exit 2
fi
output=$2
staging=$(mktemp "$(dirname "$output")/.client-input.XXXXXXXX")
trap 'unlink "$staging" 2>/dev/null || true' EXIT
case "$1" in
  android)
    url=https://github.com/tagundo/elichika/releases/download/v2026.11.14.1/LLAS_GL_FOVMOD_b25.apk
    expected_size=83535736
    expected_sha=157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738
    curl --fail --silent --show-error --location --retry 2 --max-time 240 \
      --max-filesize "$expected_size" --output "$staging" "$url"
    ;;
  playcover)
    expected_size=66457006
    expected_sha=830cfccc9e5397b2c69536ff3bf6d9e1626ff5ec7c8e587b0e89d4bdb135f53e
    # The pinned input is the public GL Local v5 IPA with the older features
    # library and two Info.plist keys; rebuild_playcover_input.py restores it
    # byte for byte, and the checks below verify the result.
    public=$(mktemp "$(dirname "$output")/.client-public.XXXXXXXX")
    trap 'unlink "$staging" 2>/dev/null || true; unlink "$public" 2>/dev/null || true' EXIT
    curl --fail --silent --show-error --location --retry 2 --max-time 240 \
      --max-filesize 66457109 --output "$public" \
      https://github.com/tagundo/elichika/releases/download/v2026.11.14.1/SIFAS_GL_Local_3.12.0_PlayCover_v5.ipa
    unlink "$staging"
    python3 -I "$(dirname "$0")/rebuild_playcover_input.py" "$public" \
      "$(dirname "$0")/../ios/build/inputs/SIFASFeatures.dylib" "$staging"
    ;;
  *)
    echo "Unknown platform: $1" >&2
    exit 2
    ;;
esac
python3 - "$staging" "$expected_size" "$expected_sha" <<'PY'
import hashlib
import sys
from pathlib import Path

file = Path(sys.argv[1])
if file.stat().st_size != int(sys.argv[2]):
    raise SystemExit("Pinned input size does not match.")
with file.open("rb") as source:
    if hashlib.file_digest(source, "sha256").hexdigest() != sys.argv[3]:
        raise SystemExit("Pinned input SHA-256 does not match.")
PY
mv -- "$staging" "$output"
