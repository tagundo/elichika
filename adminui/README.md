# adminui — elichika Database Admin WebUI

A small local browser panel for the most-used **Developer Menu** database tools,
so you can run them with clicks instead of the Termux text menu.

## Tools (first cut)

| Tool | Wraps | Input |
|------|-------|-------|
| **Backup Database** | `database_backup.py` | one click |
| **Restore Database** | `database_restore.py` | pick a backup from the list |
| **Costume Clone** | `costume_clone.py` | source → costume → check one or several target characters |
| **Remove Costume / Clone** | `costume_management.py` | review affected records → back up and remove |

Each shows a live log + progress and can stop the elichika server first (these
tools modify the server's database files).

## Run it

From the elichika install directory:

```bash
python -m adminui
```

Open the printed URL (default `http://127.0.0.1:8772/`). On desktop a browser
opens automatically. The panel `chdir`s to the install dir, because the wrapped
scripts use paths relative to it.

Options: `--host 0.0.0.0` (LAN), `--port 8772`, `--no-browser`.

## Notes

- **Backup / Restore** call the scripts' real functions directly
  (`backup_database_files`, `list_backup_folders`, `restore_from_backup`), so the
  behaviour is identical to the CLI. Restore auto-backs up the current state first.
- **Costume Clone** imports `costume_clone.py` and calls its `list_costumes` /
  `clone_costumes` functions directly (the script is import-safe; its interactive
  CLI lives under `__main__`), so the behaviour matches the CLI. The clone
  gives each copy independent model assets, including its face and animation
  model dependencies, and preserves the source's platform, mask views and colour
  attachments. Shader dependencies remain shared. It resolves source packs locally or from
  the CDN, validates them before changing databases, then backs up and stages
  the writes. A database backup covers recovery from a partial commit failure.
  A batch backs up once, isolates each target separately, and reports completed,
  failed and unattempted targets without claiming the whole batch succeeded.
- **Remove Costume / Clone** first reviews references and requires a second
  removal action. Optional default replacement changes supported HOME/live/MV
  suit references while retaining their characters, cards, poses and other
  slots. It verifies the official per-character default and account ownership;
  ambiguous references remain blocked. The database snapshots and quarantined
  files stay under `.costume-management/deletions` for recovery.
  Original game costumes are hidden unless the advanced option is checked and
  require an additional confirmation popup. Game-required defaults, card/reward
  references and other unresolved dependencies remain protected even then.
  Unknown/shared files and dictionaries are retained. Legacy custom costumes
  require the stock index packaged from the clean initialized build; never
  generate that index from an installed, modded database.
- Rina's corrected HOME scaling uses a scene Mod ZIP with separate HOME,
  board-MV and unmasked-MV models. Reopen an old modified ZIP in the updated
  viewer, save a new Mod ZIP, add it to the game and select the added costume.
  Existing installed costumes are not silently rewritten. The ZIP preserves
  canonical originals and edit recipes so repeat saves and Node/Mesh changes
  do not accumulate scaling; native platforms are retained without conversion.
- Managed apps refuse game-data preparation and Go startup while a costume
  operation is incomplete. HTTP backup/editing tools remain available. Do not
  delete recovery journals to force a start: keep their snapshots and files for
  verified recovery. Restoring an unrelated DB backup alone does not establish
  that a pending multi-file costume transaction was fully rolled back.
- These tools write installation data: keep "Stop the elichika server first" on,
  and restart the server afterwards. Install Costume in the Android app also
  offers automatic restart after a successful batch. This option stops the
  server even if the separate stop checkbox is off, and restarts only a server
  that was running beforehand. Failed installs and manual Stop keep it off.
  The choice is remembered on that device; automatic restart requires the app's
  server controller and is unavailable in the standalone PC / Termux panel.
- Costume extraction names each model using its owner in masterdata, including
  name-search results that span several characters. Models are saved under
  `Download/sukusta/extracted/3d_model` for the modding tools.
- Pure standard-library (no web framework). Same pattern as the SIFAS `webtools`
  panel.
