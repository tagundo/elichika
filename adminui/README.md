# adminui — elichika Database Admin WebUI

A small local browser panel for the most-used **Developer Menu** database tools,
so you can run them with clicks instead of the Termux text menu.

## Tools (first cut)

| Tool | Wraps | Input |
|------|-------|-------|
| **Backup Database** | `database_backup.py` | one click |
| **Restore Database** | `database_restore.py` | pick a backup from the list |
| **Costume Clone** | `costume_clone.py` | source char ID → pick costume → target char ID |

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
- **Costume Clone** lists a character's costumes with a read-only query, then runs
  the unchanged `costume_clone.py` as a subprocess (feeding the answers), so the
  actual DB inserts are exactly what the CLI does.
- These are **offline DB operations**: keep "Stop the elichika server first" on,
  and restart the server afterwards.
- Pure standard-library (no web framework). Same pattern as the SIFAS `webtools`
  panel.
