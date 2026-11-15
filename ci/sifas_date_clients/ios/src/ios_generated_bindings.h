#ifndef SIFAS_IOS_GENERATED_MATERIAL_BINDINGS_H
#define SIFAS_IOS_GENERATED_MATERIAL_BINDINGS_H
/* Generated from exact reviewed V4 native bindings; do not edit by hand. */
#include "unity_material_backend.h"
struct SifasMatPreferred { unsigned int region; uintptr_t culler, reset, term, owner_getter, director_type, actor_referer; };
static const unsigned char sifas_mat_contract_sha[32] = {0xa8,0xe8,0xfd,0x34,0x5b,0x04,0xde,0x53,0x41,0x8f,0xaf,0x7c,0x11,0x0c,0x15,0x61,0x1d,0xc9,0xb1,0xda,0xec,0x80,0x02,0xba,0x02,0x1c,0xe4,0x44,0x45,0xf9,0xae,0xee};
static inline uintptr_t sifas_mat_address(uintptr_t preferred, intptr_t slide) { return preferred + static_cast<uintptr_t>(slide); }
static inline bool sifas_mat_fill(unsigned int region, intptr_t slide, MiuApi *api, SifasMatPreferred *preferred) {
  if (!api || !preferred) return false;
  *api = {};
  if (region == 1) {
    api->array_clone = reinterpret_cast<decltype(api->array_clone)>(sifas_mat_address(0x103b71234ULL, slide));
    api->type_from_handle = reinterpret_cast<decltype(api->type_from_handle)>(sifas_mat_address(0x103b9bad0ULL, slide));
    api->handle_alloc = reinterpret_cast<decltype(api->handle_alloc)>(sifas_mat_address(0x103a95ee4ULL, slide));
    api->handle_target = reinterpret_cast<decltype(api->handle_target)>(sifas_mat_address(0x103a95da0ULL, slide));
    api->handle_free = reinterpret_cast<decltype(api->handle_free)>(sifas_mat_address(0x103a95fb0ULL, slide));
    api->instance_id = reinterpret_cast<decltype(api->instance_id)>(sifas_mat_address(0x103952b08ULL, slide));
    api->object_alive = reinterpret_cast<decltype(api->object_alive)>(sifas_mat_address(0x103952e5cULL, slide));
    api->component_game_object = reinterpret_cast<decltype(api->component_game_object)>(sifas_mat_address(0x103938ec4ULL, slide));
    api->component_transform = reinterpret_cast<decltype(api->component_transform)>(sifas_mat_address(0x103938e58ULL, slide));
    api->components_in_children = reinterpret_cast<decltype(api->components_in_children)>(sifas_mat_address(0x103940b4cULL, slide));
    api->is_instance = reinterpret_cast<decltype(api->is_instance)>(sifas_mat_address(0x103af6d4cULL, slide));
    api->is_child_of = reinterpret_cast<decltype(api->is_child_of)>(sifas_mat_address(0x103976010ULL, slide));
    api->shared_materials = reinterpret_cast<decltype(api->shared_materials)>(sifas_mat_address(0x103961050ULL, slide));
    api->set_shared_materials = reinterpret_cast<decltype(api->set_shared_materials)>(sifas_mat_address(0x103961054ULL, slide));
    api->instantiate = reinterpret_cast<decltype(api->instantiate)>(sifas_mat_address(0x103953088ULL, slide));
    api->destroy = reinterpret_cast<decltype(api->destroy)>(sifas_mat_address(0x103953490ULL, slide));
    api->get_name = reinterpret_cast<decltype(api->get_name)>(sifas_mat_address(0x10394ee98ULL, slide));
    api->set_name = reinterpret_cast<decltype(api->set_name)>(sifas_mat_address(0x103952f98ULL, slide));
    api->raw_types[MIU_RENDERER] = reinterpret_cast<const void *>(sifas_mat_address(0x1047fbfc0ULL, slide));
    api->raw_types[MIU_MONOBEHAVIOUR] = reinterpret_cast<const void *>(sifas_mat_address(0x1047e0020ULL, slide));
    api->raw_types[MIU_MATERIAL] = reinterpret_cast<const void *>(sifas_mat_address(0x1047de720ULL, slide));
    api->raw_types[MIU_AMBIENT] = reinterpret_cast<const void *>(sifas_mat_address(0x10480db20ULL, slide));
    api->raw_types[MIU_RIMLIGHT] = reinterpret_cast<const void *>(sifas_mat_address(0x10480db50ULL, slide));
    api->raw_types[MIU_BODY_PARTS] = reinterpret_cast<const void *>(sifas_mat_address(0x10480dac0ULL, slide));
    api->raw_types[MIU_CHEEK] = reinterpret_cast<const void *>(sifas_mat_address(0x104886530ULL, slide));
    api->raw_types[MIU_PROP_BASIC] = reinterpret_cast<const void *>(sifas_mat_address(0x104802eb0ULL, slide));
    api->raw_types[MIU_SPOTLIGHT_AREA] = reinterpret_cast<const void *>(sifas_mat_address(0x10480f640ULL, slide));
    api->raw_types[MIU_SPOTLIGHT_SHAFT] = reinterpret_cast<const void *>(sifas_mat_address(0x10480f670ULL, slide));
    *preferred = {1, 0x101828e5cULL, 0x101829cf4ULL, 0x10148a7a8ULL, 0x101520e18ULL, 0x104883020ULL, 0x1014836b0ULL};
    return true;
  }
  if (region == 2) {
    api->array_clone = reinterpret_cast<decltype(api->array_clone)>(sifas_mat_address(0x103b5d680ULL, slide));
    api->type_from_handle = reinterpret_cast<decltype(api->type_from_handle)>(sifas_mat_address(0x103b87f1cULL, slide));
    api->handle_alloc = reinterpret_cast<decltype(api->handle_alloc)>(sifas_mat_address(0x103a82330ULL, slide));
    api->handle_target = reinterpret_cast<decltype(api->handle_target)>(sifas_mat_address(0x103a821ecULL, slide));
    api->handle_free = reinterpret_cast<decltype(api->handle_free)>(sifas_mat_address(0x103a823fcULL, slide));
    api->instance_id = reinterpret_cast<decltype(api->instance_id)>(sifas_mat_address(0x10393ebc4ULL, slide));
    api->object_alive = reinterpret_cast<decltype(api->object_alive)>(sifas_mat_address(0x10393ef18ULL, slide));
    api->component_game_object = reinterpret_cast<decltype(api->component_game_object)>(sifas_mat_address(0x103924f80ULL, slide));
    api->component_transform = reinterpret_cast<decltype(api->component_transform)>(sifas_mat_address(0x103924f14ULL, slide));
    api->components_in_children = reinterpret_cast<decltype(api->components_in_children)>(sifas_mat_address(0x10392cc08ULL, slide));
    api->is_instance = reinterpret_cast<decltype(api->is_instance)>(sifas_mat_address(0x103ae3198ULL, slide));
    api->is_child_of = reinterpret_cast<decltype(api->is_child_of)>(sifas_mat_address(0x1039622ecULL, slide));
    api->shared_materials = reinterpret_cast<decltype(api->shared_materials)>(sifas_mat_address(0x10394d20cULL, slide));
    api->set_shared_materials = reinterpret_cast<decltype(api->set_shared_materials)>(sifas_mat_address(0x10394d210ULL, slide));
    api->instantiate = reinterpret_cast<decltype(api->instantiate)>(sifas_mat_address(0x10393f144ULL, slide));
    api->destroy = reinterpret_cast<decltype(api->destroy)>(sifas_mat_address(0x10393f54cULL, slide));
    api->get_name = reinterpret_cast<decltype(api->get_name)>(sifas_mat_address(0x10393af54ULL, slide));
    api->set_name = reinterpret_cast<decltype(api->set_name)>(sifas_mat_address(0x10393f054ULL, slide));
    api->raw_types[MIU_RENDERER] = reinterpret_cast<const void *>(sifas_mat_address(0x1047e8100ULL, slide));
    api->raw_types[MIU_MONOBEHAVIOUR] = reinterpret_cast<const void *>(sifas_mat_address(0x1047cc160ULL, slide));
    api->raw_types[MIU_MATERIAL] = reinterpret_cast<const void *>(sifas_mat_address(0x1047ca860ULL, slide));
    api->raw_types[MIU_AMBIENT] = reinterpret_cast<const void *>(sifas_mat_address(0x1047f9c60ULL, slide));
    api->raw_types[MIU_RIMLIGHT] = reinterpret_cast<const void *>(sifas_mat_address(0x1047f9c90ULL, slide));
    api->raw_types[MIU_BODY_PARTS] = reinterpret_cast<const void *>(sifas_mat_address(0x1047f9c00ULL, slide));
    api->raw_types[MIU_CHEEK] = reinterpret_cast<const void *>(sifas_mat_address(0x104872640ULL, slide));
    api->raw_types[MIU_PROP_BASIC] = reinterpret_cast<const void *>(sifas_mat_address(0x1047eeff0ULL, slide));
    api->raw_types[MIU_SPOTLIGHT_AREA] = reinterpret_cast<const void *>(sifas_mat_address(0x1047fb780ULL, slide));
    api->raw_types[MIU_SPOTLIGHT_SHAFT] = reinterpret_cast<const void *>(sifas_mat_address(0x1047fb7b0ULL, slide));
    *preferred = {2, 0x1018245c8ULL, 0x101825460ULL, 0x101486380ULL, 0x10151c73cULL, 0x10486f130ULL, 0x10147e580ULL};
    return true;
  }
  return false;
}
#endif
