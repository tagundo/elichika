# Disposable original-client UI observer

This observer reads the actual running Unity UI. It does not patch or resign the
game APK, invoke button callbacks, alter player state, or bypass game networking.
Only the bridge's main-thread scheduling callback is installed in memory.
The driver performs normal `adb shell input tap` operations using reported live
RectTransform coordinates. It must retain the client/server APK hashes in its
evidence and independently check screenshots, server requests, and UI transitions.

## Pinned setup

- Frida Python package and Android ARM64 server: **16.6.6**, both the same version.
- `frida-il2cpp-bridge`: **0.9.1**, exact version and tarball integrity in
  `package-lock.json`. This release uses the Frida 16 export API; do not upgrade
  only one part to Frida 17/bridge 0.14.
- Official server download:
  `https://github.com/frida/frida/releases/download/16.6.6/frida-server-16.6.6-android-arm64.xz`
- Bridge sources/docs: <https://github.com/vfsfitvnm/frida-il2cpp-bridge>.
  The used API signatures are present in the pinned package's `dist/index.d.ts`.

The parent runner owns the ephemeral Frida server. Bind its listener to the
disposable device's loopback and use an adb forward. Do not expose it publicly.

Build the standalone agent without `frida-compile`:

```sh
cd /workspace/client-validation/qa
npm ci --ignore-scripts
python3 bundle_unity_ui.py
node --check unity_ui.bundle.js
```

## Driver contract

Attach the read-only observer to the settings process before its normal Save and Launch action to capture startup splash timing. The bridge waits for IL2CPP; game reads execute only after initialization on the Unity main thread.
Load `unity_ui.bundle.js` using the Frida Python API, then retain messages from
the script. `status()` is nonblocking; `initialize()`, `snapshot()`, `pick()` and
`classes()` are asynchronous RPC calls executed on the Unity main thread.

```python
script = session.create_script(Path('unity_ui.bundle.js').read_text())
script.on('message', record_message)
script.load()
status = script.exports_sync.status()
script.exports_sync.initialize()
tree = script.exports_sync.snapshot({'maxNodes': 1200, 'raycastText': True})
target = script.exports_sync.pick({'textAny': ['START', 'Tap to Start'],
                                   'exact': True, 'requireHitTest': True})
# Compare tree['screen']['width'/'height'] to the real Android display/window
# bounds. Fail on an unexplained coordinate-space mismatch.
x, y = target['input']['x'], target['input']['y']
adb('shell', 'input', 'tap', str(x), str(y))
```

RPC methods:

- `status()` returns bridge/Frida versions, initialization error, architecture.
- `snapshot(options)` returns live scene/frame, Unity screen dimensions, active
  Button/Toggle/InputField/TMP_InputField/Text/TMP nodes, hierarchy paths, labels, interactable
  flags, world-corner-derived bounds, clipped bounds, and Android-origin centers.
  Canvas render cameras and parent masks/CanvasGroups are considered. EventSystem
  raycasts report whether a modal or another graphic obscures the proposed tap.
  `input` metadata reports `focused`, `readOnly`, `password`, `contentType`,
  `inputType`, value length, and redaction state. Only the exact disposable numeric
  test ID `893611090` is echoed (`numericTestId` can identify a different numeric
  test ID explicitly); passwords and other entered values remain redacted.
  Custom button/click/touchable/EventTrigger component classes are discovered
  from at most 600 active RectTransforms. Set `customButtons=False` to disable
  this extra read-only enumeration, or pass explicit `extraTypes`.
- `pick(query)` takes `id`, `text`, `textAny`, `name`, `path`, optional `kind`,
  `exact` (default true), `requireHitTest`, and optional custom `extraTypes`.
  It rejects absent or ambiguous targets. A button and its caption deduplicate
  to the same parent action. It returns coordinates without touching the game.
- `classes(pattern, maximum)` lists matching real runtime class metadata.
  If the game uses custom UI components, discover them and pass exact class names
  through `snapshot({'extraTypes': [...]})`. No arbitrary game methods are called.

Save the complete tree before/after every action. Do not use `pick` output from
an older scene/frame after a popup or transition. Screen coordinates come from
live UI geometry; screenshots are evidence, not a source of guessed tap locations.

## Honest limits

The observer is prepared from official bridge API signatures and syntax checked;
it is not runtime-validated until it attaches to the real client's Unity process.
IL2CPP symbols can be stripped, Unity synchronization context can be unavailable
during early startup, or the game may use custom UI outside standard uGUI/TMP.
Backgrounding the game can pause its main thread and an RPC; foreground it and
bound driver waits. Treat unavailable geometry/raycast metadata as a diagnostic,
not as proof that a game button is usable. `requireHitTest=True` fails safely when
the actual Unity hit test cannot be performed. Do not weaken a failed login/home/
member/MV assertion based only on observer readiness or server API success.

The current workflow binds GL b22 and JP b23 to exact assets, a stable public signing certificate, and a fresh source-built ARM64 Go fixture from frozen C4. Source-build game RPC evidence does not claim server APK installation. Only synthetic accounts are created; private credentials, raw databases, binaries and caches are excluded from uploads. See HOST_GO_INTEGRATION.md.

The overall driver deadline interrupts blocking waits; Frida attach/load/detach use bounded calls. Intro timing requires paired normal/fast actual Splash-object windows bounded by absent observations, advancing Unity frames, real elapsed time and genuine Jigbox tween duration. Verified behaviour progressTime and fade RGBA fields are additional read-only diagnostics; no DOTween position is invented. Live FOV requires observed mode-one corrections at both endpoint clamps selected through ordinary settings controls. Auto requires a real display/request transition from forced portrait back to the game's ordinary landscape request. Missing observations remain NOT_RUN.
