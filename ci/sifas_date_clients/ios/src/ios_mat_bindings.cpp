#include "ios_generated_bindings.h"
#include "ios_mat_dispatch.h"

extern "C" const void *_dyld_get_image_header(unsigned int);
extern "C" intptr_t _dyld_get_image_vmaddr_slide(unsigned int);
extern "C" void sifas_material_log(const char *);

namespace {
struct Header { uint32_t magic,cpu,subtype,kind,ncmds,cmdbytes,flags,reserved; };
struct Command { uint32_t kind,bytes; };
struct Segment {
    uint32_t kind,bytes; char name[16]; uint64_t va,memory,fileoff,filesize;
    int32_t maxprot,initprot; uint32_t sections,flags;
};
struct Section {
    char name[16],segment[16]; uint64_t va,bytes;
    uint32_t fileoff,alignment,reloc,relocs,flags,r1,r2,r3;
};
struct Sidecar {
    uint64_t magic; uint32_t version,bytes;
    uintptr_t early,late,destroy; uint32_t region,ready;
    uint64_t base; unsigned char contract_sha[32];
    uint64_t culler,reset,term,owner_getter,reserved;
};
static_assert(sizeof(Segment)==72 && sizeof(Section)==80,"Mach-O arm64 layout");
static_assert(sizeof(Sidecar)==128,"Source plan sidecar layout");
static_assert(__builtin_offsetof(Sidecar,early)==16 && __builtin_offsetof(Sidecar,late)==24 &&
              __builtin_offsetof(Sidecar,destroy)==32 && __builtin_offsetof(Sidecar,ready)==44,"Shim publication offsets");
MiuContext context={}; MiRegistry registry={}; SifasMatDispatch dispatch={};

bool equal_name(const char field[16],const char *name) {
    for (unsigned int i=0;i<16;++i) { if (field[i]!=name[i]) return false; if (!field[i]) return true; }
    return false;
}
Sidecar *find_sidecar(const Header *header,intptr_t slide) {
    if (!header || header->magic!=0xfeedfacf || header->cpu!=0x100000c ||
        header->ncmds>128 || header->cmdbytes>65536) return nullptr;
    const unsigned char *cursor=reinterpret_cast<const unsigned char *>(header+1);
    const unsigned char *end=cursor+header->cmdbytes; Sidecar *found=nullptr;
    for (uint32_t i=0;i<header->ncmds;++i) {
        if (static_cast<size_t>(end-cursor)<sizeof(Command)) return nullptr;
        const Command *command=reinterpret_cast<const Command *>(cursor);
        if (command->bytes<8 || command->bytes>static_cast<size_t>(end-cursor)) return nullptr;
        if (command->kind==0x19 && command->bytes>=sizeof(Segment)) {
            const Segment *segment=reinterpret_cast<const Segment *>(cursor);
            if (equal_name(segment->name,"__SIFASMAT")) {
                if (found || segment->sections!=1 || command->bytes!=152 || segment->maxprot!=3 || segment->initprot!=3) return nullptr;
                const Section *section=reinterpret_cast<const Section *>(segment+1);
                if (!equal_name(section->name,"__sifas_mat") || !equal_name(section->segment,"__SIFASMAT") ||
                    section->bytes!=sizeof(Sidecar) || section->va!=segment->va || section->fileoff!=segment->fileoff ||
                    segment->filesize!=0x4000 || segment->memory!=0x4000) return nullptr;
                found=reinterpret_cast<Sidecar *>(sifas_mat_address(section->va,slide));
            }
        }
        cursor+=command->bytes;
    }
    return cursor==end ? found : nullptr;
}
}

extern "C" __attribute__((visibility("hidden"))) void sifas_mat_early(void *actor,void *referer,void *props) {
    sifas_mat_dispatch_early(&dispatch,actor,referer,props);
}
extern "C" __attribute__((visibility("hidden"))) void sifas_mat_late(void *actor) {
    sifas_mat_dispatch_late(&dispatch,actor);
}
extern "C" __attribute__((visibility("hidden"))) void sifas_mat_destroy(void *manager) {
    sifas_mat_dispatch_destroy(&dispatch,manager);
}

__attribute__((constructor)) static void sifas_mat_publish() {
    /* Only structural validation, pointer binding and C-state initialization.
     * No managed/Unity operation or material scan executes at library load. */
    const Header *header=static_cast<const Header *>(_dyld_get_image_header(0));
    const intptr_t slide=_dyld_get_image_vmaddr_slide(0);
    Sidecar *sidecar=find_sidecar(header,slide);
    if (!sidecar) return; /* The same library may be inspected with an old IPA. */
    if (sidecar->magic!=0x53494641534d4154ULL || sidecar->version!=1 || sidecar->bytes!=128 ||
        sidecar->base!=0x100000000ULL || sidecar->ready || sidecar->early || sidecar->late || sidecar->destroy) {
        sifas_material_log("binding refused: unexpected or already-published sidecar header"); return;
    }
    for (size_t i=0;i<32;++i) if (sidecar->contract_sha[i]!=sifas_mat_contract_sha[i]) {
        sifas_material_log("binding refused: native wrapper contract fingerprint differs"); return;
    }
    MiuApi api={}; SifasMatPreferred preferred={};
    if (!sifas_mat_fill(sidecar->region,slide,&api,&preferred) || sidecar->culler!=preferred.culler ||
        sidecar->reset!=preferred.reset || sidecar->term!=preferred.term || sidecar->owner_getter!=preferred.owner_getter) {
        sifas_material_log("binding refused: region or original method addresses differ"); return;
    }
    if (!miu_context_init(&context,&api)) { sifas_material_log("binding refused: invalid Unity adapter table"); return; }
    const MiBackend backend=miu_backend(&context);
    if (!mi_registry_init(&registry,&backend,nullptr)) { sifas_material_log("binding refused: invalid material transaction backend"); return; }
    dispatch.context=&context; dispatch.registry=&registry; dispatch.log=sifas_material_log;
    dispatch.original_culler=reinterpret_cast<decltype(dispatch.original_culler)>(sifas_mat_address(preferred.culler,slide));
    dispatch.original_reset=reinterpret_cast<decltype(dispatch.original_reset)>(sifas_mat_address(preferred.reset,slide));
    dispatch.original_term=reinterpret_cast<decltype(dispatch.original_term)>(sifas_mat_address(preferred.term,slide));
    dispatch.member_manager=reinterpret_cast<decltype(dispatch.member_manager)>(sifas_mat_address(preferred.owner_getter,slide));
    dispatch.actor_referer=reinterpret_cast<decltype(dispatch.actor_referer)>(sifas_mat_address(preferred.actor_referer,slide));
    dispatch.director_raw_type=reinterpret_cast<const void *>(sifas_mat_address(preferred.director_type,slide));
    sidecar->early=reinterpret_cast<uintptr_t>(&sifas_mat_early);
    sidecar->late=reinterpret_cast<uintptr_t>(&sifas_mat_late);
    sidecar->destroy=reinterpret_cast<uintptr_t>(&sifas_mat_destroy);
    /* All three pointers and complete backend state precede ready publication.
     * The native leaf shims acquire-load this exact ready field before a call. */
    __atomic_store_n(&sidecar->ready,1u,__ATOMIC_RELEASE);
    sifas_material_log("bindings ready: member init, late-face extension and manager cleanup; no per-frame material scan");
}
