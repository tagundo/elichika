"""A fixed disposable costume mod, using real stock assets and normal account APIs.

Only database copies read from a caller-verified, fresh ARM64 QA target may be
changed. Game and server must both be stopped before every database write.
Authentication stays in memory. Public fixture rows are represented by hashes
in evidence; neither databases nor API credentials are written to artifacts.
"""
import base64
from contextlib import closing
from functools import wraps
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke
from android_release_smoke import PACKAGE

SOURCE_SUIT = 300201
CUSTOM_SUIT = 990000901
MEMBER = 2
MODEL_ALIAS = "qa_retained_model_990000901"
CUSTOM_TABLE = "qa_mod_retention_fixture"
MASTER_PATHS = ("assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db")
DICTIONARY_PATHS = {"en": "assets/db/gl/dictionary_en_k.db", "ko": "assets/db/gl/dictionary_ko_k.db",
                    "zh": "assets/db/gl/dictionary_zh_k.db", "ja": "assets/db/jp/dictionary_ja_k.db"}
ASSET_PATH = "assets/db/gl/asset_a_ko.db"
PATHS = (*MASTER_PATHS, *DICTIONARY_PATHS.values(), ASSET_PATH)
NAMES = {"en": "QA Retained Eli Costume", "ko": "QA 보존 에리 의상", "zh": "QA 保留繪里服裝", "ja": "QA 保持絵里衣装"}


class ModFixtureError(ValueError):
    """Only fixed, non-sensitive reason identifiers may escape the fixture."""


def require(condition, reason):
    if not condition:
        raise ModFixtureError(reason)


def schema_guard(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (sqlite3.Error, KeyError, TypeError):
            raise ModFixtureError("mod_database_schema_invalid") from None
    return guarded


def digest(value):
    def encode(item):
        if isinstance(item, bytes):
            return {"bytes": base64.b64encode(item).decode()}
        raise TypeError("unsupported_fixture_value")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode).encode()).hexdigest()


def db(contents):
    return smoke.database_from_bytes(contents)


def row(connection, table, key, value):
    # All table/column identifiers are fixed code constants, never command input.
    result = connection.execute(f'SELECT * FROM "{table}" WHERE "{key}"=?', (value,)).fetchone()
    require(result is not None, "mod_required_stock_row_missing")
    return dict(result)


def insert(connection, table, values):
    columns = ",".join('"' + key + '"' for key in values)
    marks = ",".join("?" for _ in values)
    connection.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({marks})', tuple(values.values()))


@schema_guard
def mutate_master(contents):
    with closing(db(contents)) as connection:
        require(connection.execute("SELECT 1 FROM m_suit WHERE id=?", (CUSTOM_SUIT,)).fetchone() is None,
                "mod_custom_id_collision")
        source = row(connection, "m_suit", "id", SOURCE_SUIT)
        require(source["member_m_id"] == MEMBER and isinstance(source["name"], str) and source["name"].startswith("k."), "mod_stock_owner_or_name_invalid")
        require(connection.execute("SELECT 1 FROM sqlite_master WHERE name=?", (CUSTOM_TABLE,)).fetchone() is None,
                "mod_custom_table_collision")
        cloned = dict(source)
        cloned.update(id=CUSTOM_SUIT, name=source["name"] + "_cloned",
                      display_order=connection.execute("SELECT MIN(display_order) FROM m_suit WHERE member_m_id=?", (MEMBER,)).fetchone()[0] - 1)
        insert(connection, "m_suit", cloned)
        # Original costume_clone copies the opaque base model. This additional
        # fixed view row exercises preservation of the custom FK relationship.
        connection.execute("INSERT INTO m_suit_view(suit_master_id,view_status,model_asset_path) VALUES(?,?,?)",
                           (CUSTOM_SUIT, 2, source["model_asset_path"]))
        connection.execute("UPDATE m_suit SET display_order=? WHERE id=?", (source["display_order"] - 17, SOURCE_SUIT))
        connection.execute(f'CREATE TABLE "{CUSTOM_TABLE}"(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
        connection.execute(f'INSERT INTO "{CUSTOM_TABLE}" VALUES(?,?)', ("disposable-only", "retain-custom-row"))
        connection.commit()
        return connection.serialize(), source["name"][2:] + "_cloned"


@schema_guard
def mutate_dictionary(contents, key, language):
    with closing(db(contents)) as connection:
        require(connection.execute("SELECT 1 FROM m_dictionary WHERE id=?", (key,)).fetchone() is None,
                "mod_custom_dictionary_collision")
        connection.execute("INSERT INTO m_dictionary(id,message) VALUES(?,?)", (key, NAMES[language]))
        connection.commit()
        return connection.serialize()


@schema_guard
def mutate_assets(contents, source_model):
    with closing(db(contents)) as connection:
        source_key, custom_key = f"suit:{SOURCE_SUIT}", f"suit:{CUSTOM_SUIT}"
        package = row(connection, "m_asset_package", "package_key", source_key)
        mappings = [dict(item) for item in connection.execute("SELECT * FROM m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (source_key,))]
        require(mappings and package["pack_num"] == len(mappings), "mod_stock_package_incomplete")
        require(connection.execute("SELECT 1 FROM m_asset_package WHERE package_key=?", (custom_key,)).fetchone() is None,
                "mod_package_alias_collision")
        package["package_key"] = custom_key
        insert(connection, "m_asset_package", package)
        for mapping in mappings:
            mapping["package_key"] = custom_key
            insert(connection, "m_asset_package_mapping", mapping)
        # Copy every crypto field byte-for-byte while retaining the stock pack.
        # The costume itself uses the unchanged original opaque model key, as
        # costume_clone does; this valid extra alias separately tests crypto rows.
        model = row(connection, "member_model", "asset_path", source_model)
        require(connection.execute("SELECT 1 FROM member_model WHERE asset_path=?", (MODEL_ALIAS,)).fetchone() is None,
                "mod_crypto_alias_collision")
        model["asset_path"] = MODEL_ALIAS
        insert(connection, "member_model", model)
        connection.commit()
        return connection.serialize()


def build_copies(inputs):
    """Pure in-memory edits; callers must never supply personal/original files."""
    require(set(inputs) == set(PATHS) and all(isinstance(value, bytes) for value in inputs.values()), "mod_input_schema_invalid")
    outputs = dict(inputs)
    keys = []
    for path in MASTER_PATHS:
        outputs[path], key = mutate_master(inputs[path])
        keys.append(key)
    require(keys[0] == keys[1], "mod_source_dictionary_chain_differs")
    for language, path in DICTIONARY_PATHS.items():
        outputs[path] = mutate_dictionary(inputs[path], keys[0], language)
    with closing(db(inputs[MASTER_PATHS[0]])) as master:
        model = row(master, "m_suit", "id", SOURCE_SUIT)["model_asset_path"]
    outputs[ASSET_PATH] = mutate_assets(inputs[ASSET_PATH], model)
    return outputs


@schema_guard
def public_components(inputs):
    """Hash only the exact fixture rows, not unrelated official additions."""
    components = {}
    key = None
    for path in MASTER_PATHS:
        with closing(db(inputs[path])) as connection:
            cloned = row(connection, "m_suit", "id", CUSTOM_SUIT)
            require(cloned["member_m_id"] == MEMBER, "mod_custom_owner_changed")
            view = [tuple(item) for item in connection.execute("SELECT * FROM m_suit_view WHERE suit_master_id=? ORDER BY view_status", (CUSTOM_SUIT,))]
            require(view and any(item[1] == 2 for item in view), "mod_custom_view_missing")
            marker = [tuple(item) for item in connection.execute(f'SELECT * FROM "{CUSTOM_TABLE}" ORDER BY id')]
            require(marker == [("disposable-only", "retain-custom-row")], "mod_custom_table_changed")
            override = connection.execute("SELECT display_order FROM m_suit WHERE id=?", (SOURCE_SUIT,)).fetchone()
            require(override is not None, "mod_stock_override_row_missing")
            custom_schema = [tuple(item) for item in connection.execute(f'PRAGMA table_info("{CUSTOM_TABLE}")')]
            components[path] = digest({"clone": cloned, "views": view, "override": tuple(override),
                                       "custom_table": marker, "custom_table_schema": custom_schema})
            current_key = cloned["name"][2:]
            require(key is None or key == current_key, "mod_dictionary_chain_changed")
            key = current_key
    for language, path in DICTIONARY_PATHS.items():
        with closing(db(inputs[path])) as connection:
            value = row(connection, "m_dictionary", "id", key)
            require(value["message"] == NAMES[language], "mod_custom_dictionary_changed")
            components[path] = digest(value)
    with closing(db(inputs[ASSET_PATH])) as connection:
        package = row(connection, "m_asset_package", "package_key", f"suit:{CUSTOM_SUIT}")
        mappings = [dict(item) for item in connection.execute("SELECT * FROM m_asset_package_mapping WHERE package_key=? ORDER BY pack_name", (f"suit:{CUSTOM_SUIT}",))]
        require(mappings and package["pack_num"] == len(mappings), "mod_package_alias_incomplete")
        crypto = row(connection, "member_model", "asset_path", MODEL_ALIAS)
        components[ASSET_PATH] = digest({"package": package, "mappings": mappings, "crypto": crypto})
    return components


def read_inputs(android):
    return {path: android.read(f"{smoke.FILES}/{path}") for path in PATHS}


@schema_guard
def selected_state(android, uid):
    with closing(db(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        require(connection.execute("SELECT COUNT(*) FROM u_status").fetchone()[0] == 1, "mod_unique_disposable_user_required")
        status = connection.execute("SELECT favorite_member_id FROM u_status WHERE user_id=?", (uid,)).fetchone()
        theme = connection.execute("SELECT suit_master_id,custom_background_master_id FROM u_member WHERE user_id=? AND member_master_id=?", (uid, MEMBER)).fetchone()
        owned = connection.execute("SELECT COUNT(*) FROM u_suit WHERE user_id=? AND suit_master_id=?", (uid, CUSTOM_SUIT)).fetchone()[0]
        require(status is not None and theme is not None and status[0] == MEMBER and theme[0] == CUSTOM_SUIT and owned == 1,
                "mod_custom_selection_or_ownership_missing")
        return {"favorite_member_id": MEMBER, "selected_suit_id": CUSTOM_SUIT, "background_id": theme[1], "owned_custom_suits": owned}


def verify_retained(android, fixture, uid):
    require(isinstance(fixture, dict) and fixture.get("custom_suit_id") == CUSTOM_SUIT and fixture.get("source_suit_id") == SOURCE_SUIT,
            "mod_fixture_manifest_invalid")
    current = {"components": public_components(read_inputs(android)), "selection": selected_state(android, uid)}
    require(current["components"] == fixture.get("components"), "mod_master_override_alias_or_crypto_changed")
    require(current["selection"] == fixture.get("selection"), "mod_retained_custom_selection_changed")
    return current


def assert_stopped(android):
    for process in (smoke.GAME, "libelichika.so", PACKAGE):
        require(not android.shell("sh", "-c", f"pidof {process} || true").strip(), "mod_game_and_server_must_be_stopped")


def grant_and_select(android, uid, background, language):
    # Suits are unique rewards: the normal gift handler grants them directly,
    # not through present/fetch or present/receive (including Nov3.4).
    from gl_ui_runtime.accessory_fixture import NoRedirect
    with closing(db(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        require(connection.execute("SELECT COUNT(*) FROM u_status").fetchone()[0] == 1,
                "mod_unique_disposable_gift_user_required")
        require(connection.execute("SELECT COUNT(*) FROM u_suit WHERE user_id=? AND suit_master_id=?", (uid, CUSTOM_SUIT)).fetchone()[0] == 0,
                "mod_fresh_clone_already_owned")
        auth = connection.execute("SELECT session_key,command_id FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        require(auth is not None and isinstance(auth[0], bytes) and len(auth[0]) == 32, "mod_authenticated_game_session_required")
        session, command = bytes(auth[0]), auth[1]
    boundary = "elichika-disposable-mod-fixture"
    fields = {"user_id": str(uid), "user_session_key": base64.b64encode(session).decode(), "content_type": "7",
              "content_id": str(CUSTOM_SUIT), "content_amount": "1"}
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n' for key, value in fields.items()) + f"--{boundary}--\r\n"
    request = urllib.request.Request(f"http://127.0.0.1:18080/webui/user/add_present?l={language}", data=body.encode(), method="POST",
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    else:
        status = response.status
        response.close()
    require(status in (200, 302, 303), "mod_gift_request_rejected")
    with closing(db(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        require(connection.execute("SELECT COUNT(*) FROM u_suit WHERE user_id=? AND suit_master_id=?", (uid, CUSTOM_SUIT)).fetchone()[0] == 1,
                "mod_unique_suit_grant_missing")
    client = smoke.Client(language, None)
    client.uid, client.session, client.command = uid, session, command
    client.request("/communicationMember/setTheme", {"member_master_id": MEMBER, "suit_master_id": CUSTOM_SUIT, "custom_background_master_id": background})
    client.request("/communicationMember/setFavoriteMember", {"member_master_id": MEMBER})
    return {"gift_http_status": status, "grant_mode": "unique_suit_direct", "owned_custom_suits": 1,
            "present_fetch_used": False, "present_receive_used": False}


@schema_guard
def prepare(android, before, args, report):
    result = {"status": "REFUSED", "source_suit_id": SOURCE_SUIT, "custom_suit_id": CUSTOM_SUIT}
    report["mod_fixture"] = result
    require(getattr(args, "prepare_mod_home", False) is True and before == set(), "mod_explicit_fresh_disposable_opt_in_required")
    require(args.serial == "127.0.0.1:5555" and android.shell("id").startswith("uid=0") and
            android.shell("getprop", "ro.product.cpu.abi") == "arm64-v8a" and android.shell("getprop", "ro.hardware") == "redroid",
            "mod_disposable_native_arm64_required")
    require(smoke.sha(args.candidate.read_bytes()) == smoke.LATEST_BASELINE_SHA and args.version_code == smoke.LATEST_BASELINE_CODE,
            "mod_pinned_nov3_baseline_required")
    for package, expected in ((PACKAGE, smoke.LATEST_BASELINE_SHA), (smoke.GAME, smoke.GAME_SHA)):
        installed = android.shell("pm", "path", package).splitlines()
        require(len(installed) == 1 and installed[0].startswith("package:"), "mod_installed_apk_not_unique")
        require(android.shell("sha256sum", installed[0].removeprefix("package:")).split()[0] == expected,
                "mod_installed_apk_identity_mismatch")
    with closing(db(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        ids = [item[0] for item in connection.execute("SELECT user_id FROM u_status")]
        require(len(ids) == 1 and type(ids[0]) is int and ids[0] > 0, "mod_unique_game_created_user_required")
        uid = ids[0]
        status = connection.execute("SELECT tutorial_phase FROM u_status WHERE user_id=?", (uid,)).fetchone()
        theme = connection.execute("SELECT custom_background_master_id FROM u_member WHERE user_id=? AND member_master_id=?", (uid, MEMBER)).fetchone()
        auth = connection.execute("SELECT session_key FROM u_authentication WHERE user_id=?", (uid,)).fetchone()
        require(status[0] == 99 and theme is not None and auth is not None and isinstance(auth[0], bytes) and len(auth[0]) == 32,
                "mod_game_profile_not_ready")
        background = theme[0]
    # Force-stop both processes before reading/mutating the database copies.
    android.shell("am", "force-stop", smoke.GAME)
    smoke.stop_server(android)
    assert_stopped(android)
    inputs = read_inputs(android)
    outputs = build_copies(inputs)
    expected = public_components(outputs)
    for path in PATHS:
        assert_stopped(android)
        android.write(f"{smoke.FILES}/{path}", outputs[path])
    result["cold_server_restart"] = android.start("qa-disposable-mod-fixture")
    require(public_components(read_inputs(android)) == expected, "mod_catalog_changed_during_baseline_restart")
    result["catalog_verified_after_cold_restart"] = True
    result["ownership_api"] = grant_and_select(android, uid, background, getattr(args, "qa_language", "ko"))
    fixture = {"source_suit_id": SOURCE_SUIT, "custom_suit_id": CUSTOM_SUIT, "components": expected,
               "selection": selected_state(android, uid)}
    verify_retained(android, fixture, uid)
    result.update(status="PREPARED", fixture=fixture, normal_api_ownership=True, raw_userdata_written=False)
    return {"status": "PREPARED", "user_id": uid, "favorite_suit": CUSTOM_SUIT, "favorite_member_id": MEMBER,
            "background_id": background, "mod_fixture": fixture, "fixture": "disposable_stock_model_clone",
            "game_rendering_verified": False}
