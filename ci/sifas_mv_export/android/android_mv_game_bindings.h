#ifndef SIFAS_ANDROID_MV_GAME_BINDINGS_H
#define SIFAS_ANDROID_MV_GAME_BINDINGS_H
#include "android_mv_encoder_bridge.h"
#include "android_mv_audio_provider.h"
#include <stdint.h>
#include <string.h>
/* Snapshot begins at TimeManager+0x30. Keep live engine counters/flags intact. */
static inline void amv_restore_offline_clock(void *manager,const uint8_t *snapshot,double elapsed,int same_scene,int32_t owned_capture_fps) {
    if(!same_scene){int32_t capture_fps=0;memcpy(&capture_fps,(uint8_t *)manager+0xd8,4);
        if(capture_fps==owned_capture_fps)memcpy((uint8_t *)manager+0xd8,snapshot+0xd8-0x30,4);
        return;}
    static const size_t doubles[]={0x60,0x68,0x70,0x90,0x98,0xa0};
    static const size_t singles[]={0x78,0x7c,0xa8,0xac};
    for(size_t i=0;i<sizeof(doubles)/sizeof(doubles[0]);i++)
        memcpy((uint8_t *)manager+doubles[i],snapshot+doubles[i]-0x30,8);
    for(size_t i=0;i<sizeof(singles)/sizeof(singles[0]);i++)
        memcpy((uint8_t *)manager+singles[i],snapshot+singles[i]-0x30,4);
    memcpy((uint8_t *)manager+0xd8,snapshot+0xd8-0x30,4);memcpy((uint8_t *)manager+0xfc,snapshot+0xfc-0x30,4);
    for(size_t offset=0xe0;offset<=0xe8;offset+=8){double origin=0;memcpy(&origin,snapshot+offset-0x30,8);origin+=elapsed;memcpy((uint8_t *)manager+offset,&origin,8);}
}
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    uint32_t width,height,fps; /* fps30/60/120; deterministic simulation=max(60,fps)Hz. */
    uint32_t sample_rate,channels;
    uint64_t video_frames,audio_frames;
    uint64_t song_fingerprint; /* Returned by the Unity-thread song query. */
} AmvGameConfig;
typedef struct {
    void *context;
    /* Immutable selected-cue PCM, already decoded/aligned/gain-adjusted before
     * Begin. Fill exactly count interleaved PCM16 sample frames. No network,
     * decoding, UI calls or unbounded wait is allowed from this Unity callback.
     * Return count on success or a negative value on error. */
    int (*pcm)(void *,uint64_t sample_index,uint32_t count,int16_t *destination);
    void (*progress)(void *,uint64_t accepted_video_frames,uint64_t total);
    void (*finished)(void *,const char *private_mp4_path);
    void (*failed)(void *,const char *message);
} AmvGameCallbacks;
typedef struct {
    uint32_t installed,ready,active,region;
    int32_t music_length_ms,current_time_ms;
    float gain;
    uint64_t simulation_tick,accepted_video_frames;
    char cue_sheet[256],cue_name[256],phase[80],failure[256];
    uint64_t song_fingerprint,source_samples;
    uint32_t wave_id,streaming,source_rate,source_channels;
    char acb_path[AMV_AUDIO_PATH_CAP],awb_path[AMV_AUDIO_PATH_CAP];
} AmvGameStatus;
typedef void (*AmvSongQueried)(void *context,const AmvGameStatus *,const AmvAudioSelection *,const char *error);
/* Async UI request. Metadata is copied only on the original Unity thread; the
 * callback owns no managed pointers and must copy selections before returning. */
int amv_game_request_song_query(void *context,AmvSongQueried);
/* Loader-only: inspect SHA-bound offline sidecars and dlsym original IL2CPP C
 * APIs; no managed/Unity call or thread attachment. Safe to retry before load.
 * 1=bound,0=waiting,-1=unsupported/corrupt image/contract. */
int amv_game_try_bind_loaded(void);
/* Called from an app Java thread. Retains encoder before queuing setup; actual
 * scene/clock/render operations run on the verified original Unity thread.
 * One request/session at a time. Java encoder counts must match this config.
 * Provider context remains alive until finished/failed notification. */
int amv_game_request_begin(JNIEnv *,jobject encoder,const AmvGameConfig *,
                           const AmvGameCallbacks *,jthrowable *error);
void amv_game_request_cancel(void);
/* Thread-safe cached observation; never invokes IL2CPP from the UI thread. */
void amv_game_get_status(AmvGameStatus *);

/* Exact offline shim ABI. Order: time,live,music,member,overlay,width,height,late,post. */
void amv_game_time_update(void *time_manager);
void amv_game_live_update(void *director,const void *method_info);
void amv_game_music_update(void *machine,const void *method_info);
void amv_game_member_update(void *members,const void *method_info);
void amv_game_overlay_render(void *overlay,void *source,void *destination,const void *method_info);
int32_t amv_game_screen_width(const void *method_info);
int32_t amv_game_screen_height(const void *method_info);
void amv_game_member_late_update(void *members,const void *method_info);
void amv_game_camera_post_render(void *camera,const void *method_info);
#ifdef __cplusplus
}
#endif
#endif
