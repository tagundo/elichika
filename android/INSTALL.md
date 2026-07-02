# elichika APK — install & use guide (end users)

A single Android app that runs the **elichika** private SIFAS server plus its
dev/modding tools on your phone. The SIFAS game (a separate app) connects to the
server at `127.0.0.1:8080`. No Termux, no PC required.

> **Disclaimer.** Fan-made, not affiliated with or endorsed by Bushiroad / KLab.
> For personal, educational use. You are responsible for how you use it.

---

## 1. Install

1. Download the latest `elichika-*.apk` from the release page.
2. On your phone, open it and allow **"Install unknown apps"** for your browser /
   file manager when prompted (Settings → Apps → your browser → Install unknown apps).
3. Install and open **elichika**.

All community builds share one signing key, so a newer APK installs **over** an
older one without uninstalling (your accounts/data are kept).

## 2. First run

1. Grant **storage permission** when asked — the app shares files through
   `Download/sukusta` so the game and the modding tools can see them.
2. Tap **Start**. Wait for the status to show `● 127.0.0.1:8080` (server running).
   A notification keeps it alive in the background.
3. Open the **Guide (❓)** in the app any time — it explains everything below.

Language: the app follows your system language (English / 한국어 / 日本語), or set it
in **Settings ⚙**.

## 3. Point the game at the server

Making the SIFAS client talk to `127.0.0.1:8080` is **outside this app** — it is the
same step as the Termux / other elichika setups. Follow the **LL-hax wiki**:
<https://carette.codeberg.page/ll-hax-docs/sifas/>

## 4. Game files (optional)

You do **not** have to pre-download anything. With **CDN cache** on (default), the
server fetches each missing pack on demand while you play and stores it under
`Download/sukusta/packs`. Tip: when filling the cache this way, keep **elichika in
the foreground** (not the game screen) so downloads finish without interruption.

To pre-download instead (faster first play, needs Wi-Fi):
- **Download all game files (archive.org)** — the full set; pick GL / JP / both.
- **Fetch missing only (game CDN)** — smaller, on demand.

## 5. The tabs

| Tab | What |
|-----|------|
| **Server settings / Account** | the server's Web UI (admin + user) |
| **Server content** | dev tools: costume/live/card/DB installers, backup/restore, extractor … |
| **Asset editing** | SIFAS modding tools: costume transplant, breast/skirt/mesh/texture editors, skin tone … |

Installed costume/live/card mods and edited bundles all flow through the shared
`Download/sukusta` folders (`extracted`, `modded`, `suit`, `packs`, `backup`, …).

## 6. Troubleshooting

- **Server won't start / stops** — check the **Console** tab log; use **Share log**
  to send it.
- **Game can't connect** — the server must show `● 127.0.0.1:8080`, and the client
  must be pointed at it (step 3).
- **A pack is missing in game** — keep elichika in the foreground so the CDN cache
  can download it, or pre-download (step 4).

---

<a name="ko"></a>
# 한국어 — 설치 및 사용 안내

elichika 사설 SIFAS 서버 + 개발/모딩 도구를 폰에서 실행하는 앱입니다. SIFAS 게임(별도 앱)이
`127.0.0.1:8080`으로 연결합니다. Termux·PC 불필요.

> **면책.** 팬 제작물이며 Bushiroad / KLab과 무관합니다. 개인·학습용이며, 사용 책임은 본인에게 있습니다.

**1. 설치** — 릴리스에서 `elichika-*.apk` 다운로드 → 브라우저/파일관리자에 **"출처를 알 수 없는 앱 설치"**
허용 → 설치·실행. 모든 커뮤니티 빌드는 같은 서명키라 새 APK가 기존 위에 덮어 설치됩니다(데이터 유지).

**2. 첫 실행** — 저장소 권한 허용(`Download/sukusta` 공유) → **Start** 탭 → `● 127.0.0.1:8080` 표시되면
서버 실행 중. 앱 내 **가이드(❓)**에 전체 설명이 있습니다. 언어는 시스템을 따르거나 **설정 ⚙**에서 변경.

**3. 게임을 서버로 연결** — SIFAS 클라이언트를 `127.0.0.1:8080`으로 향하게 하는 건 이 앱 범위 밖(다른
elichika 설치와 동일)입니다. **LL-hax 위키** 참고: <https://carette.codeberg.page/ll-hax-docs/sifas/>

**4. 게임 파일(선택)** — 미리 받을 필요 없습니다. **CDN 캐시**(기본 켜짐)가 플레이 중 누락 팩을 자동으로
받아 `Download/sukusta/packs`에 저장합니다. 이때 게임 화면보다 **elichika를 전면**에 두면 다운로드가 끊기지
않습니다. 미리 받으려면: **전체 다운로드(archive.org, GL/JP/둘 다)** 또는 **누락분만(게임 CDN)**.

**5. 탭** — 서버 설정/계정 = 서버 Web UI · 서버 콘텐츠 = 개발 도구(설치기·백업/복원·추출 등) ·
에셋 편집 = 모딩 도구(의상 이식·가슴/치마/메시/텍스처·스킨톤 등).

**6. 문제 해결** — 서버 안 켜짐: **콘솔** 로그 확인 · 게임 연결 안 됨: `● 127.0.0.1:8080` + 3단계 확인 ·
팩 누락: elichika를 전면에 두거나 미리 다운로드.
