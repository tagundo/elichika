# elichika
A fork of https://github.com/arina999999997/elichika based on https://github.com/YumeMichi/elichika, check out the original.

## What is the difference between github (arina999999997) and gitlab (tatara_hisoka)?
- Made for termux only
- Add-on content support
- Added SDK of developement content
- Added menu_elichika2
- Added serverdata.db & userdata.db
- Restore unused content
	- lvl 500 bond limit
	- lvl 100 card once kizuna board is maxed out
	- Appeal Chance
		- GotHeal
		- GotShield
		- GotVoltageByVo
		- GotVoltageBySp
		- GotVoltageByGd
		- GotVoltageBySk
	- Liella song
	- Expert difficulty song
	- Item
		- Leader Insight Guaranteed
		- Increase Rare Item Drop Rate
		- School Idol Radiance
	- Special SP Cutscene In Lanzhu & Mia
- Various changes
	- Replace pre-render MV with realtime (save hundred megabyte drive)
	- Disable useless setting
	- Fixed some songs not unlocked
	- Fixed aishiteru banzai formation
	- Increase max LP limit same as official
	- Increase limit skip ticket to 100
	- Make all member use swimsuit in tutorial
	- Disable 60fps live quality, you can enable on graphics setting
	- Unlocked bond story
	- Sorted costume by old to new
- Fixed consistent dictionary
- Clone as elichika2 folder so you can install safely

## Installing
Note that this part concern only this server implementation, and it only provide the easiest way to do things.

You should check out checkout the [LL hax wiki](https://carette.codeberg.page/ll-hax-docs/sifas/) for clarification and general knowledge, as it explain things better (or it can lead you to places where you can ask questions).

### Android
To install the server, first install termux, you can get it from [f-droid](https://f-droid.org/en/packages/com.termux/) or [github](https://github.com/termux/termux-app#github). Note that the google play store version will most likely NOT WORK.

Then run the install script inside termux, this will take care of everything:
```
curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/install.sh | bash
```

To run a command, copy (or type) it and hit the enter button.

#### Running the server
After installing, you need to run the server to play using the following command:

```
~/run_elichika2
```

alternate menu

```
~/menu_elichika2
1
```

Note that whenever you want to play, the server need to be on, so if you already closed termux or the server, you will have to run it again.

## Updating the server
There are 2 ways to update the server:

- The basic update is more stable but will take longer because it will be downloading more stuff and rebuilding more stuff.
- The normal update is faster, but if your server version is too old, something might break.

Regardless of what update methods you want, it is also a good idea to backup ``userdata.db`` or to export your data (with the WebUI) before doing this, as updating from a too old version might result in breaking changes anyway.


### Basic update
You can update the server using a basic update logic:

```
curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/basic_update.sh | bash
```

If you have a new enough version, you can also run:

```
~/basic_update_elichika
```
to do the same thing.

The basic update basically backup your data, reinstall, and then restore your data. This will work for pretty much every version, but it can be slower than the normal update.

### Normal update
If you update the server regularly, then you can use the normal update and it should work:

```
curl -L https://gitlab.com/tatara_hisoka/elichika/-/raw/main/bin/update.sh | bash
```

If your version is new enough, then running:

```
~/update_elichika2
```

would be enough.

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
	- if you don't want to start from the beginning, use this player ID
		- ID : 26092019 (jp) | 25022020 (gl)
![Set the ID and password](docs/images/transfer_2.png)

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

Currently, it only has the config editor, but in the future it can include things like starting/ending event and such.

Detailed explanations of some config options:

- Server's address:

    - The address to host the server at.
    - Default to ``0.0.0.0:8080`` (server listen at port 8080 on all interfaces).

- CDN server's address:

    - The server for clients to download assets.
    - Default to  https://llsifas.catfolk.party/static/ (special thanks to sarah for hosting it).
    - `elichika` also has the ability to host the CDN itself:

        - To do this, put the relevant files in `elichika/static/`.
        - Then set the CDN server address to the STRING (no protocol) `elichika` (or `elichika_tls` if you're using HTTPS).
        - This will automatically use whatever the address the client reach `elichika` with as the CDN server.
        - Aside from that, you can also just use the address like normal.
        - You should look into this if you want to further develop the game/server, as doing so might require redownloading things a lot.
    - You can also use other CDNs, but keep in mind that there are some requirements that need to be met, otherwise some download will result in errors.

- Resource config:

    - The config of how the resources work on the server.
    - `original` means the resources behave like it would in the original server. Every action that cost resources will consume those resources.
    - `comfortable` is the default settings. Things like star gems, LP, AP are unlimited. The daily song play limit or the daily tap bond limit is also removed. This is the recommended settings if you just want to play and experience the game without all the money-making limitation.
    - `free` is the free settings. Generally, resources can only go up and not down.
    - Keep in mind that some resources/systems are not controlled by these settings, but they are pretty minor.
    - And this doesn't apply to the accessories (but apply to the accessory items).
	
- Lesson drop type:

    - `fixed` is use skill id on insightskill.json
    - `gacha` is like common gacha works.
    - `random` (PLACEHOLDER) is give 12 randomize insight skill.

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
- triangle for informations and scripts to encode/decode database, for patching the ios clients, and for daily theater logs.
- [SIFAStheatre](https://twitter.com/SIFAStheatre) and [Idol Story](https://twitter.com/idoldotst) for Daily theater English tranlation and for the original Japanese transcript.
- ethan for hosting various resource and hosting a public testing server.
- rayfirefirst, cppo for various cryptographic keys.
- tungnotpunk for ios client and help with network structure.
- Suyooo for the very helpful [SIFAS wiki](https://suyo.be/sifas/wiki/), for providing more accurate stage data, and for the bad word lists.
- sarah for hosting public Internet CDN.
- Caret for the LL Hax discord.
- Yousifrill for drawing body texture.
- And other people who more than deserve to be here but I can't quite recall right now.