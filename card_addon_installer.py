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
print("This script sucks.")
print("If you could make it suck less, that would be awesome.")
print("Specifically: check docs/README.md on card section, there a LOT thing need todo")
print("")
confirm_script_card = input("Press Enter to Continue")

def backup_operate(filelist):
    # Create a folder with the current date and time as the name
    backup_folder = datetime.now().strftime("backup_db/%Y-%m-%d_%H-%M-%S")
    # Create the backup folder
    os.makedirs(backup_folder)
    
    # Copy each file from the filelist to the backup folder
    for file_path in filelist:
        # Get the directory structure of the file
        relative_path = os.path.relpath(file_path, start=".")
        dest_path = os.path.join(backup_folder, relative_path)
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        # Copy file to destination path
        shutil.copy(file_path, dest_path)
    
    print("Backup completed successfully.")
    
filelist = [
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/dictionary_ja_k.db",
    "assets/db/jp/masterdata.db",
    "serverdata.db",
    "userdata.db"
]

# init code default value (do nothing)
card_name_en = ""
card_name_ko = ""
card_name_zh = ""
card_name_ja = ""
card_name_hiragana_en = ""
card_name_hiragana_ko = ""
card_name_hiragana_zh = ""
card_name_hiragana_ja = ""
card_description = ""

# idolize
card_name_awaken_en = ""
card_name_awaken_ko = ""
card_name_awaken_zh = ""
card_name_awaken_ja = ""
card_name_awaken_hiragana_en = ""
card_name_awaken_hiragana_ko = ""
card_name_awaken_hiragana_zh = ""
card_name_awaken_hiragana_ja = ""

# EXPERT ONLY, IF YOU DON'T KNOW HOW TO SETUP SKILL THEN ASK SOMEONE OR LEAVE AS NOTHING
# RED Label Skill
# active skill
active_skill_type = 1
active_skill_name_en = ""
active_skill_name_ko = ""
active_skill_name_zh = ""
active_skill_name_ja = ""

## skill
active_skill_evaluation = 0
active_skill_evaluation_step_even_up = 0
active_skill_evaluation_step_odd_up = 0
active_skill_target_id1 = 1

## skill effect
active_skill_effect_target_parameter = 2
active_skill_effect_type = 1
active_skill_effect_calculation_type = 1
active_skill_effect_finish_type = 255
active_skill_effect_finish_value = 0
active_skill_effect_value = 0
active_skill_effect_value_step_up = 0

# BLUE Label Skill
## skill
passive_skill_evaluation = 0
passive_skill_evaluation_step_even_up = 0
passive_skill_evaluation_step_odd_up = 0
passive_skill_target_id1 = 1

## skill effect
passive_skill_effect_target_parameter = 2
passive_skill_effect_type = 1
passive_skill_effect_calculation_type = 1
passive_skill_effect_finish_type = 255
passive_skill_effect_finish_value = 0
passive_skill_effect_value = 0
passive_skill_effect_value_step_up = 0

# RED Label Skill
# passive skill ability
passive_skill_ability_condition_id1 = 1
passive_skill_ability_trigger_type = 255
passive_skill_ability_chance_percent = 0

## skill
passive_skill_ability_evaluation = 0
passive_skill_ability_target_id1 = 1

## skill effect
passive_skill_ability_effect_target_parameter = 2
passive_skill_ability_effect_type = 1
passive_skill_ability_effect_calculation_type = 1
passive_skill_ability_effect_finish_type = 255
passive_skill_ability_effect_finish_value = 0
passive_skill_ability_effect_value = 0

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
rarity_card = "SR"
attribute_card = 1
role_card = 1
is_gacha1_or_event2_card = 1

# stats
card_base_appeal = 0
card_base_stamina = 0
card_base_technique = 0
card_max_appeal = 0
card_max_stamina = 0
card_max_technique = 0

# trimming
## cut in
card_normal_trimming_live_cutin_offset_x = 0
card_normal_trimming_live_cutin_offset_y = 125
card_normal_trimming_live_cutin_offset_rotation = 0
card_normal_trimming_live_cutin_offset_scale = 100
card_awaken_trimming_live_cutin_offset_x = 0
card_awaken_trimming_live_cutin_offset_y = 125
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
card_training_tree_cell1_appeal = 0
card_training_tree_cell1_stamina = 0
card_training_tree_cell1_technique = 0
card_training_tree_cell2_appeal = 0
card_training_tree_cell2_stamina = 0
card_training_tree_cell2_technique = 0
card_training_tree_cell3_appeal = 0
card_training_tree_cell3_stamina = 0
card_training_tree_cell3_technique = 0

# gacha (UR only)
card_gacha_voice_file = ""
card_gacha_serif_en = ""
card_gacha_serif_ko = ""
card_gacha_serif_zh = ""
card_gacha_serif_ja = ""

# type card (string)
# SR
# UR
# FES
# PARTY

effect_type_dictionary_key_en = {
    1: "",
    2: "",
    3: "",
    4: "",
    5: "",
    6: "",
    7: "",
    8: "",
    9: "",
    10: "Increase base Appeal by",
    11: "",
    12: "",
    13: "",
    14: "",
    15: "",
    16: "",
    17: "",
    18: "",
    19: "",
    20: "",
    21: "",
    22: "",
    23: "",
    24: "",
    25: "",
    26: "",
    27: "",
    28: "",
    29: "",
    30: "",
    31: "",
    32: "",
    33: "",
    34: "",
    35: "",
    36: "",
    37: "",
    38: "",
    39: "",
    40: "",
    41: "",
    42: "",
    43: "",
    44: "",
    45: "",
    46: "",
    47: "",
    48: "",
    49: "",
    50: "",
    51: "",
    52: "",
    53: "",
    54: "",
    55: "",
    56: "",
    57: "",
    58: "",
    59: "",
    60: "",
    61: "",
    62: "",
    63: "",
    64: "",
    65: "",
    66: "",
    67: "",
    68: "",
    69: "",
    70: "",
    71: "",
    72: "",
    73: "",
    74: "",
    75: "",
    76: "",
    77: "",
    78: "",
    79: "",
    80: "",
    81: "",
    82: "",
    83: "",
    84: "",
    85: "",
    86: "",
    87: "",
    88: "",
    89: "",
    90: "",
    91: "",
    92: "",
    93: "",
    94: "",
    95: "",
    96: "",
    97: "",
    98: "",
    99: "",
    100: "",
    101: "",
    102: "",
    103: "",
    104: "",
    105: "",
    106: "",
    107: "",
    108: "",
    109: "",
    110: "",
    111: "",
    112: "",
    113: "",
    114: "",
    115: "",
    116: "",
    117: "",
    118: "",
    119: "",
    120: "",
    121: "",
    122: "",
    123: "",
    124: "",
    125: "",
    126: "",
    127: "",
    128: "",
    129: "",
    130: "",
    131: "",
    132: "",
    133: "",
    134: "",
    135: "",
    136: "",
    137: "",
    138: "",
    139: "",
    140: "",
    141: "",
    142: "",
    143: "",
    144: "",
    145: "",
    146: "",
    147: "",
    148: "",
    149: "",
    150: "",
    151: "",
    152: "",
    153: "",
    154: "",
    155: "",
    156: "",
    157: "",
    158: "",
    159: "",
    160: "",
    161: "",
    162: "",
    163: "",
    164: "",
    165: "",
    166: "",
    167: "",
    168: "",
    169: "",
    170: "",
    171: "",
    172: "",
    173: "",
    174: "",
    175: "",
    176: "",
    177: "",
    178: "",
    179: "",
    180: "",
    181: "",
    182: "",
    183: "",
    184: "",
    185: "",
    186: "",
    187: "",
    188: "",
    189: "",
    190: "",
    191: "",
    192: "",
    193: "",
    194: "",
    195: "",
    196: "",
    197: "",
    198: "",
    199: "",
    200: "",
    201: "",
    202: "",
    203: "",
    204: "",
    205: "",
    206: "",
    207: "",
    208: "",
    209: "",
    210: "",
    211: "",
    212: "",
    213: "",
    214: "",
    215: "",
    216: "",
    217: "",
    218: "",
    219: "",
    220: "",
    221: "",
    222: "",
    223: "",
    224: "",
    225: "",
    226: "",
    227: "",
    228: "",
    229: "",
    230: "",
    231: "",
    232: "",
    233: "",
    234: "",
    235: "",
    236: "",
    237: "",
    238: "",
    239: "",
    240: "",
    241: "",
    242: "",
    243: "",
    244: "",
    245: "",
    246: "",
    247: "",
    248: "",
    249: "",
    250: "",
    251: "",
    252: "",
    253: "",
    254: "",
    255: "",
    256: "",
    257: "",
    258: "",
    259: "",
    260: "",
    261: "",
    262: "",
    263: "",
    264: "",
    265: "",
    266: "The SP Skill gauge can be charged up to {effect_value_per_insert}",
    267: ""
}

# from suyo.be internal card
skill_target_dictionary_key_en = {
    1: "\nAffects: All units",
    2: "\nAffects: ",
    3: "\nAffects: ",
    4: "\nAffects: ",
    5: "\nAffects: ",
    6: "\nAffects: ",
    7: "\nAffects: ",
    8: "\nAffects: ",
    9: "\nAffects: ",
    10: "\nAffects: ",
    11: "\nAffects: ",
    12: "\nAffects: ",
    13: "\nAffects: ",
    14: "\nAffects: ",
    15: "\nAffects: ",
    16: "\nAffects: ",
    17: "\nAffects: ",
    18: "\nAffects: ",
    19: "\nAffects: ",
    20: "\nAffects: ",
    21: "\nAffects: ",
    22: "\nAffects: ",
    23: "\nAffects: ",
    24: "\nAffects: ",
    25: "\nAffects: ",
    26: "\nAffects: ",
    27: "\nAffects: ",
    28: "\nAffects: ",
    29: "\nAffects: µ's",
    30: "\nAffects: Aqours",
    31: "\nAffects: Nijigaku",
    32: "\nAffects: ",
    33: "\nAffects: ",
    34: "\nAffects: ",
    35: "\nAffects: CYaRon",
    36: "\nAffects: AZALEA",
    37: "\nAffects: Guilty Kiss",
    38: "\nAffects: Vo Type",
    39: "\nAffects: Sp Type",
    40: "\nAffects: Gd Type",
    41: "\nAffects: Sk Type",
    42: "\nAffects: ",
    43: "\nAffects: ",
    44: "\nAffects: ",
    45: "\nAffects: ",
    46: "\nAffects: ",
    47: "\nAffects: ",
    48: "\nAffects: ",
    49: "\nAffects: ",
    50: "\nAffects: Others (“Group”)",
    51: "\nAffects: ",
    52: "\nAffects: ",
    53: "\nAffects: Same Strategy",
    54: "\nAffects: Same School",
    55: "\nAffects: ",
    56: "\nAffects: Same Attribute",
    57: "\nAffects: Same Type",
    58: "",
    59: "\nAffects: Self",
    60: "\nAffects: Same Year",
    61: "\nAffects: Smile",
    62: "\nAffects: Pure",
    63: "\nAffects: Cool",
    64: "\nAffects: Active",
    65: "\nAffects: Natural",
    66: "\nAffects: Elegant",
    67: "\nAffects: Non-Smile",
    68: "\nAffects: Non-Vo Type",
    69: "\nAffects: 1st Years",
    70: "\nAffects: 2nd Years",
    71: "\nAffects: 3rd Years",
    72: "\nAffects: Non-Pure",
    73: "\nAffects: Non-Cool",
    74: "\nAffects: Non-Active",
    75: "\nAffects: Non-Natural",
    76: "\nAffects: Non-Elegant",
    77: "\nAffects: Non-Sp Types",
    78: "\nAffects: Non-Gd Types",
    79: "\nAffects: Non-Sk Types",
    80: "\nAffects: ",
    81: "\nAffects: ",
    82: "\nAffects: ",
    83: "\nAffects: Current Strategy",
    84: "\nAffects: ",
    85: "\nAffects: ",
    86: "\nAffects: Non-µ's",
    87: "\nAffects: Non-Vo or Gd Types",
    88: "\nAffects: Non-Vo or Sp Types",
    89: "\nAffects: Non-Vo or Sk Types",
    90: "\nAffects: Non-Gd or Sp Types",
    91: "\nAffects: ",
    92: "\nAffects: Non-Sp or Sk Types",
    93: "\nAffects: Sp and Sk Types",
    94: "\nAffects: ",
    95: "\nAffects: ",
    96: "\nAffects: Vo and Sk Types",
    97: "\nAffects: Vo and Sp Types",
    98: "\nAffects: Vo and Gd Types",
    99: "\nAffects: Non-Aqours",
    100: "\nAffects: Non-Niji",
    101: "\nAffects: Non-1st Years",
    102: "\nAffects: Non-2nd Years",
    103: "\nAffects: Non-3rd Years",
    104: "\nAffects: DiverDiva",
    105: "\nAffects: A•ZU•NA",
    106: "\nAffects: QU4RTZ",
    107: "\nAffects: Non-DiverDiva",
    108: "\nAffects: Non-A•ZU•NA",
    109: "\nAffects: Non-QU4RTZ",
    110: "\nAffects: ",
    111: "\nAffects: ",
    112: "\nAffects: Shioriko",
    113: "\nAffects: Lanzhu",
    114: "\nAffects: Mia",
    115: "\nAffects: ",
    116: "\nAffects: ",
    117: "\nAffects: ",
    118: "\nAffects: "
}

passive_skill_trigger_type_dictionary_key_en = {
    1: "All units",
    2: "",
    3: "On Appeal Chance start",
    4: "On Appeal Chance success",
    5: "On Appeal Chance failure",
    6: "",
    7: "",
    8: "",
    9: "",
    10: "",
}

finish_type_dictionary_key_en = {
    1: "until the Live Show ends",
    2: "for {finish_value_per_insert} Notes",
    3: "On Appeal Chance start",
    4: "On Appeal Chance success",
    5: "On Appeal Chance failure",
    6: "\nAffects: ",
    7: "\nAffects: ",
    8: "\nAffects: ",
    9: "\nAffects: ",
    10: "\nAffects: ",
}

skill_condition_dictionary_key_en = {
    1: "",
    2: "",
    3: "",
    4: "",
    5: "",
    6: "",
    7: "",
    8: "",
    9: "",
    10: "",
    11: "",
    12: "",
    13: "",
    14: "",
    15: "",
    16: "",
    17: "",
    18: "",
    19: "",
    20: "",
    21: "",
    22: "",
    23: "",
    24: "",
    25: "",
    26: "",
    27: "",
    28: "",
    29: "",
    30: "",
    31: "",
    32: "",
    33: "",
    34: "",
    35: "",
    36: "",
    37: "",
    38: "",
    39: "",
    40: "",
    41: "",
    42: "",
    43: "",
    44: "",
    45: "",
    46: "",
    47: "",
    48: "",
    49: "",
    50: "",
    51: "",
    52: "",
    53: "",
    54: "",
    55: "",
    56: "",
    57: "",
    58: "",
    59: "",
    60: "",
    61: "",
    62: "",
    63: "",
    64: "",
    65: "",
    66: "",
    67: "",
    68: "",
    69: "",
    70: "",
    71: "",
    72: "",
    73: "",
    74: "",
    75: "",
    76: "",
    77: "",
    78: "",
    79: "",
    80: "",
    81: "",
    82: "",
    83: "",
    84: "",
    85: "",
    86: "",
    87: "",
    88: "",
    89: "",
    90: "",
    91: "",
    92: "",
    93: "",
    94: "",
    95: "",
    96: "",
    97: "",
    98: "",
    99: "",
    100: "",
    101: "",
    102: "",
    103: "",
    104: "",
    105: "",
    106: "",
    107: "",
    108: "",
    109: "",
    110: "",
    111: "",
    112: "",
    113: "",
    114: "",
    115: "",
    116: "",
    117: "",
    118: "",
    119: "",
    120: "",
    121: "",
    122: "",
    123: "",
    124: "",
    125: "",
    126: "",
    127: "",
    128: "",
    129: "",
    130: "",
    131: "",
    132: "",
    133: "",
    134: "",
    135: "",
    136: "",
    137: "",
    138: "",
    139: "",
    140: "",
    141: "",
    142: "",
    143: "",
    144: "",
    145: "",
    146: "",
    147: "",
    148: "",
    149: "",
    150: "",
    151: "",
    152: "",
    153: "",
    154: "",
    155: "",
    156: "",
    157: "",
    158: "",
    159: "",
    160: "",
    161: "",
    162: "",
    163: "",
    164: "",
    165: "",
    166: "",
    167: "",
    168: "",
    169: "",
    170: "",
    171: "",
    172: "",
    173: "",
    174: "",
    175: "",
    176: "",
    177: "",
    178: "",
    179: "",
    180: "",
    181: "",
    182: "",
    183: "",
    184: "",
    185: "",
    186: "",
    187: "",
    188: "",
    189: "",
    190: "",
    191: "",
    192: "",
    193: "",
    194: "",
    195: "",
    196: "",
    197: "",
    198: "",
    199: "",
    200: "",
    201: "",
    202: "",
    203: "",
    204: "",
    205: "",
    206: "",
    207: "",
    208: "",
    209: "",
    210: "",
    211: "",
    212: "",
    213: "",
    214: "",
    215: "",
    216: "",
    217: "",
    218: "",
    219: "",
    220: "",
    221: "",
    222: "",
    223: "",
    224: "",
    225: "",
    226: "",
    227: "",
    228: "",
    229: "",
    230: "",
    231: "",
    232: "",
    233: "",
    234: "",
    235: "",
    236: "",
    237: "",
    238: "",
    239: "",
    240: "",
    241: "",
    242: "",
    243: "",
    244: "",
    245: "",
    246: "",
    247: "",
    248: "",
    249: "",
    250: "",
    251: "",
    252: "",
    253: "",
    254: "",
    255: "",
    256: "",
    257: "",
    258: "",
    259: "",
    260: "",
    261: "",
    262: "",
    263: "",
    264: "",
    265: "",
    266: "",
    267: "",
    268: "",
    269: "",
    270: ""
}
modding_elichika_path = "assets/package/card/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

encrypted_folder = "static/assets/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

def manipulate_file(data, keys_0, keys_1, keys_2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF

def calculate_parameter_value(min_value, max_value, min_level, max_level, level):
    # Calculate the range of levels
    level_range = max_level - min_level
    
    # Calculate the percentage of completion of the level range for the given level
    level_completion = (level - min_level) / level_range
    
    # Calculate the parameter value based on the percentage of completion
    parameter_value = int(min_value + (max_value - min_value) * level_completion)
    
    return parameter_value

# Function to generate a unique costume_id_masterdata
            
def generate_unique_card_id(cursor):
    while True:
        new_id_card = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_card WHERE id = ?;", (new_id_card,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_card
            
def generate_unique_storyside_id(cursor):
    while True:
        new_id_cardcc = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_story_side WHERE id = ?;", (new_id_cardcc,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_cardcc
            
def generate_unique_storyside2_id(cursor):
    while True:
        new_id_cardcc2 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_story_side WHERE id = ?;", (new_id_cardcc2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_cardcc2
                        
def generate_unique_activeskill_1_id(cursor):
    while True:
        new_id_acskill1 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", (new_id_acskill1,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill1

def generate_unique_activeskill_2_id(cursor):
    while True:
        new_id_acskill2 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", (new_id_acskill2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill2
            
def generate_unique_activeskill_3_id(cursor):
    while True:
        new_id_acskill3 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", (new_id_acskill3,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill3
            
def generate_unique_activeskill_4_id(cursor):
    while True:
        new_id_acskill4 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", (new_id_acskill4,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill4
            
def generate_unique_activeskill_5_id(cursor):
    while True:
        new_id_acskill5 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_active_skill WHERE id = ?;", (new_id_acskill5,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill5
            
def generate_unique_activeskill_b1_id(cursor):
    while True:
        new_id_acskill1b = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill1b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill1b

def generate_unique_activeskill_b2_id(cursor):
    while True:
        new_id_acskill2b = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill2b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill2b
            
def generate_unique_activeskill_b3_id(cursor):
    while True:
        new_id_acskill3b = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill3b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill3b
            
def generate_unique_activeskill_b4_id(cursor):
    while True:
        new_id_acskill4b = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill4b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill4b
            
def generate_unique_activeskill_b5_id(cursor):
    while True:
        new_id_acskill5b = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill5b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill5b
            
def generate_unique_activeskill_ab1_id(cursor):
    while True:
        new_id_acskill5ba = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_passive_skill WHERE id = ?;", (new_id_acskill5ba,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_acskill5ba

def generate_unique_trade_id(cursor):
    while True:
        new_id333 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_trade_product WHERE id = ?;", (new_id333,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id333
            
def generate_unique_trade_content_id(cursor):
    while True:
        new_id3334 = random.randint(0, 20000000000)
        cursor.execute("SELECT COUNT(*) FROM main.m_trade_product_content WHERE id = ?;", (new_id3334,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id3334
            
def costume_path_randomhash(cursor):
    while True:
        new_hash1 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.member_model WHERE asset_path = ?;", (new_hash1,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash1
            
def thumbnail_path_randomhash(cursor):
    while True:
        new_hash2 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash2
            
def rinaunmask_path_randomhash(cursor):
    while True:
        new_hash3 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash3,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash3

def image_card_path_randomhash(cursor):
    while True:
        new_hash4 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash4,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash4

def thumbnail_card_path_randomhash(cursor):
    while True:
        new_hash5 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash5,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash5
            
def still_card_path_randomhash(cursor):
    while True:
        new_hash6 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash6,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash6
            
def deck_card_path_randomhash(cursor):
    while True:
        new_hash7 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash7,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash7
            
def image_card_awaken_path_randomhash(cursor):
    while True:
        new_hash4aw = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash4aw,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash4aw

def thumbnail_card_awaken_path_randomhash(cursor):
    while True:
        new_hash5aw = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash5aw,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash5aw
            
def still_card_awaken_path_randomhash(cursor):
    while True:
        new_hash6aw = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash6aw,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash6aw
            
def deck_card_awaken_path_randomhash(cursor):
    while True:
        new_hash7aw = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash7aw,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash7aw
# explorer code
clear_terminal()
temp_directory = "assets/package/.cache/"
shutil.rmtree(temp_directory, ignore_errors=True)

# List all files in the directory with a ".zip" extension
zip_files = [file for file in os.listdir(modding_elichika_path) if file.endswith(".zip")]

# Display the available zip files with corresponding numbers
print("Available .zip files:")
for i, zip_file in enumerate(zip_files, start=1):
    print(f"{i}. {zip_file}")

# User input to choose a zip file by entering a number
try:
    chosen_number = int(input("Enter the number corresponding to the .zip file you want to choose: "))
    
    # Check if the chosen number is valid
    if 1 <= chosen_number <= len(zip_files):
        chosen_zip_file = zip_files[chosen_number - 1]
        zip_file_path = os.path.join(modding_elichika_path, chosen_zip_file)
        print(f"You chose: {zip_file_path}")
        # Now you can work with the chosen zip file as needed
    else:
        print("Invalid number. Please enter a valid number.")
        sys.exit(1)
except ValueError:
    print("Invalid input. Please enter a number.")
    sys.exit(1)
    
os.makedirs(temp_directory, exist_ok=True)
with open(zip_file_path, 'rb') as zip_file:
    zip_data = zip_file.read()
    
zip_buffer = io.BytesIO(zip_data)

    # Create a ZipFile object
with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
        # Extract all files to the temp directory
    zip_ref.extractall(temp_directory)

        # Iterate through the contents of the ZIP file
    for file_info in zip_ref.infolist():
            # Check if the file has a .txt extension
        if file_info.filename.endswith('.txt'):
                # Open and process the .txt file
            txt_file_path = os.path.join(temp_directory, file_info.filename)
            with open(txt_file_path, 'r', encoding='utf-8') as txt_file:
                    # Read and process each line in the extracted file
                for line in txt_file:
                    exec(line)




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

clear_terminal()
print('Name: ' + card_name_en)
if chara_id == 1:
    print('Chara: Honoka Kousaka')
elif chara_id == 2:
    print('Chara: Eli Ayase')
elif chara_id == 3:
    print('Chara: Kotori Minami')
elif chara_id == 4:
    print('Chara: Umi Sonoda')
elif chara_id == 5:
    print('Chara: Rin Hoshizora')
elif chara_id == 6:
    print('Chara: Maki Nishikino')
elif chara_id == 7:
    print('Chara: Nozomi Tojo')
elif chara_id == 8:
    print('Chara: Hanayo Koizumi')
elif chara_id == 9:
    print('Chara: Nico Yazawa')
elif chara_id == 101:
    print('Chara: Chika Takami')
elif chara_id == 102:
    print('Chara: Riko Sakurauchi')
elif chara_id == 103:
    print('Chara: Kanan Matsuura')
elif chara_id == 104:
    print('Chara: Dia Kurosawa')
elif chara_id == 105:
    print('Chara: You Watanabe')
elif chara_id == 106:
    print('Chara: Yoshiko Tsushima')
elif chara_id == 107:
    print('Chara: Hanamaru Kunikida')
elif chara_id == 108:
    print('Chara: Mari Ohara')
elif chara_id == 109:
    print('Chara: Ruby Kurosawa')
elif chara_id == 201:
    print('Chara: Ayumu Uehara')
elif chara_id == 202:
    print('Chara: Kasumi Nakasu')
elif chara_id == 203:
    print('Chara: Shizuku Osaka')
elif chara_id == 204:
    print('Chara: Karin Asaka')
elif chara_id == 205:
    print('Chara: Ai Miyashita')
elif chara_id == 206:
    print('Chara: Kanata Konoe')
elif chara_id == 207:
    print('Chara: Setsuna Yuki')
elif chara_id == 208:
    print('Chara: Emma Verde')
elif chara_id == 209:
    print('Chara: Rina Tennoji')
elif chara_id == 210:
    print('Chara: Shioriko Mifune')
elif chara_id == 212:
    print('Chara: Lanzhu Zhong')
elif chara_id == 211:
    print('Chara: Mia Taylor')
    
if chara_id_group == 13:
    print('Group: Myuzu')
elif chara_id_group == 14:
    print('Group: Aqours')
elif chara_id_group == 15:
    print('Group: Nijigasaki')
print('Description: ' + card_description)
do_you_think_want_add_this = input("do you want add this? (y/n): ")

if do_you_think_want_add_this == "y" :
    clear_terminal()
else :
    clear_terminal()
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)    

do_backup_is_important = input("would you like backup database? (y/n): ")
if do_backup_is_important == "y" :
    backup_operate(filelist)
else :
    print('well then do your own risk')
    
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
# Replace with actual method to get filesize
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
    start_encrypt3 = temp_directory + rina_unmask_costume_file
    rina_unmask_costume_filename = os.path.splitext(rina_unmask_costume_file.split("/")[-1])[0]
    rina_unmask_costume_filesize = os.path.getsize(rina_unmask_costume_file)
    encrypted_rina_unmask = "static/assets/" + os.path.splitext(rina_unmask_costume_file.split("/")[-1])[0]

    if not rina_unmask_costume_filename.isalnum() or not rina_unmask_costume_filename.islower():
        print('Invalid Rina Unmasked Costume Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)  

if not os.path.exists(encrypted_costume):
    with open(start_encrypt1, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting costume")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_costume, "wb") as file:
            file.write(data)
else:
    print("costume already encrypted")

if not os.path.exists(encrypted_thumbnail):
    with open(start_encrypt2, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting thumbnail")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_thumbnail, "wb") as file:
            file.write(data)
else:
    print("thumbnail already encrypted")

if chara_id == 209:
    if not os.path.exists(encrypted_rina_unmask):
        with open(start_encrypt3, "rb") as file:
            data = bytearray(file.read())

            key_0 = 12345
            key_1 = 0
            key_2 = 0
            print("encrypting rina unmask costume")
            manipulate_file(data, key_0, key_1, key_2)

            with open(encrypted_rina_unmask, "wb") as file:
                file.write(data)
    else:
        print("rina unmask costume already encrypted")

if not os.path.exists(encrypted_card):
    with open(start_encrypt6, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting card")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card, "wb") as file:
            file.write(data)
else:
    print("card already encrypted")
    
if not os.path.exists(encrypted_card_thumbnail):
    with open(start_encrypt7, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting card thumbnail")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_thumbnail, "wb") as file:
            file.write(data)
else:
    print("card thumbnail already encrypted")
    
if not os.path.exists(encrypted_card_still):
    with open(start_encrypt8, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting card still")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_still, "wb") as file:
            file.write(data)
else:
    print("card still already encrypted")
    
if not os.path.exists(encrypted_card_deck):
    with open(start_encrypt9, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting card deck")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_deck, "wb") as file:
            file.write(data)
else:
    print("card deck already encrypted")
    
if not os.path.exists(encrypted_card_awaken):
    with open(start_encrypt10, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting awaken card")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_awaken, "wb") as file:
            file.write(data)
else:
    print("awaken card already encrypted")
    
if not os.path.exists(encrypted_card_awaken_thumbnail):
    with open(start_encrypt11, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting awaken card thumbnail")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_awaken_thumbnail, "wb") as file:
            file.write(data)
else:
    print("awaken card thumbnail already encrypted")
    
if not os.path.exists(encrypted_card_awaken_still):
    with open(start_encrypt12, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting awaken card still")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_awaken_still, "wb") as file:
            file.write(data)
else:
    print("awaken card still already encrypted")
    
if not os.path.exists(encrypted_card_awaken_deck):
    with open(start_encrypt13, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        print("encrypting awaken card deck")
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_card_awaken_deck, "wb") as file:
            file.write(data)
else:
    print("awaken card deck already encrypted")

def read_file_and_select_text(start_encrypt4):
    with open(start_encrypt4, 'rb') as file:
        # Seek to the decimal offset 1438
        file.seek(1438)

        selected_text_deretote = b''  # Use bytes for binary reading

        while True:
            # Read one byte
            byte = file.read(1)

            # Check if the byte is the hex value 00
            if byte == b'\x00':
                break  # Stop reading if hex 00 is found

            selected_text_deretote += byte

        # Print the selected text
        return selected_text_deretote.decode('utf-8')
        
def read_file_and_select_text1(start_encrypt5):
    with open(start_encrypt5, 'rb') as file:
        # Seek to the decimal offset 1438
        file.seek(1438)

        selected_text_deretote = b''  # Use bytes for binary reading

        while True:
            # Read one byte
            byte = file.read(1)

            # Check if the byte is the hex value 00
            if byte == b'\x00':
                break  # Stop reading if hex 00 is found

            selected_text_deretote += byte

        # Print the selected text
        return selected_text_deretote.decode('utf-8')

print("assets encrypted")
shutil.copy(start_encrypt4, active_skill_voice_filename_saved)
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()
        
    sheet_name_file = read_file_and_select_text(start_encrypt4)
    costume_path = costume_path_randomhash(cursor)
    card_path = image_card_path_randomhash(cursor)
    card_thumbnail_path = thumbnail_card_path_randomhash(cursor)
    card_still_path = still_card_path_randomhash(cursor)
    card_deck_path = deck_card_path_randomhash(cursor)
    card_awaken_path = image_card_awaken_path_randomhash(cursor)
    card_awaken_thumbnail_path = thumbnail_card_awaken_path_randomhash(cursor)
    card_awaken_still_path = still_card_awaken_path_randomhash(cursor)
    card_awaken_deck_path = deck_card_awaken_path_randomhash(cursor)
    thumbnail_costume_path = thumbnail_path_randomhash(cursor)
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                    (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, active_skill_voice_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (active_skill_voice_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_thumbnail_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_still_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_deck_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_awaken_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_awaken_thumbnail_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_awaken_still_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_awaken_deck_filename,))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_path, card_filename, card_filesize))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_deck_path, card_deck_filename, card_deck_filesize))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_thumbnail_path, card_thumbnail_filename, card_thumbnail_filesize))   
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_still_path, card_still_filename, card_still_filesize))         
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_awaken_path, card_awaken_filename, card_awaken_filesize))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_awaken_deck_path, card_awaken_deck_filename, card_awaken_deck_filesize))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_awaken_thumbnail_path, card_awaken_thumbnail_filename, card_awaken_thumbnail_filesize))   
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (card_awaken_still_path, card_awaken_still_filename, card_awaken_still_filesize))
    
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        sheet_name_file1 = read_file_and_select_text1(start_encrypt5)
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
        rina_unmask_costume_path = rinaunmask_path_randomhash(cursor)
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
 
    if chara_id == 1:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '{#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Q9');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'aE');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 2:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '.]');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '8C');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'k?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 3:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'g4');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'T1');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'v');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 4:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'M!');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '_|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 't$');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 5:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '!{');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?A');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'M_');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 6:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '1Q');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'YS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '~Y');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 7:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'J9');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'L_');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '}x');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 8:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'BX');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '[*');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'dR');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 9:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Z7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'C{');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '#s');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 101:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '5]');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '85');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'MS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 102:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Bz');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'F$');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0*');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 103:
        fix_kanan_dep = "'x"
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '(A');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 't~');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 104:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '.q');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Iu');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'x=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 105:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'iy');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'jo');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'lR');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 106:
        fix_yoshiko_dep = "Z'"
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Wm');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_yoshiko_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'di');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 107:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '2*');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ';L');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'B*');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^5');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '_v');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 109:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'p2');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'a|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'U}');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 201:
        fix_ayumu_dep = ".'"
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'f%');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sq');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 202:
        fix_kasukasu_dep = '"{'
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kasukasu_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '_K');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'uK');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 203:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^g');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'bS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '#M');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 204:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '7,');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Aa');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'io');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 205:
        fix_ai_dep = '("'
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ai_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '1]');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'a+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 206:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ')#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'LB');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Si');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 207:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '8m');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'fl');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '(Q');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 208:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'g_');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'dE');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '28');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 209:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'ID');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'wS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Z$');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'xU');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ';k');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (rina_unmask_costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (rina_unmask_costume_path,))
    elif chara_id == 210:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        fix_mia_dep = 'w";'
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

# REST CODE TO GL CLIENT & IOS PLATFORM
## need redone

# Connect to masterdata.db and perform INSERT
with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
    cursor = conn.cursor()

    # Generate a unique costume_id_masterdata
    trade_content_into_json = generate_unique_trade_content_id(cursor)
    trade_id_into_json = generate_unique_trade_id(cursor)
    card_id_masterdata = generate_unique_card_id(cursor)
    min_level_card = 1
    max_level_card = 100
    
    # m_active_skill
    active_skill_1_masterdata = generate_unique_activeskill_1_id(cursor)
    active_skill_2_masterdata = generate_unique_activeskill_2_id(cursor)
    active_skill_3_masterdata = generate_unique_activeskill_3_id(cursor)
    active_skill_4_masterdata = generate_unique_activeskill_4_id(cursor)
    active_skill_5_masterdata = generate_unique_activeskill_5_id(cursor)
    active_skill_dictionary_masterdata = "k.active_skill_name_" + str(card_id_masterdata)
    active_skill_dictionary_desc1_masterdata = "k.active_skill_description_" + str(card_id_masterdata) + "_1"
    active_skill_dictionary_desc2_masterdata = "k.active_skill_description_" + str(card_id_masterdata) + "_2"
    active_skill_dictionary_desc3_masterdata = "k.active_skill_description_" + str(card_id_masterdata) + "_3"
    active_skill_dictionary_desc4_masterdata = "k.active_skill_description_" + str(card_id_masterdata) + "_4"
    active_skill_dictionary_desc5_masterdata = "k.active_skill_description_" + str(card_id_masterdata) + "_5"
    active_skill_dictionary = "active_skill_name_" + str(card_id_masterdata)
    active_skill_dictionary_desc1 = "active_skill_description_" + str(card_id_masterdata) + "_1"
    active_skill_dictionary_desc2 = "active_skill_description_" + str(card_id_masterdata) + "_2"
    active_skill_dictionary_desc3 = "active_skill_description_" + str(card_id_masterdata) + "_3"
    active_skill_dictionary_desc4 = "active_skill_description_" + str(card_id_masterdata) + "_4"
    active_skill_dictionary_desc5 = "active_skill_description_" + str(card_id_masterdata) + "_5"
    # todo : match icon same as behavior
    # are these id correct?
    
    # -- Skill Icon --
    ## Appeal Buff
    if active_skill_effect_type == 17:
        cactive_skill_icon = "K9"
    elif active_skill_effect_type == 119:
        cactive_skill_icon = "K9"
    elif active_skill_effect_type == 121:
        cactive_skill_icon = "K9"
    elif active_skill_effect_type == 123:
        cactive_skill_icon = "K9"
    elif active_skill_effect_type == 125:
        cactive_skill_icon = "K9"
    else:
        # use lock icon if no available
        cactive_skill_icon = "+H"
        
    if rarity_card == "SR":
        cactive_sp_point = 150
        cactive_chance_percent = 3000
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cactive_sp_point = 200
        cactive_chance_percent = 3300
        
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_1_masterdata, active_skill_type, active_skill_1_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_2_masterdata, active_skill_type, active_skill_2_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_3_masterdata, active_skill_type, active_skill_3_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_4_masterdata, active_skill_type, active_skill_4_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_5_masterdata, active_skill_type, active_skill_5_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, cactive_sp_point, cactive_chance_percent, donot_insert, cactive_skill_icon))
    ## dual skill not supported yet
    cactive_skill_evaluation2_logic = active_skill_evaluation + active_skill_evaluation_step_even_up
    cactive_skill_evaluation3_logic = active_skill_evaluation + active_skill_evaluation_step_even_up + active_skill_evaluation_step_odd_up
    cactive_skill_evaluation4_logic = active_skill_evaluation + active_skill_evaluation_step_even_up + active_skill_evaluation_step_odd_up + active_skill_evaluation_step_even_up
    cactive_skill_evaluation5_logic = active_skill_evaluation + active_skill_evaluation_step_even_up + active_skill_evaluation_step_odd_up + active_skill_evaluation_step_even_up + active_skill_evaluation_step_odd_up
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_1_masterdata, active_skill_evaluation, active_skill_target_id1, donot_insert, active_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_2_masterdata, cactive_skill_evaluation2_logic, active_skill_target_id1, donot_insert, active_skill_2_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_3_masterdata, cactive_skill_evaluation3_logic, active_skill_target_id1, donot_insert, active_skill_3_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_4_masterdata, cactive_skill_evaluation4_logic, active_skill_target_id1, donot_insert, active_skill_4_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_5_masterdata, cactive_skill_evaluation5_logic, active_skill_target_id1, donot_insert, active_skill_5_masterdata, donot_insert))
    cactive_skill_logic_effect2 = active_skill_effect_value + active_skill_effect_value_step_up * 1
    cactive_skill_logic_effect3 = active_skill_effect_value + active_skill_effect_value_step_up * 2
    cactive_skill_logic_effect4 = active_skill_effect_value + active_skill_effect_value_step_up * 3
    cactive_skill_logic_effect5 = active_skill_effect_value + active_skill_effect_value_step_up * 4
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (active_skill_1_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, active_skill_effect_value, active_skill_effect_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (active_skill_2_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect2, active_skill_effect_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (active_skill_3_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect3, active_skill_effect_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (active_skill_4_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect4, active_skill_effect_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '2', ?, ?, ?);", (active_skill_5_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect5, active_skill_effect_calculation_type, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    # m_passive_skill
    passive_skill_1_masterdata = generate_unique_activeskill_b1_id(cursor)
    passive_skill_2_masterdata = generate_unique_activeskill_b2_id(cursor)
    passive_skill_3_masterdata = generate_unique_activeskill_b3_id(cursor)
    passive_skill_4_masterdata = generate_unique_activeskill_b4_id(cursor)
    passive_skill_5_masterdata = generate_unique_activeskill_b5_id(cursor)
    passive_skill_ab1_masterdata = generate_unique_activeskill_ab1_id(cursor)
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
    # skill icon not implemented
    cpassive_skill_icon = "+H"
    cpassive_ability_skill_icon = "+H"
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_1_masterdata, passive_skill_dictionary_masterdata_1, passive_skill_dictionary_desc1_masterdata, passive_skill_1_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_2_masterdata, passive_skill_dictionary_masterdata_2, passive_skill_dictionary_desc2_masterdata, passive_skill_2_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_3_masterdata, passive_skill_dictionary_masterdata_3, passive_skill_dictionary_desc3_masterdata, passive_skill_3_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_4_masterdata, passive_skill_dictionary_masterdata_4, passive_skill_dictionary_desc4_masterdata, passive_skill_4_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, '255', '10000', '1', ?);", (passive_skill_5_masterdata, passive_skill_dictionary_masterdata_5, passive_skill_dictionary_desc5_masterdata, passive_skill_5_masterdata, donot_insert, cpassive_skill_icon, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_dictionary_masterdata_ab1, passive_skill_dictionary_desc1ab_masterdata, passive_skill_ab1_masterdata, donot_insert, cpassive_ability_skill_icon, passive_skill_ability_trigger_type, passive_skill_ability_chance_percent, passive_skill_ability_condition_id1, donot_insert))
    
    cpassive_skill_evaluation2_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up
    cpassive_skill_evaluation3_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up
    cpassive_skill_evaluation4_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up + passive_skill_evaluation_step_even_up
    cpassive_skill_evaluation5_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_1_masterdata, passive_skill_evaluation, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_2_masterdata, cpassive_skill_evaluation2_logic, passive_skill_target_id1, donot_insert, passive_skill_2_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_3_masterdata, cpassive_skill_evaluation3_logic, passive_skill_target_id1, donot_insert, passive_skill_3_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_4_masterdata, cpassive_skill_evaluation4_logic, passive_skill_target_id1, donot_insert, passive_skill_4_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_5_masterdata, cpassive_skill_evaluation5_logic, passive_skill_target_id1, donot_insert, passive_skill_5_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_ability_evaluation, passive_skill_ability_target_id1, donot_insert, passive_skill_ab1_masterdata, donot_insert))
    cpassive_skill_logic_effect2 = passive_skill_effect_value + passive_skill_effect_value_step_up * 1
    cpassive_skill_logic_effect3 = passive_skill_effect_value + passive_skill_effect_value_step_up * 2
    cpassive_skill_logic_effect4 = passive_skill_effect_value + passive_skill_effect_value_step_up * 3
    cpassive_skill_logic_effect5 = passive_skill_effect_value + passive_skill_effect_value_step_up * 4
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_1_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, passive_skill_effect_value, passive_skill_effect_calculation_type, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_2_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect2, passive_skill_effect_calculation_type, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_3_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect3, passive_skill_effect_calculation_type, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_4_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect4, passive_skill_effect_calculation_type, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_5_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect5, passive_skill_effect_calculation_type, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, '2', ?, '1', ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_ability_effect_target_parameter, passive_skill_ability_effect_type, passive_skill_ability_effect_value, passive_skill_ability_effect_calculation_type, donot_insert, passive_skill_ability_effect_finish_type, passive_skill_ability_effect_finish_value))
    
    # m_card
    if rarity_card == "SR":
        caddon_rarity = 20
        caddon_sp = 2
        caddon_exchange_item_id = 2
        caddon_passive_slot = 1
        caddon_passive_slot_max = 3
    elif rarity_card == "UR":
        caddon_rarity = 30
        caddon_sp = 3
        caddon_exchange_item_id = 3
        caddon_passive_slot = 1
        caddon_passive_slot_max = 3
    elif rarity_card == "FES" or rarity_card == "PARTY":
        caddon_rarity = 30
        caddon_sp = 4
        caddon_exchange_item_id = 3
        caddon_passive_slot = 2
        caddon_passive_slot_max = 4
        
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
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '1', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_1_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '2', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_2_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '3', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_3_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '4', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_4_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '5', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_5_masterdata))
    
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
    offset_x_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_x * 10000)
    offset_y_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_y * 10000)
    rotation_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_rotation * 1000)
    scale_normal_logic_cutin = int(card_normal_trimming_live_cutin_offset_scale * 100)
    offset_x_awaken_logic_cutin = int(card_normal_trimming_live_cutin_offset_x * 10000)
    offset_y_awaken_logic_cutin = int(card_normal_trimming_live_cutin_offset_y * 10000)
    rotation_awaken_logic_cutin = int(card_normal_trimming_live_cutin_offset_rotation * 1000)
    scale_awaken_logic_cutin = int(card_normal_trimming_live_cutin_offset_scale * 100)
    cursor.execute("INSERT INTO main.m_card_trimming_live_cutin (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '1', ?, ?, ?, ?);", (card_id_masterdata, offset_x_normal_logic_cutin, offset_y_normal_logic_cutin, rotation_normal_logic_cutin, scale_normal_logic_cutin))
    cursor.execute("INSERT INTO main.m_card_trimming_live_cutin (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '2', ?, ?, ?, ?);", (card_id_masterdata, offset_x_awaken_logic_cutin, offset_y_awaken_logic_cutin, rotation_awaken_logic_cutin, scale_awaken_logic_cutin))
    
    # m_card_trimming_profile
    offset_x_normal_logic_trimming = int(card_normal_trimming_profile_offset_x * 10000)
    scale_normal_logic_trimming = int(card_normal_trimming_profile_offset_scale * 1000)
    offset_x_awaken_logic_trimming = int(card_awaken_trimming_profile_offset_x * 10000)
    scale_awaken_logic_trimming = int(card_awaken_trimming_profile_offset_scale * 1000)
    cursor.execute("INSERT INTO main.m_card_trimming_profile (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '1', ?, '0', '0', ?);", (card_id_masterdata, offset_x_normal_logic_trimming, scale_normal_logic_trimming))
    cursor.execute("INSERT INTO main.m_card_trimming_profile (card_m_id, appearance_type, offset_x, offset_y, rotation, scale) VALUES (?, '2', ?, '0', '0', ?);", (card_id_masterdata, offset_x_awaken_logic_trimming, scale_awaken_logic_trimming))
    
    # m_skill_effect_value_count
    ## do i know what is this used on?
    if passive_skill_effect_type in [9999, 99999]:
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (active_skill_1_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (active_skill_2_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (active_skill_3_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (active_skill_4_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (active_skill_5_masterdata))
    if active_skill_effect_type in [9999, 99999]:
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (passive_skill_1_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (passive_skill_2_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (passive_skill_3_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (passive_skill_4_masterdata))
        cursor.execute("INSERT INTO main.m_skill_effect_value_count (id, target_count, effect_value) VALUES (?, 0, 0);", (passive_skill_5_masterdata))
    
    # m_card_awaken_parameter
    cursor.execute("INSERT INTO main.m_card_awaken_parameter (card_master_id, parameter1, parameter2, parameter3) VALUES (?, ?, ?, ?);", (card_id_masterdata, card_training_tree_awaken_appeal, card_training_tree_awaken_stamina, card_training_tree_awaken_technique))
    
    # m_card_passive_skill_original
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '1', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_1, passive_skill_1_masterdata))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '2', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_2, passive_skill_2_masterdata))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '3', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_3, passive_skill_3_masterdata))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '4', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_4, passive_skill_4_masterdata))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '5', '1', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_5, passive_skill_5_masterdata))
    cursor.execute("INSERT INTO main.m_card_passive_skill_original (card_master_id, skill_level, position, name, passive_skill_master_id) VALUES (?, '1', '2', ?, ?);", (card_id_masterdata, passive_skill_dictionary_masterdata_ab1, passive_skill_ab1_masterdata))
    # m_card_grade_up_item
    if rarity_card == "SR":
        caddon_grade_up_val1 = 25
        caddon_grade_up_val2 = 10
    elif rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        caddon_grade_up_val1 = 125
        caddon_grade_up_val2 = 30
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '1', '13', '1800', ?);", (card_id_masterdata, caddon_grade_up_val1))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '2', '13', '1800', ?);", (card_id_masterdata, caddon_grade_up_val1))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '3', '13', '1800', ?);", (card_id_masterdata, caddon_grade_up_val1))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '4', '13', '1800', ?);", (card_id_masterdata, caddon_grade_up_val1))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '5', '13', '1800', ?);", (card_id_masterdata, caddon_grade_up_val1))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '1', '13', '1805', ?);", (card_id_masterdata, caddon_grade_up_val2))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '2', '13', '1805', ?);", (card_id_masterdata, caddon_grade_up_val2))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '3', '13', '1805', ?);", (card_id_masterdata, caddon_grade_up_val2))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '4', '13', '1805', ?);", (card_id_masterdata, caddon_grade_up_val2))
    cursor.execute("INSERT INTO main.m_card_grade_up_item (card_id, grade, content_type, content_id, content_amount) VALUES (?, '5', '13', '1805', ?);", (card_id_masterdata, caddon_grade_up_val2))
    
    # m_card_parameter
    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, min_level_card, card_base_appeal, card_base_stamina, card_base_technique))
    for level in range(min_level_card + 1, max_level_card):
        appeal_rate = calculate_parameter_value(card_base_appeal, card_max_appeal, min_level_card, max_level_card, level)
        stamina_rate = calculate_parameter_value(card_base_stamina, card_max_stamina, min_level_card, max_level_card, level)
        technique_rate = calculate_parameter_value(card_base_technique, card_max_technique, min_level_card, max_level_card, level)
        cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, level, appeal_rate, stamina_rate, technique_rate))
    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, max_level_card, card_max_appeal, card_max_stamina, card_max_technique))
    
    # m_gacha_card_performance
    card_serif_dictionary_masterdata = "k.gacha" + str(sheet_name_file)
    card_serif_dictionary = "gacha" + str(sheet_name_file)
    if rarity_card == "UR":
        if chara_id == 1:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'uPV');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 2:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '\4,');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 3:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'q-!');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 4:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '*R+');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata)) 
        elif chara_id == 5:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'O]=');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 6:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'jGc');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 7:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'Kb@');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata)) 
        elif chara_id == 8:
            fix_hanayo_serif = '"HW'
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, ?);", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata, fix_hanayo_serif))
        elif chara_id == 9:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'evO');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 101:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '\P:');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 102:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'CXl');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 103:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '0[0');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 104:
            fix_dia_serif = "'E]"
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, ?);", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata, fix_dia_serif)) 
        elif chara_id == 105:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '6]!');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 106:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'QkE');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 107:
            fix_maru_serif = '"de'
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, ?);", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata, fix_maru_serif)) 
        elif chara_id == 108:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '}:+');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 109:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'HVF');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 201:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '#.u');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 202:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '!JJ');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 203:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'ZpL');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 204:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '-Nb');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 205:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'jC.');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 206:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'a-[');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 207:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'L\;');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 208:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'EWP');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 209:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '/R9');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 210:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'GM:');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 211:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, 'XTG');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
        elif chara_id == 212:
            cursor.execute("INSERT INTO main.m_gacha_card_performance (card_master_id, voice, serif, sign_movie_asset_path) VALUES (?, ?, ?, '?>g');", (card_id_masterdata, sheet_name_file, card_serif_dictionary_masterdata))
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
    ctraining_tree_logic = str(ctraining_tree_design) + str(chara_id) + str(role_card)
    cursor.execute("INSERT INTO main.m_training_tree (id, training_tree_mapping_m_id, training_tree_card_param_m_id, training_tree_card_passive_skill_increase_m_id) VALUES (?, ?, ?, ?);", (card_id_masterdata, ctraining_tree_logic, card_id_masterdata, ctraining_tree_passive_increase))
    
    # m_training_tree_card_param
    ## not done, need wrote this for each, very BIG, based on tree & role card, many value incorrect, also lim not added
    if rarity_card == "SR":
        if role_card == 1:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique))
        elif role_card == 2:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique))
        elif role_card == 3:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique))
        elif role_card == 4:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique))
    elif rarity_card == "UR": # role 3 & 4 missing
        if role_card == 1:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '67', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '70', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '61', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '62', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '65', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '69', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '71', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '72', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '63', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '64', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '66', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '68', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique))
        elif role_card == 2:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '2', ?);", (card_id_masterdata, card_training_tree_cell1_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '63', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '64', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '66', '2', ?);", (card_id_masterdata, card_training_tree_cell2_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '68', '2', ?);", (card_id_masterdata, card_training_tree_cell3_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '3', ?);", (card_id_masterdata, card_training_tree_cell1_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '67', '3', ?);", (card_id_masterdata, card_training_tree_cell2_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '70', '3', ?);", (card_id_masterdata, card_training_tree_cell3_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '4', ?);", (card_id_masterdata, card_training_tree_cell1_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '61', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '62', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '65', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '69', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '71', '4', ?);", (card_id_masterdata, card_training_tree_cell2_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '72', '4', ?);", (card_id_masterdata, card_training_tree_cell3_technique)) 
    # m_training_tree_card_story_side
    ## will return as R character because there is no way to create new one
    story_side_id_masterdata = generate_unique_storyside_id(cursor)
    cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '11', '1', ?);", (card_id_masterdata, story_side_id_masterdata))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        story_side2_id_masterdata = generate_unique_storyside2_id(cursor)
        cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '9', '1', ?);", (card_id_masterdata, story_side2_id_masterdata))
        
    # m_training_tree_card_suit
    cursor.execute("INSERT INTO main.m_training_tree_card_suit (card_m_id, training_content_no, suit_m_id) VALUES (?, '1', ?);", (card_id_masterdata, card_id_masterdata))
    
    # m_training_tree_card_voice
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '1', '1001014');", (card_id_masterdata,))
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '2', '1001015');", (card_id_masterdata,))
    
    # m_training_tree_progress_reward
    ## will return as stargem, recolor costume currectly not implemented
    if rarity_card == "SR":
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '40', '0', '1', '0', '10');", (card_id_masterdata,))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '59', '0', '1', '0', '10');", (card_id_masterdata,))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '75', '0', '1', '0', '20');", (card_id_masterdata,))
    else:
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '46', '0', '1', '0', '10');", (card_id_masterdata,))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '69', '0', '1', '0', '10');", (card_id_masterdata,))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '87', '0', '1', '0', '20');", (card_id_masterdata,))
    # Insert record into the database
    # cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, '1200', '0', ?, '1');", (trade_id_into_json, donot_insert))
    
    # TRYING FIX SOFTLOCK
    ## m_story_side
    cursor.execute("SELECT MIN(display_order) FROM main.m_story_side WHERE member_m_id = ?;", (chara_id,))
    result_story = cursor.fetchone()
    min_display_order_ja_story = result_story[0] if result_story[0] is not None else 0

    # Calculate the new display_order (decrease by 1)
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

    # Calculate the new display_order (decrease by 1)
    display_order_new_ja = min_display_order_ja - 1
            
    # Costume insert
    cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '1', ?, ?, ?);",
                   (card_id_masterdata, chara_id, card_dictionary_masterdata_2, thumbnail_costume_path, card_id_masterdata, costume_path, display_order_new_ja))
    # can't trade, how i gonna do? SBL?
    # cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, '32500', '0', ?, '1');", (trade_id_into_json, donot_insert))
    # cursor.execute("INSERT INTO main.m_trade_product_content (id, trade_product_master_id, content_display_order) VALUES (?, ?, '0');", (trade_content_into_json, trade_id_into_json))
    # cursor.execute("INSERT INTO main.m_trade_product_content_category (trade_category_master_pattern_id, trade_category_master_id, content_type, content_id) VALUES (0, ?, '3', ?);", (chara_id_group, card_id_masterdata))
   
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (card_id_masterdata, rina_unmask_costume_path))

with sqlite3.connect('assets/db/jp/dictionary_ja_k.db') as conn:
    cursor = conn.cursor()
    # dynamic skill description is not implemented, please remember
    # convert value for information
    if active_skill_effect_type not in [2, 3, 4, 5, 23, 68, 70, 128, 130, 132, 134]:
        active_skill_effect_value = str(active_skill_effect_value / 1000) + "%"
        cactive_skill_logic_effect2 = str(cactive_skill_logic_effect2 / 1000) + "%"
        cactive_skill_logic_effect3 = str(cactive_skill_logic_effect3 / 1000) + "%"
        cactive_skill_logic_effect4 = str(cactive_skill_logic_effect4 / 1000) + "%"
        cactive_skill_logic_effect5 = str(cactive_skill_logic_effect5 / 1000) + "%"
        
    if passive_skill_effect_type not in [2, 3, 4, 5, 23, 68, 70, 128, 130, 132, 134]:
        passive_skill_effect_value = str(passive_skill_effect_value / 1000) + "%"
        cpassive_skill_logic_effect2 = str(cpassive_skill_logic_effect2 / 1000) + "%"
        cpassive_skill_logic_effect3 = str(cpassive_skill_logic_effect3 / 1000) + "%"
        cpassive_skill_logic_effect4 = str(cpassive_skill_logic_effect4 / 1000) + "%"
        cpassive_skill_logic_effect5 = str(cpassive_skill_logic_effect5 / 1000) + "%"
        
    if passive_skill_ability_effect_type not in [2, 3, 4, 5, 23, 68, 70, 128, 130, 132, 134]:
        passive_skill_ability_effect_value = str(passive_skill_ability_effect_value / 1000) + "%"
        
    en_active_skill_target = skill_target_dictionary_key_en.get(active_skill_target_id1)
    en_passive_skill_target = skill_target_dictionary_key_en.get(passive_skill_target_id1)
    en_passive_skill_ability_target = skill_target_dictionary_key_en.get(passive_skill_ability_target_id1)
    en_active_skill_finish_type = finish_type_dictionary_key_en.get(active_skill_effect_finish_type)
    en_passive_skill_finish_type = finish_type_dictionary_key_en.get(passive_skill_effect_finish_type)
    en_passive_skill_ability_finish_type = finish_type_dictionary_key_en.get(passive_skill_ability_effect_finish_type)
    en_passive_skill_condition_id1 = skill_condition_dictionary_key_en.get(passive_skill_condition_id1)
    en_passive_skill_ability_condition_id1 = skill_condition_dictionary_key_en.get(passive_skill_ability_condition_id1)
    en_passive_skill_trigger_type = passive_skill_trigger_type_dictionary_key_en.get(passive_skill_trigger_type)
    en_passive_skill_ability_trigger_type = passive_skill_trigger_type_dictionary_key_en.get(passive_skill_ability_trigger_type)
    en_passive_skill_ability_effect_type = effect_type_dictionary_key_en.get(passive_skill_ability_effect_type)
    
    active_skill1_desc_text_ja = f"{en_active_skill_target}"
    active_skill2_desc_text_ja = f"{en_active_skill_target}"
    active_skill3_desc_text_ja = f"{en_active_skill_target}"
    active_skill4_desc_text_ja = f"{en_active_skill_target}"
    active_skill5_desc_text_ja = f"{en_active_skill_target}"
    passive_skill1_desc_text_ja = f"{en_passive_skill_target}"
    passive_skill2_desc_text_ja = f"{en_passive_skill_target}"
    passive_skill3_desc_text_ja = f"{en_passive_skill_target}"
    passive_skill4_desc_text_ja = f"{en_passive_skill_target}"
    passive_skill5_desc_text_ja = f"{en_passive_skill_target}"
    effect_value_per_insert = passive_skill_ability_effect_value
    passive_skillab1_desc_text_ja = f"{en_passive_skill_ability_effect_type}\nCondition: {en_passive_skill_ability_condition_id1}{en_passive_skill_ability_trigger_type}\nChance: {passive_skill_ability_chance_percent}%{en_passive_skill_ability_target}"
    passive_skill1_name_text_ja = ""
    passive_skill2_name_text_ja = ""
    passive_skill3_name_text_ja = ""
    passive_skill4_name_text_ja = ""
    passive_skill5_name_text_ja = ""
    passive_skillab1_name_text_ja = ""
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_dictionary_1, card_name_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_dictionary_2, card_name_awaken_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_hiragana_dictionary_1, card_name_hiragana_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_hiragana_dictionary_2, card_name_awaken_hiragana_ja))
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (card_serif_dictionary, card_gacha_serif_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary_desc1, active_skill1_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary_desc2, active_skill2_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary_desc3, active_skill3_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary_desc4, active_skill4_desc_text_ja))    
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary_desc5, active_skill5_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc1, passive_skill1_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc2, passive_skill2_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc3, passive_skill3_desc_text_ja))          
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc4, passive_skill4_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc5, passive_skill5_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_desc1ab, passive_skillab1_desc_text_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (active_skill_dictionary, active_skill_name_ja))    
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_1, passive_skill1_name_text_ja))    
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_2, passive_skill2_name_text_ja))  
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_3, passive_skill3_name_text_ja))  
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_4, passive_skill4_name_text_ja))  
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_5, passive_skill5_name_text_ja))  
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (passive_skill_dictionary_ab1, passive_skillab1_name_text_ja))  
    
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
        client_gacha_json = json.loads(row[0])  # Convert JSON string to Python dictionary
        client_gacha_json['card_master_id'] = card_id_masterdata  # Update the card_master_id
        updated_client_gacha = json.dumps(client_gacha_json)  # Convert Python dictionary to JSON string

        # Update the row with the modified JSON data
        cursor.execute(update_query, (updated_client_gacha, gacha_master_id))
        
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
        
   # json_data_costume = [{
  #  "content_type": 3,
  #  "content_id": card_id_masterdata,
  #  "content_amount": 1
  #  }]
    #json_string_costume = json.dumps(json_data_costume)

    #cursor.execute("INSERT INTO main.s_trade_product (product_id, trade_id, source_amount, stock_amount, contents) VALUES (?, '1200', ?, 'null', ?);", (trade_id_into_json, costume_price_val, json_string_costume))
    print("added to gold exchange shop")

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
    if rarity_card == "UR" or rarity_card == "FES" or rarity_card == "PARTY":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_filename, card_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_thumbnail_filename, card_thumbnail_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_still_filename, card_still_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_deck_filename, card_deck_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_filename, card_awaken_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_thumbnail_filename, card_awaken_thumbnail_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_still_filename, card_awaken_still_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_deck_filename, card_awaken_deck_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                    (package_key_thumbnail, active_skill_voice_filename, active_skill_voice_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                    (package_key_thumbnail, card_gacha_voice_filename, card_gacha_voice_filesize, donot_insert))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main, update_main_asset_ur))
    else:
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_filename, card_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_thumbnail_filename, card_thumbnail_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_still_filename, card_still_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_deck_filename, card_deck_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_filename, card_awaken_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_thumbnail_filename, card_awaken_thumbnail_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_still_filename, card_awaken_still_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, card_awaken_deck_filename, card_awaken_deck_filesize, donot_insert, category_thumbnail))
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                    (package_key_thumbnail, active_skill_voice_filename, active_skill_voice_filesize, donot_insert))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main, update_main_asset))

print("deleting temp folder")
shutil.rmtree(temp_directory, ignore_errors=True)

with open(check_json_config, 'r') as f:
    config_elichika = json.load(f)
    if config_elichika.get('cdn_server') != "http://127.0.0.1:8080/static":
        config_elichika['cdn_server'] = "http://127.0.0.1:8080/static"
        with open(check_json_config, 'w') as f:
            json.dump(config_elichika, f, indent=4)
            print("CDN server updated to http://127.0.0.1:8080/static")
            
print("FINISHED")