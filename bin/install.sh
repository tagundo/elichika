# install the latest version of elichika from scratch
# set the environmental variable BRANCH to pick a specific branch (latest version only)
# this can be set with export or just set when invoking bash
# Honestly this is only for testing but you can think of it as a hidden feature
# if BRANCH is not provided, then default to master
BRANCH=${BRANCH:-"master"}
# install git and golang
clear
echo "Installing Elichika... PLEASE DO NOT DISCONNECT INTERNET"
cd
rm -rf elichika
pkg install golang git -y || echo "assuming go and git are already installed"
pkg install git -y || echo "assuming go and git are already installed"
pkg install python -y || echo "assuming go and git are already installed"
# clone the source code
git clone --depth 1 https://gitlab.com/tatara_hisoka/elichika.git --branch $BRANCH --single-branch && \
cd elichika && \
# get the submodules (i.e. assets and other)
git submodule update --init --remote && \
# build server, fallback to not using CGO to work on some devices
(go build || CGO_ENABLED=0 go build) && \
# set the permission
chmod +rx elichika && \
echo "Installed succesfully!"
echo ""
echo "You can start new or use exist by select transfer with password"
echo "Enter this ID"
echo "ID: 26092019 (jp) | 25022020 (gl)"
echo ""
if [ $? -eq 0 ]; then
    echo "cd $PWD && sh elichika_utility.sh" > ~/run_elichika && \
    echo "cd $PWD && git pull && \
    git submodule deinit -f . && \
    git submodule update --init --recursive --checkout && \
    (go build || CGO_ENABLED=0 go build)" > ~/update_elichika && \
    chmod +x ~/run_elichika && \
    chmod +x ~/update_elichika && \
    echo "Use \"~/run_elichika\" in termux to run the menu!" && \
    echo "Use \"~/update_elichika\" in termux to update the server!"
else
    echo "Error installing"
fi