#if !ELICHIKA_SIMULATOR_PROBE
#error SimulatorProbe is test-only and must never be compiled into a game IPA.
#endif
#import <UIKit/UIKit.h>
#import "../ElichikaHost.h"
#import "../ElichikaPythonRuntime.h"

static NSUInteger ELFakeGameStarts;
@interface ELProbeGame : NSObject
- (void)startUnity:(UIApplication *)application;
@end
@implementation ELProbeGame
- (void)startUnity:(UIApplication *)application { (void)application; ++ELFakeGameStarts; }
@end
@interface ELProbeDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) ELProbeGame *game;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,assign) BOOL finishing;
@property(nonatomic,assign) NSTimeInterval began;
@end
@implementation ELProbeDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options;
    _window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new]; controller.view.backgroundColor=UIColor.systemBackgroundColor;
    _window.rootViewController=controller; [_window makeKeyAndVisible];
    self.began=NSDate.timeIntervalSinceReferenceDate;
    self.game=[ELProbeGame new];
    ElichikaHostInstallForProbe(ELProbeGame.class);
    [self.game startUnity:application]; // actual host must hold this call
    self.timer=[NSTimer scheduledTimerWithTimeInterval:0.5 target:self selector:@selector(observe) userInfo:nil repeats:YES];
    return YES;
}
- (void)write:(NSMutableDictionary *)result {
    result[@"fake_game_start_count"]=@(ELFakeGameStarts);
    result[@"probe_kind"]=@"native-simulator-real-backend-fake-game";
    NSString *path=[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"elichika-simulator-probe.json"];
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:NULL];
    [data writeToFile:path atomically:YES];
    NSLog(@"ELICHIKA_SIMULATOR_PROBE_JSON %@",[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]);
    [self.timer invalidate];
}
- (void)observe {
    if (self.finishing) return;
    NSMutableDictionary *status=[[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingMutableContainers error:NULL] mutableCopy];
    if ([status[@"phase"] isEqual:@"error"] || NSDate.timeIntervalSinceReferenceDate-self.began>240) {
        self.finishing=YES; status[@"probe_pass"]=@NO;
        if (![status[@"phase"] isEqual:@"error"]) { status[@"phase"]=@"error"; status[@"error"]=@"Real backend readiness timed out."; }
        [self write:status]; return;
    }
    if (![status[@"phase"] isEqual:@"running"] || ELFakeGameStarts!=1) return;
    self.finishing=YES;
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:8080/__elichika/health"]];
    [request setValue:[@"Bearer " stringByAppendingString:ElichikaHostConfiguration()[@"ready_token"]] forHTTPHeaderField:@"Authorization"];
    request.timeoutInterval=15;
    [[[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error) {
        NSDictionary *health=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        BOOL valid=!error && [(NSHTTPURLResponse *)response statusCode]==200 && [health[@"ready"] boolValue];
        dispatch_async(dispatch_get_main_queue(),^{
            status[@"authenticated_go_health"]=@(valid);
            if (!valid) {
                status[@"probe_pass"]=@NO; status[@"phase"]=@"error";
                status[@"error"]=error.localizedDescription ?: @"Authenticated Go health failed.";
                [self write:status]; return;
            }
            ElichikaPythonCall(@"probe",^(NSDictionary *probe) {
                BOOL tls=[probe[@"tls_probe"] boolValue];
                NSDictionary *dependencies=[probe[@"dependencies"] isKindOfClass:NSDictionary.class] ? probe[@"dependencies"] : @{};
                NSDictionary *runtime=[probe[@"runtime"] isKindOfClass:NSDictionary.class] ? probe[@"runtime"] : @{};
                BOOL dependenciesReady=[status[@"core_only"] boolValue] || [dependencies[@"ready"] boolValue];
                status[@"tls_probe"]=@(tls);
                status[@"runtime_probe"]=@{@"tls_probe":@(tls),@"tls_status":probe[@"tls_status"] ?: @0,
                    @"tls_error":probe[@"tls_error"] ?: @"",@"dependencies":dependencies};
                status[@"probe_pass"]=@(tls && dependenciesReady && [runtime[@"ready"] boolValue] && ELFakeGameStarts==1);
                if (![status[@"probe_pass"] boolValue]) {
                    status[@"phase"]=@"error"; status[@"error"]=@"The real Python/TLS runtime probe failed.";
                }
                [self write:status];
            });
        });
    }] resume];
}
@end
int main(int argc,char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(ELProbeDelegate.class)); }
}
