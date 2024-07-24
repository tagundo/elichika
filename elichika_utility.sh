#!/bin/bash

while true; do
    clear
    echo "==== Elichika Menu ===="
    echo ""
    echo "ID : 26092019 (jp) | 25022020 (gl)"
    echo ""
    echo "1. Run Server"
    echo "2. Update Version"
    echo "3. Reset Server"
    echo "4. Clear Cache Database"
    echo "5. Switch CDN to LocalHost"
    echo "6. Switch CDN to Catfolk"
    echo "7. Developer Menu"
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
			echo "Note that this might introduce problems because the new server might not be compatible with old database format, so you might lose progress. Future versions will try to keep things compatible or have a safe way to transfer. Though, if you know what you're doing, you can still transfer things over anyway."
			echo ""
			read -p "are you sure want update? enter to procced or exit termux (ctrl + c) if you don't want" _dummy33534
			pkill elichika
			clear
			git pull
			git submodule update --init --remote
			go build
			echo "Finished, please run again"
			exit 0
            ;;
        3)
			clear
			read -p "do you want reset everything? enter to procced or exit termux (ctrl + c) if you don't want" _dummy53534
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
			go build
			echo "Finished, please run again"
			exit 0
            ;;
        4)
			clear
			python elichika_reset.py -nostage
            read -p "Press Enter to continue..." _dummy15sz35
            ;;
        5)
            clear
			pkill elichika
            sed -i 's#https://llsifas.catfolk.party/static/#http://127.0.0.1:8080/static#g' "config.json"
            sed -i 's#all#separated#g' "config.json"
            echo "Switched To LocalHost"
            read -p "Press Enter to continue..." _dummy15555
            ;;
        6)
            clear
            pkill elichika
            sed -i 's#http://127.0.0.1:8080/static#https://llsifas.catfolk.party/static/#g' "config.json"
            sed -i 's#separated#all#g' "config.json"
            echo "Switched To Catfolk"
            read -p "Press Enter to continue..." _dummy15235
            ;;
        7)
            # Dev Menu
            while true; do
                clear
                echo "==== Developer Menu ===="
				echo "1. Add New Costume"
				echo "2. Add New Live"
				echo "3. Add New DLP"
				echo "4. Patch Masterdata"
				echo "5. LLASDecryptor"
				echo "6. Overwrite JP Client Dictionary"
				echo "7. Fetch Package"
                echo "0. Back to Main Menu"

                read -p "Enter your choice: " dev_option

                case $dev_option in
                    1)
						clear
						pkill elichika
						cd ~/elichika2/assets
                        git submodule update --init --remote
                        cd ~/elichika2
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
						cd ~/elichika2/assets
                        git submodule update --init --remote
                        cd ~/elichika2
						python tower_addon_installer.py
                        read -p "Press Enter to continue..." _dummy03777
                        ;;
                    4)
						clear
						pkill elichika
						cd ~/elichika2/assets
                        git submodule update --init --remote
                        cd ~/elichika2
						python elichika_db_importer.py
                        read -p "Press Enter to continue..." _dummy0399
                        ;;
                    5)
						clear
						pkill elichika
						python llasdecryptor.py
                        read -p "Press Enter to continue..." _dummy02555555
                        ;;
                    6)
						clear
						pkill elichika
						python replace_jp_client_dictionary.py
                        read -p "Press Enter to continue..." _dummy02555235
                        ;;
                    7)
						clear
						pkill elichika
						cd ~/elichika2/assets
                        git submodule update --init --remote
                        cd ~/elichika2
                        read -p "Press Enter to continue..." _dummy03998
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
