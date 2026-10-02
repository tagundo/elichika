"""Boot the official 16KB Android ARM64 image using Linux SDK software emulation."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time


def diagnostic_tcg_cpu(binary, evidence):
    """Expose the 16KB table walk which the SDK's old A57 CPU ID omits."""
    original = binary.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert digest == 'e85ab5c7ed7608d78cd3a2c1c9a6f6fbb0939d75d6449ef64eac3483009312d2'
    instruction = bytes.fromhex('48c780e03e02002411000048b900d016352300200a')
    offsets = [0xa04a62, 0xa04d19]
    assert original.count(instruction) == len(offsets)
    modified = bytearray(original)
    for offset in offsets:
        assert original[offset:offset+len(instruction)] == instruction
        modified[offset+9] = 0x10  # ID_AA64MMFR0_EL1.TGran16 = 1
    output = binary.with_name(binary.name+'-16k')
    shutil.copy2(binary, output)
    output.write_bytes(modified)
    report = {'type': 'diagnostic software CPU, not stock SDK emulator',
              'original_sha256': digest, 'modified_sha256': hashlib.sha256(modified).hexdigest(),
              'old_cpu_mmfr0': '0x00001124', 'new_cpu_mmfr0': '0x00101124',
              'instruction_offsets': [hex(x) for x in offsets],
              'kernel_and_apk_modified': False}
    (evidence/'tcg-cpu-diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
    return output


def main():
    evidence = Path('evidence'); evidence.mkdir(exist_ok=True)
    sdk = Path(os.environ['ANDROID_HOME'])
    adb = sdk / 'platform-tools/adb'
    base = ['-avd', 'elichika16k', '-port', '5554', '-accel', 'off',
            '-no-window', '-no-audio', '-no-boot-anim', '-no-snapshot',
            '-gpu', 'swiftshader', '-feature', '-Vulkan', '-memory', '4096',
            '-cores', '4', '-skin', '480x800', '-skip-adb-auth', '-verbose',
            '-show-kernel', '-qemu', '-machine', 'type=virt',
            '-accel', 'tcg', '-cpu', 'max']
    report = {'status': 'PREPARING', 'target': 'official Android 35 ARM64 16KB',
              'hardware_acceleration': False, 'attempts': []}
    report_path = evidence / 'android16k-boot.json'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    subprocess.run([adb, 'start-server'], check=True, timeout=30)
    backend = sdk / 'emulator/qemu/linux-x86_64/qemu-system-aarch64-headless'
    binaries = [sdk / 'emulator/emulator', backend, backend.with_name(backend.name+'-16k')]
    for index, binary in enumerate(binaries):
        if index == 2:
            binary = diagnostic_tcg_cpu(backend, evidence)
        log = evidence / f'emulator-attempt-{index}.log'
        environment = os.environ.copy()
        environment['ANDROID_EMULATOR_LAUNCHER_DIR'] = str(sdk/'emulator')
        environment['LD_LIBRARY_PATH'] = ':'.join([str(sdk/'emulator/lib64'),
            str(sdk/'emulator/lib64/gles_swiftshader'), environment.get('LD_LIBRARY_PATH','')])
        process = subprocess.Popen([str(binary), *base], stdout=log.open('wb'),
                                   stderr=subprocess.STDOUT, env=environment,
                                   start_new_session=True)
        (evidence/'emulator.pid').write_text(str(process.pid))
        started = time.monotonic()
        attempt = {'binary': str(binary), 'pid': process.pid, 'command': [str(binary), *base]}
        report['attempts'].append(attempt)
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        deadline = started + (120 if index == 1 else 1500)
        heartbeat = started
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    attempt.update({'exit_code': process.returncode, 'elapsed_seconds': round(time.monotonic()-started,1)})
                    report_path.write_text(json.dumps(report,indent=2)+'\n')
                    print(log.read_text(errors='replace')[-7000:], flush=True)
                    break
                if time.monotonic()-heartbeat >= 60:
                    heartbeat = time.monotonic()
                    print('Android boot elapsed seconds:', round(heartbeat-started), flush=True)
                    print(log.read_text(errors='replace')[-2500:], flush=True)
                if 'Kernel panic - not syncing' in log.read_text(errors='replace'):
                    attempt['error'] = 'Android kernel panic; see emulator log'
                    process.terminate()
                    process.wait(timeout=30)
                    break
                try:
                    result = subprocess.run([adb,'-s','emulator-5554','shell','getprop','sys.boot_completed'],
                                            capture_output=True,text=True,timeout=8)
                    if result.returncode == 0 and result.stdout.strip() == '1':
                        page = subprocess.check_output([adb,'-s','emulator-5554','shell','getconf','PAGE_SIZE'],
                                                       text=True,timeout=20).strip()
                        assert page == '16384', 'Booted Android does not have actual 16KB pages: '+page
                        report.update({'status':'PASS','actual_page_size':int(page),
                                       'boot_seconds':round(time.monotonic()-started,1),'selected_binary':str(binary),
                                       'diagnostic_cpu_used':index==2})
                        report_path.write_text(json.dumps(report,indent=2)+'\n')
                        print('FULL_ANDROID_BOOT_PASS_PAGE_SIZE=16384',flush=True)
                        return
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(4)
            else:
                attempt['error']='Boot deadline exceeded'
                process.terminate()
                try: process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
            attempt['elapsed_seconds'] = round(time.monotonic()-started,1)
            report_path.write_text(json.dumps(report,indent=2)+'\n')
            if index == 0:
                text = log.read_text(errors='replace')
                if not any(s in text for s in ['CPU Architecture', 'not supported', 'PANIC']):
                    raise RuntimeError('Android launcher failed for an unrelated reason; see emulator log')
                print('Retrying the SDK ARM64 backend after launcher architecture rejection',flush=True)
        except Exception as error:
            report.update({'status':'FAIL','error':str(error)})
            report_path.write_text(json.dumps(report,indent=2)+'\n')
            raise
    report.update({'status':'FAIL','error':'No full Android emulator booted'})
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    raise RuntimeError(report['error'])


if __name__ == '__main__': main()
