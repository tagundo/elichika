"""Stream only the owned Go fixture's exact Gin RPC evidence; never target state."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re

PATHS=frozenset((b'/login/startup',b'/login/login',b'/bootstrap/fetchBootstrap',b'/liveMv/start'))
LINE=re.compile(rb'^\[GIN\].*?\|\s*(\d{3})\s*\|.*?\|\s*POST\s+"([^"\r\n]+)"\s*$')


def rpc_line(raw):
    match=LINE.fullmatch(raw.rstrip(b'\r\n'))
    return match if match and match[2].split(b'?',1)[0] in PATHS else None


class IncrementalRpcEvidence:
    def __init__(self,path):
        self.path=Path(path);self.offset=0;self.identity=None;self.lines=[]

    def read(self):
        if not self.path.exists():return b''
        with self.path.open('rb') as source:
            stat=os.fstat(source.fileno())
            identity=(stat.st_dev,stat.st_ino)
            if self.identity is not None and (identity!=self.identity or stat.st_size<self.offset):
                raise ValueError('Owned Go log rotated or truncated while its writer was active')
            self.identity=identity;source.seek(self.offset)
            while True:
                raw=source.readline()
                if not raw:break
                if not raw.endswith(b'\n'):break  # Re-read this partial line after its writer flushes.
                self.offset+=len(raw)
                if rpc_line(raw):self.lines.append(raw)
        return b''.join(self.lines)


def compact_owned_log(path,evidence,tail_limit=2*1024*1024):
    """Call only after the owned process and its log consumer have stopped."""
    path=Path(path);evidence=Path(evidence)
    if not path.is_file() or path.is_symlink():raise ValueError('Owned source log is unavailable')
    proof_path=evidence/'genuine-rpc-evidence.log';index_path=evidence/'genuine-rpc-evidence-index.json'
    if path.resolve()==proof_path.resolve():raise ValueError('RPC proof cannot replace its source')
    source_hash=hashlib.sha256();proof_hash=hashlib.sha256();offset=0;line_number=0;entries=[];tail=deque();tail_size=0
    with path.open('rb') as source,proof_path.open('wb') as proof:
        for raw in source:
            line_number+=1;source_hash.update(raw);match=rpc_line(raw)
            if match:
                proof_offset=proof.tell();proof.write(raw);proof_hash.update(raw)
                entries.append({'source_line':line_number,'source_byte_offset':offset,'proof_byte_offset':proof_offset,
                    'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'status':int(match[1]),
                    'path':match[2].split(b'?',1)[0].decode('ascii')})
            offset+=len(raw);tail.append(raw);tail_size+=len(raw)
            while tail_size>tail_limit:
                excess=tail_size-tail_limit;first=tail[0]
                if len(first)<=excess:tail.popleft();tail_size-=len(first)
                else:tail[0]=first[excess:];tail_size-=excess
    tail_bytes=b''.join(tail)
    receipt={'schema_version':1,'kind':'exact-sanitized-owned-Gin-log-rpc-excerpt','source_file':path.name,
        'source_bytes':offset,'source_lines':line_number,'source_sha256':source_hash.hexdigest(),
        'proof_file':proof_path.name,'proof_sha256':proof_hash.hexdigest(),'entries':entries,
        'retained_tail_bytes':len(tail_bytes),'retained_tail_sha256':hashlib.sha256(tail_bytes).hexdigest(),
        'source_compacted_only_after_owned_writer_stopped':True}
    index_path.write_text(json.dumps(receipt,indent=2)+'\n')
    temporary=evidence/'.owned-go-tail.tmp'
    with temporary.open('xb') as target:target.write(tail_bytes)
    temporary.replace(path)
    return receipt
