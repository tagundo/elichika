"""Edit only the game's live-quality table, retaining other game/user data.

The client selects set_id through m_live_3d_asset.quality_setitng_set_id.
Quality modes are the original LiveQualityMode enum (10/20/30/40/50).
No rendering settings from the Elichika model preview are changed here.
"""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime, timezone

TABLE = "m_live_quality_setting"
KEYS = ("set_id", "quality_mode")
MODES = {10: ("Highest 3D", "최고 3D", "最高3D"),
         20: ("High 3D", "높음 3D", "高3D"),
         30: ("Medium 3D", "보통 3D", "中3D"),
         40: ("Low 3D", "낮음 3D", "低3D"),
         50: ("Low 2D", "낮음 2D", "低2D")}

# The names correspond to LiveQualitySettingVO and LiveQualityOperator in the
# original GL client. Descriptions deliberately do not promise effects that a
# particular song/stage does not contain.
FIELDS = [
    ("rendering_resolution", "general", ("3D rendering height (px)", "3D 렌더링 높이 (px)", "3D描画の高さ（px）"),
     ("Internal 3D height; width follows the screen aspect ratio. The ordinary client limits positive values to the screen height. 0 uses its 1080px fallback; this does not force 4K on a smaller screen.", "내부 3D 화면의 높이입니다. 가로는 화면 비율에 맞춥니다. 일반 재생에서는 기기 화면 높이까지만 사용하며, 0은 클라이언트의 1080px 기본값입니다. 작은 화면에서 4K를 강제하는 설정은 아닙니다.", "内部3D画面の高さです。幅は画面比率に従います。通常再生では画面の高さが上限で、0は1080pxの既定値です。小さな画面で4Kを強制する設定ではありません。")),
    ("frame_rate_60fps", "general", ("60 FPS", "60 FPS", "60 FPS"),
     ("Request the client's 60 FPS quality mode. Actual frame rate also depends on device performance and client frame-rate settings.", "클라이언트의 60 FPS 화질 모드를 요청합니다. 실제 프레임은 기기 성능과 클라이언트 프레임 설정의 영향도 받습니다.", "クライアントの60 FPS画質モードを要求します。実際のフレーム数は端末性能やクライアント設定にも依存します。")),
    ("base_light", "stage", ("Base lighting", "기본 조명", "基本照明"),
     ("Enable the stage's base-light effect track.", "무대의 기본 조명 효과 트랙을 사용합니다.", "ステージの基本照明エフェクトトラックを使用します。")),
    ("stage_ambient", "stage", ("Stage ambient light", "무대 환경광", "ステージ環境光"),
     ("Enable ambient-light effects on the stage.", "무대에 적용되는 환경광 효과를 사용합니다.", "ステージに適用される環境光エフェクトを使用します。")),
    ("stage_animation", "stage", ("Stage animation", "무대 애니메이션", "ステージアニメーション"),
     ("Enable animated stage elements in the live timeline.", "라이브 타임라인의 움직이는 무대 요소를 사용합니다.", "ライブのタイムラインにある動くステージ要素を使用します。")),
    ("stage_coloring", "stage", ("Stage color changes", "무대 색상 변화", "ステージの色変化"),
     ("Enable stage-color changes controlled by the timeline.", "타임라인에서 제어하는 무대 색상 변화를 사용합니다.", "タイムラインが制御するステージの色変化を使用します。")),
    ("stage_control", "stage", ("Stage controls", "무대 제어 효과", "ステージ制御"),
     ("Enable stage-control tracks; the available operations depend on the song's stage assets.", "무대 제어 트랙을 사용합니다. 실제 제어 내용은 곡의 무대 에셋에 따라 다릅니다.", "ステージ制御トラックを使用します。制御内容は曲のステージアセットによって異なります。")),
    ("stage_overlay_effect", "stage", ("Stage overlay effects", "무대 오버레이 효과", "ステージオーバーレイ"),
     ("Enable stage overlay-effect tracks layered over the scene.", "장면에 겹쳐지는 무대 오버레이 효과 트랙을 사용합니다.", "シーンに重なるステージのオーバーレイエフェクトを使用します。")),
    ("stage_flash_light", "stage", ("Stage flashing lights", "무대 점멸 조명", "ステージの点滅照明"),
     ("Enable the stage's flash-light effects.", "무대의 번쩍이거나 점멸하는 조명 효과를 사용합니다.", "ステージのフラッシュ・点滅照明エフェクトを使用します。")),
    ("stage_display", "stage", ("Stage screens", "무대 전광판", "ステージのスクリーン"),
     ("Enable stage display/screen tracks when the stage supplies them.", "무대에 전광판·스크린 트랙이 있을 때 사용합니다.", "ステージに表示装置・スクリーンのトラックがある場合に使用します。")),
    ("posteffect", "stage", ("Post-processing", "후처리 효과", "ポストエフェクト"),
     ("Enable the live camera's post-processing path and associated stage post-effect tracks.", "라이브 카메라의 후처리 경로와 무대 후처리 효과 트랙을 사용합니다.", "ライブカメラの後処理経路とステージのポストエフェクトを使用します。")),
    ("stage_emissive", "stage", ("Stage emissive effects", "무대 발광 효과", "ステージの発光"),
     ("Enable emissive/glowing stage effect tracks.", "무대 소재의 발광 효과 트랙을 사용합니다.", "ステージ素材の発光エフェクトトラックを使用します。")),
    ("stage_audience", "stage", ("Audience", "관객", "観客"),
     ("Enable audience-related stage tracks and objects supplied by the stage.", "무대에 포함된 관객 관련 트랙과 오브젝트를 사용합니다.", "ステージに含まれる観客関連トラックとオブジェクトを使用します。")),
    ("stage_cubemap", "stage", ("Stage cubemap reflections", "무대 큐브맵 반사", "ステージのキューブマップ反射"),
     ("Enable the stage's cubemap/reflection effect tracks.", "무대의 큐브맵·반사 효과 트랙을 사용합니다.", "ステージのキューブマップ・反射エフェクトを使用します。")),
    ("member_ambient", "member", ("Character ambient light", "캐릭터 환경광", "キャラクター環境光"),
     ("Enable ambient-light effects on the characters.", "캐릭터에 적용되는 환경광 효과를 사용합니다.", "キャラクターに適用される環境光エフェクトを使用します。")),
    ("member_rim_light", "member", ("Character rim light", "캐릭터 림라이트", "キャラクターのリムライト"),
     ("Enable character edge/rim-light effect tracks. This is separate from Elichika's model-preview lighting.", "캐릭터 가장자리를 비추는 림라이트 트랙을 사용합니다. Elichika 3D 미리보기의 림라이트 설정과는 별개입니다.", "キャラクターの縁を照らすリムライトトラックを使用します。Elichikaの3Dプレビュー照明とは別の設定です。")),
    ("member_spot_light_shaft", "member", ("Character spotlight beams", "캐릭터 스포트라이트 광선", "キャラクターのスポット光線"),
     ("Enable the shaft/beam component of character spotlights.", "캐릭터 스포트라이트의 광선 기둥 효과를 사용합니다.", "キャラクター用スポットライトの光線・光柱部分を使用します。")),
    ("member_spot_light_area", "member", ("Character spotlight areas", "캐릭터 스포트라이트 영역", "キャラクターのスポット範囲"),
     ("Enable the illuminated-area component of character spotlights.", "캐릭터 스포트라이트의 조명 영역 효과를 사용합니다.", "キャラクター用スポットライトの照射範囲部分を使用します。")),
    ("member_swing_bone_live", "member", ("Swing bones during gameplay", "리듬 게임 스윙본", "リズムゲーム中のスイングボーン"),
     ("Enable character swing-bone physics while playing the rhythm game.", "리듬 게임을 플레이할 때 캐릭터의 스윙본 물리를 사용합니다.", "リズムゲームのプレイ中にキャラクターのスイングボーン物理を使用します。")),
    ("member_swing_bone_mv", "member", ("Swing bones during MV", "MV 스윙본", "MVのスイングボーン"),
     ("Enable character swing-bone physics in MV viewing; independent of the gameplay switch.", "MV 감상에서 캐릭터의 스윙본 물리를 사용합니다. 리듬 게임 설정과 별개입니다.", "MV鑑賞でキャラクターのスイングボーン物理を使用します。プレイ中の設定とは独立しています。")),
    ("prop_ambient", "prop", ("Prop ambient light", "소품 환경광", "小道具の環境光"),
     ("Enable ambient-light effects on live props.", "라이브 소품에 적용되는 환경광 효과를 사용합니다.", "ライブの小道具に適用される環境光エフェクトを使用します。")),
    ("prop_rim_light", "prop", ("Prop rim light", "소품 림라이트", "小道具のリムライト"),
     ("Enable edge/rim-light effects on live props.", "라이브 소품 가장자리를 비추는 림라이트 효과를 사용합니다.", "ライブの小道具の縁を照らすリムライトを使用します。")),
    ("split_screen", "screen", ("Split-screen presentation", "분할 화면 연출", "画面分割演出"),
     ("Allow the song's split-screen/multiple-view presentation. Songs without this track are unchanged.", "곡의 분할 화면·여러 시점 연출을 허용합니다. 해당 트랙이 없는 곡에는 변화가 없습니다.", "曲の画面分割・複数視点演出を許可します。対応トラックのない曲には影響しません。")),
]
EDITABLE = {row[0] for row in FIELDS}


class QualityError(ValueError):
    pass


class QualityConflict(QualityError):
    pass


def _language(language):
    return {"ko": 1, "ja": 2}.get(str(language or "en").split("-")[0], 0)


def _json_value(value):
    return {"base64": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value


def _db_path(root, region):
    if region not in ("gl", "jp"):
        raise QualityError("Choose Global (GL) or Japan (JP).")
    try:
        root = Path(root).resolve(strict=True)
        path = root / "assets" / "db" / region / "masterdata.db"
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise QualityError("Prepare game data before editing graphics quality.") from None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise QualityError("The game database is outside the selected library.")
    return resolved


def _connect(path, writable=False):
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def _read_table(db):
    schema = [tuple(row) for row in db.execute("PRAGMA table_info(" + TABLE + ")")]
    columns = [row[1] for row in schema]
    if not set(KEYS).union(EDITABLE).issubset(columns):
        raise QualityError("This game database does not contain the supported live-quality table.")
    if [(row[1], row[5]) for row in schema if row[5]] != [("set_id", 1), ("quality_mode", 2)]:
        raise QualityError("The live-quality table has an unsupported primary key.")
    rows = [{key: _json_value(row[key]) for key in columns}
            for row in db.execute("SELECT * FROM " + TABLE + " ORDER BY set_id, quality_mode")]
    if not rows or len(rows) > 1000:
        raise QualityError("The live-quality table has no supported profiles.")
    data = {"schema": schema, "columns": columns, "rows": rows}
    revision = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return data, revision


def _state_directory(root):
    root = Path(root).resolve(strict=True)
    path = root / ".game-quality"
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.resolve(strict=True).is_relative_to(root) or not path.is_dir():
        raise QualityError("The quality recovery folder is outside the selected library.")
    return path


def _baseline(root, region, optional=True):
    path = Path(root).resolve(strict=True) / ".game-quality" / (region + ".initial.json")
    if not path.exists() and optional:
        return None
    try:
        if not path.resolve(strict=True).is_relative_to(Path(root).resolve(strict=True)):
            raise QualityError("The quality recovery folder is outside the selected library.")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("format") != 1 or value.get("region") != region or not isinstance(value.get("rows"), list):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise QualityError("The original quality settings could not be read from the recovery record.") from None


def inspect(root, region="gl", language="en"):
    path = _db_path(root, region)
    with closing(_connect(path)) as db:
        data, revision = _read_table(db)
    index = _language(language)
    fields = [{"name": name, "group": group, "label": label[index], "help": help_text[index],
               "type": "integer" if name == "rendering_resolution" else "boolean",
               **({"min": 0, "max": 8192} if name == "rendering_resolution" else {})}
              for name, group, label, help_text in FIELDS]
    return {"region": region, "revision": revision, "profiles": data["rows"], "fields": fields,
            "quality_modes": {str(key): value[index] for key, value in MODES.items()},
            "unknown_columns": [key for key in data["columns"] if key not in EDITABLE and key not in KEYS],
            "can_reset": _baseline(root, region) is not None}


def plan_change(root, params):
    if not isinstance(params, dict):
        raise QualityError("Invalid quality settings request.")
    region = params.get("region", "gl")
    path = _db_path(root, region)
    with closing(_connect(path)) as db:
        data, revision = _read_table(db)
    expected = params.get("revision")
    if not isinstance(expected, str) or expected != revision:
        raise QualityConflict("Quality settings changed. Reload before saving.")
    set_id, mode = params.get("set_id"), params.get("quality_mode")
    if type(set_id) is not int or type(mode) is not int:
        raise QualityError("Choose a quality profile first.")
    source = next((row for row in data["rows"] if row["set_id"] == set_id and row["quality_mode"] == mode), None)
    if source is None:
        raise QualityError("This quality profile no longer exists.")
    scope = params.get("scope", "profile")
    if scope not in ("profile", "quality", "all"):
        raise QualityError("Choose a supported quality-edit scope.")
    targets = [row for row in data["rows"] if scope == "all" or
               scope == "quality" and row["quality_mode"] == mode or
               scope == "profile" and (row["set_id"], row["quality_mode"]) == (set_id, mode)]
    action = params.get("action", "apply")
    if action not in ("apply", "reset"):
        raise QualityError("Choose save or restore original settings.")
    changes = params.get("changes", {})
    if not isinstance(changes, dict) or not set(changes).issubset(EDITABLE):
        raise QualityError("Only supported quality settings can be edited.")
    for key, value in changes.items():
        if key == "rendering_resolution":
            if type(value) is not int or not 0 <= value <= 8192:
                raise QualityError("Rendering height must be a whole number between 0 and 8192.")
        elif type(value) not in (bool, int) or value not in (0, 1):
            raise QualityError("Quality switches must be on or off.")
    baseline = _baseline(root, region) if action == "reset" else None
    if action == "reset" and baseline is None:
        raise QualityError("There are no earlier quality edits to restore.")
    originals = {(row["set_id"], row["quality_mode"]): row for row in baseline["rows"]} if baseline else {}
    updates = []
    for row in targets:
        values = changes
        if action == "reset":
            original = originals.get((row["set_id"], row["quality_mode"]))
            values = {key: original[key] for key in EDITABLE if original and key in original}
        patch = {key: int(value) for key, value in values.items() if row[key] != int(value)}
        if patch:
            updates.append({"set_id": row["set_id"], "quality_mode": row["quality_mode"], "changes": patch})
    return {"root": str(Path(root).resolve(strict=True)), "path": str(path), "region": region,
            "revision": revision, "updates": updates, "action": action, "scope": scope,
            "profile_count": len(targets), "changed_count": sum(len(row["changes"]) for row in updates)}


def _write_record(path, record):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            raise QualityError("A quality recovery record already exists.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def commit_change(plan):
    """Called under the existing complete-job DB/lifecycle guard by adminui."""
    if not plan["updates"]:
        return {"changed": False, "changed_count": 0, "profile_count": plan["profile_count"],
                "region": plan["region"], "revision": plan["revision"], "backup": None}
    root = Path(plan["root"])
    path = _db_path(root, plan["region"])
    if str(path) != plan["path"]:
        raise QualityConflict("Quality settings changed. Reload before saving.")
    db = _connect(path, writable=True)
    try:
        db.execute("BEGIN IMMEDIATE")
        data, revision = _read_table(db)
        if revision != plan["revision"]:
            raise QualityConflict("Quality settings changed. Reload before saving.")
        folder = _state_directory(root)
        initial = folder / (plan["region"] + ".initial.json")
        if not initial.exists():
            _write_record(initial, dict(format=1, region=plan["region"], **data))
        else:
            _baseline(root, plan["region"], optional=False)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = folder / (plan["region"] + "." + stamp + "." + uuid.uuid4().hex[:8] + ".json")
        _write_record(backup, dict(format=1, region=plan["region"], revision=revision, **data))
        for row in plan["updates"]:
            # All identifiers have been validated against EDITABLE; values and
            # the composite key are always parameters, never SQL source text.
            names = sorted(row["changes"])
            db.execute("UPDATE " + TABLE + " SET " + ", ".join('"' + name + '"=?' for name in names) +
                       " WHERE set_id=? AND quality_mode=?",
                       [row["changes"][name] for name in names] + [row["set_id"], row["quality_mode"]])
        db.commit()
        _, after = _read_table(db)
        return {"changed": True, "changed_count": plan["changed_count"],
                "profile_count": len(plan["updates"]), "region": plan["region"],
                "revision": after, "backup": str(backup.relative_to(root))}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
