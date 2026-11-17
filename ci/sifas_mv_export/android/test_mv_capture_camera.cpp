#include "mv_capture_camera.h"
#include <assert.h>
#include <stdio.h>

struct CameraSnapshot { void *camera; bool stage_source; bool enabled; };

int main() {
    int identities[9] = {};
    CameraSnapshot cameras[] = {
        {&identities[0], true, true},   // Main stage camera.
        {&identities[1], true, false},  // Cut-in.
        {&identities[2], false, true},  // Stage overlay.
        {&identities[3], false, false}, // Cut-in overlay.
        {&identities[4], true, false}, {&identities[5], true, false},
        {&identities[6], true, false}, {&identities[7], true, false}
    };
    const size_t count = sizeof(cameras) / sizeof(cameras[0]);
    static_assert(sifas_mv_capture_camera_capacity == 128 + 1 + 2 + 1 + 4,
                  "Every bounded camera owner must fit");
    bool frame_ready = false;
    auto callback = [&](void *camera) {
        frame_ready = frame_ready ||
            sifas_mv_capture_camera_acknowledges(cameras, count, camera);
    };
    // Frame 240: the normal stage camera supplies readiness.
    callback(cameras[0].camera);
    assert(frame_ready);
    frame_ready = false;

    // Frame 242: the authored full split disables the main camera.
    cameras[0].enabled = false;
    for (size_t i = 4; i < count; ++i) cameras[i].enabled = true;
    callback(cameras[2].camera);
    callback(cameras[3].camera);
    callback(&identities[8]);
    assert(!frame_ready);
    // Each of the four actual split callbacks can unblock this frame.
    for (size_t i = 4; i < count; ++i) {
        assert(cameras[i].enabled);
        frame_ready = false;
        callback(cameras[i].camera);
        assert(frame_ready);
        callback(cameras[i].camera);
        callback(cameras[2].camera);
        assert(frame_ready); // Duplicate and unrelated callbacks are idempotent.
    }
    frame_ready = false;
    callback(cameras[1].camera);
    assert(frame_ready); // The cut-in remains an accepted stage source.
    assert(!sifas_mv_capture_camera_acknowledges(cameras, count, nullptr));
    assert(!sifas_mv_capture_camera_acknowledges(cameras, 0, cameras[4].camera));
    assert(!sifas_mv_capture_camera_acknowledges<CameraSnapshot>(nullptr, count, cameras[4].camera));
    assert(!sifas_mv_capture_camera_acknowledges(cameras,
        sifas_mv_capture_camera_capacity + 1, cameras[4].camera));
    puts("PASS base/cut-in and all four split callbacks acknowledge capture; overlay/unowned callbacks do not");
}
