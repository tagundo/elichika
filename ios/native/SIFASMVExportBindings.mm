#import "SIFASMVExportBindings.h"
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <cstring>
#include <cmath>
#include <limits>
#include <initializer_list>
#include <cstddef>
#include <vector>

namespace {
/* VAs below were read from the actual dated GL method pointer table and
 * instruction stream. See research/game-bindings-addresses.json. This is
 * deliberately not a pattern scanner or an assumed exported IL2CPP API. */
const uint8_t kUUID[16] = {0x10,0xdf,0xf3,0xf5,0xcf,0xc3,0x3b,0xe8,0xaa,0xaa,0x3c,0x38,0xa9,0x9d,0x17,0x17};
intptr_t slide;
bool installed, active, advancing, sceneAbandoned;
SIFASMVBindingOriginals original = {};
SIFASMVBindingConfiguration config = {};
SIFASMVBindingCallbacks callbacks = {};
void *director, *observedOverlay, *sessionOverlay, *clockManager, *timeline, *music, *members;
void *exportTarget, *readbackTexture;
void *overlayCamera, *savedOverlayTarget;
uint32_t directorRoot, overlayRoot, renderRoot, readbackRoot, observedDirectorRoot, observedOverlayRoot;
uint32_t overlayCameraRoot, savedOverlayTargetRoot;
uint64_t tick;
int64_t captureIndex = -1;
bool haveTick, captured;
double clockEpoch, unscaledEpoch, savedTimelineTime, wallStart;
int32_t savedMusicTime, savedPlayState, savedUpdateMode;
bool savedMusicPlaying, savedMusicPaused;
uint32_t savedMusicFlags;
uint8_t clockSnapshot[0xe0]; /* native TimeManager offsets 0x30..0x10f */
NSString *lastFailure;
NSString *phase=@"idle";
struct Vector3 { float x,y,z; };
struct Quaternion { float x,y,z,w; };
struct BoneSnapshot {
    void *bone, *transform;
    uint8_t scalar[96];
    Quaternion rotation;
};
std::vector<BoneSnapshot> boneSnapshots;
struct ManagerSnapshot { void *manager; uint8_t paused; };
std::vector<ManagerSnapshot> managerSnapshots;
std::vector<uint8_t> boneBufferSnapshot, colliderBufferSnapshot;
void *savedBoneBuffer, *savedColliderBuffer;
int32_t savedBoneCount, savedColliderCount, savedJobIndex, savedSafetyCounter;
uint8_t savedKneeWork[24];

template<class T> T fn(uintptr_t address) { return reinterpret_cast<T>(address + slide); }
template<class T> T load(void *object, size_t offset) {
    T value; std::memcpy(&value, static_cast<uint8_t *>(object)+offset, sizeof(value)); return value;
}
template<class T> void put(void *object, size_t offset, T value) {
    std::memcpy(static_cast<uint8_t *>(object)+offset, &value, sizeof(value));
}
using InstanceVoid = void (*)(void *, const void *);
using InstanceInt = int32_t (*)(void *, const void *);
using InstanceDouble = double (*)(void *, const void *);
using RootAlloc = uint32_t (*)(void *, const void *);
using RootFree = void (*)(int32_t, const void *);
using RootTarget = void *(*)(int32_t, const void *);
using SetTime = void (*)(void *, double, const void *);
using SetMode = void (*)(void *, int32_t, const void *);
using StaticObject = void *(*)(const void *);
using SetObject = void (*)(void *, const void *);
using Blit = void (*)(void *, void *, const void *);
using SetTargetTexture = void (*)(void *,void *,const void *);
struct Rect { float x,y,width,height; };
using ReadPixels = void (*)(void *, Rect, int32_t, int32_t, bool, const void *);
using NewTexture = void (*)(void *, int32_t, int32_t, int32_t, bool, const void *);
using TemporaryRT = void *(*)(int32_t,int32_t,int32_t,int32_t,int32_t,int32_t,int32_t,int32_t,bool,const void *);

NSError *error(NSString *message) {
    return [NSError errorWithDomain:@"ElichikaMVGameBindings" code:1
                           userInfo:@{NSLocalizedDescriptionKey:message}];
}
bool onMain(NSError **out) {
    if ([NSThread isMainThread]) return true;
    if (out) *out=error(@"The MV renderer must run on Unity's main thread.");
    return false;
}
bool profileValid() {
    const mach_header *header=_dyld_get_image_header(0);
    if (!header || header->magic!=MH_MAGIC_64 || header->cputype!=CPU_TYPE_ARM64 ||
        header->ncmds>128 || header->sizeofcmds>65536) return false;
    const uint8_t *cursor=reinterpret_cast<const uint8_t *>(header)+sizeof(mach_header_64);
    const uint8_t *end=cursor+header->sizeofcmds;
    bool uuid=false;
    for (uint32_t i=0;i<header->ncmds;i++) {
        if (end-cursor<static_cast<ptrdiff_t>(sizeof(load_command))) return false;
        const load_command *command=reinterpret_cast<const load_command *>(cursor);
        if (command->cmdsize<sizeof(load_command) || command->cmdsize>static_cast<size_t>(end-cursor)) return false;
        if (command->cmd==LC_UUID && command->cmdsize==sizeof(uuid_command))
            uuid=!std::memcmp(reinterpret_cast<const uuid_command *>(command)->uuid,kUUID,16);
        cursor+=command->cmdsize;
    }
    if (!uuid || cursor!=end) return false;
    slide=_dyld_get_image_vmaddr_slide(0);
    /* Unpatched getters distinguish the pinned ABI even after entry shims. */
    const uint8_t timelineGetter[8]={0x00,0x20,0x40,0xf9,0xc0,0x03,0x5f,0xd6};
    const uint8_t timeGetter[16]={0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xe0,0x0b,0x00,0x32,0xff,0xaf,0x00,0x94};
    return !std::memcmp(reinterpret_cast<void *>(0x101520c50ULL+slide),timelineGetter,8) &&
           !std::memcmp(reinterpret_cast<void *>(0x10081498cULL+slide),timeGetter,16);
}
bool alive(void *object) {
    return object && fn<bool (*)(void *,const void *)>(0x103952e5c)(object,nullptr);
}
uint32_t retainManaged(void *object) {
    return object ? fn<RootAlloc>(0x103a95ee4)(object,nullptr) : 0;
}
void releaseManaged(uint32_t &handle) {
    if (handle) fn<RootFree>(0x103a95fb0)(static_cast<int32_t>(handle),nullptr);
    handle=0;
}
void observeDirector(void *value) {
    if (director==value && observedDirectorRoot) return;
    const uint32_t replacement=retainManaged(value);
    releaseManaged(observedDirectorRoot); releaseManaged(observedOverlayRoot);
    observedDirectorRoot=replacement; director=replacement ? value : nullptr;
    observedOverlay=nullptr;
}
void observeOverlay(void *value) {
    if (observedOverlay==value && observedOverlayRoot) return;
    const uint32_t replacement=retainManaged(value);
    releaseManaged(observedOverlayRoot);
    observedOverlayRoot=replacement; observedOverlay=replacement ? value : nullptr;
}
bool sceneValidUnchecked() {
    if (!directorRoot || !overlayRoot ||
        fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(directorRoot),nullptr)!=director ||
        fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(overlayRoot),nullptr)!=sessionOverlay ||
        !alive(director) || !alive(timeline) || !alive(music) || !alive(members) || !alive(sessionOverlay) || !alive(overlayCamera)) return false;
    if (load<void *>(director,0x40)!=timeline || load<void *>(director,0x68)!=music ||
        load<void *>(director,0x50)!=members) return false;
    void *manager=load<void *>(director,0x48);
    if (!alive(manager)) return false;
    void *final=load<void *>(manager,0x58);
    if (!final) final=load<void *>(manager,0x48);
    return final==sessionOverlay && sessionOverlay==observedOverlay && load<void *>(sessionOverlay,0x48)==overlayCamera;
}
bool sceneValid() noexcept {
    try { return sceneValidUnchecked(); } catch (...) { return false; }
}
NSString *managedString(void *object) {
    if (!object) return nil;
    const int32_t length=load<int32_t>(object,0x10);
    if (length<0 || length>4096) return nil;
    return [[NSString alloc] initWithCharacters:reinterpret_cast<const unichar *>(static_cast<uint8_t *>(object)+0x14)
                                       length:static_cast<NSUInteger>(length)];
}
void freezeDeltas() {
    if (!clockManager) return;
    for (size_t offset : {size_t(0x78),size_t(0x7c),size_t(0xa8),size_t(0xac)}) put<float>(clockManager,offset,0);
}
void completeJobs() {
    if (!members) return;
    /* Both managed JobHandle[] buffers, exact SZARRAY layout and 16-byte
     * JobHandle value size are verified in UpdateMultiThread's machine code. */
    for (size_t offset : {size_t(0xa8),size_t(0xb0)}) {
        void *array=load<void *>(members,offset);
        if (!array) {
            if (load<int32_t>(members,0x38)==0) continue;
            throw 2; /* Nonempty solver must have both actual job buffers. */
        }
        const uintptr_t count=load<uintptr_t>(array,0x18);
        if (count!=2) throw 2;
        for (uintptr_t i=0;i<count;i++)
            fn<InstanceVoid>(0x10392b49c)(static_cast<uint8_t *>(array)+0x20+i*16,nullptr);
    }
}
bool snapshotSprings() {
    completeJobs();
    boneSnapshots.clear(); managerSnapshots.clear(); boneBufferSnapshot.clear(); colliderBufferSnapshot.clear();
    savedBoneBuffer=load<void *>(members,0x30);
    savedBoneCount=load<int32_t>(members,0x38);
    savedColliderBuffer=load<void *>(members,0x50);
    savedColliderCount=load<int32_t>(members,0x58);
    savedJobIndex=load<int32_t>(members,0xa4);
    savedSafetyCounter=load<int32_t>(members,0xa0);
    std::memcpy(savedKneeWork,static_cast<uint8_t *>(members)+0x78,sizeof(savedKneeWork));
    if (savedBoneCount<0 || savedBoneCount>100000 || savedColliderCount<0 || savedColliderCount>100000 ||
        (savedBoneCount && !savedBoneBuffer) || (savedColliderCount && !savedColliderBuffer)) return false;
    void *managers=load<void *>(members,0x20);
    if (!managers) return savedBoneCount==0;
    const uintptr_t count=load<uintptr_t>(managers,0x18);
    if (count>128) return false;
    boneSnapshots.reserve(static_cast<size_t>(savedBoneCount));
    for (uintptr_t i=0;i<count;i++) {
        void *manager=load<void *>(managers,0x20+i*sizeof(void *));
        if (!manager) return false;
        managerSnapshots.push_back({manager,load<uint8_t>(manager,0x63)});
        void *bones=load<void *>(manager,0x50); /* GetSwingBones0x10183e110 */
        if (!bones) continue;
        const uintptr_t length=load<uintptr_t>(bones,0x18);
        if (length>static_cast<uintptr_t>(savedBoneCount)) return false;
        for (uintptr_t j=0;j<length;j++) {
            void *bone=load<void *>(bones,0x20+j*sizeof(void *));
            if (!bone) return false;
            void *transform=load<void *>(bone,0x98);
            if (!transform || !load<void *>(bone,0x20)) return false;
            BoneSnapshot item={}; item.bone=bone; item.transform=transform;
            std::memcpy(item.scalar,static_cast<uint8_t *>(bone)+0xb0,sizeof(item.scalar));
            item.rotation=fn<Quaternion (*)(void *,const void *)>(0x10397392c)(transform,nullptr);
            boneSnapshots.push_back(item);
        }
    }
    if (boneSnapshots.size()!=static_cast<size_t>(savedBoneCount)) return false;
    if (savedBoneCount) boneBufferSnapshot.assign(static_cast<uint8_t *>(savedBoneBuffer),static_cast<uint8_t *>(savedBoneBuffer)+static_cast<size_t>(savedBoneCount)*96);
    if (savedColliderCount) colliderBufferSnapshot.assign(static_cast<uint8_t *>(savedColliderBuffer),static_cast<uint8_t *>(savedColliderBuffer)+static_cast<size_t>(savedColliderCount)*64);
    return true;
}
void resetSpringsToInitialPose() {
    /* This reproduces SetSwingBones' initial-tip assignment without calling
     * its allocator or its manager-initialized early-return path. */
    for (const auto &item : managerSnapshots) fn<void (*)(void *,bool,const void *)>(0x10183b550)(item.manager,false,nullptr);
    for (const auto &item : boneSnapshots) {
        Quaternion rotation;
        std::memcpy(&rotation,item.scalar,sizeof(rotation));
        fn<void (*)(void *,Quaternion,const void *)>(0x103973a04)(item.transform,rotation,nullptr);
    }
    fn<void (*)(void *,bool,const void *)>(0x101522e24)(director,false,nullptr);
    fn<SetTime>(0x10397c6c8)(timeline,0,nullptr);
    fn<InstanceVoid>(0x10397c81c)(timeline,nullptr);
    fn<InstanceVoid>(0x10148a204)(members,nullptr); /* collect initial animated transforms */
    for (size_t i=0;i<boneSnapshots.size();i++) {
        const auto &item=boneSnapshots[i];
        void *child=load<void *>(item.bone,0x20);
        Vector3 tip=fn<Vector3 (*)(void *,const void *)>(0x103973314)(child,nullptr);
        uint8_t *buffer=static_cast<uint8_t *>(savedBoneBuffer)+i*96;
        std::memcpy(buffer+0x48,&tip,sizeof(tip));
        std::memcpy(buffer+0x54,&tip,sizeof(tip));
        put<Vector3>(item.bone,0xc8,tip); put<Vector3>(item.bone,0xd4,tip);
        put<uint8_t>(item.bone,0x108,0);
        put<float>(item.bone,0x10c,0);
    }
    fn<InstanceVoid>(0x10148a000)(members,nullptr); /* RequestAllSafeCorrect: two initial correction ticks */
}
void restoreSprings() {
    if (!members) return;
    completeJobs();
    if (load<void *>(members,0x30)!=savedBoneBuffer || load<int32_t>(members,0x38)!=savedBoneCount ||
        load<void *>(members,0x50)!=savedColliderBuffer || load<int32_t>(members,0x58)!=savedColliderCount)
        throw 1; /* Scene resource ownership changed; never write a stale buffer. */
    if (!boneBufferSnapshot.empty()) std::memcpy(savedBoneBuffer,boneBufferSnapshot.data(),boneBufferSnapshot.size());
    if (!colliderBufferSnapshot.empty()) std::memcpy(savedColliderBuffer,colliderBufferSnapshot.data(),colliderBufferSnapshot.size());
    put<int32_t>(members,0xa4,savedJobIndex); put<int32_t>(members,0xa0,savedSafetyCounter);
    std::memcpy(static_cast<uint8_t *>(members)+0x78,savedKneeWork,sizeof(savedKneeWork));
    for (const auto &item : boneSnapshots) {
        std::memcpy(static_cast<uint8_t *>(item.bone)+0xb0,item.scalar,sizeof(item.scalar));
        fn<void (*)(void *,Quaternion,const void *)>(0x103973a04)(item.transform,item.rotation,nullptr);
    }
    for (const auto &item : managerSnapshots) fn<void (*)(void *,bool,const void *)>(0x10183b550)(item.manager,item.paused!=0,nullptr);
    boneSnapshots.clear(); managerSnapshots.clear(); boneBufferSnapshot.clear(); colliderBufferSnapshot.clear();
}
void restore() {
    if (!active) return;
    const bool restoreScene=!sceneAbandoned && sceneValid();
    active=false; advancing=false;
    bool restorationFailed=false;
    auto attempt=[&](auto operation) { try { operation(); } catch (...) { restorationFailed=true; } };
    if (restoreScene) attempt([&] { completeJobs(); });
    if (clockManager) {
        attempt([&] {
            const double elapsed=fn<double (*)()>(0x100a91d70)()-wallStart;
            std::memcpy(static_cast<uint8_t *>(clockManager)+0x30,clockSnapshot,sizeof(clockSnapshot));
            /* Rebase anchors so the next normal frame cannot absorb the
             * entire encoding duration as simulation time. */
            for (size_t offset : {size_t(0xe0),size_t(0xe8)})
                put<double>(clockManager,offset,load<double>(clockManager,offset)+elapsed);
        });
    }
    attempt([&] {
        if (!restoreScene || !timeline || !alive(timeline)) return;
        fn<SetTime>(0x10397c6c8)(timeline,savedTimelineTime,nullptr);
        fn<InstanceVoid>(0x10397c81c)(timeline,nullptr);
        fn<SetMode>(0x10397c64c)(timeline,savedUpdateMode,nullptr);
        if (savedPlayState==1) fn<InstanceVoid>(0x10397c9cc)(timeline,nullptr);
        else fn<InstanceVoid>(0x10397c960)(timeline,nullptr);
    });
    attempt([&] {
        if (!restoreScene || !music || !alive(music)) return;
        fn<void (*)(void *,int32_t,const void *)>(0x10149dc74)(music,savedMusicTime,nullptr);
        put<int32_t>(music,0x1c,savedMusicTime);
        void *sound=fn<void *(*)(void *)>(0x1035bc074)(*reinterpret_cast<void **>(0x1058f1550ULL+slide));
        if (sound && savedMusicPlaying) {
            const uintptr_t operation=savedMusicPaused ? 0x10165b35cULL : 0x10165b694ULL;
            fn<void (*)(void *,int32_t,const void *)>(operation)(sound,load<int32_t>(music,0x80),nullptr);
        }
        put<uint32_t>(music,0x50,savedMusicFlags);
    });
    attempt([&] { if (restoreScene && members && alive(members)) restoreSprings(); });
    attempt([&] {
        if (!restoreScene || !alive(overlayCamera)) return;
        if (savedOverlayTarget && !alive(savedOverlayTarget)) throw 3;
        fn<SetTargetTexture>(0x103934410)(overlayCamera,savedOverlayTarget,nullptr);
    });
    attempt([&] { if (exportTarget && alive(exportTarget)) fn<SetObject>(0x10395ff58)(exportTarget,nullptr); });
    attempt([&] { if (readbackTexture && alive(readbackTexture)) fn<SetObject>(0x103953490)(readbackTexture,nullptr); });
    exportTarget=nullptr; readbackTexture=nullptr;
    attempt([&] { releaseManaged(renderRoot); });
    attempt([&] { releaseManaged(readbackRoot); });
    attempt([&] { releaseManaged(directorRoot); });
    attempt([&] { releaseManaged(overlayRoot); });
    attempt([&] { releaseManaged(overlayCameraRoot); });
    attempt([&] { releaseManaged(savedOverlayTargetRoot); });
    boneSnapshots.clear(); managerSnapshots.clear(); boneBufferSnapshot.clear(); colliderBufferSnapshot.clear();
    timeline=nullptr; music=nullptr; members=nullptr; sessionOverlay=nullptr; overlayCamera=nullptr; savedOverlayTarget=nullptr;
    captureIndex=-1; captured=false; haveTick=false;
    if (restorationFailed) lastFailure=@"One or more game resources rejected MV state restoration.";
    phase=restorationFailed ? @"restore-incomplete" : @"idle";
}
void fail(NSString *message) {
    NSString *detail=[NSString stringWithFormat:@"%@ [phase=%@]",message,phase];
    lastFailure=detail;
    const auto report=callbacks;
    try { restore(); } catch (...) { active=false; advancing=false; }
    /* Cleanup can add its own diagnostic; retain the initiating failure. */
    lastFailure=detail;
    if (report.failed) report.failed(report.context,detail);
}
}

BOOL SIFASMVBindingsInstallOriginals(const SIFASMVBindingOriginals *value, NSError **out) {
    if (!value || !value->timeUpdate || !value->liveUpdate || !value->musicUpdate ||
        !value->memberUpdate || !value->overlayRender || !value->screenWidth || !value->screenHeight ||
        !value->memberLateUpdate || !profileValid()) {
        if (out) *out=error(@"This MP4 renderer requires the verified GL 3.12.0 offline export shims.");
        return NO;
    }
    if (installed) {
        if (std::memcmp(&original,value,sizeof(original))) {
            if (out) *out=error(@"MV bindings are already installed with another shim contract.");
            return NO;
        }
        return YES;
    }
    original=*value; installed=true;
    return YES;
}

NSDictionary *SIFASMVBindingsStatus(void) {
    return @{ @"profile":@"GL-3.12.0-071607a0", @"installed":@(installed),
              @"active":@(active), @"liveDirectorObserved":@(director!=nullptr),
              @"finalOverlayObserved":@(observedOverlay!=nullptr),
              @"simulationTick":@(tick), @"phase":phase,
              @"lastFailure":lastFailure ?: @"" };
}

NSDictionary *SIFASMVBindingsSongSnapshot(void) {
    if (!installed || !director || !observedDirectorRoot || !onMain(nullptr)) return @{};
    try {
        if (fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(observedDirectorRoot),nullptr)!=director || !alive(director)) return @{};
        void *machine=load<void *>(director,0x68);
        if (!machine || load<uint8_t>(machine,0x18)) return @{};
        void *cue=load<void *>(machine,0x78);
        if (!cue) return @{};
        NSString *sheet=managedString(load<void *>(cue,0x10));
        NSString *name=managedString(load<void *>(cue,0x18));
        if (!sheet.length || !name.length) return @{};
        return @{ @"sheet":sheet, @"cue":name,
                  @"music_length_ms":@(load<int32_t>(machine,0x40)),
                  @"current_time_ms":@(load<int32_t>(machine,0x1c)),
                  @"start_time_ms":@0, @"source_offset_ms":@0,
                  @"timing_provenance":@"GL-3.12.0-LoadMusic-SeekMusic-zero-Sound.SetStartTime",
                  @"gain":@(load<float>(machine,0x24)) };
    } catch (...) { return @{}; }
}

BOOL SIFASMVBindingsBegin(SIFASMVBindingConfiguration value, SIFASMVBindingCallbacks sink, NSError **out) {
    if (!onMain(out)) return NO;
    if (!installed || active || !director || !observedDirectorRoot || !observedOverlayRoot || !observedOverlay || !sink.nextStep || !sink.frame || !sink.failed ||
        value.width<16 || value.height<16 || value.width>4096 || value.height>4096 ||
        value.simulationHz!=60) {
        if (out) *out=error(@"Load a 3D MV before exporting with supported dimensions and simulation rate.");
        return NO;
    }
    try {
        phase=@"snapshot-live-director";
        if (fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(observedDirectorRoot),nullptr)!=director || !alive(director)) { if(out)*out=error(@"The MV scene has closed."); return NO; }
        timeline=load<void *>(director,0x40); music=load<void *>(director,0x68);
        members=load<void *>(director,0x50);
        if (!timeline || !music || load<uint8_t>(music,0x18)) { if(out)*out=error(@"The MV is still loading."); return NO; }
        void *manager=load<void *>(director,0x48);
        if (!alive(manager)) { if(out)*out=error(@"The MV camera manager is no longer valid."); return NO; }
        sessionOverlay=load<void *>(manager,0x58);
        if (!sessionOverlay) sessionOverlay=load<void *>(manager,0x48);
        if (!alive(sessionOverlay) || sessionOverlay!=observedOverlay) {
            if(out)*out=error(@"The loaded MV has not rendered its final overlay yet."); return NO;
        }
        overlayCamera=load<void *>(sessionOverlay,0x48);
        if (!alive(overlayCamera)) { if(out)*out=error(@"The MV final camera is no longer valid."); return NO; }
        savedOverlayTarget=fn<void *(*)(void *,const void *)>(0x1039343a4)(overlayCamera,nullptr);
        clockManager=fn<void *(*)()>(0x10081498c)();
        if (!clockManager) { if(out)*out=error(@"Unity's simulation clock is unavailable."); return NO; }
        config=value; callbacks=sink; tick=0; haveTick=false; captured=false; captureIndex=-1; sceneAbandoned=false;
        savedTimelineTime=fn<InstanceDouble>(0x10397c744)(timeline,nullptr);
        savedPlayState=fn<InstanceInt>(0x10397c230)(timeline,nullptr);
        /* Native setter chain0x10077666c ->0x10071743c validates that the
         * director's update mode is uint32 at nativeObject+0x48. The managed
         * object caches nativeObject at+0x10. Restore through the setter. */
        void *nativeTimeline=load<void *>(timeline,0x10);
        if (!nativeTimeline) { if(out)*out=error(@"The MV timeline is no longer valid."); return NO; }
        savedUpdateMode=load<int32_t>(nativeTimeline,0x48);
        if (savedUpdateMode<0 || savedUpdateMode>3) { if(out)*out=error(@"The MV timeline mode differs from the verified game ABI."); return NO; }
        savedMusicTime=load<int32_t>(music,0x1c);
        savedMusicPlaying=load<uint8_t>(music,0x50)!=0;
        savedMusicPaused=load<uint8_t>(music,0x52)!=0;
        savedMusicFlags=load<uint32_t>(music,0x50);
        phase=@"snapshot-spring-buffers";
        if (!members || !snapshotSprings()) { if(out)*out=error(@"The MV spring buffers differ from the verified game layout."); return NO; }
        std::memcpy(clockSnapshot,static_cast<uint8_t *>(clockManager)+0x30,sizeof(clockSnapshot));
        clockEpoch=load<double>(clockManager,0x60);
        unscaledEpoch=load<double>(clockManager,0x70);
        wallStart=fn<double (*)()>(0x100a91d70)();
        directorRoot=retainManaged(director);
        if (!directorRoot) { if(out)*out=error(@"Cannot retain the MV scene."); return NO; }
        overlayRoot=retainManaged(sessionOverlay);
        if (!overlayRoot) { releaseManaged(directorRoot); if(out)*out=error(@"Cannot retain the MV final overlay."); return NO; }
        active=true;
        overlayCameraRoot=retainManaged(overlayCamera);
        savedOverlayTargetRoot=retainManaged(savedOverlayTarget);
        if (!overlayCameraRoot || (savedOverlayTarget && !savedOverlayTargetRoot)) { fail(@"Cannot retain the MV final camera target."); return NO; }
        phase=@"manual-timeline-mode";
        fn<SetMode>(0x10397c64c)(timeline,3,nullptr); /* DirectorUpdateMode.Manual */
        fn<InstanceVoid>(0x10397c9cc)(timeline,nullptr);
        put<uint32_t>(music,0x50,1); /* playing, no pause/fade/finish flags; CRI is paused below */
        phase=@"reset-initial-pose-and-springs";
        resetSpringsToInitialPose();
        /* Pause only CRI's playback handle after evaluating the initial music
         * track. PauseMusic would notify subscribers and pause the MV. */
        phase=@"pause-cri-song-handle";
        void *sound=fn<void *(*)(void *)>(0x1035bc074)(*reinterpret_cast<void **>(0x1058f1550ULL+slide));
        if (!sound) { fail(@"The selected MV song player is unavailable."); return NO; }
        fn<void (*)(void *,int32_t,const void *)>(0x10165b35c)(sound,load<int32_t>(music,0x80),nullptr);
        /* Explicit sRGB target reproduces the final backbuffer transfer. */
        phase=@"allocate-final-srgb-render-target";
        exportTarget=fn<TemporaryRT>(0x103960130)(value.width,value.height,0,0,2,1,0,0,false,nullptr);
        renderRoot=retainManaged(exportTarget);
        if (!renderRoot) { fail(@"Cannot retain the final MV render target."); return NO; }
        /* Setting the final overlay camera's target makes Unity allocate its
         * image-effect source at export dimensions. Redirecting only the
         * OnRenderImage destination could upscale a physical-screen source.
         * Main cameras retain their original explicit color/depth buffers. */
        phase=@"bind-export-resolution-final-camera";
        fn<SetTargetTexture>(0x103934410)(overlayCamera,exportTarget,nullptr);
        void *white=fn<StaticObject>(0x10396e548)(nullptr);
        if (!white) { fail(@"Unity cannot create the export readback texture."); return NO; }
        readbackTexture=fn<void *(*)(void *)>(0x101014950)(load<void *>(white,0));
        readbackRoot=retainManaged(readbackTexture);
        if (!renderRoot || !readbackRoot) { fail(@"Cannot retain the export textures."); return NO; }
        phase=@"allocate-readable-rgba32-texture";
        fn<NewTexture>(0x10396e1d0)(readbackTexture,value.width,value.height,4,false,nullptr); /* RGBA32, no mips */
        put<int32_t>(clockManager,0xd8,static_cast<int32_t>(value.simulationHz));
        put<float>(clockManager,0xfc,1.f);
        freezeDeltas();
        lastFailure=nil;
        phase=@"ready";
        return YES;
    } catch (...) {
        NSString *failedPhase=phase;
        fail([NSString stringWithFormat:@"The game rejected offline MV setup during %@.",failedPhase]);
        if(out)*out=error(lastFailure);
        return NO;
    }
}

void SIFASMVBindingsEnd(void) {
    if (!onMain(nullptr)) return;
    try { restore(); } catch (...) { active=false; advancing=false; lastFailure=@"The game rejected MV state restoration."; }
    callbacks={};
}

extern "C" void SIFASMVTimeUpdate(void *manager) {
    if (!installed) return;
    if (!active) { original.timeUpdate(manager); return; }
    try {
        phase=@"advance-native-clock";
        if (!sceneValid()) { fail(@"The MV scene or final camera changed during export."); original.timeUpdate(manager); return; }
        if (manager!=clockManager) { fail(@"Unity replaced its simulation clock during export."); original.timeUpdate(manager); return; }
        uint64_t next=0; int64_t image=-1;
        advancing=callbacks.nextStep(callbacks.context,&next,&image);
        if (!active) { original.timeUpdate(manager); return; }
        if (!advancing) { freezeDeltas(); return; }
        if ((haveTick && next!=tick+1) || (!haveTick && next!=0)) { fail(@"The offline simulation tick sequence is discontinuous."); return; }
        const double dt=haveTick ? 1.0/config.simulationHz : 0.0;
        original.timeUpdate(manager);
        tick=next; haveTick=true; captureIndex=image; captured=false;
        const double time=clockEpoch+static_cast<double>(tick)/config.simulationHz;
        const double unscaledTime=unscaledEpoch+static_cast<double>(tick)/config.simulationHz;
        put<double>(manager,0x60,time); put<double>(manager,0x68,time-dt); put<double>(manager,0x70,unscaledTime);
        put<float>(manager,0x78,static_cast<float>(dt)); put<float>(manager,0x7c,static_cast<float>(dt));
        put<double>(manager,0x90,time); put<double>(manager,0x98,time-dt); put<double>(manager,0xa0,unscaledTime);
        put<float>(manager,0xa8,static_cast<float>(dt)); put<float>(manager,0xac,static_cast<float>(dt));
        const double seconds=static_cast<double>(tick)/config.simulationHz;
        const uint64_t milliseconds=tick*1000ULL/config.simulationHz;
        if (milliseconds>INT32_MAX) { fail(@"The MV timeline exceeds its native time range."); return; }
        put<int32_t>(music,0x1c,static_cast<int32_t>(milliseconds));
        phase=@"evaluate-live-timeline";
        fn<SetTime>(0x10397c6c8)(timeline,seconds,nullptr);
        fn<InstanceVoid>(0x10397c81c)(timeline,nullptr);
    } catch (...) { fail(@"Unity failed to advance an offline MV frame."); }
}

extern "C" void SIFASMVLiveUpdate(void *value, const void *methodInfo) {
    if (!installed) return;
    if (!active) { observeDirector(value); original.liveUpdate(value,methodInfo); return; }
    if (value!=director) {
        sceneAbandoned=true;
        fail(@"A different MV scene started during export.");
        observeDirector(value);
        original.liveUpdate(value,methodInfo); return;
    }
    if (!sceneValid()) { fail(@"The active MV scene was destroyed during its update."); return; }
    if (!advancing) return;
    try {
        phase=@"set-live-beat-shader-time";
        original.liveUpdate(value,methodInfo); /* game music/beat shader uniforms */
    } catch (...) { fail(@"The game's MV timeline could not evaluate the requested frame."); }
}

extern "C" void SIFASMVMusicUpdate(void *value, const void *methodInfo) {
    if (!installed) return;
    if (!active || value!=music) original.musicUpdate(value,methodInfo);
}

extern "C" void SIFASMVMemberUpdate(void *value, const void *methodInfo) {
    if (!installed) return;
    if (!active || value!=members) { original.memberUpdate(value,methodInfo); return; }
    if (!advancing || tick==0) return;
    try {
        phase=@"complete-spring-physics-tick";
        /* Normal UpdateMultiThread skips its simulation when prior jobs are
         * still busy. Offline export must wait before that readiness test so
         * encoder/device speed cannot silently skip a physics tick. */
        completeJobs();
        original.memberUpdate(value,methodInfo);
        completeJobs();
    } catch (...) { fail(@"The game's spring simulation could not finish an offline physics tick."); }
}

extern "C" void SIFASMVMemberLateUpdate(void *value, const void *methodInfo) {
    if (!installed) return;
    if (!active || value!=members || (advancing && tick>0)) original.memberLateUpdate(value,methodInfo);
}

extern "C" int32_t SIFASMVScreenWidth(const void *methodInfo) {
    return active ? static_cast<int32_t>(config.width) : (original.screenWidth ? original.screenWidth(methodInfo) : 0);
}
extern "C" int32_t SIFASMVScreenHeight(const void *methodInfo) {
    return active ? static_cast<int32_t>(config.height) : (original.screenHeight ? original.screenHeight(methodInfo) : 0);
}

extern "C" void SIFASMVOverlayRender(void *overlay, void *source, void *destination, const void *methodInfo) {
    if (!installed) return;
    if (!active) { observeOverlay(overlay); original.overlayRender(overlay,source,destination,methodInfo); return; }
    if (!sceneValid()) {
        fail(@"The MV scene or final camera changed before frame capture.");
        observeOverlay(overlay);
        original.overlayRender(overlay,source,destination,methodInfo); return;
    }
    if (overlay!=sessionOverlay || !advancing || captureIndex<0 || captured) {
        original.overlayRender(overlay,source,destination,methodInfo); return;
    }
    void *previous=nullptr;
    bool restoreActive=false;
    try {
        phase=@"render-final-overlay";
        completeJobs();
        original.overlayRender(overlay,source,exportTarget,methodInfo);
        if (destination!=exportTarget)
            fn<Blit>(0x10394258c)(exportTarget,destination,nullptr);
        previous=fn<StaticObject>(0x10395fac4)(nullptr);
        restoreActive=true;
        fn<SetObject>(0x10395fac8)(exportTarget,nullptr);
        phase=@"read-final-render-pixels";
        fn<ReadPixels>(0x103970088)(readbackTexture,{0,0,static_cast<float>(config.width),static_cast<float>(config.height)},0,0,false,nullptr);
        fn<SetObject>(0x10395fac8)(previous,nullptr); restoreActive=false;
        const uint64_t needed=static_cast<uint64_t>(config.width)*config.height*4;
        const uint64_t bytes=fn<uint64_t (*)(void *,const void *)>(0x10396eea4)(readbackTexture,nullptr);
        const uint8_t *rgba=fn<const uint8_t *(*)(void *,int32_t,const void *)>(0x10396ee28)(readbackTexture,0,nullptr);
        if (!rgba || bytes<needed) { fail(@"Unity returned an incomplete final MV render."); return; }
        NSMutableData *data=[NSMutableData dataWithLength:static_cast<NSUInteger>(needed)];
        uint8_t *bgra=static_cast<uint8_t *>(data.mutableBytes);
        const size_t rowBytes=static_cast<size_t>(config.width)*4;
        for (uint32_t y=0;y<config.height;y++) {
            const uint8_t *row=rgba+(config.height-1-y)*rowBytes;
            uint8_t *out=bgra+y*rowBytes;
            for (uint32_t x=0;x<config.width;x++) { out[x*4]=row[x*4+2]; out[x*4+1]=row[x*4+1]; out[x*4+2]=row[x*4]; out[x*4+3]=255; }
        }
        captured=true;
        phase=@"submit-complete-bgra-frame";
        callbacks.frame(callbacks.context,data,rowBytes,captureIndex);
    } catch (...) {
        if (restoreActive) { try { fn<SetObject>(0x10395fac8)(previous,nullptr); } catch (...) {} }
        fail(@"Unity failed to read the complete final MV render.");
    }
}
