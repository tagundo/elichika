#!/usr/bin/env python3
"""Two prescribed actual-engine reads before UI; never runs native input."""
import argparse
import json
from pathlib import Path
import platform

from PIL import Image
from native_download_flow import analyze
from native_download_heading_ocr import digest,engine_provenance,read_heading


def verify(fixtures,evidence,*,expected_version='5.3.4',expected_machine='aarch64',
           reader=read_heading,pins=engine_provenance,machine=platform.machine):
    fixtures,evidence=Path(fixtures),Path(evidence)
    evidence.mkdir(parents=True,exist_ok=False)
    receipt={'scope':'PRESCRIBED_TWO_IMAGE_CI_ENGINE_CHECK_ONLY_NO_NATIVE_INPUT',
             'status':'FAIL','input_performed':False,'cases':[]}
    try:
        info=pins();receipt['engine']=info;receipt['machine']=machine()
        if receipt['machine']!=expected_machine:raise ValueError('CI OCR architecture differs from the prescribed ARM runner')
        if info['version'].splitlines()[0]!='tesseract '+expected_version:
            raise ValueError('CI OCR engine version differs from the prescribed 5.3.4 check')
        provenance=json.loads((fixtures/'provenance.json').read_text())
        for member in provenance['files']:
            path=fixtures/member['path']
            if Path(member['path']).name!=member['path'] or path.stat().st_size!=member['bytes'] or digest(path)!=member['sha256']:
                raise ValueError('Prescribed OCR fixture differs from its original pin')
        receipt['fixture_provenance_sha256']=digest(fixtures/'provenance.json')
        # Retained host TSVs are parser fixtures, never expected CI output.
        host=json.loads((fixtures/'host-probe-receipt.json').read_text())
        expected={case['label']:case['crop_box'] for case in host['cases']}
        for label in ('before015','after023'):
            metadata=json.loads((fixtures/(label+'.json')).read_text())
            with Image.open(fixtures/(label+'.png')) as image:
                supplemented,record=reader(image,metadata,evidence=evidence,label=label,
                    source_png=fixtures/(label+'.png'),fixture_probe=True,pins=lambda:info)
                if (record.get('status')!='QUALIFIED_HEADING_ONLY' or record.get('OCR_invocations')!=1 or
                    record['plan']['crop_box']!=expected[label]):
                    raise ValueError('Actual CI engine did not qualify the single prescribed heading read')
                observed=analyze(image,supplemented,'settings')
                action=observed.get('action') or {}
                if action.get('kind')!=('scroll-download' if label=='before015' else 'choose-light'):
                    raise ValueError('Prescribed heading changed the existing radio/visibility qualification')
            receipt['cases'].append({'label':label,'record':record['record'],
                'crop_box':record['plan']['crop_box'],'state':observed['state'],
                'qualified_light_caption':observed['observations']['light_caption'],
                'input_performed':False})
        receipt['status']='PASS'
        return receipt
    except BaseException as error:
        receipt.update(error_class=type(error).__name__,error=str(error))
        raise
    finally:
        with (evidence/'two-image-check.json').open('x') as output:
            json.dump(receipt,output,indent=2);output.write('\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,default=Path(__file__).parent/'fixtures/actual-gl-download-heading-r9')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();verify(args.fixtures,args.evidence)


if __name__=='__main__':main()
