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

# Example usage:
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
    "userdata.db"
]

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
	# 1 - Smile
	# 2 - Pure
	# 3 - Cool
	# 4 - Active
	# 5 - Natural
	# 6 - Elegant
	# 9 - Untyped / Unknown

note_emit_msec_easy = 3620
note_stamina_damage_easy = 100
evaluation_score_easy = None

note_emit_msec_normal = 3077
note_stamina_damage_normal = 200
evaluation_score_normal = None

note_emit_msec_hard = 2534
note_stamina_damage_hard = 300
evaluation_score_hard = None

# template Appeal Chance
# make sure start & end note_type is 1

# mission_type list
# 1 - GotVoltage | Gain Voltage! (x)
# 2 - JudgeSuccessGood | Get Nice or above (x) times!
# 3 - JudgeSuccessGreat | Get Great or above (x) times!
# 4 - JudgeSuccessPerfect | Get (x) Wonderfuls! 
# 5 - MaxVoltage | Get Voltage in one go!
# 6 - TriggerSp | Get (x) with an SP Skill!
# 7 - UseCardUniq | Switch strategies and Appeal with (x) members!
# 8 - CriticalCount | Get a critical: x(x)
# 9 - ActiveSkillCount | Activate a skill: x(x)
# 10 - GotHeal | Gain Stamina! (x) *unused
# 11 - GotShield | Gain Shield! (x) *unused
# 12 - GotVoltageByVo | Gain Voltage by Vo Card! (x) *unused
# 13 - GotVoltageBySp | Gain Voltage by Sp Card! (x) *unused
# 14 - GotVoltageByGd | Gain Voltage by Gd Card! (x) *unused
# 15 - GotVoltageBySk | Gain Voltage by Sk Card! (x) *unused
# 16 - KeepStaminaUpper | Maintain at least %(x) of your total Stamina, math arg_1 : (x) * 100

appeal_chance_easy = None
appeal_chance_normal = None
appeal_chance_hard = None

# entry format in int [note_start, note_end, mission_type, arg_1, reward_voltage, wave_damage]
# uncomment this if you want use it

# appeal_chance_easy = [
    # [11, 20, 16, 123, 267000, 9000],
    # [22, 30, 16, 456, 269000, 6000]
# ]

# appeal_chance_normal = [
    # [11, 20, 16, 123, 267000, 9000],
    # [22, 30, 16, 456, 269000, 6000]
# ]

# appeal_chance_hard = [
    # [11, 20, 16, 123, 267000, 9000],
    # [22, 30, 16, 456, 269000, 6000]
# ]

check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

modding_elichika_path = "assets/package/live/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

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

# Function to generate a unique live_id_masterdata
def generate_unique_live_id(cursor):
    while True:
        new_id = random.randint(0, 99999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live WHERE live_id = ?;", (new_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id
       
def generate_unique_music_id1(cursor):
    while True:
        new_id42a = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", (new_id42a,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a

def generate_unique_liveconst1_id(cursor):
    while True:
        new_id42a311 = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty_const WHERE id = ?;", (new_id42a311,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a311              
            
def generate_unique_liveconst2_id(cursor):
    while True:
        new_id42a322 = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty_const WHERE id = ?;", (new_id42a322,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a322   
            
def generate_unique_liveconst3_id(cursor):
    while True:
        new_id42a333 = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty_const WHERE id = ?;", (new_id42a333,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a333     

def generate_unique_emblem_id(cursor):
    while True:
        new_id42a3113 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_emblem WHERE id = ?;", (new_id42a3113,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a3113

def generate_unique_mission1_id(cursor):
    while True:
        new_id42a3113w1 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_mission WHERE id = ?;", (new_id42a3113w1,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a3113w1                

def generate_unique_mission2_id(cursor):
    while True:
        new_id42a3113w2 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_mission WHERE id = ?;", (new_id42a3113w2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a3113w2

def generate_unique_mission3_id(cursor):
    while True:
        new_id42a3113w3 = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_mission WHERE id = ?;", (new_id42a3113w3,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42a3113w3               

def generate_unique_music_id2(cursor):
    while True:
        new_id42b = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", (new_id42b,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42b           
            
def generate_unique_music_id3(cursor):
    while True:
        new_id42c = random.randint(0, 99999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live_difficulty WHERE live_id = ?;", (new_id42c,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42c  
            
def generate_unique_music_id(cursor):
    while True:
        new_id42 = random.randint(1000, 9999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live WHERE music_id = ?;", (new_id42,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id42    
                        
def thumbnail_path_randomhash(cursor):
    while True:
        new_hash2 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash2
            
def emblem_path_randomhash(cursor):
    while True:
        new_hash2emblem = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.texture WHERE asset_path = ?;", (new_hash2emblem,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash2emblem
            
def movie_path_randomhash(cursor):
    while True:
        new_hash2mov = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.m_movie WHERE pavement = ?;", (new_hash2mov,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash2mov
            
# explorer code
clear_terminal()
temp_directory = "assets/package/.cache/"
shutil.rmtree(temp_directory, ignore_errors=True)

# List all files in the directory with a ".zip" extension
zip_files = []
for root, dirs, files in os.walk(modding_elichika_path):
    for file in files:
        if file.endswith(".zip"):
            zip_files.append(os.path.relpath(os.path.join(root, file), modding_elichika_path))

zip_files.sort()

# Display the available zip files with corresponding numbers
print("Available .zip files:")
for i, zip_file in enumerate(zip_files, start=1):
    print(f"{i}. {zip_file}")

# User input to choose a zip file by entering a number
try:
    chosen_number = int(input("Enter the number corresponding to the .zip file you want to choose: "))
    
    # Check if the chosen number is valid
    if 1 <= chosen_number <= len(zip_files):
        zip_file_path = os.path.join(modding_elichika_path, zip_files[chosen_number - 1])
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
                try:
                    file_content = txt_file.read()
                    exec(file_content)
                except Exception as e:
                    print(f"Error executing file: {file_info.filename}\nError: {e}")





clear_terminal()
print('Name: ' + music_name_en)
print('Copyright: ' + music_copyright_name_en)
if member_group_live == 1:
    print('Group: Myuzu')
elif member_group_live == 2:
    print('Group: Aqours')
elif member_group_live == 3:
    print('Group: Nijigasaki')
elif member_group_live == 4:
    print('Group: Liella')
else:
    print('Please enter correct member_group_live value')
    sys.exit(1)    
    
    
if attribute_live == 1:
    print('Attribute: Smile')
elif attribute_live == 2:
    print('Attribute: Pure')
elif attribute_live == 3:
    print('Attribute: Cool')
elif attribute_live == 4:
    print('Attribute: Active')
elif attribute_live == 5:
    print('Attribute: Natural')
elif attribute_live == 6:
    print('Attribute: Elegant')
elif attribute_live == 9:
    print('Attribute: Untyped / Unknown')
else:
    print('Please enter correct attribute value')
    sys.exit(1)
    
if videoprime_file != "":
    print('MV Video: yes')
else:
    print('MV Video: no')
print('Description: ' + music_description)
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

start_encrypt1 = temp_directory + music_file
start_encrypt2 = temp_directory + music_sabi_file
start_encrypt3 = temp_directory + thumbnail_file
start_encrypt4 = temp_directory + emblem_file
if videoprime_file != "":
    start_encrypt5 = temp_directory + videoprime_file
    
# Extract filename and filesize from costume_file
music_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
music_sabi_filename = os.path.splitext(start_encrypt2.split("/")[-1])[0]

# Extract filename and filesize from thumbnail_file
thumbnail_music_filename = os.path.splitext(start_encrypt3.split("/")[-1])[0]
emblem_filename = os.path.splitext(start_encrypt4.split("/")[-1])[0]

# Replace with actual method to get filesize
thumbnail_music_size = os.path.getsize(start_encrypt3)
thumbnail_emblem_size = os.path.getsize(start_encrypt4)
music_live_size = os.path.getsize(start_encrypt1)
music_live_sabi_size = os.path.getsize(start_encrypt2)
if videoprime_file != "":
    mv_filesize = os.path.getsize(start_encrypt5)

if not music_filename.isalnum() or not music_filename.islower():
    print('Invalid Music Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)  
if not music_sabi_filename.isalnum() or not music_sabi_filename.islower():
    print('Invalid Music SABI Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)
if not thumbnail_music_filename.isalnum() or not thumbnail_music_filename.islower():
    print('Invalid Thumbnail Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)      
if not emblem_filename.isalnum() or not emblem_filename.islower():
    print('Invalid Emblem Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)
        
encrypted_emblem = "static/assets/" + os.path.splitext(start_encrypt4.split("/")[-1])[0]
encrypted_thumbnail = "static/assets/" + os.path.splitext(start_encrypt3.split("/")[-1])[0]
music_filename_saved = "static/assets/" + os.path.splitext(start_encrypt1.split("/")[-1])[0]
music_sabi_filename_saved = "static/assets/" + os.path.splitext(start_encrypt2.split("/")[-1])[0]
if videoprime_file != "":
    movie_filename_saved = "static/assets/" + os.path.splitext(start_encrypt5.split("/")[-1])[0]

# encrypting asset first
encrypted_folder = "static/assets/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)
    
def read_file_and_select_text(start_encrypt1):
    with open(start_encrypt1, 'rb') as file:
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
        
def read_file_and_select_text1(start_encrypt2):
    with open(start_encrypt2, 'rb') as file:
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
    
with open(start_encrypt3, "rb") as file:
    data = bytearray(file.read())

    key_0 = 12345
    key_1 = 0
    key_2 = 0
    print("encrypting jacket")
    manipulate_file(data, key_0, key_1, key_2)

    with open(encrypted_thumbnail, "wb") as file:
        file.write(data)

with open(start_encrypt4, "rb") as file:
    data = bytearray(file.read())

    key_0 = 12345
    key_1 = 0
    key_2 = 0
    print("encrypting emblem")
    manipulate_file(data, key_0, key_1, key_2)

    with open(encrypted_emblem, "wb") as file:
        file.write(data)

print("assets encrypted")

with sqlite3.connect('assets/db/gl/asset_a_en.db') as conn:
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM m_asset_pack WHERE pack_name = ?", (music_filename,))
    result_chcc = cursor.fetchone()
    if result_chcc[0] > 0:
        print(f"This live already exists in the database")
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1) 

    sheet_name_file = read_file_and_select_text(start_encrypt1)
    sheet_name_file1 = read_file_and_select_text1(start_encrypt2)
    shutil.move(start_encrypt1, music_filename_saved)
    shutil.move(start_encrypt2, music_sabi_filename_saved)
    thumbnail_music_path = thumbnail_path_randomhash(cursor)
    emblem_path = emblem_path_randomhash(cursor)
    donot_insert = None
    if videoprime_file != "":
        movie_genpath = movie_path_randomhash(cursor)
        movie_filename = os.path.splitext(start_encrypt5.split("/")[-1])[0]
        movie_filesize = os.path.getsize(start_encrypt5)
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))
        shutil.move(start_encrypt5, movie_filename_saved)
        
    # (light download auto delete fix)
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))
    
# REST CODE TO CN ZH LANGUAGE & IOS PLATFORM
with sqlite3.connect('assets/db/gl/asset_i_en.db') as conn:
    cursor = conn.cursor()   

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))

    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/gl/asset_a_ko.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))

    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/gl/asset_i_ko.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))

    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/gl/asset_a_zh.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,))
        
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/gl/asset_i_zh.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,)) 
   
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,)) 
   
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

with sqlite3.connect('assets/db/jp/asset_i_ja.db') as conn:
    cursor = conn.cursor()

    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_movie (pavement, pack_name) VALUES (?, ?);", (movie_genpath, movie_filename))
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (movie_filename,)) 
   
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_music_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (music_sabi_filename,))
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (emblem_filename,))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file, music_filename, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_sound (sheet_name, acb_pack_name, awb_pack_name) VALUES (?, ?, ?);", (sheet_name_file1, music_sabi_filename, donot_insert))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (thumbnail_music_path, thumbnail_music_filename, thumbnail_music_size))
    cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');", (emblem_path, emblem_filename, thumbnail_emblem_size))

# Connect to masterdata.db and perform INSERT
with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
    cursor = conn.cursor()

    if id_live is None:
        live_id_masterdata = generate_unique_live_id(cursor)
        music_id_masterdata = generate_unique_music_id(cursor)
        music_diff1_masterdata = generate_unique_music_id1(cursor)
        music_diff2_masterdata = generate_unique_music_id2(cursor)
        music_diff3_masterdata = generate_unique_music_id3(cursor)
    else:
        id_live_str = str(id_live)
        id_live_split1 = int(id_live_str[1:])
        live_id_masterdata = id_live
        music_id_masterdata = id_live_split1
        music_diff1_masterdata = str(id_live) + "101"
        music_diff2_masterdata = str(id_live) + "201"
        music_diff3_masterdata = str(id_live) + "301"
                
    if id_emblem is None:
        emblem_id_masterdata = generate_unique_emblem_id(cursor)
    else:
        emblem_id_masterdata = id_emblem
        
    # Generate a unique live_id_masterdata
    music_name_dictionary_masterdata = "k.song_name_so" + str(music_id_masterdata)
    music_id_copyright_masterdata = "k.song_copyright_so" + str(music_id_masterdata)
    music_name_dictionary_dic = "song_name_so" + str(music_id_masterdata)
    music_id_copyright_dic = "song_copyright_so" + str(music_id_masterdata)
    
    emblem_dictionary_description = "m_dic_emblem_description_" + str(emblem_id_masterdata)
    emblem_dictionary_description_masterdata = "k." + emblem_dictionary_description
    
    # Find the minimum display_order for the given chara_id
    cursor.execute("SELECT MAX(display_order) FROM main.m_live WHERE member_group=?;", (member_group_live,))
    result = cursor.fetchone()
    min_display_order = result[0] if result[0] is not None else 0

    cursor.execute("SELECT MAX(display_order) FROM main.m_emblem;")
    result2 = cursor.fetchone()
    min_display_order2 = result2[0] if result2[0] is not None else 0

    # Calculate the new display_order (decrease by 1)
    display_order_new = min_display_order + 1
    display_order_new2 = min_display_order2 + 1
    # Insert the new record with the updated display_order
    # there no Liella & Union chibi so i will reuse myuzu
    if member_group_live == 1:
        member_mapping_live = 10001
        if attribute_live == 1:
            drop_live_item1_easy = 104100110
            drop_live_item1_normal = 104100120
            drop_live_item1_hard = 104100130
            drop_live_item2_easy = 100100110
            drop_live_item2_normal = 100100120
            drop_live_item2_hard = 100100130
            drop_live_item3_easy = 101100110
            drop_live_item3_normal = 101100120
            drop_live_item3_hard = 101100130
            drop_live_item4_easy = 102100110
            drop_live_item4_normal = 102100120
            drop_live_item4_hard = 102100130
            drop_live_item5_easy = 103100110
            drop_live_item5_normal = 103100120
            drop_live_item5_hard = 103100130
        elif attribute_live == 2:
            drop_live_item1_easy = 104200110
            drop_live_item1_normal = 104200120
            drop_live_item1_hard = 104200130
            drop_live_item2_easy = 100200110
            drop_live_item2_normal = 100200120
            drop_live_item2_hard = 100200130
            drop_live_item3_easy = 101200110
            drop_live_item3_normal = 101200120
            drop_live_item3_hard = 101200130
            drop_live_item4_easy = 102200110
            drop_live_item4_normal = 102200120
            drop_live_item4_hard = 102200130
            drop_live_item5_easy = 103200110
            drop_live_item5_normal = 103200120
            drop_live_item5_hard = 103200130
        elif attribute_live == 3:
            drop_live_item1_easy = 104300110
            drop_live_item1_normal = 104300120
            drop_live_item1_hard = 104300130
            drop_live_item2_easy = 100300110
            drop_live_item2_normal = 100300120
            drop_live_item2_hard = 100300130
            drop_live_item3_easy = 101300110
            drop_live_item3_normal = 101300120
            drop_live_item3_hard = 101300130
            drop_live_item4_easy = 102300110
            drop_live_item4_normal = 102300120
            drop_live_item4_hard = 102300130
            drop_live_item5_easy = 103300110
            drop_live_item5_normal = 103300120
            drop_live_item5_hard = 103300130
        elif attribute_live == 4:
            drop_live_item1_easy = 104400110
            drop_live_item1_normal = 104400120
            drop_live_item1_hard = 104400130
            drop_live_item2_easy = 100400110
            drop_live_item2_normal = 100400120
            drop_live_item2_hard = 100400130
            drop_live_item3_easy = 101400110
            drop_live_item3_normal = 101400120
            drop_live_item3_hard = 101400130
            drop_live_item4_easy = 102400110
            drop_live_item4_normal = 102400120
            drop_live_item4_hard = 102400130
            drop_live_item5_easy = 103400110
            drop_live_item5_normal = 103400120
            drop_live_item5_hard = 103400130
        elif attribute_live == 5:
            drop_live_item1_easy = 104500110
            drop_live_item1_normal = 104500120
            drop_live_item1_hard = 104500130
            drop_live_item2_easy = 100500110
            drop_live_item2_normal = 100500120
            drop_live_item2_hard = 100500130
            drop_live_item3_easy = 101500110
            drop_live_item3_normal = 101500120
            drop_live_item3_hard = 101500130
            drop_live_item4_easy = 102500110
            drop_live_item4_normal = 102500120
            drop_live_item4_hard = 102500130
            drop_live_item5_easy = 103500110
            drop_live_item5_normal = 103500120
            drop_live_item5_hard = 103500130
        elif attribute_live == 6:
            drop_live_item1_easy = 104600110
            drop_live_item1_normal = 104600120
            drop_live_item1_hard = 104600130
            drop_live_item2_easy = 100600110
            drop_live_item2_normal = 100600120
            drop_live_item2_hard = 100600130
            drop_live_item3_easy = 101600110
            drop_live_item3_normal = 101600120
            drop_live_item3_hard = 101600130
            drop_live_item4_easy = 102600110
            drop_live_item4_normal = 102600120
            drop_live_item4_hard = 102600130
            drop_live_item5_easy = 103600110
            drop_live_item5_normal = 103600120
            drop_live_item5_hard = 103600130
        else:
            drop_live_item1_easy = 0
            drop_live_item1_normal = 0
            drop_live_item1_hard = 0
            drop_live_item2_easy = 0
            drop_live_item2_normal = 0
            drop_live_item2_hard = 0
            drop_live_item3_easy = 0
            drop_live_item3_normal = 0
            drop_live_item3_hard = 0
            drop_live_item4_easy = 0
            drop_live_item4_normal = 0
            drop_live_item4_hard = 0
            drop_live_item5_easy = 0
            drop_live_item5_normal = 0
            drop_live_item5_hard = 0
    elif member_group_live == 2:
        member_mapping_live = 11001
        if attribute_live == 1:
            drop_live_item1_easy = 104100210
            drop_live_item1_normal = 104100220
            drop_live_item1_hard = 104100230
            drop_live_item2_easy = 100100210
            drop_live_item2_normal = 100100220
            drop_live_item2_hard = 100100230
            drop_live_item3_easy = 101100210
            drop_live_item3_normal = 101100220
            drop_live_item3_hard = 101100230
            drop_live_item4_easy = 102100210
            drop_live_item4_normal = 102100220
            drop_live_item4_hard = 102100230
            drop_live_item5_easy = 103100210
            drop_live_item5_normal = 103100220
            drop_live_item5_hard = 103100230
        elif attribute_live == 2:
            drop_live_item1_easy = 104200210
            drop_live_item1_normal = 104200220
            drop_live_item1_hard = 104200230
            drop_live_item2_easy = 100200210
            drop_live_item2_normal = 100200220
            drop_live_item2_hard = 100200230
            drop_live_item3_easy = 101200210
            drop_live_item3_normal = 101200220
            drop_live_item3_hard = 101200230
            drop_live_item4_easy = 102200210
            drop_live_item4_normal = 102200220
            drop_live_item4_hard = 102200230
            drop_live_item5_easy = 103200210
            drop_live_item5_normal = 103200220
            drop_live_item5_hard = 103200230
        elif attribute_live == 3:
            drop_live_item1_easy = 104300210
            drop_live_item1_normal = 104300220
            drop_live_item1_hard = 104300230
            drop_live_item2_easy = 100300210
            drop_live_item2_normal = 100300220
            drop_live_item2_hard = 100300230
            drop_live_item3_easy = 101300210
            drop_live_item3_normal = 101300220
            drop_live_item3_hard = 101300230
            drop_live_item4_easy = 102300210
            drop_live_item4_normal = 102300220
            drop_live_item4_hard = 102300230
            drop_live_item5_easy = 103300210
            drop_live_item5_normal = 103300220
            drop_live_item5_hard = 103300230
        elif attribute_live == 4:
            drop_live_item1_easy = 104400210
            drop_live_item1_normal = 104400220
            drop_live_item1_hard = 104400230
            drop_live_item2_easy = 100400210
            drop_live_item2_normal = 100400220
            drop_live_item2_hard = 100400230
            drop_live_item3_easy = 101400210
            drop_live_item3_normal = 101400220
            drop_live_item3_hard = 101400230
            drop_live_item4_easy = 102400210
            drop_live_item4_normal = 102400220
            drop_live_item4_hard = 102400230
            drop_live_item5_easy = 103400210
            drop_live_item5_normal = 103400220
            drop_live_item5_hard = 103400230
        elif attribute_live == 5:
            drop_live_item1_easy = 104500210
            drop_live_item1_normal = 104500220
            drop_live_item1_hard = 104500230
            drop_live_item2_easy = 100500210
            drop_live_item2_normal = 100500220
            drop_live_item2_hard = 100500230
            drop_live_item3_easy = 101500210
            drop_live_item3_normal = 101500220
            drop_live_item3_hard = 101500230
            drop_live_item4_easy = 102500210
            drop_live_item4_normal = 102500220
            drop_live_item4_hard = 102500230
            drop_live_item5_easy = 103500210
            drop_live_item5_normal = 103500220
            drop_live_item5_hard = 103500230
        elif attribute_live == 6:
            drop_live_item1_easy = 104600210
            drop_live_item1_normal = 104600220
            drop_live_item1_hard = 104600230
            drop_live_item2_easy = 100600210
            drop_live_item2_normal = 100600220
            drop_live_item2_hard = 100600230
            drop_live_item3_easy = 101600210
            drop_live_item3_normal = 101600220
            drop_live_item3_hard = 101600230
            drop_live_item4_easy = 102600210
            drop_live_item4_normal = 102600220
            drop_live_item4_hard = 102600230
            drop_live_item5_easy = 103600210
            drop_live_item5_normal = 103600220
            drop_live_item5_hard = 103600230
        else:
            drop_live_item1_easy = 0
            drop_live_item1_normal = 0
            drop_live_item1_hard = 0
            drop_live_item2_easy = 0
            drop_live_item2_normal = 0
            drop_live_item2_hard = 0
            drop_live_item3_easy = 0
            drop_live_item3_normal = 0
            drop_live_item3_hard = 0
            drop_live_item4_easy = 0
            drop_live_item4_normal = 0
            drop_live_item4_hard = 0
            drop_live_item5_easy = 0
            drop_live_item5_normal = 0
            drop_live_item5_hard = 0
    elif member_group_live == 3:
        member_mapping_live = 12130
        if attribute_live == 1:
            drop_live_item1_easy = 104100610
            drop_live_item1_normal = 104100620
            drop_live_item1_hard = 104100630
            drop_live_item2_easy = 100100610
            drop_live_item2_normal = 100100620
            drop_live_item2_hard = 100100630
            drop_live_item3_easy = 101100610
            drop_live_item3_normal = 101100620
            drop_live_item3_hard = 101100630
            drop_live_item4_easy = 102100610
            drop_live_item4_normal = 102100620
            drop_live_item4_hard = 102100630
            drop_live_item5_easy = 103100610
            drop_live_item5_normal = 103100620
            drop_live_item5_hard = 103100630
        elif attribute_live == 2:
            drop_live_item1_easy = 104200610
            drop_live_item1_normal = 104200620
            drop_live_item1_hard = 104200630
            drop_live_item2_easy = 100200610
            drop_live_item2_normal = 100200620
            drop_live_item2_hard = 100200630
            drop_live_item3_easy = 101200610
            drop_live_item3_normal = 101200620
            drop_live_item3_hard = 101200630
            drop_live_item4_easy = 102200610
            drop_live_item4_normal = 102200620
            drop_live_item4_hard = 102200630
            drop_live_item5_easy = 103200610
            drop_live_item5_normal = 103200620
            drop_live_item5_hard = 103200630
        elif attribute_live == 3:
            drop_live_item1_easy = 104300610
            drop_live_item1_normal = 104300620
            drop_live_item1_hard = 104300630
            drop_live_item2_easy = 100300610
            drop_live_item2_normal = 100300620
            drop_live_item2_hard = 100300630
            drop_live_item3_easy = 101300610
            drop_live_item3_normal = 101300620
            drop_live_item3_hard = 101300630
            drop_live_item4_easy = 102300610
            drop_live_item4_normal = 102300620
            drop_live_item4_hard = 102300630
            drop_live_item5_easy = 103300610
            drop_live_item5_normal = 103300620
            drop_live_item5_hard = 103300630
        elif attribute_live == 4:
            drop_live_item1_easy = 104400610
            drop_live_item1_normal = 104400620
            drop_live_item1_hard = 104400630
            drop_live_item2_easy = 100400610
            drop_live_item2_normal = 100400620
            drop_live_item2_hard = 100400630
            drop_live_item3_easy = 101400610
            drop_live_item3_normal = 101400620
            drop_live_item3_hard = 101400630
            drop_live_item4_easy = 102400610
            drop_live_item4_normal = 102400620
            drop_live_item4_hard = 102400630
            drop_live_item5_easy = 103400610
            drop_live_item5_normal = 103400620
            drop_live_item5_hard = 103400630
        elif attribute_live == 5:
            drop_live_item1_easy = 104500610
            drop_live_item1_normal = 104500620
            drop_live_item1_hard = 104500630
            drop_live_item2_easy = 100500610
            drop_live_item2_normal = 100500620
            drop_live_item2_hard = 100500630
            drop_live_item3_easy = 101500610
            drop_live_item3_normal = 101500620
            drop_live_item3_hard = 101500630
            drop_live_item4_easy = 102500610
            drop_live_item4_normal = 102500620
            drop_live_item4_hard = 102500630
            drop_live_item5_easy = 103500610
            drop_live_item5_normal = 103500620
            drop_live_item5_hard = 103500630
        elif attribute_live == 6:
            drop_live_item1_easy = 104600610
            drop_live_item1_normal = 104600620
            drop_live_item1_hard = 104600630
            drop_live_item2_easy = 100600610
            drop_live_item2_normal = 100600620
            drop_live_item2_hard = 100600630
            drop_live_item3_easy = 101600610
            drop_live_item3_normal = 101600620
            drop_live_item3_hard = 101600630
            drop_live_item4_easy = 102600610
            drop_live_item4_normal = 102600620
            drop_live_item4_hard = 102600630
            drop_live_item5_easy = 103600610
            drop_live_item5_normal = 103600620
            drop_live_item5_hard = 103600630
        else:
            drop_live_item1_easy = 0
            drop_live_item1_normal = 0
            drop_live_item1_hard = 0
            drop_live_item2_easy = 0
            drop_live_item2_normal = 0
            drop_live_item2_hard = 0
            drop_live_item3_easy = 0
            drop_live_item3_normal = 0
            drop_live_item3_hard = 0
            drop_live_item4_easy = 0
            drop_live_item4_normal = 0
            drop_live_item4_hard = 0
            drop_live_item5_easy = 0
            drop_live_item5_normal = 0
            drop_live_item5_hard = 0
    elif member_group_live == 4:
        member_mapping_live = 10001
        if attribute_live == 1:
            drop_live_item1_easy = 104100410
            drop_live_item1_normal = 104100410
            drop_live_item1_hard = 104100410
            drop_live_item2_easy = 100100410
            drop_live_item2_normal = 100100410
            drop_live_item2_hard = 100100410
            drop_live_item3_easy = 101100410
            drop_live_item3_normal = 101100410
            drop_live_item3_hard = 101100410
            drop_live_item4_easy = 102100410
            drop_live_item4_normal = 102100410
            drop_live_item4_hard = 102100410
            drop_live_item5_easy = 103100410
            drop_live_item5_normal = 103100410
            drop_live_item5_hard = 103100410
        elif attribute_live == 2:
            drop_live_item1_easy = 104200410
            drop_live_item1_normal = 104200410
            drop_live_item1_hard = 104200410
            drop_live_item2_easy = 100200410
            drop_live_item2_normal = 100200410
            drop_live_item2_hard = 100200410
            drop_live_item3_easy = 101200410
            drop_live_item3_normal = 101200410
            drop_live_item3_hard = 101200410
            drop_live_item4_easy = 102200410
            drop_live_item4_normal = 102200410
            drop_live_item4_hard = 102200410
            drop_live_item5_easy = 103200410
            drop_live_item5_normal = 103200410
            drop_live_item5_hard = 103200410
        elif attribute_live == 4:
            drop_live_item1_easy = 104400410
            drop_live_item1_normal = 104400410
            drop_live_item1_hard = 104400410
            drop_live_item2_easy = 100400410
            drop_live_item2_normal = 100400410
            drop_live_item2_hard = 100400410
            drop_live_item3_easy = 101400410
            drop_live_item3_normal = 101400410
            drop_live_item3_hard = 101400410
            drop_live_item4_easy = 102400410
            drop_live_item4_normal = 102400410
            drop_live_item4_hard = 102400410
            drop_live_item5_easy = 103400410
            drop_live_item5_normal = 103400410
            drop_live_item5_hard = 103400410
        elif attribute_live == 6:
            drop_live_item1_easy = 104600410
            drop_live_item1_normal = 104600410
            drop_live_item1_hard = 104600410
            drop_live_item2_easy = 100600410
            drop_live_item2_normal = 100600410
            drop_live_item2_hard = 100600410
            drop_live_item3_easy = 101600410
            drop_live_item3_normal = 101600410
            drop_live_item3_hard = 101600410
            drop_live_item4_easy = 102600410
            drop_live_item4_normal = 102600410
            drop_live_item4_hard = 102600410
            drop_live_item5_easy = 103600410
            drop_live_item5_normal = 103600410
            drop_live_item5_hard = 103600410
        else:
            drop_live_item1_easy = 0
            drop_live_item1_normal = 0
            drop_live_item1_hard = 0
            drop_live_item2_easy = 0
            drop_live_item2_normal = 0
            drop_live_item2_hard = 0
            drop_live_item3_easy = 0
            drop_live_item3_normal = 0
            drop_live_item3_hard = 0
            drop_live_item4_easy = 0
            drop_live_item4_normal = 0
            drop_live_item4_hard = 0
            drop_live_item5_easy = 0
            drop_live_item5_normal = 0
            drop_live_item5_hard = 0
    elif member_group_live == 100:
        member_mapping_live = 10001
        drop_live_item1_easy = 0
        drop_live_item1_normal = 0
        drop_live_item1_hard = 0
        drop_live_item2_easy = 0
        drop_live_item2_normal = 0
        drop_live_item2_hard = 0
        drop_live_item3_easy = 0
        drop_live_item3_normal = 0
        drop_live_item3_hard = 0
        drop_live_item4_easy = 0
        drop_live_item4_normal = 0
        drop_live_item4_hard = 0
        drop_live_item5_easy = 0
        drop_live_item5_normal = 0
        drop_live_item5_hard = 0
    cursor.execute("INSERT INTO main.m_live (live_id, is_2d_live, music_id, bgm_path, chorus_bgm_path, live_member_mapping_id, name, pronunciation, member_group, member_unit, original_deck_name, copyright, source, jacket_asset_path, background_asset_path, display_order) VALUES (?, '1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SI', ?);",
                   (live_id_masterdata, music_id_masterdata, sheet_name_file, sheet_name_file1, member_mapping_live, music_name_dictionary_masterdata, donot_insert, member_group_live, donot_insert, donot_insert, music_id_copyright_masterdata, donot_insert, thumbnail_music_path, display_order_new))
   
    # liella attribute 3 & 5, union & untyped doesn't not have drop https://github.com/arina999999997/elichika/tree/master/docs#server-implement-progress
    # cannot get information AC, Note Gimmick & Live Gimmick
    # if you are dev, feel free to edit
    
    saved_diffx = "assets/stages/"
    output_filename1 = saved_diffx + f"{music_diff1_masterdata}.json"
    output_filename2 = saved_diffx + f"{music_diff2_masterdata}.json"
    output_filename3 = saved_diffx + f"{music_diff3_masterdata}.json"
    start_editbeatmap1 = temp_directory + easy_difficulty_file
    start_editbeatmap2 = temp_directory + normal_difficulty_file
    start_editbeatmap3 = temp_directory + hard_difficulty_file

    with open(start_editbeatmap1, 'r') as difficult_file1:
        data_difff1 = json.load(difficult_file1)
                
        data_difff1["live_difficulty_id"] = music_diff1_masterdata
        id_count_easy = 0
        for note_easy in data_difff1.get('live_notes', []):
            if 'id' in note_easy:
                id_count_easy += 1

        # experimental AC (appeal chance)
        if appeal_chance_easy is not None:
            for idx_easy, entry_easy in enumerate(appeal_chance_easy):
                id1_easy = entry_easy[0]
                id2_easy = entry_easy[1]
                wave_id_value_easy = idx_easy + 1  # Since wave_id starts from 1

                # Update live_notes wave_id and note_type
                for note_easy in data_difff1['live_notes']:
                    if note_easy['id'] >= id1_easy and note_easy['id'] <= id2_easy:
                        note_easy['wave_id'] = wave_id_value_easy

                # Update note_type
                for note_easy in data_difff1['live_notes']:
                    if note_easy['id'] == id1_easy:
                        note_easy['note_type'] = 4
                    elif note_easy['id'] == id2_easy:
                        note_easy['note_type'] = 5

                # Add entry to live_wave_settings
                data_difff1['live_wave_settings'].append({
                    "id": wave_id_value_easy,
                    "wave_damage": entry_easy[5],
                    "mission_type": entry_easy[2],
                    "arg_1": entry_easy[3],
                    "arg_2": 0,  # Assuming this is a default value
                    "reward_voltage": entry_easy[4]
                })
        # live_wave_settings_easy = data_diff.get("live_wave_settings", [])

        # # testing get info AC
        # for wave_id, arg_1, mission_type, reward_voltage, wave_damage in live_wave_settings_easy:
            # live_detail_base_add_easy = "k.live_detail_wave_gimmick_" + music_diff1_masterdata + "_" + str(wave_id)
            # with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
                # cursor = conn.cursor()
                # cursor.execute("INSERT INTO main.m_live_note_wave_gimmick_group (live_difficulty_id, wave_id, state, skill_id, name, description) VALUES (?, ?, '255', '50000001', ?, ?);",
                    # (music_diff1_masterdata, wave_id, live_detail_base_add_easy))
            
        with open(output_filename1, 'w') as difficult_file1:
            json.dump(data_difff1, difficult_file1, indent=2)
    
    with open(start_editbeatmap2, 'r') as difficult_file2:
        data_difff2 = json.load(difficult_file2)
                
        data_difff2["live_difficulty_id"] = music_diff2_masterdata
        id_count_normal = 0
        for note_normal in data_difff2.get('live_notes', []):
            if 'id' in note_normal:
                id_count_normal += 1
           
        if appeal_chance_normal is not None:
            for idx_normal, entry_normal in enumerate(appeal_chance_normal):
                id1_normal = entry_normal[0]
                id2_normal = entry_normal[1]
                wave_id_value_normal = idx_normal + 1  # Since wave_id starts from 1

                # Update live_notes wave_id and note_type
                for note_normal in data_difff2['live_notes']:
                    if note_normal['id'] >= id1_normal and note_normal['id'] <= id2_normal:
                        note_normal['wave_id'] = wave_id_value_normal

                # Update note_type
                for note_normal in data_difff2['live_notes']:
                    if note_normal['id'] == id1_normal:
                        note_normal['note_type'] = 4
                    elif note_normal['id'] == id2_normal:
                        note_normal['note_type'] = 5

                # Add entry to live_wave_settings
                data_difff2['live_wave_settings'].append({
                    "id": wave_id_value_normal,
                    "wave_damage": entry_normal[5],
                    "mission_type": entry_normal[2],
                    "arg_1": entry_normal[3],
                    "arg_2": 0,  # Assuming this is a default value
                    "reward_voltage": entry_normal[4]
                })
           
        with open(output_filename2, 'w') as difficult_file2:
            json.dump(data_difff2, difficult_file2, indent=2)
    
    with open(start_editbeatmap3, 'r') as difficult_file3:
        data_difff3 = json.load(difficult_file3)
                
        data_difff3["live_difficulty_id"] = music_diff3_masterdata
        id_count_hard = 0
        for note_hard in data_difff3.get('live_notes', []):
            if 'id' in note_hard:
                id_count_hard += 1
            
        if appeal_chance_hard is not None:
            for idx_hard, entry_hard in enumerate(appeal_chance_hard):
                id1_hard = entry_hard[0]
                id2_hard = entry_hard[1]
                wave_id_value_hard = idx_hard + 1  # Since wave_id starts from 1

                # Update live_notes wave_id and note_type
                for note_hard in data_difff3['live_notes']:
                    if note_hard['id'] >= id1_hard and note_hard['id'] <= id2_hard:
                        note_hard['wave_id'] = wave_id_value_hard

                # Update note_type
                for note_hard in data_difff3['live_notes']:
                    if note_hard['id'] == id1_hard:
                        note_hard['note_type'] = 4
                    elif note_hard['id'] == id2_hard:
                        note_hard['note_type'] = 5

                # Add entry to live_wave_settings
                data_difff3['live_wave_settings'].append({
                    "id": wave_id_value_hard,
                    "wave_damage": entry_hard[5],
                    "mission_type": entry_hard[2],
                    "arg_1": entry_hard[3],
                    "arg_2": 0,  # Assuming this is a default value
                    "reward_voltage": entry_hard[4]
                })
           
            
        with open(output_filename3, 'w') as difficult_file3:
            json.dump(data_difff3, difficult_file3, indent=2)
    
    # score logic
    # automatic setup score based on note count
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
    
    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 10, '1', ?, ?, ?, ?, ?, '10', '8', '1', ?, '2', '1500', ?, ?, '2', ?, ?, '50000', '9000', '12', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff1_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_easy, note_emit_msec_easy, recommend_power_easy, recommend_stamina_easy, drop_live_item1_easy, drop_live_item2_easy, drop_live_item3_easy, drop_live_item4_easy, drop_live_item5_easy, evaluation_score_easy, evaluation_a_score_easy, evaluation_b_score_easy, evaluation_c_score_easy, donot_insert, music_diff1_masterdata,))

    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 20, '1', ?, ?, ?, ?, ?, '12', '13', '2', ?, '2', '1300', ?, ?, '2', ?, ?, '60000', '9000', '16', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff2_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_normal, note_emit_msec_normal, recommend_power_normal, recommend_stamina_normal, drop_live_item1_normal, drop_live_item2_normal, drop_live_item3_normal, drop_live_item4_normal, drop_live_item5_normal, evaluation_score_normal, evaluation_a_score_normal, evaluation_b_score_normal, evaluation_c_score_normal, donot_insert, music_diff2_masterdata,))
                   
    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 30, '1', ?, ?, ?, ?, ?, '15', '21', '3', ?, '2', '1000', ?, ?, '3', ?, ?, '70000', '9000', '24', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff3_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_hard, note_emit_msec_hard, recommend_power_hard, recommend_stamina_hard, drop_live_item1_hard, drop_live_item2_hard, drop_live_item3_hard, drop_live_item4_hard, drop_live_item5_hard, evaluation_score_hard, evaluation_a_score_hard, evaluation_b_score_hard, evaluation_c_score_hard, donot_insert, music_diff3_masterdata,))
                   
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '3600', '10000', '50', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff1_masterdata, note_stamina_damage_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '4800', '10000', '75', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff2_masterdata, note_stamina_damage_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '6000', '10000', '100', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff3_masterdata, note_stamina_damage_hard,))
    # live end give you reward 10 stargem
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff1_masterdata, evaluation_b_score_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff1_masterdata, evaluation_score_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff2_masterdata, evaluation_b_score_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff2_masterdata, evaluation_score_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff3_masterdata, evaluation_b_score_hard,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff3_masterdata, evaluation_score_hard,))
    # evaluation drop
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff3_masterdata,))
    # emblem
    cursor.execute("INSERT INTO main.m_emblem (id, name, description, emblem_type, grade, emblem_asset_path, emblem_sub_asset_path, emblem_clear_condition_type, emblem_clear_condition_param, is_emblem_secret_condition, is_event_emblem, released_at, display_order) VALUES (?, ?, ?, '2', ?, ?, ?, '5', '100', '0', '0', '0', ?);",
                   (emblem_id_masterdata, music_name_dictionary_masterdata, emblem_dictionary_description_masterdata, donot_insert, emblem_path, donot_insert, display_order_new2)) 
    
    # mission
    if id_mission1 is None:
        mission_1_masterdata = generate_unique_mission1_id(cursor)
    else:
        mission_1_masterdata = id_mission1
        
    mission_desc_dictionary_dic1 = "freemission_desc_" + str(mission_1_masterdata)
    mission_desc_dictionary_masterdata1 = "m.freemission_desc_" + str(mission_1_masterdata)

    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m1 = cursor.fetchone()
    min_display_order_m1 = result_m1[0] if result_m1[0] is not None else 0

    display_order_new_m1 = min_display_order_m1 - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '1', '0', ?, '1529593200', ?, '20', ?, ?, ?, '14', '10', ?, ?, ?, '0');", (mission_1_masterdata, mission_desc_dictionary_masterdata1, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m1, live_id_masterdata, donot_insert, donot_insert,))
   
    if id_mission2 is None:
        mission_2_masterdata = generate_unique_mission2_id(cursor)
    else:
        mission_2_masterdata = id_mission2
        
    mission_desc_dictionary_dic2 = "freemission_desc_" + str(mission_2_masterdata)
    mission_desc_dictionary_masterdata2 = "m.freemission_desc_" + str(mission_2_masterdata)
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m2 = cursor.fetchone()
    min_display_order_m2 = result_m2[0] if result_m2[0] is not None else 0

    display_order_new_m2 = min_display_order_m2 - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '50', ?, ?, ?, '0');", (mission_2_masterdata, mission_desc_dictionary_masterdata2, mission_1_masterdata, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m2, live_id_masterdata, donot_insert, donot_insert,))
    
    if id_mission3 is None:
        mission_3_masterdata = generate_unique_mission3_id(cursor)
    else:
        mission_3_masterdata = id_mission3
        
    mission_desc_dictionary_dic3 = "freemission_desc_" + str(mission_3_masterdata)
    mission_desc_dictionary_masterdata3 = "m.freemission_desc_" + str(mission_3_masterdata)
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m3 = cursor.fetchone()
    min_display_order_m3 = result_m3[0] if result_m3[0] is not None else 0

    display_order_new_m3 = min_display_order_m3 - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '100', ?, ?, ?, '0');", (mission_3_masterdata, mission_desc_dictionary_masterdata3, mission_2_masterdata, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m3, live_id_masterdata, donot_insert, donot_insert,))
    # mission reward
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr1 = cursor.fetchone()
    min_display_order_mr1 = result_mr1[0] if result_mr1[0] is not None else 0

    display_order_new_mr1 = min_display_order_mr1 - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '1');", (mission_1_masterdata, display_order_new_mr1,))
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr2 = cursor.fetchone()
    min_display_order_mr2 = result_mr2[0] if result_mr2[0] is not None else 0

    display_order_new_mr2 = min_display_order_mr2 - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '3');", (mission_2_masterdata, display_order_new_mr2,))
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr3 = cursor.fetchone()
    min_display_order_mr3 = result_mr3[0] if result_mr3[0] is not None else 0

    display_order_new_mr3 = min_display_order_mr3 - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '15', ?, '1');", (mission_3_masterdata, display_order_new_mr3, emblem_id_masterdata,))
    
    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_live_movie (live_id, codec, movie_asset_path, stage_background_asset_path) VALUES (?, 'prime', ?, 'Bl7');", (live_id_masterdata, movie_genpath))
        
        
with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
    cursor = conn.cursor()

    # Generate a unique live_id_masterdata
    
    # Find the minimum display_order for the given chara_id
    cursor.execute("SELECT MAX(display_order) FROM main.m_live WHERE member_group=?;", (member_group_live,))
    result_ja_cl = cursor.fetchone()
    min_display_order_ja = result_ja_cl[0] if result_ja_cl[0] is not None else 0

    cursor.execute("SELECT MAX(display_order) FROM main.m_emblem;")
    result2_ja_cl = cursor.fetchone()
    min_display_order2_ja = result2_ja_cl[0] if result2_ja_cl[0] is not None else 0

    # Calculate the new display_order (decrease by 1)
    display_order_new_ja = min_display_order_ja + 1
    display_order_new2_ja = min_display_order2_ja + 1

    cursor.execute("INSERT INTO main.m_live (live_id, is_2d_live, music_id, bgm_path, chorus_bgm_path, live_member_mapping_id, name, pronunciation, member_group, member_unit, original_deck_name, copyright, source, jacket_asset_path, background_asset_path, display_order) VALUES (?, '1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SI', ?);",
                   (live_id_masterdata, music_id_masterdata, sheet_name_file, sheet_name_file1, member_mapping_live, music_name_dictionary_masterdata, donot_insert, member_group_live, donot_insert, donot_insert, music_id_copyright_masterdata, donot_insert, thumbnail_music_path, display_order_new_ja))  
    
    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 10, '1', ?, ?, ?, ?, ?, '10', '8', '1', ?, '2', '1500', ?, ?, '2', ?, ?, '50000', '9000', '12', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff1_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_easy, note_emit_msec_easy, recommend_power_easy, recommend_stamina_easy, drop_live_item1_easy, drop_live_item2_easy, drop_live_item3_easy, drop_live_item4_easy, drop_live_item5_easy, evaluation_score_easy, evaluation_a_score_easy, evaluation_b_score_easy, evaluation_c_score_easy, donot_insert, music_diff1_masterdata,))

    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 20, '1', ?, ?, ?, ?, ?, '12', '13', '2', ?, '2', '1300', ?, ?, '2', ?, ?, '60000', '9000', '16', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff2_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_normal, note_emit_msec_normal, recommend_power_normal, recommend_stamina_normal, drop_live_item1_normal, drop_live_item2_normal, drop_live_item3_normal, drop_live_item4_normal, drop_live_item5_normal, evaluation_score_normal, evaluation_a_score_normal, evaluation_b_score_normal, evaluation_c_score_normal, donot_insert, music_diff2_masterdata,))
                   
    cursor.execute("INSERT INTO main.m_live_difficulty (live_difficulty_id, live_id, live_3d_asset_master_id, live_difficulty_type, unlock_pattern, default_attribute, target_voltage, note_emit_msec, recommended_score, recommended_stamina, consumed_lp, reward_user_exp, judge_id, note_drop_group_id, drop_choose_count, rare_drop_rate, drop_content_group_id, rare_drop_content_group_id, additional_drop_max_count, additional_drop_content_group_id, additional_rare_drop_content_group_id,bottom_technique, additional_drop_decay_technique, reward_base_love_point, evaluation_s_score, evaluation_a_score, evaluation_b_score, evaluation_c_score, updated_at, lose_at_death, autoplay_requirement_id, skip_master_id, stamina_voltage_group_id, combo_voltage_group_id, difficulty_const_master_id, is_count_target, insufficient_rate) VALUES (?, ?, ?, 30, '1', ?, ?, ?, ?, ?, '15', '21', '3', ?, '2', '1000', ?, ?, '3', ?, ?, '70000', '9000', '24', ?, ?, ?, ?, '0', '1', ?, '16001', '1', '1', ?, '1', '6000');",
                   (music_diff3_masterdata, live_id_masterdata, donot_insert, attribute_live, evaluation_score_hard, note_emit_msec_hard, recommend_power_hard, recommend_stamina_hard, drop_live_item1_hard, drop_live_item2_hard, drop_live_item3_hard, drop_live_item4_hard, drop_live_item5_hard, evaluation_score_hard, evaluation_a_score_hard, evaluation_b_score_hard, evaluation_c_score_hard, donot_insert, music_diff3_masterdata,))
                   
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '3600', '10000', '50', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff1_masterdata, note_stamina_damage_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '4800', '10000', '75', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff2_masterdata, note_stamina_damage_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_const (id, sp_gauge_length, sp_gauge_additional_rate, sp_gauge_reducing_point, sp_skill_voltage_magnification, note_stamina_reduce, note_voltage_upper_limit, collabo_voltage_upper_limit, skill_voltage_upper_limit, squad_change_voltage_upper_limit) VALUES (?, '6000', '10000', '100', '10000', ?, '100000', '250000', '50000', '30000');", (music_diff3_masterdata, note_stamina_damage_hard,))
    # live end give you reward 10 stargem
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff1_masterdata, evaluation_b_score_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff1_masterdata, evaluation_score_easy,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff2_masterdata, evaluation_b_score_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff2_masterdata, evaluation_score_normal,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '1', '1', '1', '1', '0', '2');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '2', '6', ?, '1', '0', '3');", (music_diff3_masterdata, evaluation_b_score_hard,))
    cursor.execute("INSERT INTO main.m_live_difficulty_mission (live_difficulty_master_id, position, target_type, target_value, content_type, content_id, content_amount) VALUES (?, '3', '4', ?, '1', '0', '5');", (music_diff3_masterdata, evaluation_score_hard,))
    # evaluation drop
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff1_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff2_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '10');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '20');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '30');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '40');", (music_diff3_masterdata,))
    cursor.execute("INSERT INTO main.m_live_evaluation_drop (live_difficulty_master_id, evaluation_type) VALUES (?, '50');", (music_diff3_masterdata,))
    # emblem
    cursor.execute("INSERT INTO main.m_emblem (id, name, description, emblem_type, grade, emblem_asset_path, emblem_sub_asset_path, emblem_clear_condition_type, emblem_clear_condition_param, is_emblem_secret_condition, is_event_emblem, released_at, display_order) VALUES (?, ?, ?, '2', ?, ?, ?, '5', '100', '0', '0', '0', ?);",
                   (emblem_id_masterdata, music_name_dictionary_masterdata, emblem_dictionary_description_masterdata, donot_insert, emblem_path, donot_insert, display_order_new2_ja)) 
    
    # mission
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m1_ja = cursor.fetchone()
    min_display_order_m1_ja = result_m1_ja[0] if result_m1_ja[0] is not None else 0

    display_order_new_m1_ja = min_display_order_m1_ja - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '1', '0', ?, '1529593200', ?, '20', ?, ?, ?, '14', '10', ?, ?, ?, '0');", (mission_1_masterdata, mission_desc_dictionary_masterdata1, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m1_ja, live_id_masterdata, donot_insert, donot_insert,))
   
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m2_ja = cursor.fetchone()
    min_display_order_m2_ja = result_m2_ja[0] if result_m2_ja[0] is not None else 0

    display_order_new_m2_ja = min_display_order_m2_ja - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '50', ?, ?, ?, '0');", (mission_2_masterdata, mission_desc_dictionary_masterdata2, mission_1_masterdata, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m2_ja, live_id_masterdata, donot_insert, donot_insert,))
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission WHERE end_at IS NULL AND mission_clear_condition_type = 14;")
    result_m3_ja = cursor.fetchone()
    min_display_order_m3_ja = result_m3_ja[0] if result_m3_ja[0] is not None else 0

    display_order_new_m3_ja = min_display_order_m3_ja - 1
    cursor.execute("INSERT INTO main.m_mission (id, term, title, description, trigger_type, trigger_condition_1, trigger_condition_2, start_at, end_at, scene_transition_link, scene_transition_param, pickup_type, display_order, mission_clear_condition_type, mission_clear_condition_count, mission_clear_condition_param1, mission_clear_condition_param2, complete_mission_num, has_content) VALUES (?, '3', 'm.mission_name_18', ?, '2', ?, ?, '1529593200', ?, '20', ?, ?, ?, '14', '100', ?, ?, ?, '0');", (mission_3_masterdata, mission_desc_dictionary_masterdata3, mission_2_masterdata, donot_insert, donot_insert, donot_insert, donot_insert, display_order_new_m3_ja, live_id_masterdata, donot_insert, donot_insert,))
    # mission reward
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr1_ja = cursor.fetchone()
    min_display_order_mr1_ja = result_mr1_ja[0] if result_mr1_ja[0] is not None else 0

    display_order_new_mr1_ja = min_display_order_mr1_ja - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '1');", (mission_1_masterdata, display_order_new_mr1_ja,))
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr2_ja = cursor.fetchone()
    min_display_order_mr2_ja = result_mr2_ja[0] if result_mr2_ja[0] is not None else 0

    display_order_new_mr2_ja = min_display_order_mr2_ja - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '28', '16001', '3');", (mission_2_masterdata, display_order_new_mr2_ja,))
    
    cursor.execute("SELECT MIN(display_order) FROM main.m_mission_reward WHERE display_order > 300;")
    result_mr3_ja = cursor.fetchone()
    min_display_order_mr3_ja = result_mr3_ja[0] if result_mr3_ja[0] is not None else 0

    display_order_new_mr3_ja = min_display_order_mr3_ja - 1
    cursor.execute("INSERT INTO main.m_mission_reward (mission_id, display_order, content_type, content_id, content_amount) VALUES (?, ?, '15', ?, '1');", (mission_3_masterdata, display_order_new_mr3_ja, emblem_id_masterdata,))
    
    if videoprime_file != "":
        cursor.execute("INSERT INTO main.m_live_movie (live_id, codec, movie_asset_path, stage_background_asset_path) VALUES (?, 'prime', ?, 'Bl7');", (live_id_masterdata, movie_genpath))
     
with sqlite3.connect('assets/db/gl/dictionary_en_k.db') as conn:
    cursor = conn.cursor()
    message_title_en = "Clear &quot;" + str(music_name_en) + "&quot; 100 times."
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_name_dictionary_dic, music_name_en))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_id_copyright_dic, music_copyright_name_en))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (emblem_dictionary_description, message_title_en))
    
with sqlite3.connect('assets/db/gl/dictionary_ko_k.db') as conn:
    cursor = conn.cursor()
    message_title_ko = str(music_name_ko) + " 100회 클리어"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_name_dictionary_dic, music_name_ko))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_id_copyright_dic, music_copyright_name_ko))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (emblem_dictionary_description, message_title_ko))
        
with sqlite3.connect('assets/db/gl/dictionary_zh_k.db') as conn:
    cursor = conn.cursor()
    message_title_zh = "通過100次「" + str(music_name_zh) + "」"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_name_dictionary_dic, music_name_zh))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_id_copyright_dic, music_copyright_name_zh))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (emblem_dictionary_description, message_title_zh))
    
with sqlite3.connect('assets/db/jp/dictionary_ja_k.db') as conn:
    cursor = conn.cursor()
    message_title_ja = "通過100次「" + str(music_name_ja) + "」"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_name_dictionary_dic, music_name_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (music_id_copyright_dic, music_copyright_name_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (emblem_dictionary_description, message_title_ja))
    
with sqlite3.connect('assets/db/gl/dictionary_en_m.db') as conn:
    cursor = conn.cursor()
    message_mission1_en = "Clear &quot;" + str(music_name_en) + "&quot;: x10"
    message_mission2_en = "Clear &quot;" + str(music_name_en) + "&quot;: x50"
    message_mission3_en = "Clear &quot;" + str(music_name_en) + "&quot;: x100"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic1, message_mission1_en))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic2, message_mission2_en))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic3, message_mission3_en))
    
with sqlite3.connect('assets/db/gl/dictionary_ko_m.db') as conn:
    cursor = conn.cursor()
    message_mission1_ko = str(music_name_ko) + " 10회 클리어"
    message_mission2_ko = str(music_name_ko) + " 50회 클리어"
    message_mission3_ko = str(music_name_ko) + " 100회 클리어"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic1, message_mission1_ko))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic2, message_mission2_ko))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic3, message_mission3_ko))
    
with sqlite3.connect('assets/db/gl/dictionary_zh_m.db') as conn:
    cursor = conn.cursor()
    message_mission1_zh = "完成10次「" + str(music_name_zh) + "」"
    message_mission2_zh = "完成50次「" + str(music_name_zh) + "」"
    message_mission3_zh = "完成100次「" + str(music_name_zh) + "」"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic1, message_mission1_zh))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic2, message_mission2_zh))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic3, message_mission3_zh))
    
with sqlite3.connect('assets/db/jp/dictionary_ja_m.db') as conn:
    cursor = conn.cursor()
    message_mission1_ja = "「" + str(music_name_ja) + "」を10回クリアする"
    message_mission2_ja = "「" + str(music_name_ja) + "」を50回クリアする"
    message_mission3_ja = "「" + str(music_name_ja) + "」を100回クリアする"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic1, message_mission1_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic2, message_mission2_ja))
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (mission_desc_dictionary_dic3, message_mission3_ja))

with sqlite3.connect('assets/db/gl/asset_a_en.db') as conn:
    cursor = conn.cursor()
    
    package_key_live = "music:" + str(live_id_masterdata)
    package_key_common = "main"
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
        package_key_movie = "live_movie:" + str(live_id_masterdata) + "_prime"
        fresh_version_movie = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie))

with sqlite3.connect('assets/db/gl/asset_i_en.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_i_en = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_i_en = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_i_en = cursor.fetchone()[0]
    update_main_asset_i_en = get_main_asset_i_en + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_i_en, update_main_asset_i_en))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_i_en))
                
    if videoprime_file != "":
        fresh_version_movie_i_en = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_i_en))
                    
with sqlite3.connect('assets/db/gl/asset_a_ko.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_a_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_a_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_a_ko = cursor.fetchone()[0]
    update_main_asset_a_ko = get_main_asset_a_ko + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_a_ko, update_main_asset_a_ko))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_a_ko))
                
    if videoprime_file != "":
        fresh_version_movie_a_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_a_ko))
                    
with sqlite3.connect('assets/db/gl/asset_i_ko.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_i_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_i_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_i_ko = cursor.fetchone()[0]
    update_main_asset_i_ko = get_main_asset_i_ko + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_i_ko, update_main_asset_i_ko))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_i_ko))
                
    if videoprime_file != "":
        fresh_version_movie_i_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_i_ko))
                    
with sqlite3.connect('assets/db/gl/asset_a_zh.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_a_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_a_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_a_zh = cursor.fetchone()[0]
    update_main_asset_a_zh = get_main_asset_a_zh + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_a_zh, update_main_asset_a_zh))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_a_zh))
                
    if videoprime_file != "":
        fresh_version_movie_a_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_a_zh))
                    
with sqlite3.connect('assets/db/gl/asset_i_zh.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_i_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_i_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_i_zh = cursor.fetchone()[0]
    update_main_asset_i_zh = get_main_asset_i_zh + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_i_zh, update_main_asset_i_zh))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_i_zh))
                
    if videoprime_file != "":
        fresh_version_movie_i_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_i_zh))
                    
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_a_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_a_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_a_ja = cursor.fetchone()[0]
    update_main_asset_a_ja = get_main_asset_a_ja + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_a_ja, update_main_asset_a_ja))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_a_ja))
                
    if videoprime_file != "":
        fresh_version_movie_a_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_a_ja))
                    
with sqlite3.connect('assets/db/jp/asset_i_ja.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_i_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_i_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_i_ja = cursor.fetchone()[0]
    update_main_asset_i_ja = get_main_asset_i_ja + 3
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '0');",
                (package_key_live, music_filename, music_live_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '6');",
                (package_key_common, music_sabi_filename, music_live_sabi_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, thumbnail_music_filename, thumbnail_music_size, donot_insert))
    cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '8');",
                (package_key_common, emblem_filename, thumbnail_emblem_size, donot_insert))
    cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                (fresh_version_main_i_ja, update_main_asset_i_ja))
    cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live, fresh_version_i_ja))
                
    if videoprime_file != "":
        fresh_version_movie_i_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', '7');",
                    (package_key_movie, movie_filename, movie_filesize, donot_insert))
        cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                    (package_key_movie, fresh_version_movie_i_ja))
                    
# Check if the file exists
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
sys.exit(1)
