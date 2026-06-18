# elichika3
This is a fork of [[tatara_hisoka/elichika]](https://gitlab.com/tatara_hisoka/elichika), which is based on [[arina999999997/elichika]](https://github.com/arina999999997/elichika) and originally derived from [[YumeMichi/elichika]](https://github.com/YumeMichi/elichika).

**Note**: This repository is intended for my personal use.

For modding support, I recommend using [[tatara_hisoka/elichika]](https://gitlab.com/tatara_hisoka/elichika).
For playing the game without mods, use [[arina999999997/elichika]](https://github.com/arina999999997/elichika).


## Installing
### Disclaimer about the client
The clients provided might not work on your specific devices. If it doesn't work, try using another device or an emulator. DO NOT ASK ME, ASK WHO MADE FORK OKAY?

Note that this part concern only this server implementation, and it only provide the easiest way to do things.

You should check out checkout the [LL hax wiki](https://carette.codeberg.page/ll-hax-docs/sifas/) for clarification and general knowledge, as it explain things better (or it can lead you to places where you can ask questions).

### Android
To install the server, first install termux, you can get it from [f-droid](https://f-droid.org/en/packages/com.termux/) or [github](https://github.com/termux/termux-app#github). Note that the google play store version will most likely NOT WORK.

Then run the install script inside termux, this will take care of everything:
```
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install.sh | bash
```

To run a command, copy (or type) it and hit the enter button.
### PC (Windows, Linux, MacOS)
You can setup the server in a desktop machine to play on android or ios.

#### Setup manually
Install git and go, and then use the same install script with termux (on Windows, run inside git bash or some other linux shell emulator):

```
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install.sh | bash
```

This will leave some trashes, so you can clone the respository and build manually, look at the scripts for the necessary steps.

## Running the server
After installing, you need to run the server to play using the following command:

```
~/run_elichika3
```

If you have GUI for Windows/Linux, you can also just run the executable directly.

Note that whenever you want to play, the server need to be on, so if you already closed termux or the server, you will have to run it again.

## Updating the server
There are 2 ways to update the server:

- The basic update is more stable but will take longer because it will be downloading more stuff and rebuilding more stuff.
- The normal update is faster, but if your server version is too old, something might break.

Regardless of what update methods you want, it is also a good idea to backup ``userdata.db`` or to export your data (with the WebUI) before doing this, as updating from a too old version might result in breaking changes anyway.


### Basic update
You can update the server using a basic update logic:

```
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/basic_update.sh | bash
```

If you have a new enough version, you can also run:

```
~/basic_update_elichika3
```
to do the same thing.

The basic update basically backup your data, reinstall, and then restore your data. This will work for pretty much every version, but it can be slower than the normal update.

### Normal update
If you update the server regularly, then you can use the normal update and it should work:

```
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/update.sh | bash
```

If your version is new enough, then running:

```
~/update_elichika3
```

would be enough.

## Test build (Test branch)
If you want to try the `Test` branch without disturbing your stable install, you can install it into a **separate** directory (`elichika3_test`). The stable (`elichika3`) and test (`elichika3_test`) installs are independent and can coexist, each with its own shortcuts.

To install the test build (the installer is fetched from `main`; it clones the `Test` branch's code):

```
curl -L https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install_test.sh | bash
```

This creates a parallel set of shortcuts so it's easy to use from Termux on Android:

```
~/run_elichika3_test            # run the test server
~/menu_elichika3_test           # open the menu for the test build
~/update_elichika3_test         # normal update (pulls the Test branch)
~/basic_update_elichika3_test   # basic update (reinstalls from the Test branch)
```

The update commands work exactly like the stable ones, except they track the `Test` branch and operate on the `elichika3_test` directory. As with the stable build, backing up `userdata.db` (or exporting via the WebUI) before updating is recommended.

## Playing the game
With the server running, and the client network setup correctly, simply open the game and play.

The first time you login, you will be given a random user id. If you wish to, you can use the transfer account to obtain a specific user id.

### Multi accounts / Account transfer
You can use the account transfer system to switch / create account. Select ``transfer with password``. 
![Transfer system](docs/images/transfer_1.png)

Enter your user / player id and a password:

- UserId is an non-negative integer with at most 9 digits.
- If user is in the database, password will be checked against the stored password.
- Otherwise a new account with that player id and password.
    - You can also leave the password empty.
    - If you are not running the server yourself, it's highly recommended that you setup a password, because other user can take over your account if they know your user id.
    - Passwords are securely stored with bcrypt.

![Set the id and password](docs/images/transfer_2.png)

After that, confirm the transfer and you can login with the new user id.

![Confirm transfer](docs/images/transfer_3.png)

At any point, you can use the transfer id system inside the game to change your password.

![Use the system](docs/images/transfer_4.png)
![Set up new password](docs/images/transfer_5.png)
![Result](docs/images/transfer_6.png)

### Client version
You can use both the Japanese and Global client for the same server (and the same database).

However, it's recommended to not play one account (user id) in both Japanese and Global client, because some contents are exclusive to only 1 server, and will cause the client to freeze.

### Multi devices
You can use multiple devices to play the game from one server, if you have set things up correctly.

Playing the game on another device while the current one is running will cause the current one to disconnect, preventing any error being done to your user data.

## WebUI
The WebUI allow you to interact with the server in a more direct way, both to change the server and to change your player data.

To use the WebUI, navigate to the relevant address using a web browser.

### Admin
The admin WebUI is used to change the server's behaviors.

It can be found at: `<server_address>/webui/admin`, which default to http://127.0.0.1:8080/webui/admin

To use the admin webui, you will need the admin password, but it is empty by default.

Checkout the various features for a detailed explaination of each of them.

Detailed explanations of some config options:

- Server's address:

    - The address to host the server at.
    - Default to ``0.0.0.0:8080`` (server listen at port 8080 on all interfaces).

- CDN server's address:

    - The server for clients to download assets.
    - Default to  https://llsifas.imsofucking.gay/static/ (special thanks to sarah for hosting it).
    - `elichika` also has the ability to host the CDN itself:

        - To do this, put the relevant files in `elichika/static`:
          - For each package, the server expect it in `elichika/static/<package_name>`
        - Then set the CDN server address to the STRING (no protocol) `elichika` (or `elichika_tls` if you're using HTTPS).
        - This will automatically use whatever the address the client reach `elichika` with as the CDN server.
        - Aside from that, you can also just use the address like normal.
        - You should look into this if you want to further develop the game/server, as doing so might require redownloading things a lot.
    - You can also use other CDNs, but keep in mind that there are some requirements that need to be met, otherwise some download will result in errors.

- Cache CDN packs locally and serve them (`cdn_cache`):

    - When enabled, `elichika` stops handing the upstream CDN address to the client and serves every pack itself, acting as the CDN.
    - The first time a pack is needed, `elichika` downloads it from the CDN server's address (the upstream) into the cache directory and then serves it from there. Later requests are served straight from the cache without touching the network.
    - The cache directory is set by `cdn_cache_dir`:
        - Leave it empty (default) and packs are cached in the existing `static/` folder. This is the simplest option for PC/Docker, where no extra folder is needed.
        - On termux/Android, set it to the shared sukusta folder (e.g. `~/storage/downloads/sukusta/packs`) so the cache is shared with the game and the `llas_asset_extractor.py` tooling. A leading `~/` is expanded to your home directory.
    - Lookup order when serving a pack is `<cdn_cache_dir>/` -> `static/` -> download from the upstream into `<cdn_cache_dir>/`.
    - This is useful if you want a local mirror that fills itself up on demand: keep the CDN server's address pointed at a real CDN (the upstream to pull from) and turn this on.

- Resource config:

    - The config of how the resources work on the server.
    - `original` means the resources behave like it would in the original server. Every action that cost resources will consume those resources.
    - `comfortable` is the default settings. Things like star gems, LP, AP are unlimited. The daily song play limit or the daily tap bond limit is also removed. This is the recommended settings if you just want to play and experience the game without all the money-making limitation.
    - `free` is the free settings. Generally, resources can only go up and not down.
    - Keep in mind that some resources/systems are not controlled by these settings, but they are pretty minor.
    - And this doesn't apply to the accessories (but apply to the accessory items).

- Default item count:

    - The amount of items to give a player to start with.
    - Default to a generous amount, but you can set it to 0 to have a more true experience.
    - Note that you have to obtain the item in game first before you are given the "default item count" amount of that item.


### User
The user WebUI has features to help you with playing the game:

- Doing things quickly in your account, or setting up a maxed account.
- Adding resources to skip the grind.
- Import export data.

It can be located at: `<server_address>/webui/user`, which default to http://127.0.0.1:8080/webui/user

Check out the user [docs](webui/user/README.md) for more details.

Note that the user WebUI is not an account data editor, something like that might be developed later on.

## More docs
Checkout the [docs](https://github.com/arina999999997/elichika/tree/master/docs) for more details on the server and how to do more advanced stuffs.

Docs can also be found in relevant package in `.md` files. 

## Credit
Special thanks to the LL Hax community in general for:

- Archiving and hosting database / assets
- General and specific knowledges about the game

Even more special thanks for the specific individuals or groups (in no particular order):

- YumeMichi for original elichika.
- arina999999997 for fork elichika.
- triangle for informations and scripts to encode/decode database, for patching the iOS clients, for daily theater logs, for databases across all versions, and for various missing asset files.
- gam for various missing asset files.
- [SIFAStheatre](https://twitter.com/SIFAStheatre) and [Idol Story](https://twitter.com/idoldotst) for Daily theater English tranlation and for the original Japanese transcript.
- ethan for hosting various resource, for hosting a public testing server, and for help with docker.
- [yunimoo](https://github.com/yunimoo) for help with docker, and for resolving TODOs.
- rayfirefirst, cppo for various cryptographic keys.
- tungnotpunk for iOS client and help with network structure.
- Suyooo for the very helpful [SIFAS wiki](https://suyo.be/sifas/wiki/), for providing more accurate stage data, and for the bad word lists.
- sarah for hosting public Internet CDN.
- AuahDark for helping with the embedded client development.
- Caret for the LL Hax discord.
- Yousifrill for drawing body texture.
- [NishikinoClinic](https://x.com/NishikinoClinic) for SIFAS Tool.
- [AyakaMods](https://ayakamods.cc/games/love-live-school-idol-festival-all-stars.217/) for SIFAS modpage.
- And other people who more than deserve to be here.

## Disclaimer
This repository is designed for single player of SIFAS only.
