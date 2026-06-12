"""Card addon installer for elichika (refactored).

기능은 원본 card_addon_installer.py와 100% 동일하게 유지하면서
중복 코드를 데이터 테이블과 헬퍼 함수로 정리한 버전입니다.

구조:
  1. 헬퍼 함수      - 백업, 암호화, 고유 ID 생성, 스킬 아이콘 조회
  2. 데이터 테이블  - 캐릭터 이름/의존성, 가챠 연출, 트레이닝 트리, 스킬 아이콘
  3. 메인 흐름      - zip 선택 -> 설정 exec -> 암호화 -> DB 등록 -> 마무리

주의: 애드온 zip 안의 .txt 설정 파일과 dictionary_skill_en.txt 는 원본과
동일하게 모듈 전역 네임스페이스에서 exec 되므로, 설정 변수와 스킬 문구
사전들(effect_type_dictionary 등)은 모듈 전역 변수로 유지됩니다.
"""

import sqlite3
import os
import zipfile
import io
import platform
import random
import sys
import shutil
import json
import hashlib
from datetime import datetime

check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')

clear_terminal()
print("CARD ADDON WILL NOT RECEIVE UPDATE ANYMORE")
print("BY READING THIS, YOU WILL ACCEPT THE RISK")
print("")
confirm_script_card = input("Press Enter to Continue")

def backup_operate(filelist):
    # Create a folder with the current date and time as the name
    backup_folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    os.makedirs(backup_folder)

    for file_path in filelist:
        relative_path = os.path.relpath(file_path, start=".")
        dest_path = os.path.join(backup_folder, relative_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy(file_path, dest_path)

    print("Backup completed successfully.")

filelist = [
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/dictionary_ja_k.db",
    "assets/db/jp/masterdata.db",
    "serverdata.db",
    "userdata.db"
]

# load up dictionary (스킬 문구 사전 - 사전 DB 블록에서 exec 됨)
with open("dictionary_skill_en.txt", 'r', encoding='utf-8') as key_en:
    keyload_en = key_en.read()

# category
skill_effect_category_immediate = {2, 3, 4, 5, 8, 68, 69, 70, 90, 91, 92, 93, 94, 95, 96, 97, 98, 109, 110, 111, 112, 113, 114, 115, 116, 127, 128, 129, 130, 131, 132, 133, 134, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 235, 236, 241, 242, 247, 248, 253, 254, 262, 263, 266, 267}
skill_effect_category_activebasebuff = {26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 84, 85, 86, 87, 88, 89, 99, 102, 103, 104, 257}
skill_effect_category_immediate_remove  = {52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67}
skill_effect_category_player = {6, 7, 23, 25, 106, 107, 108, 209, 210, 211, 212, 99, 102, 103, 104, 266, 267}
skill_effect_category_calculation_add = [2, 3, 4, 5, 9]

# m_skill_effect_value_count 등록 대상 효과 타입 (원본 in [...] 목록 그대로)
skill_effect_value_count_types = [119, 121, 123, 125, 128, 130, 132, 134, 161, 162, 163, 164, 177, 178, 179, 180, 193, 194, 195, 196, 209, 210, 211, 212]

def manipulate_file(data, keys_0, keys_1, keys_2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF

def calculate_parameter_value(min_value, max_value, min_level, max_level, level):
    level_range = max_level - min_level
    level_completion = (level - min_level) / level_range
    parameter_value = int(min_value + (max_value - min_value) * level_completion)
    return parameter_value

def generate_unique_id(cursor, count_sql, upper, lower=0):
    """count_sql 의 COUNT 가 0이 될 때까지 [lower, upper] 난수를 뽑는다.
    (원본의 generate_unique_* 함수 17개 통합)"""
    while True:
        new_id = random.randint(lower, upper)
        cursor.execute(count_sql, (new_id,))
        if cursor.fetchone()[0] == 0:
            return new_id

def generate_unique_hash(cursor, count_sql):
    """해당 테이블에 없는 32비트 16진 해시를 뽑는다."""
    while True:
        new_hash = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute(count_sql, (new_hash,))
        if cursor.fetchone()[0] == 0:
            return new_hash

def read_acb_sheet_name(path):
    """오프셋 1438부터 0x00 직전까지의 텍스트(시트 이름)를 읽는다."""
    with open(path, 'rb') as file:
        file.seek(1438)
        selected_text_deretote = b''
        while True:
            byte = file.read(1)
            if byte == b'\x00':
                break
            selected_text_deretote += byte
        return selected_text_deretote.decode('utf-8')

def encrypt_asset_if_needed(src, dst, label):
    """key (12345, 0, 0) XOR 암호화. 이미 결과 파일이 있으면 건너뜀."""
    if not os.path.exists(dst):
        with open(src, "rb") as file:
            data = bytearray(file.read())
            key_0 = 12345
            key_1 = 0
            key_2 = 0
            print(f"encrypting {label}")
            manipulate_file(data, key_0, key_1, key_2)
            with open(dst, "wb") as file:
                file.write(data)
    else:
        print(f"{label} already encrypted")

# ---- 스킬 아이콘 매핑 (원본 if/elif 순서 그대로, 첫 일치 우선) ----
# 'KSLASH' 항목은 원본의 'K' + chr(left_slash_fix) 로직을 그대로 따른다:
# 액티브 스킬 분기에서만 left_slash_fix 가 정의되므로, 어빌리티가 먼저
# [40, 21] 에 걸리면 원본과 동일하게 NameError 가 발생한다.
KSLASH = object()
SKILL_ICON_TABLE = [
    ([20], '"4'),
    ([5, 97, 116, 134], "'I"),
    ([17], "*|"),
    ([4, 14, 94, 113, 114], ":"),
    ([6], "Ee"),
    ([2, 90, 109, 110], "IT"),
    ([17, 26, 28, 119], "K9"),
    ([40, 21], KSLASH),
    ([23, 25, 108], "QF"),
    ([19, 29], "_]"),
    ([3, 91, 92, 111, 112], 'd"'),
    ([22, 33], 'py'),
    ([18], '~.'),
    ([106], "+_"),
    ([60], "LO"),
    ([118], 'N"'),
    ([261], 'Rj4'),
    # unused icon expect dual
    ([243], "X^"),
    ([249], "*u"),
    ([237], ".&"),
    ([231], "^*"),
    ([225], ";:"),
    ([227], '2"'),
    ([226], 'iQ'),
    ([8], 'YG'),
]

def lookup_skill_icon(effect_type, define_slash):
    global left_slash_fix
    for types, icon in SKILL_ICON_TABLE:
        if effect_type in types:
            if icon is KSLASH:
                if define_slash:
                    left_slash_fix = 92
                return 'K' + chr(left_slash_fix)
            return icon
    # use lock icon if no available
    return "+H"

# 패시브 스킬 아이콘 (effect type 9-16, 그 외 잠금 아이콘)
PASSIVE_SKILL_ICONS = {9: "#?", 10: "Kz", 11: "iE", 12: "+H", 13: "<[",
                       14: ")a", 15: "EP", 16: "'y"}

# 레어도별 카드 상수: (rarity, sp, exchange_item_id, passive_slot, passive_slot_max)
RARITY_CARD_CONSTANTS = {
    "SR": (20, 2, 2, 1, 3),
    "UR": (30, 3, 3, 1, 3),
    "FES": (30, 4, 3, 2, 4),
    "PARTY": (30, 4, 3, 2, 4),
}
# ---- 캐릭터 이름 (요약 표시용) ----
CHARA_NAMES = {
    1: 'Honoka Kousaka',
    2: 'Eli Ayase',
    3: 'Kotori Minami',
    4: 'Umi Sonoda',
    5: 'Rin Hoshizora',
    6: 'Maki Nishikino',
    7: 'Nozomi Tojo',
    8: 'Hanayo Koizumi',
    9: 'Nico Yazawa',
    101: 'Chika Takami',
    102: 'Riko Sakurauchi',
    103: 'Kanan Matsuura',
    104: 'Dia Kurosawa',
    105: 'You Watanabe',
    106: 'Yoshiko Tsushima',
    107: 'Hanamaru Kunikida',
    108: 'Mari Ohara',
    109: 'Ruby Kurosawa',
    201: 'Ayumu Uehara',
    202: 'Kasumi Nakasu',
    203: 'Shizuku Osaka',
    204: 'Karin Asaka',
    205: 'Ai Miyashita',
    206: 'Kanata Konoe',
    207: 'Setsuna Yuki',
    208: 'Emma Verde',
    209: 'Rina Tennoji',
    210: 'Shioriko Mifune',
    212: 'Lanzhu Zhong',
    211: 'Mia Taylor',
}

# ---- member_model_dependency: 캐릭터별 (경로종류, 의존성) 등록 순서 그대로 ----
# 경로종류 'costume' = costume_path, 'rina' = rina_unmask_costume_path
MEMBER_MODEL_DEPENDENCIES = {
    1: [('costume', '{#'), ('costume', 'Q9'), ('costume', 'aE'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    2: [('costume', '.]'), ('costume', '8C'), ('costume', 'k?'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    3: [('costume', 'g4'), ('costume', 'T1'), ('costume', 'v'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    4: [('costume', 'M!'), ('costume', '_|'), ('costume', 't$'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    5: [('costume', '!{'), ('costume', '?A'), ('costume', 'M_'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    6: [('costume', '1Q'), ('costume', 'YS'), ('costume', '~Y'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    7: [('costume', 'J9'), ('costume', 'L_'), ('costume', '}x'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    8: [('costume', 'BX'), ('costume', '[*'), ('costume', 'dR'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    9: [('costume', 'Z7'), ('costume', 'C{'), ('costume', '#s'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    101: [('costume', '5]'), ('costume', '85'), ('costume', 'MS'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    102: [('costume', 'Bz'), ('costume', 'F$'), ('costume', '0*'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    103: [('costume', "'x"), ('costume', '(A'), ('costume', 't~'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    104: [('costume', '.q'), ('costume', 'Iu'), ('costume', 'x='), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    105: [('costume', 'iy'), ('costume', 'jo'), ('costume', 'lR'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    106: [('costume', 'Wm'), ('costume', "Z'"), ('costume', 'di'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    107: [('costume', '2*'), ('costume', ';L'), ('costume', 'Tv'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    108: [('costume', 'B*'), ('costume', '^5'), ('costume', '_v'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    109: [('costume', 'p2'), ('costume', 'a|'), ('costume', 'U}'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    201: [('costume', ".'"), ('costume', 'f%'), ('costume', 'sq'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    202: [('costume', '"{'), ('costume', '_K'), ('costume', 'uK'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    203: [('costume', '^g'), ('costume', 'bS'), ('costume', '#M'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    204: [('costume', '7,'), ('costume', 'Aa'), ('costume', 'io'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    205: [('costume', '("'), ('costume', '1]'), ('costume', 'a+'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    206: [('costume', ')#'), ('costume', 'LB'), ('costume', 'Si'), ('costume', '§?D#'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§j^'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
    207: [('costume', '8m'), ('costume', 'fl'), ('costume', '(Q'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    208: [('costume', 'g_'), ('costume', 'dE'), ('costume', '28'), ('costume', '§?D#'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§j^'), ('costume', '§Vr'), ('costume', '§M|')],
    209: [('costume', 'ID'), ('costume', 'wS'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+'), ('rina', 'Z$'), ('rina', 'xU'), ('rina', ';k'), ('rina', '§?D#'), ('rina', '§n8#'), ('rina', '§~+'), ('rina', '§y7'), ('rina', '§j^'), ('rina', '§Vr'), ('rina', '§M|')],
    210: [('costume', '^/)'), ('costume', '$EZ'), ('costume', 'sgs'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§Vr'), ('costume', '§M|')],
    211: [('costume', 'w";'), ('costume', '0W='), ('costume', 'Qp?'), ('costume', '§n8#'), ('costume', '§~+'), ('costume', '§y7'), ('costume', '§Vr'), ('costume', '§M|')],
    212: [('costume', '4fS'), ('costume', '?l='), ('costume', 'oq0'), ('costume', '§M|'), ('costume', '§Vr'), ('costume', '§n8#'), ('costume', '§y7'), ('costume', '§~+')],
}

# ---- 가챠 연출 사인 무비 경로 (UR 전용) ----
GACHA_SIGN_MOVIE = {
    1: 'uPV',
    2: '\x04,',
    3: 'q-!',
    4: '*R+',
    5: 'O]=',
    6: 'jGc',
    7: 'Kb@',
    8: '"HW',
    9: 'evO',
    101: '\\P:',
    102: 'CXl',
    103: '0[0',
    104: "'E]",
    105: '6]!',
    106: 'QkE',
    107: '"de',
    108: '}:+',
    109: 'HVF',
    201: '#.u',
    202: '!JJ',
    203: 'ZpL',
    204: '-Nb',
    205: 'jC.',
    206: 'a-[',
    207: 'L\\;',
    208: 'EWP',
    209: '/R9',
    210: 'GM:',
    211: 'XTG',
    212: '?>g',
}

# ---- m_training_tree_card_param: (레어도, 롤)별 (no, type, 셀) 등록 순서 그대로 ----
TRAINING_TREE_PARAMS = {
    ('SR', 1): [('2', '2', 'cell1_stamina'), ('6', '2', 'cell1_stamina'), ('8', '2', 'cell1_stamina'), ('11', '2', 'cell1_stamina'), ('13', '2', 'cell1_stamina'), ('23', '2', 'cell1_stamina'), ('26', '2', 'cell1_stamina'), ('29', '2', 'cell1_stamina'), ('30', '2', 'cell1_stamina'), ('33', '2', 'cell1_stamina'), ('19', '2', 'cell2_stamina'), ('40', '2', 'cell2_stamina'), ('43', '2', 'cell2_stamina'), ('44', '2', 'cell2_stamina'), ('45', '2', 'cell2_stamina'), ('48', '2', 'cell2_stamina'), ('49', '2', 'cell2_stamina'), ('56', '2', 'cell2_stamina'), ('57', '2', 'cell2_stamina'), ('60', '2', 'cell3_stamina'), ('1', '3', 'cell1_appeal'), ('4', '3', 'cell1_appeal'), ('9', '3', 'cell1_appeal'), ('24', '3', 'cell1_appeal'), ('27', '3', 'cell1_appeal'), ('32', '3', 'cell1_appeal'), ('35', '3', 'cell1_appeal'), ('36', '3', 'cell1_appeal'), ('37', '3', 'cell1_appeal'), ('39', '3', 'cell1_appeal'), ('14', '3', 'cell2_appeal'), ('15', '3', 'cell2_appeal'), ('17', '3', 'cell2_appeal'), ('18', '3', 'cell2_appeal'), ('21', '3', 'cell2_appeal'), ('22', '3', 'cell2_appeal'), ('47', '3', 'cell2_appeal'), ('52', '3', 'cell2_appeal'), ('55', '3', 'cell2_appeal'), ('58', '3', 'cell3_appeal'), ('3', '4', 'cell1_technique'), ('5', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('10', '4', 'cell1_technique'), ('12', '4', 'cell1_technique'), ('25', '4', 'cell1_technique'), ('28', '4', 'cell1_technique'), ('31', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('38', '4', 'cell1_technique'), ('16', '4', 'cell2_technique'), ('20', '4', 'cell2_technique'), ('41', '4', 'cell2_technique'), ('42', '4', 'cell2_technique'), ('46', '4', 'cell2_technique'), ('50', '4', 'cell2_technique'), ('51', '4', 'cell2_technique'), ('53', '4', 'cell2_technique'), ('54', '4', 'cell2_technique'), ('59', '4', 'cell3_technique')],
    ('SR', 2): [('3', '2', 'cell1_stamina'), ('5', '2', 'cell1_stamina'), ('7', '2', 'cell1_stamina'), ('10', '2', 'cell1_stamina'), ('12', '2', 'cell1_stamina'), ('25', '2', 'cell1_stamina'), ('28', '2', 'cell1_stamina'), ('31', '2', 'cell1_stamina'), ('34', '2', 'cell1_stamina'), ('38', '2', 'cell1_stamina'), ('16', '2', 'cell2_stamina'), ('20', '2', 'cell2_stamina'), ('41', '2', 'cell2_stamina'), ('42', '2', 'cell2_stamina'), ('46', '2', 'cell2_stamina'), ('50', '2', 'cell2_stamina'), ('51', '2', 'cell2_stamina'), ('53', '2', 'cell2_stamina'), ('54', '2', 'cell2_stamina'), ('59', '2', 'cell3_stamina'), ('2', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('11', '3', 'cell1_appeal'), ('13', '3', 'cell1_appeal'), ('23', '3', 'cell1_appeal'), ('26', '3', 'cell1_appeal'), ('29', '3', 'cell1_appeal'), ('30', '3', 'cell1_appeal'), ('33', '3', 'cell1_appeal'), ('19', '3', 'cell2_appeal'), ('40', '3', 'cell2_appeal'), ('43', '3', 'cell2_appeal'), ('44', '3', 'cell2_appeal'), ('45', '3', 'cell2_appeal'), ('48', '3', 'cell2_appeal'), ('49', '3', 'cell2_appeal'), ('56', '3', 'cell2_appeal'), ('57', '3', 'cell2_appeal'), ('60', '3', 'cell3_appeal'), ('1', '4', 'cell1_technique'), ('4', '4', 'cell1_technique'), ('9', '4', 'cell1_technique'), ('24', '4', 'cell1_technique'), ('27', '4', 'cell1_technique'), ('32', '4', 'cell1_technique'), ('35', '4', 'cell1_technique'), ('36', '4', 'cell1_technique'), ('37', '4', 'cell1_technique'), ('39', '4', 'cell1_technique'), ('14', '4', 'cell2_technique'), ('15', '4', 'cell2_technique'), ('17', '4', 'cell2_technique'), ('18', '4', 'cell2_technique'), ('21', '4', 'cell2_technique'), ('22', '4', 'cell2_technique'), ('47', '4', 'cell2_technique'), ('52', '4', 'cell2_technique'), ('55', '4', 'cell2_technique'), ('58', '4', 'cell3_technique')],
    ('SR', 3): [('1', '2', 'cell1_stamina'), ('4', '2', 'cell1_stamina'), ('9', '2', 'cell1_stamina'), ('24', '2', 'cell1_stamina'), ('27', '2', 'cell1_stamina'), ('32', '2', 'cell1_stamina'), ('35', '2', 'cell1_stamina'), ('36', '2', 'cell1_stamina'), ('37', '2', 'cell1_stamina'), ('39', '2', 'cell1_stamina'), ('14', '2', 'cell2_stamina'), ('15', '2', 'cell2_stamina'), ('17', '2', 'cell2_stamina'), ('18', '2', 'cell2_stamina'), ('21', '2', 'cell2_stamina'), ('22', '2', 'cell2_stamina'), ('47', '2', 'cell2_stamina'), ('52', '2', 'cell2_stamina'), ('55', '2', 'cell2_stamina'), ('58', '2', 'cell3_stamina'), ('3', '3', 'cell1_appeal'), ('5', '3', 'cell1_appeal'), ('7', '3', 'cell1_appeal'), ('10', '3', 'cell1_appeal'), ('12', '3', 'cell1_appeal'), ('25', '3', 'cell1_appeal'), ('28', '3', 'cell1_appeal'), ('31', '3', 'cell1_appeal'), ('34', '3', 'cell1_appeal'), ('38', '3', 'cell1_appeal'), ('16', '3', 'cell2_appeal'), ('20', '3', 'cell2_appeal'), ('41', '3', 'cell2_appeal'), ('42', '3', 'cell2_appeal'), ('46', '3', 'cell2_appeal'), ('50', '3', 'cell2_appeal'), ('51', '3', 'cell2_appeal'), ('53', '3', 'cell2_appeal'), ('54', '3', 'cell2_appeal'), ('59', '3', 'cell3_appeal'), ('2', '4', 'cell1_technique'), ('6', '4', 'cell1_technique'), ('8', '4', 'cell1_technique'), ('11', '4', 'cell1_technique'), ('13', '4', 'cell1_technique'), ('23', '4', 'cell1_technique'), ('26', '4', 'cell1_technique'), ('29', '4', 'cell1_technique'), ('30', '4', 'cell1_technique'), ('33', '4', 'cell1_technique'), ('19', '4', 'cell2_technique'), ('40', '4', 'cell2_technique'), ('43', '4', 'cell2_technique'), ('44', '4', 'cell2_technique'), ('45', '4', 'cell2_technique'), ('48', '4', 'cell2_technique'), ('49', '4', 'cell2_technique'), ('56', '4', 'cell2_technique'), ('57', '4', 'cell2_technique'), ('60', '4', 'cell3_technique')],
    ('SR', 4): [('1', '2', 'cell1_stamina'), ('4', '2', 'cell1_stamina'), ('9', '2', 'cell1_stamina'), ('24', '2', 'cell1_stamina'), ('27', '2', 'cell1_stamina'), ('32', '2', 'cell1_stamina'), ('35', '2', 'cell1_stamina'), ('36', '2', 'cell1_stamina'), ('37', '2', 'cell1_stamina'), ('39', '2', 'cell1_stamina'), ('14', '2', 'cell2_stamina'), ('15', '2', 'cell2_stamina'), ('17', '2', 'cell2_stamina'), ('18', '2', 'cell2_stamina'), ('21', '2', 'cell2_stamina'), ('22', '2', 'cell2_stamina'), ('47', '2', 'cell2_stamina'), ('52', '2', 'cell2_stamina'), ('55', '2', 'cell2_stamina'), ('58', '2', 'cell3_stamina'), ('2', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('11', '3', 'cell1_appeal'), ('13', '3', 'cell1_appeal'), ('23', '3', 'cell1_appeal'), ('26', '3', 'cell1_appeal'), ('29', '3', 'cell1_appeal'), ('30', '3', 'cell1_appeal'), ('33', '3', 'cell1_appeal'), ('19', '3', 'cell2_appeal'), ('40', '3', 'cell2_appeal'), ('43', '3', 'cell2_appeal'), ('44', '3', 'cell2_appeal'), ('45', '3', 'cell2_appeal'), ('48', '3', 'cell2_appeal'), ('49', '3', 'cell2_appeal'), ('56', '3', 'cell2_appeal'), ('57', '3', 'cell2_appeal'), ('60', '3', 'cell3_appeal'), ('3', '4', 'cell1_technique'), ('5', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('10', '4', 'cell1_technique'), ('12', '4', 'cell1_technique'), ('25', '4', 'cell1_technique'), ('28', '4', 'cell1_technique'), ('31', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('38', '4', 'cell1_technique'), ('16', '4', 'cell2_technique'), ('20', '4', 'cell2_technique'), ('41', '4', 'cell2_technique'), ('42', '4', 'cell2_technique'), ('46', '4', 'cell2_technique'), ('50', '4', 'cell2_technique'), ('51', '4', 'cell2_technique'), ('53', '4', 'cell2_technique'), ('54', '4', 'cell2_technique'), ('59', '4', 'cell3_technique')],
    ('UR', 1): [('2', '2', 'cell1_stamina'), ('6', '2', 'cell1_stamina'), ('8', '2', 'cell1_stamina'), ('12', '2', 'cell1_stamina'), ('28', '2', 'cell1_stamina'), ('30', '2', 'cell1_stamina'), ('32', '2', 'cell1_stamina'), ('35', '2', 'cell1_stamina'), ('39', '2', 'cell1_stamina'), ('41', '2', 'cell1_stamina'), ('43', '2', 'cell1_stamina'), ('46', '2', 'cell1_stamina'), ('21', '2', 'cell2_stamina'), ('23', '2', 'cell2_stamina'), ('25', '2', 'cell2_stamina'), ('48', '2', 'cell2_stamina'), ('52', '2', 'cell2_stamina'), ('53', '2', 'cell2_stamina'), ('54', '2', 'cell2_stamina'), ('57', '2', 'cell2_stamina'), ('59', '2', 'cell2_stamina'), ('60', '2', 'cell2_stamina'), ('67', '2', 'cell2_stamina'), ('70', '2', 'cell3_stamina'), ('1', '3', 'cell1_appeal'), ('5', '3', 'cell1_appeal'), ('9', '3', 'cell1_appeal'), ('11', '3', 'cell1_appeal'), ('13', '3', 'cell1_appeal'), ('14', '3', 'cell1_appeal'), ('29', '3', 'cell1_appeal'), ('31', '3', 'cell1_appeal'), ('33', '3', 'cell1_appeal'), ('36', '3', 'cell1_appeal'), ('38', '3', 'cell1_appeal'), ('45', '3', 'cell1_appeal'), ('16', '3', 'cell2_appeal'), ('17', '3', 'cell2_appeal'), ('18', '3', 'cell2_appeal'), ('19', '3', 'cell2_appeal'), ('20', '3', 'cell2_appeal'), ('58', '3', 'cell2_appeal'), ('61', '3', 'cell2_appeal'), ('62', '3', 'cell2_appeal'), ('65', '3', 'cell2_appeal'), ('69', '3', 'cell2_appeal'), ('71', '3', 'cell2_appeal'), ('72', '3', 'cell3_appeal'), ('3', '4', 'cell1_technique'), ('4', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('10', '4', 'cell1_technique'), ('15', '4', 'cell1_technique'), ('27', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('37', '4', 'cell1_technique'), ('40', '4', 'cell1_technique'), ('42', '4', 'cell1_technique'), ('44', '4', 'cell1_technique'), ('47', '4', 'cell1_technique'), ('22', '4', 'cell2_technique'), ('24', '4', 'cell2_technique'), ('26', '4', 'cell2_technique'), ('49', '4', 'cell2_technique'), ('50', '4', 'cell2_technique'), ('51', '4', 'cell2_technique'), ('55', '4', 'cell2_technique'), ('56', '4', 'cell2_technique'), ('63', '4', 'cell2_technique'), ('64', '4', 'cell2_technique'), ('66', '4', 'cell2_technique'), ('68', '4', 'cell3_technique')],
    ('UR', 2): [('3', '2', 'cell1_stamina'), ('4', '2', 'cell1_stamina'), ('7', '2', 'cell1_stamina'), ('10', '2', 'cell1_stamina'), ('15', '2', 'cell1_stamina'), ('27', '2', 'cell1_stamina'), ('34', '2', 'cell1_stamina'), ('37', '2', 'cell1_stamina'), ('40', '2', 'cell1_stamina'), ('42', '2', 'cell1_stamina'), ('44', '2', 'cell1_stamina'), ('47', '2', 'cell1_stamina'), ('22', '2', 'cell2_stamina'), ('24', '2', 'cell2_stamina'), ('26', '2', 'cell2_stamina'), ('49', '2', 'cell2_stamina'), ('50', '2', 'cell2_stamina'), ('51', '2', 'cell2_stamina'), ('55', '2', 'cell2_stamina'), ('56', '2', 'cell2_stamina'), ('63', '2', 'cell2_stamina'), ('64', '2', 'cell2_stamina'), ('66', '2', 'cell2_stamina'), ('68', '2', 'cell3_stamina'), ('2', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('12', '3', 'cell1_appeal'), ('28', '3', 'cell1_appeal'), ('30', '3', 'cell1_appeal'), ('32', '3', 'cell1_appeal'), ('35', '3', 'cell1_appeal'), ('39', '3', 'cell1_appeal'), ('41', '3', 'cell1_appeal'), ('43', '3', 'cell1_appeal'), ('46', '3', 'cell1_appeal'), ('21', '3', 'cell2_appeal'), ('23', '3', 'cell2_appeal'), ('25', '3', 'cell2_appeal'), ('48', '3', 'cell2_appeal'), ('52', '3', 'cell2_appeal'), ('53', '3', 'cell2_appeal'), ('54', '3', 'cell2_appeal'), ('57', '3', 'cell2_appeal'), ('59', '3', 'cell2_appeal'), ('60', '3', 'cell2_appeal'), ('67', '3', 'cell2_appeal'), ('70', '3', 'cell3_appeal'), ('1', '4', 'cell1_technique'), ('5', '4', 'cell1_technique'), ('9', '4', 'cell1_technique'), ('11', '4', 'cell1_technique'), ('13', '4', 'cell1_technique'), ('14', '4', 'cell1_technique'), ('29', '4', 'cell1_technique'), ('31', '4', 'cell1_technique'), ('33', '4', 'cell1_technique'), ('36', '4', 'cell1_technique'), ('38', '4', 'cell1_technique'), ('45', '4', 'cell1_technique'), ('16', '4', 'cell2_technique'), ('17', '4', 'cell2_technique'), ('18', '4', 'cell2_technique'), ('19', '4', 'cell2_technique'), ('20', '4', 'cell2_technique'), ('58', '4', 'cell2_technique'), ('61', '4', 'cell2_technique'), ('62', '4', 'cell2_technique'), ('65', '4', 'cell2_technique'), ('69', '4', 'cell2_technique'), ('71', '4', 'cell2_technique'), ('72', '4', 'cell3_technique')],
    ('UR', 3): [('1', '2', 'cell1_stamina'), ('5', '2', 'cell1_stamina'), ('9', '2', 'cell1_stamina'), ('11', '2', 'cell1_stamina'), ('13', '2', 'cell1_stamina'), ('14', '2', 'cell1_stamina'), ('29', '2', 'cell1_stamina'), ('31', '2', 'cell1_stamina'), ('33', '2', 'cell1_stamina'), ('36', '2', 'cell1_stamina'), ('38', '2', 'cell1_stamina'), ('45', '2', 'cell1_stamina'), ('16', '2', 'cell2_stamina'), ('17', '2', 'cell2_stamina'), ('18', '2', 'cell2_stamina'), ('19', '2', 'cell2_stamina'), ('20', '2', 'cell2_stamina'), ('58', '2', 'cell2_stamina'), ('61', '2', 'cell2_stamina'), ('62', '2', 'cell2_stamina'), ('65', '2', 'cell2_stamina'), ('69', '2', 'cell2_stamina'), ('71', '2', 'cell2_stamina'), ('72', '2', 'cell3_stamina'), ('3', '3', 'cell1_appeal'), ('4', '3', 'cell1_appeal'), ('7', '3', 'cell1_appeal'), ('10', '3', 'cell1_appeal'), ('15', '3', 'cell1_appeal'), ('27', '3', 'cell1_appeal'), ('34', '3', 'cell1_appeal'), ('37', '3', 'cell1_appeal'), ('40', '3', 'cell1_appeal'), ('42', '3', 'cell1_appeal'), ('44', '3', 'cell1_appeal'), ('47', '3', 'cell1_appeal'), ('22', '3', 'cell2_appeal'), ('24', '3', 'cell2_appeal'), ('26', '3', 'cell2_appeal'), ('49', '3', 'cell2_appeal'), ('50', '3', 'cell2_appeal'), ('51', '3', 'cell2_appeal'), ('55', '3', 'cell2_appeal'), ('56', '3', 'cell2_appeal'), ('63', '3', 'cell2_appeal'), ('64', '3', 'cell2_appeal'), ('66', '3', 'cell2_appeal'), ('68', '3', 'cell3_appeal'), ('2', '4', 'cell1_technique'), ('6', '4', 'cell1_technique'), ('8', '4', 'cell1_technique'), ('12', '4', 'cell1_technique'), ('28', '4', 'cell1_technique'), ('30', '4', 'cell1_technique'), ('32', '4', 'cell1_technique'), ('35', '4', 'cell1_technique'), ('39', '4', 'cell1_technique'), ('41', '4', 'cell1_technique'), ('43', '4', 'cell1_technique'), ('46', '4', 'cell1_technique'), ('21', '4', 'cell2_technique'), ('23', '4', 'cell2_technique'), ('25', '4', 'cell2_technique'), ('48', '4', 'cell2_technique'), ('52', '4', 'cell2_technique'), ('53', '4', 'cell2_technique'), ('54', '4', 'cell2_technique'), ('57', '4', 'cell2_technique'), ('59', '4', 'cell2_technique'), ('60', '4', 'cell2_technique'), ('67', '4', 'cell2_technique'), ('70', '4', 'cell3_technique')],
    ('UR', 4): [('1', '2', 'cell1_stamina'), ('5', '2', 'cell1_stamina'), ('9', '2', 'cell1_stamina'), ('11', '2', 'cell1_stamina'), ('13', '2', 'cell1_stamina'), ('14', '2', 'cell1_stamina'), ('29', '2', 'cell1_stamina'), ('31', '2', 'cell1_stamina'), ('33', '2', 'cell1_stamina'), ('36', '2', 'cell1_stamina'), ('38', '2', 'cell1_stamina'), ('45', '2', 'cell1_stamina'), ('16', '2', 'cell2_stamina'), ('17', '2', 'cell2_stamina'), ('18', '2', 'cell2_stamina'), ('19', '2', 'cell2_stamina'), ('20', '2', 'cell2_stamina'), ('58', '2', 'cell2_stamina'), ('61', '2', 'cell2_stamina'), ('62', '2', 'cell2_stamina'), ('65', '2', 'cell2_stamina'), ('69', '2', 'cell2_stamina'), ('71', '2', 'cell2_stamina'), ('72', '2', 'cell3_stamina'), ('2', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('12', '3', 'cell1_appeal'), ('28', '3', 'cell1_appeal'), ('30', '3', 'cell1_appeal'), ('32', '3', 'cell1_appeal'), ('35', '3', 'cell1_appeal'), ('39', '3', 'cell1_appeal'), ('41', '3', 'cell1_appeal'), ('43', '3', 'cell1_appeal'), ('46', '3', 'cell1_appeal'), ('21', '3', 'cell2_appeal'), ('23', '3', 'cell2_appeal'), ('25', '3', 'cell2_appeal'), ('48', '3', 'cell2_appeal'), ('52', '3', 'cell2_appeal'), ('53', '3', 'cell2_appeal'), ('54', '3', 'cell2_appeal'), ('57', '3', 'cell2_appeal'), ('59', '3', 'cell2_appeal'), ('60', '3', 'cell2_appeal'), ('67', '3', 'cell2_appeal'), ('70', '3', 'cell3_appeal'), ('3', '4', 'cell1_technique'), ('4', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('10', '4', 'cell1_technique'), ('15', '4', 'cell1_technique'), ('27', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('37', '4', 'cell1_technique'), ('40', '4', 'cell1_technique'), ('42', '4', 'cell1_technique'), ('44', '4', 'cell1_technique'), ('47', '4', 'cell1_technique'), ('22', '4', 'cell2_technique'), ('24', '4', 'cell2_technique'), ('26', '4', 'cell2_technique'), ('49', '4', 'cell2_technique'), ('50', '4', 'cell2_technique'), ('51', '4', 'cell2_technique'), ('55', '4', 'cell2_technique'), ('56', '4', 'cell2_technique'), ('63', '4', 'cell2_technique'), ('64', '4', 'cell2_technique'), ('66', '4', 'cell2_technique'), ('68', '4', 'cell3_technique')],
    ('FES', 1): [('2', '2', 'cell1_stamina'), ('6', '2', 'cell1_stamina'), ('8', '2', 'cell1_stamina'), ('12', '2', 'cell1_stamina'), ('28', '2', 'cell1_stamina'), ('30', '2', 'cell1_stamina'), ('32', '2', 'cell1_stamina'), ('35', '2', 'cell1_stamina'), ('39', '2', 'cell1_stamina'), ('41', '2', 'cell1_stamina'), ('43', '2', 'cell1_stamina'), ('46', '2', 'cell1_stamina'), ('21', '2', 'cell2_stamina'), ('23', '2', 'cell2_stamina'), ('25', '2', 'cell2_stamina'), ('48', '2', 'cell2_stamina'), ('52', '2', 'cell2_stamina'), ('53', '2', 'cell2_stamina'), ('54', '2', 'cell2_stamina'), ('57', '2', 'cell2_stamina'), ('59', '2', 'cell2_stamina'), ('60', '2', 'cell2_stamina'), ('67', '2', 'cell2_stamina'), ('70', '2', 'cell3_stamina'), ('1', '3', 'cell1_appeal'), ('5', '3', 'cell1_appeal'), ('9', '3', 'cell1_appeal'), ('11', '3', 'cell1_appeal'), ('13', '3', 'cell1_appeal'), ('14', '3', 'cell1_appeal'), ('29', '3', 'cell1_appeal'), ('31', '3', 'cell1_appeal'), ('33', '3', 'cell1_appeal'), ('36', '3', 'cell1_appeal'), ('38', '3', 'cell1_appeal'), ('45', '3', 'cell1_appeal'), ('16', '3', 'cell2_appeal'), ('17', '3', 'cell2_appeal'), ('18', '3', 'cell2_appeal'), ('19', '3', 'cell2_appeal'), ('20', '3', 'cell2_appeal'), ('58', '3', 'cell2_appeal'), ('61', '3', 'cell2_appeal'), ('62', '3', 'cell2_appeal'), ('65', '3', 'cell2_appeal'), ('69', '3', 'cell2_appeal'), ('71', '3', 'cell2_appeal'), ('72', '3', 'cell3_appeal'), ('3', '4', 'cell1_technique'), ('4', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('10', '4', 'cell1_technique'), ('15', '4', 'cell1_technique'), ('27', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('37', '4', 'cell1_technique'), ('40', '4', 'cell1_technique'), ('42', '4', 'cell1_technique'), ('44', '4', 'cell1_technique'), ('47', '4', 'cell1_technique'), ('22', '4', 'cell2_technique'), ('24', '4', 'cell2_technique'), ('26', '4', 'cell2_technique'), ('49', '4', 'cell2_technique'), ('50', '4', 'cell2_technique'), ('51', '4', 'cell2_technique'), ('55', '4', 'cell2_technique'), ('56', '4', 'cell2_technique'), ('63', '4', 'cell2_technique'), ('64', '4', 'cell2_technique'), ('66', '4', 'cell2_technique'), ('68', '4', 'cell3_technique')],
    ('FES', 2): [('3', '2', 'cell1_stamina'), ('4', '2', 'cell1_stamina'), ('7', '2', 'cell1_stamina'), ('10', '2', 'cell1_stamina'), ('15', '2', 'cell1_stamina'), ('27', '2', 'cell1_stamina'), ('34', '2', 'cell1_stamina'), ('37', '2', 'cell1_stamina'), ('40', '2', 'cell1_stamina'), ('42', '2', 'cell1_stamina'), ('44', '2', 'cell1_stamina'), ('47', '2', 'cell1_stamina'), ('22', '2', 'cell2_stamina'), ('24', '2', 'cell2_stamina'), ('26', '2', 'cell2_stamina'), ('49', '2', 'cell2_stamina'), ('50', '2', 'cell2_stamina'), ('51', '2', 'cell2_stamina'), ('55', '2', 'cell2_stamina'), ('56', '2', 'cell2_stamina'), ('63', '2', 'cell2_stamina'), ('64', '2', 'cell2_stamina'), ('66', '2', 'cell2_stamina'), ('68', '2', 'cell3_stamina'), ('2', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('12', '3', 'cell1_appeal'), ('28', '3', 'cell1_appeal'), ('30', '3', 'cell1_appeal'), ('32', '3', 'cell1_appeal'), ('35', '3', 'cell1_appeal'), ('39', '3', 'cell1_appeal'), ('41', '3', 'cell1_appeal'), ('43', '3', 'cell1_appeal'), ('46', '3', 'cell1_appeal'), ('21', '3', 'cell2_appeal'), ('23', '3', 'cell2_appeal'), ('25', '3', 'cell2_appeal'), ('48', '3', 'cell2_appeal'), ('52', '3', 'cell2_appeal'), ('53', '3', 'cell2_appeal'), ('54', '3', 'cell2_appeal'), ('57', '3', 'cell2_appeal'), ('59', '3', 'cell2_appeal'), ('60', '3', 'cell2_appeal'), ('67', '3', 'cell2_appeal'), ('70', '3', 'cell3_appeal'), ('1', '4', 'cell1_technique'), ('5', '4', 'cell1_technique'), ('9', '4', 'cell1_technique'), ('11', '4', 'cell1_technique'), ('13', '4', 'cell1_technique'), ('14', '4', 'cell1_technique'), ('29', '4', 'cell1_technique'), ('31', '4', 'cell1_technique'), ('33', '4', 'cell1_technique'), ('36', '4', 'cell1_technique'), ('38', '4', 'cell1_technique'), ('45', '4', 'cell1_technique'), ('16', '4', 'cell2_technique'), ('17', '4', 'cell2_technique'), ('18', '4', 'cell2_technique'), ('19', '4', 'cell2_technique'), ('20', '4', 'cell2_technique'), ('58', '4', 'cell2_technique'), ('61', '4', 'cell2_technique'), ('62', '4', 'cell2_technique'), ('65', '4', 'cell2_technique'), ('69', '4', 'cell2_technique'), ('71', '4', 'cell2_technique'), ('72', '4', 'cell3_technique')],
    ('FES', 3): [],
    ('FES', 4): [],
    ('PARTY', 1): [('2', '2', 'cell1_stamina'), ('4', '2', 'cell1_stamina'), ('11', '2', 'cell1_stamina'), ('13', '2', 'cell1_stamina'), ('30', '2', 'cell1_stamina'), ('31', '2', 'cell1_stamina'), ('32', '2', 'cell1_stamina'), ('33', '2', 'cell1_stamina'), ('34', '2', 'cell1_stamina'), ('53', '2', 'cell1_stamina'), ('54', '2', 'cell1_stamina'), ('55', '2', 'cell1_stamina'), ('56', '2', 'cell1_stamina'), ('57', '2', 'cell1_stamina'), ('58', '2', 'cell1_stamina'), ('59', '2', 'cell1_stamina'), ('60', '2', 'cell1_stamina'), ('61', '2', 'cell1_stamina'), ('19', '2', 'cell2_stamina'), ('23', '2', 'cell2_stamina'), ('24', '2', 'cell2_stamina'), ('64', '2', 'cell2_stamina'), ('65', '2', 'cell2_stamina'), ('25', '2', 'cell3_stamina'), ('1', '3', 'cell1_appeal'), ('3', '3', 'cell1_appeal'), ('6', '3', 'cell1_appeal'), ('8', '3', 'cell1_appeal'), ('10', '3', 'cell1_appeal'), ('12', '3', 'cell1_appeal'), ('14', '3', 'cell1_appeal'), ('15', '3', 'cell1_appeal'), ('17', '3', 'cell1_appeal'), ('26', '3', 'cell1_appeal'), ('27', '3', 'cell1_appeal'), ('28', '3', 'cell1_appeal'), ('29', '3', 'cell1_appeal'), ('48', '3', 'cell1_appeal'), ('49', '3', 'cell1_appeal'), ('50', '3', 'cell1_appeal'), ('51', '3', 'cell1_appeal'), ('52', '3', 'cell1_appeal'), ('20', '3', 'cell2_appeal'), ('22', '3', 'cell2_appeal'), ('63', '3', 'cell2_appeal'), ('67', '3', 'cell2_appeal'), ('69', '3', 'cell2_appeal'), ('70', '3', 'cell3_appeal'), ('5', '4', 'cell1_technique'), ('7', '4', 'cell1_technique'), ('9', '4', 'cell1_technique'), ('16', '4', 'cell1_technique'), ('18', '4', 'cell1_technique'), ('35', '4', 'cell1_technique'), ('36', '4', 'cell1_technique'), ('37', '4', 'cell1_technique'), ('38', '4', 'cell1_technique'), ('39', '4', 'cell1_technique'), ('40', '4', 'cell1_technique'), ('41', '4', 'cell1_technique'), ('42', '4', 'cell1_technique'), ('43', '4', 'cell1_technique'), ('44', '4', 'cell1_technique'), ('45', '4', 'cell1_technique'), ('46', '4', 'cell1_technique'), ('47', '4', 'cell1_technique'), ('21', '4', 'cell2_technique'), ('62', '4', 'cell2_technique'), ('66', '4', 'cell2_technique'), ('68', '4', 'cell2_technique'), ('71', '4', 'cell2_technique'), ('72', '4', 'cell3_technique')],
    ('PARTY', 2): [],
    ('PARTY', 3): [('63', '2', 'cell2_stamina'), ('67', '2', 'cell2_stamina'), ('69', '2', 'cell2_stamina'), ('70', '2', 'cell3_stamina'), ('15', '2', 'cell1_stamina'), ('17', '2', 'cell1_stamina'), ('20', '2', 'cell2_stamina'), ('22', '2', 'cell2_stamina'), ('10', '2', 'cell1_stamina'), ('12', '2', 'cell1_stamina'), ('14', '2', 'cell1_stamina'), ('48', '2', 'cell1_stamina'), ('49', '2', 'cell1_stamina'), ('50', '2', 'cell1_stamina'), ('51', '2', 'cell1_stamina'), ('52', '2', 'cell1_stamina'), ('6', '2', 'cell1_stamina'), ('8', '2', 'cell1_stamina'), ('26', '2', 'cell1_stamina'), ('27', '2', 'cell1_stamina'), ('28', '2', 'cell1_stamina'), ('29', '2', 'cell1_stamina'), ('1', '2', 'cell1_stamina'), ('3', '2', 'cell1_stamina'), ('40', '3', 'cell1_appeal'), ('41', '3', 'cell1_appeal'), ('42', '3', 'cell1_appeal'), ('43', '3', 'cell1_appeal'), ('62', '3', 'cell2_appeal'), ('66', '3', 'cell2_appeal'), ('68', '3', 'cell2_appeal'), ('71', '3', 'cell2_appeal'), ('72', '3', 'cell3_appeal'), ('16', '3', 'cell1_appeal'), ('18', '3', 'cell1_appeal'), ('21', '3', 'cell2_appeal'), ('35', '3', 'cell1_appeal'), ('36', '3', 'cell1_appeal'), ('37', '3', 'cell1_appeal'), ('38', '3', 'cell1_appeal'), ('39', '3', 'cell1_appeal'), ('5', '3', 'cell1_appeal'), ('7', '3', 'cell1_appeal'), ('9', '3', 'cell1_appeal'), ('44', '3', 'cell1_appeal'), ('45', '3', 'cell1_appeal'), ('46', '3', 'cell1_appeal'), ('47', '3', 'cell1_appeal'), ('24', '4', 'cell2_technique'), ('25', '4', 'cell3_technique'), ('58', '4', 'cell1_technique'), ('59', '4', 'cell1_technique'), ('60', '4', 'cell1_technique'), ('61', '4', 'cell1_technique'), ('64', '4', 'cell2_technique'), ('65', '4', 'cell2_technique'), ('19', '4', 'cell2_technique'), ('23', '4', 'cell2_technique'), ('53', '4', 'cell1_technique'), ('54', '4', 'cell1_technique'), ('55', '4', 'cell1_technique'), ('56', '4', 'cell1_technique'), ('57', '4', 'cell1_technique'), ('11', '4', 'cell1_technique'), ('13', '4', 'cell1_technique'), ('30', '4', 'cell1_technique'), ('31', '4', 'cell1_technique'), ('32', '4', 'cell1_technique'), ('33', '4', 'cell1_technique'), ('34', '4', 'cell1_technique'), ('2', '4', 'cell1_technique'), ('4', '4', 'cell1_technique')],
}

# ============================================================
# 메인 흐름
# ============================================================

# ---- 애드온 설정 기본값 (zip 안의 .txt가 exec로 덮어씀) ----
# init code default value (do nothing)
id_card = None
id_active_skill = None
id_active_skill_ability = None
id_passive_skill = None
card_name_en = ""
card_name_ko = ""
card_name_zh = ""
card_name_ja = ""
card_name_awaken_en = ""
card_name_awaken_ko = ""
card_name_awaken_zh = ""
card_name_awaken_ja = ""
card_name_hiragana_en = ""
card_name_hiragana_ko = ""
card_name_hiragana_zh = ""
card_name_hiragana_ja = ""
card_name_awaken_hiragana_en = ""
card_name_awaken_hiragana_ko = ""
card_name_awaken_hiragana_zh = ""
card_name_awaken_hiragana_ja = ""
card_description = ""
rarity_card = "SR"
attribute_card = 1
role_card = 1
is_gacha1_or_event2_card = 1

# base
active_skill_voice_file = ""
costume_file = ""
costume_thumbnail_file = ""
card_normal_file = ""
card_normal_thumbnail_file = ""
card_normal_still_file = ""
card_normal_deck_file = ""
card_awaken_file = ""
card_awaken_thumbnail_file = ""
card_awaken_still_file = ""
card_awaken_deck_file = ""
chara_id = 1

# stats
card_base_appeal = 0
card_base_stamina = 0
card_base_technique = 0

# trimming
## cut in
card_normal_trimming_live_cutin_offset_x = 0
card_normal_trimming_live_cutin_offset_y = 0
card_normal_trimming_live_cutin_offset_rotation = 0
card_normal_trimming_live_cutin_offset_scale = 100
card_awaken_trimming_live_cutin_offset_x = 0
card_awaken_trimming_live_cutin_offset_y = 0
card_awaken_trimming_live_cutin_offset_rotation = 0
card_awaken_trimming_live_cutin_offset_scale = 100
## profile
card_normal_trimming_profile_offset_x = 0
card_normal_trimming_profile_offset_scale = 100
card_awaken_trimming_profile_offset_x = 0
card_awaken_trimming_profile_offset_scale = 100

# training tree
card_training_tree_awaken_appeal = 0
card_training_tree_awaken_stamina = 0
card_training_tree_awaken_technique = 0
card_training_tree_cell_extra_appeal = 0
card_training_tree_cell_extra_stamina = 0
card_training_tree_cell_extra_technique = 0

# gacha (UR only)
card_gacha_voice_file = ""
card_gacha_serif_en = ""
card_gacha_serif_ko = ""
card_gacha_serif_zh = ""
card_gacha_serif_ja = ""

# Simple skill setup
# Active Skill
active_skill_name_en = ""
active_skill_name_ko = ""
active_skill_name_zh = ""
active_skill_name_ja = ""

## skill
active_skill_target_id1 = 1

## skill effect
active_skill_effect_type = 1
active_skill_effect_finish_type = 255
active_skill_effect_finish_value = 0
active_skill_effect_value = 0
active_skill_effect_value_step_up = 0

# Passive Skill
## skill
passive_skill_target_id1 = 1

## skill effect
passive_skill_effect_type = 9 # 9 - 16
passive_skill_effect_value = 0
passive_skill_effect_value_step_up = 0

# Active Skill Ability
active_skill_ability_condition_id1 = 1
active_skill_ability_trigger_type = 1
active_skill_ability_chance_percent = 0

## skill
active_skill_ability_target_id1 = 1

# skill effect
active_skill_ability_effect_type = 1
active_skill_ability_effect_finish_type = 255
active_skill_ability_effect_finish_value = 0
active_skill_ability_effect_value = 0

# EXPERT ONLY, IF YOU DON'T KNOW HOW TO SETUP SKILL THEN ASK SOMEONE OR LEAVE AS NOTHING
# Active Skill
active_skill_type = 1 # common value
active_skill_chance_percent = None # if none will use based on rarity card

## skill effect
active_skill_effect_target_parameter = 2 # common attack

# Active Skill Ability
## skill effect
active_skill_ability_effect_target_parameter = 2 # common attack

# type card (string): SR / UR / FES / PARTY

# useless (?), used on display show power but it never accurate what so
active_skill_evaluation = 0
active_skill_evaluation_step_even_up = 0
active_skill_evaluation_step_odd_up = 0
active_skill_ability_evaluation = 0
passive_skill_evaluation = 0
passive_skill_evaluation_step_even_up = 0
passive_skill_evaluation_step_odd_up = 0

modding_elichika_path = "assets/package/card/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

encrypted_folder = "static/assets/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

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

# ---- 캐릭터 ID 보정 및 그룹 산출 ----
# Get user inputs
if chara_id == 212:
    chara_id = 211
elif chara_id == 211:
    chara_id = 212

if 1 <= chara_id <= 9:
    chara_id_group = 13
elif 101 <= chara_id <= 109:
    chara_id_group = 14
elif 201 <= chara_id <= 212:
    chara_id_group = 15

# ---- 요약 출력 및 확인 ----
clear_terminal()
print('Name: ' + card_name_en)
if chara_id in CHARA_NAMES:
    print('Chara: ' + CHARA_NAMES[chara_id])

if chara_id_group == 13:
    print('Group: Myuzu')
elif chara_id_group == 14:
    print('Group: Aqours')
elif chara_id_group == 15:
    print('Group: Nijigasaki')
print('Description: ' + card_description)
do_you_think_want_add_this = input("do you want add this? (y/n): ")

if do_you_think_want_add_this == "y":
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

# ---- 파일 경로/이름/크기 산출 및 검증 ----
start_encrypt1 = temp_directory + costume_file
start_encrypt4 = temp_directory + active_skill_voice_file
start_encrypt6 = temp_directory + card_normal_file
start_encrypt7 = temp_directory + card_normal_thumbnail_file
start_encrypt8 = temp_directory + card_normal_still_file
start_encrypt9 = temp_directory + card_normal_deck_file
start_encrypt10 = temp_directory + card_awaken_file
start_encrypt11 = temp_directory + card_awaken_thumbnail_file
start_encrypt12 = temp_directory + card_awaken_still_file
start_encrypt13 = temp_directory + card_awaken_deck_file
start_encrypt2 = temp_directory + costume_thumbnail_file
thumbnail_costume_filename = os.path.splitext(start_encrypt2.split("/")[-1])[0]
thumbnail_costume_size = os.path.getsize(start_encrypt2)
encrypted_thumbnail = "static/assets/" + os.path.splitext(start_encrypt2.split("/")[-1])[0]
if not thumbnail_costume_filename.isalnum() or not thumbnail_costume_filename.islower():
    print('Invalid Thumbnail Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)

# Extract filename and filesize from costume_file
costume_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
costume_filesize = os.path.getsize(start_encrypt1)

# perform check length to avoid auto delete
if not costume_filename.isalnum() or not costume_filename.islower():
    print('Invalid Costume Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)

encrypted_costume = "static/assets/" + os.path.splitext(start_encrypt1.split("/")[-1])[0]

card_filename = os.path.splitext(start_encrypt6.split("/")[-1])[0]
active_skill_voice_filename = os.path.splitext(start_encrypt4.split("/")[-1])[0]
card_thumbnail_filename = os.path.splitext(start_encrypt7.split("/")[-1])[0]
card_still_filename = os.path.splitext(start_encrypt8.split("/")[-1])[0]
card_deck_filename = os.path.splitext(start_encrypt9.split("/")[-1])[0]
card_awaken_filename = os.path.splitext(start_encrypt10.split("/")[-1])[0]
card_awaken_thumbnail_filename = os.path.splitext(start_encrypt11.split("/")[-1])[0]
card_awaken_still_filename = os.path.splitext(start_encrypt12.split("/")[-1])[0]
card_awaken_deck_filename = os.path.splitext(start_encrypt13.split("/")[-1])[0]
card_filesize = os.path.getsize(start_encrypt6)
active_skill_voice_filesize = os.path.getsize(start_encrypt4)
card_thumbnail_filesize = os.path.getsize(start_encrypt7)
card_still_filesize = os.path.getsize(start_encrypt8)
card_deck_filesize = os.path.getsize(start_encrypt9)
card_awaken_filesize = os.path.getsize(start_encrypt10)
card_awaken_thumbnail_filesize = os.path.getsize(start_encrypt11)
card_awaken_still_filesize = os.path.getsize(start_encrypt12)
card_awaken_deck_filesize = os.path.getsize(start_encrypt13)
donot_insert = None

encrypted_card = "static/assets/" + os.path.splitext(start_encrypt6.split("/")[-1])[0]
encrypted_card_thumbnail = "static/assets/" + os.path.splitext(start_encrypt7.split("/")[-1])[0]
encrypted_card_still = "static/assets/" + os.path.splitext(start_encrypt8.split("/")[-1])[0]
encrypted_card_deck = "static/assets/" + os.path.splitext(start_encrypt9.split("/")[-1])[0]
encrypted_card_awaken = "static/assets/" + os.path.splitext(start_encrypt10.split("/")[-1])[0]
encrypted_card_awaken_thumbnail = "static/assets/" + os.path.splitext(start_encrypt11.split("/")[-1])[0]
encrypted_card_awaken_still = "static/assets/" + os.path.splitext(start_encrypt12.split("/")[-1])[0]
encrypted_card_awaken_deck = "static/assets/" + os.path.splitext(start_encrypt13.split("/")[-1])[0]
active_skill_voice_filename_saved = "static/assets/" + os.path.splitext(start_encrypt4.split("/")[-1])[0]
if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
    start_encrypt5 = temp_directory + card_gacha_voice_file
    card_gacha_voice_filesize = os.path.getsize(start_encrypt5)
    card_gacha_voice_filename = os.path.splitext(start_encrypt5.split("/")[-1])[0]
    card_gacha_voice_filename_saved = "static/assets/" + os.path.splitext(start_encrypt5.split("/")[-1])[0]

if chara_id == 209:
    # (원본 그대로: 파일명/크기 산출에 temp 경로가 아닌 설정값을 직접 사용)
    start_encrypt3 = temp_directory + rina_unmask_costume_file
    rina_unmask_costume_filename = os.path.splitext(rina_unmask_costume_file.split("/")[-1])[0]
    rina_unmask_costume_filesize = os.path.getsize(rina_unmask_costume_file)
    encrypted_rina_unmask = "static/assets/" + os.path.splitext(rina_unmask_costume_file.split("/")[-1])[0]

    if not rina_unmask_costume_filename.isalnum() or not rina_unmask_costume_filename.islower():
        print('Invalid Rina Unmasked Costume Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)

# ---- 에셋 암호화 (이미 있으면 건너뜀) ----
encrypt_asset_if_needed(start_encrypt1, encrypted_costume, "costume")
encrypt_asset_if_needed(start_encrypt2, encrypted_thumbnail, "thumbnail")
if chara_id == 209:
    encrypt_asset_if_needed(start_encrypt3, encrypted_rina_unmask, "rina unmask costume")
encrypt_asset_if_needed(start_encrypt6, encrypted_card, "card")
encrypt_asset_if_needed(start_encrypt7, encrypted_card_thumbnail, "card thumbnail")
encrypt_asset_if_needed(start_encrypt8, encrypted_card_still, "card still")
encrypt_asset_if_needed(start_encrypt9, encrypted_card_deck, "card deck")
encrypt_asset_if_needed(start_encrypt10, encrypted_card_awaken, "awaken card")
encrypt_asset_if_needed(start_encrypt11, encrypted_card_awaken_thumbnail, "awaken card thumbnail")
encrypt_asset_if_needed(start_encrypt12, encrypted_card_awaken_still, "awaken card still")
encrypt_asset_if_needed(start_encrypt13, encrypted_card_awaken_deck, "awaken card deck")

print("assets encrypted")
shutil.copy(start_encrypt4, active_skill_voice_filename_saved)

# ---- asset_a_ja: 에셋 팩/텍스처/모델/의존성 등록 ----
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()

    sheet_name_file = read_acb_sheet_name(start_encrypt4)
    costume_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.member_model WHERE asset_path = ?;")
    card_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_thumbnail_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_still_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_deck_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_awaken_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_awaken_thumbnail_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_awaken_still_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    card_awaken_deck_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    thumbnail_costume_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                    (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, active_skill_voice_filename, donot_insert))
    for pack_name_to_insert in (card_filename, active_skill_voice_filename,
                                card_thumbnail_filename, card_still_filename,
                                card_deck_filename, card_awaken_filename,
                                card_awaken_thumbnail_filename, card_awaken_still_filename,
                                card_awaken_deck_filename):
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (pack_name_to_insert,))
    for tex_path, tex_pack, tex_size in (
            (card_path, card_filename, card_filesize),
            (card_deck_path, card_deck_filename, card_deck_filesize),
            (card_thumbnail_path, card_thumbnail_filename, card_thumbnail_filesize),
            (card_still_path, card_still_filename, card_still_filesize),
            (card_awaken_path, card_awaken_filename, card_awaken_filesize),
            (card_awaken_deck_path, card_awaken_deck_filename, card_awaken_deck_filesize),
            (card_awaken_thumbnail_path, card_awaken_thumbnail_filename, card_awaken_thumbnail_filesize),
            (card_awaken_still_path, card_awaken_still_filename, card_awaken_still_filesize)):
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (tex_path, tex_pack, tex_size))

    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        sheet_name_file1 = read_acb_sheet_name(start_encrypt5)
        cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, card_gacha_voice_filename, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_gacha_voice_filename,))
        shutil.copy(start_encrypt5, card_gacha_voice_filename_saved)

    # (light download auto delete fix)
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))

    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))

    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))

    if chara_id == 209:
        rina_unmask_costume_path = generate_unique_hash(cursor, "SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;")
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))

    # 캐릭터별 모델 의존성 등록 (원본 if/elif 1행씩 -> 테이블)
    for dep_kind, dep_value in MEMBER_MODEL_DEPENDENCIES.get(chara_id, []):
        dep_path = rina_unmask_costume_path if dep_kind == 'rina' else costume_path
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (dep_path, dep_value))

# REST CODE TO GL CLIENT & IOS PLATFORM
## need redone

# ---- masterdata: 카드/스킬/트레이닝 트리/스토리/의상 등록 ----
with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
    cursor = conn.cursor()

    # 레어도별 카드 상수
    if rarity_card in RARITY_CARD_CONSTANTS:
        (caddon_rarity, caddon_sp, caddon_exchange_item_id,
         caddon_passive_slot, caddon_passive_slot_max) = RARITY_CARD_CONSTANTS[rarity_card]
    trade_content_into_json = generate_unique_id(
        cursor, "SELECT COUNT(*) FROM main.m_trade_product_content WHERE id = ?;", 20000000000)
    trade_id_into_json = generate_unique_id(
        cursor, "SELECT COUNT(*) FROM main.m_trade_product WHERE id = ?;", 999999999)
    if id_card is None:
        card_id_masterdata = generate_unique_id(
            cursor, "SELECT COUNT(*) FROM main.m_card WHERE id = ?;", 999999999, 100000000)
    else:
        id_card_str = str(id_card)
        id_card_split1 = int(id_card_str[:2])
        id_card_split2 = int(id_card_str[1:])
        if 1 <= chara_id <= 9:
            id_chara_card_id = "00" + str(chara_id)
        else:
            id_chara_card_id = chara_id
        card_id_masterdata = str(id_card_split1) + str(id_chara_card_id) + str(caddon_rarity) + str(id_card_split2)
    min_level_card = 1
    max_level_card = 100

    if active_skill_effect_type in skill_effect_category_calculation_add:
        cactive_skill_calculation_type = 1
    else:
        active_skill_effect_value = int(active_skill_effect_value * 100)
        active_skill_effect_value_step_up = int(active_skill_effect_value_step_up * 100)
        cactive_skill_calculation_type = 2

    if active_skill_ability_effect_type in skill_effect_category_calculation_add:
        cactive_skill_ability_calculation_type = 1
    else:
        active_skill_ability_chance_logic = int(active_skill_ability_chance_percent * 100)
        active_skill_ability_effect_value = int(active_skill_ability_effect_value * 100)
        cactive_skill_ability_calculation_type = 2

    passive_skill_effect_value = int(passive_skill_effect_value * 100)
    passive_skill_effect_value_step_up = int(passive_skill_effect_value_step_up * 100)

    # m_active_skill - 스킬 레벨 1~5 ID
    if id_active_skill is None:
        active_skill_ids = [generate_unique_id(cursor, "SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", 999999999)
                            for _ in range(5)]
    else:
        active_skill_ids = [str(id_active_skill) + f"0{n}" for n in range(1, 6)]
    (active_skill_1_masterdata, active_skill_2_masterdata, active_skill_3_masterdata,
     active_skill_4_masterdata, active_skill_5_masterdata) = active_skill_ids

    active_skill_dictionary_masterdata = "k.active_skill_name_" + str(card_id_masterdata)
    active_skill_descs_masterdata = ["k.active_skill_description_" + str(card_id_masterdata) + f"_{n}" for n in range(1, 6)]
    (active_skill_dictionary_desc1_masterdata, active_skill_dictionary_desc2_masterdata,
     active_skill_dictionary_desc3_masterdata, active_skill_dictionary_desc4_masterdata,
     active_skill_dictionary_desc5_masterdata) = active_skill_descs_masterdata
    active_skill_dictionary = "active_skill_name_" + str(card_id_masterdata)
    active_skill_descs = ["active_skill_description_" + str(card_id_masterdata) + f"_{n}" for n in range(1, 6)]
    (active_skill_dictionary_desc1, active_skill_dictionary_desc2, active_skill_dictionary_desc3,
     active_skill_dictionary_desc4, active_skill_dictionary_desc5) = active_skill_descs
    # todo : match icon same as behavior
    # are these id correct?

    # -- Skill Icon Red Label --
    ## Appeal Buff still no set up / no dual skill icon
    cactive_skill_icon = lookup_skill_icon(active_skill_effect_type, define_slash=True)
    cactive_ability_skill_icon = lookup_skill_icon(active_skill_ability_effect_type, define_slash=False)

    if active_skill_chance_percent is not None:
        zactive_logic = int(active_skill_chance_percent * 100)
        cactive_chance_percent = zactive_logic
    elif rarity_card == "SR":
        cactive_sp_point = 150
        cactive_chance_percent = 3000
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cactive_sp_point = 200
        cactive_chance_percent = 3300

    # auto settings based on skill effect type
    if active_skill_effect_type in skill_effect_category_player:
        active_skill_target_id1 = 58

    if active_skill_effect_type in skill_effect_category_immediate:
        active_skill_effect_finish_type = 3
        active_skill_effect_finish_value = 0
        active_skill_target_id1 = 58
    elif active_skill_effect_type in skill_effect_category_immediate_remove:
        active_skill_effect_finish_type = 3
        active_skill_effect_finish_value = 0
    elif active_skill_effect_type in skill_effect_category_activebasebuff:
        active_skill_effect_finish_type = 1
        active_skill_effect_finish_value = 0

    # active skill ability
    if active_skill_ability_effect_type in skill_effect_category_player:
        active_skill_ability_target_id1 = 58

    if active_skill_ability_effect_type in skill_effect_category_immediate:
        active_skill_ability_effect_finish_type = 3
        active_skill_ability_effect_finish_value = 0
        active_skill_ability_target_id1 = 58
    elif active_skill_ability_effect_type in skill_effect_category_immediate_remove:
        active_skill_ability_effect_finish_type = 3
        active_skill_ability_effect_finish_value = 0
    elif active_skill_ability_effect_type in skill_effect_category_activebasebuff:
        active_skill_ability_effect_finish_type = 1
        active_skill_ability_effect_finish_value = 0

    for skill_id in active_skill_ids:
        cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (skill_id, active_skill_type, skill_id, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    ## dual skill not supported yet
    # 평가치: 짝수/홀수 증가분을 번갈아 누적 (원본 덧셈 순서 보존)
    active_skill_evaluations = [active_skill_evaluation]
    for step in (active_skill_evaluation_step_even_up, active_skill_evaluation_step_odd_up,
                 active_skill_evaluation_step_even_up, active_skill_evaluation_step_odd_up):
        active_skill_evaluations.append(active_skill_evaluations[-1] + step)
    for skill_id, evaluation in zip(active_skill_ids, active_skill_evaluations):
        cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (skill_id, evaluation, active_skill_target_id1, donot_insert, skill_id, donot_insert))
    # 효과값: 레벨당 step_up 누적 (원본 덧셈 순서 보존)
    cactive_skill_logic_effect2 = active_skill_effect_value + active_skill_effect_value_step_up
    cactive_skill_logic_effect3 = cactive_skill_logic_effect2 + active_skill_effect_value_step_up
    cactive_skill_logic_effect4 = cactive_skill_logic_effect3 + active_skill_effect_value_step_up
    cactive_skill_logic_effect5 = cactive_skill_logic_effect4 + active_skill_effect_value_step_up
    active_skill_effect_values = [active_skill_effect_value, cactive_skill_logic_effect2,
                                  cactive_skill_logic_effect3, cactive_skill_logic_effect4,
                                  cactive_skill_logic_effect5]
    for skill_id, effect_value in zip(active_skill_ids, active_skill_effect_values):
        cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (skill_id, active_skill_effect_target_parameter, active_skill_effect_type, effect_value, cactive_skill_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))

    # m_passive_skill
    if id_passive_skill is None:
        passive_skill_ids = [generate_unique_id(cursor, "SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", 999999999)
                             for _ in range(5)]
    else:
        passive_skill_ids = [str(id_passive_skill) + f"0{n}" for n in range(1, 6)]
    (passive_skill_1_masterdata, passive_skill_2_masterdata, passive_skill_3_masterdata,
     passive_skill_4_masterdata, passive_skill_5_masterdata) = passive_skill_ids
    if id_active_skill_ability is None:
        passive_skill_ab1_masterdata = generate_unique_id(cursor, "SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", 999999999)
    else:
        passive_skill_ab1_masterdata = str(id_active_skill_ability) + "01"
    passive_skill_dictionary_masterdata_1 = "k.passive_skill_name_" + str(passive_skill_1_masterdata)
    passive_skill_dictionary_masterdata_2 = "k.passive_skill_name_" + str(passive_skill_2_masterdata)
    passive_skill_dictionary_masterdata_3 = "k.passive_skill_name_" + str(passive_skill_3_masterdata)
    passive_skill_dictionary_masterdata_4 = "k.passive_skill_name_" + str(passive_skill_4_masterdata)
    passive_skill_dictionary_masterdata_5 = "k.passive_skill_name_" + str(passive_skill_5_masterdata)
    passive_skill_dictionary_masterdata_ab1 = "k.passive_skill_name_" + str(passive_skill_ab1_masterdata)
    passive_skill_dictionary_desc1_masterdata = "k.passive_skill_description_" + str(passive_skill_1_masterdata)
    passive_skill_dictionary_desc2_masterdata = "k.passive_skill_description_" + str(passive_skill_2_masterdata)
    passive_skill_dictionary_desc3_masterdata = "k.passive_skill_description_" + str(passive_skill_3_masterdata)
    passive_skill_dictionary_desc4_masterdata = "k.passive_skill_description_" + str(passive_skill_4_masterdata)
    passive_skill_dictionary_desc5_masterdata = "k.passive_skill_description_" + str(passive_skill_5_masterdata)
    passive_skill_dictionary_desc1ab_masterdata = "k.passive_skill_description_" + str(passive_skill_ab1_masterdata)
    # same name for each id (expect ability)?
    passive_skill_dictionary_1 = "passive_skill_name_" + str(passive_skill_1_masterdata)
    passive_skill_dictionary_2 = "passive_skill_name_" + str(passive_skill_2_masterdata)
    passive_skill_dictionary_3 = "passive_skill_name_" + str(passive_skill_3_masterdata)
    passive_skill_dictionary_4 = "passive_skill_name_" + str(passive_skill_4_masterdata)
    passive_skill_dictionary_5 = "passive_skill_name_" + str(passive_skill_5_masterdata)
    passive_skill_dictionary_ab1 = "passive_skill_name_" + str(passive_skill_ab1_masterdata)
    passive_skill_dictionary_desc1 = "passive_skill_description_" + str(passive_skill_1_masterdata)
    passive_skill_dictionary_desc2 = "passive_skill_description_" + str(passive_skill_2_masterdata)
    passive_skill_dictionary_desc3 = "passive_skill_description_" + str(passive_skill_3_masterdata)
    passive_skill_dictionary_desc4 = "passive_skill_description_" + str(passive_skill_4_masterdata)
    passive_skill_dictionary_desc5 = "passive_skill_description_" + str(passive_skill_5_masterdata)
    passive_skill_dictionary_desc1ab = "passive_skill_description_" + str(passive_skill_ab1_masterdata)
    ## dual skill not supported yet
    # passive skill icon done but 1 missing
    cpassive_skill_icon = PASSIVE_SKILL_ICONS.get(passive_skill_effect_type, "+H")

    passive_names_masterdata = [passive_skill_dictionary_masterdata_1, passive_skill_dictionary_masterdata_2,
                                passive_skill_dictionary_masterdata_3, passive_skill_dictionary_masterdata_4,
                                passive_skill_dictionary_masterdata_5]
    passive_descs_masterdata = [passive_skill_dictionary_desc1_masterdata, passive_skill_dictionary_desc2_masterdata,
                                passive_skill_dictionary_desc3_masterdata, passive_skill_dictionary_desc4_masterdata,
                                passive_skill_dictionary_desc5_masterdata]
    for skill_id, name_key, desc_key in zip(passive_skill_ids, passive_names_masterdata, passive_descs_masterdata):
        cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (skill_id, name_key, desc_key, skill_id, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_dictionary_masterdata_ab1, passive_skill_dictionary_desc1ab_masterdata, passive_skill_ab1_masterdata, donot_insert, cactive_ability_skill_icon, active_skill_ability_trigger_type, active_skill_ability_chance_logic, active_skill_ability_condition_id1, donot_insert))

    passive_skill_evaluations = [passive_skill_evaluation]
    for step in (passive_skill_evaluation_step_even_up, passive_skill_evaluation_step_odd_up,
                 passive_skill_evaluation_step_even_up, passive_skill_evaluation_step_odd_up):
        passive_skill_evaluations.append(passive_skill_evaluations[-1] + step)
    for skill_id, evaluation in zip(passive_skill_ids, passive_skill_evaluations):
        cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (skill_id, evaluation, passive_skill_target_id1, donot_insert, skill_id, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, active_skill_ability_evaluation, active_skill_ability_target_id1, donot_insert, passive_skill_ab1_masterdata, donot_insert))
    cpassive_skill_logic_effect2 = passive_skill_effect_value + passive_skill_effect_value_step_up
    cpassive_skill_logic_effect3 = cpassive_skill_logic_effect2 + passive_skill_effect_value_step_up
    cpassive_skill_logic_effect4 = cpassive_skill_logic_effect3 + passive_skill_effect_value_step_up
    cpassive_skill_logic_effect5 = cpassive_skill_logic_effect4 + passive_skill_effect_value_step_up
    passive_skill_effect_values = [passive_skill_effect_value, cpassive_skill_logic_effect2,
                                   cpassive_skill_logic_effect3, cpassive_skill_logic_effect4,
                                   cpassive_skill_logic_effect5]
    for skill_id, effect_value in zip(passive_skill_ids, passive_skill_effect_values):
        cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, '2', ?, ?, '2', '2', '1', ?, '255', '0');", (skill_id, passive_skill_effect_type, effect_value, donot_insert))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_ab1_masterdata, active_skill_ability_effect_target_parameter, active_skill_ability_effect_type, active_skill_ability_effect_value, cactive_skill_ability_calculation_type, donot_insert, active_skill_ability_effect_finish_type, active_skill_ability_effect_finish_value))
    if rarity_card == "PARTY":
        if id_passive_skill is None:
            passive_skill_6_masterdata = generate_unique_id(cursor, "SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", 999999999)
            passive_skill_7_masterdata = generate_unique_id(cursor, "SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", 999999999)
        else:
            passive_skill_6_masterdata = str(id_passive_skill) + "06"
            passive_skill_7_masterdata = str(id_passive_skill) + "07"
        passive_skill_dictionary_masterdata_6 = "k.passive_skill_name_" + str(passive_skill_6_masterdata)
        passive_skill_dictionary_masterdata_7 = "k.passive_skill_name_" + str(passive_skill_7_masterdata)
        passive_skill_dictionary_desc6_masterdata = "k.passive_skill_description_" + str(passive_skill_6_masterdata)
        passive_skill_dictionary_desc7_masterdata = "k.passive_skill_description_" + str(passive_skill_7_masterdata)
        passive_skill_dictionary_6 = "passive_skill_name_" + str(passive_skill_6_masterdata)
        passive_skill_dictionary_7 = "passive_skill_name_" + str(passive_skill_7_masterdata)
        passive_skill_dictionary_desc6 = "passive_skill_description_" + str(passive_skill_6_masterdata)
        passive_skill_dictionary_desc7 = "passive_skill_description_" + str(passive_skill_7_masterdata)
        cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_6_masterdata, passive_skill_dictionary_masterdata_6, passive_skill_dictionary_desc4_masterdata, passive_skill_6_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
        cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_7_masterdata, passive_skill_dictionary_masterdata_7, passive_skill_dictionary_desc5_masterdata, passive_skill_7_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
        cpassive_skill_evaluation6_logic = passive_skill_evaluations[4] + passive_skill_evaluation_step_even_up
        cpassive_skill_evaluation7_logic = cpassive_skill_evaluation6_logic + passive_skill_evaluation_step_odd_up
        cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_6_masterdata, cpassive_skill_evaluation6_logic, passive_skill_target_id1, donot_insert, passive_skill_6_masterdata, donot_insert))
        cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_7_masterdata, cpassive_skill_evaluation7_logic, passive_skill_target_id1, donot_insert, passive_skill_7_masterdata, donot_insert))
        cpassive_skill_logic_effect6 = cpassive_skill_logic_effect5 + passive_skill_effect_value_step_up
        cpassive_skill_logic_effect7 = cpassive_skill_logic_effect6 + passive_skill_effect_value_step_up
        cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, '2', ?, ?, '2', '2', '1', ?, '255', '0');", (passive_skill_6_masterdata, passive_skill_effect_type, cpassive_skill_logic_effect6, donot_insert))
        cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, '2', ?, ?, '2', '2', '1', ?, '255', '0');", (passive_skill_7_masterdata, passive_skill_effect_type, cpassive_skill_logic_effect7, donot_insert))
        cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '6', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_6, passive_skill_6_masterdata))
        cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '7', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_7, passive_skill_7_masterdata))

    # m_card
    if is_gacha1_or_event2_card == 1:
        caddon_flag_gacha = 1
        caddon_flag_event = 0
    elif is_gacha1_or_event2_card == 2:
        caddon_flag_gacha = 0
        caddon_flag_event = 1

    cursor.execute("SELECT MAX(school_idol_no) FROM main.m_card;", ())
    result_idol = cursor.fetchone()
    min_school_idol_ja = result_idol[0] if result_idol[0] is not None else 0

    new_school_idol_ja = min_school_idol_ja + 1

    cursor.execute("INSERT INTO main.m_card (id, member_m_id, school_idol_no, card_rarity_type, card_attribute, role, member_card_thumbnail_asset_path, at_gacha, at_event, training_tree_m_id, active_skill_voice_path, sp_point, exchange_item_id, role_effect_master_id, passive_skill_slot, max_passive_skill_slot) VALUES (?, ?, ?, ?, ?, ?, '>i', ?, ?, ?, ?, ?, ?, ?, ?, ?);", (card_id_masterdata, chara_id, new_school_idol_ja, caddon_rarity, attribute_card, role_card, caddon_flag_gacha, caddon_flag_event, card_id_masterdata, sheet_name_file, caddon_sp, caddon_exchange_item_id, role_card, caddon_passive_slot, caddon_passive_slot_max))

    # m_card_active_skill
    for level_n, skill_id in enumerate(active_skill_ids, start=1):
        cursor.execute(f"INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '{level_n}', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, skill_id))

    # m_card_appearance
    card_dictionary_masterdata_1 = "k.card_name_" + str(card_id_masterdata)
    card_dictionary_masterdata_2 = "k.card_name_awaken_" + str(card_id_masterdata)
    card_dictionary_1 = "card_name_" + str(card_id_masterdata)
    card_dictionary_2 = "card_name_awaken_" + str(card_id_masterdata)
    card_hiragana_dictionary_masterdata_1 = "k.card_name_hiragana_" + str(card_id_masterdata)
    card_hiragana_dictionary_masterdata_2 = "k.card_name_hiragana_awaken_" + str(card_id_masterdata)
    card_hiragana_dictionary_1 = "card_name_hiragana_" + str(card_id_masterdata)
    card_hiragana_dictionary_2 = "card_name_hiragana_awaken_" + str(card_id_masterdata)
    clivedeck_id1 = "Card/CardTrimAuto/tex_card_" + str(card_id_masterdata) + "_0_t"
    clivedeck_id2 = "Card/CardTrimAuto/tex_card_" + str(card_id_masterdata) + "_1_t"
    cursor.execute("INSERT INTO main.m_card_appearance (card_m_id, appearance_type, card_name, pronunciation, image_asset_path, thumbnail_asset_path, still_thumbnail_asset_path, background_asset_path, live_deck_asset_path_id) VALUES (?, '1', ?, ?, ?, ?, ?, 'eS', ?);", (card_id_masterdata, card_dictionary_masterdata_1, card_hiragana_dictionary_masterdata_1, card_path, card_thumbnail_path, card_still_path, clivedeck_id1))
    cursor.execute("INSERT INTO main.m_card_appearance (card_m_id, appearance_type, card_name, pronunciation, image_asset_path, thumbnail_asset_path, still_thumbnail_asset_path, background_asset_path, live_deck_asset_path_id) VALUES (?, '2', ?, ?, ?, ?, ?, 'eS', ?);", (card_id_masterdata, card_dictionary_masterdata_2, card_hiragana_dictionary_masterdata_2, card_awaken_path, card_awaken_thumbnail_path, card_awaken_still_path, clivedeck_id2))

    # m_card_trimming_live_deck
    cursor.execute("INSERT INTO main.m_card_trimming_live_deck (id, asset_path) VALUES (?, ?);", (clivedeck_id1, card_deck_path))
    cursor.execute("INSERT INTO main.m_card_trimming_live_deck (id, asset_path) VALUES (?, ?);", (clivedeck_id2, card_awaken_deck_path))

    # m_card_trimming_live_cutin
    # invert sign of a number for photoshop (원본 그대로: x는 normal 값을 양쪽에 사용)
    invert_offset_x_normal = card_normal_trimming_live_cutin_offset_x * -1
    invert_offset_y_normal = card_awaken_trimming_live_cutin_offset_y * -1
    invert_offset_x_awaken = card_normal_trimming_live_cutin_offset_x * -1
    invert_offset_y_awaken = card_awaken_trimming_live_cutin_offset_y * -1
    offset_x_normal_logic_cutin = int(invert_offset_x_normal * 10000)
    offset_y_normal_logic_cutin = int(invert_offset_y_normal * 10000)
    rotation_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_rotation * 1000)
    scale_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_scale * 100)
    offset_x_awaken_logic_cutin = int(invert_offset_x_awaken * 10000)
    offset_y_awaken_logic_cutin = int(invert_offset_y_awaken * 10000)
    rotation_awaken_logic_cutin = int(card_awaken_trimming_live_cutin_offset_rotation * 1000)
    scale_awaken_logic_cutin = int(card_awaken_trimming_live_cutin_offset_scale * 100)
    cursor.execute("INSERT INTO main.m_card_trimming_live_cutin (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '1', ?, ?, ?, ?);", (card_id_masterdata, offset_x_normal_logic_cutin, offset_y_normal_logic_cutin, rotation_normal_logic_cutin, scale_normal_logic_cutin))
    cursor.execute("INSERT INTO main.m_card_trimming_live_cutin (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '2', ?, ?, ?, ?);", (card_id_masterdata, offset_x_awaken_logic_cutin, offset_y_awaken_logic_cutin, rotation_awaken_logic_cutin, scale_awaken_logic_cutin))

    # m_card_trimming_profile
    invert_offset_x_normal_profile = card_normal_trimming_profile_offset_x * -1
    invert_offset_x_awaken_profile = card_awaken_trimming_profile_offset_x * -1
    offset_x_normal_logic_trimming = int(invert_offset_x_normal_profile * 10000)
    scale_normal_logic_trimming = int(card_normal_trimming_profile_offset_scale * 100)
    offset_x_awaken_logic_trimming = int(invert_offset_x_awaken_profile * 10000)
    scale_awaken_logic_trimming = int(card_awaken_trimming_profile_offset_scale * 100)
    cursor.execute("INSERT INTO main.m_card_trimming_profile (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '1', ?, '0', '0', ?);", (card_id_masterdata, offset_x_normal_logic_trimming, scale_normal_logic_trimming))
    cursor.execute("INSERT INTO main.m_card_trimming_profile (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '2', ?, '0', '0', ?);", (card_id_masterdata, offset_x_awaken_logic_trimming, scale_awaken_logic_trimming))

    # m_skill_effect_value_count
    if active_skill_ability_effect_type in skill_effect_value_count_types:
        for count_n in range(10):
            cursor.execute(f"INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, '{count_n}', ?);", (passive_skill_ab1_masterdata, int(active_skill_ability_effect_value * count_n)))
    if active_skill_effect_type in skill_effect_value_count_types:
        for skill_id, effect_value in zip(active_skill_ids, active_skill_effect_values):
            for count_n in range(10):
                cursor.execute(f"INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, '{count_n}', ?);", (skill_id, int(effect_value * count_n)))

    # m_card_awaken_parameter
    cursor.execute("INSERT INTO main.m_card_awaken_parameter (card_master_id, parameter1, parameter2, parameter3) VALUES (?, ?, ?, ?);", (card_id_masterdata, card_training_tree_awaken_stamina, card_training_tree_awaken_appeal, card_training_tree_awaken_technique))

    # m_card_passive_skill_original
    for level_n, (skill_id, name_key) in enumerate(zip(passive_skill_ids, passive_names_masterdata), start=1):
        cursor.execute(f"INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '{level_n}', '1', ?, ?);", (card_id_masterdata, name_key, skill_id))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '1', '2', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_ab1, passive_skill_ab1_masterdata))
    # m_card_grade_up_item
    if rarity_card == "SR":
        caddon_grade_up_val1 = 25
        caddon_grade_up_val2 = 10
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        caddon_grade_up_val1 = 125
        caddon_grade_up_val2 = 30
    for item_id, amount in (('1800', 'caddon_grade_up_val1'), ('1805', 'caddon_grade_up_val2')):
        amount_value = caddon_grade_up_val1 if item_id == '1800' else caddon_grade_up_val2
        for grade in range(1, 6):
            cursor.execute(f"INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '{grade}', '13', '{item_id}', ?);", (card_id_masterdata, amount_value))

    # m_card_parameter (calculated average from official card, dtype : float64)
    if rarity_card == "R":
        zcard_max_appeal = int(card_base_appeal * 1.995153)
        zcard_max_stamina = int(card_base_stamina * 1.995914)
        zcard_max_technique = int(card_base_technique * 1.995760)
    if rarity_card == "SR":
        zcard_max_appeal = int(card_base_appeal * 1.995525)
        zcard_max_stamina = int(card_base_stamina * 1.995633)
        zcard_max_technique = int(card_base_technique * 1.995492)
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        zcard_max_appeal = int(card_base_appeal * 2.333638)
        zcard_max_stamina = int(card_base_stamina * 2.333778)
        zcard_max_technique = int(card_base_technique * 2.333629)

    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, min_level_card, card_base_appeal, card_base_stamina, card_base_technique))
    for level in range(min_level_card + 1, max_level_card):
        appeal_rate = calculate_parameter_value(card_base_appeal, zcard_max_appeal, min_level_card, max_level_card, level)
        stamina_rate = calculate_parameter_value(card_base_stamina, zcard_max_stamina, min_level_card, max_level_card, level)
        technique_rate = calculate_parameter_value(card_base_technique, zcard_max_technique, min_level_card, max_level_card, level)
        cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, level, appeal_rate, stamina_rate, technique_rate))
    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, max_level_card, zcard_max_appeal, zcard_max_stamina, zcard_max_technique))

    # m_gacha_card_performance
    card_serif_dictionary_masterdata = "k.gacha_" + str(sheet_name_file1)
    card_serif_dictionary = "gacha_" + str(sheet_name_file1)
    if rarity_card == "UR":
        if chara_id in GACHA_SIGN_MOVIE:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, ?);", (card_id_masterdata, sheet_name_file1, card_serif_dictionary_masterdata, GACHA_SIGN_MOVIE[chara_id]))
    else:
        cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, ?);", (card_id_masterdata, donot_insert, donot_insert, donot_insert))
    # m_training_tree
    if rarity_card == "SR":
        ctraining_tree_passive_increase = 1
        ctraining_tree_design = 12
    elif rarity_card == "UR":
        ctraining_tree_passive_increase = 1
        ctraining_tree_design = 13
    elif rarity_card == "FES":
        ctraining_tree_design = 23
        ctraining_tree_passive_increase = 1
    elif rarity_card == "PARTY":
        ctraining_tree_design = 33
        ctraining_tree_passive_increase = 2

    formatted_chara_id = f"{chara_id:03}"
    ctraining_tree_logic = str(ctraining_tree_design) + str(formatted_chara_id) + str(role_card)

    cursor.execute("INSERT INTO main.m_training_tree (id, training_tree_mapping_m_id, training_tree_card_param_m_id, training_tree_card_passive_skill_increase_m_id) VALUES (?, ?, ?, ?);", (card_id_masterdata, ctraining_tree_logic, card_id_masterdata, ctraining_tree_passive_increase))

    # m_training_tree_card_param
    # using logic for UR / FES / PARTY, this is not accurate what so
    if rarity_card == "SR":
        card_training_tree_cell1_appeal = int(card_base_appeal / 7.15)
        card_training_tree_cell2_appeal = int(card_base_appeal / 4.75)
        card_training_tree_cell3_appeal = int(card_training_tree_cell2_appeal + card_training_tree_cell_extra_appeal)
        card_training_tree_cell1_stamina = int(card_base_stamina / 7.15)
        card_training_tree_cell2_stamina = int(card_base_stamina / 4.75)
        card_training_tree_cell3_stamina = int(card_training_tree_cell2_stamina + card_training_tree_cell_extra_stamina)
        card_training_tree_cell1_technique = int(card_base_technique / 7.15)
        card_training_tree_cell2_technique = int(card_base_technique / 4.75)
        card_training_tree_cell3_technique = int(card_training_tree_cell2_technique + card_training_tree_cell_extra_technique)
    elif rarity_card == "UR" or rarity_card == "FES":
        card_training_tree_cell1_appeal = int(card_base_appeal / 6)
        card_training_tree_cell2_appeal = int(card_base_appeal / 4)
        card_training_tree_cell3_appeal = int(card_training_tree_cell2_appeal + card_training_tree_cell_extra_appeal)
        card_training_tree_cell1_stamina = int(card_base_stamina / 6)
        card_training_tree_cell2_stamina = int(card_base_stamina / 4)
        card_training_tree_cell3_stamina = int(card_training_tree_cell2_stamina + card_training_tree_cell_extra_stamina)
        card_training_tree_cell1_technique = int(card_base_technique / 6)
        card_training_tree_cell2_technique = int(card_base_technique / 4)
        card_training_tree_cell3_technique = int(card_training_tree_cell2_technique + card_training_tree_cell_extra_technique)
    elif rarity_card == "PARTY":
        card_training_tree_cell1_appeal = int(card_base_appeal / 5.54)
        card_training_tree_cell2_appeal = int(card_base_appeal / 3.43)
        card_training_tree_cell3_appeal = int(card_training_tree_cell2_appeal + card_training_tree_cell_extra_appeal)
        card_training_tree_cell1_stamina = int(card_base_stamina / 5.54)
        card_training_tree_cell2_stamina = int(card_base_stamina / 3.43)
        card_training_tree_cell3_stamina = int(card_training_tree_cell2_stamina + card_training_tree_cell_extra_stamina)
        card_training_tree_cell1_technique = int(card_base_technique / 5.54)
        card_training_tree_cell2_technique = int(card_base_technique / 3.43)
        card_training_tree_cell3_technique = int(card_training_tree_cell2_technique + card_training_tree_cell_extra_technique)
    ## not done, need wrote this for each, very BIG, based on tree & role card, many value incorrect, also lim not added
    # (레어도, 롤)별 등록 행은 TRAINING_TREE_PARAMS 테이블 참고 - 원본 if/elif 순서 그대로
    for content_no, content_type, cell_name in TRAINING_TREE_PARAMS.get((rarity_card, role_card), []):
        cell_value = globals()['card_training_tree_' + cell_name]
        cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, ?, ?, ?);", (card_id_masterdata, content_no, content_type, cell_value))

    # m_training_tree_card_story_side
    ## will return as R character because there is no way to create new one
    id_card_str_combined = str(card_id_masterdata)
    id_split3_str = id_card_str_combined[0] + id_card_str_combined[2:]
    story_side_id_masterdata = str(id_split3_str) + "1"
    cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '11', '1', ?);", (card_id_masterdata, story_side_id_masterdata))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        story_side2_id_masterdata = str(id_split3_str) + "2"
        cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '9', '1', ?);", (card_id_masterdata, story_side2_id_masterdata))

    # m_training_tree_card_suit
    cursor.execute("INSERT INTO main.m_training_tree_card_suit (card_m_id, training_content_no, suit_m_id) VALUES (?, '1', ?);", (card_id_masterdata, card_id_masterdata))

    # m_training_tree_card_voice
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '1', '1001014');", (card_id_masterdata,))
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '2', '1001015');", (card_id_masterdata,))

    # m_training_tree_progress_reward
    ## will return as stargem, recolor costume currectly not implemented
    if rarity_card == "SR":
        progress_reward_rows = (('40', '10'), ('59', '10'), ('75', '20'))
    else:
        progress_reward_rows = (('46', '10'), ('69', '10'), ('87', '20'))
    for activate_num, amount in progress_reward_rows:
        cursor.execute(f"INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '{activate_num}', '0', '1', '0', '{amount}');", (card_id_masterdata,))

    # TRYING FIX SOFTLOCK
    ## m_story_side
    cursor.execute("SELECT MIN(display_order) FROM main.m_story_side WHERE member_m_id = ?;", (chara_id,))
    result_story = cursor.fetchone()
    min_display_order_ja_story = result_story[0] if result_story[0] is not None else 0

    display_order_new_ja_story = min_display_order_ja_story - 1
    # return as honoka
    cursor.execute("INSERT INTO main.m_story_side (id, member_m_id, card_m_id, story_no, title, scenario_script_asset_path, card_image_asset_path, story_side_color, display_order, story_side_release_route) VALUES (?, ?, ?, '1', 'm.ss_title_100013001_1', 'SS/0001/ss_100013001_01', ?, 'ffcc00', ?, '1');", (story_side_id_masterdata, chara_id, card_id_masterdata, card_still_path, display_order_new_ja_story))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        display_order_new_ja_story2 = display_order_new_ja_story - 1
        cursor.execute("INSERT INTO main.m_story_side (id, member_m_id, card_m_id, story_no, title, scenario_script_asset_path, card_image_asset_path, story_side_color, display_order, story_side_release_route) VALUES (?, ?, ?, '2', 'm.ss_title_100013001_2', 'SS/0001/ss_100013001_02', ?, 'ffcc00', ?, '2');", (story_side2_id_masterdata, chara_id, card_id_masterdata, card_still_path, display_order_new_ja_story2))

    # Find the minimum display_order for the given chara_id
    cursor.execute("SELECT MIN(display_order) FROM main.m_suit WHERE member_m_id = ?;", (chara_id,))
    result = cursor.fetchone()
    min_display_order_ja = result[0] if result[0] is not None else 0

    display_order_new_ja = min_display_order_ja - 1

    # Costume insert
    cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '1', ?, ?, ?);",
                   (card_id_masterdata, chara_id, card_dictionary_masterdata_2, thumbnail_costume_path, card_id_masterdata, costume_path, display_order_new_ja))
    # can't trade, how i gonna do? SBL?

    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (card_id_masterdata, rina_unmask_costume_path))

# ---- dictionary_ja_k: 스킬 설명/카드 이름 사전 등록 ----
with sqlite3.connect('assets/db/jp/dictionary_ja_k.db') as conn:
    cursor = conn.cursor()
    exec(keyload_en)
    # convert value for information
    if active_skill_effect_type not in skill_effect_category_calculation_add:
        active_skill_effect_value = str(active_skill_effect_value / 100) + "%"
        cactive_skill_logic_effect2 = str(cactive_skill_logic_effect2 / 100) + "%"
        cactive_skill_logic_effect3 = str(cactive_skill_logic_effect3 / 100) + "%"
        cactive_skill_logic_effect4 = str(cactive_skill_logic_effect4 / 100) + "%"
        cactive_skill_logic_effect5 = str(cactive_skill_logic_effect5 / 100) + "%"

    passive_skill_effect_value = str(passive_skill_effect_value / 100) + "%"
    cpassive_skill_logic_effect2 = str(cpassive_skill_logic_effect2 / 100) + "%"
    cpassive_skill_logic_effect3 = str(cpassive_skill_logic_effect3 / 100) + "%"
    cpassive_skill_logic_effect4 = str(cpassive_skill_logic_effect4 / 100) + "%"
    cpassive_skill_logic_effect5 = str(cpassive_skill_logic_effect5 / 100) + "%"

    if active_skill_ability_effect_type not in skill_effect_category_calculation_add:
        active_skill_ability_effect_value = str(active_skill_ability_effect_value / 100) + "%"

    en_active_skill_ability_condition_id1 = skill_condition_dictionary.get(active_skill_ability_condition_id1)
    en_active_skill_ability_effect_type = effect_type_dictionary.get(active_skill_ability_effect_type)
    en_active_skill_ability_finish_type = finish_type_dictionary.get(active_skill_ability_effect_finish_type)
    en_active_skill_ability_target = skill_target_dictionary.get(active_skill_ability_target_id1)
    en_active_skill_ability_trigger_type = trigger_type_dictionary.get(active_skill_ability_trigger_type)
    en_active_skill_ability_name_effect_type = effect_type_name_dictionary.get(active_skill_ability_effect_type)
    en_active_skill_ability_name_target = skill_target_name_dictionary.get(active_skill_ability_target_id1)
    en_active_skill_finish_type = finish_type_dictionary.get(active_skill_effect_finish_type)
    en_active_skill_effect_type = effect_type_dictionary.get(active_skill_effect_type)
    en_active_skill_target = skill_target_dictionary.get(active_skill_target_id1)
    en_passive_skill_effect_type = effect_type_dictionary.get(passive_skill_effect_type)
    en_passive_skill_name_effect_type = effect_type_name_dictionary.get(passive_skill_effect_type)
    en_passive_skill_name_target = skill_target_name_dictionary.get(passive_skill_target_id1)
    en_passive_skill_target = skill_target_dictionary.get(passive_skill_target_id1)

    passive_skill1_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
    passive_skill2_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
    passive_skill3_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
    passive_skill4_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
    passive_skill5_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
    passive_skillab1_name_text = f"{en_active_skill_ability_name_effect_type}{en_active_skill_ability_name_target}"

    ### insertion code logic
    effect_value_per_insert = active_skill_ability_effect_value
    passive_skillab1_desc_text_ja = f"{en_active_skill_ability_effect_type.format(effect_value_per_insert=effect_value_per_insert)}\nCondition: {en_active_skill_ability_condition_id1}{en_active_skill_ability_trigger_type}\nChance: {active_skill_ability_chance_percent}%{en_active_skill_ability_target}"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc1ab, passive_skillab1_desc_text_ja))

    # 액티브 스킬 설명: 레벨 1~5 (효과값만 상이)
    finish_value_per_insert = active_skill_effect_finish_value
    active_skill_effect_values_text = [active_skill_effect_value, cactive_skill_logic_effect2,
                                       cactive_skill_logic_effect3, cactive_skill_logic_effect4,
                                       cactive_skill_logic_effect5]
    for desc_key, effect_value_per_insert in zip(active_skill_descs, active_skill_effect_values_text):
        active_skill_desc_text_ja = f"{en_active_skill_effect_type.format(effect_value_per_insert=effect_value_per_insert)}{en_active_skill_finish_type.format(finish_value_per_insert=finish_value_per_insert)}{en_active_skill_target}"
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (desc_key, active_skill_desc_text_ja))

    # 패시브 스킬 설명: 레벨 1~5
    passive_descs = [passive_skill_dictionary_desc1, passive_skill_dictionary_desc2,
                     passive_skill_dictionary_desc3, passive_skill_dictionary_desc4,
                     passive_skill_dictionary_desc5]
    passive_skill_effect_values_text = [passive_skill_effect_value, cpassive_skill_logic_effect2,
                                        cpassive_skill_logic_effect3, cpassive_skill_logic_effect4,
                                        cpassive_skill_logic_effect5]
    for desc_key, effect_value_per_insert in zip(passive_descs, passive_skill_effect_values_text):
        passive_skill_desc_text_ja = f"{en_passive_skill_effect_type.format(effect_value_per_insert=effect_value_per_insert)}{en_passive_skill_target}"
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (desc_key, passive_skill_desc_text_ja))

    if rarity_card == "PARTY":
        cpassive_skill_logic_effect6 = str(cpassive_skill_logic_effect6 / 100) + "%"
        cpassive_skill_logic_effect7 = str(cpassive_skill_logic_effect7 / 100) + "%"

        passive_skill6_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
        passive_skill7_name_text = f"{en_passive_skill_name_effect_type}{en_passive_skill_name_target}"
        effect_value_per_insert = cpassive_skill_logic_effect6
        passive_skill6_desc_text_ja = f"{en_passive_skill_effect_type.format(effect_value_per_insert=effect_value_per_insert)}{en_passive_skill_target}"
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc6, passive_skill6_desc_text_ja))

        effect_value_per_insert = cpassive_skill_logic_effect7
        passive_skill7_desc_text_ja = f"{en_passive_skill_effect_type.format(effect_value_per_insert=effect_value_per_insert)}{en_passive_skill_target}"
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc7, passive_skill7_desc_text_ja))
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_6, passive_skill6_name_text))
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_7, passive_skill7_name_text))

    ###
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_dictionary_1, card_name_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_dictionary_2, card_name_awaken_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_hiragana_dictionary_1, card_name_hiragana_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_hiragana_dictionary_2, card_name_awaken_hiragana_ja))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_serif_dictionary, card_gacha_serif_ja))

    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary, active_skill_name_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_1, passive_skill1_name_text))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_2, passive_skill2_name_text))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_3, passive_skill3_name_text))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_4, passive_skill4_name_text))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_5, passive_skill5_name_text))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_ab1, passive_skillab1_name_text))

# ---- serverdata: 가챠 배너 갱신 ----
with sqlite3.connect('serverdata.db') as conn:
    cursor = conn.cursor()

    update_query = "UPDATE s_gacha SET client_gacha = ? WHERE gacha_master_id = ?;"

    # Fetch the current JSON data based on chara_id_group
    if chara_id_group == 13:
        gacha_master_id = 2230615
    elif chara_id_group == 14:
        gacha_master_id = 2230616
    elif chara_id_group == 15:
        gacha_master_id = 2230617
    else:
        # Handle other cases if needed
        pass

    cursor.execute("SELECT client_gacha FROM s_gacha WHERE gacha_master_id = ?", (gacha_master_id,))
    row = cursor.fetchone()
    if row:
        client_gacha_json = json.loads(row[0])
        for appeal in client_gacha_json['gacha_appeals']:
            appeal['card_master_id'] = card_id_masterdata
        updated_client_gacha = json.dumps(client_gacha_json)

        cursor.execute(update_query, (updated_client_gacha, gacha_master_id))

    # 주의: 원본의 연산자 우선순위 그대로 유지
    # (UR/FES 는 그룹과 무관하게 첫 매칭 분기로 들어감)
    if rarity_card == "SR" and chara_id_group == 13:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('200', ?);", (card_id_masterdata,))
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY" and chara_id_group == 13:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('300', ?);", (card_id_masterdata,))
    elif rarity_card == "SR" and chara_id_group == 14:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('201', ?);", (card_id_masterdata,))
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY" and chara_id_group == 14:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('301', ?);", (card_id_masterdata,))
    elif rarity_card == "SR" and chara_id_group == 15:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('202', ?);", (card_id_masterdata,))
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY" and chara_id_group == 15:
        cursor.execute("INSERT INTO main.s_gacha_card (group_master_id, card_master_id) VALUES ('302', ?);", (card_id_masterdata,))

    print("added to gacha banner")

# ---- asset_a_ja: 다운로드 패키지 등록 ----
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()

    donot_insert = None
    package_key_costume = "suit:" + str(card_id_masterdata)
    package_key_thumbnail = "main"
    category_costume = '3'
    category_thumbnail = '8'
    fresh_version = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main = hashlib.sha1(str(random.random()).encode()).hexdigest()

    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset = cursor.fetchone()[0]
    update_main_asset = get_main_asset + 10
    update_main_asset_ur = get_main_asset + 11
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                    (package_key_costume, fresh_version))
    else:
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_costume, fresh_version))

    # 썸네일/카드/보이스 매핑 (UR 계열은 가챠 보이스 1행 추가)
    thumbnail_mappings = [
        (thumbnail_costume_filename, thumbnail_costume_size),
        (card_filename, card_filesize),
        (card_thumbnail_filename, card_thumbnail_filesize),
        (card_still_filename, card_still_filesize),
        (card_deck_filename, card_deck_filesize),
        (card_awaken_filename, card_awaken_filesize),
        (card_awaken_thumbnail_filename, card_awaken_thumbnail_filesize),
        (card_awaken_still_filename, card_awaken_still_filesize),
        (card_awaken_deck_filename, card_awaken_deck_filesize),
    ]
    for pack_name_to_insert, pack_size in thumbnail_mappings:
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, pack_name_to_insert, pack_size, donot_insert, category_thumbnail))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_thumbnail, active_skill_voice_filename, active_skill_voice_filesize, donot_insert))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                    (package_key_thumbnail, card_gacha_voice_filename, card_gacha_voice_filesize, donot_insert))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main, update_main_asset_ur))
    else:
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main, update_main_asset))

print("deleting temp folder")
shutil.rmtree(temp_directory, ignore_errors=True)

with open(check_json_config, 'r') as f:
    config_elichika = json.load(f)
    xcheck_cdn = config_elichika.get('cdn_server')
    xcheck_cdnpath = config_elichika.get('cdn_path_type')
    if xcheck_cdn != "http://127.0.0.1:8080/static" and xcheck_cdnpath != "all":
        config_elichika['cdn_server'] = "http://127.0.0.1:8080/static"
        config_elichika['cdn_path_type'] = "all"
        with open(check_json_config, 'w') as f:
            json.dump(config_elichika, f, indent=4)
            print("CDN server updated to http://127.0.0.1:8080/static")

print("FINISHED")
