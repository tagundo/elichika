# Elichika for macOS

Elichika's macOS companion packages the Go server, Python tools and the same web
editor used by Android into `Elichika.app`. It supports Apple Silicon and macOS
13 or later. The app includes its own Python interpreter, wheels, Go executable
and ASTC encoder; users do not install Python, Go, Homebrew or pip.

## Shared code and native integration

- Go game services, Python tools, payload migrations, Node Scaling, Mesh Baker,
  recipes and the Three.js viewer are shared with Android.
- `modtools/webtools/web/static/platform.js` adapts native file selection,
  reveal, full-screen, keyboard commands and language changes. Desktop layouts
  rearrange the same editor components; Android keeps its touch layout.
- `App/` implements the SwiftUI sidebar, menus, file panels, WebKit integration
  and owned runtime lifecycle.
- `runtime/` hosts the existing Python panels and owns the Go child. Native
  controls use a per-launch bearer capability. The tool panels use a separate
  session, exact loopback Host/Origin checks and HttpOnly cookies.
- `build/` pins and bundles native dependencies; `ci/` validates the finished
  app, source provenance, private library paths and actual execution.

## Running the app

Download the validated Apple Silicon app archive from the macOS workflow,
extract it and open `Elichika.app`. The first launch prepares writable game
data while displaying progress. The game server starts only when requested;
the asset editor is available independently.

The review build is ad-hoc signed and is not Apple-notarized. macOS may require
approval in Privacy & Security for an app downloaded from the Internet.

Data, accounts, configuration, pack caches and backups live outside the app at
`~/Library/Application Support/Elichika`. The default library is its
`sukusta/` directory. Moving or updating the app preserves those files.
Existing owner configuration and database modifications are preserved by the
same transactional payload update engine used on Android.

The server initially listens on `127.0.0.1:8080`. Stop it before changing the
server address and CDN address in Settings. To connect a phone on the same
network, configure the desired listening address and the Mac's reachable CDN
URL. The Python editor and native control endpoints remain private loopback
services.

Use **Open** / **Command-O** for native model selection, **Command-S** to save
body edits, and **Show in Finder** for selected or generated files. The editor
retains the same Node Scaling / Mesh Baker methods and source-bound recipe
format on both platforms. Saved result inspection and re-editing from preserved
originals are shared implementations.

Pose/body and expression controls have separate collapsible panels. Common body
parts use a selection list. In a wide window, drag either boundary beside the 3D
preview to share the width between file selection, the model and its controls.
Both boundaries support left/right arrow keys. Home or **Default layout** in the
file selection area restores both widths. macOS remembers the chosen widths
across app launches independently of the private WebKit session.

Quitting the app stops its owned Python runtime and Go child. It does not find
or kill unrelated servers by executable name.

## Build and validation

The `Build standalone macOS Apple Silicon app` workflow in
[macos.yml](../.github/workflows/macos.yml) builds the actual reviewed source and
submodule pin. Its optional `version` input overrides the checked-in
[macOS app version](VERSION), which uses the Korean calendar date. The workflow
generates the official server data using the Android migration/order/determinism
sequence, then packages the private runtime.

On an Apple Silicon Mac with Xcode command-line tools, Go 1.22.12 and Python 3.12
available as build tools, the packaging entry points are:

```sh
python3 macos/build/build_payload.py --repo . --output /tmp/elichika-shared
python3 macos/build/build_app.py --repo . --shared /tmp/elichika-shared \
  --output /tmp/elichika-built/Elichika.app --cache /tmp/elichika-build-cache \
  --version 2026.11.06.2 --report /tmp/elichika-build.json
```

The source checkout must first contain initialized, ordered and deterministically
generated game data as shown in the workflow. Build downloads are pinned by
version and SHA-256; the packaged app performs no dependency installation.

The workflow checks:

- Shared CLI path handling and preservation of Android/Termux defaults.
- Python runtime authentication, native file authorization, data updates,
  server control, port conflicts and parent/child shutdown.
- Swift native contract tests and shared HTTP/Unity/WebGL editor regressions.
- Bundled Python imports, numerical work, image/ASTC codecs and Archive.org HTTPS
  using bundled certificate roots.
- Every Mach-O dependency and symlink resolves to the bundle or macOS system
  libraries, with no build-host Python or Homebrew dependency.
- The actual signed app starts, controls Go, edits and saves a model, reloads it,
  quits cleanly, moves to a path containing spaces and Korean characters, and
  launches again with the same user data.
- Bundled contents remain read-only and the signature verifies after both launches.
  The outer app directory keeps normal owner permissions so Finder can move it.

The resulting `.app.zip`, `SHA256SUMS` and execution evidence are uploaded as
workflow artifacts. Packaging does not merge code or publish a GitHub release.
