QA-only native WKWebView diagnostic
=================================

These files are scratch diagnostic tools. They do not modify the product, tests,
native app, shader, AA samples, model geometry, saved edits, or physics solver.
The native host is a separate AppKit executable, not the shipped Elichika app.

Preferred execution uses the exact validated C2 Mac app artifact (parent
9ffb5c6c362dd883275c89f7308c0fd9376323bc, tools
46065d67a3114f85945ac9218eddb00c1c22380f) only as a read-only backend/static source.
The app's own private Python launches elichika_macos.py with a fresh isolated
data/library directory. The initial UI request supplies its normal private
session header from a mode-0600 file, then normal cookies/APIs handle import.
The header file is deleted, never passed to JS, and never included in reports.

The JS imports official Eli Mermaid festa vol.1 (400022007), automatic face, and
CHASE dance 12008/1200801 through the normal packaged UI/CDN routes. No game files
need to be committed. The orchestrator records hashes of downloaded Unity/WAV
fixtures and every static webroot file, and verifies static files stay unchanged.

On an ARM64 macOS 15 runner with the UI session active:

  xcrun swiftc -parse-as-library -swift-version 5 -O \
    -target arm64-apple-macos13.0 \
    NativeWKDiagnostic.swift -framework AppKit -framework WebKit \
    -o NativeWKDiagnostic

  python3 run_native_diagnostic.py \
    --app /ABS/Elichika.app \
    --host /ABS/NativeWKDiagnostic \
    --config /ABS/config.json \
    --output /ABS/NEW-diagnostic-output

Use a fresh output directory. No runtime pip, external package installation, or
rebuild of Elichika.app is needed. Only the QA-only Swift host is compiled.

Outputs worth uploading as diagnostic artifacts:
  orchestration-report.json
  webroot-source-sha256.json
  downloaded-fixtures-sha256.json
  backend.log
  host.stdout.txt / host.stderr.txt
  native/native-report.json
  native/*.png

Do not upload private-work/ (it is a disposable normal app runtime/payload and
download cache, not evidence needed for review). The native report includes the
actual platform, visible/occluded window state, scale/refresh-rate metadata,
driver identity, viewport/drawing-buffer/sample/depth state and screenshots.

The screenshot matrix holds CHASE 58.5s and geometry fixed while varying distance
and only the camera near plane. Each image records a posed-world-vertex hash,
per-mesh projected bounds/depths and whether the plane clips any positive-depth
vertices. Near-camera body intersections can make close shot comparisons unsafe;
the recorded per-mesh minimum depths must be reviewed before calling a visual
difference a precision fix.

The timing phases keep HQ/MSAA and the normal display-refresh physics setting.
Audio-off is an explicitly labeled diagnostic A/B phase, not a product fix.
Per frame, the probe records narrow rig time, exact audio-clock returns, direct
media time/readiness, rig update duration, draw duration and small physics timing
counters. Full rig/physics state is sampled only at phase/shot boundaries.
WebKit may lack PerformanceObserver longtask; that absence is recorded rather
than treated as failure. Optional home/dance transition phases record skipped
when the original home clip is unavailable. Every phase retains source defaults.

Limits: this is cloud-runner native WebKit evidence, not the user's MacBook FPS,
not proof of the shipped AppKit container's timing, and not full original-game
pixel/physics parity. Source physics unavailable/missing-runtime state is recorded
without substituting a different solver or forcing unsupported runtime metadata.

Local Linux validation: preload Node syntax, async probe body syntax and Python
compilation passed. The real source-backend/CDN/UI functional rehearsal passed
with initial JP preferences forced then GL selected, confirming catalog response
settlement, costume/automatic-face import, CHASE and linked music, two same-pose
far snapshots at original/.1 near and two short timing phases. Actual MSAA was
4; page errors and unhandled rejections were 0. A separate first rehearsal also
passed the already-GL selection path. This is functional host-Chrome evidence,
not native Mac rendering or FPS evidence. The Swift source still requires actual
macOS compilation and native execution.
