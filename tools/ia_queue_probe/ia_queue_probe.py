#!/usr/bin/env python3
"""Bounded read-only IA queue probe; never output credentials or raw responses."""
import argparse
import http.client
import json
import os
from pathlib import Path
import time
import urllib.parse
import xml.etree.ElementTree as ET

HOST = "s3.us.archive.org"
PREFIX = "elichika-assets-20261115-e316340d-fa6f6031"
BUCKETS = (None, *(PREFIX + suffix for suffix in ("-b00", "-b04", "-b08")))
LIMIT = 65536
CODES = frozenset({"SlowDown", "ServiceUnavailable", "InternalError", "AccessDenied", "InvalidAccessKeyId",
                   "SignatureDoesNotMatch", "RequestTimeout", "InvalidArgument", "InvalidBucketName",
                   "PermanentRedirect", "TemporaryRedirect", "AllAccessDisabled", "OperationAborted"})
DETAIL_NUMBERS = ("accesskey_ration", "accesskey_tasks_queued", "bucket_limit", "bucket_ration",
                  "bucket_tasks_queued", "rationing_engaged", "rationing_level", "total_global_limit", "total_tasks_queued")


def safe_xml(body):
    result = {"xml_code": "UNKNOWN", "spam_refusal": b"appears to be spam" in body.lower()}
    if len(body) > LIMIT or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        return result
    try:
        root = ET.fromstring(body)
        if root.tag.rsplit("}", 1)[-1] != "Error":
            return result
        codes = [node.text for node in root if node.tag.rsplit("}", 1)[-1] == "Code"]
        if len(codes) == 1 and codes[0] in CODES:
            result["xml_code"] = codes[0]
    except (ET.ParseError, ValueError):
        pass
    return result


def probe(access_key, bucket, deadline, connection_factory=None):
    if bucket not in BUCKETS:
        raise ValueError("Only reviewed owned bucket probes are allowed")
    result = {"scope": "account" if bucket is None else bucket.rsplit("-", 1)[-1],
              "over_limit": None, "http_status": None, "category": "UNAVAILABLE"}
    connection = None
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result["category"] = "DEADLINE"
            return result
        params = {"check_limit": 1, "accesskey": access_key}
        if bucket is not None:
            params["bucket"] = bucket
        # This path contains the access key and must never be logged or returned.
        path = "/?" + urllib.parse.urlencode(params)
        factory = connection_factory or (lambda timeout: http.client.HTTPSConnection(HOST, timeout=timeout))
        connection = factory(min(10, max(1, remaining)))
        connection.request("GET", path, headers={"Accept": "application/json", "User-Agent": "elichika-readonly-queue-probe/1.0"})
        response = connection.getresponse()
        result["http_status"] = response.status
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > LIMIT):
            result["category"] = "RESPONSE_BOUND"
            return result
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            result["category"] = "RESPONSE_BOUND"
            return result
        if response.status != 200:
            result.update(safe_xml(raw))
            result["category"] = "HTTP_ERROR"
            return result
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("accesskey") != access_key or value.get("bucket") not in (bucket, "" if bucket is None else bucket):
            result["category"] = "RESPONSE_BINDING"
            return result
        if type(value.get("over_limit")) is not int or value["over_limit"] not in (0, 1):
            result["category"] = "RESPONSE_SCHEMA"
            return result
        result.update(over_limit=value["over_limit"], category="READY" if value["over_limit"] == 0 else "OVER_LIMIT")
        detail = value.get("detail")
        if isinstance(detail, dict):
            selected = {key: detail[key] for key in DETAIL_NUMBERS if type(detail.get(key)) is int and 0 <= detail[key] <= 10**15}
            if selected:
                result["unstable_numeric_detail"] = selected
        return result
    except (OSError, http.client.HTTPException):
        result["category"] = "NETWORK_OR_TLS_ERROR"
        return result
    except (ValueError, TypeError, OverflowError, UnicodeError):
        result["category"] = "RESPONSE_SCHEMA"
        return result
    except Exception:
        result["category"] = "PROBE_INTERNAL_ERROR"
        return result
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    key = os.environ.pop("ELICHIKA_ARCHIVE_ACCESS_KEY", "")
    if not key or len(key) > 512 or any(char in key for char in "\r\n"):
        report = {"schema": 1, "read_only": True, "status": "ACCESS_KEY_UNAVAILABLE", "results": []}
    else:
        deadline = time.monotonic() + 45
        results = [probe(key, bucket, deadline) for bucket in BUCKETS]
        report = {"schema": 1, "read_only": True, "status": "PROBED",
                  "documented_signal": "Only over_limit 0/1 is a stable documented availability signal; numeric detail is unstable.",
                  "results": results}
    raw = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    Path(args.output).write_text(raw)
    print(raw, end="")
    return 0 if report["status"] == "PROBED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
