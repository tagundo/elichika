# 조사 노트 — elichika 안드로이드 앱(APK)의 iOS(IPA) 이식 가능성

`android/`(standalone APK, [`docs/android_app.md`](android_app.md))를 아이폰/아이패드에서
같은 방식으로 돌릴 수 있는지 조사한 결과입니다. **구현은 하지 않았고**, 저장소 코드 분석 +
공개 자료 확인만 했습니다.

> **결론 한 줄**: "APK를 IPA로 변환"은 존재하지 않는 작업이고(형식·런타임이 완전히 다름),
> 셸(Kotlin 1,386줄)을 Swift로 **다시 쓰는 이식**은 기술적으로 가능합니다. 다만 iOS의
> **백그라운드 실행 제약**과 **서명/배포 제약** 때문에 안드로이드 앱의 핵심 가치(한 기기에서
> 원클릭 완결)가 대부분 사라집니다. 그리고 **서버는 이미 iOS 클라이언트를 완전히 지원**하므로,
> iOS 유저는 지금도 LAN의 elichika에 붙어서 그냥 플레이할 수 있습니다 — 이식의 실익이 낮습니다.

---

## 1. "APK → IPA 변환기"는 없다

|            | APK                                        | IPA                                          |
|------------|--------------------------------------------|----------------------------------------------|
| 실행 코드 | DEX 바이트코드(ART) + ELF `.so`             | Mach-O arm64 (정적 링크)                      |
| 프레임워크 | Activity / Service / WebView / Chaquopy     | UIKit·SwiftUI / WKWebView / (Chaquopy 없음)   |
| 설치       | 자체 서명 후 아무 기기에 사이드로드          | 프로비저닝 프로파일 + 코드서명 필수            |
| 프로세스   | `ProcessBuilder`로 별도 실행파일 exec 가능   | **exec 금지**(앱 번들의 메인 바이너리만 실행)  |

바이너리 호환성이 0이라 자동 변환은 원리적으로 불가능합니다("apk to ipa converter"를 표방하는
사이트는 전부 광고성입니다). 실제로 가능한 건 **네이티브 셸 재작성 + 페이로드 재사용**입니다.

---

## 2. 이식할 때 재사용되는 것 / 다시 써야 하는 것

### 그대로 재사용 (앱 가치의 대부분)

| 자산 | 근거 |
|------|------|
| Go 서버 전체 | 일반(`!embedded`) 빌드에 **cgo가 한 줄도 없음** — `import "C"`는 `embedded/jni.go`, `log/log_embedded_android.go` 둘뿐이고 둘 다 `//go:build embedded` |
| SQLite | `modernc.org/sqlite` = **순수 Go**(cgo 불필요) |
| 서버 WebUI (`webui/`) | Go가 서빙, 클라이언트는 WebView뿐 |
| 개발 도구 `adminui/` | 순수 stdlib `http.server` (`elichika_launch.py`) |
| 번들 페이로드 | `assets/`, `serverdata.db`, `server init jsons/`, `*.pem` — 전부 데이터 |
| `actions.json` | 선언형 메뉴, 플랫폼 무관 |

### 다시 써야 하는 것 (Kotlin 1,386줄 + Gradle/Chaquopy)

| 안드로이드 | 줄수 | iOS 대응 | 난이도 |
|-----------|-----:|----------|--------|
| `ServerProcess` (`libelichika.so`를 subprocess로 exec) | 85 | **exec 불가** → Go를 `-buildmode=c-archive`(GOOS=ios) 또는 `gomobile bind`로 정적 라이브러리/xcframework화, 앱 프로세스 안에서 goroutine 실행 | **높음** (§3-C) |
| `ServerService` (foreground service + wake lock) | 230 | 대응물 없음 | **최상** (§3-A) |
| `PyServers` (Chaquopy) | 49 | BeeWare `Python-Apple-support`로 CPython 임베드 | 중~높음 (§3-D) |
| `MainActivity` (탭·콘솔·WebView·설정·파일피커) | 664 | SwiftUI + `WKWebView` (거의 1:1) | 중 |
| `AssetInstaller` (payload 추출, `Download/sukusta` 공유폴더) | 227 | Bundle→Documents 복사 + `UIFileSharingEnabled` | 낮음 |
| `Bus`, `Lang` | 131 | Combine + `Localizable.strings` | 낮음 |
| `MANAGE_EXTERNAL_STORAGE`, `Intent(ACTION_SEND/VIEW)`, 알림 | — | Documents 노출, `UIActivityViewController`, `UNUserNotificationCenter` | 낮음 |
| Gradle CI (`.github/workflows/android.yml`) | — | Xcode 프로젝트 + **macOS 러너** (unsigned `.ipa` 산출) | 중 |
| `usesCleartextTraffic` | — | ATS `NSAllowsLocalNetworking` (루프백은 로컬네트워크 권한 프롬프트 대상 아님) | 낮음 |

---

## 3. 장벽 4개 (심각도 순)

### A. 백그라운드 실행 — 설계 자체를 바꾸는 문제

게임(별도 앱)을 포그라운드로 띄우는 순간 서버 앱은 **suspend**되고 `127.0.0.1:8080`이 죽습니다.
안드로이드의 foreground service + wake lock(`ServerService`)에 해당하는 게 iOS에는 없습니다.

- `UIBackgroundModes: audio` + 무음 재생 — iSH 등이 쓰는 방식. 사이드로드에선 동작하지만
  App Store 규정 위반이고, 배터리 소모, 게임 오디오 세션과의 충돌(`.mixWithOthers` 필요),
  OS 업데이트로 언제든 막힐 수 있는 회색 지대.
- `beginBackgroundTask`는 ~30초, VoIP/`NEAppPushProvider`는 특수 엔타이틀먼트라 개인 사이드로드 불가.
- 근본 해결은 **서버를 게임 프로세스 안에 넣는 것**뿐입니다(§5 선택지 C).

### B. 서명·배포 — "APK 하나 받아서 설치"가 불가능

App Store 배포는 애초에 선택지가 아닙니다(사설 서버 + 저작권). 남는 경로:

| 경로 | 유효기간 | 제약 |
|------|---------|------|
| 무료 Apple ID + SideStore/AltStore | **7일**마다 재서명 | 앱 3개 제한, 주 10 App ID |
| 유료 개발자 계정 ($99/년) | 1년 | ad-hoc 100대, UDID 등록 |
| TrollStore (영구) | 영구 | **iOS 17.0 이하 전용** — 18/26에는 없음 |
| AltStore PAL 등 대체 마켓 | — | EU/일본/브라질 한정 + 배포자 법인 요건 |

즉 어떤 경로든 사용자 쪽 절차가 안드로이드보다 훨씬 무겁습니다. 현재 릴리스 APK가 **276 MB**
(`elichika-2026.08.15.1.apk`)인데, 7일마다 재서명하는 운용을 전제해야 합니다.

### C. 프로세스 격리 상실 — 조용하지만 광범위한 문제

현재 구조는 Kotlin이 서버를 **별도 프로세스**로 띄우기 때문에, 서버가 죽어도 앱은 살아서 종료
코드를 로그에 찍습니다. in-process로 바뀌면:

- 이 저장소에는 `utils.CheckErr`/`log.Panic` 호출이 **1,119곳**(516개 파일)입니다. gin의 Recovery는
  요청 핸들러만 감싸므로, **init/CLI 경로의 panic은 앱 전체를 죽입니다**.
- `config`·`clientdb`·`locale`·`userdata`의 초기화가 패키지 `init()`이라 **한 프로세스에서 1회**만
  성립합니다 → "서버 중지 후 재시작"이 지금처럼 kill+exec가 아니라 gin만 `Shutdown()`하고 상태를
  되돌리는 리팩터링이 필요합니다(`shutdown` 패키지는 프로세스 종료 전제로 짜여 있음).
- 콘솔 액션(`download_packs`, `rebuild_assets`, `download_archive`, `reset_accounts`, `cdn_cache`)은
  현재 `main.go`의 `os.Args` 분기입니다. c-archive에서는 **exported 함수로 재노출**해야 하고,
  실패 시 프로세스가 죽는 대신 에러를 반환하도록 고쳐야 합니다.
- `libastcenc.so`(ASTC 인코더 CLI)도 exec으로 부르므로 **라이브러리로 링크**하거나 포기해야 합니다.

이건 안드로이드의 `embedded` 빌드 태그(게임 프로세스에 서버를 심는 변종)가 이미 밟아본 패턴이라
선례는 있습니다 — `embedded_main.go`가 `init()`에서 gin을 띄우고 `main()`을 비워두는 구조.

### D. 임베디드 파이썬 + 네이티브 의존성

Chaquopy(안드로이드 전용)의 iOS 대응물은 BeeWare `Python-Apple-support`입니다(CPython 3.13의
PEP 730 iOS 지원, tier-3). 결과:

- **개발 도구(`adminui`)**: stdlib만 쓰므로 이식 가능. ✅
- **모드 도구(`webtools`)**: UnityPy + `lz4`/`brotli`(C 확장) + `numpy`/`Pillow` + `astcenc` 실행파일.
  iOS는 확장 모듈을 **개별 `.framework`로 서명·번들**해야 하고 iOS wheel 생태계가 사실상 없어서
  직접 빌드(mobile-forge)해야 합니다 → **1차 이식에서는 모드 도구가 통째로 빠집니다**. ❌

---

## 4. 중요한 사실 — 서버는 **이미** iOS 클라이언트를 지원한다

이식 논의보다 실익이 큰 부분입니다. 서버 코드에 iOS를 위해 고칠 게 없습니다:

- `locale/locale.go`의 `LoadAsset()`이 `asset_a_<lang>.db`(안드로이드)와 **`asset_i_<lang>.db`(iOS)를
  둘 다** 로드합니다.
- `clientdb/clientdb.go`가 `config.Platforms = {"a", "i"}`로 `masterdata_a_*`/`masterdata_i_*`를 모두
  리키잉합니다.
- `enum/platform.go`에 `PlatformApple`(=iOS)가 정의돼 있고, `download_packs`는 팩 이름 기준으로
  두 플랫폼 팩을 모두 받습니다(그만큼 캐시 용량은 늘어납니다).

그리고 커뮤니티 문서(LL Hax) 기준 **SIFAS iOS 클라이언트는 ipa 패치 없이 사이드로드 후 설정 화면에서
서버 URL을 직접 입력**할 수 있습니다(단 `Info.plist`의 `NSAllowsArbitraryLoads`를 켜야 평문 HTTP가
됩니다 — 미리 패치된 ipa도 배포됨). 즉 **아이폰 유저는 PC/맥/라즈베리파이/같은 Wi-Fi의 안드로이드
폰에서 도는 elichika를 가리키기만 하면 지금 당장 플레이됩니다.** `docs/hosting.md`가 말하는 그
경로입니다.

→ iOS 포팅의 순수한 이득은 **"기기 하나로 완결"** 뿐인데, 그게 정확히 §3-A 때문에 제일 깨지기 쉬운
부분입니다.

---

## 5. 선택지 비교

| # | 접근 | 작업량 | 백그라운드 문제 | 모드 도구 | 배포 |
|---|------|--------|----------------|-----------|------|
| **A** | **포팅 안 함** — iOS 클라 → LAN의 elichika | **0** (문서만) | 없음(서버가 다른 기기) | 그대로 유지 | 없음 |
| **B** | Swift 셸 + Go c-archive (앱 1개) | 큼 (셸 재작성 + §3-C 리팩터링) | 무음오디오 꼼수에 의존 | 1차엔 없음 | 7일 재서명 |
| **C** | 게임 IPA에 dylib 주입 (`embedded`의 iOS판) | 중~큼 + 재서명 파이프라인 | **구조적으로 해결**(같은 프로세스) | 없음 | 게임 재서명 필요 |
| **D** | iSH/a-Shell 안에서 실행 | 작음 | 여전히 있음 | 없음 | — |

- **A (권장)**: 실익 대비 비용이 압도적으로 좋습니다. `README.md`/`docs/hosting.md`에 "아이폰은 서버를
  다른 기기에 두고 클라 설정에서 주소를 바꾸면 된다"를 명시하는 정도면 충분합니다.
- **B**: "아이폰 하나로 완결"을 정말 원할 때. 단 사용자는 매주 재서명 + 백그라운드 꼼수 + 모드 도구
  부재를 감수해야 합니다.
- **C**: 백그라운드 문제가 사라지는 유일한 정공법(서버가 게임 프로세스 안에서 돎). 안드로이드
  `embedded` 프로젝트와 같은 발상이고, iOS에선 c-archive → dylib → 게임 번들 `Frameworks/`에 넣고
  load command 추가(`insert_dylib`) → 재서명. 다만 **복호화된 게임 IPA 재배포**가 전제라 이 저장소
  범위 밖이고, Unity IL2CPP 앱 안에서 Go 런타임이 공존하는지 실측이 필요합니다.
- **D**: iSH는 x86 에뮬레이션이라 arm64 Go 바이너리를 못 돌리고(별도 x86 빌드 필요) 성능이 처참합니다.
  실용성 없음.

---

## 6. 그래도 B/C를 시도한다면 — 최소 검증 순서 (전부 Mac + Xcode 필요)

1. **`GOOS=ios GOARCH=arm64 CGO_ENABLED=1 go build -buildmode=c-archive`가 이 저장소에서 통과하는가.**
   최대 리스크는 `modernc.org/sqlite`(+`modernc.org/libc`)입니다. Go는 `GOOS=ios`에서 `darwin` 태그와
   `_darwin*` 파일 접미사를 함께 인정하므로 darwin/arm64 생성 코드가 그대로 먹힐 **가능성이 높지만
   미검증**입니다. 실패하면 cgo용 `mattn/go-sqlite3`로 갈아타야 하고, 드라이버명 변경이 xorm 사용처
   전반에 파급됩니다.
2. 빈 SwiftUI 앱에 정적 라이브러리를 링크해 서버를 띄우고 `curl 127.0.0.1:8080`이 200을 주는지.
3. **게임을 포그라운드로 올린 상태에서 무음오디오 백그라운드 모드로 서버가 몇 시간 버티는지 실측.**
   여기서 막히면 B는 폐기하고 C만 남습니다.
4. 그 다음에야 CPython 임베드 → `adminui` → (선택) 모드 도구 wheel 빌드.

1~3번이 전부 통과해야 의미가 있고, 각각이 독립적으로 프로젝트를 중단시킬 수 있습니다.

---

## 7. 미확인 / 리스크 목록

- `modernc.org/sqlite`의 ios/arm64 빌드 (위 1번) — **가장 큰 미지수**.
- in-process 전환 후 `init()` 1회성 문제와 panic 전파를 실제로 어디까지 손봐야 하는지 (1,119곳 전수
  수정이 아니라, init/CLI 경로만 감싸면 되는지 실측 필요).
- 팩 캐시 용량: iOS 팩까지 받으면 수 GB. iOS는 앱 삭제 시 데이터가 함께 사라지고, iCloud 백업 제외
  플래그(`isExcludedFromBackup`)를 안 걸면 백업이 폭발합니다.
- Unity IL2CPP 게임 프로세스 + Go 런타임 공존(선택지 C) — 시그널 핸들러 충돌 여부 미검증.
- 무음오디오 백그라운드 유지가 최신 iOS에서 얼마나 오래 버티는지 — 실측 필요.

---

## 출처

- 저장소 내부 근거: `android/README.md`, `.github/workflows/android.yml`,
  `android/app/src/main/java/com/tagundo/elichika/*.kt`, `main.go`, `embedded_main.go`,
  `embedded/jni.go`, `locale/locale.go`, `clientdb/clientdb.go`, `enum/platform.go`, `go.mod`
- LL Hax Docs — SIFAS 사설 서버(iOS 클라 사이드로드 / 서버 URL 설정 / `NSAllowsArbitraryLoads`):
  <https://carette.codeberg.page/ll-hax-docs/sifas/private-server/>
- PEP 730 — Adding iOS as a supported platform: <https://peps.python.org/pep-0730/>
- BeeWare Python-Apple-support: <https://github.com/beeware/Python-Apple-support>
- gomobile (`bind` → xcframework, `-buildmode=c-archive`):
  <https://pkg.go.dev/golang.org/x/mobile/cmd/gomobile>
- 백그라운드 유지(무음 오디오) 논의: <https://developer.apple.com/forums/thread/750136>
- 사이드로딩 현황(SideStore/AltStore 7일·TrollStore는 iOS 17.0 이하):
  <https://sideloadly.io/faq.html>
