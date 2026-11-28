#include "mv_capture_camera.h"
#include <assert.h>
#include <stdio.h>

struct CameraSnapshot { void *camera; bool stage_source; bool enabled; };

static void test_split_frame_freshness() {
    int textures[5] = {};
    const void *targets[] = {&textures[0], &textures[1], &textures[2], &textures[3]};
    SifasMvFrameCameras frame{};
    frame.reset();
    assert(!frame.ready(0, true, nullptr));
    frame.acknowledge_stage(true);
    assert(frame.ready(0, true, nullptr));

    // The next frame switches to subcamera 1 with the main camera off.
    // A late stage callback or a render to its old texture is insufficient.
    frame.reset();
    frame.acknowledge_stage(true);
    frame.acknowledge_split(0, &textures[4]);
    assert(!frame.ready(0x1, false, targets));
    assert(!frame.ready(0x1, false, nullptr));
    frame.acknowledge_split(0, targets[0]);
    assert(frame.ready(0x1, false, targets));

    // A main-camera picture and two split views can contribute together.
    frame.reset();
    frame.acknowledge_stage(false); // A stage callback from the cut-in.
    frame.acknowledge_split(3, targets[3]);
    frame.acknowledge_split(3, targets[3]);
    assert(!frame.ready(0x9, true, targets));
    frame.acknowledge_split(0, targets[0]);
    assert(!frame.ready(0x9, true, targets));
    frame.acknowledge_stage(true);
    assert(frame.ready(0x9, true, targets));
    assert(!frame.ready(0xf, true, targets));

    // A retry of the same simulation tick must receive all callbacks again.
    frame.reset();
    frame.acknowledge_split(0, targets[0]);
    assert(!frame.ready(0x9, false, targets));
    frame.acknowledge_split(3, targets[3]);
    assert(frame.ready(0x9, false, targets));
    targets[3] = &textures[4];
    assert(!frame.ready(0x9, false, targets));
    frame.acknowledge_split(3, targets[3]);
    assert(frame.ready(0x9, false, targets));
    targets[3] = nullptr;
    frame.acknowledge_split(3, nullptr);
    assert(!frame.ready(0x9, false, targets));

    // Returning to the ordinary stage path also requires a fresh callback.
    frame.reset();
    frame.acknowledge_split(0, targets[0]);
    assert(!frame.ready(0, true, nullptr));
    frame.acknowledge_stage(false);
    assert(frame.ready(0, true, nullptr));
}

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

    test_split_frame_freshness();

    SifasMvWindowGeometry window{1080, 2340, false};
    assert(window.update(1080, 2340) == SifasMvWindowChange::Stable);
    assert(window.accepts_render(1080, 2340));
    // If Android resizes after simulation but before rendering, the next
    // camera callback cannot acknowledge until Unity observes that geometry.
    assert(!window.accepts_render(2208, 1840));
    assert(window.update(2208, 1840) == SifasMvWindowChange::Changed);
    assert(!window.accepts_render(1080, 2340));
    assert(window.accepts_render(2208, 1840));
    assert(window.update(2208, 1840) == SifasMvWindowChange::Stable);

    // A transient presentation-surface loss invalidates readiness even when
    // the backing gaming window returns at exactly its prior dimensions.
    assert(window.update(0, 1840) == SifasMvWindowChange::Unavailable);
    assert(!window.accepts_render(2208, 1840));
    assert(!window.accepts_render(0, 1840));
    assert(window.update(2208, 1840) == SifasMvWindowChange::Changed);
    assert(window.accepts_render(2208, 1840));
    assert(window.update(1080, 2340) == SifasMvWindowChange::Changed);
    assert(!window.accepts_render(2208, 1840));
    puts("PASS camera acknowledgments, split target freshness, and resize boundaries");
}
