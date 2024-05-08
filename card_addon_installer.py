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

modding_elichika_path = "assets/package/card/"

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

def calculate_parameter_value(min_value, max_value, min_level, max_level, level):
    # Calculate the range of levels
    level_range = max_level - min_level
    
    # Calculate the percentage of completion of the level range for the given level
    level_completion = (level - min_level) / level_range
    
    # Calculate the parameter value based on the percentage of completion
    parameter_value = int(min_value + (max_value - min_value) * level_completion)
    
    return parameter_value

# Function to generate a unique costume_id_masterdata
def generate_unique_costume_id(cursor):
    while True:
        new_id = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (new_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id
            
def generate_unique_card_id(cursor):
    while True:
        new_id_card = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_card WHERE id = ?;", (new_id_card,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id_card
                        
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
temp_directory = "assets/data/suit/temp/"
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
    
if chara_id_group == 13:
    print('Group: Myuzu')
elif chara_id_group == 14:
    print('Group: Aqours')
elif chara_id_group == 15:
    print('Group: Nijigasaki')
print('Description: ' + costume_description)
do_you_think_want_add_this = input("do you want add this? (y/n): ")

if do_you_think_want_add_this == "y" :
    clear_terminal()
else :
    clear_terminal()
    shutil.rmtree(temp_directory, ignore_errors=True)
    sys.exit(1)    

start_encrypt4 = temp_directory + active_skill_voice_file
start_encrypt5 = temp_directory + card_gacha_voice_file
start_encrypt6 = temp_directory + card_normal_file
start_encrypt7 = temp_directory + card_normal_thumbnail_file
start_encrypt8 = temp_directory + card_normal_still_file
start_encrypt9 = temp_directory + card_normal_deck_file
start_encrypt10 = temp_directory + card_awaken_file
start_encrypt11 = temp_directory + card_awaken_thumbnail_file
start_encrypt12 = temp_directory + card_awaken_still_file
start_encrypt13 = temp_directory + card_awaken_deck_file

if thumbnail_file != "":
    start_encrypt2 = temp_directory + thumbnail_file
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
card_thumbnail_filename = os.path.splitext(start_encrypt7.split("/")[-1])[0]
card_still_filename = os.path.splitext(start_encrypt8.split("/")[-1])[0]
card_deck_filename = os.path.splitext(start_encrypt9.split("/")[-1])[0]
card_awaken_filename = os.path.splitext(start_encrypt10.split("/")[-1])[0]
card_awaken_thumbnail_filename = os.path.splitext(start_encrypt11.split("/")[-1])[0]
card_awaken_still_filename = os.path.splitext(start_encrypt12.split("/")[-1])[0]
card_awaken_deck_filename = os.path.splitext(start_encrypt13.split("/")[-1])[0]
card_filesize = os.path.getsize(start_encrypt6)
card_thumbnail_filesize = os.path.getsize(start_encrypt7)
card_still_filesize = os.path.getsize(start_encrypt8)
card_deck_filesize = os.path.getsize(start_encrypt9)
card_awaken_filesize = os.path.getsize(start_encrypt10)
card_awaken_thumbnail_filesize = os.path.getsize(start_encrypt11)
card_awaken_still_filesize = os.path.getsize(start_encrypt12)
card_awaken_deck_filesize = os.path.getsize(start_encrypt13)

encrypted_card = "static/assets/" + os.path.splitext(start_encrypt6.split("/")[-1])[0]
encrypted_card_thumbnail = "static/assets/" + os.path.splitext(start_encrypt7.split("/")[-1])[0]
encrypted_card_still = "static/assets/" + os.path.splitext(start_encrypt8.split("/")[-1])[0]
encrypted_card_deck = "static/assets/" + os.path.splitext(start_encrypt9.split("/")[-1])[0]
encrypted_card_awaken = "static/assets/" + os.path.splitext(start_encrypt10.split("/")[-1])[0]
encrypted_card_awaken_thumbnail = "static/assets/" + os.path.splitext(start_encrypt11.split("/")[-1])[0]
encrypted_card_awaken_still = "static/assets/" + os.path.splitext(start_encrypt11.split("/")[-1])[0]
encrypted_card_awaken_deck = "static/assets/" + os.path.splitext(start_encrypt11.split("/")[-1])[0]

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
with sqlite3.connect('assets/db/jp/asset_a_ja.db') as conn:
    cursor = conn.cursor()
    
    sheet_name_file = read_file_and_select_text(start_encrypt4)
    sheet_name_file1 = read_file_and_select_text1(start_encrypt5)
    costume_path = costume_path_randomhash(cursor)
    card_path = image_card_path_randomhash(cursor)
    card_thumbnail_path = thumbnail_card_path_randomhash(cursor)
    card_still_path = still_card_path_randomhash(cursor)
    card_deck_path = deck_card_path_randomhash(cursor)
    card_awaken_path = image_card_awaken_path_randomhash(cursor)
    card_awaken_thumbnail_path = thumbnail_card_awaken_path_randomhash(cursor)
    card_awaken_still_path = still_card_awaken_path_randomhash(cursor)
    card_awaken_deck_path = deck_card_awaken_path_randomhash(cursor)
    cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (card_filename,))
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
    elif chara_id == 212:
        fix_mia_dep = 'w";'
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    elif chara_id == 212:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, ?);", (costume_path, fix_mia_dep))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '0W=');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, 'Qp?');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§n8#');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§~+');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§y7');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§Vr');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '§M|');", (costume_path,))
    elif chara_id == 211:
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '4fS');", (costume_path,))
        cursor.execute("INSERT INTO main.member_model_dependency (asset_path, dependency) VALUES (?, '?l=');", (costume_path,))
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
    trade_content_into_json = generate_unique_trade_content_id(cursor)
    trade_id_into_json = generate_unique_trade_id(cursor)
    costume_id_masterdata = generate_unique_costume_id(cursor)
    card_id_masterdata = generate_unique_card_id(cursor)
    costume_dictionary = "suit_name_" + str(costume_id_masterdata)
    costume_dictionary_masterdata = "k." + costume_dictionary
    donot_insert = None 
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
    
    cactive_skill_probablity_logic = int(active_skill_chance_percent * 100)
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_1_masterdata, active_skill_type, active_skill_1_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, active_skill_sp_gauge_point, cactive_skill_probablity_logic, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_2_masterdata, active_skill_type, active_skill_2_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, active_skill_sp_gauge_point, cactive_skill_probablity_logic, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_3_masterdata, active_skill_type, active_skill_3_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, active_skill_sp_gauge_point, cactive_skill_probablity_logic, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_4_masterdata, active_skill_type, active_skill_4_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, active_skill_sp_gauge_point, cactive_skill_probablity_logic, donot_insert, cactive_skill_icon))
    cursor.execute("INSERT INTO main.m_active_skill (id, skill_type, skill_rarity_type, skill_master_id, name, description, sp_gauge_point, trigger_probability, icon_asset_path, thumbnail_asset_path) VALUES (?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (active_skill_5_masterdata, active_skill_type, active_skill_5_masterdata, active_skill_dictionary_masterdata, active_skill_dictionary_desc1_masterdata, active_skill_sp_gauge_point, cactive_skill_probablity_logic, donot_insert, cactive_skill_icon))
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
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_1_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, active_skill_effect_value, active_skill_effect_scale_type, active_skill_effect_calculation_type, active_skill_effect_timing, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_2_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect2, active_skill_effect_scale_type, active_skill_effect_calculation_type, active_skill_effect_timing, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_3_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect3, active_skill_effect_scale_type, active_skill_effect_calculation_type, active_skill_effect_timing, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_4_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect4, active_skill_effect_scale_type, active_skill_effect_calculation_type, active_skill_effect_timing, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (active_skill_5_masterdata, active_skill_effect_target_parameter, active_skill_effect_type, cactive_skill_logic_effect5, active_skill_effect_scale_type, active_skill_effect_calculation_type, active_skill_effect_timing, donot_insert, active_skill_effect_finish_type, active_skill_effect_finish_value))
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
    ## dual skill not supported yet
    cpassive_skill_icon = "+H"
    cpassive_ability_skill_icon = "+H"
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_1_masterdata, passive_skill_dictionary_masterdata_1, passive_skill_dictionary_desc1_masterdata, passive_skill_1_masterdata, donot_insert, cpassive_skill_icon, passive_skill_trigger_type, passive_skill_chance_percent, passive_skill_condition_id1, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_2_masterdata, passive_skill_dictionary_masterdata_2, passive_skill_dictionary_desc2_masterdata, passive_skill_2_masterdata, donot_insert, cpassive_skill_icon, passive_skill_trigger_type, passive_skill_chance_percent, passive_skill_condition_id1, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_3_masterdata, passive_skill_dictionary_masterdata_3, passive_skill_dictionary_desc3_masterdata, passive_skill_3_masterdata, donot_insert, cpassive_skill_icon, passive_skill_trigger_type, passive_skill_chance_percent, passive_skill_condition_id1, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_4_masterdata, passive_skill_dictionary_masterdata_4, passive_skill_dictionary_desc4_masterdata, passive_skill_4_masterdata, donot_insert, cpassive_skill_icon, passive_skill_trigger_type, passive_skill_chance_percent, passive_skill_condition_id1, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_5_masterdata, passive_skill_dictionary_masterdata_5, passive_skill_dictionary_desc5_masterdata, passive_skill_5_masterdata, donot_insert, cpassive_skill_icon, passive_skill_trigger_type, passive_skill_chance_percent, passive_skill_condition_id1, donot_insert))
    cursor.execute("INSERT INTO main.m_passive_skill (id, name, description, rarity, skill_master_id, icon_asset_path, thumbnail_asset_path, trigger_type, trigger_probability, skill_condition_master_id1, skill_condition_master_id2) VALUES (?, ?, ?, '1', ?, ?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_dictionary_masterdata_ab1, passive_skill_dictionary_desc1ab_masterdata, passive_skill_ab1_masterdata, donot_insert, cpassive_ability_skill_icon, passive_skill_ability_trigger_type, passive_skill_ability_chance_percent, passive_skill_condition_id1, donot_insert))
    
    cpassive_skill_evaluation2_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up
    cpassive_skill_evaluation3_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up
    cpassive_skill_evaluation4_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up + passive_skill_evaluation_step_even_up
    cpassive_skill_evaluation5_logic = passive_skill_evaluation + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up + passive_skill_evaluation_step_even_up + passive_skill_evaluation_step_odd_up
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_1_masterdata, passive_skill_evaluation, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_2_masterdata, cpassive_skill_evaluation2_logic, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_3_masterdata, cpassive_skill_evaluation3_logic, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_4_masterdata, cpassive_skill_evaluation4_logic, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_5_masterdata, cpassive_skill_evaluation5_logic, passive_skill_target_id1, donot_insert, passive_skill_1_masterdata, donot_insert))
    cursor.execute("INSERT INTO main.m_skill (id, evaluation_param, skill_target_master_id1, skill_target_master_id2, skill_effect_master_id1, skill_effect_master_id2) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_ability_evaluation, passive_skill_ability_target_id1, donot_insert, passive_skill_ab1_masterdata, donot_insert))
    cpassive_skill_logic_effect2 = passive_skill_effect_value + passive_skill_effect_value_step_up * 1
    cpassive_skill_logic_effect3 = passive_skill_effect_value + passive_skill_effect_value_step_up * 2
    cpassive_skill_logic_effect4 = passive_skill_effect_value + passive_skill_effect_value_step_up * 3
    cpassive_skill_logic_effect5 = passive_skill_effect_value + passive_skill_effect_value_step_up * 4
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_1_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, passive_skill_effect_value, passive_skill_effect_scale_type, passive_skill_effect_calculation_type, passive_skill_effect_timing, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_2_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect2, passive_skill_effect_scale_type, passive_skill_effect_calculation_type, passive_skill_effect_timing, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_3_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect3, passive_skill_effect_scale_type, passive_skill_effect_calculation_type, passive_skill_effect_timing, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_4_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect4, passive_skill_effect_scale_type, passive_skill_effect_calculation_type, passive_skill_effect_timing, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_5_masterdata, passive_skill_effect_target_parameter, passive_skill_effect_type, cpassive_skill_logic_effect5, passive_skill_effect_scale_type, passive_skill_effect_calculation_type, passive_skill_effect_timing, donot_insert, passive_skill_effect_finish_type, passive_skill_effect_finish_value))
    cursor.execute("INSERT INTO main.m_skill_effect (id, target_parameter, effect_type, effect_value, scale_type, calc_type, timing, icon_asset_path, finish_type, finish_value) VALUES (?, ?, ?, ?, ?, ?);", (passive_skill_ab1_masterdata, passive_skill_ability_effect_target_parameter, passive_skill_ability_effect_type, passive_skill_ability_effect_value, passive_skill_ability_effect_scale_type, passive_skill_ability_effect_calculation_type, passive_skill_ability_effect_timing, donot_insert, passive_skill_ability_effect_finish_type, passive_skill_ability_effect_finish_value))
    
    # m_card
    if type_card == "SR":
        caddon_rarity = 20
        caddon_sp = 2
        caddon_exchange_item_id = 2
        caddon_passive_slot = 1
        caddon_passive_slot_max = 3
    elif type_card == "UR":
        caddon_rarity = 30
        caddon_sp = 3
        caddon_exchange_item_id = 3
        caddon_passive_slot = 1
        caddon_passive_slot_max = 3
    elif type_card == "FES" or type_card == "PARTY":
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
      
    cursor.execute("INSERT INTO main.m_card (id, member_m_id, school_idol_no, card_rarity_type, card_attribute, role, member_card_thumbnail_asset_path, at_gacha, at_event, training_tree_m_id, active_skill_voice_path, sp_point, exchange_item_id, role_effect_master_id, passive_skill_slot, max_passive_skill_slot) VALUES (?, ?, ?, ?, ?, ?, '>i', ?, ?, ?, ?, ?, ?, ?, ?, ?);", (card_id_masterdata, chara_id, new_school_idol_ja, caddon_rarity, attribute_card, role_card, caddon_flag_gacha, caddon_flag_event, card_id_masterdata, MISSING_VO, caddon_sp, caddon_exchange_item_id, role_card, caddon_passive_slot, caddon_passive_slot_max))

    # m_card_active_skill
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '1', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_1_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '2', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_2_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '3', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_3_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '4', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_4_masterdata))
    cursor.execute("INSERT INTO main.m_card_active_skill (card_master_id, skill_level, name, active_skill_master_id) VALUES (?, '5', ?, ?);", (card_id_masterdata, active_skill_dictionary_masterdata, active_skill_5_masterdata))
    
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
    cursor.execute("INSERT INTO main.m_card_awaken_parameter (card_master_id, parameter1, parameter2, parameter3) VALUES (?, ?, ?, ?);", (card_id_masterdata, card_awaken_appeal, card_awaken_stamina, card_awaken_technique))
    
    # m_card_grade_up_item
    if type_card == "SR":
        caddon_grade_up_val1 = 25
        caddon_grade_up_val2 = 10
    elif type_card == "UR" or type_card == "FES" or type_card == "PARTY":
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
    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, min_level_card, card_min_appeal, card_min_stamina, card_min_technique))
    for level in range(min_level_card + 1, max_level_card):
        appeal_rate = calculate_parameter_value(card_min_appeal, card_max_appeal, min_level_card, max_level_card, level)
        stamina_rate = calculate_parameter_value(card_min_stamina, card_max_stamina, min_level_card, max_level_card, level)
        technique_rate = calculate_parameter_value(card_min_technique, card_max_technique, min_level_card, max_level_card, level)
        cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, level, appeal, stamina, technique))
    cursor.execute("INSERT INTO main.m_card_parameter (card_m_id, level, appeal, stamina, technique) VALUES (?, ?, ?, ?, ?);", (card_id_masterdata, max_level_card, card_max_appeal, card_max_stamina, card_max_technique))
    
    # m_training_tree
    if type_card == "SR":
        ctraining_tree_passive_increase = 1
        ctraining_tree_design = 12
    elif type_card == "UR":
        ctraining_tree_passive_increase = 1
        ctraining_tree_design = 13
    elif type_card == "FES":
        ctraining_tree_design = 23
        ctraining_tree_passive_increase = 1
    elif type_card == "PARTY":
        ctraining_tree_design = 33
        ctraining_tree_passive_increase = 2
    ctraining_tree_logic = str(ctraining_tree_design) + str(chara_id) + str(role_card)
    cursor.execute("INSERT INTO main.m_training_tree (id, training_tree_mapping_m_id, training_tree_card_param_m_id, training_tree_card_passive_skill_increase_m_id) VALUES (?, ?, ?, ?);", (card_id_masterdata, ctraining_tree_logic, card_id_masterdata, ctraining_tree_passive_increase))
    
    # m_training_tree_card_param
    ## not done, need wrote this for each, very BIG, based on tree & role card, many value incorrect, also lim not added
    if type_card == "SR":
        if role_card = 1:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '2', ?);", (card_id_masterdata, card_training_tree_max_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '3', ?);", (card_id_masterdata, card_training_tree_max_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '4', ?);", (card_id_masterdata, card_training_tree_max_technique))
        elif role_card = 2:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '2', ?);", (card_id_masterdata, card_training_tree_max_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '3', ?);", (card_id_masterdata, card_training_tree_max_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '4', ?);", (card_id_masterdata, card_training_tree_max_technique))
        elif role_card = 3:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '2', ?);", (card_id_masterdata, card_training_tree_max_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '3', ?);", (card_id_masterdata, card_training_tree_max_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '4', ?);", (card_id_masterdata, card_training_tree_max_technique))
        elif role_card = 4:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '2', ?);", (card_id_masterdata, card_training_tree_max_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '3', ?);", (card_id_masterdata, card_training_tree_max_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '4', ?);", (card_id_masterdata, card_training_tree_max_technique))
    elif type_card == "UR":
        if role_card = 1:
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '2', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '6', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '8', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '12', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '28', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '30', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '32', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '35', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '39', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '41', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '43', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '46', '2', ?);", (card_id_masterdata, card_training_tree_min_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '21', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '23', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '25', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '48', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '52', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '53', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '54', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '57', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '59', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '60', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '67', '2', ?);", (card_id_masterdata, card_training_tree_med_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '70', '2', ?);", (card_id_masterdata, card_training_tree_max_appeal))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '1', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '5', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '9', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '11', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '13', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '14', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '29', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '31', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '33', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '36', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '38', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '45', '3', ?);", (card_id_masterdata, card_training_tree_min_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '16', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '17', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '18', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '19', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '20', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '58', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '61', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '62', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '65', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '69', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '71', '3', ?);", (card_id_masterdata, card_training_tree_med_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '72', '3', ?);", (card_id_masterdata, card_training_tree_max_stamina))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '3', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '4', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '7', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '10', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '15', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '27', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '34', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '37', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '40', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '42', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '44', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '47', '4', ?);", (card_id_masterdata, card_training_tree_min_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '22', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '24', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '26', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '49', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '50', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '51', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '55', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '56', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '63', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '64', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '66', '4', ?);", (card_id_masterdata, card_training_tree_med_technique))
            cursor.execute("INSERT INTO main.m_training_tree_card_param (id, training_content_no, training_content_type, value) VALUES (?, '68', '4', ?);", (card_id_masterdata, card_training_tree_max_technique))
        
    # m_training_tree_card_story_side
    ## will return as R character because there is no way to create new one
    if type_card == "SR":
        cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '9', '1', '121110011');", (card_id_masterdata))
    else:
        cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '9', '1', '121110011');", (card_id_masterdata))
        cursor.execute("INSERT INTO main.m_training_tree_card_story_side (card_m_id, training_content_type, training_content_no, story_side_m_id) VALUES (?, '11', '1', '121110011');", (card_id_masterdata))
        
    # m_training_tree_card_suit
    cursor.execute("INSERT INTO main.m_training_tree_card_suit (card_m_id, training_content_no, suit_m_id) VALUES (?, '1', ?);", (card_id_masterdata, costume_id_masterdata))
    
    # m_training_tree_card_voice
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '1', '1001014');", (card_id_masterdata))
    cursor.execute("INSERT INTO main.m_training_tree_card_voice (card_m_id, training_content_no, navi_action_id) VALUES (?, '2', '1001015');", (card_id_masterdata))
    
    # m_training_tree_progress_reward
    ## will return as stargem, recolor costume currectly not implemented
    if type_card == "SR":
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '40', '0', '1', '0', '10');", (card_id_masterdata))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '59', '0', '1', '0', '10');", (card_id_masterdata))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '75', '0', '1', '0', '20');", (card_id_masterdata))
    else:
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '46', '0', '1', '0', '10');", (card_id_masterdata))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '69', '0', '1', '0', '10');", (card_id_masterdata))
        cursor.execute("INSERT INTO main.m_training_tree_progress_reward (card_master_id, activate_num, display_order, content_type, content_id, content_amount) VALUES (?, '87', '0', '1', '0', '20');", (card_id_masterdata))
    # Insert record into the database
    cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, '1200', '0', ?, '1');", (trade_id_into_json, donot_insert))
    
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
        
    # Costume insert
    cursor.execute("INSERT INTO main.m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, '2', '0', ?, ?);",
                   (costume_id_masterdata, chara_id, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_ja))
    cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, '1200', '0', ?, '1');", (trade_id_into_json, donot_insert))
    cursor.execute("INSERT INTO main.m_trade_product_content (id, trade_product_master_id, content_display_order) VALUES (?, ?, '1');", (trade_content_into_json, trade_id_into_json))
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
                   (costume_id_masterdata, chara_id, costume_dictionary_masterdata, thumbnail_costume_path, costume_path, display_order_new_gl))
    cursor.execute("INSERT INTO main.m_trade_product (id, trade_master_id, source_amount_color_on, label, display_order) VALUES (?, '1200', '0', ?, '1');", (trade_id_into_json, donot_insert))
    cursor.execute("INSERT INTO main.m_trade_product_content (id, trade_product_master_id, content_display_order) VALUES (?, ?, '1');", (trade_content_into_json, trade_id_into_json))
    cursor.execute("INSERT INTO main.m_trade_product_content_category (trade_category_master_pattern_id, trade_category_master_id, content_type, content_id) VALUES (0, ?, '7', ?);", (chara_id_group, costume_id_masterdata))
   
    if chara_id == 209:
        cursor.execute("INSERT INTO main.m_suit_view (suit_master_id, view_status, model_asset_path) VALUES (?, '2', ?);", (costume_id_masterdata, rina_unmask_costume_path))

with sqlite3.connect('assets/db/jp/dictionary_ja_k.db') as conn:
    cursor = conn.cursor()
    active_skill1_desc_text_ja = "TEST"
    active_skill2_desc_text_ja = "TEST"
    active_skill3_desc_text_ja = "TEST"
    active_skill4_desc_text_ja = "TEST"
    active_skill5_desc_text_ja = "TEST"
    passive_skill1_desc_text_ja = "TEST"
    passive_skill2_desc_text_ja = "TEST"
    passive_skill3_desc_text_ja = "TEST"
    passive_skill4_desc_text_ja = "TEST"
    passive_skill5_desc_text_ja = "TEST"
    passive_skillab1_desc_text_ja = "TEST"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_ja))

with sqlite3.connect('assets/db/gl/dictionary_en_k.db') as conn:
    cursor = conn.cursor()
    active_skill1_desc_text_en = "TEST"
    active_skill2_desc_text_en = "TEST"
    active_skill3_desc_text_en = "TEST"
    active_skill4_desc_text_en = "TEST"
    active_skill5_desc_text_en = "TEST"
    passive_skill1_desc_text_en = "TEST"
    passive_skill2_desc_text_en = "TEST"
    passive_skill3_desc_text_en = "TEST"
    passive_skill4_desc_text_en = "TEST"
    passive_skill5_desc_text_en = "TEST"
    passive_skillab1_desc_text_en = "TEST"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_en))
    
with sqlite3.connect('assets/db/gl/dictionary_ko_k.db') as conn:
    cursor = conn.cursor()
    active_skill1_desc_text_ko = "TEST"
    active_skill2_desc_text_ko = "TEST"
    active_skill3_desc_text_ko = "TEST"
    active_skill4_desc_text_ko = "TEST"
    active_skill5_desc_text_ko = "TEST"
    passive_skill1_desc_text_ko = "TEST"
    passive_skill2_desc_text_ko = "TEST"
    passive_skill3_desc_text_ko = "TEST"
    passive_skill4_desc_text_ko = "TEST"
    passive_skill5_desc_text_ko = "TEST"
    passive_skillab1_desc_text_ko = "TEST"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_ko))
    
with sqlite3.connect('assets/db/gl/dictionary_zh_k.db') as conn:
    cursor = conn.cursor()
    active_skill1_desc_text_zh = "TEST"
    active_skill2_desc_text_zh = "TEST"
    active_skill3_desc_text_zh = "TEST"
    active_skill4_desc_text_zh = "TEST"
    active_skill5_desc_text_zh = "TEST"
    passive_skill1_desc_text_zh = "TEST"
    passive_skill2_desc_text_zh = "TEST"
    passive_skill3_desc_text_zh = "TEST"
    passive_skill4_desc_text_zh = "TEST"
    passive_skill5_desc_text_zh = "TEST"
    passive_skillab1_desc_text_zh = "TEST"
    cursor.execute("INSERT INTO main.m_dictionary (id, message) VALUES (?, ?);", (costume_dictionary, costume_name_zh))
            
with sqlite3.connect('serverdata.db') as conn:
    cursor = conn.cursor()     
    
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
        costume_price_val = 5000000

    cursor.execute("INSERT INTO main.s_trade_product (product_id, trade_id, source_amount, stock_amount, contents) VALUES (?, '1200', ?, 'null', ?);", (trade_id_into_json, costume_price_val, json_string_costume))
    print("added to gold exchange shop")

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
    
print("deleting temp folder")
shutil.rmtree(temp_directory, ignore_errors=True)
print("FINISHED")