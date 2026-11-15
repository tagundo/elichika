#!/usr/bin/env python3
"""Probe a running, real SIFAS backend in an owned disposable app sandbox.

The wire protocol matches tests/android_release_smoke.py: RSA-OAEP/SHA1 masks,
startup/authentication/session HMAC-SHA1, and sequential command identifiers.
Only this probe's synthetic account is changed. Credentials stay in a mode-0600
file in the data root, permitting a second app launch to verify persistence.
Receipts never contain credentials, HTTP bodies, user identifiers or DB rows.
This does not exercise or claim actual SIFAS rendering or MV playback.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE = 32 * 1024 * 1024
STATE_KIND = "elichika-ios-protocol-probe-account"
EVENT_KEY = bytes.fromhex("4924c4421e9e3a287dc31e2ff241a8fb46389c7f30bafee791bb06c9ae3b6c82")
STARTUP_KEYS = {"ja": b"5f7IZY1QrAX0D49g", "en": b"TxQFwgNcKDlesb93",
                "ko": b"TxQFwgNcKDlesb93", "zh": b"TxQFwgNcKDlesb93"}


class ProbeError(Exception):
    """Only fixed, non-sensitive diagnostics are eligible for receipts."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise ProbeError(code, message)


def bounded_json(path, limit=65536):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            "invalid_input", "Required bounded regular JSON input is unavailable.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value, *, private=False):
    """Atomic replacement; private credentials are never copied to evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), "linked_output", "Output must not be a symbolic link.")
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".elichika-probe-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600 if private else 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rsa_public_numbers(pem):
    """Read a bounded PKCS#1 or SubjectPublicKeyInfo RSA public key."""
    require(len(pem) <= 65536 and b"PRIVATE KEY" not in pem,
            "public_key", "A bounded RSA public key is required.")
    numbers = []

    def walk(value, depth=0):
        require(depth <= 4, "public_key", "RSA public key structure is invalid.")
        position = 0
        while position < len(value):
            require(position + 2 <= len(value), "public_key", "RSA public key structure is invalid.")
            tag, length = value[position:position + 2]
            position += 2
            if length & 128:
                count = length & 127
                require(0 < count <= 4 and position + count <= len(value),
                        "public_key", "RSA public key structure is invalid.")
                length = int.from_bytes(value[position:position + count], "big")
                position += count
            require(position + length <= len(value), "public_key", "RSA public key structure is invalid.")
            item = value[position:position + length]
            position += length
            if tag == 48:
                walk(item, depth + 1)
            elif tag == 3 and item[:1] == b"\0":
                walk(item[1:], depth + 1)
            elif tag == 2:
                numbers.append(int.from_bytes(item, "big"))

    der = base64.b64decode(b"".join(line for line in pem.splitlines()
                                   if not line.startswith(b"---")), validate=True)
    walk(der)
    require(len(numbers) == 2 and 1024 <= numbers[0].bit_length() <= 8192
            and numbers[1] >= 3 and numbers[1] % 2 == 1,
            "public_key", "RSA public key parameters are unsupported.")
    return numbers


def mgf1(seed, length):
    return b"".join(hashlib.sha1(seed + index.to_bytes(4, "big")).digest()
                    for index in range((length + 19) // 20))[:length]


def rsa_mask(public_numbers):
    modulus, exponent = public_numbers
    size = (modulus.bit_length() + 7) // 8
    mask, seed = secrets.token_bytes(32), secrets.token_bytes(20)
    data = hashlib.sha1(b"").digest() + bytes(size - len(mask) - 42) + b"\1" + mask
    masked_data = bytes(a ^ b for a, b in zip(data, mgf1(seed, size - 21)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, mgf1(masked_data, 20)))
    encoded = b"\0" + masked_seed + masked_data
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus).to_bytes(size, "big")
    return mask, base64.b64encode(encrypted).decode("ascii")


def verify_response(raw, path, key):
    require(len(raw) <= MAX_RESPONSE, "response_bound", "Game response exceeded its byte bound.")
    wire = raw.decode("utf-8").strip()
    envelope = json.loads(wire)
    require(isinstance(envelope, list) and len(envelope) == 5 and wire.startswith("[")
            and wire.endswith("]") and isinstance(envelope[-1], str),
            "response_envelope", "Game response envelope is invalid.")
    expected = hmac.new(key, (path + " " + wire[1:wire.rfind(",")]).encode(), hashlib.sha1).hexdigest()
    require(hmac.compare_digest(envelope[-1], expected),
            "response_hmac", "Game response HMAC did not verify.")
    require(envelope[2] == 0, "response_rejected", "Game protocol returned a non-success response type.")
    require(isinstance(envelope[3], dict), "response_payload", "Game response payload is not an object.")
    return envelope[3]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProbeError("redirect", "The local game endpoint attempted an HTTP redirect.")


class Client:
    def __init__(self, endpoint, language, public_numbers, requests, *, timeout=45,
                 startup_key=None, event_key=EVENT_KEY):
        self.endpoint, self.language, self.public_numbers = endpoint, language, public_numbers
        self.requests, self.timeout = requests, timeout
        self.startup_key, self.event_key = startup_key or STARTUP_KEYS[language], event_key
        self.uid, self.auth, self.session, self.auth_count, self.command = None, None, None, 0, 0
        # A host's proxy environment must not forward probe credentials elsewhere.
        self.transport = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, route, payload, *, login=False, startup=False):
        path = route + "?l=" + self.language
        if not startup:
            self.command = 1 if login else self.command + 1
            path += f"&u={self.uid}&id={self.command}"
        key = self.startup_key if startup else self.auth if login else self.session
        require(isinstance(key, bytes) and key, "request_key", "Game request key is unavailable.")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        signature = hmac.new(key, (path + " " + body).encode(), hashlib.sha1).hexdigest()
        request = urllib.request.Request(self.endpoint + path,
            data=("[" + body + "," + json.dumps(signature) + "]").encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        row = {"route": route, "response_hmac_verified": False}
        self.requests.append(row)
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                row["http_status"] = response.status
                require(response.status == 200, "http_status", "Local game request did not return HTTP 200.")
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as failure:
            row["http_status"] = failure.code
            failure.close()
            raise ProbeError("http_status", "Local game request did not return HTTP 200.") from None
        result = verify_response(raw, path, key)
        row["response_hmac_verified"] = True
        return result

    def create(self, identifier):
        mask, encrypted = rsa_mask(self.public_numbers)
        result = self.request("/login/startup", {"mask": encrypted,
            "resemara_detection_identifier": identifier, "time_difference": 0,
            "recaptcha_token": ""}, startup=True)
        self.uid = result.get("user_id")
        encoded = base64.b64decode(result.get("authorization_key", ""), validate=True)
        require(type(self.uid) is int and self.uid > 0 and len(encoded) == 32,
                "startup_credentials", "Startup did not return valid synthetic account credentials.")
        self.auth = bytes(a ^ b for a, b in zip(encoded, mask))

    def login(self):
        mask, encrypted = rsa_mask(self.public_numbers)
        self.auth_count += 1
        result = self.request("/login/login", {"user_id": self.uid, "auth_count": self.auth_count,
            "mask": encrypted, "asset_state": "", "recaptcha_token": ""}, login=True)
        encoded = base64.b64decode(result.get("session_key", ""), validate=True)
        require(len(encoded) == 32 and isinstance(result.get("user_model"), dict),
                "login_session", "Login did not return a valid session and user model.")
        self.session = bytes(a ^ b ^ c for a, b, c in zip(encoded, mask, self.event_key))
        return result["user_model"]


def dictionary(value):
    require(isinstance(value, list) and len(value) % 2 == 0 and len(value) <= 200000,
            "model_dictionary", "Game model dictionary encoding is invalid.")
    result = {}
    for index in range(0, len(value), 2):
        key = value[index]
        require(type(key) is int and key not in result,
                "model_dictionary", "Game model dictionary contains invalid or duplicate keys.")
        result[key] = value[index + 1]
    return result


@contextmanager
def readonly_database(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "database_missing", "Required game database is unavailable.")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def account_snapshot(database, client):
    with readonly_database(database) as connection:
        auth = connection.execute("SELECT authorization_key,authorization_count,session_key,command_id "
            "FROM u_authentication WHERE user_id=?", (client.uid,)).fetchone()
        status = connection.execute("SELECT device_token FROM u_status WHERE user_id=?", (client.uid,)).fetchone()
        require(auth is not None and status is not None,
                "account_missing", "Synthetic account was not committed to the active userdata database.")
        require(hmac.compare_digest(bytes(auth["authorization_key"]), client.auth),
                "account_key", "Committed synthetic account credentials differ from the startup credentials.")
        return {"auth_count": auth["authorization_count"], "command": auth["command_id"],
                "session": bytes(auth["session_key"]), "device_token": status["device_token"]}


def read_deck(database, uid, table, song):
    require(table in ("u_live_mv_deck", "u_live_mv_deck_custom"),
            "deck_table", "MV probe table is invalid.")
    with readonly_database(database) as connection:
        row = connection.execute(f"SELECT * FROM {table} WHERE user_id=? AND live_master_id=?", (uid, song)).fetchone()
        require(row is not None, "mv_database", "MV save was not visible through a new SQLite connection.")
        result = {"live_master_id": row["live_master_id"]}
        for prefix in ("member_master_id_", "suit_master_id_"):
            for position in range(1, 13):
                value = row[prefix + str(position)]
                result[prefix + str(position)] = json.loads(value) if isinstance(value, (str, bytes)) else value
        return result


def deck_payload(song, deck_type, members, suits):
    return {"live_master_id": song, "live_mv_deck_type": deck_type,
            "member_master_id_by_pos": [item for pair in sorted(members.items()) for item in pair],
            "suit_master_id_by_pos": [item for pair in sorted(suits.items()) for item in pair],
            "view_status_by_pos": []}


def check_deck(deck, song, members, suits):
    require(deck.get("live_master_id") == song, "mv_identity", "MV deck lost its per-song identity.")
    for position, member in members.items():
        require(deck.get("member_master_id_" + str(position)) == member,
                "mv_member", "MV deck did not retain its selected per-slot members.")
    for position, suit in suits.items():
        require(deck.get("suit_master_id_" + str(position)) == suit,
                "mv_suit", "MV deck did not retain its selected per-slot costumes.")


def master_lineup(connection, song):
    rows = connection.execute("SELECT m.position,m.member_master_id,m.suit_master_id,i.suit_m_id "
        "FROM m_live l JOIN m_live_member_mapping m ON m.mapping_id=l.live_member_mapping_id "
        "JOIN m_member_init i ON i.member_m_id=m.member_master_id WHERE l.live_id=? ORDER BY m.position",
        (song,)).fetchall()
    require(rows and [row["position"] for row in rows] == list(range(1, len(rows) + 1))
            and len(rows) <= 12, "mv_fixture", "Official MV lineup is unavailable or has unsupported positions.")
    return ({row["position"]: row["member_master_id"] for row in rows},
            {row["position"]: row["suit_master_id"] if row["suit_master_id"] is not None
             else row["suit_m_id"] for row in rows})


def exercise_mv(client, database, master, report):
    """Public protocol + committed SQLite oracle; never a rendered MV claim."""
    with readonly_database(master) as connection:
        original_members, original_suits = master_lineup(connection, 10002)
        require(len(original_members) == 9, "mv_fixture", "Stock START:DASH fixture must have nine master-derived positions.")
        suits = [row[0] for row in connection.execute("SELECT id FROM m_suit WHERE member_m_id=1 ORDER BY id")]
        require(100011001 in suits and len(suits) >= 2,
                "mv_fixture", "Official Honoka fixture needs the initial and one other costume.")
        alternate = next(suit for suit in suits if suit != 100011001)
        all_rows = connection.execute("SELECT l.live_id,m.position,m.member_master_id FROM m_live l "
            "JOIN m_live_member_mapping m ON m.mapping_id=l.live_member_mapping_id ORDER BY l.live_id,m.position").fetchall()
        by_song = {}
        for row in all_rows:
            by_song.setdefault(row["live_id"], []).append(row)
        songs12 = [song for song, rows in by_song.items() if len(rows) == 12
                   and [row["position"] for row in rows] == list(range(1, 13))]
        pair12 = None
        for song in songs12[1:]:
            first = by_song[songs12[0]]
            if (by_song[song][0]["member_master_id"], by_song[song][-1]["member_master_id"]) != (
                    first[0]["member_master_id"], first[-1]["member_master_id"]):
                pair12 = (songs12[0], song)
                break
        lineups12 = [master_lineup(connection, song) for song in pair12] if pair12 else []

    expected = {}

    def save(song, kind, members, selected):
        response = client.request("/liveMv/saveDeck", deck_payload(song, kind, members, selected))
        field = "user_live_mv_deck_by_id" if kind == 1 else "user_live_mv_deck_custom_by_id"
        returned = dictionary(response.get("user_model", {}).get(field))
        require(song in returned and isinstance(returned[song], dict),
                "mv_model", "MV save did not return the selected deck model update.")
        check_deck(returned[song], song, members, selected)
        table = "u_live_mv_deck" if kind == 1 else "u_live_mv_deck_custom"
        committed = read_deck(database, client.uid, table, song)
        check_deck(committed, song, members, selected)
        expected[(field, song)] = committed
        return committed

    def start(song, kind):
        before = {key: read_deck(database, client.uid,
            "u_live_mv_deck" if key[0] == "user_live_mv_deck_by_id" else "u_live_mv_deck_custom", key[1])
            for key in expected}
        result = client.request("/liveMv/start", {"live_master_id": song, "live_mv_deck_type": kind,
                                                "stage_master_id": None})
        require(type(result.get("uniq_id")) is int and result["uniq_id"] > 0,
                "mv_start", "MV start did not return a positive protocol identifier.")
        for key, previous in before.items():
            current = read_deck(database, client.uid,
                "u_live_mv_deck" if key[0] == "user_live_mv_deck_by_id" else "u_live_mv_deck_custom", key[1])
            require(current == previous, "mv_start_mutation", "MV start changed a committed deck.")

    original = save(10002, 1, original_members, original_suits)
    duplicate_members = {1: 1, 2: 1}
    save(10002, 2, duplicate_members, {1: 100011001, 2: 100011001})
    report["gates"]["mv_custom_duplicate_same_costume"] = {"status": "PASS", "positions": [1, 2]}
    save(10002, 2, duplicate_members, {1: 100011001, 2: alternate})
    require(read_deck(database, client.uid, "u_live_mv_deck", 10002) == original,
            "mv_type_isolation", "Custom save overwrote the independent Original deck.")
    report["gates"]["mv_custom_duplicate_independent_costumes"] = {"status": "PASS", "positions": [1, 2]}
    start(10002, 2)
    start(10002, 1)
    report["gates"]["mv_original_master_lineup"] = {"status": "PASS", "positions": 9, "live_master_id": 10002}
    report["gates"]["mv_start_preserves_decks"] = {"status": "PASS", "deck_types": ["Original", "Custom"]}
    music = client.request("/live/fetchLiveMusicSelect", {})
    require(isinstance(music.get("user_model_diff"), dict) and isinstance(music.get("weekday_state"), dict),
            "music_select", "Music-select protocol did not return its expected model and weekday state.")
    report["gates"]["mv_music_select"] = {"status": "PASS"}
    if pair12:
        for song, (members, selected) in zip(pair12, lineups12):
            save(song, 1, members, selected)
        song = pair12[0]
        save(song, 2, {1: 1, 12: 1}, {1: 100011001, 12: alternate})
        for song in pair12:
            start(song, 1)
        start(pair12[0], 2)
        report["gates"]["mv_twelve_slot_per_song"] = {"status": "PASS", "songs": 2, "positions": [1, 12]}
    else:
        report["gates"]["mv_twelve_slot_per_song"] = {"status": "NOT_RUN",
            "reason": "Official catalog does not provide two distinct twelve-slot lineup fixtures."}
    return expected


def probe(endpoint, data_root, output=None, *, language="en", account_state=None,
          public_key=None, protocol_config=None, master_database=None, timeout=45):
    """Return a bounded redacted receipt; failure details never echo server data."""
    report = {"schema": 1, "probe_kind": "real-sifas-encrypted-protocol", "passed": False,
        "status": "FAIL", "gates": {}, "failures": [], "requests": [],
        "actual_SIFAS_game_executed": False, "game_visual_MV_playback": "UNVERIFIED",
        "scope": "Real startup/login/HOME/bootstrap/MV API and committed SQLite state; no game rendering claim."}
    for name in ("startup", "retained_account_persistence", "retained_mv_persistence", "login", "home_theme", "bootstrap",
                 "database_commit", "mv_protocol", "model_reload"):
        report["gates"][name] = {"status": "NOT_RUN"}
    report["gates"]["costume_clone_install"] = {"status": "NOT_RUN",
        "reason": "No actual costume-clone tool/Unity asset fixture is supplied to this protocol probe."}
    stage = "preflight"
    started = time.monotonic()
    state = None
    state_path = None
    client = None
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        require(parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/") and parsed.port is not None,
                "endpoint", "Probe endpoint must be a loopback HTTP origin with an explicit port.")
        endpoint = endpoint.rstrip("/")
        root = Path(data_root).resolve(strict=True)
        require(root.is_dir(), "data_root", "Owned disposable data root is unavailable.")
        require(language in STARTUP_KEYS, "language", "Probe language is unsupported.")
        require(0 < timeout <= 120, "timeout", "Probe timeout must be between zero and 120 seconds.")
        database = root / "userdata.db"
        state_path = Path(account_state) if account_state is not None else root / ".ios-protocol-probe-account.json"
        require(not state_path.is_symlink() and state_path.resolve().is_relative_to(root),
                "account_state", "Private probe account state must remain inside the owned data root.")
        public = Path(public_key) if public_key is not None else root / "publickey.pem"
        require(public.is_file() and not public.is_symlink() and public.stat().st_size <= 65536,
                "public_key", "Required bounded public key is unavailable.")
        pem = public.read_bytes()
        fingerprint = hashlib.sha256(pem).hexdigest()
        numbers = rsa_public_numbers(pem)
        startup_keys, event_key, fetch_types = dict(STARTUP_KEYS), EVENT_KEY, [2, 3, 4, 5, 9]
        if protocol_config is not None:
            config = bounded_json(protocol_config)
            require(isinstance(config, dict) and set(config) <= {
                "startup_keys", "server_event_receiver_key", "bootstrap_fetch_types"},
                "protocol_config", "Protocol fixture configuration contains unsupported fields.")
            for lang, value in config.get("startup_keys", {}).items():
                require(lang in startup_keys and isinstance(value, str) and 1 <= len(value) <= 128,
                        "protocol_config", "Protocol fixture startup keys are invalid.")
                startup_keys[lang] = value.encode()
            if "server_event_receiver_key" in config:
                event_key = bytes.fromhex(config["server_event_receiver_key"])
            fetch_types = config.get("bootstrap_fetch_types", fetch_types)
        require(len(event_key) == 32 and isinstance(fetch_types, list) and len(fetch_types) <= 8
                and all(type(item) is int and item in (2, 3, 4, 5, 7, 9, 10, 11) for item in fetch_types),
                "protocol_config", "Protocol fixture key size or bootstrap types are invalid.")
        with readonly_database(database) as connection:
            require([row[0] for row in connection.execute("PRAGMA quick_check")] == ["ok"],
                    "database_integrity", "Active userdata database failed SQLite quick_check.")
        client = Client(endpoint, language, numbers, report["requests"], timeout=timeout,
                        startup_key=startup_keys[language], event_key=event_key)
        report["gates"]["preflight"] = {"status": "PASS", "language": language}

        def save_state():
            state.update({"uid": client.uid, "authorization_key": base64.b64encode(client.auth).decode(),
                          "auth_count": client.auth_count})
            write_json(state_path, state, private=True)

        if state_path.exists():
            stage = "retained_account_persistence"
            state = bounded_json(state_path)
            require(isinstance(state, dict) and state.get("schema") == 1 and state.get("kind") == STATE_KIND
                    and state.get("language") == language and state.get("public_key_sha256") == fingerprint,
                    "account_state", "Private state is not a matching synthetic probe account.")
            require(stat.S_IMODE(state_path.stat().st_mode) & 0o077 == 0,
                    "account_permissions", "Private probe credentials have overly broad permissions.")
            client.uid = state.get("uid")
            client.auth = base64.b64decode(state.get("authorization_key", ""), validate=True)
            require(type(client.uid) is int and client.uid > 0 and len(client.auth) == 32,
                    "account_state", "Private synthetic account credentials are invalid.")
            previous = account_snapshot(database, client)
            require(previous["auth_count"] == state.get("auth_count")
                    and (not state.get("device_token") or previous["device_token"] == state["device_token"]),
                    "retained_account", "Prior committed account marker or authentication counter did not persist.")
            client.auth_count = previous["auth_count"]
            report["gates"][stage] = {"status": "PASS", "prior_bootstrap_marker_verified": bool(state.get("device_token"))}
            report["gates"]["startup"] = {"status": "NOT_RUN", "reason": "Reusing the prior launch's synthetic startup credentials."}
        else:
            stage = "startup"
            state = {"schema": 1, "kind": STATE_KIND, "language": language,
                     "public_key_sha256": fingerprint, "run_id": secrets.token_hex(16), "sequence": 0}
            client.create("ios-protocol-probe-" + state["run_id"])
            save_state()
            account_snapshot(database, client)
            report["gates"][stage] = {"status": "PASS", "rsa_oaep_sha1": True, "response_hmac": True}
            report["gates"]["retained_account_persistence"] = {"status": "NOT_RUN", "reason": "Requires a second call after app relaunch with the same sandbox."}

        stage = "login"
        model = client.login()
        save_state()
        report["gates"][stage] = {"status": "PASS", "rsa_oaep_sha1": True, "authorization_hmac": True}
        if state.get("mv_decks"):
            stage = "retained_mv_persistence"
            require(isinstance(state["mv_decks"], list) and len(state["mv_decks"]) <= 8,
                    "account_state", "Prior synthetic MV receipt is invalid.")
            for previous in state["mv_decks"]:
                field, song, deck = previous["field"], previous["song"], previous["deck"]
                require(field in ("user_live_mv_deck_by_id", "user_live_mv_deck_custom_by_id")
                        and type(song) is int and isinstance(deck, dict),
                        "account_state", "Prior synthetic MV receipt is invalid.")
                current = read_deck(database, client.uid,
                    "u_live_mv_deck" if field == "user_live_mv_deck_by_id" else "u_live_mv_deck_custom", song)
                returned = dictionary(model.get(field))
                require(current == deck and song in returned
                        and all(returned[song].get(key) == value for key, value in deck.items()),
                        "retained_mv", "Prior launch's committed MV decks did not survive reload unchanged.")
            report["gates"][stage] = {"status": "PASS", "saved_mv_decks_verified_before_new_saves": len(state["mv_decks"])}
        stage = "home_theme"
        members = dictionary(model.get("user_member_by_member_id"))
        owned = dictionary(model.get("user_suit_by_suit_id"))
        eligible = [(key, value) for key, value in sorted(members.items())
                    if isinstance(value, dict) and value.get("suit_master_id") in owned
                    and value.get("custom_background_master_id", 0) > 0]
        require(eligible, "home_model", "Login did not contain an owned HOME member, costume and background.")
        member_id, member = eligible[0]
        theme = {"member_master_id": member_id, "suit_master_id": member["suit_master_id"],
                 "custom_background_master_id": member["custom_background_master_id"]}
        changed = client.request("/communicationMember/setTheme", theme)
        returned = dictionary(changed.get("user_model", {}).get("user_member_by_member_id"))
        require(member_id in returned and all(returned[member_id].get(key) == value for key, value in theme.items()),
                "home_theme", "Signed HOME theme round trip did not retain its selected values.")
        report["gates"][stage] = {"status": "PASS", "session_hmac": True, "existing_owned_theme_reapplied": True}
        stage = "bootstrap"
        state["sequence"] += 1
        marker = "ios-protocol-" + hashlib.sha256((state["run_id"] + ":" + str(state["sequence"])).encode()).hexdigest()[:32]
        bootstrap = client.request("/bootstrap/fetchBootstrap", {"bootstrap_fetch_types": fetch_types,
            "device_token": marker, "device_name": "Owned iOS protocol probe"})
        require(isinstance(bootstrap.get("user_model_diff"), dict),
                "bootstrap_model", "HOME bootstrap did not return a user model update.")
        report["gates"][stage] = {"status": "PASS", "session_hmac": True, "fetch_types": fetch_types}
        stage = "database_commit"
        persisted = account_snapshot(database, client)
        require(persisted["auth_count"] == client.auth_count and persisted["command"] == client.command
                and hmac.compare_digest(persisted["session"], client.session) and persisted["device_token"] == marker,
                "database_commit", "Protocol authentication/session/marker changes were not committed to SQLite.")
        with readonly_database(database) as connection:
            home = connection.execute("SELECT suit_master_id,custom_background_master_id FROM u_member "
                                      "WHERE user_id=? AND member_master_id=?", (client.uid, member_id)).fetchone()
            require(home is not None and tuple(home) == (theme["suit_master_id"], theme["custom_background_master_id"]),
                    "home_commit", "HOME theme was not visible through a new SQLite connection.")
        state["device_token"] = marker
        save_state()
        report["gates"][stage] = {"status": "PASS", "new_readonly_connection": True,
                                  "session_key_matches": True, "command_counter_matches": True}
        stage = "mv_protocol"
        master = Path(master_database) if master_database is not None else root / "assets/db" / (
            "jp" if language == "ja" else "gl") / "masterdata.db"
        expected = exercise_mv(client, database, master, report)
        report["gates"][stage] = {"status": "PASS", "actual_gameplay_or_rendering": False}
        stage = "model_reload"
        model = client.login()
        save_state()
        for (field, song), deck in expected.items():
            returned = dictionary(model.get(field))
            require(song in returned and all(returned[song].get(key) == value for key, value in deck.items()),
                    "model_reload", "Fresh authenticated login did not reload the committed per-song MV deck.")
        state["mv_decks"] = [{"field": field, "song": song, "deck": deck}
                             for (field, song), deck in sorted(expected.items())]
        save_state()
        persisted = account_snapshot(database, client)
        require(persisted["auth_count"] == client.auth_count and persisted["command"] == client.command
                and persisted["device_token"] == marker,
                "relogin_commit", "Fresh login did not preserve the committed marker and authentication state.")
        report["gates"][stage] = {"status": "PASS", "fresh_authorized_session": True,
                                  "saved_mv_decks_reloaded": len(expected)}
        report["passed"] = True
        report["status"] = "PASS_CORE_PROTOCOL"
    except Exception as failure:
        code = failure.code if isinstance(failure, ProbeError) else type(failure).__name__
        message = str(failure) if isinstance(failure, ProbeError) else "Probe operation failed; sensitive details were omitted."
        report["gates"][stage] = {"status": "FAIL", "code": code}
        report["failures"].append({"gate": stage, "code": code, "message": message})
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["request_count"] = len(report["requests"])
    if output is not None:
        try:
            require(state_path is None or Path(output).resolve() != state_path.resolve(),
                    "output_collision", "Evidence output must differ from private credential state.")
            write_json(output, report)
        except Exception:
            report["passed"] = False
            report["status"] = "FAIL"
            report["failures"].append({"gate": "evidence", "code": "evidence_write", "message": "Redacted evidence could not be written."})
    return report


def self_test():
    """Packet/crypto unit checks only; never manufacture a live-server gate."""
    key, path = bytes(range(32)), "/unit?l=en&u=1&id=2"
    body = '123,"version",0,{"ok":true}'
    signature = hmac.new(key, (path + " " + body).encode(), hashlib.sha1).hexdigest()
    raw = ("[" + body + "," + json.dumps(signature) + "]").encode()
    require(verify_response(raw, path, key) == {"ok": True}, "selftest", "HMAC packet check failed.")
    try:
        verify_response(raw.replace(b'true', b'null'), path, key)
    except ProbeError as failure:
        require(failure.code == "response_hmac", "selftest", "HMAC tamper rejection check failed.")
    else:
        raise ProbeError("selftest", "Tampered packet was accepted.")
    require(dictionary([1, {"value": 2}]) == {1: {"value": 2}}, "selftest", "Dictionary check failed.")
    with tempfile.TemporaryDirectory(prefix="elichika-protocol-unit-") as directory:
        directory = Path(directory)
        private, public = directory / "private.pem", directory / "public.pem"
        def openssl(arguments, data=None):
            result = subprocess.run(["openssl", *arguments], input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=30, check=False)
            require(result.returncode == 0, "selftest_crypto", "OpenSSL crypto unit operation failed.")
            return result.stdout
        openssl(["genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)])
        public.write_bytes(openssl(["pkey", "-in", str(private), "-pubout"]))
        mask, encrypted = rsa_mask(rsa_public_numbers(public.read_bytes()))
        decoded = openssl(["pkeyutl", "-decrypt", "-inkey", str(private), "-pkeyopt", "rsa_padding_mode:oaep",
                           "-pkeyopt", "rsa_oaep_md:sha1", "-pkeyopt", "rsa_mgf1_md:sha1"], base64.b64decode(encrypted))
        require(hmac.compare_digest(mask, decoded), "selftest_crypto", "RSA-OAEP/SHA1 interoperability failed.")
        state = directory / "state.json"
        write_json(state, {"synthetic": True}, private=True)
        require(stat.S_IMODE(state.stat().st_mode) == 0o600 and bounded_json(state) == {"synthetic": True},
                "selftest_state", "Private state write/read check failed.")
    return {"schema": 1, "status": "PASS_UNIT_SELF_TESTS", "real_server_contacted": False,
            "checks": ["response_hmac", "tamper_rejection", "model_dictionary", "RSA_OAEP_SHA1_OpenSSL", "private_state_permissions"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--language", default="en", choices=tuple(STARTUP_KEYS))
    parser.add_argument("--account-state", type=Path)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--protocol-config", type=Path)
    parser.add_argument("--master-database", type=Path)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        report = self_test()
        if args.output:
            write_json(args.output, report)
    else:
        if not args.endpoint or not args.data_root:
            parser.error("--endpoint and --data-root are required unless --self-test is selected")
        report = probe(args.endpoint, args.data_root, args.output, language=args.language,
            account_state=args.account_state, public_key=args.public_key, protocol_config=args.protocol_config,
            master_database=args.master_database, timeout=args.timeout)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("passed") or report.get("status") == "PASS_UNIT_SELF_TESTS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
