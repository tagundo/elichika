"""Server-contents adapter for verified official costume CDN restoration."""
from pathlib import Path

from adminui import i18n
from adminui.serverctl import installation_server
from adminui.tools.common import ensure_repo_on_path


def _module():
    ensure_repo_on_path()
    import costume_cdn_restore
    return costume_cdn_restore


def _root():
    from adminui.jobs import MANAGER
    return Path(MANAGER._runtime_root)


def costume_cdn_options(params):
    return _module().costume_options(_root(), region=params.get("region"),
        platform=params.get("platform", "both"), character=params.get("character", ""),
        search=params.get("search", ""), language=i18n.normalize(params.get("lang")) or "en")


def _translate(text, lang):
    text = str(text)
    for prefix in ("Downloading the original costume pack: ", "Recovery backup: ",
                   "The original CDN could not provide package ",
                   "The original CDN download failed. Check your connection and retry: ",
                   "The downloaded original model could not be verified: "):
        if text.startswith(prefix):
            return i18n.tr(prefix, lang) + text[len(prefix):]
    return i18n.tr(text, lang)


class _LocalizedJob:
    def __init__(self, job, lang):
        self.job, self.lang = job, lang
    def __getattr__(self, name):
        return getattr(self.job, name)
    def log(self, value):
        self.job.log(_translate(value, self.lang))


def run_costume_cdn(job, params):
    language = i18n.normalize(params.get("lang")) or "en"
    selected = params.get("costume")
    if not isinstance(selected, str) or not selected:
        raise ValueError(i18n.tr("Choose an original costume to restore.", language))
    module = _module()
    active = _LocalizedJob(job, language)
    try:
        # A running game server can hold stale availability/catalogue state.
        # Stop it before touching packs; the user can restart after completion.
        from adminui import serverctl
        managed = serverctl._controller is not None
        result = module.restore_costume(active, root=_root(), suit=selected,
            region=params.get("region"), platform=params.get("platform", "both"), language=language,
            publication_context=lambda: installation_server(active.log, stop=True, restart=managed))
    except module.RestoreCancelled as error:
        return _translate(str(error), language)
    except ValueError as error:
        raise ValueError(_translate(str(error), language)) from error
    return (i18n.tr("Original costume restored. Load it again through Game assets; already-open models and unsaved edits were preserved.", language)
            + " " + i18n.tr("Recovery backup: ", language) + result["backup"])
