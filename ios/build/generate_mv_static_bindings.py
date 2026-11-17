#!/usr/bin/env python3
"""Resolve the Android export contract against the exact GL iOS metadata.

All addresses come from the signed-input image's registrations. No API address
is inferred from an Android RVA or from adjacent stripped functions.
"""
import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path


class Registry:
    METHOD_POINTERS = 0x104E508A0
    REGISTRATION = 0x104D952B0
    CODE_REGISTRATION = 0x104B3FBD8

    def __init__(self, image, metadata):
        self.image, self.metadata = image, metadata
        self.h = struct.unpack_from('<68I', metadata)
        assert self.h[:2] == (0xFAB11BAF, 24)
        self.segments = []
        off = 32
        for _ in range(struct.unpack_from('<I', image, 16)[0]):
            cmd, size = struct.unpack_from('<II', image, off)
            if cmd == 0x19:
                _, _, _, va, _, fileoff, filesize, *_ = struct.unpack_from('<II16sQQQQiiII', image, off)
                if filesize:
                    self.segments.append((va, fileoff, filesize))
            off += size
        self.types = [self.type(i) for i in range(self.h[41] // 100)]
        self.methods = [self.method(i) for i in range(self.h[13] // 52)]
        self.by_name = {self.full(t): t for t in self.types}
        reg = [self.unpack('<QQ', self.REGISTRATION + i * 16) for i in range(8)]
        assert reg[5][0] == reg[6][0] == len(self.types)
        self.generic_classes, self.generic_insts, self.generic_methods, self.raw_types, self.method_specs, self.offsets, self.sizes, self.usages = reg
        self.cache_names = {}

    def off(self, address):
        for va, fileoff, size in self.segments:
            if va <= address < va + size:
                return fileoff + address - va
        raise ValueError(f'Unmapped VA {address:#x}')

    def unpack(self, fmt, address):
        return struct.unpack_from(fmt, self.image, self.off(address))

    def ptr(self, address):
        return self.unpack('<Q', address)[0]

    def s(self, index):
        assert 0 <= index < self.h[7]
        off = self.h[6] + index
        return self.metadata[off:self.metadata.index(0, off)].decode()

    def type(self, index):
        t = struct.unpack_from('<19i8H2I', self.metadata, self.h[40] + 100 * index)
        return dict(index=index, name=self.s(t[0]), namespace=self.s(t[1]), typeindex=t[2], parent=t[5], fieldstart=t[11], methodstart=t[12], fieldcount=t[21], methodcount=t[19])

    def method(self, index):
        t = struct.unpack_from('<10iI4H', self.metadata, self.h[12] + 52 * index)
        return dict(index=index, name=self.s(t[0]), classindex=t[1], returntype=t[2], paramstart=t[3], generic=t[4], methodindex=t[5], flags=t[11], params=t[14])

    @staticmethod
    def full(t):
        return '.'.join(x for x in (t['namespace'], t['name']) if x)

    def raw(self, index):
        assert 0 <= index < self.raw_types[0]
        return self.ptr(self.raw_types[1] + index * 8)

    def name_raw(self, address):
        if address in self.cache_names:
            return self.cache_names[address]
        data, bits = self.unpack('<QI', address)
        kind, byref = (bits >> 16) & 255, bool(bits & (1 << 30))
        primitives = {1: 'System.Void', 2: 'System.Boolean', 3: 'System.Char', 4: 'System.SByte', 5: 'System.Byte', 6: 'System.Int16', 7: 'System.UInt16', 8: 'System.Int32', 9: 'System.UInt32', 10: 'System.Int64', 11: 'System.UInt64', 12: 'System.Single', 13: 'System.Double', 14: 'System.String', 24: 'System.IntPtr', 25: 'System.UIntPtr', 28: 'System.Object'}
        if kind in primitives:
            name = primitives[kind]
        elif kind in (0x11, 0x12):
            name = self.full(self.types[data & 0xffffffff])
        elif kind == 0x1d:
            name = self.name_raw(data) + '[]'
        elif kind == 0x0f:
            name = self.name_raw(data) + '*'
        elif kind == 0x14:
            element = self.ptr(data)
            rank = self.unpack('<B', data + 8)[0]
            name = self.name_raw(element) + '[' + ',' * (rank - 1) + ']'
        elif kind == 0x15:
            index = self.unpack('<i', data)[0]
            inst = self.ptr(data + 8)
            count = self.unpack('<I', inst)[0]
            argv = self.ptr(inst + 8)
            name = self.full(self.types[index]) + '<' + ','.join(self.name_raw(self.ptr(argv + i * 8)) for i in range(count)) + '>'
        elif kind in (0x13, 0x1e):
            name = f'!{kind:x}:{data}'
        else:
            raise ValueError(f'Unsupported type {kind:#x} at {address:#x}')
        if byref:
            name += '&'
        self.cache_names[address] = name
        return name

    def typename(self, index):
        return self.name_raw(self.raw(index))

    def method_row(self, mt):
        owner = self.types[mt['classindex']]
        params = [struct.unpack_from('<iii', self.metadata, self.h[22] + (mt['paramstart'] + i) * 12)[2] for i in range(mt['params'])]
        address = self.ptr(self.METHOD_POINTERS + mt['methodindex'] * 8) if mt['methodindex'] >= 0 else None
        return dict(va=hex(address) if address else None, return_type=self.typename(mt['returntype']), parameter_types=[self.typename(i) for i in params], parameter_type_indices=params, is_static=bool(mt['flags'] & 0x10), ownerFullName=self.full(owner), method_name=mt['name'], metadata_index=mt['index'], first32hex=self.image[self.off(address):self.off(address) + 32].hex() if address else None)

    def resolve_method(self, owner, name, static, result, params):
        t = self.by_name[owner]
        found = []
        for i in range(t['methodstart'], t['methodstart'] + t['methodcount']):
            mt = self.methods[i]
            if mt['name'] != name or mt['params'] != len(params) or bool(mt['flags'] & 0x10) != static:
                continue
            row = self.method_row(mt)
            if row['return_type'] == result and row['parameter_types'] == params:
                found.append(row)
        if len(found) != 1:
            raise ValueError(f'Expected one {owner}.{name}({params}): {found}')
        return found[0]

    def resolve_field(self, owner, name, expected=None, size=None):
        t = self.by_name[owner]
        offsets = self.ptr(self.offsets[1] + t['index'] * 8)
        found = []
        for local in range(t['fieldcount']):
            index = t['fieldstart'] + local
            si, ti, _ = struct.unpack_from('<iii', self.metadata, self.h[24] + index * 12)
            if self.s(si) != name:
                continue
            typename = self.typename(ti)
            if expected and typename != expected:
                raise ValueError(f'Field type differs: {owner}.{name}: {typename} != {expected}')
            raw = self.raw(ti)
            _, bits = self.unpack('<QI', raw)
            assert not (bits & 0x10), f'Static field {owner}.{name}'
            offset = self.unpack('<i', offsets + local * 4)[0]
            found.append(dict(offset=offset, size=size, ownerFullName=owner, type=typename, metadata_index=index, type_index=ti, field_name=name))
        if len(found) != 1:
            raise ValueError(f'Expected one field {owner}.{name}: {found}')
        return found[0]

    def class_row(self, t):
        sizes = self.ptr(self.sizes[1] + t['index'] * 8)
        instance, native, static, thread = self.unpack('<IIII', sizes)
        raw = self.raw(t['typeindex'])
        _, bits = self.unpack('<QI', raw)
        is_value = ((bits >> 16) & 255) == 0x11
        return dict(type_index=t['index'], il2cpp_type_index=t['typeindex'], raw_type_va=hex(raw), value_size=instance - 16 if is_value else None, instance_size=instance, native_size=native, parent=self.typename(t['parent']) if t['parent'] >= 0 else None)

    def closed_method(self, owner, name, argument):
        definition = self.by_name[owner]
        definitions = [mt for mt in self.methods if mt['classindex'] == definition['index'] and mt['name'] == name]
        assert len(definitions) == 1
        insts = []
        for i in range(self.generic_insts[0]):
            inst = self.ptr(self.generic_insts[1] + i * 8)
            count = self.unpack('<I', inst)[0]
            if count == 1 and self.name_raw(self.ptr(self.ptr(inst + 8))) == argument:
                insts.append(i)
        specs = []
        for i in range(self.method_specs[0]):
            method, class_inst, method_inst = self.unpack('<iii', self.method_specs[1] + i * 12)
            if method == definitions[0]['index'] and class_inst in insts and method_inst == -1:
                specs.append(i)
        assert len(specs) == 1
        matches = []
        _, pointers = self.unpack('<QQ', self.CODE_REGISTRATION + 32)
        for i in range(self.generic_methods[0]):
            spec, method, invoker = self.unpack('<iii', self.generic_methods[1] + i * 12)
            if spec == specs[0]:
                matches.append((self.ptr(pointers + method * 8), invoker))
        assert len(matches) == 1
        address, invoker = matches[0]
        pairs = []
        for i in range(self.h[51] // 8):
            dest, source = struct.unpack_from('<II', self.metadata, self.h[50] + i * 8)
            if source >> 29 == 6 and source & 0x1fffffff == specs[0]:
                pairs.append((i, dest))
        assert pairs
        cells = {self.ptr(self.usages[1] + dest * 8) for _, dest in pairs}
        assert len(cells) == 1
        lists = []
        for i in range(self.h[49] // 8):
            start, count = struct.unpack_from('<II', self.metadata, self.h[48] + i * 8)
            if any(start <= pair < start + count for pair, _ in pairs):
                lists.append(i)
        return dict(va=hex(address), return_type='System.Void', parameter_types=[argument] if name == 'Broadcast' else [], is_static=False, ownerFullName=owner, method_name=name, metadata_index=definitions[0]['index'], method_spec_index=specs[0], method_info_cell_va=hex(next(iter(cells))), method_info_usage_lists=lists, first32hex=self.image[self.off(address):self.off(address) + 32].hex(), generic_argument=argument, invoker_index=invoker)


def arguments(text):
    return [x.strip() for x in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)(?![^()]*\))', text)]


def branch_target(address, word, link=False):
    assert word >> 26 == (0b100101 if link else 0b000101)
    displacement = word & 0x03ffffff
    if displacement & 0x02000000:
        displacement -= 0x04000000
    return address + displacement * 4


def annotate_job_handle_abi(method, read_at):
    """The method table names boxed adjustors; job arrays hold unboxed values."""
    assert method['ownerFullName'] == 'Unity.Jobs.JobHandle'
    boxed = int(method['va'], 16)
    prefix = read_at(boxed, 8)
    add, branch = struct.unpack('<II', prefix)
    assert add == 0x91004000, 'Expected boxed JobHandle this+16 adjustor'
    body = branch_target(boxed + 4, branch)
    assert body == 0x10392B49C
    assert prefix == bytes.fromhex(method['first32hex'])[:8]
    calls = []
    for call in (0x101489B24, 0x101489B64):
        word = struct.unpack('<I', read_at(call, 4))[0]
        assert branch_target(call, word, link=True) == body
        calls.append(dict(va=hex(call), instruction=hex(word)))
    method.update(unboxed_call_va=hex(body), unboxed_first32hex=read_at(body, 32).hex(), boxed_adjustor_this_bytes=16, original_member_unboxed_calls=calls)


def generate(image, metadata, contract):
    r = Registry(image, metadata)
    init = contract[contract.index('bool init_runtime()'):contract.index('bool complete_jobs()')]
    init = re.sub(r'^#.*$', '', init, flags=re.MULTILINE)
    owners = {name: '.'.join(x for x in (ns, cls) if x) for name, ns, cls in re.findall(r'\*(\w+)=klass\("([^"]*)","([^"]*)"\)', init)}
    params = {}
    for match in re.finditer(r'\*(\w+)\[\]\s*=\s*\{([^}]*)\}', init):
        params[match[1]] = re.findall(r'"([^"]*)"', match[2])
    def owner(text):
        if text.startswith('klass('):
            return '.'.join(x for x in re.findall(r'"([^"]*)"', text) if x)
        return owners[text]
    methods, fields, missing = {}, {}, []
    for macro, text in re.findall(r'\b([MF])\(([^;]+)\);', init):
        if text.startswith('dst,'):
            continue
        a = arguments(text)
        try:
            if macro == 'M':
                dst, own, name, static, ret, count, arg = a
                methods[dst] = r.resolve_method(owner(own), json.loads(name), static == 'true', json.loads(ret), [] if arg == 'nullptr' else params[arg])
            else:
                dst, own, name, typ, size = a
                fields[dst] = r.resolve_field(owner(own), json.loads(name), None if typ == 'nullptr' else json.loads(typ), int(size))
        except (ValueError, KeyError) as exc:
            missing.append(dict(macro=macro, declaration=text, error=str(exc)))
    methods['hook[OVERLAY]'] = r.resolve_method('LLAS.Scene.Live.Components.LiveCoreOverlayCamera', 'OnRenderImage', False, 'System.Void', ['UnityEngine.RenderTexture', 'UnityEngine.RenderTexture'])
    waveform = [r.method_row(mt) for mt in r.methods if mt['name'] == 'GetWaveFormInfo' and r.full(r.types[mt['classindex']]) == 'CriAtomExAcb' and mt['params'] == 2]
    waveform = [mt for mt in waveform if mt['parameter_types'][0] == 'System.String' and mt['parameter_types'][1].endswith('&')]
    assert len(waveform) == 1, waveform
    methods['cri_waveform'] = waveform[0]
    wave = waveform[0]['parameter_types'][1][:-1]
    for dst, name, typ, size in [('wave_id', 'waveId', None, 4), ('wave_rate', 'samplingRate', None, 4), ('wave_channels', 'numChannels', None, 4), ('wave_samples', 'numSamples', None, 8), ('wave_streaming', 'streamingFlag', 'System.Boolean', 1)]:
        fields[dst] = r.resolve_field(wave, name, typ, size)
    cues = [t for t in r.types if any(r.s(struct.unpack_from('<iii', metadata, r.h[24] + (t['fieldstart'] + j) * 12)[0]) == '<CueSheetName>k__BackingField' for j in range(t['fieldcount']))]
    cue_names = []
    for t in cues:
        try:
            sheet = r.resolve_field(r.full(t), '<CueSheetName>k__BackingField', 'System.String', 8)
            cue = r.resolve_field(r.full(t), '<CueName>k__BackingField', 'System.String', 8)
        except ValueError:
            continue
        cue_names.append(r.full(t))
        fields['cue_sheet'], fields['cue_name'] = sheet, cue
    assert len(cue_names) == 1, cue_names
    fields['list_items'] = r.resolve_field('System.Collections.Generic.List`1', '_items', None, 8)
    fields['list_size'] = r.resolve_field('System.Collections.Generic.List`1', '_size', 'System.Int32', 4)
    # Open generic metadata leaves field offsets at zero. The original core
    # camera calls this exact shared List<reference>.Add implementation when it
    # adds its command buffer. Its two loads independently establish the closed
    # reference-list layout; never consume those unresolved metadata zeros.
    call_va, add_va = 0x10148082C, 0x102316C0C
    branch = r.unpack('<I', call_va)[0]
    displacement = branch & 0x03ffffff
    if displacement & 0x02000000:
        displacement -= 0x04000000
    assert branch >> 26 == 0b100101 and call_va + displacement * 4 == add_va
    size_word = r.unpack('<I', add_va + 0x20)[0]
    items_word = r.unpack('<I', add_va + 0x24)[0]
    assert size_word == 0xb9401816 and items_word == 0xf9400817
    fields['list_items'].update(offset=16, metadata_open_generic_offset=0, layout_proof='Original LiveCoreCamera.SetRenderTextures -> shared reference List.Add -> ldr x23,[x0,#0x10]')
    fields['list_size'].update(offset=24, metadata_open_generic_offset=0, layout_proof='Original LiveCoreCamera.SetRenderTextures -> shared reference List.Add -> ldr w22,[x0,#0x18]')
    methods['pause_broadcast'] = r.closed_method('KLab.MessageBuses.DeferredMessageBus`1', 'Broadcast', 'LLAS.MBus.Live.PauseMessage')
    methods['pause_dispatch'] = r.closed_method('KLab.MessageBuses.DeferredMessageBus`1', 'Dispatch', 'LLAS.MBus.Live.PauseMessage')
    used = set(owners.values()) | {row['ownerFullName'] for row in methods.values()} | {row['ownerFullName'] for row in fields.values()} | {'UnityEngine.Rendering.RenderTargetIdentifier', 'Unity.Jobs.JobHandle', 'LLAS.MBus.Live.PauseMessage'}
    classes = {name: r.class_row(r.by_name[name]) for name in sorted(used)}
    assert classes['Unity.Jobs.JobHandle']['value_size'] == 16
    assert r.class_row(r.by_name['UnityEngine.SceneManagement.Scene'])['value_size'] == 4
    annotate_job_handle_abi(methods['job_complete'], lambda address, size: image[r.off(address):r.off(address) + size])
    native = {}
    for name, va in [('initialize_metadata', 0x101037C34), ('object_new', 0x101014950), ('type_from_handle', 0x103B9BAD0), ('is_instance', 0x103AF6D4C), ('particle_wake', 0x100611CE4)]:
        native[name] = dict(va=hex(va), first32hex=image[r.off(va):r.off(va) + 32].hex())
    native['reference_list_add'] = dict(va=hex(add_va), first32hex=image[r.off(add_va):r.off(add_va) + 32].hex(), command_buffer_call_va=hex(call_va), command_buffer_call_word=hex(branch), size_load_va=hex(add_va + 0x20), size_load_word=hex(size_word), items_load_va=hex(add_va + 0x24), items_load_word=hex(items_word))
    return dict(schema=1, image_sha256=hashlib.sha256(image).hexdigest(), metadata_sha256=hashlib.sha256(metadata).hexdigest(), registration_va=hex(r.REGISTRATION), method_pointer_table_va=hex(r.METHOD_POINTERS), registrations={name: dict(count=pair[0], pointer=hex(pair[1])) for name, pair in [('types', r.raw_types), ('field_offsets', r.offsets), ('type_sizes', r.sizes)]}, native=native, methods=methods, fields=fields, classes=classes, missing=missing)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ipa', type=Path, required=True)
    p.add_argument('--contract', type=Path, default=Path(__file__).resolve().parents[2] / 'ci/sifas_mv_export/android/android_mv_game_bindings.cpp')
    p.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'native/SIFASMVStaticProfile.json')
    a = p.parse_args()
    with zipfile.ZipFile(a.ipa) as z:
        image = z.read('Payload/global.app/global')
        metadata = z.read('Payload/global.app/Data/Managed/Metadata/global-metadata.dat')
    result = generate(image, metadata, a.contract.read_text())
    a.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(methods=len(result['methods']), fields=len(result['fields']), classes=len(result['classes']), missing=result['missing'])))
    return bool(result['missing'])


if __name__ == '__main__':
    raise SystemExit(main())
