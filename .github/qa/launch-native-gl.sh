#!/usr/bin/env bash
# Run on a dedicated Linux ARM64 Actions runner with a candidate Go server on port 8080.
set -euo pipefail

[[ $(uname -m) == aarch64 ]] || { printf '%s\n' 'An ARM64 game runner is required.' >&2; exit 2; }
evidence=${1:?Usage: launch-native-gl.sh EVIDENCE_DIR [screen|assets]}
mode=${2:-screen}
[[ $mode == screen || $mode == assets ]]
mkdir -p "$evidence"
evidence=$(realpath "$evidence")
workspace=$(mktemp -d "${RUNNER_TEMP:-/tmp}/stock-gl-game.XXXXXX")
container=stock-gl-${workspace##*.}
apk=$workspace/public-b25.apk
serial=
game=com.klab.lovelive.allstars.global
activity=$game.GlobalUnsafeMainActivity
native_image=redroid/redroid@sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa
release=https://github.com/tagundo/elichika/releases/download/v2026.11.14.1/LLAS_GL_FOVMOD_b25.apk
digest=157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738

collect() {
    if [[ -n $serial ]]; then
        timeout 8 adb -s "$serial" logcat -d -v threadtime > "$evidence/android-logcat.txt" 2>&1 || true
        timeout 8 adb -s "$serial" shell dumpsys activity activities > "$evidence/android-activities.txt" 2>&1 || true
        timeout 8 adb -s "$serial" shell dumpsys SurfaceFlinger --list > "$evidence/android-layers.txt" 2>&1 || true
        timeout 8 adb -s "$serial" exec-out screencap -p > "$evidence/android-screen.png" || true
        timeout 8 adb -s "$serial" reverse --remove tcp:8080 >/dev/null 2>&1 || true
        adb disconnect "$serial" >/dev/null 2>&1 || true
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker network rm "$container" >/dev/null 2>&1 || true
    docker volume rm "$container" >/dev/null 2>&1 || true
    rm -f -- "$apk" "$workspace/device-http.txt"
    rmdir -- "$workspace"
}
trap collect EXIT

curl --silent --show-error --max-time 5 --output /dev/null \
     --write-out 'Candidate HTTP status %{http_code}\n' http://127.0.0.1:8080/webui/user/ | tee "$evidence/host-http.txt"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
     --retry 2 --max-time 180 --max-filesize 85000000 --output "$apk" "$release"
printf '%s  %s\n' "$digest" "$apk" | sha256sum --check | tee "$evidence/apk-sha256.txt"
apksigner verify "$apk"

sudo modprobe binder_linux devices=binder,hwbinder,vndbinder || {
    sudo apt-get install -y "linux-modules-extra-$(uname -r)"
    sudo modprobe binder_linux devices=binder,hwbinder,vndbinder
}
docker pull --platform linux/arm64 "$native_image"
network_flags=()
[[ $mode != screen ]] || network_flags=(--internal)
docker network create "${network_flags[@]}" "$container" >/dev/null
docker volume create "$container" >/dev/null
docker run --detach --privileged --name "$container" --network "$container" \
    --volume "$container:/data" "$native_image" androidboot.use_memfd=true \
    androidboot.redroid_gpu_mode=guest androidboot.redroid_width=720 \
    androidboot.redroid_height=1280 androidboot.redroid_fps=20 ro.secure=0 >/dev/null
serial=$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container"):5555
[[ $serial != :5555 ]]

device() { timeout 12 adb -s "$serial" "$@"; }
deadline=$((SECONDS + 240))
while :; do
    adb connect "$serial" >/dev/null 2>&1 || true
    if [[ $(timeout 4 adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true) == 1 ]]; then
        break
    fi
    (( SECONDS < deadline )) || { printf '%s\n' 'ARM64 Android failed to boot.' >&2; exit 1; }
    sleep 2
done
[[ $(device shell getprop ro.product.cpu.abi | tr -d '\r') == arm64-v8a ]]
device shell getprop > "$evidence/android-properties.txt"
device shell settings --user 0 put secure immersive_mode_confirmations confirmed
device reverse tcp:8080 tcp:8080
device reverse --list > "$evidence/reverse.txt"
# Some toybox netcat builds close the socket as soon as stdin closes. Keep
# the pipe open briefly and preserve evidence even when this optional probe
# exits before it can read the reply. The game request is checked separately.
device shell "{ printf 'GET /webui/user/ HTTP/1.0\\r\\nHost: localhost:8080\\r\\n\\r\\n'; sleep 2; } | toybox nc -w 5 127.0.0.1 8080" \
    > "$workspace/device-http.txt" 2>&1 || true
head -n 3 "$workspace/device-http.txt" > "$evidence/device-http.txt"

if device shell pm path "$game" | grep -q '^package:'; then
    printf '%s\n' 'The disposable Android system already has the game installed.' >&2
    exit 1
fi
timeout 120 adb -s "$serial" install "$apk"
device logcat -c
device shell am start -W -n "$game/$activity" | tee "$evidence/native-activity-start.txt"
grep -q '^Status: ok' "$evidence/native-activity-start.txt"
deadline=$((SECONDS + 150))
while :; do
    pid=$(device shell pidof "$game" | tr -d '\r' || true)
    layers=$(device shell dumpsys SurfaceFlinger --list || true)
    if [[ $pid =~ ^[0-9]+$ ]] && grep -F 'SurfaceView' <<< "$layers" | grep -Fq "$game"; then
        printf '%s\n' "$pid" > "$evidence/game-pid.txt"
        printf '%s\n' "$layers" > "$evidence/first-unity-surface.txt"
        device exec-out screencap -p > "$evidence/first-unity-surface.png"
        break
    fi
    (( SECONDS < deadline )) || { printf '%s\n' 'ARM64 SIFAS Unity SurfaceView did not appear.' >&2; exit 1; }
    sleep 2
done

if [[ -n ${ELICHIKA_GAME_QA_FOLLOWUP:-} ]]; then
    # A separate private UI sequence can supply calibrated taps after the first proof.
    # It receives only the owned Android serial and QA evidence directory.
    bash "$ELICHIKA_GAME_QA_FOLLOWUP" "$serial" "$evidence" "$mode"
fi
