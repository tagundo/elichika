/* SOURCE ONLY Android integration. Compile together with original-runtime
 * invoke transport, portable C core, and MIU_CATCH_CPP_EXCEPTIONS=0 backend.
 * This file does not catch managed exceptions or depend on a C++ runtime.
 */
#include "material_android_binding.h"
#include "android_material_invoke.h"
#include "unity_material_backend.h"
#include "material_isolation.h"
#include <android/log.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>

namespace {
/* One retained Normal GCHandle per manager, including empty early passes.
 * This is deliberately independent of the material registry: an empty pass
 * has no actor record, and Unity may clear a manager's native pointer before
 * OnDestroy, making GetInstanceID return zero. Transitions may overlap, so the
 * table is bounded rather than a single global current-manager reference.
 */
constexpr size_t manager_capacity=64;
struct ManagerOwner { MiRoot root;uint64_t id;unsigned int release_fault; };
struct RuntimeState {
    MaiContext invoke;
    MiuApi api;
    MiuContext unity;
    MiRegistry registry;
    MiAndroidOriginals originals;
    ManagerOwner managers[manager_capacity];
    pthread_t unity_thread;
    unsigned int thread_bound;
    unsigned int prepared;
};
RuntimeState state{};
pthread_mutex_t thread_guard=PTHREAD_MUTEX_INITIALIZER;

void *allocate_zeroed(void *,size_t bytes) { return calloc(1,bytes); }
void release_memory(void *,void *memory) { free(memory); }

void log_failure(RuntimeState *s,const char *phase,const MiResult *result=nullptr) {
    const MiuError error=miu_last_error(&s->unity);
    __android_log_print(ANDROID_LOG_ERROR,"SIFAS-Material",
        "%s: core=%d stage=%u slot=%zu element=%zu backend=%u operation=%u "
        "index=%zu transport=%u method=%u generation=%llu retained=%u",
        phase,result?static_cast<int>(result->code):0,
        result?static_cast<unsigned>(result->stage):0u,
        result?result->slot:MI_NONE,result?result->element:MI_NONE,
        static_cast<unsigned>(error.code),static_cast<unsigned>(error.operation),
        error.index,static_cast<unsigned>(s->invoke.last_failure),
        static_cast<unsigned>(s->invoke.last_method),
        static_cast<unsigned long long>(s->invoke.failure_generation),
        result?static_cast<unsigned>(result->ownership_retained):0u);
}

bool on_unity_thread(RuntimeState *s,const char *phase) {
    pthread_mutex_lock(&thread_guard);
    const pthread_t current=pthread_self();
    if (!s->thread_bound) { s->unity_thread=current;s->thread_bound=1; }
    const bool same=pthread_equal(s->unity_thread,current)!=0;
    pthread_mutex_unlock(&thread_guard);
    /* A rejected caller may race accepted Unity-thread operations. Never read
     * mutable backend/transport diagnostics on this path. */
    if (!same) __android_log_print(ANDROID_LOG_ERROR,"SIFAS-Material","%s",phase);
    return same;
}

int prepare(void *opaque,const MiAndroidOriginals *originals) {
    auto *s=static_cast<RuntimeState *>(opaque);
    if (!s || !originals || (originals->region!=1 && originals->region!=2)) return 0;
    if (s->prepared) return s->originals.region==originals->region &&
        s->originals.native_load_bias==originals->native_load_bias;
    /* Loader-only: all of these initializers copy POD/function pointers only.
     * No managed Type rooting, MethodInfo discovery, Unity calls or thread attach.
     */
    const MaiRegion region=originals->region==1?MAI_GL:MAI_JP;
    if (!mai_context_init(&s->invoke,region,originals->native_load_bias,&s->api) ||
        !miu_context_init(&s->unity,&s->api)) return 0;
    const MiBackend backend=miu_backend(&s->unity);
    const MiAllocator allocator{nullptr,allocate_zeroed,release_memory};
    if (!mi_registry_init(&s->registry,&backend,&allocator)) return 0;
    s->originals=*originals; /* Never retain prepare's stack-backed descriptor. */
    s->prepared=1;
    return 1;
}

bool cached_manager(RuntimeState *s,void *manager,ManagerOwner **entry) {
    *entry=nullptr;
    if (!manager) return false;
    const MiBackend backend=miu_backend(&s->unity);
    for (auto &candidate:s->managers) {
        if (!candidate.root) continue;
        if (candidate.release_fault) return false;
        MiObject target=0;
        if (!backend.get_target(backend.context,candidate.root,&target) || !target)
            return false; /* A broken root must not permit another owner map. */
        if (target==reinterpret_cast<MiObject>(manager)) {
            *entry=&candidate;return true;
        }
    }
    return true;
}

bool retain_manager(RuntimeState *s,void *manager,uint64_t *id) {
    *id=0;ManagerOwner *existing=nullptr;
    if (!cached_manager(s,manager,&existing)) return false;
    if (existing) { *id=existing->id;return true; }
    ManagerOwner *empty=nullptr;
    for (auto &candidate:s->managers) if (!candidate.root) { empty=&candidate;break; }
    if (!empty) {
        __android_log_print(ANDROID_LOG_ERROR,"SIFAS-Material",
            "material owner cache is full (%zu retained managers); new actor isolation skipped",
            manager_capacity);return false;
    }
    const MiBackend backend=miu_backend(&s->unity);
    MiRoot root=0;MiObject target=0;uint64_t next_id=0;
    if (!backend.root(backend.context,reinterpret_cast<MiObject>(manager),&root) || !root)
        return false;
    bool ok=backend.get_target(backend.context,root,&target) && target &&
        backend.object_identity(backend.context,target,&next_id) && next_id;
    /* Backend identity zero-extends the signed Unity int32 ID. A different
     * rooted managed object may never reuse an active owner key. */
    if (ok) for (const auto &candidate:s->managers)
        if (candidate.root && candidate.id==next_id) {
            __android_log_print(ANDROID_LOG_ERROR,"SIFAS-Material",
                "different managed managers have the same active owner ID %llu; new actor isolation skipped",
                static_cast<unsigned long long>(next_id));
            ok=false;break;
        }
    if (!ok) { backend.unroot(backend.context,root);return false; }
    *empty={root,next_id,0};*id=next_id;return true;
}

bool retained_owner_target(RuntimeState *s,uint64_t owner) {
    const MiBackend backend=miu_backend(&s->unity);
    for (const auto &entry:s->managers) {
        if (!entry.root || entry.id!=owner) continue;
        if (entry.release_fault) return false;
        MiObject target=0;
        return backend.get_target(backend.context,entry.root,&target) && target;
    }
    return false;
}

bool owner_from_referer(RuntimeState *s,void *referer,uint64_t *owner) {
    *owner=0;
    if (!referer) return false;
    const uint64_t before=mai_failure_generation(&s->invoke);
    void *manager=mai_member_manager(referer,nullptr);
    if (mai_failure_generation(&s->invoke)!=before || !manager) return false;
    return retain_manager(s,manager,owner);
}

void early(void *opaque,void *actor,void *referer,void *member_prop) {
    auto *s=static_cast<RuntimeState *>(opaque);(void)member_prop;
    if (!s || !s->prepared || !actor || !on_unity_thread(s,"early hook on wrong thread")) return;
    miu_clear_error(&s->unity);uint64_t owner=0;
    if (!owner_from_referer(s,referer,&owner)) {
        log_failure(s,"cannot resolve early actor member-manager");return;
    }
    const MiResult result=miu_apply_actor(&s->unity,&s->registry,
        reinterpret_cast<MiObject>(actor),owner);
    if (result.code<0) log_failure(s,"early material isolation failed",&result);
}

void pre_reset(void *opaque,void *actor) {
    auto *s=static_cast<RuntimeState *>(opaque);
    if (!s || !s->prepared || !actor || !on_unity_thread(s,"pre-reset hook on wrong thread")) return;
    uint64_t owner=0;miu_clear_error(&s->unity);
    const uint64_t lookup_generation=mai_failure_generation(&s->invoke);
    const int found=miu_actor_owner(&s->unity,&s->registry,
        reinterpret_cast<MiObject>(actor),&owner);
    /* A false return is a genuine core miss only when both error channels
     * stayed clean. Never reinterpret an actor identity/transport failure as
     * authorization to recover via the stored referer. */
    if (miu_last_error(&s->unity).code!=MIU_SUCCESS ||
        mai_failure_generation(&s->invoke)!=lookup_generation) {
        log_failure(s,"late actor identity lookup failed");return;
    }
    if (found && !retained_owner_target(s,owner)) {
        /* Core ownership must never bypass a failed/terminal manager root.
         * A known owner does not authorize referer fallback or cache repair. */
        log_failure(s,"late actor owner has no valid retained member-manager");return;
    }
    if (!found) {
        /* Empty early / clean early failure creates no core material record.
         * Original Init stores ComponentReferer before this late hook (the
         * early hook instead receives its captured original referer argument).
         * Resolve the pinned getter only on lookup miss; dirty retained actor
         * records still go through their original owner and normal core gate.
         */
        const uint64_t before=mai_failure_generation(&s->invoke);
        void *referer=mai_actor_referer(actor,nullptr);
        if (mai_failure_generation(&s->invoke)!=before ||
            !owner_from_referer(s,referer,&owner)) {
            log_failure(s,"cannot resolve late actor member-manager");return;
        }
    }
    const MiResult result=miu_apply_actor(&s->unity,&s->registry,
        reinterpret_cast<MiObject>(actor),owner);
    if (result.code<0) log_failure(s,"pre-reset material isolation failed",&result);
}

uint64_t manager_identity(void *opaque,void *manager) {
    auto *s=static_cast<RuntimeState *>(opaque);uint64_t owner=0;
    if (!s || !s->prepared || !on_unity_thread(s,"manager teardown on wrong thread")) return 0;
    miu_clear_error(&s->unity);
    ManagerOwner *entry=nullptr;
    /* Raw managed-target comparison remains valid after Unity native death;
     * do not call object_alive/GetInstanceID here. A missing cache means no
     * accepted early/late pass was allowed to create owned materials. */
    if (cached_manager(s,manager,&entry) && entry) owner=entry->id;
    if (!owner) log_failure(s,"cannot recover retained material owner before Term");
    return owner;
}

void cleanup_owner(void *opaque,uint64_t owner) {
    auto *s=static_cast<RuntimeState *>(opaque);
    if (!s || !s->prepared || !owner || !on_unity_thread(s,"material cleanup on wrong thread")) return;
    ManagerOwner *entry=nullptr;
    for (auto &candidate:s->managers)
        if (candidate.root && candidate.id==owner) { entry=&candidate;break; }
    if (!entry) { log_failure(s,"missing retained member-manager during cleanup");return; }
    if (entry->release_fault) {
        log_failure(s,"member-manager root release previously quarantined");return;
    }
    miu_clear_error(&s->unity);
    const MiResult result=miu_cleanup_owner(&s->unity,&s->registry,owner);
    if (result.code<0 || result.ownership_retained) {
        log_failure(s,"owned material cleanup retained resources",&result);return;
    }
    /* The transport's valid once-owned Normal GCHandle free is the audited
     * original-engine no-fail C API, not a managed boxed GCHandle.Free thunk.
     * Release only after normal original Term + successful combined cleanup.
     * Unexpected backend unroot faults retain this entry and fail closed. */
    const MiBackend backend=miu_backend(&s->unity);
    backend.unroot(backend.context,entry->root);
    if (miu_last_error(&s->unity).code!=MIU_SUCCESS) {
        /* Backend retained the unexpected fault in quarantine. Keep a terminal
         * descriptor, never retry/free that handle through a second owner. */
        entry->release_fault=1;
        log_failure(s,"retained member-manager root release failed");return;
    }
    *entry={};
    /* Managed Type objects are a bounded process-lifetime cache, not per-scene
     * allocation. Do not release shared type roots while other managers or a
     * pending partial clone may still use this backend/context.
     */
}

void report_helper_error(void *opaque,const char *phase) {
    auto *s=static_cast<RuntimeState *>(opaque);
    /* Binder reports can follow a rejected wrong-thread destroy. Detailed
     * diagnostics are logged by accepted callbacks; this path reads no mutable
     * RuntimeState diagnostics and is safe concurrently with those callbacks. */
    if (s && s->prepared)
        __android_log_print(ANDROID_LOG_ERROR,"SIFAS-Material","%s",phase);
}
} // namespace

extern "C" int mi_android_runtime_try_bind_loaded(void) {
    const MiAndroidRuntimeOps ops{&state,prepare,early,pre_reset,manager_identity,
        cleanup_owner,report_helper_error};
    return mi_android_try_bind_loaded(&ops);
}
