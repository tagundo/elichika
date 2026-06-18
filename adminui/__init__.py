"""adminui - a local WebUI for elichika's Developer-Menu database tools.

Same local-first pattern as the SIFAS webtools panel: a stdlib http.server with a
job manager + SSE, wrapping the existing admin scripts (database_backup,
database_restore, costume_clone) so they can be run from a browser instead of the
Termux text menu. Must be run from the elichika install directory (the scripts
use paths relative to it).
"""

__version__ = "0.1.0"
