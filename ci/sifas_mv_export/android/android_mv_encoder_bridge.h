#ifndef SIFAS_ANDROID_MV_ENCODER_BRIDGE_H
#define SIFAS_ANDROID_MV_ENCODER_BRIDGE_H
#include <jni.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct AmvEncoder AmvEncoder;
/* Create AndroidMVEncoder on a Java thread with the app class loader, then bind
 * that actual object. This avoids FindClass from a foreign attached thread.
 * The handle owns one global reference. All JNIEnv pointers must belong to the
 * CURRENT attached calling thread. No call here runs Unity/physics/rendering.
 * Java exceptions are cleared and returned as local refs through error; caller
 * must DeleteLocalRef. Do not call a bridge function with an exception pending.
 */
AmvEncoder *amv_encoder_bind(JNIEnv *, jobject encoder, jthrowable *error);
int amv_encoder_matches_config(JNIEnv *,AmvEncoder *,int width,int height,int fps,int64_t frames,
                                int sample_rate,int channels,int64_t audio_frames,jthrowable *error);
/* 1=accepted (source copied), 0=backpressure (same index/data retry), -1=error.
 * I420 is limited-range SDR Rec709 contiguous Y/U/V. PCM16 is little endian,
 * interleaved. Native memory is borrowed only for this synchronous JNI call.
 */
int amv_encoder_offer_i420(JNIEnv *, AmvEncoder *, int64_t frame_index,
                           const uint8_t *, size_t, jthrowable *error);
int amv_encoder_offer_pcm16(JNIEnv *, AmvEncoder *, int64_t sample_index,
                            const uint8_t *, size_t, jthrowable *error);
int amv_encoder_finish(JNIEnv *, AmvEncoder *, jthrowable *error);
int amv_encoder_cancel(JNIEnv *, AmvEncoder *, jthrowable *error);
/* NULL without error means pending. Nonnull is a local jstring ref containing
 * the finalized private MP4 path; caller owns it. Failure returns a throwable.
 * This query does not block the Unity/UI thread.
 */
jstring amv_encoder_completed_path(JNIEnv *, AmvEncoder *, jthrowable *error);
/* Stop all producers and serialize with EVERY in-flight bridge call (including
 * cancel/completed_path) before unbind; no handle access is valid afterwards.
 * Call cancel when abandoning a session. Its Java worker retains the encoder
 * until cleanup, so unbind may release this root after native calls stop. Await
 * cleanup off the Unity/UI thread only when the caller needs its completion.
 */
void amv_encoder_unbind(JNIEnv *, AmvEncoder *);
#ifdef __cplusplus
}
#endif
#endif
