"""Read-only binding of a signed APK's official data to its committed receipt.

Only public source records and bounded installer metadata are returned. Live
modded game DBs are not compared to stock, and no account/config values escape.
"""
from contextlib import closing
import hashlib
import json
import re
import zipfile

import android_gl_visual_smoke as smoke

MANIFEST = "assets/payload_revision.json"
MANAGED = {"webui", "server init jsons", "privatekey.pem", "publickey.pem", "assets", "static", "serverdata.db"}
HEX = re.compile(r"[0-9a-f]{64}")
EPOCH = "managed-game-content-v1"
PAIRS = {"assets/db/gl/masterdata.db": "assets/db/jp/masterdata.db"}
PAIRS.update({f"assets/db/gl/asset_{p}_{l}.db": f"assets/db/jp/asset_{p}_ja.db"
              for p in ("a", "i") for l in ("en", "ko", "zh")})
REQUIRED = {"serverdata.db", *PAIRS, *PAIRS.values(), "assets/db/jp/dictionary_ja_k.db",
            *(f"assets/db/gl/dictionary_{language}_k.db" for language in ("en", "ko", "zh"))}


class ReceiptError(ValueError):
    """Fixed reasons only; never propagate metadata bodies or SQL exceptions."""


def require(value, reason):
    if not value:
        raise ReceiptError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "candidate_revision_duplicate_key")
        result[key] = value
    return result


def decode(raw, limit):
    require(isinstance(raw, bytes) and len(raw) <= limit, "candidate_revision_metadata_size")
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except ReceiptError:
        raise
    except Exception:
        raise ReceiptError("candidate_revision_metadata_invalid") from None


def is_database(name):
    return name == "serverdata.db" or bool(re.fullmatch(r"assets/db/(gl|jp)/[^/]+\.db", name))


def read_packaged_manifest(apk):
    """Hash the actual signed archive streams; do not extract/copy payloads."""
    try:
        with zipfile.ZipFile(apk) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)) and names.count(MANIFEST) == 1,
                    "candidate_revision_archive_invalid")
            info = archive.getinfo(MANIFEST)
            require(info.file_size <= 4 * 1024 * 1024, "candidate_revision_metadata_size")
            manifest = decode(archive.read(info), 4 * 1024 * 1024)
            require(isinstance(manifest, dict) and set(manifest) == {
                "format", "compatibility_epoch", "jp_global_algorithm", "files", "revision"},
                "candidate_revision_contract_invalid")
            require(type(manifest["format"]) is int and manifest["format"] == 1
                    and manifest["compatibility_epoch"] == EPOCH
                    and manifest["jp_global_algorithm"] == "jp-global-content-v1",
                    "candidate_revision_contract_invalid")
            body = {key: value for key, value in manifest.items() if key != "revision"}
            revision = "payload-v1:" + hashlib.sha256(json.dumps(body, sort_keys=True,
                ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
            require(manifest["revision"] == revision, "candidate_revision_digest_mismatch")
            files = manifest["files"]
            require(isinstance(files, dict) and 1 <= len(files) <= 20000,
                    "candidate_revision_file_set_invalid")
            actual = {name[len("assets/payload/"):] for name in names
                      if name.startswith("assets/payload/") and not name.endswith("/")
                      and name[len("assets/payload/"):].split("/")[0] in MANAGED}
            require(actual == set(files), "candidate_revision_file_set_invalid")
            for name, record in files.items():
                parts = name.split("/")
                require(parts[0] in MANAGED and all(part not in ("", ".", "..", ".git") for part in parts)
                        and "\\" not in name and ":" not in name
                        and not any(ord(char) < 32 for char in name)
                        and isinstance(record, dict) and set(record) == {"sha256", "bytes"}
                        and isinstance(record["sha256"], str) and HEX.fullmatch(record["sha256"])
                        and type(record["bytes"]) is int and 0 <= record["bytes"] <= 2 * 1024 ** 3,
                        "candidate_revision_file_invalid")
                entry = archive.getinfo("assets/payload/" + name)
                require(entry.file_size == record["bytes"], "candidate_revision_payload_mismatch")
                require(not is_database(name) or entry.file_size >= 100,
                        "candidate_revision_file_invalid")
                with archive.open(entry) as stream:
                    require(hashlib.file_digest(stream, "sha256").hexdigest() == record["sha256"],
                            "candidate_revision_payload_mismatch")
            require(REQUIRED.issubset(files), "candidate_revision_file_set_invalid")
            return manifest
    except ReceiptError:
        raise
    except Exception:
        raise ReceiptError("candidate_revision_archive_invalid") from None


def verify_committed_receipt(android, manifest):
    """Read the official baseline index, without exporting it to artifacts."""
    try:
        revision = manifest["revision"]
        raw = android.read(smoke.FILES + "/installed_version")
        require(len(raw) <= 4096 and raw.decode().strip() == revision,
                "candidate_committed_revision_mismatch")
        descriptor = decode(android.read(smoke.FILES + "/.payload-upgrade/current.json"), 1024 * 1024)
        expected = {name: record for name, record in manifest["files"].items() if is_database(name)}
        require(type(descriptor.get("contract_version")) is int and descriptor.get("contract_version") == 1
                and descriptor.get("payload_version") == revision
                and descriptor.get("jp_global_algorithm") == "jp-global-content-v1"
                and descriptor.get("jp_global_integrated") is True
                and type(descriptor.get("baseline_format")) is int and descriptor.get("baseline_format") == 1
                and descriptor.get("baseline_index") == ".payload-upgrade/baseline.sqlite"
                and descriptor.get("incoming_databases") == expected,
                "candidate_committed_receipt_mismatch")
        coverage = descriptor.get("jp_global_coverage")
        require(isinstance(coverage, list) and len(coverage) == len(PAIRS), "candidate_committed_coverage_mismatch")
        seen = set()
        for row in coverage:
            target = row.get("target")
            source = PAIRS.get(target)
            require(target not in seen and source is not None and row.get("source") == source
                    and row.get("algorithm_version") == "jp-global-content-v1"
                    and row.get("source_sha256") == expected[source]["sha256"],
                    "candidate_committed_coverage_mismatch")
            seen.add(target)
        raw = android.read(smoke.FILES + "/.payload-upgrade/baseline.sqlite")
        require(100 <= len(raw) <= 16 * 1024 * 1024, "candidate_committed_baseline_invalid")
        with closing(smoke.database_from_bytes(raw)) as db:
            require([tuple(row) for row in db.execute("PRAGMA integrity_check")] == [("ok",)], "candidate_committed_baseline_invalid")
            require(dict(db.execute("SELECT key,value FROM meta")) == {"format": "1", "payload_version": revision},
                    "candidate_committed_baseline_mismatch")
            rows = db.execute("SELECT file,sha256,bytes FROM files").fetchall()
            require(len(rows) == len(expected) and {name: {"sha256": digest, "bytes": size}
                    for name, digest, size in rows} == expected, "candidate_committed_baseline_mismatch")
            manifests = dict(db.execute("SELECT file,contents FROM manifests"))
            expected_headers = {name: record for name, record in manifest["files"].items()
                                if re.fullmatch(r"assets/db/(gl|jp)/masterdata_[ai]_[a-z]{2}", name)}
            require(set(manifests) == set(expected_headers) and all(isinstance(value, bytes)
                    and len(value) == expected_headers[name]["bytes"]
                    and hashlib.sha256(value).hexdigest() == expected_headers[name]["sha256"]
                    for name, value in manifests.items()), "candidate_committed_headers_mismatch")
        return {"status": "PASS", "data_revision": revision, "compatibility_epoch": manifest["compatibility_epoch"],
                "official_database_count": len(expected), "official_header_count": len(expected_headers)}
    except ReceiptError:
        raise
    except Exception:
        raise ReceiptError("candidate_committed_receipt_invalid") from None
