#include "android_mv_encoder_bridge.h"
#include <stdlib.h>
#include <limits.h>

struct AmvEncoder {
    jobject encoder;
    jmethodID video, audio, finish, cancel, completed, config;
};
static int take_exception(JNIEnv *env,jthrowable *out) {
    jthrowable error=(*env)->ExceptionOccurred(env);
    if (!error) return 0;
    (*env)->ExceptionClear(env);
    if (out) *out=error; else (*env)->DeleteLocalRef(env,error);
    return 1;
}
static int invalid(JNIEnv *env,jthrowable *error) {
    jclass type=(*env)->FindClass(env,"java/lang/IllegalArgumentException");
    if (type) { (*env)->ThrowNew(env,type,"Invalid MV encoder bridge argument"); (*env)->DeleteLocalRef(env,type); }
    take_exception(env,error);
    return -1;
}
AmvEncoder *amv_encoder_bind(JNIEnv *env,jobject encoder,jthrowable *error) {
    if (error) *error=NULL;
    if (!env) return NULL;
    if (!encoder) { invalid(env,error); return NULL; }
    AmvEncoder *handle=(AmvEncoder *)calloc(1,sizeof(*handle));
    if (!handle) {
        jclass type=(*env)->FindClass(env,"java/lang/OutOfMemoryError");
        if (type) { (*env)->ThrowNew(env,type,"MV bridge allocation"); (*env)->DeleteLocalRef(env,type); }
        take_exception(env,error); return NULL;
    }
    jclass type=(*env)->GetObjectClass(env,encoder);
    if (take_exception(env,error) || !type) { free(handle); return NULL; }
    handle->video=(*env)->GetMethodID(env,type,"offerVideo","(JLjava/nio/ByteBuffer;)Z");
    if (take_exception(env,error)) goto fail;
    handle->audio=(*env)->GetMethodID(env,type,"offerAudio","(JLjava/nio/ByteBuffer;)Z");
    if (take_exception(env,error)) goto fail;
    handle->finish=(*env)->GetMethodID(env,type,"finish","()V");
    if (take_exception(env,error)) goto fail;
    handle->cancel=(*env)->GetMethodID(env,type,"cancel","()V");
    if (take_exception(env,error)) goto fail;
    handle->completed=(*env)->GetMethodID(env,type,"completedPath","()Ljava/lang/String;");
    if (take_exception(env,error)) goto fail;
    handle->config=(*env)->GetMethodID(env,type,"matchesConfig","(IIIJIIJ)Z");
    if (take_exception(env,error)) goto fail;
    handle->encoder=(*env)->NewGlobalRef(env,encoder);
    if (take_exception(env,error) || !handle->encoder) goto fail;
    (*env)->DeleteLocalRef(env,type);
    return handle;
fail:
    if (handle->encoder) (*env)->DeleteGlobalRef(env,handle->encoder);
    (*env)->DeleteLocalRef(env,type); free(handle); return NULL;
}
int amv_encoder_matches_config(JNIEnv *env,AmvEncoder *handle,int width,int height,int fps,int64_t frames,
                                int sample_rate,int channels,int64_t audio_frames,jthrowable *error) {
    if(error)*error=NULL;
    if(!env)return -1;
    if(!handle)return invalid(env,error);
    jboolean matches=(*env)->CallBooleanMethod(env,handle->encoder,handle->config,
        (jint)width,(jint)height,(jint)fps,(jlong)frames,(jint)sample_rate,(jint)channels,(jlong)audio_frames);
    return take_exception(env,error)?-1:matches?1:0;
}
static int offer(JNIEnv *env,AmvEncoder *handle,int audio,int64_t index,
                 const uint8_t *data,size_t size,jthrowable *error) {
    if (error) *error=NULL;
    if (!env) return -1;
    if (!handle || !data || !size || size>INT_MAX || index<0) return invalid(env,error);
    jobject buffer=(*env)->NewDirectByteBuffer(env,(void *)data,(jlong)size);
    if (take_exception(env,error) || !buffer) return -1;
    jboolean accepted=(*env)->CallBooleanMethod(env,handle->encoder,
        audio?handle->audio:handle->video,(jlong)index,buffer);
    int failed=take_exception(env,error);
    (*env)->DeleteLocalRef(env,buffer);
    return failed?-1:accepted?1:0;
}
int amv_encoder_offer_i420(JNIEnv *env,AmvEncoder *handle,int64_t index,
                           const uint8_t *data,size_t size,jthrowable *error) {
    return offer(env,handle,0,index,data,size,error);
}
int amv_encoder_offer_pcm16(JNIEnv *env,AmvEncoder *handle,int64_t index,
                            const uint8_t *data,size_t size,jthrowable *error) {
    return offer(env,handle,1,index,data,size,error);
}
static int command(JNIEnv *env,AmvEncoder *handle,int cancel,jthrowable *error) {
    if (error) *error=NULL;
    if (!env) return -1;
    if (!handle) return invalid(env,error);
    (*env)->CallVoidMethod(env,handle->encoder,cancel?handle->cancel:handle->finish);
    return take_exception(env,error)?-1:1;
}
int amv_encoder_finish(JNIEnv *env,AmvEncoder *handle,jthrowable *error) { return command(env,handle,0,error); }
int amv_encoder_cancel(JNIEnv *env,AmvEncoder *handle,jthrowable *error) { return command(env,handle,1,error); }
jstring amv_encoder_completed_path(JNIEnv *env,AmvEncoder *handle,jthrowable *error) {
    if (error) *error=NULL;
    if (!env) return NULL;
    if (!handle) { invalid(env,error); return NULL; }
    jstring path=(jstring)(*env)->CallObjectMethod(env,handle->encoder,handle->completed);
    if (take_exception(env,error)) { if (path) (*env)->DeleteLocalRef(env,path); return NULL; }
    return path;
}
void amv_encoder_unbind(JNIEnv *env,AmvEncoder *handle) {
    if (!env || !handle) return;
    (*env)->DeleteGlobalRef(env,handle->encoder); free(handle);
}
