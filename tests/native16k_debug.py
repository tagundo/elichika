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
print('PYTHON_DIAGNOSTIC_REPORT='+json.dumps(python_checks()),flush=True)
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
    # Separate naturally distinct components, each below the artifact tool limit.
    for label, exclude in (('debug-native-root', 'python'), ('debug-python-root', None)):
        output=args.exports/(label+'.tar.gz')
        with tarfile.open(output,'w:gz',compresslevel=6) as tar:
            if exclude:
                for path in sorted(root.iterdir()):
                    if path.name != exclude: tar.add(path, arcname=path.name)
            else: tar.add(root/'python',arcname='python')
        assert output.stat().st_size < 31*1024*1024, (label,output.stat().st_size)
    (args.exports/'kernel-16384.gz').write_bytes(gzip.compress(kernel.read_bytes(),compresslevel=6))
    (args.exports/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    subprocess.run(['bash','-c','find . -print0 | cpio --null -o --format=newc --owner=0:0 | gzip -1'],
                   cwd=root,stdout=(args.work/'debug-initramfs.gz').open('wb'),check=True)
    subprocess.run(['qemu-system-aarch64','-machine','virt','-accel','tcg','-cpu','max','-m','1024','-smp','2',
                    '-nographic','-no-reboot','-kernel',str(kernel),'-initrd',str(args.work/'debug-initramfs.gz'),
                    '-append','console=ttyAMA0 rdinit=/init nokaslr selinux=0'],
                    stdout=(args.evidence/'python-diagnostic-16384.txt').open('wb'),stderr=subprocess.STDOUT,
                    check=True,timeout=300)

if __name__ == '__main__': main()
