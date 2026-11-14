"""Accepted pure checkpoint_failure copied verbatim from the pinned GL source.

Source /dev/shm/sifas-gl-primary-failure-checkpoint-20261114/r2/qa/native_ocr_control.py
SHA256 cad50d3fa3965a857ef9012a9b84b81540adff098fadd381d32ce88b7acd0abd.
Only this pure function is reused; no GL runtime or profile is imported.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import traceback


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checkpoint_failure(report, error, save, started):
    """Preserve the primary failure before cleanup; log no exception text."""
    current_error=type(error).__name__+': '+str(error);current_trace=traceback.format_exc()
    primary=report.get('primary_failure_recorded') is not True
    report['status']='FAIL'
    if primary:
        report['primary_failure_recorded']=True
        report['error']=current_error;report['traceback']=current_trace
    else:
        report.setdefault('secondary_failure_checkpoints',[]).append({'error':current_error,'traceback':current_trace})
    try:
        save()
    except Exception as failed:
        report[('primary' if primary else 'secondary')+'_failure_checkpoint_error_class']=type(failed).__name__
    safe_name=lambda value:re.sub(r'[^A-Za-z0-9_.<>-]','_',value)[:96]
    breadcrumb={'event':'qa-primary-failure' if primary else 'qa-secondary-failure','exception_class':safe_name(type(error).__name__),
        'traceback_sha256':digest(current_trace.encode()),
        'trace_frames':[{'filename':safe_name(Path(frame.filename).name),'line':frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__,limit=-16)],
        'elapsed_seconds':round(time.monotonic()-started,3)}
    checkpoint_error=report.get(('primary' if primary else 'secondary')+'_failure_checkpoint_error_class')
    if checkpoint_error:
        breadcrumb['checkpoint_error_class']=safe_name(checkpoint_error)
    try:
        print(json.dumps(breadcrumb,separators=(',',':')),flush=True)
    except Exception as failed:
        report[('primary' if primary else 'secondary')+'_failure_breadcrumb_error_class']=type(failed).__name__
