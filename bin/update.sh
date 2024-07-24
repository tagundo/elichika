# update the server using the following process:
# - update the code (elichika)
# - update the submodules (assets)
# - rebuild the binary
# - rebuild the assets
# note that this will destroy the current state of serverdata.db
# backup you files, or better yet, make sure that serverdata.db only store derived data

git pull && \
git submodule deinit -f . && \
git submodule update --init --recursive --checkout && \
(go build || CGO_ENABLED=0 go build) && \
./elichika reinit && \
echo "Updated succesfully!"


if [ $? -eq 0 ]; then
    echo "cd $PWD && ./elichika" > ~/run_elichika2 && \
    echo "cd $PWD && sh elichika_utility.sh" > ~/menu_elichika2 && \
    echo "cd $PWD && curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/install.sh | bash"  > ~/update_elichika2 && \
    chmod +x ~/run_elichika2 && \
    chmod +x ~/update_elichika2 && \
	chmod +x ~/menu_elichika2 && \
    echo "Use \"~/run_elichika2\" in termux to run the server!" && \
    echo "Use \"~/menu_elichika2\" in termux to run the menu!" && \
    echo "Use \"~/update_elichika2\" in termux to update the server!"
else
    echo "Error updating!"
fi