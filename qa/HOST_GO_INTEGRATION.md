Host Go transport candidate; no runtime approval yet

Use this candidate's four new files (`host_go_fixture.py`, `build_host_go_fixture.py`,
`host_seed_account.go`, `test_host_go_fixture.py`) and review the driver/downloader
integration diffs beside this directory. Do not replace a newer main driver: it may
already contain additional MV selectors. The slider control uses a single tap at
the live SeekBar endpoint; dragging from its center transiently changes the paired
slider and is unsuitable for equal min/max QA.

Root has frozen exact C5 commit b503631efee12bdf224ae94962bd1403a4658da3. In the current fresh manifest,
set server.source_commit to that 40-character SHA and server.approval_scope to
`final_source_build_fixture`. Remove the server APK asset/version/hash fields from
that source-build server descriptor. Keep the independently reviewed client asset,
original provenance, certificate, and observer entries current. The builder rejects
a placeholder, local non-ARM64 machine, reused/dirty checkout, wrong Go version,
changed/untracked sources, unexpected data, or mismatched official gitlinks.

On ubuntu-24.04-arm, keep the current genuine Android preparation and client
signature checks. Replace only these workflow portions:

1. Read the frozen manifest's server.source_commit as the checkout ref. Checkout
   tagundo/elichika into `server-source`, recursive submodules and
   persist-credentials:false. Use actions/setup-go@v5 with go-version:'1.22.12'.
2. Download current client + pinned observer using the normal safe downloader plus
   `--skip-server-apk`. Do not verify or report an uninstalled server APK.
3. Prepare the fresh fixture BEFORE starting game UI:

```sh
python3 qa/build_host_go_fixture.py \
  --source-root "$GITHUB_WORKSPACE/server-source" \
  --source-sha "$FROZEN_C5_SHA" \
  --output "$RUNNER_TEMP/host-go-fixture"
```

4. Run the merged genuine UI driver:

```sh
"$RUNNER_TEMP/qa-venv/bin/python" -u qa/feature_client_smoke.py \
  --fixtures qa/frozen-fixtures.json --region "$QA_REGION" \
  --host-server-root "$GITHUB_WORKSPACE/server-source" \
  --host-server-receipt "$RUNNER_TEMP/host-go-fixture/host-go-fixture.json" \
  --client-apk "$RUNNER_TEMP/client-qa-fixtures/client.apk" \
  --server-source "$GITHUB_WORKSPACE/server-source" --evidence evidence \
  --unity-agent qa/unity_ui.bundle.js --max-seconds "$QA_SECONDS" \
  --settings-orientation portrait --settings-scalar 2.0 --fast-intro
```

The fixture launches its exact executable as a tracked owned PID, checks
/proc/PID/exe SHA256 plus its independent readiness nonce, then uses
`adb reverse tcp:8080 tcp:8080`. The game's original localhost URL stays intact.
The environment contains no GitHub tokens, privileged local WebUI token, or
fixture-password env. The genuine game transfer UI receives only the synthetic
account created by the normal CreateNewAccount API in a fresh server database.
Read-only DB observations and sanitized HTTP logs replace adb reads of server
private files. No Frida method/callback invocation or game/database injection is
added.

Only the approved legacy template (`yumemichi_userdata.db`, SHA256
90680f5885dc680c17eddbbff145a561901f06e69b8e412d98b55157aa5c0b27) is omitted in
this disposable CI source checkout before any Go execution. Original repositories
and their template remain intact. The seeder refuses any preexisting account and
initializes the one synthetic account through production CreateNewAccount. A
random 16-character ASCII alphanumeric password stays in a mode-0600 private file.

Artifact allowlist: upload `evidence/` plus explicitly copied sanitized build/init
logs and public `host-go-fixture.json` receipt. NEVER upload the entire fixture
output or server-source directory: these contain private synthetic credentials,
raw userdata, compiled executables, and CDN caches. Do not copy
`synthetic-account.private.json` into evidence. The public receipt contains only
its local file path, not the password. Runtime report records actual source,
exact binary, Go1.22.12, flags, official gitlinks, and installed-client provenance.

Source-build game RPC QA cannot approve installation or native lifecycle of the
server APK. Those native host checks remain mandatory separately. The feature
report preserves NOT_RUN/PARTIAL for unimplemented or unobserved FOV/orientation/
intro/MV/no-new-costume cases. Startup, successful HTTP, or source equivalence
cannot turn those cases into PASS.

Local transport proof: 28 Python tests pass, including a separately compiled tiny
authored C HTTP transport executable. No Elichika/game ARM64 binary ran locally.
Actual root-frozen C5 source compilation and genuine ARM64 Android UI execution
remain required; current manifest is bound to final C5 source-build scope; actual runtime remains unvalidated.
