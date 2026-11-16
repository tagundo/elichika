"""Small ELF packaging tests and actual generated ARM64 leaf execution.

No game ELF is materialized or executed. Unicorn runs only authored branches,
dispatch shims and one inspected copied stack-store instruction, stopping before
all original game/engine bodies and callbacks.
"""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import mv_export_elf_patch as patcher

ROOT = Path(__file__).resolve().parent


def synthetic(with_phdr=True):
    data = bytearray(0x10100)
    phdrs = [(1, 5, 0, 0, 0, 0x3000, 0x3000, 65536),
             (1, 6, 0x10000, 0x10000, 0x10000, 256, 256, 65536)]
    if with_phdr:
        phdrs.insert(0, (6, 4, 64, 64, 64, 3 * 56, 3 * 56, 8))
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    data[:64] = patcher.EHDR.pack(ident, 3, 183, 1, 0, 64, 0, 0, 64, 56, len(phdrs), 0, 0, 0)
    for n, phdr in enumerate(phdrs):
        patcher.PHDR.pack_into(data, 64 + 56 * n, *phdr)
    hooks = []
    for n, (key, slot) in enumerate(sorted(patcher.SLOTS.items(), key=lambda item: item[1])):
        if slot == 0:
            continue
        rva = 0x1000 + n * 0x80
        first = 0xF81E0FF3
        relocation = {"kind": "copy_non_pc_relative_first_instruction", "word": first}
        if key == "musicUpdate":
            first = patcher.branch(rva, 0x2400)
            relocation = {"kind": "tail_branch", "target": 0x2400}
        raw = patcher.word(first) + patcher.word(0xD503201F) * 15
        data[rva:rva + 64] = raw
        hooks.append({"hook_key": key, "rva": rva, "first64hex": raw.hex(),
                      "first64sha256": patcher.digest(raw), "relocation": relocation})
    time_rva = 0x2000
    full = patcher.word(0xFC1E0FE8) + patcher.word(0xD503201F) * 121
    data[time_rva:time_rva + len(full)] = full
    source = bytes(data)
    profile = {"region": "GL", "native_sha256": patcher.digest(source), "native_bytes": len(source),
               "unity_sha256": patcher.digest(source), "unity_bytes": len(source), "hooks": hooks,
               "time_manager": {"hook_key": "timeUpdate", "rva": time_rva,
                                "first64hex": full[:64].hex(), "first64sha256": patcher.digest(full[:64]),
                                "full_bytes": len(full), "full_sha256": patcher.digest(full), "get_rva": 0x2800,
                                "relocation": {"kind": "copy_non_pc_relative_first_instruction", "word": 0xFC1E0FE8}}}
    return source, profile


class PackagingTests(unittest.TestCase):
    def test_preserves_loads_and_adds_exact_sidecar(self):
        for has_phdr in (False, True):
            for kind in (1, 2):
                raw, profile = synthetic(has_phdr)
                plan = patcher.make_plan(io.BytesIO(raw), profile, "55" * 32, kind)
                self.assertEqual([p for p in plan["program_headers"] if p[0] == 1][:-2],
                                 [p for p in plan["source_program_headers"] if p[0] == 1])
                self.assertEqual(sum(p[0] == 6 for p in plan["program_headers"]), 1)
                self.assertTrue(all(p[1] & 3 != 3 for p in plan["program_headers"] if p[0] == 1))
                sidecar = bytes.fromhex(plan["appends"][1]["hex"])
                self.assertEqual(struct.unpack_from("<8s6I", sidecar), (patcher.MAGIC, 2, 320, 1, kind, 0, 0))
                self.assertEqual(sidecar[32:64].hex(), patcher.digest(raw))
                self.assertEqual(sidecar[64:96], b"\x55" * 32)
                self.assertEqual(sidecar[96:168], bytes(72))
                self.assertEqual(sidecar[168:176], bytes(8))
                originals = struct.unpack_from("<9Q", sidecar, 176)
                self.assertEqual({n for n, value in enumerate(originals) if value}, {0} if kind == 2 else set(range(1, 9)))
                for hook in plan["hooks"]:
                    self.assertEqual(originals[hook["slot"]], hook["shim_rva"] + 32)
                    self.assertEqual(len(bytes.fromhex(hook["shim_hex"])), 64)
                for item in plan["appends"]:
                    self.assertEqual(item["offset"] % 65536, 0)
                    self.assertEqual(item["rva"] % 65536, 0)
                self.assertEqual(raw, synthetic(has_phdr)[0])

    def test_hash_preimage_and_layout_fail_closed(self):
        raw, profile = synthetic()
        changed = bytearray(raw); changed[0x2500] ^= 1
        with self.assertRaisesRegex(ValueError, "Whole source"):
            patcher.make_plan(io.BytesIO(changed), profile, "55" * 32, 1)
        changed = bytearray(raw); changed[profile["hooks"][0]["rva"] + 8] ^= 1
        with self.assertRaisesRegex(ValueError, "64-byte hook"):
            patcher.make_plan(io.BytesIO(changed), profile, "55" * 32, 1)
        changed = bytearray(raw); struct.pack_into("<I", changed, 64 + 56 + 4, 7)
        with self.assertRaisesRegex(ValueError, "writable/executable"):
            patcher.make_plan(io.BytesIO(changed), profile, "55" * 32, 1)
        with self.assertRaisesRegex(ValueError, "Truncated|Whole source"):
            patcher.make_plan(io.BytesIO(raw[:-1]), profile, "55" * 32, 1)

    def test_rejects_unsafe_relocation_and_wrong_branch(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            patcher.shim_bytes(0x30000, 0x40000, 0, 0x1000, 0x10000000,
                               {"kind": "copy_non_pc_relative_first_instruction", "word": 0x10000000})
        with self.assertRaisesRegex(ValueError, "target differs"):
            patcher.shim_bytes(0x30000, 0x40000, 2, 0x1000, patcher.branch(0x1000, 0x2000),
                               {"kind": "tail_branch", "target": 0x2004})
        with self.assertRaisesRegex(ValueError, "B range"):
            patcher.branch(0, 1 << 28)
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            raw, profile = synthetic(); profile["hooks"][0] = profile["hooks"][1]
            patcher.make_plan(io.BytesIO(raw), profile, "55" * 32, 1)

    def test_fresh_streamed_output_and_failure_cleanup(self):
        raw, profile = synthetic()
        plan = patcher.make_plan(io.BytesIO(raw), profile, "55" * 32, 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.so"
            patcher.write_image(io.BytesIO(raw), plan, output)
            self.assertEqual(output.stat().st_size, plan["output_bytes"])
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), plan["output_sha256"])
            result = output.read_bytes()
            for hook in plan["hooks"]:
                self.assertEqual(struct.unpack_from("<I", result, hook["entry_offset"])[0], hook["entry_patch_word"])
                self.assertEqual(result[hook["entry_offset"] + 4:hook["entry_offset"] + 64],
                                 bytes.fromhex(hook["entry_before64"])[4:])
            with self.assertRaisesRegex(ValueError, "Fresh"):
                patcher.write_image(io.BytesIO(raw), plan, output)
            self.assertEqual(output.read_bytes(), result)
            broken = bytearray(raw); broken[-1] ^= 1
            failed = Path(directory) / "failed.so"
            with self.assertRaisesRegex(ValueError, "Whole source"):
                patcher.write_image(io.BytesIO(broken), plan, failed)
            self.assertFalse(failed.exists())


try:
    sys.path[:0] = ["/tmp/mv-suit-fix-python-20261115"]
    import unicorn
    from unicorn import arm64_const as regs
except ImportError:
    unicorn = None


@unittest.skipIf(unicorn is None, "Unicorn is unavailable; packaging tests still run")
class AuthoredArm64Tests(unittest.TestCase):
    def execute(self, hook, slot, bias, state):
        uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        mapped, writes = set(), []
        page = 4096
        def put(address, data):
            for start in range(address // page * page, (address + len(data) - 1) // page * page + page, page):
                if start not in mapped:
                    uc.mem_map(start, page); mapped.add(start)
            uc.mem_write(address, bytes(data))
        entry = bias + hook["rva"]
        shim = bias + 0x7800000 + slot * 64
        sidecar = bias + 0x7810000
        selected = 0x7100100000 + slot * 0x1000
        wrong = 0x7100200000 + slot * 0x1000
        original_word = struct.unpack_from("<I", bytes.fromhex(hook["first64hex"]))[0]
        # RVA-relative relocation is independent of the loaded ASLR bias.
        raw = patcher.shim_bytes(shim - bias, sidecar - bias, slot, hook["rva"], original_word, hook["relocation"])
        put(entry, patcher.word(patcher.branch(entry, shim)))
        put(shim, raw)
        original = bias + (hook["relocation"]["target"] if hook["relocation"]["kind"] == "tail_branch" else hook["rva"] + 4)
        for target in (original, selected, wrong):
            put(target, patcher.word(0xD65F03C0))
        config = bytearray(320)
        struct.pack_into("<I", config, 24, 0 if state == "unbound" else 1)
        for n in range(9):
            struct.pack_into("<Q", config, 96 + 8 * n, wrong)
        struct.pack_into("<Q", config, 96 + 8 * slot, 0 if state == "null" else selected)
        put(sidecar, config)
        for address in (entry, shim, original, selected, wrong):
            uc.mem_protect(address // page * page, page, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        stack = 0x700100000
        put(stack - page, bytes(page))
        uc.reg_write(regs.UC_ARM64_REG_SP, stack)
        xvalues = [0xABC0000000000000 + n * 0x10101 for n in range(31)]
        qvalues = [0x123456789ABCDEF00123456789ABC000 + n for n in range(32)]
        xregisters = [getattr(regs, "UC_ARM64_REG_X" + str(n)) for n in range(31)]
        for register, value in zip(xregisters, xvalues):
            uc.reg_write(register, value)
        for n, value in enumerate(qvalues):
            uc.reg_write(getattr(regs, "UC_ARM64_REG_Q" + str(n)), value)
        uc.reg_write(regs.UC_ARM64_REG_NZCV, 0xA0000000)
        reached = []
        def instruction(machine, address, size, opaque):
            if address in (original, selected, wrong):
                reached.append(address); machine.emu_stop()
        def write(machine, access, address, size, value, opaque):
            writes.append((address, size))
        uc.hook_add(unicorn.UC_HOOK_CODE, instruction)
        uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
        uc.emu_start(shim + 32 if state == "direct" else entry, 0, count=32)
        self.assertEqual(reached, [selected if state == "bound" else original])
        self.assertEqual(uc.reg_read(regs.UC_ARM64_REG_NZCV), 0xA0000000)
        for n, value in enumerate(xvalues):
            if n not in (16, 17):
                self.assertEqual(uc.reg_read(xregisters[n]), value)
        for n, value in enumerate(qvalues):
            self.assertEqual(uc.reg_read(getattr(regs, "UC_ARM64_REG_Q" + str(n))), value)
        self.assertEqual(bytes(uc.mem_read(sidecar, 320)), bytes(config))
        if state == "bound" or hook["relocation"]["kind"] == "tail_branch":
            self.assertEqual(uc.reg_read(regs.UC_ARM64_REG_SP), stack)
            self.assertEqual(writes, [])
        else:
            layouts = {0xF81E0FF3: (32, struct.pack("<Q", xvalues[19])),
                       0xFC1D0FE8: (48, struct.pack("<Q", qvalues[8] & ((1 << 64) - 1))),
                       0xA9BD57F6: (48, struct.pack("<QQ", xvalues[22], xvalues[21])),
                       0xA9BE4FF4: (32, struct.pack("<QQ", xvalues[20], xvalues[19])),
                       0xFC1E0FE8: (32, struct.pack("<Q", qvalues[8] & ((1 << 64) - 1)))}
            amount, expected = layouts[original_word]
            self.assertEqual(uc.reg_read(regs.UC_ARM64_REG_SP), stack - amount)
            self.assertEqual(bytes(uc.mem_read(stack - amount, len(expected))), expected)
            self.assertEqual(sum(n for address, n in writes), len(expected))
            self.assertTrue(all(stack - amount <= address and address + n <= stack - amount + len(expected)
                                for address, n in writes))

    def test_both_actual_profiles_all_slots_aslr_and_publication_states(self):
        count = 0
        for region in ("GL", "JP"):
            profile = json.loads((ROOT / ("android_mv_profile_" + region + ".json")).read_text())
            for hook in [profile["time_manager"]] + profile["hooks"]:
                slot = patcher.SLOTS[hook["hook_key"]]
                for bias in (0, 0x7000000000, 0x1234500000, 0x1234511000):
                    for state in ("unbound", "null", "bound", "direct"):
                        with self.subTest(region=region, slot=slot, bias=bias, state=state):
                            self.execute(hook, slot, bias, state)
                            count += 1
        self.assertEqual(count, 288)


if __name__ == "__main__":
    unittest.main(verbosity=2)
