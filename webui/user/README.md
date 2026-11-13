# User features for WebUI
## Authentication
The following requirements are needed for authentication:

- User need to login via user id and password (empty string if they haven't set one)
- User must have completed the tutorial

The requirements are necessary for some feature, but they also present spamming (but maybe not a lot).

The native Elichika app can instead open its own local server using a private,
per-process capability. Its account picker lists stored account IDs for click
login. This does not enable password-free access for ordinary remote browsers.
The private WebUI capability is separate from the server readiness nonce.

After selecting an account, **Client login / migration** shows the server
connection details and an account backup export. Existing bcrypt passwords
cannot be recovered. The user can explicitly set or generate a new client
password, which preserves progress, authorization keys and current sessions.
New managed passwords use the game's documented 8–16 ASCII letter/digit policy;
generated passwords contain 16 cryptographically random alphanumeric characters.
Existing hashes and already saved credentials are not automatically changed.
Only that new password can be revealed or copied later. Its local copy is
AES-GCM encrypted using a random 32-byte, mode-0600 installation key
(`.local-webui-credentials.key`), and every reveal checks the current bcrypt
hash. Changing the password elsewhere invalidates the saved copy. Neither the
encrypted local credential nor the install key is included in account exports;
database imports and gameplay resets keep the current installation's password.

## Locale
When using the WebUI, it's important to choose the correct client language. This is mainly for the server, as some content might not exist for other languages and will make your account unavailable.

In the future, maybe the client language can also change how the WebUI display things.

## Features
Some features and what they do. Viewing them on the webui also explain the feature a bit more.
### Account builder
This allow you to do things fast in the game, it also has a button to get you a maxed out account (based on your locale).
### Resource helper
This allow you to get items in the game so you can progress faster, but it won't do the thing for you like the account builder.
### Reset progress
This allow you to reset and play stuff again, while keeping the other data of your account.
### Import/Export account
Allow you to export / import your account:

- Exporting to .db file allow you to save all data that is compatible with elichika.
- Exporting to .json allow you to get the canonical network data, so you can import them elsewhere if necessary.

Importing an account will overwrite your (account logged into webui's) current progress.

### Advanced
Some features require advancded understanding of the game's internal (or the server too).

- Add item using id: Allow user to add an item directly using id.
