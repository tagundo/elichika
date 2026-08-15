# Updating the asset repository on a server that already runs

*This is considered [advanced usage](advanced_usage.md).*

New elichika versions sometimes ship changes to the master data as SQL migrations in the
asset repository (`assets/sql/`). On a **fresh** install those apply by themselves on the
first start. On a server that has **already run**, they silently do not.

This page explains why, and how to pick up the new data either way.

## Why a running server does not pick them up

`clientdb` applies a migration to a client database only while that database is still
pristine. It decides that with git, in `clientdb/is_not_changed_normal.go`:

```
git diff --exit-code --quiet db/jp/masterdata.db
```

Unmodified (exit 0) means "the migrations have not been applied yet, run them". Modified
means "already applied, skip". That is what stops the migrations re-running on every
start and hitting `UNIQUE constraint` errors.

The consequence is that the very first start makes every client database modified, so
from then on **no new migration will ever be applied to them** until the databases are
put back to their committed state.

Nothing warns you about this on its own. A feature whose data is missing just behaves as
if it were switched off. The lesson drop tables are an example: without them, lessons
still work but drop no insight skills at all, and the server log says so on start:

```
Lesson drop tables missing from masterdata: [m_lesson_drop_amount ...]
Lessons will use the built-in drop amounts and will not drop insight skills.
Reset the asset repository so the sql migrations run again to get them.
```

## Which route to take

|                                                    | Route |
|----------------------------------------------------|-------|
| You have never hand-modified the databases          | [Full reset](#full-reset) |
| You have installed cards, costumes, lives, or edited the database yourself | [Apply just the new migration](#apply-just-the-new-migration) |

**A full reset throws away every change made to the databases**, including everything the
installer scripts (`card_addon_installer.py`, `costume_addon_installer.py`,
`live_addon_installer.py`, …) have written. See
[modifying database](modify_database.md), which already recommends keeping your own
changes as SQL scripts so you can replay them.

Back the databases up before doing either of these:

```sh
cp -r assets/db assets/db.backup
```

## Full reset

Stop the server first.

The WebUI does this for you: the update button in the admin UI runs `git pull`, then
deinitialises and re-checks-out the `assets` submodule, rebuilds, and runs
`rebuild_assets`. The deinit is what restores the databases, so the migrations run again.

By hand, from the elichika directory:

```sh
git pull                                              # get the new elichika + submodule pin
git submodule deinit -f assets                        # discard the asset working tree
git submodule update --init --recursive --checkout assets
go build
./elichika rebuild_assets                             # applies every migration, rebuilds serverdata.db
```

If you only need the databases restored, without moving the submodule pin:

```sh
git -C assets checkout -- db/
./elichika rebuild_assets
```

Every migration runs from the committed EOS databases upwards, not just the new one, so
this takes a couple of minutes.

## Apply just the new migration

This keeps your modified databases and adds only the new tables. Stop the server, then
from the elichika directory:

```sh
git -C assets pull                                    # get the new sql file

# apply the shared migration to both regions
for region in jp gl; do
  sqlite3 "assets/db/$region/masterdata.db" < assets/sql/001.masterdata.db.sql
done

./elichika rebuild_assets
```

Without the `sqlite3` command available, python does the same job:

```sh
python3 - <<'PY'
import sqlite3
sql = open('assets/sql/001.masterdata.db.sql', encoding='utf-8').read()
for region in ('jp', 'gl'):
    con = sqlite3.connect(f'assets/db/{region}/masterdata.db')
    con.executescript(sql)
    con.commit()
    con.close()
PY
```

Two things to know:

- Pick the right file. `assets/sql/<order>.<database>.sql` at the root of `sql/` applies to
  every region; the ones under `assets/sql/gl/` and `assets/sql/jp/` are region specific and
  the file name says which database they belong to.
- This is not idempotent. Running it twice fails on `CREATE TABLE`, because the table is
  already there. That is harmless — the first run already did the work — but if you want to
  re-run it cleanly, drop the tables it creates first.

## Checking it worked

The server log on start is the quickest signal. `Loading Lesson` with **no**
`Lesson drop tables missing` line after it means the data is in place.

To check directly:

```sh
sqlite3 assets/db/jp/masterdata.db \
  "SELECT has_exclusive, weight FROM m_lesson_skill_no_drop ORDER BY has_exclusive;"
```

Expected:

```
0|5896
1|1898
```

And in game: run a lesson a few times. You should get at most one insight skill per run,
where before the fix the result screen offered a fixed list on every single run.

## Note for the Android app

None of this applies to the standalone APK. It ships databases that CI already migrated,
so a fresh install is already up to date — installing the new APK is the whole procedure.
See [the Android app doc](android_app.md).
