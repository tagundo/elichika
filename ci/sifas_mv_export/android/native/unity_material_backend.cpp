#include "unity_material_backend.h"

/* Deliberately no STL or exported IL2CPP API dependency. Standard C++ exception
 * containment is needed because the pinned managed wrappers can throw native
 * IL2CPP exceptions. Platform linkers must provide the genuine C++ ABI runtime.
 */

namespace {
constexpr uintptr_t FIELD_TOKEN = 0x100u;
struct Field { MiuType type; size_t offset; MiSlotKind kind; };
const Field fields[] = {
    {MIU_AMBIENT, 0x20, MI_MATERIAL_ARRAY_FIELD},
    {MIU_RIMLIGHT, 0x30, MI_MATERIAL_ARRAY_FIELD},
    {MIU_BODY_PARTS, 0x48, MI_MATERIAL_FIELD},
    {MIU_CHEEK, 0x28, MI_MATERIAL_FIELD},
};
constexpr size_t FIELD_COUNT = sizeof(fields) / sizeof(fields[0]);

bool fail(MiuContext *c, MiuCode code, MiuOperation op, size_t i = MI_NONE) noexcept {
    if (c && c->error.code == MIU_SUCCESS) c->error = {code, op, i};
    return false;
}
bool valid(MiuContext *c) noexcept { return c && c->initialized == 1; }
uint64_t generation(MiuContext *c) noexcept {
    return c && c->api.transport_failure_generation ?
        c->api.transport_failure_generation(c->api.transport_context) : 0;
}
template <class F> bool checked(MiuContext *c, MiuOperation op, F f) noexcept {
    uint64_t before = generation(c);
#if MIU_CATCH_CPP_EXCEPTIONS
    try {
#endif
        bool result = f();
        if (generation(c) != before) return fail(c, MIU_TRANSPORT_EXCEPTION, op);
        return result;
#if MIU_CATCH_CPP_EXCEPTIONS
    }
    catch (...) { return fail(c, MIU_NATIVE_EXCEPTION, op); }
#endif
}
/* Each managed call is checked before another native call or an ownership
 * publication. A successful later call cannot erase an earlier invoke failure.
 * Keep a returned raw value available for partial-resource cleanup on failure.
 */
template <class R, class F> bool managed(MiuContext *c, MiuOperation op, F f, R *out) noexcept {
    uint64_t before = generation(c);
#if MIU_CATCH_CPP_EXCEPTIONS
    try {
#endif
        *out = f();
        if (generation(c) != before) return fail(c, MIU_TRANSPORT_EXCEPTION, op);
        return true;
#if MIU_CATCH_CPP_EXCEPTIONS
    }
    catch (...) { return fail(c, MIU_NATIVE_EXCEPTION, op); }
#endif
}
template <class F> bool managed_void(MiuContext *c, MiuOperation op, F f) noexcept {
    uint64_t before = generation(c);
#if MIU_CATCH_CPP_EXCEPTIONS
    try {
#endif
        f();
        if (generation(c) != before) return fail(c, MIU_TRANSPORT_EXCEPTION, op);
        return true;
#if MIU_CATCH_CPP_EXCEPTIONS
    }
    catch (...) { return fail(c, MIU_NATIVE_EXCEPTION, op); }
#endif
}
bool root_ref(MiuContext *c, void *p, MiRoot *out) noexcept {
    if (!out) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_ROOT);
    *out = 0;
    if (!p) return true;
    if (!valid(c) || c->quarantine_count) return fail(c, MIU_QUARANTINED_HANDLE, MIU_OP_ROOT);
    uint32_t h = 0;
    if (!managed(c, MIU_OP_ROOT, [&]() { return c->api.handle_alloc(p, nullptr); }, &h)) {
        if (h) { /* Transport normally returns zero on failure; retain defensively. */
            if (c->quarantine_count < MIU_MAX_QUARANTINE) c->quarantine[c->quarantine_count++] = h;
            else c->initialized = 2;
        }
        return false;
    }
    if (!h) return fail(c, MIU_NULL_RETURN, MIU_OP_ROOT);
    *out = h; return true;
}
bool target(MiuContext *c, MiRoot root, void **out) noexcept {
    if (!out) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_TARGET);
    *out = nullptr;
    if (!root) return true;
    if (!valid(c) || root > UINT32_MAX) return fail(c, MIU_INVALID_HANDLE, MIU_OP_TARGET);
    void *p = nullptr;
    if (!managed(c, MIU_OP_TARGET, [&]() { return c->api.handle_target(static_cast<int32_t>(root), nullptr); }, &p)) return false;
    if (!p) return fail(c, MIU_NULL_RETURN, MIU_OP_TARGET);
    *out = p; return true;
}
void unroot(MiuContext *c, MiRoot root) noexcept {
    if (!root) return;
    if (!valid(c) || root > UINT32_MAX) { fail(c, MIU_INVALID_HANDLE, MIU_OP_UNROOT); return; }
    if (!managed_void(c, MIU_OP_UNROOT, [&]() { c->api.handle_free(static_cast<int32_t>(root), nullptr); })) {
        /* A valid once-owned Normal GCHandle free is an audited no-fail contract.
         * Retain unexpected failures rather than throwing through the C core.
         * Subsequent allocations are refused. This is a binding/contract fault,
         * never reported as successful resource cleanup.
         */
        fail(c, MIU_QUARANTINED_HANDLE, MIU_OP_UNROOT);
        if (c->quarantine_count < MIU_MAX_QUARANTINE)
            c->quarantine[c->quarantine_count++] = root;
        else c->initialized = 2; /* terminal contract fault; no further mutation */
    }
}
struct Hold {
    MiuContext *c; MiRoot h;
    explicit Hold(MiuContext *v) : c(v), h(0) {}
    ~Hold() { unroot(c, h); }
    Hold(const Hold &) = delete; Hold &operator=(const Hold &) = delete;
    bool take(void *p) { return root_ref(c, p, &h); }
    void *get() { void *p = nullptr; return target(c, h, &p) ? p : nullptr; }
    bool value(void **p) { return target(c, h, p); }
    MiRoot release() { MiRoot r = h; h = 0; return r; }
};

void *read_ref(void *owner, size_t offset) noexcept {
    return *reinterpret_cast<void **>(static_cast<unsigned char *>(owner) + offset);
}
void write_ref(void *owner, size_t offset, void *value) noexcept {
    *reinterpret_cast<void **>(static_cast<unsigned char *>(owner) + offset) = value;
}
bool array_size(MiuContext *c, void *a, size_t *n) noexcept {
    if (!n) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_ARRAY_READ);
    *n = 0; if (!a) return true;
    /* Actual pinned 64-bit IL2CPP SZARRAY layout; only known ref arrays enter. */
    if (read_ref(a, 0x10)) return fail(c, MIU_BAD_ARRAY, MIU_OP_ARRAY_READ);
    uintptr_t count = *reinterpret_cast<uintptr_t *>(static_cast<unsigned char *>(a) + 0x18);
    if (count > MIU_MAX_ENUMERATED) return fail(c, MIU_BOUND, MIU_OP_ARRAY_READ);
    *n = static_cast<size_t>(count); return true;
}
void *array_element(void *a, size_t i) noexcept { return read_ref(a, 0x20 + 8 * i); }
bool type_object(MiuContext *c, MiuType type, void **out) noexcept {
    if (!out || type >= MIU_TYPE_COUNT) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_TYPE);
    *out = nullptr;
    if (!c->types[type]) {
        Hold t(c);
        void *value = nullptr;
        if (!managed(c, MIU_OP_TYPE, [&]() { return c->api.type_from_handle(c->api.raw_types[type], nullptr); }, &value) ||
            !t.take(value) || !t.h) return fail(c, MIU_NULL_RETURN, MIU_OP_TYPE, type);
        c->types[type] = t.release();
    }
    return target(c, c->types[type], out);
}
bool is_type(MiuContext *c, MiuType type, void *p, bool *answer) noexcept {
    if (!answer) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_TYPE);
    *answer = false; if (!p) return true;
    void *t = nullptr;
    if (!type_object(c, type, &t)) return false;
    unsigned char result = 0;
    if (!managed(c, MIU_OP_TYPE, [&]() { return c->api.is_instance(t, p, nullptr); }, &result)) return false;
    *answer = result != 0; return true;
}
bool alive(MiuContext *c, void *p) noexcept {
    if (!p) return false;
    unsigned char result = 0;
    return managed(c, MIU_OP_IDENTITY, [&]() { return c->api.object_alive(p, nullptr); }, &result) &&
        (result ? true : fail(c, MIU_DEAD_OBJECT, MIU_OP_IDENTITY));
}
bool identity(MiuContext *c, void *p, uint64_t *id) noexcept {
    if (!id) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_IDENTITY);
    *id = 0;
    if (!alive(c, p)) return false;
    int32_t raw = 0;
    if (!managed(c, MIU_OP_IDENTITY, [&]() { return c->api.instance_id(p, nullptr); }, &raw)) return false;
    if (!raw) return fail(c, MIU_DEAD_OBJECT, MIU_OP_IDENTITY);
    *id = static_cast<uint32_t>(raw); return true;
}
bool slot_owner(MiuContext *c, const MiSlot *s, void **owner, const Field **f) noexcept {
    if (!s || !owner || !f || !target(c, s->owner, owner) || !*owner)
        return fail(c, MIU_INVALID_SLOT, MIU_OP_SLOT_READ);
    *f = nullptr; bool correct = false;
    if (s->kind == MI_RENDERER_ARRAY) {
        if (s->token || !is_type(c, MIU_RENDERER, *owner, &correct) || !correct)
            return fail(c, MIU_INVALID_SLOT, MIU_OP_SLOT_READ);
    } else {
        if (s->token < FIELD_TOKEN || s->token - FIELD_TOKEN >= FIELD_COUNT)
            return fail(c, MIU_INVALID_SLOT, MIU_OP_SLOT_READ);
        *f = &fields[s->token - FIELD_TOKEN];
        if (s->kind != (*f)->kind || !is_type(c, (*f)->type, *owner, &correct) || !correct)
            return fail(c, MIU_INVALID_SLOT, MIU_OP_SLOT_READ);
    }
    return alive(c, *owner);
}

int cb_root(void *v, MiObject o, MiRoot *r) { return root_ref(static_cast<MiuContext *>(v), reinterpret_cast<void *>(o), r); }
int cb_target(void *v, MiRoot h, MiObject *o) {
    void *p = nullptr; bool ok = target(static_cast<MiuContext *>(v), h, &p);
    if (o) *o = reinterpret_cast<MiObject>(p);
    return ok && o;
}
void cb_unroot(void *v, MiRoot h) { unroot(static_cast<MiuContext *>(v), h); }
int cb_identity(void *v, MiObject p, uint64_t *id) { return identity(static_cast<MiuContext *>(v), reinterpret_cast<void *>(p), id); }
int cb_same(void *v, MiRoot a, MiRoot b, int *same) {
    MiuContext *c = static_cast<MiuContext *>(v); void *x = nullptr, *y = nullptr;
    if (!same || !target(c, a, &x) || !target(c, b, &y)) return false;
    *same = x == y; return true;
}
int cb_read_slot(void *v, const MiSlot *s, MiRoot *out) {
    MiuContext *c = static_cast<MiuContext *>(v); if (!out) return false; *out = 0;
    void *owner = nullptr; const Field *f = nullptr;
    if (!slot_owner(c, s, &owner, &f)) return false;
    void *value = f ? read_ref(owner, f->offset) : nullptr;
    if (!f && !managed(c, MIU_OP_SLOT_READ, [&]() { return c->api.shared_materials(owner, nullptr); }, &value)) return false;
    return root_ref(c, value, out);
}
int cb_write_slot(void *v, const MiSlot *s, MiRoot value) {
    MiuContext *c = static_cast<MiuContext *>(v); void *owner = nullptr, *p = nullptr; const Field *f = nullptr;
    if (!slot_owner(c, s, &owner, &f) || !target(c, value, &p)) return false;
    if (f) { write_ref(owner, f->offset, p); return true; }
    return managed_void(c, MIU_OP_SLOT_WRITE, [&]() { c->api.set_shared_materials(owner, p, nullptr); });
}
int cb_array_count(void *v, MiRoot a, size_t *n) {
    MiuContext *c = static_cast<MiuContext *>(v); void *p = nullptr;
    return target(c, a, &p) && array_size(c, p, n);
}
int cb_array_get(void *v, MiRoot a, size_t i, MiRoot *out) {
    MiuContext *c = static_cast<MiuContext *>(v); if (!out) return false; *out = 0;
    void *p = nullptr; size_t n = 0;
    if (!target(c, a, &p) || !array_size(c, p, &n) || i >= n) return fail(c, MIU_BOUND, MIU_OP_ARRAY_READ, i);
    return root_ref(c, array_element(p, i), out);
}
int cb_array_set(void *v, MiRoot a, size_t i, MiRoot value) {
    MiuContext *c = static_cast<MiuContext *>(v); void *p = nullptr, *q = nullptr; size_t n = 0;
    if (!target(c, a, &p) || !target(c, value, &q) || !array_size(c, p, &n) || i >= n)
        return fail(c, MIU_BOUND, MIU_OP_ARRAY_WRITE, i);
    if (q) {
        bool material = false;
        if (!is_type(c, MIU_MATERIAL, q, &material) || !material)
            return fail(c, MIU_TYPE_MISMATCH, MIU_OP_ARRAY_WRITE, i);
    }
    /* Matches audited plain STR reference stores in these exact IL2CPP builds.
     * Not a claim that arbitrary moving/incremental collectors permit this.
     */
    write_ref(p, 0x20 + 8 * i, q); return true;
}
int cb_clone_array(void *v, MiRoot a, MiRoot *out) {
    MiuContext *c = static_cast<MiuContext *>(v); if (!out) return false; *out = 0;
    void *p = nullptr; size_t n = 0;
    if (!target(c, a, &p) || !array_size(c, p, &n)) return false;
    if (!p) return true;
    return checked(c, MIU_OP_ARRAY_CLONE, [&]() {
        Hold copy(c);
        void *value = nullptr;
        if (!managed(c, MIU_OP_ARRAY_CLONE, [&]() { return c->api.array_clone(p, nullptr); }, &value) ||
            !copy.take(value) || !copy.h)
            return fail(c, MIU_NULL_RETURN, MIU_OP_ARRAY_CLONE);
        void *q = copy.get(); size_t count = 0;
        if (!q || q == p || read_ref(q, 0) != read_ref(p, 0) ||
            !array_size(c, q, &count) || count != n)
            return fail(c, MIU_BAD_ARRAY, MIU_OP_ARRAY_CLONE);
        *out = copy.release(); return true;
    });
}
int cb_clone_material(void *v, MiRoot src, MiRoot *out) {
    MiuContext *c = static_cast<MiuContext *>(v); if (!out) return false; *out = 0;
    if (!valid(c) || c->pending_count || c->terminal_resource_fault || c->quarantine_count)
        return fail(c, MIU_PENDING_MATERIAL, MIU_OP_MATERIAL_CLONE);
    void *p = nullptr; bool correct = false;
    if (!target(c, src, &p) || !alive(c, p) || !is_type(c, MIU_MATERIAL, p, &correct) || !correct)
        return fail(c, MIU_TYPE_MISMATCH, MIU_OP_MATERIAL_CLONE);
    Hold clone(c), name(c); void *created_clone = nullptr;
    bool ok = checked(c, MIU_OP_MATERIAL_CLONE, [&]() {
        void *source_name = nullptr;
        if (!managed(c, MIU_OP_MATERIAL_CLONE, [&]() { return c->api.get_name(p, nullptr); }, &source_name) || !name.take(source_name)) return false;
        if (!managed(c, MIU_OP_MATERIAL_CLONE, [&]() { return c->api.instantiate(p, nullptr); }, &created_clone)) return false;
        if (!created_clone || created_clone == p) return fail(c, MIU_NULL_RETURN, MIU_OP_MATERIAL_CLONE);
        if (!clone.take(created_clone)) return false;
        void *q = clone.get(); bool material = false;
        if (!q || !is_type(c, MIU_MATERIAL, q, &material) || !material) return fail(c, MIU_TYPE_MISMATCH, MIU_OP_MATERIAL_CLONE);
        void *n = nullptr; if (!target(c, name.h, &n)) return false;
        return managed_void(c, MIU_OP_MATERIAL_CLONE, [&]() { c->api.set_name(q, n, nullptr); });
    });
    if (!ok) {
        /* Destroy only the engine object created by this callback. Never src. */
        void *q = created_clone;
        if (q && q != p && !managed_void(c, MIU_OP_MATERIAL_DESTROY, [&]() { c->api.destroy(q, nullptr); })) {
            /* One unresolved partial clone blocks future apply, bounding native
             * ownership. Keep the exact strong root until manager teardown.
             */
            if (c->pending_count < MIU_MAX_PENDING_MATERIALS) {
                MiuPendingMaterial &pending = c->pending[c->pending_count++];
                pending.owner_id = c->current_owner; pending.root = clone.release();
                pending.created_object = reinterpret_cast<MiObject>(q);
                if (!pending.root) c->terminal_resource_fault = 1;
            } else c->terminal_resource_fault = 1;
        }
        return false;
    }
    *out = clone.release(); return true;
}
int cb_destroy_material(void *v, MiRoot root) {
    MiuContext *c = static_cast<MiuContext *>(v); void *p = nullptr;
    if (!target(c, root, &p)) return false;
    if (!p) return true;
    unsigned char live = 0;
    if (!managed(c, MIU_OP_MATERIAL_DESTROY, [&]() { return c->api.object_alive(p, nullptr); }, &live)) return false;
    return !live || managed_void(c, MIU_OP_MATERIAL_DESTROY, [&]() { c->api.destroy(p, nullptr); });
}
int cb_source_policy(void *v, MiObject, uint64_t id, MiMaterialPolicy *out) {
    MiuContext *c = static_cast<MiuContext *>(v);
    if (!valid(c) || !out || !id) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_IDENTITY);
    *out = MI_SOURCE_ISOLATE;
    for (size_t i = 0; i < c->preserved_material_count; ++i)
        if (c->preserved_material_ids[i] == id) { *out = MI_SOURCE_PRESERVE; break; }
    return true;
}

bool add_id(MiuContext *c, uint64_t *ids, size_t *count, size_t cap, uint64_t id) noexcept {
    for (size_t i = 0; i < *count; ++i) if (ids[i] == id) return true;
    if (*count == cap) return fail(c, MIU_BOUND, MIU_OP_EFFECT_EXCLUSION);
    ids[(*count)++] = id; return true;
}
bool preserve_material(MiuContext *c, void *p) noexcept {
    if (!p) return true;
    uint64_t id = 0;
    if (!identity(c, p, &id)) return false;
    return add_id(c, c->preserved_material_ids, &c->preserved_material_count, MIU_MAX_EFFECT_MATERIALS, id);
}
bool preserve_array(MiuContext *c, void *a) noexcept {
    size_t n = 0; if (!array_size(c, a, &n)) return false;
    for (size_t i = 0; i < n; ++i) if (!preserve_material(c, array_element(a, i))) return false;
    return true;
}
struct Scan {
    MiuContext *c;
    MiRoot prop_transforms[MIU_MAX_PROP_ROOTS] = {};
    bool prop_initialized[MIU_MAX_PROP_ROOTS] = {};
    size_t prop_count = 0;
    uint64_t excluded_renderers[MIU_MAX_EFFECT_RENDERERS] = {};
    size_t renderer_count = 0;
    explicit Scan(MiuContext *v) : c(v) {}
    ~Scan() { for (size_t i = 0; i < prop_count; ++i) unroot(c, prop_transforms[i]); }
    bool excluded_renderer(void *p) {
        if (!renderer_count) return false;
        uint64_t id = 0; if (!identity(c, p, &id)) return true;
        for (size_t i = 0; i < renderer_count; ++i) if (excluded_renderers[i] == id) return true;
        return false;
    }
    bool add_renderer(void *p) {
        if (!p) return true;
        uint64_t id = 0;
        return identity(c, p, &id) && add_id(c, excluded_renderers, &renderer_count, MIU_MAX_EFFECT_RENDERERS, id);
    }
    bool in_prop(void *component, bool *inside, bool *initialized) {
        *inside = false; *initialized = false;
        if (!prop_count) return true;
        Hold transform(c);
        void *raw_transform = nullptr;
        if (!managed(c, MIU_OP_PROP_EXCLUSION, [&]() { return c->api.component_transform(component, nullptr); }, &raw_transform) ||
            !transform.take(raw_transform) || !transform.h)
            return fail(c, MIU_NULL_RETURN, MIU_OP_PROP_EXCLUSION);
        void *t = nullptr; if (!transform.value(&t) || !t) return false;
        for (size_t i = 0; i < prop_count; ++i) {
            void *parent = nullptr; if (!target(c, prop_transforms[i], &parent)) return false;
            unsigned char child = 0;
            if (!managed(c, MIU_OP_PROP_EXCLUSION, [&]() { return c->api.is_child_of(t, parent, nullptr); }, &child)) return false;
            if (child) { *inside = true; *initialized = *initialized || prop_initialized[i]; }
        }
        return true;
    }
};
bool enumerate(MiuContext *c, void *go, MiuType type, Hold &result) noexcept {
    void *t = nullptr;
    if (!type_object(c, type, &t)) return false;
    void *value = nullptr;
    return managed(c, MIU_OP_ENUMERATE, [&]() { return c->api.components_in_children(go, t, 1, nullptr); }, &value) &&
        result.take(value) && result.h;
}
bool add_slot(MiuContext *c, MiuSlots *out, void *owner, MiSlotKind kind, uintptr_t token) noexcept {
    if (out->count >= MI_MAX_SLOTS) return fail(c, MIU_BOUND, MIU_OP_ENUMERATE);
    MiRoot h = 0; if (!root_ref(c, owner, &h)) return false;
    size_t i = out->count++;
    out->roots[i] = h; out->slots[i] = {kind, h, token}; return true;
}
bool prepare_prop_scopes(MiuContext *c, void *go, Scan &scan) noexcept {
    Hold values(c);
    if (!enumerate(c, go, MIU_PROP_BASIC, values)) return false;
    void *a = nullptr; if (!values.value(&a) || !a) return false;
    size_t n = 0;
    if (!array_size(c, a, &n) || n > MIU_MAX_PROP_ROOTS) return fail(c, MIU_BOUND, MIU_OP_PROP_EXCLUSION);
    for (size_t i = 0; i < n; ++i) {
        void *prop = array_element(a, i); if (!prop) continue;
        Hold p(c), transform(c);
        void *raw_transform = nullptr;
        if (!p.take(prop) || !managed(c, MIU_OP_PROP_EXCLUSION, [&]() { return c->api.component_transform(prop, nullptr); }, &raw_transform) ||
            !transform.take(raw_transform) || !transform.h)
            return fail(c, MIU_NULL_RETURN, MIU_OP_PROP_EXCLUSION, i);
        size_t at = scan.prop_count++;
        scan.prop_transforms[at] = transform.release();
        /* Existing game's dictionary is an ownership marker, not guessed data. */
        scan.prop_initialized[at] = read_ref(prop, 0x38) != nullptr;
    }
    return true;
}
bool prepare_effect_scopes(MiuContext *c, void *components, Scan &scan) noexcept {
    size_t n = 0; if (!array_size(c, components, &n)) return false;
    for (size_t i = 0; i < n; ++i) {
        void *p = array_element(components, i); if (!p) continue;
        Hold component(c); if (!component.take(p)) return false;
        bool shaft = false, area = false;
        if (!is_type(c, MIU_SPOTLIGHT_SHAFT, p, &shaft) || !is_type(c, MIU_SPOTLIGHT_AREA, p, &area)) return false;
        if (shaft) {
            if (!scan.add_renderer(read_ref(p, 0x38)) || !preserve_material(c, read_ref(p, 0x40))) return false;
            Hold renderers(c), materials(c);
            if (!renderers.take(read_ref(p, 0x58)) || !materials.take(read_ref(p, 0x60))) return false;
            void *a = nullptr; if (!renderers.value(&a)) return false;
            size_t count = 0;
            if (!array_size(c, a, &count)) return false;
            for (size_t j = 0; j < count; ++j) if (!scan.add_renderer(array_element(a, j))) return false;
            void *m = nullptr;
            if (!materials.value(&m) || !preserve_array(c, m)) return false;
        }
        if (area && (!scan.add_renderer(read_ref(p, 0x20)) || !preserve_material(c, read_ref(p, 0x28)))) return false;
    }
    return true;
}
} // namespace

extern "C" int miu_context_init(MiuContext *c, const MiuApi *a) {
    if (!c || c->initialized || !a || !a->array_clone || !a->type_from_handle || !a->handle_alloc || !a->handle_target || !a->handle_free ||
        !a->instance_id || !a->object_alive || !a->component_game_object || !a->component_transform ||
        !a->components_in_children || !a->is_instance || !a->is_child_of || !a->shared_materials ||
        !a->set_shared_materials || !a->instantiate || !a->destroy || !a->get_name || !a->set_name) return false;
    for (size_t i = 0; i < MIU_TYPE_COUNT; ++i) if (!a->raw_types[i]) return false;
#if !MIU_CATCH_CPP_EXCEPTIONS
    if (!a->transport_failure_generation) return false;
#endif
    *c = {}; c->api = *a; c->initialized = 1; return true;
}
extern "C" MiBackend miu_backend(MiuContext *c) {
    MiBackend b = {};
    b.context = c; b.root = cb_root; b.get_target = cb_target; b.unroot = cb_unroot;
    b.object_identity = cb_identity; b.same_reference = cb_same;
    b.read_slot = cb_read_slot; b.write_slot = cb_write_slot;
    b.array_count = cb_array_count; b.array_get = cb_array_get; b.array_set = cb_array_set;
    b.clone_array = cb_clone_array; b.clone_material = cb_clone_material; b.destroy_material = cb_destroy_material;
    b.source_policy = cb_source_policy;
    return b;
}
extern "C" void miu_clear_error(MiuContext *c) { if (c) c->error = {}; }
extern "C" MiuError miu_last_error(const MiuContext *c) { return c ? c->error : MiuError{MIU_BAD_ARGUMENT, MIU_OP_NONE, MI_NONE}; }
extern "C" const char *miu_error_text(MiuCode c) {
    const char *names[] = {"success", "invalid backend argument", "managed wrapper raised a native exception", "invalid strong handle",
        "managed wrapper returned null", "unexpected managed array layout", "actor scope exceeds a validated bound", "managed type mismatch",
        "unknown material field or renderer slot", "destroyed Unity object", "incompatible material ownership", "GC handle free contract failed; root retained",
        "game runtime_invoke reported a managed exception", "partial private material cleanup is pending manager teardown",
        "native material creation could not be rooted or cleaned; isolation disabled for this session"};
    return static_cast<unsigned>(c) < sizeof(names) / sizeof(names[0]) ? names[c] : "unknown backend error";
}
extern "C" void miu_release_slots(MiuContext *c, MiuSlots *s) {
    if (!s) return;
    for (size_t i = 0; i < s->count; ++i) unroot(c, s->roots[i]);
    *s = {};
}
extern "C" int miu_collect_slots(MiuContext *c, MiObject actor, MiuSlots *out) {
    if (!valid(c) || !out || out->count || c->quarantine_count) return fail(c, MIU_BAD_ARGUMENT, MIU_OP_ENUMERATE);
    if (c->pending_count || c->terminal_resource_fault)
        return fail(c, c->terminal_resource_fault ? MIU_UNROOTED_NATIVE_RESOURCE : MIU_PENDING_MATERIAL, MIU_OP_ENUMERATE);
    miu_clear_error(c); c->preserved_material_count = 0;
    Hold actor_root(c), go(c), renderers(c), components(c); Scan scan(c);
    bool ok = checked(c, MIU_OP_ENUMERATE, [&]() {
        void *p = reinterpret_cast<void *>(actor);
        void *raw_go = nullptr;
        if (!actor_root.take(p) || !alive(c, p) ||
            !managed(c, MIU_OP_ENUMERATE, [&]() { return c->api.component_game_object(p, nullptr); }, &raw_go) ||
            !go.take(raw_go) || !go.h) return false;
        void *g = nullptr; if (!go.value(&g) || !g) return false;
        if (!prepare_prop_scopes(c, g, scan) || !enumerate(c, g, MIU_RENDERER, renderers) || !enumerate(c, g, MIU_MONOBEHAVIOUR, components)) return false;
        void *all = nullptr; if (!components.value(&all) || !all) return false;
        if (!prepare_effect_scopes(c, all, scan)) return false;
        /* Preserve actual private materials of already-initialized props. The
         * dictionary's internals are never guessed; reachable private renderer
         * and lighting references are collected from its validated subtree.
         */
        void *r = nullptr; if (!renderers.value(&r) || !r) return false;
        size_t n = 0;
        if (!array_size(c, r, &n)) return false;
        for (size_t i = 0; i < n; ++i) {
            void *renderer = array_element(r, i); if (!renderer) continue;
            Hold current(c); if (!current.take(renderer)) return false;
            bool prop = false, initialized = false;
            if (!scan.in_prop(renderer, &prop, &initialized)) return false;
            if (prop) {
                if (initialized) {
                    Hold mats(c); void *raw_mats = nullptr;
                    if (!managed(c, MIU_OP_PROP_EXCLUSION, [&]() { return c->api.shared_materials(renderer, nullptr); }, &raw_mats) ||
                        !mats.take(raw_mats)) return false;
                    void *value = nullptr; if (!mats.value(&value) || !preserve_array(c, value)) return false;
                }
                continue;
            }
            if (scan.excluded_renderer(renderer)) { if (c->error.code != MIU_SUCCESS) return false; continue; }
            if (!add_slot(c, out, renderer, MI_RENDERER_ARRAY, 0)) return false;
        }
        if (!array_size(c, all, &n)) return false;
        for (size_t i = 0; i < n; ++i) {
            void *component = array_element(all, i); if (!component) continue;
            Hold current(c); if (!current.take(component)) return false;
            bool prop = false, initialized = false;
            if (!scan.in_prop(component, &prop, &initialized)) return false;
            for (size_t k = 0; k < FIELD_COUNT; ++k) {
                bool matches = false;
                if (!is_type(c, fields[k].type, component, &matches)) return false;
                if (!matches) continue;
                if (prop) {
                    if (initialized) {
                        Hold value(c); if (!value.take(read_ref(component, fields[k].offset))) return false;
                        void *p = nullptr; if (!value.value(&p)) return false;
                        if (fields[k].kind == MI_MATERIAL_ARRAY_FIELD) { if (!preserve_array(c, p)) return false; }
                        else if (!preserve_material(c, p)) return false;
                    }
                    continue;
                }
                if (!read_ref(component, fields[k].offset)) continue;
                if (!add_slot(c, out, component, fields[k].kind, FIELD_TOKEN + k)) return false;
            }
        }
        return true;
    });
    if (!ok) { miu_release_slots(c, out); c->preserved_material_count = 0; }
    return ok;
}
extern "C" int miu_release_types(MiuContext *c) {
    if (!valid(c)) return false;
    while (c->pending_count) {
        size_t before = c->pending_count;
        if (!miu_cleanup_pending_owner(c, c->pending[0].owner_id) || c->pending_count == before) return false;
    }
    for (size_t i = 0; i < MIU_TYPE_COUNT; ++i) { unroot(c, c->types[i]); c->types[i] = 0; }
    /* Retry only exact previously-owned handles; no guessed handle numbers. */
    size_t original = c->quarantine_count; c->quarantine_count = 0;
    for (size_t i = 0; i < original; ++i) unroot(c, c->quarantine[i]);
    return c->quarantine_count == 0 && c->initialized == 1;
}
extern "C" MiResult miu_apply_actor(MiuContext *c, MiRegistry *registry, MiObject actor, uint64_t owner_id) {
    MiuSlots slots = {};
    if (!valid(c) || c->current_owner || !owner_id) {
        MiResult r = {}; r.code = MI_BAD_ARGUMENT; r.stage = MI_STAGE_ACTOR; return r;
    }
    c->current_owner = owner_id;
    if (!miu_collect_slots(c, actor, &slots)) {
        MiResult result = {}; result.code = MI_BACKEND_CONTRACT; result.stage = MI_STAGE_SCAN;
        result.slot = result.element = result.rollback_slot = MI_NONE; result.owner_id = owner_id;
        result.ownership_retained = c->pending_count || c->terminal_resource_fault;
        c->current_owner = 0;
        return result;
    }
    MiResult result = mi_apply(registry, actor, owner_id, slots.slots, slots.count);
    miu_release_slots(c, &slots);
    if (c->quarantine_count || c->initialized != 1 || c->pending_count || c->terminal_resource_fault) {
        result.code = MI_CLEANUP_FAILED; result.stage = MI_STAGE_CLEANUP;
        result.ownership_retained = 1;
    }
    c->current_owner = 0;
    return result;
}
extern "C" int miu_actor_owner(MiuContext *c, const MiRegistry *registry, MiObject actor, uint64_t *owner_id) {
    uint64_t actor_id = 0;
    return identity(c, reinterpret_cast<void *>(actor), &actor_id) && mi_actor_owner(registry, actor_id, owner_id);
}
extern "C" int miu_cleanup_pending_owner(MiuContext *c, uint64_t owner_id) {
    if (!valid(c)) return false;
    for (size_t i = 0; i < c->pending_count;) {
        MiuPendingMaterial &entry = c->pending[i];
        if (entry.owner_id != owner_id) { ++i; continue; }
        if (!entry.root) return fail(c, MIU_UNROOTED_NATIVE_RESOURCE, MIU_OP_MATERIAL_DESTROY);
        if (!cb_destroy_material(c, entry.root)) return false;
        MiRoot root = entry.root;
        for (size_t j = i + 1; j < c->pending_count; ++j) c->pending[j - 1] = c->pending[j];
        --c->pending_count; c->pending[c->pending_count] = {};
        unroot(c, root);
    }
    return !c->quarantine_count && !c->terminal_resource_fault;
}
extern "C" MiResult miu_cleanup_owner(MiuContext *c, MiRegistry *registry, uint64_t owner_id) {
    MiResult result = mi_cleanup_owner(registry, owner_id);
    if (!miu_cleanup_pending_owner(c, owner_id)) {
        result.code = MI_CLEANUP_FAILED; result.stage = MI_STAGE_CLEANUP;
        result.ownership_retained = 1;
    }
    return result;
}
