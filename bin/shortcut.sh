# Setup shortcuts
#
# The shortcut names follow the install DIRECTORY, so a stable install in
# ~/elichika3 creates ~/run_elichika3 / ~/update_elichika3 / ..., and a test
# install in ~/elichika3_test creates ~/run_elichika3_test / ~/update_elichika3_test
# / ... - both can coexist.
#
# The update commands always pull the helper scripts from the *main* branch (the
# scripts are maintained only there). They still operate on THIS directory, and
# update.sh/basic_update.sh act on whatever branch this copy tracks (git pull /
# reinstall of the same branch), so a test install keeps tracking the Test code.
#
# Works on Termux/Android, macOS, Linux and Windows (Git Bash/MSYS/Cygwin).
#
# NAME = install directory name (e.g. elichika3 or elichika3_test)
NAME="$(basename "$PWD")"
RAW="https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin"

# The server binary is "elichika" everywhere except Windows, where Go produces
# "elichika.exe". Detect it from whatever was actually built.
BIN="./elichika"
[ -f ./elichika.exe ] && BIN="./elichika.exe"

echo "cd $PWD && $BIN"                                  > ~/run_"$NAME" && \
echo "cd $PWD && sh elichika_utility.sh"               > ~/menu_"$NAME" && \
echo "cd $PWD && curl -L $RAW/update.sh | bash"        > ~/update_"$NAME" && \
echo "cd $PWD && curl -L $RAW/basic_update.sh | bash"  > ~/basic_update_"$NAME" && \
chmod +x ~/run_"$NAME" 2>/dev/null
chmod +x ~/menu_"$NAME" 2>/dev/null
chmod +x ~/update_"$NAME" 2>/dev/null
chmod +x ~/basic_update_"$NAME" 2>/dev/null
echo "Use \"~/run_$NAME\" to run the server!" && \
echo "Use \"~/menu_$NAME\" to run the menu!" && \
echo "Use \"~/update_$NAME\" to update the server!" && \
echo "Use \"~/basic_update_$NAME\" to update the server using basic logic (slower, but works even from a really old version)!"

# ---------------------------------------------------------------------------
# Double-click launchers for the menu.
#
# The repo ships self-locating launchers in the install folder:
#   elichika_menu.command  (macOS/Linux: double-click to open the menu)
#   elichika_menu.cmd      (Windows: double-click to open the menu)
#
# Make sure the .command is executable (git usually keeps the bit, but a
# Windows checkout or a zip download can lose it), and drop a matching
# double-click shortcut on the Desktop so you don't even have to open the
# install folder. The Desktop shortcut just forwards to the in-folder one, so
# there is a single source of truth for the actual launch logic.
# ---------------------------------------------------------------------------
chmod +x ./elichika_menu.command 2>/dev/null

case "$(uname -s 2>/dev/null)" in
    Darwin)
        DESKTOP="$HOME/Desktop"
        if [ -d "$DESKTOP" ] && [ -f ./elichika_menu.command ]; then
            printf '#!/bin/bash\nexec "%s/elichika_menu.command"\n' "$PWD" > "$DESKTOP/menu_$NAME.command"
            chmod +x "$DESKTOP/menu_$NAME.command" 2>/dev/null
            echo "Double-click \"$DESKTOP/menu_$NAME.command\" to open the menu!"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        WINDESK="${USERPROFILE:-$HOME}/Desktop"
        [ -d "$WINDESK" ] || WINDESK="$HOME/Desktop"
        if [ -d "$WINDESK" ] && [ -f ./elichika_menu.cmd ]; then
            SELF_CMD="$(cygpath -w "$PWD/elichika_menu.cmd" 2>/dev/null || echo "$PWD/elichika_menu.cmd")"
            printf '@echo off\r\ncall "%s"\r\n' "$SELF_CMD" > "$WINDESK/menu_$NAME.cmd"
            echo "Double-click \"$WINDESK\\menu_$NAME.cmd\" to open the menu!"
        fi
        ;;
esac
