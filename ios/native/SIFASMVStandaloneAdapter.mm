#import "SIFASMVStandaloneAdapter.h"
#if defined(SIFAS_STANDALONE)
#include <atomic>
#include <cmath>
#include <cstring>

/* Reuse the exact selected-wave HCA/ADX decoder and aligned PCM path used by
 * Android. Darwin calls the same POSIX stat timestamps by different names.
 * The build also compiles android/mv_audio_codec/clhca.c once. */
#if defined(__APPLE__)
#define st_mtim st_mtimespec
#define st_ctim st_ctimespec
#endif
#include "../../ci/sifas_mv_export/android/android_mv_audio_provider.cpp"
#if defined(__APPLE__)
#undef st_mtim
#undef st_ctim
#endif

static __weak UIViewController *SIFASMVPresenter;
NSDictionary *SIFASMVStandaloneConfiguration(void) {
    NSString *documents=NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject;
    return @{@"data_root":documents ?: [NSHomeDirectory() stringByAppendingPathComponent:@"Documents"],
             @"language":NSLocale.preferredLanguages.firstObject ?: @"en"};
}
void SIFASMVStandaloneSetPresenter(UIViewController *presenter) {
    UIWindow *window=presenter.viewIfLoaded.window;
    SIFASMVPresenter=window.rootViewController ?: presenter;
}
UIViewController *SIFASMVStandalonePresenter(void) {
    UIViewController *presenter=SIFASMVPresenter;
    if (presenter.viewIfLoaded.window && !presenter.view.window.hidden) return presenter;
    UIWindow *visible=nil;
    for (UIWindow *window in UIApplication.sharedApplication.windows) {
        UIViewController *root=window.rootViewController;
        if (window.hidden || window.alpha<=0 || window.windowLevel!=UIWindowLevelNormal ||
            !root || [root isKindOfClass:UIAlertController.class]) continue;
        if (window.windowScene && (window.windowScene.activationState==UISceneActivationStateBackground ||
            window.windowScene.activationState==UISceneActivationStateUnattached)) continue;
        if (window.isKeyWindow) { SIFASMVPresenter=root; return root; }
        if (!visible) visible=window;
    }
    SIFASMVPresenter=visible.rootViewController;
    return SIFASMVPresenter;
}
BOOL SIFASMVStandaloneShowGame(void) {
    return UIApplication.sharedApplication.applicationState==UIApplicationStateActive && SIFASMVStandalonePresenter()!=nil;
}

namespace {
dispatch_queue_t audioQueue() {
    static dispatch_queue_t queue; static dispatch_once_t once;
    dispatch_once(&once, ^{ queue=dispatch_queue_create("app.sifas.standalone.mv-audio",DISPATCH_QUEUE_SERIAL); });
    return queue;
}
std::atomic<uint64_t> audioGeneration{1};
AmvAudioProvider *audioProvider=nullptr;
NSString *audioIdentifier=nil;
struct Cancellation { uint64_t generation; };
int cancelled(void *context) { return audioGeneration.load()!=static_cast<Cancellation *>(context)->generation; }
NSDictionary *failure(NSString *message) { return @{@"ok":@NO,@"error":@{@"message":message ?: @"MV audio failed."}}; }
void replyOnMain(void (^completion)(NSDictionary *),NSDictionary *reply) {
    dispatch_async(dispatch_get_main_queue(), ^{ completion(reply); });
}
bool number(NSDictionary *values,NSString *key,int64_t minimum,int64_t maximum,int64_t &result) {
    id value=values[key]; if (![value isKindOfClass:NSNumber.class]) return false;
    double real=[value doubleValue]; result=[value longLongValue];
    return std::isfinite(real) && real==double(result) && result>=minimum && result<=maximum;
}
bool path(id value,char *output,bool required) {
    if (![value isKindOfClass:NSString.class]) return !required;
    NSString *text=value; if (!text.length) return !required;
    const char *bytes=text.fileSystemRepresentation;
    if (!text.isAbsolutePath || !bytes || std::strlen(bytes)>=AMV_AUDIO_PATH_CAP) return false;
    std::strcpy(output,bytes); return true;
}
bool selection(NSDictionary *values,AmvAudioSelection &out) {
    if (![values isKindOfClass:NSDictionary.class]) return false;
    out={}; out.abi_version=AMV_AUDIO_ABI; int64_t integer=0;
    if (!number(values,@"streaming",0,1,integer)) return false; out.streaming=uint32_t(integer);
    if (!path(values[@"acb_path"],out.acb_path,true) || !path(values[@"awb_path"],out.awb_path,out.streaming!=0)) return false;
    if (!number(values,@"wave_id",0,UINT32_MAX,integer)) return false; out.wave_id=uint32_t(integer);
    if (!number(values,@"sample_rate",8000,96000,integer)) return false; out.sample_rate=uint32_t(integer);
    if (!number(values,@"channels",1,2,integer)) return false; out.channels=uint32_t(integer);
    if (!number(values,@"source_samples",1,INT64_MAX,integer)) return false; out.source_samples=uint64_t(integer);
    if (!number(values,@"music_length_ms",1,1200000,integer)) return false; out.music_length_ms=int32_t(integer);
    if (!number(values,@"start_time_ms",-1200000,1200000,integer)) return false; out.start_time_ms=int32_t(integer);
    if (!number(values,@"source_offset_ms",0,1200000,integer)) return false; out.source_offset_ms=int32_t(integer);
    id gain=values[@"gain"];
    if (![gain isKindOfClass:NSNumber.class] || !std::isfinite([gain doubleValue]) || [gain doubleValue]<0 || [gain doubleValue]>4) return false;
    out.gain=[gain floatValue]; return true;
}
}

void SIFASMVStandaloneAudioCall(NSString *method,NSDictionary *arguments,void (^completion)(NSDictionary *)) {
    if (!NSThread.isMainThread) {
        dispatch_async(dispatch_get_main_queue(), ^{ SIFASMVStandaloneAudioCall(method,arguments,completion); }); return;
    }
    if ([method isEqual:@"mv_export_audio_prepare"]) {
        if (!SIFASMVBindingsAudioSelection) { completion(failure(@"Standalone audio is unavailable: the loaded CRI cue adapter is missing.")); return; }
        NSDictionary *selected=[SIFASMVBindingsAudioSelection() copy];
        const uint64_t generation=audioGeneration.fetch_add(1)+1;
        dispatch_async(audioQueue(), ^{
            AmvAudioSelection cue={}; NSDictionary *video=arguments[@"video"]; int64_t frames=0,fps=0,denominator=0;
            if (!selection(selected,cue) || !number(video,@"frame_count",1,INT64_MAX,frames) ||
                !number(video,@"fps_numerator",1,INT32_MAX,fps) || !number(video,@"fps_denominator",1,INT32_MAX,denominator)) {
                replyOnMain(completion,failure(@"The loaded CRI cue has no complete selected waveform/path/timing metadata.")); return;
            }
            if (audioProvider) { replyOnMain(completion,failure(@"The previous song PCM is still owned by an export.")); return; }
            NSString *cache=[NSTemporaryDirectory() stringByAppendingPathComponent:@"SIFASMVAudio"];
            NSError *directoryError=nil;
            if (![NSFileManager.defaultManager createDirectoryAtPath:cache withIntermediateDirectories:YES attributes:nil error:&directoryError]) {
                replyOnMain(completion,failure(directoryError.localizedDescription)); return;
            }
            AmvAudioError error={}; Cancellation cancellation={generation}; AmvAudioProvider *prepared=nullptr;
            if (!amv_audio_prepare(&cue,cache.fileSystemRepresentation,uint64_t(frames),uint32_t(fps),uint32_t(denominator),cancelled,&cancellation,&prepared,&error)) {
                replyOnMain(completion,failure([NSString stringWithUTF8String:error.message])); return;
            }
            if (cancelled(&cancellation)) { amv_audio_close(prepared); replyOnMain(completion,failure(@"MV audio preparation was cancelled.")); return; }
            AmvAudioInfo info={};
            if (!amv_audio_get_info(prepared,&info)) { amv_audio_close(prepared); replyOnMain(completion,failure(@"Prepared PCM metadata is unavailable.")); return; }
            audioProvider=prepared; audioIdentifier=NSUUID.UUID.UUIDString;
            replyOnMain(completion,@{@"ok":@YES,@"session_id":audioIdentifier,
                @"manifest":@{@"sampleRate":@(info.sample_rate),@"channels":@(info.channels),@"sampleCount":@(info.audio_frames)}});
        });
    } else if ([method isEqual:@"mv_export_audio_read"]) {
        dispatch_async(audioQueue(), ^{
            int64_t first=0,count=0; AmvAudioInfo info={};
            if (!audioProvider || ![arguments[@"session_id"] isEqual:audioIdentifier] || !amv_audio_get_info(audioProvider,&info) ||
                !number(arguments,@"first_sample",0,INT64_MAX,first) || !number(arguments,@"max_frames",1,8192,count) ||
                uint64_t(first)>info.audio_frames || uint64_t(count)>info.audio_frames-uint64_t(first)) {
                replyOnMain(completion,failure(@"The selected song PCM read is stale or outside its duration.")); return;
            }
            NSMutableData *pcm=[NSMutableData dataWithLength:NSUInteger(count)*info.channels*2];
            if (amv_audio_read_at(audioProvider,uint64_t(first),uint32_t(count),static_cast<int16_t *>(pcm.mutableBytes))!=count) {
                replyOnMain(completion,failure(@"The selected song PCM chunk could not be read.")); return;
            }
            replyOnMain(completion,@{@"ok":@YES,@"session_id":audioIdentifier,@"first_sample":@(first),@"frame_count":@(count),@"pcm_data":pcm});
        });
    } else if ([method isEqual:@"mv_export_audio_close"]) {
        audioGeneration.fetch_add(1);
        dispatch_async(audioQueue(), ^{
            if (arguments[@"session_id"] && audioIdentifier && ![arguments[@"session_id"] isEqual:audioIdentifier]) {
                replyOnMain(completion,failure(@"A stale export cannot close another song's PCM.")); return;
            }
            if (audioProvider) amv_audio_close(audioProvider);
            audioProvider=nullptr; audioIdentifier=nil; replyOnMain(completion,@{@"ok":@YES});
        });
    } else completion(failure(@"Unknown standalone MV audio operation."));
}
#endif
