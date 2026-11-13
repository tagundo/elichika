#!/usr/bin/env python3
"""Prepare two exact official OCR models in a disposable user-owned directory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

COMMIT='87416418657359cb625c412a48b6e1d6d41c29bd'
FILES=(('chi_tra.traineddata',2366642,'529c5b5797d64b126065cd55f2bb4c7fd7b15790798091b1ff259941a829330b'),
       ('kor.traineddata',1677415,'6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();args.destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    receipts=[]
    for name,size,expected in FILES:
        url=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/{name}'
        with urllib.request.urlopen(url,timeout=40) as response:
            assert response.status==200
            data=response.read(size+1)
        assert len(data)==size and hashlib.sha256(data).hexdigest()==expected,'Official OCR model differs from exact pin'
        with (args.destination/name).open('xb') as output:output.write(data)
        receipts.append({'name':name,'bytes':size,'sha256':expected})
    system=Path('/usr/share/tesseract-ocr/5/tessdata')
    for name in ('eng.traineddata','configs'):
        source=(system/name).resolve(strict=True)
        (args.destination/name).symlink_to(source,target_is_directory=source.is_dir())
    args.evidence.mkdir(parents=True,exist_ok=True)
    receipt={'repository':'tesseract-ocr/tessdata_fast','commit':COMMIT,'files':receipts,
       'system_english_model_sha256':hashlib.file_digest((system/'eng.traineddata').open('rb'),'sha256').hexdigest(),
       'tesseract_version':subprocess.check_output(['tesseract','--version'],text=True)}
    (args.evidence/'ocr-language-models.json').write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':main()
