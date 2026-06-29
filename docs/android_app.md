# elichika 안드로이드 앱 (standalone APK)

Termux + `bin/install.sh` 과정을 대체하는 **설치형 APK** 입니다. 앱 하나가 elichika 서버와
개발/모드 도구를 모두 띄우고, 실제 SIFAS 게임(별도 APK)은 `127.0.0.1:8080` 으로 접속합니다.

소스/빌드 구조와 유지보수 방식은 [`../android/README.md`](../android/README.md) 를 참고하세요.

## APK 받기 / 설치

로컬 NDK 없이 **GitHub Actions** 가 APK를 빌드합니다.

1. GitHub 저장소 → **Actions** → **Build Android APK** 워크플로 → **Run workflow**
   (또는 `android/`·`main.go`·`adminui/` 변경을 푸시하면 자동 실행).
2. 완료되면 실행 페이지 하단 **Artifacts** 의 `elichika-debug-apk` 를 내려받습니다.
3. 기기에서 zip을 풀어 나온 `app-debug.apk` 를 설치합니다(출처를 알 수 없는 앱 설치 허용 필요).
   디버그 서명이라 개인 사이드로드 설치가 됩니다. 정식 서명이 필요하면
   `android/app/build.gradle.kts` 에 `signingConfig` 를 추가하고 `assembleRelease` 를 쓰세요.

## 사용법

1. 앱 실행 → **서버 시작**. 최초 1회는 서버 파일을 풀고(번들 페이로드), 서버가 뜨면 상태가
   `● 127.0.0.1:8080` 으로 바뀝니다. 포그라운드 알림이 떠 있는 동안 화면을 꺼도 서버는 유지됩니다.
2. **콘솔** 탭의 버튼으로 게임 파일 다운로드 / 마스터 데이터 재빌드 등을 실행합니다
   (이 버튼들은 `android/app/src/main/assets/actions.json` 에서 옵니다).
3. **서버 WebUI / 개발 도구 / 모드 도구** 탭은 각각 `:8080/webui`, `:8772`(adminui),
   `:8770`(webtools) 로컬 웹 UI를 보여줍니다.
4. 게임 클라이언트를 `127.0.0.1:8080` 으로 향하게 합니다(아래 "게임 연결").

## 게임 연결 (앱 범위 밖)

게임 APK가 사설 서버를 보도록 만드는 작업(DNS/hosts/프록시 또는 클라이언트 패치)은 이 앱이
하지 않습니다. 기존 Termux/embedded 방식과 동일하게 처리하세요 — LL-hax 위키 참고.

## 기능 대응표 (elichika_utility.sh → 앱)

| 메뉴 | 앱에서 |
|------|--------|
| 서버 실행/중지 | **서버 시작/중지** 버튼 |
| 게임 파일 다운로드(CDN) | 콘솔 탭 `게임 파일 다운로드` (`download_packs`) |
| 마스터 데이터 재빌드 | 콘솔 탭 `마스터 데이터 재빌드` (`rebuild_assets`) |
| CDN 소스/캐시 설정 | 서버 WebUI(admin) 페이지 |
| Developer Menu: 백업/복원, costume clone | **개발 도구** 탭 (adminui) |
| Developer Menu: costume/live/card/db installer, 사전 덮어쓰기 | 아래 "알려진 제한" 참고 |
| Mod Menu: breast/skirt/mesh/packer/extractor 등 | **모드 도구** 탭 (webtools) |
| GameBanana / AyakaMods 모드페이지 | 콘솔 탭 링크 버튼 |
| 업데이트 | 새 APK 설치(= CI 재빌드). 데이터는 보존됩니다 |

## 알려진 제한 / 향후 작업

- **Developer Menu 의 zip 설치 도구**(costume/live/card/db installer, JP 사전 덮어쓰기)는 아직
  웹 UI에 없습니다. 해당 스크립트들이 모듈 최상단에서 `input()`/`exec()` 로 동작해 그대로는
  인프로세스 호출이 안 됩니다. 래핑 레시피는 `adminui/tools/registry.py` 상단 주석에 적어 두었고,
  그 전까지는 Termux CLI 로만 사용합니다.
- **모드 도구(UnityPy 의존):** Chaquopy 가 `UnityPy`/`numpy`/`Pillow` 를 APK에 넣습니다. 일부
  텍스처 디코더 휠이 arm64 에서 빌드되지 않으면 텍스처 계열 도구가 제한될 수 있습니다(본/골격
  편집 도구는 영향 없음). CI 빌드 로그에서 pip 단계를 확인하세요.
- **DNS:** 서버는 `GOOS=android` + cgo 로 빌드되어 bionic resolver 를 써 CDN 다운로드가 됩니다.
- **지역:** JP 안드로이드 클라이언트가 검증된 경로입니다.
