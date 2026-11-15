# Date client candidate pipeline (source only)

This source kit is **not installed, activated or built**. It makes a finite hosted
Ubuntu job concrete: two unsigned Android APKs and three ad-hoc PlayCover IPA
candidates. It does not read Android signing credentials, publish releases,
install applications, make account writes or replace any previous release.

The baseline is the immutable `v2026.11.14.1` joint release. Full archive SHA256
and lengths are pinned in `client_pipeline.py`. Canonical date allocation remains
an explicit Root choice: pass the same Seoul `YYYY.MM.DD.N` once to all products.
`2026.11.15.1` is an example/planned allocation, not a published build.

## What changes

- Android starts from the actual released **b25** ZIP and DEX. It replaces only
  `classes.dex` and root version fields in `AndroidManifest.xml`, removes stale
  v1 signature members, and zipaligns. Every other retained payload is streamed
  unchanged and SHA256 compared, including both `libil2cpp.so` and `libfovmod.so`.
  The incremental DEX updater keeps its unrelated-class/method proof. The new
  FOV UI reads installed date metadata and restores settings after a two-second
  hold in the upper-right corner.
- iOS starts from each actual released **v5** IPA. It preserves the complete
  signed native executable byte for byte, so per-position suit and V5 material
  hooks remain installed. It changes only the root Info.plist date fields and
  `Frameworks/SIFASFeatures.dylib`. The helper links **five** units: the date UI,
  material core, Unity backend, native bindings/dispatch and material logging.
  The reviewed mixed-language builder keeps explicit library imports, unwind
  sections, two-level namespace, undefined-symbol errors and ad-hoc signing.
  The original UI's Hide/Show button and two-second restore gesture remain.

Original source copies and hashes are in `original-copy-provenance.json`.
Only two portability changes were made to the Android source driver: explicit
SDK/dependency environment paths. The iOS builder relocates the existing pinned
old-builder and four import proofs into this kit; its import symbol/library map
is unchanged. All material source/header bytes are unchanged. The source lock
pins every packaged build input after these explicit changes.

## Hosted recipe

1. Root reviews `SOURCE_REVIEW_PACKET.json`, installs the frozen tree at
   `ci/sifas_date_clients/` on an isolated branch, edits the template branch name
   and allocates the desired `CLIENT_BUILD` consistently. Do not overwrite
   default/main or the previous release. The dispatch-only behavior of a new
   off-default GitHub workflow is unreliable; the exact isolated push trigger
   in the template is the intended initial activation route.
2. The template installs official Android SDK command-line tools **12.0**,
   platform **34**, build-tools **34.0.0**, NDK **28.2.13676358**, Java **17** and
   Python **3.12** on the hosted runner. The exact bundled Dexlib/Guava/failure
   access jar sizes/hashes are checked against the already tested local tools.
   No Maven download or unpinned `latest` dependency is used by this driver.
3. Run tiny package/source-scope tests and the 14 shared metadata tests. Only
   explicit `--execute-build` begins public baseline downloads and compilation.
4. Upload the candidate directory as an Actions artifact. This workflow does
   **not** publish a GitHub release and does not sign Android APKs. Android
   artifacts ending `-unsigned.apk` are not user-installable releases.
5. Root can download one reviewed unsigned APK at a time and use the existing
   protected stable signer locally, without copying the signing key to CI:

   ```sh
   python /dev/shm/sifas-client-20261113/android/tools/sign_android.py \
     /owned/path/LLAS_GL_FOVMOD_DATE-unsigned.apk /owned/path/LLAS_GL_FOVMOD_DATE.apk \
     --keystore /workspace/.private/sifas-client-release/sifas-client-release.p12 \
     --password-file /workspace/.private/sifas-client-release/keystore-password \
     --expected-cert-sha256 5ccf5b5f73dcebad61255f6bfca848eb2022eedb741515d16ac84f94c405a9e3
   ```

   The existing signer verifies v1/v2/v3, certificate, payloads and alignment.
   There is no existing named game-client signing Secret contract in the
   repository, so this recipe does not invent one or upload private keys.
6. Validate installed date labels, gesture/save return behavior, MV duplicate
   character lighting/face behavior, normal game startup, FOV and orientation.
   PlayCover and latest iOS/SideStore are separate runtime gates. Join only the
   verified installables with the next Elichika server release; candidate
   artifacts and static packaging success are not a runtime validation claim.

## Inert review and tests

```sh
python -B client_pipeline.py --build 2026.11.15.1
python -B -m unittest -v test_client_pipeline
(cd metadata && python -B -m unittest discover -s tests -v)
```

Performed here: eleven focused package safety/source-scope tests, fourteen
metadata tests, deterministic source-lock verification and syntax compilation.
No new DEX, helper, APK or IPA product was built, signed, installed or uploaded.
No new workflow was activated. The first metadata-test invocation used the wrong
working directory and failed to import; the corrected invocation above passes.

Limitations before activation: real hosted SDK package/jar availability and all
five candidate builds have not run; the whole runner recipe has no runtime
result. The source kit intentionally fails if baseline, dependency, source,
archive path/scope, payload identity or explicit SDK assumptions differ.
