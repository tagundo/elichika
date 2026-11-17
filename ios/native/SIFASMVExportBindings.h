#pragma once
#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdbool.h>

/* Exact GL 3.12.0 native adapter. Hooks are installed by the offline IPA
 * patcher; this module never changes executable memory. All operations and
 * callbacks below run on Unity's main thread. */
typedef struct {
    void *context;
    /* Called before a full Unity simulation frame. False keeps the game
     * clocks and discrete spring integration frozen while UIKit stays live.
     * captureIndex=-1 requests an intermediate physics frame. Tick zero is
     * the initial image, before the first positive simulation delta. */
    bool (*nextStep)(void *context, uint64_t *simulationTick, int64_t *captureIndex);
    /* Owns a single immutable top-to-bottom BGRA8 copy. The caller must stop
     * granting steps until its bounded encoder queue accepts this frame. */
    void (*frame)(void *context, NSData *pixels, NSUInteger rowBytes, int64_t captureIndex);
    void (*failed)(void *context, NSString *message);
} SIFASMVBindingCallbacks;

typedef struct {
    uint32_t width, height;
    uint32_t simulationHz; /* max(60, fps), fixed game clock. */
    uint32_t outputFps; /* 30, 60 or 120; no real-time throughput gate. */
} SIFASMVBindingConfiguration;

/* Original/trampoline entrypoints supplied by the SHA-pinned offline shim.
 * Every managed method has its real trailing MethodInfo* argument. */
typedef struct {
    void (*timeUpdate)(void *timeManager);
    void (*liveUpdate)(void *director, const void *methodInfo);
    void (*musicUpdate)(void *musicMachine, const void *methodInfo);
    void (*memberUpdate)(void *memberManager, const void *methodInfo);
    void (*overlayRender)(void *overlay, void *source, void *destination, const void *methodInfo);
    int32_t (*screenWidth)(const void *methodInfo);
    int32_t (*screenHeight)(const void *methodInfo);
    void (*memberLateUpdate)(void *memberManager, const void *methodInfo);
    void (*cameraPostRender)(void *camera, const void *methodInfo);
} SIFASMVBindingOriginals;

FOUNDATION_EXPORT BOOL SIFASMVBindingsInstallOriginals(const SIFASMVBindingOriginals *originals, NSError **error);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsStatus(void);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsSongSnapshot(void);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsAudioSelection(void);
FOUNDATION_EXPORT BOOL SIFASMVBindingsBegin(SIFASMVBindingConfiguration configuration,
                                          SIFASMVBindingCallbacks callbacks, NSError **error);
FOUNDATION_EXPORT void SIFASMVBindingsEnd(void);

#ifdef __cplusplus
extern "C" {
#endif
/* Published as RW sidecar callbacks; exported for offline shim binding. */
void SIFASMVTimeUpdate(void *timeManager);
void SIFASMVLiveUpdate(void *director, const void *methodInfo);
void SIFASMVMusicUpdate(void *musicMachine, const void *methodInfo);
void SIFASMVMemberUpdate(void *memberManager, const void *methodInfo);
void SIFASMVOverlayRender(void *overlay, void *source, void *destination, const void *methodInfo);
int32_t SIFASMVScreenWidth(const void *methodInfo);
int32_t SIFASMVScreenHeight(const void *methodInfo);
void SIFASMVMemberLateUpdate(void *memberManager, const void *methodInfo);
void SIFASMVCameraPostRender(void *camera, const void *methodInfo);
#ifdef __cplusplus
}
#endif
