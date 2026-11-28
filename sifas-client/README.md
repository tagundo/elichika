# SIFAS 클라이언트 (Android GL FOVMOD, Apple Silicon PlayCover GL)

SIFAS 게임 클라이언트의 FOV·MP4 내보내기 패치 소스와 빌드 도구다. Android GL FOVMOD `2026.11.21.4`와 PlayCover GL `2026.11.21.2`의 복구 소스(원래 비공개 `tagundo/SIFAS-Client`, 커밋 `2dfbb12`)에서 시작해 2026.11.26 변경을 더했다. 원본 게임 APK·IPA와 게임 에셋은 이 폴더에 없다. 빌드할 때 공개 릴리즈에서 받는다.

| 대상 | 소스 |
| --- | --- |
| Android GL FOVMOD | [ci/sifas_mv_export](ci/sifas_mv_export/) |
| PlayCover GL | [ios/native](ios/native/), [ios/build](ios/build/), [ios/ci](ios/ci/) |

빌드는 elichika의 `SIFAS client build` workflow([.github/workflows/sifas-client-build.yml](../.github/workflows/sifas-client-build.yml))가 한다. [.github/sifas-client-build.json](../.github/sifas-client-build.json)의 버전을 바꿔 푸시하면 시작되고, APK와 IPA는 3일간 Actions artifact로 남는다.

## 빌드 입력

| 대상 | 입력 | 검증 |
| --- | --- | --- |
| Android | `v2026.11.14.1`의 `LLAS_GL_FOVMOD_b25.apk` | 83,535,736 bytes, SHA-256 `157f92a4…a738` |
| PlayCover | `v2026.11.14.1`의 `SIFAS_GL_Local_3.12.0_PlayCover_v5.ipa`에서 복원한 고정 입력 | 66,457,006 bytes, SHA-256 `830cfccc…f53e` |

PlayCover 고정 입력(`ios/build/inputs.lock.json`)은 공개 v5 IPA와 ZIP 항목 두 개만 다르다. [rebuild_playcover_input.py](scripts/rebuild_playcover_input.py)가 v5 IPA의 `SIFASFeatures.dylib`를 [ios/build/inputs/SIFASFeatures.dylib](ios/build/inputs/SIFASFeatures.dylib)(SHA-256 `5f3ed872…31b8`, 설정 메뉴·FOV 모드 라이브러리)로, `Info.plist`의 `CFBundleVersion`·`SIFASBuildVersion`을 고정 값으로 바꾼다. 나머지 항목의 압축 바이트는 그대로 복사한다. 결과는 고정 입력과 바이트 단위로 같고, [fetch-build-input.sh](scripts/fetch-build-input.sh)가 크기와 SHA-256을 확인한다.

## Android 빌드와 서명

Linux x86-64, Python 3.11+, Temurin JDK **17.0.21.1+2**, Android 플랫폼 **34 ext7 r03**, build-tools **34.0.0**, NDK **28.2.13676358**을 쓴다.

```bash
work=$(mktemp -d)
scripts/fetch-build-input.sh android "$work/b25.apk"
python3 -B ci/sifas_mv_export/build_android_mv.py --execute --region GL \
  --input-apk "$work/b25.apk" --sdk "$ANDROID_SDK_ROOT" \
  --work "$work/build" --build 2026.11.27.1
```

- 빌더가 Manifest, `classes.dex`, `libfovmod.so`, `libil2cpp.so`, `libunity.so`를 바꾸고 `zipalign`으로 정렬한다. 네이티브 파일과 NDK 플래그는 `build_android_mv.py`의 `NATIVE_UNITS`·`compile_helper`, Java 컴파일은 [build_menu_dex.py](ci/sifas_mv_export/android/build_menu_dex.py)에 있다.
- Android 소스를 고치면 [source-lock-MV.json](ci/sifas_mv_export/source-lock-MV.json)의 크기와 SHA-256을 갱신한다. 갱신하지 않으면 빌드가 멈춘다.
- **서명:** workflow는 Elichika 앱과 같은 릴리즈 키(`RELEASE_*` secret)로 서명하고, 요청 파일의 `signing_cert_sha256`(`fed02060…f930`)과 인증서가 다르면 멈춘다. 21.4 테스트 키(`7d18bc…83c2`)나 b25 키로 서명된 설치본에서는 한 번 지우고 설치해야 한다.

## PlayCover 빌드

Linux에서 NDK 28.2의 Clang/LLD, Theos `iPhoneOS16.5.sdk`(커밋 `0222fd54…`), `rcodesign` 0.29.0을 쓴다. 설치 명령은 [ios/build/linux/README.md](ios/build/linux/README.md)에 있다.

```bash
work=$(mktemp -d)
scripts/fetch-build-input.sh playcover "$work/input.ipa"
python3 -B ios/build/linux/compile_standalone.py --repo . --out "$work/compile" \
  --sdk "$SIFAS_IOS_SDK" --toolchain "$SIFAS_NDK/bin" --source-commit "$(git rev-parse HEAD)"
python3 -B ios/build/linux/package_standalone.py --repo . --source "$work/input.ipa" \
  --compile-dir "$work/compile" --work "$work/package" \
  --output "$work/PlayCover.ipa" --version 2026.11.27.1 --signer "$SIFAS_RCODESIGN"
```

결과는 Apple Silicon의 PlayCover에 가져오는 ad-hoc 서명 ARM64 iPhoneOS IPA다. PlayCover에서 같은 bundle ID로 설치하면 앱 데이터는 보통 유지된다.

## 테스트

- Android: `python3 -B -m unittest discover -s ci/sifas_mv_export -p 'test_build_android_mv.py'`, Java 호스트 테스트 `GestureStateTest`·`GroupPlanTest`·`MP4GaplessTest`·`MVExportContractTest`·`UpdateFovDexTest`(android.jar와 고정 jar로 컴파일), 기기 인코더 QA `AndroidMVEncoderDeviceTest.java`.
- PlayCover: [ios/ci](ios/ci/)(고정 입력이 필요한 테스트는 `SIFAS_MV_SOURCE_IPA`), [ios/native/tests](ios/native/tests/)(macOS·시뮬레이터 필요).
- `ios/ci`의 `test_experimental_policy`, `test_native_name_repair`, `test_official_payload`, `test_parity_android_consumers`, `test_parity_pipeline`, `test_probe_launch`, `test_simulator_launch`는 복구 소스에 빠진 파일(예: `.github/workflows/ios-unified.yml`) 때문에 복구 시점부터 실패한다.
- 변경 위치와 확인할 점은 [NOTES.md](NOTES.md)에 있다.
