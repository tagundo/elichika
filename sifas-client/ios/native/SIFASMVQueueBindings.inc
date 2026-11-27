// GL 3.12.0 queue bindings. All managed calls are made on Unity's main
// thread. The packaging profile pins the executable before patching.
struct QueuedMember {
    int32_t position, member, suit, view;
    uint64_t appearance;
};
struct QueuedGraphics {
    int32_t quality, resolution, flags, settingQuality, brightness, screenRatio;
};
struct QueuedSelection {
    int32_t liveMaster, stage, difficulty, deck;
    uint32_t count;
    QueuedMember members[12];
    QueuedGraphics graphics;
};
enum class QueueNavigationPhase { Idle, Leaving, Picker, Playing };
struct QueueNavigation {
    QueueNavigationPhase phase;
    QueuedSelection selection;
    uint32_t sourceScene, transition;
    int32_t sourceDirector;
    bool consumedAssetSelection, qualityApplied, settingApplied, assetFailure;
};
QueueNavigation queueNavigation{};
QueuedSelection queueLoadedSelection{};
int32_t queueLoadedDirector;
struct QueueObservedSelection {
    QueuedSelection selection;
    int64_t stateId;
    int32_t previousDirector;
    bool hasQuality, hasSetting, hasFormation;
};
QueueObservedSelection queueObserved{};
// The scene load whose LiveSettingVO, LiveQualitySettingVO or 3D member assets
// a queue navigation overrode, by StateObject.LiveMv UniqId (0 when the state
// was not readable then, which matches every load). The scene keeps those saved
// values even when the navigation fails or is cancelled before it confirms the
// load, so only a confirmed navigation (queueLoadedDirector) may describe that
// load. A confirmed navigation, or a later scene load observed without
// overrides, clears it.
struct QueueOverriddenLoad {
    bool pending;
    int64_t stateId;
    bool matches(int64_t current) const { return pending && (!stateId || stateId==current); }
};
QueueOverriddenLoad queueOverriddenLoad{};
void queueMarkOverriddenLoad(int64_t stateId) { queueOverriddenLoad={true,stateId}; }
uint64_t queueNavigationGeneration;
void (^queueNavigationCompletion)(NSString *);
struct QueueAssetScope {
    const QueuedSelection &selection;
    bool memberMapRead=false;
    bool suitMapRead=false;
    uint32_t memberMap=0;
    uint32_t suitMap=0;
    ~QueueAssetScope() { release(&suitMap); release(&memberMap); }
};
thread_local QueueAssetScope *queueAssetScope;

constexpr StaticClass queueDeckSceneClass{"LLAS.Scene.EntryPoint.LiveMvDeckSelectScene",0x1047fcc80,false};
constexpr StaticClass queueDeckRootClass{"LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot",0x1048704f0,false};
constexpr StaticClass queueMemberAssetClass{"LLAS.DM.ValueObject.LiveMember3DAssetVO",0x1047e5200,false};
constexpr StaticClass queueQualityClass{"LLAS.DM.ValueObject.LiveQualitySettingVO",0x1048538d0,false};
constexpr StaticClass queueLiveVOClass{"LiveMvVO",0x104854750,false};
constexpr StaticClass queueSettingClass{"LLAS.DM.ValueObject.LiveSettingVO",0x104853890,false};
constexpr StaticClass queueModelPathClass{"LLAS.DM.ValueObject.MemberModelPathVO",0x10484ca40,false};
constexpr StaticClass queueFacialPathClass{"LLAS.DM.ValueObject.MemberFacialPathVO",0x10484c9e0,false};
constexpr StaticClass queueFacialAnimationPathClass{"LLAS.DM.ValueObject.MemberFacialAnimationPathVO",0x10484c980,false};

bool queueOnUnityThread() {
    return [NSThread isMainThread] && thread_known && pthread_equal(pthread_self(),unity_thread);
}
bool queueReadyForBindings() {
    return queueOnUnityThread() && installed && runtime_ready && !active && !quarantined;
}
void queueLog(const char *format,...) __attribute__((format(printf,1,2)));
void queueLog(const char *format,...) {
    char text[320];
    va_list args;va_start(args,format);vsnprintf(text,sizeof(text),format,args);va_end(args);
    NSLog(@"SIFAS-MV queue: %s",text);
}
// The static profile has no Unity or IL2CPP runtime dependency: it verifies
// pinned code bytes. A saved queue may open from a menu after a cold start,
// before any LiveDirector.Update hook initialized it (Android 21.4 does the
// same from its queue pump). A mismatch is permanent, exactly as in Update.
bool queueEnsureRuntime() {
    if(runtime_ready)return true;
    if(runtime_rejected||!installed||!queueOnUnityThread())return false;
    if(init_runtime())return true;
    runtime_rejected=true;
    record_failure("This game client does not match the verified MV export interfaces");
    phase("unsupported MV interfaces");
    return false;
}
// System.Nullable<T> of a 4-byte T (Int32, LiveMvDeckType) in this IL2CPP
// build: the value is the low int32 and the HasValue byte is at +4, with three
// padding bytes. Nullable<LiveMvDeckType>.ctor at 0x102beedc0 is
// `mov w8,#1; strb w8,[x0,#4]; str w1,[x0]` and get_HasValue at 0x102beedd0
// is `ldrb w0,[x0,#4]`; the Int32 instantiation at 0x102bee988/0x102bee998 is
// identical, and GetMvLiveMember3DAssetVOs (0x101d9c7f4) spills its Nullable
// argument x1 to sp+8 and calls that getter on it. Android 21.4 reads the same
// layout (NullableInt{int32 value; uint8 has_value}). Returns the value, 0
// without a value and -1 for a HasValue byte that is neither 0 nor 1.
uint8_t queueNullableHasValue(uint64_t value) {
    return static_cast<uint8_t>(value>>32);
}
int32_t queueNullableValue(uint64_t value) {
    const uint8_t has=queueNullableHasValue(value);
    return has==1?static_cast<int32_t>(static_cast<uint32_t>(value)):has==0?0:-1;
}
uint64_t queueNullableMake(int32_t value) {
    return (static_cast<uint64_t>(1)<<32)|static_cast<uint32_t>(value);
}
void *queueUsageCell(uintptr_t address) {
    return *reinterpret_cast<void **>(address+slide);
}
void queueInitialize(uint32_t usage) {
    native<void (*)(uint32_t)>(0x101037c34)(usage);
}
void *queueCurrentState() {
    return native<void *(*)(const void *)>(0x101ae5080)(nullptr);
}
// found receives the number of matching live objects (UINT32_MAX when the
// search itself failed); only exactly one match is returned.
void *queueFindUniqueUnityObject(const StaticClass &klass, bool liveScene=false, uint32_t *found=nullptr) {
    if(found)*found=UINT32_MAX;
    void *type=managed_type(&klass);
    void *args[]={type};
    void *values=type?reference(m.find_objects,nullptr,args):nullptr;
    uint32_t count=length(values,16);
    if(count==UINT32_MAX)return nullptr;
    uint32_t arrayRoot=root(values);
    if(values&&!arrayRoot)return nullptr;
    void *selected=nullptr;
    uint32_t matches=0;
    for(uint32_t i=0;i<count;i++) {
        void *item=element(values,i);
        if(!alive(item))continue;
        if(liveScene&&(load<uint8_t>(item,f.scene_pre_final.offset)||load<uint8_t>(item,f.scene_post_final.offset)))continue;
        if(++matches==1)selected=item;
    }
    release(&arrayRoot);
    if(found)*found=matches;
    return matches==1?selected:nullptr;
}
bool queueReadLiveIdentity(QueuedSelection &selection, const char **missing=nullptr) {
    void *state=queueCurrentState();
    if(!state) { if(missing)*missing="State.Inst"; return false; }
    // StateObject.LiveMv, StateObject.Live, Live.LiveStage.
    void *liveMv=load<void *>(state,0xb0),*live=load<void *>(state,0xa8);
    void *difficulty=live?load<void *>(live,0x20):nullptr;
    if(missing)*missing=!liveMv?"StateObject.LiveMv":!live?"StateObject.Live":!difficulty?"Live.LiveStage":"value";
    if(!liveMv||!difficulty)return false;
    selection.liveMaster=load<int32_t>(liveMv,0x18);
    selection.stage=load<int32_t>(liveMv,0x24);
    selection.difficulty=load<int32_t>(difficulty,0x10);
    selection.deck=queueNullableValue(load<uint64_t>(liveMv,0x1c));
    return selection.liveMaster>0 && selection.stage>=0 &&
        selection.difficulty>0 && (selection.deck==1||selection.deck==2);
}
int64_t queueLiveStateId() {
    void *state=queueCurrentState();
    void *live=state?load<void *>(state,0xb0):nullptr;
    return live?load<int64_t>(live,0x10):0;
}
int32_t queueDirectorIdentity() {
    return director&&alive(director)?native<int32_t (*)(void *,const void *)>(0x103952b08)(director,nullptr):0;
}
bool queueSameLive(const QueuedSelection &left, const QueuedSelection &right) {
    return left.liveMaster==right.liveMaster && left.stage==right.stage && left.deck==right.deck;
}
bool queueIsQualityMode(int32_t value) {
    return value==10 || value==20 || value==30 || value==40;
}
bool queueReadQuality(void *object, QueuedGraphics &graphics) {
    if(!static_instance(object,&queueQualityClass)||load<uint8_t>(object,0x14))return false;
    graphics.quality=load<int32_t>(object,0x10);
    graphics.resolution=load<int32_t>(object,0x18);
    graphics.flags=0;
    for(uint32_t i=0;i<22;i++) {
        const auto setting=load<uint8_t>(object,0x1c+i);
        if(setting>1)return false;
        graphics.flags|=setting<<i;
    }
    return queueIsQualityMode(graphics.quality) && graphics.resolution>=0;
}
bool queueReadSetting(void *object, QueuedGraphics &graphics) {
    if(!static_instance(object,&queueSettingClass))return false;
    graphics.settingQuality=load<int32_t>(object,0x10);
    graphics.brightness=load<int32_t>(object,0x30);
    graphics.screenRatio=load<uint8_t>(object,0x34);
    return queueIsQualityMode(graphics.settingQuality) && graphics.screenRatio<=1;
}
bool queueApplyingSelection() {
    QueuedSelection current{};
    return queueNavigation.phase==QueueNavigationPhase::Playing &&
        queueReadLiveIdentity(current) && queueSameLive(current,queueNavigation.selection);
}
int32_t queueReadMemberView(int32_t memberId) {
    void *state=queueCurrentState();
    void *model=state?load<void *>(state,0x10):nullptr;
    void *membersById=model?native<void *(*)(void *,const void *)>(0x101e47a88)(model,nullptr):nullptr;
    if(!membersById)return 0;
    // The 3D asset VO constructor initializes this exact Dictionary<Int32,
    // UserMember>.TryGetValue specialization and uses it before the view flag.
    void *info=queueUsageCell(0x10589e760);
    if(!info)return 0;
    void *member=nullptr;
    if(!native<uint8_t (*)(void *,int32_t,void **,const void *)>(0x103212a44)(membersById,memberId,&member,info))return 1;
    return member?queueOriginals.queueViewStatus(member,nullptr):0;
}
bool queueReadAppearance(void *vo, uint64_t &appearance) {
    // The resolved model/facial paths include the view-status substitutions
    // and are a stronger postcondition than the member and suit IDs alone.
    const StaticClass *classes[]={&queueModelPathClass,&queueFacialPathClass,
        &queueFacialAnimationPathClass,&queueFacialAnimationPathClass};
    appearance=1469598103934665603ULL;
    const auto add=[&](uint16_t item){ appearance=(appearance^item)*1099511628211ULL; };
    for(size_t i=0;i<4;i++) {
        void *path=load<void *>(vo,0x30+i*8);
        if(!path) { if(!i)return false;add(0);continue; }
        if(!static_instance(path,classes[i]))return false;
        void *name=load<void *>(path,0x10);
        const int32_t count=e.string_length(name);
        if(count<0||count>2048||(!i&&!count))return false;
        const uint16_t *characters=e.string_chars(name);
        add(1);add(static_cast<uint16_t>(count));
        for(int32_t j=0;j<count;j++)add(characters[j]);
    }
    return true;
}
// Diagnostic text for the last queueReadMembers rejection (never a decision input).
char queueMemberFailure[96];
bool queueMembersRejected(const char *format,...) __attribute__((format(printf,1,2)));
bool queueMembersRejected(const char *format,...) {
    va_list args;va_start(args,format);vsnprintf(queueMemberFailure,sizeof(queueMemberFailure),format,args);va_end(args);
    return false;
}
bool queueReadMembers(void *array, QueuedSelection &selection, bool readView) {
    uint32_t count=length(array,12);
    if(!count||count==UINT32_MAX)return queueMembersRejected(array?"member count outside 1-12":"no member asset array");
    uint16_t used=0;
    for(uint32_t i=0;i<count;i++) {
        void *vo=element(array,i);
        if(!static_instance(vo,&queueMemberAssetClass))return queueMembersRejected("slot %u is not a member 3D asset",i);
        auto &slot=selection.members[i];
        slot.position=load<int32_t>(vo,0x28);
        slot.member=load<int32_t>(vo,0x10);
        // <SuitId> is a Nullable<Int32>: value at +0x50, HasValue at +0x54
        // (the factory stores Nullable<Int32>.ctor's result through the
        // setter at 0x101feeb00, `str x1,[x0,#0x50]`).
        const auto suit=load<uint64_t>(vo,0x50);
        if(slot.position<1 || slot.position>12 || slot.member<=0)
            return queueMembersRejected("slot %u position %d member %d",i,slot.position,slot.member);
        const uint8_t suitHasValue=queueNullableHasValue(suit);
        if(suitHasValue!=1)
            return suitHasValue ? queueMembersRejected("member %d suit HasValue byte %u",slot.member,suitHasValue) :
                queueMembersRejected("member %d has no suit id",slot.member);
        uint16_t bit=1u<<(slot.position-1);
        if(used&bit)return queueMembersRejected("position %d is used twice",slot.position);
        used|=bit;
        slot.suit=queueNullableValue(suit);
        if(slot.suit<0)return queueMembersRejected("member %d suit %d",slot.member,slot.suit);
        if(!queueReadAppearance(vo,slot.appearance))return queueMembersRejected("member %d model/facial asset paths",slot.member);
        if(readView) {
            slot.view=queueReadMemberView(slot.member);
            if(slot.view!=1 && slot.view!=2)return queueMembersRejected("member %d view status %d",slot.member,slot.view);
        }
    }
    selection.count=count;
    queueMemberFailure[0]=0;
    return true;
}
bool queueSameAssetSlots(const QueuedSelection &expected, void *array) {
    QueuedSelection actual{};
    if(!queueReadMembers(array,actual,false) || actual.count!=expected.count)return false;
    for(uint32_t i=0;i<actual.count;i++) {
        const auto &slot=actual.members[i];
        bool matched=false;
        for(uint32_t j=0;j<expected.count;j++) {
            const auto &wanted=expected.members[j];
            matched=matched||(slot.position==wanted.position && slot.member==wanted.member &&
                slot.suit==wanted.suit && slot.appearance==wanted.appearance);
        }
        if(!matched)return false;
    }
    return true;
}
bool queueSelectionInt(id value, int32_t min, int32_t &output) {
    if(![value isKindOfClass:NSNumber.class]||
       CFGetTypeID((__bridge CFTypeRef)value)==CFBooleanGetTypeID())return false;
    const double number=[value doubleValue];
    if(!isfinite(number)||number<min||number>INT32_MAX||floor(number)!=number)return false;
    output=static_cast<int32_t>(number);
    return true;
}
bool queueSelectionAppearance(id value, uint64_t &output) {
    if(![value isKindOfClass:NSString.class] || [value length]!=16)return false;
    output=0;
    for(NSUInteger i=0;i<16;i++) {
        const unichar c=[value characterAtIndex:i];
        if(c>='0'&&c<='9')output=(output<<4)|(c-'0');
        else if(c>='a'&&c<='f')output=(output<<4)|(c-'a'+10);
        else return false;
    }
    return true;
}
// legacySuit is set when a member carries suit_id 1: earlier builds decoded
// Nullable<Int32> backwards and saved the HasValue byte (always 1) as every
// member's suit id. No SIFAS suit has id 1, and the real suits of such an
// entry are lost, so it can never be restored and is rejected.
bool queueDecodeSelection(NSDictionary *input, QueuedSelection &selection, bool *legacySuit=nullptr) {
    if(legacySuit)*legacySuit=false;
    if(![input isKindOfClass:NSDictionary.class] ||
       !queueSelectionInt(input[@"live_master_id"],1,selection.liveMaster) ||
       !queueSelectionInt(input[@"stage_id"],0,selection.stage) ||
       !queueSelectionInt(input[@"difficulty_id"],1,selection.difficulty) ||
       !queueSelectionInt(input[@"deck_type"],1,selection.deck) || selection.deck>2)return false;
    NSDictionary *graphics=input[@"graphics"];
    auto &settings=selection.graphics;
    if(![graphics isKindOfClass:NSDictionary.class] ||
       !queueSelectionInt(graphics[@"quality"],1,settings.quality) || !queueIsQualityMode(settings.quality) ||
       !queueSelectionInt(graphics[@"resolution"],0,settings.resolution) ||
       !queueSelectionInt(graphics[@"flags"],0,settings.flags) || settings.flags>=(1<<22) ||
       !queueSelectionInt(graphics[@"setting_quality"],1,settings.settingQuality) || !queueIsQualityMode(settings.settingQuality) ||
       !queueSelectionInt(graphics[@"brightness"],INT32_MIN,settings.brightness) ||
       !queueSelectionInt(graphics[@"screen_ratio"],0,settings.screenRatio) || settings.screenRatio>1)return false;
    NSArray *members=input[@"members"];
    if(![members isKindOfClass:NSArray.class] || !members.count || members.count>12)return false;
    uint16_t used=0;
    for(id candidate in members) {
        NSDictionary *row=candidate;
        auto &slot=selection.members[selection.count];
        if(![row isKindOfClass:NSDictionary.class] ||
           !queueSelectionInt(row[@"position"],1,slot.position) || slot.position>12 ||
           !queueSelectionInt(row[@"member_id"],1,slot.member) ||
           !queueSelectionInt(row[@"suit_id"],0,slot.suit) ||
           !queueSelectionInt(row[@"view_status"],1,slot.view) || slot.view>2 ||
           !queueSelectionAppearance(row[@"appearance"],slot.appearance))return false;
        if(slot.suit==1) { if(legacySuit)*legacySuit=true; return false; }
        uint16_t bit=1u<<(slot.position-1);
        if(used&bit)return false;
        used|=bit;
        for(uint32_t i=0;i<selection.count;i++) {
            const auto &prior=selection.members[i];
            if(prior.member==slot.member && prior.view!=slot.view)return false;
        }
        selection.count++;
    }
    return true;
}
NSDictionary *queueEncodeSelection(const QueuedSelection &selection) {
    NSMutableArray *members=[NSMutableArray arrayWithCapacity:selection.count];
    for(uint32_t i=0;i<selection.count;i++) {
        const auto &slot=selection.members[i];
        [members addObject:@{@"position":@(slot.position),@"member_id":@(slot.member),
                             @"suit_id":@(slot.suit),@"view_status":@(slot.view),
                             @"appearance":[NSString stringWithFormat:@"%016llx",static_cast<unsigned long long>(slot.appearance)]}];
    }
    const auto &graphics=selection.graphics;
    return @{@"live_master_id":@(selection.liveMaster),@"stage_id":@(selection.stage),
             @"difficulty_id":@(selection.difficulty),@"deck_type":@(selection.deck),
             @"graphics":@{@"quality":@(graphics.quality),@"resolution":@(graphics.resolution),
                            @"flags":@(graphics.flags),@"setting_quality":@(graphics.settingQuality),
                            @"brightness":@(graphics.brightness),@"screen_ratio":@(graphics.screenRatio)},
             @"members":[members copy]};
}
bool queueGetDeckMaps(QueueAssetScope &scope) {
    // Exact IL2CPP class/MethodInfo cells and metadata-usage list from
    // LivePartnerState's existing Dictionary<Int32,Int32> constructor.
    queueInitialize(42467);
    void *klass=queueUsageCell(0x105868670),*ctor=queueUsageCell(0x1058df3b0);
    void *add=queueUsageCell(0x1058df3c0);
    if(!klass||!ctor||!add)return false;
    auto objectNew=native<void *(*)(void *)>(0x101014950);
    auto newMap=native<void (*)(void *,int32_t,const void *)>(0x1031f78e0);
    auto insert=native<void (*)(void *,int32_t,int32_t,const void *)>(0x1031f8354);
    void *memberMap=objectNew(klass);
    if(!(scope.memberMap=root(memberMap)))return false;
    newMap(memberMap,scope.selection.count,ctor);
    void *suitMap=objectNew(klass);
    if(!(scope.suitMap=root(suitMap)))return false;
    newMap(suitMap,scope.selection.count,ctor);
    for(uint32_t i=0;i<scope.selection.count;i++) {
        const auto &slot=scope.selection.members[i];
        insert(memberMap,slot.position,slot.member,add);
        insert(suitMap,slot.position,slot.suit,add);
    }
    return true;
}
void *queueSceneManager() {
    queueInitialize(41973); // The original MV picker action initializes these cells.
    void *klass=queueUsageCell(0x105869110),*info=queueUsageCell(0x1058f1538);
    if(!klass||!info)return nullptr;
    if((load<uint16_t>(klass,0x126)&(1u<<9)) && !load<uint32_t>(klass,0xd8))
        native<void (*)(void *)>(0x10102e358)(klass);
    return native<void *(*)(const void *)>(0x1035bc074)(info);
}
void *queueDeckTransition(const QueuedSelection &selected) {
    queueInitialize(41973);
    void *klass=queueUsageCell(0x105882970);
    if(!klass)return nullptr;
    void *transition=native<void *(*)(void *)>(0x101014950)(klass);
    uint32_t retained=root(transition);
    if(!retained)return nullptr;
    try {
        native<void (*)(void *,int32_t,int32_t,const void *)>(0x101378f64)(
            transition,selected.liveMaster,selected.difficulty,nullptr);
    } catch (...) { release(&retained); throw; }
    queueNavigation.transition=retained;
    return transition;
}
bool queueBeginningPicker(void *deckScene) {
    // Scene applies exactly the requested item once its ordinary transition is complete.
    void *picker=load<void *>(deckScene,0x40);
    if(!alive(picker) || !static_instance(picker,&queueDeckRootClass))return false;
    void *vo=load<void *>(picker,0x98);
    if(!vo||load<int32_t>(vo,0x10)!=queueNavigation.selection.liveMaster)return false;
    if(load<uint8_t>(vo,0x28)||load<uint8_t>(vo,0x29))return false;
    void *tabGroup=load<void *>(picker,0x20);
    void *tabs=tabGroup?load<void *>(tabGroup,0x58):nullptr;
    void *stageVO=load<void *>(vo,0x18);
    void *stages=stageVO?load<void *>(stageVO,0x10):nullptr;
    uint32_t countTabs=length(tabs,16),countStages=length(stages,64);
    if(countTabs==UINT32_MAX||countStages==UINT32_MAX)return false;
    int32_t tabIndex=-1,stageIndex=-1;
    for(uint32_t i=0;i<countTabs;i++) {
        void *tab=element(tabs,i);
        if(tab&&load<int32_t>(tab,0x10)==queueNavigation.selection.liveMaster&&
           queueNullableValue(load<uint64_t>(tab,0x14))==queueNavigation.selection.deck)tabIndex=i;
    }
    for(uint32_t i=0;i<countStages;i++) {
        void *stage=element(stages,i);
        if(stage&&!load<uint8_t>(stage,0x20)&&load<int32_t>(stage,0x10)==queueNavigation.selection.stage)stageIndex=i;
    }
    if(tabIndex<0||stageIndex<0)return false;
    native<void (*)(void *,int32_t,const void *)>(0x1018c02a0)(tabGroup,tabIndex,nullptr);
    native<void (*)(void *,int32_t,const void *)>(0x10157cc48)(picker,stageIndex,nullptr);
    void *selectedTab=native<void *(*)(void *,const void *)>(0x1018bfd84)(tabGroup,nullptr);
    void *selectedStage=load<void *>(picker,0x78);
    if(selectedTab!=element(tabs,tabIndex)||selectedStage!=element(stages,stageIndex))return false;
    // The original picker coroutine prefetches these models, then dispatches
    // the regular Play RPC and normal LiveMvScene coroutine via its callback.
    void *routine=native<void *(*)(void *,const void *)>(0x10157cbb4)(picker,nullptr);
    if(!routine)return false;
    queueNavigation.phase=QueueNavigationPhase::Playing;
    return native<void *(*)(void *,void *,const void *)>(0x103950828)(picker,routine,nullptr)!=nullptr;
}
void queueCompleteNavigation(NSString *error) {
    ++queueNavigationGeneration;
    auto completion=queueNavigationCompletion;
    queueNavigationCompletion=nil;
    release(&queueNavigation.sourceScene);
    release(&queueNavigation.transition);
    queueNavigation={};
    if(completion)completion(error);
}
void queuePollNavigation(uint64_t generation, unsigned remaining) {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,250*NSEC_PER_MSEC),dispatch_get_main_queue(),^{
        if(generation!=queueNavigationGeneration || queueNavigation.phase==QueueNavigationPhase::Idle)return;
        if(!remaining) { queueCompleteNavigation(@"Timed out while preparing the registered MV."); return; }
        try {
            void *manager=queueSceneManager();
            if(manager && !native<uint8_t (*)(void *,const void *)>(0x10162d11c)(manager,nullptr)) {
                if(queueNavigation.phase==QueueNavigationPhase::Picker ||
                   queueNavigation.phase==QueueNavigationPhase::Leaving) {
                    void *picker=queueFindUniqueUnityObject(queueDeckSceneClass);
                    if(picker) {
                        void *data=load<void *>(picker,0x48);
                        if(data==e.gchandle_get_target(queueNavigation.transition)) {
                            if(!queueBeginningPicker(picker))queueCompleteNavigation(@"The registered MV deck or stage is unavailable.");
                        }
                    }
                } else if(queueNavigation.assetFailure) {
                    queueCompleteNavigation(@"The registered MV formation could not be restored.");
                } else if(queueNavigation.consumedAssetSelection && queueNavigation.qualityApplied &&
                          queueNavigation.settingApplied && cached.ready && director && alive(director)) {
                    void *scene=queueFindUniqueUnityObject(*f.scene_pre_final.owner,true);
                    QueuedSelection observed{};
                    const auto &expected=queueNavigation.selection;
                    if(scene && scene!=e.gchandle_get_target(queueNavigation.sourceScene) &&
                       queueReadLiveIdentity(observed) &&
                       native<int32_t (*)(void *,const void *)>(0x103952b08)(director,nullptr)!=queueNavigation.sourceDirector &&
                       queueSameLive(observed,expected)) {
                        queueLoadedSelection=expected;
                        queueLoadedDirector=native<int32_t (*)(void *,const void *)>(0x103952b08)(director,nullptr);
                        // This director now names the overridden load exactly.
                        queueOverriddenLoad={};
                        queueCompleteNavigation(nil);
                    }
                }
            }
        } catch (...) { queueCompleteNavigation(@"The game rejected the registered MV transition."); }
        if(generation==queueNavigationGeneration)queuePollNavigation(generation,remaining-1);
    });
}

// Registration read for "Add to export queue". The registered selection names
// the loaded MV and what its scene load consumed: song/stage/difficulty/deck,
// the LiveSettingVO and LiveQualitySettingVO values and the member formation.
// Load-time observation (the exact GetLiveMvVO, GetLiveQualitySettingVO and 3D
// asset call sites above) stays authoritative when it belongs to the current
// director. When it is incomplete, because the scene was entered through a path
// those call sites do not see or a later load replaced it, each missing part is
// read from current game state through bindings this file already uses, as
// Android 21.4 reads its snapshot from live objects:
// - quality: LiveCoreCameraManager.liveQualitySetting of the live director
//   (static profile field camera_quality; the export already owns that object);
// - setting: a fresh LiveMvDM.GetLiveMvVO() through its original trampoline;
// - formation: Live3DDM.GetMvLiveMember3DAssetVOs(live, deck) through its
//   original trampoline, the same factory the 3D scene load calls.
// Every value passes the validators the observed path uses, and the result must
// decode exactly as SIFASMVBindingsQueueOpen will decode it later.
// The live parts are what the game would load now, not values read back from
// the scene on screen, so they are used only to register a new entry, never to
// decide that the loaded scene already is a queued entry (allowLive below),
// and never for a load a queue navigation overrode without confirming it
// (queueOverriddenLoad).
struct QueueSelectionRead {
    QueuedSelection selection{};
    const char *check=nullptr;
    char detail[224]{};
    bool transient=false;
};
struct QueueRooted {
    uint32_t handle=0;
    explicit QueueRooted(void *object) : handle(root(object)) {}
    ~QueueRooted() { release(&handle); }
    QueueRooted(const QueueRooted &)=delete;
    QueueRooted &operator=(const QueueRooted &)=delete;
};
bool queueRejected(QueueSelectionRead &read,const char *check,bool transient,const char *format,...) __attribute__((format(printf,4,5)));
bool queueRejected(QueueSelectionRead &read,const char *check,bool transient,const char *format,...) {
    read.check=check;read.transient=transient;
    va_list args;va_start(args,format);vsnprintf(read.detail,sizeof(read.detail),format,args);va_end(args);
    return false;
}
bool queueReadCurrentQuality(QueueSelectionRead &read,QueuedGraphics &graphics) {
    void *manager=reference(m.camera_manager,director);
    void *quality=manager&&field_object(manager,f.camera_quality)?load<void *>(manager,f.camera_quality.offset):nullptr;
    QueuedGraphics current=graphics;
    if(queueReadQuality(quality,current)) {
        graphics.quality=current.quality;graphics.resolution=current.resolution;graphics.flags=current.flags;
        return true;
    }
    if(!static_instance(quality,&queueQualityClass))
        return queueRejected(read,"graphics.quality",false,"LiveCoreCameraManager.liveQualitySetting is %s",
            quality?"not a LiveQualitySettingVO":"missing");
    return queueRejected(read,"graphics.quality",false,"quality mode %d, movie flag %u, resolution %d, or a feature flag above 1",
        load<int32_t>(quality,0x10),load<uint8_t>(quality,0x14),load<int32_t>(quality,0x18));
}
bool queueReadCurrentSetting(QueueSelectionRead &read,QueuedGraphics &graphics) {
    if(!queueOriginals.queueLiveVO)return queueRejected(read,"graphics.setting",false,"%s","LiveMvDM.GetLiveMvVO is unavailable");
    void *liveVO=queueOriginals.queueLiveVO(nullptr);
    QueueRooted retained(liveVO);
    if(!liveVO||!retained.handle||!static_instance(liveVO,&queueLiveVOClass))
        return queueRejected(read,"graphics.setting",false,"LiveMvDM.GetLiveMvVO returned %s",liveVO?"another type":"null");
    void *setting=load<void *>(liveVO,0x18);
    QueuedGraphics current=graphics;
    if(queueReadSetting(setting,current)) {
        graphics.settingQuality=current.settingQuality;graphics.brightness=current.brightness;graphics.screenRatio=current.screenRatio;
        return true;
    }
    if(!static_instance(setting,&queueSettingClass))
        return queueRejected(read,"graphics.setting",false,"LiveMvVO setting is %s",setting?"not a LiveSettingVO":"missing");
    return queueRejected(read,"graphics.setting",false,"setting quality mode %d, screen ratio %u",
        load<int32_t>(setting,0x10),load<uint8_t>(setting,0x34));
}
bool queueReadCurrentFormation(QueueSelectionRead &read,const QueuedSelection &live,QueuedSelection &selection) {
    if(!queueOriginals.queueMemberAssets)
        return queueRejected(read,"formation.members",false,"%s","Live3DDM.GetMvLiveMember3DAssetVOs is unavailable");
    // Nullable<LiveMvDeckType> exactly as the scene load passes it in x1 and
    // queueNullableValue decodes it: the value in the low 32 bits, HasValue=1
    // in the byte above it, zero padding.
    void *assets=queueOriginals.queueMemberAssets(live.liveMaster,queueNullableMake(live.deck),nullptr);
    QueueRooted retained(assets);
    if(!assets||!retained.handle)
        return queueRejected(read,"formation.members",false,"GetMvLiveMember3DAssetVOs(%d, deck %d) returned null",live.liveMaster,live.deck);
    QueuedSelection formation{};
    if(!queueReadMembers(assets,formation,true))return queueRejected(read,"formation.members",false,"%s",queueMemberFailure);
    selection.count=formation.count;
    std::memcpy(selection.members,formation.members,sizeof(selection.members));
    return true;
}
// allowLive: false accepts only a selection the scene load itself confirmed
// (source=queue-opened by a confirmed queue navigation, or source=observed);
// true also reads the missing parts from live game state (registration only).
bool queueReadSelection(QueueSelectionRead &read, bool allowLive) {
    if(![NSThread isMainThread])return queueRejected(read,"thread.main",false,"%s","called off the main thread");
    if(!installed)return queueRejected(read,"bindings.installed",false,"%s","the offline export shims are not installed");
    if(!thread_known)return queueRejected(read,"thread.unity-unknown",true,"%s","no Unity frame has reached the export hooks yet");
    if(!pthread_equal(pthread_self(),unity_thread))
        return queueRejected(read,"thread.unity",false,"%s","this main thread is not the Unity thread seen by the hooks");
    if(!queueEnsureRuntime()) {
        char failure[sizeof(cached.failure)];
        pthread_mutex_lock(&guard);std::memcpy(failure,cached.failure,sizeof(failure));pthread_mutex_unlock(&guard);
        failure[sizeof(failure)-1]=0;
        return queueRejected(read,"runtime.rejected",false,"%s",failure[0]?failure:"static profile verification failed");
    }
    if(quarantined)return queueRejected(read,"export.quarantined",false,"%s","a previous export could not restore its MV state");
    if(active)return queueRejected(read,"export.active",false,"%s","an MV export owns the scene");
    if(queueNavigation.phase!=QueueNavigationPhase::Idle)
        return queueRejected(read,"navigation.busy",true,"queue navigation phase %d",static_cast<int>(queueNavigation.phase));
    if(!director||!observed_director_root||e.gchandle_get_target(observed_director_root)!=director||!alive(director)) {
        // Worth waiting for only while an MV scene is loading its director.
        uint32_t scenes=0;
        queueFindUniqueUnityObject(*f.scene_pre_final.owner,true,&scenes);
        return queueRejected(read,"director.live",scenes&&scenes!=UINT32_MAX,
            "no live 3D MV director has run its Update (live LiveMvScene objects: %d)",scenes==UINT32_MAX?-1:static_cast<int>(scenes));
    }
    if(!cached.ready) {
        void *manager=reference(m.camera_manager,director);
        void *final=manager?reference(m.final_overlay,manager):nullptr;
        void *machine=reference(m.music_machine,director);
        if(!observed_overlay_root||!overlay)
            return queueRejected(read,"cached.ready:final-camera",true,"%s","the final MV overlay camera has not rendered to the screen");
        if(overlay!=final)
            return queueRejected(read,"cached.ready:final-camera",true,"%s","the observed final overlay is not the director's current one");
        if(!machine||!alive(machine)||load<uint8_t>(machine,f.loading.offset))
            return queueRejected(read,"cached.ready:music-loading",true,"%s","the MV music machine is missing or loading");
        AmvGameStatus song{};AmvAudioSelection audio{};
        const bool waveform=audio_selection(&song,&audio);
        return queueRejected(read,"cached.ready:song",true,"length %d ms, cue sheet %s, cue %s, waveform %s",
            cached.music_length_ms,cached.cue_sheet[0]?"read":"missing",cached.cue_name[0]?"read":"missing",
            waveform?"read":"unreadable");
    }
    uint32_t scenes=0;
    if(!queueFindUniqueUnityObject(*f.scene_pre_final.owner,true,&scenes)) {
        if(scenes==UINT32_MAX)return queueRejected(read,"scene.unique",true,"%s","the LiveMvScene search failed");
        return queueRejected(read,"scene.unique",true,"%u live LiveMvScene objects",scenes);
    }
    QueuedSelection live{};
    const char *missing="value";
    if(!queueReadLiveIdentity(live,&missing))
        return queueRejected(read,"state.live-identity",false,"%s missing or invalid (live %d, stage %d, difficulty %d, deck %d)",
            missing,live.liveMaster,live.stage,live.difficulty,live.deck);
    const int32_t identity=queueDirectorIdentity();
    if(!identity)return queueRejected(read,"director.identity",true,"%s","the director has no instance id");
    if(identity==queueLoadedDirector&&queueSameLive(live,queueLoadedSelection)) {
        read.selection=queueLoadedSelection;
        snprintf(read.detail,sizeof(read.detail),"source=queue-opened");
        return true;
    }
    const int64_t stateId=queueLiveStateId();
    // A queue navigation wrote saved values into this load's VOs and then
    // failed, timed out or was cancelled before it confirmed the scene. Neither
    // the stale observation nor live state describes what is on screen.
    if(queueOverriddenLoad.matches(stateId))
        return queueRejected(read,"navigation.override-unconfirmed",false,
            "the export queue overrode this MV load (state %lld) and did not confirm it",static_cast<long long>(stateId));
    const bool observedLoad=identity!=queueObserved.previousDirector &&
        stateId==queueObserved.stateId && queueSameLive(live,queueObserved.selection);
    if(observedLoad&&queueObserved.hasSetting&&queueObserved.hasQuality&&queueObserved.hasFormation) {
        queueLoadedSelection=queueObserved.selection;
        queueLoadedDirector=identity;
        read.selection=queueLoadedSelection;
        snprintf(read.detail,sizeof(read.detail),"source=observed");
        return true;
    }
    if(!allowLive)
        return queueRejected(read,"selection.unconfirmed",false,
            "the scene load was not fully observed (load observation %s; setting %d, quality %d, formation %d)",
            observedLoad?"partial":(queueObserved.stateId?"belongs to another load":"absent"),
            observedLoad&&queueObserved.hasSetting,observedLoad&&queueObserved.hasQuality,observedLoad&&queueObserved.hasFormation);
    const bool useSetting=observedLoad&&queueObserved.hasSetting;
    const bool useQuality=observedLoad&&queueObserved.hasQuality;
    const bool useFormation=observedLoad&&queueObserved.hasFormation;
    QueuedSelection selection=live;
    auto &graphics=selection.graphics;
    const auto &observed=queueObserved.selection.graphics;
    if(useSetting) {
        graphics.settingQuality=observed.settingQuality;graphics.brightness=observed.brightness;graphics.screenRatio=observed.screenRatio;
    } else if(!queueReadCurrentSetting(read,graphics))return false;
    if(useQuality) {
        graphics.quality=observed.quality;graphics.resolution=observed.resolution;graphics.flags=observed.flags;
    } else if(!queueReadCurrentQuality(read,graphics))return false;
    if(useFormation) {
        selection.count=queueObserved.selection.count;
        std::memcpy(selection.members,queueObserved.selection.members,sizeof(selection.members));
    } else if(!queueReadCurrentFormation(read,live,selection))return false;
    read.selection=selection;
    snprintf(read.detail,sizeof(read.detail),"source setting=%s quality=%s formation=%s; load observation %s",
        useSetting?"observed":"live",useQuality?"observed":"live",useFormation?"observed":"live",
        observedLoad?"partial":(queueObserved.stateId?"belongs to another load":"absent"));
    return true;
}
