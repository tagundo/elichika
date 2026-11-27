// Simulator-only regression: run the real menu action after its alert has
// dismissed. No Unity, native game bindings, audio preparation or MP4 is run.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import "ElichikaMVEncoder.h"
#import "SIFASMVExportSession.h"
#import "SIFASMVExportBindings.h"
#import "SIFASMVExportFOV.hpp"
#import "SIFASMVStandaloneAdapter.h"
#include <cstdio>
#include <cstdlib>

using ActionHandler=void (^)(UIAlertAction *);
using ActionFactory=UIAlertAction *(*)(id,SEL,NSString *,UIAlertActionStyle,ActionHandler);
static ActionFactory originalActionFactory;
static ActionHandler productionHandler;
static __weak UIAlertController *releasedAlert;
static NSMutableDictionary *checks;
static BOOL finished=NO;
static NSUInteger nativeStarts=0;
static BOOL probingGroup=NO;
static NSDictionary *openedSelection, *appliedFOV;
static NSMutableArray<NSString *> *renderRequests;
static NSUInteger fovRestores=0, navigationCancels=0;
static void (^navigationReady)(NSString *);
static void (^combinationStarted)(void);
static BOOL holdNavigation=NO;
static BOOL simulateMac=NO, allowMacRenderer=NO, simulateHiddenGame=NO, mockMacRenderActive=NO;
static NSUInteger macRenderBegins=0, macRenderEnds=0;
static NSArray<NSString *> *groupOrder, *stageOrder;
static NSArray<NSDictionary *> *ordinaryEntries;
static NSURL *existingOutput;
// "Combine into MP4s" with several groups: single clips render as ordinary
// queue entries, groups of two or more through the combined path.
static BOOL groupedRun=NO;
static NSString *groupedFourth=@"6C0F1B0E-2D4A-4F51-9C3B-7A1E5D2B8F44";
static NSUInteger groupedRenderBegins=0, groupedRenderEnds=0;

@interface ELMVExportCoordinator : NSObject
+ (instancetype)shared;
- (BOOL)writeQueue:(NSArray<NSDictionary *> *)entries;
- (void)startCombinedQueue:(NSArray<NSString *> *)identifiers;
- (void)startCombinedGroups:(NSArray<NSArray<NSString *> *> *)groups;
- (void)retryCombinedQueueEntry:(NSString *)identifier;
- (void)finishQueueEntry:(NSString *)phase message:(NSString *)message output:(NSURL *)output safe:(BOOL)safe;
- (NSArray<NSDictionary *> *)queueEntries;
- (NSArray<NSURL *> *)queuedOutputs;
@end

typedef void (^ProbeCombinationCompletion)(NSURL *, NSError *);
@interface MVMenuProbeCombination : NSObject
@property(nonatomic,copy) NSArray<NSURL *> *inputs;
@property(nonatomic,strong) NSURL *destination;
@property(nonatomic,strong) dispatch_queue_t callbackQueue;
@property(nonatomic,copy) ProbeCombinationCompletion completion;
@property(nonatomic) BOOL cancelled;
- (void)complete:(NSURL *)output problem:(NSError *)problem;
- (void)cancel;
@end

static MVMenuProbeCombination *activeCombination;
static NSError *ProbeProblem(NSString *reason) {
    return [NSError errorWithDomain:@"MVMenuProbe" code:2 userInfo:@{NSLocalizedDescriptionKey:reason}];
}
@implementation MVMenuProbeCombination
- (void)complete:(NSURL *)output problem:(NSError *)problem {
    ProbeCombinationCompletion completion=self.completion;
    self.completion=nil;
    if (completion) dispatch_async(self.callbackQueue, ^{ completion(output,problem); });
}
- (void)cancel {
    self.cancelled=YES;
    [self complete:nil problem:ProbeProblem(@"Mock assembly cancelled")];
}
@end

static ELMVMP4Combination *CaptureCombination(id type,SEL selector,NSArray<NSURL *> *sources,NSURL *output,
        dispatch_queue_t worker,dispatch_queue_t callback,ProbeCombinationCompletion completion) {
    (void)type; (void)selector; (void)worker;
    activeCombination=[MVMenuProbeCombination new];
    activeCombination.inputs=[sources copy];
    activeCombination.destination=output;
    activeCombination.callbackQueue=callback;
    activeCombination.completion=completion;
    if (combinationStarted) dispatch_async(dispatch_get_main_queue(),combinationStarted);
    return (ELMVMP4Combination *)(id)activeCombination;
}

// Link only these test bindings, never SIFASMVExportBindings/Bootstrap.mm.
NSDictionary *SIFASMVBindingsStatus(void) { return @{@"installed":@(probingGroup),@"liveDirectorObserved":@(probingGroup)}; }
NSDictionary *SIFASMVBindingsSongSnapshot(void) { return @{}; }
NSDictionary *SIFASMVBindingsAudioSelection(void) { return @{}; }
NSDictionary *SIFASMVBindingsQueueSelection(void) { return openedSelection; }
NSDictionary *SIFASMVBindingsQueueSelectionChecked(NSString **check,NSString **detail,BOOL *transient) {
    if (check) *check=openedSelection ? nil : @"director.live";
    if (detail) *detail=@"menu probe test binding";
    if (transient) *transient=NO;
    return openedSelection;
}
BOOL SIFASMVBindingsQueueOpen(NSDictionary *selection,void (^completion)(NSString *error)) {
    if (!probingGroup) return NO;
    openedSelection=selection;
    if (holdNavigation) navigationReady=[completion copy];
    else completion(nil);
    return YES;
}
// Every fixture selection decodes; the legacy-suit rule lives in the real
// bindings, which this probe never links.
NSString *SIFASMVBindingsQueueSelectionDefect(NSDictionary *selection) { (void)selection; return nil; }
void SIFASMVBindingsQueueCancelNavigation(void) { ++navigationCancels; }
BOOL SIFASMVStandaloneRunOnMac(void) { return simulateMac; }
extern "C" BOOL SIFASMVProbeRealShowGame(void);
BOOL SIFASMVStandaloneShowGame(void) { return !simulateHiddenGame && SIFASMVProbeRealShowGame(); }
BOOL SIFASMVBindingsBeginMacBackgroundRender(void) {
    ++macRenderBegins;
    if (!simulateMac || !allowMacRenderer || mockMacRenderActive) return NO;
    mockMacRenderActive=YES;
    return YES;
}
void SIFASMVBindingsEndMacBackgroundRender(void) {
    mockMacRenderActive=NO;
    ++macRenderEnds;
}
BOOL SIFASMVBindingsMacBackgroundRenderFallbackActive(void) { return NO; }
NSDictionary *SIFASMVExportCaptureFOV(void) {
    return appliedFOV ?: @{@"min":@0.75,@"max":@1};
}
SIFASMVExportFOVOverride *SIFASMVExportApplyFOV(NSDictionary *bounds, NSString **error) {
    if (probingGroup && !appliedFOV && SIFASMVExportValidFOV(bounds)) {
        appliedFOV=[bounds copy];
        return (SIFASMVExportFOVOverride *)(id)appliedFOV;
    }
    if (error) *error=@"Invalid fixture FOV";
    return nil;
}
BOOL SIFASMVExportRestoreFOV(SIFASMVExportFOVOverride *token) {
    if (!appliedFOV || (id)token!=appliedFOV) return NO;
    appliedFOV=nil;
    ++fovRestores;
    return YES;
}
BOOL SIFASMVBindingsBegin(SIFASMVBindingConfiguration configuration,SIFASMVBindingCallbacks callbacks,NSError **error) {
    (void)configuration; (void)callbacks; ++nativeStarts;
    if (error) *error=[NSError errorWithDomain:@"MVMenuProbe" code:1 userInfo:@{NSLocalizedDescriptionKey:@"This UI probe has no game renderer."}];
    return NO;
}
void SIFASMVBindingsEnd(void) {}

static void Finish(BOOL passed,NSString *reason) {
    if (finished) return; finished=YES;
    NSMutableDictionary *report=[checks mutableCopy] ?: [NSMutableDictionary new];
    report[@"status"]=passed?@"PASS_UIKIT_STANDALONE_MENU_REGRESSION":@"FAIL_UIKIT_STANDALONE_MENU_REGRESSION";
    report[@"reason"]=reason ?: @""; report[@"actual_uikit_simulator"]=@YES;
    report[@"actual_playcover"]=@NO; report[@"actual_game_rendering"]=@NO; report[@"mp4_encoding"]=@NO;
    report[@"native_export_starts"]=@(nativeStarts);
    NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL];
    NSString *path=NSProcessInfo.processInfo.environment[@"MV_MENU_PROBE_RESULT"] ?: [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/mv-menu-result.json"];
    [NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:NULL];
    BOOL written=[json writeToFile:path options:NSDataWritingAtomic error:NULL];
    fprintf(stdout,"MV_MENU_PROBE_RESULT %s\n",[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String); fflush(stdout);
    exit(passed && written?0:1);
}
static UIAlertAction *CaptureAction(id type,SEL selector,NSString *title,UIAlertActionStyle style,ActionHandler handler) {
    if ([title isEqualToString:@"MP4 export"]) productionHandler=[handler copy];
    return originalActionFactory(type,selector,title,style,handler);
}
static UIView *FindPanel(UIView *view) {
    if ([view isKindOfClass:NSClassFromString(@"SIFASMVStandalonePanel")]) return view;
    for (UIView *child in view.subviews) { UIView *found=FindPanel(child); if (found) return found; }
    return nil;
}
static NSURL *QueueFixtureURL(void) {
    NSURL *support=[NSFileManager.defaultManager URLForDirectory:NSApplicationSupportDirectory inDomain:NSUserDomainMask
                                               appropriateForURL:nil create:YES error:NULL];
    return [support URLByAppendingPathComponent:@"Elichika-MV-Export-Queue.json"];
}
static NSDictionary *QueueEntry(NSString *identifier, NSNumber *minimum, NSNumber *maximum) {
    return @{@"id":identifier,@"selection":@{@"live_master_id":@15001,@"stage_id":@42},
             @"title":@"Fixture MV",@"width":@1920,@"height":@1080,@"fps":@60,@"codec":@"h264",
             @"bitrate":@12000000,@"fov":@{@"min":minimum,@"max":maximum},@"phase":@"waiting"};
}
static UIButton *FindButton(UIView *view, NSString *action, NSString *identifier, id target) {
    if ([view isKindOfClass:UIButton.class]) {
        UIButton *button=(UIButton *)view;
        if ((!identifier || [button.accessibilityIdentifier isEqual:identifier]) &&
            [[button actionsForTarget:target forControlEvent:UIControlEventTouchUpInside] containsObject:action]) return button;
    }
    for (UIView *child in view.subviews) {
        UIButton *found=FindButton(child,action,identifier,target);
        if (found) return found;
    }
    return nil;
}
static NSDictionary *SavedGroup(void) {
    NSData *data=[NSData dataWithContentsOfURL:QueueFixtureURL()];
    NSArray *entries=[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL][@"entries"];
    if (entries.count!=ordinaryEntries.count+1 ||
        ![[entries subarrayWithRange:NSMakeRange(0,ordinaryEntries.count)] isEqualToArray:ordinaryEntries]) return nil;
    NSDictionary *group=entries.lastObject;
    return [group[@"combined_sources"] isEqual:groupOrder] ? group : nil;
}
static BOOL WriteMarker(NSString *marker,NSURL *url) {
    return [NSFileManager.defaultManager createDirectoryAtURL:url.URLByDeletingLastPathComponent
        withIntermediateDirectories:YES attributes:nil error:NULL] &&
        [marker writeToURL:url atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}
static NSString *ReadMarker(NSURL *url) {
    return [NSString stringWithContentsOfURL:url encoding:NSUTF8StringEncoding error:NULL];
}
static void SimulateBackground(void) {
    [NSNotificationCenter.defaultCenter postNotificationName:UIApplicationDidEnterBackgroundNotification object:nil];
}
static NSURL *ProbeExports(void) {
    NSURL *documents=[NSFileManager.defaultManager URLForDirectory:NSDocumentDirectory inDomain:NSUserDomainMask
        appropriateForURL:nil create:YES error:NULL];
    return [documents URLByAppendingPathComponent:@"exports" isDirectory:YES];
}
static NSURL *SingleOutput(NSString *identifier) {
    return [[ProbeExports() URLByAppendingPathComponent:[@"MV-" stringByAppendingString:identifier] isDirectory:YES]
        URLByAppendingPathComponent:[NSString stringWithFormat:@"MV-15001-%@.mp4",identifier]];
}
static void CaptureRequestedClip(ELMVExportCoordinator *coordinator,SEL selector,NSUInteger width,NSUInteger height,
        int32_t fps,NSString *codec,NSUInteger bitrate,NSDictionary *entry) {
    (void)selector;
    NSNumber *stage=entry[@"selection"][@"stage_id"];
    if (groupedRun) {
        if (!stage || ![entry[@"selection"] isEqual:openedSelection] || ![entry[@"fov"] isEqual:appliedFOV]) {
            Finish(NO,@"A grouped MP4 clip did not use its own saved selection and FOV."); return;
        }
        [renderRequests addObject:stage.stringValue];
        NSURL *directory=[coordinator valueForKey:@"combinedDirectory"];
        NSURL *clip=directory ? [[directory URLByAppendingPathComponent:[NSString stringWithFormat:@"Clip-%lu",
            (unsigned long)[[coordinator valueForKey:@"combinedClips"] count]+1] isDirectory:YES]
            URLByAppendingPathComponent:@"Clip.mp4"] : SingleOutput(entry[@"id"]);
        if (!WriteMarker(stage.stringValue,clip)) { Finish(NO,@"The mock grouped clip could not be written."); return; }
        [coordinator finishQueueEntry:@"completed" message:nil output:clip safe:YES];
        return;
    }
    if (!stage || ![entry[@"selection"] isEqual:openedSelection] || ![entry[@"fov"] isEqual:appliedFOV] ||
        width!=1280 || height!=720 || fps!=60 || ![codec isEqual:@"h264"] || bitrate!=12000000 ||
        ![entry[@"id"] isEqual:SavedGroup()[@"id"]]) {
        Finish(NO,@"A clip did not inherit first-item video settings and its own selection/FOV."); return;
    }
    [renderRequests addObject:stage.stringValue];
    NSUInteger index=[[coordinator valueForKey:@"combinedClips"] count]+1;
    NSURL *directory=[[coordinator valueForKey:@"combinedDirectory"] URLByAppendingPathComponent:
        [NSString stringWithFormat:@"Clip-%lu",(unsigned long)index] isDirectory:YES];
    NSURL *clip=[directory URLByAppendingPathComponent:@"Clip.mp4"];
    if (!clip || !WriteMarker(stage.stringValue,clip)) { Finish(NO,@"The mock clip could not be written."); return; }
    [coordinator finishQueueEntry:@"completed" message:nil output:clip safe:YES];
}

@interface MVMenuProbeDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) UIAlertController *menu;
@property(nonatomic) BOOL started;
- (void)exerciseCombinedQueue:(UIView *)panel;
- (void)retryCombinedFromBackground:(BOOL)withRenderer;
- (void)checkAssemblyAttempt:(NSUInteger)attempt;
- (void)checkCombinedCleanup:(NSUInteger)attempt;
- (void)exerciseGroupedRun;
- (void)checkGroupedRun:(NSUInteger)attempt;
@end
@implementation MVMenuProbeDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options; checks=[NSMutableDictionary new];
    NSDictionary *first=QueueEntry(@"F2393595-1B6B-4122-9402-EFF4012CC74F",@0.75,@1.0);
    NSDictionary *second=QueueEntry(@"9579A35C-D7C7-4F80-ACC8-B27646DEAE7A",@0.875,@1.125);
    NSData *fixture=[NSJSONSerialization dataWithJSONObject:@{@"schema":@1,@"entries":@[first,second]} options:0 error:NULL];
    if (![fixture writeToURL:QueueFixtureURL() options:NSDataWritingAtomic error:NULL])
        Finish(NO,@"The queue fixture could not be created.");
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController=[UIViewController new]; self.window.rootViewController.view.backgroundColor=UIColor.blackColor;
    [self.window makeKeyAndVisible];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(), ^{ Finish(NO,@"UIKit menu probe exceeded 30 seconds."); });
    return YES;
}
- (void)applicationDidBecomeActive:(UIApplication *)application {
    (void)application; if (self.started) return; self.started=YES;
    dispatch_async(dispatch_get_main_queue(), ^{ [self exerciseMenu]; });
}
- (void)exerciseMenu {
    @try {
        Method factory=class_getClassMethod(UIAlertAction.class,@selector(actionWithTitle:style:handler:));
        originalActionFactory=reinterpret_cast<ActionFactory>(method_setImplementation(factory,reinterpret_cast<IMP>(&CaptureAction)));
        @autoreleasepool {
            // Calls the actual production UIAlertController factory hook.
            self.menu=[UIAlertController alertControllerWithTitle:@"Client settings" message:@"Simulator regression fixture" preferredStyle:UIAlertControllerStyleAlert];
            releasedAlert=self.menu;
            checks[@"production_action_captured"]=@(productionHandler!=nil);
            method_setImplementation(factory,reinterpret_cast<IMP>(originalActionFactory));
            if (!productionHandler) { Finish(NO,@"Production MP4 action was not captured."); return; }
            [self.window.rootViewController presentViewController:self.menu animated:NO completion:^{
                checks[@"alert_presented"]=@(self.menu.presentingViewController!=nil);
                [self.window.rootViewController dismissViewControllerAnimated:NO completion:^{
                    checks[@"presenting_nil_after_dismissal"]=@(self.menu.presentingViewController==nil);
                    self.menu=nil;
                    // Cross a run-loop/autorelease boundary without requiring
                    // UIKit to release its own last reference to the alert.
                    dispatch_async(dispatch_get_main_queue(), ^{ [self invokeDismissedAction]; });
                }];
            }];
        }
    } @catch (NSException *exception) { Finish(NO,exception.reason); }
}
- (void)invokeDismissedAction {
    @try {
        checks[@"weak_alert_deallocated"]=@(releasedAlert==nil);
        checks[@"presenting_nil_before_handler"]=@(releasedAlert==nil || releasedAlert.presentingViewController==nil);
        if (![checks[@"alert_presented"] boolValue] || ![checks[@"presenting_nil_after_dismissal"] boolValue] || ![checks[@"presenting_nil_before_handler"] boolValue]) {
            Finish(NO,@"The fixture did not reach the dismissed-alert race."); return;
        }
        productionHandler(nil); checks[@"production_handler_invoked"]=@YES;
        dispatch_async(dispatch_get_main_queue(), ^{ [self inspectPanel]; });
    } @catch (NSException *exception) { Finish(NO,exception.reason); }
}
- (void)inspectPanel {
    @try {
        UIView *panel=FindPanel(self.window); checks[@"panel_attached_same_window"]=@(panel.window==self.window && panel.bounds.size.width>0 && panel.bounds.size.height>0);
        if (!panel) { Finish(NO,@"The real MP4 handler did not attach the standalone panel after alert dismissal."); return; }
        BOOL fields=YES;
        for (NSString *key in @[@"widthField",@"heightField",@"bitrateField"]) {
            id field=[panel valueForKey:key]; BOOL found=[field isKindOfClass:UITextField.class] && [field isDescendantOfView:panel]; checks[key]=@(found); fields=fields && found;
        }
        UISegmentedControl *rate=[panel valueForKey:@"rate"],*codec=[panel valueForKey:@"codec"];
        BOOL rates=[rate isKindOfClass:UISegmentedControl.class] && [rate isDescendantOfView:panel] && rate.numberOfSegments==3;
        if (rates) rates=[[rate titleForSegmentAtIndex:0] isEqual:@"30 FPS"] && [[rate titleForSegmentAtIndex:1] isEqual:@"60 FPS"] && [[rate titleForSegmentAtIndex:2] isEqual:@"120 FPS"];
        BOOL codecs=[codec isKindOfClass:UISegmentedControl.class] && [codec isDescendantOfView:panel] && codec.numberOfSegments==2;
        if (codecs) codecs=[[codec titleForSegmentAtIndex:0] isEqual:@"HEVC"] && [[codec titleForSegmentAtIndex:1] isEqual:@"H.264"];
        checks[@"fps_controls"]=@(rates); checks[@"codec_controls"]=@(codecs); checks[@"bindings_installed"]=@NO;
        UIButton *add=[panel valueForKey:@"queueAddButton"],*start=[panel valueForKey:@"queueStartButton"],*save=[panel valueForKey:@"queueSaveButton"];
        UIStackView *rows=[panel valueForKey:@"queueRows"];
        BOOL queue=[add isKindOfClass:UIButton.class] && [add isDescendantOfView:panel] &&
            [start isKindOfClass:UIButton.class] && [start isDescendantOfView:panel] && start.enabled &&
            [save isKindOfClass:UIButton.class] && [save isDescendantOfView:panel] && !save.enabled &&
            rows.arrangedSubviews.count==4;
        if (queue) {
            UILabel *first=(UILabel *)rows.arrangedSubviews[0],*second=(UILabel *)rows.arrangedSubviews[2];
            UIStackView *actions=(UIStackView *)rows.arrangedSubviews[3];
            queue=[first.text containsString:@"FOV 0.75 / 1"] && [second.text containsString:@"FOV 0.875 / 1.125"] &&
                actions.arrangedSubviews.count==2;
            if (queue) {
                [(UIButton *)actions.arrangedSubviews[0] sendActionsForControlEvents:UIControlEventTouchUpInside];
                NSData *data=[NSData dataWithContentsOfURL:QueueFixtureURL()];
                NSArray *saved=[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL][@"entries"];
                queue=saved.count==2 && [saved[0][@"fov"] isEqual:@{@"min":@0.875,@"max":@1.125}] &&
                    [saved[1][@"fov"] isEqual:@{@"min":@0.75,@"max":@1.0}];
            }
        }
        checks[@"same_mv_different_fov_preserved_after_reorder"]=@(queue);
        BOOL passed=[checks[@"panel_attached_same_window"] boolValue] && fields && rates && codecs && queue && nativeStarts==0;
        if (!passed) { Finish(NO,@"Standalone panel/control assertions failed."); return; }
        [self exerciseCombinedQueue:panel];
    } @catch (NSException *exception) { Finish(NO,exception.reason); }
}
- (void)exerciseCombinedQueue:(UIView *)panel {
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    NSString *first=@"F2393595-1B6B-4122-9402-EFF4012CC74F";
    NSString *second=@"9579A35C-D7C7-4F80-ACC8-B27646DEAE7A";
    NSString *third=@"3A5F1348-27EF-4E0F-8270-B213BCBB49B0";
    NSArray<NSString *> *sourceIDs=@[first,second,third];
    groupOrder=@[third,first,second]; stageOrder=@[@"43",@"41",@"42"];
    NSMutableArray<NSDictionary *> *entries=[NSMutableArray new];
    for (NSUInteger index=0;index<sourceIDs.count;index++) {
        NSMutableDictionary *entry=[QueueEntry(sourceIDs[index],@(0.75+0.0625*index),@(1.0+0.0625*index)) mutableCopy];
        entry[@"selection"]=@{@"live_master_id":@15001,@"stage_id":@(41+index)};
        if (index==2) { entry[@"width"]=@1280; entry[@"height"]=@720; }
        if (index==0) entry[@"phase"]=@"completed";
        [entries addObject:[entry copy]];
    }
    ordinaryEntries=[entries copy];
    NSURL *documents=[NSFileManager.defaultManager URLForDirectory:NSDocumentDirectory inDomain:NSUserDomainMask
        appropriateForURL:nil create:YES error:NULL];
    NSURL *exports=[documents URLByAppendingPathComponent:@"exports" isDirectory:YES];
    NSString *existingName=[@"MV-" stringByAppendingString:first];
    existingOutput=[[exports URLByAppendingPathComponent:existingName isDirectory:YES]
        URLByAppendingPathComponent:[NSString stringWithFormat:@"MV-15001-%@.mp4",first]];
    if (!WriteMarker(@"existing standalone export",existingOutput) || ![coordinator writeQueue:ordinaryEntries]) {
        Finish(NO,@"The combined queue fixture could not be saved."); return;
    }
    Method render=class_getInstanceMethod(coordinator.class,@selector(startWidth:height:fps:codec:bitrate:queueEntry:));
    Method assemble=class_getClassMethod(ELMVMP4Combination.class,@selector(combineSources:outputURL:workerQueue:callbackQueue:completion:));
    UIButton *combine=[panel valueForKey:@"combineButton"];
    if (!render || !assemble || !combine.enabled || ![combine.accessibilityIdentifier isEqual:@"Elichika.MVExport.Combine"]) {
        Finish(NO,@"The installed menu does not expose the combined queue flow."); return;
    }
    method_setImplementation(render,reinterpret_cast<IMP>(&CaptureRequestedClip));
    method_setImplementation(assemble,reinterpret_cast<IMP>(&CaptureCombination));
    [combine sendActionsForControlEvents:UIControlEventTouchUpInside];
    UIStackView *choices=[panel valueForKey:@"combineContent"];
    if (choices.hidden) { Finish(NO,@"The playback-order form did not open."); return; }
    for (NSString *identifier in sourceIDs) {
        UIButton *add=FindButton(choices,@"addCombinedSource:",identifier,panel);
        if (!add) { Finish(NO,@"A registered MV is missing from the combined selector."); return; }
        [add sendActionsForControlEvents:UIControlEventTouchUpInside];
    }
    for (NSUInteger index=0;index<2;index++) {
        UIButton *up=FindButton(choices,@"moveCombinedUp:",third,panel);
        if (!up.enabled) { Finish(NO,@"The third MV could not move to the first position."); return; }
        [up sendActionsForControlEvents:UIControlEventTouchUpInside];
    }
    UIButton *start=FindButton(choices,@"startCombinedSelection",nil,panel);
    if (!start.enabled || ![[panel valueForKey:@"combinedSelection"] isEqualToArray:groupOrder]) {
        Finish(NO,@"The combined selector did not keep the requested playback order."); return;
    }
    checks[@"combined_selector_keeps_explicit_order"]=@YES;
    renderRequests=[NSMutableArray new];
    probingGroup=YES; holdNavigation=YES;
    [start sendActionsForControlEvents:UIControlEventTouchUpInside];
    void (^stale)(NSString *)=navigationReady;
    navigationReady=nil; holdNavigation=NO;
    if (!stale || ![SIFASMVExportStatus()[@"busy"] boolValue]) {
        Finish(NO,@"The combined job did not wait on its first stage selection."); return;
    }
    SimulateBackground(); stale(nil);
    dispatch_async(dispatch_get_main_queue(), ^{
        if (renderRequests.count || navigationCancels!=1 || appliedFOV || fovRestores!=1 ||
            macRenderBegins || macRenderEnds || [coordinator valueForKey:@"macExportActivity"] ||
            ![SavedGroup()[@"phase"] isEqual:@"waiting"] || [SIFASMVExportStatus()[@"busy"] boolValue]) {
            Finish(NO,@"iOS background cancellation did not restore FOV or reject a stale navigation callback."); return;
        }
        checks[@"combined_navigation_cancel_rejects_stale_callback"]=@YES;
        checks[@"ios_background_cancellation_preserved"]=@YES;
        [self retryCombinedFromBackground:NO];
    });
}
- (void)retryCombinedFromBackground:(BOOL)withRenderer {
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    simulateMac=YES; allowMacRenderer=withRenderer;
    holdNavigation=YES; openedSelection=nil;
    [coordinator retryCombinedQueueEntry:SavedGroup()[@"id"]];
    void (^ready)(NSString *)=navigationReady;
    navigationReady=nil; holdNavigation=NO;
    if (!ready || ![coordinator valueForKey:@"macExportActivity"] || mockMacRenderActive!=withRenderer) {
        Finish(NO,@"A Mac export did not acquire the expected activity and render leases."); return;
    }
    SimulateBackground();
    if (![SIFASMVExportStatus()[@"busy"] boolValue]) {
        if (withRenderer || mockMacRenderActive || fovRestores!=2 || macRenderEnds!=0 ||
            [coordinator valueForKey:@"macExportActivity"] || ![SavedGroup()[@"phase"] isEqual:@"waiting"]) {
            Finish(NO,@"Background rendering was retained on an unsupported Mac runtime."); return;
        }
        checks[@"unsupported_mac_background_cancels_and_releases"]=@YES;
        [self retryCombinedFromBackground:YES]; return;
    }
    if (!withRenderer) { Finish(NO,@"The Mac export retained an unverified render lease."); return; }
    checks[@"confirmed_mac_background_retains_queue"]=@YES;
    simulateHiddenGame=YES;
    combinationStarted=^{ [self checkAssemblyAttempt:0]; };
    ready(nil);
}
- (void)checkAssemblyAttempt:(NSUInteger)attempt {
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    MVMenuProbeCombination *operation=activeCombination;
    NSMutableArray *markers=[NSMutableArray new];
    for (NSURL *source in operation.inputs) [markers addObject:ReadMarker(source) ?: @"missing"];
    NSArray<NSURL *> *visible=coordinator.queuedOutputs;
    if (![markers isEqualToArray:stageOrder] || ![renderRequests isEqualToArray:stageOrder] ||
        appliedFOV || fovRestores!=2+3*(attempt+1) || visible.count!=1 ||
        mockMacRenderActive || macRenderBegins!=attempt+2 || macRenderEnds!=attempt+1 ||
        ![coordinator valueForKey:@"macExportActivity"] ||
        ![ReadMarker(visible.firstObject) isEqual:@"existing standalone export"] ||
        ![SIFASMVExportStatus()[@"busy"] boolValue]) {
        Finish(NO,@"The assembly saw wrong clip order, an unexpected lease/FOV state or premature outputs."); return;
    }
    SimulateBackground();
    if (operation.cancelled || ![SIFASMVExportStatus()[@"busy"] boolValue]) {
        Finish(NO,@"The completed clips could not continue assembly in Mac background."); return;
    }
    checks[@"mac_assembly_can_continue_without_render_lease"]=@YES;
    simulateHiddenGame=NO;
    checks[@"combined_clips_are_ordered_and_private"]=@YES;
    if (attempt==0) {
        [operation complete:nil problem:ProbeProblem(@"Mock assembly failed")];
    } else if (attempt==1) {
        [NSNotificationCenter.defaultCenter postNotificationName:UISceneDidDisconnectNotification object:nil];
    } else {
        if (!WriteMarker(@"only the combined result",operation.destination)) {
            Finish(NO,@"The mock combined file could not be published."); return;
        }
        [operation complete:operation.destination problem:nil];
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        NSString *required=attempt==0?@"failed":attempt==1?@"waiting":@"completed";
        NSArray<NSURL *> *outputs=coordinator.queuedOutputs;
        if (![SavedGroup()[@"phase"] isEqual:required] || [SIFASMVExportStatus()[@"busy"] boolValue] ||
            [coordinator valueForKey:@"macExportActivity"] || mockMacRenderActive ||
            outputs.count!=(attempt==2?2u:1u) ||
            (attempt==1 && !operation.cancelled) ||
            (attempt==2 && ![ReadMarker(outputs.lastObject) isEqual:@"only the combined result"]) ||
            ![ReadMarker(existingOutput) isEqual:@"existing standalone export"]) {
            Finish(NO,@"The combined job did not persist its proper outcome or preserve the source."); return;
        }
        if (attempt==2) {
            checks[@"combined_failure_cancel_retry_and_atomic_publication"]=@YES;
            [self checkCombinedCleanup:0]; return;
        }
        [renderRequests removeAllObjects];
        combinationStarted=^{ [self checkAssemblyAttempt:attempt+1]; };
        [coordinator retryCombinedQueueEntry:SavedGroup()[@"id"]];
    });
}
- (void)checkCombinedCleanup:(NSUInteger)attempt {
    NSURL *exports=existingOutput.URLByDeletingLastPathComponent.URLByDeletingLastPathComponent;
    NSArray<NSString *> *names=[NSFileManager.defaultManager contentsOfDirectoryAtPath:exports.path error:NULL];
    if (!names) { Finish(NO,@"The probe could not inspect the export folder."); return; }
    for (NSString *name in names) if ([name hasPrefix:@".mv-combine-"]) {
        if (attempt>=50) { Finish(NO,@"A combined job did not remove its private clip directory."); return; }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/50),dispatch_get_main_queue(), ^{ [self checkCombinedCleanup:attempt+1]; });
        return;
    }
    checks[@"combined_private_clip_directories_cleaned"]=@YES;
    [self exerciseGroupedRun];
}
// Builder: MP4 #1 = an already exported MV (skipped, never re-rendered),
// MP4 #2 = two clips (combined path), MP4 #3 empty (ignored), MP4 #4 = one
// waiting MV (its ordinary queued export).
- (void)exerciseGroupedRun {
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    UIView *panel=FindPanel(self.window);
    NSString *first=@"F2393595-1B6B-4122-9402-EFF4012CC74F";
    NSString *second=@"9579A35C-D7C7-4F80-ACC8-B27646DEAE7A";
    NSString *third=@"3A5F1348-27EF-4E0F-8270-B213BCBB49B0";
    NSMutableDictionary *fourth=[QueueEntry(groupedFourth,@1.0,@1.25) mutableCopy];
    fourth[@"selection"]=@{@"live_master_id":@15001,@"stage_id":@44};
    fourth[@"width"]=@1280; fourth[@"height"]=@720;
    NSArray<NSDictionary *> *before=[coordinator.queueEntries arrayByAddingObject:[fourth copy]];
    if (!panel || ![coordinator writeQueue:before]) { Finish(NO,@"The grouped run fixture could not be saved."); return; }
    UIButton *combine=[panel valueForKey:@"combineButton"];
    [panel performSelector:@selector(refresh)];
    if (!combine.enabled || ![combine.accessibilityIdentifier isEqual:@"Elichika.MVExport.Combine"]) {
        Finish(NO,@"The menu does not offer Combine into MP4s after a combined export."); return;
    }
    [combine sendActionsForControlEvents:UIControlEventTouchUpInside];
    UIStackView *choices=[panel valueForKey:@"combineContent"];
    void (^add)(NSString *)=^(NSString *identifier) {
        [FindButton(choices,@"addCombinedSource:",identifier,panel) sendActionsForControlEvents:UIControlEventTouchUpInside];
    };
    void (^newGroup)(void)=^{
        [FindButton(choices,@"addCombinedGroup",nil,panel) sendActionsForControlEvents:UIControlEventTouchUpInside];
    };
    add(first); newGroup(); add(groupedFourth); add(second); newGroup(); newGroup(); add(third);
    NSArray *expected=@[@[first],@[groupedFourth,second],@[],@[third]];
    UIButton *start=FindButton(choices,@"startCombinedSelection",nil,panel);
    if (choices.hidden || ![[panel valueForKey:@"combinedGroups"] isEqual:expected] ||
        [[panel valueForKey:@"activeCombinedGroup"] unsignedIntegerValue]!=3 || !start.enabled ||
        ![[start titleForState:UIControlStateNormal] containsString:@"3"]) {
        Finish(NO,@"The group builder did not keep its MP4s, their order or the active MP4."); return;
    }
    // Choosing an MP4 makes it active; items already in an MP4 are not offered again.
    [FindButton(choices,@"selectCombinedGroup:",@"Elichika.MVExport.Combine.Group.2",panel) sendActionsForControlEvents:UIControlEventTouchUpInside];
    start=FindButton(choices,@"startCombinedSelection",nil,panel);
    if ([[panel valueForKey:@"activeCombinedGroup"] unsignedIntegerValue]!=1 || FindButton(choices,@"addCombinedSource:",first,panel) ||
        !start.enabled) {
        Finish(NO,@"Selecting an MP4 or the available-item list misbehaved."); return;
    }
    checks[@"grouped_builder_keeps_groups_and_order"]=@YES;
    groupedRun=YES; probingGroup=YES; holdNavigation=NO; [renderRequests removeAllObjects];
    // Still the confirmed Mac renderer of the earlier steps (simulateMac and
    // allowMacRenderer stay set): the run takes one render lease for all MP4s.
    groupedRenderBegins=macRenderBegins; groupedRenderEnds=macRenderEnds;
    combinationStarted=^{
        MVMenuProbeCombination *operation=activeCombination;
        NSMutableArray *markers=[NSMutableArray new];
        for (NSURL *source in operation.inputs) [markers addObject:ReadMarker(source) ?: @"missing"];
        if (![markers isEqualToArray:@[@"44",@"42"]] || !WriteMarker(@"grouped combined result",operation.destination)) {
            Finish(NO,@"The grouped combined MP4 saw the wrong clips."); return;
        }
        // MP4 #4 still follows: its game window and render lease must outlive
        // this assembly, because a Mac app in the background can acquire neither.
        UIView *blocker=[coordinator valueForKey:@"inputBlocker"];
        if (!simulateMac || !mockMacRenderActive || !blocker.superview || ![coordinator valueForKey:@"macExportActivity"]) {
            Finish(NO,@"A grouped run released its game window or Mac render lease before its remaining MP4s."); return;
        }
        simulateHiddenGame=YES;
        SimulateBackground();
        if (operation.cancelled || ![SIFASMVExportStatus()[@"busy"] boolValue]) {
            Finish(NO,@"A grouped Mac run did not continue its assembly in the background."); return;
        }
        checks[@"grouped_mac_background_keeps_window_and_render_lease"]=@YES;
        [operation complete:operation.destination problem:nil];
    };
    [start sendActionsForControlEvents:UIControlEventTouchUpInside];
    if (![SIFASMVExportStatus()[@"busy"] boolValue] || !choices.hidden) {
        Finish(NO,@"The grouped run did not start in the background from the queue view."); return;
    }
    [self checkGroupedRun:0];
}
- (void)checkGroupedRun:(NSUInteger)attempt {
    if ([SIFASMVExportStatus()[@"busy"] boolValue]) {
        if (attempt>=250) { Finish(NO,@"The grouped run did not finish."); return; }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/50),dispatch_get_main_queue(), ^{ [self checkGroupedRun:attempt+1]; });
        return;
    }
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    NSString *third=@"3A5F1348-27EF-4E0F-8270-B213BCBB49B0";
    NSString *second=@"9579A35C-D7C7-4F80-ACC8-B27646DEAE7A";
    NSDictionary *thirdEntry=nil, *group=nil;
    for (NSDictionary *entry in coordinator.queueEntries) {
        if ([entry[@"id"] isEqual:third]) thirdEntry=entry;
        if ([entry[@"combined_sources"] isEqual:(@[groupedFourth,second])]) group=entry;
    }
    NSString *message=SIFASMVExportStatus()[@"message"];
    const BOOL english=[NSLocale.preferredLanguages.firstObject hasPrefix:@"en"];
    // MP4 #4 rendered while the game window was hidden in the background.
    simulateHiddenGame=NO;
    if (![renderRequests isEqualToArray:@[@"44",@"42",@"43"]] || ![thirdEntry[@"phase"] isEqual:@"completed"] ||
        ![ReadMarker(SingleOutput(third)) isEqual:@"43"] || ![group[@"phase"] isEqual:@"completed"] ||
        ![ReadMarker(existingOutput) isEqual:@"existing standalone export"] || appliedFOV ||
        (english && ![message containsString:@"2 exported, 1 skipped, 0 failed"]) ||
        [coordinator valueForKey:@"macExportActivity"] || mockMacRenderActive || [coordinator valueForKey:@"inputBlocker"] ||
        macRenderBegins-groupedRenderBegins!=1 || macRenderEnds-groupedRenderEnds!=1) {
        Finish(NO,@"The grouped run did not export, skip and summarize its MP4s in order."); return;
    }
    checks[@"grouped_run_skips_renders_and_summarizes"]=@YES;
    Finish(nativeStarts==0,@"Production menu, combined queue and grouped MP4 lifecycle passed with synthetic renderer and assembly.");
}
@end
int main(int argc,char **argv) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(MVMenuProbeDelegate.class)); }
}
