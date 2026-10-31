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

The Console groups full-width action buttons in a vertically scrolling menu.
Advanced actions and diagnostic logs start collapsed; expand them when needed.
Expanded logs have their own bounded scroll area, with Share and Clear controls,
and incoming log lines do not move the action menu.

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

The running-server notification includes a Stop action. Settings also offers an
automatic stop timer in minutes (0 disables it); the service owns the timer, so
resizing the app or entering split screen does not reset it. Changing the timer
while running starts a new countdown.

Split screen keeps the selected tab and WebView form state while the window
resizes. Developer and modding tools remain available during a costume install
while the game server is stopped. In Install Costume, enable automatic restart
to stop the server before the batch and restart it after successful completion.
An initially stopped server stays stopped. A failed installation or a manual
Stop leaves it stopped so you can inspect the log before continuing.

## What CI assembles before `gradle assembleDebug`

The Go binary, the bundled data payload and the embedded Python sources are
**not committed** — `.github/workflows/android.yml` produces them:

- `app/src/main/jniLibs/arm64-v8a/libelichika.so` — the server, cross-compiled
  for `android/arm64` (NDK r28c, cgo and external linking with 16 KB alignment)
  from the normal (`!embedded`) build. ASTC uses the same NDK with flexible page sizes.
- `app/native-wheels/` — a source-pinned FreeType 2.9.1 wheel rebuilt with 16 KB
  alignment. Pillow's published Chaquopy dependency still uses 4 KB alignment;
  the local wheel preserves its ABI, SONAME and license. OpenBLAS 0.3.33 is also
  rebuilt with C LAPACK, replacing the legacy Fortran runtime whose 4 KB RELRO
  boundary made mutable data read-only on 16 KB kernels. Both libraries retain
  the SONAMEs expected by Pillow/NumPy and bundle their licenses.
- `app/src/main/assets/payload/` — `server init jsons/`, `webui/` (`.go` stripped),
  `privatekey.pem`, `publickey.pem`, the Harasho master-data tree, and a prebuilt
  `serverdata.db` (built on the runner via `rebuild_assets`). Extracted to the
  app files dir by `AssetInstaller`. Configuration is created on the device;
  account databases and user configuration are never included in the payload.
- `app/src/main/python/` — `adminui/` and the dev installer scripts (this repo),
  plus `webtools/` and the modding scripts from the **`modtools/` git submodule**
  (SIFAS-MODDING-HELPING-TOOLS), alongside the committed `elichika_launch.py`. CI
  updates the submodule's tracked `claude/elichika-apk-build-wwkuu3` branch for
  ordinary development builds. The `codex/console-tools-release` preflight branch,
  tag builds and runs with `release_tag` keep the exact submodule commit recorded
  in the server repository. Before publishing, commit
  and push the modding-tool changes, then commit the updated `modtools` gitlink
  in elichika so the release contains the reviewed tools.

## Building locally

You need the Android SDK, NDK `28.2.13676358`, JDK 17 and Python 3.13. Chaquopy
17 embeds Python 3.13, and its build interpreter must use the same major/minor
version. Assemble the payload/jniLibs/python the same way
CI does (see the workflow), then:

```
cd android
./gradlew :app:assembleDebug
```

To build from locally prepared Android wheels without contacting any Python
package index, pass `-PchaquopyWheelhouse=/absolute/path/to/wheels`. The wheelhouse
must contain each pinned dependency and its transitive Android dependencies.
`-PbuildPython=/path/to/python3.13` selects the matching host interpreter.
The default APK targets ARM64; `-PappAbi=x86_64` builds a native emulator variant
when the corresponding Go/ASTC binaries and local native wheels are prepared.

APK CI fetches the immutable dependency commit
`39b2279db6cf111e2c353cd4880c58e3607837da` from this repository (published on
`build/android-python-wheels`) and extracts its manifest and eight wheels into
the runner's temporary directory. `android/ci/verify_python_wheelhouse.py` checks
the manifest schema, Python/NDK/ABI, complete file set, sizes, SHA-256 hashes,
wheel tags and native ELF architecture before Gradle runs. All APK and
instrumentation builds use that verified wheelhouse with `--no-index`, so pip
does not contact Python package indexes. FreeType and OpenBLAS continue to be
rebuilt from their pinned sources by the consuming workflow.

For x86_64 QA, the pinned `modernc.org/libc` Linux implementation uses legacy
filesystem syscalls rejected by Android's app seccomp policy. Build its Go
binary with the scoped overlay helper before selecting `-PappAbi=x86_64`:

```sh
python3 android/ci/build_go_x86_qa.py --ndk "$ANDROID_NDK_ROOT" \
  --work /tmp/elichika-x86-qa \
  --output android/app/src/main/jniLibs/x86_64/libelichika.so
```

Run this command from the repository root with Go on `PATH`. It preserves the
dependency pins and module cache, replaces the relevant amd64 filesystem calls
with their equivalent `*at` calls for this build, and records the patch, hashes
and command in the work directory. The normal ARM64 build does not use it.

The debug-signed APK at `app/build/outputs/apk/debug/app-debug.apk` is installable
for personal sideloading. Every build shares one committed debug key
(`app/elichika-debug.keystore`, password `android`) so updates install over each
other without an uninstall. That key is public — fine for sideloading, but do NOT
use it for public distribution (anyone could sign a same-identity "update").

## Native page-size verification

APK CI runs `android/ci/audit_native.py` on the finished release APK. It checks
every ARM64 ELF load segment, including Python extensions and dependent libraries
inside Chaquopy's `.imy` ZIP assets. A 4 KB-only file, incompatible segment
mapping, or RELRO boundary which protects adjacent mutable data blocks the build. Keep legacy native-library extraction enabled: the Go
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
