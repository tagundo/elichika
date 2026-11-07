# Original-game scene validation, second lane

This QA branch does not publish a release or implement the three-role mod format in the product. The frozen public Rina bundles and publication adapter remain unchanged.

Provider: signed `2026.11.07.1`, version code `2026110701`, producer `682c2c32958f343a61066770e2bd52d83e95bdb5`, run `42339779291`, artifact `13561129360`. Raw APK SHA256: `6f8998c12e459b82d878ba93db2660693ced20b442dd3f093d7d7513735ac690`. The original GL3.12 reference player remains SHA256 `8aaaeac075afa1c7908e6b91ab4d7f6a9e3cbf298574c0fa59fab51081dde82e`.

The workflow requires provider onboarding: the one original-game-created synthetic account must already have main phase 99 and scene tips 1–4 persisted before any fixture API runs. Missing rows fail the new-provider check. The reusable fixture can complete missing rows through official endpoints only when strict provider mode is explicitly disabled; the workflow enables strict mode. Preparation precedes the observed Rina scenario restart. It never writes native guide state, song-selection preferences or rule descriptions.

Use normal input and freshly measured widgets throughout:

1. Verify actual HOME, typed HOME controller counts, active Rina model and delayed target scales.
2. Enter normal Live music selection. Open Filter, select Solo, attribute condition 4, and `3D live`; keep Default sort and choose its second order toggle (Descending). Measure each control in the current tree. Public-master intersection predicts `[12008,12006,12021]`; the actual returned IDs and selected live ID are authoritative. Require selected/decided CHASE `12008` before claiming a target MV case.
3. Complete the ordinary song-download confirmations if required. TOKIMEKI's previous 45.11MB prompt does not establish CHASE's size or download state.
4. Enter the real Custom MV deck, verify type 2 and Rina member 209 at position 1 using split suit `912093017`. Use normal popup confirmation for board view 1 and bare view 2. Run both actual MVs, then the board comparison suit `912093018`, and return to HOME.
5. Retain actual route timestamps, fresh UI, safe synthetic state and native initialization/delayed snapshots. The strict scene auditor still requires every target case and the baseline initialization-cache comparison. Do not substitute another song, cast, current fixture label or prefab co-load for these cases.

The earlier tutorial-popup SIGSEGV remains unresolved. This lane captures only the owned reference-game PID/package during its launch window: UTC logcat plus at most four bounded text tombstones, 64 total frames, safe library basenames including `memfd:frida-agent-64.so`, and relative PC offsets. Raw logs, registers, memory dumps, authentication data and arbitrary paths are not persisted. Per-round reports and the final check distinguish incomplete capture, an owned crash, a restarted PID and unrelated system failures.

The observer, UI reader, model bytes and scene/physics checks remain frozen; the auditor's only changed literal is the approved provider APK hash. Android13 execution does not establish iOS runtime behavior or a complete physics trajectory.
