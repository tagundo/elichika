#!/usr/bin/env bash
#
# Install the TEST build of elichika.
#
# This installs the "Test" branch into a SEPARATE directory (~/elichika3_test by
# default) so it can live alongside your stable ~/elichika3 install. The two do
# not share files, so trying the test build never touches your stable server.
#
# It is just a thin wrapper that sets the branch/directory and hands off to the
# normal install.sh, so all the real install logic stays in one place.
#
# Override the defaults if you want, e.g.:
#   BRANCH=Test INSTALL_NAME=elichika3_test curl -L .../install_test.sh | bash

# default to the Test branch and a dedicated directory, but allow overrides
export BRANCH="${BRANCH:-Test}"
export INSTALL_NAME="${INSTALL_NAME:-elichika3_test}"

echo "Installing the TEST build (branch: $BRANCH) into ~/$INSTALL_NAME ..."

# fetch install.sh from MAIN (the helper scripts are maintained only on main).
# BRANCH/INSTALL_NAME are exported, so the piped bash clones the Test branch's
# CODE into ~/elichika3_test using main's install logic.
curl -L "https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install.sh" | bash
