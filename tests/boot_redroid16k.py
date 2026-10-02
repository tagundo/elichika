"""Boot unmodified Redroid ARM64 userland on Google's actual 16KB kernel."""
import gzip
import ctypes
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
import zlib

from android_16k_native import PackageRanges, elf_alignment


def run(*args, **kwargs):
    return subprocess.run(list(map(str,args)),check=True,**kwargs)


def modules_from_ramdisk(data, destination):
    if data.startswith(b'\x1f\x8b'):
        data=gzip.decompress(data)
    elif data.startswith(bytes.fromhex('02214c18')):
        library=ctypes.CDLL('liblz4.so.1')
        library.LZ4_decompress_safe.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int]
        library.LZ4_decompress_safe.restype=ctypes.c_int
        position=4;parts=[]
        while position+4<=len(data):
            count=struct.unpack_from('<I',data,position)[0];position+=4
            if count in (0,0x184c2102):continue
            assert count<=len(data)-position
            source=ctypes.create_string_buffer(data[position:position+count])
            output=ctypes.create_string_buffer(8*1024*1024)
            size=library.LZ4_decompress_safe(source,output,count,len(output));assert size>0,size
            parts.append(output.raw[:size]);position+=count
        data=b''.join(parts)
    position=0;extracted=[]
    while position+110<=len(data):
        if data[position:position+6] not in (b'070701',b'070702'):
            position=data.find(b'070701',position)
            if position<0:break
        fields=[int(data[position+6+i*8:position+14+i*8],16) for i in range(13)]
        length,size=fields[11],fields[6]
        name=data[position+110:position+110+length-1].decode()
        start=(position+110+length+3)&~3
        if name.startswith('lib/modules/') and fields[1]&0o170000==0o100000:
            assert '..' not in Path(name).parts
            path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data[start:start+size]);extracted.append(name)
        position=(start+size+3)&~3
    assert any(x.endswith('virtio_blk.ko') for x in extracted),extracted
    return extracted


def vendor_filesystem(image, destination):
    with image.open('rb') as source:
        source.seek(512);header=bytearray(source.read(512));assert header[:8]==b'EFI PART'
        length,checksum=struct.unpack_from('<II',header,12)
        struct.pack_into('<I',header,16,0)
        assert zlib.crc32(header[:length])==checksum
        lba,count,size,checksum=struct.unpack_from('<QIII',header,72)
        source.seek(lba*512);entries=source.read(count*size);assert zlib.crc32(entries)==checksum
        partition=next(entries[i*size:(i+1)*size] for i in range(count)
          if entries[i*size+56:i*size+128].decode('utf-16-le').split('\0')[0]=='vendor')
        first,last=struct.unpack_from('<QQ',partition,32)
        source.seek(first*512);remaining=(last-first+1)*512
        with destination.open('wb') as output:
            while remaining:
                data=source.read(min(remaining,8*1024*1024));assert data
                output.write(data);remaining-=len(data)
    return destination


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
    with zipfile.ZipFile(package) as archive:
        modules=modules_from_ramdisk(archive.read('arm64-v8a/ramdisk.img'),init)
        with archive.open('arm64-v8a/vendor.img') as source,(work/'vendor.img').open('wb') as output:
            while chunk:=source.read(8*1024*1024):output.write(chunk)
    (init/'lib/modules').mkdir(parents=True,exist_ok=True)
    volume=vendor_filesystem(work/'vendor.img',work/'vendor-partition.img')
    run('debugfs','-R','rdump /lib/modules '+str(init/'lib'),volume,stdout=subprocess.DEVNULL)
    assert (init/'lib/modules/virtio_net.ko').is_file()
    (evidence/'official-kernel-modules.json').write_text(json.dumps({'ramdisk':modules,'vendor_network_module':True},indent=2)+'\n')
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
for module in virtio_mmio virtio_blk failover net_failover virtio_net; do
 if test -f /lib/modules/$module.ko; then /bin/busybox insmod /lib/modules/$module.ko; fi
done
for attempt in 1 2 3 4 5 6 7 8 9 10; do
 if test -f /sys/class/block/vda/dev; then break; fi
 /bin/busybox sleep 1
done
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
