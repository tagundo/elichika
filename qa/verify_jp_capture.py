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
from capture_memory_budget import MemoryBudgetUnavailable, memory_snapshot, require_headroom


def sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def memory_hold(path,diagnostic,error,phase,tests=0):
    print(str(error),file=sys.stderr)
    record={'status':'RESOURCE_HOLD_NO_RUNTIME_OR_FEATURE_QUALIFICATION','phase':phase,
        'error':str(error)[:1024],'tests':tests,'successful':False,'memory_diagnostic':diagnostic,
        'execution':{'argv':sys.orig_argv,'interpreter':str(Path(sys.executable).resolve()),
            'interpreter_sha256':sha(Path(sys.executable).resolve()),'dont_write_bytecode':sys.dont_write_bytecode,
            'optimize':sys.flags.optimize,'fresh_prefix':sys.pycache_prefix},'exit':1}
    raw=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode()
    if len(raw)>65536:
        rows=diagnostic.get('cgroup2_mountinfo',[])
        rows=rows if isinstance(rows,list) else [rows]
        record['execution']['argv']=[str(value)[:512] for value in sys.orig_argv[:16]]
        record['execution']['argv_truncated']=True
        record['memory_diagnostic']={'truncated':True,'reason':'64KiB diagnostic cap',
            'pid':diagnostic.get('pid'),'current_mount':diagnostic.get('current_mount'),
            'proc_self_cgroup':str(diagnostic.get('proc_self_cgroup',''))[:512],
            'cgroup2_mountinfo':rows[-1:]}
        raw=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode()
    try:
        if len(raw)>65536:raise OSError('Refusal diagnostic exceeds64KiB')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as output:output.write(raw)
    except OSError as diagnostic_error:print('Original RESOURCE_HOLD retained; diagnostic write error: '+str(diagnostic_error),file=sys.stderr)
    return 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    assert sys.dont_write_bytecode and sys.flags.optimize==0 and sys.pycache_prefix
    cache=Path(sys.pycache_prefix);assert cache.is_dir() and not list(cache.iterdir())
    before_diagnostic={}
    try:
        before_memory=memory_snapshot(diagnostic=before_diagnostic);require_headroom(before_memory)
    except MemoryBudgetUnavailable as error:return memory_hold(args.receipt,before_diagnostic,error,'before-pure-tests')
    root=Path(__file__).parent
    sources=[{'path':str(path),'sha256':sha(path)} for path in sorted(root.rglob('*')) if path.is_file()]
    for path in root.glob('*.py'):compile(ast.parse(path.read_text()),str(path),'exec')
    suite=unittest.TestSuite([
        unittest.defaultTestLoader.discover(str(root),pattern='test_jp_capture.py'),
        unittest.defaultTestLoader.discover(str(root),pattern='test_capture_memory_budget.py')])
    began=time.monotonic();result=unittest.TextTestRunner(verbosity=2).run(suite)
    assert sources==[{'path':str(path),'sha256':sha(path)} for path in sorted(root.rglob('*')) if path.is_file()]
    assert not list(cache.iterdir())
    after_diagnostic={}
    try:
        after_memory=memory_snapshot(diagnostic=after_diagnostic);require_headroom(after_memory,allowance=0)
    except MemoryBudgetUnavailable as error:return memory_hold(args.receipt,after_diagnostic,error,'after-pure-tests',result.testsRun)
    record={'status':'PURE_TESTS_ONLY_NO_RUNTIME_OR_FEATURE_QUALIFICATION',
        'tests':result.testsRun,'successful':result.wasSuccessful(),
        'failures':len(result.failures),'errors':len(result.errors),'seconds':time.monotonic()-began,
        'source_hashes_before_after':sources,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'memory_before':before_memory,'memory_after':after_memory,
        'memory_diagnostic_before':before_diagnostic,'memory_diagnostic_after':after_diagnostic,
        'execution':{'argv':sys.orig_argv,'interpreter':str(Path(sys.executable).resolve()),
            'interpreter_sha256':sha(Path(sys.executable).resolve()),'version':sys.version,
            'dont_write_bytecode':True,'optimize':0,'fresh_prefix_empty_before_after':str(cache)},
        'exit':0 if result.wasSuccessful() else 1}
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    with args.receipt.open('x') as output:json.dump(record,output,ensure_ascii=False,indent=2);output.write('\n')
    print(json.dumps({'receipt':str(args.receipt),'sha256':sha(args.receipt),'tests':result.testsRun,'successful':result.wasSuccessful()}))
    return record['exit']


if __name__=='__main__':raise SystemExit(main())
