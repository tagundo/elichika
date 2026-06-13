# update the server using the following process:
# - Backup userdata.db (for user data)
# - Backup serverdata.db (for events state)
# - Comletely remove elichika and reinstall
# - Restore userdata.db and serverdata.db
# - Rebuild serverdata.db to new state
# running this command also potentially remove outdated backup

mv -f userdata.db ../userdata.db.temp && \
mv -f serverdata.db ../serverdata.db.temp && \
mv -f config.json ../config.json.temp && \
echo "Backed up databases, reinstalling" && \
cd .. && rm -rf elichika2 && \
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install.sh | bash && \
echo "Restoring old databases" && \
mv userdata.db.temp elichika2/userdata.db && \
mv serverdata.db.temp elichika2/serverdata.db && \
mv config.json.temp elichika2/config.json && \
cd elichika2 && \
./elichika rebuild_assets && \
echo "Updated succesfully!"


if [ $? -eq 0 ]; then
    chmod +rwx ./bin/shortcut.sh && \
    ./bin/shortcut.sh
else
    echo "Error updating!"
fi
