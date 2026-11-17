#ifndef SIFAS_MV_CAPTURE_CAMERA_H
#define SIFAS_MV_CAPTURE_CAMERA_H
#include <stddef.h>

// 128 core cameras, cut-in, two overlays, final compositor, four split views.
static constexpr size_t sifas_mv_capture_camera_capacity = 136;

template<class Snapshot>
inline bool sifas_mv_capture_camera_acknowledges(
        const Snapshot *cameras, size_t count, const void *camera) {
    if (!camera || !cameras || count > sifas_mv_capture_camera_capacity) return false;
    for (size_t i = 0; i < count; ++i)
        if (cameras[i].stage_source && cameras[i].camera == camera) return true;
    return false;
}
#endif
