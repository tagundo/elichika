# install the latest version of elichika from scratch
#
# Environment variables (both optional, set via export or inline when invoking):
#   BRANCH        which branch's CODE to install. Defaults to "main".
#                 e.g. BRANCH=Test installs the test build's code.
#   INSTALL_NAME  directory to install into. Defaults to "elichika3".
#                 e.g. INSTALL_NAME=elichika3_test keeps the test build separate
#                 from the stable one so the two can coexist.
# Honestly the branch override is only for testing but you can think of it as a hidden feature.
#
# NOTE: the helper scripts (this one, shortcut.sh, update.sh, basic_update.sh) are
# maintained on the *main* branch only. Only the game CODE comes from $BRANCH, so a
# test build clones the Test branch's code but still uses main's helper scripts.
# That is why we fetch shortcut.sh from main below instead of running the copy that
# was checked out from $BRANCH (which may be older).
BRANCH=${BRANCH:-"main"}
INSTALL_NAME=${INSTALL_NAME:-"elichika3"}

# (Re)generate the termux shortcuts using main's generator (see NOTE above).
gen_shortcuts() {
    _sc="$(mktemp 2>/dev/null || echo /tmp/elichika_shortcut.sh)"
    if curl -fsSL "https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/shortcut.sh" -o "$_sc" && [ -s "$_sc" ]; then
        bash "$_sc"
    elif [ -f ./bin/shortcut.sh ]; then
        echo "Note: couldn't fetch shortcut.sh from main; using the local copy." >&2
        chmod +x ./bin/shortcut.sh
        ./bin/shortcut.sh
    fi
    rm -f "$_sc"
}
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
echo "Installing $INSTALL_NAME (branch: $BRANCH)..."
# install git and golang
pkg install golang git python -y || echo "assuming go, git and python are already installed"
# clone the source code
rm -rf "$INSTALL_NAME"
git clone --depth 1 --branch "$BRANCH" --single-branch https://github.com/tagundo/elichika.git "$INSTALL_NAME" && \
cd "$INSTALL_NAME" && \
# get the submodules (i.e. assets and other)
git submodule update --init assets && \
# build server, fallback to not using CGO to work on some devices
(CGO_ENABLED=0 go build -o elichika || go build) && \
# set the permission
chmod +rx elichika && \
chmod +rx elichika_utility.sh && \
echo "Installed succesfully!"

if [ $? -eq 0 ]; then
    gen_shortcuts
else
    echo "Error installing"
fi
