
import sqlite3
import random
import os

def generate_unique_costume_id(cursor):
    while True:
        new_id = random.randint(0, 999999999)
        cursor.execute("SELECT COUNT(*) FROM main.m_suit WHERE id = ?;", (new_id,))
        if cursor.fetchone()[0] == 0:
            return new_id

def get_real_costume_name(dict_cursor, name_key):
    """Function to get actual costume name from dictionary_en_k.db"""
    # Remove 'k.' prefix from masterdata
    clean_key = name_key.replace('k.', '') if name_key.startswith('k.') else name_key
    dict_cursor.execute("SELECT message FROM main.m_dictionary WHERE id = ?", (clean_key,))
    res = dict_cursor.fetchone()
    return res[0] if res else name_key

def list_costumes_by_character(cursor, dict_cursor, chara_id):
    """Function to query costume list for a specific character (with number selection feature)"""
    cursor.execute(
        "SELECT id, name FROM m_suit WHERE member_m_id = ? "
        "AND name NOT LIKE '%_cloned' "
        "AND name NOT LIKE '%복제' "
        "AND name NOT LIKE '%克隆' "
        "AND name NOT LIKE '%โคลน' "
        "AND name NOT LIKE '%クローン' "
        "ORDER BY display_order",
        (chara_id,)
    )
    rows = cursor.fetchall()
    
    if not rows:
        print(f"No costumes found for character ID {chara_id}.")
        return [], {}
    print(f"Costume list for character ID {chara_id}:")
    print('='*80)
    costume_dict = {}
    for idx, (costume_id, name_key) in enumerate(rows, 1):
        real_name = get_real_costume_name(dict_cursor, name_key)
        costume_dict[str(idx)] = (costume_id, name_key, real_name)
        print(f"[{idx:2}] Costume ID: {costume_id:>10} | Costume name: {real_name}")
    print('='*80)
    print("Usage: Enter number (1,2,3...) or costume ID directly")
    return rows, costume_dict

def get_costume_selection(costumes, costume_dict):
    while True:
        sel = input("Enter number or costume ID: ").strip()
        if sel in costume_dict:
            cid, key, rname = costume_dict[sel]
            return cid, key, rname
        if sel.isdigit():
            for cid, key in costumes:
                if cid == int(sel):
                    return cid, key, get_real_costume_name(dict_cursor, key)
            print(f"❌ Costume ID {sel} is not in the list.")
        else:
            print("❌ Invalid input.")

# Script start
print("\nCharacter list:")
print("1:Honoka	2:Eli		3:Kotori")
print("4:Umi		5:Rin		 6:Maki")
print("7:Nozomi	8:Hanayo	9:Nico\n")
print("101:Chika	102:Riko	103:Kanan")
print("104:Dia		105:You		106:Yoshiko")
print("107:Hanamaru	108:Mari	109:Ruby\n")
print("201:Ayumu	202:Kasumi	203:Shizuku")
print("204:Karin	205:Ai		206:Kanata")
print("207:Setsuna	208:Emma	209:Rina")
print("210:Shioriko	211:Mia		212:Lanzhu\n")

# DB connection
md_conn = sqlite3.connect('assets/db/gl/masterdata.db')
md_cur = md_conn.cursor()

dict_conn = sqlite3.connect('assets/db/gl/dictionary_en_k.db')
dict_cursor = dict_conn.cursor()

# 1. Query
src_id = input("Enter character ID of the costume to copy: ")
rows, cdict = list_costumes_by_character(md_cur, dict_cursor, src_id)
if not rows:
    exit()
cid, key, rname = get_costume_selection(rows, cdict)

# 2. Target character
print("\nCharacter list:")
print("1:Honoka	2:Eli		3:Kotori")
print("4:Umi		5:Rin		 6:Maki")
print("7:Nozomi	8:Hanayo	9:Nico\n")
print("101:Chika	102:Riko	103:Kanan")
print("104:Dia		105:You		106:Yoshiko")
print("107:Hanamaru	108:Mari	109:Ruby\n")
print("201:Ayumu	202:Kasumi	203:Shizuku")
print("204:Karin	205:Ai		206:Kanata")
print("207:Setsuna	208:Emma	209:Rina")
print("210:Shioriko	211:Mia		212:Lanzhu\n")
tgt_id = input("Enter target character ID: ")
input("Press Enter to proceed if everything is correct...")

# 3. Insert
new_id = generate_unique_costume_id(md_cur)
# cloned key, name
cloned_key = key + '_cloned'

suffix_map = {
    'en':' Cloned',
    'ko':' 복제',
    'zh':' 克隆',
    'th':' โคลน',
    'jp':' クローン'
}
dict_paths = {
    'en':'assets/db/gl/dictionary_en_k.db',
    'ko':'assets/db/gl/dictionary_ko_k.db',
    'zh':'assets/db/gl/dictionary_zh_k.db',
    'th':'assets/db/gl/dictionary_th_k.db',
    'jp':'assets/db/jp/dictionary_ja_k.db'
}
for lang, path in dict_paths.items():
    if os.path.exists(path):
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        msg = rname + suffix_map.get(lang, suffix_map['en'])
        key_no_prefix = cloned_key.replace('k.', '')
        cur.execute(
            "INSERT OR IGNORE INTO main.m_dictionary (id, message) VALUES (?, ?);",
            (key_no_prefix, msg)
        )
        conn.commit()
        conn.close()

# Insert into m_suit
# Insert into GL
md_cur.execute("SELECT member_m_id, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path FROM m_suit WHERE id = ?", (cid,))
mrow = md_cur.fetchone()
new_display = md_cur.execute("SELECT MIN(display_order) FROM m_suit WHERE member_m_id = ?", (tgt_id,)).fetchone()[0] - 1
md_cur.execute("INSERT INTO m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
               , (new_id, tgt_id, cloned_key, mrow[1], mrow[2], mrow[3], mrow[4], new_display))
md_conn.commit()
# Insert into JP
md_conn = sqlite3.connect('assets/db/jp/masterdata.db')
md_cur = md_conn.cursor()
md_cur.execute("SELECT member_m_id, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path FROM m_suit WHERE id = ?", (cid,))
mrow = md_cur.fetchone()
new_display = md_cur.execute("SELECT MIN(display_order) FROM m_suit WHERE member_m_id = ?", (tgt_id,)).fetchone()[0] - 1
md_cur.execute("INSERT INTO m_suit (id, member_m_id, name, thumbnail_image_asset_path, suit_release_route, suit_release_value, model_asset_path, display_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
               , (new_id, tgt_id, cloned_key, mrow[1], mrow[2], mrow[3], mrow[4], new_display))
md_conn.commit()


with sqlite3.connect('userdata.db') as conn:
    cursor = conn.cursor()  
    cursor.execute("SELECT user_id FROM u_status")
    user_ids = cursor.fetchall()
    for user_id_ins in user_ids:
        user_id_ins = user_id_ins[0]
        cursor.execute("INSERT INTO main.u_suit (user_id, suit_master_id, is_new) VALUES (?, ?, '0');", (user_id_ins, new_id))


print(f"✅ Costume '{rname}' (new ID: {new_id}) has been copied to character {tgt_id}.")

# Close connections
md_conn.close()
dict_conn.close()
