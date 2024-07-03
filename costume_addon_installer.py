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

# init variable

costume_name_en = ""
costume_name_ko = ""
costume_name_zh = ""
costume_name_ja = ""
costume_description = ""

costume_file = ""
costume_facedynamic_file = ""
rina_unmask_costume_file = ""
thumbnail_file = ""
chara_id = None
chara_id_append = None
id_costume = None
id_trade_product = None

check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

modding_elichika_path = "assets/package/suit/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

encrypted_folder = "static/assets/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)
       
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

# Function to generate a unique costume_id_masterdata
def generate_unique_costume_id(cursor):
    while True:
        new_id = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (new_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id
            
def generate_unique_trade_id(cursor):
    while True:
        new_id333 = random.randint(0, 999)
        formatted_id = f"{channel_exchange_trade}{new_id333:03}"
        cursor.execute("SELECT COUNT(*) FROM main.m_trade_product WHERE id = ?;", (formatted_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id333        
            
def costume_path_randomhash(cursor):
    while True:
        new_hash1 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.member_model WHERE asset_path = ?;", (new_hash1,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash1
            
def costume_facedynamic_path_randomhash(cursor):
    while True:
        new_hash1ggg = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.member_model WHERE asset_path = ?;", (new_hash1ggg,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash1ggg
            
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

start_encrypt1 = temp_directory + costume_file
costume_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
costume_filesize = os.path.getsize(start_encrypt1)
file_extension = start_encrypt1.split(".")[-1]

if file_extension.isdigit():
    chara_id = int(file_extension)

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
if costume_name_en != "":
    print('Name: ' + costume_name_en)
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
else:
    print("Invalid chara id")
    sys.exit(1)  
    
if chara_id_group == 13:
    print('Group: Myuzu')
elif chara_id_group == 14:
    print('Group: Aqours')
elif chara_id_group == 15:
    print('Group: Nijigasaki')
if costume_description != "":
    print('Description: ' + costume_description)
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
    
if thumbnail_file != "":
    start_encrypt2 = temp_directory + thumbnail_file
    thumbnail_costume_filename = os.path.splitext(start_encrypt2.split("/")[-1])[0]
    thumbnail_costume_size = os.path.getsize(start_encrypt2)
    encrypted_thumbnail = "static/assets/" + os.path.splitext(start_encrypt2.split("/")[-1])[0]
    if not thumbnail_costume_filename.isalnum() or not thumbnail_costume_filename.islower():
        print('Invalid Thumbnail Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)  

if costume_facedynamic_file != "":
    start_encrypt4 = temp_directory + costume_facedynamic_file
    facedynamic_costume_filename = os.path.splitext(start_encrypt4.split("/")[-1])[0]
    facedynamic_costume_size = os.path.getsize(start_encrypt4)
    encrypted_facedynamic = "static/assets/" + os.path.splitext(start_encrypt4.split("/")[-1])[0]
    if not facedynamic_costume_filename.isalnum() or not facedynamic_costume_filename.islower():
        print('Invalid Facedynamic Filename, Exiting.')
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)  

# perform check length to avoid auto delete
if not costume_filename.isalnum() or not costume_filename.islower():
    print('Invalid Costume Filename, Exiting.')
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)  

encrypted_costume = "static/assets/" + os.path.splitext(start_encrypt1.split("/")[-1])[0]

if chara_id == 209:
    start_encrypt3 = temp_directory + rina_unmask_costume_file
    rina_unmask_costume_filename = os.path.splitext(start_encrypt3.split("/")[-1])[0]
    rina_unmask_costume_filesize = os.path.getsize(start_encrypt3)
    encrypted_rina_unmask = "static/assets/" + os.path.splitext(start_encrypt3.split("/")[-1])[0]

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

if thumbnail_file != "":
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

if costume_facedynamic_file != "":
    if not os.path.exists(encrypted_facedynamic):
        with open(start_encrypt4, "rb") as file:
            data = bytearray(file.read())

            key_0 = 12345
            key_1 = 0
            key_2 = 0
            print("encrypting facedynamic")
            manipulate_file(data, key_0, key_1, key_2)

            with open(encrypted_facedynamic, "wb") as file:
                file.write(data)
    else:
        print("facedynamic already encrypted")

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

print("assets encrypted")
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM m_asset_pack WHERE pack_name = ?", (costume_filename,))
    result_chcc = cursor.fetchone()
    if result_chcc[0] > 0:
        print(f"This costume already exists in the database")
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1) 
        
    if costume_facedynamic_file != "":
        costume_facedynamic_path = costume_facedynamic_path_randomhash(cursor)
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (facedynamic_costume_filename,))
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (costume_facedynamic_path, facedynamic_costume_filename, facedynamic_costume_size))
        
    costume_path = costume_path_randomhash(cursor)
    if thumbnail_file != "":
        thumbnail_costume_path = thumbnail_path_randomhash(cursor)
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

# REST CODE TO GL CLIENT & IOS PLATFORM

with sqlite3.connect('assets/db/jp/asset_i_ja.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
 
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_a_en.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
                   
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_i_en.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
 
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_a_ko.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
                   
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_i_ko.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))     
 
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_a_zh.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))    
 
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

with sqlite3.connect('assets/db/gl/asset_i_zh.db') as conn:
    cursor = conn.cursor()
    
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (thumbnail_costume_filename,))
        cursor.execute("INSERT INTO main.texture (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                       (thumbnail_costume_path, thumbnail_costume_filename, thumbnail_costume_size))
                       
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (costume_filename,))
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (rina_unmask_costume_filename,))
        
    cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (costume_path, costume_filename, costume_filesize))
                                 
    if chara_id == 209:
        cursor.execute("INSERT INTO main.member_model (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                   (rina_unmask_costume_path, rina_unmask_costume_filename, rina_unmask_costume_filesize))       
 
    if chara_id == 1:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_kanan_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Tv');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§?D#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§j^');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
    elif chara_id == 108:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_ayumu_dep))
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:        
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '^/)');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '$EZ');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'sgs');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
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
        if costume_facedynamic_file != "":
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, costume_facedynamic_path))
        else:
            cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'oq0');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))

# Connect to masterdata.db and perform INSERT
with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
    cursor = conn.cursor()

    # Generate a unique costume_id_masterdata
    channel_exchange_trade = 50000 + int(chara_id)
    if id_costume is None:
        costume_id_masterdata = generate_unique_costume_id(cursor)
    else:
        costume_id_masterdata = id_costume
        
    if id_trade_product is None:
        zgenerate_id = generate_unique_trade_id(cursor)
        trade_id_into_json = str(channel_exchange_trade) + str(zgenerate_id)
    else:
        formatted_id_trade_product = f"{id_trade_product:03}"
        trade_id_into_json = str(channel_exchange_trade) + str(formatted_id_trade_product)
        
    if chara_id_append is None:
        chara_id_suit = chara_id
    else:
        chara_id_suit = chara_id_append
        
    trade_content_into_json = str(trade_id_into_json) + "01"

    costume_dictionary = "suit_name_" + str(costume_id_masterdata)
    costume_dictionary_masterdata = "k." + costume_dictionary
    donot_insert = None 
    
    # Find the minimum display_order for the given chara_id
    cursor.execute("SELECT MIN(display_order) FROM main.m_suit WHERE member_m_id = ?;", (chara_id,))
    result = cursor.fetchone()
    min_display_order_ja = result[0] if result[0] is not None else 0

    # Calculate the new display_order (decrease by 1)
    display_order_new_ja = min_display_order_ja - 1
    
    # use chara thumbnail if thumbnail file is empty
    if thumbnail_file == "" and chara_id == 1:
        thumbnail_costume_path = "Y0"
    elif thumbnail_file == "" and chara_id == 2:
        thumbnail_costume_path = "y{"
    elif thumbnail_file == "" and chara_id == 3:
        thumbnail_costume_path = "q["
    elif thumbnail_file == "" and chara_id == 4:
        thumbnail_costume_path = "~5"
    elif thumbnail_file == "" and chara_id == 5:
        thumbnail_costume_path = "hE"
    elif thumbnail_file == "" and chara_id == 6:
        thumbnail_costume_path = "r5"
    elif thumbnail_file == "" and chara_id == 7:
        thumbnail_costume_path = "d>"
    elif thumbnail_file == "" and chara_id == 8:
        thumbnail_costume_path = "uY"
    elif thumbnail_file == "" and chara_id == 9:
        thumbnail_costume_path = ";s"
    elif thumbnail_file == "" and chara_id == 101:
        thumbnail_costume_path = "h\""
    elif thumbnail_file == "" and chara_id == 102:
        thumbnail_costume_path = "(+"
    elif thumbnail_file == "" and chara_id == 103:
        thumbnail_costume_path = "j{"
    elif thumbnail_file == "" and chara_id == 104:
        thumbnail_costume_path = "<_"
    elif thumbnail_file == "" and chara_id == 105:
        thumbnail_costume_path = "a6"
    elif thumbnail_file == "" and chara_id == 106:
        thumbnail_costume_path = "O_"
    elif thumbnail_file == "" and chara_id == 107:
        thumbnail_costume_path = "`8"
    elif thumbnail_file == "" and chara_id == 108:
        thumbnail_costume_path = "fQ"
    elif thumbnail_file == "" and chara_id == 109:
        thumbnail_costume_path = "Y'"
    elif thumbnail_file == "" and chara_id == 201:
        thumbnail_costume_path = "a}"
    elif thumbnail_file == "" and chara_id == 202:
        thumbnail_costume_path = "E|"
    elif thumbnail_file == "" and chara_id == 203:
        thumbnail_costume_path = "TO"
    elif thumbnail_file == "" and chara_id == 204:
        thumbnail_costume_path = "TF"
    elif thumbnail_file == "" and chara_id == 205:
        thumbnail_costume_path = "4]"
    elif thumbnail_file == "" and chara_id == 206:
        thumbnail_costume_path = "R)"
    elif thumbnail_file == "" and chara_id == 207:
        thumbnail_costume_path = ","
    elif thumbnail_file == "" and chara_id == 208:
        thumbnail_costume_path = "7`"
    elif thumbnail_file == "" and chara_id == 209:
        thumbnail_costume_path = "-/"
    elif thumbnail_file == "" and chara_id == 210:
        thumbnail_costume_path = "[]Z"
    elif thumbnail_file == "" and chara_id == 211:
        thumbnail_costume_path = "5|["
    elif thumbnail_file == "" and chara_id == 212:
        thumbnail_costume_path = "-C;"
        
    # Insert the new record with the updated display_order
    cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '2', '0', ?, ?);",
                   (costume_id_masterdata, chara_id_suit, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_ja))
    cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, ?, '0', ?, '1');", (trade_id_into_json, channel_exchange_trade, donot_insert))
    cursor.execute("INSERT INTO main.m_trade_product_content (id, trade_product_master_id, content_display_order) VALUES (?, ?, '0');", (trade_content_into_json, trade_id_into_json))
    cursor.execute("INSERT INTO main.m_trade_product_content_category (trade_category_master_pattern_id, trade_category_master_id, content_type, content_id) VALUES (0, ?, '7', ?);", (chara_id_group, costume_id_masterdata))
   
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (costume_id_masterdata, rina_unmask_costume_path))

with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
    cursor = conn.cursor()
    
    # Find the minimum display_order for the given chara_id
    cursor.execute("SELECT MIN(display_order) FROM main.m_suit WHERE member_m_id = ?;", (chara_id,))
    result = cursor.fetchone()
    min_display_order_gl = result[0] if result[0] is not None else 0

    # Calculate the new display_order (decrease by 1)
    display_order_new_gl = min_display_order_gl - 1

    # Insert the new record with the updated display_order
    cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '2', '0', ?, ?);",
                   (costume_id_masterdata, chara_id_suit, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_gl))
    cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, ?, '0', ?, '1');", (trade_id_into_json, channel_exchange_trade, donot_insert))
    cursor.execute("INSERT INTO main.m_trade_product_content (id, trade_product_master_id, content_display_order) VALUES (?, ?, '0');", (trade_content_into_json, trade_id_into_json))
    cursor.execute("INSERT INTO main.m_trade_product_content_category (trade_category_master_pattern_id, trade_category_master_id, content_type, content_id) VALUES (0, ?, '7', ?);", (chara_id_group, costume_id_masterdata))
   
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (costume_id_masterdata, rina_unmask_costume_path))
            
with sqlite3.connect('serverdata.db') as conn:
    cursor = conn.cursor()  
    
    cursor.execute("SELECT COUNT(*) FROM s_trade_product WHERE product_id = ?", (trade_id_into_json,))
    result_chc2c = cursor.fetchone()
    if result_chc2c[0] > 0:
        print(f"This trade product already exists in the database")
    else:
        json_data_costume = [{
        "content_type": 7,
        "content_id": costume_id_masterdata,
        "content_amount": 1
        }]
        json_string_costume = json.dumps(json_data_costume)

        costume_free_price = input("do you want make as free? (y/n): ")

        if costume_free_price == "y" :
            costume_price_val = 0
        else :
            costume_price_val = 110

        cursor.execute("INSERT INTO main.s_trade_product (product_id, trade_id, source_amount, stock_amount, contents) VALUES (?, ?, ?, '1', ?);", (trade_id_into_json, channel_exchange_trade, costume_price_val, json_string_costume))
        print("added to channel exchange shop")

with sqlite3.connect('assets/db/gl/asset_a_en.db') as conn:
    cursor = conn.cursor()
    
    donot_insert = None
    package_key_costume = "suit:" + str(costume_id_masterdata)
    package_key_thumbnail = "main"
    category_costume = '3'
    category_thumbnail = '8'
    fresh_version = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset = cursor.fetchone()[0]
    update_main_asset = get_main_asset + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version))
    else:
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
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main, update_main_asset))

with sqlite3.connect('assets/db/gl/asset_i_en.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_ei = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_ei = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_ei = cursor.fetchone()[0]
    update_main_asset_ei = get_main_asset_ei + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_ei))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ei))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ei))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_ei))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_ei, update_main_asset_ei))
                
with sqlite3.connect('assets/db/gl/asset_a_ko.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_ko = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_ko = cursor.fetchone()[0]
    update_main_asset_ko = get_main_asset_ko + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_ko))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ko))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ko))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_ko))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_ko, update_main_asset_ko))
                
with sqlite3.connect('assets/db/gl/asset_i_ko.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_ik = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_ik = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_ik = cursor.fetchone()[0]
    update_main_asset_ik = get_main_asset_ik + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_ik))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ik))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ik))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_ik))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_ik, update_main_asset_ik))
                
with sqlite3.connect('assets/db/gl/asset_a_zh.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_zh = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_zh = cursor.fetchone()[0]
    update_main_asset_zh = get_main_asset_zh + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_zh))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_zh))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_zh))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_zh))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_zh, update_main_asset_zh))
                
with sqlite3.connect('assets/db/gl/asset_i_zh.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_zi = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_zi = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_zi = cursor.fetchone()[0]
    update_main_asset_zi = get_main_asset_zi + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_zi))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_zi))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_zi))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_zi))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_zi, update_main_asset_zi))
                
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_ja = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_ja = cursor.fetchone()[0]
    update_main_asset_ja = get_main_asset_ja + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_ja))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ja))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ja))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_ja))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_ja, update_main_asset_ja))
                
with sqlite3.connect('assets/db/jp/asset_i_ja.db') as conn:
    cursor = conn.cursor()
    
    fresh_version_ji = hashlib.sha1(str(random.random()).encode()).hexdigest()
    fresh_version_main_ji = hashlib.sha1(str(random.random()).encode()).hexdigest()
    
    cursor.execute("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = 'main';")
    get_main_asset_ji = cursor.fetchone()[0]
    update_main_asset_ji = get_main_asset_ji + 1
    if costume_facedynamic_file != "":
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '3');",
                        (package_key_costume, fresh_version_ji))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, facedynamic_costume_filename, facedynamic_costume_size, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ji))
    else:
        if chara_id == 209:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, rina_unmask_costume_filename, rina_unmask_costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '2');",
                        (package_key_costume, fresh_version_ji))
        else:
            cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                        (package_key_costume, costume_filename, costume_filesize, donot_insert, category_costume))
            cursor.execute("INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                        (package_key_costume, fresh_version_ji))
    if thumbnail_file != "":
        cursor.execute("INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                    (package_key_thumbnail, thumbnail_costume_filename, thumbnail_costume_size, donot_insert, category_thumbnail))
        cursor.execute("REPLACE INTO main.m_asset_package (package_key, version, pack_num) VALUES ('main', ?, ?);",
                    (fresh_version_main_ji, update_main_asset_ji))

with sqlite3.connect('assets/db/jp/dictionary_ja_k.db') as conn:
    cursor = conn.cursor()
    if costume_name_ja == "":
        costume_name_ja = package_key_costume
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_ja))

with sqlite3.connect('assets/db/gl/dictionary_en_k.db') as conn:
    cursor = conn.cursor()
    if costume_name_en == "":
        costume_name_en = package_key_costume
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_en))
    
with sqlite3.connect('assets/db/gl/dictionary_ko_k.db') as conn:
    cursor = conn.cursor()
    if costume_name_ko == "":
        costume_name_ko = package_key_costume
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_ko))
    
with sqlite3.connect('assets/db/gl/dictionary_zh_k.db') as conn:
    cursor = conn.cursor()
    if costume_name_zh == "":
        costume_name_zh = package_key_costume
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_zh))
    
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