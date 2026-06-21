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
