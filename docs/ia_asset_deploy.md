# Deploying bulk assets to archive.org (IA)

This explains how the game's bulk asset files (the flat pack/metapack files in
`sukusta/packs`) are packaged, uploaded to archive.org, and downloaded back by
elichika. It's the "Download all game files (from archive.org)" path.

## How elichika consumes the archive

At runtime the game asks elichika for each pack by name (`/asset/getPackUrl` →
`/static/<name>`, or a byte range into a metapack). Packs are located by **basename
anywhere under the cache dir** (`handler/asset/cache.go`), so the on-disk layout is
irrelevant — the files just have to be present.

The bulk pre-seed (`handler/asset/archive.go`, and the Termux menu option 7) downloads
tar files from an archive.org item and **stream-extracts** them into the cache dir,
dropping the first path component and skipping files that already exist (incremental /
resumable). Because lookup is by basename, **no file→pack manifest is needed** — parts
can be split at file boundaries however you like.

## Why TAR parts (not one big zip, not byte-split chunks)

- **Complete tars pass IA's archive check; byte-split chunks don't.** IA validates
  archive uploads by content; a chunk that starts mid-file (or with a zip's `PK\x03\x04`
  magic) is rejected as a broken archive. Every tar this script writes is a complete,
  valid archive.
- **Several parts upload in parallel.** IA takes one object over one stream, which is
  slow from a distant connection. N complete tars upload as N parallel streams.
- **tar streams; zip doesn't.** elichika extracts tar straight from the HTTP body. Go's
  `archive/zip` needs random access to the central directory, so a zip can't be
  stream-extracted without buffering the whole part.
- **Uncompressed = no CPU cost.** The pack files are already compressed AssetBundles, so
  the tars are stored (no deflate), just like `zip -0`.

## 1. Pack

Run `pack_ia_tars.py` once per region against the flat packs directory:

```sh
python3 pack_ia_tars.py --src /path/to/sukusta/packs --region gl --out ./ia_out --part-size 2
python3 pack_ia_tars.py --src /path/to/sukusta/packs --region jp --out ./ia_out --part-size 2
```

It produces, per region:

- `sifas-<region>-cdn-assets[-<version>].partNN.tar` — complete, uncompressed tars,
  each ≤ `--part-size` GiB (a single file bigger than that gets its own part). Every
  entry is stored as `packs/<basename>` so the download side's `--strip-components=1`
  lands it flat.
- `sifas-<region>-cdn-assets.manifest` — a plain-text list of the part filenames (one
  per line, `#` comments allowed). The name is **version-less on purpose** so the
  download side always fetches the same manifest URL; the parts it lists may be
  versioned.

`--version <hash>` is optional (embeds a snapshot label in the part names). Use
`--dry-run` to preview the split and manifest without writing tars.

**Disk-tight?** Peak disk is `sources + one region's parts`. Do one region at a time:
pack `gl` → upload → delete the `gl` parts → pack `jp`.

## 2. Upload

Upload everything in the output directory to the IA item with your parallel uploader
(16 streams). **Upload the `*.part*.tar` files first and the `.manifest` last**, so a
downloader never reads a manifest that references parts which aren't up yet.

The item identifier is `llsifas-elichika-static-data` (set in `handler/asset/archive.go`
as `archiveItem` and in `elichika_utility.sh` as `ARCHIVE_ITEM`). Change both if you use
a different item.

## 3. Download (automatic)

`./elichika download_archive gl|jp|both` and Termux menu option 7 both:

1. fetch `sifas-<region>-cdn-assets.manifest` from the item,
2. download and extract every part it lists (aria2c multi-connection in the menu,
   skipping files already present),
3. and, **if a region has no manifest yet**, fall back to the older single-tar dump
   (`ll-sifas-cdn-data`) so downloads keep working during migration.

Restart the server afterwards so it indexes the new files.
