"""Read-only resource snapshots for this owned disposable QA runtime."""
import json
import os
from pathlib import Path
import re
import shutil
import time


def selected_fields(raw, names):
    result={}
    for line in raw.splitlines():
        key,separator,value=line.partition(':')
        if separator and key in names:result[key]=value.strip()
    return result


def network_counters(raw):
    result={}
    for line in raw.splitlines():
        name,separator,value=line.partition(':')
        if not separator:continue
        fields=value.split()
        if len(fields)>=16 and all(item.isdigit() for item in fields):
            result[name.strip()]={'rx_bytes':int(fields[0]),'tx_bytes':int(fields[8])}
    return result


class ResourcePhases:
    def __init__(self, device, host, evidence):
        self.device,self.host,self.evidence=device,host,Path(evidence)
        self.records=[]

    def capture(self,label,*,pid=None):
        assert re.fullmatch('[a-z0-9_-]{1,70}',label)
        record={'phase':label,'captured_unix_ms':int(time.time()*1000),
                'scope':'Read-only owned-host/guest resource evidence; UI estimates are not transferred bytes'}
        def observe(key,fn):
            try:record[key]=fn()
            except Exception as error:record[key]={'error':type(error).__name__}
        def guest_read(path):return self.device.adb('exec-out','cat',path,raw=True,timeout=5).decode()
        observe('host_disk',lambda:dict(zip(('total','used','free'),shutil.disk_usage(self.host.root))))
        memory=('MemTotal','MemAvailable','MemFree','SwapTotal','SwapFree')
        observe('host_memory',lambda:selected_fields(Path('/proc/meminfo').read_text(),memory))
        observe('guest_memory',lambda:selected_fields(guest_read('/proc/meminfo'),memory))
        observe('guest_data_disk_df_pk',lambda:self.device.shell('df','-Pk','/data',timeout=10))
        observe('host_interface_counters',lambda:network_counters(Path('/proc/net/dev').read_text()))
        observe('guest_interface_counters',lambda:network_counters(guest_read('/proc/net/dev')))
        record['network_counter_limit']='Interface aggregates include all traffic; they are not exact CDN/game transfer bytes'
        def cache_usage():
            root=Path(self.host.config['cdn_cache_dir']).resolve()
            assert root.is_relative_to(self.host.receipt_path.parent)
            total=count=0
            if root.exists():
                for folder,dirs,files in os.walk(root,followlinks=False):
                    dirs[:]=[name for name in dirs if not (Path(folder)/name).is_symlink()]
                    for name in files:
                        path=Path(folder)/name
                        if path.is_symlink() or not path.is_file():continue
                        total+=path.stat().st_size;count+=1
                        if count>100000:raise ValueError('Owned cache inventory exceeded bound')
            return {'regular_files':count,'stored_bytes':total,
                    'limit':'Actual stored cache bytes, not HTTP transfer bytes or the UI uncompressed estimate'}
        observe('owned_cdn_cache_usage',cache_usage)
        status_names=('VmPeak','VmSize','VmRSS','VmSwap','Threads')
        if pid and str(pid).isdigit():
            observe('guest_game_process',lambda:selected_fields(guest_read('/proc/'+str(pid)+'/status'),status_names))
        if self.host.process:
            observe('host_go_process',lambda:selected_fields(Path('/proc',str(self.host.process.pid),'status').read_text(),status_names))
        relative=f'resources-{len(self.records):03d}-{label}.json'
        (self.evidence/relative).write_text(json.dumps(record,indent=2)+'\n')
        self.records.append(relative)
        return relative
