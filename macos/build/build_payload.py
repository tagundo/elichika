#!/usr/bin/env python3
"""Stage the same deterministic official payload used by the Android app.

Run after rebuild_assets, outfit ordering and deterministic-serverdata checks.
Tool dictionaries are separate resources because payload_revision deliberately
limits the set of managed server paths.
"""
import argparse
from pathlib import Path
import shutil
import sys

from common import copy_tree, require, sha256, source_identity, source_ignore, write_json


def stage(repo, output):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    require(not output.exists(), "Shared payload output already exists")
    require(not output.is_relative_to(repo), "Stage shared payload outside the source checkout")
    output.mkdir(parents=True)
    payload = output / "payload"
    payload.mkdir()
    for name in ("server init jsons", "webui", "assets"):
        copy_tree(repo / name, payload / name, ignore=source_ignore)
    for source in (payload / "webui").rglob("*.go"):
        source.unlink()
    for name in ("privatekey.pem", "publickey.pem", "serverdata.db"):
        require((repo / name).is_file(), f"Missing initialized payload file: {name}")
        shutil.copy2(repo / name, payload / name)
    # Config, account DB and runtime caches are never copied from the build host.
    require(not (payload / "config.json").exists() and not (payload / "userdata.db").exists(),
            "Mutable runtime files must not be bundled")
    tools = output / "tool-data"
    tools.mkdir()
    for path in sorted(repo.glob("dictionary_*.txt")):
        shutil.copy2(path, tools / path.name)
    for name in ("dictionary_skill_en.txt", "dictionary_live_en.txt"):
        require((tools / name).is_file(), f"Required tool dictionary is missing: {name}")
    sys.path.insert(0, str(repo))
    # Freeze the clean official suit set before packaging mutable game data.
    # The same file is bundled on Android; legacy deletion never infers stock
    # membership from IDs or translated names in the user's live databases.
    from costume_management import write_stock_index
    import subprocess
    assets_commit = subprocess.check_output(
        ["git", "-C", str(repo / "assets"), "rev-parse", "HEAD"], text=True).strip()
    write_stock_index(repo / "assets", payload / "assets/costume-stock-index.json", assets_commit)
    import payload_revision
    manifest = payload_revision.build_manifest(str(payload))
    write_json(output / "payload_revision.json", manifest)
    payload_revision.verify_packaged_manifest(str(payload), manifest)
    report = {"schema": 1, "source": source_identity(repo),
              "serverdata_sha256": sha256(payload / "serverdata.db"),
              "manifest_sha256": sha256(output / "payload_revision.json"),
              "tool_data": {path.name: sha256(path) for path in sorted(tools.iterdir())}}
    write_json(output / "shared-payload-build.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.repo, args.output)
