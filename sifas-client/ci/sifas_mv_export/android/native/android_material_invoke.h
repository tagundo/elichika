#ifndef SIFAS_ANDROID_MATERIAL_INVOKE_H
#define SIFAS_ANDROID_MATERIAL_INVOKE_H

#include "unity_material_backend.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum { MAI_GL = 0, MAI_JP = 1 } MaiRegion;
typedef enum {
    MAI_ARRAY_CLONE, MAI_TYPE_FROM_HANDLE, MAI_INSTANCE_ID, MAI_OBJECT_ALIVE,
    MAI_COMPONENT_GAME_OBJECT, MAI_COMPONENT_TRANSFORM, MAI_COMPONENTS_IN_CHILDREN,
    MAI_IS_INSTANCE, MAI_IS_CHILD_OF, MAI_SHARED_MATERIALS, MAI_SET_SHARED_MATERIALS,
    MAI_INSTANTIATE, MAI_DESTROY, MAI_GET_NAME, MAI_SET_NAME, MAI_MEMBER_MANAGER,
    MAI_ACTOR_REFERER,
    MAI_METHOD_COUNT
} MaiMethod;
typedef enum {
    MAI_FAILURE_NONE, MAI_FAILURE_ARGUMENT, MAI_FAILURE_THREAD,
    MAI_FAILURE_CLASS, MAI_FAILURE_METHOD, MAI_FAILURE_SIGNATURE,
    MAI_FAILURE_MANAGED_EXCEPTION, MAI_FAILURE_BOX, MAI_FAILURE_HANDLE
} MaiFailure;

/* These are ORIGINAL SAME-ENGINE exported C APIs at the audited fixed image VAs.
 * No foreign C++ ABI or exception runtime is introduced. All metadata/handle
 * calls require valid audited pointers and an attached original Unity thread.
 * runtime_invoke is the engine's exception-out boundary for managed calls.
 */
typedef struct {
    void *(*runtime_invoke)(const void *, void *, void **, void **);
    void *(*class_from_type)(const void *);
    const void *(*class_get_methods)(void *, void **);
    uint32_t (*method_get_token)(const void *);
    uint32_t (*method_get_param_count)(const void *);
    const void *(*method_get_param)(const void *, uint32_t);
    const void *(*method_get_return_type)(const void *);
    void *(*method_get_class)(const void *);
    uint32_t (*method_get_flags)(const void *, uint32_t *);
    unsigned char (*type_equals)(const void *, const void *);
    void *(*object_get_class)(void *);
    void *(*object_unbox)(void *);
    uint32_t (*gchandle_new)(void *, unsigned char);
    void *(*gchandle_get_target)(uint32_t);
    void (*gchandle_free)(uint32_t);
    unsigned char (*class_is_assignable_from)(void *, void *);
} MaiExports;

typedef struct {
    MaiExports engine;
    uintptr_t image_load_bias;
    const void *build_pins;
    const void *methods[MAI_METHOD_COUNT];
    void *declaring_classes[MAI_METHOD_COUNT];
    uint64_t failure_generation;
    size_t live_handles;
    MaiFailure last_failure;
    MaiMethod last_method;
    unsigned int initialized;
} MaiContext;

/* SOURCE-ONLY transport. Parent binder must validate exact source image/preimages
 * before calling this initializer. It only copies pointers and configures typed
 * thunks: no engine call, MethodInfo resolution, managed allocation or thread
 * attachment occurs in loader context.
 *
 * MiuApi has no context parameter on its typed operations. Therefore exactly one
 * process-lifetime MaiContext can be selected; storage and its MiuApi must remain
 * valid until process/module teardown. Calls are serialized on the already
 * attached original Unity thread. No rebinding or use-after-context-lifetime.
 *
 * Each managed thunk lazily resolves MethodInfo by exact declaring class, token,
 * staticness, parameter count, canonical parameter and return Il2CppType equality.
 * A managed exception or validation failure yields zero and increments the
 * transport's monotonic failure generation. Success never resets that counter.
 * Counter exhaustion at 2^64 failures is outside the supported lifetime.
 */
int mai_context_init(MaiContext *, MaiRegion, uintptr_t image_load_bias, MiuApi *);
uint64_t mai_failure_generation(void *);
/* Same transport for the hook bridge's manager-owner getter. */
void *mai_member_manager(void *director, const void *unused_method_info);
/* Late-face owner fallback when the core has not retained an actor yet. */
void *mai_actor_referer(void *actor, const void *unused_method_info);

#ifdef __cplusplus
}
#endif
#endif
