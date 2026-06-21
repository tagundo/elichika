# SIFAS에 커스텀 3D 댄스 라이브 넣기 (Dance Live Timeline)

오디오만 있고 **3D 댄스(MV)가 없는 곡**(예: μ's 마키의 *Daring!!*)에, *noesis-llsifac*
으로 SIFAC → SIFAS 리타겟팅한 댄스를 **하나의 라이브로 만들어 넣는** 방법과 도구를
설명합니다. 입술 움직임·표정·무대·무대 이펙트·카메라까지 어디까지 넣을 수 있는지도
정리합니다.

> 핵심 도구: **`live_dance_installer.py`** (GUI/CLI) + **`live_install_core.py`** (엔진).
> 기존 `camera_live_timeline_replacer.py`는 타임라인 파일 **하나만 교체**하지만, 이 도구는
> 타임라인 + 댄스 모션(+표정 등)과 의존성, 무대/이펙트, 그리고 *댄스가 없던 곡*의
> `m_live_3d_asset` 생성·연결까지 **한 번에** 처리합니다.

**English summary at the bottom → [English](#english).**

---

## 1. 큰 그림 — 3개 저장소가 이어지는 파이프라인

하나의 댄스 라이브는 세 저장소의 결과물이 합쳐져 완성됩니다.

```
[noesis-llsifac]                 [SIFAS-MODDING-HELPING-TOOLS]            [elichika]
SIFAC 댄스 FBX                    라이브 타임라인 에셋(UABEA/UnityPy)        서버 DB 설치
  │ sifac_anim_retarget.py         │ live_timeline/ 5단계 스크립트           │ live_dance_installer.py
  ▼                                 ▼ (입싱크: SCD → 입모양 A/I/U/E/O/N)       ▼ (이 문서)
SIFAS .anim ──► sifac_anim_to_bundle.py ──► 댄스 모션 번들 ┐               곡 선택(이름) → 에셋 암호화·등록
                                                          ├─► 라이브 타임라인 + 의존성 + 무대/이펙트
                          도너 라이브 타임라인(카메라/연출) ┘               → m_live_3d_asset 업데이트/생성
```

| 단계 | 저장소 | 산출물 |
|------|--------|--------|
| ① 리타겟 | noesis-llsifac | SIFAC 댄스 → SIFAS `.anim` (`sifac_anim_retarget.py`) |
| ② 번들화 | noesis-llsifac | `.anim` → 게임용 모션 **AssetBundle** (`sifac_anim_to_bundle.py`, DenseClip) |
| ③ 타임라인 편집 | SIFAS-MODDING | 도너 라이브 타임라인에 입싱크/연출 적용 (`live_timeline/` 1~5번) |
| ④ **설치** | **elichika** | 곡에 댄스 연결 + 에셋 등록 (**이 문서의 도구**) |

④번이 그동안 "쉬운 도구"가 없던 빠진 고리였습니다.

---

## 2. 무엇을 넣을 수 있나 (조사 결과)

SIFAS 라이브 타임라인(`LiveTimelineData` 에셋)과 elichika DB(`asset_manager/generic_asset.go`,
`camera_live_timeline_replacer.py`)를 분석한 결과입니다.

| 요소 | 저장 위치 | 가능? | 연결 방법 |
|------|-----------|:----:|-----------|
| **댄스(몸 모션)** | 별도 모션 번들(AnimationClip) | ✅ | noesis ①②로 번들 생성 → 타임라인 **의존성**으로 등록 |
| **입술(립싱크)** | **라이브 타임라인 에셋 내부** mouth TimelineClip<br>(`m_DisplayName`=A/I/U/E/O/N, `m_Start`/`m_Duration`/`index`/`weight`) | ✅ | SIFAS-MODDING `live_timeline/` SCD 워크플로우. SIFAC `*_lyrics_*.scd`(`Scor` 매직) → 입모양 |
| **표정(facial)** | 별도 자산 팩 `member_facial` / `member_facial_animation` + 타임라인 facial 트랙 | ✅(구조상) | 자산으로 등록 + 의존성. SCD가 `*facial*.scd`도 같은 포맷으로 다룸 |
| **무대(stage)** | 자산 테이블 `stage` + `m_live_3d_asset.live_stage_master_id` | ✅ | **DB 컬럼 1개** — 가장 쉬움 |
| **무대 이펙트** | 자산 테이블 `stage_effect` + `m_live_3d_asset.stage_effect_asset_path` | ✅ | **DB 컬럼 1개** — 가장 쉬움 |
| **카메라** | 라이브 타임라인 에셋 내부 카메라 트랙 | ✅ | 타임라인 에셋에 포함(도너 타임라인 그대로 또는 편집) |

**정리**
- **입술·카메라**는 라이브 타임라인 에셋 *자체*에 들어 있습니다. 그래서 "댄스 라이브
  타임라인"과 "카메라 라이브 타임라인"은 사실 **같은 타임라인 에셋의 다른 트랙**이거나,
  별도 의존성 에셋입니다. 이 도구는 타임라인을 통째로 등록하므로 둘 다 따라옵니다.
- **표정·무대·무대이펙트**는 *별도 자산 팩*입니다. 무대/이펙트는 `m_live_3d_asset`의
  컬럼만 바꾸면 되고(도구가 드롭다운으로 노출), 표정은 자산 등록 + 의존성 연결로 넣습니다.
- 모든 자산 테이블(`live_timeline`, `member_facial`, `stage_effect`, …)은 동일한 6컬럼
  형태 `(asset_path, pack_name, head, size, key1, key2)`라서(`generic_asset.go` 확인),
  엔진의 `register_asset_row()` 하나로 종류에 상관없이 등록합니다.

---

## 3. 도구 사용법 — `live_dance_installer.py`

### GUI (데스크톱)

```bash
python3 live_dance_installer.py
```

1. **게임 DB 폴더(assets)** 를 지정하고 **Load songs**. 곡 목록이 이름으로 뜨고,
   *댄스가 없는 곡*만 보도록 필터할 수 있습니다(`Daring` 같은 곡 찾기 쉬움).
2. **대상 곡**을 고릅니다. 댄스가 없으면 "NONE (will clone a donor)"로 표시됩니다.
3. **Assets** 에 파일을 추가합니다:
   - *Live timeline* = ②③에서 만든 라이브 타임라인 에셋 (**TIMELINE**으로 표시)
   - *Dance motion* = noesis ②의 모션 번들 (의존성으로 자동 연결)
   - 필요하면 *Facial* / *Facial animation* 추가
4. **Stage / Stage effect** 를 카탈로그(드롭다운)에서 고릅니다. (선택)
5. **Preview (dry run)** 로 바뀔 내용을 확인 → 문제 없으면 **Install** (DB 백업 자동).

### CLI / 헤드리스 (Termux·서버)

```bash
# 곡 목록 (댄스 없는 곡만)
python3 live_dance_installer.py --db assets --list-songs --no-dance-only

# 무대 / 이펙트 카탈로그
python3 live_dance_installer.py --db assets --list-stages
python3 live_dance_installer.py --db assets --list-effects

# Daring(live_id 1002)에 댄스 라이브 설치 — 먼저 미리보기
python3 live_dance_installer.py --db assets --live-id 1002 \
    --timeline daring_timeline.bytes --motion daring_motion.bundle \
    --stage 12 --effect my_stage_effect --dry-run

# 실제 설치 (자동 백업)
python3 live_dance_installer.py --db assets --live-id 1002 \
    --timeline daring_timeline.bytes --motion daring_motion.bundle --stage 12
```

설치 후, `camera_live_timeline_replacer.py`와 마찬가지로 `config.json`의 `cdn_server`가
`http://127.0.0.1:8080/static`을 가리켜야 클라이언트가 새 에셋을 받습니다.

---

## 4. 모드와 난이도 — replace vs add

곡에 댄스를 **새로 넣는 것**과 **기존 댄스를 바꾸는 것**은 다릅니다. 그리고
`m_live_difficulty`는 **난이도(이지·노말·어려움)별로 분리된 row**이고, 각 난이도가
자기 `live_3d_asset_master_id`(=댄스)를 가집니다. 그래서 이 도구는 모드와 난이도를
명시적으로 다룹니다.

**세 도구의 역할 구분**

| 도구 | 하는 일 | 난이도 처리 |
|------|---------|-------------|
| `live_addon_installer.py` | **새 곡 자체**를 추가(m_live + 비트맵 + 오디오) | 이지/노말/어려움 난이도를 **새로 생성**(댄스는 NULL) |
| `camera_live_timeline_replacer.py` | 기존 3D 곡의 타임라인 **하나 교체** | 기존 난이도 그대로(공유 3D 에셋 수정) |
| **`live_dance_installer.py` (이 도구)** | 기존 곡에 **댄스를 붙이거나 교체** | 아래 모드로 난이도별 선택 |

**두 가지 모드**

- **`replace`** — 곡에 **이미 댄스가 있을 때**. 그 곡의 `m_live_3d_asset` 한 줄을
  업데이트하므로, 그 에셋을 공유하는 **모든 난이도**가 한 번에 새 댄스가 됩니다
  (기존 `camera_live_timeline_replacer.py`와 같은 동작).
- **`add`** — 곡에 **댄스가 없을 때**(Daring 등 NULL), **또는 특정 난이도에만 다른
  댄스**를 주고 싶을 때. 도너 row를 복제해 **새 3D 에셋**을 만들고, **선택한 난이도의**
  `live_3d_asset_master_id`만 거기로 재연결합니다.
- **`auto`**(기본) — 곡에 댄스가 있으면 `replace`, 없으면 `add`로 자동 결정.

**난이도 선택**

GUI는 곡을 고르면 난이도별 체크박스(Easy/Normal/Hard, 댄스 유무 표시)를 보여주고,
CLI는 타입으로 고릅니다(10=Easy, 20=Normal, 30=Hard):

```bash
# Daring의 '어려움(Hard)'에만 댄스를 추가
python3 live_dance_installer.py --db assets --live-id 1002 \
    --timeline daring_hard.bytes --mode add --difficulty-types 30

# 곡 목록을 난이도별 댄스 상태와 함께 보기
python3 live_dance_installer.py --db assets --list-songs
#  live_id=1002 ... [NO DANCE] Daring   Easy:— Normal:— Hard:—
```

팩(`modinstall.txt`)에는 난이도 **id가 아니라 타입**(`target_difficulty_types`)으로
저장되어 DB가 달라도 안전하게 이식됩니다.

---

## 5. 동작 원리

설치 한 번이 하는 일(`live_install_core.install_dance_live`):

1. **암호화** — 각 에셋을 XOR PRNG(시드 `12345/0/0`, `manipulate_file`)로 암호화해
   `static/<pack_name>`에 저장. (기존 설치기와 바이트 단위로 동일)
2. **자산 등록** — 8개 자산 DB(`asset_a`/`asset_i` × gl/jp) 모두에:
   - `live_timeline`(또는 `member_facial` 등) 한 줄 + `m_asset_pack`
   - CDN: `m_asset_package_mapping` + `m_asset_package`
3. **의존성 연결** — 대상 곡이 이미 댄스가 있었다면 기존 타임라인의 의존성을 새
   타임라인으로 복사(`live_timeline_dependency`). 추가한 모션/표정 에셋도 새 타임라인의
   의존성으로 등록.
4. **`m_live_3d_asset` 처리(스키마-불문)** — gl·jp masterdata 모두에:
   - 곡에 3D 에셋이 **있으면** → `timeline`, `live_stage_master_id`,
     `stage_effect_asset_path`, `quality_setitng_set_id`, `shader_variant_asset_path` 중
     존재하는 컬럼만 **UPDATE**.
   - 곡에 3D 에셋이 **없으면**(NULL, 댄스 없는 곡) → 도너 row를 `SELECT *`로 **통째 복제**해
     새 `id` 부여(컬럼 목록은 `PRAGMA`로 런타임에 읽음 → 모르는 컬럼도 보존), 위 값 적용,
     그리고 그 곡의 `m_live_difficulty.live_3d_asset_master_id`를 새 id로 **재연결**.
     새 id는 gl·jp에서 **하나로 공유**합니다.

스키마를 하드코딩하지 않고 `PRAGMA table_info` / `SELECT *`로 다루기 때문에, 실제 게임
DB에 "카메라 타임라인" 같은 추가 컬럼이 있어도 `--shader`/`extra_columns`로 그대로
설정할 수 있고, 복제 시에도 보존됩니다.

---

## 6. 배포용 모드 팩 — `modinstall.txt`가 늘어나는 부분

elichika의 설치기들은 **`modinstall.txt`(파이썬 `name = value` 모음)** 와 에셋이 든
`.zip` 팩을 읽습니다(`camera_live_timeline_replacer.py`, `costume_addon_installer.py`,
`live_addon_installer.py`). 그래서 댄스를 더 넣을수록 이 `modinstall.txt`도 **자연히
늘어납니다** — 타임라인 파일 하나가 아니라 댄스 모션·표정 파일과 의존성 정보, 대상
곡까지 담아야 하기 때문입니다.

**예전 (카메라 타임라인 1개)**

```python
live_timeline_file = "my_timeline.bytes"
live_timeline_num = 30001            # 업데이트할 m_live_3d_asset.id
timeline = "deadbeef"               # 의존성을 복사해올 도너 타임라인 asset_path
live_stage_master_id = 7
stage_effect_asset_path = ""
quality_setitng_set_id = None
shader_variant_asset_path = ""
```

**지금 (댄스 라이브 한 벌)** — 위 변수에 **다음이 추가**됩니다:

```python
# --- dance-live extras (live_dance_installer.py가 읽고, 옛 카메라 설치기는 무시) ---
install_mode = "add"                # auto | replace | add
target_live_id = 1002               # 댄스를 붙일 곡(GUI에선 이름으로 선택)
donor_3d_asset_id = 9001            # 댄스 없는 곡일 때 복제할 도너 row
target_difficulty_types = []        # [] = 전체; 예: [30] = 어려움(Hard)에만
dependency_files = ["daring_motion.bundle", "daring_facial.bundle"]
dependency_tables = {"daring_facial.bundle": "member_facial"}
```

추가 변수는 **옛 설치기가 무해하게 무시**하도록 했습니다(코스튬 패커의 듀얼 플랫폼
`costume_file_ios`와 같은 방식). 즉 같은 팩으로 옛 설치기는 타임라인만 설치하고, 새
`live_dance_installer.py`는 모션·표정까지 모두 설치합니다.

**손으로 쓸 필요는 없습니다.** 이 도구가 팩을 만들고/읽습니다:

```bash
# 팩 만들기(.zip + modinstall.txt 자동 생성) — DB는 건드리지 않음
python3 live_dance_installer.py --db assets --live-id 1002 \
    --timeline daring_timeline.bytes --motion daring_motion.bundle \
    --stage 7 --build-pack daring_dance.zip

# 팩 설치하기
python3 live_dance_installer.py --db assets --pack daring_dance.zip
```

GUI에도 **Build pack… / Install from pack…** 버튼이 있습니다. 팩의 `modinstall.txt`는
`exec()`가 아니라 `ast`로 **안전하게 파싱**합니다(코드 실행 없음).

> 참고: 댄스가 없던 곡(`live_3d_asset_master_id = NULL`)은 옛 카메라 설치기로는
> 안 됩니다(존재하지 않는 id를 UPDATE하므로). 이런 곡은 새 도구의 **복제+재연결**
> 경로가 처리합니다.

---

## 7. 한계와 주의

- **실제 게임 DB로의 검증은 직접 해야 합니다.** 이 저장소엔 게임 DB가 없어서, 엔진은
  실제 스키마 *형태*를 모사한 합성 DB(`tests/test_live_install_core.py`)로 검증했습니다.
  설치는 항상 **Preview(dry run)** → **백업** → 설치 순서로, 소수의 곡에서 먼저 시험하세요.
- **인게임 재생은 Unity가 필요한 부분**이라 최종 확인은 게임에서 해야 합니다(타임라인이
  참조하는 멤버 모델·모션 바인딩이 맞아야 자연스럽게 재생됩니다).
- **모션 바인딩**: noesis `sifac_anim_to_bundle.py`는 멤버 상대 경로의 CRC32 해시로
  바인딩합니다. 타임라인이 기대하는 멤버/스켈레톤과 모션 번들이 일치해야 합니다.
- **표정 클립 편집기**는 아직 없습니다. 표정은 *자산 등록/교체* 수준으로 지원하며, 표정
  타임라인 트랙을 새로 작성하는 것은 향후 작업입니다.
- 이 도구는 비공식 팬 제작 도구이며, 사용 책임은 사용자에게 있습니다.

---

## 8. SIFAC의 무대·이펙트·카메라를 SIFAS로 넣을 수 있나

각 요소는 **① SIFAC에서 추출 / ② SIFAS 형식으로 변환 / ③ SIFAS에 등록·지정**의
세 단계로 나뉘고, 단계마다 난이도가 다릅니다.

| 요소 | ① 추출 (noesis-llsifac) | ② SIFAS 형식 변환 | ③ 등록·지정 (이 도구) |
|------|------------------------|-------------------|----------------------|
| **카메라** | ✅ `.bscam` → FBX, 또는 **카메라 트랙 JSON**(`sifac_camera.py`) | ⚠️ 타임라인 카메라 키에 주입(샘플 필요, 데이터라 가능) | ✅ 라이브 타임라인으로 함께 설치 |
| **무대(지오메트리)** | ✅ FBX + PNG (`--preset stages`) | ❌ **Unity 에디터로 SIFAS 무대 번들 재빌드 필요** | ✅ `live_stage_master_id` 지정 |
| **무대 이펙트** | ⚠️ raw `.efx`/`.efxa`만(변환기 없음) | ❌ 포맷 분석 + Unity 재빌드 필요 | ✅ `stage_effect_asset_path` 지정 |

**핵심**
- **카메라**가 가장 현실적입니다. 지오메트리 번들이 아니라 **키프레임 데이터**(위치·
  회전·FOV)이고, SIFAS에서 카메라는 **라이브 타임라인 안의 키**라서 — 그리고 그
  타임라인은 이 도구가 이미 설치합니다. `noesis-llsifac/tools/sifac_camera.py`가
  `.bscam`을 SIFAS-space 프레임별 카메라 트랙(JSON)으로 변환합니다. 그 트랙을 실제
  타임라인의 카메라 키에 써 넣는 단계는 입싱크처럼 **실제 타임라인 샘플에서 필드를
  고정**해야 합니다.
- **무대·무대이펙트**는 지오메트리는 뽑히지만(무대는 FBX, 이펙트는 raw만), 작동하는
  SIFAS 번들로 **다시 묶는 건 Unity 에디터 작업**입니다 — elichika가 커스텀 코스튬에
  대해 명시한 한계("assetbundle을 새로 빌드할 방법이 없음", "UABE/UABEA로 기존 에셋
  수정만 가능")와 같은 벽입니다. 단, **완성된 SIFAS 번들이 있으면 이 도구의 등록·지정
  (③)은 그대로 처리**합니다(무대는 `live_stage_master_id`, 이펙트는
  `stage_effect_asset_path` 컬럼).

정리하면: **추출은 셋 다 가능**, **변환은 카메라가 현실적**(데이터)·무대/이펙트는
Unity 필요, **등록·지정은 셋 다 이 도구가 처리**.

> 저장소 코드 + 공개 자료(LL hax, GameBanana 등)를 함께 확인한 **상세 조사 노트**와
> 출처는 [`sifac_porting_research.md`](sifac_porting_research.md)에 있습니다. 다음
> 단계 후보(타임라인 TypeTree 인스펙터 → 카메라 주입기)도 거기 정리돼 있습니다.

---

## English

How to give a SIFAS song that has **audio but no 3D dance** (e.g. μ's Maki's
*Daring!!*) a full dance live, using a dance retargeted from SIFAC by
*noesis-llsifac*.

**The pipeline spans three repos:** noesis-llsifac retargets the SIFAC dance to a
SIFAS `.anim` and bakes it into a motion **AssetBundle**
(`sifac_anim_retarget.py` → `sifac_anim_to_bundle.py`); SIFAS-MODDING's
`live_timeline/` scripts edit a donor **live timeline** asset (lip-sync from SCD,
curve fixes); and **elichika** installs it — the missing easy step, now provided
by **`live_dance_installer.py`** (GUI + CLI) on top of the tested
**`live_install_core.py`** engine.

**What can be added** (verified against `asset_manager/generic_asset.go` and the
shipped installer):

| Element | Where it lives | Method |
|---|---|---|
| Dance (body motion) | separate motion bundle | register as a timeline **dependency** |
| Lip-sync | **inside** the live timeline asset (mouth `TimelineClip`s, `m_DisplayName` A/I/U/E/O/N) | SIFAS-MODDING SCD workflow |
| Facial | `member_facial` / `member_facial_animation` asset packs | register asset + dependency |
| Stage | `stage` table + `m_live_3d_asset.live_stage_master_id` | one DB column |
| Stage effect | `stage_effect` table + `m_live_3d_asset.stage_effect_asset_path` | one DB column |
| Camera | inside the live timeline asset | comes with the timeline |

So lip-sync and camera ride **inside the timeline asset itself**; facial, stage
and stage-effect are **separate asset packs** the tool can register and link.

**The installer** picks the target song by name (no-dance songs flagged),
installs the timeline + motion (+ optional facial), copies/extends timeline
dependencies, sets stage/effect, and — for a song that has *no* 3D asset yet —
**clones a donor `m_live_3d_asset` row** (schema-agnostically, via `PRAGMA` +
`SELECT *`) and re-points the song's difficulties at it. The same XOR encryption
(seed `12345/0/0`) and the same asset / CDN / dependency SQL as the shipped tools
are reused, so output is interchangeable. Always **Preview (dry run)**, keep the
**backup** on, and confirm final playback in-game.
