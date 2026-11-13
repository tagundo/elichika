"""Fallback only for this run's tracked exact source Go child after watchdog."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    runtime=args.evidence/'host-go-runtime.json'
    if not runtime.is_file() or not args.receipt.is_file():return
    record=json.loads(runtime.read_text());expected=json.loads(args.receipt.read_text())
    pid=record['pid']
    assert type(pid) is int and pid>1
    proc=Path('/proc')/str(pid)
    result={'original_identity':record,'scope':'Only exact tracked Go PID/startticks/executable may be signalled'}
    if proc.exists():
        ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
        assert ticks==record['start_ticks'] and str((proc/'exe').resolve(strict=True))==expected['binary_path']
        with (proc/'exe').open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
        assert actual==record['binary_sha256']==expected['server_fixture']['binary_sha256']
        os.kill(pid,signal.SIGTERM)
        end=time.monotonic()+8
        while proc.exists() and time.monotonic()<end:time.sleep(.1)
        if proc.exists():
            assert (proc/'stat').read_text().rsplit(')',1)[1].split()[19]==ticks
            os.kill(pid,signal.SIGKILL)
            end=time.monotonic()+2
            while proc.exists() and time.monotonic()<end:time.sleep(.1)
    result['original_process_absent']=not proc.exists()
    (args.evidence/'fallback-owned-Go-stop.json').write_text(json.dumps(result,indent=2)+'\n')
    assert result['original_process_absent']


if __name__=='__main__':main()
