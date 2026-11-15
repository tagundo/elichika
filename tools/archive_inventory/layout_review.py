#!/usr/bin/env python3
"""Source-only deterministic layout review. No network or account-write code."""
from __future__ import annotations
import argparse
import codecs
import hashlib
import json
from pathlib import Path
import re
import time
import zipfile

INVENTORY_SHA = "e316340dfda6078d0c8b7ab28951ab48f588608f8d1834a1de6580d5cc68c755"
TARGET_SHA = "e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c"
SEED_RAW = {"journal.json": "76fc8a69c26b5830014401e54605b2e50ed22d458dd55301668609b3f61c7629",
            "journal.events.jsonl": "a22d940c9a626e01c5d18fcfe7012bcc709ddd5b9d9d2c8f94a7a0dec8d21c80"}
SEED_SOURCE = {"run_id": 43699687032, "source_commit": "1d487a4cf512127f3b1afbe62b0ed4f83b3a3ba1",
               "artifact_id": 14156036891, "zip_sha256": "0dd6c141a9c9bb49a7f22cdf09b52e9019be216143b2a74d28686d546f041e0f",
               "raw_sha256": SEED_RAW}
PREFIX = "elichika-assets-20261115-e316340d-fa6f6031"
ITEMS = tuple(PREFIX + f"-b{i:02d}" for i in range(5))
OLD_ABSENT_ITEMS = tuple(PREFIX + f"-b{i:02d}" for i in range(5, 9))
INDEX_PREFIX = "elichika-selective-five-v1"
PROFILES = ("gl/android/en", "gl/android/ko", "gl/android/zh", "gl/ios/en", "gl/ios/ko", "gl/ios/zh", "jp/android/ja", "jp/ios/ja")
INDEX_KEYS = tuple(INDEX_PREFIX + "/profiles/" + p + ".json" for p in PROFILES) + (INDEX_PREFIX + "/catalog.json",)
ACK = frozenset(("PUT_ACKNOWLEDGED", "REMOTE_METADATA_VERIFIED"))
EXPECTED_OBJECTS, EXPECTED_BYTES, EXPECTED_ACKS, EXPECTED_STAGED = 42830, 33321064961, 401, 6
SHA = re.compile(r"[0-9a-f]{64}\Z")
MD5 = re.compile(r"[0-9a-f]{32}\Z")


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class JsonStream:
    """Decode one bounded value at a time while hashing exact original bytes."""
    def __init__(self, stream):
        self.stream, self.buffer, self.pos, self.eof = stream, "", 0, False
        self.decoder, self.utf8, self.sha = json.JSONDecoder(), codecs.getincrementaldecoder("utf8")(), hashlib.sha256()

    def fill(self):
        raw = self.stream.read(65536)
        self.sha.update(raw)
        self.buffer = self.buffer[self.pos:] + self.utf8.decode(raw, final=not raw)
        self.pos = 0
        self.eof = not raw
        require(len(self.buffer) <= 4 * 1024 * 1024, "An inventory JSON value exceeds the review bound")

    def char(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace(): self.pos += 1
            if self.pos < len(self.buffer): return self.buffer[self.pos]
            require(not self.eof, "Truncated inventory JSON")
            self.fill()

    def take(self, expected):
        require(self.char() == expected, "Unexpected inventory JSON structure")
        self.pos += 1

    def value(self):
        self.char()
        while True:
            try:
                value, self.pos = self.decoder.raw_decode(self.buffer, self.pos)
                return value
            except json.JSONDecodeError:
                require(not self.eof, "Malformed inventory JSON")
                self.fill()

    def objects(self, headers):
        self.take("{"); seen = set()
        while self.char() != "}":
            key = self.value(); require(isinstance(key, str) and key not in seen, "Duplicate inventory header")
            seen.add(key); self.take(":")
            if key == "objects":
                self.take("{"); names = set()
                while self.char() != "}":
                    name = self.value(); require(name not in names, "Duplicate inventory object")
                    names.add(name); self.take(":"); obj = self.value()
                    yield name, obj
                    if self.char() != "}": self.take(",")
                self.take("}")
            else:
                headers[key] = self.value()
            if self.char() != "}": self.take(",")
        self.take("}")
        # Include final newline/trailing bytes in the source SHA, rejecting data.
        while True:
            require(not self.buffer[self.pos:].strip(), "Trailing inventory data")
            if self.eof: break
            self.pos = len(self.buffer); self.fill()


def load_seed(directory):
    directory = Path(directory); raw = {}
    for name, expected in SEED_RAW.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 1024 * 1024, "Unsafe old seed source")
        raw[name] = path.read_bytes()
        require(hashlib.sha256(raw[name]).hexdigest() == expected, "Old seed bytes differ")
    journal = json.loads(raw["journal.json"]); identity = journal["identity"]
    require(identity["prefix"] == PREFIX and identity["session"] == "fa6f6031e8e339617ab58709d81f0e4f" and
            identity["account"] == "tagundo" and identity["inventory_sha256"] == INVENTORY_SHA and
            identity["target_manifest_sha256"] == TARGET_SHA and identity["allow_partial"] is False and
            identity["requested_total"] == 42830, "Old seed identity differs")
    objects = {}
    for line in raw["journal.events.jsonl"].splitlines():
        require(len(line) <= 8192, "Oversized old seed event")
        event = json.loads(line)
        require(event.get("type") in ("objects", "index_objects", "status"), "Unknown old seed event")
        require(event.get("type") != "index_objects", "A prior index may not be silently migrated")
        if event.get("type") == "objects": objects[event["name"]] = event["record"]
    require(sum(r["status"] in ACK for r in objects.values()) == EXPECTED_ACKS and
            sum(r["status"] == "STAGED" for r in objects.values()) == EXPECTED_STAGED and len(objects) == EXPECTED_ACKS + EXPECTED_STAGED,
            "Old seed status totals differ")
    return identity, objects


def new_item(name):
    return ITEMS[int.from_bytes(hashlib.sha256(name.encode("ascii")).digest(), "big") % 5]


def build_plan(object_rows, identity, seed_objects):
    placements, counts, sizes, retained, retained_locations, staged, pending_existing, profile_names = {}, dict.fromkeys(ITEMS, 0), dict.fromkeys(ITEMS, 0), {}, {}, {}, {}, dict.fromkeys(PROFILES, 0)
    seed_seen = set()
    for name, obj in object_rows:
        require(isinstance(name, str) and re.fullmatch(r"[a-z0-9]{6}", name), "Unsafe target name")
        require(name not in placements and type(obj.get("size")) is int and obj["size"] > 0 and SHA.fullmatch(obj.get("sha256", "")), "Invalid target object")
        old = seed_objects.get(name)
        if old:
            seed_seen.add(name)
            require(old["size"] == obj["size"] and old["sha256"] == obj["sha256"] and
                    old["path"] == "packs/" + name and MD5.fullmatch(old["md5"]), "Seed object differs from full inventory")
            require(old["status"] in ACK or (old["status"] == "STAGED" and old["item"] in ITEMS + OLD_ABSENT_ITEMS),
                    "Old pending reference is outside the reviewed marked/absent namespace")
        keep = old is not None and old["status"] in ACK
        keep_pending = old is not None and old["status"] == "STAGED" and old["item"] in ITEMS
        item = old["item"] if keep or keep_pending else new_item(name)
        require(item in ITEMS, "Retained object is outside the five owned containers")
        placements[name] = item; counts[item] += 1; sizes[item] += obj["size"]
        for profile in obj["profiles"]:
            require(profile in profile_names, "Unknown target profile")
            profile_names[profile] += 1
        if keep or keep_pending:
            retained_locations[name] = {"item": old["item"], "path": old["path"], "size": old["size"], "sha256": old["sha256"], "md5": old["md5"], "status": old["status"]}
            if keep: retained[name] = retained_locations[name]
            else: pending_existing[name] = {**retained_locations[name], "fresh_same_path_public_check_required": True}
        elif old:
            require(old["status"] == "STAGED", "Unknown old object status")
            staged[name] = {"old_item": old["item"], "new_item": item, "path": old["path"],
                            "retargeted": old["item"] != item, "fresh_old_and_new_remote_absence_required": True}
    require(seed_seen == set(seed_objects), "A seed object is absent from the full target")
    require(len(placements) == EXPECTED_OBJECTS and sum(sizes.values()) == EXPECTED_BYTES, "Target total differs")
    require(len(retained) == EXPECTED_ACKS and len(staged) + len(pending_existing) == EXPECTED_STAGED, "Retained or pending totals differ")
    projected = {item: counts[item] + (len(INDEX_KEYS) if item == ITEMS[0] else 0) + 32 for item in ITEMS}
    require(all(n <= 9900 for n in projected.values()), "Full projected item count exceeds 9900")
    layout = {"schema": 1, "kind": "EXISTING_OWNED_FIVE_V1", "source_inventory_sha256": INVENTORY_SHA,
              "target_manifest_sha256": TARGET_SHA, "seed": SEED_SOURCE,
              "old_identity_sha256": hashlib.sha256(canonical(identity)).hexdigest(),
              "owned_items": list(ITEMS), "index_item": ITEMS[0], "index_prefix": INDEX_PREFIX,
              "index_keys": list(INDEX_KEYS), "formula": "Retain ACK and existing-owned STAGED locations; otherwise full SHA256(ASCII name) integer modulo5",
              "placements": placements, "retained_acknowledged": retained, "retained_locations": retained_locations,
              "pending_existing_locations": pending_existing, "staged_pending_absence": staged,
              "file_count_cap": 9900, "reserved_ia_metadata_files_per_item": 32}
    digest = hashlib.sha256(canonical(layout)).hexdigest()
    new_identity = {**identity, "publication_layout": {"schema": 1, "kind": layout["kind"], "layout_sha256": digest,
                                                     "index_item": ITEMS[0], "index_prefix": INDEX_PREFIX}}
    return {"schema": 1, "status": "SOURCE_ONLY_LAYOUT_REVIEW", "migration_authorized": False,
            "publication_authorized": False, "layout_sha256": digest, "layout": layout,
            "new_identity_template": new_identity, "review": {"objects": len(placements), "bytes": sum(sizes.values()),
              "retained_acknowledged": len(retained), "retained_location_references": len(retained_locations),
              "pending_existing_locations": len(pending_existing), "staged_pending_absence": len(staged),
              "pack_counts": counts, "pack_bytes": sizes, "projected_full_counts_including_32_reserved": projected,
              "profile_counts": profile_names}}


def verify_migration_absence(review, identity, seed_objects, snapshots):
    """Validate fresh public snapshots supplied by the reviewed hosted adapter.

    This does not fetch snapshots, create a journal, or authorize any PUT.
    """
    layout = review["layout"]
    require(hashlib.sha256(canonical(layout)).hexdigest() == review["layout_sha256"], "Layout digest differs")
    require(layout["seed"] == SEED_SOURCE and layout["source_inventory_sha256"] == INVENTORY_SHA and
            layout["target_manifest_sha256"] == TARGET_SHA, "Layout source/seed provenance differs")
    require(layout["old_identity_sha256"] == hashlib.sha256(canonical(identity)).hexdigest(), "Old seed identity differs")
    require(tuple(layout["owned_items"]) == ITEMS, "Owned item whitelist differs")
    captured = snapshots.get("captured_at_unix")
    require(type(captured) in (int, float) and 0 <= time.time() - captured <= 120 and
            snapshots.get("origin") == "PUBLIC_IA_METADATA", "Public migration snapshots are absent or stale")
    snapshots = snapshots["items"]
    needed = set(ITEMS) | {r["item"] for r in seed_objects.values() if r["status"] == "STAGED"}
    require(set(snapshots) == needed, "Fresh old/new public snapshot set differs")
    public = {}
    for item, snapshot in snapshots.items():
        if item not in ITEMS:
            require(snapshot is None, "An old retargeted item is no longer absent; review is required")
            public[item] = {}
            continue
        if snapshot is None:
            require(item not in ITEMS, "An owned target container disappeared; never create it")
            public[item] = {}
            continue
        meta = snapshot.get("metadata", {})
        scalar = lambda x: x[0] if isinstance(x, list) and len(x) == 1 else x
        require(not snapshot.get("is_dark") and scalar(meta.get("identifier")) == item and
                scalar(meta.get("elichikasession")) == identity["session"] and
                scalar(meta.get("elichikainventorysha256")) == identity["inventory_sha256"] and
                scalar(meta.get("elichikaaccount")) == identity["account"], "Public container ownership differs")
        files = {}
        for row in snapshot.get("files", []):
            key = row.get("name")
            require(isinstance(key, str) and key not in files, "Duplicate/invalid public file")
            files[key] = row
            if key.startswith(INDEX_PREFIX + "/"):
                raise ValueError("New controlled index namespace already has files")
            if key.startswith("packs/"):
                name = key[6:]; old = seed_objects.get(name)
                require(old and (old["status"] in ACK or name in layout["pending_existing_locations"]) and
                        old["item"] == item and old["path"] == key,
                        "Public pack has no retained owned reference; do not adopt it")
                require(not row.get("private") and not row.get("old_version") and
                        int(row.get("size", -1)) == old["size"] and row.get("md5") == old["md5"],
                        "Public retained pack size/MD5 differs")
        if item in ITEMS:
            require(sum(not key.startswith("packs/") for key in files) <= 32,
                    "Existing non-pack files exceed the reserved metadata allowance")
        public[item] = files
    for name, pending in layout["staged_pending_absence"].items():
        require(pending["path"] not in public[pending["old_item"]] and pending["path"] not in public[pending["new_item"]],
                "A STAGED old/new path is visible; retargeting is not permitted")
    return {"status": "ABSENCE_AND_OWNERSHIP_VALIDATED_ONLY", "retained_ack_count": len(layout["retained_acknowledged"]),
            "retained_reference_count": len(layout["retained_locations"]),
            "pending_existing_count": len(layout["pending_existing_locations"]),
            "pending_staged_count": len(layout["staged_pending_absence"]), "account_writes": 0,
            "still_requires": "Root-reviewed new-layout journal and a single existing-container PUT before any full run"}


def diagnostic_draft(review, seed_objects):
    """A non-executable request plan; source and ownership checks remain required."""
    name = "00jst0"; record = seed_objects[name]; layout = review["layout"]
    require(record["status"] == "STAGED" and record["size"] == 9688 and
            record["md5"] == "59d3c0f357b61893c19d46c119b76de2" and
            record["sha256"] == "97455d0c890c0f9a3f6540d1d5236ad2a7287b40e0d3b0d8b37a3b65b208c137" and
            layout["placements"][name] == ITEMS[4], "Diagnostic object/destination differs")
    return {"schema": 1, "status": "SOURCE_ONLY_REVIEW_REQUIRED", "authorized": False,
            "name": name, "item": ITEMS[4], "path": record["path"], "size": record["size"],
            "md5": record["md5"], "sha256": record["sha256"], "layout_sha256": review["layout_sha256"],
            "max_put_requests": 1, "workers": 1, "max_attempts": 1, "index_publication": False,
            "auto_make_bucket": False, "metadata_mutation_headers": False,
            "requires_before_put": ["Pinned old seed bytes and complete identity", "Explicit new layout journal identity",
                "Fresh marked existing b04 metadata and packs/00jst0 absence", "Fresh old b08 item/path absence",
                "Full original source, size, MD5 and SHA256 staging checks"],
            "stop_on": "Any refusal/spam/unknown response; no automatic retry or prefix/account rotation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-zip", required=True)
    parser.add_argument("--seed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    identity, records = load_seed(args.seed_dir)
    with zipfile.ZipFile(args.inventory_zip) as archive:
        member = archive.getinfo("inventory.json")
        require(member.file_size == 27837263, "Unexpected pinned inventory size")
        with archive.open(member) as source:
            reader, headers = JsonStream(source), {}
            result = build_plan(reader.objects(headers), identity, records)
            require(reader.sha.hexdigest() == INVENTORY_SHA, "Full source inventory SHA differs")
            require(headers.get("status") == "COMPLETE" and headers.get("target_manifest_sha256") == TARGET_SHA,
                    "Full source target status differs")
    Path(args.output).write_bytes(canonical(result))
    Path(args.output).with_suffix(".diagnostic-draft.json").write_bytes(canonical(diagnostic_draft(result, records)))
    print(json.dumps({"layout_sha256": result["layout_sha256"], **result["review"]}, sort_keys=True))


if __name__ == "__main__":
    main()
