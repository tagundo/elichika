"""Live (악곡) addon installer for elichika (refactored).

기능은 원본 live_addon_installer.py와 100% 동일하게 유지하면서
중복 코드를 데이터 테이블과 헬퍼 함수로 정리한 버전입니다.

구조:
  1. 데이터 테이블  - DB 경로, 그룹/속성 이름, 드롭 아이템 규칙, SQL 모음
  2. 헬퍼 함수      - 백업, 암호화, 고유 ID 생성, 비트맵 편집, DB 삽입
  3. 메인 흐름      - zip 선택 -> 설정 exec -> 암호화 -> DB 등록 -> 마무리

주의: 애드온 zip 안의 .txt 설정 파일과 dictionary_live_en.txt 는 원본과
동일하게 모듈 전역 네임스페이스에서 exec 되므로, 설정 변수(music_file 등)와
mission_type_name_dictionary 는 모듈 전역 변수로 유지됩니다.
"""

import sqlite3
import os
import zipfile
import io
import json
import platform
import random
import sys
import shutil
import hashlib
from datetime import datetime

# ============================================================
# 1. 데이터 테이블
# ============================================================

# 백업 대상 파일 목록
filelist = [
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
    "assets/db/gl/dictionary_en_k.db",
    "assets/db/gl/dictionary_ko_k.db",
    "assets/db/gl/dictionary_zh_k.db",
    "assets/db/gl/masterdata.db",
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
    "assets/db/jp/dictionary_ja_k.db",
    "assets/db/jp/masterdata.db",
    "serverdata.db",
    "userdata.db",
]

# 에셋 DB 등록 순서 (원본 처리 순서 그대로)
ASSET_DB_PATHS = [
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
]

# 다운로드 패키지 등록 순서 (원본과 동일)
PACKAGE_DB_PATHS = list(ASSET_DB_PATHS)

GROUP_NAMES = {1: 'Myuzu', 2: 'Aqours', 3: 'Nijigasaki', 4: 'Liella'}

ATTRIBUTE_NAMES = {1: 'Smile', 2: 'Pure', 3: 'Cool', 4: 'Active',
                   5: 'Natural', 6: 'Elegant', 9: 'Untyped / Unknown'}

# m_live 의 live_member_mapping_id (Liella/Union 치비가 없어 뮤즈 재사용)
MEMBER_MAPPING = {1: 10001, 2: 11001, 3: 12130, 4: 10001, 100: 10001}

# 드롭 아이템 ID 규칙: 10{P}{attr}00{G}{D}0
#   P = 아이템별 접두 숫자 (item1..item5)
#   G = 그룹 코드, D = 난이도 (easy 1 / normal 2 / hard 3)
DROP_ITEM_PREFIX = ('4', '0', '1', '2', '3')   # item1..item5
DROP_GROUP_CODE = {1: '1', 2: '2', 3: '6', 4: '4'}
DIFF_KEYS = ('easy', 'normal', 'hard')

# m_live_difficulty INSERT (난이도별 상수가 박힌 원본 SQL 그대로)
LIVE_DIFFICULTY_SQL = [
    "INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 10, '1', ?, ?, ?, ?, ?, '10', '8', '1', ?, '2', '1500', ?, ?, '2', ?, ?, '50000', '9000', '12', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
    "INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 20, '1', ?, ?, ?, ?, ?, '12', '13', '2', ?, '2', '1300', ?, ?, '2', ?, ?, '60000', '9000', '16', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
    "INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 30, '1', ?, ?, ?, ?, ?, '15', '21', '3', ?, '2', '1000', ?, ?, '3', ?, ?, '70000', '9000', '24', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
]

# m_live_difficulty_const INSERT (sp 게이지 길이/감소 포인트만 난이도별 상이)
LIVE_DIFFICULTY_CONST_SQL = [
    "INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '3600', '10000', '50', '10000', ?, '100000', '250000', '50000', '30000');",
    "INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '4800', '10000', '75', '10000', ?, '100000', '250000', '50000', '30000');",
    "INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '6000', '10000', '100', '10000', ?, '100000', '250000', '50000', '30000');",
]

M_LIVE_SQL = "INSERT INTO main.m_live (live_id, is_2d_live, music_id, bgm_path, chorus_bgm_path, live_member_mapping_id, name, pronunciation, member_group, member_unit, original_deck_name, copyright, source, jacket_asset_path, background_asset_path, display_order) VALUES (?, '1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SI', ?);"

M_EMBLEM_SQL = "INSERT INTO main.m_emblem (id, name, description, emblem_type, grade, emblem_asset_path, emblem_sub_asset_path, emblem_clear_condition_type, emblem_clear_condition_param, is_emblem_secret_condition, is_event_emblem, released_at, display_order) VALUES (?, ?, ?, '2', ?, ?, ?, '5', '100', '0', '0', '0', ?);"

# m_mission INSERT (트리거/달성 횟수만 미션별 상이)
MISSION_SQL = [
    "INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '1', '0', ?, '1529593200', ?, '20', ?, ?, ?, '14', '10', ?, ?, ?, '0');",
    "INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '50', ?, ?, ?, '0');",
    "INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '100', ?, ?, ?, '0');",
]

MISSION_REWARD_SQL = [
    ("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '1');", None),
    ("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '3');", None),
    ("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '15', ?, '1');", 'emblem'),
]

# 사전(_k) DB: (경로, 언어 키)
DICTIONARY_K_DBS = [
    ("assets/db/gl/dictionary_en_k.db", "en"),
    ("assets/db/gl/dictionary_ko_k.db", "ko"),
    ("assets/db/gl/dictionary_zh_k.db", "zh"),
    ("assets/db/jp/dictionary_ja_k.db", "ja"),
]

# 사전(_m) DB: (경로, 언어 키)
DICTIONARY_M_DBS = [
    ("assets/db/gl/dictionary_en_m.db", "en"),
    ("assets/db/gl/dictionary_ko_m.db", "ko"),
    ("assets/db/gl/dictionary_zh_m.db", "zh"),
    ("assets/db/jp/dictionary_ja_m.db", "ja"),
]

# 엠블럼 설명(100회 클리어) 문구 - 원본 그대로 (ja 가 zh 문구를 쓰는 것 포함)
EMBLEM_TITLE_TEMPLATES = {
    "en": 'Clear &quot;{name}&quot; 100 times.',
    "ko": '{name} 100회 클리어',
    "zh": '通過100次「{name}」',
    "ja": '通過100次「{name}」',
}

# 미션 설명 문구 (10/50/100회) - 원본 그대로
MISSION_TITLE_TEMPLATES = {
    "en": ['Clear &quot;{name}&quot;: x10', 'Clear &quot;{name}&quot;: x50', 'Clear &quot;{name}&quot;: x100'],
    "ko": ['{name} 10회 클리어', '{name} 50회 클리어', '{name} 100회 클리어'],
    "zh": ['完成10次「{name}」', '完成50次「{name}」', '完成100次「{name}」'],
    "ja": ['「{name}」を10回クリアする', '「{name}」を50回クリアする', '「{name}」を100回クリアする'],
}

# ============================================================
# 2. 헬퍼 함수
# ============================================================

def backup_operate(filelist):
    # Create a folder with the current date and time as the name
    backup_folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    os.makedirs(backup_folder)

    # Copy each file from the filelist to the backup folder
    for file_path in filelist:
        relative_path = os.path.relpath(file_path, start=".")
        dest_path = os.path.join(backup_folder, relative_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy(file_path, dest_path)

    print("Backup completed successfully.")


def is_termux():
    return 'com.termux' in os.getenv('PREFIX', '')


def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')


def manipulate_file(data, keys_0, keys_1, keys_2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF


def generate_unique_id(cursor, count_sql, upper, lower=0):
    """count_sql 의 COUNT 가 0이 될 때까지 [lower, upper] 난수를 뽑는다.
    (원본의 generate_unique_* 함수들을 하나로 통합)"""
    while True:
        new_id = random.randint(lower, upper)
        cursor.execute(count_sql, (new_id,))
        if cursor.fetchone()[0] == 0:
            return new_id


def generate_unique_hash(cursor, count_sql):
    """texture/m_movie 에 없는 32비트 16진 해시를 뽑는다."""
    while True:
        new_hash = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute(count_sql, (new_hash,))
        if cursor.fetchone()[0] == 0:
            return new_hash


def read_acb_sheet_name(path):
    """오프셋 1438부터 0x00 직전까지의 텍스트(시트 이름)를 읽는다.
    (원본 read_file_and_select_text / read_file_and_select_text1 통합)"""
    with open(path, 'rb') as file:
        file.seek(1438)
        selected_text_deretote = b''
        while True:
            byte = file.read(1)
            if byte == b'\x00':
                break
            selected_text_deretote += byte
        return selected_text_deretote.decode('utf-8')


def encrypt_asset(src, dst, label):
    """jacket/emblem 암호화: key (12345, 0, 0) 으로 XOR 후 저장."""
    with open(src, "rb") as file:
        data = bytearray(file.read())
        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print(f"encrypting {label}")
        manipulate_file(data, key_0, key_1, key_2)
        with open(dst, "wb") as file:
            file.write(data)


def compute_drop_items(member_group, attribute):
    """난이도별 드롭 아이템 ID 5종을 계산한다.
    반환: {'easy': [item1..item5], 'normal': [...], 'hard': [...]}
    원본의 360줄짜리 if/elif 테이블과 동일한 값을 만든다."""
    drops = {}
    for d_idx, d_key in enumerate(DIFF_KEYS, start=1):
        if member_group == 100 or attribute not in (1, 2, 3, 4, 5, 6):
            drops[d_key] = [0, 0, 0, 0, 0]
        else:
            g = DROP_GROUP_CODE[member_group]
            drops[d_key] = [int(f"10{p}{attribute}00{g}{d_idx}0")
                            for p in DROP_ITEM_PREFIX]
    return drops


def lookup_note_gimmick_info(cursor, description):
    """m_live_difficulty_note_gimmick 에서 기존 기믹 정보를 조회한다."""
    cursor.execute("SELECT skill_master_id FROM m_live_difficulty_note_gimmick WHERE description = ?", (description,))
    skill_master_id = cursor.fetchone()[0]
    cursor.execute("SELECT note_gimmick_icon_type FROM m_live_difficulty_note_gimmick WHERE description = ?", (description,))
    icon_type = cursor.fetchone()[0]
    cursor.execute("SELECT note_gimmick_type FROM m_live_difficulty_note_gimmick WHERE description = ?", (description,))
    gimmick_type = cursor.fetchone()[0]
    cursor.execute("SELECT name FROM m_live_difficulty_note_gimmick WHERE description = ?", (description,))
    name = cursor.fetchone()[0]
    return skill_master_id, icon_type, gimmick_type, name


def insert_note_gimmick_rows(cursor, diff_id, note_ids, gimmick_type, icon_type,
                             skill_master_id, name, description):
    for note_id in note_ids:
        cursor.execute("INSERT INTO main.m_live_difficulty_note_gimmick (live_difficulty_id, note_id, note_gimmick_type, note_gimmick_icon_type, skill_master_id, name, description) VALUES (?, ?, ?, ?, ?, ?, ?);",
                       (diff_id, note_id, gimmick_type, icon_type, skill_master_id, name, description))


def insert_appeal_chance_row(cursor, diff_id, wave_id, entry):
    """m_live_note_wave_gimmick_group 등록. (GL/JP masterdata 공용)"""
    skill_id = entry['skill_id']
    state = entry['time']
    name = f"k.live_detail_wave_mission_{diff_id}_{wave_id}"
    cursor.execute("SELECT description FROM m_live_note_wave_gimmick_group WHERE skill_id = ? AND state = ?", (skill_id, state,))
    description = cursor.fetchone()[0]
    cursor.execute("INSERT INTO main.m_live_note_wave_gimmick_group (live_difficulty_id, wave_id, state, skill_id, name, description) VALUES (?, ?, ?, ?, ?, ?);",
                   (diff_id, wave_id, state, skill_id, name, description))


def insert_stage_gimmick_row(cursor, diff_id, entry):
    """m_live_difficulty_gimmick 등록. 조회한 (description, name) 을 반환."""
    skill_id = entry['skill_id']
    gimmick_id = entry['id']
    cursor.execute("SELECT description FROM m_live_difficulty_gimmick WHERE skill_master_id = ?", (skill_id,))
    description = cursor.fetchone()[0]
    cursor.execute("SELECT name FROM m_live_difficulty_gimmick WHERE skill_master_id = ?", (skill_id,))
    name = cursor.fetchone()[0]
    cursor.execute("INSERT INTO main.m_live_difficulty_gimmick (id, live_difficulty_master_id, trigger_type, condition_master_id1, condition_master_id2, skill_master_id, name, description) VALUES (?, ?, '2', '1', '1', ?, ?, ?);",
                   (gimmick_id, diff_id, skill_id, name, description))
    return description, name


def process_beatmap(cursor, in_path, out_path, diff_id,
                    note_gimmick, appeal_chance, stage_gimmick):
    """비트맵 JSON 을 편집해 out_path 에 저장하고 노트 수를 반환한다.
    (GL masterdata 의 easy/normal/hard 3중 복붙 블록 통합)
    DB 기믹 등록은 원본처럼 같은 cursor(GL masterdata)로 수행한다."""
    with open(in_path, 'r', encoding='utf-8') as difficult_file:
        data = json.load(difficult_file)

        data["live_difficulty_id"] = diff_id
        id_count = 0
        for note in data.get('live_notes', []):
            if 'id' in note:
                id_count += 1

        # ---- 노트 기믹 ----
        if note_gimmick is not None:
            for idx_note, entry_note in enumerate(note_gimmick):
                ids_note = entry_note['note_id']
                skill_desc_id = entry_note['skill_description_id']
                uniq_note_id = idx_note + 1001

                description = f"k.live_detail_notes_desc_{skill_desc_id}"
                skill_master_id, icon_type, gimmick_type, name = \
                    lookup_note_gimmick_info(cursor, description)

                for note_gmk in data['live_notes']:
                    if note_gmk['id'] in ids_note:
                        note_gmk['gimmick_id'] = skill_desc_id

                insert_note_gimmick_rows(cursor, diff_id, ids_note, gimmick_type,
                                         icon_type, skill_master_id, name, description)

                data['note_gimmicks'].append({
                    "uniq_id": uniq_note_id,
                    "id": skill_desc_id,
                    "note_gimmick_type": gimmick_type,
                    "arg_1": 0,
                    "arg_2": 0,
                    "effect_m_id": skill_master_id,
                    "icon_type": icon_type
                })

        # ---- 어필 찬스 (experimental AC) ----
        if appeal_chance is not None:
            for idx, entry in enumerate(appeal_chance):
                id1 = entry['note_start']
                id2 = entry['note_end']
                wave_id_value = idx + 1  # Since wave_id starts from 1

                insert_appeal_chance_row(cursor, diff_id, wave_id_value, entry)

                # Update live_notes wave_id
                for note in data['live_notes']:
                    if note['id'] >= id1 and note['id'] <= id2:
                        note['wave_id'] = wave_id_value

                # AC 시작/종료 마커 노트 추가
                for note in data['live_notes']:
                    if note['id'] == id1:
                        call_time_start = note.get('call_time')
                        note_position_start = note.get('note_position')
                        # fix stuck appeal chance hold
                        if note_position_start == 1:
                            note_position_start = 2
                        elif note_position_start == 2:
                            note_position_start = 1
                        data['live_notes'].append({
                            "id": 0,
                            "call_time": int(call_time_start - 1),
                            "note_type": 4,
                            "note_position": note_position_start,
                            "gimmick_id": 0,
                            "note_action": 1,
                            "wave_id": wave_id_value,
                            "note_random_drop_color": 99,
                            "auto_judge_type": 20
                        })
                    elif note['id'] == id2:
                        call_time_end = note.get('call_time')
                        note_position_end = note.get('note_position')
                        data['live_notes'].append({
                            "id": 0,
                            "call_time": int(call_time_end + 1),
                            "note_type": 5,
                            "note_position": note_position_end,
                            "gimmick_id": 0,
                            "note_action": 1,
                            "wave_id": wave_id_value,
                            "note_random_drop_color": 99,
                            "auto_judge_type": 20
                        })

                data['live_wave_settings'].append({
                    "id": wave_id_value,
                    "wave_damage": entry['wave_damage'],
                    "mission_type": entry['mission_type'],
                    "arg_1": entry['mission_value'],
                    "arg_2": 0,  # Assuming this is a default value
                    "reward_voltage": entry['reward_voltage']
                })

        # ---- 스테이지 기믹 (사전 등록 불필요) ----
        if stage_gimmick is not None:
            if 'stage_gimmick_dict' not in data:
                data['stage_gimmick_dict'] = [2, []]
            elif len(data['stage_gimmick_dict']) != 2:
                data['stage_gimmick_dict'] = [2, []]

            for idx_gimmick, entry_gimmick in enumerate(stage_gimmick):
                uniq_id = idx_gimmick + 1001
                insert_stage_gimmick_row(cursor, diff_id, entry_gimmick)
                data['stage_gimmick_dict'][1].append({
                    "gimmick_master_id": entry_gimmick['id'],
                    "condition_master_id_1": 1,
                    "condition_master_id_2": 1,
                    "skill_master_id": entry_gimmick['skill_id'],
                    "uniq_id": uniq_id,
                })

        # ---- 마무리: call_time 순 정렬 후 id 재부여 ----
        live_notes_fixup = data['live_notes']
        live_notes_fixup.sort(key=lambda x: int(x['call_time']))
        for idx_finalize, item_finalize in enumerate(live_notes_fixup):
            item_finalize['id'] = idx_finalize + 1

        with open(out_path, 'w', encoding='utf-8') as difficult_file:
            json.dump(data, difficult_file, indent=2)

    return id_count

def insert_asset_rows(cursor):
    """8개 에셋 DB 공통: m_movie / m_asset_pack / m_asset_sound / texture 등록."""
    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))

    # (light download auto delete fix)
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))


def insert_live_difficulty_block(cursor):
    """m_live_difficulty / const / 난이도 미션 / 평가 드롭 등록.
    (GL/JP masterdata 공통 - 전역 계산값 사용)"""
    diff_ids = [music_diff1_masterdata, music_diff2_masterdata, music_diff3_masterdata]
    eval_scores = [evaluation_score_easy, evaluation_score_normal, evaluation_score_hard]
    eval_a = [evaluation_a_score_easy, evaluation_a_score_normal, evaluation_a_score_hard]
    eval_b = [evaluation_b_score_easy, evaluation_b_score_normal, evaluation_b_score_hard]
    eval_c = [evaluation_c_score_easy, evaluation_c_score_normal, evaluation_c_score_hard]
    emit = [note_emit_msec_easy, note_emit_msec_normal, note_emit_msec_hard]
    power = [recommend_power_easy, recommend_power_normal, recommend_power_hard]
    stamina = [recommend_stamina_easy, recommend_stamina_normal, recommend_stamina_hard]
    damage = [note_stamina_damage_easy, note_stamina_damage_normal, note_stamina_damage_hard]

    for i, d_key in enumerate(DIFF_KEYS):
        d = drop_items[d_key]
        cursor.execute(LIVE_DIFFICULTY_SQL[i],
                       (diff_ids[i], live_id_masterdata, donot_insert, attribute_live,
                        eval_scores[i], emit[i], power[i], stamina[i],
                        d[0], d[1], d[2], d[3], d[4],
                        eval_scores[i], eval_a[i], eval_b[i], eval_c[i],
                        donot_insert, diff_ids[i],))

    for i in range(3):
        cursor.execute(LIVE_DIFFICULTY_CONST_SQL[i], (diff_ids[i], damage[i],))

    # live end give you reward 10 stargem
    for i in range(3):
        cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (diff_ids[i],))
        cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (diff_ids[i], eval_b[i],))
        cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (diff_ids[i], eval_scores[i],))

    # evaluation drop
    for i in range(3):
        for ev_type in ('10', '20', '30', '40', '50'):
            cursor.execute(f"INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '{ev_type}');", (diff_ids[i],))


def insert_missions_and_rewards(cursor, generate_ids):
    """m_mission (10/50/100회 클리어) 3종과 보상 등록.
    GL은 ID 생성-삽입을 미션별로 교차 수행(원본과 동일), JP는 기존 ID 재사용."""
    global mission_1_masterdata, mission_2_masterdata, mission_3_masterdata
    global mission_desc_dictionary_dic1, mission_desc_dictionary_dic2, mission_desc_dictionary_dic3
    global mission_desc_dictionary_masterdata1, mission_desc_dictionary_masterdata2, mission_desc_dictionary_masterdata3

    preset_ids = [id_mission1, id_mission2, id_mission3]
    mission_ids = [mission_1_masterdata, mission_2_masterdata, mission_3_masterdata] if not generate_ids else [None, None, None]
    desc_keys = [None, None, None]

    for n in range(3):
        if generate_ids:
            if preset_ids[n] is None:
                mission_ids[n] = generate_unique_id(
                    cursor, "SELECT COUNT(*) FROM main.m_mission WHERE id = ?;", 999999999)
            else:
                mission_ids[n] = preset_ids[n]
            desc_keys[n] = "freemission_desc_" + str(mission_ids[n])
        else:
            desc_keys[n] = "freemission_desc_" + str(mission_ids[n])

        desc_masterdata = "m." + desc_keys[n]

        cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
        result_m = cursor.fetchone()
        min_display_order_m = result_m[0] if result_m[0] is not None else 0
        display_order_new_m = min_display_order_m - 1

        if n == 0:
            params = (mission_ids[0], desc_masterdata, donot_insert, donot_insert,
                      donot_insert, donot_insert, display_order_new_m,
                      live_id_masterdata, donot_insert, donot_insert,)
        else:
            params = (mission_ids[n], desc_masterdata, mission_ids[n-1], donot_insert,
                      donot_insert, donot_insert, donot_insert, display_order_new_m,
                      live_id_masterdata, donot_insert, donot_insert,)
        cursor.execute(MISSION_SQL[n], params)

    # mission reward
    for n in range(3):
        cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
        result_mr = cursor.fetchone()
        min_display_order_mr = result_mr[0] if result_mr[0] is not None else 0
        display_order_new_mr = min_display_order_mr - 1
        sql, extra = MISSION_REWARD_SQL[n]
        if extra == 'emblem':
            cursor.execute(sql, (mission_ids[n], display_order_new_mr, emblem_id_masterdata,))
        else:
            cursor.execute(sql, (mission_ids[n], display_order_new_mr,))

    mission_1_masterdata, mission_2_masterdata, mission_3_masterdata = mission_ids
    mission_desc_dictionary_dic1, mission_desc_dictionary_dic2, mission_desc_dictionary_dic3 = desc_keys
    mission_desc_dictionary_masterdata1 = "m." + desc_keys[0]
    mission_desc_dictionary_masterdata2 = "m." + desc_keys[1]
    mission_desc_dictionary_masterdata3 = "m." + desc_keys[2]


def insert_appeal_chance_dictionary(cursor, diff_id, appeal_chance):
    """어필 찬스 미션 설명을 사전(_k) DB에 등록한다.
    (4개 언어 x 3난이도 = 12회 복붙 블록 통합)"""
    for idx_dict, entry_dict in enumerate(appeal_chance):
        wave_id_dictionary = idx_dict + 1
        wave_id_naming = f"live_detail_wave_mission_{diff_id}_{wave_id_dictionary}"
        template = mission_type_name_dictionary.get(entry_dict['mission_type'])
        if entry_dict['mission_type'] == 16:
            arg1_value = int(entry_dict['mission_value'] / 100)
        else:
            arg1_value = int(entry_dict['mission_value'])
        arg1_per_insert = arg1_value
        appeal_chance_text = f"{template.format(arg1_per_insert=arg1_per_insert)}"
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (wave_id_naming, appeal_chance_text))


def insert_package_rows(cursor):
    """8개 에셋 DB 공통: 다운로드 패키지 매핑/버전 등록."""
    fresh_version = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main = hashlib.sha1(str(random.random()).encode()).hexdigest()

    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset = cursor.fetchone()[0]
    update_main_asset = get_main_asset + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                   (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                   (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                   (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                   (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                   (fresh_version_main, update_main_asset))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                   (package_key_live, fresh_version))

    if videoprime_file != "":
        fresh_version_movie = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                       (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                       (package_key_movie, fresh_version_movie))

# ============================================================
# 3. 메인 흐름
# ============================================================

# ---- 어필 찬스 미션 문구 사전 (4개 사전 DB에서 exec 됨) ----
with open("dictionary_live_en.txt", 'r', encoding='utf-8') as key_file:
    keyload = key_file.read()

# ---- 애드온 설정 기본값 (zip 안의 .txt가 exec로 덮어씀) ----
appeal_chance_easy = None
appeal_chance_normal = None
appeal_chance_hard = None
stage_gimmick_easy = None
stage_gimmick_normal = None
stage_gimmick_hard = None
note_gimmick_easy = None
note_gimmick_normal = None
note_gimmick_hard = None

# init code
id_live = None
id_emblem = None
id_mission1 = None
id_mission2 = None
id_mission3 = None

music_name_en = ""
music_name_ko = ""
music_name_zh = ""
music_name_ja = ""
music_copyright_name_en = ""
music_copyright_name_ko = ""
music_copyright_name_zh = ""
music_copyright_name_ja = ""
music_description = ""

music_file = ""
music_sabi_file = ""
thumbnail_file = ""
emblem_file = ""
videoprime_file = ""
easy_difficulty_file = ""
normal_difficulty_file = ""
hard_difficulty_file = ""

# settings
member_group_live = 100
	# 1 - Myuzu
	# 2 - Aqours
	# 3 - Nijigasaki
	# 4 - Liella
	# 100 - Union *unused

attribute_live = 9
	# 1 - Smile ... 9 - Untyped / Unknown (자세한 목록은 ATTRIBUTE_NAMES 참고)

note_emit_msec_easy = 3620
note_stamina_damage_easy = 100
evaluation_score_easy = None

note_emit_msec_normal = 3077
note_stamina_damage_normal = 200
evaluation_score_normal = None

note_emit_msec_hard = 2534
note_stamina_damage_hard = 300
evaluation_score_hard = None

# mission_type / gimmick / appeal_chance 설정 형식 예시는
# 원본 live_addon_installer.py 상단 주석을 참고하세요.

check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

# Set folder path based on environment
if is_termux():
    modding_elichika_path = os.path.expanduser('~/storage/downloads/sukusta/live/')
    termux_storage_chc = os.path.expanduser('~/storage/')
    if not os.path.exists(termux_storage_chc):
        print('Path is missing, please execute termux-setup-storage command and allow it')
        sys.exit(1)
else:
    # Set a default or other path if not in Termux
    modding_elichika_path = "assets/package/live/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

# ---- zip 파일 선택 ----
clear_terminal()
temp_directory = "assets/package/.cache/"
shutil.rmtree(temp_directory, ignore_errors=True)

zip_files = []
for root, dirs, files in os.walk(modding_elichika_path):
    for file in files:
        if file.endswith(".zip"):
            zip_files.append(os.path.relpath(os.path.join(root, file), modding_elichika_path))

zip_files.sort()

print("Available .zip files:")
for i, zip_file in enumerate(zip_files, start=1):
    print(f"{i}. {zip_file}")

try:
    chosen_number = int(input("Enter the number corresponding to the .zip file you want to choose: "))
    if 1 <= chosen_number <= len(zip_files):
        zip_file_path = os.path.join(modding_elichika_path, zip_files[chosen_number - 1])
        print(f"You chose: {zip_file_path}")
    else:
        print("Invalid number. Please enter a valid number.")
        sys.exit(1)
except ValueError:
    print("Invalid input. Please enter a number.")
    sys.exit(1)

# ---- zip 추출 및 .txt 설정 exec (원본과 동일하게 모듈 전역에서 실행) ----
os.makedirs(temp_directory, exist_ok=True)
with open(zip_file_path, 'rb') as zip_file:
    zip_data = zip_file.read()

zip_buffer = io.BytesIO(zip_data)

with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
    zip_ref.extractall(temp_directory)
    for file_info in zip_ref.infolist():
        if file_info.filename.endswith('.txt'):
            txt_file_path = os.path.join(temp_directory, file_info.filename)
            with open(txt_file_path, 'r', encoding='utf-8') as txt_file:
                try:
                    file_content = txt_file.read()
                    exec(file_content)
                except Exception as e:
                    print(f"Error executing file: {file_info.filename}\nError: {e}")

# ---- 요약 출력 및 확인 ----
clear_terminal()
print('Name: ' + music_name_en)
print('Copyright: ' + music_copyright_name_en)
if member_group_live in GROUP_NAMES:
    print('Group: ' + GROUP_NAMES[member_group_live])
else:
    print('Please enter correct member_group_live value')
    sys.exit(1)

if attribute_live in ATTRIBUTE_NAMES:
    print('Attribute: ' + ATTRIBUTE_NAMES[attribute_live])
else:
    print('Please enter correct attribute value')
    sys.exit(1)

if videoprime_file != "":
    print('MV Video: yes')
else:
    print('MV Video: no')
print('Description: ' + music_description)
do_you_think_want_add_this = input("do you want add this? (y/n): ")

if do_you_think_want_add_this != "n":
    clear_terminal()
else:
    clear_terminal()
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)

do_backup_is_important = input("would you like backup database? (y/n): ")
if do_backup_is_important == "y":
    backup_operate(filelist)
else:
    print('well then do your own risk')

# ---- 파일 경로/이름/크기 산출 ----
start_encrypt1 = temp_directory + music_file
start_encrypt2 = temp_directory + music_sabi_file
start_encrypt3 = temp_directory + thumbnail_file
start_encrypt4 = temp_directory + emblem_file
if videoprime_file != "":
    start_encrypt5 = temp_directory + videoprime_file

music_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
music_sabi_filename = os.path.splitext(start_encrypt2.split("/")[-1])[0]
thumbnail_music_filename = os.path.splitext(start_encrypt3.split("/")[-1])[0]
emblem_filename = os.path.splitext(start_encrypt4.split("/")[-1])[0]

thumbnail_music_size = os.path.getsize(start_encrypt3)
thumbnail_emblem_size = os.path.getsize(start_encrypt4)
music_live_size = os.path.getsize(start_encrypt1)
music_live_sabi_size = os.path.getsize(start_encrypt2)
if videoprime_file != "":
    mv_filesize = os.path.getsize(start_encrypt5)

# ---- 파일명 검증 (소문자 영숫자만 허용) ----
for check_name, check_label in [(music_filename, 'Music'),
                                (music_sabi_filename, 'Music SABI'),
                                (thumbnail_music_filename, 'Thumbnail'),
                                (emblem_filename, 'Emblem')]:
    if not check_name.isalnum() or not check_name.islower():
        print(f'Invalid {check_label} Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)

encrypted_emblem = "static/assets/" + os.path.splitext(start_encrypt4.split("/")[-1])[0]
encrypted_thumbnail = "static/assets/" + os.path.splitext(start_encrypt3.split("/")[-1])[0]
music_filename_saved = "static/assets/" + os.path.splitext(start_encrypt1.split("/")[-1])[0]
music_sabi_filename_saved = "static/assets/" + os.path.splitext(start_encrypt2.split("/")[-1])[0]
if videoprime_file != "":
    movie_filename_saved = "static/assets/" + os.path.splitext(start_encrypt5.split("/")[-1])[0]

# ---- static/assets 암호화 ----
encrypted_folder = "static/assets/"
if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

encrypt_asset(start_encrypt3, encrypted_thumbnail, "jacket")
encrypt_asset(start_encrypt4, encrypted_emblem, "emblem")
print("assets encrypted")

# ---- 8개 에셋 DB 등록 (첫 DB에서 중복 검사/시트명 추출/파일 이동) ----
with sqlite3.connect(ASSET_DB_PATHS[0]) as conn:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM m_asset_pack WHERE pack_name = ?", (music_filename,))
    result_chcc = cursor.fetchone()
    if result_chcc[0] > 0:
        print(f"This live already exists in the database")
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)

    sheet_name_file = read_acb_sheet_name(start_encrypt1)
    sheet_name_file1 = read_acb_sheet_name(start_encrypt2)
    shutil.move(start_encrypt1, music_filename_saved)
    shutil.move(start_encrypt2, music_sabi_filename_saved)
    thumbnail_music_path = generate_unique_hash(
        cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    emblem_path = generate_unique_hash(
        cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    donot_insert = None
    if videoprime_file != "":
        movie_genpath = generate_unique_hash(
            cursor, "SELECT COUNT(*) FROM main.m_movie WHERE pavement = ?;")
        movie_filename = os.path.splitext(start_encrypt5.split("/")[-1])[0]
        movie_filesize = os.path.getsize(start_encrypt5)
        shutil.move(start_encrypt5, movie_filename_saved)
        # 첫 DB의 m_movie/m_asset_pack 등록은 insert_asset_rows 가 수행

    insert_asset_rows(cursor)

for asset_db_path in ASSET_DB_PATHS[1:]:
    with sqlite3.connect(asset_db_path) as conn:
        cursor = conn.cursor()
        insert_asset_rows(cursor)

# ---- masterdata (GL): ID 생성, m_live, 비트맵 편집, 난이도/미션/엠블럼 ----
with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
    cursor = conn.cursor()

    if id_live is None:
        live_id_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_live WHERE live_id = ?;", 99999)
        music_id_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_live WHERE music_id = ?;", 9999, 1000)
        music_diff1_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", 99999999)
        music_diff2_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", 99999999)
        music_diff3_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", 99999999)
    else:
        id_live_str = str(id_live)
        id_live_split1 = int(id_live_str[1:])
        live_id_masterdata = id_live
        music_id_masterdata = id_live_split1
        music_diff1_masterdata = str(id_live) + "101"
        music_diff2_masterdata = str(id_live) + "201"
        music_diff3_masterdata = str(id_live) + "301"

    if id_emblem is None:
        emblem_id_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_emblem WHERE id = ?;", 999999999)
    else:
        emblem_id_masterdata = id_emblem

    music_name_dictionary_masterdata = "k.song_name_so" + str(music_id_masterdata)
    music_id_copyright_masterdata = "k.song_copyright_so" + str(music_id_masterdata)
    music_name_dictionary_dic = "song_name_so" + str(music_id_masterdata)
    music_id_copyright_dic = "song_copyright_so" + str(music_id_masterdata)

    emblem_dictionary_description = "m_dic_emblem_description_" + str(emblem_id_masterdata)
    emblem_dictionary_description_masterdata = "k." + emblem_dictionary_description

    cursor.execute("SELECT MAX(display_order) FROM main.m_live WHERE member_group=?;", (member_group_live,))
    result = cursor.fetchone()
    min_display_order = result[0] if result[0] is not None else 0

    cursor.execute("SELECT MAX(display_order) FROM main.m_emblem;")
    result2 = cursor.fetchone()
    min_display_order2 = result2[0] if result2[0] is not None else 0

    display_order_new = min_display_order + 1
    display_order_new2 = min_display_order2 + 1

    # there no Liella & Union chibi so i will reuse myuzu
    member_mapping_live = MEMBER_MAPPING[member_group_live]
    drop_items = compute_drop_items(member_group_live, attribute_live)

    cursor.execute(M_LIVE_SQL,
                   (live_id_masterdata, music_id_masterdata, sheet_name_file, sheet_name_file1, member_mapping_live, music_name_dictionary_masterdata, donot_insert, member_group_live, donot_insert, donot_insert, music_id_copyright_masterdata, donot_insert, thumbnail_music_path, display_order_new))

    # cannot get information Note Gimmick
    # if you are dev, feel free to edit

    saved_diffx = "assets/stages/"
    output_filename1 = saved_diffx + f"{music_diff1_masterdata}.json"
    output_filename2 = saved_diffx + f"{music_diff2_masterdata}.json"
    output_filename3 = saved_diffx + f"{music_diff3_masterdata}.json"
    start_editbeatmap1 = temp_directory + easy_difficulty_file
    start_editbeatmap2 = temp_directory + normal_difficulty_file
    start_editbeatmap3 = temp_directory + hard_difficulty_file

    id_count_easy = process_beatmap(cursor, start_editbeatmap1, output_filename1,
                                    music_diff1_masterdata, note_gimmick_easy,
                                    appeal_chance_easy, stage_gimmick_easy)
    id_count_normal = process_beatmap(cursor, start_editbeatmap2, output_filename2,
                                      music_diff2_masterdata, note_gimmick_normal,
                                      appeal_chance_normal, stage_gimmick_normal)
    id_count_hard = process_beatmap(cursor, start_editbeatmap3, output_filename3,
                                    music_diff3_masterdata, note_gimmick_hard,
                                    appeal_chance_hard, stage_gimmick_hard)

    # score logic - automatic setup score based on note count
    if evaluation_score_easy is None:
        evaluation_score_easy = int(id_count_easy * 12500)
    if evaluation_score_normal is None:
        evaluation_score_normal = int(id_count_normal * 25000)
    if evaluation_score_hard is None:
        evaluation_score_hard = int(id_count_hard * 50000)

    evaluation_a_score_easy = int(evaluation_score_easy * 0.75)
    evaluation_b_score_easy = int(evaluation_score_easy * 0.5)
    evaluation_c_score_easy = int(evaluation_score_easy * 0.25)
    evaluation_a_score_normal = int(evaluation_score_normal * 0.75)
    evaluation_b_score_normal = int(evaluation_score_normal * 0.5)
    evaluation_c_score_normal = int(evaluation_score_normal * 0.25)
    evaluation_a_score_hard = int(evaluation_score_hard * 0.75)
    evaluation_b_score_hard = int(evaluation_score_hard * 0.5)
    evaluation_c_score_hard = int(evaluation_score_hard * 0.25)

    # stat logic
    recommend_stamina_easy = int(note_stamina_damage_easy * id_count_easy)
    recommend_stamina_normal = int(note_stamina_damage_normal * id_count_normal)
    recommend_stamina_hard = int(note_stamina_damage_hard * id_count_hard)
    recommend_power_easy = int(evaluation_score_easy / id_count_easy / 3)
    recommend_power_normal = int(evaluation_score_normal / id_count_normal / 3)
    recommend_power_hard = int(evaluation_score_hard / id_count_hard / 3)

    insert_live_difficulty_block(cursor)

    # emblem
    cursor.execute(M_EMBLEM_SQL,
                   (emblem_id_masterdata, music_name_dictionary_masterdata, emblem_dictionary_description_masterdata, donot_insert, emblem_path, donot_insert, display_order_new2))

    # mission + reward (ID 생성 포함)
    insert_missions_and_rewards(cursor, generate_ids=True)

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_live_movie (live_id, codec, movie_asset_path, stage_background_asset_path) VALUES (?, 'prime', ?, 'Bl7');", (live_id_masterdata, movie_genpath))

# ---- masterdata (JP): GL과 동일 내용을 JP DB에 등록 ----
with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(display_order) FROM main.m_live WHERE member_group=?;", (member_group_live,))
    result_ja_cl = cursor.fetchone()
    min_display_order_ja = result_ja_cl[0] if result_ja_cl[0] is not None else 0

    cursor.execute("SELECT MAX(display_order) FROM main.m_emblem;")
    result2_ja_cl = cursor.fetchone()
    min_display_order2_ja = result2_ja_cl[0] if result2_ja_cl[0] is not None else 0

    display_order_new_ja = min_display_order_ja + 1
    display_order_new2_ja = min_display_order2_ja + 1

    # 노트 기믹 (JSON 편집 없이 DB 등록만)
    jp_diff_ids = [music_diff1_masterdata, music_diff2_masterdata, music_diff3_masterdata]
    jp_note_gimmicks = [note_gimmick_easy, note_gimmick_normal, note_gimmick_hard]
    for jp_diff_id, jp_ng in zip(jp_diff_ids, jp_note_gimmicks):
        if jp_ng is not None:
            for entry_note in jp_ng:
                ids_note = entry_note['note_id']
                skill_desc_id = entry_note['skill_description_id']
                description = f"k.live_detail_notes_desc_{skill_desc_id}"
                skill_master_id, icon_type, gimmick_type, name = \
                    lookup_note_gimmick_info(cursor, description)
                insert_note_gimmick_rows(cursor, jp_diff_id, ids_note, gimmick_type,
                                         icon_type, skill_master_id, name, description)

    # 어필 찬스 / 스테이지 기믹 (난이도별 교차 순서: 원본과 동일)
    jp_appeal_chances = [appeal_chance_easy, appeal_chance_normal, appeal_chance_hard]
    jp_stage_gimmicks = [stage_gimmick_easy, stage_gimmick_normal, stage_gimmick_hard]
    for jp_diff_id, jp_ac, jp_sg in zip(jp_diff_ids, jp_appeal_chances, jp_stage_gimmicks):
        if jp_ac is not None:
            for idx, entry in enumerate(jp_ac):
                insert_appeal_chance_row(cursor, jp_diff_id, idx + 1, entry)
        # add gimmick, no need dictionary insert
        if jp_sg is not None:
            for entry_gimmick in jp_sg:
                insert_stage_gimmick_row(cursor, jp_diff_id, entry_gimmick)

    cursor.execute(M_LIVE_SQL,
                   (live_id_masterdata, music_id_masterdata, sheet_name_file, sheet_name_file1, member_mapping_live, music_name_dictionary_masterdata, donot_insert, member_group_live, donot_insert, donot_insert, music_id_copyright_masterdata, donot_insert, thumbnail_music_path, display_order_new_ja))

    insert_live_difficulty_block(cursor)

    # emblem
    cursor.execute(M_EMBLEM_SQL,
                   (emblem_id_masterdata, music_name_dictionary_masterdata, emblem_dictionary_description_masterdata, donot_insert, emblem_path, donot_insert, display_order_new2_ja))

    # mission + reward (GL에서 만든 ID 재사용)
    insert_missions_and_rewards(cursor, generate_ids=False)

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_live_movie (live_id, codec, movie_asset_path, stage_background_asset_path) VALUES (?, 'prime', ?, 'Bl7');", (live_id_masterdata, movie_genpath))

# ---- 사전(_k) DB: 곡명/저작권/엠블럼 설명 + 어필 찬스 문구 ----
music_names = {"en": music_name_en, "ko": music_name_ko,
               "zh": music_name_zh, "ja": music_name_ja}
copyright_names = {"en": music_copyright_name_en, "ko": music_copyright_name_ko,
                   "zh": music_copyright_name_zh, "ja": music_copyright_name_ja}

for dict_db, lang in DICTIONARY_K_DBS:
    with sqlite3.connect(dict_db) as conn:
        cursor = conn.cursor()
        exec(keyload)  # mission_type_name_dictionary 정의 (원본과 동일하게 매번 exec)
        message_title = EMBLEM_TITLE_TEMPLATES[lang].format(name=str(music_names[lang]))
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_name_dictionary_dic, music_names[lang]))
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_id_copyright_dic, copyright_names[lang]))
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (emblem_dictionary_description, message_title))
        if appeal_chance_easy is not None:
            insert_appeal_chance_dictionary(cursor, music_diff1_masterdata, appeal_chance_easy)
        if appeal_chance_normal is not None:
            insert_appeal_chance_dictionary(cursor, music_diff2_masterdata, appeal_chance_normal)
        if appeal_chance_hard is not None:
            insert_appeal_chance_dictionary(cursor, music_diff3_masterdata, appeal_chance_hard)

# ---- 사전(_m) DB: 미션 설명 (10/50/100회) ----
mission_desc_keys = [mission_desc_dictionary_dic1, mission_desc_dictionary_dic2, mission_desc_dictionary_dic3]
for dict_db, lang in DICTIONARY_M_DBS:
    with sqlite3.connect(dict_db) as conn:
        cursor = conn.cursor()
        for n in range(3):
            message_mission = MISSION_TITLE_TEMPLATES[lang][n].format(name=str(music_names[lang]))
            cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_keys[n], message_mission))

# ---- 8개 에셋 DB에 다운로드 패키지 등록 ----
package_key_live = "music:" + str(live_id_masterdata)
package_key_common = "main"
if videoprime_file != "":
    package_key_movie = "live_movie:" + str(live_id_masterdata) + "_prime"

for package_db_path in PACKAGE_DB_PATHS:
    with sqlite3.connect(package_db_path) as conn:
        cursor = conn.cursor()
        insert_package_rows(cursor)

# ---- 마무리 ----
print("deleting temp folder")
shutil.rmtree(temp_directory, ignore_errors=True)

with open(check_json_config, 'r') as f:
    config_elichika = json.load(f)
    xcheck_cdn = config_elichika.get('cdn_server')
    if xcheck_cdn != "http://127.0.0.1:8080/static":
        config_elichika['cdn_server'] = "http://127.0.0.1:8080/static"
        with open(check_json_config, 'w') as f:
            json.dump(config_elichika, f, indent=4)
            print("CDN server updated to http://127.0.0.1:8080/static")

print("FINISHED")
sys.exit(1)
