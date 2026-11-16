#import "SIFASMVExportBindings.h"
#include "SIFASMVExportPatchProfile.h"
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <atomic>
#include <cstring>

namespace {
bool zero(const uint8_t *value, size_t size) {
    for (size_t i=0;i<size;i++) if (value[i]) return false;
    return true;
}

bool verify(intptr_t &slide) {
    const auto *header=reinterpret_cast<const mach_header_64 *>(_dyld_get_image_header(0));
    if (!header || header->magic!=MH_MAGIC_64 || header->cputype!=CPU_TYPE_ARM64 ||
        header->cpusubtype!=0 || header->filetype!=MH_EXECUTE ||
        header->ncmds>128 || header->sizeofcmds>8192-sizeof(*header)) return false;
    slide=_dyld_get_image_vmaddr_slide(0);
    if (reinterpret_cast<uintptr_t>(header)!=kSIFASMVBase+slide) return false;
    const uint8_t *cursor=reinterpret_cast<const uint8_t *>(header)+sizeof(*header);
    const uint8_t *end=cursor+header->sizeofcmds;
    bool uuid=false, rx=false, rw=false, linkedit=false;
    unsigned segmentIndex=0;
    for (uint32_t i=0;i<header->ncmds;i++) {
        if (end-cursor<static_cast<ptrdiff_t>(sizeof(load_command))) return false;
        const auto *command=reinterpret_cast<const load_command *>(cursor);
        if (command->cmdsize<sizeof(load_command) || command->cmdsize%8 ||
            command->cmdsize>static_cast<size_t>(end-cursor)) return false;
        if (command->cmd==LC_UUID) {
            if (uuid || command->cmdsize!=sizeof(uuid_command)) return false;
            uuid=!std::memcmp(reinterpret_cast<const uuid_command *>(command)->uuid,kSIFASMVUUID,16);
            if (!uuid) return false;
        } else if (command->cmd==LC_SEGMENT_64) {
            if (command->cmdsize<sizeof(segment_command_64)) return false;
            const auto *segment=reinterpret_cast<const segment_command_64 *>(command);
            if (segment->nsects>64 || command->cmdsize!=sizeof(*segment)+segment->nsects*sizeof(section_64)) return false;
            if (!std::strncmp(segment->segname,"__SIFASMVX",16) || !std::strncmp(segment->segname,"__SIFASMVD",16)) {
                const bool executable=!std::strncmp(segment->segname,"__SIFASMVX",16);
                const uintptr_t preferred=executable?kSIFASMVRX:kSIFASMVRW;
                const uint64_t fileOffset=91455488+(executable?0:16384);
                const vm_prot_t protections=executable?(VM_PROT_READ|VM_PROT_EXECUTE):(VM_PROT_READ|VM_PROT_WRITE);
                if (segmentIndex!=(executable?4:5) || segment->vmaddr!=preferred ||
                    segment->vmsize!=16384 || segment->fileoff!=fileOffset || segment->filesize!=16384 ||
                    segment->maxprot!=protections || segment->initprot!=protections || segment->nsects!=1) return false;
                const auto *section=reinterpret_cast<const section_64 *>(segment+1);
                if (section->addr!=preferred || section->offset!=fileOffset ||
                    section->size!=(executable?kSIFASMVRXSize:kSIFASMVSidecarSize) || section->align!=4 ||
                    std::strncmp(section->segname,segment->segname,16) ||
                    std::strncmp(section->sectname,executable?"__text":"__data",16) ||
                    section->flags!=(executable?0x80000400u:0u)) return false;
                if (executable) { if(rx)return false; rx=true; }
                else { if(rw)return false; rw=true; }
            } else if (!std::strncmp(segment->segname,"__LINKEDIT",16)) {
                if (segmentIndex!=6 || segment->vmaddr!=kSIFASMVRX+32768 ||
                    segment->fileoff!=91455488+32768) return false;
                linkedit=true;
            }
            segmentIndex++;
        }
        cursor+=command->cmdsize;
    }
    if (cursor!=end || !uuid || !rx || !rw || !linkedit || segmentIndex!=7) return false;
    const auto *rxBytes=reinterpret_cast<const uint8_t *>(kSIFASMVRX+slide);
    const auto *rwBytes=reinterpret_cast<const uint8_t *>(kSIFASMVRW+slide);
    if (std::memcmp(rxBytes,kSIFASMVRXBytes,sizeof(kSIFASMVRXBytes)) ||
        !zero(rxBytes+kSIFASMVRXSize,16384-kSIFASMVRXSize) ||
        std::memcmp(rwBytes,kSIFASMVSidecar,sizeof(kSIFASMVSidecar)) ||
        !zero(rwBytes+kSIFASMVSidecarSize,16384-kSIFASMVSidecarSize)) return false;
    for (size_t i=0;i<kSIFASMVHookCount;i++) {
        const auto &pin=kSIFASMVHooks[i];
        const auto *code=reinterpret_cast<const uint8_t *>(pin.va+slide);
        if (std::memcmp(code,&pin.branch,4) || std::memcmp(code+4,pin.original+4,28)) return false;
    }
    return true;
}

template<class T> T trampoline(size_t index, intptr_t slide) {
    return reinterpret_cast<T>(kSIFASMVRX+index*64+16+slide);
}

void install() {
    intptr_t slide=0;
    if (!verify(slide)) {
        NSLog(@"Elichika MV shims inactive: exact offline patch profile was not verified.");
        return;
    }
    SIFASMVBindingOriginals originals={};
    originals.timeUpdate=trampoline<decltype(originals.timeUpdate)>(0,slide);
    originals.liveUpdate=trampoline<decltype(originals.liveUpdate)>(1,slide);
    originals.musicUpdate=trampoline<decltype(originals.musicUpdate)>(2,slide);
    originals.memberUpdate=trampoline<decltype(originals.memberUpdate)>(3,slide);
    originals.overlayRender=trampoline<decltype(originals.overlayRender)>(4,slide);
    originals.screenWidth=trampoline<decltype(originals.screenWidth)>(5,slide);
    originals.screenHeight=trampoline<decltype(originals.screenHeight)>(6,slide);
    originals.memberLateUpdate=trampoline<decltype(originals.memberLateUpdate)>(7,slide);
    originals.cameraPostRender=trampoline<decltype(originals.cameraPostRender)>(8,slide);
    NSError *error=nil;
    if (!SIFASMVBindingsInstallOriginals(&originals,&error)) {
        NSLog(@"Elichika MV shims inactive: %@",error.localizedDescription);
        return;
    }
    const uintptr_t callbacks[]={reinterpret_cast<uintptr_t>(&SIFASMVTimeUpdate),
        reinterpret_cast<uintptr_t>(&SIFASMVLiveUpdate),reinterpret_cast<uintptr_t>(&SIFASMVMusicUpdate),
        reinterpret_cast<uintptr_t>(&SIFASMVMemberUpdate),reinterpret_cast<uintptr_t>(&SIFASMVOverlayRender),
        reinterpret_cast<uintptr_t>(&SIFASMVScreenWidth),reinterpret_cast<uintptr_t>(&SIFASMVScreenHeight),
        reinterpret_cast<uintptr_t>(&SIFASMVMemberLateUpdate),reinterpret_cast<uintptr_t>(&SIFASMVCameraPostRender)};
    static_assert(sizeof(callbacks)/sizeof(callbacks[0])==kSIFASMVHookCount,"hook contract differs");
    // Only the dedicated RW callback cells are published. Executable pages
    // remain unchanged; null cells always tail into the offline trampoline.
    for (size_t i=0;i<kSIFASMVHookCount;i++)
        __atomic_store_n(reinterpret_cast<uintptr_t *>(kSIFASMVRW+kSIFASMVCallbackOffset+i*8+slide),callbacks[i],__ATOMIC_RELEASE);
}
}

__attribute__((constructor)) static void SIFASMVExportBootstrap() {
    @autoreleasepool {
        @try { install(); }
        @catch (NSException *exception) {
            NSLog(@"Elichika MV bootstrap failed: %@",exception.reason);
        }
    }
}
