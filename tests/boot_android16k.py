"""Boot the official 16KB Android ARM64 image using Linux SDK software emulation."""
import json
import os
from pathlib import Path
import subprocess
import time


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
    binaries = [sdk / 'emulator/emulator',
                sdk / 'emulator/qemu/linux-x86_64/qemu-system-aarch64-headless']
    for index, binary in enumerate(binaries):
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
        deadline = started + 1500
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    attempt.update({'exit_code': process.returncode, 'elapsed_seconds': round(time.monotonic()-started,1)})
                    report_path.write_text(json.dumps(report,indent=2)+'\n')
                    print(log.read_text(errors='replace')[-7000:], flush=True)
                    break
                try:
                    result = subprocess.run([adb,'-s','emulator-5554','shell','getprop','sys.boot_completed'],
                                            capture_output=True,text=True,timeout=8)
                    if result.returncode == 0 and result.stdout.strip() == '1':
                        page = subprocess.check_output([adb,'-s','emulator-5554','shell','getconf','PAGE_SIZE'],
                                                       text=True,timeout=20).strip()
                        assert page == '16384', 'Booted Android does not have actual 16KB pages: '+page
                        report.update({'status':'PASS','actual_page_size':int(page),
                                       'boot_seconds':round(time.monotonic()-started,1),'selected_binary':str(binary)})
                        report_path.write_text(json.dumps(report,indent=2)+'\n')
                        print('FULL_ANDROID_BOOT_PASS_PAGE_SIZE=16384',flush=True)
                        return
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(4)
            else:
                attempt['error']='Boot deadline exceeded'
                process.terminate()
                process.wait(timeout=30)
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
