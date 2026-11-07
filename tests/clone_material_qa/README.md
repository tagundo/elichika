# Original Unity clone material A/B

This manual, isolated QA job tests a specific mechanism: two inactive actors
instantiated from one cached prefab can have distinct components/renderers while
referencing the same serialized mutable lighting materials. It then loads the
original and two independently privatized model bundles and checks that their
lighting material identities and native writes are independent.

It does **not** establish rendered-MV lighting, member initialization/face merge,
or a fix for intermittent stage loading. Those require separate actual-stage
cold/warm repetitions. Material sharing alone is legitimate prefab reuse; the
relevant risk is per-actor direct color mutation of those shared materials.

The workflow pins the unchanged public GL3.12 APK, Frida17.25.2, bridge0.14.0,
Redroid ARM64 image, every model and every public shader/dependency bundle.
`fixtures/manifest.json` binds the source producer/catalog/dependency manifest
hashes, target13, controlled material names, shader CAB/path IDs and saved colors.
`prepare_fixtures.py` uses UnityPy1.25.0 to verify every mutable lighting material
is internal, both controller arrays agree, all original externals resolve, and
private copies preserve the same material data and external dependency graph.
iOS copies remain a separate static-invariant result; this Android job never
loads iOS resources.

Before any runner adb operation, `ownership.py` requires the exact fresh Docker
container, immutable image, loopback-only Android port, current GitHub run labels,
and this job's data mount. It refuses local or other-lane targets. The workflow
also checks this gate before starting its first adb query. No existing account,
local device, or concurrently running QA lane is a permitted target.

Six fresh original-player processes cover board/bare shared-prefab controls and
source+privateA+privateB forward/reverse load order. The engine loads all pinned
dependencies before models. Actors are instantiated under an already inactive
owned parent, so they never enter the hierarchy's active state or call game
initialization in this test. Ambient/Rimlight `get_Materials` are direct native
field reads. The probe reads only `Renderer.sharedMaterials`: it never invokes
`Renderer.material` or `Renderer.materials`, which would make copies and hide
aliasing. This restriction is audited in source; the report's policy string is
not an independent runtime interception or proof.

Native Shader identity and Material.HasProperty must match pinned dependencies;
missing/fallback shaders cannot produce PASS. For both internal head/body
materials and `_AmbientColor`/`_RimlightColor`, sequential native SetColor/GetColor
checks must demonstrate cross-talk in the shared control and its absence across
all three private identities. Original colors are snapshotted, restored and read
back before destroying only owned actors/parent with allowDestroyingAssets=false
and unloading only owned bundles in reverse order. Prefab IDs are explicitly
excluded from destruction. Host/device SHA checks follow all cases; exceptions,
timeouts or restoration errors fail the run. No hooks, global unload, shader
globals, actor initializers, gameplay callbacks, account edits or UI navigation
are used. The only native dialog action is a freshly measured exact known public
Google Play-services warning's OK button, inherited from the proven harness.

On host timeout/error the runner requests cooperative cancellation and waits a
bounded30 seconds for the probe's cleanup acknowledgement. In-flight native
loads make that acknowledgement incomplete. An unacknowledged script is never
unloaded/detached before the verified owned game process has been terminated;
that fallback is explicitly FAILED and provides no restoration proof. Host
cleanup/hash attempts and individual GC-handle releases are independent so one
failure cannot skip all remaining cleanup or evidence. The workflow's always
diagnostics/removal also revalidates ownership and leaves a mismatched target
untouched.

Preparation (local, static only):

```sh
PYTHONPATH=/path/to/pinned/UnityPy1.25.0 python prepare_fixtures.py \
  --clones /path/to/clone-producer/manifest.json \
  --dependencies /path/to/dependencies/manifest.json --output /fresh/fixtures
python -m unittest discover -s tests/clone_material_qa -p 'test_*.py'
node --check tests/clone_material_qa/probe.js
```

Dispatch remains a separate parent-reviewed action. The new manual workflow is
the already registered `.github/workflows/android-ui-qa.yml` identity in this
isolated QA branch; main and active scene-QA branches remain unchanged.
