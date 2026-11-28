#ifndef SIFAS_ANDROID_MV_AUDIO_PROVIDER_H
#define SIFAS_ANDROID_MV_AUDIO_PROVIDER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define AMV_AUDIO_PATH_CAP 4096
#define AMV_AUDIO_ABI 1
typedef struct {
    uint32_t abi_version;
    /* Copies from the loaded CriAtomCueSheet, never a page/file-picker path. */
    char acb_path[AMV_AUDIO_PATH_CAP],awb_path[AMV_AUDIO_PATH_CAP];
    uint32_t wave_id,streaming,sample_rate,channels;
    uint64_t source_samples; /* Exact CRI waveform/header sample frames. */
    float gain;
    int32_t music_length_ms,start_time_ms,source_offset_ms;
} AmvAudioSelection;
typedef struct {
    uint32_t abi_version,sample_rate,channels,bytes_per_frame,wave_id;
    uint64_t audio_frames,source_frames;
    int64_t start_sample,source_offset_samples;
    uint32_t decoder; /* 1=CLHCA, 2=scalar ADX. */
} AmvAudioInfo;
typedef enum {
    AMV_AUDIO_OK=0,AMV_AUDIO_ARGUMENT=1,AMV_AUDIO_SOURCE=2,
    AMV_AUDIO_BANK=3,AMV_AUDIO_FORMAT=4,AMV_AUDIO_CRYPT=5,
    AMV_AUDIO_LIMIT=6,AMV_AUDIO_SPACE=7,AMV_AUDIO_IO=8,
    AMV_AUDIO_CANCELLED=9,AMV_AUDIO_CHANGED=10,AMV_AUDIO_MEMORY=11
} AmvAudioCode;
typedef struct { int code;char message[256]; } AmvAudioError;
typedef struct AmvAudioProvider AmvAudioProvider;
typedef int (*AmvAudioCancelled)(void *context);
/* Worker only: source <=64 MiB, aligned PCM <=96 MiB, duration <=1200 s.
 * Output is an owned private, immediately unlinked cache file. It is decoded,
 * mapped read-only and prefaulted before returning. All paths come from the
 * host/game adapter; callers must not forward arbitrary page request paths.
 * audio_frames=ceil(video_frames*fps_denominator*sample_rate/fps_numerator).
 * Cancels/errors close only owned descriptors. No shared C++ runtime needed. */
int amv_audio_prepare(const AmvAudioSelection *,const char *private_cache_root,
    uint64_t video_frames,uint32_t fps_numerator,uint32_t fps_denominator,
    AmvAudioCancelled,void *cancel_context,AmvAudioProvider **out,AmvAudioError *);
int amv_audio_get_info(const AmvAudioProvider *,AmvAudioInfo *out);
/* Immutable mapped PCM: no explicit I/O/decoding/wait. Exactly count (<=8192)
 * frames or -1. Safe to retry the same index. Close after callbacks stop. */
int amv_audio_read_at(const AmvAudioProvider *,uint64_t first_sample,
    uint32_t count,int16_t *destination);
void amv_audio_close(AmvAudioProvider *);
#ifdef __cplusplus
}
#endif
#endif
