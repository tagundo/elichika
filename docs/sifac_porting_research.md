# 조사 노트 — SIFAC의 카메라·무대·이펙트를 SIFAS로

`docs/dance_live_timeline.md` §8의 요약을 뒷받침하는 **상세 조사 결과**입니다.
저장소(noesis-llsifac · SIFAS-MODDING-HELPING-TOOLS · elichika) 코드 분석과 공개
자료(LL hax 문서, GameBanana, 리버싱 저장소)를 함께 확인했습니다.

> 결론 한 줄: **카메라**는 데이터(키프레임)라 이식 경로가 분명합니다. **무대·무대
> 이펙트**는 추출은 되지만 SIFAS 번들로 다시 묶는 건 Unity 에디터가 필요하고, 특히
> `.efx`는 파서조차 없어 가장 멀리 있습니다.

---

## 1. 카메라 — 가장 현실적 (데이터)

**확인된 사실**
- SIFAS의 카메라는 독립 에셋이 아니라 **`LiveTimelineData`(라이브 타임라인) 안의
  키프레임**입니다(noesis `sifac_camera.py` 주석, elichika 문서, 그리고 커뮤니티
  근거 ↓ 모두 일치).
- SIFAC 카메라(`.bscam`/BSCM) 추출·변환은 **이미 구현**: `sifac_camera.py`가
  위치·회전·FOV를 프레임별로 샘플링해 SIFAS Y-up 공간의 JSON으로 내보냅니다(테스트
  7/7).
- **커뮤니티 선례**: GameBanana에 *"Camera LiveTimeline Solo Front/Back"* SIFAS
  모드가 존재 → 카메라 타임라인이 실제로 모딩 대상이며, 사용자가 말한 "카메라 라이브
  타임라인"이 별도 개념으로 통용됨을 확인.

**남은 단계(주입)와 방법**
- 우리 카메라 트랙(JSON)을 실제 SIFAS 타임라인의 카메라 키에 써 넣으면 됩니다. 방식은
  이미 검증된 **립싱크 워크플로우와 동일** — UABEA/UnityPy로 타임라인 MonoBehaviour를
  열고, 카메라 키의 시간에 맞춰 값을 덮어쓰기.
- 막는 것은 단 하나: **SIFAS `LiveTimelineData`의 카메라 키 필드 이름**(예:
  `LiveTimelineKeyCameraData`류의 pos/lookAt/fov 필드)이 공개 자료로 깔끔히 안 나옵니다.
  이는 KLab가 SIF부터 써 온 LiveTimeline 프레임워크지만 SIFAS의 정확한 레이아웃은
  **실제 타임라인 에셋에서 TypeTree로 덤프**해야 확정됩니다.

**그래서 다음 enabler(권장)**: `sifac_anim_to_bundle.py --inspect`처럼, **실제 SIFAS
타임라인 번들의 MonoBehaviour 구조(카메라/표정/이펙트 키 목록)를 덤프하는 도구**.
사용자가 자기 타임라인에 한 번 돌리면 정확한 필드가 드러나고, 그걸로 카메라 주입기를
완성할 수 있습니다. (샘플 하나면 "미지수"가 "구현"으로 바뀜.)

---

## 2. 무대(stage) — 추출 O, 재패키징 ✗(Unity 필요)

- **추출**: SIFAC 무대 지오메트리는 `sifac_convert.py --preset stages`로 **FBX+PNG**.
- **변환**: 작동하는 SIFAS 무대가 되려면 SIFAS 프리팹/셰이더/컴포넌트로 **Unity
  에디터에서 번들을 새로 빌드**해야 합니다. elichika가 커스텀 코스튬에 대해 명시한 벽과
  동일("assetbundle을 새로 빌드할 방법 없음", "UABE/UABEA로 기존 에셋 수정만").
- **마스터 스키마 미상**: `live_stage_master_id`가 가리키는 **`m_live_stage` 마스터
  테이블 정의가 elichika Go 코드에 없습니다.** 그래서 새 무대를 "정의"하긴 어렵고,
  도구는 **이미 게임이 쓰는 stage id를 재사용**(`list_existing_3d_values`)합니다.
- **등록·지정**: 완성된 SIFAS 무대 번들만 있으면 이 도구가 `live_stage_master_id`
  지정/`stage` 테이블 등록은 처리.

---

## 3. 무대 이펙트(.efx) — 가장 멀다

- **추출**: `.efx`/`.efxa`는 `live` 프리셋으로 아카이브에서 **추출만** 됩니다
  (`sifac_native.py`의 타입 매핑, `sifac_extract.py` live 프리셋).
- **파서 없음**: noesis-llsifac에 **`.efx` 구조를 해석하는 파서가 전혀 없습니다.**
  매직/필드 레이아웃 미상, 추출 후에는 raw 바이너리 블롭. → SIFAS로 변환하려면
  **포맷 역분석 + Unity 이펙트 번들 재빌드** 둘 다 필요.
- **등록·지정**: 완성된 SIFAS `stage_effect` 번들이 있으면
  `m_live_3d_asset.stage_effect_asset_path` 지정은 이 도구가 처리.

---

## 4. (참고) 입싱크·표정

- **립싱크**: 완전 검증됨. SIFAS-MODDING `live_timeline/` 5단계로 SCD→입모양(A/I/U/E/O/N),
  타임라인 필드(`m_Start`/`m_Duration`/`m_DisplayName`)가 이미 고정.
- **표정**: 별도 `member_facial`/`member_facial_animation` 번들 + 타임라인 표정 트랙.
  SCD가 `*facial*.scd`도 같은 포맷으로 다루므로 데이터는 있으나, 표정 **트랙 편집기는
  아직 없음**(카메라 주입기와 같은 TypeTree 작업 필요).

---

## 난이도 정리

| 요소 | 추출 | SIFAS 변환 | 등록·지정 | 막는 것 |
|------|:---:|:---:|:---:|------|
| 카메라 | ✅ | ⚠️ 데이터→타임라인 키 주입 | ✅ | 타임라인 카메라 키 필드명(샘플로 확정) |
| 무대 | ✅ FBX | ❌ Unity 재빌드 | ✅ | `m_live_stage` 스키마 + 번들 빌드 |
| 무대이펙트 | ⚠️ raw만 | ❌ RE+Unity | ✅ | `.efx` 파서 없음 |
| 표정 | ✅ SCD | ⚠️ 트랙 편집기 필요 | ✅ | 타임라인 표정 키 필드명 |
| 립싱크 | ✅ SCD | ✅ 완료 | ✅ | — |

**우선순위 제안**: ① 타임라인 TypeTree 인스펙터(샘플에서 카메라/표정/이펙트 키 구조
덤프) → ② 카메라 주입기(가장 가치 높음) → ③ 표정 트랙 편집기. 무대/이펙트의 변환은
Unity 에디터 영역이라 별도 가이드로 다루는 게 맞습니다.

---

## 출처

- LL Hax Docs — SIFAS: <https://carette.codeberg.page/ll-hax-docs/sifas/> ·
  저장소 <https://codeberg.org/carette/ll-hax-docs>
- GameBanana — *Camera LiveTimeline Solo Front/Back (beta)* (SIFAS):
  <https://gamebanana.com/mods/574578>
- Francesco149 / reversing-sifas (주로 네트워크 프로토콜):
  <https://github.com/Francesco149/reversing-sifas>
- nosyrbllewe / LLASDecryptor (SIFAS DB 복호):
  <https://github.com/nosyrbllewe/LLASDecryptor>
- UABEA (Unity 에셋 번들 에디터): <https://github.com/nesrak1/UABEA>
- 저장소 내부 근거: `noesis-llsifac/tools/sifac_camera.py`,
  `noesis-llsifac/tools/sifac_native.py`(.efx 매핑),
  `SIFAS-MODDING-HELPING-TOOLS/live_timeline/`(타임라인 편집),
  `elichika/asset_manager/generic_asset.go`(자산 테이블),
  `elichika/live_install_core.py`(무대/이펙트 지정).
