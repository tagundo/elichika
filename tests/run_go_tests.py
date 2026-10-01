#!/usr/bin/env python3
"""Run Go tests from a disposable, initialized server installation."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from validate_runtime import validate_runtime


REPOSITORY = Path(__file__).resolve().parent.parent


def run(command, *, cwd, env=None):
    subprocess.run(command, cwd=cwd, env=env, check=True)


def prepare_runtime(runtime, assets, env):
    if not (assets / "db/gl/masterdata.db").is_file():
        raise RuntimeError(f"Missing Harasho databases in {assets}; initialize the assets submodule first.")
    # Dirty DBs may have already run non-idempotent historical SQL. Use original
    # tracked databases so this is also a genuine fresh-install regression check.
    run(["git", "diff", "--exit-code", "--quiet", "HEAD", "--", "db/"], cwd=assets)
    # Share Git objects read-only, but give the copy its own index and HEAD. The
    # production migration gate needs a real Git index to recognize pristine DBs.
    run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(assets), str(runtime / "assets")], cwd=REPOSITORY)
    run(["git", "read-tree", "HEAD"], cwd=runtime / "assets")
    shutil.copytree(assets, runtime / "assets", dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
    for name in ("server init jsons", "webui"):
        shutil.copytree(REPOSITORY / name, runtime / name)
    for name in ("privatekey.pem", "publickey.pem"):
        shutil.copy2(REPOSITORY / name, runtime / name)
    binary = runtime / "elichika_host"
    print(f"Preparing fresh runtime: {runtime}", flush=True)
    run(["go", "build", "-o", str(binary), "."], cwd=REPOSITORY, env=env)
    run([str(binary), "rebuild_assets"], cwd=runtime, env=env)


def run_tests(runtime, arguments, env):
    validate_runtime(runtime)
    run([sys.executable, str(runtime / "assets/tests/validate_localization.py"), "--runtime", str(runtime)], cwd=REPOSITORY, env=env)
    run(["go", "vet", "./..."], cwd=REPOSITORY, env=env)
    env = dict(env, ELICHIKA_TEST_RUNTIME=str(runtime), ELICHIKA_TEST_WRAPPER=str(REPOSITORY / "tests/run_go_test_binary.sh"))
    # Package initialization opens shared SQLite files and updates manifests.
    # Serialize packages; also keep Go test's vet checks and disable test caching.
    # Go starts -exec from each package directory. Pass the absolute wrapper via
    # the environment so paths with spaces/quotes need no Go -exec escaping.
    executor = '''sh -c 'exec sh "$ELICHIKA_TEST_WRAPPER" "$@"' go-test-runtime'''
    run(["go", "test", "-count=1", "-p", "1", "-exec", executor, *arguments], cwd=REPOSITORY, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, help="Pristine Harasho checkout (default: repository assets submodule)")
    parser.add_argument("--runtime", type=Path, help="Reuse an initialized disposable installation; tests may modify it")
    parser.add_argument("go_arguments", nargs=argparse.REMAINDER, help="Arguments after -- are passed to go test (default: ./...)")
    args = parser.parse_args()
    if args.assets and args.runtime:
        parser.error("--assets and --runtime cannot be combined")
    arguments = args.go_arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    arguments = arguments or ["./..."]
    # The server's optional JNI bridge requires an Android compiler with cgo on.
    # The host build and all tests intentionally use the portable pure-Go path.
    env = dict(os.environ, CGO_ENABLED="0")
    if args.runtime:
        run_tests(args.runtime.resolve(), arguments, env)
    else:
        assets = (args.assets or REPOSITORY / "assets").resolve()
        with tempfile.TemporaryDirectory(prefix="elichika-go-tests-") as directory:
            runtime = Path(directory)
            prepare_runtime(runtime, assets, env)
            run_tests(runtime, arguments, env)


if __name__ == "__main__":
    main()
