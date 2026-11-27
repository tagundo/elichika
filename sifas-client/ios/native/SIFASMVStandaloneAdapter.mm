#import "SIFASMVStandaloneAdapter.h"
#if defined(SIFAS_STANDALONE)
#import "SIFASMVExportFOV.hpp"
#import <CoreFoundation/CoreFoundation.h>
#import <objc/runtime.h>
#include "SIFASMVExportPatchProfile.h"
#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <pthread.h>

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
BOOL SIFASMVStandaloneRunOnMac(void) {
    NSProcessInfo *process=NSProcessInfo.processInfo;
    SEL selector=sel_registerName("isiOSAppOnMac");
    if (![process respondsToSelector:selector]) return NO;
    using IsIOSAppOnMac=BOOL (*)(id,SEL);
    return reinterpret_cast<IsIOSAppOnMac>([process methodForSelector:selector])(process,selector);
}

namespace {
struct FOVBounds {
    float minimum;
    float maximum;
};
struct FOVConfig {
    FOVBounds bounds;
    uint32_t otherSettings[4];
    uint32_t magic;
    uint32_t version;
};
static_assert(sizeof(FOVConfig) == 32, "Original FOV configuration ABI");

using RefreshFOV = void (*)();
using DefaultsObject = id (*)(NSUserDefaults *, SEL, NSString *);
using DefaultsDouble = double (*)(NSUserDefaults *, SEL, NSString *);
struct FOVRuntime {
    const FOVConfig *config;
    RefreshFOV refresh;
    uintptr_t featureSlide;
};

FOVRuntime fovRuntime{};
NSUserDefaults *fovDefaults;
std::atomic<DefaultsObject> originalDefaultsObject;
std::atomic<DefaultsDouble> originalDefaultsDouble;

// Unchanged SIFASFeatures.dylib from the pinned 18.7 standalone IPA.
constexpr uint8_t fovFeatureUUID[] = {0x4c, 0x4c, 0x44, 0x62, 0x55, 0x55, 0x31, 0x44,
                                     0xa1, 0x10, 0xcb, 0x94, 0xf1, 0xba, 0x04, 0xb0};
constexpr uintptr_t fovConfigAddress = 0x1057338a0;
constexpr uintptr_t preferenceReader = 0x4a5c;
constexpr uintptr_t objectMinCall = 0x4ab4, objectMaxCall = 0x4afc;
constexpr uintptr_t doubleMinCall = 0x4adc, doubleMaxCall = 0x4b20;
NSString *const fovMinKey = @"SIFASFOVMinimum";
NSString *const fovMaxKey = @"SIFASFOVMaximum";

bool validBounds(double minimum, double maximum) {
    return minimum >= 0.5 && minimum <= maximum && maximum <= 2.0;
}

bool readBounds(id value, FOVBounds &bounds) {
    if (![value isKindOfClass:NSDictionary.class]) return false;
    NSDictionary *values = value;
    NSNumber *minimum = values[@"min"], *maximum = values[@"max"];
    if (values.count != 2 || ![minimum isKindOfClass:NSNumber.class] ||
        ![maximum isKindOfClass:NSNumber.class] ||
        CFGetTypeID((__bridge CFTypeRef)minimum) == CFBooleanGetTypeID() ||
        CFGetTypeID((__bridge CFTypeRef)maximum) == CFBooleanGetTypeID()) return false;
    const double min = minimum.doubleValue, max = maximum.doubleValue;
    if (!validBounds(min, max)) return false;
    bounds = {float(min), float(max)};
    return true;
}

bool matchesBounds(FOVBounds first, FOVBounds second) {
    return first.minimum == second.minimum && first.maximum == second.maximum;
}

bool hasFOVImageUUID(const mach_header_64 *header, uint32_t type, const uint8_t *expected) {
    if (!header || header->magic != MH_MAGIC_64 || header->cputype != CPU_TYPE_ARM64 ||
        header->cpusubtype != 0 || header->filetype != type || header->ncmds > 128 ||
        header->sizeofcmds > 8192 - sizeof(*header)) return false;
    const uint8_t *cursor = reinterpret_cast<const uint8_t *>(header + 1);
    const uint8_t *end = cursor + header->sizeofcmds;
    bool matched = false;
    for (uint32_t index = 0; index < header->ncmds; ++index) {
        if (size_t(end - cursor) < sizeof(load_command)) return false;
        const auto *command = reinterpret_cast<const load_command *>(cursor);
        if (command->cmdsize < sizeof(*command) || command->cmdsize % 8 ||
            command->cmdsize > size_t(end - cursor)) return false;
        if (command->cmd == LC_UUID) {
            if (matched || command->cmdsize != sizeof(uuid_command) ||
                std::memcmp(reinterpret_cast<const uuid_command *>(command)->uuid, expected, 16)) return false;
            matched = true;
        }
        cursor += command->cmdsize;
    }
    return cursor == end && matched;
}

// The exact check the last unresolved lookup stopped at (diagnostics only).
const char *fovResolveCheck = "fov.unresolved";
char fovResolveDetail[160];
bool fovUnresolved(const char *check, const char *format, ...) __attribute__((format(printf, 2, 3)));
bool fovUnresolved(const char *check, const char *format, ...) {
    fovResolveCheck = check;
    va_list args;
    va_start(args, format);
    vsnprintf(fovResolveDetail, sizeof(fovResolveDetail), format, args);
    va_end(args);
    return false;
}

bool resolveFOVRuntime() {
    if (fovRuntime.config) return true;
    const auto *main = reinterpret_cast<const mach_header_64 *>(_dyld_get_image_header(0));
    if (!hasFOVImageUUID(main, MH_EXECUTE, kSIFASMVUUID))
        return fovUnresolved("fov.main-image", "%s", "image 0 is not the pinned arm64 game executable (header or LC_UUID differs)");
    const auto *config = getsectbynamefromheader_64(main, "__DATA", "__sifas_cfg");
    if (!config || config->addr != fovConfigAddress || config->size != sizeof(FOVConfig) ||
        config->align != 4 || config->flags != 0)
        return fovUnresolved("fov.config-section", "__DATA,__sifas_cfg is %s", config ? "at a different address or size" : "missing");
    const auto *live = reinterpret_cast<const FOVConfig *>(config->addr + _dyld_get_image_vmaddr_slide(0));
    if (live->magic != 0x53494641 || live->version != 1)
        return fovUnresolved("fov.config-section", "magic 0x%08x version %u", live->magic, live->version);

    Class featureClass = objc_getClass("SIFASFeatures");
    Method poll = class_getInstanceMethod(featureClass, sel_registerName("poll:"));
    if (!poll)
        return fovUnresolved("fov.feature-class", "%s", featureClass ? "SIFASFeatures has no poll: method" : "the SIFASFeatures class is not loaded");
    const uint32_t images = _dyld_image_count();
    for (uint32_t index = 1; index < images; ++index) {
        const auto *dylib = reinterpret_cast<const mach_header_64 *>(_dyld_get_image_header(index));
        if (!hasFOVImageUUID(dylib, MH_DYLIB, fovFeatureUUID)) continue;
        const auto *text = getsectbynamefromheader_64(dylib, "__TEXT", "__text");
        const uintptr_t slide = _dyld_get_image_vmaddr_slide(index);
        const auto code = [slide](uintptr_t address) { return reinterpret_cast<const uint32_t *>(slide + address); };
        constexpr uint32_t readerStart[] = {0xd10283ff, 0x6d0323e9, 0xa9046ffc, 0xa90567fa};
        if (!text || text->addr != 0x4000 || text->size != 0xb360)
            return fovUnresolved("fov.feature-code", "%s", "SIFASFeatures.dylib __TEXT,__text differs");
        if (reinterpret_cast<uintptr_t>(method_getImplementation(poll)) != slide + 0x4024)
            return fovUnresolved("fov.feature-poll", "%s", "-[SIFASFeatures poll:] is not the pinned implementation (replaced or hooked)");
        if (std::memcmp(code(preferenceReader), readerStart, sizeof(readerStart)) ||
            *code(0x4064) != 0x9400027e || *code(objectMinCall) != 0x94002a31 ||
            *code(objectMaxCall) != 0x94002a1f || *code(doubleMinCall) != 0x94002a27 ||
            *code(doubleMaxCall) != 0x94002a16)
            return fovUnresolved("fov.feature-code", "%s", "the SIFASFeatures FOV preference reader differs");
        fovRuntime = {live, reinterpret_cast<RefreshFOV>(slide + preferenceReader), slide};
        return true;
    }
    return fovUnresolved("fov.feature-library", "no loaded image of %u has the pinned SIFASFeatures.dylib UUID", images);
}
}

@interface SIFASMVExportFOVOverride : NSObject {
@public
    FOVBounds original;
    NSNumber *minimum;
    NSNumber *maximum;
    BOOL enabled;
    BOOL restored;
}
@end
@implementation SIFASMVExportFOVOverride
@end

namespace {
SIFASMVExportFOVOverride *activeFOV;

NSNumber *queuedFOVValue(NSUserDefaults *defaults, NSString *key, uintptr_t caller,
                         uintptr_t minimumCall, uintptr_t maximumCall) {
    if (!pthread_main_np() || defaults != fovDefaults || !activeFOV || !activeFOV->enabled) return nil;
    // Only the preserved feature's two limit reads see the entry's override.
    // All other defaults readers and writes continue through Foundation.
    if (caller == fovRuntime.featureSlide + minimumCall + 4 && [key isEqualToString:fovMinKey]) return activeFOV->minimum;
    if (caller == fovRuntime.featureSlide + maximumCall + 4 && [key isEqualToString:fovMaxKey]) return activeFOV->maximum;
    return nil;
}

id exportFOVObjectForKey(NSUserDefaults *defaults, SEL selector, NSString *key) {
    NSNumber *value = queuedFOVValue(defaults, key, reinterpret_cast<uintptr_t>(__builtin_return_address(0)),
                                     objectMinCall, objectMaxCall);
    return value ?: originalDefaultsObject.load()(defaults, selector, key);
}

double exportFOVDoubleForKey(NSUserDefaults *defaults, SEL selector, NSString *key) {
    NSNumber *value = queuedFOVValue(defaults, key, reinterpret_cast<uintptr_t>(__builtin_return_address(0)),
                                     doubleMinCall, doubleMaxCall);
    return value ? value.doubleValue : originalDefaultsDouble.load()(defaults, selector, key);
}

bool installFOVDefaults() {
    if (fovDefaults) return true;
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    Class implementation = object_getClass(defaults);
    Method object = class_getInstanceMethod(implementation, @selector(objectForKey:));
    Method number = class_getInstanceMethod(implementation, @selector(doubleForKey:));
    if (!object || !number) return false;
    originalDefaultsObject.store(reinterpret_cast<DefaultsObject>(method_getImplementation(object)));
    originalDefaultsDouble.store(reinterpret_cast<DefaultsDouble>(method_getImplementation(number)));
    method_setImplementation(object, reinterpret_cast<IMP>(&exportFOVObjectForKey));
    method_setImplementation(number, reinterpret_cast<IMP>(&exportFOVDoubleForKey));
    fovDefaults = defaults;
    return true;
}

bool refreshFOV(FOVBounds expected) {
    @try {
        fovRuntime.refresh();
        return matchesBounds(fovRuntime.config->bounds, expected);
    } @catch (NSException *exception) {
        (void)exception;
        return false;
    }
}
}

BOOL SIFASMVExportValidFOV(id value) {
    FOVBounds bounds{};
    return readBounds(value, bounds);
}

NSDictionary *SIFASMVExportCaptureFOV(void) {
    if (!pthread_main_np() || !resolveFOVRuntime()) return nil;
    FOVBounds bounds = fovRuntime.config->bounds;
    if (!validBounds(bounds.minimum, bounds.maximum)) return nil;
    return @{@"min": @(bounds.minimum), @"max": @(bounds.maximum)};
}

NSString *SIFASMVExportFOVFailure(NSString **detail) {
    NSString *check = nil, *text = @"";
    if (!pthread_main_np()) {
        check = @"fov.main-thread";
        text = @"called off the main thread";
    } else if (!resolveFOVRuntime()) {
        check = [NSString stringWithUTF8String:fovResolveCheck];
        text = [NSString stringWithUTF8String:fovResolveDetail] ?: @"";
    } else {
        const FOVBounds bounds = fovRuntime.config->bounds;
        if (!validBounds(bounds.minimum, bounds.maximum)) {
            check = @"fov.bounds";
            text = [NSString stringWithFormat:@"minimum %.5g, maximum %.5g", bounds.minimum, bounds.maximum];
        }
    }
    if (detail) *detail = text;
    return check;
}

SIFASMVExportFOVOverride *SIFASMVExportApplyFOV(NSDictionary *bounds, NSString **error) {
    FOVBounds target{};
    FOVBounds previous{};
    if (!pthread_main_np() || activeFOV || !readBounds(bounds, target) ||
        !readBounds(SIFASMVExportCaptureFOV(), previous)) {
        if (error) *error = @"The saved FOV could not be applied to the current game.";
        return nil;
    }
    SIFASMVExportFOVOverride *token = [SIFASMVExportFOVOverride new];
    token->original = previous;
    token->minimum = @(target.minimum);
    token->maximum = @(target.maximum);
    activeFOV = token;
    if (matchesBounds(previous, target)) return token;
    if (installFOVDefaults()) {
        token->enabled = YES;
        if (refreshFOV(target)) return token;
        token->enabled = NO;
        const bool rollback = refreshFOV(previous);
        if (error) *error = rollback ? @"The game did not apply the saved FOV." : @"The game did not verify FOV restoration.";
    } else if (error) {
        *error = @"The FOV adapter is unavailable.";
    }
    activeFOV = nil;
    return nil;
}

BOOL SIFASMVExportRestoreFOV(SIFASMVExportFOVOverride *token) {
    if (!pthread_main_np() || !token) return NO;
    if (token->restored) return YES;
    if (activeFOV != token) return NO;
    token->enabled = NO;
    token->restored = refreshFOV(token->original);
    activeFOV = nil;
    return token->restored;
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
