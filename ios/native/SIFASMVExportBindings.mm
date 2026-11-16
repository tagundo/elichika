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
bool installed, active, advancing, sceneAbandoned, finalCameraObserved, resolutionRequested, resolutionReady;
bool springSnapshotReady, clockSnapshotValid, clockMutated, sceneMutated;
SIFASMVBindingOriginals original = {};
SIFASMVBindingConfiguration config = {};
SIFASMVBindingCallbacks callbacks = {};
void *director, *observedOverlay, *sessionOverlay, *clockManager, *timeline, *music, *members;
void *sceneCameraManager;
void *readbackTexture;
void *overlayCamera;
uint32_t directorRoot, overlayRoot, readbackRoot, observedDirectorRoot, observedOverlayRoot;
uint32_t overlayCameraRoot;
int32_t savedWidth, savedHeight;
int32_t savedFullScreenMode, savedRefreshRate;
void *screenManager;
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
    void *bone, *transform, *child, *parent;
    uint8_t scalar[96];
    Quaternion rotation;
};
std::vector<BoneSnapshot> boneSnapshots;
struct ManagerSnapshot {
    void *manager, *bones;
    size_t firstBone;
    uintptr_t boneCount;
    uint8_t paused;
};
std::vector<ManagerSnapshot> managerSnapshots;
struct SnapshotRoot { void *object; uint32_t handle; };
constexpr size_t kMaxSnapshotRoots=32768;
constexpr size_t kMaxSolverCopyBytes=32U*1024U*1024U;
std::vector<SnapshotRoot> snapshotRoots;
std::vector<uint8_t> boneBufferSnapshot, colliderBufferSnapshot;
void *savedManagersArray, *savedJobArrays[2];
uintptr_t savedManagerCount;
uint8_t savedNativeArrays[4][16];
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
struct Rect { float x,y,width,height; };
using ReadPixels = void (*)(void *, Rect, int32_t, int32_t, bool, const void *);
using NewTexture = void (*)(void *, int32_t, int32_t, int32_t, bool, const void *);
using SetResolution = void (*)(int32_t,int32_t,int32_t,int32_t,const void *);

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
bool retainSnapshot(void *object) {
    if (!object || snapshotRoots.size()>=kMaxSnapshotRoots) return false;
    /* Reserve the complete bounded ledger before allocating its first handle,
     * so appending an allocated handle cannot lose it to std::bad_alloc. */
    if (snapshotRoots.capacity()<kMaxSnapshotRoots) snapshotRoots.reserve(kMaxSnapshotRoots);
    const uint32_t handle=retainManaged(object);
    if (!handle) return false;
    snapshotRoots.push_back({object,handle});
    return true;
}
bool snapshotRootsValid() {
    for (const auto &entry : snapshotRoots)
        if (!entry.handle || fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(entry.handle),nullptr)!=entry.object) return false;
    return true;
}
bool releaseSnapshotRoots() noexcept {
    size_t retained=0;
    for (auto entry : snapshotRoots) {
        try { releaseManaged(entry.handle); }
        catch (...) { snapshotRoots[retained++]=entry; }
    }
    /* Failed frees remain in the same bounded ledger for a later retry. No
     * new setup is permitted while this quarantine is nonempty. */
    snapshotRoots.resize(retained);
    return retained==0;
}
void observeDirector(void *value) {
    if (director==value && observedDirectorRoot) return;
    const uint32_t replacement=retainManaged(value);
    releaseManaged(observedDirectorRoot); releaseManaged(observedOverlayRoot);
    observedDirectorRoot=replacement; director=replacement ? value : nullptr;
    observedOverlay=nullptr;
    finalCameraObserved=false;
}
void observeOverlay(void *value) {
    if (observedOverlay==value && observedOverlayRoot) return;
    const uint32_t replacement=retainManaged(value);
    releaseManaged(observedOverlayRoot);
    observedOverlayRoot=replacement; observedOverlay=replacement ? value : nullptr;
}
bool ownedSnapshotValid() {
    if (!springSnapshotReady || !snapshotRootsValid() || !members || !alive(members) ||
        !load<uint8_t>(members,0x28)) return false; /* Term clears setupGroupData after disposal. */
    if (load<void *>(members,0x20)!=savedManagersArray) return false;
    for (size_t i=0;i<4;i++)
        if (std::memcmp(static_cast<uint8_t *>(members)+0x30+i*16,savedNativeArrays[i],16)) return false;
    for (size_t i=0;i<2;i++) {
        void *array=load<void *>(members,0xa8+i*8);
        if (array!=savedJobArrays[i] || (!array && savedBoneCount)) return false;
        if (array && load<uintptr_t>(array,0x18)!=2) return false;
    }
    if (!savedManagersArray) return savedManagerCount==0 && boneSnapshots.empty();
    if (load<uintptr_t>(savedManagersArray,0x18)!=savedManagerCount || managerSnapshots.size()!=savedManagerCount) return false;
    for (size_t i=0;i<managerSnapshots.size();i++) {
        const auto &manager=managerSnapshots[i];
        if (load<void *>(savedManagersArray,0x20+i*sizeof(void *))!=manager.manager || !alive(manager.manager) ||
            load<void *>(manager.manager,0x50)!=manager.bones) return false;
        if (!manager.bones) { if (manager.boneCount) return false; continue; }
        if (load<uintptr_t>(manager.bones,0x18)!=manager.boneCount ||
            manager.firstBone>boneSnapshots.size() || manager.boneCount>boneSnapshots.size()-manager.firstBone) return false;
        for (uintptr_t j=0;j<manager.boneCount;j++) {
            const auto &bone=boneSnapshots[manager.firstBone+j];
            if (load<void *>(manager.bones,0x20+j*sizeof(void *))!=bone.bone || !alive(bone.bone) ||
                load<void *>(bone.bone,0x98)!=bone.transform || load<void *>(bone.bone,0x20)!=bone.child ||
                load<void *>(bone.bone,0xa8)!=bone.parent || !alive(bone.transform) || !alive(bone.child) || !alive(bone.parent)) return false;
        }
    }
    return true;
}
void requireOwnedSnapshot() {
    if (!ownedSnapshotValid()) { sceneAbandoned=true; throw 4; }
}
bool sceneValidUnchecked() {
    if (!directorRoot || !overlayRoot || !snapshotRootsValid() ||
        fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(directorRoot),nullptr)!=director ||
        fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(overlayRoot),nullptr)!=sessionOverlay ||
        !alive(director) || !load<uint8_t>(director,0x20)) return false;
    if (load<void *>(director,0x40)!=timeline || load<void *>(director,0x68)!=music ||
        load<void *>(director,0x50)!=members || load<void *>(director,0x48)!=sceneCameraManager) return false;
    /* Compare the retained owner's fields before touching a formerly-owned
     * managed wrapper: replacing a field can make its previous target collectible. */
    if (!alive(timeline) || !alive(music) || !alive(members) || !alive(sessionOverlay) || !alive(overlayCamera)) return false;
    void *manager=sceneCameraManager;
    if (!alive(manager)) return false;
    void *final=load<void *>(manager,0x58);
    if (!final) final=load<void *>(manager,0x48);
    return final==sessionOverlay && sessionOverlay==observedOverlay && load<void *>(sessionOverlay,0x48)==overlayCamera && ownedSnapshotValid();
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
    if (active && clockSnapshotValid) clockMutated=true;
    for (size_t offset : {size_t(0x78),size_t(0x7c),size_t(0xa8),size_t(0xac)}) put<float>(clockManager,offset,0);
}
void completeJobs() {
    if (springSnapshotReady) requireOwnedSnapshot();
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
    springSnapshotReady=false;
    boneSnapshots.clear(); managerSnapshots.clear(); boneBufferSnapshot.clear(); colliderBufferSnapshot.clear();
    if (!members || !load<uint8_t>(members,0x28)) return false;
    savedBoneBuffer=load<void *>(members,0x30);
    savedBoneCount=load<int32_t>(members,0x38);
    savedColliderBuffer=load<void *>(members,0x50);
    savedColliderCount=load<int32_t>(members,0x58);
    savedJobIndex=load<int32_t>(members,0xa4);
    savedSafetyCounter=load<int32_t>(members,0xa0);
    std::memcpy(savedKneeWork,static_cast<uint8_t *>(members)+0x78,sizeof(savedKneeWork));
    if (savedBoneCount<0 || savedBoneCount>100000 || savedColliderCount<0 || savedColliderCount>100000 ||
        (savedBoneCount && !savedBoneBuffer) || (savedColliderCount && !savedColliderBuffer) ||
        static_cast<size_t>(savedBoneCount)*96+static_cast<size_t>(savedColliderCount)*64>kMaxSolverCopyBytes) return false;
    for (size_t i=0;i<4;i++) std::memcpy(savedNativeArrays[i],static_cast<uint8_t *>(members)+0x30+i*16,16);
    savedManagersArray=load<void *>(members,0x20);
    savedManagerCount=savedManagersArray ? load<uintptr_t>(savedManagersArray,0x18) : 0;
    if (savedManagerCount>128 || (!savedManagersArray && savedBoneCount) ||
        static_cast<size_t>(savedBoneCount)*4+savedManagerCount*2+snapshotRoots.size()+3>kMaxSnapshotRoots) return false;
    if (savedManagersArray && !retainSnapshot(savedManagersArray)) return false;
    for (size_t i=0;i<2;i++) {
        savedJobArrays[i]=load<void *>(members,0xa8+i*8);
        if (!savedJobArrays[i]) { if(savedBoneCount) return false; continue; }
        if (!retainSnapshot(savedJobArrays[i]) || load<uintptr_t>(savedJobArrays[i],0x18)!=2) return false;
    }
    boneSnapshots.reserve(static_cast<size_t>(savedBoneCount));
    managerSnapshots.reserve(static_cast<size_t>(savedManagerCount));
    for (uintptr_t i=0;i<savedManagerCount;i++) {
        void *manager=load<void *>(savedManagersArray,0x20+i*sizeof(void *));
        if (!retainSnapshot(manager) || !alive(manager)) return false;
        void *bones=load<void *>(manager,0x50); /* GetSwingBones0x10183e110 */
        const uintptr_t length=bones ? load<uintptr_t>(bones,0x18) : 0;
        if (bones && !retainSnapshot(bones)) return false;
        if (length>static_cast<uintptr_t>(savedBoneCount) || boneSnapshots.size()+length>static_cast<size_t>(savedBoneCount)) return false;
        managerSnapshots.push_back({manager,bones,boneSnapshots.size(),length,load<uint8_t>(manager,0x63)});
        for (uintptr_t j=0;j<length;j++) {
            void *bone=load<void *>(bones,0x20+j*sizeof(void *));
            if (!retainSnapshot(bone) || !alive(bone)) return false;
            void *transform=load<void *>(bone,0x98), *child=load<void *>(bone,0x20), *parent=load<void *>(bone,0xa8);
            if (!retainSnapshot(transform) || !retainSnapshot(child) || !retainSnapshot(parent) ||
                !alive(transform) || !alive(child) || !alive(parent)) return false;
            BoneSnapshot item={}; item.bone=bone; item.transform=transform; item.child=child; item.parent=parent;
            boneSnapshots.push_back(item);
        }
    }
    if (boneSnapshots.size()!=static_cast<size_t>(savedBoneCount)) return false;
    springSnapshotReady=true;
    requireOwnedSnapshot();
    completeJobs();
    requireOwnedSnapshot();
    for (auto &item : boneSnapshots) {
        std::memcpy(item.scalar,static_cast<uint8_t *>(item.bone)+0xb0,sizeof(item.scalar));
        item.rotation=fn<Quaternion (*)(void *,const void *)>(0x10397392c)(item.transform,nullptr);
    }
    if (savedBoneCount) boneBufferSnapshot.assign(static_cast<uint8_t *>(savedBoneBuffer),static_cast<uint8_t *>(savedBoneBuffer)+static_cast<size_t>(savedBoneCount)*96);
    if (savedColliderCount) colliderBufferSnapshot.assign(static_cast<uint8_t *>(savedColliderBuffer),static_cast<uint8_t *>(savedColliderBuffer)+static_cast<size_t>(savedColliderCount)*64);
    return true;
}
void resetSpringsToInitialPose() {
    requireOwnedSnapshot();
    /* This reproduces SetSwingBones' initial-tip assignment without calling
     * its allocator or its manager-initialized early-return path. */
    for (const auto &item : managerSnapshots) fn<void (*)(void *,bool,const void *)>(0x10183b550)(item.manager,false,nullptr);
    for (const auto &item : boneSnapshots) {
        Quaternion rotation;
        std::memcpy(&rotation,item.scalar,sizeof(rotation));
        fn<void (*)(void *,Quaternion,const void *)>(0x103973a04)(item.transform,rotation,nullptr);
    }
    requireOwnedSnapshot();
    fn<void (*)(void *,bool,const void *)>(0x101522e24)(director,false,nullptr);
    requireOwnedSnapshot();
    fn<SetTime>(0x10397c6c8)(timeline,0,nullptr);
    fn<InstanceVoid>(0x10397c81c)(timeline,nullptr);
    requireOwnedSnapshot();
    fn<InstanceVoid>(0x10148a204)(members,nullptr); /* collect initial animated transforms */
    requireOwnedSnapshot();
    for (size_t i=0;i<boneSnapshots.size();i++) {
        const auto &item=boneSnapshots[i];
        Vector3 tip=fn<Vector3 (*)(void *,const void *)>(0x103973314)(item.child,nullptr);
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
    requireOwnedSnapshot();
    completeJobs();
    requireOwnedSnapshot();
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
}
bool clearOwnedSetup() noexcept {
    springSnapshotReady=false;
    boneSnapshots.clear(); managerSnapshots.clear(); boneBufferSnapshot.clear(); colliderBufferSnapshot.clear();
    bool released=releaseSnapshotRoots();
    for (uint32_t *handle : {&directorRoot,&overlayRoot,&overlayCameraRoot,&readbackRoot}) {
        try { releaseManaged(*handle); } catch (...) { released=false; }
    }
    timeline=nullptr; music=nullptr; members=nullptr; sessionOverlay=nullptr; overlayCamera=nullptr; sceneCameraManager=nullptr;
    readbackTexture=nullptr; clockManager=nullptr; screenManager=nullptr;
    savedManagersArray=nullptr; savedJobArrays[0]=nullptr; savedJobArrays[1]=nullptr;
    savedBoneBuffer=nullptr; savedColliderBuffer=nullptr; savedManagerCount=0;
    resolutionRequested=false; resolutionReady=false; clockSnapshotValid=false; clockMutated=false; sceneMutated=false;
    captureIndex=-1; captured=false; haveTick=false; advancing=false;
    callbacks={};
    return released;
}
void restore() {
    if (!active) {
        if (!clearOwnedSetup()) { lastFailure=@"MV managed-root cleanup is incomplete; setup must be retried before exporting."; phase=@"cleanup-incomplete"; }
        return;
    }
    bool restoreScene=!sceneAbandoned && sceneMutated && sceneValid();
    active=false; advancing=false;
    bool restorationFailed=false;
    auto attempt=[&](auto operation) { try { operation(); } catch (...) { restorationFailed=true; } };
    if (restoreScene) attempt([&] { completeJobs(); });
    if (clockSnapshotValid && clockMutated && clockManager) {
        attempt([&] {
            if (fn<void *(*)()>(0x10081498c)()!=clockManager) throw 5;
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
        if (!sceneValid()) { restoreScene=false; sceneAbandoned=true; throw 4; }
        fn<SetMode>(0x10397c64c)(timeline,savedUpdateMode,nullptr);
        if (savedPlayState==1) fn<InstanceVoid>(0x10397c9cc)(timeline,nullptr);
        else fn<InstanceVoid>(0x10397c960)(timeline,nullptr);
    });
    attempt([&] {
        if (!restoreScene || !music || !alive(music)) return;
        if (!sceneValid()) { restoreScene=false; sceneAbandoned=true; throw 4; }
        fn<void (*)(void *,int32_t,const void *)>(0x10149dc74)(music,savedMusicTime,nullptr);
        if (!sceneValid()) { restoreScene=false; sceneAbandoned=true; throw 4; }
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
        if (resolutionRequested && fn<void *(*)()>(0x1008f85d8)()==screenManager)
            fn<SetResolution>(0x10396462c)(savedWidth,savedHeight,savedFullScreenMode,savedRefreshRate,nullptr);
    });
    attempt([&] { if (readbackTexture && alive(readbackTexture)) fn<SetObject>(0x103953490)(readbackTexture,nullptr); });
    if (!clearOwnedSetup()) restorationFailed=true;
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
        !value->memberLateUpdate || !value->cameraPostRender || !profileValid()) {
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
    bool observed=false;
    if (installed && observedDirectorRoot && [NSThread isMainThread]) {
        try {
            observed=fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(observedDirectorRoot),nullptr)==director &&
                     alive(director) && load<uint8_t>(director,0x20)!=0;
        } catch (...) { observed=false; }
    }
    return @{ @"profile":@"GL-3.12.0-071607a0", @"installed":@(installed),
              @"active":@(active), @"liveDirectorObserved":@(observed),
              @"finalOverlayObserved":@(finalCameraObserved),
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
        const int32_t identity=fn<InstanceInt>(0x103952b08)(director,nullptr);
        if (!identity) return @{};
        return @{ @"sheet":sheet, @"cue":name,
                  @"scene_identity":@(identity),
                  @"music_length_ms":@(load<int32_t>(machine,0x40)),
                  @"current_time_ms":@(load<int32_t>(machine,0x1c)),
                  @"start_time_ms":@0, @"source_offset_ms":@0,
                  @"timing_provenance":@"GL-3.12.0-LoadMusic-SeekMusic-zero-Sound.SetStartTime",
                  @"gain":@(load<float>(machine,0x24)) };
    } catch (...) { return @{}; }
}

BOOL SIFASMVBindingsBegin(SIFASMVBindingConfiguration value, SIFASMVBindingCallbacks sink, NSError **out) {
    if (!onMain(out)) return NO;
    if (!active) restore(); /* Retry any prior bounded root quarantine first. */
    if (!snapshotRoots.empty() || directorRoot || overlayRoot || overlayCameraRoot || readbackRoot) {
        if(out)*out=error(@"Managed roots from the previous export could not be released."); return NO;
    }
    if (!installed || active || !director || !observedDirectorRoot || !sink.nextStep || !sink.frame || !sink.failed ||
        value.width<16 || value.height<16 || value.width>4096 || value.height>4096 ||
        value.simulationHz!=60) {
        if (out) *out=error(@"Load a 3D MV before exporting with supported dimensions and simulation rate.");
        return NO;
    }
    struct BeginRollback {
        bool committed=false;
        ~BeginRollback() { if (!committed) restore(); }
    } rollback;
    try {
        phase=@"snapshot-live-director";
        if (fn<RootTarget>(0x103a95da0)(static_cast<int32_t>(observedDirectorRoot),nullptr)!=director || !alive(director)) { if(out)*out=error(@"The MV scene has closed."); return NO; }
        timeline=load<void *>(director,0x40); music=load<void *>(director,0x68);
        members=load<void *>(director,0x50);
        void *manager=load<void *>(director,0x48);
        sceneCameraManager=manager;
        if (!retainSnapshot(timeline) || !retainSnapshot(music) || !retainSnapshot(members) || !retainSnapshot(manager)) {
            if(out)*out=error(@"Cannot retain the MV's timeline, song, member and camera managers."); return NO;
        }
        if (!alive(timeline) || !alive(music) || !alive(members) || load<uint8_t>(music,0x18)) { if(out)*out=error(@"The MV is still loading."); return NO; }
        if (!alive(manager)) { if(out)*out=error(@"The MV camera manager is no longer valid."); return NO; }
        sessionOverlay=load<void *>(manager,0x58);
        if (!sessionOverlay) sessionOverlay=load<void *>(manager,0x48);
        if (!retainSnapshot(sessionOverlay) || !alive(sessionOverlay)) { if(out)*out=error(@"The MV final overlay is no longer valid."); return NO; }
        overlayCamera=load<void *>(sessionOverlay,0x48);
        if (!retainSnapshot(overlayCamera) || !alive(overlayCamera)) { if(out)*out=error(@"The MV final camera is no longer valid."); return NO; }
        if (fn<bool (*)(void *,const void *)>(0x103930014)(sessionOverlay,nullptr)) {
            if(out)*out=error(@"Resume the MV before exporting; its pause or blur effect is active."); return NO;
        }
        if (fn<void *(*)(void *,const void *)>(0x1039343a4)(overlayCamera,nullptr)) {
            if(out)*out=error(@"The MV final camera uses an unsupported custom target."); return NO;
        }
        observeOverlay(sessionOverlay);
        clockManager=fn<void *(*)()>(0x10081498c)();
        if (!clockManager) { if(out)*out=error(@"Unity's simulation clock is unavailable."); return NO; }
        config=value; callbacks=sink; tick=0; haveTick=false; captured=false; captureIndex=-1; sceneAbandoned=false;
        resolutionRequested=false; resolutionReady=false;
        savedWidth=original.screenWidth(nullptr); savedHeight=original.screenHeight(nullptr);
        if (savedWidth<=0 || savedHeight<=0) { if(out)*out=error(@"Unity has no valid rendering surface."); return NO; }
        /* The exact iOS ScreenManager vtable exposes the current mode and
         * refresh getters even though the managed getters were stripped.
         * Preserve the enum, including its native -1 keep-current sentinel;
         * a Boolean fullscreen overload would discard the original mode. */
        screenManager=fn<void *(*)()>(0x1008f85d8)();
        if (!screenManager || load<uintptr_t>(screenManager,0)!=0x10525bb00ULL+slide) {
            if(out)*out=error(@"The native rendering-surface manager differs from the verified game ABI."); return NO;
        }
        savedFullScreenMode=fn<int32_t (*)(void *)>(0x100a92490)(screenManager);
        savedRefreshRate=fn<int32_t (*)(void *)>(0x100a92498)(screenManager);
        if (savedFullScreenMode < -1 || savedFullScreenMode > 3 || savedRefreshRate<0 || savedRefreshRate>1000) {
            if(out)*out=error(@"Unity returned an invalid rendering-surface mode."); return NO;
        }
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
        clockSnapshotValid=true;
        clockEpoch=load<double>(clockManager,0x60);
        unscaledEpoch=load<double>(clockManager,0x70);
        wallStart=fn<double (*)()>(0x100a91d70)();
        directorRoot=retainManaged(director);
        if (!directorRoot) { if(out)*out=error(@"Cannot retain the MV scene."); return NO; }
        overlayRoot=retainManaged(sessionOverlay);
        if (!overlayRoot) { releaseManaged(directorRoot); if(out)*out=error(@"Cannot retain the MV final overlay."); return NO; }
        active=true;
        overlayCameraRoot=retainManaged(overlayCamera);
        if (!overlayCameraRoot) { fail(@"Cannot retain the MV final camera."); return NO; }
        phase=@"manual-timeline-mode";
        requireOwnedSnapshot();
        sceneMutated=true;
        fn<SetMode>(0x10397c64c)(timeline,3,nullptr); /* DirectorUpdateMode.Manual */
        fn<InstanceVoid>(0x10397c9cc)(timeline,nullptr);
        requireOwnedSnapshot();
        put<uint32_t>(music,0x50,1); /* playing, no pause/fade/finish flags; CRI is paused below */
        phase=@"reset-initial-pose-and-springs";
        resetSpringsToInitialPose();
        /* Pause only CRI's playback handle after evaluating the initial music
         * track. PauseMusic would notify subscribers and pause the MV. */
        phase=@"pause-cri-song-handle";
        void *sound=fn<void *(*)(void *)>(0x1035bc074)(*reinterpret_cast<void **>(0x1058f1550ULL+slide));
        if (!sound) { fail(@"The selected MV song player is unavailable."); return NO; }
        fn<void (*)(void *,int32_t,const void *)>(0x10165b35c)(sound,load<int32_t>(music,0x80),nullptr);
        void *white=fn<StaticObject>(0x10396e548)(nullptr);
        if (!white) { fail(@"Unity cannot create the export readback texture."); return NO; }
        readbackTexture=fn<void *(*)(void *)>(0x101014950)(load<void *>(white,0));
        readbackRoot=retainManaged(readbackTexture);
        if (!readbackRoot) { fail(@"Cannot retain the export readback texture."); return NO; }
        phase=@"allocate-readable-rgba32-texture";
        fn<NewTexture>(0x10396e1d0)(readbackTexture,value.width,value.height,4,false,nullptr); /* RGBA32, no mips */
        clockMutated=true;
        put<int32_t>(clockManager,0xd8,static_cast<int32_t>(value.simulationHz));
        put<float>(clockManager,0xfc,1.f);
        freezeDeltas();
        phase=@"request-native-rendering-resolution";
        resolutionRequested=true;
        fn<SetResolution>(0x10396462c)(value.width,value.height,savedFullScreenMode,savedRefreshRate,nullptr);
        lastFailure=nil;
        phase=@"waiting-native-rendering-resolution";
        rollback.committed=true;
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
        const int32_t actualWidth=original.screenWidth(nullptr), actualHeight=original.screenHeight(nullptr);
        if (actualWidth!=static_cast<int32_t>(config.width) || actualHeight!=static_cast<int32_t>(config.height)) {
            advancing=false;
            freezeDeltas();
            phase=@"waiting-native-rendering-resolution";
            if (resolutionReady || fn<double (*)()>(0x100a91d70)()-wallStart>15.0)
                fail([NSString stringWithFormat:@"Unity could not create the requested %ux%u render surface (actual %dx%d).",config.width,config.height,actualWidth,actualHeight]);
            return;
        }
        resolutionReady=true;
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
        if (!sceneValid()) { sceneAbandoned=true; fail(@"The MV resources changed while evaluating an offline frame."); }
    } catch (...) { fail(@"Unity failed to advance an offline MV frame."); }
}

extern "C" void SIFASMVLiveUpdate(void *value, const void *methodInfo) {
    if (!installed) return;
    if (!active) {
        try { observeDirector(value); } catch (...) { director=nullptr; observedOverlay=nullptr; finalCameraObserved=false; }
        original.liveUpdate(value,methodInfo); return;
    }
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
    if (!active || value!=members) { original.memberLateUpdate(value,methodInfo); return; }
    if (!advancing || tick==0) return;
    try { original.memberLateUpdate(value,methodInfo); }
    catch (...) { fail(@"The game's skirt safety correction failed during an offline physics tick."); }
}

extern "C" int32_t SIFASMVScreenWidth(const void *methodInfo) {
    /* The real engine surface owns these values. Never advertise a size that
     * Unity has not allocated; camera/postFX targets follow the actual size. */
    return original.screenWidth ? original.screenWidth(methodInfo) : 0;
}
extern "C" int32_t SIFASMVScreenHeight(const void *methodInfo) {
    return original.screenHeight ? original.screenHeight(methodInfo) : 0;
}

extern "C" void SIFASMVOverlayRender(void *overlay, void *source, void *destination, const void *methodInfo) {
    if (!installed) return;
    /* Preserve the game's original shared backbuffer pipeline. Normal MV
     * rendering has this effect disabled; pause/blur is outside this path. */
    original.overlayRender(overlay,source,destination,methodInfo);
    if (!active) { try { observeOverlay(overlay); } catch (...) { finalCameraObserved=false; } return; }
    if (overlay==sessionOverlay) fail(@"The MV pause or blur effect became active during export.");
}

extern "C" void SIFASMVCameraPostRender(void *camera, const void *methodInfo) {
    if (!installed) return;
    original.cameraPostRender(camera,methodInfo);
    if (![NSThread isMainThread]) {
        if (active) dispatch_async(dispatch_get_main_queue(), ^{
            if (active) fail(@"Unity dispatched the final render callback outside its main thread.");
        });
        return;
    }
    if (!active) {
        try {
            if (!director || !observedDirectorRoot || !alive(director)) return;
            void *manager=load<void *>(director,0x48);
            if (!alive(manager)) return;
            void *overlay=load<void *>(manager,0x58);
            if (!overlay) overlay=load<void *>(manager,0x48);
            if (alive(overlay) && load<void *>(overlay,0x48)==camera) {
                observeOverlay(overlay); finalCameraObserved=true;
            }
        } catch (...) { /* No export owns resources; readiness stays false. */ }
        return;
    }
    if (!sceneValid()) { fail(@"The MV scene or final camera changed before frame capture."); return; }
    if (camera!=overlayCamera || !advancing || captureIndex<0 || captured) return;
    void *previous=nullptr;
    bool restoreActive=false;
    try {
        phase=@"validate-final-camera-backbuffer";
        if (!resolutionReady || original.screenWidth(nullptr)!=static_cast<int32_t>(config.width) ||
            original.screenHeight(nullptr)!=static_cast<int32_t>(config.height) ||
            fn<bool (*)(void *,const void *)>(0x103930014)(sessionOverlay,nullptr) ||
            fn<void *(*)(void *,const void *)>(0x1039343a4)(overlayCamera,nullptr)) {
            fail(@"The final MV backbuffer changed or a pause/blur effect became active."); return;
        }
        const int32_t viewportWidth=fn<InstanceInt>(0x1039341f4)(overlayCamera,nullptr);
        const int32_t viewportHeight=fn<InstanceInt>(0x103934260)(overlayCamera,nullptr);
        if (viewportWidth<=0 || viewportHeight<=0 || viewportWidth>static_cast<int32_t>(config.width) ||
            viewportHeight>static_cast<int32_t>(config.height)) {
            fail(@"Unity returned an invalid final MV camera viewport."); return;
        }
        finalCameraObserved=true;
        completeJobs();
        previous=fn<StaticObject>(0x10395fac4)(nullptr);
        restoreActive=true;
        /* The final overlay camera has no active image effect. All original
         * main cameras/postFX and its overlay geometry have already rendered
         * into Unity's shared native backbuffer; UIKit is a separate layer. */
        fn<SetObject>(0x10395fac8)(nullptr,nullptr);
        phase=@"read-complete-game-backbuffer";
        fn<ReadPixels>(0x103970088)(readbackTexture,{0,0,static_cast<float>(config.width),static_cast<float>(config.height)},0,0,false,nullptr);
        fn<SetObject>(0x10395fac8)(previous,nullptr); restoreActive=false;
        const uint64_t needed=static_cast<uint64_t>(config.width)*config.height*4;
        const int64_t bytes=fn<int64_t (*)(void *,const void *)>(0x10396eea4)(readbackTexture,nullptr);
        const uint8_t *rgba=fn<const uint8_t *(*)(void *,int32_t,const void *)>(0x10396ee28)(readbackTexture,0,nullptr);
        if (!rgba || bytes<=0 || static_cast<uint64_t>(bytes)!=needed) { fail(@"Unity returned an incomplete final MV render."); return; }
        NSMutableData *data=[NSMutableData dataWithLength:static_cast<NSUInteger>(needed)];
        uint8_t *bgra=static_cast<uint8_t *>(data.mutableBytes);
        if (!data || !bgra) { fail(@"There is not enough memory for the final MV frame."); return; }
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
