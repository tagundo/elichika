#ifndef SIFAS_MATERIAL_ISOLATION_H
#define SIFAS_MATERIAL_ISOLATION_H

/* Portable ownership/transaction core. This file declares no Unity/IL2CPP ABI.
 * All calls execute on the validated Unity thread. The caller must serialize
 * access; callbacks must not reenter this registry.
 */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MI_MAX_ACTORS 32u
#define MI_MAX_SLOTS 128u
#define MI_MAX_MATERIALS 256u
#define MI_MAX_ARRAY_ELEMENTS 4096u
#define MI_NONE ((size_t)-1)

typedef uintptr_t MiObject;
typedef uintptr_t MiRoot;

typedef enum { MI_MATERIAL_FIELD = 1, MI_MATERIAL_ARRAY_FIELD = 2,
               MI_RENDERER_ARRAY = 3 } MiSlotKind;
typedef struct {
    MiSlotKind kind;
    MiRoot owner;             /* Borrowed input root; core retains its own root. */
    uintptr_t token;          /* Opaque field offset/id or renderer operation id. */
} MiSlot;
typedef enum { MI_SOURCE_ISOLATE = 0, MI_SOURCE_PRESERVE = 1 } MiMaterialPolicy;

/* Callback contract:
 * - A nonzero root is a strong GC handle, never a raw managed pointer.
 * - read_slot, array_get, and both clone callbacks return an OWNED strong root
 *   atomically, before another managed allocation can invalidate their result.
 * - Null managed values are represented by root 0. get_target(0) returns 0.
 * - Every failing root-producing callback leaves output 0 and cleans any
 *   partial resource it created. clone_material creates a genuinely NEW Unity
 *   Material with all properties copied, including restoring the original name.
 * - same_reference compares managed object identity, not Unity overloaded ==.
 * - write_slot/array_set accept borrowed roots and do not consume them. A failed
 *   write_slot may have changed the slot: core restores the failed slot too.
 * - unroot is noexcept and succeeds for a valid once-owned handle. Native
 *   adapters must contain exceptions before returning to this C code.
 * - destroy_material destroys only the Material, not its root; a false return
 *   means destruction did not happen and can be retried safely.
 * - object_identity is Unity InstanceID/native object identity, never its name.
 * - Slot owners must be live Unity Objects; stage/UI slots must be excluded by
 *   the platform enumerator. Core retains owner roots for rollback safety.
 */
typedef struct {
    void *context;
    int (*root)(void *, MiObject, MiRoot *);
    int (*get_target)(void *, MiRoot, MiObject *);
    void (*unroot)(void *, MiRoot);
    int (*object_identity)(void *, MiObject, uint64_t *);
    int (*same_reference)(void *, MiRoot, MiRoot, int *);
    int (*read_slot)(void *, const MiSlot *, MiRoot *);
    int (*write_slot)(void *, const MiSlot *, MiRoot);
    int (*array_count)(void *, MiRoot, size_t *);
    int (*array_get)(void *, MiRoot, size_t, MiRoot *);
    int (*array_set)(void *, MiRoot, size_t, MiRoot);
    int (*clone_array)(void *, MiRoot, MiRoot *);
    int (*clone_material)(void *, MiRoot, MiRoot *);
    int (*destroy_material)(void *, MiRoot);
    /* Optional: PRESERVE only exact, validated, already game-owned material
     * identities. Never infer from names. Policy must agree for one source ID
     * across all slots and repeated apply phases for that actor. */
    int (*source_policy)(void *, MiObject, uint64_t, MiMaterialPolicy *);
} MiBackend;

typedef struct {
    void *context;
    void *(*allocate_zeroed)(void *, size_t);
    void (*release)(void *, void *);
} MiAllocator;

typedef enum {
    MI_OK = 0, MI_ALREADY_APPLIED = 1, MI_NO_MATERIALS = 2,
    MI_BAD_ARGUMENT = -1, MI_LIMIT = -2, MI_ALLOCATION_FAILED = -3,
    MI_ROOT_FAILED = -4, MI_IDENTITY_FAILED = -5, MI_SLOT_READ_FAILED = -6,
    MI_ARRAY_FAILED = -7, MI_CLONE_FAILED = -8, MI_BACKEND_CONTRACT = -9,
    MI_SLOT_WRITE_FAILED = -10, MI_ROLLBACK_FAILED = -11,
    MI_CLEANUP_FAILED = -12, MI_DIRTY_ACTOR = -13, MI_OWNER_MISMATCH = -14,
    MI_POLICY_CONFLICT = -15, MI_POLICY_FAILED = -16
} MiCode;

typedef enum {
    MI_STAGE_NONE, MI_STAGE_ACTOR, MI_STAGE_SLOT, MI_STAGE_SCAN,
    MI_STAGE_CLONE, MI_STAGE_ARRAY, MI_STAGE_COMMIT, MI_STAGE_ROLLBACK,
    MI_STAGE_CLEANUP
} MiStage;

typedef struct {
    MiCode code;
    MiStage stage;
    size_t slot, element, rollback_slot;
    uint64_t actor_id, owner_id;
    size_t materials;
    int applied;
    int ownership_retained; /* Dirty/failed cleanup kept roots for safe retry. */
} MiResult;

typedef struct {
    MiBackend backend;
    MiAllocator allocator;
    void *records[MI_MAX_ACTORS];
    unsigned int initialized;
    unsigned int busy;
} MiRegistry;

int mi_registry_init(MiRegistry *, const MiBackend *, const MiAllocator *);
/* Actor and all borrowed slot roots must stay rooted throughout this call.
 * owner_id is the actual member-manager Unity identity supplied by the platform,
 * NOT a scene id. This permits overlapping managers within the same scene.
 * Repeated apply for one actor extends its persistent material alias map, so a
 * later-created face can reuse the entry-phase private materials. A failed
 * extension rolls back only that invocation, preserving earlier phases.
 */
MiResult mi_apply(MiRegistry *, MiObject actor, uint64_t owner_id,
                  const MiSlot *, size_t slot_count);

/* Call ONLY from validated actor/member-manager teardown, after rendering/jobs
 * using these Materials have stopped. Destroy is idempotent; failed destruction
 * keeps its strong root and ownership record for a later retry.
 */
MiResult mi_cleanup_actor(MiRegistry *, uint64_t actor_id);
MiResult mi_cleanup_owner(MiRegistry *, uint64_t owner_id);
size_t mi_retained_actor_count(const MiRegistry *);
/* Read-only owner lookup for the late-face hook, which has no referer argument.
 * Returns 1 for a known actor (including retained failed-transaction records),
 * 0 if absent. No callback/allocation; registry access remains serialized. */
int mi_actor_owner(const MiRegistry *, uint64_t actor_id, uint64_t *owner_id);

#ifdef __cplusplus
}
#endif
#endif
