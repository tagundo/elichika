"""Pinned PlayCover default non-PlaySign/non-bypass entitlement composition.

Derived from source commit a7b1693d4fa4310367990cd35d4ebafb20e5c965:
Entitlements.setBaseEntitlements/composeEntitlements, Rules/default.yaml allow,
and PlayRules.buildRules. It never reads installed app entitlements.
"""
from pathlib import Path

def expected(home):
    base = {key: True for key in (
        'com.apple.security.assets.movies.read-write', 'com.apple.security.assets.music.read-write',
        'com.apple.security.assets.pictures.read-write', 'com.apple.security.device.audio-input',
        'com.apple.security.network.client', 'com.apple.security.network.server',
        'com.apple.security.device.bluetooth', 'com.apple.security.device.camera',
        'com.apple.security.device.microphone', 'com.apple.security.device.usb',
        'com.apple.security.files.downloads.read-write', 'com.apple.security.files.user-selected.read-write',
        'com.apple.security.personal-information.addressbook', 'com.apple.security.personal-information.calendars',
        'com.apple.security.personal-information.location', 'com.apple.security.print', 'com.apple.security.app-sandbox')}
    root = str(Path(home))
    rules = [
        '(allow user-preference-write (preference-domain ".GlobalPreferences"))',
        '(allow user-preference-read (preference-domain ".GlobalPreferences"))',
        f'(allow file* file-read* file-write* file-write-data file-read-metadata file-ioctl (subpath "{root}/Library/Containers/io.playcover.PlayCover"))',
        f'(allow file* file-read* file-read-metadata file-ioctl (subpath "{root}/Library/Frameworks/PlayTools.framework"))',
        f'(allow file* file-read* (subpath "{root}/Library/Group Containers/"))',
        '(allow network* ipc-posix*)',
        '(deny process-fork)']
    critical = ['/bin/bash', '/usr/sbin/sshd', '/usr/libexec/ssh-keysign', '/bin/sh', '/etc/ssh/sshd_config', '/usr/libexec/sftp-server', '/usr/bin/ssh']
    rules += [f'(deny file* file-read* file-read-metadata file-ioctl (literal "{path}"))' for path in critical]
    base['com.apple.security.temporary-exception.sbpl'] = rules
    return base
