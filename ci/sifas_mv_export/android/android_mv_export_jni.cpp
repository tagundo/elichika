#include "android_mv_game_bindings.h"
#include "android_mv_audio_provider.h"
#include <jni.h>
#include <pthread.h>
#include <atomic>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include <math.h>
#include <android/log.h>

#if defined(__EXCEPTIONS) || defined(__GXX_RTTI)
#error "Compile MV JNI with -fno-exceptions -fno-rtti"
#endif

namespace {
pthread_mutex_t registry_guard=PTHREAD_MUTEX_INITIALIZER;
std::atomic<uint64_t> cancellation{1};
uint64_t next_selection=1,next_handle=1;
unsigned int preparing_count;
struct Source {
    bool available;
    uint64_t id,epoch;
    AmvGameStatus status;
    AmvAudioSelection selection;
} latest;
struct Listener {
    JavaVM *vm;
    jobject object;
    jmethodID song,progress,finished,failed;
    uint64_t epoch;
};
struct Prepared {
    uint64_t id,epoch;
    bool active,terminal;
    uint32_t fps;
    AmvAudioProvider *audio;
    AmvAudioInfo info;
    AmvGameStatus song;
    Listener listener;
};
Prepared *prepared[2];

void throw_io(JNIEnv *env,const char *message) {
    if(env->ExceptionCheck())env->ExceptionClear();
    jclass type=env->FindClass("java/io/IOException");
    if(type){env->ThrowNew(type,message);env->DeleteLocalRef(type);}
}
void clear_callback_exception(JNIEnv *env,const char *phase) {
    if(env->ExceptionCheck()) {
        env->ExceptionClear();
        __android_log_print(ANDROID_LOG_ERROR,"SIFAS-MV","Java callback failed during %s",phase);
    }
}
struct Env {
    JavaVM *vm;
    JNIEnv *env;
    bool attached;
    explicit Env(JavaVM *value):vm(value),env(nullptr),attached(false) {
        if(!vm)return;
        jint result=vm->GetEnv((void **)&env,JNI_VERSION_1_6);
        if(result==JNI_EDETACHED) {
            if(vm->AttachCurrentThread(&env,nullptr)==JNI_OK)attached=true;
            else env=nullptr;
        } else if(result!=JNI_OK)env=nullptr;
    }
    ~Env(){if(attached)vm->DetachCurrentThread();}
};
void release_listener(JNIEnv *env,Listener *listener) {
    if(env&&listener->object)env->DeleteGlobalRef(listener->object);
    *listener={};
}
bool bind_listener(JNIEnv *env,jobject object,bool query,Listener *out) {
    if(!object||env->GetJavaVM(&out->vm)!=JNI_OK)return false;
    out->epoch=cancellation.load();
    jclass type=env->GetObjectClass(object);
    if(!type)return false;
    out->failed=env->GetMethodID(type,"onFailed","(Ljava/lang/String;)V");
    if(!env->ExceptionCheck()) {
        if(query)out->song=env->GetMethodID(type,"onSong","(Ljava/lang/String;)V");
        else {
            out->progress=env->GetMethodID(type,"onProgress","(JJ)V");
            if(!env->ExceptionCheck())out->finished=env->GetMethodID(type,"onFinished","(Ljava/lang/String;)V");
        }
    }
    env->DeleteLocalRef(type);
    if(env->ExceptionCheck())return false;
    out->object=env->NewGlobalRef(object);
    return out->object&&!env->ExceptionCheck();
}

/* Use real UTF-8 for POSIX paths and UTF-16 for Java strings. NewStringUTF's
 * modified UTF-8 would corrupt supplementary Unicode characters in paths. */
bool java_utf8(JNIEnv *env,jstring string,char *out,size_t capacity) {
    if(!string||!capacity)return false;
    jsize count=env->GetStringLength(string);
    const jchar *chars=env->GetStringChars(string,nullptr);
    if(!chars)return false;
    size_t at=0;bool valid=true;
    for(jsize i=0;i<count&&valid;i++) {
        uint32_t code=chars[i];
        if(code>=0xd800&&code<=0xdbff) {
            if(++i>=count||chars[i]<0xdc00||chars[i]>0xdfff){valid=false;break;}
            code=0x10000+((code-0xd800)<<10)+chars[i]-0xdc00;
        } else if(code>=0xdc00&&code<=0xdfff){valid=false;break;}
        if(!code){valid=false;break;}
        uint8_t bytes[4];unsigned n=0;
        if(code<0x80)bytes[n++]=(uint8_t)code;
        else if(code<0x800){bytes[n++]=0xc0|(code>>6);bytes[n++]=0x80|(code&63);}
        else if(code<0x10000){bytes[n++]=0xe0|(code>>12);bytes[n++]=0x80|((code>>6)&63);bytes[n++]=0x80|(code&63);}
        else {bytes[n++]=0xf0|(code>>18);bytes[n++]=0x80|((code>>12)&63);bytes[n++]=0x80|((code>>6)&63);bytes[n++]=0x80|(code&63);}
        if(n>=capacity-at){valid=false;break;}
        for(unsigned j=0;j<n;j++)out[at++]=(char)bytes[j];
    }
    env->ReleaseStringChars(string,chars);
    if(!valid){out[0]=0;return false;}
    out[at]=0;return at>0;
}
jstring new_utf8(JNIEnv *env,const char *text) {
    if(!text)return nullptr;
    size_t size=strlen(text);
    if(size>32768)return nullptr;
    jchar *chars=(jchar *)malloc((size+1)*sizeof(jchar));
    if(!chars)return nullptr;
    size_t at=0,index=0;bool valid=true;
    while(index<size) {
        uint32_t code=(uint8_t)text[index++],minimum=0;unsigned trailing=0;
        if(code<0x80){}
        else if((code&0xe0)==0xc0){code&=31;trailing=1;minimum=0x80;}
        else if((code&0xf0)==0xe0){code&=15;trailing=2;minimum=0x800;}
        else if((code&0xf8)==0xf0){code&=7;trailing=3;minimum=0x10000;}
        else {valid=false;break;}
        if(trailing>size-index){valid=false;break;}
        for(unsigned i=0;i<trailing;i++) {
            uint8_t byte=(uint8_t)text[index++];
            if((byte&0xc0)!=0x80){valid=false;break;}
            code=(code<<6)|(byte&63);
        }
        if(!valid||!code||code<minimum||code>0x10ffff||(code>=0xd800&&code<=0xdfff)){valid=false;break;}
        if(code<0x10000)chars[at++]=(jchar)code;
        else {code-=0x10000;chars[at++]=(jchar)(0xd800+(code>>10));chars[at++]=(jchar)(0xdc00+(code&1023));}
    }
    jstring result=valid?env->NewString(chars,(jsize)at):nullptr;
    free(chars);return result;
}
struct Json {
    char bytes[24576];size_t count;bool valid;
    Json():bytes{},count(0),valid(true){}
    void raw(const char *text) {
        size_t size=strlen(text);
        if(size>=sizeof(bytes)-count){valid=false;return;}
        memcpy(bytes+count,text,size);count+=size;bytes[count]=0;
    }
    void number(const char *key,uint64_t value,bool comma=true) {
        char text[128];snprintf(text,sizeof(text),"%s\"%s\":%llu",comma?",":"",key,(unsigned long long)value);raw(text);
    }
    void string(const char *key,const char *value) {
        raw(",\"");raw(key);raw("\":\"");
        for(const unsigned char *p=(const unsigned char *)value;*p;p++) {
            char byte[8];
            if(*p=='"'||*p=='\\'){byte[0]='\\';byte[1]=(char)*p;byte[2]=0;raw(byte);}
            else if(*p<32){snprintf(byte,sizeof(byte),"\\u%04x",*p);raw(byte);}
            else {byte[0]=(char)*p;byte[1]=0;raw(byte);}
        }
        raw("\"");
    }
};
void send_failure(JNIEnv *env,const Listener &listener,const char *message) {
    jstring text=new_utf8(env,message);
    if(text){env->CallVoidMethod(listener.object,listener.failed,text);env->DeleteLocalRef(text);}
    clear_callback_exception(env,"failure");
}
void song_ready(void *opaque,const AmvGameStatus *status,const AmvAudioSelection *selection,const char *error) {
    Listener *listener=(Listener *)opaque;
    Env scope(listener->vm);JNIEnv *env=scope.env;
    if(!env){free(listener);return;}
    AmvGameStatus cached{};amv_game_get_status(&cached);
    if(error||!status||!selection||!cached.ready||cached.song_fingerprint!=status->song_fingerprint||
        listener->epoch!=cancellation.load()) {
        send_failure(env,*listener,error?error:"Let the loaded MV render, then try exporting again.");
        release_listener(env,listener);free(listener);return;
    }
    uint64_t id=0;
    pthread_mutex_lock(&registry_guard);
    if(next_selection<INT64_MAX&&listener->epoch==cancellation.load()) {
        id=next_selection++;latest={};latest.available=true;latest.id=id;latest.epoch=listener->epoch;latest.status=*status;latest.selection=*selection;
    }
    pthread_mutex_unlock(&registry_guard);
    if(!id){send_failure(env,*listener,"MV selection was cancelled or expired");release_listener(env,listener);free(listener);return;}
    Json json;json.raw("{");json.number("selection_id",id,false);json.number("ready",1);
    json.number("music_length_ms",(uint32_t)status->music_length_ms);json.number("sample_rate",selection->sample_rate);
    json.number("channels",selection->channels);json.number("source_samples",selection->source_samples);
    json.number("wave_id",selection->wave_id);json.number("streaming",selection->streaming);
    json.number("start_time_ms",(uint32_t)selection->start_time_ms);json.number("source_offset_ms",(uint32_t)selection->source_offset_ms);
    json.string("cue_sheet",status->cue_sheet);json.string("cue_name",status->cue_name);
    json.string("acb_path",selection->acb_path);json.string("awb_path",selection->awb_path);
    char gain[96];snprintf(gain,sizeof(gain),",\"gain\":%.9g}",(double)selection->gain);json.raw(gain);
    jstring value=json.valid?new_utf8(env,json.bytes):nullptr;
    if(value){env->CallVoidMethod(listener->object,listener->song,value);env->DeleteLocalRef(value);clear_callback_exception(env,"song query");}
    else {clear_callback_exception(env,"query string allocation");send_failure(env,*listener,"MV metadata exceeded its bounds");}
    release_listener(env,listener);free(listener);
}
bool parse_selection_id(JNIEnv *env,jstring text,uint64_t *out) {
    jclass type=env->FindClass("org/json/JSONObject");if(!type)return false;
    jmethodID ctor=env->GetMethodID(type,"<init>","(Ljava/lang/String;)V"),get=nullptr;
    if(!env->ExceptionCheck())get=env->GetMethodID(type,"getLong","(Ljava/lang/String;)J");
    jobject object=!env->ExceptionCheck()?env->NewObject(type,ctor,text):nullptr;
    jstring key=object?env->NewStringUTF("selection_id"):nullptr;
    jlong value=key&&!env->ExceptionCheck()?env->CallLongMethod(object,get,key):0;
    bool valid=!env->ExceptionCheck()&&value>0;
    if(key)env->DeleteLocalRef(key);if(object)env->DeleteLocalRef(object);env->DeleteLocalRef(type);
    if(valid)*out=(uint64_t)value;return valid;
}
int is_cancelled(void *context){return cancellation.load()!=*(uint64_t *)context;}
Prepared *find(uint64_t id){for(Prepared *value:prepared)if(value&&value->id==id)return value;return nullptr;}
bool registered(Prepared *value){for(Prepared *slot:prepared)if(slot==value)return true;return false;}
void remove(Prepared *value){for(Prepared *&slot:prepared)if(slot==value){slot=nullptr;return;}}
void dispose(Prepared *value,JNIEnv *env) {
    if(!value)return;amv_audio_close(value->audio);release_listener(env,&value->listener);free(value);
}
int pcm(void *context,uint64_t first,uint32_t count,int16_t *out) {
    return amv_audio_read_at(((Prepared *)context)->audio,first,count,out);
}
void progress(void *context,uint64_t done,uint64_t total) {
    Prepared *value=(Prepared *)context;
    // The bindings serialize PCM/progress/terminal callbacks on Unity's thread.
    Env scope(value->listener.vm);if(!scope.env)return;
    scope.env->CallVoidMethod(value->listener.object,value->listener.progress,(jlong)done,(jlong)total);
    clear_callback_exception(scope.env,"progress");
}
void terminal(void *context,const char *text,bool success) {
    Prepared *value=(Prepared *)context;
    pthread_mutex_lock(&registry_guard);
    if(!registered(value)||!value->active||value->terminal){pthread_mutex_unlock(&registry_guard);return;}
    value->terminal=true;Listener listener=value->listener;
    pthread_mutex_unlock(&registry_guard);
    Env scope(listener.vm);JNIEnv *env=scope.env;
    if(env) {
        if(success) {
            jstring path=new_utf8(env,text);
            if(path){env->CallVoidMethod(listener.object,listener.finished,path);env->DeleteLocalRef(path);clear_callback_exception(env,"completion");}
            else {clear_callback_exception(env,"completion string allocation");send_failure(env,listener,"The completed MP4 path could not be returned");}
        } else send_failure(env,listener,text);
    }
    pthread_mutex_lock(&registry_guard);remove(value);pthread_mutex_unlock(&registry_guard);
    dispose(value,env);
}
void finished(void *context,const char *path){terminal(context,path,true);}
void failed(void *context,const char *message){terminal(context,message,false);}
}

extern "C" JNIEXPORT jint JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativeQuery(
        JNIEnv *env,jclass,jobject callback) {
    if(amv_game_try_bind_loaded()!=1)return 0;
    Listener *listener=(Listener *)calloc(1,sizeof(Listener));
    if(!listener){throw_io(env,"MV query allocation failed");return -1;}
    if(!bind_listener(env,callback,true,listener)){release_listener(env,listener);free(listener);return -1;}
    int result=amv_game_request_song_query(listener,song_ready);
    if(result!=1){release_listener(env,listener);free(listener);}return result;
}
extern "C" JNIEXPORT jlong JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativePrepare(
        JNIEnv *env,jclass,jstring json,jstring root,jint fps) {
    if((fps!=30&&fps!=60&&fps!=120)||!json||!root){throw_io(env,"Invalid MV audio preparation request (supported fps: 30, 60, 120)");return 0;}
    uint64_t id=0;if(!parse_selection_id(env,json,&id)){throw_io(env,"Invalid native MV selection token");return 0;}
    Source selected{};uint64_t epoch=cancellation.load();
    pthread_mutex_lock(&registry_guard);
    unsigned count=preparing_count;for(Prepared *value:prepared)if(value)count++;
    bool available=latest.available&&latest.id==id&&latest.epoch==epoch;
    bool full=count>=2;
    if(available&&!full){selected=latest;latest.available=false;preparing_count++;}
    pthread_mutex_unlock(&registry_guard);
    if(!available||full){throw_io(env,full?"Previous MV audio is still owned":"The selected MV expired; query it again");return 0;}
    char cache[AMV_AUDIO_PATH_CAP];AmvAudioProvider *audio=nullptr;AmvAudioError error{};
    bool path=java_utf8(env,root,cache,sizeof(cache))&&cache[0]=='/';
    uint64_t frames=selected.selection.music_length_ms>0?
        ((uint64_t)selected.selection.music_length_ms*(uint32_t)fps+999)/1000:0;
    bool decoded=path&&frames&&amv_audio_prepare(&selected.selection,cache,frames,(uint32_t)fps,1,is_cancelled,&epoch,&audio,&error);
    Prepared *value=decoded?(Prepared *)calloc(1,sizeof(Prepared)):nullptr;
    if(value){value->audio=audio;value->fps=(uint32_t)fps;value->epoch=epoch;value->song=selected.status;
        if(!amv_audio_get_info(audio,&value->info)){free(value);value=nullptr;}}
    pthread_mutex_lock(&registry_guard);preparing_count--;
    int slot=!prepared[0]?0:!prepared[1]?1:-1;
    if(value&&slot>=0&&next_handle<INT64_MAX&&cancellation.load()==epoch){value->id=next_handle++;prepared[slot]=value;}
    pthread_mutex_unlock(&registry_guard);
    if(!value||!value->id) {
        if(audio)amv_audio_close(audio);free(value);
        throw_io(env,!path?"Invalid private MV cache directory":error.message[0]?error.message:
            cancellation.load()!=epoch?"MV audio preparation was cancelled":"MV audio preparation failed");return 0;
    }
    return (jlong)value->id;
}
extern "C" JNIEXPORT jstring JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativePreparedInfo(
        JNIEnv *env,jclass,jlong handle) {
    AmvAudioInfo info{};uint64_t frames=0;
    pthread_mutex_lock(&registry_guard);Prepared *value=find((uint64_t)handle);
    if(value&&!value->active){info=value->info;frames=((uint64_t)value->song.music_length_ms*value->fps+999)/1000;}
    pthread_mutex_unlock(&registry_guard);
    if(!frames){throw_io(env,"MV prepared audio handle expired");return nullptr;}
    char json[512];snprintf(json,sizeof(json),"{\"sample_rate\":%u,\"channels\":%u,\"audio_frames\":%llu,\"video_frames\":%llu}",
        info.sample_rate,info.channels,(unsigned long long)info.audio_frames,(unsigned long long)frames);
    return env->NewStringUTF(json);
}
extern "C" JNIEXPORT jint JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativeBegin(
        JNIEnv *env,jclass,jlong handle,jobject encoder,jint width,jint height,jint fps,jobject callback) {
    pthread_mutex_lock(&registry_guard);Prepared *value=find((uint64_t)handle);
    if(!value||value->active||fps!=(jint)value->fps||value->epoch!=cancellation.load()){
        pthread_mutex_unlock(&registry_guard);throw_io(env,"MV prepared audio does not match this export");return -1;}
    Listener listener{};
    if(!bind_listener(env,callback,false,&listener)){release_listener(env,&listener);pthread_mutex_unlock(&registry_guard);return -1;}
    if(listener.epoch!=value->epoch){release_listener(env,&listener);pthread_mutex_unlock(&registry_guard);throw_io(env,"MV export was cancelled");return -1;}
    AmvGameConfig config{};config.width=(uint32_t)width;config.height=(uint32_t)height;config.fps=(uint32_t)fps;
    config.video_frames=((uint64_t)value->song.music_length_ms*value->fps+999)/1000;
    config.sample_rate=value->info.sample_rate;config.channels=value->info.channels;
    config.audio_frames=value->info.audio_frames;config.song_fingerprint=value->song.song_fingerprint;
    AmvGameCallbacks sink{value,pcm,progress,finished,failed};jthrowable error=nullptr;
    // Publish the listener before queueing: the original Unity thread can
    // consume this request immediately after the bindings release their lock.
    value->listener=listener;
    int result=amv_game_request_begin(env,encoder,&config,&sink,&error);
    if(result==1)value->active=true;
    else {release_listener(env,&value->listener);}
    pthread_mutex_unlock(&registry_guard);
    if(error){env->Throw(error);env->DeleteLocalRef(error);}return result;
}
extern "C" JNIEXPORT void JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativeRelease(
        JNIEnv *env,jclass,jlong handle) {
    pthread_mutex_lock(&registry_guard);Prepared *value=find((uint64_t)handle);
    if(value&&!value->active)remove(value);else value=nullptr;
    pthread_mutex_unlock(&registry_guard);if(value)dispose(value,env);
}
extern "C" JNIEXPORT void JNICALL Java_com_klab_lovelive_allstars_fovmod_AndroidMVExport_nativeCancel(JNIEnv *,jclass) {
    cancellation.fetch_add(1);
    pthread_mutex_lock(&registry_guard);latest.available=false;pthread_mutex_unlock(&registry_guard);
    amv_game_request_cancel();
}
