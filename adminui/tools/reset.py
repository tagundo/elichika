"""Clear the downloaded CDN pack cache to free storage.

On Android the packs live in the shared Download/sukusta/packs (config
cdn_cache_dir), not in static/, so this simply empties that folder. Packs are
re-downloadable, so this is safe; anything still needed is fetched again the
next time the game plays (or via "Download missing").
"""
import json
import os
import shutil


def _pack_dir():
    d = ""
    try:
        with open("config.json", encoding="utf-8") as f:
            d = (json.load(f).get("cdn_cache_dir") or "").strip()
    except Exception:
        d = ""
    if not d:
        base = os.environ.get("SUKUSTA_DIR") or os.path.expanduser("~/storage/downloads/sukusta")
        d = os.path.join(base, "packs")
    return os.path.abspath(os.path.expanduser(d))


def run_clear_packs(job, params):
    d = _pack_dir()
    if not os.path.isdir(d):
        return f"nothing to clear — {d} does not exist yet"
    removed, freed = 0, 0
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                for root, _dirs, files in os.walk(p):
                    for fn in files:
                        try:
                            freed += os.path.getsize(os.path.join(root, fn))
                        except OSError:
                            pass
                shutil.rmtree(p)
            else:
                try:
                    freed += os.path.getsize(p)
                except OSError:
                    pass
                os.remove(p)
            removed += 1
        except OSError as exc:
            job.log(f"skip {name}: {exc}")
    job.log(f"removed {removed} item(s) from {d}")
    return (f"pack cache cleared ({freed // (1024 * 1024)} MB freed) — "
            "missing packs re-download when you play or via Download missing")
