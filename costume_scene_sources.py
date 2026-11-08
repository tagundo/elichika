"""Verify the canonical Rina authoring face before reusing the game asset.

Shared-board exports retain the original face for editing. Publishing that same
Unity CAB under another model key would alias the installed face in the client.
Reuse is allowed only after the actual catalogue section decrypts byte-for-byte
to the declared native face. Its complete catalogue dependency closure remains
the installer's responsibility; no copied face with missing edges is created.
"""
import hashlib
from pathlib import Path


def face_preflight(db, raw, *, root, platform, region, source_suit_id=None):
    """Read-only asset admission; pack resolution may populate the normal cache."""
    from costume_scene_installer import _descriptor, _closure, _mapping, _pack_destination, _safe_file
    from costume_clone_assets import _bundle
    import llas_asset_extractor as extractor

    if platform not in ("android", "ios") or region not in ("gl", "jp"):
        raise ValueError("The canonical face has an unsupported native catalogue.")
    root = Path(root).resolve()
    raw = bytes(raw)
    table, descriptor = _descriptor(db, "Z$")
    if table != "member_model" or int(descriptor["size"]) != len(raw):
        raise ValueError("The canonical face does not match the installed original Rina face.")
    # Validate transitive model/shader descriptors and download mappings before
    # admitting the reuse. The caller also registers this entire closure.
    closure = _closure(db, ["Z$"])
    mappings = {pack: _mapping(db, pack) for pack in closure}
    pending, sections = ["Z$"], {}
    while pending:
        asset = pending.pop()
        if asset in sections:
            continue
        kind, section = _descriptor(db, asset)
        if int(mappings[section["pack_name"]]["file_size"]) < int(section["head"]) + int(section["size"]):
            raise ValueError("An original face dependency section exceeds its download mapping.")
        sections[asset] = section
        if kind == "member_model":
            pending.extend(row[0] for row in db.execute(
                "SELECT dependency FROM member_model_dependency WHERE asset_path=?", (asset,)))
    destination = _pack_destination(root)
    roots = extractor.build_pack_roots(str(root), [str(destination)],
        [path for path, status in extractor.detect_game_candidates() if status == "found"])
    resolver = extractor.PackResolver(roots, str(destination), extractor.DEFAULT_CDN_BASE, db)
    pack = resolver.resolve(descriptor["pack_name"])
    if pack is None:
        raise FileNotFoundError("The original Rina face pack is unavailable for verification.")
    pack = _safe_file(pack)
    head, size = int(descriptor["head"]), int(descriptor["size"])
    with pack.open("rb") as stream:
        stream.seek(head)
        decrypted = bytearray(stream.read(size))
    if len(decrypted) != size:
        raise ValueError("The original Rina face pack section is truncated.")
    extractor.decrypt_section(decrypted, extractor.FIXED_KEY0,
                              int(descriptor["key1"]), int(descriptor["key2"]))
    if bytes(decrypted) != raw:
        raise ValueError("The canonical face differs from the installed original Rina face; use a complete native model graph.")
    _, _, serialized = _bundle(raw)
    native = 13 if platform == "android" else 9
    if any(int(file.target_platform) != native for file in serialized):
        raise ValueError("The canonical face belongs to a different native platform.")
    return {"asset_path": "Z$", "sha256": hashlib.sha256(raw).hexdigest(),
            "platform": platform, "region": region, "source_suit_id": source_suit_id,
            "serialized_cabs": sorted(file.name for file in serialized),
            "descriptor": descriptor, "dependency_packs": sorted(closure),
            "dependency_sections": sections}
