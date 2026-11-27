# PlayCover 2026.11.21.2 Linux build

The delivered GL Local build was compiled from upstream Elichika source `78ec138962a9265e6a68c311ce069654313935f1`. This folder contains the Linux build and packaging helpers used for the verified replay. Run the commands from the root of the source checkout.

Use Linux x86-64 with Python 3.11 or later, Git, Android NDK `28.2.13676358` (r28c), and the Theos `iPhoneOS16.5.sdk`. The original compile used NDK Clang and LLD 19.0.1 for `arm64-apple-ios13.0`. The compile helper checks SDK commit `0222fd5413cf4b9af096f37b4621afa2688572f7` and SDK tree `81466d46b666daa04ae3d2b0b9d5324f0f621359`.

The packaging helper checks the Linux x86-64 musl `rcodesign` 0.29.0 executable. The archive is release asset [209933462](https://github.com/indygreg/apple-platform-rs/releases/download/apple-codesign/0.29.0/apple-codesign-0.29.0-x86_64-unknown-linux-musl.tar.gz) with SHA-256 `dbe85cedd8ee4217b64e9a0e4c2aef92ab8bcaaa41f20bde99781ff02e600002`.

## Original input

Use the exact `SIFAS_GL_Local_3.12.0_PlayCover_2026.11.15.1_candidate.ipa` with SHA-256 `830cfccc9e5397b2c69536ff3bf6d9e1626ff5ec7c8e587b0e89d4bdb135f53e`. Source and artifact hashes are pinned in [inputs.lock.json](../inputs.lock.json). The authenticated [GitHub Actions artifact 14150829830](https://github.com/tagundo/elichika/actions/runs/43689208250/artifacts/14150829830) is scheduled to expire on November 29, 2026 at 07:16 UTC. The same IPA is available to repository members through [the pinned input fetcher](../../../scripts/fetch-build-input.sh). From the checkout root, run `scripts/fetch-build-input.sh playcover "$BASE_IPA"` with GitHub CLI authentication. The fetcher uses the existing private fixture commit and verifies the Git blob and IPA digests.

`fetch_game.py` checks the workflow provenance and both artifact and IPA bytes when `GITHUB_TOKEN` can read the source repository's Actions artifacts. It also accepts an existing IPA via `--local-ipa` and checks the same IPA digest. The packaging helper takes the verified IPA directly.

## Build and compare

Set `NDK_ROOT` to the installed r28c NDK directory, `TOOLS` to a writable tool directory, and `BASE_IPA` to the input IPA above.

```bash
git clone --filter=blob:none --no-checkout https://github.com/theos/sdks.git "$TOOLS/theos-sdks"
git -C "$TOOLS/theos-sdks" sparse-checkout set iPhoneOS16.5.sdk
git -C "$TOOLS/theos-sdks" checkout --detach 0222fd5413cf4b9af096f37b4621afa2688572f7

curl --fail --location --output "$TOOLS/apple-codesign.tar.gz" \
  https://github.com/indygreg/apple-platform-rs/releases/download/apple-codesign/0.29.0/apple-codesign-0.29.0-x86_64-unknown-linux-musl.tar.gz
printf '%s  %s\n' dbe85cedd8ee4217b64e9a0e4c2aef92ab8bcaaa41f20bde99781ff02e600002 \
  "$TOOLS/apple-codesign.tar.gz" | sha256sum -c -
tar -xzf "$TOOLS/apple-codesign.tar.gz" -C "$TOOLS"

build_dir=$(mktemp -d)
output="$build_dir/SIFAS_GL_Local_3.12.0_PlayCover_2026.11.21.2-test.ipa"
python3 -B ios/build/linux/compile_standalone.py \
  --repo . --out "$build_dir/compile" \
  --sdk "$TOOLS/theos-sdks/iPhoneOS16.5.sdk" \
  --toolchain "$NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64/bin"
python3 -B ios/build/linux/package_standalone.py \
  --repo . --source "$BASE_IPA" \
  --compile-dir "$build_dir/compile" --work "$build_dir/packaging" \
  --output "$output" --version 2026.11.21.2 \
  --signer "$TOOLS/apple-codesign-0.29.0-x86_64-unknown-linux-musl/rcodesign"
python3 -B ios/build/linux/verify_playcover_21_2.py "$output"
```

The compile helper records the current Git commit for a clean checkout. If running from an archive of the source tree, pass its source commit via `--source-commit`. The verifier checks the signed main executable and the signed `SIFASMVExport.dylib` against the delivered IPA's hashes. Use `--delivered PATH` to check the original delivery file as well.

The two verified Linux rebuilds matched all 1,355 uncompressed ZIP member digests. The archive SHA-256 varies with the DOS timestamps on the added dylib and two generated signing envelopes. The package uses ad-hoc signing and targets a compatible PlayCover setup on Apple Silicon. Linux replay verifies code and resource hashes. Launch and gameplay in PlayCover require Mac testing.

Portable source and packaging tests run with the guarded input supplied externally.

```bash
for test_file in test_mv_export_patch.py test_mv_job_handle_abi.py test_packaging.py; do
  SIFAS_MV_SOURCE_IPA="$BASE_IPA" python3 -B -m unittest discover -s ios/ci -p "$test_file"
done
```
