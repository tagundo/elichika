#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
QA_PACKAGE=com.klab.lovelive.allstars.fovmod.codecqa
QA_ACTIVITY=com.klab.lovelive.allstars.fovmod.CodecQaActivity
QA_ARTIFACTS="$PWD/artifacts"
mkdir -p "$QA_ARTIFACTS"
QA_ADB="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}/platform-tools/adb"
test -x "$QA_ADB" || QA_ADB=adb
QA_SERIAL="${ANDROID_SERIAL:-}"
if test -z "$QA_SERIAL"; then
  mapfile -t QA_DEVICES < <("$QA_ADB" devices | awk 'NR>1 && $2=="device" {print $1}')
  test "${#QA_DEVICES[@]}" = 1 || { echo 'Expected exactly one adb target; set ANDROID_SERIAL explicitly' >&2; exit 2; }
  QA_SERIAL="${QA_DEVICES[0]}"
fi
qa_adb() { "$QA_ADB" -s "$QA_SERIAL" "$@"; }
QA_INSTALLED=0
qa_collect() {
  QA_EXIT=$?
  trap - EXIT
  set +e
  qa_adb logcat -d -v threadtime > "$QA_ARTIFACTS/logcat.txt" 2>&1
  qa_adb logcat -b crash -d -v threadtime > "$QA_ARTIFACTS/logcat-crash.txt" 2>&1
  qa_adb exec-out screencap -p > "$QA_ARTIFACTS/screenshot.png"
  qa_adb exec-out uiautomator dump /dev/tty > "$QA_ARTIFACTS/ui-tree.xml" 2>&1
  if test "$QA_INSTALLED" = 1; then
    qa_adb exec-out run-as "$QA_PACKAGE" tar -cf - files > "$QA_ARTIFACTS/app-files.tar"
    if tar -tf "$QA_ARTIFACTS/app-files.tar" >/dev/null 2>&1; then
      tar -xf "$QA_ARTIFACTS/app-files.tar" -C "$QA_ARTIFACTS"
    fi
    qa_adb shell am force-stop "$QA_PACKAGE" >/dev/null 2>&1
    qa_adb uninstall "$QA_PACKAGE" > "$QA_ARTIFACTS/uninstall.txt" 2>&1
  fi
  echo "$QA_EXIT" > "$QA_ARTIFACTS/runner-exit-code.txt"
  exit "$QA_EXIT"
}
trap qa_collect EXIT
qa_adb shell getprop > "$QA_ARTIFACTS/device-properties.txt"
qa_adb shell dumpsys media.codec > "$QA_ARTIFACTS/media-codec-before.txt"
qa_adb install -r build/codec-qa.apk
QA_INSTALLED=1
qa_adb shell pm clear "$QA_PACKAGE" | tee "$QA_ARTIFACTS/clear-qa-package.txt"
qa_adb logcat -c
qa_adb shell cmd package resolve-activity --brief "$QA_PACKAGE" | tee "$QA_ARTIFACTS/resolved-activity.txt"
qa_adb shell am start -W -n "$QA_PACKAGE/$QA_ACTIVITY" | tee "$QA_ARTIFACTS/launch.txt"
QA_DEADLINE=$((SECONDS + 480))
while (( SECONDS < QA_DEADLINE )); do
  QA_STATUS="$(qa_adb shell run-as "$QA_PACKAGE" cat files/status.txt 2>/dev/null | tr -d '\r' || true)"
  printf '%s\n' "$QA_STATUS" > "$QA_ARTIFACTS/last-status.txt"
  case "$QA_STATUS" in
    PASS*) echo "$QA_STATUS"; exit 0 ;;
    FAIL*) echo "$QA_STATUS" >&2; exit 1 ;;
  esac
  sleep 2
done
echo 'FAIL: codec QA exceeded 480 seconds' >&2
exit 124
