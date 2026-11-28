# Actual iOS build and packaging

The manual `ios-unified.yml` workflow runs on an ARM64 macOS/Xcode host. Its
default `sdk-compile` mode builds the production Go/SQLite C archive for
`iphoneos` and `iphonesimulator`, a device `ElichikaHost.framework`, and a
separate Simulator probe app linked against the real CPython 3.13 framework.
It produces compiler receipts, not an IPA or a runtime validation claim.

`core-runtime` also initializes the same deterministic official GL/JP server
data as Android/macOS and runs the separate probe twice on each of an iPhone
and an iPad Simulator. This mode explicitly omits full modding dependencies.

`runtime-inputs` compiles and retains only the real device/Simulator wheels
and signed codec frameworks. Its NOT-IPA artifact records exact source, lock,
patch and output hashes; it does not initialize a server, provision an app or
claim runtime execution.

`tools-runtime` reuses the pinned successful dependency artifact after checking
its run/source identity, every file hash and the unchanged compiler inputs.
It builds and runs only the separate Simulator probe with the full tool stack.
The explicit Simulator-only provision flag may retain the currently incomplete
Archive configuration for this test. No device app or IPA is built. Production
full-runtime validation rejects this marker and still requires the existing
complete Archive publication guard.

`experimental-candidate` is a separate QA entry point for the exact reviewed
217-byte Archive-pending configuration. It requires full Simulator tool,
protocol, lifecycle and persistence gates from the same source before composing
the actual device game. Its app label, signed capability, Info metadata,
manifest and IPA filename identify `EXPERIMENTAL_ARCHIVE_PENDING` and
`UNTESTED_DEVICE`; SideStore user signing is required. Existing user packs can
be placed directly in Files/Finder. The pending individual-file publication is
not advertised as available. A Simulator runtime cannot enter this device IPA,
and an experimental runtime cannot pass the production packaging entry point.

`experimental-package` is a narrow device packaging consumer of Source 12's
completed four-launch full Simulator proof. It accepts only the pinned original
evidence and the exact game artifact label correction. Every native, Python,
runtime, Go, root app, assets and tools input must be unchanged; only explicitly
listed packaging, CI, documentation and test paths can differ. The packaging
entry point independently rechecks this closure and original proof SHA. It
preserves Source 12 as the tested runtime source and records the current
packaging consumer separately, with no fresh Simulator execution claim. The
actual 66 MB game is fetched and fully verified before compilation, then the
real device Go/Python/native app is rebuilt, signed and checked for preservation.
No Simulator target or binary is built or included by this mode. The normal
same-source experimental path and production publication guard are unchanged.

The test/QA workflow can reuse only the exact retained official payload pinned
in `official-payload.lock.json`. Its Source 9 data producer remains identified
separately from the current platform consumer. Reuse requires that producer to
be an ancestor, a clean committed checkout and submodules, and no committed
changes outside `ios/` and `.github/`; the original iOS payload builder and
shared helper also must be unchanged. The complete retained ZIP, original
proof, each file and the packaged data manifest are verified. The reviewed
producer run failed later during app startup; its payload retention and upload
must have succeeded. This does not supply any runtime or IPA gate result.
Production `full-candidate` keeps its fresh producer and publication guard.

The separate Simulator probe records bounded, atomic stage progress as
diagnostics. Its host watchdog allows 60 seconds for first progress, fixed
budgets for startup, health, TLS, tools, each real lifecycle operation and each
WebView origin, and an absolute 600-second launch cap. Heartbeats and detail
labels cannot reset a stage entrance; late transitions cannot revive an expired
budget. Actual Source 10 iPad logs completed initial database loading at
17:58:02 UTC, read-only configuration initialization at 17:58:28 and restart at
17:58:52, before the former single 260-second deadline at 17:59:02. The new
budgets preserve all three initializations and the final WebView checks.
Progress never authorizes success; all four cold-launch receipts and real
protocol, persistence, source and bundle gates remain mandatory. Failures retain
the last validated progress, native error receipt and screenshot before the
owned sandbox is deleted.

`full-candidate` requires the complete wheel/codec closure, runs full Simulator
gates, obtains the exact existing GL Local game through the locked successful
GitHub artifact export, and packages the actual monolithic SIFAS app. It refuses
an incomplete runtime. Current native dependency failures remain build failures;
they are never converted into successful packaging receipts.

The build uses the actual build day in `Asia/Seoul`, preserving the game short
version `3.12.0` and mapping `YYYY.MM.DD.N` to Apple's `YYMM.DD.N` bundle version.
The source, assets, tools, game, CPython and native codec identities are recorded
in the receipts. The existing incomplete Archive catalog and production release
guards are not modified by these scripts.

The device IPA preserves every original member, including legacy universal
helpers and the existing Settings/FOV/orientation/MV/material patches. Its only
permitted original-file changes are the new host load command, intended app
metadata, and ad-hoc signing. `signature_proof.py` compares every original
architecture slice, section and non-signature byte, allowing only signature
fields and `__LINKEDIT` size changes. No second `UIApplicationMain`, Unity
runtime, or Simulator game class is linked into the device framework.

All new native Python extensions live in signed iOS frameworks with CPython
`.fwork`/`.origin` mappings. The installed app is read-only; server databases,
imported documents and downloaded assets use its writable sandbox. No build
host executable, user database or host configuration is included.

The intended app metadata enables `UIFileSharingEnabled` and
`LSSupportsOpeningDocumentsInPlace`. The app's Documents directory, including
its packs folder, is accessible through Files and Finder for direct placement
of large asset sets. This does not turn the game into a document browser or
add a LAN permission prompt; its embedded services use loopback addresses.

The output is named `UNTESTED-iPhone-iPad.ipa`, is fully ad-hoc signed and
verified, and requires the user's SideStore signing. Compiler, Simulator and
packaging success do not prove actual SIFAS gameplay on a physical iPhone/iPad.
These scripts upload only CI candidate artifacts and evidence; they do not
publish releases or distribute certificates.

Portable boundary tests:

```sh
python3 -B -m unittest discover -s ios/ci -p 'test_*.py' -v
```

On an actual Apple build host:

```sh
python3 -B ios/ci/run_build.py --mode sdk-compile --repo . \
  --work /tmp/elichika-ios-build --evidence /tmp/elichika-ios-evidence \
  --delivery /tmp/elichika-ios-candidate
```
