/* Host regression for material binding with the offline MV ELF extension.
 * Only synthetic mapped data and loader metadata are used; no ARM/game code
 * executes. Build with g++ -std=c++17 -fno-exceptions -fno-rtti -pthread.
 * MATERIAL_BINDING_SOURCE can select the pre-fix source to reproduce failure.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <link.h>
#include <sys/mman.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>

static dl_phdr_info *loaded_image;
static int test_dl_iterate_phdr(int (*callback)(dl_phdr_info *, size_t, void *),
                                void *context);
#define dl_iterate_phdr test_dl_iterate_phdr
#ifndef MATERIAL_BINDING_SOURCE
#define MATERIAL_BINDING_SOURCE "native/material_android_binding.cc"
#endif
#include MATERIAL_BINDING_SOURCE
#undef dl_iterate_phdr

static int test_dl_iterate_phdr(int (*callback)(dl_phdr_info *, size_t, void *),
                                void *context) {
    return loaded_image ? callback(loaded_image, sizeof(*loaded_image), context) : 0;
}

static unsigned prepares;
static bool allow_prepare;
static MiAndroidOriginals prepared;
static int prepare(void *, const MiAndroidOriginals *value) {
    ++prepares;
    prepared = *value;
    return allow_prepare;
}
static void early(void *, void *, void *, void *) {}
static void reset(void *, void *) {}
static uint64_t identity(void *, void *) { return 1; }
static void cleanup(void *, uint64_t) {}
static const MiAndroidRuntimeOps ops{nullptr, prepare, early, reset, identity, cleanup, nullptr};

struct Image {
    void *memory;
    size_t bytes;
    const Layout &layout;
    ElfW(Phdr) headers[15]{};
    dl_phdr_info info{};
    MiAndroidSidecar *sidecar;

    Image(size_t layout_index, unsigned count) : layout(layouts[layout_index]) {
        bytes = layout.sidecar_va + 3 * 65536;
        memory = mmap(nullptr, bytes, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(memory != MAP_FAILED);
        info.dlpi_addr = reinterpret_cast<uintptr_t>(memory);
        info.dlpi_name = "/synthetic/libil2cpp.so";
        info.dlpi_phdr = headers;
        info.dlpi_phnum = count;
        headers[0].p_type = PT_LOAD;
        headers[0].p_flags = PF_R | PF_X;
        headers[0].p_filesz = headers[0].p_memsz = layout.sidecar_va;
        headers[1].p_type = PT_LOAD;
        headers[1].p_flags = PF_R | PF_W;
        headers[1].p_vaddr = headers[1].p_offset = layout.sidecar_va;
        headers[1].p_filesz = headers[1].p_memsz = 64;
        headers[1].p_align = 65536;
        // Two distinct MV extension loads; the material loads remain intact.
        headers[12].p_type = headers[13].p_type = PT_LOAD;
        headers[12].p_flags = PF_R | PF_X;
        headers[13].p_flags = PF_R | PF_W;
        for (unsigned n = 12; n < 14; ++n) {
            headers[n].p_vaddr = headers[n].p_offset = layout.sidecar_va + (n - 11) * 65536;
            headers[n].p_filesz = headers[n].p_memsz = n == 12 ? 4608 : 320;
            headers[n].p_align = 65536;
        }
        sidecar = reinterpret_cast<MiAndroidSidecar *>(at(layout.sidecar_va));
        memcpy(sidecar->magic, "SMATRW01", 8);
        sidecar->version = 1;
        sidecar->size = 64;
        sidecar->region = layout.region;
        for (size_t n = 0; n < 3; ++n) {
            memcpy(at(layout.hook_va[n]), &layout.hook_word[n], 4);
            memcpy(at(layout.original_va[n]), &layout.original_first_word[n], 4);
            memcpy(at(layout.bridge_va[n]), layout.bridge_bytes[n], layout.bridge_size[n]);
        }
        prepares = 0;
        allow_prepare = true;
        prepared = {};
        originals = {};
        runtime_ops = {};
        published_sidecar = nullptr;
        loaded_image = &info;
    }
    unsigned char *at(uint64_t rva) { return static_cast<unsigned char *>(memory) + rva; }
    ~Image() {
        loaded_image = nullptr;
        published_sidecar = nullptr;
        munmap(memory, bytes);
    }
    void refused(int result = MI_ANDROID_UNSUPPORTED_IMAGE) {
        assert(mi_android_try_bind_loaded(&ops) == result);
        assert(sidecar->ready == 0);
        assert(prepares == (result == MI_ANDROID_PREPARE_FAILED ? 1u : 0u));
    }
};

int main() {
    unsigned checks = 0;
    for (size_t region = 0; region < 2; ++region) {
        for (unsigned count : {12u, 14u}) {
            Image image(region, count);
            assert(mi_android_try_bind_loaded(&ops) == MI_ANDROID_BOUND);
            assert(prepares == 1 && prepared.region == image.layout.region);
            assert(prepared.native_load_bias == image.info.dlpi_addr);
            assert(prepared.original_culler == image.info.dlpi_addr + image.layout.original_va[0]);
            assert(prepared.original_reset == image.info.dlpi_addr + image.layout.original_va[1]);
            assert(prepared.original_term == image.info.dlpi_addr + image.layout.original_va[2]);
            assert(image.sidecar->ready == 1 && image.sidecar->early_callback &&
                   image.sidecar->pre_reset_callback && image.sidecar->destroy_callback);
            assert(mi_android_try_bind_loaded(&ops) == MI_ANDROID_ALREADY_BOUND);
            assert(prepares == 1);
            ++checks;
        }
        for (unsigned count : {0u, 11u, 13u, 15u}) {
            Image image(region, count); image.refused(); ++checks;
        }
        for (unsigned failure = 0; failure < 14; ++failure) {
            Image image(region, 14);
            switch (failure) {
            case 0: image.info.dlpi_phdr = nullptr; break;
            case 1: image.sidecar->magic[0] ^= 1; break;
            case 2: image.sidecar->version = 2; break;
            case 3: image.sidecar->size = 320; break;
            case 4: image.sidecar->region ^= 3; break;
            case 5: image.sidecar->reserved[0] = 1; break;
            case 6: image.sidecar->early_callback = 1; break;
            case 7: image.headers[1].p_flags = PF_R | PF_W | PF_X; break;
            case 8: image.headers[1].p_memsz = 320; break;
            case 9: image.headers[1].p_align = 16384; break;
            case 10: image.headers[1].p_offset += 4; break;
            case 11: image.at(image.layout.hook_va[0])[0] ^= 1; break;
            case 12: image.at(image.layout.bridge_va[1])[7] ^= 1; break;
            case 13: image.at(image.layout.original_va[2])[0] ^= 1; break;
            }
            image.refused(); ++checks;
        }
        { Image image(region, 14); allow_prepare = false;
          image.refused(MI_ANDROID_PREPARE_FAILED); ++checks; }
        { Image image(region, 14); image.info.dlpi_name = "/synthetic/libunity.so";
          image.refused(MI_ANDROID_WAITING); ++checks; }
    }
    assert(mi_android_try_bind_loaded(nullptr) == MI_ANDROID_BAD_OPS);
    printf("PASS: %u GL/JP layout, strict-refusal and idempotence cases; no game code executed.\n", checks + 1);
}
