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
# NAME = install directory name (e.g. elichika3 or elichika3_test)
NAME="$(basename "$PWD")"
RAW="https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin"

echo "cd $PWD && ./elichika"                       > ~/run_"$NAME" && \
echo "cd $PWD && sh elichika_utility.sh"           > ~/menu_"$NAME" && \
echo "cd $PWD && curl -L $RAW/update.sh | bash"        > ~/update_"$NAME" && \
echo "cd $PWD && curl -L $RAW/basic_update.sh | bash"  > ~/basic_update_"$NAME" && \
chmod +x ~/run_"$NAME" && \
chmod +x ~/menu_"$NAME" && \
chmod +x ~/update_"$NAME" && \
chmod +x ~/basic_update_"$NAME" && \
echo "Use \"~/run_$NAME\" in termux to run the server!" && \
echo "Use \"~/menu_$NAME\" in termux to run the menu!" && \
echo "Use \"~/update_$NAME\" in termux to update the server!" && \
echo "Use \"~/basic_update_$NAME\" in termux to update the server using basic logic (slower, but works even from a really old version)!"
