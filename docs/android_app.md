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
| 업데이트 | 새 APK 설치. 기존 모드·계정 데이터를 유지하며 새 기본 데이터를 병합합니다 |

## 업데이트와 모드 보존

일반 APK 업데이트는 기존 의상·라이브·번역·자산 연결과 계정의 선택·소유 기록을 함께 유지합니다.
새 기본 데이터는 복사본에 병합하고 검증한 뒤 적용합니다. 준비 중 실패하거나 저장 공간이 부족하면
기존 DB를 교체하지 않으며, 적용 도중 앱이 종료되면 다음 준비에서 복구합니다.

처음 이 방식으로 업데이트하는 기존 설치는 비교할 과거 기본 DB가 없으므로 기존 행을 우선 유지하고
새 항목을 추가합니다. 이후에는 보관한 기본 DB와 비교해 사용자가 수정하지 않은 공식 행도 갱신합니다.
서로 맞지 않는 스키마나 데이터 제약 충돌은 임의로 덮어쓰지 않고 적용을 중단합니다.

앱의 백업 복원 기능을 사용하면 복원한 데이터에 현재 APK의 새 항목을 다시 병합합니다. 의상 정의,
자산·사전 DB, 서버 DB와 계정 DB는 같은 시점의 백업 세트로 복원해야 선택 기록이 어긋나지 않습니다.
파일 관리자로 일부 DB만 교체하는 작업은 이 복원 절차에 포함되지 않습니다.

**서버 초기화 (모드 제거)** 는 별도 기능입니다. 원본 게임 데이터를 복원하고 게임 계정 상태를
다시 생성하며 로그인 인증만 유지합니다. 일반 업데이트에 이 기능이나 마스터 데이터 재빌드는 필요하지 않습니다.
이미 초기화로 삭제된 모드 정의는 새 APK만으로 재생성되지 않으므로 해당 모드나 백업이 필요합니다.

## 알려진 제한 / 향후 작업

- **Developer Menu 의 zip 설치 도구**(costume/live/card/db installer, JP 사전 덮어쓰기)는 아직
  웹 UI에 없습니다. 해당 스크립트들이 모듈 최상단에서 `input()`/`exec()` 로 동작해 그대로는
  인프로세스 호출이 안 됩니다. 래핑 레시피는 `adminui/tools/registry.py` 상단 주석에 적어 두었고,
  그 전까지는 Termux CLI 로만 사용합니다.
- **모드 도구(UnityPy 의존):** 현재 Chaquopy 가 `numpy`/`Pillow` 만 APK에 넣고 **`UnityPy` 는
  넣지 않습니다.** UnityPy 가 Chaquopy 프리빌트 휠 저장소에 없고 네이티브 디코더 의존성
  (texture2ddecoder/etcpak 등)이 arm64 빌드에 실패해 APK 빌드 전체를 깨뜨리기 때문입니다.
  모드 도구는 UnityPy 를 lazy import 하므로 없을 때 안내 메시지로 graceful 하게 동작하고, 서버·개발
  도구·UnityPy 비의존 경로는 정상 동작합니다. arm64 용 UnityPy 휠 세트가 마련되면
  `android/app/build.gradle.kts` 의 pip 블록에 `install("UnityPy")` 를 다시 추가하세요.
- **DNS:** 서버는 `GOOS=android` + cgo 로 빌드되어 bionic resolver 를 써 CDN 다운로드가 됩니다.
- **지역:** JP 안드로이드 클라이언트가 검증된 경로입니다.
