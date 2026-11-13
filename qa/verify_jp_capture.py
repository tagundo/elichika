"""Run only bounded pure JP capture tests and record actual Python execution."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import unittest


def sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    assert sys.dont_write_bytecode and sys.flags.optimize==0 and sys.pycache_prefix
    cache=Path(sys.pycache_prefix);assert cache.is_dir() and not list(cache.iterdir())
    cgroup=Path('/sys/fs/cgroup');limit=(cgroup/'memory.max').read_text().strip()
    current=int((cgroup/'memory.current').read_text())
    if limit!='max':assert int(limit)-current>=272*1024**2,'192MiB reserve plus80MiB test allowance required'
    root=Path(__file__).parent
    sources=[{'path':str(path),'sha256':sha(path)} for path in sorted(root.rglob('*')) if path.is_file()]
    for path in root.glob('*.py'):compile(ast.parse(path.read_text()),str(path),'exec')
    suite=unittest.defaultTestLoader.discover(str(root),pattern='test_jp_capture.py')
    began=time.monotonic();result=unittest.TextTestRunner(verbosity=2).run(suite)
    assert sources==[{'path':str(path),'sha256':sha(path)} for path in sorted(root.rglob('*')) if path.is_file()]
    assert not list(cache.iterdir())
    after=int((cgroup/'memory.current').read_text())
    if limit!='max':assert int(limit)-after>=192*1024**2
    record={'status':'PURE_TESTS_ONLY_NO_RUNTIME_OR_FEATURE_QUALIFICATION',
        'tests':result.testsRun,'successful':result.wasSuccessful(),
        'failures':len(result.failures),'errors':len(result.errors),'seconds':time.monotonic()-began,
        'source_hashes_before_after':sources,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'memory_limit':limit,'memory_current_before':current,'memory_current_after':after,
        'execution':{'argv':sys.orig_argv,'interpreter':str(Path(sys.executable).resolve()),
            'interpreter_sha256':sha(Path(sys.executable).resolve()),'version':sys.version,
            'dont_write_bytecode':True,'optimize':0,'fresh_prefix_empty_before_after':str(cache)},
        'exit':0 if result.wasSuccessful() else 1}
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    with args.receipt.open('x') as output:json.dump(record,output,ensure_ascii=False,indent=2);output.write('\n')
    print(json.dumps({'receipt':str(args.receipt),'sha256':sha(args.receipt),'tests':result.testsRun,'successful':result.wasSuccessful()}))
    return record['exit']


if __name__=='__main__':raise SystemExit(main())
