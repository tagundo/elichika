#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llas_asset_extractor.py
=======================
elichika / LLAS game asset extractor (decryptor).

Uses the same XOR stream-cipher from llasdecryptor.py, but instead of asking
the user to type key1 / key2 / head / size by hand, it reads them automatically
from the asset DB (member_model, texture, stage ...).
(This matches the original LLASDecryptor behaviour and is the correct, safe way.)

Improvements over the original llasdecryptor.py
  1. Auto key lookup   : no need to type key1/key2 -- pulled from the DB.
  2. Head offset       : metapacks (several assets in one pack) are sliced
                         [head:head+size] before decrypting. (The original
                         XOR-ed the whole file, which corrupts metapacks.)
  3. Multi-select      : '3', '1,4,7', '4-8', '1, 4-8, 14-23', 'all'.
  4. Two select modes  :
        - Mode 1: character -> costume (costume_clone.py style, 3D models)
        - Mode 2: pick an asset table directly (models/textures/stages/skills...)
  5. Auto extension    : UnityFS -> .unity, PNG -> .png, JPG -> .jpg, else .bin
  6. Output folder     : you choose where assets go; they are sorted into
                         per-category subfolders (3d_model / texture / stage ...).
  7. Termux friendly   : default storage path + setup-storage check.
  8. Pack resolution   : for each pack, look in packs/ first; if missing, copy
                         it from static//game files into packs/; if still missing,
                         download it from the CDN into packs/ (<cdn><pack_name>,
                         metapacks handled). Then read from packs/. So packs/
                         becomes a growing local mirror. --cdn / --no-cdn control
                         the network; --packs adds extra source folders.

Usage
  python3 llas_asset_extractor.py                 # use current folder as elichika root
  python3 llas_asset_extractor.py --base ~/elichika
  python3 llas_asset_extractor.py --base . --out ~/storage/downloads/sukusta/extracted
  # Default source: copy the game's assets here with a file manager, then just run:
  #   ~/storage/downloads/sukusta/packs/pak9/...   or   .../sukusta/packs/files/pak9/...
  # Or point at any other folder explicitly:
  python3 llas_asset_extractor.py --base ~/elichika --packs ~/storage/downloads/sukusta/packs
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

# key0 is always 12345 in LLAS asset encryption.
FIXED_KEY0 = 12345

# Tables using the head/size/key1/key2 schema (the "encrypted" asset tables,
# per the original LLASDecryptor).
ENCRYPTED_TABLES = [
    ("adv_script", "Adv Script (story scripts)"),
    ("background", "Background"),
    ("gacha_performance", "Gacha Performance"),
    ("live2d_sd_model", "Live2D SD Model (2D)"),
    ("live_prop_skeleton", "Live Prop Skeleton"),
    ("live_timeline", "Live Timeline"),
    ("member_model", "Member Model (3D models / costumes)"),
    ("member_sd_model", "Member SD Model (2D)"),
    ("member_facial", "Member Facial"),
    ("member_facial_animation", "Member Facial Animation"),
    ("navi_motion", "Navi Motion"),
    ("navi_timeline", "Navi Timeline"),
    ("shader", "Shader"),
    ("skill_effect", "Skill Effect"),
    ("skill_timeline", "Skill Timeline"),
    ("skill_wipe", "Skill Wipe"),
    ("stage", "Stage"),
    ("stage_effect", "Stage Effect"),
    ("texture", "Texture (cards etc.)"),
]

# Character list (from costume_clone.py)
CHARACTERS = {
    1: "Honoka", 2: "Eli", 3: "Kotori", 4: "Umi", 5: "Rin", 6: "Maki",
    7: "Nozomi", 8: "Hanayo", 9: "Nico",
    101: "Chika", 102: "Riko", 103: "Kanan", 104: "Dia", 105: "You",
    106: "Yoshiko", 107: "Hanamaru", 108: "Mari", 109: "Ruby",
    201: "Ayumu", 202: "Kasumi", 203: "Shizuku", 204: "Karin", 205: "Ai",
    206: "Kanata", 207: "Setsuna", 208: "Emma", 209: "Rina",
    210: "Shioriko", 211: "Mia", 212: "Lanzhu",
}


# ============================================================
# Crypto / file utils
# ============================================================

def decrypt_section(data, key0, key1, key2):
    """Same XOR stream as manipulate_file in llasdecryptor.py (in-place).

    XOR, so encrypt/decrypt are symmetric. key1/key2 from the DB may be a
    negative int32, so normalise to 32-bit unsigned (matches the C# behaviour)."""
    k0 = key0 & 0xFFFFFFFF
    k1 = key1 & 0xFFFFFFFF
    k2 = key2 & 0xFFFFFFFF
    for i in range(len(data)):
        data[i] ^= ((k1 ^ k0 ^ k2) >> 24) & 0xFF
        k0 = (0x343fd * k0 + 0x269ec3) & 0xFFFFFFFF
        k1 = (0x343fd * k1 + 0x269ec3) & 0xFFFFFFFF
        k2 = (0x343fd * k2 + 0x269ec3) & 0xFFFFFFFF


def detect_extension(data):
    """Guess the extension from the decrypted bytes' magic number."""
    if data[:7] == b"UnityFS":
        return ".unity"
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"@UTF" or data[:4] == b"CRID":
        return ".acb"        # sound (if a sound asset ended up in an encrypted table)
    return ".bin"


# Where the Android game client stores its downloaded assets.
# (Inside .../files/files are the DBs and pkg<X>/ folders; packs live at
#  pkg<first-char-of-pack>/<pack_name>.)
GAME_PACKAGE_NAMES = [
    "com.klab.lovelive.allstars",          # JP
    "com.klab.lovelive.allstars.global",   # GL
]

# Where you copied the game's assets with a file manager (readable from Termux).
# On Android 11+ Termux can't read another app's Android/data directly, so the
# practical workflow is: copy .../files (or its pak*/ folders) here, then run.
# This folder is auto-searched; both layouts are handled:
#   ~/storage/downloads/sukusta/packs/pak9/...        (buckets at the top)
#   ~/storage/downloads/sukusta/packs/files/pak9/...  (inside a 'files' wrapper)
COPIED_PACKS_DIR = os.path.expanduser("~/storage/downloads/sukusta/packs")


def _probe_dir(path):
    """Classify a directory cheaply: 'found' | 'no_access' | 'absent'.
    One directory open + one read (reveals Android 11+ EACCES on Android/data)."""
    try:
        with os.scandir(path) as it:
            next(it, None)          # force a read so a blocked dir raises here
        return "found"
    except PermissionError:
        return "no_access"
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "no_access"          # any other access error -> treat as inaccessible


def detect_game_candidates():
    """Return [(path, status)] for the game client's asset folder candidates
    (.../files/files). status is 'found' / 'no_access' / 'absent'.
    Probes each distinct physical location only once."""
    bases = [
        "/sdcard/Android/data",
        "/storage/emulated/0/Android/data",
        os.path.expanduser("~/storage/shared/Android/data"),  # Termux: -> /sdcard
    ]
    out, seen = [], set()
    for base in bases:
        for pkg in GAME_PACKAGE_NAMES:
            cand = os.path.join(base, pkg, "files", "files")
            key = os.path.realpath(cand)        # /sdcard == /storage/emulated/0 == ~/storage/shared
            if key in seen:
                continue
            seen.add(key)
            out.append((cand, _probe_dir(cand)))
    return out


def build_pack_roots(base_dir, extra_dirs, game_roots):
    """Build the ordered list of source roots to search for packs:
      1) folders given with --packs
      2) the copied-packs folder (~/storage/downloads/sukusta/packs)
      3) readable game client folders (.../files/files), if any
      4) elichika's static/ and the root (local setup)
    Only readable game_roots are passed in (blocked ones are shown in the banner)."""
    roots = []
    for d in extra_dirs or []:
        roots.append(os.path.abspath(os.path.expanduser(d)))
    roots.append(COPIED_PACKS_DIR)
    roots.extend(game_roots)
    roots.append(os.path.join(base_dir, "static"))
    roots.append(base_dir)
    # dedup (keep order)
    seen, unique = set(), []
    for r in roots:
        ap = os.path.abspath(r)
        if ap not in seen:
            seen.add(ap)
            unique.append(ap)
    return unique


def root_has_content_shallow(root):
    """Cheap, non-recursive check: does root hold any file, or a
    pak*/pkg*/files/static subfolder? Used for the startup 'no packs' nudge
    without building the full index."""
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if e.is_file():
                        return True
                    if e.is_dir():
                        n = e.name.lower()
                        if (n.startswith("pak") or n.startswith("pkg")
                                or n in ("files", "static")):
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


# Per-root pack index cache: {root(abspath): {basename: fullpath}}
_pack_index_cache = {}


def _is_bucket_dir(name):
    """A bucket folder like pak1, pak2 / pkg0 ..."""
    n = name.lower()
    return n.startswith("pak") or n.startswith("pkg")


def _index_dir(d, index, prog=None):
    """Index files directly inside d as basename->path (one level, no reads)."""
    try:
        for entry in os.scandir(d):
            if entry.is_file():
                index.setdefault(entry.name, entry.path)
                if prog is not None:
                    prog.file()
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        pass


# Wrapper folders that may sit between a root and its pak*/pkg* buckets.
_WRAPPER_DIRS = {"files", "static"}


def _index_buckets_under(d, index, dirs=None, prog=None, depth=0):
    """Index files directly in d, plus files inside d's pak*/pkg* buckets.
    Descends one more level into 'files'/'static' wrapper folders, so all of
    these are handled:
        <d>/pak9/...            (buckets at this level)
        <d>/files/pak9/...      ('files' wrapper)
        <d>/static/pak9/...     ('static' wrapper)
        <d>/files/files/pak9/.. (nested, up to a small depth)
    Only descends into wrapper- or bucket-named dirs, so it never walks
    unrelated trees (e.g. assets/db). Lists names only — no file reads.

    When `dirs` is given it collects {scanned_dir: mtime} for every directory we
    touch, which the on-disk cache stores as its staleness signature: adding or
    removing a file/folder bumps its parent dir's mtime, so a changed mtime on any
    stored dir (root, a bucket, or a wrapper) means the cache must be rebuilt."""
    _index_dir(d, index, prog)                    # flat files at this level
    if dirs is not None:
        try:
            dirs[os.path.abspath(d)] = os.stat(d).st_mtime
        except OSError:
            pass
    try:
        entries = list(os.scandir(d))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        name = entry.name.lower()
        if _is_bucket_dir(name):
            _index_dir(entry.path, index, prog)   # files inside a bucket
            if dirs is not None:
                try:
                    dirs[os.path.abspath(entry.path)] = os.stat(entry.path).st_mtime
                except OSError:
                    pass
        elif name in _WRAPPER_DIRS and depth < 3:
            _index_buckets_under(entry.path, index, dirs, prog, depth + 1)


# ---- on-disk pack index cache -----------------------------------------------
# The first time a big packs/ folder is indexed, os.scandir over thousands of
# files on Android's FUSE-backed shared storage can take ~30s (cold). We persist
# the resulting {basename: path} map to a small JSON so later runs — even after
# the app is restarted — skip the cold scan and load in a few ms. Staleness is
# caught by re-stat'ing the dirs we scanned (see _index_buckets_under): any add /
# remove bumps a stored dir's mtime, which invalidates the cache and forces a
# rebuild. The cache lives OUTSIDE the indexed roots so writing it never changes
# a root's mtime (which would otherwise invalidate the cache we just wrote).
_INDEX_CACHE_VERSION = 1


def _index_cache_enabled():
    return os.environ.get("LLAS_NO_INDEX_CACHE", "").strip().lower() not in (
        "1", "true", "yes", "on")


def _index_cache_dir():
    """Writable, persistent location for the index cache. Override with
    LLAS_INDEX_CACHE_DIR (the app can point this at a guaranteed-writable path);
    defaults to ~/.cache/llas_extractor (Termux home / the app's HOME)."""
    override = os.environ.get("LLAS_INDEX_CACHE_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".cache", "llas_extractor")


def _index_cache_path(root):
    h = hashlib.sha1(os.path.abspath(root).encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return os.path.join(_index_cache_dir(), h + ".json")


def _load_disk_index(root):
    """Return the cached {basename: path} for root if a fresh cache exists, else
    None. 'Fresh' = every directory recorded at build time still has the same
    mtime (cheap: a handful of stat calls, not a full re-scan)."""
    if not _index_cache_enabled():
        return None
    root = os.path.abspath(root)
    try:
        with open(_index_cache_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("version") != _INDEX_CACHE_VERSION
            or data.get("root") != root):
        return None
    dirs, index = data.get("dirs"), data.get("index")
    if not isinstance(dirs, dict) or not isinstance(index, dict):
        return None
    for d, mtime in dirs.items():
        try:
            if os.stat(d).st_mtime != mtime:
                return None                       # something changed -> rebuild
        except OSError:
            return None                           # a scanned dir vanished -> rebuild
    return index


def _save_disk_index(root, index, dirs):
    """Persist the index atomically. Silently skips (in-memory cache still works)
    if the cache location isn't writable."""
    if not _index_cache_enabled() or not dirs:
        return
    path = _index_cache_path(root)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": _INDEX_CACHE_VERSION,
                       "root": os.path.abspath(root),
                       "dirs": dirs, "index": index}, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _invalidate_disk_index(root):
    """Drop the on-disk cache for root (called when we add a pack to it)."""
    try:
        os.remove(_index_cache_path(root))
    except OSError:
        pass


def _clear_disk_index_cache():
    """Remove all cached indexes (used by --refresh-index)."""
    d = _index_cache_dir()
    try:
        for fn in os.listdir(d):
            if fn.endswith(".json") or fn.endswith(".json.tmp"):
                try:
                    os.remove(os.path.join(d, fn))
                except OSError:
                    pass
    except OSError:
        pass


class _ScanProgress:
    """Heartbeat for the one-time cold pack-folder scan, so a slow first index
    doesn't look like a hang. Stays quiet for quick scans (< ~0.7s) and prints a
    running file count roughly every 1.5s while a long scan is in progress.
    Writes via print(), which the web adapter captures into the job log."""

    def __init__(self, root, log=print):
        self.root = root
        self.log = log
        self.files = 0
        self._t0 = time.monotonic()
        self._last = self._t0
        self._announced = False

    def file(self):
        self.files += 1
        if self.files & 0x3FF == 0:               # check the clock every 1024 files
            self._tick()

    def _tick(self):
        now = time.monotonic()
        if not self._announced and now - self._t0 > 0.7:
            self.log(f"Indexing packs under {self.root} … "
                     f"(first run on shared storage can take a while)")
            self._announced = True
            self._last = now
        elif self._announced and now - self._last > 1.5:
            self.log(f"  … {self.files:,} pack files indexed so far")
            self._last = now

    def done(self):
        el = time.monotonic() - self._t0
        if self._announced or el > 0.7:
            self.log(f"Pack index ready: {self.files:,} files in {el:.1f}s "
                     f"(cached — the next run will be instant)")


def _scan_pack_index(root):
    """Full cold scan of root -> ({basename: path}, {scanned_dir: mtime})."""
    index, dirs = {}, {}
    prog = _ScanProgress(root)
    _index_buckets_under(root, index, dirs, prog)
    prog.done()
    return index, dirs


def build_pack_index(root):
    """Index pack files under root, so packs can be found by name even when bucket
    names (pak1, pak9 ...) don't encode the pack name. Handles buckets directly
    under root and under a 'files'/'static' wrapper.

    Three tiers, fastest first: this process's in-memory cache, the on-disk cache
    (survives restarts), then a full cold scan (which is then persisted)."""
    root = os.path.abspath(root)
    if root in _pack_index_cache:
        return _pack_index_cache[root]
    index = _load_disk_index(root)
    if index is not None:
        if len(index) >= 200:                     # note the fast path on big folders
            print(f"Pack index loaded from cache: {len(index):,} packs ({root})")
    else:
        index, dirs = _scan_pack_index(root)
        _save_disk_index(root, index, dirs)
    _pack_index_cache[root] = index
    return index


def find_pack_file(pack_roots, pack_name):
    """Find the actual pack file path across several source roots, autodetecting layout.

    For each root:
    1) fast direct guesses (known layouts)
         <root>/pkg<X>/<pack>, <root>/<pack>,
         <root>/static/<pack>, <root>/static/pkg<X>/<pack>
    2) otherwise, look it up by basename in an index built from pak1/pak2/...
       buckets (matches the real game's .../files/files/pak<N>/ layout)
    """
    if not pack_name:
        return None
    first = pack_name[0]
    for root in pack_roots:
        for p in (
            os.path.join(root, "pkg" + first, pack_name),
            os.path.join(root, pack_name),
            os.path.join(root, "static", pack_name),
            os.path.join(root, "static", "pkg" + first, pack_name),
        ):
            if os.path.isfile(p):
                return p
        idx = build_pack_index(root)
        hit = idx.get(pack_name)
        if hit:
            return hit
    return None


# Public CDN that serves the encrypted packs (from elichika's cdn_server default).
# The game/elichika fetch a pack as: <CDN_BASE><pack_name>  (no pkg prefix, no query).
DEFAULT_CDN_BASE = "https://llsifas.imsofucking.gay/static/"

_UA = "llas-extractor"
_DOWNLOADER = None   # cached: 'curl' | 'wget' | 'urllib'


def downloader_name():
    """Pick a download backend once. Prefer curl/wget because Termux's bundled
    python is often built without the ssl module (so urllib can't open https)."""
    global _DOWNLOADER
    if _DOWNLOADER is None:
        if shutil.which("curl"):
            _DOWNLOADER = "curl"
        elif shutil.which("wget"):
            _DOWNLOADER = "wget"
        else:
            _DOWNLOADER = "urllib"
    return _DOWNLOADER


def download_url(url, tmp):
    """Download url -> tmp. Returns (ok, err_string_or_None).
    Uses curl/wget when present (works without python ssl), else urllib."""
    tool = downloader_name()

    if tool == "curl":
        try:
            r = subprocess.run(
                ["curl", "-sSL", "--connect-timeout", "15", "--max-time", "600",
                 "-A", _UA, "-o", tmp, "-w", "%{http_code}", url],
                capture_output=True, text=True)
        except Exception as e:
            return False, f"curl: {e}"
        code = (r.stdout or "").strip()
        if code.startswith("2"):
            return True, None
        if code.isdigit() and code != "000":      # real HTTP status (e.g. 404)
            return False, f"HTTP {code}"
        err = (r.stderr or "").strip().splitlines()  # transport error (DNS/conn/TLS)
        return False, (err[-1] if err else f"curl exit {r.returncode}")

    if tool == "wget":
        try:
            r = subprocess.run(["wget", "-q", "-U", _UA, "-O", tmp, url],
                               capture_output=True, text=True)
        except Exception as e:
            return False, f"wget: {e}"
        if r.returncode == 0:
            return True, None
        if r.returncode == 8:                      # server error response (often 404)
            return False, "HTTP 404"
        err = (r.stderr or "").strip().splitlines()
        return False, (err[-1] if err else f"wget exit {r.returncode}")

    # urllib fallback (needs python built with ssl for https)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


class PackResolver:
    """Locate a pack and make sure it ends up in packs_dir, in this order:
       1) already in packs_dir
       2) found in another source root (static/, game files/) -> copy into packs_dir
       3) download from the CDN into packs_dir            (<cdn_base><pack_name>)
       4) (rare) download its metapack and carve out the pack into packs_dir
    Returns a path inside packs_dir, or None. Then extract_one reads that file.
    Uses only the standard library (urllib) so nothing extra is needed in Termux."""

    def __init__(self, pack_roots, packs_dir, cdn_base, asset_conn):
        self.roots = [os.path.abspath(r) for r in pack_roots]
        self.packs_dir = os.path.abspath(packs_dir)
        self.cdn_base = (cdn_base.rstrip("/") + "/") if cdn_base else None
        self.asset_conn = asset_conn          # for the rare metapack lookup
        self._meta_tmp = {}                   # metapack_name -> temp path (reused per run)
        self.stats = {"packs": 0, "copied": 0, "cdn": 0, "metapack": 0, "missing": 0}

    # ---- lookups ----
    def _in_packs(self, pack_name):
        return build_pack_index(self.packs_dir).get(pack_name)

    def _in_other_roots(self, pack_name):
        for root in self.roots:
            if root == self.packs_dir:
                continue
            hit = build_pack_index(root).get(pack_name)
            if hit:
                return hit
        return None

    # ---- writes into packs_dir ----
    def _dest(self, pack_name):
        return os.path.join(self.packs_dir, pack_name)

    def _register_pack(self, dest, pack_name):
        """A new pack now lives in packs_dir. Update the in-memory index in place
        (so a bulk download doesn't rescan the whole folder for every pack) and
        drop the stale on-disk cache — it's rebuilt fresh on the next cold start
        (packs_dir's mtime changed anyway, so it would be invalidated regardless)."""
        idx = _pack_index_cache.get(os.path.abspath(self.packs_dir))
        if idx is not None:
            idx[pack_name] = dest
        _invalidate_disk_index(self.packs_dir)

    def _finalize(self, tmp, pack_name):
        os.makedirs(self.packs_dir, exist_ok=True)
        dest = self._dest(pack_name)
        os.replace(tmp, dest)
        self._register_pack(dest, pack_name)
        return dest

    def _copy_in(self, src, pack_name):
        os.makedirs(self.packs_dir, exist_ok=True)
        dest = self._dest(pack_name)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copy2(src, dest)
            self._register_pack(dest, pack_name)
        return dest

    # ---- CDN ----
    @staticmethod
    def _http_get(url, tmp):
        return download_url(url, tmp)

    @staticmethod
    def _looks_like_pack(path):
        """Reject HTML/empty error pages saved as if they were a pack."""
        try:
            if os.path.getsize(path) == 0:
                return False
            with open(path, "rb") as f:
                head = f.read(16).lstrip()
            low = head.lower()
            return not (low.startswith(b"<!doctype") or low.startswith(b"<html"))
        except OSError:
            return False

    def _download_direct(self, pack_name):
        tmp = self._dest(pack_name) + ".part"
        os.makedirs(self.packs_dir, exist_ok=True)
        ok, err = self._http_get(self.cdn_base + pack_name, tmp)
        if not ok:
            if os.path.exists(tmp):
                os.remove(tmp)
            if err != "HTTP 404":            # 404 just means "try metapack / not there"
                print(f"  [cdn] {pack_name}: download failed ({err})")
            return None
        if not self._looks_like_pack(tmp):
            os.remove(tmp)
            return None
        return self._finalize(tmp, pack_name)

    def _metapack_info(self, pack_name):
        try:
            row = self.asset_conn.execute(
                "SELECT metapack_name, metapack_offset, file_size "
                "FROM m_asset_package_mapping "
                "WHERE pack_name = ? AND metapack_name IS NOT NULL LIMIT 1",
                (pack_name,)).fetchone()
        except sqlite3.Error:
            return None
        if not row or not row[0]:
            return None
        return row[0], int(row[1] or 0), int(row[2] or 0)

    def _download_via_metapack(self, pack_name):
        info = self._metapack_info(pack_name)
        if not info:
            return None
        metapack_name, offset, file_size = info
        mp = self._meta_tmp.get(metapack_name)
        if mp is None or not os.path.exists(mp):
            mp = os.path.join(self.packs_dir, "." + metapack_name + ".metapack.part")
            os.makedirs(self.packs_dir, exist_ok=True)
            ok, err = self._http_get(self.cdn_base + metapack_name, mp)
            if not ok:
                if os.path.exists(mp):
                    os.remove(mp)
                print(f"  [cdn] {pack_name}: metapack {metapack_name} failed ({err})")
                return None
            if not self._looks_like_pack(mp):
                os.remove(mp)
                return None
            self._meta_tmp[metapack_name] = mp
        # carve the individual pack [offset : offset+file_size] out of the metapack
        try:
            with open(mp, "rb") as f:
                f.seek(offset)
                data = f.read(file_size) if file_size > 0 else f.read()
        except OSError as e:
            print(f"  [cdn] {pack_name}: carve failed ({e})")
            return None
        tmp = self._dest(pack_name) + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        return self._finalize(tmp, pack_name)

    def cleanup(self):
        """Remove temporary metapack downloads kept for the run."""
        for mp in self._meta_tmp.values():
            try:
                os.remove(mp)
            except OSError:
                pass
        self._meta_tmp.clear()

    # ---- main entry ----
    def resolve(self, pack_name):
        hit = self._in_packs(pack_name)
        if hit:
            self.stats["packs"] += 1
            return hit
        hit = self._in_other_roots(pack_name)
        if hit:
            self.stats["copied"] += 1
            return self._copy_in(hit, pack_name)
        if self.cdn_base:
            hit = self._download_direct(pack_name)
            if hit:
                self.stats["cdn"] += 1
                return hit
            hit = self._download_via_metapack(pack_name)
            if hit:
                self.stats["metapack"] += 1
                return hit
        self.stats["missing"] += 1
        return None


# Chars forbidden on FAT/exFAT (Android shared storage) + path separators
_ILLEGAL_CHARS = '\\/:*?"<>|'


def sanitize(name):
    """Make a filesystem-safe name (asset paths can contain §, \\, [ etc.).
    Only truly-illegal chars (\\ / : * ? " < > | and control chars) become _;
    everything else (§ { [ ] ; # ~ + ...) is kept as-is.
    Note: surviving special chars may need quoting in the Termux shell."""
    safe = "".join("_" if (c in _ILLEGAL_CHARS or ord(c) < 32) else c for c in name)
    safe = safe.strip(" .")          # trim trailing spaces/dots (Windows / some FS)
    return safe or "asset"


# ============================================================
# Selection input parser (same rules as costume_addon_installer.py)
# ============================================================

def parse_selection(user_input, max_n):
    """Parse a selection string into a 1-based index list.
    Supports: 'all'/'a'/'*', '3', '1,4,7', '4-8', '1, 4-8, 14-23' ('8-4' -> 4-8)."""
    text = user_input.strip().lower()
    if text in ("all", "a", "*"):
        return list(range(1, max_n + 1))
    chosen, seen = [], set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise ValueError(f"invalid range: '{token}'")
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                start, end = end, start
            if start < 1 or end > max_n:
                raise ValueError(f"out of range (1-{max_n}): '{token}'")
            nums = range(start, end + 1)
        else:
            if not token.isdigit():
                raise ValueError(f"invalid number: '{token}'")
            num = int(token)
            if not (1 <= num <= max_n):
                raise ValueError(f"out of range (1-{max_n}): '{token}'")
            nums = (num,)
        for n in nums:
            if n not in seen:
                seen.add(n)
                chosen.append(n)
    if not chosen:
        raise ValueError("nothing selected")
    return chosen


def ask_selection(prompt, max_n):
    while True:
        try:
            return parse_selection(input(prompt), max_n)
        except ValueError as e:
            print(f"  input error: {e}. Try again.")


# ============================================================
# Extraction core
# ============================================================

# table -> per-category subfolder name. Falls back to the table name.
CATEGORY_DIRS = {
    "member_model": "3d_model",            # 3D models / costumes
    "member_sd_model": "sd_model_2d",
    "live2d_sd_model": "live2d_sd_model",
    "texture": "texture",
    "background": "background",
    "stage": "stage",
    "stage_effect": "stage_effect",
}


def category_dir(table):
    """Return the per-category subfolder name for a table."""
    return CATEGORY_DIRS.get(table, table)


def extract_one(resolver, out_dir, table, asset_path, pack_name, head, size,
                key1, key2, used_names, manifest, file_label=None):
    """Decrypt one asset and write it into out_dir/<category>/. Reports success/failure.
    The resolver finds the pack in packs/, or copies/downloads it into packs/ first.
    file_label (when given) is used for the on-disk filename; the manifest still
    records the real asset_path so nothing is lost."""
    pack_path = resolver.resolve(pack_name)
    if pack_path is None:
        print(f"  [skip] {asset_path}: pack '{pack_name}' not found (local + CDN)")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, "", "MISSING_PACK"))
        return False
    try:
        with open(pack_path, "rb") as f:
            f.seek(head)
            section = bytearray(f.read(size))
        if len(section) < size:
            print(f"  [warn] {asset_path}: pack is truncated ({len(section)}/{size}B)")
        decrypt_section(section, FIXED_KEY0, key1, key2)
        ext = detect_extension(section)
        if ext == ".bin":   # decrypted data isn't a known format -> something is off
            print(f"  [warn] {asset_path}: decrypted data isn't a known type "
                  f"(wrong DB platform/keys, or metapack offset?)")

        # create the per-category subfolder
        cat = category_dir(table)
        cat_path = os.path.join(out_dir, cat)
        os.makedirs(cat_path, exist_ok=True)

        base_name = sanitize(file_label if file_label else asset_path)
        out_name = base_name + ext
        rel = os.path.join(cat, out_name)
        if rel in used_names:                      # disambiguate with head (per folder)
            out_name = f"{base_name}_{head}{ext}"
            rel = os.path.join(cat, out_name)
        n = 1
        while rel in used_names:
            out_name = f"{base_name}_{head}_{n}{ext}"
            rel = os.path.join(cat, out_name)
            n += 1
        used_names.add(rel)

        out_path = os.path.join(cat_path, out_name)
        with open(out_path, "wb") as f:
            f.write(section)
        print(f"  [ok]   {asset_path}  ->  {rel}  ({size}B, key {key1}/{key2})")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, rel, "OK"))
        return True
    except Exception as e:
        print(f"  [fail] {asset_path}: {e}")
        manifest.append((table, asset_path, pack_name, head, size, key1, key2, "", f"ERROR:{e}"))
        return False


def write_manifest(out_dir, manifest):
    """Write an extraction log CSV for traceability."""
    import csv
    path = os.path.join(out_dir, "_extract_manifest.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "asset_path", "pack_name", "head", "size",
                    "key1", "key2", "output_file", "status"])
        w.writerows(manifest)
    print(f"\nLog written: {path}")


def print_resolver_stats(resolver):
    """Show where the packs came from this run."""
    s = resolver.stats
    bits = []
    if s["packs"]:
        bits.append(f"{s['packs']} from packs/")
    if s["copied"]:
        bits.append(f"{s['copied']} copied into packs/")
    if s["cdn"]:
        bits.append(f"{s['cdn']} downloaded from CDN")
    if s["metapack"]:
        bits.append(f"{s['metapack']} via metapack")
    if s["missing"]:
        bits.append(f"{s['missing']} not found")
    if bits:
        print("Packs: " + ", ".join(bits))


# ============================================================
# DB discovery
# ============================================================

def table_has_columns(conn, table, cols):
    try:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    have = {row[1] for row in info}
    return all(c in have for c in cols)


def list_asset_dbs(base_dir):
    """Find assets/db/**/asset_*.db."""
    found = []
    db_root = os.path.join(base_dir, "assets", "db")
    for root, _dirs, files in os.walk(db_root):
        for fn in files:
            if fn.startswith("asset_") and fn.endswith(".db"):
                found.append(os.path.join(root, fn))
    return sorted(found)


def choose_asset_db(base_dir):
    dbs = list_asset_dbs(base_dir)
    if not dbs:
        print(f"No asset DB found under: {os.path.join(base_dir, 'assets', 'db')}")
        print("(check that --base points at the elichika root)")
        sys.exit(1)
    print("\nChoose the asset DB to use (asset_a_* = Android, asset_i_* = iOS):")
    for i, db in enumerate(dbs, 1):
        print(f"  {i}. {os.path.relpath(db, base_dir)}")
    idx = ask_selection("Enter number (one only): ", len(dbs))[0]
    return dbs[idx - 1]


def find_masterdata(base_dir):
    for loc in ("gl", "jp"):
        p = os.path.join(base_dir, "assets", "db", loc, "masterdata.db")
        if os.path.isfile(p):
            return p
    return None


def find_dictionary(base_dir):
    """Dictionary DB for showing costume names. Prefer English, then others."""
    order = ["dictionary_en_k.db", "dictionary_ko_k.db",
             "dictionary_ja_k.db", "dictionary_zh_k.db"]
    for loc in ("gl", "jp"):
        for fn in order:
            p = os.path.join(base_dir, "assets", "db", loc, fn)
            if os.path.isfile(p):
                return p
    return None


# ============================================================
# Mode 1: character -> costume (costume_clone.py style)
# ============================================================

def real_costume_name(dict_conn, name_key):
    if dict_conn is None or not name_key:
        return name_key
    clean = name_key[2:] if name_key.startswith("k.") else name_key
    try:
        row = dict_conn.execute(
            "SELECT message FROM m_dictionary WHERE id = ?", (clean,)).fetchone()
        return row[0] if row and row[0] else name_key
    except sqlite3.Error:
        return name_key


_CHCO_RE = re.compile(r"ch\d+_co\d+", re.IGNORECASE)


def costume_code(md_conn, model_path):
    """The canonical chNNNN_coNNNN code for a costume (the identifier modders and
    GameBanana use), parsed from its thumbnail / model asset paths in m_suit.
    Falls back to id<suit_id> so the filename still carries a useful, complete,
    unique reference; '' only if the costume can't be found."""
    if md_conn is None or not model_path:
        return ""
    try:
        row = md_conn.execute(
            "SELECT id, thumbnail_image_asset_path, model_asset_path FROM m_suit "
            "WHERE model_asset_path = ? LIMIT 1", (model_path,)).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    suit_id, thumb, model = row
    for src in (thumb, model):
        if src:
            m = _CHCO_RE.search(str(src))
            if m:
                return m.group(0).lower()
    return f"id{suit_id}" if suit_id is not None else ""


def mode_costume(base_dir, out_dir, asset_db, pack_roots, cdn_base):
    md_path = find_masterdata(base_dir)
    if md_path is None:
        print("Could not find masterdata.db, so costume mode is unavailable.")
        return
    if not table_has_columns(sqlite3.connect(asset_db), "member_model",
                             ["asset_path", "pack_name", "head", "size", "key1", "key2"]):
        print(f"The selected DB has no member_model table: {asset_db}")
        return

    md = sqlite3.connect(md_path)
    dict_conn = None
    dp = find_dictionary(base_dir)
    if dp:
        dict_conn = sqlite3.connect(dp)
    asset = sqlite3.connect(asset_db)
    resolver = PackResolver(pack_roots, COPIED_PACKS_DIR, cdn_base, asset)

    # Character selection
    print("\nCharacters:")
    keys = list(CHARACTERS.keys())
    line = []
    for i, cid in enumerate(keys, 1):
        line.append(f"{cid}:{CHARACTERS[cid]}")
        if i % 6 == 0:
            print("  " + "  ".join(line)); line = []
    if line:
        print("  " + "  ".join(line))
    chara = input("\nEnter character ID: ").strip()
    if not chara.isdigit() or int(chara) not in CHARACTERS:
        print("Invalid character ID."); return
    chara = int(chara)

    # Costume list for that character (m_suit)
    rows = md.execute(
        "SELECT id, name, model_asset_path FROM m_suit "
        "WHERE member_m_id = ? AND name NOT LIKE '%_cloned' "
        "ORDER BY display_order", (chara,)).fetchall()
    if not rows:
        print("No costumes found."); return

    print(f"\n{CHARACTERS[chara]} costumes:")
    print("=" * 78)
    listing = []
    for idx, (suit_id, name_key, model_path) in enumerate(rows, 1):
        rname = real_costume_name(dict_conn, name_key)
        listing.append((suit_id, name_key, model_path, rname))
        print(f"  [{idx:2}] {rname}   (model: {model_path})")
    print("=" * 78)

    chosen = ask_selection("Costumes to extract ('3', '1,4-8', 'all'): ", len(listing))

    used, manifest = set(), []
    ok = 0
    print(f"\n-> extracting to {out_dir}")
    for n in chosen:
        suit_id, name_key, model_path, rname = listing[n - 1]
        mm = asset.execute(
            "SELECT pack_name, head, size, key1, key2 FROM member_model "
            "WHERE asset_path = ?", (model_path,)).fetchone()
        if mm is None:
            print(f"  [skip] {rname}: '{model_path}' not in member_model")
            continue
        pack_name, head, size, key1, key2 = mm
        # Name the file with useful, complete identifiers — character, the
        # canonical chNNNN_coNNNN code, and the costume name — instead of the
        # cryptic internal model path (which stays in the manifest).
        code = costume_code(md, model_path)
        label = sanitize("_".join(p for p in (CHARACTERS[chara], code, rname) if p))
        if extract_one(resolver, out_dir, "member_model", model_path, pack_name,
                       head, size, key1, key2, used, manifest, file_label=label):
            ok += 1
    if manifest:
        write_manifest(out_dir, manifest)
    print(f"\nDone. {ok} ok / {len(chosen)} selected")
    print_resolver_stats(resolver)
    resolver.cleanup()
    md.close(); asset.close()
    if dict_conn:
        dict_conn.close()


# ============================================================
# Mode 2: pick an asset table directly
# ============================================================

def mode_table(base_dir, out_dir, asset_db, pack_roots, cdn_base):
    conn = sqlite3.connect(asset_db)
    resolver = PackResolver(pack_roots, COPIED_PACKS_DIR, cdn_base, conn)
    cols = ["asset_path", "pack_name", "head", "size", "key1", "key2"]
    avail = [(t, d) for t, d in ENCRYPTED_TABLES if table_has_columns(conn, t, cols)]
    if not avail:
        print("This DB has no extractable encrypted tables."); return

    print("\nChoose an asset type (table) to extract:")
    for i, (t, d) in enumerate(avail, 1):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {i:2}. {d}  [{t}] ({cnt} entries)")
    t_idx = ask_selection("Table number (one only): ", len(avail))[0]
    table = avail[t_idx - 1][0]

    rows = conn.execute(
        f"SELECT asset_path, pack_name, head, size, key1, key2 FROM {table} "
        "ORDER BY asset_path").fetchall()
    if not rows:
        print("No entries."); return

    # tables can be large, so offer a filter
    flt = input(f"\n[{table}] {len(rows)} entries. Filter by asset_path (substring, blank = all): ").strip()
    if flt:
        rows = [r for r in rows if flt.lower() in (r[0] or "").lower()]
        if not rows:
            print("Nothing matches the filter."); return

    print(f"\n[{table}] {len(rows)} candidates:")
    show = rows if len(rows) <= 200 else rows[:200]
    for idx, (ap, pn, hd, sz, k1, k2) in enumerate(show, 1):
        print(f"  [{idx:3}] {ap:<14} pack={pn} head={hd} size={sz}")
    if len(rows) > 200:
        print(f"  ... (showing first 200. Narrow with a filter, or 'all' to extract all {len(rows)})")

    chosen = ask_selection("Entries to extract ('3', '1,4-8', 'all'): ", len(rows))

    used, manifest = set(), []
    ok = 0
    print(f"\n-> extracting to {out_dir}")
    for n in chosen:
        ap, pn, hd, sz, k1, k2 = rows[n - 1]
        if extract_one(resolver, out_dir, table, ap, pn, hd, sz, k1, k2, used, manifest):
            ok += 1
    if manifest:
        write_manifest(out_dir, manifest)
    print(f"\nDone. {ok} ok / {len(chosen)} selected")
    print_resolver_stats(resolver)
    resolver.cleanup()
    conn.close()


# ============================================================
# Main
# ============================================================

def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


def default_out_dir(base_dir):
    if is_termux():
        return os.path.expanduser("~/storage/downloads/sukusta/extracted")
    return os.path.join(base_dir, "extracted")


def main():
    ap = argparse.ArgumentParser(
        description="elichika/LLAS asset extractor (auto DB key lookup + costume/table selection)")
    ap.add_argument("--base", default=".",
                    help="elichika root (folder containing assets/db and static). Default: current folder")
    ap.add_argument("--out", default=None,
                    help="output folder (per-category subfolders are created under it). "
                         "Default (termux): ~/storage/downloads/sukusta/extracted")
    ap.add_argument("--packs", action="append", default=None,
                    help="explicit assetbundle (pack) folder. Can be given multiple times. "
                         "e.g. the game's .../files/files folder. "
                         "If omitted, auto-detects the game folder + uses elichika static/")
    ap.add_argument("--cdn", default=DEFAULT_CDN_BASE,
                    help=f"CDN base URL to download missing packs from "
                         f"(<cdn><pack_name>). Default: {DEFAULT_CDN_BASE}")
    ap.add_argument("--no-cdn", action="store_true",
                    help="never touch the network; only use local packs/static/files")
    ap.add_argument("--no-index-cache", action="store_true",
                    help="don't read/write the on-disk pack index cache (always rescan)")
    ap.add_argument("--refresh-index", action="store_true",
                    help="delete cached pack indexes and rebuild them this run")
    args = ap.parse_args()

    if args.no_index_cache:
        os.environ["LLAS_NO_INDEX_CACHE"] = "1"
    if args.refresh_index:
        _clear_disk_index_cache()

    base_dir = os.path.abspath(os.path.expanduser(args.base))

    if is_termux():
        if not os.path.exists(os.path.expanduser("~/storage")):
            print("No Termux storage access. Run this first:")
            print("  termux-setup-storage   (and allow the permission)")
            sys.exit(1)

    if not os.path.isdir(os.path.join(base_dir, "assets", "db")):
        print(f"'{base_dir}' has no assets/db.")
        print("Run from the elichika root, or pass the path with --base.")
        sys.exit(1)

    out_dir = os.path.abspath(os.path.expanduser(args.out or default_out_dir(base_dir)))
    os.makedirs(out_dir, exist_ok=True)

    # Detect the game folder once; only readable ones are searched, blocked
    # ones are surfaced in the banner with the reason.
    game_candidates = detect_game_candidates()
    game_found = [p for p, s in game_candidates if s == "found"]
    game_blocked = [(p, s) for p, s in game_candidates if s != "found"]

    pack_roots = build_pack_roots(base_dir, args.packs, game_found)
    cdn_base = None if args.no_cdn else (args.cdn or None)

    print("=" * 60)
    print("LLAS asset extractor")
    print(f"  root   : {base_dir}")
    print(f"  output : {out_dir}")
    print(f"  CDN    : {cdn_base if cdn_base else '(disabled)'}")
    if cdn_base:
        dl = downloader_name()
        print(f"  fetch  : {dl}")
        if dl == "urllib":
            try:
                import ssl  # noqa: F401
            except Exception:
                print("           (warning: no curl/wget and python has no ssl -> "
                      "https downloads will fail; run 'pkg install curl')")
    print("  pack search locations (in priority order):")
    for r in pack_roots:
        mark = "[found] " if os.path.isdir(r) else "[absent]"
        print(f"    {mark} {r}")
    # Show only game folders that exist but are blocked (the useful 'why' case);
    # absent candidates are not worth cluttering the banner with.
    for p, s in game_blocked:
        if s == "no_access":
            print(f"    [no access] {p}")
            print(f"                (Android 11+ blocks this without root/Shizuku -- "
                  f"copy it into packs/, or let the CDN handle it)")
    print("=" * 60)

    # Cheap 'nothing to extract from' nudge (no full index build at startup;
    # indexes are built lazily during extraction).
    has_local = any(root_has_content_shallow(r) for r in pack_roots)
    if not has_local and not cdn_base:
        print(f"\n[!] No local packs and CDN is disabled. Copy the game's 'files'")
        print(f"    folder into {COPIED_PACKS_DIR}, then run again.")
    elif not has_local:
        print(f"\n[i] No local packs; missing ones will be downloaded from the CDN")
        print(f"    into {COPIED_PACKS_DIR} as needed.")

    asset_db = choose_asset_db(base_dir)
    print(f"Selected DB: {os.path.relpath(asset_db, base_dir)}")

    print("\nChoose an extraction mode:")
    print("  1. Character -> costume (3D models)")
    print("  2. Pick an asset table directly (models/textures/stages/skills/...)")
    mode = ask_selection("Number: ", 2)[0]
    if mode == 1:
        mode_costume(base_dir, out_dir, asset_db, pack_roots, cdn_base)
    else:
        mode_table(base_dir, out_dir, asset_db, pack_roots, cdn_base)


if __name__ == "__main__":
    main()
