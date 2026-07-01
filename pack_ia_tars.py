#!/usr/bin/env python3
"""Pack a flat directory of pack/metapack files into several complete, uncompressed
TAR "parts" for uploading to archive.org (IA), plus a small manifest listing them.

Why this exists
---------------
elichika downloads its bulk assets from an archive.org item and stream-extracts them
into the cache dir (see handler/asset/archive.go and the Termux menu's "Download all
game files"). Uploading one giant 17 GB tar from a far-away connection is slow because
IA accepts a single object over a single TCP stream. Splitting into several *complete*
tars lets you upload them in parallel (each is a valid archive that passes IA's archive
check, unlike raw byte-split chunks), and elichika downloads every part and extracts
them into the same flat cache dir.

No file->pack manifest is needed: elichika locates packs by *basename* anywhere under
the cache dir, so the parts can be split at file boundaries arbitrarily. This script
only emits a *parts* manifest (which tar files exist), which the download side reads.

Each tar entry is stored as "<prefix>/<basename>" (default prefix: "packs") so the
download side can drop the first path component (tar --strip-components=1 / Go's
stripFirstComponent) and land every file flat in the cache dir, exactly like the
existing single-tar dumps.

Usage
-----
    python3 pack_ia_tars.py --src /path/to/sukusta/packs --region gl --out /path/to/out
    python3 pack_ia_tars.py --src /path/to/sukusta/packs --region jp --out /path/to/out \
        --part-size 2 --version 2d61e7b4e89961c7

Then upload every file in --out (the *.part*.tar files and the *.manifest) to your IA
item with your parallel uploader. Disk-tight? Do one region at a time: pack gl -> upload
-> delete the gl parts -> pack jp. The manifest is tiny; upload it last so a reader never
sees a manifest referencing parts that aren't up yet.
"""

import argparse
import os
import sys
import tarfile

GiB = 1024 * 1024 * 1024


def collect_files(src):
    """Return (basename, fullpath) for every regular, non-hidden file under src.

    Flattening to basename matches how elichika looks packs up (by basename); pack
    names are globally unique, so this is safe. Duplicate basenames are reported and
    the later one is skipped so a tar never contains two entries with the same name.
    """
    seen = {}
    files = []
    for root, _dirs, names in os.walk(src):
        for name in names:
            if name.startswith("."):
                continue  # skip .tmp-*, .cdncache-*, .DS_Store, etc.
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            if name in seen:
                print(f"  ! duplicate basename skipped: {full} (kept {seen[name]})",
                      file=sys.stderr)
                continue
            seen[name] = full
            files.append((name, full))
    files.sort(key=lambda p: p[0])
    return files


def bin_pack(files, part_bytes):
    """Group files into parts so each part is <= part_bytes (a single file larger than
    part_bytes gets its own part). Returns a list of parts, each a list of (name, path).
    """
    parts = []
    cur, cur_size = [], 0
    for name, full in files:
        size = os.path.getsize(full)
        if cur and cur_size + size > part_bytes:
            parts.append(cur)
            cur, cur_size = [], 0
        cur.append((name, full))
        cur_size += size
    if cur:
        parts.append(cur)
    return parts


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(description="Pack pack files into IA-friendly tar parts.")
    ap.add_argument("--src", required=True, help="flat directory of pack/metapack files")
    ap.add_argument("--region", required=True, choices=["gl", "jp"], help="region label")
    ap.add_argument("--out", required=True, help="output directory for the tars + manifest")
    ap.add_argument("--part-size", type=float, default=2.0,
                    help="target size per tar part, in GiB (default: 2)")
    ap.add_argument("--version", default="",
                    help="optional version/hash to embed in the tar names")
    ap.add_argument("--prefix", default="packs",
                    help="wrapper dir prefix inside each tar (default: packs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan the parts and print the manifest without writing tars")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        sys.exit(f"--src is not a directory: {args.src}")
    os.makedirs(args.out, exist_ok=True)
    part_bytes = int(args.part_size * GiB)

    print(f"scanning {args.src} ...")
    files = collect_files(args.src)
    if not files:
        sys.exit("no files found under --src")
    total = sum(os.path.getsize(f) for _n, f in files)
    print(f"  {len(files)} files, {human(total)} total")

    parts = bin_pack(files, part_bytes)
    width = max(2, len(str(len(parts))))

    stem = f"sifas-{args.region}-cdn-assets"
    if args.version:
        stem += f"-{args.version}"

    manifest_names = []
    for i, part in enumerate(parts, 1):
        tar_name = f"{stem}.part{str(i).zfill(width)}.tar"
        manifest_names.append(tar_name)
        part_size = sum(os.path.getsize(f) for _n, f in part)
        print(f"  {tar_name}: {len(part)} files, {human(part_size)}")
        if args.dry_run:
            continue
        tar_path = os.path.join(args.out, tar_name)
        # format=GNU_FORMAT handles long names and >8 GiB members; no compression (store).
        with tarfile.open(tar_path, "w", format=tarfile.GNU_FORMAT) as tar:
            for name, full in part:
                tar.add(full, arcname=f"{args.prefix}/{name}", recursive=False)

    manifest_name = f"sifas-{args.region}-cdn-assets.manifest"
    manifest_path = os.path.join(args.out, manifest_name)
    manifest_body = (
        f"# parts manifest for region '{args.region}' - one tar filename per line\n"
        f"# {len(parts)} part(s), {human(total)} total, {len(files)} files\n"
        + "".join(n + "\n" for n in manifest_names)
    )
    if args.dry_run:
        print("\n--- manifest (dry-run, not written) ---")
        print(manifest_body, end="")
    else:
        with open(manifest_path, "w") as f:
            f.write(manifest_body)
        print(f"\nwrote {manifest_name} ({len(parts)} part(s))")
        print(f"done. upload the *.part*.tar files then {manifest_name} (last) from {args.out}")


if __name__ == "__main__":
    main()
