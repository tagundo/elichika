#!/bin/sh
# Go supplies an absolute path to the compiled test binary and its arguments.
set -eu
cd "${ELICHIKA_TEST_RUNTIME:?run through tests/run_go_tests.py}"
exec "$@"
