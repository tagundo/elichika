// Copyright (c) 2026 Elichika contributors. MIT licensed.
// In-process iOS form of the existing bounded scalar UnityCrunch decoder.
// Retains upstream checksums, authored-mip validation and pixel channel order.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <vector>
#include "unitycrunch/crn_decomp.h"
#include "etc.h"

namespace {
constexpr size_t MiB = 1024 * 1024;
constexpr size_t MaxInput = 128 * MiB, MaxMemory = 256 * MiB, MaxCrunch = 64 * MiB;
constexpr uint64_t Magic = UINT64_C(0x454c494348494b41);
struct Budget { size_t used, limit; };
struct alignas(std::max_align_t) Allocation { size_t size; uint64_t magic; };
std::mutex slot;
void* allocate(void* pointer, size_t size, size_t* actual, bool movable, void* opaque) {
    auto& budget = *static_cast<Budget*>(opaque);
    auto* old = pointer ? static_cast<Allocation*>(pointer) - 1 : nullptr;
    if (old && old->magic != Magic) return nullptr;
    const size_t before = old ? old->size : 0;
    if (actual) *actual = before;
    if (!size) {
        if (old) { budget.used -= before; old->magic = 0; std::free(old); }
        if (actual) *actual = 0;
        return nullptr;
    }
    if (old && !movable) return size <= before ? pointer : nullptr;
    if (size > budget.limit || budget.used - before > budget.limit - size) return nullptr;
    auto* result = static_cast<Allocation*>(std::realloc(old, sizeof(Allocation) + size));
    if (!result) return nullptr;
    budget.used = budget.used - before + size;
    result->size = size; result->magic = Magic;
    if (actual) *actual = size;
    return result + 1;
}
size_t allocation_size(void* pointer, void*) {
    if (!pointer) return 0;
    auto* block = static_cast<Allocation*>(pointer) - 1;
    return block->magic == Magic ? block->size : 0;
}
struct Callbacks {
    Callbacks(Budget* budget) { unitycrnd::crnd_set_memory_callbacks(allocate, allocation_size, budget); }
    ~Callbacks() { unitycrnd::crnd_set_memory_callbacks(nullptr, nullptr, nullptr); }
};
struct Context {
    unitycrnd::crnd_unpack_context value;
    ~Context() { if (value) unitycrnd::crnd_unpack_end(value); }
};
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
void span(size_t offset, size_t size, size_t header, size_t total) {
    check(offset <= total && size <= total - offset && (!size || offset >= header), "Invalid Crunch data offsets");
}
}

extern "C" __attribute__((visibility("default")))
int elichika_texture65_decode(const uint8_t* data, size_t size, unsigned width, unsigned height,
                             unsigned mip, uint8_t* rgba, size_t capacity, char* error, size_t error_capacity) {
    std::lock_guard<std::mutex> lease(slot);
    try {
        check(data && rgba && width && height && width <= 8192 && height <= 8192 &&
              size_t(width) * height <= 4096 * 4096 && mip <= 13, "Texture dimensions exceed the limit");
        const unsigned selected_width = std::max(1U, width >> mip), selected_height = std::max(1U, height >> mip);
        const size_t pixels = size_t(selected_width) * selected_height, output_size = pixels * 4;
        check(capacity == output_size, "RGBA output capacity differs");
        check(size >= sizeof(unitycrnd::crn_header) && size <= MaxInput, "Encoded texture size is invalid");
        const auto* header = reinterpret_cast<const unitycrnd::crn_header*>(data);
        const unsigned levels = header->m_levels;
        unsigned max_levels = 1;
        for (unsigned edge = std::max(width, height); edge > 1; edge >>= 1) ++max_levels;
        const size_t header_bytes = header->m_header_size;
        check(header->m_sig == unitycrnd::crn_header::cCRNSigValue && levels && levels <= max_levels && mip < levels &&
              header_bytes == offsetof(unitycrnd::crn_header, m_level_ofs) + 4 * levels && header_bytes <= size &&
              header->m_data_size == size && header->m_width == width && header->m_height == height &&
              header->m_faces == 1 && header->m_flags == 0 && header->m_format == cCRNFmtETC2A,
              "Unsupported or inconsistent UnityCrunch ETC2A header");
        for (const auto* palette : {&header->m_color_endpoints, &header->m_color_selectors,
                                   &header->m_alpha_endpoints, &header->m_alpha_selectors})
            span(palette->m_ofs, palette->m_size, header_bytes, size);
        span(header->m_tables_ofs, header->m_tables_size, header_bytes, size);
        size_t previous = header_bytes;
        const uint8_t* offsets = data + offsetof(unitycrnd::crn_header, m_level_ofs);
        for (unsigned level = 0; level < levels; ++level) {
            const auto* at = offsets + 4 * level;
            const size_t offset = (size_t(at[0]) << 24) | (size_t(at[1]) << 16) | (size_t(at[2]) << 8) | at[3];
            check(offset >= previous && offset < size, "Invalid Crunch mip offsets");
            previous = offset;
        }
        unitycrnd::crn_file_info file;
        check(unitycrnd::crnd_validate_file(data, size, &file), "Crunch checksum validation failed");
        unitycrnd::crn_texture_info info;
        check(unitycrnd::crnd_get_texture_info(data, size, &info) && info.m_bytes_per_block == 16, "Invalid ETC2A block layout");
        const size_t pitch = ((size_t(selected_width) + 3) / 4) * 16;
        const size_t block_bytes = pitch * ((size_t(selected_height) + 3) / 4);
        const size_t fixed = size + block_bytes + output_size * 2;
        check(fixed < MaxMemory, "Texture exceeds the decoder memory budget");
        Budget budget{0, std::min(MaxCrunch, MaxMemory - fixed)};
        Callbacks callbacks(&budget);
        std::vector<uint8_t> blocks(block_bytes);
        std::vector<uint32_t> bgra(pixels);
        Context context{unitycrnd::crnd_unpack_begin(data, size)};
        check(context.value, "Cannot initialize bounded Crunch decoder");
        void* destination = blocks.data();
        check(unitycrnd::crnd_unpack_level(context.value, &destination, block_bytes, pitch, mip), "Crunch level decode failed");
        check(decode_etc2a8(blocks.data(), selected_width, selected_height, bgra.data()), "ETC2A pixel decode failed");
        const auto* bytes = reinterpret_cast<const uint8_t*>(bgra.data());
        for (size_t pixel = 0; pixel < pixels; ++pixel) {
            rgba[pixel * 4] = bytes[pixel * 4 + 2]; rgba[pixel * 4 + 1] = bytes[pixel * 4 + 1];
            rgba[pixel * 4 + 2] = bytes[pixel * 4]; rgba[pixel * 4 + 3] = bytes[pixel * 4 + 3];
        }
        return 0;
    } catch (const std::exception& failure) {
        if (error && error_capacity) {
            std::strncpy(error, failure.what(), error_capacity - 1);
            error[error_capacity - 1] = 0;
        }
        return 1;
    }
}
