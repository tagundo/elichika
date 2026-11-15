#ifndef SIFAS_IOS_MAT_DISPATCH_H
#define SIFAS_IOS_MAT_DISPATCH_H

#include "unity_material_backend.h"
extern "C" int snprintf(char *, size_t, const char *, ...) noexcept;

/* No UIKit timer or background entry: all three paths run synchronously from
 * the original Unity member initialization/member-manager destruction calls. */
struct SifasMatOwnerCounters {
    uint64_t owner;
    MiRoot manager_root;
    size_t early, late, failures;
};
struct SifasMatDispatch {
    MiuContext *context;
    MiRegistry *registry;
    void (*original_culler)(void *, const void *);
    void (*original_reset)(void *, const void *);
    void (*original_term)(void *, const void *);
    void *(*member_manager)(void *, const void *);
    void *(*actor_referer)(void *, const void *);
    const void *director_raw_type;
    MiRoot director_type_root;
    void (*log)(const char *);
    SifasMatOwnerCounters owners[MI_MAX_ACTORS];
};

static inline SifasMatOwnerCounters *sifas_mat_owner_counter(SifasMatDispatch *d, uint64_t owner, bool create) {
    SifasMatOwnerCounters *empty = nullptr;
    for (size_t i=0; i<MI_MAX_ACTORS; ++i) {
        if (d->owners[i].owner == owner && owner) return &d->owners[i];
        if (!d->owners[i].owner && !empty) empty = &d->owners[i];
    }
    if (create && empty) { empty->owner=owner; return empty; }
    return nullptr;
}
static inline void sifas_mat_report(SifasMatDispatch *d, const char *phase, const char *reason,
                                    uint64_t owner, const MiResult *result) noexcept {
    if (!d || !d->log) return;
    const MiuError error=miu_last_error(d->context);
    char text[448];
    snprintf(text,sizeof(text),"%s: %s; owner=%llu core=%d stage=%d slot=%zu element=%zu rollback=%zu backend=%d operation=%d index=%zu (%s) retained_actors=%zu",
             phase,reason,static_cast<unsigned long long>(owner),result ? static_cast<int>(result->code) : 0,
             result ? static_cast<int>(result->stage) : 0,result ? result->slot : MI_NONE,
             result ? result->element : MI_NONE,result ? result->rollback_slot : MI_NONE,
             static_cast<int>(error.code),static_cast<int>(error.operation),error.index,
             miu_error_text(error.code),mi_retained_actor_count(d->registry));
    try { d->log(text); } catch (...) { /* Diagnostics must not alter game flow. */ }
}
static inline bool sifas_mat_manager_id(SifasMatDispatch *d, void *manager, uint64_t *owner) noexcept {
    if (!d || !manager || !owner) return false;
    *owner=0;
    try {
        if (!d->context->api.object_alive(manager,nullptr)) return false;
        const int32_t id=d->context->api.instance_id(manager,nullptr);
        if (!id) return false;
        *owner=static_cast<uint32_t>(id); return true;
    } catch (...) { return false; }
}
static inline uint64_t sifas_mat_transport_generation(SifasMatDispatch *d) {
    return d->context->api.transport_failure_generation ?
        d->context->api.transport_failure_generation(d->context->api.transport_context) : 0;
}
static inline bool sifas_mat_adapter_usable(const SifasMatDispatch *d) noexcept {
    return d && d->context && d->context->initialized==1 &&
        !d->context->terminal_resource_fault && !d->context->quarantine_count;
}
static inline bool sifas_mat_cached_owner_valid(SifasMatDispatch *d, uint64_t owner) noexcept {
    if (!sifas_mat_adapter_usable(d)) return false;
    SifasMatOwnerCounters *counter=sifas_mat_owner_counter(d,owner,false);
    if (!counter || !counter->manager_root) return false;
    try {
        const MiBackend transport=miu_backend(d->context);
        MiObject manager=0;
        if (!transport.get_target(transport.context,counter->manager_root,&manager) || !manager) return false;
        /* This strong root was established only from the validated director's
         * pinned manager getter. A resolved live target must still have the
         * original owner ID; never substitute a different referer on failure. */
        uint64_t actual_owner=0;
        return sifas_mat_manager_id(d,reinterpret_cast<void *>(manager),&actual_owner) && actual_owner==owner;
    } catch (...) { return false; }
}
static inline bool sifas_mat_find_owner(SifasMatDispatch *d, void *referer, uint64_t *owner) noexcept {
    if (!sifas_mat_adapter_usable(d) || !referer || !owner) return false;
    try {
        const MiBackend transport=miu_backend(d->context);
        if (!d->director_type_root) {
            void *type=d->context->api.type_from_handle(d->director_raw_type,nullptr);
            if (!type) return false;
            if (!transport.root(transport.context,reinterpret_cast<MiObject>(type),&d->director_type_root) || !d->director_type_root) return false;
        }
        MiObject type_value=0;
        if (!transport.get_target(transport.context,d->director_type_root,&type_value)) return false;
        void *type=reinterpret_cast<void *>(type_value);
        if (!type || !d->context->api.is_instance(type,referer,nullptr)) return false;
        void *manager=d->member_manager(referer,nullptr);
        if (!sifas_mat_manager_id(d,manager,owner)) return false;
        SifasMatOwnerCounters *counter=sifas_mat_owner_counter(d,*owner,true);
        if (!counter) return false;
        if (counter->manager_root) {
            MiObject existing=0;
            return transport.get_target(transport.context,counter->manager_root,&existing) && existing==reinterpret_cast<MiObject>(manager);
        }
        if (!transport.root(transport.context,reinterpret_cast<MiObject>(manager),&counter->manager_root) || !counter->manager_root) {
            if (!counter->early && !counter->late && !counter->failures) *counter={};
            return false;
        }
        return true;
    } catch (...) { return false; }
}
static inline void sifas_mat_apply_caught(SifasMatDispatch *d, void *actor, void *referer, bool late) noexcept {
    uint64_t owner=0;
    try {
        miu_clear_error(d->context);
        const uint64_t generation=sifas_mat_transport_generation(d);
        bool found=false;
        if (late) {
            found=miu_actor_owner(d->context,d->registry,reinterpret_cast<MiObject>(actor),&owner);
            if (miu_last_error(d->context).code!=MIU_SUCCESS || generation!=sifas_mat_transport_generation(d)) {
                sifas_mat_report(d,"late","actor owner lookup failed; retained ownership is not replaced",owner,nullptr);
                return;
            }
            if (found && !sifas_mat_cached_owner_valid(d,owner)) {
                sifas_mat_report(d,"late","cached member-manager root is unavailable, native-dead, mismatched, or adapter disabled; retained ownership is not replaced",owner,nullptr);
                return;
            }
            /* Original Initialize assigned this property before the pre-reset
             * call. Use the pinned getter only when early had no retained
             * record (zero materials or a fully rolled-back clean failure),
             * and the lookup completed without an identity/transport error. */
            if (!found && d->actor_referer)
                found=sifas_mat_find_owner(d,d->actor_referer(actor,nullptr),&owner);
        } else found=sifas_mat_find_owner(d,referer,&owner);
        if (!found) {
            sifas_mat_report(d,late ? "late" : "early","referer is not a live validated member-manager owner",owner,nullptr);
            return;
        }
        if (miu_last_error(d->context).code!=MIU_SUCCESS || generation!=sifas_mat_transport_generation(d)) {
            sifas_mat_report(d,late ? "late" : "early","member-manager validation failed in native transport; material work skipped",owner,nullptr);
            return;
        }
        SifasMatOwnerCounters *counter=sifas_mat_owner_counter(d,owner,true);
        if (counter) { if (late) ++counter->late; else ++counter->early; }
        const MiResult result=miu_apply_actor(d->context,d->registry,reinterpret_cast<MiObject>(actor),owner);
        if (result.code<0) {
            if (counter) ++counter->failures;
            sifas_mat_report(d,late ? "late" : "early","material transaction failed; original game initialization continues",owner,&result);
        }
    } catch (...) {
        SifasMatOwnerCounters *counter=sifas_mat_owner_counter(d,owner,false);
        if (counter) ++counter->failures;
        sifas_mat_report(d,late ? "late" : "early","native exception contained in material adapter",owner,nullptr);
    }
}

/* These wrappers deliberately are NOT noexcept: exceptions from the original
 * game methods retain the original callsite behavior. Only mod work is caught. */
static inline void sifas_mat_dispatch_early(SifasMatDispatch *d, void *actor, void *referer, void *member_props) {
    (void)member_props; /* Existing prop-specific ownership remains game-managed. */
    sifas_mat_apply_caught(d,actor,referer,false);
    d->original_culler(actor,nullptr); /* Original MethodInfo is pinned NULL. */
}
static inline void sifas_mat_dispatch_late(SifasMatDispatch *d, void *actor) {
    sifas_mat_apply_caught(d,actor,nullptr,true);
    d->original_reset(actor,nullptr); /* Original MethodInfo is pinned NULL. */
}
static inline void sifas_mat_cleanup_caught(SifasMatDispatch *d, uint64_t owner) noexcept {
    if (!owner) return;
    try {
        miu_clear_error(d->context);
        /* Combined adapter cleanup also releases a rooted partial clone whose
         * copy succeeded but name restoration and first Destroy both failed. */
        const MiResult result=miu_cleanup_owner(d->context,d->registry,owner);
        SifasMatOwnerCounters *counter=sifas_mat_owner_counter(d,owner,false);
        if (result.code<0) {
            sifas_mat_report(d,"destroy","owned material cleanup failed; ownership retained for safety",owner,&result);
        } else {
            /* unroot consumes this once-owned handle; a transport failure moves
             * it into the backend quarantine instead of losing its ownership. */
            if (counter && counter->manager_root) {
                const MiBackend transport=miu_backend(d->context);
                const MiRoot root=counter->manager_root;counter->manager_root=0;
                transport.unroot(transport.context,root);
                if (miu_last_error(d->context).code!=MIU_SUCCESS) {
                    sifas_mat_report(d,"destroy","materials cleaned; manager root release is retained in adapter quarantine",owner,&result);
                    *counter={};return;
                }
            }
            char text[224];
            snprintf(text,sizeof(text),"manager cleanup owner=%llu early=%zu late=%zu failures=%zu retained_actors=%zu",
                     static_cast<unsigned long long>(owner),counter ? counter->early : 0,
                     counter ? counter->late : 0,counter ? counter->failures : 0,
                     mi_retained_actor_count(d->registry));
            if (d->log) d->log(text);
            if (counter) *counter={};
        }
    } catch (...) { sifas_mat_report(d,"destroy","native exception contained during owned material cleanup",owner,nullptr); }
}
static inline void sifas_mat_dispatch_destroy(SifasMatDispatch *d, void *manager) {
    uint64_t owner=0;
    /* Unity may have cleared the native pointer before this managed callback.
     * Match the strongly rooted managed reference; do not use Unity ==/alive or
     * re-read GetInstanceID during destruction. No cached owner means this mod
     * never established ownership or created clones for that manager. */
    try {
        const MiBackend transport=miu_backend(d->context);
        for (size_t i=0;i<MI_MAX_ACTORS;++i) if (d->owners[i].manager_root) {
            MiObject stored=0;
            if (transport.get_target(transport.context,d->owners[i].manager_root,&stored) && stored==reinterpret_cast<MiObject>(manager)) {
                owner=d->owners[i].owner;break;
            }
        }
    } catch (...) { sifas_mat_report(d,"destroy","could not read cached member-manager strong identity",0,nullptr); }
    /* Only a successful Term proves native job/buffer use has stopped. An
     * original exception propagates with roots/materials retained; destroying
     * them during incomplete job teardown would risk use-after-free. */
    d->original_term(manager,nullptr);
    sifas_mat_cleanup_caught(d,owner);
}
#endif
