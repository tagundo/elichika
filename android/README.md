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
  for `android/arm64` (NDK, cgo) from the normal (`!embedded`) build.
- `app/src/main/assets/payload/` — `server init jsons/`, `webui/` (`.go` stripped),
  `privatekey.pem`, `publickey.pem`, a default `config.json`, and a prebuilt
  `serverdata.db` (built on the runner via `rebuild_assets`). Extracted to the
  app files dir on first launch by `AssetInstaller`.
- `app/src/main/python/` — `adminui/` and the dev installer scripts (this repo),
  plus `webtools/` and the modding scripts from the **`modtools/` git submodule**
  (SIFAS-MODDING-HELPING-TOOLS), alongside the committed `elichika_launch.py`. CI
  bumps the submodule to its latest `main` before building, so the app always
  ships the newest tools; elichika no longer vendors its own (stale) copies.

## Building locally

You need the Android SDK + NDK. Assemble the payload/jniLibs/python the same way
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
3. Bump `versionCode` (must increase) and `versionName` in `app/build.gradle.kts`.
4. Tag and push: `git tag v0.1.2 && git push origin v0.1.2`.

CI then builds `assembleRelease` signed with your private key and attaches the
APK to a GitHub Release. Without the secrets, the release build falls back to the
debug key (so PR/local builds still work), so make sure the secrets are set before
you tag. Users who had a debug-signed build installed must uninstall once when
switching to the release-signed APK (different signature); after that, tagged
releases update in place.

## Pointing the game at the server

Out of scope for this app — patch/redirect the SIFAS client to `127.0.0.1:8080`
the same way the Termux/embedded flows do (see the LL-hax wiki).
