#!/usr/bin/env python3
"""Refuse all device actions unless this manual GHA job owns the target Docker."""
import json
import os
from pathlib import Path
import re
import subprocess

CONTAINER = 'clone-material-unity-qa'
IMAGE = 'redroid/redroid@sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa'


def validate_container(value, environ):
    if environ.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'[1-9][0-9]*', environ.get('GITHUB_RUN_ID', '')):
        raise ValueError('Only the explicitly owned disposable manual GitHub Actions job is allowed')
    if value['Name'] != '/' + CONTAINER or value['Config']['Image'] != IMAGE or not value['State']['Running']:
        raise ValueError('Unexpected or stopped Docker target')
    labels = value['Config'].get('Labels', {})
    if labels.get('elichika.qa.scope') != 'clone-material' or labels.get('elichika.qa.run') != environ['GITHUB_RUN_ID']:
        raise ValueError('Target ownership labels do not match this job')
    if value['NetworkSettings']['Ports'].get('5555/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': '5555'}]:
        raise ValueError('Unexpected Android network exposure')
    expected = str(Path(environ['RUNNER_TEMP']).resolve() / 'clone-material-data')
    mounts = [mount for mount in value['Mounts'] if mount['Destination'] == '/data']
    if len(mounts) != 1 or mounts[0]['Type'] != 'bind' or mounts[0]['Source'] != expected or not mounts[0]['RW']:
        raise ValueError('Android data must be this job\'s fresh owned bind mount')
    return {'container': CONTAINER, 'run_id': environ['GITHUB_RUN_ID'], 'image': IMAGE,
            'data_mount': expected, 'serial': '127.0.0.1:5555'}


def verify():
    values = json.loads(subprocess.check_output(['docker', 'inspect', CONTAINER], timeout=15))
    if len(values) != 1:
        raise ValueError('Exactly one owned container is required')
    return validate_container(values[0], os.environ)


if __name__ == '__main__':
    print(json.dumps(verify(), sort_keys=True))
