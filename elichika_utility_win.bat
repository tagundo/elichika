@echo off
:menu
cls
echo ==== Elichika Menu (Windows) (Converted from .sh) ====
echo.
echo ID : 26092019 (jp) ^| 25022020 (gl)
echo.
echo 1. Run Server
echo 2. Update Version
echo 3. Reset Server
echo 4. Clear Cache Database
echo 5. Switch CDN to LocalHost
echo 6. Switch CDN to Catfolk
echo 7. Developer Menu
echo 0. Exit

set /p option=Enter your choice: 

if %option%==1 goto run_server
if %option%==2 goto update_version
if %option%==3 goto reset_server
if %option%==4 goto clear_cache
if %option%==5 goto switch_localhost
if %option%==6 goto switch_catfolk
if %option%==7 goto developer_menu
if %option%==0 goto exit_menu
goto invalid_option

:run_server
cls
start elichika.exe
pause
goto menu

:update_version
cls
echo Note that this might introduce problems because the new server might not be compatible with old database format, so you might lose progress. Future versions will try to keep things compatible or have a safe way to transfer. Though, if you know what you're doing, you can still transfer things over anyway.
echo.
pause
cls
git pull
git submodule update --init --remote
go build
echo Finished, please run again
exit

:reset_server
cls
echo This will reset repostitory including serverdata.db, userdata.db and config.json, make sure back up properly.
echo.
pause
del serverdata.db
del userdata.db
del config.json
cls
python elichika_reset.py
git fetch origin main
git reset --hard origin/main
git clean -fd
cd assets
git fetch origin main
git reset --hard origin/main
git clean -fd
cd ..
echo Building executable
go build
echo Finished, please run again
exit

:clear_cache
cls
python elichika_reset.py -nostage
pause
goto menu

:switch_localhost
cls
powershell -Command "(Get-Content config.json) -replace 'https://llsifas.catfolk.party/static/', 'http://127.0.0.1:8080/static' | Set-Content config.json"
powershell -Command "(Get-Content config.json) -replace 'all', 'separated' | Set-Content config.json"
echo Switched To LocalHost
pause
goto menu

:switch_catfolk
cls
powershell -Command "(Get-Content config.json) -replace 'http://127.0.0.1:8080/static', 'https://llsifas.catfolk.party/static/' | Set-Content config.json"
powershell -Command "(Get-Content config.json) -replace 'separated', 'all' | Set-Content config.json"
echo Switched To Catfolk
pause
goto menu

:developer_menu
:dev_menu
cls
echo ==== Developer Menu ====
echo 1. Add New Costume
echo 2. Add New Live
echo 3. Add New DLP
echo 4. Patch Masterdata
echo 5. LLASDecryptor
echo 6. Overwrite JP Client Dictionary
echo 7. Fetch Package
echo 8. GameBanana Modpage
echo 0. Back to Main Menu

set /p dev_option=Enter your choice: 

if %dev_option%==1 goto add_costume
if %dev_option%==2 goto add_live
if %dev_option%==3 goto add_dlp
if %dev_option%==4 goto patch_masterdata
if %dev_option%==5 goto llasdecryptor
if %dev_option%==6 goto overwrite_jp_client
if %dev_option%==7 goto fetch_package
if %dev_option%==8 goto gamebanana_modpage
if %dev_option%==0 goto menu
goto invalid_dev_option

:add_costume
cls
python costume_addon_installer.py
pause
goto dev_menu

:add_live
cls
python live_addon_installer.py
pause
goto dev_menu

:add_dlp
cls
python tower_addon_installer.py
pause
goto dev_menu

:patch_masterdata
cls
python elichika_db_importer.py
pause
goto dev_menu

:llasdecryptor
cls
python llasdecryptor.py
pause
goto dev_menu

:overwrite_jp_client
cls
python replace_jp_client_dictionary.py
pause
goto dev_menu

:fetch_package
cls
cd assets
git submodule update --init --remote
cd ..
pause
goto dev_menu

:gamebanana_modpage
cls
start https://gamebanana.com/games/20519
goto dev_menu

:invalid_dev_option
echo Invalid option. Please try again.
pause
goto dev_menu

:invalid_option
echo Invalid option. Please try again.
pause
goto menu

:exit_menu
cls
echo Exiting Elichika Menu.
exit
