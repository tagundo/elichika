#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "android_mv_game_bindings.h"
#include "mv_pixel_convert.h"
#include <android/log.h>
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
#include <math.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <limits.h>
#include <stddef.h>
#include <stdarg.h>
#include <initializer_list>
#include <atomic>
#include "android_mv_patch_profiles.h"
#if defined(__EXCEPTIONS) || defined(__GXX_RTTI)
#error "Use same-engine runtime_invoke exception-out, -fno-exceptions -fno-rtti"
#endif

namespace {
enum Slot { TIME,LIVE,MUSIC,MEMBER,OVERLAY,WIDTH,HEIGHT,LATE,POST,SLOTS };
struct Sidecar {
    char magic[8]; uint32_t version,size,region,kind,ready,reserved;
    uint8_t source[32],profile[32]; uintptr_t callback[9],slot_padding,original[9]; uint8_t tail[72];
};
static_assert(sizeof(Sidecar)==320,"offline MV sidecar ABI");
static_assert(offsetof(Sidecar,ready)==24 && offsetof(Sidecar,callback)==96 &&
              offsetof(Sidecar,original)==176,"offline MV sidecar offsets");
struct Engine {
    void *(*domain_get)(); const void **(*domain_get_assemblies)(void *,size_t *);
    void *(*assembly_get_image)(const void *); void *(*class_from_name)(void *,const char *,const char *);
    const void *(*class_get_methods)(void *,void **); const char *(*method_get_name)(const void *);
    uint32_t (*method_get_param_count)(const void *); const void *(*method_get_param)(const void *,uint32_t);
    const void *(*method_get_return_type)(const void *); uint32_t (*method_get_flags)(const void *,uint32_t *);
    void *(*method_get_class)(const void *); void *(*runtime_invoke)(const void *,void *,void **,void **);
    char *(*type_get_name)(const void *); void (*free_memory)(void *);
    void *(*class_from_type)(const void *); const void *(*class_get_type)(void *);
    void *(*type_get_object)(const void *); void *(*object_get_class)(void *); void *(*class_get_parent)(void *);
    unsigned char (*class_is_assignable_from)(void *,void *); void *(*object_unbox)(void *);
    void *(*object_new)(void *); uint32_t (*class_instance_size)(void *);
    int32_t (*class_value_size)(void *,uint32_t *); void *(*class_get_field_from_name)(void *,const char *);
    size_t (*field_get_offset)(void *); const void *(*field_get_type)(void *);
    uint32_t (*field_get_flags)(void *); uint32_t (*gchandle_new)(void *,unsigned char);
    void *(*gchandle_get_target)(uint32_t); void (*gchandle_free)(uint32_t);
    uintptr_t (*array_length)(void *); void *(*thread_current)();
    int32_t (*string_length)(void *); const uint16_t *(*string_chars)(void *);
    unsigned char (*type_is_byref)(const void *);
    void (*format_exception)(void *,char *,int32_t);
} e;
struct Method { const void *info; void *owner; bool is_static; };
struct Field { size_t offset; void *owner; size_t size; };
struct Rect { float x,y,width,height; };
struct RenderTargetIdentifier {alignas(8) uint8_t data[40];};
struct Vec3 { float x,y,z; };
struct Quat { float x,y,z,w; };
struct NativeArray { void *data; int32_t length; uint32_t allocator; };
struct Bone { void *bone,*transform,*child;uint32_t bone_root,transform_root,child_root; uint8_t scalar[128]; Quat rotation; };
struct Manager { void *object,*array;uint32_t object_root,array_root; uint8_t paused; };
struct Methods {
    Method hook[9],alive,find_objects,timeline,time_get,time_set,mode_get,mode_set,state_get,play,stop,pause,evaluate;
    Method camera_manager,member_manager,music_machine,final_overlay,reset_components,resize_cameras;
    Method rt_constructor,rt_create,rt_release,rt_active_get,rt_active_set,texture_constructor;
    Method read_pixels,image_pointer,image_size,blit,destroy,job_complete,apply_transform,request_safe;
    Method manager_bones,manager_pause_get,manager_pause_set,position,rotation_get,rotation_set;
    Method sound_pause,sound_paused;
    Method overlay_camera,behaviour_enabled,behaviour_set_enabled,overlay_paused,camera_target,camera_set_target,camera_width,camera_height;
    Method camera_update,camera_resume,core_camera,cutin_camera,quality_get,quality_set,quality_post_effect,rt_created;
    Method command_clear,command_blit,target_identifier,camera_commands,camera_clear_get,camera_clear_set;
    Method resume_broadcast,resume_dispatch,pause_broadcast,pause_dispatch,pause_se_voices;
    Method dm_pause_get,dm_pause_set,dm_wait_get,dm_wait_set;
    Method state_instance,live_state;
    Method texture_width,texture_height;
    Method cri_sheet,cri_waveform;
} m;
struct Fields {
    Field loading,music_time,length,gain,sound,cue,cue_sheet,cue_name;
    Field playing,pausing,paused,finished;
    Field managers,bone_array,collider_array,job_index,safety,knee_l,knee_r,jobs_a,jobs_b;
    Field child,transform,scalar_first,scalar_end,current_tip,previous_tip,correct_adjust,ratio;
    Field scene_pre_final,scene_post_final,scene_paused,overlay_blur;
    Field camera_quality,camera_buffers[4],camera_list,camera_cutin,camera_current_width,camera_current_height;
    Field camera_overlay,camera_cutin_overlay,core_command_buffers,core_quality;
    Field camera_pause_step,camera_live_blur,camera_skill_pause,camera_msaa_changed,camera_buffer_write;
    Field scene_mediator,mediator_state,mediator_pause_bus,mediator_resume_bus;
    Field cri_acb,cri_acb_path,cri_awb_path,wave_id,wave_rate,wave_channels,wave_samples,wave_streaming;
} f;
struct Original { uintptr_t entry[9]; } original;
struct Request { bool pending,cancel; JavaVM *vm; AmvEncoder *encoder; AmvGameConfig config; AmvGameCallbacks sink; } request;
struct Query {bool pending;void *context;AmvSongQueried callback;} query;
pthread_mutex_t guard=PTHREAD_MUTEX_INITIALIZER;
pthread_t unity_thread;
bool thread_known,installed,runtime_ready,runtime_rejected,advancing,awaiting_capture,have_tick,finishing,abandoned,request_busy;
bool resolution_ready,render_state_saved,render_chain_rebuilt,cameras_suspended;
std::atomic<bool> scoped_render_dimensions{false};
bool quarantined;
std::atomic<bool> active{false};
uint32_t region,reentry;
Sidecar *il_sidecar,*unity_sidecar;
uintptr_t il_bias,unity_bias;
void *director,*overlay,*timeline,*music,*members,*camera_manager,*session_overlay,*mv_scene,*clock_manager;
void *rt,*texture,*sound,*overlay_camera;
uint32_t observed_director_root,observed_overlay_root,scene_root,texture_root,rt_root;
uint32_t session_director_root,session_overlay_root;
uint32_t overlay_camera_root;
uint32_t timeline_root,music_root,members_root,camera_manager_root,sound_root,managers_array_root;
void *managers_array;
uint8_t clock_snapshot[0xe0];
double clock_epoch,unscaled_epoch,saved_time,wall_start;
int32_t saved_mode,saved_state,saved_music_time;
int32_t saved_width,saved_height;
uint8_t saved_music_flags[4],saved_sound_pause;
NativeArray saved_bones,saved_colliders;
void *bone_bytes,*collider_bytes;
Bone *bones; Manager *managers; uint32_t manager_count,bone_count;
int32_t saved_job_index,saved_safety;
uint8_t saved_knees[24];
uint8_t *pixels; int16_t pcm[4096*2];
uint64_t tick,accepted_frames,audio_index,pending_frame;
uint32_t simulation_hz;
bool capture_after_overlay;
char setup_failure[256];
bool pending_pixels,frame_ready;
struct CameraSnapshot {void *camera;uint32_t handle;uint8_t enabled,render_enabled;};
void *pause_mediator,*pause_bus,*resume_bus;uint32_t pause_mediator_root,pause_bus_root,resume_bus_root;
int32_t saved_pause_state;uint8_t saved_dm_pause,saved_tutorial_wait;bool common_resume_sent;
void *pause_state_owner,*pause_live_state;uint32_t pause_state_owner_root,pause_live_state_root;
char managed_failure[192];
CameraSnapshot render_cameras[132];uint32_t render_camera_count;
void *quality,*saved_capture,*saved_final_target,*internal_targets[4];
uint32_t quality_root,saved_capture_root,saved_final_target_root,internal_roots[4];
int32_t saved_quality_resolution,saved_camera_pause_step,saved_manager_width,saved_manager_height,saved_overlay_clear;
uint8_t saved_scene_paused,saved_overlay_blur,saved_overlay_effect,saved_camera_live_blur,saved_camera_skill_pause,saved_camera_msaa_changed,saved_buffer_write;
AmvGameConfig config;
AmvGameCallbacks sink;
AmvEncoder *encoder;
JavaVM *vm;
AmvGameStatus cached;
struct Terminal {
    bool pending,success; AmvGameCallbacks callback;
    char path[1024],message[256];
} terminal;

double now() { timespec t{}; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
bool setup_rejected(const char *format,...) {
    va_list args;va_start(args,format);vsnprintf(setup_failure,sizeof(setup_failure),format,args);va_end(args);
    return false;
}
uint32_t simulation_rate(uint32_t fps) { return fps==120?120:60; }
template<class T>T load(void *p,size_t off) { T v; memcpy(&v,(uint8_t *)p+off,sizeof(v)); return v; }
template<class T>void put(void *p,size_t off,T v) { memcpy((uint8_t *)p+off,&v,sizeof(v)); }
void phase(const char *text) { pthread_mutex_lock(&guard); snprintf(cached.phase,sizeof(cached.phase),"%s",text); pthread_mutex_unlock(&guard); }
void publish() {
    pthread_mutex_lock(&guard); cached.installed=installed; cached.region=region; cached.active=active;
    cached.simulation_tick=have_tick?tick:0; cached.accepted_video_frames=accepted_frames;
    pthread_mutex_unlock(&guard);
}
void record_failure(const char *text) {
    pthread_mutex_lock(&guard); snprintf(cached.failure,sizeof(cached.failure),"%s",text); cached.ready=0; pthread_mutex_unlock(&guard);
    __android_log_print(ANDROID_LOG_ERROR,"SIFAS-MV","%s",text);
}
bool own_thread() {
    const pthread_t current=pthread_self();
    pthread_mutex_lock(&guard);
    if (!thread_known) { unity_thread=current; thread_known=true; }
    bool same=pthread_equal(unity_thread,current)!=0;
    pthread_mutex_unlock(&guard); return same;
}
bool typename_is(const void *type,const char *expected) {
    char *name=e.type_get_name(type); if (!name) return false;
    bool same=strcmp(name,expected)==0; e.free_memory(name); return same;
}
void *klass(const char *ns,const char *name) {
    size_t count=0; void *domain=e.domain_get(); if (!domain) return nullptr;
    const void **assemblies=e.domain_get_assemblies(domain,&count); if (!assemblies || count>512) return nullptr;
    void *found=nullptr;
    for (size_t i=0;i<count;i++) {
        void *image=e.assembly_get_image(assemblies[i]);
        void *value=image?e.class_from_name(image,ns,name):nullptr;
        if (value && found && value!=found) return nullptr;
        if (value) found=value;
    }
    return found;
}
bool method(Method *out,void *owner,const char *name,bool is_static,const char *result,
            int count,const char *const *types=nullptr) {
    if (!owner) return false;
    void *iterator=nullptr; const void *found=nullptr; size_t iterations=0;
    while (const void *candidate=e.class_get_methods(owner,&iterator)) {
        if (++iterations>4096) return false;
        if (e.method_get_class(candidate)!=owner || strcmp(e.method_get_name(candidate),name) ||
                e.method_get_param_count(candidate)!=(uint32_t)count) continue;
        uint32_t implementation=0;
        if (((e.method_get_flags(candidate,&implementation)&0x10)!=0)!=is_static ||
                !typename_is(e.method_get_return_type(candidate),result)) continue;
        bool matches=true;
        for (int i=0;i<count;i++) if (!typename_is(e.method_get_param(candidate,i),types[i])) matches=false;
        if (!matches) continue;
        if (found) return false;
        found=candidate;
    }
    if (!found) return false;
    *out={found,owner,is_static}; return true;
}
bool field(Field *out,void *owner,const char *name,const char *type,size_t bytes) {
    if (!owner) return false;
    void *value=e.class_get_field_from_name(owner,name);
    if (!value || (e.field_get_flags(value)&0x10) || (type && !typename_is(e.field_get_type(value),type))) return false;
    size_t off=e.field_get_offset(value),size=e.class_instance_size(owner);
    if (off<16 || off>4096 || bytes>size || off>size-bytes) return false;
    *out={off,owner,bytes}; return true;
}
bool field_object(void *object,const Field &field) {
    return object && e.class_is_assignable_from(field.owner,e.object_get_class(object));
}
bool waveform_method(void *owner) {
    if(!owner)return false;void *iterator=nullptr;const void *found=nullptr;size_t iterations=0;
    while(const void *candidate=e.class_get_methods(owner,&iterator)){
        if(++iterations>4096)return false;
        uint32_t implementation=0;
        if(e.method_get_class(candidate)!=owner||strcmp(e.method_get_name(candidate),"GetWaveFormInfo")||e.method_get_param_count(candidate)!=2||
            (e.method_get_flags(candidate,&implementation)&0x10)||!typename_is(e.method_get_return_type(candidate),"System.Boolean")||
            !typename_is(e.method_get_param(candidate,0),"System.String")||!e.type_is_byref(e.method_get_param(candidate,1)))continue;
        void *info=e.class_from_type(e.method_get_param(candidate,1));uint32_t alignment=0;
        // Actual managed WaveformInfo is 40 B: six scalar fields followed
        // by a reserved int[] reference at+0x20. Native CRI's 32-B wire struct
        // must not be confused with this managed out-parameter representation.
        if(!info||e.class_value_size(info,&alignment)!=40)return false;
        if(!field(&f.wave_id,info,"waveId",nullptr,4)||!field(&f.wave_rate,info,"samplingRate",nullptr,4)||
            !field(&f.wave_channels,info,"numChannels",nullptr,4)||!field(&f.wave_samples,info,"numSamples",nullptr,8)||
            !field(&f.wave_streaming,info,"streamingFlag","System.Boolean",1))return false;
        const Field *fields[]={&f.wave_id,&f.wave_rate,&f.wave_channels,&f.wave_samples,&f.wave_streaming};
        for(const Field *v:fields)if(v->offset<16||v->offset-16+v->size>40)return false;
        if(found)return false;found=candidate;
    }
    if(!found)return false;m.cri_waveform={found,owner,false};return true;
}
struct Result { bool ok; void *value; };
Result invoke(const Method &method,void *self,void **args=nullptr) {
    if (!method.info || (!method.is_static && (!self ||
            !e.class_is_assignable_from(method.owner,e.object_get_class(self))))) return {false,nullptr};
    void *exception=nullptr;
    void *value=e.runtime_invoke(method.info,method.is_static?nullptr:self,args,&exception);
    if(exception){char description[160]={};e.format_exception(exception,description,sizeof(description));
        if(char *line=strchr(description,'\n'))*line=0;
        const char *operation=e.method_get_name(method.info);
        if(!managed_failure[0])snprintf(managed_failure,sizeof(managed_failure),"%s: %s",operation,description[0]?description:"managed exception without formatted details");
        __android_log_print(ANDROID_LOG_ERROR,"SIFAS-MV","%s: %s",operation,description);}
    return {!exception,value};
}
bool invoke_void(const Method &method,void *self,void **args=nullptr) {
    Result r=invoke(method,self,args); return r.ok && !r.value;
}
template<class T>bool value(const Method &method,void *self,T *out,void **args=nullptr) {
    Result r=invoke(method,self,args);
    if (!r.ok || !r.value || e.object_get_class(r.value)!=e.class_from_type(e.method_get_return_type(method.info))) return false;
    void *data=e.object_unbox(r.value); if (!data) return false; memcpy(out,data,sizeof(T)); return true;
}
void *reference(const Method &method,void *self,void **args=nullptr) {
    Result r=invoke(method,self,args); return r.ok?r.value:nullptr;
}
bool alive(void *object) { uint8_t yes=0; void *args[]={object}; return object && value(m.alive,nullptr,&yes,args) && yes; }
uint32_t root(void *object) { return object?e.gchandle_new(object,0):0; }
void release(uint32_t *handle) { if (*handle) e.gchandle_free(*handle); *handle=0; }
uint32_t length(void *array,uint32_t max) { uintptr_t n=array?e.array_length(array):0; return n<=max?(uint32_t)n:UINT32_MAX; }
void *element(void *array,uint32_t index) { return load<void *>(array,32+(size_t)index*8); }
bool original_call(Slot slot,void *self,void **args=nullptr) {
    const uint32_t bit=1u<<slot; reentry|=bit;
    bool ok=invoke_void(m.hook[slot],self,args); reentry&=~bit; return ok;
}
bool init_runtime() {
    if (runtime_ready) return true;
    if (!e.thread_current()) return false;
    void *ld=klass("LLAS.Scene.Live","LiveDirectorBase"),*mm=klass("LLAS.Scene.Live.Components","LiveCoreMemberManager");
    void *cm=klass("LLAS.Scene.Live.Components","LiveCoreCameraManager"),*oc=klass("LLAS.Scene.Live.Components","LiveCoreOverlayCamera");
    void *mu=klass("LLAS.Scene.Live.Components","LiveMusicMachine"),*pd=klass("UnityEngine.Playables","PlayableDirector");
    void *tr=klass("UnityEngine","Transform"),*sb=klass("LLAS.Components.Members","SwingBone");
    void *sm=klass("LLAS.Components.Members","SwingBoneManager"),*tex=klass("UnityEngine","Texture2D");
    void *render=klass("UnityEngine","RenderTexture"),*obj=klass("UnityEngine","Object");
    void *scene=klass("LLAS.Scene.EntryPoint","LiveMvScene"),*jobs=klass("Unity.Jobs","JobHandle");
    const char *b[] = {"System.Boolean"},*i[]={"System.Int32"},*d[]={"System.Double"};
    const char *uobj[]={"UnityEngine.Object"},*type[]={"System.Type"};
    const char *rtarg[]={"UnityEngine.RenderTexture"},*blend[]={"UnityEngine.Texture","UnityEngine.RenderTexture"};
    const char *rctor[]={"System.Int32","System.Int32","System.Int32","UnityEngine.RenderTextureFormat","UnityEngine.RenderTextureReadWrite"};
    const char *tctor[]={"System.Int32","System.Int32","UnityEngine.TextureFormat","System.Boolean"};
    const char *read[]={"UnityEngine.Rect","System.Int32","System.Int32","System.Boolean"};
    const char *mode[]={"UnityEngine.Playables.DirectorUpdateMode"},*q[]={"UnityEngine.Quaternion"};
    const char *camera_arg[]={"UnityEngine.Camera"};
    const char *sheet_args[]={"System.String"};
    const char *texture_arg[]={"UnityEngine.Texture"},*command_blit_args[]={"UnityEngine.Texture","UnityEngine.Rendering.RenderTargetIdentifier"};
    const char *event_arg[]={"UnityEngine.Rendering.CameraEvent"},*clear_arg[]={"UnityEngine.CameraClearFlags"};
#define M(dst,owner,name,stat,ret,n,args) if(!method(&m.dst,owner,name,stat,ret,n,args))return false
    M(hook[LIVE],ld,"Update",false,"System.Void",0,nullptr);
    M(hook[MUSIC],mu,"Update",false,"System.Void",0,nullptr);
    M(hook[MEMBER],mm,"Update",false,"System.Void",0,nullptr);
    M(hook[LATE],mm,"LateUpdate",false,"System.Void",0,nullptr);
    // Explicit two-argument validation avoids accepting an unrelated overload.
#undef M
    const char *overlay_args[]={"UnityEngine.RenderTexture","UnityEngine.RenderTexture"};
    if (!method(&m.hook[OVERLAY],oc,"OnRenderImage",false,"System.Void",2,overlay_args)) return false;
#define M(dst,owner,name,stat,ret,n,args) if(!method(&m.dst,owner,name,stat,ret,n,args))return false
    M(alive,obj,"op_Implicit",true,"System.Boolean",1,uobj);
    M(hook[POST],klass("UnityEngine","Camera"),"FireOnPostRender",true,"System.Void",1,camera_arg);
    M(overlay_camera,oc,"get_Camera",false,"UnityEngine.Camera",0,nullptr);
    M(behaviour_enabled,klass("UnityEngine","Behaviour"),"get_enabled",false,"System.Boolean",0,nullptr);
    M(behaviour_set_enabled,klass("UnityEngine","Behaviour"),"set_enabled",false,"System.Void",1,b);
    M(overlay_paused,oc,"IsPause",false,"System.Boolean",0,nullptr);
    M(camera_target,klass("UnityEngine","Camera"),"get_targetTexture",false,"UnityEngine.RenderTexture",0,nullptr);
    M(camera_set_target,klass("UnityEngine","Camera"),"set_targetTexture",false,"System.Void",1,rtarg);
    M(camera_width,klass("UnityEngine","Camera"),"get_pixelWidth",false,"System.Int32",0,nullptr);
    M(camera_height,klass("UnityEngine","Camera"),"get_pixelHeight",false,"System.Int32",0,nullptr);
    M(texture_width,klass("UnityEngine","Texture"),"get_width",false,"System.Int32",0,nullptr);
    M(texture_height,klass("UnityEngine","Texture"),"get_height",false,"System.Int32",0,nullptr);
    M(camera_update,cm,"Update",false,"System.Void",0,nullptr);
    M(camera_resume,cm,"Resume",false,"System.Void",0,nullptr);
    M(core_camera,klass("LLAS.Scene.Live.Components","LiveCoreCamera"),"get_Camera",false,"UnityEngine.Camera",0,nullptr);
    M(cutin_camera,klass("LLAS.Components.SkillCutin","SkillCutinCamera"),"get_Camera",false,"UnityEngine.Camera",0,nullptr);
    M(quality_get,klass("LLAS.DM.ValueObject","LiveQualitySettingVO"),"get_RenderingResolution",false,"System.Int32",0,nullptr);
    M(quality_set,klass("LLAS.DM.ValueObject","LiveQualitySettingVO"),"set_RenderingResolution",false,"System.Void",1,i);
    M(quality_post_effect,klass("LLAS.DM.ValueObject","LiveQualitySettingVO"),"get_PostEffect",false,"System.Boolean",0,nullptr);
    M(command_clear,klass("UnityEngine.Rendering","CommandBuffer"),"Clear",false,"System.Void",0,nullptr);
    M(command_blit,klass("UnityEngine.Rendering","CommandBuffer"),"Blit",false,"System.Void",2,command_blit_args);
    M(target_identifier,klass("UnityEngine.Rendering","RenderTargetIdentifier"),"op_Implicit",true,"UnityEngine.Rendering.RenderTargetIdentifier",1,texture_arg);
    M(camera_commands,klass("UnityEngine","Camera"),"GetCommandBuffers",false,"UnityEngine.Rendering.CommandBuffer[]",1,event_arg);
    M(camera_clear_get,klass("UnityEngine","Camera"),"get_clearFlags",false,"UnityEngine.CameraClearFlags",0,nullptr);
    M(camera_clear_set,klass("UnityEngine","Camera"),"set_clearFlags",false,"System.Void",1,clear_arg);
    M(resume_broadcast,klass("KLab.MessageBuses","DeferredMessageBus"),"Broadcast",false,"System.Void",0,nullptr);
    M(resume_dispatch,klass("KLab.MessageBuses","DeferredMessageBus"),"Dispatch",false,"System.Void",0,nullptr);
    M(pause_se_voices,mu,"PauseSEAndVoices",false,"System.Void",0,nullptr);
    M(dm_pause_get,klass("LLAS.DM","LiveGamePauseDM"),"get_IsPause",true,"System.Boolean",0,nullptr);
    M(dm_pause_set,klass("LLAS.DM","LiveGamePauseDM"),"SetPause",true,"System.Void",1,b);
    M(dm_wait_get,klass("LLAS.DM","LiveGamePauseDM"),"get_IsWaitingTutorialAction",true,"System.Boolean",0,nullptr);
    M(dm_wait_set,klass("LLAS.DM","LiveGamePauseDM"),"SetWaitingTutorialAction",true,"System.Void",1,b);
    M(state_instance,klass("DotUnder","State"),"get_Inst",true,"DotUnder.StateObject",0,nullptr);
    M(live_state,klass("DotUnder","StateObject"),"get_LiveState",false,"DotUnder.LiveState.LiveState",0,nullptr);
    M(cri_sheet,klass("","CriAtom"),"GetCueSheet",true,"CriAtomCueSheet",1,sheet_args);
    M(find_objects,obj,"FindObjectsOfType",true,"UnityEngine.Object[]",1,type);
    M(timeline,ld,"get_TimelineDirector",false,"UnityEngine.Playables.PlayableDirector",0,nullptr);
    M(camera_manager,ld,"get_CameraManager",false,"LLAS.Scene.Live.Components.LiveCoreCameraManager",0,nullptr);
    M(member_manager,ld,"get_MemberManager",false,"LLAS.Scene.Live.Components.LiveCoreMemberManager",0,nullptr);
    M(music_machine,ld,"get_MusicMachine",false,"LLAS.Scene.Live.Components.LiveMusicMachine",0,nullptr);
    M(final_overlay,cm,"get_OverlayCamera",false,"LLAS.Scene.Live.Components.LiveCoreOverlayCamera",0,nullptr);
    M(reset_components,ld,"ResetComponents",false,"System.Void",1,b);
    M(resize_cameras,cm,"Update3DCameraRenderTextures",false,"System.Void",0,nullptr);
    M(time_get,pd,"get_time",false,"System.Double",0,nullptr);
    M(time_set,pd,"set_time",false,"System.Void",1,d);
    M(mode_set,pd,"set_timeUpdateMode",false,"System.Void",1,mode);
    M(state_get,pd,"get_state",false,"UnityEngine.Playables.PlayState",0,nullptr);
    M(play,pd,"Play",false,"System.Void",0,nullptr); M(stop,pd,"Stop",false,"System.Void",0,nullptr);
    M(pause,pd,"Pause",false,"System.Void",0,nullptr);
    M(evaluate,pd,"Evaluate",false,"System.Void",0,nullptr);
    M(rt_constructor,render,".ctor",false,"System.Void",5,rctor);
    M(rt_create,render,"Create",false,"System.Boolean",0,nullptr);
    M(rt_created,render,"IsCreated",false,"System.Boolean",0,nullptr);
    M(rt_release,render,"Release",false,"System.Void",0,nullptr);
    M(rt_active_get,render,"get_active",true,"UnityEngine.RenderTexture",0,nullptr);
    M(rt_active_set,render,"set_active",true,"System.Void",1,rtarg);
    M(texture_constructor,tex,".ctor",false,"System.Void",4,tctor);
    M(read_pixels,tex,"ReadPixels",false,"System.Void",4,read);
    M(image_pointer,tex,"GetWritableImageData",false,"System.IntPtr",1,i);
    M(image_size,tex,"GetRawImageDataSize",false,"System.Int64",0,nullptr);
    M(blit,klass("UnityEngine","Graphics"),"Blit",true,"System.Void",2,blend);
    M(destroy,obj,"Destroy",true,"System.Void",1,uobj);
    M(job_complete,jobs,"Complete",false,"System.Void",0,nullptr);
    M(apply_transform,mm,"ApplyTransform",false,"System.Void",0,nullptr);
    M(request_safe,mm,"RequestAllSafeCorrect",false,"System.Void",0,nullptr);
    M(manager_bones,sm,"GetSwingBones",false,"LLAS.Components.Members.SwingBone[]",0,nullptr);
    M(manager_pause_get,sm,"get_Paused",false,"System.Boolean",0,nullptr);
    M(manager_pause_set,sm,"set_Paused",false,"System.Void",1,b);
    M(position,tr,"get_position",false,"UnityEngine.Vector3",0,nullptr);
    M(rotation_get,tr,"get_localRotation",false,"UnityEngine.Quaternion",0,nullptr);
    M(rotation_set,tr,"set_localRotation",false,"System.Void",1,q);
    M(sound_pause,klass("LLAS","SoundPlayer"),"Pause",false,"System.Void",1,b);
    M(sound_paused,klass("LLAS","SoundPlayer"),"IsPaused",false,"System.Boolean",0,nullptr);
#undef M
#define F(dst,owner,name,type,sz) if(!field(&f.dst,owner,name,type,sz))return false
    F(loading,mu,"isLoading","System.Boolean",1); F(music_time,mu,"musicPlayingTime","System.Int32",4);
    F(length,mu,"<MusicLength>k__BackingField","System.Int32",4); F(gain,mu,"defaultMusicVolume","System.Single",4);
    F(sound,mu,"soundPlayer",nullptr,8); F(cue,mu,"musicCue",nullptr,8);
    F(playing,mu,"<IsPlayingMusic>k__BackingField","System.Boolean",1);
    F(pausing,mu,"<IsPausingMusic>k__BackingField","System.Boolean",1);
    F(paused,mu,"<IsPausedMusic>k__BackingField","System.Boolean",1);
    F(finished,mu,"<IsFinishedMusic>k__BackingField","System.Boolean",1);
    F(managers,mm,"swingBoneManagers",nullptr,8); F(bone_array,mm,"boneTransforms",nullptr,16);
    F(collider_array,mm,"colliderTransforms",nullptr,16); F(job_index,mm,"keyJobBuffer","System.Int32",4);
    F(safety,mm,"requestSkirtSafeCount","System.Int32",4); F(knee_l,mm,"workKneeL","UnityEngine.Vector3",12);
    F(knee_r,mm,"workKneeR","UnityEngine.Vector3",12); F(jobs_a,mm,"swingBoneJobHandle",nullptr,8);
    F(jobs_b,mm,"transformJobHandle",nullptr,8); F(child,sb,"child","UnityEngine.Transform",8);
    F(transform,sb,"transformCache","UnityEngine.Transform",8);
    F(scalar_first,sb,"localRotation","UnityEngine.Quaternion",16); F(scalar_end,sb,"childOtherRot",nullptr,8);
    F(current_tip,sb,"currentTipPosition","UnityEngine.Vector3",12);
    F(previous_tip,sb,"previousTipPosition","UnityEngine.Vector3",12);
    F(correct_adjust,sb,"<SafeCorrectAdjust>k__BackingField","System.Boolean",1);
    F(ratio,sb,"skirtRotRatio","System.Single",4);
    F(scene_pre_final,scene,"isPreFinalized","System.Boolean",1);
    F(scene_post_final,scene,"isPostFinalized","System.Boolean",1);
    F(scene_paused,scene,"isPause","System.Boolean",1);
    F(overlay_blur,oc,"isBlur","System.Boolean",1);
    F(camera_quality,cm,"liveQualitySetting",nullptr,8);
    F(camera_buffers[0],cm,"beforePostprocessingBuffer","UnityEngine.RenderTexture",8);
    F(camera_buffers[1],cm,"afterPostprocessingBuffer","UnityEngine.RenderTexture",8);
    F(camera_buffers[2],cm,"depthBuffer","UnityEngine.RenderTexture",8);
    F(camera_buffers[3],cm,"captureRenderTexture","UnityEngine.RenderTexture",8);
    F(camera_list,cm,"cameras",nullptr,8);F(camera_cutin,cm,"cutinCamera",nullptr,8);
    F(camera_overlay,cm,"overlayCamera",nullptr,8);F(camera_cutin_overlay,cm,"cutinOverlayCamera",nullptr,8);
    F(core_command_buffers,klass("LLAS.Scene.Live.Components","LiveCoreCamera"),"commandBuffers",nullptr,8);
    F(core_quality,klass("LLAS.Scene.Live.Components","LiveCoreCamera"),"liveQualitySetting",nullptr,8);
    F(camera_current_width,cm,"currentWidth","System.Int32",4);F(camera_current_height,cm,"currentHeight","System.Int32",4);
    F(camera_pause_step,cm,"cameraPauseStep",nullptr,4);
    F(camera_live_blur,cm,"isLiveEndBlur","System.Boolean",1);F(camera_skill_pause,cm,"isSkillCutinPause","System.Boolean",1);
    F(camera_msaa_changed,cm,"isMSAALevelChanged","System.Boolean",1);F(camera_buffer_write,cm,"<BufferWrite>k__BackingField","System.Boolean",1);
    F(scene_mediator,scene,"pauseMediator",nullptr,8);
    F(mediator_state,klass("LLAS.Scene.Live","LivePauseMediator"),"currentState",nullptr,4);
    F(mediator_pause_bus,klass("LLAS.Scene.Live","LivePauseMediator"),"pauseMBus",nullptr,8);
    F(mediator_resume_bus,klass("LLAS.Scene.Live","LivePauseMediator"),"resumeMBus",nullptr,8);
    F(cri_acb,klass("","CriAtomCueSheet"),"acb","CriAtomExAcb",8);
    F(cri_acb_path,klass("","CriAtomCueSheet"),"acbFile","System.String",8);
    F(cri_awb_path,klass("","CriAtomCueSheet"),"awbFile","System.String",8);
#undef F
    if(!waveform_method(klass("","CriAtomExAcb")))return false;
    uint32_t alignment=0;
    if(e.class_value_size(m.target_identifier.owner,&alignment)!=sizeof(RenderTargetIdentifier))return false;
    if (e.class_value_size(jobs,&alignment)!=16 || f.knee_r.offset!=f.knee_l.offset+12 ||
        f.scalar_end.offset<=f.scalar_first.offset || f.scalar_end.offset-f.scalar_first.offset>sizeof(Bone::scalar)) return false;
    // NativeArray descriptors are verified independently in both Android
    // UpdateMultiThread/ApplyTransform/SetSwingBones instruction streams.
    if (f.bone_array.offset!=0x30 || f.collider_array.offset!=0x50 || f.jobs_a.offset!=0xa8 ||
        f.jobs_b.offset!=0xb0 || f.job_index.offset!=0xa4 || f.scalar_first.offset!=0xb0 ||
        f.scalar_end.offset!=0x110 || f.current_tip.offset!=0xc8 || f.previous_tip.offset!=0xd4) return false;
    runtime_ready=true; return true;
}

bool complete_jobs() {
    if (!members) return false;
    const Field *fields[]={&f.jobs_a,&f.jobs_b};
    for (const Field *field:fields) {
        void *array=load<void *>(members,field->offset);
        if (!array) { if (!load<NativeArray>(members,f.bone_array.offset).length) continue; return false; }
        if (length(array,2)!=2) return false;
        for (uint32_t i=0;i<2;i++) {
            // Value-type self is unboxed storage. Original engine invocation
            // contains managed exceptions; no second C++ runtime is used.
            void *exception=nullptr;
            e.runtime_invoke(m.job_complete.info,(uint8_t *)array+32+i*16,nullptr,&exception);
            if (exception) return false;
        }
    }
    return true;
}
void release_pause_snapshot();
bool restore_pause_state();
void free_snapshot() {
    release_pause_snapshot();
    for(uint32_t i=0;i<bone_count;i++){release(&bones[i].bone_root);release(&bones[i].transform_root);release(&bones[i].child_root);}
    for(uint32_t i=0;i<manager_count;i++)if(managers){release(&managers[i].object_root);release(&managers[i].array_root);}
    release(&managers_array_root);managers_array=nullptr;
    free(bones); free(managers); free(bone_bytes); free(collider_bytes); free(pixels);
    bones=nullptr; managers=nullptr; bone_bytes=collider_bytes=nullptr; pixels=nullptr;
    bone_count=manager_count=0;
}
bool snapshot_springs() {
    if (!complete_jobs()) return setup_rejected("Original member swing/transform jobs could not complete before the snapshot");
    saved_bones=load<NativeArray>(members,f.bone_array.offset);
    saved_colliders=load<NativeArray>(members,f.collider_array.offset);
    if (saved_bones.length<0 || saved_bones.length>100000 || saved_colliders.length<0 || saved_colliders.length>100000 ||
        (saved_bones.length&&!saved_bones.data) || (saved_colliders.length&&!saved_colliders.data))
        return setup_rejected("Original spring NativeArray descriptors are invalid (bones=%d, colliders=%d)",saved_bones.length,saved_colliders.length);
    size_t bone_size=(size_t)saved_bones.length*96,collider_size=(size_t)saved_colliders.length*64;
    if (bone_size+collider_size>32*1024*1024)return setup_rejected("Original spring buffers exceed the 32 MiB snapshot limit");
    void *array=load<void *>(members,f.managers.offset);uint32_t count_managers=length(array,128);
    if (count_managers==UINT32_MAX || (!array&&saved_bones.length))return setup_rejected("Original spring manager array is missing or exceeds 128 managers");
    manager_count=count_managers;
    managers_array=array;managers_array_root=root(array);if(array&&!managers_array_root)return false;
    bones=(Bone *)calloc(saved_bones.length?saved_bones.length:1,sizeof(Bone));
    managers=(Manager *)calloc(manager_count?manager_count:1,sizeof(Manager));
    bone_bytes=malloc(bone_size?bone_size:1); collider_bytes=malloc(collider_size?collider_size:1);
    if (!bones || !managers || !bone_bytes || !collider_bytes)return setup_rejected("Not enough memory to snapshot %d spring bones and %d colliders",saved_bones.length,saved_colliders.length);
    saved_job_index=load<int32_t>(members,f.job_index.offset); saved_safety=load<int32_t>(members,f.safety.offset);
    memcpy(saved_knees,(uint8_t *)members+f.knee_l.offset,24);
    for (uint32_t i=0;i<manager_count;i++) {
        void *manager=element(array,i); if (!manager)return setup_rejected("Spring manager %u is null",i);
        uint8_t paused=0; if (!value(m.manager_pause_get,manager,&paused))return setup_rejected("Spring manager %u could not report its pause state",i);
        managers[i].object=manager;managers[i].paused=paused;managers[i].object_root=root(manager);
        if(!managers[i].object_root)return false;
        void *list=reference(m.manager_bones,manager); uint32_t count=length(list,saved_bones.length);
        if (count==UINT32_MAX || count>(uint32_t)saved_bones.length-bone_count)return setup_rejected("Spring manager %u bone count exceeds the original native buffer",i);
        managers[i].array=list;managers[i].array_root=root(list);if(list&&!managers[i].array_root)return false;
        for (uint32_t j=0;j<count;j++) {
            Bone &item=bones[bone_count++]; item.bone=element(list,j);
            if (!field_object(item.bone,f.transform))return setup_rejected("Spring manager %u bone %u is not a valid SwingBone",i,j);
            item.bone_root=root(item.bone);item.transform=load<void *>(item.bone,f.transform.offset);
            item.child=load<void *>(item.bone,f.child.offset);item.transform_root=root(item.transform);item.child_root=root(item.child);
            if (!item.bone_root||!item.transform_root||!item.child_root||!alive(item.transform)||!alive(item.child)||
                !value(m.rotation_get,item.transform,&item.rotation))return setup_rejected("Spring manager %u bone %u has a missing transform/child or unreadable rotation",i,j);
            memcpy(item.scalar,(uint8_t *)item.bone+f.scalar_first.offset,f.scalar_end.offset-f.scalar_first.offset);
        }
    }
    if (bone_count!=(uint32_t)saved_bones.length)return setup_rejected("Spring manager/native bone counts disagree (%u versus %d)",bone_count,saved_bones.length);
    if(bone_size)memcpy(bone_bytes,saved_bones.data,bone_size);
    if(collider_size)memcpy(collider_bytes,saved_colliders.data,collider_size);
    return true;
}
// Manual export must finish evaluating the requested time before a camera
// callback can qualify that output frame. DeferredEvaluate only enqueues work;
// a rendered camera callback is not an acknowledgement of that queue.
bool set_time(double seconds) { void *args[]={&seconds}; return invoke_void(m.time_set,timeline,args)&&invoke_void(m.evaluate,timeline); }
bool restart_timeline_graph() {
    // No-seek mixers keep started/completed clip indices across backward time
    // assignments. Stop destroys that graph; Play constructs fresh mixers with
    // their original -1 index sentinels. Reset the baseline before constructing
    // the new graph, so authored tracks reapply camera/member/stage values.
    uint8_t no=0;void *reset[]={&no};
    return invoke_void(m.stop,timeline)&&invoke_void(m.reset_components,director,reset)&&invoke_void(m.play,timeline);
}
bool reset_springs() {
    uint8_t no=0; void *unpause[]={&no};
    for (uint32_t i=0;i<manager_count;i++) if (!invoke_void(m.manager_pause_set,managers[i].object,unpause)) return false;
    for (uint32_t i=0;i<bone_count;i++) { void *args[]={bones[i].scalar}; if (!invoke_void(m.rotation_set,bones[i].transform,args)) return false; }
    if (!set_time(0) || !invoke_void(m.apply_transform,members)) return false;
    for (uint32_t i=0;i<bone_count;i++) {
        Vec3 tip{}; if (!value(m.position,load<void *>(bones[i].bone,f.child.offset),&tip)) return false;
        put<Vec3>(saved_bones.data,(size_t)i*96+72,tip); put<Vec3>(saved_bones.data,(size_t)i*96+84,tip);
        put<Vec3>(bones[i].bone,f.current_tip.offset,tip); put<Vec3>(bones[i].bone,f.previous_tip.offset,tip);
        put<uint8_t>(bones[i].bone,f.correct_adjust.offset,0); put<float>(bones[i].bone,f.ratio.offset,0);
    }
    return invoke_void(m.request_safe,members);
}
bool scene_valid() {
    return session_director_root && session_overlay_root && scene_root &&
        e.gchandle_get_target(session_director_root)==director && e.gchandle_get_target(session_overlay_root)==session_overlay &&
        e.gchandle_get_target(scene_root)==mv_scene && timeline_root&&e.gchandle_get_target(timeline_root)==timeline&&
        music_root&&e.gchandle_get_target(music_root)==music&&members_root&&e.gchandle_get_target(members_root)==members&&
        camera_manager_root&&e.gchandle_get_target(camera_manager_root)==camera_manager&&sound_root&&e.gchandle_get_target(sound_root)==sound&&
        alive(director)&&alive(timeline)&&alive(music)&&alive(members)&&alive(session_overlay)&&alive(mv_scene)&&
        !load<uint8_t>(mv_scene,f.scene_pre_final.offset)&&!load<uint8_t>(mv_scene,f.scene_post_final.offset)&&
        reference(m.timeline,director)==timeline && reference(m.member_manager,director)==members &&
        reference(m.music_machine,director)==music && reference(m.camera_manager,director)==camera_manager&&
        reference(m.final_overlay,camera_manager)==session_overlay && !load<uint8_t>(music,f.loading.offset)&&
        load<void *>(music,f.sound.offset)==sound&&
        overlay_camera_root&&e.gchandle_get_target(overlay_camera_root)==overlay_camera&&alive(overlay_camera)&&
        reference(m.overlay_camera,session_overlay)==overlay_camera&&pause_mediator_root&&pause_bus_root&&resume_bus_root&&
        e.gchandle_get_target(pause_mediator_root)==pause_mediator&&e.gchandle_get_target(pause_bus_root)==pause_bus&&
        e.gchandle_get_target(resume_bus_root)==resume_bus&&load<void *>(mv_scene,f.scene_mediator.offset)==pause_mediator&&
        load<void *>(pause_mediator,f.mediator_pause_bus.offset)==pause_bus&&load<void *>(pause_mediator,f.mediator_resume_bus.offset)==resume_bus;
}
bool spring_owners_valid() {
    NativeArray b=load<NativeArray>(members,f.bone_array.offset),c=load<NativeArray>(members,f.collider_array.offset);
    if(b.data!=saved_bones.data||b.length!=saved_bones.length||c.data!=saved_colliders.data||c.length!=saved_colliders.length||
        load<void *>(members,f.managers.offset)!=managers_array||
        (managers_array&&e.gchandle_get_target(managers_array_root)!=managers_array)||length(managers_array,128)!=manager_count)return false;
    uint32_t flat=0;
    for(uint32_t i=0;i<manager_count;i++){
        Manager &manager=managers[i];
        if(e.gchandle_get_target(manager.object_root)!=manager.object||element(managers_array,i)!=manager.object||
            reference(m.manager_bones,manager.object)!=manager.array||
            (manager.array&&e.gchandle_get_target(manager.array_root)!=manager.array))return false;
        uint32_t n=length(manager.array,bone_count);if(n==UINT32_MAX||n>bone_count-flat)return false;
        for(uint32_t j=0;j<n;j++,flat++){
            Bone &bone=bones[flat];
            if(element(manager.array,j)!=bone.bone||e.gchandle_get_target(bone.bone_root)!=bone.bone||
                e.gchandle_get_target(bone.transform_root)!=bone.transform||e.gchandle_get_target(bone.child_root)!=bone.child||
                load<void *>(bone.bone,f.transform.offset)!=bone.transform||load<void *>(bone.bone,f.child.offset)!=bone.child||
                !alive(bone.transform)||!alive(bone.child))return false;
        }
    }
    return flat==bone_count;
}
void release_session_roots(){release(&timeline_root);release(&music_root);release(&members_root);release(&camera_manager_root);release(&sound_root);}
void freeze() {
    advancing=false;
    if (clock_manager) for (size_t offset:{size_t(0x78),size_t(0x7c),size_t(0xa8),size_t(0xac)}) put<float>(clock_manager,offset,0);
}
JNIEnv *environment() {
    if (!vm) return nullptr; JNIEnv *env=nullptr;
    jint result=vm->GetEnv((void **)&env,JNI_VERSION_1_6);
    if(result==JNI_OK)return env;
    // Main-thread authority comes from the exact native Unity callbacks, not
    // from attaching to either VM. Java attachment only enables JNI transport.
    return result==JNI_EDETACHED&&own_thread()&&vm->AttachCurrentThread(&env,nullptr)==JNI_OK?env:nullptr;
}
bool restore_render_state();
void release_render_state();
bool restore_scene() {
    bool safe=!abandoned&&scene_valid(),ok=safe;
    active=false; advancing=false;
    if (safe && (!spring_owners_valid()||!complete_jobs())) {
        // Do not race worker jobs with snapshot writes. Retain this one bounded
        // owner/snapshot set and disable further exports instead of guessing
        // that a failed completion means the native buffers are idle.
        safe=false;ok=false;quarantined=true;
    }
    if (clock_manager) {
        double elapsed=now()-wall_start;
        // Restore only fields explicitly controlled by offline simulation.
        // Engine frame counters (+c8/+d0), one-shot flags (+c0/+c1) and other
        // normal Update state must keep advancing; rewinding them invalidates
        // gaze/lighting frame caches after returning to regular MV playback.
        amv_restore_offline_clock(clock_manager,clock_snapshot,elapsed,safe,(int32_t)simulation_hz);
        // Verified startup-wallclock anchors: prevent the next normal frame
        // from absorbing all encoder wall time as one simulation delta.
    }
    if (safe) {
        // The export graph has completed the song. A backward restore on that
        // graph would skip the original MV's earlier lip/light/effect clips.
        ok=restart_timeline_graph()&&ok;
        ok=set_time(saved_time)&&ok;
        NativeArray current=load<NativeArray>(members,f.bone_array.offset),colliders=load<NativeArray>(members,f.collider_array.offset);
        if (current.data!=saved_bones.data || current.length!=saved_bones.length ||
            colliders.data!=saved_colliders.data || colliders.length!=saved_colliders.length) ok=false;
        else {
            if(saved_bones.length)memcpy(saved_bones.data,bone_bytes,(size_t)saved_bones.length*96);
            if(saved_colliders.length)memcpy(saved_colliders.data,collider_bytes,(size_t)saved_colliders.length*64);
            put<int32_t>(members,f.job_index.offset,saved_job_index); put<int32_t>(members,f.safety.offset,saved_safety);
            memcpy((uint8_t *)members+f.knee_l.offset,saved_knees,24);
            for (uint32_t i=0;i<bone_count;i++) {
                memcpy((uint8_t *)bones[i].bone+f.scalar_first.offset,bones[i].scalar,f.scalar_end.offset-f.scalar_first.offset);
                void *args[]={&bones[i].rotation}; ok=invoke_void(m.rotation_set,bones[i].transform,args)&&ok;
            }
            for (uint32_t i=0;i<manager_count;i++) { void *args[]={&managers[i].paused}; ok=invoke_void(m.manager_pause_set,managers[i].object,args)&&ok; }
        }
        void *mode[]={&saved_mode}; ok=invoke_void(m.mode_set,timeline,mode)&&ok;
        ok=invoke_void(saved_state==1?m.play:m.pause,timeline)&&ok;
        put<int32_t>(music,f.music_time.offset,saved_music_time);
        const Field *flags[]={&f.playing,&f.pausing,&f.paused,&f.finished};
        for (unsigned i=0;i<4;i++) put<uint8_t>(music,flags[i]->offset,saved_music_flags[i]);
        void *paused[]={&saved_sound_pause}; ok=invoke_void(m.sound_pause,sound,paused)&&ok;
        ok=restore_pause_state()&&ok;
        // Timeline evaluation can change camera tracks. Restore the original
        // paused camera/blur/enabled state only after that evaluation.
        ok=restore_render_state()&&ok;
    }
    if (rt) { ok=invoke_void(m.rt_release,rt)&&ok; void *args[]={rt}; ok=invoke_void(m.destroy,nullptr,args)&&ok; }
    if (texture) { void *args[]={texture}; ok=invoke_void(m.destroy,nullptr,args)&&ok; }
    release(&rt_root); release(&texture_root);
    rt=texture=nullptr;
    if(!quarantined){release(&session_director_root); release(&session_overlay_root); release(&scene_root);release(&overlay_camera_root);
        release_session_roots();session_overlay=mv_scene=nullptr;free_snapshot();release_render_state();}
    pending_pixels=awaiting_capture=finishing=frame_ready=false; publish(); return ok;
}
void dispatch_terminal() {
    if(!terminal.pending)return;
    Terminal done=terminal;terminal={};
    pthread_mutex_lock(&guard);request_busy=false;pthread_mutex_unlock(&guard);
    if(done.success){phase("finished");if(done.callback.finished)done.callback.finished(done.callback.context,done.path);}
    else {record_failure(done.message);phase("failed");if(done.callback.failed)done.callback.failed(done.callback.context,done.message);}
}
void end_notification(const AmvGameCallbacks &callback,bool success,const char *path,const char *message) {
    terminal={};terminal.pending=true;terminal.success=success;terminal.callback=callback;
    if(path)snprintf(terminal.path,sizeof(terminal.path),"%s",path);
    if(message){if(!success&&managed_failure[0])snprintf(terminal.message,sizeof(terminal.message),"%s | %s",managed_failure,message);
        else snprintf(terminal.message,sizeof(terminal.message),"%s",message);}
    dispatch_terminal();
}
void fail(const char *message) {
    AmvGameCallbacks callback=sink;
    JNIEnv *env=environment(); if (env&&encoder) { jthrowable error=nullptr; amv_encoder_cancel(env,encoder,&error); if(error)env->DeleteLocalRef(error); }
    bool restored=true;
    if (active) restored=restore_scene(); else {
        release(&session_director_root); release(&session_overlay_root); release(&scene_root);release(&overlay_camera_root);
        release_session_roots();free_snapshot();release_render_state();
    }
    if(!restored&&quarantined)message="MV spring jobs did not complete safely; retained scene roots require restarting the game before another export";
    record_failure(message); phase("failed");
    // Java worker retains its encoder until cleanup; all native calls have
    // stopped before releasing this global reference/bridge handle.
    if (env&&encoder) amv_encoder_unbind(env,encoder); encoder=nullptr;
    sink={};end_notification(callback,false,nullptr,message);publish();
}
bool managed_string(void *string,char *out,size_t capacity) {
    if (!string || !capacity) return false;
    int32_t count=e.string_length(string); const uint16_t *chars=e.string_chars(string);
    if (count<1 || count>255 || !chars) return false;
    // Cue identifiers in the actual catalogs are ASCII; never silently mangle
    // another Unicode cue into a different asset lookup.
    if ((size_t)count>=capacity) return false;
    for (int32_t i=0;i<count;i++) { if (chars[i]<32||chars[i]>126)return false; out[i]=(char)chars[i]; }
    out[count]=0; return true;
}
bool utf8_string(void *string,char *out,size_t capacity,bool optional=false) {
    if(!capacity)return false;out[0]=0;if(!string)return optional;
    int32_t count=e.string_length(string);const uint16_t *chars=e.string_chars(string);
    if(count<0||!chars)return false;size_t at=0;
    for(int32_t i=0;i<count;i++){
        uint32_t code=chars[i];
        if(code>=0xd800&&code<=0xdbff){if(++i>=count||chars[i]<0xdc00||chars[i]>0xdfff)return false;code=0x10000+((code-0xd800)<<10)+(chars[i]-0xdc00);}
        else if(code>=0xdc00&&code<=0xdfff)return false;
        if(!code)return false;uint8_t bytes[4];unsigned n=0;
        if(code<0x80){bytes[n++]=(uint8_t)code;}else if(code<0x800){bytes[n++]=0xc0|(code>>6);bytes[n++]=0x80|(code&63);}
        else if(code<0x10000){bytes[n++]=0xe0|(code>>12);bytes[n++]=0x80|((code>>6)&63);bytes[n++]=0x80|(code&63);}
        else{bytes[n++]=0xf0|(code>>18);bytes[n++]=0x80|((code>>12)&63);bytes[n++]=0x80|((code>>6)&63);bytes[n++]=0x80|(code&63);}
        if(n>=capacity-at)return false;for(unsigned j=0;j<n;j++)out[at++]=(char)bytes[j];
    }
    out[at]=0;return optional||at>0;
}
bool audio_selection(AmvGameStatus *status,AmvAudioSelection *selection) {
    if(!runtime_ready||!director||!observed_director_root||e.gchandle_get_target(observed_director_root)!=director||!alive(director))return false;
    void *machine=reference(m.music_machine,director);
    if(!alive(machine)||load<uint8_t>(machine,f.loading.offset))return false;
    void *cue=load<void *>(machine,f.cue.offset);if(!cue)return false;
    void *owner=e.object_get_class(cue);
    if(!field(&f.cue_sheet,owner,"<CueSheetName>k__BackingField","System.String",8)||
        !field(&f.cue_name,owner,"<CueName>k__BackingField","System.String",8))return false;
    void *sheet_name=load<void *>(cue,f.cue_sheet.offset),*cue_name=load<void *>(cue,f.cue_name.offset);
    if(!managed_string(sheet_name,status->cue_sheet,sizeof(status->cue_sheet))||
        !managed_string(cue_name,status->cue_name,sizeof(status->cue_name)))return false;
    void *sheet_args[]={sheet_name};void *sheet=reference(m.cri_sheet,nullptr,sheet_args);
    if(!sheet||!field_object(sheet,f.cri_acb))return false;
    void *acb=load<void *>(sheet,f.cri_acb.offset);if(!acb)return false;
    if(!utf8_string(load<void *>(sheet,f.cri_acb_path.offset),status->acb_path,sizeof(status->acb_path))||
        !utf8_string(load<void *>(sheet,f.cri_awb_path.offset),status->awb_path,sizeof(status->awb_path),true))return false;
    alignas(8) uint8_t info[40]={};uint8_t found=0;void *wave_args[]={cue_name,info};
    if(!value(m.cri_waveform,acb,&found,wave_args)||!found)return false;
    int32_t rate=load<int32_t>(info,f.wave_rate.offset-16),channels=load<int32_t>(info,f.wave_channels.offset-16);
    int64_t samples=load<int64_t>(info,f.wave_samples.offset-16);uint32_t wave=load<uint32_t>(info,f.wave_id.offset-16);
    uint32_t streaming=load<uint8_t>(info,f.wave_streaming.offset-16);
    if(rate<8000||rate>96000||channels<1||channels>2||samples<=0||streaming>1||(streaming&&!status->awb_path[0]))return false;
    status->source_rate=(uint32_t)rate;status->source_channels=(uint32_t)channels;status->source_samples=(uint64_t)samples;
    status->wave_id=wave;status->streaming=streaming;
    status->music_length_ms=load<int32_t>(machine,f.length.offset);status->current_time_ms=load<int32_t>(machine,f.music_time.offset);
    status->gain=load<float>(machine,f.gain.offset);if(status->music_length_ms<=0||!isfinite(status->gain)||status->gain<0)return false;
    *selection={};selection->abi_version=AMV_AUDIO_ABI;selection->wave_id=wave;selection->streaming=streaming;
    selection->sample_rate=rate;selection->channels=channels;selection->source_samples=samples;selection->gain=status->gain;
    selection->music_length_ms=status->music_length_ms;
    // Android LoadMusic/SetMusicStartTime/SeekMusic zero-start chains are part
    // of the source audit. No speaker/audio-wallclock capture is used.
    selection->start_time_ms=0;selection->source_offset_ms=0;
    memcpy(selection->acb_path,status->acb_path,sizeof(selection->acb_path));memcpy(selection->awb_path,status->awb_path,sizeof(selection->awb_path));
    uint64_t fingerprint=1469598103934665603ULL;uint32_t gain_bits=0;memcpy(&gain_bits,&selection->gain,4);
    // C struct padding is not identity. Hash canonical strings and scalar
    // values only so query and Begin can compare exactly the same selection.
    const uint64_t numbers[]={wave,streaming,(uint32_t)rate,(uint32_t)channels,(uint64_t)samples,
        (uint32_t)selection->music_length_ms,(uint32_t)selection->start_time_ms,(uint32_t)selection->source_offset_ms,gain_bits};
    const uint8_t *parts[]={ (const uint8_t *)status->cue_sheet,(const uint8_t *)status->cue_name,
        (const uint8_t *)selection->acb_path,(const uint8_t *)selection->awb_path,(const uint8_t *)numbers };
    size_t sizes[]={strlen(status->cue_sheet)+1,strlen(status->cue_name)+1,strlen(selection->acb_path)+1,
        strlen(selection->awb_path)+1,sizeof(numbers)};
    for(unsigned p=0;p<5;p++)for(size_t i=0;i<sizes[p];i++){fingerprint^=parts[p][i];fingerprint*=1099511628211ULL;}
    status->song_fingerprint=fingerprint?fingerprint:1;return true;
}
void observe(void *value) {
    if (director!=value) {
        release(&observed_director_root); release(&observed_overlay_root);
        observed_director_root=root(value); director=observed_director_root?value:nullptr; overlay=nullptr;
    }
    AmvGameStatus snapshot{}; snapshot.installed=installed; snapshot.region=region;
    if (runtime_ready&&director&&alive(director)) {
        void *machine=reference(m.music_machine,director),*manager=reference(m.camera_manager,director);
        void *final=manager?reference(m.final_overlay,manager):nullptr;
        if (machine&&alive(machine)&&!load<uint8_t>(machine,f.loading.offset)) {
            snapshot.music_length_ms=load<int32_t>(machine,f.length.offset);
            snapshot.current_time_ms=load<int32_t>(machine,f.music_time.offset); snapshot.gain=load<float>(machine,f.gain.offset);
            void *cue=load<void *>(machine,f.cue.offset);
            if (cue) {
                void *c=e.object_get_class(cue);
                if (field(&f.cue_sheet,c,"<CueSheetName>k__BackingField","System.String",8)&&
                    field(&f.cue_name,c,"<CueName>k__BackingField","System.String",8)) {
                    managed_string(load<void *>(cue,f.cue_sheet.offset),snapshot.cue_sheet,sizeof(snapshot.cue_sheet));
                    managed_string(load<void *>(cue,f.cue_name.offset),snapshot.cue_name,sizeof(snapshot.cue_name));
                }
            }
            snapshot.ready=!quarantined&&observed_overlay_root&&overlay==final&&snapshot.music_length_ms>0&&snapshot.cue_sheet[0]&&snapshot.cue_name[0];
            AmvAudioSelection selection{};if(!audio_selection(&snapshot,&selection))snapshot.ready=0;
        }
    }
    pthread_mutex_lock(&guard);
    snprintf(snapshot.phase,sizeof(snapshot.phase),"%s",cached.phase);
    snprintf(snapshot.failure,sizeof(snapshot.failure),"%s",cached.failure); cached=snapshot;
    pthread_mutex_unlock(&guard);
}
void release_pause_snapshot() {
    release(&pause_mediator_root);release(&pause_bus_root);release(&resume_bus_root);
    release(&pause_state_owner_root);release(&pause_live_state_root);pause_state_owner=pause_live_state=nullptr;
    pause_mediator=pause_bus=resume_bus=nullptr;common_resume_sent=false;
}
bool snapshot_pause_state() {
    pause_mediator=load<void *>(mv_scene,f.scene_mediator.offset);pause_mediator_root=root(pause_mediator);
    if(!pause_mediator_root||!field_object(pause_mediator,f.mediator_state))return setup_rejected("Could not retain the current MV pause mediator");
    saved_pause_state=load<int32_t>(pause_mediator,f.mediator_state.offset);
    if(saved_pause_state!=0&&saved_pause_state!=2)return setup_rejected("The MV pause/resume transition is still in progress (state %d); wait for it to finish before exporting",saved_pause_state);
    pause_bus=load<void *>(pause_mediator,f.mediator_pause_bus.offset);resume_bus=load<void *>(pause_mediator,f.mediator_resume_bus.offset);
    pause_bus_root=root(pause_bus);resume_bus_root=root(resume_bus);
    if(!pause_bus_root||!resume_bus_root)return setup_rejected("Could not retain the current MV registered pause/resume buses");
    void *parent=e.class_get_parent(e.object_get_class(pause_bus));const char *types[]={"LLAS.MBus.Live.PauseMessage"};
    if(!method(&m.pause_broadcast,parent,"Broadcast",false,"System.Void",1,types)||
       !method(&m.pause_dispatch,parent,"Dispatch",false,"System.Void",0,nullptr))return setup_rejected("The current MV pause bus does not match the original PauseMessage/Dispatch interfaces");
    void *message=e.class_from_type(e.method_get_param(m.pause_broadcast.info,0));uint32_t alignment=0;Field waiting{};
    if(!message||e.class_value_size(message,&alignment)!=1||
       !field(&waiting,message,"<IsWaitingTutorialAction>k__BackingField","System.Boolean",1)||waiting.offset!=16)
        return setup_rejected("The current MV PauseMessage is not the verified one-byte Boolean value type");
    if(!value(m.dm_pause_get,nullptr,&saved_dm_pause)||!value(m.dm_wait_get,nullptr,&saved_tutorial_wait))
        return setup_rejected("Could not snapshot the current MV pause/tutorial state");
    Result state=invoke(m.state_instance,nullptr);if(!state.ok||!state.value)return setup_rejected("The current MV has no readable DotUnder state owner");
    pause_state_owner=state.value;pause_state_owner_root=root(pause_state_owner);
    Result live=invoke(m.live_state,pause_state_owner);if(!live.ok)return setup_rejected("Could not inspect whether a gameplay LiveState exists for tutorial flags");
    pause_live_state=live.value;pause_live_state_root=root(pause_live_state);
    if(!pause_state_owner_root||(pause_live_state&&!pause_live_state_root))return setup_rejected("Could not retain the current MV/gameplay state ownership");
    if(!pause_live_state&&saved_tutorial_wait)return setup_rejected("Tutorial waiting is set without a gameplay LiveState");
    return true;
}
bool set_waiting_flag(uint8_t *waiting) {
    // Original getter treats absent gameplay LiveState as false; its setter
    // dereferences that state unconditionally. MV-only scenes have no such
    // state to mutate. Never create a gameplay state just to write this flag.
    if(!pause_live_state)return true;
    Result state=invoke(m.state_instance,nullptr),live=state.ok&&state.value==pause_state_owner?invoke(m.live_state,state.value):Result{false,nullptr};
    if(!state.ok||state.value!=pause_state_owner||!live.ok||live.value!=pause_live_state||
       e.gchandle_get_target(pause_state_owner_root)!=pause_state_owner||e.gchandle_get_target(pause_live_state_root)!=pause_live_state){
        if(!managed_failure[0])snprintf(managed_failure,sizeof(managed_failure),"SetWaitingTutorialAction: original gameplay LiveState ownership changed");return false;}
    void *args[]={waiting};return invoke_void(m.dm_wait_set,nullptr,args);
}
bool restore_pause_flags() {
    void *paused[]={&saved_dm_pause};
    bool ok=invoke_void(m.dm_pause_set,nullptr,paused);
    return set_waiting_flag(&saved_tutorial_wait)&&ok;
}
bool resume_pause_state() {
    if(saved_pause_state!=2)return true;
    // Use this MV's original registered receiver graph, including stage cameras,
    // mixers, heads/eyes, shafts, thread sleeper, SE/voices and time-scale owner.
    // Broadcast is deferred, so synchronously drain this same retained bus.
    common_resume_sent=true;
    uint8_t no=0;void *clear_flags[]={&no};
    bool cleared=invoke_void(m.dm_pause_set,nullptr,clear_flags);
    cleared=set_waiting_flag(&no)&&cleared;
    if(!cleared){restore_pause_flags();return setup_rejected("Could not clear the current MV pause/tutorial flags before resuming its receivers");}
    if(!invoke_void(m.resume_broadcast,resume_bus)||!invoke_void(m.resume_dispatch,resume_bus)||
       load<int32_t>(pause_mediator,f.mediator_state.offset)!=0){restore_pause_flags();return setup_rejected("The current MV registered resume handlers did not complete");}
    uint8_t yes=1;void *args[]={&yes};
    if(!invoke_void(m.pause_se_voices,music)||!invoke_void(m.sound_pause,sound,args)){
        restore_pause_flags();return setup_rejected("Could not silence the original MV music/SE/voices after resuming its render components");}
    return true;
}
bool restore_pause_state() {
    if(!common_resume_sent)return true;
    if(!restore_pause_flags())return false;
    uint8_t message=saved_tutorial_wait;void *args[]={&message};
    bool restored=invoke_void(m.pause_broadcast,pause_bus,args)&&invoke_void(m.pause_dispatch,pause_bus)&&
       load<int32_t>(pause_mediator,f.mediator_state.offset)==saved_pause_state;
    return restore_pause_flags()&&restored;
}
bool remember_camera(void *camera) {
    if(!alive(camera))return false;
    for(uint32_t i=0;i<render_camera_count;i++)if(render_cameras[i].camera==camera)return true;
    if(render_camera_count>=sizeof(render_cameras)/sizeof(render_cameras[0]))return false;
    CameraSnapshot &item=render_cameras[render_camera_count++];item={};item.camera=camera;item.handle=root(camera);
    return item.handle&&value(m.behaviour_enabled,camera,&item.enabled);
}
bool suspend_rendering(bool suspend) {
    if(suspend==cameras_suspended)return true;
    bool ok=true;
    for(uint32_t i=0;i<render_camera_count;i++){
        CameraSnapshot &item=render_cameras[i];uint8_t enabled=suspend?0:item.render_enabled;
        if(suspend)ok=value(m.behaviour_enabled,item.camera,&item.render_enabled)&&ok;
        void *args[]={&enabled};ok=invoke_void(m.behaviour_set_enabled,item.camera,args)&&ok;
    }
    cameras_suspended=suspend;return ok;
}
void release_render_state() {
    scoped_render_dimensions=false;
    if(render_chain_rebuilt&&saved_capture&&alive(saved_capture)){
        invoke_void(m.rt_release,saved_capture);void *args[]={saved_capture};invoke_void(m.destroy,nullptr,args);
    }
    for(uint32_t i=0;i<render_camera_count;i++)release(&render_cameras[i].handle);
    for(uint32_t i=0;i<4;i++){release(&internal_roots[i]);internal_targets[i]=nullptr;}
    release(&quality_root);release(&saved_capture_root);release(&saved_final_target_root);
    render_camera_count=0;quality=saved_capture=saved_final_target=nullptr;
    render_state_saved=render_chain_rebuilt=cameras_suspended=resolution_ready=false;
}
bool snapshot_render_state() {
    quality=load<void *>(camera_manager,f.camera_quality.offset);quality_root=root(quality);
    if(!quality_root||!value(m.quality_get,quality,&saved_quality_resolution))return setup_rejected("Could not retain the original MV rendering quality");
    Result target=invoke(m.camera_target,overlay_camera);if(!target.ok)return setup_rejected("Could not read the original final MV camera target");
    saved_final_target=target.value;saved_final_target_root=root(saved_final_target);
    if(saved_final_target&&!saved_final_target_root)return setup_rejected("Could not retain the original final MV target texture");
    if(!value(m.camera_clear_get,overlay_camera,&saved_overlay_clear))return setup_rejected("Could not snapshot final MV camera clear flags");
    saved_capture=load<void *>(camera_manager,f.camera_buffers[3].offset);saved_capture_root=root(saved_capture);
    if(saved_capture&&!saved_capture_root)return setup_rejected("Could not retain the original paused MV frame");
    saved_scene_paused=load<uint8_t>(mv_scene,f.scene_paused.offset);saved_overlay_blur=load<uint8_t>(session_overlay,f.overlay_blur.offset);
    if(!value(m.behaviour_enabled,session_overlay,&saved_overlay_effect))return setup_rejected("Could not snapshot the original MV compositor enabled state");
    saved_camera_pause_step=load<int32_t>(camera_manager,f.camera_pause_step.offset);
    saved_camera_live_blur=load<uint8_t>(camera_manager,f.camera_live_blur.offset);
    saved_camera_skill_pause=load<uint8_t>(camera_manager,f.camera_skill_pause.offset);
    saved_camera_msaa_changed=load<uint8_t>(camera_manager,f.camera_msaa_changed.offset);
    saved_buffer_write=load<uint8_t>(camera_manager,f.camera_buffer_write.offset);
    saved_manager_width=load<int32_t>(camera_manager,f.camera_current_width.offset);
    saved_manager_height=load<int32_t>(camera_manager,f.camera_current_height.offset);
    void *list=load<void *>(camera_manager,f.camera_list.offset);uint32_t count=length(list,128);
    if(count==UINT32_MAX)return setup_rejected("MV camera list exceeds the verified camera snapshot bounds");
    for(uint32_t i=0;i<count;i++)if(!remember_camera(reference(m.core_camera,element(list,i))))return setup_rejected("Could not snapshot MV camera %u",i);
    void *cutin=load<void *>(camera_manager,f.camera_cutin.offset);
    if(alive(cutin)&&!remember_camera(reference(m.cutin_camera,cutin)))return setup_rejected("Could not snapshot the MV cut-in camera");
    const Field *overlays[]={&f.camera_overlay,&f.camera_cutin_overlay};
    for(const Field *field:overlays){void *item=load<void *>(camera_manager,field->offset);
        if(alive(item)&&!remember_camera(reference(m.overlay_camera,item)))return setup_rejected("Could not snapshot an MV overlay camera");}
    if(!remember_camera(overlay_camera))return setup_rejected("Could not snapshot the final MV camera");
    render_state_saved=true;return true;
}
bool target_allocated(void *target) {
    int32_t width=0,height=0;uint8_t created=0;
    return alive(target)&&value(m.texture_width,target,&width)&&value(m.texture_height,target,&height)&&
        width==(int32_t)config.width&&height==(int32_t)config.height&&value(m.rt_created,target,&created)&&created;
}
bool render_targets_valid() {
    uint8_t created=0;
    if(!resolution_ready||!rt_root||e.gchandle_get_target(rt_root)!=rt||!value(m.rt_created,rt,&created)||!created)return false;
    Result target=invoke(m.camera_target,overlay_camera);if(!target.ok||target.value!=rt)return false;
    for(uint32_t i=0;i<4;i++)if(load<void *>(camera_manager,f.camera_buffers[i].offset)!=internal_targets[i]||
        (internal_targets[i]&&(!internal_roots[i]||e.gchandle_get_target(internal_roots[i])!=internal_targets[i])))return false;
    return true;
}
bool route_final_blits() {
    RenderTargetIdentifier destination{};void *target_args[]={rt};
    if(!value(m.target_identifier,nullptr,&destination,target_args))return setup_rejected("Unity could not construct the owned MV RenderTargetIdentifier");
    void *list=load<void *>(camera_manager,f.camera_list.offset);uint32_t count=length(list,128);
    if(count==UINT32_MAX)return setup_rejected("Original MV camera list changed during target construction");
    for(uint32_t i=0;i<count;i++){
        void *core=element(list,i),*commands=field_object(core,f.core_command_buffers)?load<void *>(core,f.core_command_buffers.offset):nullptr;
        void *owner=commands?e.object_get_class(commands):nullptr;Field items{},size{};
        if(!field(&items,owner,"_items",nullptr,8)||!field(&size,owner,"_size","System.Int32",4)||load<int32_t>(commands,size.offset)!=1)
            return setup_rejected("MV camera %u does not expose its original single final-blit command buffer",i);
        void *array=load<void *>(commands,items.offset);uint32_t capacity=length(array,UINT32_MAX-1);
        if(capacity==UINT32_MAX||!capacity)return setup_rejected("MV camera %u final command-buffer list is empty",i);
        void *core_settings=load<void *>(core,f.core_quality.offset);uint8_t post_effect=0;
        if(!value(m.quality_post_effect,core_settings,&post_effect))return setup_rejected("Could not read MV camera %u original post-effect setting",i);
        void *buffer=element(array,0),*source=internal_targets[post_effect?1:0];
        if(!source)return setup_rejected("MV camera %u original %s output texture is missing",i,post_effect?"post-effect":"color");
        void *args[]={source,&destination};
        // Replace only the original game's final copy. Its original stage
        // target buffers, post-FX materials and processing remain intact.
        if(!invoke_void(m.command_clear,buffer)||!invoke_void(m.command_blit,buffer,args))
            return setup_rejected("Could not route MV camera %u final post-processing output to the owned target",i);
    }
    void *cutin=load<void *>(camera_manager,f.camera_cutin.offset);
    if(alive(cutin)){
        void *camera=reference(m.cutin_camera,cutin);int32_t after_everything=20;void *event_args[]={&after_everything};
        void *array=reference(m.camera_commands,camera,event_args);
        if(length(array,2)!=1)return setup_rejected("MV cut-in camera does not have its original single final-blit command buffer");
        void *args[]={internal_targets[0],&destination};void *buffer=element(array,0);
        if(!invoke_void(m.command_clear,buffer)||!invoke_void(m.command_blit,buffer,args))return setup_rejected("Could not route the original MV cut-in output to the owned target");
    }
    return true;
}
bool create_render_targets() {
    put<uint8_t>(mv_scene,f.scene_paused.offset,0);put<uint8_t>(session_overlay,f.overlay_blur.offset,0);
    put<uint8_t>(camera_manager,f.camera_live_blur.offset,0);put<uint8_t>(camera_manager,f.camera_skill_pause.offset,0);
    if(!invoke_void(m.camera_resume,camera_manager))return setup_rejected("The original MV camera manager could not resume its cameras for offline rendering");
    // Retain the original pause-frame texture instead of releasing its pixels.
    // The original manager creates/wires the entire stage/post-FX/depth chain.
    put<void *>(camera_manager,f.camera_buffers[3].offset,nullptr);render_chain_rebuilt=true;
    int32_t height=config.height;void *quality_args[]={&height};
    if(!invoke_void(m.quality_set,quality,quality_args))return setup_rejected("Could not set the offline MV intermediate render height");
    put<int32_t>(camera_manager,f.camera_current_width.offset,-1);put<int32_t>(camera_manager,f.camera_current_height.offset,-1);
    scoped_render_dimensions=true;bool rebuilt=invoke_void(m.camera_update,camera_manager);scoped_render_dimensions=false;
    void *restore_quality[]={&saved_quality_resolution};bool restored=invoke_void(m.quality_set,quality,restore_quality);
    // Normal game/UI Screen queries remain real. Prevent automatic per-frame
    // reconstruction of these verified offline targets at the device size.
    put<int32_t>(camera_manager,f.camera_current_width.offset,saved_width);put<int32_t>(camera_manager,f.camera_current_height.offset,saved_height);
    if(!rebuilt||!restored)return setup_rejected("Original MV stage/post-processing render-target construction failed");
    for(uint32_t i=0;i<4;i++){
        internal_targets[i]=load<void *>(camera_manager,f.camera_buffers[i].offset);internal_roots[i]=root(internal_targets[i]);
        if(internal_targets[i]){uint8_t created=0;
            if(!value(m.rt_created,internal_targets[i],&created)||(!created&&(!value(m.rt_create,internal_targets[i],&created)||!created)))
                return setup_rejected("Unity could not create MV intermediate target %u at %u x %u",i,config.width,config.height);}
        if((i!=1||internal_targets[i])&&(!internal_roots[i]||!target_allocated(internal_targets[i])))
            return setup_rejected("MV intermediate target %u was not actually allocated at %u x %u",i,config.width,config.height);
    }
    int32_t width=config.width,depth=24,format=0,read_write=0;void *args[]={&width,&height,&depth,&format,&read_write};
    rt=e.object_new(m.rt_constructor.owner);rt_root=root(rt);uint8_t created=0;
    if(!rt_root||!invoke_void(m.rt_constructor,rt,args)||!value(m.rt_create,rt,&created)||!created||!target_allocated(rt))
        return setup_rejected("Unity could not allocate the independent %u x %u final MV RenderTexture",config.width,config.height);
    if(!route_final_blits())return false;
    void *target[]={rt};if(!invoke_void(m.camera_set_target,overlay_camera,target))return setup_rejected("Could not attach the independent final MV RenderTexture");
    int32_t do_not_clear=4;void *clear_args[]={&do_not_clear};
    if(!invoke_void(m.camera_clear_set,overlay_camera,clear_args))return setup_rejected("Could not preserve the composed MV pixels for its final overlay camera");
    uint8_t effect=0;if(!value(m.behaviour_enabled,session_overlay,&effect))return setup_rejected("Could not read the original MV compositor after target construction");
    capture_after_overlay=effect!=0;resolution_ready=true;return true;
}
bool restore_render_state() {
    if(!render_state_saved)return true;
    scoped_render_dimensions=false;bool ok=true;void *target[]={saved_final_target};
    ok=invoke_void(m.camera_set_target,overlay_camera,target)&&ok;
    void *clear_args[]={&saved_overlay_clear};ok=invoke_void(m.camera_clear_set,overlay_camera,clear_args)&&ok;
    if(render_chain_rebuilt){
        void *quality_args[]={&saved_quality_resolution};ok=invoke_void(m.quality_set,quality,quality_args)&&ok;
        put<uint8_t>(camera_manager,f.camera_live_blur.offset,0);put<int32_t>(camera_manager,f.camera_pause_step.offset,0);
        put<int32_t>(camera_manager,f.camera_current_width.offset,-1);put<int32_t>(camera_manager,f.camera_current_height.offset,-1);
        ok=invoke_void(m.camera_update,camera_manager)&&ok;
        void *capture=load<void *>(camera_manager,f.camera_buffers[3].offset);
        if(saved_capture&&alive(saved_capture)&&alive(capture)){void *args[]={saved_capture,capture};ok=invoke_void(m.blit,nullptr,args)&&ok;}
    }
    put<uint8_t>(mv_scene,f.scene_paused.offset,saved_scene_paused);put<uint8_t>(session_overlay,f.overlay_blur.offset,saved_overlay_blur);
    void *effect[]={&saved_overlay_effect};ok=invoke_void(m.behaviour_set_enabled,session_overlay,effect)&&ok;
    put<int32_t>(camera_manager,f.camera_pause_step.offset,saved_camera_pause_step);
    put<uint8_t>(camera_manager,f.camera_live_blur.offset,saved_camera_live_blur);put<uint8_t>(camera_manager,f.camera_skill_pause.offset,saved_camera_skill_pause);
    put<uint8_t>(camera_manager,f.camera_msaa_changed.offset,saved_camera_msaa_changed);put<uint8_t>(camera_manager,f.camera_buffer_write.offset,saved_buffer_write);
    put<int32_t>(camera_manager,f.camera_current_width.offset,saved_manager_width);put<int32_t>(camera_manager,f.camera_current_height.offset,saved_manager_height);
    for(uint32_t i=0;i<render_camera_count;i++){void *args[]={&render_cameras[i].enabled};ok=invoke_void(m.behaviour_set_enabled,render_cameras[i].camera,args)&&ok;}
    cameras_suspended=false;return ok;
}
bool begin(const Request &begin_request) {
    setup_failure[0]=0;managed_failure[0]=0;
    config=begin_request.config; sink=begin_request.sink; encoder=begin_request.encoder; vm=begin_request.vm;
    if (!runtime_ready) return setup_rejected("MV export interfaces have not initialized; reopen a 3D MV");
    if (!director || !observed_director_root) return setup_rejected("No loaded 3D MV director is available");
    if (!observed_overlay_root) return setup_rejected("The MV final camera has not rendered yet; resume the MV and try again");
    if (!clock_manager) return setup_rejected("Unity has not supplied the MV clock");
    if (!environment()) return setup_rejected("The Unity render thread could not access the Android encoder");
    timeline=reference(m.timeline,director); music=reference(m.music_machine,director); members=reference(m.member_manager,director);
    camera_manager=reference(m.camera_manager,director); session_overlay=reference(m.final_overlay,camera_manager);
    if (!alive(timeline)) return setup_rejected("The loaded MV timeline is missing or was destroyed");
    if (!alive(music)) return setup_rejected("The loaded MV music player is missing or was destroyed");
    if (!alive(members)) return setup_rejected("The loaded MV member manager is missing or was destroyed");
    if (!alive(session_overlay)||session_overlay!=overlay) return setup_rejected("The MV final camera changed while preparing audio; try again");
    if (load<uint8_t>(music,f.loading.offset)) return setup_rejected("The MV music is still loading; wait for playback before exporting");
    overlay_camera=reference(m.overlay_camera,session_overlay);uint8_t effect=1;
    Result custom=invoke(m.camera_target,overlay_camera);
    if(!alive(overlay_camera))return setup_rejected("The final MV overlay has no live Unity camera");
    if(!value(m.behaviour_enabled,session_overlay,&effect))return setup_rejected("Unity could not read the final MV compositor state");
    if(!custom.ok)return setup_rejected("Unity could not read the final MV camera target");
    // enabled is the normal image compositor, not the pause flag. Run its
    // original OnRenderImage and capture that output; never bypass its effects.
    capture_after_overlay=effect!=0;
    using Dimension=int32_t(*)(const void *);
    saved_width=((Dimension)original.entry[WIDTH])(nullptr);saved_height=((Dimension)original.entry[HEIGHT])(nullptr);
    if(saved_width<=0||saved_height<=0)return setup_rejected("Unity reported an invalid screen size (%d x %d)",saved_width,saved_height);
    resolution_ready=false;
    int32_t duration=load<int32_t>(music,f.length.offset);
    AmvGameStatus current{};AmvAudioSelection selected{};
    if(!audio_selection(&current,&selected))return setup_rejected("The selected MV cue or source audio is no longer loaded");
    if(current.song_fingerprint!=config.song_fingerprint)return setup_rejected("The MV song changed while decoding its audio; prepare this song again");
    if (duration<=0 || config.video_frames!=((uint64_t)duration*config.fps+999)/1000 ||
        config.audio_frames!=(config.video_frames*config.sample_rate+config.fps-1)/config.fps)
        return setup_rejected("MV duration/frame counts disagree: duration=%d ms, fps=%u, video=%llu, audio=%llu",duration,config.fps,
            (unsigned long long)config.video_frames,(unsigned long long)config.audio_frames);
    void *type=e.type_get_object(e.class_get_type(f.scene_pre_final.owner)); void *args[]={type};
    void *scenes=type?reference(m.find_objects,nullptr,args):nullptr; uint32_t count=length(scenes,16);
    uint32_t scenes_root=root(scenes);if(scenes&&!scenes_root)return setup_rejected("Could not retain the MV scene search results");
    mv_scene=nullptr;
    bool duplicate_scene=false;
    for (uint32_t i=0;i<count&&count!=UINT32_MAX;i++) {
        void *item=element(scenes,i);
        if (alive(item)&&!load<uint8_t>(item,f.scene_pre_final.offset)&&!load<uint8_t>(item,f.scene_post_final.offset)) {
            if (mv_scene){duplicate_scene=true;break;} mv_scene=item;
        }
    }
    scene_root=root(mv_scene);release(&scenes_root);
    if (duplicate_scene)return setup_rejected("More than one live MV scene is loaded; exit and reopen the MV");
    if (!mv_scene||!scene_root)return setup_rejected("No active LiveMvScene could be retained (scene count=%u)",count);
    if (!value(m.time_get,timeline,&saved_time))return setup_rejected("Unity could not read the MV timeline position");
    if (!value(m.state_get,timeline,&saved_state))return setup_rejected("Unity could not read the MV timeline play state");
    // The managed update-mode getter is stripped. The native setter's actual
    // Android chain and +0x48 field require the profile proof checked at bind.
    void *native_timeline=load<void *>(timeline,0x10);
    if(!native_timeline)return setup_rejected("The MV timeline has no native PlayableDirector");
    saved_mode=load<int32_t>(native_timeline,0x48);
    if(saved_mode<0||saved_mode>3)return setup_rejected("PlayableDirector update mode is outside the verified ABI range (%d)",saved_mode);
    sound=load<void *>(music,f.sound.offset);
    if (!sound||!value(m.sound_paused,sound,&saved_sound_pause))return setup_rejected("The original MV SoundPlayer could not report its pause state");
    timeline_root=root(timeline);music_root=root(music);members_root=root(members);camera_manager_root=root(camera_manager);sound_root=root(sound);
    if(!timeline_root||!music_root||!members_root||!camera_manager_root||!sound_root)return setup_rejected("Could not retain one or more MV timeline/music/member/camera objects");
    saved_music_time=load<int32_t>(music,f.music_time.offset);
    const Field *flags[]={&f.playing,&f.pausing,&f.paused,&f.finished};
    for(unsigned i=0;i<4;i++) saved_music_flags[i]=load<uint8_t>(music,flags[i]->offset);
    if (!snapshot_springs()) return setup_failure[0]?false:setup_rejected("Could not snapshot original MV spring jobs or bone buffers");
    if (!snapshot_render_state())return false;
    if (!snapshot_pause_state())return false;
    session_director_root=root(director); session_overlay_root=root(session_overlay);overlay_camera_root=root(overlay_camera);
    if (!session_director_root||!session_overlay_root||!scene_root||!overlay_camera_root)return setup_rejected("Could not retain the final MV render session");
    memcpy(clock_snapshot,(uint8_t *)clock_manager+0x30,sizeof(clock_snapshot));
    clock_epoch=load<double>(clock_manager,0x60); unscaled_epoch=load<double>(clock_manager,0x70); wall_start=now();
    if (!isfinite(clock_epoch)||!isfinite(unscaled_epoch))return setup_rejected("Unity's MV clock contains a non-finite time value");
    active=true; abandoned=false; have_tick=false; accepted_frames=audio_index=0;
    advancing=awaiting_capture=finishing=pending_pixels=frame_ready=false;
    if(!resume_pause_state())return false;
    int32_t manual=3; void *mode[]={&manual};
    if (!invoke_void(m.mode_set,timeline,mode))return setup_rejected("Unity rejected manual MV timeline update mode");
    if (!restart_timeline_graph())return setup_rejected("Could not rebuild the MV timeline and reset its original lip/light/effect clip progression");
    if (!reset_springs())return setup_rejected("The original MV spring reset/initial timeline evaluation failed");
    // Build/reroute targets only after the original baseline reset and fresh
    // track initialization; a later full reset would clear the routed state.
    if(!create_render_targets())return false;
    uint8_t yes=1,no=0; void *pause_sound[]={&yes};
    if (!invoke_void(m.sound_pause,sound,pause_sound))return setup_rejected("The original SoundPlayer could not pause live audio for offline export");
    put<uint8_t>(music,f.playing.offset,yes); put<uint8_t>(music,f.pausing.offset,no);
    put<uint8_t>(music,f.paused.offset,no); put<uint8_t>(music,f.finished.offset,no);
    int32_t width=config.width,height=config.height;
    texture=e.object_new(m.texture_constructor.owner); texture_root=root(texture);
    int32_t rgba=4; void *texargs[]={&width,&height,&rgba,&no};
    if (!texture_root||!invoke_void(m.texture_constructor,texture,texargs))return setup_rejected("Unity could not allocate the %u x %u RGBA readback texture",config.width,config.height);
    pixels=(uint8_t *)malloc((size_t)config.width*config.height*3/2);
    if (!pixels)return setup_rejected("Not enough memory for the %u x %u I420 frame buffer",config.width,config.height);
    // Keep the original fixedDeltaTime/cache (+48/+50/+58). Unity's built-in
    // FixedUpdate/PhysX retains its configured rate; custom spring invocation
    // follows the original variable-frame path at 60 or 120 Hz below.
    simulation_hz=simulation_rate(config.fps);
    put<int32_t>(clock_manager,0xd8,(int32_t)simulation_hz); put<float>(clock_manager,0xfc,1.f); freeze();
    pthread_mutex_lock(&guard);cached.failure[0]=0;pthread_mutex_unlock(&guard);
    phase("rendering independent MV targets"); publish(); return true;
}
void capture_frame(void *target) {
    uint8_t effect=0,paused=0;int32_t width=0,height=0;
    Result custom=invoke(m.camera_target,overlay_camera);
    if(!scene_valid()||!spring_owners_valid()||!complete_jobs()||!resolution_ready){fail("Final MV scene/spring ownership changed before readback");return;}
    if(!value(m.behaviour_enabled,session_overlay,&effect)||(effect!=0)!=capture_after_overlay){fail("The final MV compositor was enabled/disabled during export");return;}
    if(!value(m.overlay_paused,session_overlay,&paused)||paused||load<uint8_t>(session_overlay,f.overlay_blur.offset)){
        fail("MV was paused or blurred during export; resume it before starting another export");return;}
    if(!custom.ok||custom.value!=rt||target!=rt||!render_targets_valid()){fail("The independent MV target or intermediate allocation changed during export");return;}
    if(!value(m.camera_width,overlay_camera,&width)||!value(m.camera_height,overlay_camera,&height)||
        width<=0||height<=0||width>(int32_t)config.width||height>(int32_t)config.height){fail("Final MV camera viewport does not fit the requested frame");return;}
    if(target&&(!value(m.texture_width,target,&width)||!value(m.texture_height,target,&height)||
        width!=(int32_t)config.width||height!=(int32_t)config.height)){
        fail("Final MV compositor output texture does not match the requested frame size");return;}
    Result old=invoke(m.rt_active_get,nullptr);void *previous=old.value;
    void *select[]={target};bool selected=old.ok&&invoke_void(m.rt_active_set,nullptr,select);
    Rect rect{0,0,(float)config.width,(float)config.height};int32_t zero=0;uint8_t no=0;
    void *readargs[]={&rect,&zero,&zero,&no};bool read=selected&&invoke_void(m.read_pixels,texture,readargs);
    void *restore[]={previous};bool restored=!selected||invoke_void(m.rt_active_set,nullptr,restore);
    int64_t bytes=0;uintptr_t pointer=0;void *mip[]={&zero};
    if(!read||!restored||!value(m.image_size,texture,&bytes)||!value(m.image_pointer,texture,&pointer,mip)||
        !pointer||bytes!=(int64_t)config.width*config.height*4){fail("Unity returned an unexpected MV readback layout");return;}
    if(!amv_rgba_bottom_up_to_i420((const uint8_t *)pointer,(size_t)bytes,config.width,config.height,
            pixels,(size_t)config.width*config.height*3/2)){fail("MV readback color conversion rejected its bounds");return;}
    pending_pixels=true;awaiting_capture=false;frame_ready=false;
}

bool submit() {
    if (!pending_pixels) return true;
    if(pending_frame!=accepted_frames){fail("MV frame index sequence changed");return false;}
    JNIEnv *env=environment(); if (!env) { fail("Unity thread has no Java environment"); return false; }
    uint64_t target=((pending_frame+1)*config.sample_rate+config.fps-1)/config.fps;
    if(target>config.audio_frames)target=config.audio_frames;
    jthrowable error=nullptr;
    while(audio_index<target) {
        uint32_t count=(uint32_t)(target-audio_index); if(count>4096)count=4096;
        if (sink.pcm(sink.context,audio_index,count,pcm)!=(int)count) { fail("Selected-cue PCM provider failed"); return false; }
        int accepted=amv_encoder_offer_pcm16(env,encoder,audio_index,(uint8_t *)pcm,(size_t)count*config.channels*2,&error);
        if(error)env->DeleteLocalRef(error);
        if(accepted<0){fail("AAC encoder rejected PCM");return false;} if(!accepted)return false; audio_index+=count;
    }
    int accepted=amv_encoder_offer_i420(env,encoder,pending_frame,pixels,(size_t)config.width*config.height*3/2,&error);
    if(error)env->DeleteLocalRef(error);
    if(accepted<0){fail("Video encoder rejected a complete MV frame");return false;} if(!accepted)return false;
    pending_pixels=false; accepted_frames++; publish();
    if(sink.progress)sink.progress(sink.context,accepted_frames,config.video_frames);
    if(accepted_frames==config.video_frames) {
        // Video ceil(duration*FPS) always covers the exact declared audio span.
        if(audio_index!=config.audio_frames){fail("Final PCM count differs from the selected cue duration");return false;}
        if(amv_encoder_finish(env,encoder,&error)<0){if(error)env->DeleteLocalRef(error);fail("Encoder refused finalization");return false;}
        finishing=true;phase("finalizing");
    }
    return true;
}
} // namespace

extern "C" int amv_game_request_begin(JNIEnv *env,jobject object,const AmvGameConfig *cfg,const AmvGameCallbacks *callbacks,jthrowable *error) {
    if(error)*error=nullptr;
    if(!env||!object||!cfg||!callbacks||!callbacks->pcm||!callbacks->failed||!callbacks->finished ||
        (cfg->fps!=30&&cfg->fps!=60&&cfg->fps!=120)||cfg->width<16||cfg->height<16||
        (uint64_t)cfg->width*cfg->height>(uint64_t)INT32_MAX/4 ||
        (cfg->width&1)||(cfg->height&1)||cfg->channels<1||cfg->channels>2||cfg->sample_rate<8000||cfg->sample_rate>96000 ||
        !cfg->video_frames||!cfg->audio_frames||cfg->video_frames>INT64_MAX||cfg->audio_frames>INT64_MAX)return -1;
    pthread_mutex_lock(&guard);
    if(request_busy||request.pending||cached.active||!cached.ready){pthread_mutex_unlock(&guard);return 0;}
    AmvEncoder *handle=amv_encoder_bind(env,object,error);
    JavaVM *machine=nullptr;
    if(!handle||env->GetJavaVM(&machine)!=JNI_OK){if(handle)amv_encoder_unbind(env,handle);pthread_mutex_unlock(&guard);return -1;}
    if(amv_encoder_matches_config(env,handle,cfg->width,cfg->height,cfg->fps,(int64_t)cfg->video_frames,
            cfg->sample_rate,cfg->channels,(int64_t)cfg->audio_frames,error)!=1){amv_encoder_unbind(env,handle);pthread_mutex_unlock(&guard);return -1;}
    request={true,false,machine,handle,*cfg,*callbacks};request_busy=true;pthread_mutex_unlock(&guard);return 1;
}
extern "C" void amv_game_request_cancel(){
    Query cancelled_query{};
    pthread_mutex_lock(&guard);request.cancel=true;
    if(query.pending){cancelled_query=query;query={};}
    pthread_mutex_unlock(&guard);
    // Releasing a cancelled query needs no Unity/metadata access. This error
    // callback may run on the caller thread even while Unity is backgrounded.
    if(cancelled_query.pending)cancelled_query.callback(cancelled_query.context,nullptr,nullptr,"Export cancelled");
}
extern "C" void amv_game_get_status(AmvGameStatus *out){if(out){pthread_mutex_lock(&guard);*out=cached;pthread_mutex_unlock(&guard);}}
extern "C" int amv_game_request_song_query(void *context,AmvSongQueried callback){
    if(!callback)return -1;pthread_mutex_lock(&guard);
    if(!installed||query.pending||request_busy){pthread_mutex_unlock(&guard);return 0;}
    query={true,context,callback};pthread_mutex_unlock(&guard);return 1;
}

extern "C" void amv_game_time_update(void *manager) {
    using Fn=void(*)(void*);Fn fallback=(Fn)original.entry[TIME];if(!fallback)return;
    if(!own_thread()){fallback(manager);return;}
    if(active&&clock_manager!=manager){clock_manager=nullptr;abandoned=true;fail("Unity replaced its native clock during export");fallback(manager);return;}
    clock_manager=manager;
    Query song{};pthread_mutex_lock(&guard);if(query.pending){song=query;query={};}pthread_mutex_unlock(&guard);
    if(song.pending){AmvGameStatus status{};AmvAudioSelection selection{};
        bool ok=runtime_ready&&!active&&!quarantined&&audio_selection(&status,&selection);
        song.callback(song.context,ok?&status:nullptr,ok?&selection:nullptr,ok?nullptr:"Load a 3D MV before exporting; paused MVs are supported");}
    Request start{};bool cancel=false;
    pthread_mutex_lock(&guard);cancel=request.cancel;request.cancel=false;
    if(request.pending){start=request;request.pending=false;request.encoder=nullptr;}pthread_mutex_unlock(&guard);
    if(start.pending){if(cancel){encoder=start.encoder;vm=start.vm;sink=start.sink;fail("Export cancelled before setup");}
        else if(!begin(start))fail(setup_failure[0]?setup_failure:"MV export setup failed without a diagnostic");}
    if(cancel&&active)fail("Export cancelled");
    if(!active){fallback(manager);dispatch_terminal();return;}
    if(!scene_valid()){abandoned=true;fail("MV scene changed during export");fallback(manager);return;}
    if(!spring_owners_valid()){fail("MV spring resource ownership changed during export");return;}
    using Dimension=int32_t(*)(const void*);
    int32_t actual_width=((Dimension)original.entry[WIDTH])(nullptr),actual_height=((Dimension)original.entry[HEIGHT])(nullptr);
    put<int32_t>(camera_manager,f.camera_current_width.offset,actual_width);
    put<int32_t>(camera_manager,f.camera_current_height.offset,actual_height);
    if(!render_targets_valid()){fail("Owned offline MV render targets changed or lost their GPU allocation");return;}
    // Camera callbacks can run before AfterEverything command buffers and
    // post-processing have finished. Read only at the next frame boundary;
    // never disable a camera or read its target inside its render callback.
    if(awaiting_capture&&frame_ready){capture_frame(rt);if(!active)return;}
    if(pending_pixels&&!submit()){if(active){
        if(!suspend_rendering(true)){fail("Could not suspend owned MV cameras during encoder backpressure");return;}
        freeze();}return;}
    if(finishing) {
        if(!suspend_rendering(true)){fail("Could not suspend owned MV cameras during encoder finalization");return;}
        freeze();JNIEnv *env=environment();jthrowable error=nullptr;
        jstring path=env?amv_encoder_completed_path(env,encoder,&error):nullptr;
        if(error){env->DeleteLocalRef(error);fail("MP4 encoder finalization failed");return;}
        if(path){const char *text=env->GetStringUTFChars(path,nullptr);char copy[1024]={};
            bool valid_path=text&&env->GetStringUTFLength(path)>0&&env->GetStringUTFLength(path)<(jsize)sizeof(copy);
            if(valid_path)snprintf(copy,sizeof(copy),"%s",text);
            if(text){env->ReleaseStringUTFChars(path,text);}
            else if(env->ExceptionCheck()){env->ExceptionClear();}
            env->DeleteLocalRef(path);
            AmvGameCallbacks done=sink;bool restored=restore_scene();amv_encoder_unbind(env,encoder);encoder=nullptr;sink={};
            if(!valid_path||!restored)end_notification(done,false,nullptr,quarantined?
                "MP4 finished, but spring jobs did not complete safely; restart the game before another export":
                "MP4 finished but MV state restoration failed");
            else end_notification(done,true,copy,nullptr);}
        return;
    }
    if(awaiting_capture){freeze();return;}
    if(!suspend_rendering(false)){fail("Could not resume the owned MV cameras for the next output frame");return;}
    uint64_t next=have_tick?tick+1:0;
    if(next>INT32_MAX*(uint64_t)simulation_hz/1000){fail("MV time exceeds the native millisecond range");return;}
    fallback(manager);tick=next;double dt=have_tick?1.0/simulation_hz:0;have_tick=true;
    double t=clock_epoch+(double)tick/simulation_hz,u=unscaled_epoch+(double)tick/simulation_hz;
    put<double>(manager,0x60,t);put<double>(manager,0x68,t-dt);put<double>(manager,0x70,u);
    put<double>(manager,0x90,t);put<double>(manager,0x98,t-dt);put<double>(manager,0xa0,u);
    for(size_t off:{size_t(0x78),size_t(0x7c),size_t(0xa8),size_t(0xac)})put<float>(manager,off,(float)dt);
    put<int32_t>(music,f.music_time.offset,(int32_t)(tick*1000/simulation_hz));
    advancing=true;
    if(!set_time((double)tick/simulation_hz)){fail("MV timeline evaluation did not complete before rendering");return;}
    uint64_t divisor=simulation_hz/config.fps;
    if(tick%divisor==0){pending_frame=tick/divisor;awaiting_capture=true;}
    publish();
}
extern "C" void amv_game_live_update(void *self,const void *mi) {
    using Fn=void(*)(void*,const void*);Fn fallback=(Fn)original.entry[LIVE];if(!fallback)return;
    if(!own_thread()){fallback(self,mi);return;}
    if(reentry&(1u<<LIVE)){fallback(self,mi);return;}
    if(!runtime_ready){
        if(!runtime_rejected&&!init_runtime()){
            runtime_rejected=true;record_failure("This game client does not match the verified MV export interfaces");phase("unsupported MV interfaces");}
        if(!runtime_ready){fallback(self,mi);return;}
    }
    if(!active){observe(self);fallback(self,mi);return;}
    if(self!=director){abandoned=true;fail("Different live director appeared during export");observe(self);fallback(self,mi);return;}
    if(advancing&&!original_call(LIVE,self))fail("MV beat/shader update failed");
}
extern "C" void amv_game_music_update(void *self,const void *mi) {
    using Fn=void(*)(void*,const void*);Fn fallback=(Fn)original.entry[MUSIC];if(!fallback)return;
    if(!own_thread()){fallback(self,mi);return;}
    if(reentry&(1u<<MUSIC)){fallback(self,mi);return;}
    if(!active||self!=music)fallback(self,mi);
}
extern "C" void amv_game_member_update(void *self,const void *mi) {
    using Fn=void(*)(void*,const void*);Fn fallback=(Fn)original.entry[MEMBER];if(!fallback)return;
    if(!own_thread()){fallback(self,mi);return;}
    if(reentry&(1u<<MEMBER)){fallback(self,mi);return;}
    if(!active||self!=members){fallback(self,mi);return;}
    if(!advancing||tick==0)return;
    if(!spring_owners_valid()||!complete_jobs()||!original_call(MEMBER,self)||!complete_jobs())fail("Original MV spring simulation/job completion failed");
}
extern "C" void amv_game_member_late_update(void *self,const void *mi) {
    using Fn=void(*)(void*,const void*);Fn fallback=(Fn)original.entry[LATE];if(!fallback)return;
    if(!own_thread()){fallback(self,mi);return;}
    if(reentry&(1u<<LATE)){fallback(self,mi);return;}
    if(!active||self!=members){fallback(self,mi);return;}
    if(advancing&&tick>0&&!original_call(LATE,self))fail("MV spring safety correction failed");
}
extern "C" int32_t amv_game_screen_width(const void *mi){using Fn=int32_t(*)(const void*);
    if(scoped_render_dimensions.load()&&thread_known&&pthread_equal(unity_thread,pthread_self()))return (int32_t)config.width;
    return original.entry[WIDTH]?((Fn)original.entry[WIDTH])(mi):0;}
extern "C" int32_t amv_game_screen_height(const void *mi){using Fn=int32_t(*)(const void*);
    if(scoped_render_dimensions.load()&&thread_known&&pthread_equal(unity_thread,pthread_self()))return (int32_t)config.height;
    return original.entry[HEIGHT]?((Fn)original.entry[HEIGHT])(mi):0;}
extern "C" void amv_game_overlay_render(void *self,void *source,void *destination,const void *mi) {
    using Fn=void(*)(void*,void*,void*,const void*);Fn fallback=(Fn)original.entry[OVERLAY];if(!fallback)return;
    if(!own_thread()){fallback(self,source,destination,mi);return;}
    if(reentry&(1u<<OVERLAY)){fallback(self,source,destination,mi);return;}
    if(!active){fallback(self,source,destination,mi);return;}
    void *args[]={source,destination};
    if(!original_call(OVERLAY,self,args)){fail("MV overlay effect failed");return;}
    if(self==session_overlay&&capture_after_overlay&&awaiting_capture&&!pending_pixels)
        frame_ready=true;
}
extern "C" void amv_game_camera_post_render(void *camera,const void *mi) {
    using Fn=void(*)(void*,const void*);Fn fallback=(Fn)original.entry[POST];if(!fallback)return;
    if(!own_thread()){fallback(camera,mi);amv_game_request_cancel();return;}
    if(reentry&(1u<<POST)){fallback(camera,mi);return;}
    if(!active){
        fallback(camera,mi);
        if(runtime_ready&&director&&alive(director)){
            void *manager=reference(m.camera_manager,director),*final=manager?reference(m.final_overlay,manager):nullptr;
            if(alive(final)&&reference(m.overlay_camera,final)==camera){uint8_t enabled=0;Result target=invoke(m.camera_target,camera);
                if(value(m.behaviour_enabled,final,&enabled)&&target.ok&&!target.value){
                    uint32_t retained=root(final);release(&observed_overlay_root);overlay=retained?final:nullptr;observed_overlay_root=retained;}}}
        return;
    }
    void *args[]={camera};
    if(!original_call(POST,nullptr,args)){fail("Original camera post-render delegate failed");return;}
    if(camera!=overlay_camera||capture_after_overlay||!awaiting_capture||pending_pixels)return;
    frame_ready=true;
}

namespace {
struct Image {uintptr_t bias;Sidecar *side;const ElfW(Phdr) *ph;ElfW(Half) count;};
struct Found {Image il,unity;bool corrupt;};
int find_image(dl_phdr_info *info,size_t,void *opaque) {
    Found *found=(Found *)opaque;const char *name=strrchr(info->dlpi_name,'/');name=name?name+1:info->dlpi_name;
    bool il=!strcmp(name,"libil2cpp.so"),unity=!strcmp(name,"libunity.so");if(!il&&!unity)return 0;
    Sidecar *side=nullptr;
    for(ElfW(Half)i=0;i<info->dlpi_phnum;i++){
        const ElfW(Phdr)&p=info->dlpi_phdr[i];
        if(p.p_type==PT_LOAD&&p.p_flags==(PF_R|PF_W)&&p.p_filesz==320&&p.p_memsz==320){
            Sidecar *candidate=(Sidecar *)(info->dlpi_addr+p.p_vaddr);
            if(!memcmp(candidate->magic,"SMVAND02",8)){if(side){found->corrupt=true;return 1;}side=candidate;}
        }
    }
    if(il)found->il={info->dlpi_addr,side,info->dlpi_phdr,info->dlpi_phnum};
    else found->unity={info->dlpi_addr,side,info->dlpi_phdr,info->dlpi_phnum};return 0;
}
bool mapped(const Image &image,uintptr_t rva,size_t bytes,uint32_t flags) {
    for(ElfW(Half)i=0;i<image.count;i++) {const ElfW(Phdr)&p=image.ph[i];
        if(p.p_type==PT_LOAD&&p.p_flags==flags&&rva>=p.p_vaddr&&
            rva-p.p_vaddr<=p.p_memsz&&bytes<=p.p_memsz-(rva-p.p_vaddr))return true;}
    return false;
}
bool image_valid(const Image &image,const AmvPatchImageProfile &profile) {
    Sidecar *side=image.side;
    if(!side||side!=(Sidecar *)(image.bias+profile.sidecar_rva)||
        !mapped(image,profile.sidecar_rva,sizeof(Sidecar),PF_R|PF_W)||
        memcmp(side->source,profile.source_sha256,32)||memcmp(side->profile,profile.profile_sha256,32))return false;
    for(unsigned i=0;i<SLOTS;i++){
        if(side->callback[i]||side->original[i]!=profile.original_rva[i])return false;
        if(!profile.entry_rva[i])continue;
        if(!mapped(image,profile.entry_rva[i],4,PF_R|PF_X)||!mapped(image,profile.shim_rva[i],64,PF_R|PF_X)||
            load<uint32_t>((void *)image.bias,profile.entry_rva[i])!=profile.entry_patch_word[i]||
            memcmp((void *)(image.bias+profile.shim_rva[i]),profile.shim_bytes[i],64))return false;
    }
    return true;
}
bool exports(void *library) {
#define E(member,name) e.member=(decltype(e.member))dlsym(library,"il2cpp_" name);if(!e.member)return false
    E(domain_get,"domain_get");E(domain_get_assemblies,"domain_get_assemblies");E(assembly_get_image,"assembly_get_image");
    E(class_from_name,"class_from_name");E(class_get_methods,"class_get_methods");E(method_get_name,"method_get_name");
    E(method_get_param_count,"method_get_param_count");E(method_get_param,"method_get_param");E(method_get_return_type,"method_get_return_type");
    E(method_get_flags,"method_get_flags");E(method_get_class,"method_get_class");E(runtime_invoke,"runtime_invoke");
    E(type_get_name,"type_get_name");E(free_memory,"free");E(class_from_type,"class_from_type");E(class_get_type,"class_get_type");
    E(type_get_object,"type_get_object");E(object_get_class,"object_get_class");E(class_get_parent,"class_get_parent");E(class_is_assignable_from,"class_is_assignable_from");
    E(object_unbox,"object_unbox");E(object_new,"object_new");E(class_instance_size,"class_instance_size");E(class_value_size,"class_value_size");
    E(class_get_field_from_name,"class_get_field_from_name");E(field_get_offset,"field_get_offset");E(field_get_type,"field_get_type");
    E(field_get_flags,"field_get_flags");E(gchandle_new,"gchandle_new");E(gchandle_get_target,"gchandle_get_target");
    E(gchandle_free,"gchandle_free");E(array_length,"array_length");E(thread_current,"thread_current");
    E(string_length,"string_length");E(string_chars,"string_chars");
    E(type_is_byref,"type_is_byref");
    E(format_exception,"format_exception");
#undef E
    return true;
}
}
extern "C" int amv_game_try_bind_loaded() {
    pthread_mutex_lock(&guard);
    if(installed){pthread_mutex_unlock(&guard);return 1;}
    Found found{};dl_iterate_phdr(find_image,&found);
    if(found.corrupt){pthread_mutex_unlock(&guard);return -1;}
    if(!found.il.bias||!found.unity.bias){pthread_mutex_unlock(&guard);return 0;}
    Sidecar *il=found.il.side,*unity=found.unity.side;
    if(!il||!unity||il->version!=2||unity->version!=2||il->size!=320||unity->size!=320||il->kind!=1||unity->kind!=2||
        il->region<1||il->region>2||il->region!=unity->region||il->ready||unity->ready){pthread_mutex_unlock(&guard);return -1;}
    const AmvPatchImageProfile &il_profile=amv_patch_images[(il->region-1)*2];
    const AmvPatchImageProfile &unity_profile=amv_patch_images[(il->region-1)*2+1];
    if(!image_valid(found.il,il_profile)||!image_valid(found.unity,unity_profile)){pthread_mutex_unlock(&guard);return -1;}
    void *library=dlopen("libil2cpp.so",RTLD_NOW|RTLD_NOLOAD);
    if(!library){pthread_mutex_unlock(&guard);return 0;}
    bool valid=exports(library);dlclose(library);
    if(!valid){pthread_mutex_unlock(&guard);return -1;}
    for(unsigned i=0;i<SLOTS;i++){
        Sidecar *side=i==TIME?unity:il;uintptr_t bias=i==TIME?found.unity.bias:found.il.bias;
        if(!side->original[i]||side->callback[i]){pthread_mutex_unlock(&guard);return -1;}
        original.entry[i]=bias+side->original[i];
    }
    uintptr_t callbacks[]={ (uintptr_t)amv_game_time_update,(uintptr_t)amv_game_live_update,(uintptr_t)amv_game_music_update,
        (uintptr_t)amv_game_member_update,(uintptr_t)amv_game_overlay_render,(uintptr_t)amv_game_screen_width,
        (uintptr_t)amv_game_screen_height,(uintptr_t)amv_game_member_late_update,(uintptr_t)amv_game_camera_post_render};
    for(unsigned i=0;i<SLOTS;i++)if(i==TIME)unity->callback[i]=callbacks[i];else il->callback[i]=callbacks[i];
    il_bias=found.il.bias;unity_bias=found.unity.bias;il_sidecar=il;unity_sidecar=unity;region=il->region;installed=true;
    __atomic_store_n(&il->ready,1,__ATOMIC_RELEASE);__atomic_store_n(&unity->ready,1,__ATOMIC_RELEASE);
    cached.installed=1;cached.region=region;snprintf(cached.phase,sizeof(cached.phase),"waiting for loaded MV");
    pthread_mutex_unlock(&guard);return 1;
}
