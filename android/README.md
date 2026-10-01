# elichika standalone Android app

A single installable APK that runs the elichika server (and its dev/modding
tools) on a phone, replacing the Termux + `bin/install.sh` flow. The actual
SIFAS game (a separate APK) connects to this app's local server at
`127.0.0.1:8080`.

This module lives **inside the elichika repo on purpose**: the app is versioned
with the server, so a server change and the app that ships it land together.

## What runs inside the app

| Service | What | Port | How |
|---------|------|------|-----|
| elichika server | the Go binary `libelichika.so` | 8080 | subprocess (`ServerProcess`) under a foreground `ServerService` |
| adminui | elichika dev tools web UI (stdlib `http.server`) | 8772 | embedded Python (Chaquopy), `elichika_launch.py` |
| webtools | SIFAS modding tools web UI (stdlib `http.server`) | 8770 | embedded Python (Chaquopy), `elichika_launch.py` |

The UI (`MainActivity`) is a thin shell: a Start/Stop button, a Console tab with
buttons generated from `assets/actions.json`, and three WebView tabs for the
server WebUI and the two tool web UIs.

## Maintainability: how to add features without touching Kotlin

- **New dev/mod tool** → add an entry to `adminui/tools/registry.py` (this repo)
  or `webtools/tools/registry.py` (SIFAS-MODDING-HELPING-TOOLS). It appears in
  the corresponding WebView tab automatically.
- **New server page / endpoint** → add it in Go (`handler/`, `webui/`); it shows
  up under the Server WebUI tab automatically.
- **New menu action** (run a CLI verb, open a URL) → add one object to
  `app/src/main/assets/actions.json`. No Kotlin change.

The Kotlin layer only knows how to: run the binary, host WebViews, and dispatch
`actions.json`. It contains no server or tool logic.

## What CI assembles before `gradle assembleDebug`

The Go binary, the bundled data payload and the embedded Python sources are
**not committed** — `.github/workflows/android.yml` produces them:

- `app/src/main/jniLibs/arm64-v8a/libelichika.so` — the server, cross-compiled
  for `android/arm64` (NDK r28c, cgo and external linking with 16 KB alignment)
  from the normal (`!embedded`) build. ASTC uses the same NDK with flexible page sizes.
- `app/native-wheels/` — a source-pinned FreeType 2.9.1 wheel rebuilt with 16 KB
  alignment. Pillow's published Chaquopy dependency still uses 4 KB alignment;
  the local wheel preserves its ABI, SONAME and license.
- `app/src/main/assets/payload/` — `server init jsons/`, `webui/` (`.go` stripped),
  `privatekey.pem`, `publickey.pem`, the Harasho master-data tree, and a prebuilt
  `serverdata.db` (built on the runner via `rebuild_assets`). Extracted to the
  app files dir by `AssetInstaller`. Configuration is created on the device;
  account databases and user configuration are never included in the payload.
- `app/src/main/python/` — `adminui/` and the dev installer scripts (this repo),
  plus `webtools/` and the modding scripts from the **`modtools/` git submodule**
  (SIFAS-MODDING-HELPING-TOOLS), alongside the committed `elichika_launch.py`. CI
  updates the submodule's tracked `claude/elichika-apk-build-wwkuu3` branch before building, so the app
  ships the newest tools; elichika no longer vendors its own (stale) copies.

## Building locally

You need the Android SDK, NDK `28.2.13676358`, JDK 17 and Python 3.13. Chaquopy
17 embeds Python 3.13, and its build interpreter must use the same major/minor
version. Assemble the payload/jniLibs/python the same way
CI does (see the workflow), then:

```
cd android
./gradlew :app:assembleDebug
```

The debug-signed APK at `app/build/outputs/apk/debug/app-debug.apk` is installable
for personal sideloading. Every build shares one committed debug key
(`app/elichika-debug.keystore`, password `android`) so updates install over each
other without an uninstall. That key is public — fine for sideloading, but do NOT
use it for public distribution (anyone could sign a same-identity "update").

## Native page-size verification

APK CI runs `android/ci/audit_native.py` on the finished release APK. It checks
every ARM64 ELF load segment, including Python extensions and dependent libraries
inside Chaquopy's `.imy` ZIP assets. A 4 KB-only file or incompatible segment
mapping blocks the build. Keep legacy native-library extraction enabled: the Go
server and ASTC binaries execute from `nativeLibraryDir`.

The same signed APK then undergoes signer/payload verification, an Android 14
in-place upgrade and native-package instrumentation, and native execution on
official 4 KB/16 KB ARM kernels. The latter runs the original Go server, CPython,
Python compression/image/numerical modules and ASTC; game API checks use synthetic
accounts. The kernel VM has no Android framework or Chaquopy Java bridge. Android
instrumentation covers the real Java bridge separately on the 4 KB Android host.
Physical-device and original-game-client behavior require further device checks.

Run **Build Android APK** with an empty `release_tag` to generate APKs and all
verification artifacts without publication. Inspect the native layout, runtime,
instrumentation and signed-APK audit artifacts for the exact APK digest tested.

## Publishing a public release (GitHub Releases)

For public distribution, sign with a PRIVATE key that only you hold, so only you
can issue updates. One-time setup:

1. Create a release keystore locally (keep the file + passwords safe, back them
   up — losing them means you can never update the app again):
   ```
   keytool -genkeypair -v -keystore elichika-release.keystore \
     -alias elichika -keyalg RSA -keysize 2048 -validity 10000 \
     -storepass '<STORE_PW>' -keypass '<KEY_PW>' \
     -dname "CN=elichika, O=elichika, C=US"
   ```
2. Add four repository secrets (Settings → Secrets and variables → Actions):
   - `RELEASE_KEYSTORE_BASE64` — `base64 -w0 elichika-release.keystore`
   - `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS` (=`elichika`), `RELEASE_KEY_PASSWORD`
3. Choose a CalVer tag, such as `v2026.10.01.1`. CI derives `versionName` and a
   strictly increasing `versionCode` from it.
4. Push that tag, or supply it as `release_tag` in **Build Android APK**.

CI builds `assembleRelease` signed with your private key and publishes it only
after the APK audit, Android upgrade and 4 KB/16 KB native execution checks pass.
Without the secrets, local builds fall back to the debug key; the official-signer
continuity check prevents that key from passing the publication gate. Users who had a debug-signed build installed must uninstall once when
switching to the release-signed APK (different signature); after that, tagged
releases update in place.

## Pointing the game at the server

Out of scope for this app — patch/redirect the SIFAS client to `127.0.0.1:8080`
the same way the Termux/embedded flows do (see the LL-hax wiki).
