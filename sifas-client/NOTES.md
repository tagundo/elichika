# 최신 테스트 클라이언트 인수인계 검증

## 원본 빌드와 재빌드 해시

| 결과 | SHA-256 | 비교 |
| --- | --- | --- |
| Android 배포 APK의 `classes.dex` | `d4a8a9da16fefef5cf2394f0d4aa758b71b06d47846b0fcfb796ce69dcf16855` | 새 빌드와 일치 |
| Android 배포 APK의 `lib/arm64-v8a/libfovmod.so` | `0f48b8b0c92b9c0e57ae67cb19e41740ac7a00675a452680f5ef56aa23b11a3b` | 새 빌드와 일치 |
| Android 기존 서명으로 재서명한 APK 전체 | `73e4a804bfe2f70448a6b6c8d1844429198fd3cfb9494b29a9e6a0350ee65411` | 기존 전달본과 일치 |
| Android unsigned APK 전체 | `9e43f0f3d6de484c172e866e6056d32bf87ef35082277aeccc33a97a19db4edd` | 과거 unsigned APK와 일치 |
| PlayCover 서명된 주 실행 파일 `Payload/global.app/global` | `a835e8237187375415b745e36f28bf3aded6576f149057c6e11616690f794d96` | Linux 재현 빌드와 일치 |
| PlayCover 서명된 `Frameworks/SIFASMVExport.dylib` | `727be49d92ca6978e73e6cb94c43ecbb0eb8587429848198781a65285cf60995` | Linux 재현 빌드와 일치 |

Android Manifest와 `libunity.so`, `libil2cpp.so`의 세 변경 항목도 기존 배포본과 일치했다. Android 테스트 42건과 PlayCover 테스트 24건이 통과했다. PlayCover는 1,355개 ZIP 항목의 압축 해제한 바이트가 일치했다. IPA 외부 ZIP의 SHA-256은 새 dylib 한 개와 서명 리소스 두 개의 DOS 타임스탬프가 달라 달라질 수 있다. IPA 결과는 Linux에서 서명 페이지와 패키징을 검사한 것이며 PlayCover 게임 실행 결과는 별도다.

## 이어갈 코드 위치

- Android 우측 상단 길게 누르기는 [FovMod.java](ci/sifas_mv_export/android/FovMod.java)의 `CornerHold`와 `GameGesture.edge(Activity)`를 사용한다. 현재 영역은 64dp이고 `HOLD_MS`는 2,000ms다. 영역 크기와 시간 설정을 추가할 때 시간 제한을 참조하는 상태 머신과 타이머 예약을 함께 확인한다.
- Android 인게임 버튼의 `Save and close`는 [FovMod.java](ci/sifas_mv_export/android/FovMod.java)에서 익명 클릭 리스너와 함께 만들어진다. 생성된 `FovMod$7` 파일 대신 Java 소스를 수정한다. 별도 `FovSettingsActivity`의 두 메서드는 [UpdateFovDex.java](ci/sifas_mv_export/android/UpdateFovDex.java)에서 패치한다.
- Android 목록은 [AndroidMVExport.java](ci/sifas_mv_export/android/AndroidMVExport.java)의 `QueueItem`, `combined_sources`, `CombinedRun`과 [AndroidMVEncoder.java](ci/sifas_mv_export/android/AndroidMVEncoder.java)의 합본 처리를 사용한다. PlayCover의 목록과 합본은 [SIFASMVExportSession.mm](ios/native/SIFASMVExportSession.mm)과 [SIFASMVStandaloneMenu.mm](ios/native/SIFASMVStandaloneMenu.mm)에서 시작한다. 여러 묶음을 별도 MP4로 만드는 작업은 후속 구현이다.

## 2026.11.26 변경

- **Android 구석 길게 누르기:** 설정창에서 영역 32/48/64/96/128/160 dp(기본 64)와 시간 0.5/1/1.5/2/3/4/5초(기본 2)를 고른다. `fovmod` SharedPreferences의 `cornerDp`·`holdMs`에 저장하고, 누르기가 시작될 때의 시간을 끝까지 쓴다. 기존 `saveConfig`·`saveConfigAndCheck(Context,int,int,int,int)`는 그대로이고 `saveInGameConfigAndCheck`가 새로 생겼다.
- **Android 저장 버튼:** `Save and close`가 `Save`(저장/保存)로 바뀌었다. 동작은 같다.
- **묶음 합치기(양쪽):** `Combine into MP4s…`에서 MP4 여러 개를 한 번에 만든다. 클립 2개 이상은 기존 합본 경로, 1개는 일반 내보내기이고 이미 MP4가 있으면 건너뛴다. 묶음은 순서대로 백그라운드에서 돈다. 취소·재시작 필요·격리는 남은 묶음을 멈추고, 다른 실패는 다음 묶음으로 넘어간다.
- **PlayCover Queue 추가:** 게임의 `Nullable<int>`를 값과 has-value 바이트를 뒤바꿔 읽고 있었다(21.2 바이너리: 값 +0, 플래그 +4). 덱 종류와 의상 ID가 잘못 읽혀 추가가 실패한 것으로 본다. 이전 빌드가 저장한 항목은 다시 등록하라는 메시지로 막는다. 추가는 일시적인 상태에서 최대 12초 기다리고, 실패하면 메시지 끝의 `[check]` 코드와 `SIFAS-MV queue:` 로그 줄로 막힌 검사를 알린다.
- **PlayCover 구석 길게 누르기:** 소스가 없는 `SIFASFeatures.dylib`(UUID·`__text` 해시 고정)의 delegate 두 개를 런타임에 바꿔 영역과 시간을 적용한다. 바이트는 고치지 않는다. `Client settings`의 `Corner hold…`에서 고른다.
- 위 변경은 Linux 컴파일·링크와 호스트 테스트만 거쳤다. 실제 기기·PlayCover 실행은 아직이다.
