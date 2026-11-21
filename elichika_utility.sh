#!/bin/bash

# keep the device awake during long downloads (Android suspends Termux when the screen is off).
wake_lock()   { command -v termux-wake-lock   >/dev/null 2>&1 && termux-wake-lock; }
wake_unlock() { command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock; }

# ---------------------------------------------------------------------------
# Cross-platform helpers (so the menu works the same on macOS / Windows /
# Linux / Android-Termux). Defined up here so every menu entry can use them.
# ---------------------------------------------------------------------------

# Where the maintained helper scripts live (always pulled from the main branch).
RAW_BIN="https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin"

# The server binary is "elichika" everywhere except Windows, where Go builds
# "elichika.exe". Echo whichever one is actually present (default ./elichika).
server_bin() {
    if [ -f ./elichika.exe ]; then echo "./elichika.exe"; else echo "./elichika"; fi
}

# Stop any running server, cross-platform.
#   - Linux/macOS/Termux: pkill the server by its command line with SIGKILL
#     (plain "pkill -x" doesn't match "./elichika" on Termux). The pattern
#     targets the server binary only, not this script or the install directory
#     name (elichika3 / elichika3_test).
#   - Windows Git Bash (no pkill): fall back to taskkill on elichika.exe.
stop_server() {
    if command -v pkill >/dev/null 2>&1; then
        pkill -9 -f '(^|/)elichika(\.exe)?( |$)' 2>/dev/null || true
    elif command -v taskkill >/dev/null 2>&1; then
        taskkill //F //IM elichika.exe >/dev/null 2>&1 || true
    fi
}

# Open a URL in the default browser, cross-platform (Linux: xdg-open,
# macOS: open, Windows: start via cmd / PowerShell). Used by the modpage links.
open_url() {
    url="$1"
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1
    elif command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1
    elif command -v cmd  >/dev/null 2>&1; then cmd //c start "" "$url" >/dev/null 2>&1
    elif command -v powershell >/dev/null 2>&1; then powershell -NoProfile -Command "Start-Process '$url'" >/dev/null 2>&1
    else echo "Open this link in your browser: $url"; fi
}

# Run the server in the foreground. Press Ctrl+C to stop the server and return
# to the menu instead of killing this whole script: a no-op SIGINT trap keeps
# the menu alive while the signal still reaches the server (which exits on it).
# This is why stopping the server is no longer a separate menu entry - you just
# press Ctrl+C while it runs.
run_server() {
    clear
    stop_server          # clear out any stale instance first
    bin="$(server_bin)"
    if [ ! -f "$bin" ]; then
        echo "Server binary not found ($bin)."
        echo "Build it first with '2. Update Server' (or 'Reset Server')."
        read -p "Press Enter to continue..." _dummy_norun
        return
    fi
    echo "Starting the server..."
    echo "Press Ctrl+C to stop the server and return to the menu."
    echo ""
    trap ':' INT
    "$bin"
    trap - INT
    stop_server          # make sure nothing lingers after it exits
    echo ""
    read -p "Server stopped. Press Enter to return to the menu..." _dummy_run
}

# Fetch and run one of the maintained update scripts (update.sh / basic_update.sh).
# Prefer the latest copy from main so the update logic is always current; fall
# back to the local bin/ copy when offline. Both scripts back up and preserve
# userdata.db / serverdata.db / config / assets, so updating is non-destructive.
# We exit the menu afterwards because the update may have replaced this very
# script - reopen the menu to run the fresh copy.
run_update_script() {
    us_name="$1"
    clear
    stop_server          # free the databases before the update touches them
    sleep 1
    rc=0
    _us="$(mktemp 2>/dev/null || echo "/tmp/elichika_$us_name")"
    if curl -fsSL "$RAW_BIN/$us_name" -o "$_us" 2>/dev/null && [ -s "$_us" ]; then
        bash "$_us"; rc=$?
    elif [ -f "./bin/$us_name" ]; then
        echo "Could not fetch the latest $us_name online; using the local copy."
        bash "./bin/$us_name"; rc=$?
    else
        echo "ERROR: could not fetch $us_name and no local copy was found."
        echo "Check your internet connection and try again."
        rm -f "$_us"
        read -p "Press Enter to continue..." _dummy_upderr
        return
    fi
    rm -f "$_us"
    echo ""
    if [ "$rc" -eq 0 ]; then
        echo "Update finished successfully."
    else
        echo "Update did NOT finish cleanly (exit code $rc) - see the messages above."
    fi
    echo "Please reopen the menu so it runs the updated copy."
    read -p "Press Enter to exit..." _dummy_updone
    exit 0
}

# Update submenu - the "update list". Updating keeps your data (userdata.db /
# serverdata.db / config), so it's safe to run regularly. The normal update is
# the recommended one on macOS/Windows; the basic update does a full reinstall.
update_menu() {
    while true; do
        clear
        echo "==== Update Server ===="
        echo ""
        echo "Both options KEEP your account data (userdata.db) and settings."
        echo "Tip: export your data in the WebUI first before a big version jump."
        echo ""
        echo "1. Normal update  (recommended; pulls the latest code and rebuilds)"
        echo "2. Basic update   (slower full reinstall; use if the normal update fails)"
        echo "0. Back to Main Menu"
        echo ""
        read -p "Enter your choice: " upd_option
        case $upd_option in
            1) run_update_script "update.sh" ;;
            2) run_update_script "basic_update.sh" ;;
            0) break ;;
            *)
                echo "Invalid option. Please try again."
                read -p "Press Enter to continue..." _dummy_updinv
                ;;
        esac
    done
}

# Foreground downloads keep Termux awake and return to the menu after Ctrl+C.
run_game_download() {
    local binary status
    binary="$(server_bin)"
    if [ ! -f "$binary" ]; then
        echo "Server binary not found ($binary). Build it with '2. Update Server'."
        read -r -p "Press Enter to continue... " _dummy_download
        return
    fi

    trap ':' INT
    wake_lock
    stop_server
    sleep 1 && "$binary" "$@"
    status=$?
    wake_unlock
    trap - INT

    echo ""
    if [ "$status" -ne 0 ]; then
        echo "Download stopped or failed (exit code $status)."
    fi
    echo "Start the server (option 1) to index downloaded files."
    read -r -p "Press Enter to continue... " _dummy_download
}

download_archive_menu() {
    clear
    echo "==== Download game files from archive.org ===="
    echo "Verified cached packs are reused."
    echo ""
    echo "1. All (GL + JP)"
    echo "2. GL all"
    echo "3. JP all"
    echo "4. GL APK"
    echo "5. GL iOS"
    echo "6. JP APK"
    echo "7. JP iOS"
    echo "0. Back"
    echo ""

    local archive_scope
    read -r -p "Select a download preset [1]: " archive_scope || return
    case "${archive_scope:-1}" in
        1) set -- both both all "$@" ;;
        2) set -- gl both all "$@" ;;
        3) set -- jp both ja "$@" ;;
        4) set -- gl android all "$@" ;;
        5) set -- gl ios all "$@" ;;
        6) set -- jp android ja "$@" ;;
        7) set -- jp ios ja "$@" ;;
        0) return ;;
        *)
            echo "Invalid download preset."
            read -r -p "Press Enter to continue... " _dummy_archive
            return
            ;;
    esac
    run_game_download download_archive "$@"
}

download_missing_menu() {
    clear
    echo "==== Download missing game files ===="
    echo "1. CDN"
    echo "2. archive.org"
    echo "0. Back"
    echo ""

    local download_source
    read -r -p "Select a download source [1]: " download_source || return
    case "${download_source:-1}" in
        1) download_missing_cdn ;;
        2) download_archive_menu --missing ;;
        0) return ;;
        *)
            echo "Invalid download source."
            read -r -p "Press Enter to continue... " _dummy_download_source
            ;;
    esac
}

# Download packs missing from the cache for a client, using the configured CDN.
download_missing_cdn() {
    clear
    local dl_region dl_platform dl_language dl_workers
    # show the actual game-CDN host from config (cdn_server), used only as a fallback.
    cdn_val=$(grep -oE '"cdn_server":"[^"]*"' config.json 2>/dev/null | sed -E 's/.*:"([^"]*)"/\1/')
    cdn_host=$(printf '%s' "$cdn_val" | sed -E 's#^[a-z]+://##; s#/.*##')
    [ -z "$cdn_host" ] && cdn_host="the configured CDN"
    echo "Download missing files for the selected client from $cdn_host."
    echo "Required shared files are included. Cached files are reused."
    echo ""
    read -r -p "Region (gl/jp/both) [gl]: " dl_region || return
    dl_region=${dl_region:-gl}
    read -r -p "Game platform (android/ios/both) [android]: " dl_platform || return
    dl_platform=${dl_platform:-android}
    case "$dl_region" in
        gl) read -r -p "Game language (all/en/ko/zh) [all]: " dl_language || return ;;
        jp) dl_language=ja ;;
        both) dl_language=all ;;
    esac
    dl_language=${dl_language:-all}
    read -r -p "Simultaneous downloads [3]: " dl_workers || return
    dl_workers=${dl_workers:-3}
    if [[ ! "$dl_region" =~ ^(gl|jp|both)$ || ! "$dl_platform" =~ ^(android|ios|both)$ ||
          ! "$dl_language" =~ ^(all|en|ko|zh|ja)$ || "$dl_region/$dl_language" == gl/ja ||
          ! "$dl_workers" =~ ^[1-9][0-9]*$ ]]; then
        echo "Invalid download selection."
        read -r -p "Press Enter to continue..." _dummy_dlmiss
        return
    fi
    run_game_download download_packs "$dl_workers" --region "$dl_region" --platform "$dl_platform" --language "$dl_language"
}

while true; do
    clear
    echo "==== Elichika Menu ===="
    echo ""
    if grep -q '"cdn_cache":true' config.json 2>/dev/null; then cache_state="ON"; else cache_state="OFF"; fi
    echo "1. Run Server  (press Ctrl+C while it runs to stop it)"
    echo "2. Update Server (keeps your data; works on Mac/Windows/Linux/Android)"
    echo "3. Reset Server"
    echo "4. Clear Cache Database"
    echo "5. Reset CDN to default (public server)"
    echo "6. CDN Cache: $cache_state (store game files locally & serve them)"
    echo "7. Download game files from archive.org"
    echo "8. Download missing game files (CDN or archive.org)"
    echo "9. Developer Menu"
    echo "10. Modding Menu"
    echo "0. Exit"

    read -p "Enter your choice: " option

    case $option in
        1)
            run_server
            ;;
        2)
            update_menu
            ;;
        3)
            clear
            echo "NOTE: This will reset the server to its current state"
            echo "WARNING: ALL saved Player IDs will be LOST!"
            echo "Backup your files, or better yet..."
            echo ""
            read -p "Are you sure you want to reset the server? Press Enter to proceed, or press Ctrl+C to exit Termux if you don't want to continue: " _dummy53534
            stop_server
            rm serverdata.db
            rm userdata.db
            rm config.json
            clear
            python3 elichika_reset.py
            # reset the code to whatever branch this copy tracks (stable -> main,
            # test -> Test). relative paths are used so this works no matter what
            # the install directory is named (elichika3, elichika3_test, ...).
            CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
            git fetch origin "$CUR_BRANCH"
            git reset --hard "origin/$CUR_BRANCH"
            git clean -fd
            cd assets
            git fetch origin main
            git reset --hard origin/main
            git clean -fd
            cd ..
            echo "Building server..."
            CGO_ENABLED=0 go build -o elichika || go build
            echo "Finished, please run again"
            exit 0
            ;;
        4)
            clear
            python3 elichika_reset.py -nostage
            read -p "Press Enter to continue..." _dummy15sz35
            ;;
        5)
            # Reset the CDN source (cdn_server) to the default public server. Use this if the game
            # can't download assets after settings were changed.
            clear
            stop_server
            sed -i 's#"cdn_server":"[^"]*"#"cdn_server":"https://llsifas.imsofucking.gay/static/"#' "config.json"
            echo "CDN source reset to the default public server."
            echo "Restart the server (option 1) to apply."
            read -p "Press Enter to continue..." _dummy_cdnreset
            ;;
        6)
            # Toggle CDN Cache: when ON, elichika downloads any pack the game needs from the CDN,
            # stores it locally (cdn_cache_dir), and serves it - so it loads fast next time.
            # cdn_cache_dir is set on the admin config page (default: the local static/ folder on PC,
            # the shared ~/storage/downloads/sukusta/packs folder on Termux/Android).
            clear
            stop_server
            if grep -q '"cdn_cache":true' "config.json"; then
                sed -i 's#"cdn_cache":true#"cdn_cache":false#g' "config.json"
                echo "CDN Cache is now OFF (the game downloads from the CDN directly)."
            elif grep -q '"cdn_cache":false' "config.json"; then
                sed -i 's#"cdn_cache":false#"cdn_cache":true#g' "config.json"
                echo "CDN Cache is now ON (game files are stored locally and served fast)."
            else
                echo "Could not find cdn_cache in config.json - run the server once first."
            fi
            echo "Restart the server (option 1) to apply."
            read -p "Press Enter to continue..." _dummy15236
            ;;
        7)
            download_archive_menu
            ;;
        8)
            download_missing_menu
            ;;
        9)
            # Dev Menu
            while true; do
                clear
                echo "==== Developer Menu ===="
            echo "1. Add New Costume"
            echo "2. Add New Live"
            echo "3. Add New DLP (Deprecated)"
            echo "4. Add New Card (Deprecated)"
            echo "5. Patch Masterdata"
            echo "6. LLASDecryptor"
            echo "7. Overwrite JP Client Dictionary"
            echo "8. GameBanana Modpage"
            echo "9. AyakaMods Modpage"
            echo "10. camera live timeline replacer"
            echo "11. Costume clone"
            echo "12. Backup db"
            echo "13. Restore db"
                    echo "0. Back to Main Menu"

                read -p "Enter your choice: " dev_option

                case $dev_option in
                    1)
                        clear
                        stop_server
                        python3 costume_addon_installer.py
                        read -p "Press Enter to continue..." _dummy01
                        ;;
                    2)
                        clear
                        stop_server
                        python3 live_addon_installer.py
                        read -p "Press Enter to continue..." _dummy02
                        ;;
                    3)
                        clear
                        stop_server
                        python3 tower_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    4)
                        clear
                        stop_server
                        python3 card_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    5)
                        clear
                        stop_server
                        python3 elichika_db_importer.py
                        read -p "Press Enter to continue..." _dummy0399
                        ;;
                    6)
                        clear
                        stop_server
                        python3 llasdecryptor.py
                        read -p "Press Enter to continue..." _dummy02555555
                        ;;
                    7)
                        clear
                        stop_server
                        python3 replace_jp_client_dictionary.py
                        read -p "Press Enter to continue..." _dummy02555235
                        ;;
                    8)
                        clear
                        stop_server
                        open_url "https://gamebanana.com/games/20519"
                        ;;
                    9)
                        clear
                        stop_server
                        open_url "https://ayakamods.com/games/love-live-school-idol-festival-all-stars.217/"
                        ;;
                    10)
                        clear
                        stop_server
                        python3 camera_live_timeline_replacer.py
                        read -p "Press Enter to continue..." _dummy9999999999
                        ;;
                    11)
                        clear
                        stop_server
                        python3 costume_clone.py
                        read -p "Press Enter to continue..." _dummy99999999999
                        ;;
                    12)
                        clear
                        stop_server
                        python3 database_backup.py
                        read -p "Press Enter to continue..." _dummy999999999999
                        ;;
                    13)
                        clear
                        stop_server
                        python3 database_restore.py
                        read -p "Press Enter to continue..." _dummy9999999999999
                        ;;
                    0)
                        break
                        ;;
                    *)
                        echo "Invalid option. Please try again."
                        read -p "Press Enter to continue..." _dummy0407
                        ;;
                esac
            done
            ;;
        10)
            # Mod Menu
            while true; do
                clear
                echo "==== Mod Menu ===="
            echo "1. extract assetbundle from sukusta/packs or static or CDN"
            echo "2. unity_costumemod_packer.py"
            echo "3. sifas_breast_tuner.py"
            echo "4. skirt_length_changer.py"
            echo "5. sifas_mesh_baker.py"
            echo "0. Back to Main Menu"
                read -p "Enter your choice: " mod_option

                case $mod_option in
                    1)
                        clear
                        stop_server
                        python3 llas_asset_extractor.py
                        read -p "Press Enter to continue..." _dummy012
                        ;;
                    2)
                        clear
                        stop_server
                        python3 modtools/unity_costumemod_packer.py
                        read -p "Press Enter to continue..." _dummy0123
                        ;;
                    3)
                        clear
                        stop_server
                        python3 modtools/sifas_breast_tuner.py
                        read -p "Press Enter to continue..." _dummy01234
                        ;;
                    4)
                        clear
                        stop_server
                        python3 modtools/skirt_length_changer.py
                        read -p "Press Enter to continue..." _dummy01235
                        ;;
                    5)
                        clear
                        stop_server
                        python3 modtools/sifas_mesh_baker.py
                        read -p "Press Enter to continue..." _dummy012356
                        ;;
                    0)
                        break
                        ;;
                    *)
                        echo "Invalid option. Please try again."
                        read -p "Press Enter to continue..." _dummy0407
                        ;;
                esac
            done
            ;;
        0)
            clear
            echo "Exiting Elichika Menu."
            exit 0
            ;;
        *)
            echo "Invalid option. Please try again."
            read -p "Press Enter to continue..." _dummy09875
            ;;
    esac
done
