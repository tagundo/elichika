#!/usr/bin/env python3
"""Persist allowlisted diagnostics, never account keys or raw provider logs."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_gl_visual_smoke as smoke


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    android = smoke.Android("127.0.0.1:5555", args.evidence)
    assert android.shell("getprop", "ro.hardware") == "redroid"
    report = {"captures": []}
    smoke.capture_phase_diagnostics(android, args.evidence, "scene-final", report)
    receipt_path = args.evidence / "gl/publication-receipt.json"
    trace = {"captured_unix_seconds": time.time(), "source": "literal public fixture pack names in the disposable provider log", "observations": []}
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        packs = {Path(path).name for path in receipt["outputs"] if path.startswith("static/")}
        assert len(packs) == 6 and all(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name) for name in packs)
        try:
            text = android.read("/sdcard/Download/sukusta/logs/elichika.log").decode("utf-8", "replace")
            for line in text.splitlines():
                for pack in packs:
                    if pack in line:
                        match = re.search(r"\d{2}:\d{2}:\d{2}", line)
                        trace["observations"].append({"pack": pack, "clock": match.group() if match else None})
            trace["observations"] = trace["observations"][:256]
        except Exception as error:
            trace["unavailable"] = type(error).__name__
    trace["limitation"] = "No entry means no request trace was observed; staged pack presence alone is not a client request or scene-use proof. No raw log lines or API keys are persisted."
    (args.evidence / "public-pack-trace.json").write_text(json.dumps(trace, indent=2) + "\n")


if __name__ == "__main__":
    main()
