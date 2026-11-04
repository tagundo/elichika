# Follow-up commands on the same disposable Android run

The workflow calls `followup.py` once per numbered round. Each round polls the
GitHub contents API for `tests/gl_ui_runtime/live-command.json` on
`codex/jp-global-content-gl-qa`, using the runner's `GITHUB_TOKEN` for read-only
GET requests. It waits in ten-second intervals for at most 600 seconds. A command
must match both the current GitHub run ID **as a string** and this round's integer
sequence. A missing file, another run, or another sequence causes no device action.
The manual workflow supports rounds 1 through 40 on that same device.

The checked-in `run_id="0", sequence=0, action="noop"` file cannot match a real
round. To request a round, replace its contents on the command branch with one
of these exact schemas, using the actual current run and sequence:

```json
{"run_id":"41700000000","sequence":1,"action":"capture"}
```

```json
{"run_id":"41700000000","sequence":2,"action":"tap_widget","widget_id":12345,"expected_class":"LLAS.Components.UI.ProductButton","expected_bounds":[10,20,110,60],"expected_label":"OK"}
```

```json
{"run_id":"41700000000","sequence":3,"action":"set_favorite_suit","suit_id":321107}
```

```json
{"run_id":"41700000000","sequence":4,"action":"seed_accessories"}
```

```json
{"run_id":"41700000000","sequence":5,"action":"back"}
```

```json
{"run_id":"41700000000","sequence":6,"action":"upgrade_candidate","artifact_id":123,"artifact_run_id":"41700000001","source_sha":"4ab6b4f275a1fb2e006e46ab46b60124996fc451","apk_sha256":"0000000000000000000000000000000000000000000000000000000000000000","version_code":2026110400,"version_name":"2026.11.04-dev"}
```

```json
{"run_id":"41700000000","sequence":7,"action":"close"}
```

The base-only recovery command is:

```json
{"run_id":"41700000000","sequence":8,"action":"relaunch_game"}
```

Choose its next live sequence before issuing `close`; a closed run cannot accept
further commands.

Artifact IDs, run IDs and the all-zero APK hash above are placeholders. Replace
them with the actual approved artifact pins before requesting the upgrade.

The bounds and ID in the tap example are placeholders. Copy the actual target
from the latest same-run `unity-ui-tree.json`; never derive coordinates from a
screenshot. `expected_bounds` means the target's
`inputDiagnostics.raycastArea.geometry.bounds`, which can differ from the
visible widget's own rectangle. The helper obtains a new tree immediately before
input and requires a unique matching ID, exact class, active/clickable state,
an active raycast target, verified same-Canvas geometry, and all four bounds
within one pixel of the expected bounds. It then uses only the fresh actual
raycast rectangle's center for ordinary rectangular areas, or the verified
interior point described below for an exact Triangle area, for a normal 240 ms
touchscreen gesture. The command
cannot supply tap coordinates, duration, source, shell text, callbacks or URLs.

For exact `LLAS.Components.TriangleRaycastArea`, the reader must supply a
`verifiedTriangleHitPoint` with kind
`TriangleRaycastArea.local-corners-pivot.strict-interior.v1`. The helper requires
its integer point strictly inside the measured area and Game view, matching
Canvas/camera IDs, and independently recomputes strict barycentric containment
from its three finite projected vertices. Missing, unknown, boundary, degenerate
or mismatched proof refuses without a rectangle-center fallback. This verifies
the approved JS shape calculation only: the inspector does not call the original
raycast predicate or check ancestor filters/occlusion. Those limitations remain
in the selection report and screenshot context remains necessary.

`expected_label` is optional and is an additional exact condition on the widget's
observed public labels. It never adds a string to the UI reader's allowlist.
The reader's current public-label configuration remains authoritative. A
pre-gesture `colleague.IsEnable=false` is not a refusal condition: that lock can
normally be acquired during pointer-down. Modal occlusion remains a limitation
of the component reader, so inspect the before/after screenshot context.

`capture` performs no input and records 30 seconds of screenshots and live UI
trees. `tap_widget` records 60 seconds afterward. Both work without an initial
state file if fresh UI snapshots succeed. Every UI operation attempts fresh
before/after screenshots and JSON. Passive captures never dismiss dialogs or
grant permissions.
`back` has no parameters and sends the ordinary Android `KEYCODE_BACK`, then
observes for 30 seconds with the same fresh before/after evidence.

Current-UI actions (`capture`, `tap_widget`, `back`) require a running verified
Game view. Maintenance (`set_favorite_suit`, `seed_accessories`,
`upgrade_candidate`, `relaunch_game`) instead checks the prepared synthetic UID,
native ARM64/root target, local GL reference SHA and installed GL APK SHA first.
It saves a passive Android screenshot and treats the before Unity snapshot as
optional, so an already-stopped game can be recovered. Successful maintenance
still requires a fresh post-restart game snapshot. If an operation fails,
post-action evidence errors are recorded separately and never replace its cause.

`relaunch_game` launches the unchanged installed GL app through the normal
activity, known GMS acknowledgement and fresh title/download guards. It does not
change the current favorite, themes or cache, reinstall either APK, or weaken an
earlier upgrade preservation failure.

`set_favorite_suit` accepts only `300207`, `321107`, or `321207`. It additionally
requires the initial state file to identify the one prepared game-created
synthetic account, preserves the baseline account, and checks current account
uniqueness. The existing `prepare_new_home` verifies ownership and uses ordinary
localhost game APIs, keeping authentication material in memory. The game restarts
normally, the known GMS warning follows the existing exact UI acknowledgement,
and title input uses a fresh UI tree. Contract acceptance is attempted only when
that synthetic account's terms version is below 3 and the existing contract
scene guard succeeds. The helper then observes for 120 seconds. It neither grants
items nor changes account databases directly.

`seed_accessories` has no additional parameters. It first requires that same
prepared synthetic identity and a stored `new_home.favorite_suit` in the allowed
three-suit set, before any grant. The separate `accessory_fixture` uses normal
present APIs to prepare only fixed R accessories `303313` and `304511`; commands
cannot choose accessory IDs or recipient IDs. The caller then reuses the normal
favorite/theme setup and restart using the validated favorite recorded in the
initial QA state. It does not infer the pre-grant outfit or claim to restore an
unknown current choice. The fixture and UI evidence remain scoped to the one
new game-created synthetic account.

`upgrade_candidate` is limited to the fixed repository `tagundo/elichika`, source
commit `4ab6b4f275a1fb2e006e46ab46b60124996fc451`, version code `2026110400` and
version name `2026.11.04-dev`. Before any artifact access it requires the prepared
synthetic UID proof. GitHub artifact metadata must identify the exact requested
artifact ID, `elichika-release-apk` name, workflow run and source SHA. Only the
metadata/ZIP requests to the constructed GitHub API endpoint carry the token.
The single HTTPS redirect must target an allowed Azure blob or GitHub Actions
host, and its download request carries no Authorization header or additional
redirect. Signed URLs, headers and bodies are never recorded.

The ZIP and its one expected APK are streamed to temporary storage outside all
evidence directories, checked for safe archive membership and exact APK SHA,
and deleted afterward. Both the current and replacement wrapper must have the
same pinned version. The game and wrapper stop normally; only the wrapper is
reinstalled with `-r`. Full logical userdata, profile, deck and configuration
hashes must match after installation and the new native server's startup. The
new native executable SHA and six localized titles are verified from the actual
installed databases through `m_suit → m_member.name → dictionary` references.

Before each preservation guard, the report records full userdata/profile/deck
hashes and configuration raw/canonical hashes for `before_update`,
`after_install` and `after_start`. Configuration formatting, key order and JSON
escape reserialization may differ; parsed values and types must stay identical.
Added/removed/changed configuration key names and userdata table/column hash
differences are recorded without values, authentication material or DB exports.
The full userdata hash remains a strict guard. A mismatch is evidence of a failed
preservation check and does not by itself establish data loss. Known post-install
preservation refusals leave the next explicit maintenance round available for
diagnosis/relaunch; they do not silently continue the rejected upgrade.

The GL APK is neither reinstalled nor cleared, and this action does not delete
or replace its data/cache. The current actual favorite, themes and background
remain in userdata: the initial QA state's favorite is not replayed. The caller
then launches GL normally, uses the existing fresh-title and download-dialog
guards, and records 120 seconds for cache refresh. Ordinary GL cache refresh may
update its client dictionaries. Captured screens still require visual review.

Each round writes `followup.json` with its command SHA256 and outcome; command
contents, tokens, GitHub error bodies and account databases are never exported.
Malformed commands, credential failures, unexpected infrastructure errors and
original-APK/target identity failures close the sequence via the shared
`evidence/gl-followup-closed.marker`. A routine safe action refusal, such as a
changed widget, label, geometry or missing synthetic-account proof, saves its
context and allows the next numbered round. `close` and 600-second idle timeout
also close the sequence. Later rounds skip once that marker exists. An existing
round output also refuses instead of replaying a potentially completed action.
Closing a round is a control operation and performs no device interaction.

Host checks:

```sh
python3 -m py_compile tests/gl_ui_runtime/followup.py
python3 -m unittest discover -s tests/gl_ui_runtime -p test_followup.py -v
```

These validate refusal and command-selection behavior with synthetic fixtures;
they do not establish an Android runtime result.
