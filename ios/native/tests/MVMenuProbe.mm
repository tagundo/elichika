// Simulator-only regression: run the real menu action after its alert has
// dismissed. No Unity, native game bindings, audio preparation or MP4 is run.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import "SIFASMVExportSession.h"
#import "SIFASMVExportBindings.h"
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

// Link only these test bindings, never SIFASMVExportBindings/Bootstrap.mm.
NSDictionary *SIFASMVBindingsStatus(void) { return @{@"installed":@NO,@"liveDirectorObserved":@NO}; }
NSDictionary *SIFASMVBindingsSongSnapshot(void) { return @{}; }
NSDictionary *SIFASMVBindingsAudioSelection(void) { return @{}; }
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

@interface MVMenuProbeDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) UIAlertController *menu;
@property(nonatomic) BOOL started;
@end
@implementation MVMenuProbeDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options; checks=[NSMutableDictionary new];
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController=[UIViewController new]; self.window.rootViewController.view.backgroundColor=UIColor.blackColor;
    [self.window makeKeyAndVisible];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,15*NSEC_PER_SEC),dispatch_get_main_queue(), ^{ Finish(NO,@"UIKit menu probe exceeded15 seconds."); });
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
        BOOL passed=[checks[@"panel_attached_same_window"] boolValue] && fields && rates && codecs && nativeStarts==0;
        Finish(passed,passed?@"Actual production MP4 action opens the same-window controls after its alert loses its presenter.":@"Standalone panel/control assertions failed.");
    } @catch (NSException *exception) { Finish(NO,exception.reason); }
}
@end
int main(int argc,char **argv) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(MVMenuProbeDelegate.class)); }
}
