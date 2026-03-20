# install the latest version of elichika from scratch
# set the environmental variable BRANCH to pick a specific branch (latest version only)
# this can be set with export or just set when invoking bash
# Honestly this is only for testing but you can think of it as a hidden feature
# if BRANCH is not provided, then default to master
BRANCH=${BRANCH:-"main"}
clear

echo "Requesting storage permission..."

# safer permission loop
while true; do
    termux-setup-storage
    sleep 3

    if [ -d "$HOME/storage/shared" ]; then
        echo "Storage permission granted."
        break
    else
        echo "Storage permission NOT granted. Please allow it."
    fi

    sleep 2
done
echo "Installing elichika2..."
# install git and golang
pkg install golang git python -y || echo "assuming go, git and python are already installed"
# clone the source code
rm -rf elichika2
git clone --depth 1 --branch $BRANCH --single-branch https://gitlab.com/tatara_hisoka/elichika.git elichika2 && \
cd elichika2 && \
# get the submodules (i.e. assets and other)
git submodule update --init assets && \
# build server, fallback to not using CGO to work on some devices
(CGO_ENABLED=0 go build -o elichika || go build) && \
# set the permission
chmod +rx elichika && \
chmod +rx elichika_utility.sh && \
echo "Installed succesfully!"

if [ $? -eq 0 ]; then
    chmod +rwx ./bin/shortcut.sh && \
    ./bin/shortcut.sh
else
    echo "Error installing"
fi