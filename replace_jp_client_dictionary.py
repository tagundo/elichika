import sqlite3
import os
import shutil
import platform
import sys

def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')

# List of tuples containing pairs of source and target databases
dir_db_gl = "assets/db/gl/"
dir_db_jp = "assets/db/jp/"
clear_terminal()
print("Choose language you want change to JP client:")
print("1. English")
print("2. Korean")
print("3. Chinese")
print("4. Thailand")
lang = int(input("Enter the number corresponding you want to choose: "))
if lang == 1:
    lang = "en"
elif lang == 2:
    lang = "ko"
elif lang == 3:
    lang = "zh"
elif lang == 4:
    lang = "th"
else:
    sys.exit(1) 

conf_ok = input("you can't undo to JP language once changed, okay? press enter to change")

db_pairs = [
    (f'{dir_db_gl}dictionary_{lang}_android.db', f'{dir_db_jp}dictionary_ja_android.db'),
    (f'{dir_db_gl}dictionary_{lang}_k.db', f'{dir_db_jp}dictionary_ja_k.db'),
    (f'{dir_db_gl}dictionary_{lang}_dummy.db', f'{dir_db_jp}dictionary_ja_dummy.db'),
    (f'{dir_db_gl}dictionary_{lang}_inline_image.db', f'{dir_db_jp}dictionary_ja_inline_image.db'),
    (f'{dir_db_gl}dictionary_{lang}_ios.db', f'{dir_db_jp}dictionary_ja_ios.db'),
    (f'{dir_db_gl}dictionary_{lang}_m.db', f'{dir_db_jp}dictionary_ja_m.db'),
    (f'{dir_db_gl}dictionary_{lang}_petag.db', f'{dir_db_jp}dictionary_ja_petag.db'),
    (f'{dir_db_gl}dictionary_{lang}_v.db', f'{dir_db_jp}dictionary_ja_v.db'),
]

s_gl = f'{dir_db_gl}dictionary_{lang}_s.db'
s_ja = f'{dir_db_jp}dictionary_ja_s.db'

for source_db, target_db in db_pairs:
    # Connect to source and target databases
    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)

    # Create cursor objects
    source_cursor = source_conn.cursor()
    target_cursor = target_conn.cursor()

    # Execute SELECT query to retrieve data from the source table
    source_cursor.execute("SELECT * FROM m_dictionary")
    rows = source_cursor.fetchall()

    # Iterate through rows and update target database if necessary
    for row in rows:
        text_string, replacement = row[0], row[1]
        target_cursor.execute("UPDATE m_dictionary SET message = ? WHERE id = ?", (replacement, text_string))

    # Commit changes in target database
    target_conn.commit()

    # Close connections
    source_conn.close()
    target_conn.close()

shutil.copy(s_gl, s_ja)
print("Finished")