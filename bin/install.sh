# install the latest version of elichika from scratch
#
# Cross-platform: works on Termux (Android), macOS, Linux, and Windows
# (Git Bash / MSYS2 / Cygwin). On WSL it behaves like Linux.
#
# Environment variables (all optional, set via export or inline when invoking):
#   BRANCH        which branch's CODE to install. Defaults to "main".
#                 e.g. BRANCH=Test installs the test build's code.
#   INSTALL_NAME  directory to install into. Defaults to "elichika3".
#                 e.g. INSTALL_NAME=elichika3_test keeps the test build separate
#                 from the stable one so the two can coexist.
#   SKIP_DEPS     set to 1 to skip the automatic dependency install step
#                 (use this if you already have go/git/python and don't want
#                 the script to touch your package manager).
#   NO_BREW_AUTOINSTALL   (macOS) set to 1 to NOT auto-install Homebrew when missing.
#   NO_CHOCO_AUTOINSTALL  (Windows) set to 1 to NOT auto-install Chocolatey when missing.
# Honestly the branch override is only for testing but you can think of it as a hidden feature.
#
# NOTE: the helper scripts (this one, shortcut.sh, update.sh, basic_update.sh) are
# maintained on the *main* branch only. Only the game CODE comes from $BRANCH, so a
# test build clones the Test branch's code but still uses main's helper scripts.
# That is why we fetch shortcut.sh from main below instead of running the copy that
# was checked out from $BRANCH (which may be older).
BRANCH=${BRANCH:-"main"}
INSTALL_NAME=${INSTALL_NAME:-"elichika3"}

# ---------------------------------------------------------------------------
# Detect the operating system / environment.
#   Sets OS to one of: termux, macos, linux, windows, unknown
# Termux must be checked first because it also reports as Linux via uname.
# ---------------------------------------------------------------------------
detect_os() {
    if command -v termux-setup-storage >/dev/null 2>&1 || [ -n "${TERMUX_VERSION:-}" ]; then
        echo "termux"; return
    fi
    case "$(uname -s 2>/dev/null)" in
        Darwin)               echo "macos" ;;
        Linux)                echo "linux" ;;   # WSL lands here too, which is what we want
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)                    echo "unknown" ;;
    esac
}
OS="$(detect_os)"

# Go appends .exe on Windows; everything else builds a plain "elichika".
BIN="elichika"
[ "$OS" = "windows" ] && BIN="elichika.exe"

# ---------------------------------------------------------------------------
# Storage permission — ONLY meaningful on Termux/Android.
# On every other platform there is nothing to grant, so we skip it (running
# termux-setup-storage there just spins forever printing "command not found").
# ---------------------------------------------------------------------------
request_storage_permission() {
    if [ "$OS" != "termux" ]; then
        return 0
    fi
    echo "Requesting storage permission..."
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
}

# ---------------------------------------------------------------------------
# Install go, git and python using the platform's package manager.
# Any failure here is non-fatal: we just assume the tools are already present
# and let the build step surface a clearer error if they really are missing.
# ---------------------------------------------------------------------------

# True when go, git and python are all already on PATH (python or python3).
have_build_tools() {
    command -v go  >/dev/null 2>&1 &&
    command -v git >/dev/null 2>&1 &&
    { command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; }
}

# macOS: make sure Homebrew is available, installing it automatically if missing
# (so the one-line `curl | bash` works on a fresh Mac with no setup).
# Set NO_BREW_AUTOINSTALL=1 to opt out of the automatic install.
ensure_homebrew() {
    # Already on PATH? done.
    command -v brew >/dev/null 2>&1 && return 0
    # Installed but not on PATH yet (common right after install)? load it.
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"; return 0
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"; return 0
    fi
    if [ "${NO_BREW_AUTOINSTALL:-0}" = "1" ]; then
        echo "Homebrew not found and NO_BREW_AUTOINSTALL=1 set; install it from https://brew.sh." >&2
        return 1
    fi
    echo "Homebrew not found. Installing it now (this can take a few minutes and may ask for your macOS password)..."
    # NONINTERACTIVE=1 so the installer doesn't block waiting for a RETURN
    # keypress when this script itself is being run via `curl | bash`.
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
        echo "Homebrew install failed. Install it manually from https://brew.sh, then re-run." >&2
        return 1
    }
    # Put brew on PATH for the rest of this script.
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    command -v brew >/dev/null 2>&1
}

install_deps_linux() {
    # Use sudo only when we are not root and sudo is available.
    SUDO=""
    if [ "$(id -u 2>/dev/null)" != "0" ] && command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y golang git python3
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y golang git python3
    elif command -v yum >/dev/null 2>&1; then
        $SUDO yum install -y golang git python3
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -Sy --noconfirm go git python
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper install -y go git python3
    elif command -v apk >/dev/null 2>&1; then
        $SUDO apk add go git python3
    else
        echo "No known Linux package manager found. Please install go, git and python manually." >&2
        return 0
    fi
}

# Windows: make sure Chocolatey is available, bootstrapping it if missing so a
# fresh machine with no package manager can still install go/git/python.
# Note: installing Chocolatey requires an *Administrator* shell; if this script
# isn't elevated the bootstrap will fail and we fall back to manual links.
# Set NO_CHOCO_AUTOINSTALL=1 to opt out of the automatic install.
ensure_choco() {
    # Already on PATH? done (opt-out never blocks using an existing choco).
    command -v choco >/dev/null 2>&1 && return 0
    # Installed but not on this shell's PATH yet? add it.
    if [ -x "/c/ProgramData/chocolatey/bin/choco.exe" ]; then
        export PATH="/c/ProgramData/chocolatey/bin:$PATH"; return 0
    fi
    if [ "${NO_CHOCO_AUTOINSTALL:-0}" = "1" ]; then
        return 1
    fi
    if ! command -v powershell >/dev/null 2>&1; then
        echo "PowerShell not found; cannot bootstrap Chocolatey automatically." >&2
        return 1
    fi
    echo "No package manager found. Installing Chocolatey (requires an Administrator shell)..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command \
        "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))" || {
        echo "Chocolatey install failed (are you running this shell as Administrator?)." >&2
        return 1
    }
    if [ -x "/c/ProgramData/chocolatey/bin/choco.exe" ]; then
        export PATH="/c/ProgramData/chocolatey/bin:$PATH"
    fi
    command -v choco >/dev/null 2>&1
}

install_deps_windows() {
    if command -v winget >/dev/null 2>&1; then
        winget install --id GoLang.Go      -e --silent --accept-source-agreements --accept-package-agreements
        winget install --id Git.Git        -e --silent --accept-source-agreements --accept-package-agreements
        winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
    elif command -v pacman >/dev/null 2>&1; then
        # MSYS2 environment
        pacman -S --noconfirm --needed mingw-w64-x86_64-go git python
    elif ensure_choco; then
        # uses an existing Chocolatey or the one we just bootstrapped
        choco install -y golang git python
    else
        echo "No package manager (winget/choco) found and Chocolatey bootstrap was unavailable." >&2
        echo "Please install manually:" >&2
        echo "  Go     -> https://go.dev/dl/" >&2
        echo "  Git    -> https://git-scm.com/download/win" >&2
        echo "  Python -> https://www.python.org/downloads/" >&2
        return 0
    fi
    # Freshly installed tools usually aren't on THIS shell's PATH yet; add the
    # common locations so the build step in the same run can find them.
    [ -d "/c/Program Files/Go/bin" ]      && export PATH="/c/Program Files/Go/bin:$PATH"
    [ -d "/c/ProgramData/chocolatey/bin" ] && export PATH="/c/ProgramData/chocolatey/bin:$PATH"
}

install_deps() {
    if [ "${SKIP_DEPS:-0}" = "1" ]; then
        echo "SKIP_DEPS=1 set; skipping dependency install."
        return 0
    fi
    case "$OS" in
        termux)
            pkg install golang git python -y
            ;;
        macos)
            if have_build_tools; then
                echo "go, git and python are already installed; skipping Homebrew."
            elif ensure_homebrew; then
                brew install go git python
            fi
            ;;
        linux)
            install_deps_linux
            ;;
        windows)
            install_deps_windows
            ;;
        *)
            echo "Unknown OS; skipping automatic dependency install." >&2
            ;;
    esac || echo "assuming go, git and python are already installed"
}

# (Re)generate the shortcuts using main's generator (see NOTE above).
gen_shortcuts() {
    _sc="$(mktemp 2>/dev/null || echo /tmp/elichika_shortcut.sh)"
    if curl -fsSL "https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/shortcut.sh" -o "$_sc" && [ -s "$_sc" ]; then
        bash "$_sc"
    elif [ -f ./bin/shortcut.sh ]; then
        echo "Note: couldn't fetch shortcut.sh from main; using the local copy." >&2
        chmod +x ./bin/shortcut.sh 2>/dev/null || true
        bash ./bin/shortcut.sh
    fi
    rm -f "$_sc"
}

# ---------------------------------------------------------------------------
# Clone the source, fetch assets, and build.
# Returns non-zero on the first failing step. On success the CWD is left
# inside the install directory (gen_shortcuts relies on that).
# ---------------------------------------------------------------------------
build_and_install() {
    rm -rf "$INSTALL_NAME"
    git clone --depth 1 --branch "$BRANCH" --single-branch https://github.com/tagundo/elichika.git "$INSTALL_NAME" || return 1
    cd "$INSTALL_NAME" || return 1
    # get the submodules (i.e. assets and other)
    git submodule update --init assets || return 1
    # build server, fallback to not using CGO to work on some devices
    (CGO_ENABLED=0 go build -o "$BIN" || go build -o "$BIN") || return 1
    # set the permission (no-op / not needed on Windows)
    if [ "$OS" != "windows" ]; then
        chmod +rx "$BIN" 2>/dev/null || true
        chmod +rx elichika_utility.sh 2>/dev/null || true
    fi
    return 0
}

clear

echo "Detected platform: $OS"
request_storage_permission

echo "Installing $INSTALL_NAME (branch: $BRANCH)..."
# install git and golang (per-platform; non-fatal on failure)
install_deps

if build_and_install; then
    echo "Installed successfully!"
    gen_shortcuts
else
    echo "Error installing" >&2
    exit 1
fi
