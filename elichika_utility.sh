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
    echo "6. Developer Menu"
    echo "7. Modding Menu"	
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
        7)
            # Mod Menu
            while true; do
                clear
                echo "==== Mod Menu ===="
			echo "1. extract assetbundle from static(LocalHost)"
			echo "2. extract assetbundle from game(currently not working)"
            echo "0. Back to Main Menu"
                read -p "Enter your choice: " mod_option

                case $mod_option in
                    1)
						clear
						pkill elichika
						python3 llas_asset_extractor_from_static.py
                        read -p "Press Enter to continue..." _dummy012
                        ;;
                    2)
						clear
						pkill elichika
						python3 llas_asset_extractor_from_game.py
                        read -p "Press Enter to continue..." _dummy0123
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
