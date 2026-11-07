"""Independent model assets for costume clones.

A new suit id does not give the client a new model: its loaders/cache use the
model asset path. Each clone therefore needs its own model path and Unity bundle
identity. Model dependencies are private too, since face/animation bundles can
contain mutable materials. Shader dependencies remain shared.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid


_CAB = re.compile(r"^CAB-[0-9a-f]{32}$", re.IGNORECASE)
# config.Platforms/GlLanguages/JpLanguages and clientdb.updateClientDb require
# these eight catalogs. Additional installed locales are cloned as well.
REQUIRED_ASSET_CATALOGS = {
    "gl": tuple(f"asset_{platform}_{language}.db" for platform in ("a", "i")
                for language in ("en", "ko", "zh")),
    "jp": ("asset_a_ja.db", "asset_i_ja.db"),
}


def _cleanup_connections(connections, method):
    """Attempt every cleanup without replacing the operation's original error."""
    for conn in connections:
        if conn is not None:
            try:
                getattr(conn, method)()
            except Exception:
                pass


def _bundle(data):
    import UnityPy
    if not data.startswith(b"UnityFS\0"):
        raise ValueError("costume model is not a UnityFS bundle")
    env = UnityPy.load(data)
    files = list(env.files.values())
    if len(files) != 1 or type(files[0]).__name__ != "BundleFile":
        raise ValueError("costume model must contain one UnityFS bundle")
    bundle = files[0]
    serialized = [f for f in bundle.files.values() if hasattr(f, "objects")]
    if not serialized or any(not _CAB.fullmatch(f.name) for f in serialized):
        raise ValueError("costume model has an unsupported serialized-file identity")
    return env, bundle, serialized


def _cab_names(data):
    _, _, files = _bundle(data)
    return [f.name for f in files]


def _cab_mapping(names, namespace):
    return {name.lower(): "CAB-" + hashlib.sha256(
        (namespace + ":" + name.lower()).encode()).hexdigest()[:32] for name in names}


def _runtime_name(namespace, serialized_name, original_name):
    return "clone_" + hashlib.sha256((namespace + ":" + serialized_name + ":" +
        str(original_name)).encode()).hexdigest() + ".unity3d"


def _runtime_names(data, namespace):
    _, _, files = _bundle(data)
    result = {}
    for sf in files:
        for obj in sf.objects.values():
            if obj.type.name == "AssetBundle":
                tree = obj.read_typetree()
                if tree.get("m_AssetBundleName"):
                    original = tree["m_AssetBundleName"]
                    result[original] = _runtime_name(namespace, sf.name, original)
    return result


def isolate_bundle(data, namespace, _identities=None, _bundle_names=None):
    """Copy a model without sharing its serialized assets or streamed resources.

    Only CAB identities and AssetBundle runtime names change. Object/path ids,
    prefab load paths, meshes, materials and animation data are preserved. CABs
    have a fixed width, so resource paths can be replaced without deserializing
    unknown MonoBehaviours or changing any binary field sizes/offsets.
    """
    _, bundle, serialized = _bundle(data)
    identities = dict(_identities or {})
    identities.update(_cab_mapping([f.name for f in serialized], namespace))

    def rename(value):
        # Archive paths can use lower-case CAB names while the directory uses
        # upper-case CAB. Do not rename external shared dependencies.
        for old, new in identities.items():
            value = re.sub(re.escape(old), lambda match: (
                new.lower() if match.group().startswith("cab-") else new), value,
                flags=re.IGNORECASE)
        return value

    found_bundle = False
    for sf in serialized:
        for external in sf.externals:
            external.path = rename(external.path)
        for obj in sf.objects.values():
            raw = obj.get_raw_data()
            updated = raw
            for old, new in identities.items():
                updated = re.sub(re.escape(old.encode()), lambda match: (
                    new.lower().encode() if match.group().startswith(b"cab-") else new.encode()),
                    updated, flags=re.IGNORECASE)
            if updated != raw:
                obj.set_raw_data(updated)
            if obj.type.name == "AssetBundle":
                tree = obj.read_typetree()
                for field in ("m_Name", "m_AssetBundleName"):
                    if field in tree:
                        tree[field] = _runtime_name(namespace, sf.name, tree[field])
                if _bundle_names:
                    tree["m_Dependencies"] = [_bundle_names.get(name, name)
                                               for name in tree.get("m_Dependencies", [])]
                obj.save_typetree(tree)
                found_bundle = True
        sf.name = rename(sf.name)
        sf.mark_changed()
    if not found_bundle:
        raise ValueError("costume model has no AssetBundle metadata")
    bundle.files = {rename(name): value for name, value in bundle.files.items()}
    result = bundle.save(packer="lz4")
    # Parse again before registering anything; malformed outputs must never
    # become downloadable models. No texture decoding/recompression is needed.
    _, _, copied = _bundle(result)
    if sorted(len(f.objects) for f in copied) != sorted(len(f.objects) for f in serialized):
        raise ValueError("costume bundle object count changed while isolating it")
    return result


def _columns(conn, table):
    return [row[1] for row in conn.execute('PRAGMA table_info("' + table + '")')]


def _rows(conn, table, column, value):
    columns = _columns(conn, table)
    if not columns:
        return []
    return [dict(zip(columns, row)) for row in conn.execute(
        'SELECT * FROM "' + table + '" WHERE "' + column + '"=?', (value,))]


def _insert(conn, table, row):
    columns = list(row)
    conn.execute('INSERT INTO "' + table + '" (' + ','.join('"' + c + '"' for c in columns)
                 + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                 tuple(row[c] for c in columns))


def _model_closure(conn, roots, catalog):
    """Return dependency-first models; shared shader edges keep their identity."""
    ordered, states = [], {}

    def visit(model, depth=0):
        if states.get(model) == "visiting":
            raise ValueError("cyclic model dependency in " + str(catalog) + ": " + model)
        if states.get(model) == "done":
            return
        if depth > 256:
            raise ValueError("model dependency graph is too deep in " + str(catalog))
        if len(_rows(conn, "member_model", "asset_path", model)) != 1:
            raise ValueError("model " + model + " is missing or ambiguous in " + str(catalog))
        states[model] = "visiting"
        for row in sorted(_rows(conn, "member_model_dependency", "asset_path", model),
                          key=lambda item: item["dependency"]):
            dependency = row["dependency"]
            models = _rows(conn, "member_model", "asset_path", dependency)
            shaders = _rows(conn, "shader", "asset_path", dependency)
            if len(models) + len(shaders) != 1:
                raise ValueError("missing or ambiguous model dependency in " + str(catalog) +
                                 ": " + model + " -> " + str(dependency))
            if models:
                visit(dependency, depth + 1)
        states[model] = "done"
        ordered.append(model)

    for root in sorted(roots):
        visit(root)
    return ordered


def _pack_directory():
    # Go's localPath/getPackUrl consult the configured directory even when
    # cdn_cache is false. Writing directly there also avoids static-to-cache
    # migration; the desktop costume installer uses that valid legacy route.
    android = hasattr(sys, "getandroidapilevel") or "com.termux" in os.environ.get("PREFIX", "")
    android_default = "~/storage/downloads/sukusta/packs"
    default = android_default if android else "static"
    try:
        with open("config.json", encoding="utf-8") as f:
            configured = json.load(f).get("cdn_cache_dir")
        if configured == android_default and not android:
            # config/runtime.go migrates this old automatic Android default to
            # an empty value on desktop. Read the same effective setting even
            # when the server has not yet rewritten config.json.
            default = "static"
        elif isinstance(configured, str) and configured.strip():
            default = configured
    except (OSError, ValueError):
        pass
    return Path(os.path.expanduser(default))


class CloneAssets:
    def __init__(self):
        self.models = {}
        self.connections = []
        self.catalogs = []
        self.packs = {}
        self.created = []
        self.commit_started = False
        self.destination = _pack_directory()

    def publish(self):
        self.destination.mkdir(parents=True, exist_ok=True)
        for name, data in self.packs.items():
            path = self.destination / name
            # Fresh content-addressed names never replace a source pack.
            try:
                with path.open("xb") as f:
                    self.created.append(path)
                    f.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError("clone pack name collides with an existing file")

    def register(self):
        for conn, records, source_ids, new_id in self.catalogs:
            mapping = {}
            for source_id in source_ids:
                for row in _rows(conn, "m_asset_package_mapping", "package_key", "suit:" + str(source_id)):
                    row["package_key"] = "suit:" + str(new_id)
                    mapping.setdefault(row["pack_name"], row)
            for old_path, new_path, pack, size in records:
                _insert(conn, "member_model", dict(asset_path=new_path, pack_name=pack,
                    head="0", size=size, key1="0", key2="0"))
                _insert(conn, "m_asset_pack", dict(pack_name=pack, auto_delete="0"))
                for row in _rows(conn, "member_model_dependency", "asset_path", old_path):
                    row["asset_path"] = new_path
                    row["dependency"] = dict((a, b) for a, b, _, _ in records).get(row["dependency"], row["dependency"])
                    _insert(conn, "member_model_dependency", row)
                mapping[pack] = dict(package_key="suit:" + str(new_id), pack_name=pack,
                    file_size=size, metapack_name=None, metapack_offset="0", category="3")
            # Attached colour suits can ask the client to load their private
            # base suit first. Both package keys must describe the same closure.
            target_ids = set(source_ids.values()) if isinstance(source_ids, dict) else {new_id}
            for target_id in sorted(target_ids):
                package_key = "suit:" + str(target_id)
                for row in mapping.values():
                    _insert(conn, "m_asset_package_mapping", dict(row, package_key=package_key))
                _insert(conn, "m_asset_package", dict(package_key=package_key,
                    version=hashlib.sha1(uuid.uuid4().bytes).hexdigest(), pack_num=str(len(mapping))))

    def commit(self):
        self.commit_started = True
        for conn in self.connections:
            conn.commit()

    def rollback(self):
        _cleanup_connections(self.connections, "rollback")
        if not self.commit_started:
            for path in self.created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def close(self):
        _cleanup_connections(self.connections, "close")


def prepare_clone_assets(region_models, new_id, source_ids, log=print):
    """Resolve/validate native bundles before publishing clone packs or mutating DBs.

    Source pack resolution may populate the local download cache during this
    preflight. Existing assets and all database rows remain unchanged.
    """
    import llas_asset_extractor as extractor
    plan = CloneAssets()
    namespace = uuid.uuid4().hex
    try:
        missing = [Path("assets/db", region, name)
                   for region in region_models
                   for name in REQUIRED_ASSET_CATALOGS[region]
                   if not Path("assets/db", region, name).is_file()]
        if missing:
            raise FileNotFoundError("missing required clone asset catalogs: " +
                                    ", ".join(str(path) for path in missing))
        catalogs = []
        for region, models in region_models.items():
            paths = sorted(Path("assets/db", region).glob("asset_[ai]_*.db"))
            if models and not paths:
                raise FileNotFoundError("missing model asset catalogs for " + region)
            for path in paths:
                conn = sqlite3.connect(path)
                plan.connections.append(conn)
                for table, required in (
                    ("member_model", {"asset_path", "pack_name", "head", "size", "key1", "key2"}),
                    ("member_model_dependency", {"asset_path", "dependency"}),
                    ("shader", {"asset_path"}),
                    ("m_asset_pack", {"pack_name", "auto_delete"}),
                    ("m_asset_package", {"package_key", "version", "pack_num"}),
                    ("m_asset_package_mapping", {"package_key", "pack_name", "file_size", "metapack_name", "metapack_offset", "category"})):
                    if not required.issubset(_columns(conn, table)):
                        raise ValueError("invalid clone asset catalog " + str(path) + ": " + table)
                catalogs.append((region, path, conn, _model_closure(conn, models, path)))
        # Logical model identities agree across the platform/language catalogs.
        for region in region_models:
            models = {model for item_region, _, _, closure in catalogs if item_region == region
                      for model in closure}
            for old in sorted(models):
                while True:
                    candidate = uuid.uuid4().hex[:8]
                    if candidate not in plan.models.values() and all(not conn.execute(
                        "SELECT 1 FROM member_model WHERE asset_path=?", (candidate,)).fetchone()
                        for conn in plan.connections):
                        break
                plan.models[region, old] = candidate

        roots = extractor.build_pack_roots(os.getcwd(), [str(plan.destination)],
            [p for p, status in extractor.detect_game_candidates() if status == "found"])
        cache = {}
        for region, path, conn, models in catalogs:
            resolver = extractor.PackResolver(roots, str(plan.destination), extractor.DEFAULT_CDN_BASE, conn)
            originals = {}
            for old in models:
                row = conn.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (old,)).fetchone()
                if not row:
                    raise ValueError("model " + old + " is missing from " + str(path))
                pack, head, size, key1, key2 = row
                descriptor = (pack, int(head), int(size), int(key1), int(key2))
                if descriptor not in cache:
                    source = resolver.resolve(pack)
                    if source is None:
                        raise FileNotFoundError("source model pack is unavailable: " + str(pack))
                    if int(head) < 0 or int(size) <= 0:
                        raise ValueError("invalid source model section: " + old)
                    with open(source, "rb") as f:
                        f.seek(int(head))
                        data = bytearray(f.read(int(size)))
                    if len(data) != int(size):
                        raise ValueError("truncated source model pack: " + str(pack))
                    extractor.decrypt_section(data, extractor.FIXED_KEY0, int(key1), int(key2))
                    _cab_names(bytes(data))
                    cache[descriptor] = bytes(data)
                originals[old] = cache[descriptor]
            identities = {}
            ambiguous_cabs = set()
            bundle_names = {}
            ambiguous_names = set()
            for old, data in originals.items():
                model_namespace = namespace + ":" + region + ":" + old
                for original, renamed in _cab_mapping(_cab_names(data), model_namespace).items():
                    if original in identities and identities[original] != renamed:
                        ambiguous_cabs.add(original)
                    identities[original] = renamed
                for original, renamed in _runtime_names(data, model_namespace).items():
                    if original in bundle_names and bundle_names[original] != renamed:
                        ambiguous_names.add(original)
                    bundle_names[original] = renamed
            for original in ambiguous_names:
                del bundle_names[original]
            for original in ambiguous_cabs:
                del identities[original]
            # Generic duplicate bundle names can be harmless in standalone
            # inputs. A dependency on such a name cannot be resolved safely.
            if ambiguous_names or ambiguous_cabs:
                for data in originals.values():
                    _, _, files = _bundle(data)
                    for sf in files:
                        if any(any(cab in external.path.lower() for cab in ambiguous_cabs)
                               for external in sf.externals):
                            raise ValueError("ambiguous private model CAB dependency")
                        for obj in sf.objects.values():
                            if obj.type.name == "AssetBundle" and ambiguous_names.intersection(
                                    obj.read_typetree().get("m_Dependencies", [])):
                                raise ValueError("ambiguous private model bundle dependency")
            records = []
            for old, data in originals.items():
                cloned = bytearray(isolate_bundle(data, namespace + ":" + region + ":" + old,
                                                  identities, bundle_names))
                extractor.decrypt_section(cloned, extractor.FIXED_KEY0, 0, 0)
                pack = "cc" + hashlib.sha256(cloned).hexdigest()[:30]
                plan.packs[pack] = bytes(cloned)
                records.append((old, plan.models[region, old], pack, len(cloned)))
            plan.catalogs.append((conn, records, source_ids[region], new_id))
            log("prepared independent costume models: " + str(path))
        return plan
    except Exception:
        plan.rollback()
        plan.close()
        raise
