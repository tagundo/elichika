"""One bounded pure-source test set. This script cannot activate the candidate."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import unittest

from capture_memory_budget import memory_snapshot, require_headroom


def sha(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True);args=parser.parse_args()
    assert sys.dont_write_bytecode and sys.flags.optimize==0 and sys.pycache_prefix
    cache=Path(sys.pycache_prefix);assert cache.is_dir() and not list(cache.iterdir())
    before=memory_snapshot();require_headroom(before)
    # A hard80MiB address-space ceiling bounds this one host-only process.
    maximum=80*1024**2;resource.setrlimit(resource.RLIMIT_AS,(maximum,maximum))
    root=Path(__file__).parent
    def sources():
        return [{'path':str(path.relative_to(root)),'sha256':sha(path),'bytes':path.stat().st_size}
            for path in sorted(root.rglob('*')) if path.is_file()]
    original=sources()
    for path in root.glob('*.py'):compile(ast.parse(path.read_text()),str(path),'exec')
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root),pattern=pattern)
        for pattern in ('test_jp_complete_matcher.py','test_jp_light_adapter.py',
            'test_jp_native_home_flow.py','test_jp_chooser_scroll.py','test_jp_native_home_v2.py',
            'test_jp_native_home_v3_phase.py','test_jp_native_home_cleanup.py','test_jp_title_pulse.py',
            'test_jp_current_light.py'))
    started=time.monotonic();result=unittest.TextTestRunner(verbosity=2).run(suite)
    assert sources()==original and not list(cache.iterdir())
    after=memory_snapshot();require_headroom(after,allowance=0)
    receipt={'status':'PURE_SOURCE_TESTS_ONLY_NO_DEVICE_CI_API_REF_OR_FEATURE_QUALIFICATION',
        'successful':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skipped':len(result.skipped),'seconds':time.monotonic()-started,
        'source_hashes_before_after':original,'memory_before':before,'memory_after':after,
        'hard_address_space_limit_bytes':maximum,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'execution':{'argv':sys.orig_argv,'interpreter':str(Path(sys.executable).resolve()),
            'interpreter_sha256':sha(Path(sys.executable).resolve()),'dont_write_bytecode':True,
            'optimize':0,'fresh_prefix_empty_before_after':str(cache)},'exit':0 if result.wasSuccessful() else 1}
    with args.receipt.open('x') as output:json.dump(receipt,output,ensure_ascii=False,indent=2);output.write('\n')
    print(json.dumps({'receipt':str(args.receipt),'sha256':sha(args.receipt),
        'tests':result.testsRun,'successful':result.wasSuccessful()}))
    return receipt['exit']


if __name__=='__main__':raise SystemExit(main())
