#include "android_material_invoke.h"
#include <string.h>

#if defined(__EXCEPTIONS) || defined(__GXX_RTTI)
#error "Android transport requires -fno-exceptions -fno-rtti; use same-engine runtime_invoke exception-out."
#endif

namespace {
enum MaiReturn { MAI_RET_REF, MAI_RET_VOID, MAI_RET_I32, MAI_RET_BOOL };
struct MaiMethodPin {
    uintptr_t owner_type, return_type, parameters[2];
    uint32_t token;
    unsigned char parameter_count, is_static, return_kind;
};
struct MaiExportPins {
    uintptr_t runtime_invoke, class_from_type, class_get_methods;
    uintptr_t method_get_token, method_get_param_count, method_get_param;
    uintptr_t method_get_return_type, method_get_class, method_get_flags;
    uintptr_t type_equals, object_get_class, object_unbox;
    uintptr_t gchandle_new, gchandle_get_target, gchandle_free;
    uintptr_t class_is_assignable_from;
};
struct MaiBuildPins {
    MaiExportPins exports;
    MaiMethodPin methods[MAI_METHOD_COUNT];
    uintptr_t backend_types[MIU_TYPE_COUNT];
};
#include "android_invoke_pins.inc"

MaiContext *active_context = nullptr;
const size_t METHOD_ITERATION_LIMIT = 4096;

const void *pointer(MaiContext *c, uintptr_t va) {
    return reinterpret_cast<const void *>(c->image_load_bias + va);
}
void failed(MaiContext *c, MaiFailure why, MaiMethod method) {
    if (!c) return;
    ++c->failure_generation;
    c->last_failure = why;
    c->last_method = method;
}
MaiContext *context() {
    return active_context && active_context->initialized == 1 ? active_context : nullptr;
}
const MaiMethodPin &pin(MaiContext *c, MaiMethod m) {
    return static_cast<const MaiBuildPins *>(c->build_pins)->methods[m];
}
const void *resolve(MaiContext *c, MaiMethod m) {
    if (c->methods[m]) return c->methods[m];
    const MaiMethodPin &p = pin(c, m);
    MaiExports &e = c->engine;
    void *owner = e.class_from_type(pointer(c, p.owner_type));
    if (!owner) { failed(c, MAI_FAILURE_CLASS, m); return nullptr; }
    void *iterator = nullptr;
    const void *found = nullptr;
    size_t count = 0;
    for (;;) {
        const void *candidate = e.class_get_methods(owner, &iterator);
        if (!candidate) break;
        if (++count > METHOD_ITERATION_LIMIT) {
            failed(c, MAI_FAILURE_METHOD, m); return nullptr;
        }
        if (e.method_get_token(candidate) != p.token) continue;
        if (found) { failed(c, MAI_FAILURE_METHOD, m); return nullptr; }
        uint32_t implementation_flags = 0;
        uint32_t flags = e.method_get_flags(candidate, &implementation_flags);
        (void)implementation_flags;
        if (e.method_get_class(candidate) != owner ||
            ((flags & 0x10u) != 0) != (p.is_static != 0) ||
            e.method_get_param_count(candidate) != p.parameter_count ||
            !e.type_equals(e.method_get_return_type(candidate), pointer(c, p.return_type))) {
            failed(c, MAI_FAILURE_SIGNATURE, m); return nullptr;
        }
        for (uint32_t i = 0; i < p.parameter_count; ++i) {
            if (!e.type_equals(e.method_get_param(candidate, i), pointer(c, p.parameters[i]))) {
                failed(c, MAI_FAILURE_SIGNATURE, m); return nullptr;
            }
        }
        found = candidate;
    }
    if (!found) { failed(c, MAI_FAILURE_METHOD, m); return nullptr; }
    c->methods[m] = found;
    c->declaring_classes[m] = owner;
    return found;
}
void *invoke(MaiMethod m, void *self, void **args) {
    MaiContext *c = context();
    if (!c) return nullptr;
    const MaiMethodPin &p = pin(c, m);
    if (!p.is_static && !self) { failed(c, MAI_FAILURE_ARGUMENT, m); return nullptr; }
    const void *method = resolve(c, m);
    if (!method) return nullptr;
    if (!p.is_static) {
        void *actual_class = c->engine.object_get_class(self);
        if (!actual_class || !c->engine.class_is_assignable_from(c->declaring_classes[m], actual_class)) {
            failed(c, MAI_FAILURE_CLASS, m); return nullptr;
        }
    }
    void *exception = nullptr;
    void *value = c->engine.runtime_invoke(method, p.is_static ? nullptr : self, args, &exception);
    if (exception) {
        /* Exception object is never formatted, allocated from, or passed to a
         * foreign catch. Original engine runtime_invoke has already contained it. */
        failed(c, MAI_FAILURE_MANAGED_EXCEPTION, m);
        return nullptr;
    }
    if (p.return_kind == MAI_RET_VOID && value) {
        failed(c, MAI_FAILURE_BOX, m); return nullptr;
    }
    return value;
}
bool unbox(MaiMethod m, void *boxed, void *output, size_t bytes) {
    MaiContext *c = context();
    if (!c) return false;
    const MaiMethodPin &p = pin(c, m);
    void *expected_class = c->engine.class_from_type(pointer(c, p.return_type));
    if (!boxed || !expected_class || c->engine.object_get_class(boxed) != expected_class) {
        failed(c, MAI_FAILURE_BOX, m); return false;
    }
    void *data = c->engine.object_unbox(boxed);
    if (!data) { failed(c, MAI_FAILURE_BOX, m); return false; }
    memcpy(output, data, bytes);
    return true;
}
int32_t invoke_i32(MaiMethod m, void *self, void **args) {
    MaiContext *c = context(); if (!c) return 0;
    uint64_t before = c->failure_generation;
    void *boxed = invoke(m, self, args);
    int32_t value = 0;
    if (before != c->failure_generation || !unbox(m, boxed, &value, sizeof(value))) return 0;
    return value;
}
unsigned char invoke_bool(MaiMethod m, void *self, void **args) {
    MaiContext *c = context(); if (!c) return 0;
    uint64_t before = c->failure_generation;
    void *boxed = invoke(m, self, args);
    unsigned char value = 0;
    if (before != c->failure_generation || !unbox(m, boxed, &value, sizeof(value))) return 0;
    if (value > 1) { failed(c, MAI_FAILURE_BOX, m); return 0; }
    return value;
}

void *array_clone(void *self, const void *) { return invoke(MAI_ARRAY_CLONE, self, nullptr); }
void *type_from_handle(const void *raw_type, const void *) {
    MaiContext *c = context(); if (!c) return nullptr;
    if (!raw_type) { failed(c, MAI_FAILURE_ARGUMENT, MAI_TYPE_FROM_HANDLE); return nullptr; }
    /* RuntimeTypeHandle is a one-word value struct: argument points to VALUE
     * storage containing Il2CppType*, not to an object and not Il2CppClass*. */
    const void *handle_value = raw_type;
    void *args[] = {&handle_value};
    return invoke(MAI_TYPE_FROM_HANDLE, nullptr, args);
}
uint32_t handle_alloc(void *object, const void *) {
    MaiContext *c = context(); if (!c || !object) return 0;
    uint32_t value = c->engine.gchandle_new(object, 0); /* Normal strong, not pinned. */
    if (!value) failed(c, MAI_FAILURE_HANDLE, MAI_ARRAY_CLONE);
    else ++c->live_handles;
    return value;
}
void *handle_target(int32_t handle, const void *) {
    MaiContext *c = context(); if (!c || !handle) return nullptr;
    void *value = c->engine.gchandle_get_target(static_cast<uint32_t>(handle));
    if (!value) failed(c, MAI_FAILURE_HANDLE, MAI_ARRAY_CLONE);
    return value;
}
void handle_free(int32_t handle, const void *) {
    MaiContext *c = context(); if (!c || !handle) return;
    /* Original same-engine API; backend guarantees valid once-owned handles.
     * There is no boxing, managed Free adjustor thunk or foreign C++ catch. */
    c->engine.gchandle_free(static_cast<uint32_t>(handle));
    if (c->live_handles) --c->live_handles;
}
int32_t instance_id(void *self, const void *) { return invoke_i32(MAI_INSTANCE_ID, self, nullptr); }
unsigned char object_alive(void *object, const void *) {
    void *args[] = {object}; /* Reference parameter is OBJECT directly. */
    return invoke_bool(MAI_OBJECT_ALIVE, nullptr, args);
}
void *component_game_object(void *self, const void *) { return invoke(MAI_COMPONENT_GAME_OBJECT, self, nullptr); }
void *component_transform(void *self, const void *) { return invoke(MAI_COMPONENT_TRANSFORM, self, nullptr); }
void *components_in_children(void *self, void *type, unsigned char include_inactive, const void *) {
    MaiContext *c = context(); if (!c) return nullptr;
    if (!type || include_inactive > 1) { failed(c, MAI_FAILURE_ARGUMENT, MAI_COMPONENTS_IN_CHILDREN); return nullptr; }
    void *args[] = {type, &include_inactive};
    return invoke(MAI_COMPONENTS_IN_CHILDREN, self, args);
}
unsigned char is_instance(void *self, void *object, const void *) {
    void *args[] = {object}; return invoke_bool(MAI_IS_INSTANCE, self, args);
}
unsigned char is_child_of(void *self, void *parent, const void *) {
    void *args[] = {parent}; return invoke_bool(MAI_IS_CHILD_OF, self, args);
}
void *shared_materials(void *self, const void *) { return invoke(MAI_SHARED_MATERIALS, self, nullptr); }
void set_shared_materials(void *self, void *array, const void *) {
    void *args[] = {array}; (void)invoke(MAI_SET_SHARED_MATERIALS, self, args);
}
void *instantiate(void *object, const void *) {
    void *args[] = {object}; return invoke(MAI_INSTANTIATE, nullptr, args);
}
void destroy(void *object, const void *) {
    void *args[] = {object}; (void)invoke(MAI_DESTROY, nullptr, args);
}
void *get_name(void *self, const void *) { return invoke(MAI_GET_NAME, self, nullptr); }
void set_name(void *self, void *name, const void *) {
    void *args[] = {name}; (void)invoke(MAI_SET_NAME, self, args);
}
} // namespace

extern "C" uint64_t mai_failure_generation(void *context_pointer) {
    const MaiContext *c = static_cast<const MaiContext *>(context_pointer);
    return c ? c->failure_generation : 0;
}
extern "C" void *mai_member_manager(void *director, const void *) {
    return invoke(MAI_MEMBER_MANAGER, director, nullptr);
}
extern "C" void *mai_actor_referer(void *actor, const void *) {
    return invoke(MAI_ACTOR_REFERER, actor, nullptr);
}
extern "C" int mai_context_init(MaiContext *c, MaiRegion region, uintptr_t bias, MiuApi *out) {
    if (out) memset(out, 0, sizeof(*out));
    if (!c || !out || active_context || !bias || (region != MAI_GL && region != MAI_JP)) return 0;
    memset(c, 0, sizeof(*c));
    const MaiBuildPins &p = mai_builds[static_cast<unsigned int>(region)];
    c->build_pins = &p;
    c->image_load_bias = bias;
#define MAI_EXPORT(name) c->engine.name = reinterpret_cast<decltype(c->engine.name)>(bias + p.exports.name)
    MAI_EXPORT(runtime_invoke); MAI_EXPORT(class_from_type); MAI_EXPORT(class_get_methods);
    MAI_EXPORT(method_get_token); MAI_EXPORT(method_get_param_count); MAI_EXPORT(method_get_param);
    MAI_EXPORT(method_get_return_type); MAI_EXPORT(method_get_class); MAI_EXPORT(method_get_flags);
    MAI_EXPORT(type_equals); MAI_EXPORT(object_get_class); MAI_EXPORT(object_unbox);
    MAI_EXPORT(gchandle_new); MAI_EXPORT(gchandle_get_target); MAI_EXPORT(gchandle_free);
    MAI_EXPORT(class_is_assignable_from);
#undef MAI_EXPORT
    out->array_clone = array_clone; out->type_from_handle = type_from_handle;
    out->handle_alloc = handle_alloc; out->handle_target = handle_target; out->handle_free = handle_free;
    out->instance_id = instance_id; out->object_alive = object_alive;
    out->component_game_object = component_game_object; out->component_transform = component_transform;
    out->components_in_children = components_in_children; out->is_instance = is_instance;
    out->is_child_of = is_child_of; out->shared_materials = shared_materials;
    out->set_shared_materials = set_shared_materials; out->instantiate = instantiate;
    out->destroy = destroy; out->get_name = get_name; out->set_name = set_name;
    for (size_t i = 0; i < MIU_TYPE_COUNT; ++i) out->raw_types[i] = pointer(c, p.backend_types[i]);
    out->transport_context = c;
    out->transport_failure_generation = mai_failure_generation;
    c->last_method = MAI_METHOD_COUNT;
    c->initialized = 1;
    active_context = c;
    return 1;
}
