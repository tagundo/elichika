# Disposable mod preservation QA

This QA-only branch prepares a fresh actual GL control for the v5 data-revision
updater. The initial wrapper is the published v4 APK: source
`cca1438a8ee4408123e6ede22d974f1dbf2a823b`, build `41884324695`, version
`2026.11.04.4`, code `2026110404`, APK SHA256
`815e9dd70d1b0e89b97f76b83c1b71136ec7f5f73f6e9a6a983d123a7aa42cac`.
The v5 candidate is `2026.11.05.1` / `2026110501`, source
`56861368fd76b82f395492b8e1c456a71a28a57a`, build `41950334362`, artifact `13381940509`.
Root's independent raw-APK fast audit bound APK SHA256
`f31f2aad8de3e05821c25b18781c0bcaf7e13178daa16b94c17c0e03f654fb0f` and native SHA256
`e8f3ab088f2eb5bad28508d71ebc2414aab898c755c7659d8bde6d981f5e0262`.
The initial dispatch prepares only v4. Candidate installation still
requires root's independent review of the actual baseline custom Home PNG.

The public v4 wrapper is a reproducible published baseline; this synthetic
fixture makes no claim about an unknown personal installation.
The unchanged original GL3.12.0 APK runs Korean with Light download. No GL data
clear, cache deletion, reset, or GL APK replacement is part of this test.

`prepare_new_home=true` selects this branch's mod fixture. It reuses the existing
boolean input, keeping workflow_dispatch within its10-input limit. It requires
the existing `prepare_english=true` (locale setup), `tap_surface_center=true`,
`skip_game=false`, and `latest_baseline_upgrade=false`. The workflow_call defaults
remain unchanged. Live commands read `codex/gl-mod-preservation-v5-qa` exclusively.

The fixture requires loopback Redroid, root, native ARM64, exact installed wrapper
and GL APK hashes, an empty account set before launch, and exactly one new game-
created authenticated account. It stops GL and the wrapper/server and verifies
all three process names are absent before reading/editing database copies and
again before every write. Original stock databases and personal files are never
modified by host preparation or tests; no raw userdata database is written.

The fixed costume990000901 clones stock Eli300201 (9th Anniversary T-Shirt) onto
the same member2, following costume_clone's integer0..999999999 range and opaque model/
thumbnail reuse. It also adds view2 pointing to the same real model, localized
`*_cloned` names, a harmless display-order override on the existing source row,
and one custom table. KO Android assets receive a `suit:990000901` package alias
and a separate member_model crypto alias. Their pack names, offsets, size, head
and crypto values are copied from existing stock data; no invented pack file or
modified asset payload is used. The original stock model key remains the actual
costume's model, as in costume_clone.

After a cold server restart, the catalog is verified before any gift. The normal
suit gift handler grants this unique item directly; its
ownership is read back before the normal theme/favourite APIs. No present-box
entry or receive request is fabricated.
Only safe row hashes and selected IDs enter evidence. The custom master/view/
dictionary/alias/override/table rows, exact ownership and exact selected custom
ID must all survive. A stock costume or missing custom master is a refusal even
if vanilla Home renders successfully. The real Eli T-shirt also differs visibly
from the default school uniform, providing a second check for human review.

Before update, after APK installation, after server startup, and after each live
followup, the mod rows and selected ID are checked. The normal full userdata/
profile/deck/config guards still apply. The updated GL master must additionally
contain suits300207/321107/321207, background202300200 and live13001/music3001.
Actual KO custom Home must be captured before and after the wrapper-only update.

The v5 signed archive's `assets/payload_revision.json` is checked against the
actual payload streams before installation. Its canonical `payload-v1:` revision
must match `installed_version`, `.payload-upgrade/current.json.payload_version`,
and the bounded public baseline metadata after startup. The exact official DB
source SHA/size map, seven JP/GL coverage pairs and original base-header bytes
must match that signed manifest. This deliberately keeps modded live DBs distinct
from official stock metadata. The installed and running native digest must also
match root's audited constant. Existing full logical userdata/profile/deck/config,
fixture component, exact custom selection, signature, GL APK and imported-content
guards remain required. An APK version string cannot stand in for the revision.

Native diagnostics now use logcat threadtime and retain only crash timestamp,
bounded signal/PID/TID, an exact allowlisted process name (otherwise `redacted`),
and library basenames. Messages, arguments, paths, addresses, credentials and
unknown strings are discarded. Fatal-signal counts remain separate from those
attributable events so unattributed crashes cannot silently become passes.

The earlier controlled positive run `41831583335` and losing negative control
`41834438421` remain historical evidence. Their UI images and candidate hashes
are not v5 proof. Fresh before/after actual Home captures and bounded client logs
are required. Unattributed Bluetooth/system crashes stay separate from game
exceptions; no all-process crash-free claim follows from a rendered Home.

Host tests use only small synthetic data. Actual Android/GL validation remains
pending the independently audited v5 candidate and root's dispatch.
