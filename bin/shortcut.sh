# Setup shortcuts
echo "cd $PWD && ./elichika" > ~/run_elichika2 && \
echo "cd $PWD && sh elichika_utility.sh" > ~/menu_elichika2 && \
echo "cd $PWD && curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/install.sh | bash"  > ~/update_elichika2 && \
echo "cd $PWD && curl -L https://raw.githubusercontent.com/arina999999997/elichika/master/bin/basic_update.sh | bash"  > ~/basic_update_elichika && \
chmod +x ~/run_elichika2 && \
chmod +x ~/update_elichika2 && \
chmod +x ~/menu_elichika2 && \
chmod +x ~/basic_update_elichika2 && \
echo "Use \"~/run_elichika2\" in termux to run the server!" && \
echo "Use \"~/menu_elichika2\" in termux to run the menu!" && \
echo "Use \"~/update_elichika2\" in termux to update the server!"
echo "Use \"~/basic_update_elichika2\" in termux to update the server using basic logic (will be slower but will work even if you have a really old version)!"