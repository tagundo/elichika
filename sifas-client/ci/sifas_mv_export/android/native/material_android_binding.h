#ifndef SIFAS_MATERIAL_ANDROID_BINDING_H
#define SIFAS_MATERIAL_ANDROID_BINDING_H
#include <stddef.h>
#include <stdint.h>

/* Versioned data-only sidecar. Old SFOVRW22 remains a separate unchanged32B
 * PT_LOAD. Loader thread prepares context/function pointers, then release-stores
 * ready=1; the offline RX leaf bridges acquire-load ready before callbacks.
 * Active callbacks and their containing native library must never be unloaded.
 */
typedef struct {
    char magic[8];
    uint32_t version, size, region, ready;
    uint64_t early_callback, pre_reset_callback, destroy_callback;
    uint64_t reserved[2];
} MiAndroidSidecar;

typedef struct {
    uint32_t region;
    uintptr_t native_load_bias;
    uintptr_t original_culler, original_reset, original_term;
} MiAndroidOriginals;

/* Runtime adapter is authored/linked separately with the portable core and
 * Unity backend. prepare runs on the loader thread and MUST do no Unity calls,
 * managed allocation, type rooting or enumeration. It must COPY originals,
 * whose pointer is valid only during prepare. All RuntimeOps must be noexcept:
 * Android managed errors use original-engine runtime_invoke exception-out,
 * never a foreign C++ catch. Other callbacks run only
 * through original Unity call sites on the attached Unity thread.
 *
 * early associates actor with actual manager identity derived from referer.
 * pre_reset extends that SAME actor registry/map before original color reset.
 * manager_identity recovers the cached owner via a strong managed manager root
 * before original Term, even if Unity already cleared its native pointer.
 * Manager rooting/identity collision checks precede any actor material apply.
 * cleanup_owner runs only after Term returns, releasing that manager root only
 * after combined backend/core cleanup succeeds. All callbacks serialize the
 * registry and honor rollback/idempotence/ownership rules. Failed cleanup
 * retains roots for retry. Rejected-thread diagnostics read no mutable state.
 * The Android integration is compiled -fno-exceptions/-fno-rtti and must not
 * introduce a second private C++ exception runtime.
 */
typedef struct {
    void *context;
    int (*prepare)(void *, const MiAndroidOriginals *);
    void (*early)(void *, void *actor, void *referer, void *member_prop);
    void (*pre_reset)(void *, void *actor);
    uint64_t (*manager_identity)(void *, void *manager);
    void (*cleanup_owner)(void *, uint64_t owner_id);
    void (*report_helper_error)(void *, const char *phase);
} MiAndroidRuntimeOps;

enum {
    MI_ANDROID_WAITING = 0, MI_ANDROID_BOUND = 1, MI_ANDROID_ALREADY_BOUND = 2,
    MI_ANDROID_BAD_OPS = -1, MI_ANDROID_UNSUPPORTED_IMAGE = -2,
    MI_ANDROID_PREPARE_FAILED = -3
};

#ifdef __cplusplus
extern "C" {
#endif
/* Explicit integration point for the existing native settings loader/waiter.
 * This does not start a thread, scan until success, install an executable hook,
 * load a library or call Unity. Default/unintegrated execution remains inert.
 * Caller must retain context and containing native library for process lifetime.
 */
int mi_android_try_bind_loaded(const MiAndroidRuntimeOps *);
#ifdef __cplusplus
}
static_assert(sizeof(MiAndroidSidecar) == 64, "material sidecar ABI");
static_assert(offsetof(MiAndroidSidecar, ready) == 20, "ready ABI");
static_assert(offsetof(MiAndroidSidecar, early_callback) == 24, "callback ABI");
static_assert(offsetof(MiAndroidSidecar, pre_reset_callback) == 32, "callback ABI");
static_assert(offsetof(MiAndroidSidecar, destroy_callback) == 40, "callback ABI");
#endif
#endif
