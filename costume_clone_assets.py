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


# Backward-compatible private aliases; all asset tools share this primitive.
from sifas_asset_crypto import (_CRYPTO_BLOCK_SIZE, _CRYPTO_FAST_MIN_SIZE,
                                _lcg_coefficients, crypt_section as _crypt_section)


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


def _bundle_metadata(data):
    """Inspect immutable source metadata once, never retaining mutable UnityPy files.

    A native model commonly appears in three GL locale catalogs. Keeping just
    the names/dependencies lets each catalog validate its own graph without
    reparsing the same model. The isolator always receives original bytes and
    creates its own mutable environment.
    """
    _, _, files = _bundle(data)
    cabs, runtime, externals, dependencies = [], [], [], []
    for sf in files:
        cabs.append(sf.name)
        externals.extend(external.path for external in sf.externals)
        for obj in sf.objects.values():
            if obj.type.name == "AssetBundle":
                tree = obj.read_typetree()
                if tree.get("m_AssetBundleName"):
                    runtime.append((sf.name, tree["m_AssetBundleName"]))
                dependencies.extend(tree.get("m_Dependencies", []))
    return tuple(cabs), tuple(runtime), tuple(externals), tuple(dependencies)


def isolate_bundle(data, namespace, _identities=None, _bundle_names=None):
    """Use the same identity-only isolation as scene exports on both platforms."""
    try:
        from webtools.core.bundle_identity import isolate_bundle as shared_isolate
    except ModuleNotFoundError as exc:
        if exc.name not in ("webtools", "webtools.core", "webtools.core.bundle_identity"):
            raise
        # Source checkout CLI: packaged apps already put webtools on sys.path.
        source_tools = Path(__file__).resolve().parent / "modtools"
        if not (source_tools / "webtools/core/bundle_identity.py").is_file():
            raise RuntimeError("Initialize the pinned modtools submodule before cloning") from exc
        sys.path.insert(0, str(source_tools))
        from webtools.core.bundle_identity import isolate_bundle as shared_isolate
    return shared_isolate(data, namespace, _identities=_identities,
                          _bundle_names=_bundle_names)


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
        self.plain_packs = {}
        self.copied_source_packs = {}
        self.required_source_packs = {}
        self.retained_texture_packs = {}
        self.created = []
        self.commit_started = False
        self.destination = _pack_directory()
        self._registration_rows = None

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

    def registration_rows(self):
        """Freeze exact planned inserts once, including package versions."""
        if self._registration_rows is not None:
            return self._registration_rows
        rows = []
        for conn, records, source_ids, new_id in self.catalogs:
            mapping = {}
            for source_id in source_ids:
                for row in _rows(conn, "m_asset_package_mapping", "package_key", "suit:" + str(source_id)):
                    row["package_key"] = "suit:" + str(new_id)
                    mapping.setdefault(row["pack_name"], row)
            # Canonical descendants own the copied models. Keep old packs only
            # when a shared shader or retained thumbnail still requires them.
            for pack in self.copied_source_packs.get(conn, set()) - self.required_source_packs.get(conn, set()):
                mapping.pop(pack, None)
            # Managed Face clones retain a shared thumbnail descriptor rather
            # than copying its pixels. Give their own suit download package
            # that pack too: the donor's owned main-package mapping can be
            # removed independently when its costume is deleted.
            for pack in self.retained_texture_packs.get(conn, ()):
                candidates = _rows(conn, 'm_asset_package_mapping', 'pack_name', pack)
                identities = {(row['file_size'], row.get('metapack_name'), row.get('metapack_offset', 0))
                              for row in candidates}
                if len(identities) != 1:
                    raise ValueError('retained thumbnail has missing or conflicting download mappings')
                mapping.setdefault(pack, dict(candidates[0], package_key='suit:' + str(new_id)))
            for old_path, new_path, pack, size in records:
                rows.append((conn, "member_model", dict(asset_path=new_path, pack_name=pack,
                    head="0", size=size, key1="0", key2="0")))
                rows.append((conn, "m_asset_pack", dict(pack_name=pack, auto_delete="0")))
                for row in _rows(conn, "member_model_dependency", "asset_path", old_path):
                    row["asset_path"] = new_path
                    row["dependency"] = dict((a, b) for a, b, _, _ in records).get(row["dependency"], row["dependency"])
                    rows.append((conn, "member_model_dependency", row))
                mapping[pack] = dict(package_key="suit:" + str(new_id), pack_name=pack,
                    file_size=size, metapack_name=None, metapack_offset="0", category="3")
            # Attached colour suits can ask the client to load their private
            # base suit first. Both package keys must describe the same closure.
            target_ids = set(source_ids.values()) if isinstance(source_ids, dict) else {new_id}
            for target_id in sorted(target_ids):
                package_key = "suit:" + str(target_id)
                for row in mapping.values():
                    rows.append((conn, "m_asset_package_mapping", dict(row, package_key=package_key)))
                rows.append((conn, "m_asset_package", dict(package_key=package_key,
                    version=hashlib.sha1(uuid.uuid4().bytes).hexdigest(), pack_num=str(len(mapping)))))
        self._registration_rows = rows
        return rows

    def register(self):
        for conn, table, row in self.registration_rows():
            _insert(conn, table, row)

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


def prepare_clone_assets(region_models, new_id, source_ids, log=print, *, shared_roots=None,
                         retained_textures=None, private_source=False):
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
                catalogs.append((region, path, conn, models))
        # A native costume mod can legitimately be Android-only or iOS-only.
        # Its master rows are shared, while the other native catalogs have no
        # root models at all. Skip only a WHOLE absent platform; a missing
        # locale, one missing Rina variant, or a broken dependency still fails
        # before publishing any clone files or database rows.
        native_catalogs = {}
        for region, path, conn, roots in catalogs:
            counts = [len(_rows(conn, 'member_model', 'asset_path', model)) for model in roots]
            if any(counts) and not all(count == 1 for count in counts):
                _model_closure(conn, roots, path)  # retain its precise error
            native = 'ios' if path.name.startswith('asset_i_') else 'android'
            native_catalogs.setdefault(native, []).append((region, path, conn, roots, bool(counts) and all(count == 1 for count in counts)))
        catalogs = []
        for native, group in native_catalogs.items():
            if not any(row[4] for row in group):
                log('source costume has no ' + native + ' models; native clone catalogs skipped')
                continue
            for region, path, conn, roots, present in group:
                if not present:
                    _model_closure(conn, roots, path)
                catalogs.append((region, path, conn, _model_closure(conn, roots, path)))
        if not catalogs:
            raise ValueError('source costume has no models in any native asset catalog')
        # Logical model identities agree across the platform/language catalogs.
        shared_keys = {}
        if shared_roots is not None:
            if set(shared_roots) != set(region_models) or any(
                    set(family) != {"primary", "unmasked"} or
                    len(set(family.values())) != 2 or not set(family.values()) <= region_models[region]
                    for region, family in shared_roots.items()):
                raise ValueError("invalid canonical clone physical model family")
        for region in region_models:
            models = {model for item_region, _, _, closure in catalogs if item_region == region
                      for model in closure}
            for old in sorted(models):
                role = next((role for role, path in shared_roots[region].items() if path == old), None) if shared_roots else None
                if role in shared_keys:
                    plan.models[region, old] = shared_keys[role]
                    continue
                while True:
                    candidate = uuid.uuid4().hex[:8]
                    if candidate not in plan.models.values() and all(not conn.execute(
                        "SELECT 1 FROM member_model WHERE asset_path=?", (candidate,)).fetchone()
                        for conn in plan.connections):
                        break
                plan.models[region, old] = candidate
                if role is not None:
                    shared_keys[role] = candidate

        roots = extractor.build_pack_roots(os.getcwd(), [str(plan.destination)],
            [p for p, status in extractor.detect_game_candidates() if status == "found"])
        cache = {}
        metadata_cache = {}
        # Reuse immutable output only within this one clone/namespace. Two
        # catalogs may share source bytes but have different private graphs;
        # both final CAB and runtime dependency maps are part of the key.
        isolated_cache = {}

        def inspect(data):
            if data not in metadata_cache:
                metadata_cache[data] = _bundle_metadata(data)
            return metadata_cache[data]

        for region, path, conn, models in catalogs:
            resolver = extractor.PackResolver(roots, str(plan.destination), extractor.DEFAULT_CDN_BASE, conn)
            originals = {}
            source_descriptors = {}
            if shared_roots is not None or private_source:
                plan.copied_source_packs[conn] = {
                    row["pack_name"] for old in models for row in _rows(conn, "member_model", "asset_path", old)}
                required = set()
                if "pack_name" in _columns(conn, "shader"):
                    pending = []
                    for old in models:
                        for edge in _rows(conn, "member_model_dependency", "asset_path", old):
                            if _rows(conn, "shader", "asset_path", edge["dependency"]):
                                pending.append(edge["dependency"])
                    seen_shaders = set()
                    while pending:
                        shader = pending.pop()
                        if shader in seen_shaders:
                            continue
                        seen_shaders.add(shader)
                        rows = _rows(conn, "shader", "asset_path", shader)
                        if len(rows) != 1:
                            raise ValueError("missing or ambiguous shared shader dependency")
                        required.add(rows[0]["pack_name"])
                        pending.extend(row["dependency"] for row in _rows(conn, "shader_dependency", "asset_path", shader))
                if retained_textures and "pack_name" in _columns(conn, "texture"):
                    for texture in retained_textures.get(region, ()):
                        packs = {row["pack_name"] for row in _rows(conn, "texture", "asset_path", texture)}
                        required.update(packs)
                        if private_source:
                            plan.retained_texture_packs.setdefault(conn, set()).update(packs)
                plan.required_source_packs[conn] = required
            for old in models:
                row = conn.execute("SELECT pack_name,head,size,key1,key2 FROM member_model WHERE asset_path=?", (old,)).fetchone()
                if not row:
                    raise ValueError("model " + old + " is missing from " + str(path))
                pack, head, size, key1, key2 = row
                descriptor = (pack, int(head), int(size), int(key1), int(key2))
                source_descriptors[old] = descriptor
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
                    _crypt_section(data, extractor.FIXED_KEY0, int(key1), int(key2))
                    original = bytes(data)
                    inspect(original)
                    cache[descriptor] = original
                originals[old] = cache[descriptor]
            identities = {}
            ambiguous_cabs = set()
            bundle_names = {}
            ambiguous_names = set()
            model_namespaces = {old: namespace + ":" + (
                hashlib.sha256(data).hexdigest() if shared_roots else region + ":" + old)
                for old, data in originals.items()}
            seen_cabs = set()
            for old, data in originals.items():
                model_namespace = model_namespaces[old]
                cabs, runtime, _, _ = inspect(data)
                if shared_roots:
                    owned_cabs = {name.lower() for name in cabs}
                    if seen_cabs.intersection(owned_cabs):
                        raise ValueError("canonical clone has ambiguous duplicate physical model CABs")
                    seen_cabs.update(owned_cabs)
                for original, renamed in _cab_mapping(cabs, model_namespace).items():
                    if original in identities and identities[original] != renamed:
                        ambiguous_cabs.add(original)
                    identities[original] = renamed
                # Preserve the standalone inspector's last-wins behavior for
                # repeated runtime names within one physical bundle.
                runtime_names = {original: _runtime_name(model_namespace, serialized_name, original)
                                 for serialized_name, original in runtime}
                for original, renamed in runtime_names.items():
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
                    _, _, externals, dependencies = inspect(data)
                    if any(any(cab in external.lower() for cab in ambiguous_cabs)
                           for external in externals):
                        raise ValueError("ambiguous private model CAB dependency")
                    if ambiguous_names.intersection(dependencies):
                        raise ValueError("ambiguous private model bundle dependency")
            records = []
            identity_key = tuple(sorted(identities.items()))
            bundle_name_key = tuple(sorted(bundle_names.items()))
            for old, data in originals.items():
                key = (source_descriptors[old], data, model_namespaces[old],
                       identity_key, bundle_name_key, (extractor.FIXED_KEY0, 0, 0))
                if key not in isolated_cache:
                    cloned = bytearray(isolate_bundle(data, model_namespaces[old],
                                                      identities, bundle_names))
                    plain = bytes(cloned) if shared_roots else None
                    _crypt_section(cloned, extractor.FIXED_KEY0, 0, 0)
                    encoded = bytes(cloned)
                    pack = "cc" + hashlib.sha256(encoded).hexdigest()[:30]
                    isolated_cache[key] = (pack, encoded, plain)
                pack, encoded, plain = isolated_cache[key]
                plan.packs[pack] = encoded
                if shared_roots:
                    plan.plain_packs[pack] = plain
                records.append((old, plan.models[region, old], pack, len(encoded)))
            plan.catalogs.append((conn, records, source_ids[region], new_id))
            log("prepared independent costume models: " + str(path))
        return plan
    except Exception:
        plan.rollback()
        plan.close()
        raise
