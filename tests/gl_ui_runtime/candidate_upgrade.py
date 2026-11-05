"""Upgrade only the wrapper APK on an existing disposable GL QA device.

The caller must validate the prepared, game-created synthetic UID first. No GL
APK reinstall/data clearing, preference mutation, or game UI actions occur here.
"""
from contextlib import closing
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke
import android_release_smoke as release
import revision_receipt

# Filled only after root independently audits the exact private signed build.
SOURCE_SHA = "56861368fd76b82f395492b8e1c456a71a28a57a"
ARTIFACT_ID = 13381940509
ARTIFACT_RUN_ID = "41950334362"
APK_SHA256 = "f31f2aad8de3e05821c25b18781c0bcaf7e13178daa16b94c17c0e03f654fb0f"
NATIVE_SHA256 = "e8f3ab088f2eb5bad28508d71ebc2414aab898c755c7659d8bde6d981f5e0262"
VERSION_CODE = 2026110501
VERSION_NAME = "2026.11.05.1"
APK_NAME = "elichika-2026.11.05.1.apk"
BASELINE_SHA256 = "815e9dd70d1b0e89b97f76b83c1b71136ec7f5f73f6e9a6a983d123a7aa42cac"
BASELINE_VERSION_CODE = 2026110404
BASELINE_VERSION_NAME = "2026.11.04.4"
SIGNER_SHA256 = "fed020601692d2e759286831ad229f0c8e4562a8e90f9067d7472fa5fc99f930"
REPOSITORY = "tagundo/elichika"
MAX_BYTES = 768 * 1024 * 1024


class CandidateUpgradeError(ValueError):
    """Only fixed non-sensitive reason identifiers may be used."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def validate_pins(command, repository):
    if (ARTIFACT_ID <= 0 or not re.fullmatch(r"[0-9a-f]{40}", SOURCE_SHA)
            or not re.fullmatch(r"[0-9a-f]{64}", APK_SHA256)
            or not re.fullmatch(r"[0-9a-f]{64}", NATIVE_SHA256)):
        raise CandidateUpgradeError("candidate_not_pinned_after_independent_audit")
    if repository != REPOSITORY:
        raise CandidateUpgradeError("candidate_repository_not_allowlisted")
    if type(command.get("artifact_id")) is not int or command["artifact_id"] != ARTIFACT_ID:
        raise CandidateUpgradeError("invalid_candidate_artifact_id")
    if command.get("artifact_run_id") != ARTIFACT_RUN_ID:
        raise CandidateUpgradeError("invalid_candidate_run_id")
    if command.get("source_sha") != SOURCE_SHA:
        raise CandidateUpgradeError("candidate_source_not_allowlisted")
    if command.get("apk_sha256") != APK_SHA256:
        raise CandidateUpgradeError("invalid_candidate_apk_hash")
    if type(command.get("version_code")) is not int or command["version_code"] != VERSION_CODE or command.get("version_name") != VERSION_NAME:
        raise CandidateUpgradeError("candidate_version_not_allowlisted")
    return {key: command[key] for key in ("artifact_id", "artifact_run_id", "source_sha", "apk_sha256", "version_code", "version_name")}


def validate_metadata(metadata, pins):
    workflow = metadata.get("workflow_run", {}) if isinstance(metadata, dict) else {}
    if (not isinstance(metadata, dict) or type(metadata.get("id")) is not int or metadata["id"] != pins["artifact_id"] or
            metadata.get("name") != "elichika-release-apk" or metadata.get("expired") is not False or
            not isinstance(workflow, dict) or type(workflow.get("id")) is not int or
            str(workflow["id"]) != pins["artifact_run_id"] or workflow.get("head_sha") != pins["source_sha"]):
        raise CandidateUpgradeError("candidate_artifact_metadata_mismatch")


def trusted_redirect(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        valid = (parsed.scheme == "https" and not parsed.username and not parsed.password and
                 parsed.port in (None, 443) and not parsed.fragment and
                 any(host.endswith(suffix) for suffix in (".blob.core.windows.net", ".actions.githubusercontent.com")) and
                 not any(ord(c) <= 32 for c in url))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise CandidateUpgradeError("candidate_download_host_not_allowlisted")
    return url


def copy_bounded(source, destination):
    total = 0
    with destination.open("wb") as output:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_BYTES:
                raise CandidateUpgradeError("candidate_download_too_large")
            output.write(block)
    if total == 0:
        raise CandidateUpgradeError("candidate_download_empty")


def extract_candidate(archive_path, directory, pins):
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise CandidateUpgradeError("candidate_archive_members_invalid")
            entry = entries[0]
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (entry.filename != APK_NAME or entry.is_dir() or kind not in (0, stat.S_IFREG) or
                    entry.flag_bits & 1 or not 0 < entry.file_size <= MAX_BYTES):
                raise CandidateUpgradeError("candidate_archive_member_invalid")
            target = directory / "candidate.apk"
            with archive.open(entry) as source:
                copy_bounded(source, target)
        with target.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != pins["apk_sha256"]:
            raise CandidateUpgradeError("candidate_apk_hash_mismatch")
        return target
    except CandidateUpgradeError:
        raise
    except Exception:
        raise CandidateUpgradeError("candidate_archive_invalid") from None


def download_candidate(repository, pins, directory, token):
    if not token:
        raise CandidateUpgradeError("candidate_actions_token_missing")
    opener = urllib.request.build_opener(NoRedirect)
    base = f"https://api.github.com/repos/{repository}/actions/artifacts/{pins['artifact_id']}"
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Elichika-disposable-GL-candidate-upgrade"}
    try:
        with opener.open(urllib.request.Request(base, headers=headers, method="GET"), timeout=30) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise CandidateUpgradeError("candidate_metadata_too_large")
        validate_metadata(json.loads(raw), pins)
        request = urllib.request.Request(base + "/zip", headers=headers, method="GET")
        try:
            with opener.open(request, timeout=30):
                raise CandidateUpgradeError("candidate_download_redirect_missing")
        except urllib.error.HTTPError as redirect:
            try:
                if redirect.code != 302:
                    raise CandidateUpgradeError("candidate_download_redirect_missing")
                location = trusted_redirect(redirect.headers.get("Location", ""))
            finally:
                redirect.close()
        # Never forward Authorization, API headers, or follow another redirect.
        public_request = urllib.request.Request(location, headers={"User-Agent": "Elichika-disposable-GL-candidate-upgrade"}, method="GET")
        archive_path = directory / "artifact.zip"
        with opener.open(public_request, timeout=90) as response:
            copy_bounded(response, archive_path)
        return extract_candidate(archive_path, directory, pins)
    except CandidateUpgradeError:
        raise
    except Exception:
        # URLs, signed query strings, bodies, headers, and token never enter an
        # exception message or an evidence file.
        raise CandidateUpgradeError("candidate_artifact_download_failed") from None


def verify_apk_certificate(apk):
    """Check the APK signature locally; never persist signer-tool output."""
    roots = [os.environ.get(name) for name in ("ANDROID_SDK_ROOT", "ANDROID_HOME")]
    signer = next((Path(root) / "build-tools/34.0.0/apksigner" for root in roots
                   if root and (Path(root) / "build-tools/34.0.0/apksigner").is_file()), None)
    if signer is None:
        raise CandidateUpgradeError("candidate_apksigner_unavailable")
    try:
        checked = subprocess.run([str(signer), "verify", "--verbose", "--print-certs", str(apk)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=True)
        certificates = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$",
                                  checked.stdout.decode("utf-8", "replace"), re.MULTILINE)
        if len(certificates) != 1 or certificates[0].lower() != SIGNER_SHA256:
            raise CandidateUpgradeError("candidate_apk_signer_mismatch")
    except CandidateUpgradeError:
        raise
    except Exception:
        raise CandidateUpgradeError("candidate_apk_signature_verification_failed") from None
    return SIGNER_SHA256


def installed_apk_path(android, package=release.PACKAGE):
    rows = android.shell("pm", "path", package).splitlines()
    if len(rows) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_~+./=-]+/base\.apk", rows[0]):
        raise CandidateUpgradeError("candidate_installed_apk_not_unique")
    return rows[0][8:]


def verify_retained_game(android):
    actual = android.shell("sha256sum", installed_apk_path(android, smoke.GAME)).split()[0]
    if actual != smoke.GAME_SHA:
        raise CandidateUpgradeError("candidate_gl_apk_hash_changed")
    return actual


def verify_baseline(android, directory):
    existing = android.shell("dumpsys", "package", release.PACKAGE)
    if (not re.search(r"(?:^|\s)versionCode=" + str(BASELINE_VERSION_CODE) + r"(?:\s|$)", existing) or
            not re.search(r"(?:^|\s)versionName=" + re.escape(BASELINE_VERSION_NAME) + r"(?:\s|$)", existing)):
        raise CandidateUpgradeError("candidate_existing_wrapper_version_mismatch")
    path = installed_apk_path(android)
    if android.shell("sha256sum", path).split()[0] != BASELINE_SHA256:
        raise CandidateUpgradeError("candidate_existing_wrapper_hash_mismatch")
    local = directory / "baseline.apk"
    android.adb("pull", path, str(local), timeout=180)
    with local.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != BASELINE_SHA256:
        raise CandidateUpgradeError("candidate_existing_wrapper_hash_mismatch")
    certificate = verify_apk_certificate(local)
    return {"apk_sha256": actual, "version_code": BASELINE_VERSION_CODE,
            "version_name": BASELINE_VERSION_NAME, "signer_certificate_sha256": certificate,
            "signature_verification": "PASS"}


def userdata_state(android, uid):
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/userdata.db"))) as connection:
        profile = connection.execute("SELECT * FROM u_status WHERE user_id=?", (uid,)).fetchall()
        decks = connection.execute("SELECT * FROM u_live_deck WHERE user_id=? ORDER BY user_live_deck_id", (uid,)).fetchall()
        def digest(rows):
            value = [tuple(row) for row in rows]
            encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                                 default=lambda data: {"bytes": bytes(data).hex()}).encode()
            return hashlib.sha256(encoded).hexdigest()
        tables = {}
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        for table, sql in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            rows = connection.execute("SELECT * FROM " + quote(table)).fetchall()
            columns = [row[1] for row in connection.execute("PRAGMA table_info(" + quote(table) + ")")]
            # Sorted hashes diagnose changed data without exporting row values.
            def multiset_hash(values):
                return smoke.sha(json.dumps(sorted(digest([value]) for value in values), separators=(",", ":")).encode())
            tables[table] = {"rows": len(rows), "schema_sha256": smoke.sha((sql or "").encode()),
                             "rows_sha256": multiset_hash(rows),
                             "columns": {column: multiset_hash([(row[index],) for row in rows])
                                         for index, column in enumerate(columns)}}
        return {"logical_sha256": smoke.sha("\n".join(connection.iterdump()).encode()),
                "accounts": connection.execute("SELECT COUNT(*) FROM u_status").fetchone()[0],
                "profile_sha256": digest(profile), "deck_sha256": digest(decks),
                "profile_rows": len(profile), "deck_rows": len(decks), "tables": tables}


def userdata_changes(before, after):
    changes = {}
    old, new = before.get("tables", {}), after.get("tables", {})
    for table in sorted(old.keys() | new.keys()):
        if old.get(table) == new.get(table):
            continue
        previous, current = old.get(table, {}), new.get(table, {})
        columns_before, columns_after = previous.get("columns", {}), current.get("columns", {})
        changes[table] = {"kind": "added" if table not in old else "removed" if table not in new else "changed",
                          "schema_changed": previous.get("schema_sha256") != current.get("schema_sha256"),
                          "row_count_changed": previous.get("rows") != current.get("rows"),
                          "changed_columns": sorted(column for column in columns_before.keys() | columns_after.keys()
                                                    if columns_before.get(column) != columns_after.get(column))}
    return {"logical_changed": before.get("logical_sha256") != after.get("logical_sha256"),
            "profile_changed": before.get("profile_sha256") != after.get("profile_sha256"),
            "deck_changed": before.get("deck_sha256") != after.get("deck_sha256"), "tables": changes}


def config_state(raw):
    """Hash JSON in memory; type tags prevent bool/int or number rounding equality."""
    result = {"raw_sha256": smoke.sha(raw), "semantic_sha256": None, "valid": False, "keys": {}}
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value
    def typed(value):
        if isinstance(value, dict):
            return ["object", [[key, typed(value[key])] for key in sorted(value)]]
        if isinstance(value, list):
            return ["array", [typed(item) for item in value]]
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("nonfinite number")
            # Decimal normalization without context rounding.
            sign, digits, exponent = value.as_tuple()
            digits = list(digits)
            while len(digits) > 1 and digits[-1] == 0:
                digits.pop()
                exponent += 1
            return ["decimal", sign, digits, exponent]
        return [type(value).__name__, value]
    def digest(value):
        return smoke.sha(json.dumps(typed(value), ensure_ascii=True, separators=(",", ":")).encode())
    def keys(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                child = path + "/" + key.replace("~", "~0").replace("/", "~1")
                result["keys"][child] = digest(item)
                keys(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                keys(item, path + "/" + str(index))
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite number")))
        if not isinstance(value, dict):
            return result
        result.update(semantic_sha256=digest(value), valid=True)
        keys(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return result


def config_changes(before, after):
    old, new = before["keys"], after["keys"]
    return {"added_keys": sorted(new.keys() - old.keys()), "removed_keys": sorted(old.keys() - new.keys()),
            "changed_keys": sorted(key for key in old.keys() & new.keys() if old[key] != new[key])}


def record_retained(result, stage, userdata, config, before=None, config_before=None):
    # Store evidence before any preservation guard can raise.
    result[stage] = userdata
    result.setdefault("config", {})[stage] = {key: config[key] for key in ("raw_sha256", "semantic_sha256", "valid")}
    if before is not None:
        result.setdefault("userdata_changes", {})[stage] = userdata_changes(before, userdata)
        result.setdefault("config_changes", {})[stage] = config_changes(config_before, config)


def record_mod_retained(android, state, result, uid, stage):
    fixture = state.get("new_home", {}).get("mod_fixture")
    if fixture is None:
        return
    from gl_ui_runtime.mod_fixture import ModFixtureError, verify_retained
    record = {"status": "REFUSED"}
    result.setdefault("mod_preservation", {})[stage] = record
    try:
        record.update(verify_retained(android, fixture, uid), status="PASS")
    except ModFixtureError as error:
        record["reason"] = str(error)
        raise CandidateUpgradeError("candidate_mod_fixture_not_preserved") from None


def verify_imported_content(android):
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/assets/db/gl/masterdata.db"))) as master:
        suits = [row[0] for row in master.execute("SELECT id FROM m_suit WHERE id IN (300207,321107,321207) ORDER BY id")]
        background = master.execute("SELECT id FROM m_custom_background WHERE id=202300200").fetchone()
        live = master.execute("SELECT live_id,music_id FROM m_live WHERE live_id=13001").fetchone()
    if suits != [300207, 321107, 321207] or background is None or live is None or tuple(live) != (13001, 3001):
        raise CandidateUpgradeError("candidate_official_additions_missing")
    return {"suit_ids": suits, "background_id": background[0], "live_id": live[0], "music_id": live[1]}


def verify_titles(android):
    with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/assets/db/gl/masterdata.db"))) as master:
        references = master.execute("""
            SELECT s.id,s.name,s.member_m_id,m.name FROM m_suit s
            JOIN m_member m ON m.id=s.member_m_id WHERE s.id IN (321107,321207) ORDER BY s.id
        """).fetchall()
    expected = [(321107, "k.suit_name_321207", 211, "k.m_dic_member_name_212"),
                (321207, "k.suit_name_321107", 212, "k.m_dic_member_name_211")]
    if [tuple(row) for row in references] != expected:
        raise CandidateUpgradeError("candidate_member_reference_chain_changed")
    result = {}
    for language, prefix in (("en", "ODAIBA Gamers T-Shirt"), ("ko", "오다이바 게이머즈 T셔츠"), ("zh", "ODAIBA Gamers T恤")):
        checked = []
        with closing(smoke.database_from_bytes(android.read(f"{smoke.FILES}/assets/db/gl/dictionary_{language}_k.db"))) as dictionary:
            for suit_id, suit_key, member_id, member_key in references:
                if not suit_key.startswith("k.") or not member_key.startswith("k."):
                    raise CandidateUpgradeError("candidate_dictionary_reference_invalid")
                owner = dictionary.execute("SELECT message FROM m_dictionary WHERE id=?", (member_key[2:],)).fetchone()
                title = dictionary.execute("SELECT message FROM m_dictionary WHERE id=?", (suit_key[2:],)).fetchone()
                if not owner or not owner[0] or not title or title[0] != prefix + " " + owner[0]:
                    raise CandidateUpgradeError("candidate_localized_owner_title_not_repaired")
                checked.append({"suit_id": suit_id, "member_id": member_id, "member_dictionary_key": member_key,
                                "suit_dictionary_key": suit_key, "title": title[0]})
        result[language] = checked
    return result


def upgrade_candidate(android, args, state, report, command, uid):
    result = {"status": "RUNNING", "game_restart_required": True}
    report["candidate_upgrade"] = result
    try:
        pins = validate_pins(command, args.repository)
        home = state.get("new_home", {})
        home_uid = home.get("user_id", home.get("uid"))
        if type(uid) is not int or uid <= 0 or home.get("status") != "PREPARED" or type(home_uid) is not int or home_uid != uid:
            raise CandidateUpgradeError("candidate_known_synthetic_uid_required")
        if not android.shell("id").startswith("uid=0") or android.shell("getprop", "ro.product.cpu.abi") != "arm64-v8a":
            raise CandidateUpgradeError("candidate_disposable_arm64_target_required")
        evidence_roots = {Path(args.evidence).resolve(), Path(args.state).resolve().parent.parent}
        runner_temp = os.environ.get("RUNNER_TEMP")
        if not runner_temp:
            raise CandidateUpgradeError("candidate_runner_temp_missing")
        base = Path(runner_temp).resolve()
        if any(base == evidence or base.is_relative_to(evidence) for evidence in evidence_roots):
            raise CandidateUpgradeError("candidate_temporary_path_inside_evidence")
        result.update(pins)
        with tempfile.TemporaryDirectory(prefix="elichika-qa-candidate-", dir=base) as temporary:
            temporary_path = Path(temporary).resolve()
            if any(temporary_path == evidence or temporary_path.is_relative_to(evidence) for evidence in evidence_roots):
                raise CandidateUpgradeError("candidate_temporary_path_inside_evidence")
            result["game_apk_before_sha256"] = verify_retained_game(android)
            result["baseline"] = verify_baseline(android, temporary_path)
            apk = download_candidate(args.repository, pins, temporary_path, os.environ.get("GITHUB_TOKEN", ""))
            result["signer_certificate_sha256"] = verify_apk_certificate(apk)
            with zipfile.ZipFile(apk) as archive:
                if archive.namelist().count("lib/arm64-v8a/libelichika.so") != 1:
                    raise CandidateUpgradeError("candidate_arm64_native_missing")
                expected_native = smoke.sha(archive.read("lib/arm64-v8a/libelichika.so"))
            if expected_native != NATIVE_SHA256:
                raise CandidateUpgradeError("candidate_audited_native_hash_mismatch")
            try:
                manifest = revision_receipt.read_packaged_manifest(apk)
            except revision_receipt.ReceiptError as error:
                raise CandidateUpgradeError(str(error)) from None
            result["data_revision"] = manifest["revision"]
            android.shell("am", "force-stop", smoke.GAME)
            smoke.stop_server(android)
            before = userdata_state(android, uid)
            config_before = config_state(android.read(f"{smoke.FILES}/config.json"))
            record_retained(result, "before_update", before, config_before)
            record_mod_retained(android, state, result, uid, "before_update")
            if before["profile_rows"] != 1 or before["deck_rows"] < 1:
                raise CandidateUpgradeError("candidate_synthetic_profile_or_deck_missing")
            if not config_before["valid"]:
                raise CandidateUpgradeError("candidate_config_invalid")
            installed = android.install(apk, VERSION_CODE)
            result["install"] = installed
            after_install = userdata_state(android, uid)
            config_after_install = config_state(android.read(f"{smoke.FILES}/config.json"))
            record_retained(result, "after_install", after_install, config_after_install, before, config_before)
            record_mod_retained(android, state, result, uid, "after_install")
            if installed.get("native_sha256") != expected_native:
                raise CandidateUpgradeError("candidate_installed_native_hash_mismatch")
            info = android.shell("dumpsys", "package", release.PACKAGE)
            if (not re.search(r"(?:^|\s)versionCode=" + str(VERSION_CODE) + r"(?:\s|$)", info) or
                    not re.search(r"(?:^|\s)versionName=" + re.escape(VERSION_NAME) + r"(?:\s|$)", info)):
                raise CandidateUpgradeError("candidate_installed_version_mismatch")
            actual_apk = android.shell("sha256sum", installed_apk_path(android)).split()[0]
            if actual_apk != pins["apk_sha256"]:
                raise CandidateUpgradeError("candidate_installed_apk_hash_mismatch")
            if after_install != before:
                raise CandidateUpgradeError("candidate_install_changed_userdata")
            if not config_after_install["valid"] or config_after_install["semantic_sha256"] != config_before["semantic_sha256"]:
                raise CandidateUpgradeError("candidate_install_changed_config")
            started = android.start("followup-candidate-upgrade")
            result["start"] = started
            after_start = userdata_state(android, uid)
            config_after_start = config_state(android.read(f"{smoke.FILES}/config.json"))
            record_retained(result, "after_start", after_start, config_after_start, before, config_before)
            record_mod_retained(android, state, result, uid, "after_start")
            result["game_apk_after_sha256"] = verify_retained_game(android)
            if started.get("running_native_sha256") != expected_native:
                raise CandidateUpgradeError("candidate_running_native_hash_mismatch")
            if after_start != before:
                raise CandidateUpgradeError("candidate_start_changed_userdata")
            if not config_after_start["valid"] or config_after_start["semantic_sha256"] != config_before["semantic_sha256"]:
                raise CandidateUpgradeError("candidate_start_changed_config")
            try:
                result["committed_data_receipt"] = revision_receipt.verify_committed_receipt(android, manifest)
            except revision_receipt.ReceiptError as error:
                raise CandidateUpgradeError(str(error)) from None
            result.update(after_install=after_install, after_start=after_start, start=started,
                          userdata_preserved=True, profile_preserved=True, deck_preserved=True, config_preserved=True,
                          repaired_titles=verify_titles(android), status="UPGRADED")
            if home.get("mod_fixture") is not None:
                result["official_additions"] = verify_imported_content(android)
        return result
    except CandidateUpgradeError as error:
        result.update(status="REFUSED", reason=str(error))
        raise
    except Exception:
        result.update(status="REFUSED", reason="candidate_upgrade_failed")
        raise CandidateUpgradeError("candidate_upgrade_failed") from None
