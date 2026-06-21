#!/bin/bash
# Double-clickable launcher for the Elichika menu (macOS / Linux desktop).
#
# On macOS, Finder runs *.command files in Terminal when you double-click them
# (the file just needs the execute bit, which git keeps). So instead of opening
# a terminal and typing the menu command every time, just double-click this.
#
# It cd's into its OWN folder first, so it keeps working no matter where the
# install lives or what the folder is named (elichika3, elichika3_test, ...).
cd "$(dirname "$0")" || exit 1
exec bash ./elichika_utility.sh
