"""Source-bound HQ 3D thumbnails for the existing costume ZIP installer.

The browser renders through the same SDK/3D pipeline as viewer Save and the
thumbnail updater. Installation consumes only those completed, verified images;
it never substitutes a texture thumbnail when rendering fails.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile

from adminui.tools.common import ensure_repo_on_path


def ensure_webtools():
    root = Path(ensure_repo_on_path()) / "modtools"
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _require(value, message):
    if not value:
        raise ValueError(message)


def render_options(params):
    """Resolve only actual installer choices; callers cannot supply model paths."""
    ensure_webtools()
    from adminui.tools.installers import _addon_list, _locate
    from webtools.core.sukusta import default_sukusta_dir
    _require(isinstance(params, dict), "Invalid costume installation options.")
    _require(type(params.get("auto_thumbnail", True)) is bool,
             "Choose whether to generate a high-quality 3D thumbnail.")
    _require(params.get("auto_thumbnail", True), "Enable automatic 3D thumbnails before rendering.")
    fit = params.get("thumbnail_fit_full", False)
    _require(type(fit) is bool, "Choose whether to fit the full character in its thumbnail.")
    names = _addon_list(params.get("addon"))
    _require(1 <= len(names) <= 128 and len(set(names)) == len(names),
             "Choose one to 128 different costume ZIPs to install.")
    paths = []
    for name in names:
        _require(Path(name).name == name and "\\" not in name and "\0" not in name and name.lower().endswith(".zip"),
                 "Choose a costume ZIP from the installer list.")
        source = _locate("costume", name)
        _require(source is not None, "The selected costume ZIP was not found: " + name)
        paths.append(str(Path(source).absolute()))
    return {"mode": "multi", "in_paths": "\n".join(paths),
            "out_dir": str(Path(default_sukusta_dir(".installer-thumbnails")).resolve()),
            "thumbnail_size": 256, "variant": "auto", "thumbnail_fit_full": fit}


def plan(params):
    ensure_webtools()
    from webtools.core import mod_thumbnail_replace, viewer_thumbnails
    options = render_options(params)
    for source in options["in_paths"].splitlines():
        try:
            mod_thumbnail_replace.inspect(source)
        except (ValueError, OSError) as error:
            raise ValueError(Path(source).name + ": " + str(error)) from error
    return viewer_thumbnails.plan({"kind": "updater", "params": options})


@contextmanager
def install_inputs(job, params):
    """Prepare every selected ZIP before the first server stop or DB write."""
    ensure_webtools()
    from adminui.tools.installers import _addon_list, _dirs, _file_sha256, INSTALLERS
    from webtools.core import mod_thumbnail_replace, viewer_thumbnails
    options = render_options(params)
    provider = viewer_thumbnails.updater_provider(dict(options, thumbnail_plan=params.get("thumbnail_plan")))
    root = Path(options["out_dir"])
    _require(not root.is_symlink(), "The thumbnail staging folder cannot be a symbolic link.")
    root.mkdir(parents=True, exist_ok=True)
    prepared = {}
    with tempfile.TemporaryDirectory(prefix="install-", dir=root) as temporary:
        try:
            sources = options["in_paths"].splitlines()
            for index, (name, source) in enumerate(zip(_addon_list(params.get("addon")), sources)):
                _require(not job.should_stop(), "Thumbnail preparation was cancelled before installation.")
                job.log("[costume] Preparing high-quality 3D thumbnail: " + name)
                try:
                    result = mod_thumbnail_replace.replace(source, temporary, provider(source),
                        size=256, variant="auto", should_stop=job.should_stop)
                except (ValueError, OSError) as error:
                    raise ValueError(name + ": " + str(error)) from error
                prepared[name] = result
                job.log("COSTUME_INSTALL_THUMBNAIL " + json.dumps({key: result[key] for key in
                    ("source_sha256", "thumbnail_sha256", "character_id", "quality", "originals_preserved")}, sort_keys=True))
                job.progress(index + 1, len(sources))
            _require(not job.should_stop(), "Thumbnail preparation was cancelled before installation.")
            for name, result in prepared.items():
                _require(not job.should_stop(), "Thumbnail preparation was cancelled before installation.")
                _require(_file_sha256(result["source_path"]) == result["source_sha256"],
                         "The selected costume ZIP changed after its thumbnail was rendered: " + name)
                _require(_file_sha256(result["output_path"]) == result["sha256"],
                         "The prepared thumbnail ZIP changed before installation: " + name)
            _require(not job.should_stop(), "Thumbnail preparation was cancelled before installation.")
            yield prepared
        finally:
            # Legacy installers scan their own folders. Remove only our unique,
            # byte-identical staging copies; uploaded ZIPs are never changed.
            for result in prepared.values():
                name = Path(result["output_path"]).name
                for folder in _dirs(INSTALLERS["costume"]):
                    copy = Path(folder) / name
                    try:
                        if not copy.is_symlink() and copy.is_file() and _file_sha256(copy) == result["sha256"]:
                            copy.unlink()
                    except OSError:
                        pass
