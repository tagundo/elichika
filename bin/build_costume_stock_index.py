#!/usr/bin/env python3
"""Index the clean, initialized official build payload before any mod installs.

Never run this against an installed user's mutable databases: absence from this
index permits conservative removal of legacy custom costume registrations.
"""
import argparse
from pathlib import Path
import subprocess
import sys


def build(repo, destination):
    repo = Path(repo).resolve(strict=True)
    source = subprocess.check_output(
        ["git", "-C", str(repo / "assets"), "rev-parse", "HEAD"], text=True).strip()
    sys.path.insert(0, str(repo))
    from costume_management import write_stock_index
    return write_stock_index(repo / "assets", Path(destination), source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.repo, args.output)
    print("Protected stock costumes: " + ", ".join(
        region + "=" + str(len(data["suit_ids"]))
        for region, data in sorted(result["regions"].items())))
