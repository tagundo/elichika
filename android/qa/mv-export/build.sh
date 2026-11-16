#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
QA_ROOT="$PWD"
QA_SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
test -n "$QA_SDK" || { echo 'ANDROID_SDK_ROOT or ANDROID_HOME is required' >&2; exit 2; }
QA_TOOLS="$QA_SDK/build-tools/34.0.0"
QA_ANDROID_JAR="$QA_SDK/platforms/android-34/android.jar"
for QA_REQUIRED in "$QA_TOOLS/aapt" "$QA_TOOLS/d8" "$QA_TOOLS/zipalign" "$QA_TOOLS/apksigner" "$QA_ANDROID_JAR"; do
  test -f "$QA_REQUIRED" || { echo "Missing existing SDK tool: $QA_REQUIRED" >&2; exit 2; }
done
if command -v javac >/dev/null; then
  QA_JAVAC=(javac)
else
  java com.sun.tools.javac.Main -version >/dev/null
  QA_JAVAC=(java com.sun.tools.javac.Main)
fi
command -v keytool >/dev/null
mkdir -p build/classes build/dex build/package
find src -name '*.java' -print | LC_ALL=C sort > build/sources.list
test -s build/sources.list
"${QA_JAVAC[@]}" -parameters -encoding UTF-8 -source 8 -target 8 -bootclasspath "$QA_ANDROID_JAR" -d build/classes @build/sources.list
find build/classes -name '*.class' -print | LC_ALL=C sort > build/classes.list
"$QA_TOOLS/d8" --min-api 21 --lib "$QA_ANDROID_JAR" --output build/dex @build/classes.list
"$QA_TOOLS/aapt" package -f -M AndroidManifest.xml -I "$QA_ANDROID_JAR" -F build/package/unsigned.apk
cp build/dex/classes.dex build/package/classes.dex
(cd build/package && zip -q -0 unsigned.apk classes.dex)
"$QA_TOOLS/zipalign" -f 4 build/package/unsigned.apk build/package/aligned.apk
if test ! -f build/qa-debug.jks; then
  keytool -genkeypair -keystore build/qa-debug.jks -storepass android -keypass android -alias qa-debug -keyalg RSA -keysize 2048 -validity 2 -dname 'CN=Isolated Codec QA' -noprompt >/dev/null 2>&1
fi
"$QA_TOOLS/apksigner" sign --ks build/qa-debug.jks --ks-pass pass:android --key-pass pass:android --out build/codec-qa.apk build/package/aligned.apk
"$QA_TOOLS/apksigner" verify build/codec-qa.apk
sha256sum build/codec-qa.apk > build/codec-qa.apk.sha256
echo "Built $QA_ROOT/build/codec-qa.apk"
