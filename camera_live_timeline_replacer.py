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

# init variable
live_timeline_file = ""
live_timeline_num = None
timeline = ""
live_stage_master_id = None
stage_effect_asset_path = ""
live_prop_skeleton_asset_path =""
quality_setitng_set_id = None
shader_variant_asset_path = ""


check_json_config = "config.json"

if not os.path.exists(check_json_config):
    print('Config file is missing, Exiting...')
    sys.exit(1)

def is_termux():
    return 'com.termux' in os.getenv('PREFIX', '')

# Set folder path based on environment
if is_termux():
    modding_elichika_path = os.path.expanduser('~/storage/downloads/sukusta/livetimeline/')
    termux_storage_chc = os.path.expanduser('~/storage/')
    if not os.path.exists(termux_storage_chc):
        print('Path is missing, please execute termux-setup-storage command and allow it')
        sys.exit(1)
else:
    # Set a default or other path if not in Termux
    modding_elichika_path = "assets/package/livetimeline/"

if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)

encrypted_folder = "static/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)

batch_proccess_list = []
is_nested = False
mod_installed = False

def open_and_check_zip(file_path):
    global is_nested  # To modify the global variable
    try:
        is_nested = False
        # Open the zip file in read mode
        with zipfile.ZipFile(file_path, 'r') as zip_ref2:
            print(f"Contents of '{file_path}':")
            # List all files in the zip
            for file_name in zip_ref2.namelist():
                print(f" - {file_name}")
                # Check if the file is another zip file
                if file_name.endswith('.zip'):
                    print(f"  -> Found nested zip file: {file_name}")
                    is_nested = True
            if is_nested:
                # Create a path for nested extraction
                extracted_path = os.path.splitext(os.path.basename(file_path))[0]
                nested_path = os.path.join("assets", "package", ".nested", extracted_path)
                os.makedirs(nested_path, exist_ok=True)
                zip_ref2.extractall(nested_path)
            else:
                batch_proccess_list.append(file_path)
                
    except zipfile.BadZipFile:
        print(f"Error: '{file_path}' is not a valid zip file.")
    except Exception as e:
        print(f"An error occurred: {e}")

def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')

def generate_crc32(sukusta_path):
    with open(sukusta_path, 'rb') as f_suku:
        file_data_suku = f_suku.read()
    return f"{zlib.crc32(file_data_suku) & 0xFFFFFFFF:08x}"  # Unsigned CRC32 in hex format

def manipulate_file(data, keys_0, keys_1, keys_2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF

# Function to generate a live_timeline_id_masterdata
def generate_unique_live_timeline_id(cursor):
    while True:
        new_id = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_live WHERE live_id = ?;", (new_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_id
                        
def live_timeline_path_randomhash(cursor):
    while True:
        new_hash2 = format(random.randint(0, 0xFFFFFFFF), 'x')
        cursor.execute("SELECT COUNT(*) FROM main.live_timeline WHERE asset_path = ?;", (new_hash2,))
        count = cursor.fetchone()[0]
        if count == 0:
            return new_hash2
        
def load_dependencies_from_db(db_path):
    """ live_timeline_dependency 테이블에서 dependencies를 로드하는 함수 """
    dependencies = {}

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_path, dependency FROM main.live_timeline_dependency")
            rows = cursor.fetchall()
            
            for asset_path, dependency in rows:
                if asset_path not in dependencies:
                    dependencies[asset_path] = []
                dependencies[asset_path].append(dependency)

    except sqlite3.Error as e:
        print(f" Error loading dependencies from {db_path}: {e}")

    return dependencies

# explorer code
clear_terminal()
temp_directory = "assets/package/.cache/"
shutil.rmtree(temp_directory, ignore_errors=True)            
nested_path_batch = "assets/package/.nested/"
shutil.rmtree(nested_path_batch, ignore_errors=True)

# List all files in the directory with a ".zip" extension
if is_termux():
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
    do_you_think_want_add_this = input("Do you want to proceed? (y/n): ")
    if do_you_think_want_add_this != "n" :
        pass
    else :
        clear_terminal()
        shutil.rmtree(temp_directory, ignore_errors=True)
        sys.exit(1)
    do_backup_is_important = input("would you like backup database? (y/n): ")
    if do_backup_is_important == "y" :
        backup_operate(filelist)
    else :
        print('well then do your own risk')
else:
    import tkinter as tk
    from tkinter import filedialog
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    zip_file_path = filedialog.askopenfilenames(title="Locate Zip File")
    if zip_file_path:
        for print_addon in zip_file_path:
            print(f"Selected: {print_addon}")
    else:
        print("No file selected")
        sys.exit(1)
    response = messagebox.askyesnocancel("Confirmation", "Do you want to backup database?")
    if response is True:  # User clicked "Yes"
        print("User chose Yes.")
        backup_operate(filelist)
    elif response is False:  # User clicked "No"
        print("User chose No.")
    elif response is None:  # User clicked "Cancel"
        sys.exit(1)

if is_termux():
    zip_file_paths = [zip_file_path] # fix termux
    for zip_file_path_batch in zip_file_paths:
        open_and_check_zip(zip_file_path_batch)
else:
    for zip_file_path_batch in zip_file_path:
        open_and_check_zip(zip_file_path_batch)
        
for root3, dirs, files3 in os.walk(nested_path_batch):
    for file4 in files3:
        if file4.endswith(".zip"):
            # Append the full path of the .zip file to the list
            batch_proccess_list.append(os.path.join(root3, file4))
            
for mass_addon in batch_proccess_list:
    os.makedirs(temp_directory, exist_ok=True)
    with open(mass_addon, 'rb') as zip_file:
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

    start_encrypt1 = temp_directory + live_timeline_file


    # Extract filename and filesize from background_file
    live_timeline_filename = os.path.splitext(start_encrypt1.split("/")[-1])[0]
    # Replace with actual method to get filesize
    live_timeline_size = os.path.getsize(start_encrypt1)

    encrypted_live_timeline = "static/" + os.path.splitext(start_encrypt1.split("/")[-1])[0]

    # encrypting asset first

    with open(start_encrypt1, "rb") as file:
        data = bytearray(file.read())

        key_0 = 12345
        key_1 = 0
        key_2 = 0
        manipulate_file(data, key_0, key_1, key_2)

        with open(encrypted_live_timeline, "wb") as file:
            file.write(data)

    print("asset encrypted")

    # Organize the dependency list for each timeline in db(gl)
    dependencies_db_path = "assets/db/gl/asset_a_en.db"
    dependencies = load_dependencies_from_db(dependencies_db_path)

    if not dependencies:
        print(f" Error: No dependencies found in {dependencies_db_path}. Please check the database.")
        sys.exit(1)

    with sqlite3.connect('assets/db/gl/asset_a_en.db') as conn:
        cursor = conn.cursor()
        
        live_timeline_path = live_timeline_path_randomhash(cursor)

    # Extract repetitive database processing logic into a function
    def insert_live_timeline(db_path, live_timeline_filename, live_timeline_path, live_timeline_size, timeline):
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Insert into m_asset_pack (light download auto delete fix)
            cursor.execute("INSERT INTO main.m_asset_pack (pack_name, auto_delete) VALUES (?, '0');", (live_timeline_filename,))
            
            # Insert into live_timeline
            cursor.execute(
                "INSERT INTO main.live_timeline (asset_path, pack_name, head, size, key1, key2) VALUES (?, ?, '0', ?, '0', '0');",
                (live_timeline_path, live_timeline_filename, live_timeline_size)
            )

            # Insert into live_timeline_dependency (if a corresponding dependency exists)
            if timeline in dependencies:
                for dependency in dependencies[timeline]:
                    cursor.execute("INSERT INTO main.live_timeline_dependency (asset_path, dependency) VALUES (?, ?);",
                                   (live_timeline_path, dependency))

    # List of databases to execute
    databases = [
        "assets/db/jp/asset_a_ja.db",
        "assets/db/jp/asset_i_ja.db",
        "assets/db/gl/asset_a_en.db",
        "assets/db/gl/asset_a_ko.db",
        "assets/db/gl/asset_a_zh.db",
        "assets/db/gl/asset_i_en.db",
        "assets/db/gl/asset_i_ko.db",
        "assets/db/gl/asset_i_zh.db"
    ]

    # Execute `insert_live_timeline` for all databases
    for db in databases:
        insert_live_timeline(db, live_timeline_filename, live_timeline_path, live_timeline_size, timeline)



    # Connect to masterdata.db and perform INSERT
    with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
        cursor = conn.cursor()
        
        donot_insertbg = None
        live_timeline_id_masterdata = generate_unique_live_timeline_id(cursor)


    # Execute UPDATE SQL
    sql = """
    UPDATE "main"."m_live_3d_asset"
    SET 
        "timeline" = ?,
        "live_stage_master_id" = ?,
        "stage_effect_asset_path" = ?,
        "quality_setitng_set_id" = ?,
        "shader_variant_asset_path" = ?
    WHERE 
        "id" = ?;
    """
    data = (live_timeline_path, live_stage_master_id, stage_effect_asset_path, quality_setitng_set_id, shader_variant_asset_path, live_timeline_num)
    with sqlite3.connect('assets/db/gl/masterdata.db') as conn:
        cursor = conn.cursor()
        cursor.execute(sql, data)
        print(f"ID {live_timeline_num} has been successfully updated to gl masterdata.db")
    with sqlite3.connect('assets/db/jp/masterdata.db') as conn:
        cursor = conn.cursor()
        cursor.execute(sql, data)
        print(f"ID {live_timeline_num} has been successfully updated to jp masterdata.db")
        
    # experimental add cdn asset to db
    def insert_cdn_asset(db_path, live_timeline_id_masterdata, live_timeline_filename, live_timeline_size):
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            package_key_live_timeline = f"live:{live_timeline_id_masterdata}"
            category_live_timeline = '0'
            fresh_version = hashlib.sha1(str(random.random()).encode()).hexdigest()

            cursor.execute(
                "INSERT INTO main.m_asset_package_mapping (package_key, pack_name, file_size, metapack_name, metapack_offset, category) VALUES (?, ?, ?, ?, '0', ?);",
                (package_key_live_timeline, live_timeline_filename, live_timeline_size, None, category_live_timeline)
            )
            cursor.execute(
                "INSERT INTO main.m_asset_package (package_key, version, pack_num) VALUES (?, ?, '1');",
                (package_key_live_timeline, fresh_version)
            )

    # Execute `insert_cdn_asset` for all databases
    for db in databases:
        insert_cdn_asset(db, live_timeline_id_masterdata, live_timeline_filename, live_timeline_size)


        
    print("deleting temp folder")
    shutil.rmtree(temp_directory, ignore_errors=True)
    mod_installed = True

if mod_installed:
    with open(check_json_config, 'r') as f:
        config_elichika = json.load(f)
        xcheck_cdn = config_elichika.get('cdn_server')
        if xcheck_cdn != "http://127.0.0.1:8080/static":
            config_elichika['cdn_server'] = "http://127.0.0.1:8080/static"
            with open(check_json_config, 'w') as f:
                json.dump(config_elichika, f, indent=4)
                print("CDN server updated to http://127.0.0.1:8080/static")
                
    print("deleting nested folder")
    shutil.rmtree(nested_path_batch, ignore_errors=True)
    print("FINISHED")
else:
    print("Nothing installed")
       
