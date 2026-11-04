# Follow-up commands on the same disposable Android run

The workflow calls `followup.py` once per numbered round. Each round polls the
GitHub contents API for `tests/gl_ui_runtime/live-command.json` on
`codex/jp-global-content-gl-qa`, using the runner's `GITHUB_TOKEN` for read-only
GET requests. It waits in ten-second intervals for at most 600 seconds. A command
must match both the current GitHub run ID **as a string** and this round's integer
sequence. A missing file, another run, or another sequence causes no device action.

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
{"run_id":"41700000000","sequence":5,"action":"close"}
```

The bounds and ID in the tap example are placeholders. Copy the actual target
from the latest same-run `unity-ui-tree.json`; never derive coordinates from a
screenshot. `expected_bounds` means the target's
`inputDiagnostics.raycastArea.geometry.bounds`, which can differ from the
visible widget's own rectangle. The helper obtains a new tree immediately before
input and requires a unique matching ID, exact class, active/clickable state,
an active raycast target, verified same-Canvas geometry, and all four bounds
within one pixel of the expected bounds. It then uses only the fresh actual
raycast rectangle's center for a normal 240 ms touchscreen gesture. The command
cannot supply tap coordinates, duration, source, shell text, callbacks or URLs.

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
