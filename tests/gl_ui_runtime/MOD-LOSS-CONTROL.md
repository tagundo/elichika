# Expected mod loss: negative control only

This branch is separate from `codex/gl-mod-preservation-qa`. Its positive updater
and strict mod preservation checks remain unchanged. The separate runner may
observe a controlled loss; it never turns the positive updater's REFUSED result
into UPGRADED/PASS or repairs/removes the fixture itself.

The exact closed target is the withdrawn formal APK8c725e5a…/sourcee6aa8588…,
build41791847801/artifact13304790579, version2026.11.04.1/code2026110401 and
signerfed02060…. `mod_loss_policy.py` contains the full hashes and refuses any
future positive pins, target overrides, other branch or control mode. The run
must use `refs/heads/codex/gl-mod-loss-control` and native loopback Redroid.
Production/Main/release/tag changes and real backups are outside this control.

Start with the fixed fresh synthetic custom Home fixture described in
`MOD-PRESERVATION.md`, Korean/Light, on representative Nov3.4. Obtain a followup
capture showing the actual Eli custom T-shirt Home. Root independently reviews
that PNG and computes its SHA256. Only then queue this six-field command:

```json
{
  "run_id": "CURRENT_RUN_ID",
  "sequence": 3,
  "action": "observe_expected_mod_loss",
  "control_mode": "expected-mod-loss",
  "reviewed_baseline_sequence": 2,
  "reviewed_baseline_png_sha256": "EXACT_SHA256_OF_FOLLOWUP_2_AFTER_PNG"
}
```

The previous baseline report must match this run/sequence, be CAPTURED in this
mode, and show `baseline_mod.status=PASS`. The exact PNG bytes are checked and a
fresh strict custom master/ownership/selection verification precedes install.
Normal commands are limited to capture, observed tap_widget and close; generic
upgrade, arbitrary APK pins, callbacks, fallback selection and reseeding are not
accepted. The workflow still uses ten inputs, with `prepare_new_home=true`
selecting the fixed mod fixture and the legacy locale-setup input enabled.

The original positive updater performs the wrapper-only installation. Only its
specific custom-preservation REFUSED after installation/startup is eligible for
the negative controller. The controller independently verifies actual installed
APK bytes/certificate/version/native library, single running native process,
three readiness services, original GL APK, full userdata/profile/deck and config
semantics. Both recorded and fresh startup snapshots must preserve core state.
An after_install refusal requires completing install checks and a normal server
start; an after_start refusal requires completing the remaining startup checks.

Before launching GL, the valid new GL master must have lost custom990000901,
retain its normal stock source and the new JP content, while the same synthetic
account still owns/selects990000901 for member2 with the original background.
Loss/retention of other custom catalog components is reported separately. Any
unrelated refusal, core change, stock fallback, ownership loss, invalid master,
wrong identity or service failure blocks client observation.

After these gates the original client follows normal launch/title/download UI.
Allow the normal download, use a fresh observed Close for completion, then capture
bootstrap/loading/NRE/native diagnostics. Game crashes are possible evidence:
after snapshots are optional, and missing Game view is recorded rather than
requiring process survival. No cache clear, catalog deletion, clone restoration,
manual exception, field write or callback is used.

Every control report stays labelled `expected-mod-loss`, with the positive
REFUSED retained. Client outcome is `OBSERVATION_REQUIRES_INDEPENDENT_REVIEW`;
catalog loss alone, generic loading, a generic exception, or a working fallback
does not establish the hypothesized failure. Root reviews the relevant code
stack and actual screens before classifying or closing the run. Followup
artifacts are named `gl-mod-loss-control-N` to avoid mixing them with positive
results. The release remains withdrawn; this control grants no publish action.

Host preparation passes153 Python tests, the JS preference checks, py_compile,
14 shell syntax blocks and the ten-input workflow limit. No Android run, APK
build, release or tag action is part of the host checks. Run41827878073 stopped
before custom Home when the initial fixture incorrectly expected a present-box
entry for a unique suit. The fixed fixture follows Nov3.4's normal direct-grant
behavior, verifies exact ownership, and never fabricates a present/receive path.
