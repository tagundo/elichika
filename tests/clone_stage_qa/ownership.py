"""Guard every ADB call and cleanup in this separately owned manual QA job."""
import json
import os
from pathlib import Path
import re
import subprocess

CONTAINER = "clone-stage-original-qa"
IMAGE = "redroid/redroid@sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa"
SERIAL = "127.0.0.1:5555"


def validate(value, env):
    if env.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"[1-9][0-9]*", env.get("GITHUB_RUN_ID", "")):
        raise ValueError("OWNED_MANUAL_GITHUB_JOB_REQUIRED")
    if value["Name"] != "/" + CONTAINER or value["Config"]["Image"] != IMAGE or not value["State"]["Running"]:
        raise ValueError("EXACT_RUNNING_CONTAINER_REQUIRED")
    labels = value["Config"].get("Labels", {})
    if labels.get("elichika.qa.scope") != "clone-stage" or labels.get("elichika.qa.run") != env["GITHUB_RUN_ID"]:
        raise ValueError("CONTAINER_OWNERSHIP_MISMATCH")
    if value["NetworkSettings"]["Ports"].get("5555/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "5555"}]:
        raise ValueError("LOOPBACK_ANDROID_PORT_REQUIRED")
    expected = str(Path(env["RUNNER_TEMP"]).resolve() / "clone-stage-data")
    mounts = [item for item in value["Mounts"] if item["Destination"] == "/data"]
    if len(mounts) != 1 or mounts[0]["Type"] != "bind" or mounts[0]["Source"] != expected or not mounts[0]["RW"]:
        raise ValueError("FRESH_JOB_DATA_MOUNT_REQUIRED")
    return {"container": CONTAINER, "run_id": env["GITHUB_RUN_ID"], "image": IMAGE,
            "serial": SERIAL, "data_mount": expected}


def verify():
    values = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER], timeout=15))
    if len(values) != 1:
        raise ValueError("EXACTLY_ONE_CONTAINER_REQUIRED")
    return validate(values[0], os.environ)


def adb_args(parts):
    if parts == ["connect", SERIAL] or parts == ["disconnect", SERIAL]:
        return parts
    if len(parts) >= 3 and parts[:2] == ["-s", SERIAL]:
        return parts
    raise ValueError("EXACT_OWNED_ADB_SERIAL_REQUIRED")


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
