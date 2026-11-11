"""Owned canonical archives for shared-board clones, never inferred from names.

Execution resources follow each clone's private model graph. Authoring originals,
recipes, goldens and the original donor proof remain byte-for-byte canonical.
"""
from contextlib import ExitStack, closing
import copy
import hashlib
from pathlib import Path
import uuid


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _shared(manifest):
    from costume_scene_installer import _codec, _shared_capabilities_valid
    codec = _codec()
    if not _shared_capabilities_valid(manifest):
        raise ValueError("Cloning scene-specific HOME/MV costumes requires re-exporting the source as shared-board v2.")
    return codec


def _catalog_name(conn):
    return Path(next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")).name


def canonical_clone_candidates(*, root="."):
    """Cheap listing index only; selecting a source still verifies everything."""
    from costume_management import _read_receipt, ManagementError
    from costume_scene_installer import _shared_capabilities_valid
    root = Path(root).resolve()
    result = set()
    for path in (root / ".costume-management/receipts").glob("*.json"):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                continue
            receipt = _read_receipt(root, path.stem)
            source = receipt.get("source")
            scene = source.get("canonical_scene") if isinstance(source, dict) else None
            if receipt.get("kind") != "clone" or receipt.get("state") != "committed" or not isinstance(scene, dict):
                continue
            manifest = scene.get("manifest", {})
            if not isinstance(manifest, dict):
                continue
            archive = Path(scene["archive_path"])
            if (scene.get("version") == 2 and _shared_capabilities_valid(manifest) and manifest.get("character_id") == 209 and
                    type(manifest.get("target_member_id")) is int and
                    manifest.get("default_variant") in ("primary", "unmasked") and
                    archive.parent == root / ".costume-management/sources" and
                    not archive.is_symlink() and archive.is_file()):
                result.update(receipt["suit_ids"])
        except (OSError, ValueError, KeyError, TypeError, ManagementError):
            continue
    return result


class CanonicalCloneArchive:
    def __init__(self, raw, source):
        self.raw, self.source = raw, source
        self.path = Path(source["archive_path"])
        self.created = False

    def descriptor(self):
        return dict(path=str(self.path), sha256=_sha(self.raw), size=len(self.raw))

    def publish(self):
        from costume_scene_installer import _safe_file
        import os
        _safe_file(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("xb") as stream:
            self.created = True
            stream.write(self.raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def rollback(self, retain=False):
        if self.created and not retain:
            self.path.unlink(missing_ok=True)


def prepare_canonical_clone(source, assets, target_member_id, use_no_mask, *, root="."):
    """Rebind ONLY execution refs to the prepared private native payloads."""
    from costume_scene_installer import read_package
    decoded = read_package(source["archive_path"], source["sha256"])
    manifest, files = copy.deepcopy(decoded["manifest"]), dict(decoded["files"])
    codec = _shared(manifest)
    if target_member_id == 209 and use_no_mask:
        raise ValueError("A shared-board Rina costume must use its board default; choose the board option.")
    if set(manifest["platforms"]) != {"android", "ios"}:
        raise ValueError("Cloning a shared-board costume requires both native Android and iOS families.")
    canonical = source["canonical_model_paths"]
    if set(canonical) != {"gl", "jp"} or any(set(f) != {"primary", "unmasked"} for f in canonical.values()):
        raise ValueError("The canonical source has no complete physical board/bare authority.")
    paths = {region: {variant: assets.models[region, old] for variant, old in family.items()}
             for region, family in canonical.items()}
    if paths["gl"] != paths["jp"]:
        raise ValueError("Canonical clone logical roots disagree across regions.")
    # Preserve canonical authoring companions. Only the execution graph is
    # replaced; reopening must never pair an original body with a private face.
    def refs(value):
        if isinstance(value, dict):
            if {"member", "sha256", "bytes"} <= set(value):
                yield value["member"]
            else:
                for child in value.values():
                    yield from refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from refs(child)
    protected = set(refs({key: value for key, value in manifest.items()
                          if key not in ("platforms", "execution_model_graph")}))
    root_members = set(refs(manifest["platforms"]))
    if protected.intersection(root_members):
        raise ValueError("Canonical authoring resources must be separate from execution roots.")
    previous_graph = manifest.pop("execution_model_graph", {})
    for member in set(refs(previous_graph)) - protected - root_members:
        files.pop(member, None)
    by_platform = {"android": [], "ios": []}
    graph_paths = {region: {} for region in canonical}
    from costume_clone_assets import _rows
    for conn, records, _, _ in assets.catalogs:
        name = _catalog_name(conn)
        region = Path(next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")).parent.name
        platform = "android" if name.startswith("asset_a_") else "ios"
        raw_by_old = {old: assets.plain_packs[pack] for old, _, pack, _ in records}
        ids = {old: "m" + _sha(raw)[:24] for old, raw in raw_by_old.items()}
        if len(set(ids.values())) != len(ids):
            raise ValueError("Canonical clone model graph contains ambiguous physical aliases.")
        roles = dict(navi_board=ids[canonical[region]["primary"]],
                     mv_board=ids[canonical[region]["primary"]],
                     mv_unmasked=ids[canonical[region]["unmasked"]])
        root_names = {roles[role]: manifest["platforms"][platform][role]["member"]
                      for role in ("mv_board", "mv_unmasked")}
        nodes, payloads = {}, {}
        for old, raw in raw_by_old.items():
            node_id = ids[old]
            member = root_names.get(node_id, "execution/" + platform + "/" + node_id + ".unity")
            if member in protected:
                raise ValueError("Private execution resources cannot replace canonical authoring resources.")
            models, shaders = [], []
            for edge in _rows(conn, "member_model_dependency", "asset_path", old):
                target = edge["dependency"]
                if target in ids:
                    models.append(ids[target])
                elif len(_rows(conn, "shader", "asset_path", target)) == 1:
                    shaders.append(target)
                else:
                    raise ValueError("Canonical clone graph has an unresolved dependency.")
            nodes[node_id] = dict(resource=codec.reference(member, raw, platform),
                model_dependencies=sorted(models), shared_shader_dependencies=sorted(shaders))
            payloads[member] = raw
        graph = dict(nodes=nodes, role_bindings=roles)
        by_platform[platform].append((graph, payloads))
        mapping = {ids[old]: new for old, new, _, _ in records}
        if graph_paths[region].setdefault(platform, mapping) != mapping:
            raise ValueError("Canonical clone logical graph differs across locale catalogs.")
    manifest["execution_model_graph"] = {}
    for platform, catalogs in by_platform.items():
        if not catalogs or any(graph != catalogs[0][0] for graph, _ in catalogs[1:]):
            raise ValueError("Canonical clone native model payloads or edges differ across regional catalogs: " + platform)
        graph, payloads = catalogs[0]
        manifest["execution_model_graph"][platform] = graph
        files.update(payloads)
        for role, node_id in graph["role_bindings"].items():
            manifest["platforms"][platform][role] = copy.deepcopy(graph["nodes"][node_id]["resource"])
    manifest.update(target_member_id=target_member_id,
                    default_variant="unmasked" if use_no_mask else "primary")
    raw = codec.encode_package(manifest, files)
    archive = Path(root).resolve() / ".costume-management/sources" / ("clone-" + uuid.uuid4().hex + ".zip")
    selected = paths["gl"][manifest["default_variant"]]
    runtime = dict(navi_board=selected, mv_board=selected, mv_unmasked=paths["gl"]["unmasked"])
    metadata = dict(version=2, archive_path=str(archive), package_sha256=_sha(raw), manifest=manifest,
                    canonical_model_paths=paths, runtime_model_paths=runtime,
                    graph_model_paths=graph_paths)
    return CanonicalCloneArchive(raw, metadata)


def resolve_canonical_clone_source(suit_id, *, root="."):
    """Verify owned archive, installed rows/files and exact execution routing."""
    from costume_management import _read_receipt, _connect, _selected, _owned_file, _verify_file
    from costume_scene_installer import _safe_file, read_package
    from costume_clone_assets import REQUIRED_ASSET_CATALOGS
    root = Path(root).resolve()
    matches = []
    for path in (root / ".costume-management/receipts").glob("*.json"):
        _safe_file(path)
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("A canonical clone receipt exceeds its size limit.")
        receipt = _read_receipt(root, path.stem)
        if receipt.get("kind") == "clone" and suit_id in receipt.get("suit_ids", []):
            matches.append(receipt)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("This clone has ambiguous installation provenance.")
    receipt = matches[0]
    source = receipt.get("source", {})
    if not isinstance(source, dict):
        raise ValueError("This clone's source provenance is invalid.")
    if "canonical_scene" not in source:
        return None
    scene = source["canonical_scene"]
    if receipt.get("state") != "committed" or type(scene) is not dict or scene.get("version") != 2:
        raise ValueError("This canonical clone has incomplete installation provenance.")
    # Keep one validated read-only connection per DB during this single
    # verification, including its later route/graph checks. Queries, native
    # files and archive hashes are all rechecked on the next call.
    with ExitStack() as stack:
        databases = {}

        def database(relative):
            if relative not in databases:
                databases[relative] = stack.enter_context(closing(_connect(root, relative)))
            return databases[relative]

        for item in receipt["owned_rows"]:
            if _selected(database(item["db"]), item["table"], item["key"]) != [item["row"]]:
                raise ValueError("The canonical clone's installed database rows changed.")
        owned_files = [_owned_file(root, spec) for spec in receipt["owned_files"]]
        for spec in owned_files:
            _verify_file(spec)
        archive = _safe_file(scene["archive_path"])
        if archive.parent != root / ".costume-management/sources" or not any(
                spec["path"] == str(archive) and spec["sha256"] == scene["package_sha256"] for spec in owned_files):
            raise ValueError("The canonical clone does not own its preserved archive.")
        decoded = read_package(archive, scene["package_sha256"])
        manifest = decoded["manifest"]
        _shared(manifest)
        if manifest != scene["manifest"]:
            raise ValueError("The canonical clone's preserved metadata changed.")
        target, variant = manifest["target_member_id"], manifest["default_variant"]
        if target != source["target_member_id"]:
            raise ValueError("The canonical clone owner disagrees with its archive.")
        canonical, runtime = scene["canonical_model_paths"], scene["runtime_model_paths"]
        if set(canonical) != {"gl", "jp"} or canonical["gl"] != canonical["jp"] or any(
                set(f) != {"primary", "unmasked"} or len(set(f.values())) != 2 for f in canonical.values()):
            raise ValueError("The canonical clone's physical model authority is invalid.")
        selected = canonical["gl"][variant]
        if runtime != dict(navi_board=selected, mv_board=selected, mv_unmasked=canonical["gl"]["unmasked"]):
            raise ValueError("The canonical clone's selected model routes are invalid.")
        import llas_asset_extractor as extractor
        packs = {Path(item["path"]).name: item for item in owned_files if item["role"] == "pack"}
        for region, catalogs in REQUIRED_ASSET_CATALOGS.items():
            db = database("assets/db/" + region + "/masterdata.db")
            row = db.execute("SELECT member_m_id,model_asset_path FROM m_suit WHERE id=?", (suit_id,)).fetchone()
            views = {r[0]: r[1] for r in db.execute("SELECT view_status,model_asset_path FROM m_suit_view WHERE suit_master_id=?", (suit_id,))}
            if row is None or tuple(row) != (target, selected) or views != {1: selected, 2: canonical[region]["unmasked"]}:
                raise ValueError("The canonical clone's installed HOME/MV routes changed.")
            for catalog in catalogs:
                platform = "android" if catalog.startswith("asset_a_") else "ios"
                graph = manifest["execution_model_graph"][platform]
                bindings = scene["graph_model_paths"][region][platform]
                if (set(bindings) != set(graph["nodes"]) or len(set(bindings.values())) != len(bindings) or
                        bindings[graph["role_bindings"]["mv_board"]] != canonical[region]["primary"] or
                        bindings[graph["role_bindings"]["mv_unmasked"]] != canonical[region]["unmasked"]):
                    raise ValueError("The canonical clone's complete execution graph authority is invalid.")
                relative = "assets/db/" + region + "/" + catalog
                db = database(relative)
                for node_id, model in bindings.items():
                    node = graph["nodes"][node_id]
                    ref = node["resource"]
                    owned = [item for item in receipt["owned_rows"] if item["db"] == relative and
                             item["table"] == "member_model" and item["row"].get("asset_path") == model]
                    rows = db.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (model,)).fetchall()
                    if len(owned) != 1 or len(rows) != 1 or rows[0][0] not in packs:
                        raise ValueError("The canonical clone execution resource is not owned.")
                    pack, head, size, key1, key2 = rows[0]
                    raw = bytearray(Path(packs[pack]["path"]).read_bytes()[int(head):int(head) + int(size)])
                    extractor.decrypt_section(raw, extractor.FIXED_KEY0, int(key1), int(key2))
                    if bytes(raw) != decoded["files"][ref["member"]]:
                        raise ValueError("The canonical archive does not match its installed native execution resource.")
                    edges = sorted(row[0] for row in db.execute(
                        "SELECT dependency FROM member_model_dependency WHERE asset_path=?", (model,)))
                    expected = sorted([bindings[dep] for dep in node["model_dependencies"]] + node["shared_shader_dependencies"])
                    if edges != expected:
                        raise ValueError("The canonical clone's installed model graph edges changed.")
                    if any(len(db.execute("SELECT asset_path FROM shader WHERE asset_path=?", (key,)).fetchall()) != 1
                           for key in node["shared_shader_dependencies"]):
                        raise ValueError("The canonical clone's shared shader authority is missing.")
        return dict(archive_path=str(archive), sha256=decoded["sha256"], install_id=receipt["install_id"],
                    suit_id=suit_id, runtime_model_paths=runtime, canonical_model_paths=canonical,
                    target_member_id=target, default_variant=variant, manifest_version=2,
                    main_model_path=selected)
