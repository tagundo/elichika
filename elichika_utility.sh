#!/bin/bash

while true; do
    clear
    echo "==== Elichika Menu ===="
    echo ""
    echo "1. Run Server"
    echo "2. Reset Server"
    echo "3. Clear Cache Database"
    echo "4. Switch CDN to LocalHost"
    echo "5. Switch CDN to ImSoFuckingGay"
    echo "6. Toggle CDN Cache (download packs into cdn_cache_dir & serve them)"
    echo "7. Developer Menu"
    echo "8. Modding Menu"
    echo "9. Stop Server"
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
            clear
			pkill elichika
            sed -i 's#https://llsifas.imsofucking.gay/static/#http://127.0.0.1:8080/static#g' "config.json"
            echo "Switched To LocalHost"
            read -p "Press Enter to continue..." _dummy15555
            ;;
        5)
            clear
            pkill elichika
            sed -i 's#http://127.0.0.1:8080/static#https://llsifas.imsofucking.gay/static/#g' "config.json"
            echo "Switched To Catfolk"
            read -p "Press Enter to continue..." _dummy15235
            ;;
        6)
            # Toggle CDN Cache: when ON, elichika downloads any missing pack from the
            # CDN (cdn_server) into cdn_cache_dir and serves it itself, acting as the CDN.
            # cdn_cache_dir is set in the admin config page (empty = static/,
            # termux: ~/storage/downloads/sukusta/packs to share with the game/tools).
            clear
            pkill elichika
            if grep -q '"cdn_cache":true' "config.json"; then
                sed -i 's#"cdn_cache":true#"cdn_cache":false#g' "config.json"
                echo "CDN Cache: OFF (game downloads from the CDN directly)"
            elif grep -q '"cdn_cache":false' "config.json"; then
                sed -i 's#"cdn_cache":false#"cdn_cache":true#g' "config.json"
                echo "CDN Cache: ON (missing packs are downloaded into cdn_cache_dir and served locally)"
            else
                echo "Could not find cdn_cache in config.json - run the server once first."
            fi
            read -p "Press Enter to continue..." _dummy15236
            ;;
        7)
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
        8)
            # Mod Menu
            while true; do
                clear
                echo "==== Mod Menu ===="
			echo "1. extract assetbundle from sukusta/packs or static or CDN"
			echo "2. Download all packs (archive.org, accelerated)"
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
                        # Bulk-download all packs from archive.org into the cdn cache dir.
                        # archive.org supports HTTP range, so aria2c does a segmented/parallel
                        # (accelerated) download like macOS "Download Shuttle"; curl -C - is the
                        # single-connection resumable fallback.
                        clear
                        # resolve cdn_cache_dir from config.json (default ~/storage/downloads/sukusta/packs)
                        cache_dir=$(grep -oE '"cdn_cache_dir":"[^"]*"' config.json 2>/dev/null | sed -E 's/.*:"([^"]*)"/\1/')
                        [ -z "$cache_dir" ] && cache_dir="$HOME/storage/downloads/sukusta/packs"
                        # expand a leading ~ (POSIX-safe; escape the ~ so it isn't tilde-expanded to
                        # $HOME inside the pattern, which would leave a stray /~/ in the path)
                        case "$cache_dir" in
                            "~")   cache_dir="$HOME" ;;
                            "~/"*) cache_dir="$HOME/${cache_dir#\~/}" ;;
                        esac
                        mkdir -p "$cache_dir"
                        echo "Cache dir: $cache_dir"
                        echo ""
                        echo "Item: https://archive.org/download/ll-sifas-cdn-data"
                        read -p "Region (gl/jp) [gl]: " dl_region; dl_region=${dl_region:-gl}
                        if [ "$dl_region" = "jp" ]; then
                            def_ver="b66ec2295e9a00aa"
                        else
                            def_ver="2d61e7b4e89961c7"
                        fi
                        read -p "Master version hash [$def_ver]: " dl_ver; dl_ver=${dl_ver:-$def_ver}
                        dl_url="https://archive.org/download/ll-sifas-cdn-data/sifas-${dl_region}-cdn-assets-${dl_ver}.tar"
                        dl_tar="$cache_dir/.cdn-data-download.tar"
                        echo "Downloading: $dl_url"
                        # aria2c must actually RUN, not just exist: a fresh Termux install can be
                        # linked against newer libs (e.g. libxml2.so.16) than what's installed, so the
                        # binary exists but fails with "library not found". Test with --version.
                        aria_ok() { command -v aria2c >/dev/null 2>&1 && aria2c --version >/dev/null 2>&1; }
                        if ! aria_ok; then
                            echo "Setting up aria2 for accelerated downloads..."
                            if command -v pkg >/dev/null 2>&1; then
                                pkg install -y aria2
                                if ! aria_ok; then
                                    # broken shared libs: upgrade everything, then reinstall aria2
                                    echo "Upgrading Termux packages to fix libraries (one-time, may take a few minutes)..."
                                    pkg upgrade -y
                                    pkg install -y aria2
                                fi
                            elif command -v apt-get >/dev/null 2>&1; then
                                apt-get install -y aria2
                            fi
                        fi
                        dl_rc=1
                        if aria_ok; then
                            # archive.org can throttle/limit parallel connections, so step the
                            # connection count down on failure (resuming with -c) before giving up.
                            for dl_conns in 16 8 4 2 1; do
                                echo "Downloading with aria2c ($dl_conns connection(s))..."
                                aria2c -c -x"$dl_conns" -s"$dl_conns" -k1M --file-allocation=none \
                                       -d "$cache_dir" -o ".cdn-data-download.tar" "$dl_url"
                                dl_rc=$?
                                [ "$dl_rc" -eq 0 ] && break
                                echo "Failed (rc=$dl_rc), retrying with fewer connections..."
                            done
                        fi
                        if [ "$dl_rc" -ne 0 ]; then
                            echo "aria2 unavailable - falling back to curl (single connection, resumable)."
                            echo "NOTE: archive.org throttles single connections, so a large tar can be"
                            echo "      very slow this way. Getting aria2 working is strongly recommended."
                            curl -L -C - -o "$dl_tar" "$dl_url"
                            dl_rc=$?
                        fi
                        if [ "$dl_rc" -ne 0 ] || [ ! -s "$dl_tar" ]; then
                            echo "Download failed (rc=$dl_rc). Check the region/version and your connection."
                        else
                            echo "Extracting into $cache_dir ..."
                            # most packs sit at the tar root; if your tar wraps them in a folder,
                            # move them up afterwards so files are at <cache_dir>/<packname>.
                            tar -xf "$dl_tar" -C "$cache_dir" && rm -f "$dl_tar"
                            echo "Done. Packs should now be under: $cache_dir"
                            echo "Verify with: ls \"$cache_dir\" | head"
                        fi
                        read -p "Press Enter to continue..." _dummy_dlall
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
