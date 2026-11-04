# Disposable mod preservation QA

This branch prepares an actual GL control for the mod-preserving payload update.
It has not been built, dispatched, or run on Android. Candidate pins still name
the previous formal APK and must be replaced with the audited new candidate's
source/build/artifact/APK hash/version before dispatch.

The initial wrapper is the pinned Nov3.4 official APK. The user's actual older
wrapper version is unconfirmed, so Nov3.4 is a representative published baseline.
The unchanged original GL3.12.0 APK runs Korean with Light download. No GL data
clear, cache deletion, reset, or GL APK replacement is part of this test.

`prepare_new_home=true` selects this branch's mod fixture. It reuses the existing
boolean input, keeping workflow_dispatch within its10-input limit. It requires
the existing `prepare_english=true` (locale setup), `tap_surface_center=true`,
`skip_game=false`, and `latest_baseline_upgrade=false`. The workflow_call defaults
remain unchanged. Live commands read `codex/gl-mod-preservation-qa` exclusively.

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
suit gift handler grants this unique item directly, including on Nov3.4; its
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

Native diagnostics now use logcat threadtime and retain only crash timestamp,
bounded signal/PID/TID, an exact allowlisted process name (otherwise `redacted`),
and library basenames. Messages, arguments, paths, addresses, credentials and
unknown strings are discarded. Fatal-signal counts remain separate from those
attributable events so unattributed crashes cannot silently become passes.

Host validation:109 Python tests, JS preference checks, py_compile,14 shell
syntax blocks and the10-input limit pass. The fixture also passed an in-memory
copy validation against seven original stock databases, with source file SHA256
unchanged. Actual Android/GL validation is pending the new candidate.
