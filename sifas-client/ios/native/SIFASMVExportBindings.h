#pragma once
#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdbool.h>

/* Exact GL 3.12.0 native adapter. Hooks are installed by the offline IPA
 * patcher; this module never changes executable memory. All operations and
 * callbacks below run on Unity's main thread. */
@class ELMVPixelFrame;

typedef struct {
    void *context;
    /* Called before a full Unity simulation frame. False keeps the game
     * clocks and discrete spring integration frozen while UIKit stays live.
     * captureIndex=-1 requests an intermediate physics frame. Tick zero is
     * the initial image, before the first positive simulation delta. */
    bool (*nextStep)(void *context, uint64_t *simulationTick, int64_t *captureIndex);
    /* Retained top-to-bottom opaque BGRA pixel buffer, immutable through Retry
     * and encoder ownership. No steps are granted before frame acceptance. */
    void (*frame)(void *context, ELMVPixelFrame *pixels, NSUInteger rowBytes, int64_t captureIndex);
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
    void *(*queueMemberAssets)(int32_t liveMasterId, uint64_t deckType, const void *methodInfo);
    void *(*queueMemberMap)(void *liveMaster, uint64_t deckType, const void *methodInfo);
    void *(*queueSuitMap)(void *liveMaster, uint64_t deckType, const void *methodInfo);
    int32_t (*queueViewStatus)(void *member, const void *methodInfo);
    void *(*queueNextSceneData)(void *scene, const void *methodInfo);
    void *(*queueQuality)(const void *methodInfo);
    void *(*queueLiveVO)(const void *methodInfo);
} SIFASMVBindingOriginals;

FOUNDATION_EXPORT BOOL SIFASMVBindingsInstallOriginals(const SIFASMVBindingOriginals *originals, NSError **error);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsStatus(void);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsSongSnapshot(void);
FOUNDATION_EXPORT NSDictionary *SIFASMVBindingsAudioSelection(void);
/* The loaded MV's selection only when the scene load itself confirms it: a
 * completed queue navigation opened it, or its load was fully observed. Use it
 * to decide whether the loaded scene already is a queued entry. */
FOUNDATION_EXPORT NSDictionary *_Nullable SIFASMVBindingsQueueSelection(void);
/* For "Add to export queue": like SIFASMVBindingsQueueSelection, but when the
 * load observation is incomplete the missing parts are read from live game
 * state (never for a load a queue navigation overrode without confirming it).
 * On nil, check receives the exact failed precondition as a stable identifier
 * (for example "cached.ready:final-camera" or "formation.members"), detail the
 * values the check read, and transient whether the condition can clear while
 * the MV keeps loading. On success, detail names where each part of the
 * selection came from (load observation, queue navigation or live state). */
FOUNDATION_EXPORT NSDictionary *_Nullable SIFASMVBindingsQueueSelectionChecked(NSString *_Nullable *_Nullable check,
                                                                             NSString *_Nullable *_Nullable detail,
                                                                             BOOL *_Nullable transient);
/* Nil when SIFASMVBindingsQueueOpen can decode a saved selection; otherwise
 * "selection.legacy-suit" for an entry an earlier build saved with suit id 1
 * (it can never be restored) or "selection.invalid". */
FOUNDATION_EXPORT NSString *_Nullable SIFASMVBindingsQueueSelectionDefect(NSDictionary *selection);
FOUNDATION_EXPORT BOOL SIFASMVBindingsQueueOpen(NSDictionary *selection,
                                              void (^completion)(NSString *_Nullable error));
FOUNDATION_EXPORT void SIFASMVBindingsQueueCancelNavigation(void);
FOUNDATION_EXPORT BOOL SIFASMVBindingsBegin(SIFASMVBindingConfiguration configuration,
                                          SIFASMVBindingCallbacks callbacks, NSError **error);
FOUNDATION_EXPORT void SIFASMVBindingsEnd(void);

#if defined(SIFAS_STANDALONE)
/* A main-thread export lease for the exact standalone game on Apple Silicon. */
FOUNDATION_EXPORT BOOL SIFASMVBindingsBeginMacBackgroundRender(void);
FOUNDATION_EXPORT void SIFASMVBindingsEndMacBackgroundRender(void);
FOUNDATION_EXPORT BOOL SIFASMVBindingsMacBackgroundRenderFallbackActive(void);
#endif

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
void *SIFASMVQueueMemberAssets(int32_t liveMasterId, uint64_t deckType, const void *methodInfo);
void *SIFASMVQueueMemberMap(void *liveMaster, uint64_t deckType, const void *methodInfo);
void *SIFASMVQueueSuitMap(void *liveMaster, uint64_t deckType, const void *methodInfo);
int32_t SIFASMVQueueViewStatus(void *member, const void *methodInfo);
void *SIFASMVQueueNextSceneData(void *scene, const void *methodInfo);
void *SIFASMVQueueQuality(const void *methodInfo);
void *SIFASMVQueueLiveVO(const void *methodInfo);
#ifdef __cplusplus
}
#endif
