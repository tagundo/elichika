"""Prepare a small, repeatable diagnostic from an already audited signed APK."""
import argparse
import ast
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import types

import android_16k_native as vm

C_PROBE = r'''
#include <stdio.h>
#include <signal.h>
#include <ucontext.h>
#include <unistd.h>
#include <fcntl.h>
extern void Py_Initialize(void);
extern int PyRun_SimpleString(const char *);
extern int Py_FinalizeEx(void);
static struct sigaction previous;
static void crash(int signal, siginfo_t *info, void *context) {
    ucontext_t *state = context;
    char line[256];
    int size = snprintf(line, sizeof(line), "NATIVE_CRASH signal=%d pc=0x%lx sp=0x%lx addr=%p\n",
                        signal, (unsigned long)state->uc_mcontext.pc,
                        (unsigned long)state->uc_mcontext.sp, info->si_addr);
    write(2, line, size);
    int fd = open("/proc/self/maps", O_RDONLY);
    if (fd >= 0) {
        char buffer[4096];
        int count;
        while ((count = read(fd, buffer, sizeof(buffer))) > 0) write(2, buffer, count);
        close(fd);
    }
    if (previous.sa_flags & SA_SIGINFO) previous.sa_sigaction(signal, info, context);
    else previous.sa_handler(signal);
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    Py_Initialize();
    if (PyRun_SimpleString("import sys, faulthandler\n"
                          "sys.stdout=open(1,'w',buffering=1,closefd=False)\n"
                          "sys.stderr=open(2,'w',buffering=1,closefd=False)\n"
                          "faulthandler.enable()\n") != 0) return 2;
    struct sigaction action = {0};
    action.sa_sigaction = crash;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&action.sa_mask);
    sigaction(SIGSEGV, &action, &previous);
    int status = PyRun_SimpleString("__file__='/python/native_probe.py'\n"
                          "exec(compile(open(__file__,encoding='utf-8').read(),__file__,'exec'))\n");
    if (Py_FinalizeEx() < 0) return 120;
    return status == 0 ? 0 : 1;
}
'''


def main():
    parser = argparse.ArgumentParser()
    for name in ('candidate', 'image', 'ndk', 'work', 'evidence', 'exports'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.exports.mkdir(parents=True, exist_ok=True)
    vm.PYTHON_PROBE = C_PROBE
    report = {}
    kernel, _ = vm.prepare(args, report)
    root = args.work / 'root'
    # Original Go/data operations are covered by the full compatibility gate.
    # Keep the original Python/ASTC modules for fast repeated fault localization.
    shutil.rmtree(root / 'runtime')
    (root / 'runtime').mkdir()
    (root / 'probe/libelichika.so').unlink()
    script = root / 'python/native_probe.py'
    tree = ast.parse(script.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'python_checks':
            body = []
            for index, statement in enumerate(node.body):
                label = f'{index:02d} '+ast.unparse(statement).splitlines()[0]
                body.extend(ast.parse(f'print({("NATIVE_STEP="+label)!r}, flush=True)').body)
                body.append(statement)
            node.body = body
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            node.body = ast.parse('''os.chdir('/runtime')
print('FUNCTIONAL_PAGE_SIZE='+str(os.sysconf('SC_PAGE_SIZE')),flush=True)
result=python_checks()
import numpy as np
numeric=[]
for dtype in (np.float32,np.float64,np.complex64,np.complex128):
    matrix=np.array([[3,1,0.25],[0.25,4,-0.5],[1,0.5,5]],dtype=dtype)
    if np.issubdtype(dtype,np.complexfloating):
        matrix += np.array([[0.2j,-0.5j,0.1j],[0.4j,0.2j,-0.1j],[0.3j,0.1j,0.4j]],dtype=dtype)
    tolerance=3e-4 if matrix.dtype.itemsize/(2 if np.iscomplexobj(matrix) else 1)==4 else 1e-10
    def close(actual,expected):
        assert np.allclose(actual,expected,rtol=tolerance,atol=tolerance), (dtype,actual,expected)
    rhs=np.array([[2,1],[7,2],[3,-1]],dtype=dtype)
    close(matrix @ np.linalg.inv(matrix),np.eye(3))
    close(matrix @ np.linalg.solve(matrix,rhs),rhs)
    u,s,vh=np.linalg.svd(matrix)
    close((u*s) @ vh,matrix)
    q,r=np.linalg.qr(matrix)
    close(q @ r,matrix)
    close(q.conj().T @ q,np.eye(3))
    values,vectors=np.linalg.eig(matrix)
    close(matrix @ vectors,vectors*values)
    close(np.linalg.det(matrix),np.prod(values))
    hermitian=matrix.conj().T @ matrix
    values,vectors=np.linalg.eigh(hermitian)
    close(hermitian @ vectors,vectors*values)
    factor=np.linalg.cholesky(hermitian)
    close(factor @ factor.conj().T,hermitian)
    solution,residual,rank,singular=np.linalg.lstsq(matrix,rhs,rcond=None)
    assert rank==3
    close(matrix @ solution,rhs)
    rng=np.random.default_rng(16384)
    left=rng.uniform(-1,1,(32,48)).astype(dtype)
    right=rng.uniform(-1,1,(48,24)).astype(dtype)
    if np.iscomplexobj(matrix):
        left += 1j*rng.uniform(-1,1,left.shape).astype(dtype)
        right += 1j*rng.uniform(-1,1,right.shape).astype(dtype)
    close(np.dot(left,right),np.einsum('ik,kj->ij',left,right,optimize=False))
    close(np.fft.ifft(np.fft.fft(left,axis=0),axis=0),left)
    numeric.append({'dtype':np.dtype(dtype).name,'operations':['inverse','solve','svd','qr','eig','det','eigh','cholesky','lstsq','blas_matrix_multiply','fft_random_roundtrip'],'status':'PASS'})
    print('NUMPY_DTYPE_OK='+np.dtype(dtype).name,flush=True)
result['additional_numpy_abi_checks']=numeric
print('PYTHON_DIAGNOSTIC_REPORT='+json.dumps(result),flush=True)
''').body
    ast.fix_missing_locations(tree)
    script.write_text(ast.unparse(tree)+'\n')
    initial = (root/'init').read_text().split('echo BEGIN_ANDROID_16K_PROBE')[0]
    (root/'init').write_text(initial+'''echo BEGIN_PYTHON_DIAGNOSTIC
/probe/elfcheck /probe/control-16384.so /probe/control-4096.so
/probe/pythoncheck
echo PYTHON_DIAGNOSTIC_EXIT=$?
echo END_PYTHON_DIAGNOSTIC
/bin/busybox poweroff -f
''')
    (args.exports/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    subprocess.run(['bash','-c','find . -print0 | cpio --null -o --format=newc --owner=0:0 | gzip -1'],
                   cwd=root,stdout=(args.work/'debug-initramfs.gz').open('wb'),check=True)
    control_kernel=vm.four_k_kernel(args,report)
    results={}
    for page,image in ((4096,control_kernel),(16384,kernel)):
        output=args.evidence/f'python-diagnostic-{page}.txt'
        subprocess.run(['qemu-system-aarch64','-machine','virt','-accel','tcg','-cpu','max','-m','1024','-smp','2',
                        '-nographic','-no-reboot','-kernel',str(image),'-initrd',str(args.work/'debug-initramfs.gz'),
                        '-append','console=ttyAMA0 rdinit=/init nokaslr selinux=0'],
                       stdout=output.open('wb'),stderr=subprocess.STDOUT,check=True,timeout=300)
        console=output.read_text(errors='replace')
        assert f'FUNCTIONAL_PAGE_SIZE={page}' in console
        assert 'PYTHON_DIAGNOSTIC_EXIT=0' in console and 'NATIVE_CRASH' not in console, console[-6000:]
        results[str(page)]=json.loads(next(l.split('=',1)[1] for l in console.splitlines() if l.startswith('PYTHON_DIAGNOSTIC_REPORT=')))
        assert len(results[str(page)]['additional_numpy_abi_checks'])==4
    report.update({'status':'PASS','signed_candidate_sha256':args.candidate_sha256,'source_commit':'5c29f2302b4f30231dc523802468725c647460ff','additional_numpy_abi_checks':results})
    (args.evidence/'additional-numpy-abi.json').write_text(json.dumps(report,indent=2)+'\n')
    print('All four NumPy data types and native Python operations PASS on both 4KB and 16KB kernels')

if __name__ == '__main__': main()
