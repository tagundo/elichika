#!/bin/bash

# keep the device awake during long downloads (Android suspends Termux when the screen is off).
wake_lock()   { command -v termux-wake-lock   >/dev/null 2>&1 && termux-wake-lock; }
wake_unlock() { command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock; }

# install/upgrade aria2 so it can actually RUN (a fresh Termux install can be linked against newer
# libs than installed, e.g. libxml2.so.16, so the binary exists but fails - test with --version).
# Returns success if aria2c is usable.
ensure_aria2() {
    if command -v aria2c >/dev/null 2>&1 && aria2c --version >/dev/null 2>&1; then
        return 0
    fi
    echo "Setting up aria2 for faster downloads..."
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y aria2
        if ! { command -v aria2c >/dev/null 2>&1 && aria2c --version >/dev/null 2>&1; }; then
            echo "Upgrading packages to fix libraries (one-time, may take a few minutes)..."
            pkg upgrade -y
            pkg install -y aria2
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get install -y aria2
    fi
    command -v aria2c >/dev/null 2>&1 && aria2c --version >/dev/null 2>&1
}

# Download one region's archive tar and extract it into the cache dir.
# args: <region: gl|jp> <version hash> <cache_dir> <parent_dir>
archive_one() {
    a_region="$1"; a_ver="$2"; a_cache="$3"; a_parent="$4"
    a_url="https://archive.org/download/ll-sifas-cdn-data/sifas-${a_region}-cdn-assets-${a_ver}.tar"
    a_tar="$a_parent/.cdn-data-download.tar"
    echo ""
    echo "=== $a_region: $a_url ==="
    a_rc=1
    if ensure_aria2; then
        # archive.org can throttle parallel connections, so step the count down on failure
        # (resuming with -c) before giving up.
        for a_conns in 16 8 4 2 1; do
            echo "Downloading with aria2c ($a_conns connection(s))..."
            aria2c -c -x"$a_conns" -s"$a_conns" -k1M --file-allocation=none \
                   -d "$a_parent" -o ".cdn-data-download.tar" "$a_url"
            a_rc=$?
            [ "$a_rc" -eq 0 ] && break
            echo "Failed (rc=$a_rc), retrying with fewer connections..."
        done
    fi
    if [ "$a_rc" -ne 0 ]; then
        echo "aria2 unavailable - falling back to curl (single connection, resumable, slow)."
        curl -L -C - -o "$a_tar" "$a_url"
        a_rc=$?
    fi
    if [ "$a_rc" -ne 0 ] || [ ! -s "$a_tar" ]; then
        echo "$a_region download failed (rc=$a_rc). Check the version and your connection."
        return 1
    fi
    echo "Extracting $a_region into $a_cache ..."
    mkdir -p "$a_cache"
    # --strip-components=1 drops the "sifas-..-<hash>/" wrapper; --skip-old-files keeps files you
    # already have (fast incremental, no manual move needed).
    if tar -xf "$a_tar" -C "$a_cache" --strip-components=1 --skip-old-files; then
        rm -f "$a_tar"
        echo "$a_region done."
    else
        echo "Extract failed. If your tar lacks --skip-old-files (busybox), run: pkg install tar"
        return 1
    fi
}

# Download ALL game files as big archives from archive.org (gl, jp, or both). This does NOT touch
# the game's CDN, so it won't burden it - this is the recommended way to get everything.
download_all_archive() {
    clear
    echo "Download ALL game files (big archives from archive.org)."
    echo "This does NOT use the game CDN, so it won't burden it."
    echo ""
    # resolve cdn_cache_dir from config.json (default ~/storage/downloads/sukusta/packs)
    cache_dir=$(grep -oE '"cdn_cache_dir":"[^"]*"' config.json 2>/dev/null | sed -E 's/.*:"([^"]*)"/\1/')
    [ -z "$cache_dir" ] && cache_dir="$HOME/storage/downloads/sukusta/packs"
    # expand a leading ~ (POSIX-safe; escape the ~ so it isn't tilde-expanded inside the pattern)
    case "$cache_dir" in
        "~")   cache_dir="$HOME" ;;
        "~/"*) cache_dir="$HOME/${cache_dir#\~/}" ;;
    esac
    mkdir -p "$cache_dir"
    dl_parent=$(dirname "$cache_dir")
    echo "Save location: $cache_dir"
    echo ""
    echo "GL = Global (English/Korean/Chinese), JP = Japan. 'both' gets everything."
    read -p "Region (gl/jp/both) [both]: " dl_region; dl_region=${dl_region:-both}
    case "$dl_region" in
        gl) dl_regions="gl" ;;
        jp) dl_regions="jp" ;;
        *)  dl_regions="gl jp" ;;
    esac
    wake_lock   # keep going with the screen off
    for r in $dl_regions; do
        if [ "$r" = "jp" ]; then rv="b66ec2295e9a00aa"; else rv="2d61e7b4e89961c7"; fi
        archive_one "$r" "$rv" "$cache_dir" "$dl_parent"
    done
    wake_unlock
    echo ""
    echo "All done. Restart the server (option 1) so it indexes the new files."
    read -p "Press Enter to continue..." _dummy_dlall
}

# Download only the game files you don't already have, from the official game CDN. Gentle on the
# server (few parallel downloads); for large amounts prefer download_all_archive.
download_missing_cdn() {
    clear
    # show the actual game-CDN host from config (cdn_server), used only as a fallback.
    cdn_val=$(grep -oE '"cdn_server":"[^"]*"' config.json 2>/dev/null | sed -E 's/.*:"([^"]*)"/\1/')
    cdn_host=$(printf '%s' "$cdn_val" | sed -E 's#^[a-z]+://##; s#/.*##')
    [ -z "$cdn_host" ] && cdn_host="the configured CDN"
    echo "Download the files you're still missing, from the CDN ($cdn_host)."
    echo "These are files newer than the archive (so they're not in option 6),"
    echo "and they only come from the game CDN. Skips anything you already have."
    echo ""
    echo "IMPORTANT: run option 6 (download all) FIRST so this only has to fetch the"
    echo "           few newest files from the CDN, instead of a lot."
    echo "(These files also download automatically as you play, so this is optional.)"
    echo ""
    wake_lock   # keep going with the screen off
    pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
    sleep 1
    read -p "Simultaneous downloads [3]: " dl_workers; dl_workers=${dl_workers:-3}
    ./elichika download_packs "$dl_workers"
    wake_unlock
    read -p "Press Enter to continue..." _dummy_dlmiss
}

while true; do
    clear
    echo "==== Elichika Menu ===="
    echo ""
    if grep -q '"cdn_cache":true' config.json 2>/dev/null; then cache_state="ON"; else cache_state="OFF"; fi
    echo "1. Run Server"
    echo "2. Reset Server"
    echo "3. Clear Cache Database"
    echo "4. Reset CDN to default (public server)"
    echo "5. CDN Cache: $cache_state (store game files locally & serve them)"
    echo "6. Download all game files (fast, from archive.org)"
    echo "7. Get remaining files not in the archive (from the CDN)"
    echo "8. Developer Menu"
    echo "9. Modding Menu"
    echo "10. Stop Server"
    echo "0. Exit"

    read -p "Enter your choice: " option

    case $option in
        1)
            clear
            pkill elichika
			./elichika
            read -p "Press Enter to continue..." _dummy1
            ;;
        2)
			clear
			echo "NOTE: This will reset the server to its current state"
			echo "WARNING: ALL saved Player IDs will be LOST!"
			echo "Backup your files, or better yet..."
			echo ""
			read -p "Are you sure you want to reset the server? Press Enter to proceed, or press Ctrl+C to exit Termux if you don't want to continue: " _dummy53534
			pkill elichika
			rm serverdata.db
			rm userdata.db
			rm config.json
			clear
			python3 elichika_reset.py
			git fetch origin main
			git reset --hard origin/main
			git clean -fd
			cd ~/elichika2/assets
			git fetch origin main
			git reset --hard origin/main
			git clean -fd
			cd ~/elichika2
			echo "Building server..."
			CGO_ENABLED=0 go build -o elichika || go build
			echo "Finished, please run again"
			exit 0
            ;;
        3)
			clear
			python3 elichika_reset.py -nostage
            read -p "Press Enter to continue..." _dummy15sz35
            ;;
        4)
            # Reset the CDN source (cdn_server) to the default public server. Use this if the game
            # can't download assets after settings were changed.
            clear
            pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
            sed -i 's#"cdn_server":"[^"]*"#"cdn_server":"https://llsifas.imsofucking.gay/static/"#' "config.json"
            echo "CDN source reset to the default public server."
            echo "Restart the server (option 1) to apply."
            read -p "Press Enter to continue..." _dummy_cdnreset
            ;;
        5)
            # Toggle CDN Cache: when ON, elichika downloads any pack the game needs from the CDN,
            # stores it locally (cdn_cache_dir), and serves it - so it loads fast next time.
            # cdn_cache_dir is set on the admin config page (default ~/storage/downloads/sukusta/packs).
            clear
            pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
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
        6)
            download_all_archive
            ;;
        7)
            download_missing_cdn
            ;;
        8)
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
						pkill elichika
						python3 costume_addon_installer.py
                        read -p "Press Enter to continue..." _dummy01
                        ;;
                    2)
						clear
						pkill elichika
						python3 live_addon_installer.py
                        read -p "Press Enter to continue..." _dummy02
                        ;;
                    3)
						clear
						pkill elichika
						python3 tower_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    4)
						clear
						pkill elichika
						python3 card_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    5)
						clear
						pkill elichika
						python3 elichika_db_importer.py
                        read -p "Press Enter to continue..." _dummy0399
                        ;;
                    6)
						clear
						pkill elichika
						python3 llasdecryptor.py
                        read -p "Press Enter to continue..." _dummy02555555
                        ;;
                    7)
						clear
						pkill elichika
						python3 replace_jp_client_dictionary.py
                        read -p "Press Enter to continue..." _dummy02555235
                        ;;
                    8)
						clear
						pkill elichika
						xdg-open https://gamebanana.com/games/20519
                        ;;
                    9)
						clear
						pkill elichika
						xdg-open https://ayakamods.cc/games/love-live-school-idol-festival-all-stars.217/
                        ;;
                    10)
						clear
						pkill elichika
						python3 camera_live_timeline_replacer.py
                        read -p "Press Enter to continue..." _dummy9999999999
                        ;;
                    11)
						clear
						pkill elichika
						python3 costume_clone.py
                        read -p "Press Enter to continue..." _dummy99999999999
                        ;;
                    12)
						clear
						pkill elichika
						python3 database_backup.py
                        read -p "Press Enter to continue..." _dummy999999999999
                        ;;
                    13)
						clear
						pkill elichika
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
        9)
            # Mod Menu
            while true; do
                clear
                echo "==== Mod Menu ===="
			echo "1. extract assetbundle from sukusta/packs or static or CDN" 
			echo "2. unity_costumemod_packer.py"
			echo "3. sifas_breast_tuner.py"
			echo "4. skirt_length_changer.py"
            echo "0. Back to Main Menu"
                read -p "Enter your choice: " mod_option

                case $mod_option in
                    1)
						clear
						pkill elichika
						python3 llas_asset_extractor.py
                        read -p "Press Enter to continue..." _dummy012
                        ;;
                    2)
						clear
						pkill elichika
						python3 unity_costumemod_packer.py
                        read -p "Press Enter to continue..." _dummy0123
                        ;;
                    3)
						clear
						pkill elichika
						python3 sifas_breast_tuner.py
                        read -p "Press Enter to continue..." _dummy01234
                        ;;
                    4)
						clear
						pkill elichika
						python3 skirt_length_changer.py
                        read -p "Press Enter to continue..." _dummy01235
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
            # Stop Server
            clear
            echo "Stopping any running elichika..."
            # plain SIGTERM / pkill -x don't reliably kill "./elichika" on Termux, so match the
            # command line and use SIGKILL. the pattern targets the server binary only, not this
            # script or the elichika2 directory name.
            pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
            sleep 1
            if pgrep -f '(^|/)elichika( |$)' >/dev/null 2>&1; then
                echo "Warning: elichika is still running."
            else
                echo "Server stopped."
            fi
            read -p "Press Enter to continue..." _dummy_stop
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
