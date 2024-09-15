#!/bin/bash

while true; do
    clear
    echo "==== Elichika Menu ===="
    echo ""
    echo "1. Run Server"
    echo "2. Reset Server"
    echo "3. Clear Cache Database"
    echo "4. Switch CDN to LocalHost"
    echo "5. Switch CDN to Catfolk"
    echo "6. Developer Menu"
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
			echo "note that this will reset everything the current state of server"
			echo "backup you files, or better yet"
			echo ""
			read -p "are you sure want reset server? enter to procced or exit termux (ctrl + c) if you don't want" _dummy53534
			pkill elichika
			rm serverdata.db
			rm userdata.db
			rm config.json
			clear
			python elichika_reset.py
			git fetch origin main
			git reset --hard origin/main
			git clean -fd
			cd ~/elichika2/assets
			git fetch origin main
			git reset --hard origin/main
			git clean -fd
			cd ~/elichika2
			echo "Building server..."
			go build
			echo "Finished, please run again"
			exit 0
            ;;
        3)
			clear
			python elichika_reset.py -nostage
            read -p "Press Enter to continue..." _dummy15sz35
            ;;
        4)
            clear
			pkill elichika
            sed -i 's#https://llsifas.catfolk.party/static/#http://127.0.0.1:8080/static#g' "config.json"
            sed -i 's#all#separated#g' "config.json"
            echo "Switched To LocalHost"
            read -p "Press Enter to continue..." _dummy15555
            ;;
        5)
            clear
            pkill elichika
            sed -i 's#http://127.0.0.1:8080/static#https://llsifas.catfolk.party/static/#g' "config.json"
            sed -i 's#separated#all#g' "config.json"
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
				echo "3. Add New DLP (Unstable)"
				echo "4. Add New Card (Unstable)"
				echo "5. Patch Masterdata"
				echo "6. LLASDecryptor"
				echo "7. Overwrite JP Client Dictionary"
				echo "8. GameBanana Modpage"
                echo "0. Back to Main Menu"

                read -p "Enter your choice: " dev_option

                case $dev_option in
                    1)
						clear
						pkill elichika
						python costume_addon_installer.py
                        read -p "Press Enter to continue..." _dummy01
                        ;;
                    2)
						clear
						pkill elichika
						python live_addon_installer.py
                        read -p "Press Enter to continue..." _dummy02
                        ;;
                    3)
						clear
						pkill elichika
						python tower_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    4)
						clear
						pkill elichika
						python card_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    5)
						clear
						pkill elichika
						python elichika_db_importer.py
                        read -p "Press Enter to continue..." _dummy0399
                        ;;
                    6)
						clear
						pkill elichika
						python llasdecryptor.py
                        read -p "Press Enter to continue..." _dummy02555555
                        ;;
                    7)
						clear
						pkill elichika
						python replace_jp_client_dictionary.py
                        read -p "Press Enter to continue..." _dummy02555235
                        ;;
                    8)
						clear
						pkill elichika
						xdg-open https://gamebanana.com/games/20519
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
