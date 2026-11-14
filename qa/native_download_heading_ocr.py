"""One bounded, current-frame heading read; never authorizes input itself."""
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from native_download_heading import (runtime_heading_eligible,derive_heading_plan,
    render_heading,parse_heading_tsv,merge_heading_metadata)

ENGLISH_SHA256='7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@functools.lru_cache(maxsize=1)
def engine_provenance():
    executable=shutil.which('tesseract')
    if executable is None:raise FileNotFoundError('Tesseract executable is unavailable')
    engine=Path(executable).resolve(strict=True)
    data=Path(os.environ.get('TESSDATA_PREFIX','/usr/share/tesseract-ocr/5/tessdata')).resolve(strict=True)
    model=data/'eng.traineddata'
    if digest(model)!=ENGLISH_SHA256:raise ValueError('English OCR model differs from the reviewed pin')
    version=subprocess.run([str(engine),'--version'],capture_output=True,timeout=5,check=True)
    return {'engine':str(engine),'engine_sha256':digest(engine),'version':version.stdout.decode(),
            'version_argv':[str(engine),'--version'],'version_stderr':version.stderr.decode(),
            'tessdata_dir':str(data),'model_sha256':ENGLISH_SHA256,
            'tsv_config_sha256':digest(data/'configs/tsv')}


def _write_json(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
        stream.flush();os.fsync(stream.fileno())


def _raw_result(evidence,label,stdout,stderr):
    result={}
    for key,suffix,data in (('tsv','tsv',stdout),('stderr','stderr',stderr)):
        if data is None:data=b''
        if isinstance(data,str):data=data.encode()
        path=evidence/(label+'-download-heading.'+suffix)
        with path.open('xb') as stream:stream.write(data)
        result[key]={'path':path.name,'bytes':len(data),'sha256':digest(path)}
    return result


def read_heading(image,metadata,*,evidence,label,source_png,fixture_probe=False,
                 runner=subprocess.run,pins=engine_provenance):
    """Return supplemented metadata and a retained diagnostic, at most once.

    fixture_probe is only the explicit pre-UI two-image CI verifier. The live
    settings caller always retains runtime eligibility and existing UI gates.
    """
    evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',label):raise ValueError('Invalid heading proof label')
    record_path=evidence/(label+'-download-heading.json')
    intent_path=evidence/(label+'-download-heading-intent.json')
    if record_path.exists() or intent_path.exists():
        return metadata,{'status':'ALREADY_ATTEMPTED_NO_SECOND_OCR','record':record_path.name,'input_performed':False}
    if not fixture_probe and not runtime_heading_eligible(metadata):
        return metadata,{'status':'NOT_ELIGIBLE_NO_OCR','input_performed':False}
    record={'status':'NO_OCR_PLAN','source_screenshot_sha256':metadata.get('screenshot_sha256'),
            'scope':'CURRENT_FRAME_HEADING_OCR_ONLY_NO_INPUT','fixture_probe':fixture_probe,
            'OCR_invocations':0,'input_performed':False,'record':record_path.name}
    result=metadata
    try:
        if digest(source_png)!=metadata.get('screenshot_sha256'):raise ValueError('Current source PNG hash differs from metadata')
        plan=derive_heading_plan(image,metadata);record['plan']=plan
        if plan is None:return metadata,record
        info=pins();record['engine']=info
        if info.get('model_sha256')!=ENGLISH_SHA256:raise ValueError('Heading engine model pin is invalid')
        transformed=evidence/(label+'-download-heading.png')
        prepared=render_heading(image,plan)
        try:prepared.save(transformed)
        finally:prepared.close()
        record['transformed_png']={'path':transformed.name,'sha256':digest(transformed)}
        argv=[info['engine'],str(transformed),'stdout','--tessdata-dir',info['tessdata_dir'],
              '-l','eng','--psm','7','tsv']
        record['argv']=argv;record['OCR_invocations']=1
        _write_json(intent_path,record)
        try:
            completed=runner(argv,capture_output=True,timeout=15,
                             env=dict(os.environ,OMP_THREAD_LIMIT='1',TESSDATA_PREFIX=info['tessdata_dir']))
        except subprocess.TimeoutExpired as error:
            record.update(_raw_result(evidence,label,error.stdout,error.stderr))
            raise
        record.update(_raw_result(evidence,label,completed.stdout,completed.stderr))
        record['exit']=completed.returncode
        if completed.returncode:raise RuntimeError('Prescribed heading OCR exited unsuccessfully')
        tokens=parse_heading_tsv(completed.stdout.decode(),plan);record['every_token']=tokens
        try:
            result=merge_heading_metadata(metadata,plan,tokens)
        except ValueError as error:
            record.update(status='REJECTED_NO_METADATA_CHANGE',reason=str(error));return metadata,record
        record.update(status='QUALIFIED_HEADING_ONLY',transform=result['download_heading_transform'])
        return result,record
    except BaseException as error:
        record.update(status='FAILED_NO_RETRY',error_class=type(error).__name__,error=str(error))
        raise
    finally:
        _write_json(record_path,record)
