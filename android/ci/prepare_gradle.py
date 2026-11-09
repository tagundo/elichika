#!/usr/bin/env python3
"""Verify the pinned official ZIP before feeding the ordinary Gradle wrapper.

The wrapper retains its canonical URL, checksum, extraction and .ok ownership.
This build-time helper supplies only its normal, verified ZIP cache entry.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


DISTRIBUTION_URL = "https://services.gradle.org/distributions/gradle-8.9-bin.zip"
API_URL = "https://api.github.com/repos/gradle/gradle-distributions/releases/assets/178998845"
EXPECTED_BYTES = 136114148
EXPECTED_SHA256 = "d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab"
ATTEMPTS = 3
TIMEOUT_SECONDS = 20
ATTEMPT_SECONDS = 180
_OFFICIAL_HOSTS = {"api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


class PrepareError(RuntimeError):
    pass


def _official_https(url):
    value = urllib.parse.urlsplit(url)
    if (value.scheme != "https" or value.hostname not in _OFFICIAL_HOSTS
            or value.username is not None or value.password is not None
            or value.port not in (None, 443) or value.fragment):
        raise PrepareError("Gradle download must remain on an official HTTPS asset host.")


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        _official_https(newurl)
        redirected = super().redirect_request(request, fp, code, message, headers, newurl)
        if redirected is not None:
            # Initial authentication uses unredirected headers. Strip it here
            # too, so later refactors cannot forward a token to the asset CDN.
            for collection in (redirected.headers, redirected.unredirected_hdrs):
                for name in list(collection):
                    if name.lower() == "authorization":
                        del collection[name]
        return redirected


def _open(request, *, timeout):
    return urllib.request.build_opener(OfficialRedirects()).open(request, timeout=timeout)


def cache_zip_path(gradle_user_home):
    # Exact Gradle PathAssembler contract: positive MD5 integer in radix36.
    number = int.from_bytes(hashlib.md5(DISTRIBUTION_URL.encode("utf-8"), usedforsecurity=False).digest(), "big")
    alphabet, encoded = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while number:
        number, digit = divmod(number, 36)
        encoded = alphabet[digit] + encoded
    return Path(gradle_user_home).absolute() / "wrapper/dists/gradle-8.9-bin" / (encoded or "0") / "gradle-8.9-bin.zip"


def _check_components(path):
    path = Path(path)
    for item in [*reversed(path.parents), path]:
        if item.is_symlink():
            raise PrepareError("The Gradle cache must not contain symbolic links.")
        if item.exists() and item != path and not item.is_dir():
            raise PrepareError("A Gradle cache parent is not a directory.")


def _verified(path):
    _check_components(path)
    if not path.exists():
        return False
    if not path.is_file() or path.stat().st_size != EXPECTED_BYTES:
        raise PrepareError("The existing Gradle ZIP cache has the wrong type or size; it was preserved.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise PrepareError("The existing Gradle ZIP cache checksum is invalid; it was preserved.")
    return True


def _request():
    _official_https(API_URL)
    request = urllib.request.Request(API_URL, method="GET", headers={
        "Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Elichika-Gradle-build-preparation",
    })
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        # Only this exact API request receives auth; urllib never copies this
        # collection into a redirected request. No credential enters a report.
        request.add_unredirected_header("Authorization", "Bearer " + token)
    return request


def _download(path, opener):
    started = time.monotonic()
    with opener(_request(), timeout=TIMEOUT_SECONDS) as response:
        _official_https(response.geturl())
        if response.status != 200:
            raise urllib.error.HTTPError(API_URL, response.status, "Asset request failed", {}, None)
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                valid = int(length) == EXPECTED_BYTES
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise PrepareError("The official Gradle asset has an unexpected Content-Length.")
        digest, total = hashlib.sha256(), 0
        with path.open("wb") as stream:
            while True:
                if time.monotonic() - started >= ATTEMPT_SECONDS:
                    raise TimeoutError("Gradle asset read exceeded the attempt deadline.")
                block = response.read(min(1024 * 1024, EXPECTED_BYTES - total + 1))
                if not block:
                    break
                total += len(block)
                if total > EXPECTED_BYTES:
                    raise PrepareError("The official Gradle asset exceeds its pinned size.")
                digest.update(block)
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if total != EXPECTED_BYTES or digest.hexdigest() != EXPECTED_SHA256:
            raise PrepareError("The official Gradle asset failed its pinned size or SHA-256 check.")


def prepare(gradle_user_home, *, opener=None, sleeper=None):
    opener = _open if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    path = cache_zip_path(gradle_user_home)
    if _verified(path):
        return {"status": "HIT", "path": str(path), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256, "attempts": 0}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _check_components(path)
    except OSError as error:
        raise PrepareError("The Gradle cache directory cannot be prepared.") from error
    for attempt in range(1, ATTEMPTS + 1):
        temporary = None
        try:
            fd, name = tempfile.mkstemp(prefix=".verified-gradle-", suffix=".part", dir=path.parent)
            os.close(fd)
            temporary = Path(name)
            _download(temporary, opener)
            _check_components(path)
            if _verified(path):
                return {"status": "HIT", "path": str(path), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256, "attempts": attempt}
            try:
                # Hard-link publication is atomic and never overwrites a file
                # another wrapper/preparer created while this request ran.
                os.link(temporary, path)
            except FileExistsError:
                if not _verified(path):
                    raise PrepareError("A conflicting Gradle cache entry appeared.")
            return {"status": "SEEDED", "path": str(path), "bytes": EXPECTED_BYTES,
                    "sha256": EXPECTED_SHA256, "attempts": attempt,
                    "source": API_URL, "wrapper_installation_unchanged": True}
        except urllib.error.HTTPError as error:
            transient = error.code in _TRANSIENT_HTTP
            if not transient or attempt == ATTEMPTS:
                raise PrepareError("Official Gradle asset request failed (HTTP " + str(error.code) + ").") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as error:
            if attempt == ATTEMPTS:
                raise PrepareError("Official Gradle asset transport failed (" + type(error).__name__ + ").") from None
        except OSError as error:
            raise PrepareError("The verified Gradle cache could not be written.") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        sleeper(min(2 ** (attempt - 1), 4))
    raise PrepareError("Official Gradle download attempts were exhausted.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gradle-user-home", type=Path,
                        default=Path(os.environ.get("GRADLE_USER_HOME") or Path.home() / ".gradle"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = prepare(args.gradle_user_home)
    except (PrepareError, OSError) as error:
        parser.exit(1, "Gradle preparation failed: " + str(error) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
