"""Boot unmodified Redroid ARM64 userland on Google's actual 16KB kernel."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import time
import urllib.request
import zipfile

from android_16k_native import PackageRanges, elf_alignment


def run(*args, **kwargs):
    return subprocess.run(list(map(str,args)),check=True,**kwargs)


def prepare():
    work=Path('redroid-vm');work.mkdir(exist_ok=True)
    evidence=Path('evidence');evidence.mkdir(exist_ok=True)
    package=PackageRanges()
    package.url='https://dl.google.com/android/repository/sys-img/google_apis/arm64-v8a-ps16k-35_r05.zip'
    package.length=1778788352
    with zipfile.ZipFile(package) as archive:data=archive.read('arm64-v8a/kernel-ranchu')
    if data.startswith(b'\x1f\x8b'):data=gzip.decompress(data)
    assert hashlib.sha256(data).hexdigest()=='9be489e37c3966878c3c34fc3a910d34fa3c3d7c1ae4f7262907c69291121935'
    assert ((struct.unpack_from('<Q',data,24)[0]>>1)&3)==2
    (work/'kernel').write_bytes(data)
    image='redroid/redroid:16.0.0_64only-latest'
    run('docker','pull','--platform','linux/arm64',image)
    metadata=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]
    assert metadata['Architecture']=='arm64'
    (evidence/'redroid-image.json').write_text(json.dumps({'digests':metadata['RepoDigests'],'id':metadata['Id'],'architecture':metadata['Architecture'],'entrypoint':metadata['Config']['Entrypoint']},indent=2)+'\n')
    container=subprocess.check_output(['docker','create','--platform','linux/arm64',image]).decode().strip()
    try:run('docker','export','--output',work/'android.tar',container)
    finally:run('docker','rm',container)
    root=work/'android';root.mkdir(exist_ok=True)
    run('sudo','tar','--numeric-owner','-xf',work/'android.tar','-C',root)
    (work/'android.tar').unlink()
    layout={}
    for name in ['system/bin/init','system/bin/linker64','system/lib64/libc.so','system/lib64/libart.so']:
        path=root/name
        if path.exists():
            align=elf_alignment(path.read_bytes());assert min(align)>=16384,(name,align)
            layout[name]=align
    (evidence/'platform-elf-layout.json').write_text(json.dumps(layout,indent=2)+'\n')
    run('truncate','-s','8G',work/'android.ext4')
    run('sudo','mkfs.ext4','-q','-F','-b','4096','-d',root,work/'android.ext4')
    entry=metadata['Config']['Entrypoint'] or metadata['Config']['Cmd']
    assert entry and entry[0].startswith('/'),entry
    init=work/'initrd';init.mkdir(exist_ok=True)
    index=gzip.decompress(urllib.request.urlopen('https://ports.ubuntu.com/ubuntu-ports/dists/noble/main/binary-arm64/Packages.gz',timeout=90).read()).decode()
    block=next(x for x in index.split('\n\n') if x.startswith('Package: busybox-static\n'))
    fields=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
    binary=urllib.request.urlopen('https://ports.ubuntu.com/ubuntu-ports/'+fields['Filename'],timeout=90).read()
    assert hashlib.sha256(binary).hexdigest()==fields['SHA256']
    (work/'busybox.deb').write_bytes(binary)
    run('dpkg-deb','--extract',work/'busybox.deb',init)
    (init/'bin').mkdir(exist_ok=True)
    busybox=next(x for x in init.rglob('busybox') if x.is_file())
    if busybox!=init/'bin/busybox':shutil.copy2(busybox,init/'bin/busybox')
    for name in ['dev','proc','sys','newroot']:(init/name).mkdir(exist_ok=True)
    arguments=[*entry,'androidboot.hardware=redroid','androidboot.use_memfd=true',
      'androidboot.redroid_gpu_mode=guest','androidboot.redroid_width=480',
      'androidboot.redroid_height=800','androidboot.redroid_dpi=160',
      'androidboot.redroid_fps=10','ro.secure=0']
    environment='\n'.join('export '+shlex.quote(value) for value in (metadata['Config'].get('Env') or []) if value.split('=',1)[0] not in ['HOME','PATH'])
    script='''#!/bin/busybox sh
set -ex
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
/bin/busybox mount -t tmpfs tmpfs /dev
for pair in 'null 1 3' 'zero 1 5' 'full 1 7' 'random 1 8' 'urandom 1 9' 'console 5 1' 'tty 5 0'; do
 set -- $pair
 /bin/busybox mknod -m 666 /dev/$1 c $2 $3
done
/bin/busybox mkdir -p /dev/pts /dev/shm
/bin/busybox mount -t devpts devpts /dev/pts
for device in /sys/class/block/*/dev; do
 name=${device%/dev}; name=${name##*/}; id=$(/bin/busybox cat "$device")
 /bin/busybox mknod -m 660 /dev/$name b ${id%:*} ${id#*:} || true
done
for device in /sys/class/misc/*/dev; do
 name=${device%/dev}; name=${name##*/}; id=$(/bin/busybox cat "$device")
 /bin/busybox mknod -m 666 /dev/$name c ${id%:*} ${id#*:} || true
done
/bin/busybox ip link set lo up
/bin/busybox ip link set eth0 up
/bin/busybox ip address add 10.0.2.15/24 dev eth0
/bin/busybox ip route add default via 10.0.2.2
/bin/busybox mount -t ext4 /dev/vda /newroot
for name in dev proc sys; do
 /bin/busybox mkdir -p /newroot/$name
 /bin/busybox mount --move /$name /newroot/$name
done
export PATH=/system/bin:/system/xbin:/vendor/bin
'''+environment+'\nexec /bin/busybox switch_root /newroot '+shlex.join(arguments)+'\n'
    (init/'init').write_text(script);(init/'init').chmod(0o755)
    with (work/'initrd.gz').open('wb') as output:
        run('bash','-o','pipefail','-c','find . -print0 | cpio --null -o --format=newc --owner=0:0 | gzip -1',cwd=init,stdout=output)
    report={'status':'PREPARED','android_userland':'Redroid 16 ARM64','image_digests':metadata['RepoDigests'],
      'kernel_sha256':hashlib.sha256(data).hexdigest(),'kernel_page_size':16384,
      'limits':['Software emulation, rooted Android container userland, SELinux disabled; not a stock physical phone'],
      'kernel_modified':False,'apk_modified':False}
    (evidence/'redroid16k-boot.json').write_text(json.dumps(report,indent=2)+'\n')


def start():
    args=['qemu-system-aarch64','-machine','virt','-accel','tcg','-cpu','max','-m','4096','-smp','2',
      '-display','none','-serial','file:evidence/redroid-vm.log','-no-reboot',
      '-kernel','redroid-vm/kernel','-initrd','redroid-vm/initrd.gz',
      '-append','console=ttyAMA0 earlycon=pl011,0x9000000 rdinit=/init selinux=0 androidboot.hardware=redroid',
      '-drive','if=none,id=android,file=redroid-vm/android.ext4,format=raw',
      '-device','virtio-blk-device,drive=android','-netdev','user,id=network,hostfwd=tcp:127.0.0.1:15555-:5555',
      '-device','virtio-net-device,netdev=network']
    p=subprocess.Popen(args,start_new_session=True,stdout=Path('evidence/qemu-host.log').open('wb'),stderr=subprocess.STDOUT)
    Path('evidence/emulator.pid').write_text(str(p.pid))


def wait():
    report_path=Path('evidence/redroid16k-boot.json');report=json.loads(report_path.read_text())
    for _ in range(180):
        try:os.kill(int(Path('evidence/emulator.pid').read_text()),0)
        except ProcessLookupError:
            report.update({'status':'FAIL','error':'Virtual machine exited before Android boot'})
            report_path.write_text(json.dumps(report,indent=2)+'\n');raise RuntimeError(report)
        subprocess.run(['adb','connect','127.0.0.1:15555'],capture_output=True,timeout=10)
        result=subprocess.run(['adb','-s','127.0.0.1:15555','shell','getprop','sys.boot_completed'],capture_output=True,text=True,timeout=10)
        if result.returncode==0 and result.stdout.strip()=='1':
            page=subprocess.check_output(['adb','-s','127.0.0.1:15555','shell','getconf','PAGE_SIZE'],text=True).strip()
            assert page=='16384',page
            report.update({'status':'PASS','actual_page_size':int(page)})
            report_path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return
        time.sleep(5)
    report.update({'status':'FAIL','error':'Android framework did not complete boot'})
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    raise RuntimeError(report)


if __name__=='__main__':
    import sys
    {'prepare':prepare,'start':start,'wait':wait}[sys.argv[1]]()
