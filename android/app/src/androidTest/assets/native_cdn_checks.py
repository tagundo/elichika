"""Read-only probes of the app's real bundled original-costume catalog."""
import hashlib
from pathlib import Path
import re
import socket
import sqlite3
from unittest.mock import patch


def check(root, expected_index_sha256):
    import costume_cdn_catalog as catalog
    import costume_cdn_restore as restore
    root = Path(root).resolve(strict=True)
    index_path = root / catalog.INDEX_PATH
    assert index_path.is_file() and not index_path.is_symlink()
    assert re.fullmatch(r"[a-f0-9]{64}", expected_index_sha256)
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    assert digest(index_path) == expected_index_sha256, "Installed CDN catalog differs from the signed payload"
    files = [index_path, *(root / "assets/db").glob("*/masterdata.db"),
             *(root / "assets/db").glob("*/asset_[ai]_*.db")]
    before = {str(path.relative_to(root)): digest(path) for path in files}
    connections, network_requests = [], []
    real_connect = sqlite3.connect
    def readonly_connect(path, *args, **kwargs):
        assert kwargs.get("uri") is True and str(path).endswith("?mode=ro"), path
        connections.append(str(path))
        return real_connect(path, *args, **kwargs)
    def refuse_network(*args, **kwargs):
        network_requests.append(True)
        raise AssertionError("Read-only original-costume plan tried to access the network")
    plans = []
    with patch.object(sqlite3, "connect", side_effect=readonly_connect), \
            patch.object(restore, "urlopen", side_effect=refuse_network), \
            patch.object(socket, "create_connection", side_effect=refuse_network):
        index = catalog.load_index(root)
        assert re.fullmatch(r"[a-f0-9]{40}", index["source_commit"])
        for region, platform, language in (("gl", "android", "en"), ("jp", "ios", "ja")):
            suits = index["regions"][region]["suits"]
            assert suits
            selected = min(suits, key=int)
            plan = restore.plan_restore(root, suit="suit:" + selected,
                                        region=region, platform=platform, language=language)
            assert plan["suit"] == int(selected) and plan["source_commit"] == index["source_commit"]
            assert plan["region"] == region and plan["platforms"] == [platform]
            assert plan["packs"] and plan["catalogs"] and plan["models"]
            plans.append(plan)
    assert connections and not network_requests
    after = {str(path.relative_to(root)): digest(path) for path in files}
    assert before == after, "Read-only original-costume plan modified source databases or catalog"
    return {"status": "PASS_BUNDLED_CATALOG_READ_ONLY_PLAN", "root": str(root),
            "index_sha256": expected_index_sha256, "index_bytes": index_path.stat().st_size,
            "source_commit": index["source_commit"],
            "original_costumes": {region: len(index["regions"][region]["suits"]) for region in ("gl", "jp")},
            "plans": plans, "read_only_database_connections": len(connections),
            "network_requests": 0, "source_preserved": True, "source_files": before,
            "modules": {module.__name__: module.__file__ for module in (catalog, restore)},
            "scope": "Actual bundled catalog and read-only Android/GL + iOS/JP restore planning; no pack download or publication"}
