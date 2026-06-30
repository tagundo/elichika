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
for personal sideloading. For a release-signed build, add a `signingConfig` and
use `assembleRelease`.

## Pointing the game at the server

Out of scope for this app — patch/redirect the SIFAS client to `127.0.0.1:8080`
the same way the Termux/embedded flows do (see the LL-hax wiki).
