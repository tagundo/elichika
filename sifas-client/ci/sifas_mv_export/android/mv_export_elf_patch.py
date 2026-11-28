#!/usr/bin/env python3
"""Exact-input offline MV hook planner and fresh-output ELF writer.

Without --plan this program is inert. Planning streams frozen b25 ZIP members;
it creates JSON/header source only. --write-dir additionally materializes fresh
native copies and must be explicitly requested. No source APK/library is edited,
no executable is run, and no runtime executable-memory writes are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parent
ALIGN = 65536
CODE_OFFSET = 4096
SHIM_BYTES = 64
SIDECAR_BYTES = 320
MAGIC = b"SMVAND02"
CHUNK = 1024 * 1024
EHDR = struct.Struct("<16sHHIQQQIHHHHHH")
PHDR = struct.Struct("<IIQQQQQQ")
SLOTS = {"timeUpdate": 0, "liveUpdate": 1, "musicUpdate": 2,
         "memberUpdate": 3, "overlayRender": 4, "screenWidth": 5,
         "screenHeight": 6, "memberLateUpdate": 7, "postRender": 8}
QUEUE_SLOTS = {"queueMemberAssets": 9, "queueMemberMap": 10, "queueSuitMap": 11,
               "queueViewStatus": 12, "queueQuality": 13}
ALL_SLOTS = {**SLOTS, **QUEUE_SLOTS}
QUEUE_SIDECAR_BYTES = SIDECAR_BYTES + 16 * len(QUEUE_SLOTS)
# Every copied instruction is an independently inspected, non-PC-relative
# stack store from these exact profiles. Arbitrary instruction relocation is
# deliberately unsupported. A tail B is decoded/re-encoded separately.
COPY_WORDS = {0xF81E0FF3, 0xFC1D0FE8, 0xA9BD57F6, 0xA9BE4FF4, 0xFC1E0FE8}
# Exact GL 3.12.0 queue factory and dictionary stack setup, member-view field
# read and quality getter's first non-PC-relative register instruction.
QUEUE_COPY_WORDS = {0xD10143FF, 0xD10243FF, 0xD101C3FF, 0xB9402800, 0xAA1F03E0}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def align(value, page=ALIGN):
    return (value + page - 1) // page * page


def word(value):
    return struct.pack("<I", value)


def branch(pc, target):
    delta = target - pc
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), "B range/alignment")
    return 0x14000000 | ((delta // 4) & 0x3FFFFFF)


def branch_target(pc, instruction):
    require(instruction & 0xFC000000 == 0x14000000, "Expected unconditional tail B")
    value = instruction & 0x3FFFFFF
    if value & (1 << 25):
        value -= 1 << 26
    return pc + value * 4


def adrp(pc, target, register):
    pages = ((target & ~4095) - (pc & ~4095)) // 4096
    require(-(1 << 20) <= pages < (1 << 20), "ADRP range")
    return 0x90000000 | ((pages & 3) << 29) | (((pages >> 2) & 0x7FFFF) << 5) | register


def cbz(pc, target, register, wide=False):
    delta = target - pc
    require(delta % 4 == 0 and -(1 << 20) <= delta < (1 << 20), "CBZ range")
    return (0xB4000000 if wide else 0x34000000) | (((delta // 4) & 0x7FFFF) << 5) | register


def shim_bytes(pc, sidecar, slot, entry, original_word, relocation):
    """Leaf dispatch using x16/x17 only; no BL, flag changes or dispatch writes.

    The callable original trampoline starts at byte32. Its one copied original
    stack store is the sole possible memory write on an unbound fallback path.
    A bound callback receives the untouched original ABI arguments and LR.
    """
    require(0 <= slot < len(ALL_SLOTS), "Callback slot")
    ready = sidecar + 24
    fallback = pc + 32
    extra = slot >= len(SLOTS)
    delta = (SIDECAR_BYTES + 8 * (slot - len(SLOTS)) if extra else 96 + 8 * slot) - 24
    load_callback = (0xF9400000 | ((delta // 8) << 10)) if extra else (0xF8400000 | ((delta & 511) << 12))
    words = [adrp(pc, ready, 16),
             0x91000000 | ((ready & 4095) << 10) | (16 << 5) | 16,
             0x88DFFE11,  # LDAR W17,[X16], paired with binder release store
             cbz(pc + 12, fallback, 17),
             load_callback | (16 << 5) | 17,
             cbz(pc + 20, fallback, 17, True),
             0xD61F0220,  # BR X17: original caller LR survives
             0xD503201F]
    kind = relocation["kind"]
    if kind == "tail_branch":
        target = branch_target(entry, original_word)
        require(target == relocation["target"], "Tail-branch target differs")
        words += [branch(fallback, target), 0xD503201F]
    else:
        require(kind == "copy_non_pc_relative_first_instruction" and
                original_word == relocation["word"] and original_word in (QUEUE_COPY_WORDS if extra else COPY_WORDS),
                "Unsupported first-instruction relocation")
        words += [original_word, branch(fallback + 4, entry + 4)]
    words += [0xD503201F] * (SHIM_BYTES // 4 - len(words))
    return b"".join(word(w) for w in words)


def read_exact(source, offset, count):
    require(offset >= 0 and count >= 0, "Invalid read extent")
    source.seek(offset)
    data = source.read(count)
    require(len(data) == count, "Truncated source extent")
    return data


def elf_headers(source, source_bytes):
    raw = read_exact(source, 0, EHDR.size)
    header = EHDR.unpack(raw)
    require(header[0][:7] == b"\x7fELF\x02\x01\x01" and header[1] == 3 and
            header[2] == 183 and header[8] == 64 and header[9] == PHDR.size,
            "Only ELF64 LE AArch64 ET_DYN is supported")
    require(1 <= header[10] <= 64 and header[5] + PHDR.size * header[10] <= source_bytes,
            "Invalid original program-header table")
    table = read_exact(source, header[5], PHDR.size * header[10])
    phdrs = [PHDR.unpack_from(table, n * PHDR.size) for n in range(header[10])]
    require(sum(p[0] == 6 for p in phdrs) <= 1, "Duplicate PT_PHDR")
    for p in phdrs:
        require(p[2] + p[5] <= source_bytes, "Segment exceeds source file")
        if p[0] == 1:
            require(p[5] <= p[6] and p[7] > 0 and p[7] & (p[7] - 1) == 0 and
                    p[2] % p[7] == p[3] % p[7] and p[1] & 3 != 3,
                    "Invalid or writable/executable original PT_LOAD")
    require(any(p[0] == 1 for p in phdrs), "No original PT_LOAD")
    return raw, header, phdrs


def file_offset(phdrs, rva, count=1):
    matches = [p[2] + rva - p[3] for p in phdrs
               if p[0] == 1 and p[3] <= rva and rva + count <= p[3] + p[5]]
    require(len(matches) == 1, "RVA must have exactly one file-backed PT_LOAD")
    return matches[0]


def validate_load_layout(phdrs):
    loads = [p for p in phdrs if p[0] == 1]
    for page in (4096, 16384, 65536):
        spans = sorted((p[3] // page * page, align(p[3] + p[6], page)) for p in loads)
        require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])),
                "PT_LOAD overlap after page rounding")
    require(all(p[1] & 3 != 3 for p in loads), "RWX PT_LOAD forbidden")


def mutation(name, offset, before, after):
    require(len(before) == len(after) and before != after, "Invalid fixed-length mutation")
    return {"name": name, "offset": offset, "before": before.hex(), "after": after.hex()}


def stream_result(source, source_bytes, expected_sha, patches, appends, output=None):
    """Bounded source verification, mutation and optional fresh-output copying."""
    patches = sorted(patches, key=lambda p: p["offset"])
    require(all(a["offset"] + len(bytes.fromhex(a["before"])) <= b["offset"]
                for a, b in zip(patches, patches[1:])), "Overlapping mutations")
    captured = [bytearray() for _ in patches]
    original, result, position = hashlib.sha256(), hashlib.sha256(), 0
    source.seek(0)

    def emit(data):
        result.update(data)
        if output is not None:
            output.write(data)

    while raw := source.read(CHUNK):
        require(position + len(raw) <= source_bytes, "Source grew beyond pinned size")
        original.update(raw)
        edited = bytearray(raw)
        for n, patch in enumerate(patches):
            before, after = bytes.fromhex(patch["before"]), bytes.fromhex(patch["after"])
            low = max(position, patch["offset"])
            high = min(position + len(raw), patch["offset"] + len(before))
            if low < high:
                captured[n] += raw[low - position:high - position]
                edited[low - position:high - position] = after[low - patch["offset"]:high - patch["offset"]]
        emit(edited)
        position += len(raw)
    require(position == source_bytes and original.hexdigest() == expected_sha,
            "Whole source ELF size/hash differs")
    for patch, seen in zip(patches, captured):
        require(bytes(seen).hex() == patch["before"], "Mutation preimage differs: " + patch["name"])
    for appended in appends:
        require(position <= appended["offset"], "Append overlaps source or prior append")
        while position < appended["offset"]:
            count = min(CHUNK, appended["offset"] - position)
            emit(bytes(count)); position += count
        data = bytes.fromhex(appended["hex"])
        emit(data); position += len(data)
    return result.hexdigest(), position


def make_plan(source, profile, profile_sha, image_kind):
    """Verify a seekable exact source and return a deterministic inert plan."""
    require(profile["region"] in ("GL", "JP") and image_kind in (1, 2), "Region/image kind")
    require(len(bytes.fromhex(profile_sha)) == 32, "Profile digest length")
    unity = image_kind == 2
    expected = profile["unity_sha256" if unity else "native_sha256"]
    source_bytes = profile["unity_bytes" if unity else "native_bytes"]
    require(len(bytes.fromhex(expected)) == 32, "Source digest length")
    raw_header, header, old_phdrs = elf_headers(source, source_bytes)
    validate_load_layout(old_phdrs)
    hooks = [profile["time_manager"]] if unity else profile["hooks"]
    require(len(hooks) == (1 if unity else 8), "Unexpected hook count")
    require(len({h["hook_key"] for h in hooks}) == len(hooks) and
            {SLOTS[h["hook_key"]] for h in hooks} == ({0} if unity else set(range(1, 9))),
            "Missing or duplicate typed hook slot")
    queue_hooks = profile.get("queue_hooks", []) if not unity else []
    if queue_hooks:
        require(profile["region"] == "GL" and len(queue_hooks) == len(QUEUE_SLOTS) and
                {h["hook_key"] for h in queue_hooks} == set(QUEUE_SLOTS), "Unexpected GL queue hook set")
    sidecar_size = QUEUE_SIDECAR_BYTES if queue_hooks else SIDECAR_BYTES
    rx_offset = align(source_bytes)
    rx_rva = align(max(p[3] + p[6] for p in old_phdrs if p[0] == 1))
    rw_offset, rw_rva = rx_offset + ALIGN, rx_rva + ALIGN
    new_count = len(old_phdrs) - sum(p[0] == 6 for p in old_phdrs) + 3
    require(new_count * PHDR.size <= CODE_OFFSET, "Program headers exceed RX prefix")
    code, records, mutations = bytearray(), [], []
    originals = [0] * len(ALL_SLOTS)
    for hook in sorted(hooks + queue_hooks, key=lambda h: ALL_SLOTS[h["hook_key"]]):
        slot, entry = ALL_SLOTS[hook["hook_key"]], hook["rva"]
        require(entry % 4 == 0, "Unaligned entry")
        require(any(p[0] == 1 and p[1] & 1 and p[3] <= entry and entry + 64 <= p[3] + p[5]
                    for p in old_phdrs), "Hook entry must be in executable PT_LOAD")
        offset = file_offset(old_phdrs, entry, 64)
        before = read_exact(source, offset, 64)
        require(before.hex() == hook["first64hex"] and digest(before) == hook["first64sha256"],
                "Exact 64-byte hook preimage differs: " + hook["hook_key"])
        if unity:
            full = read_exact(source, file_offset(old_phdrs, entry, hook["full_bytes"]), hook["full_bytes"])
            require(digest(full) == hook["full_sha256"], "TimeManager full FDE-span hash differs")
        shim_rva = rx_rva + CODE_OFFSET + len(code)
        generated = shim_bytes(shim_rva, rw_rva, slot, entry, struct.unpack_from("<I", before)[0], hook["relocation"])
        code += generated
        original_rva = shim_rva + 32
        originals[slot] = original_rva
        patched = word(branch(entry, shim_rva))
        mutations.append(mutation(hook["hook_key"], offset, before[:4], patched))
        records.append({"key": hook["hook_key"], "slot": slot, "entry_rva": entry,
                        "entry_offset": offset, "entry_before64": before.hex(),
                        "entry_patch_word": struct.unpack("<I", patched)[0],
                        "shim_rva": shim_rva, "shim_hex": generated.hex(),
                        "original_rva": original_rva, "relocation": hook["relocation"]})
    rx_size = CODE_OFFSET + len(code)
    phdrs = [(6, 4, rx_offset, rx_rva, rx_rva, new_count * PHDR.size, new_count * PHDR.size, 8)]
    phdrs += [p for p in old_phdrs if p[0] != 6]
    phdrs += [(1, 5, rx_offset, rx_rva, rx_rva, rx_size, rx_size, ALIGN),
              (1, 6, rw_offset, rw_rva, rw_rva, sidecar_size, sidecar_size, ALIGN)]
    require(len(phdrs) == new_count and rx_size < ALIGN, "New ELF layout")
    require([p for p in phdrs if p[0] == 1][:-2] == [p for p in old_phdrs if p[0] == 1],
            "Original PT_LOAD changed")
    validate_load_layout(phdrs)
    table = b"".join(PHDR.pack(*p) for p in phdrs)
    rx = table + bytes(CODE_OFFSET - len(table)) + code
    sidecar = bytearray(sidecar_size)
    struct.pack_into("<8s6I", sidecar, 0, MAGIC, 3 if queue_hooks else 2, sidecar_size,
                     1 if profile["region"] == "GL" else 2, image_kind, 0, 0)
    sidecar[32:64] = bytes.fromhex(expected)
    sidecar[64:96] = bytes.fromhex(profile_sha)
    struct.pack_into("<9Q", sidecar, 176, *originals[:len(SLOTS)])
    if queue_hooks:
        struct.pack_into("<5Q", sidecar, SIDECAR_BYTES + 8 * len(QUEUE_SLOTS), *originals[len(SLOTS):])
    mutations += [mutation("e_phoff", 32, raw_header[32:40], struct.pack("<Q", rx_offset)),
                  mutation("e_phnum", 56, raw_header[56:58], struct.pack("<H", new_count))]
    appends = [{"name": "MV_RX", "offset": rx_offset, "rva": rx_rva, "flags": 5, "hex": rx.hex()},
               {"name": "MV_RW", "offset": rw_offset, "rva": rw_rva, "flags": 6, "hex": sidecar.hex()}]
    output_sha, output_bytes = stream_result(source, source_bytes, expected, mutations, appends)
    return {"schema": 1, "status": "EXACT_SOURCE_VALIDATED_PLAN_ONLY", "region": profile["region"],
            "image_kind": image_kind, "member": "lib/arm64-v8a/" + ("libunity.so" if unity else "libil2cpp.so"),
            "source_sha256": expected, "source_bytes": source_bytes, "profile_sha256": profile_sha,
            "output_sha256": output_sha, "output_bytes": output_bytes,
            "sidecar_rva": rw_rva, "rx_rva": rx_rva,
            "get_time_manager_rva": profile["time_manager"]["get_rva"] if unity else 0,
            "source_program_headers": old_phdrs, "program_headers": phdrs,
            "hooks": records, "patches": sorted(mutations, key=lambda p: p["offset"]), "appends": appends,
            "old_load_segments_preserved": True, "runtime_code_writes": False,
            "callback_publication": "Validate both image sidecars, fill all callback slots, then release-store ready=1; no unpublish/unload while callbacks may execute.",
            "unwind_limit": "Leaf dispatch changes only IP scratch registers; copied prologue trampolines have no generated FDE. Async sampling/unwind inside a shim is not runtime-proven."}


def generated_header(plans):
    lines = ["/* Generated from exact frozen APK/ELF/profile inputs; no runtime validation claim. */",
             "#ifndef SIFAS_ANDROID_MV_PATCH_PROFILES_H", "#define SIFAS_ANDROID_MV_PATCH_PROFILES_H",
             "#include <stdint.h>",
             "typedef struct { uint32_t region, image_kind, sidecar_bytes; uint64_t sidecar_rva, rx_rva, get_time_manager_rva;",
             "  unsigned char source_sha256[32], profile_sha256[32];",
             "  uint64_t entry_rva[14], shim_rva[14], original_rva[14]; uint32_t entry_patch_word[14];",
             "  unsigned char shim_bytes[14][64]; } AmvPatchImageProfile;",
             "static const AmvPatchImageProfile amv_patch_images[] = {"]
    def values(items):
        return "{" + ",".join(str(x) for x in items) + "}"
    def rawbytes(hexstr):
        return values(bytes.fromhex(hexstr))
    for plan in plans:
        hooks = {h["slot"]: h for h in plan["hooks"]}
        lines += ["  { /* " + plan["region"] + "/" + str(plan["image_kind"]) + " */",
                  "    " + ",".join(map(str, [1 if plan["region"] == "GL" else 2, plan["image_kind"], len(bytes.fromhex(plan["appends"][1]["hex"])), plan["sidecar_rva"], plan["rx_rva"], plan["get_time_manager_rva"]])) + ",",
                  "    " + rawbytes(plan["source_sha256"]) + "," + rawbytes(plan["profile_sha256"]) + ","]
        for key in ("entry_rva", "shim_rva", "original_rva", "entry_patch_word"):
            lines.append("    " + values(hooks[n][key] if n in hooks else 0 for n in range(len(ALL_SLOTS))) + ",")
        lines.append("    {" + ",".join(rawbytes(hooks[n]["shim_hex"]) if n in hooks else "{0}" for n in range(len(ALL_SLOTS))) + "}")
        lines.append("  },")
    lines += ["};", "#define AMV_PATCH_IMAGE_COUNT (sizeof(amv_patch_images)/sizeof(amv_patch_images[0]))", "#endif", ""]
    return "\n".join(lines)


def write_image(source, plan, destination):
    destination = Path(destination)
    require(not destination.exists() and not destination.is_symlink() and destination.parent.is_dir(), "Fresh native destination required")
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            sha, size = stream_result(source, plan["source_bytes"], plan["source_sha256"],
                                      plan["patches"], plan["appends"], output)
            require((sha, size) == (plan["output_sha256"], plan["output_bytes"]), "Plan/output identity differs")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apk-gl", type=Path, default=Path("/dev/shm/sifas-android-material-b25-GL-20261115/LLAS_GL_FOVMOD_b25.apk"))
    parser.add_argument("--apk-jp", type=Path, default=Path("/dev/shm/sifas-android-material-b25-JP-20261115/LLAS_JP_FOVMOD_b25.apk"))
    parser.add_argument("--output-plan", type=Path, default=ROOT / "android_mv_patch_plan.json")
    parser.add_argument("--header", type=Path, default=ROOT / "android_mv_patch_profiles.h")
    parser.add_argument("--write-dir", type=Path, help="Explicitly also materialize large fresh ELF copies")
    args = parser.parse_args()
    if not args.plan:
        if args.write_dir:
            parser.error("--write-dir requires --plan")
        print(json.dumps({"status": "INERT", "large_outputs_created": False})); return
    require(args.output_plan.resolve() != args.header.resolve(), "Plan/header outputs must differ")
    if args.write_dir:
        require(args.write_dir.resolve() not in (args.output_plan.resolve(), args.header.resolve()),
                "Native output directory must differ from plan/header")
    for path in (args.output_plan, args.header):
        require(not path.exists() and not path.is_symlink() and path.parent.is_dir(), "Fresh plan/header output required")
    if args.write_dir:
        require(not args.write_dir.exists() and not args.write_dir.is_symlink() and args.write_dir.parent.is_dir(), "Fresh native output directory required")
    plans, inputs = [], []
    for region, apk in (("GL", args.apk_gl), ("JP", args.apk_jp)):
        raw = (ROOT / ("android_mv_profile_" + region + ".json")).read_bytes()
        profile, profile_sha = json.loads(raw), digest(raw)
        require(profile["region"] == region and apk.is_file() and not apk.is_symlink() and apk.stat().st_size == profile["apk_bytes"], "Exact source APK required")
        with apk.open("rb") as source:
            require(hashlib.file_digest(source, "sha256").hexdigest() == profile["apk_sha256"], "Whole APK digest differs")
        with zipfile.ZipFile(apk) as archive:
            require(len(set(archive.namelist())) == len(archive.namelist()), "Duplicate ZIP members")
            for kind in (1, 2):
                member = "lib/arm64-v8a/" + ("libil2cpp.so" if kind == 1 else "libunity.so")
                with archive.open(member) as source:
                    plans.append(make_plan(source, profile, profile_sha, kind))
                inputs.append((apk, member))
    document = {"schema": 1, "status": "STATIC_PLANS_NOT_GAME_RUNTIME_VALIDATED", "images": plans,
                "sidecar": {"magic": MAGIC.decode(), "version": 2, "bytes": 320, "ready_offset": 24,
                            "callbacks_offset": 96, "original_rvas_offset": 176},
                "queue_sidecar": {"version": 3, "bytes": QUEUE_SIDECAR_BYTES,
                                  "callbacks_offset": SIDECAR_BYTES, "original_rvas_offset": SIDECAR_BYTES + 8 * len(QUEUE_SLOTS)},
                "typed_slots": ALL_SLOTS, "large_outputs_created": bool(args.write_dir)}
    with args.output_plan.open("x") as target:
        json.dump(document, target, indent=2); target.write("\n")
    with args.header.open("x") as target:
        target.write(generated_header(plans))
    if args.write_dir:
        args.write_dir.mkdir(mode=0o700)
        for (apk, member), plan in zip(inputs, plans):
            name = plan["region"] + "-" + Path(member).name
            with zipfile.ZipFile(apk) as archive, archive.open(member) as source:
                write_image(source, plan, args.write_dir / name)
    print(json.dumps({"plan": str(args.output_plan), "header": str(args.header),
                      "images": len(plans), "large_outputs_created": bool(args.write_dir)}))


if __name__ == "__main__":
    main()
