# Server regression tests

Install Go 1.22, Git and Python 3 (use Git Bash on Windows), then initialize the asset submodule:

```sh
git submodule update --init --recursive
python3 assets/tests/validate_shooting_star.py
python3 assets/tests/validate_localization.py
python3 tests/run_go_tests.py
```

The SQL validators need Harasho's full history, including baseline commit
`1d24cef1d2e697a98d9785fc26bf825b36b44978`. For a shallow asset checkout, run
`git -C assets fetch --unshallow` first.

The Go runner copies the pristine asset checkout and server JSON files into a
temporary installation, builds the host server, runs `rebuild_assets`, and checks
that both locale databases contain usable lesson drops and all 29 Shooting Star
mappings. It then runs `go vet ./...` with its full default analyzer set and
`go test -count=1 -p 1 -exec ... ./...`, also keeping Go test's vet checks enabled,
with `CGO_ENABLED=0`. This runs the lesson loader, real lesson
execution/persistence and database upgrade regressions, plus all other Go tests.
Packages run sequentially because initialization writes shared runtime files.
The temporary installation is deleted when the command finishes, including on
failure. The source checkout, client databases and any installed user data are
never changed. Go may populate its usual module and build caches.

The source `assets/db` must match its Git commit; a previously initialized
installation cannot serve as a fresh fixture because historical SQL is not
idempotent. Uncommitted source SQL and dictionary edits are copied into the
fixture so they can be checked before committing. To use another pristine
Harasho worktree, or run a selected package:

```sh
python3 tests/run_go_tests.py --assets /path/to/harasho -- ./gamedata ./subsystem/user_lesson ./clientdb/upgrades
```

Android CI already rebuilds a fresh disposable checkout for its APK payload. It
uses the same readiness check and runner without copying/rebuilding a second
installation:

```sh
python3 tests/validate_runtime.py /path/to/disposable/runtime
python3 tests/run_go_tests.py --runtime /path/to/disposable/runtime
```

`--runtime` allows package initialization to write there; use it only for a
disposable build directory. APK CI fails if the host rebuild or readiness check
fails, even though a production server can continue training after an optional
animation upgrade fails.

The runner also validates the prepared GL English, Korean and Chinese dictionary
databases against the localization upgrade data. Android CI checks these files
after rebuilding, so an optional text upgrade failure cannot silently ship an
uncorrected payload.
