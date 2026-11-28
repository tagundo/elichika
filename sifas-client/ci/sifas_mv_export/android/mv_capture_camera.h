#ifndef SIFAS_MV_CAPTURE_CAMERA_H
#define SIFAS_MV_CAPTURE_CAMERA_H
#include <stddef.h>
#include <stdint.h>

// 128 core cameras, cut-in, two overlays, final compositor, four split views.
static constexpr size_t sifas_mv_capture_camera_capacity = 136;

enum class SifasMvWindowChange {Unavailable, Stable, Changed};
struct SifasMvWindowGeometry {
    int32_t width, height;
    bool unavailable;
    // Returning from a removed surface establishes a new render boundary
    // even when Android restores the same window dimensions.
    SifasMvWindowChange update(int32_t next_width, int32_t next_height) {
        if (next_width <= 0 || next_height <= 0) {
            unavailable = true;
            return SifasMvWindowChange::Unavailable;
        }
        const bool changed = unavailable || width != next_width || height != next_height;
        width = next_width;
        height = next_height;
        unavailable = false;
        return changed ? SifasMvWindowChange::Changed : SifasMvWindowChange::Stable;
    }
    bool accepts_render(int32_t rendered_width, int32_t rendered_height) const {
        return !unavailable && rendered_width > 0 && rendered_height > 0 &&
            width == rendered_width && height == rendered_height;
    }
};

// Observations belong to one Unity render pass. Split meshes sample their
// own camera targets, so a base-camera callback or an older target cannot
// stand in for a split camera that still has to render.
struct SifasMvFrameCameras {
    static constexpr size_t split_count = 4;
    const void *split_targets[split_count]{};
    bool stage_rendered = false;
    bool main_rendered = false;

    void reset() { *this = {}; }
    void acknowledge_stage(bool main_camera) {
        stage_rendered = true;
        main_rendered = main_rendered || main_camera;
    }
    void acknowledge_split(size_t index, const void *target) {
        if (index < split_count) split_targets[index] = target;
    }
    bool ready(uint8_t active_split_mask, bool main_camera_active, const void *const *current_targets) const {
        if (!active_split_mask) return stage_rendered;
        if (!current_targets || active_split_mask >= (1u << split_count) ||
                (main_camera_active && !main_rendered)) return false;
        for (size_t i = 0; i < split_count; ++i) {
            if ((active_split_mask & (1u << i)) &&
                    (!current_targets[i] || split_targets[i] != current_targets[i])) return false;
        }
        return true;
    }
};

template<class Snapshot>
inline bool sifas_mv_capture_camera_acknowledges(
        const Snapshot *cameras, size_t count, const void *camera) {
    if (!camera || !cameras || count > sifas_mv_capture_camera_capacity) return false;
    for (size_t i = 0; i < count; ++i)
        if (cameras[i].stage_source && cameras[i].camera == camera) return true;
    return false;
}
#endif
