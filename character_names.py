"""Single source of truth for character id -> name, shared by the dev tools.

Two forms are provided so tools stay consistent instead of each carrying their
own copy (which used to drift — costume_clone had full names, the extractor had
first names):

  CHARACTERS   id -> full name  ("Hanamaru Kunikida") — used for pickers/labels.
  FIRST_NAMES  id -> given name ("Hanamaru")          — used for output filenames.

The modding-tools repo (llas_asset_extractor.CHARACTERS) keeps its own copy for
standalone CLI use; adminui/selftest.py asserts the id sets match so a new
character added to one side but not the other fails CI.
"""

CHARACTERS = {
    1: "Honoka Kousaka", 2: "Eli Ayase", 3: "Kotori Minami", 4: "Umi Sonoda",
    5: "Rin Hoshizora", 6: "Maki Nishikino", 7: "Nozomi Tojo", 8: "Hanayo Koizumi",
    9: "Nico Yazawa",
    101: "Chika Takami", 102: "Riko Sakurauchi", 103: "Kanan Matsuura",
    104: "Dia Kurosawa", 105: "You Watanabe", 106: "Yoshiko Tsushima",
    107: "Hanamaru Kunikida", 108: "Mari Ohara", 109: "Ruby Kurosawa",
    201: "Ayumu Uehara", 202: "Kasumi Nakasu", 203: "Shizuku Osaka",
    204: "Karin Asaka", 205: "Ai Miyashita", 206: "Kanata Konoe",
    207: "Setsuna Yuki", 208: "Emma Verde", 209: "Rina Tennoji",
    210: "Shioriko Mifune", 211: "Mia Taylor", 212: "Lanzhu Zhong",
}

# Given name only (first token of the full name) — nicer for filenames.
FIRST_NAMES = {cid: name.split()[0] for cid, name in CHARACTERS.items()}
