QA-only WebAudio DSP reference experiment
========================================

This is a NEW copied scratch harness. The original six-file distance harness,
its native run 42864800837, raw images and source freezes remain unchanged.
No product source, app bytes, frozen tests, Git index, workflow, build or release
has been modified by this diagnostic agent.

Use the same exact validated C2 app artifact: parent
9ffb5c6c362dd883275c89f7308c0fd9376323bc, tools
46065d67a3114f85945ac9218eddb00c1c22380f. Only a separate public AppKit/WKWebView
host is compiled. This is not the shipped AppKit container or user MacBook FPS.

The helper embedded at the beginning of probe.js is the independently tested
WKPCMReference helper SHA256
69f7d6648962b682e4df16242e8a0b854ac628a94a22d03d13b62b677d100e13.
Nine deterministic helper tests and its own actual Chrome preflight passed.

The experiment uses the original normal CDN/UI Eli Mermaid festa vol.1 costume,
automatic face, CHASE dance and music. The loaded workload must match the first
native control: 8 meshes, 14169 triangles, 11410 vertices, 39 textures, 2 source
materials, HQ and actual MSAA4. Body-source SHA and unchanged static/app bytes
remain mandatory. The three phases are:

1. Original HTML media, offset50/rate1, 12 seconds. No AudioContext is created or
   decoded before this phase finishes. All baseline per-frame reference fields
   must be null.
2. Only now create/decode one same-origin original linked PCM WAV. Require exact
   equality of its URL and the current original HTML player's src. Record the
   actual native WAV SHA, source PCM and decoded-buffer format. The known host
   hash0790393a... is a comparison, not a cross-CPU rejection rule. Resume must
   actually reach running with a bounded wait. Disable original HTML playback
   with its existing checkbox. AudioBufferSourceNode.start(offset,0 scheduleAhead)
   uses its actual AudioContext epoch; the QA-only public getPlaybackClock
   override returns mapped DSP time only during this 12-second reference phase.
   No wall-clock prediction or smoothing is used. Raw original getter results
   (normally null because disabled), DSP time, output timestamp if available,
   context/source state, current rig time, rAF/CPU and physics metrics are recorded.
3. Stop/disconnect the source and fully close the context before returning to
   original HTML media at offset50 for another 12 seconds. If the context cannot
   close, this control is skipped and cannot count as a successful experiment.

Finally restore the original public clock function and original audio checkbox,
stop the model, close the context and shut down the owned private backend.
Per-phase current HTML player references/listeners are refreshed, avoiding the
old distance harness's stale-element measurement after clip rebind. Clock sample
fields reset each phase and include clockReadAt, so the initial delta0 frame is
not mistaken for a fresh old-clock observation.

A blocked/suspended/unavailable AudioContext is recorded explicitly. A complete
read-only diagnostic may execute successfully while referenceExperimentValid is
false; that is NOT DSP support or success. A DSP_PHASE_OBSERVED result additionally
must satisfy nonempty baseline/reference/return frames, no context during the
baseline, exact same WAV URL, native PCM SHA recorded, running actual DSP with
original HTML clock null, context closed before return control, and restored API.
Any interruption/fallback invalidates a DSP-success interpretation. No fabricated
user activation, quality, devicePixelRatio or capabilities are used in native WK.
No physical/audible output or AVFoundation counters are captured, so clock stability
alone does not prove audible quality or every device's underlying audio behavior.

The helper bounds encoded WAV to32MiB and decoded PCM to64MiB. One buffer/context/
source is used. Abort/generation, source-ended and disposal behavior are covered
by its independent boundary tests. This is a prototype, not the full production
transport, fallback, multi-track, cache or all-platform support implementation.

Run on the existing active ARM64 macOS15 UI runner:

  xcrun swiftc -parse-as-library -swift-version 5 -O \
    -target arm64-apple-macos13.0 NativeWKDiagnostic.swift \
    -framework AppKit -framework WebKit -o NativeWKDiagnostic

  python3 run_native_diagnostic.py --app /ABS/Elichika.app \
    --host /ABS/NativeWKDiagnostic --config /ABS/config.json \
    --output /ABS/NEW-diagnostic-output

Use a fresh output directory. Runtime preparation uses the app's exact private
Python/codecs and normal authenticated session header (0600 temporary file,
never passed to JS/reported, removed finally). No pip or app rebuild is required.
Do not upload private-work/; upload only native reports, source/input guards,
fixture hash manifests and bounded logs. There are no distance screenshots in
this clock-only config; the original native near/geometry evidence is preserved.

Local integration validation: real host backend/CDN/UI, an actual trusted browser
click for normal local user activation, three short controls, unchanged same Eli
stats/MSAA4, native-WAV host hash0790393a..., running reference context, all raw
original getter samples null in DSP phase, closed context throughout return
control, original API/checkbox restored, page errors/rejections0. This is Linux
Chrome functional evidence, not native WebKit/FPS/output evidence. One initial
QA assertion caught a stale cached clock value on the first delta0 frame; that
failed proof was preserved and per-phase clock fields were reset before the clean
exit0 rerun passed. Swift source is byte-identical to the actual compiled/passed
first native run; new JS experiment still requires actual native execution.
