# install the latest version of elichika from scratch
# set the environmental variable BRANCH to pick a specific branch (latest version only)
# this can be set with export or just set when invoking bash
# Honestly this is only for testing but you can think of it as a hidden feature
# if BRANCH is not provided, then default to main
BRANCH=${BRANCH:-"main"}
# install git and golang
clear
echo "Installing Elichika... PLEASE DO NOT DISCONNECT INTERNET"
echo "Download speed too slow? close installer by CTRL+C then use 1.1.1.1 and try again"
cd
rm -rf elichika_tatara_hisoka
pkg install golang git -y || echo "assuming go and git are already installed"
pkg install git -y || echo "assuming go and git are already installed"
pkg install python -y || echo "assuming go and git are already installed"
# clone the source code
git clone --depth 1 --branch $BRANCH --single-branch https://gitlab.com/tatara_hisoka/elichika.git elichika_tatara_hisoka && \
cd elichika_tatara_hisoka && \
# get the submodules (i.e. assets and other)
git submodule update --init --remote && \
# build server, fallback to not using CGO to work on some devices
echo "Building executable, it takes 5 - 15 minutes+ depend your phone"
(go build || CGO_ENABLED=0 go build) && \
# set the permission
chmod +rx elichika && \
chmod +rx elichika_utility.sh && \
echo "Installed succesfully!"
echo ""
echo "You can start new or use exist by select transfer with password"
echo "Enter this ID"
echo "ID: 26092019 (jp) | 25022020 (gl)"
echo ""
if [ $? -eq 0 ]; then
    echo "cd $PWD && ./elichika" > ~/run_elichika_gitlab && \
    echo "cd $PWD && sh elichika_utility.sh" > ~/menu_elichika_gitlab && \
    echo "cd $PWD && curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/install.sh | bash"  > ~/update_elichika_gitlab && \
    chmod +x ~/run_elichika_gitlab && \
    chmod +x ~/update_elichika_gitlab && \
	chmod +x ~/menu_elichika_gitlab && \
    echo "Use \"~/run_elichika_gitlab\" in termux to run the server!" && \
    echo "Use \"~/menu_elichika_gitlab\" in termux to run the menu!" && \
    echo "Use \"~/update_elichika_gitlab\" in termux to update the server!"
else
    echo "Error installing"
fi