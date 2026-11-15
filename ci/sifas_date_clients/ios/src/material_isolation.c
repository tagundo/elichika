#include "material_isolation.h"
#include <stdlib.h>
#include <string.h>

#define MI_MAGIC 0x4d49434fu

typedef struct {
    uint64_t source_id, private_id;
    MiRoot source, private_material;
    MiMaterialPolicy policy;
    int owned, destroyed;
} Material;
typedef struct {
    MiRoot old_value;             /* Borrowed from a retained slot. */
    MiRoot new_value;             /* Owned only when changed. */
    size_t count, input_slot;
    int changed;
} Array;
typedef struct {
    MiSlot descriptor;
    uint64_t owner_id;
    MiRoot old_value, new_value;   /* new_value is borrowed from Material/Array. */
    size_t input_slot, material_index, array_index;
    int changed, attempted;
} Slot;
typedef struct {
    uint64_t actor_id, owner_id;
    MiRoot actor;
    size_t material_count, phase_base, slot_count, array_count;
    int dirty;
    Material materials[MI_MAX_MATERIALS];
    Slot slots[MI_MAX_SLOTS];
    Array arrays[MI_MAX_SLOTS];
} Record;

static void *default_allocate(void *unused, size_t size) {
    (void)unused;
    return calloc(1, size);
}
static void default_release(void *unused, void *pointer) {
    (void)unused;
    free(pointer);
}
static MiResult result(MiCode code, MiStage stage) {
    MiResult out;
    memset(&out, 0, sizeof(out));
    out.code = code;
    out.stage = stage;
    out.slot = out.element = out.rollback_slot = MI_NONE;
    return out;
}
static void release_root(MiRegistry *registry, MiRoot *root) {
    if (*root) {
        registry->backend.unroot(registry->backend.context, *root);
        *root = 0;
    }
}
static int retain_root(MiRegistry *registry, MiRoot input, MiRoot *output) {
    MiObject object = 0;
    MiBackend *b = &registry->backend;
    *output = 0;
    return b->get_target(b->context, input, &object) && object &&
           b->root(b->context, object, output) && *output;
}
static int identity(MiRegistry *registry, MiRoot root, uint64_t *id) {
    MiObject object = 0;
    MiBackend *b = &registry->backend;
    *id = 0;
    return b->get_target(b->context, root, &object) && object &&
           b->object_identity(b->context, object, id) && *id;
}
static size_t find_source(const Record *record, uint64_t id) {
    size_t i;
    for (i = 0; i < record->material_count; ++i)
        if (record->materials[i].source_id == id) return i;
    return MI_NONE;
}
static size_t find_private(const Record *record, uint64_t id) {
    size_t i;
    for (i = 0; i < record->material_count; ++i)
        if (record->materials[i].private_id == id &&
            record->materials[i].private_material) return i;
    return MI_NONE;
}

/* Takes an owned temporary root. Its ownership is transferred only for a new
 * source; otherwise the temporary is released on all exits. */
static MiCode collect_material(MiRegistry *registry, Record *record,
                               MiRoot *temporary, size_t *index, int *changed) {
    uint64_t id;
    size_t found;
    MiMaterialPolicy policy = MI_SOURCE_ISOLATE;
    *index = MI_NONE;
    *changed = 0;
    if (!*temporary) return MI_OK;
    if (!identity(registry, *temporary, &id)) {
        release_root(registry, temporary);
        return MI_IDENTITY_FAILED;
    }
    if (registry->backend.source_policy) {
        MiObject object = 0;
        if (!registry->backend.get_target(registry->backend.context,
                                          *temporary, &object) || !object ||
            !registry->backend.source_policy(registry->backend.context,
                                             object, id, &policy)) {
            release_root(registry, temporary);
            return MI_POLICY_FAILED;
        }
        if (policy != MI_SOURCE_ISOLATE && policy != MI_SOURCE_PRESERVE) {
            release_root(registry, temporary);
            return MI_BACKEND_CONTRACT;
        }
    }
    found = find_private(record, id);
    if (found != MI_NONE) {
        if (policy != MI_SOURCE_ISOLATE) {
            release_root(registry, temporary);
            return MI_POLICY_CONFLICT;
        }
        *index = found;
        release_root(registry, temporary);
        return MI_OK;
    }
    found = find_source(record, id);
    if (found != MI_NONE && record->materials[found].policy != policy) {
        release_root(registry, temporary);
        return MI_POLICY_CONFLICT;
    }
    if (found == MI_NONE) {
        Material *material;
        if (record->material_count == MI_MAX_MATERIALS) {
            release_root(registry, temporary);
            return MI_LIMIT;
        }
        found = record->material_count++;
        material = &record->materials[found];
        memset(material, 0, sizeof(*material));
        material->source_id = id;
        material->policy = policy;
        material->source = *temporary;
        *temporary = 0;
    } else release_root(registry, temporary);
    *index = found;
    *changed = policy == MI_SOURCE_ISOLATE;
    return MI_OK;
}

static void release_phase_roots(MiRegistry *registry, Record *record) {
    size_t i;
    for (i = 0; i < record->array_count; ++i)
        if (record->arrays[i].changed)
            release_root(registry, &record->arrays[i].new_value);
    for (i = 0; i < record->slot_count; ++i) {
        release_root(registry, &record->slots[i].old_value);
        release_root(registry, &record->slots[i].descriptor.owner);
    }
    for (i = 0; i < record->material_count; ++i)
        release_root(registry, &record->materials[i].source);
    memset(record->slots, 0, sizeof(record->slots));
    memset(record->arrays, 0, sizeof(record->arrays));
    record->slot_count = record->array_count = 0;
}

/* Failed destroys keep their private strong root; successful ones are cleared
 * before any retry can see them. Source materials are never passed here. */
static int destroy_range(MiRegistry *registry, Record *record, size_t first) {
    size_t i;
    int ok = 1;
    MiBackend *b = &registry->backend;
    for (i = first; i < record->material_count; ++i) {
        Material *material = &record->materials[i];
        if (!material->private_material) continue;
        if (material->owned && !material->destroyed) {
            if (!b->destroy_material(b->context, material->private_material)) {
                ok = 0;
                continue;
            }
            material->destroyed = 1;
        }
        release_root(registry, &material->private_material);
    }
    return ok;
}
static size_t record_position(const MiRegistry *registry, const Record *record) {
    size_t i;
    for (i = 0; i < MI_MAX_ACTORS; ++i)
        if (registry->records[i] == record) return i;
    return MI_NONE;
}
static size_t free_position(const MiRegistry *registry) {
    size_t i;
    for (i = 0; i < MI_MAX_ACTORS; ++i)
        if (!registry->records[i]) return i;
    return MI_NONE;
}
static void forget_record(MiRegistry *registry, Record *record) {
    size_t position = record_position(registry, record);
    if (position != MI_NONE) registry->records[position] = 0;
    release_phase_roots(registry, record);
    release_root(registry, &record->actor);
    registry->allocator.release(registry->allocator.context, record);
}
static void retain_record(MiRegistry *registry, Record *record) {
    if (record_position(registry, record) == MI_NONE) {
        size_t position = free_position(registry);
        /* A free position was reserved logically before the first allocation;
         * registry access is serialized and callbacks cannot reenter. */
        if (position != MI_NONE) registry->records[position] = record;
    }
}
static size_t material_roots(const Record *record) {
    size_t i, count = 0;
    for (i = 0; i < record->material_count; ++i)
        if (record->materials[i].private_material) ++count;
    return count;
}

int mi_registry_init(MiRegistry *registry, const MiBackend *backend,
                     const MiAllocator *allocator) {
    if (!registry || !backend || !backend->root || !backend->get_target ||
        !backend->unroot || !backend->object_identity || !backend->same_reference ||
        !backend->read_slot || !backend->write_slot || !backend->array_count ||
        !backend->array_get || !backend->array_set || !backend->clone_array ||
        !backend->clone_material || !backend->destroy_material) return 0;
    if (allocator && (!allocator->allocate_zeroed || !allocator->release)) return 0;
    memset(registry, 0, sizeof(*registry));
    registry->backend = *backend;
    if (allocator) registry->allocator = *allocator;
    else {
        registry->allocator.allocate_zeroed = default_allocate;
        registry->allocator.release = default_release;
    }
    registry->initialized = MI_MAGIC;
    return 1;
}

MiResult mi_apply(MiRegistry *registry, MiObject actor, uint64_t owner_id,
                  const MiSlot *input, size_t count) {
    MiResult out = result(MI_BAD_ARGUMENT, MI_STAGE_NONE);
    Record *record = 0;
    MiBackend *b;
    MiRoot actor_root = 0;
    uint64_t actor_id = 0;
    size_t i, j, elements = 0;
    int existing = 0, any_changed = 0;
    if (!registry || registry->initialized != MI_MAGIC || registry->busy ||
        !actor || !owner_id || (count && !input)) return out;
    if (count > MI_MAX_SLOTS) return result(MI_LIMIT, MI_STAGE_SLOT);
    registry->busy = 1;
    b = &registry->backend;
    out.owner_id = owner_id;
    out.stage = MI_STAGE_ACTOR;
    if (!b->root(b->context, actor, &actor_root) || !actor_root) {
        out.code = MI_ROOT_FAILED;
        goto done;
    }
    if (!identity(registry, actor_root, &actor_id)) {
        out.code = MI_IDENTITY_FAILED;
        goto done;
    }
    out.actor_id = actor_id;
    for (i = 0; i < MI_MAX_ACTORS; ++i) {
        Record *candidate = (Record *)registry->records[i];
        if (candidate && candidate->actor_id == actor_id) {
            record = candidate;
            existing = 1;
            break;
        }
    }
    if (existing) {
        release_root(registry, &actor_root);
        if (record->owner_id != owner_id) {
            out.code = MI_OWNER_MISMATCH;
            goto done;
        }
        if (record->dirty) {
            out.code = MI_DIRTY_ACTOR;
            out.ownership_retained = 1;
            goto done;
        }
    } else {
        if (free_position(registry) == MI_NONE) {
            out.code = MI_LIMIT;
            goto done;
        }
        record = (Record *)registry->allocator.allocate_zeroed(
            registry->allocator.context, sizeof(*record));
        if (!record) {
            out.code = MI_ALLOCATION_FAILED;
            goto done;
        }
        /* Custom allocators promise zeroing; initialize anyway for robustness. */
        memset(record, 0, sizeof(*record));
        record->actor = actor_root;
        actor_root = 0;
        record->actor_id = actor_id;
        record->owner_id = owner_id;
    }
    record->phase_base = record->material_count;
    for (i = 0; i < count; ++i) {
        Slot *slot;
        uint64_t owner_identity;
        int duplicate = 0;
        out.stage = MI_STAGE_SLOT;
        out.slot = i;
        if (input[i].kind < MI_MATERIAL_FIELD || input[i].kind > MI_RENDERER_ARRAY ||
            !input[i].owner) {
            out.code = MI_BAD_ARGUMENT;
            goto abort_phase;
        }
        if (!identity(registry, input[i].owner, &owner_identity)) {
            out.code = MI_IDENTITY_FAILED;
            goto abort_phase;
        }
        for (j = 0; j < record->slot_count; ++j) {
            Slot *previous = &record->slots[j];
            if (previous->descriptor.kind != input[i].kind ||
                previous->descriptor.token != input[i].token) continue;
            if (previous->owner_id == owner_identity) { duplicate = 1; break; }
        }
        if (duplicate) continue;
        slot = &record->slots[record->slot_count++];
        memset(slot, 0, sizeof(*slot));
        slot->input_slot = i;
        slot->owner_id = owner_identity;
        slot->material_index = slot->array_index = MI_NONE;
        slot->descriptor = input[i];
        slot->descriptor.owner = 0;
        if (!retain_root(registry, input[i].owner, &slot->descriptor.owner)) {
            out.code = MI_ROOT_FAILED;
            goto abort_phase;
        }
        if (!b->read_slot(b->context, &slot->descriptor, &slot->old_value)) {
            out.code = MI_SLOT_READ_FAILED;
            goto abort_phase;
        }
        if (!slot->old_value) continue;
        out.stage = MI_STAGE_SCAN;
        if (slot->descriptor.kind == MI_MATERIAL_FIELD) {
            MiRoot temporary = 0;
            if (!retain_root(registry, slot->old_value, &temporary)) {
                out.code = MI_ROOT_FAILED;
                goto abort_phase;
            }
            out.code = collect_material(registry, record, &temporary,
                                        &slot->material_index, &slot->changed);
            if (out.code != MI_OK) goto abort_phase;
        } else {
            Array *array;
            for (j = 0; j < record->array_count; ++j) {
                int same = 0;
                if (!b->same_reference(b->context, slot->old_value,
                                       record->arrays[j].old_value, &same)) {
                    out.code = MI_ROOT_FAILED;
                    goto abort_phase;
                }
                if (same) break;
            }
            slot->array_index = j;
            if (j < record->array_count) continue;
            array = &record->arrays[record->array_count++];
            memset(array, 0, sizeof(*array));
            array->old_value = slot->old_value;
            array->input_slot = i;
            if (!b->array_count(b->context, array->old_value, &array->count)) {
                out.code = MI_ARRAY_FAILED;
                goto abort_phase;
            }
            if (array->count > MI_MAX_ARRAY_ELEMENTS - elements) {
                out.code = MI_LIMIT;
                goto abort_phase;
            }
            elements += array->count;
            for (j = 0; j < array->count; ++j) {
                MiRoot temporary = 0;
                size_t index;
                int changed;
                out.element = j;
                if (!b->array_get(b->context, array->old_value, j, &temporary)) {
                    out.code = MI_ARRAY_FAILED;
                    goto abort_phase;
                }
                out.code = collect_material(registry, record, &temporary,
                                            &index, &changed);
                if (out.code != MI_OK) goto abort_phase;
                if (changed) array->changed = 1;
            }
        }
    }
    out.slot = out.element = MI_NONE;
    out.stage = MI_STAGE_CLONE;
    for (i = record->phase_base; i < record->material_count; ++i) {
        Material *material = &record->materials[i];
        out.element = i;
        if (material->policy == MI_SOURCE_PRESERVE) continue;
        if (!b->clone_material(b->context, material->source,
                               &material->private_material) ||
            !material->private_material) {
            out.code = MI_CLONE_FAILED;
            goto abort_phase;
        }
        material->owned = 1;
        if (!identity(registry, material->private_material, &material->private_id)) {
            out.code = MI_IDENTITY_FAILED;
            goto abort_phase;
        }
        if (find_source(record, material->private_id) != MI_NONE) {
            /* A backend returned a source: never destroy that object. */
            material->owned = 0;
            release_root(registry, &material->private_material);
            out.code = MI_BACKEND_CONTRACT;
            goto abort_phase;
        }
        for (j = 0; j < i; ++j)
            if (record->materials[j].private_id == material->private_id) break;
        if (j < i) {
            /* Duplicate ownership would double-destroy a prior clone. */
            material->owned = 0;
            release_root(registry, &material->private_material);
            out.code = MI_BACKEND_CONTRACT;
            goto abort_phase;
        }
    }
    out.stage = MI_STAGE_ARRAY;
    out.element = MI_NONE;
    for (i = 0; i < record->array_count; ++i) {
        Array *array = &record->arrays[i];
        size_t copied_count;
        int same;
        out.slot = array->input_slot;
        if (!array->changed) {
            array->new_value = array->old_value;
            continue;
        }
        if (!b->clone_array(b->context, array->old_value, &array->new_value) ||
            !array->new_value) {
            out.code = MI_CLONE_FAILED;
            goto abort_phase;
        }
        if (!b->same_reference(b->context, array->old_value, array->new_value, &same) ||
            same || !b->array_count(b->context, array->new_value, &copied_count) ||
            copied_count != array->count) {
            out.code = MI_BACKEND_CONTRACT;
            goto abort_phase;
        }
        for (j = 0; j < array->count; ++j) {
            MiRoot temporary = 0;
            uint64_t id;
            size_t index;
            out.element = j;
            if (!b->array_get(b->context, array->old_value, j, &temporary)) {
                out.code = MI_ARRAY_FAILED;
                goto abort_phase;
            }
            if (!temporary) continue;
            if (!identity(registry, temporary, &id)) {
                release_root(registry, &temporary);
                out.code = MI_IDENTITY_FAILED;
                goto abort_phase;
            }
            index = find_private(record, id);
            if (index == MI_NONE) index = find_source(record, id);
            if (index != MI_NONE &&
                record->materials[index].policy == MI_SOURCE_PRESERVE) {
                release_root(registry, &temporary);
                continue; /* Clone kept the original, externally-owned ref. */
            }
            if (index == MI_NONE || !record->materials[index].private_material) {
                release_root(registry, &temporary);
                out.code = MI_BACKEND_CONTRACT;
                goto abort_phase;
            }
            if (!b->array_set(b->context, array->new_value, j,
                              record->materials[index].private_material)) {
                release_root(registry, &temporary);
                out.code = MI_ARRAY_FAILED;
                goto abort_phase;
            }
            release_root(registry, &temporary);
        }
    }
    for (i = 0; i < record->slot_count; ++i) {
        Slot *slot = &record->slots[i];
        if (slot->material_index != MI_NONE)
            slot->new_value = record->materials[slot->material_index].private_material;
        if (slot->array_index != MI_NONE) {
            Array *array = &record->arrays[slot->array_index];
            slot->new_value = array->new_value;
            slot->changed = array->changed;
        }
        if (slot->changed) any_changed = 1;
    }
    out.stage = MI_STAGE_COMMIT;
    out.element = MI_NONE;
    for (i = 0; i < record->slot_count; ++i) {
        Slot *slot = &record->slots[i];
        if (!slot->changed) continue;
        out.slot = slot->input_slot;
        slot->attempted = 1;
        if (!b->write_slot(b->context, &slot->descriptor, slot->new_value)) {
            int restored = 1;
            out.code = MI_SLOT_WRITE_FAILED;
            for (j = i + 1; j > 0; --j) {
                Slot *previous = &record->slots[j - 1];
                if (previous->attempted &&
                    !b->write_slot(b->context, &previous->descriptor,
                                   previous->old_value)) {
                    if (out.rollback_slot == MI_NONE)
                        out.rollback_slot = previous->input_slot;
                    restored = 0;
                }
            }
            if (!restored) {
                record->dirty = 1;
                retain_record(registry, record);
                out.code = MI_ROLLBACK_FAILED;
                out.stage = MI_STAGE_ROLLBACK;
                out.ownership_retained = 1;
                goto done;
            }
            goto abort_phase;
        }
    }
    release_phase_roots(registry, record);
    record->phase_base = record->material_count;
    if (!record->material_count && !existing) {
        forget_record(registry, record);
        record = 0;
        out.code = MI_NO_MATERIALS;
    } else {
        retain_record(registry, record);
        out.code = any_changed ? MI_OK : (existing ? MI_ALREADY_APPLIED : MI_NO_MATERIALS);
        out.applied = any_changed;
    }
    out.stage = MI_STAGE_NONE;
    out.slot = out.element = MI_NONE;
    goto done;

abort_phase:
    if (record) {
        int cleaned = destroy_range(registry, record, record->phase_base);
        release_phase_roots(registry, record);
        if (!cleaned) {
            record->dirty = 2;
            retain_record(registry, record);
            out.ownership_retained = 1;
        } else {
            memset(&record->materials[record->phase_base], 0,
                   (record->material_count - record->phase_base) * sizeof(Material));
            record->material_count = record->phase_base;
            if (!existing) {
                forget_record(registry, record);
                record = 0;
            }
        }
    }
done:
    if (record) out.materials = material_roots(record);
    release_root(registry, &actor_root);
    registry->busy = 0;
    return out;
}

static MiResult cleanup_record(MiRegistry *registry, Record *record) {
    MiResult out = result(MI_OK, MI_STAGE_CLEANUP);
    out.actor_id = record->actor_id;
    out.owner_id = record->owner_id;
    if (!destroy_range(registry, record, 0)) {
        out.code = MI_CLEANUP_FAILED;
        out.ownership_retained = 1;
        out.materials = material_roots(record);
        return out;
    }
    forget_record(registry, record);
    return out;
}

MiResult mi_cleanup_actor(MiRegistry *registry, uint64_t actor_id) {
    MiResult out = result(MI_BAD_ARGUMENT, MI_STAGE_CLEANUP);
    size_t i;
    if (!registry || registry->initialized != MI_MAGIC || registry->busy || !actor_id)
        return out;
    registry->busy = 1;
    out.code = MI_OK;
    out.actor_id = actor_id;
    for (i = 0; i < MI_MAX_ACTORS; ++i) {
        Record *record = (Record *)registry->records[i];
        if (record && record->actor_id == actor_id) {
            out = cleanup_record(registry, record);
            break;
        }
    }
    registry->busy = 0;
    return out;
}

MiResult mi_cleanup_owner(MiRegistry *registry, uint64_t owner_id) {
    MiResult out = result(MI_BAD_ARGUMENT, MI_STAGE_CLEANUP);
    size_t i;
    if (!registry || registry->initialized != MI_MAGIC || registry->busy || !owner_id)
        return out;
    registry->busy = 1;
    out.code = MI_OK;
    out.owner_id = owner_id;
    for (i = 0; i < MI_MAX_ACTORS; ++i) {
        Record *record = (Record *)registry->records[i];
        if (record && record->owner_id == owner_id) {
            MiResult current = cleanup_record(registry, record);
            if (current.code != MI_OK && out.code == MI_OK) out = current;
        }
    }
    registry->busy = 0;
    return out;
}

size_t mi_retained_actor_count(const MiRegistry *registry) {
    size_t i, count = 0;
    if (!registry || registry->initialized != MI_MAGIC) return 0;
    for (i = 0; i < MI_MAX_ACTORS; ++i)
        if (registry->records[i]) ++count;
    return count;
}

int mi_actor_owner(const MiRegistry *registry, uint64_t actor_id, uint64_t *owner_id) {
    size_t i;
    if (!registry || registry->initialized != MI_MAGIC || !actor_id || !owner_id)
        return 0;
    for (i = 0; i < MI_MAX_ACTORS; ++i) {
        const Record *record = (const Record *)registry->records[i];
        if (record && record->actor_id == actor_id) {
            *owner_id = record->owner_id;
            return 1;
        }
    }
    return 0;
}
