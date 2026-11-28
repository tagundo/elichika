#ifndef SIFAS_UNITY_MATERIAL_BACKEND_H
#define SIFAS_UNITY_MATERIAL_BACKEND_H

/* Fixed-build Unity adapter. No symbol discovery or hook installation lives here.
 * Function pointers, raw types and field offsets require the platform audit pins.
 * Every public operation except context_init must run on the original Unity
 * thread, with calls serialized. No runtime code-memory changes are performed.
 */
#include "material_isolation.h"
#include <stddef.h>
#include <stdint.h>

#ifndef MIU_CATCH_CPP_EXCEPTIONS
#define MIU_CATCH_CPP_EXCEPTIONS 1
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    MIU_RENDERER, MIU_MONOBEHAVIOUR, MIU_MATERIAL,
    MIU_AMBIENT, MIU_RIMLIGHT, MIU_BODY_PARTS, MIU_CHEEK,
    MIU_PROP_BASIC, MIU_SPOTLIGHT_AREA, MIU_SPOTLIGHT_SHAFT,
    MIU_TYPE_COUNT
} MiuType;

/* All signatures include the audited trailing non-generic MethodInfo* argument.
 * Backend passes null only for wrappers proven not to consume it. These are
 * compiled managed wrappers, NOT assumed exported IL2CPP API functions.
 */
typedef struct {
    void *(*array_clone)(void *, const void *);
    void *(*type_from_handle)(const void *, const void *);
    uint32_t (*handle_alloc)(void *, const void *);
    void *(*handle_target)(int32_t, const void *);
    void (*handle_free)(int32_t, const void *);
    int32_t (*instance_id)(void *, const void *);
    unsigned char (*object_alive)(void *, const void *);
    void *(*component_game_object)(void *, const void *);
    void *(*component_transform)(void *, const void *);
    void *(*components_in_children)(void *, void *, unsigned char, const void *);
    unsigned char (*is_instance)(void *, void *, const void *);
    unsigned char (*is_child_of)(void *, void *, const void *);
    void *(*shared_materials)(void *, const void *);
    void (*set_shared_materials)(void *, void *, const void *);
    void *(*instantiate)(void *, const void *);
    void (*destroy)(void *, const void *);
    void *(*get_name)(void *, const void *);
    void (*set_name)(void *, void *, const void *);
    const void *raw_types[MIU_TYPE_COUNT];
    /* Android transport invokes through the game's own runtime_invoke and
     * captures its exception-out. It increments this counter monotonically on
     * failure and returns safe zero, never throwing across private runtimes.
     * Direct iOS transport may leave these null when shared-runtime catch is on.
     */
    void *transport_context;
    uint64_t (*transport_failure_generation)(void *);
} MiuApi;

typedef enum {
    MIU_SUCCESS = 0, MIU_BAD_ARGUMENT, MIU_NATIVE_EXCEPTION,
    MIU_INVALID_HANDLE, MIU_NULL_RETURN, MIU_BAD_ARRAY, MIU_BOUND,
    MIU_TYPE_MISMATCH, MIU_INVALID_SLOT, MIU_DEAD_OBJECT,
    MIU_MIXED_OWNERSHIP, MIU_QUARANTINED_HANDLE, MIU_TRANSPORT_EXCEPTION,
    MIU_PENDING_MATERIAL, MIU_UNROOTED_NATIVE_RESOURCE
} MiuCode;
typedef enum {
    MIU_OP_NONE, MIU_OP_ROOT, MIU_OP_TARGET, MIU_OP_UNROOT,
    MIU_OP_TYPE, MIU_OP_IDENTITY, MIU_OP_SLOT_READ, MIU_OP_SLOT_WRITE,
    MIU_OP_ARRAY_READ, MIU_OP_ARRAY_WRITE, MIU_OP_ARRAY_CLONE,
    MIU_OP_MATERIAL_CLONE, MIU_OP_MATERIAL_DESTROY,
    MIU_OP_ENUMERATE, MIU_OP_PROP_EXCLUSION, MIU_OP_EFFECT_EXCLUSION
} MiuOperation;
typedef struct { MiuCode code; MiuOperation operation; size_t index; } MiuError;

#define MIU_MAX_ENUMERATED 4096u
#define MIU_MAX_PROP_ROOTS 32u
#define MIU_MAX_EFFECT_RENDERERS 128u
#define MIU_MAX_EFFECT_MATERIALS 256u
#define MIU_MAX_QUARANTINE 64u
#define MIU_MAX_PENDING_MATERIALS 1u
typedef struct {
    uint64_t owner_id;
    MiRoot root;
    MiObject created_object; /* Diagnostic only if root==0; never dereference. */
} MiuPendingMaterial;

typedef struct {
    MiuApi api;
    MiRoot types[MIU_TYPE_COUNT];
    MiRoot quarantine[MIU_MAX_QUARANTINE];
    size_t quarantine_count;
    uint64_t preserved_material_ids[MIU_MAX_EFFECT_MATERIALS];
    size_t preserved_material_count;
    MiuPendingMaterial pending[MIU_MAX_PENDING_MATERIALS];
    size_t pending_count;
    uint64_t current_owner;
    unsigned int terminal_resource_fault;
    MiuError error;
    unsigned int initialized;
} MiuContext;

/* Fixed bounded caller-owned collection. Slot owner roots are borrowed by core;
 * collect_slots owns them until release_slots. Core retains its own roots if a
 * failed rollback needs to preserve the descriptor after release_slots returns.
 */
typedef struct {
    MiSlot slots[MI_MAX_SLOTS];
    MiRoot roots[MI_MAX_SLOTS];
    size_t count;
} MiuSlots;

int miu_context_init(MiuContext *, const MiuApi *);
MiBackend miu_backend(MiuContext *);
void miu_clear_error(MiuContext *);
MiuError miu_last_error(const MiuContext *);
const char *miu_error_text(MiuCode);

/* Enumerates only root's character components. Mutation fields are the exact
 * four audited non-owning roles: Ambient+20[], Rimlight+30[], BodyParts+48,
 * CheekBase+28. PropBasic subtrees and exact Area/Shaft renderer/material
 * identities are excluded. Their exact Material IDs are supplied to the core's
 * preserve policy, so mixed arrays retain existing game-owned effect references.
 * This is deliberately not a generic arbitrary-field reflection editor.
 */
int miu_collect_slots(MiuContext *, MiObject actor, MiuSlots *);
void miu_release_slots(MiuContext *, MiuSlots *);
MiResult miu_apply_actor(MiuContext *, MiRegistry *, MiObject actor, uint64_t owner_id);
int miu_actor_owner(MiuContext *, const MiRegistry *, MiObject actor, uint64_t *owner_id);
/* Run after the original member-manager Term has stopped users of its mats.
 * This also retries backend-owned partial clones even if core has no record.
 */
int miu_cleanup_pending_owner(MiuContext *, uint64_t owner_id);
MiResult miu_cleanup_owner(MiuContext *, MiRegistry *, uint64_t owner_id);

/* Call only after all registry records using this backend have been cleaned.
 * Returns false if a previously unexpected free failure remains quarantined.
 */
int miu_release_types(MiuContext *);

#ifdef __cplusplus
}
#endif
#endif
