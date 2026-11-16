/* SOURCE ONLY. Offline leaf bridges already exist in the planned ELF. This
 * loader binder writes only its distinct64B RW sidecar, never code pages or
 * old FOV state. Normal compiler frames contain original calls. Android helper
 * operations must contain managed exceptions inside the original engine's
 * runtime_invoke exception-out transport; this file has NO foreign C++ catch
 * and is compiled -fno-exceptions/-fno-rtti. No mprotect, allocation of code, /proc writes or
 * runtime hook installation is used.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "material_android_binding.h"
#include <elf.h>
#include <link.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>

namespace {
using Original = void (*)(void *, const void *);
struct Layout {
    uint32_t region;
    uint64_t sidecar_va;
    uint64_t hook_va[3], bridge_va[3], original_va[3];
    uint32_t hook_word[3], original_first_word[3];
    const unsigned char *bridge_bytes[3];
    size_t bridge_size[3];
};
#include "material_android_layouts.generated.inc"

pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
MiAndroidRuntimeOps runtime_ops{};
MiAndroidOriginals originals{};
MiAndroidSidecar *published_sidecar = nullptr;

void report(const char *phase) noexcept {
    if (runtime_ops.report_helper_error)
        runtime_ops.report_helper_error(runtime_ops.context, phase);
}

void early_callback(void *actor, const void *method, void *referer,
                    void *member_prop) {
    runtime_ops.early(runtime_ops.context, actor, referer, member_prop);
    /* Original exceptions propagate through this plain non-catching frame. */
    reinterpret_cast<Original>(originals.original_culler)(actor, method);
}

void pre_reset_callback(void *actor, const void *method) {
    runtime_ops.pre_reset(runtime_ops.context, actor);
    reinterpret_cast<Original>(originals.original_reset)(actor, method);
}

void destroy_callback(void *manager, const void *method) {
    uint64_t owner = 0;
    owner = runtime_ops.manager_identity(runtime_ops.context, manager);
    reinterpret_cast<Original>(originals.original_term)(manager, method);
    if (!owner) { report("missing material owner identity at teardown"); return; }
    runtime_ops.cleanup_owner(runtime_ops.context, owner);
}

bool add(uintptr_t base, uint64_t offset, uintptr_t *result) {
    if (offset > UINTPTR_MAX || base > UINTPTR_MAX - static_cast<uintptr_t>(offset))
        return false;
    *result = base + static_cast<uintptr_t>(offset);
    return true;
}

bool contains(const dl_phdr_info *info, uint64_t va, size_t bytes,
              uint32_t flags) {
    if (va > UINT64_MAX - bytes) return false;
    for (ElfW(Half) i = 0; i < info->dlpi_phnum; ++i) {
        const auto &p = info->dlpi_phdr[i];
        if (p.p_type == PT_LOAD && p.p_flags == flags && p.p_vaddr <= va &&
            p.p_vaddr <= UINT64_MAX-p.p_filesz && va+bytes <= p.p_vaddr+p.p_filesz)
            return true;
    }
    return false;
}

bool validate_code(const dl_phdr_info *info, const Layout &layout) {
    for (size_t i=0; i<3; ++i) {
        uintptr_t site, bridge, original;
        if (!contains(info,layout.hook_va[i],4,PF_R|PF_X) ||
            !contains(info,layout.bridge_va[i],layout.bridge_size[i],PF_R|PF_X) ||
            !contains(info,layout.original_va[i],4,PF_R|PF_X) ||
            !add(info->dlpi_addr,layout.hook_va[i],&site) ||
            !add(info->dlpi_addr,layout.bridge_va[i],&bridge) ||
            !add(info->dlpi_addr,layout.original_va[i],&original)) return false;
        uint32_t actual_site, actual_original;
        memcpy(&actual_site,reinterpret_cast<const void *>(site),4);
        memcpy(&actual_original,reinterpret_cast<const void *>(original),4);
        if (actual_site != layout.hook_word[i] ||
            actual_original != layout.original_first_word[i] ||
            memcmp(reinterpret_cast<const void *>(bridge),layout.bridge_bytes[i],
                   layout.bridge_size[i])) return false;
    }
    return true;
}

struct Attempt { const MiAndroidRuntimeOps *ops; int result; };
int find_material_sidecar(dl_phdr_info *info, size_t, void *opaque) {
    auto &attempt=*static_cast<Attempt *>(opaque);
    const char *name=info->dlpi_name ? strrchr(info->dlpi_name,'/') : nullptr;
    name=name ? name+1 : info->dlpi_name;
    if (!name || strcmp(name,"libil2cpp.so")) return 0;
    attempt.result=MI_ANDROID_UNSUPPORTED_IMAGE;
    if (!info->dlpi_phdr || info->dlpi_phnum != 12) return 1;
    for (const auto &layout : layouts) {
        for (ElfW(Half) i=0; i<info->dlpi_phnum; ++i) {
            const auto &p=info->dlpi_phdr[i];
            if (p.p_type != PT_LOAD || p.p_flags != (PF_R|PF_W) ||
                p.p_vaddr != layout.sidecar_va || p.p_filesz != 64 ||
                p.p_memsz != 64 || p.p_align != 65536 ||
                p.p_offset%16384 != p.p_vaddr%16384) continue;
            uintptr_t address;
            if (!add(info->dlpi_addr,p.p_vaddr,&address)) return 1;
            auto *config=reinterpret_cast<MiAndroidSidecar *>(address);
            if (memcmp(config->magic,"SMATRW01",8) || config->version != 1 ||
                config->size != 64 || config->region != layout.region ||
                config->reserved[0] || config->reserved[1] ||
                !validate_code(info,layout)) return 1;
            if (__atomic_load_n(&config->ready,__ATOMIC_ACQUIRE)) {
                attempt.result=(published_sidecar == config) ?
                    MI_ANDROID_ALREADY_BOUND : MI_ANDROID_UNSUPPORTED_IMAGE;
                return 1; /* Never replace active callbacks/context. */
            }
            if (config->early_callback || config->pre_reset_callback ||
                config->destroy_callback) return 1;
            MiAndroidOriginals next{};
            next.region=layout.region;next.native_load_bias=info->dlpi_addr;
            if (!add(info->dlpi_addr,layout.original_va[0],&next.original_culler)||
                !add(info->dlpi_addr,layout.original_va[1],&next.original_reset)||
                !add(info->dlpi_addr,layout.original_va[2],&next.original_term)) return 1;
            if (!attempt.ops->prepare(attempt.ops->context,&next)) {
                attempt.result=MI_ANDROID_PREPARE_FAILED;return 1;
            }
            originals=next;runtime_ops=*attempt.ops;published_sidecar=config;
            /* No Unity API calls above. Complete data/ops publication precedes
             * ready's release store, paired with every RX bridge's LDAR. */
            config->early_callback=reinterpret_cast<uintptr_t>(&early_callback);
            config->pre_reset_callback=reinterpret_cast<uintptr_t>(&pre_reset_callback);
            config->destroy_callback=reinterpret_cast<uintptr_t>(&destroy_callback);
            __atomic_store_n(&config->ready,1u,__ATOMIC_RELEASE);
            attempt.result=MI_ANDROID_BOUND;return 1;
        }
    }
    return 1;
}
} // namespace

extern "C" int mi_android_try_bind_loaded(const MiAndroidRuntimeOps *ops) {
    if (!ops || !ops->prepare || !ops->early || !ops->pre_reset ||
        !ops->manager_identity || !ops->cleanup_owner) return MI_ANDROID_BAD_OPS;
    pthread_mutex_lock(&guard);
    Attempt attempt{ops,MI_ANDROID_WAITING};
    dl_iterate_phdr(find_material_sidecar,&attempt);
    pthread_mutex_unlock(&guard);
    return attempt.result;
}
