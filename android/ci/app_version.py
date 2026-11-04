"""Derive APK CalVer fields; this module never authorizes publication."""
import argparse
import datetime
from pathlib import Path
import re


VERSION = re.compile(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})(?:\.(0|[1-9][0-9]?))?\Z")


def calver(value):
    match = VERSION.fullmatch(value)
    if match is None:
        raise ValueError('Version must be YYYY.MM.DD[.N], with N between 0 and 99')
    year, month, day = map(int, match.group(1, 2, 3))
    datetime.date(year, month, day)
    code = (year * 10000 + month * 100 + day) * 100 + int(match.group(4) or 0)
    if not 0 < code <= 2_100_000_000:
        raise ValueError('CalVer exceeds the Android versionCode limit')
    return value, code


def derive_version(release_tag='', build_version='', ref='', today=None):
    if release_tag and build_version:
        raise ValueError('release_tag and build_version cannot be used together')
    if build_version:
        # A tag ref itself authorizes the existing publish job. Do not let an
        # artifact-only version override accidentally ride that publication path.
        if ref.startswith('refs/tags/'):
            raise ValueError('build_version requires a branch ref, not a tag ref')
        return calver(build_version)
    if release_tag:
        if not release_tag.startswith('v'):
            raise ValueError('release_tag must start with v')
        return calver(release_tag[1:])
    if ref.startswith('refs/tags/'):
        tag = ref.removeprefix('refs/tags/')
        if not tag.startswith('v'):
            raise ValueError('Release tag must start with v')
        return calver(tag[1:])
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    _, code = calver(today.strftime('%Y.%m.%d'))
    return today.strftime('%Y.%m.%d') + '-dev', code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag', default='')
    parser.add_argument('--build-version', default='')
    parser.add_argument('--ref', default='')
    parser.add_argument('--github-output', type=Path, required=True)
    args = parser.parse_args()
    try:
        name, code = derive_version(args.release_tag, args.build_version, args.ref)
    except ValueError as error:
        parser.error(str(error))
    with args.github_output.open('a') as output:
        output.write(f'name={name}\ncode={code}\n')
    print(f'elichika version: {name} (code {code})')


if __name__ == '__main__':
    main()
