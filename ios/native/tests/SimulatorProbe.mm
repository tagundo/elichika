#if !ELICHIKA_SIMULATOR_PROBE
#error SimulatorProbe is test-only and must never be compiled into a game IPA.
#endif
#import <UIKit/UIKit.h>
#import "../ElichikaHost.h"
#import "../ElichikaPythonRuntime.h"
#include "../ProbeBudget.hpp"

static NSUInteger ELFakeGameStarts;
@interface ELProbeGame : NSObject
- (void)startUnity:(UIApplication *)application;
@end
@implementation ELProbeGame
- (void)startUnity:(UIApplication *)application { (void)application; ++ELFakeGameStarts; }
@end
@interface ELProbeDelegate : UIResponder <UIApplicationDelegate> {
    elichika::ProbeBudget _budget;
}
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) ELProbeGame *game;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,assign) BOOL finishing;
@property(nonatomic,assign) NSTimeInterval began;
@property(nonatomic,assign) NSTimeInterval lastHeartbeat;
@property(nonatomic,assign) NSUInteger launchNumber;
@property(nonatomic,assign) BOOL completed;
@property(nonatomic,assign) BOOL parityProbe;
@property(nonatomic,copy) NSString *detail;
@property(nonatomic,strong) NSMutableArray *timingEvents;
- (void)advanceStage:(NSString *)name entered:(NSTimeInterval)entered;
@end
@implementation ELProbeDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options;
    _window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new]; controller.view.backgroundColor=UIColor.systemBackgroundColor;
    _window.rootViewController=controller; [_window makeKeyAndVisible];
    self.began=NSProcessInfo.processInfo.systemUptime;
    const BOOL coreOnly=[NSProcessInfo.processInfo.arguments containsObject:@"--elichika-core-probe"];
    self.parityProbe=[NSProcessInfo.processInfo.arguments containsObject:@"--elichika-parity-probe"];
    _budget=elichika::ProbeBudget(self.began,coreOnly,self.parityProbe);
    self.detail=@""; self.timingEvents=[NSMutableArray new];
    for (NSString *argument in NSProcessInfo.processInfo.arguments) {
        if ([argument isEqual:@"--elichika-probe-launch=1"]) self.launchNumber=1;
        if ([argument isEqual:@"--elichika-probe-launch=2"]) self.launchNumber=2;
    }
    __weak ELProbeDelegate *weakSelf=self;
    ElichikaHostSetProbeStageHandler(^(NSString *stage,NSTimeInterval entered) {
        ELProbeDelegate *strong=weakSelf;
        // Worker completion is recorded only when its returned result reaches
        // the callback below; an error path cannot skip successful stages.
        if (strong && !strong.completed && ![stage isEqual:@"python_complete"]) [strong advanceStage:stage entered:entered];
    });
    [self recordTimingAt:self.began]; [self progress:@"running"];
    if (coreOnly && self.parityProbe) {
        [self write:[@{@"schema":@1,@"phase":@"error",@"probe_pass":@NO,
            @"error":@"The management UI proof requires the full tools runtime, not core-only mode."} mutableCopy]];
        return YES;
    }
    if (!self.launchNumber) {
        [self write:[@{@"schema":@1,@"phase":@"error",@"probe_pass":@NO,@"error":@"The cold-launch index is missing."} mutableCopy]];
        return YES;
    }
    self.game=[ELProbeGame new];
    ElichikaHostInstallForProbe(ELProbeGame.class);
    [self.game startUnity:application]; // actual host must hold this call
    self.timer=[NSTimer scheduledTimerWithTimeInterval:0.5 target:self selector:@selector(observe) userInfo:nil repeats:YES];
    return YES;
}
- (void)recordTimingAt:(NSTimeInterval)entered {
    [self.timingEvents addObject:@{@"stage":[NSString stringWithUTF8String:_budget.stage().name],@"detail":self.detail ?: @"",
        @"elapsed_seconds":@(entered-_budget.start())}];
}
- (void)progress:(NSString *)status {
    const double now=NSProcessInfo.processInfo.systemUptime;
    NSDictionary *value=@{@"schema":@1,@"probe_kind":@"native-simulator-progress",@"launch_number":@(self.launchNumber),
        @"sequence":@(_budget.sequence()),@"stage":[NSString stringWithUTF8String:_budget.stage().name],@"detail":self.detail ?: @"",
        @"status":status,@"elapsed_seconds":@(now-_budget.start()),@"stage_elapsed_seconds":@(now-_budget.entered()),
        @"stage_budget_seconds":@(_budget.stage().seconds),@"start_uptime_seconds":@(_budget.start()),
        @"stage_enter_uptime_seconds":@(_budget.entered()),@"sample_uptime_seconds":@(now)};
    NSString *path=[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"elichika-simulator-progress.json"];
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:NULL];
    if (!data || data.length>8192 || ![data writeToFile:path options:NSDataWritingAtomic error:NULL])
        NSLog(@"ELICHIKA_SIMULATOR_PROGRESS_WRITE_FAILED");
    self.lastHeartbeat=now;
}
- (void)advanceStage:(NSString *)name {
    [self advanceStage:name entered:NSProcessInfo.processInfo.systemUptime];
}
- (void)advanceStage:(NSString *)name entered:(NSTimeInterval)entered {
    if (self.completed) return;
    const int previous=_budget.index(); NSString *previousDetail=self.detail;
    if (!_budget.advanceAt(name.UTF8String,entered,NSProcessInfo.processInfo.systemUptime)) {
        NSMutableDictionary *failure=[[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL] mutableCopy];
        failure[@"probe_pass"]=@NO; failure[@"phase"]=@"error"; failure[@"error"]=@"Probe stage order or fixed deadline was violated.";
        [self write:failure]; return;
    }
    NSString *canonical=[NSString stringWithUTF8String:_budget.stage().name];
    self.detail=[name isEqual:canonical] ? @"" : name;
    if (previous!=_budget.index() || ![previousDetail isEqual:self.detail]) [self recordTimingAt:entered];
    [self progress:@"running"];
}
- (void)write:(NSMutableDictionary *)result {
    if (self.completed) return;
    self.completed=YES; [self.timer invalidate];
    if ([result[@"probe_pass"] boolValue]) {
        if (!_budget.advance("complete",NSProcessInfo.processInfo.systemUptime)) {
            result[@"probe_pass"]=@NO; result[@"phase"]=@"error"; result[@"error"]=@"Probe deadline expired before its final receipt.";
        } else { self.detail=@""; [self recordTimingAt:_budget.entered()]; }
    }
    // Publish the final stage before receipt serialization or filesystem I/O.
    // The independent runner enforces this fixed five-second stage even if the
    // main thread stalls, and cannot accept a JSON file until complete/complete.
    [self progress:[result[@"probe_pass"] boolValue] ? @"running" : @"failed"];
    result[@"fake_game_start_count"]=@(ELFakeGameStarts);
    if (self.parityProbe) result[@"management_ui_required"]=@YES;
    result[@"probe_kind"]=@"native-simulator-real-backend-fake-game";
    NSDictionary *configuration=ElichikaHostConfiguration();
    NSFileManager *manager=NSFileManager.defaultManager;
    NSString *documents=[manager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject.path.stringByResolvingSymlinksInPath;
    NSString *support=[manager URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject.path.stringByResolvingSymlinksInPath;
    NSDictionary *expected=@{@"data_root":[support stringByAppendingPathComponent:@"Elichika/data"],
        @"packs_root":[documents stringByAppendingPathComponent:@"Elichika/packs"],
        @"imports_root":[documents stringByAppendingPathComponent:@"Elichika/imports"]};
    BOOL storageValid=YES;
    for (NSString *key in expected) {
        NSString *actual=[configuration[key] stringByStandardizingPath].stringByResolvingSymlinksInPath;
        BOOL directory=NO;
        if (![actual isEqual:expected[key]] || ![manager fileExistsAtPath:actual isDirectory:&directory] || !directory) storageValid=NO;
    }
    result[@"storage_paths_valid"]=@(storageValid);
    result[@"storage_layout"]=@{@"data_relative_application_support":@"Elichika/data",@"packs_relative_documents":@"Elichika/packs",@"imports_relative_documents":@"Elichika/imports"};
    if (!storageValid) {
        result[@"probe_pass"]=@NO; result[@"phase"]=@"error";
        if (![result[@"error"] length]) result[@"error"]=@"The actual native storage configuration failed its Documents contract.";
    }
    result[@"probe_timing"]=@{@"elapsed_seconds":@(NSProcessInfo.processInfo.systemUptime-_budget.start()),
        @"absolute_budget_seconds":@600,@"final_stage":[NSString stringWithUTF8String:_budget.stage().name],@"events":self.timingEvents};
    NSString *path=[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"elichika-simulator-probe.json"];
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:NULL];
    BOOL written=data && [data writeToFile:path options:NSDataWritingAtomic error:NULL];
    if ([result[@"probe_pass"] boolValue] && (!written || _budget.expired(NSProcessInfo.processInfo.systemUptime))) {
        result[@"probe_pass"]=@NO; result[@"phase"]=@"error";
        result[@"error"]=written ? @"Probe deadline expired while writing its final receipt." : @"Could not write the final probe receipt.";
        data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:NULL];
        [data writeToFile:path options:NSDataWritingAtomic error:NULL];
    }
    _budget.seal();
    [self progress:[result[@"probe_pass"] boolValue] ? @"complete" : @"failed"];
    NSLog(@"ELICHIKA_SIMULATOR_PROBE_JSON %@",[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]);
    [self.timer invalidate];
}
- (void)observe {
    if (self.completed) return;
    const double now=NSProcessInfo.processInfo.systemUptime;
    if (_budget.expired(now)) {
        NSMutableDictionary *failure=[[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL] mutableCopy];
        failure[@"probe_pass"]=@NO; failure[@"phase"]=@"error";
        failure[@"error"]=[NSString stringWithFormat:@"Probe deadline exceeded in %@.",[NSString stringWithUTF8String:_budget.stage().name]];
        [self write:failure]; return;
    }
    if (now-self.lastHeartbeat>=2) [self progress:@"running"];
    if (self.finishing) return;
    NSMutableDictionary *status=[[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL] mutableCopy];
    if ([status[@"phase"] isEqual:@"error"]) {
        self.finishing=YES; status[@"probe_pass"]=@NO;
        [self write:status]; return;
    }
    if (![status[@"phase"] isEqual:@"running"] || ELFakeGameStarts!=1) return;
    self.finishing=YES;
    [self advanceStage:@"native_health"]; if (self.completed) return;
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:8080/__elichika/health"]];
    [request setValue:[@"Bearer " stringByAppendingString:ElichikaHostConfiguration()[@"ready_token"]] forHTTPHeaderField:@"Authorization"];
    request.timeoutInterval=15;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error) {
        NSDictionary *health=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        BOOL valid=!error && [(NSHTTPURLResponse *)response statusCode]==200 && [health[@"ready"] boolValue];
        dispatch_async(dispatch_get_main_queue(),^{
            if (self.completed) return;
            status[@"authenticated_go_health"]=@(valid);
            if (!valid) {
                status[@"probe_pass"]=@NO; status[@"phase"]=@"error";
                status[@"error"]=error.localizedDescription ?: @"Authenticated Go health failed.";
                [self write:status]; return;
            }
            [self advanceStage:@"tls"]; if (self.completed) return;
            ElichikaPythonCall(@"probe",^(NSDictionary *probe) {
                if (self.completed) return;
                BOOL tls=[probe[@"tls_probe"] boolValue];
                NSDictionary *dependencies=[probe[@"dependencies"] isKindOfClass:NSDictionary.class] ? probe[@"dependencies"] : @{};
                NSDictionary *runtime=[probe[@"runtime"] isKindOfClass:NSDictionary.class] ? probe[@"runtime"] : @{};
                NSDictionary *tools=[probe[@"tools_probe"] isKindOfClass:NSDictionary.class] ? probe[@"tools_probe"] : @{};
                BOOL dependenciesReady=[status[@"core_only"] boolValue] || [dependencies[@"ready"] boolValue];
                status[@"tls_probe"]=@(tls);
                status[@"runtime_probe"]=@{@"tls_probe":@(tls),@"tls_status":probe[@"tls_status"] ?: @0,
                    @"tls_error":probe[@"tls_error"] ?: @"",@"dependencies":dependencies,@"tools_probe":tools,
                    @"ready":@([probe[@"ready"] boolValue])};
                status[@"probe_pass"]=@([probe[@"ready"] boolValue] && tls && dependenciesReady && [runtime[@"ready"] boolValue] && ELFakeGameStarts==1);
                if (![status[@"probe_pass"] boolValue]) {
                    status[@"phase"]=@"error"; status[@"error"]=@"The real Python/TLS runtime probe failed.";
                    [self write:status]; return;
                }
                [self advanceStage:@"python_complete"]; if (self.completed) return;
                if ([status[@"core_only"] boolValue]) {
                    status[@"web_storage_probe"]=@{@"ready":@NO,@"actual_management_webview":@NO,@"skipped_core_only":@YES};
                    [self write:status]; return;
                }
                ElichikaHostProbeWebStorage(self.launchNumber,^(NSDictionary *storage) {
                    if (self.completed) return;
                    status[@"web_storage_probe"]=storage;
                    if (![storage[@"ready"] boolValue]) {
                        status[@"probe_pass"]=@NO; status[@"phase"]=@"error";
                        status[@"error"]=@"The actual management WebView failed its cold-launch preferences persistence check.";
                        [self write:status]; return;
                    }
                    if (!self.parityProbe) { [self write:status]; return; }
                    ElichikaHostProbeManagement(^(NSDictionary *management) {
                        if (self.completed) return;
                        NSDictionary *reply=[management isKindOfClass:NSDictionary.class] ? management : @{};
                        status[@"management_ui_probe"]=reply;
                        BOOL managementReady=[management isKindOfClass:NSDictionary.class];
                        for (NSString *key in @[@"ready",@"actual_management_webview",@"page_loaded",@"javascript_ready",
                            @"state_fetch",@"controls_present",@"native_binding",@"go_stopped",@"server_restarted"])
                            managementReady=managementReady && [reply[key] isEqual:@YES];
                        id detail=reply[@"error"];
                        BOOL noError=!detail || detail==NSNull.null || [detail isEqual:@NO]
                            || ([detail isKindOfClass:NSString.class] && ![detail length]);
                        managementReady=managementReady && noError && ELFakeGameStarts==1;
                        status[@"probe_pass"]=@(managementReady);
                        if (!managementReady) {
                            status[@"phase"]=@"error";
                            status[@"error"]=[detail isKindOfClass:NSString.class] && [detail length]
                                ? detail : @"The actual management WebView failed its stop/start and native-binding proof.";
                        }
                        [self write:status];
                    });
                });
            });
        });
    }] resume];
}
@end
int main(int argc,char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(ELProbeDelegate.class)); }
}
