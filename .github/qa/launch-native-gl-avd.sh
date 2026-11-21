#!/usr/bin/env bash
# Disposable Linux x86_64 runner with an official Google Play Android image.
set -euo pipefail

evidence=${1:?Usage: launch-native-gl-avd.sh EVIDENCE_DIR [screen|assets]}
mode=${2:-screen}
api=${QA_AVD_API:-30}
[[ $api == 30 || $api == 32 || $api == 34 ]]
[[ $(uname -m) == x86_64 && -e /dev/kvm ]]
[[ $mode == screen || $mode == assets ]]
mkdir -p "$evidence"
evidence=$(realpath "$evidence")
sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:?Installed Android SDK is required}}
sdk_tools=$sdk/cmdline-tools/latest/bin
system_image="system-images;android-$api;google_apis_playstore;x86_64"
scratch=$(mktemp -d "${RUNNER_TEMP:-/tmp}/stock-gl-avd.XXXXXX")
export ANDROID_AVD_HOME="$scratch/avds"
mkdir "$ANDROID_AVD_HOME"
avd=stock_gl_${api}_${scratch##*.}
serial=emulator-5554
apk=$scratch/public-b25.apk
game=com.klab.lovelive.allstars.global
activity=$game.GlobalUnsafeMainActivity
release=https://github.com/tagundo/elichika/releases/download/v2026.11.14.1/LLAS_GL_FOVMOD_b25.apk
digest=157f92a46fcaefaca52c2c8209b35e059773be62fc74a8c8e20c2ac3f9dea738
emulator_pid=

device() { timeout 25 adb -s "$serial" "$@"; }
collect() {
    if [[ -n $emulator_pid ]]; then
        device logcat -d -v threadtime > "$evidence/android-logcat.txt" 2>&1 || true
        device shell dumpsys SurfaceFlinger --list > "$evidence/android-layers.txt" 2>&1 || true
        device exec-out screencap -p > "$evidence/android-screen.png" || true
        device exec-out uiautomator dump /dev/tty > "$evidence/android-ui.xml" 2>&1 || true
        device reverse --remove tcp:8080 >/dev/null 2>&1 || true
        device emu kill >/dev/null 2>&1 || kill "$emulator_pid" 2>/dev/null || true
    fi
    rm -f -- "$apk"
    # The runner owns the entire temporary AVD directory and removes it at job exit.
}
trap collect EXIT

if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then sudo chmod 0666 /dev/kvm; fi
test -r /dev/kvm -a -w /dev/kvm
test -x "$sdk_tools/sdkmanager" -a -x "$sdk_tools/avdmanager"
if adb devices | grep -q "^$serial[[:space:]]"; then
    printf '%s\n' 'Another device already owns emulator-5554.' >&2
    exit 1
fi

python3 -c 'print("y\n" * 256)' | "$sdk_tools/sdkmanager" --licenses > "$scratch/sdk-licenses.txt"
"$sdk_tools/sdkmanager" --install emulator "$system_image" > "$scratch/sdk-install.txt"
printf 'no\n' | "$sdk_tools/avdmanager" create avd --name "$avd" --package "$system_image" \
    --path "$ANDROID_AVD_HOME/$avd.avd" --device pixel_4 > "$scratch/avd-create.txt"
printf '%s\n' "$system_image" > "$evidence/android-system-image.txt"
"$sdk/emulator/emulator" -avd "$avd" -port 5554 -accel on -no-window -no-snapshot \
    -gpu swangle -no-boot-anim -camera-back none -camera-front none \
    > "$evidence/emulator-start.txt" 2>&1 &
emulator_pid=$!

deadline=$((SECONDS + 240))
while :; do
    if [[ $(timeout 5 adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true) == 1 ]]; then
        break
    fi
    kill -0 "$emulator_pid"
    (( SECONDS < deadline )) || { printf '%s\n' 'The official Google Play AVD did not boot.' >&2; exit 1; }
    sleep 2
done

{
    for key in ro.build.fingerprint ro.product.cpu.abilist ro.product.cpu.abilist64 ro.dalvik.vm.native.bridge ro.opengles.version; do
        printf '%s=' "$key"
        device shell getprop "$key" | tr -d '\r'
    done
    device shell pm path com.google.android.gms
    device shell pm path com.android.vending
} | tee "$evidence/gms-arm64-preflight.txt"
grep -Eq '^ro.product.cpu.abilist64=([^,]+,)*arm64-v8a(,|$)' "$evidence/gms-arm64-preflight.txt"
grep -Eq '^ro.dalvik.vm.native.bridge=lib[^[:space:]]+\.so$' "$evidence/gms-arm64-preflight.txt"
[[ $(grep -c '^package:' "$evidence/gms-arm64-preflight.txt") -ge 2 ]]

device shell input keyevent KEYCODE_WAKEUP
device shell wm dismiss-keyguard
device shell settings --user 0 put secure immersive_mode_confirmations confirmed
device reverse tcp:8080 tcp:8080
device reverse --list > "$evidence/reverse.txt"
device shell "{ printf 'GET /webui/user/ HTTP/1.0\\r\\nHost: localhost:8080\\r\\n\\r\\n'; sleep 2; } | toybox nc -w 5 127.0.0.1 8080" \
    > "$scratch/device-http.txt" 2>&1 || true
head -n 3 "$scratch/device-http.txt" > "$evidence/device-http.txt"

curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --retry 2 --max-time 180 --max-filesize 85000000 --output "$apk" "$release"
printf '%s  %s\n' "$digest" "$apk" | sha256sum --check | tee "$evidence/apk-sha256.txt"
apksigner verify "$apk"
if device shell pm path "$game" | grep -q '^package:'; then
    printf '%s\n' 'This temporary AVD unexpectedly contains the game.' >&2
    exit 1
fi
timeout 150 adb -s "$serial" install "$apk"
device logcat -c
timeout 60 adb -s "$serial" shell am start -W -n "$game/$activity" | tee "$evidence/native-activity-start.txt"
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
    (( SECONDS < deadline )) || { printf '%s\n' 'The translated SIFAS Unity SurfaceView did not appear.' >&2; exit 1; }
    sleep 2
done
if [[ -n ${ELICHIKA_GAME_QA_FOLLOWUP:-} ]]; then
    bash "$ELICHIKA_GAME_QA_FOLLOWUP" "$serial" "$evidence" "$mode"
fi
