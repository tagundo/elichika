#import "ElichikaHost.h"
#import "ElichikaPythonRuntime.h"
#include "HostCore.hpp"
#include "SIFASProfile.h"
#include "RSAPublicKey.hpp"
#import <WebKit/WebKit.h>
#import <Security/Security.h>
#import <dispatch/dispatch.h>
#import <objc/runtime.h>
#import <mach-o/dyld.h>
#import <mach-o/loader.h>
#import <mach/vm_prot.h>
#include <dlfcn.h>
#include <cstring>

static elichika::HostCore &ELCore(void) { static elichika::HostCore value; return value; }
static IMP ELOriginalStart;
static BOOL ELGateInstalled, ELProfileSupported, ELPollPending, ELBootstrapStarted;
static id ELCapturedController, ELCapturedApplication;
static SEL ELStartSelector;
static NSDictionary *ELConfiguration, *ELRuntimeStatus;
static NSString *ELHookError, *ELProgress;
static NSString *ELClientRegion;
static BOOL ELRoutingPrepared;
static NSTimer *ELPollTimer;
static UIWindow *ELPanelWindow;
static UIButton *ELMenuButton;
static __weak UIWindow *ELGameWindow;
static id ELMenuTarget(void);
static void ELRefreshMenu(void);
static NSString *const ELShowServerButtonKey=@"ElichikaShowServerButton";
static elichika::ServerButtonPolicy &ELButtonPolicy(void) {
    static elichika::ServerButtonPolicy policy; static BOOL loaded;
    if (!loaded) { NSUserDefaults *defaults=NSUserDefaults.standardUserDefaults;
        policy.load([defaults objectForKey:ELShowServerButtonKey]!=nil,[defaults boolForKey:ELShowServerButtonKey]); loaded=YES; }
    return policy;
}
static NSString *ELButtonText(NSString *english,NSString *korean,NSString *japanese) {
    NSString *language=ELConfiguration[@"language"] ?: NSLocale.preferredLanguages.firstObject;
    return [language hasPrefix:@"ko"] ? korean : ([language hasPrefix:@"ja"] ? japanese : english);
}

static NSString *ELJSON(id value) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:NULL];
    return data ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : @"{}";
}
static NSString *ELMessage(id value) {
    if ([value isKindOfClass:NSString.class]) return value;
    if ([value isKindOfClass:NSDictionary.class] && [value[@"message"] isKindOfClass:NSString.class]) return value[@"message"];
    return @"";
}
static UIWindow *ELFindGameWindow(void) {
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (window!=ELPanelWindow && window.rootViewController && !window.hidden && window.windowLevel<UIWindowLevelAlert)
            if (window.isKeyWindow) return window;
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (window!=ELPanelWindow && window.rootViewController && !window.hidden && window.windowLevel<UIWindowLevelAlert) return window;
    return nil;
}
UIViewController *ElichikaHostPresenter(void) {
    UIWindow *window=ELPanelWindow.hidden || !ELPanelWindow ? ELFindGameWindow() : ELPanelWindow;
    UIViewController *controller=window.rootViewController;
    while (controller.presentedViewController && !controller.presentedViewController.isBeingDismissed) controller=controller.presentedViewController;
    return controller;
}
NSDictionary *ElichikaHostConfiguration(void) { return ELConfiguration ?: @{}; }
NSString *ElichikaHostDiagnosticsJSON(void) {
    const auto &core=ELCore();
    return ELJSON(@{@"schema":@1,@"phase":[NSString stringWithUTF8String:core.phase()],
                    @"captured":@(core.captured()),@"game_started":@(core.started()),
                    @"real_backend_ready":@(core.ready()),@"foreground":@(core.foreground()),
                    @"gate_installed":@(ELGateInstalled),@"profile_supported":@(ELProfileSupported),
                    @"routing_prepared":@(ELRoutingPrepared),
                    @"server_button_visible":@(ELButtonPolicy().visible()),
                    @"core_only":ELConfiguration[@"core_only"] ?: @NO,
                    @"generation":@(core.generation()),@"error":ELHookError ?: [NSString stringWithUTF8String:core.error().c_str()]});
}

@interface ELPanelController : UIViewController <WKNavigationDelegate,WKScriptMessageHandler>
@property(nonatomic,strong) UILabel *statusLabel;
@property(nonatomic,strong) UIActivityIndicatorView *spinner;
@property(nonatomic,strong) UISegmentedControl *sections;
@property(nonatomic,strong) WKWebView *web;
@property(nonatomic,strong) UIButton *retry;
@property(nonatomic,strong) UIButton *buttonVisibility;
- (void)refresh;
@end
static ELPanelController *ELPanel;
static void ELBeginBackend(void);
static void ELMaybeStartGame(void);
static void ELReceiveStatus(NSDictionary *status, uint64_t generation);

static BOOL ELIsPanelURL(NSURL *url) {
    if (![url.scheme.lowercaseString isEqual:@"http"] || ![url.host isEqual:@"127.0.0.1"] || url.user || url.password) return NO;
    NSMutableSet *ports=[NSMutableSet setWithObject:@8080];
    for (NSString *key in @[@"admin_url",@"tools_url"]) {
        NSURL *panel=[NSURL URLWithString:ELRuntimeStatus[key] ?: @""];
        if ([panel.host isEqual:@"127.0.0.1"] && panel.port) [ports addObject:panel.port];
    }
    return url.port && [ports containsObject:url.port];
}
static void ELHidePanel(void) {
    ELPanelWindow.hidden=YES;
    UIWindow *window=ELGameWindow ?: ELFindGameWindow(); [window makeKeyWindow];
}
@implementation ELPanelController
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor=UIColor.systemBackgroundColor;
    self.title=@"Elichika";
    self.navigationItem.rightBarButtonItem=[[UIBarButtonItem alloc] initWithTitle:@"Game" style:UIBarButtonItemStyleDone target:self action:@selector(close)];
    _statusLabel=[UILabel new]; _statusLabel.numberOfLines=0; _statusLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline];
    _spinner=[[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    _retry=[UIButton buttonWithType:UIButtonTypeSystem]; [_retry setTitle:@"Retry setup" forState:UIControlStateNormal];
    [_retry addTarget:self action:@selector(retrySetup) forControlEvents:UIControlEventTouchUpInside];
    _sections=[[UISegmentedControl alloc] initWithItems:@[@"Accounts",@"Server",@"Tools"]];
    [_sections addTarget:self action:@selector(openSection) forControlEvents:UIControlEventValueChanged];
    _buttonVisibility=[UIButton buttonWithType:UIButtonTypeSystem];
    [_buttonVisibility addTarget:self action:@selector(toggleServerButton) forControlEvents:UIControlEventTouchUpInside];
    UILabel *guidance=[UILabel new]; guidance.numberOfLines=0;
    guidance.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2]; guidance.textColor=UIColor.secondaryLabelColor;
    guidance.text=ELButtonText(@"Hide the button for MVs. Hold the upper-left corner for 2 seconds to reopen this panel. The choice is saved.",
        @"MV 화면을 가리지 않도록 버튼을 숨깁니다. 왼쪽 위 모서리를 2초간 길게 누르면 이 패널을 다시 열 수 있습니다. 선택은 저장됩니다.",
        @"MVを見やすくするためにボタンを隠します。左上隅を2秒間長押しすると、このパネルを再び開けます。設定は保存されます。");
    WKWebViewConfiguration *configuration=[WKWebViewConfiguration new];
    configuration.websiteDataStore=WKWebsiteDataStore.nonPersistentDataStore;
    [configuration.userContentController addScriptMessageHandler:self name:@"elichika"];
    NSString *script=@"(()=>{const p=new Map();let n=0;window.ElichikaIOS=Object.freeze({request:(action,options={})=>new Promise((resolve,reject)=>{const id=String(++n);p.set(id,{resolve,reject});window.webkit.messageHandlers.elichika.postMessage({id,action,...options});})});window.addEventListener('elichika-native-result',e=>{const x=e.detail,j=p.get(x.id);if(j){p.delete(x.id);x.error?j.reject(Error(x.error)):j.resolve(x.result)}})})();";
    [configuration.userContentController addUserScript:[[WKUserScript alloc] initWithSource:script injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    _web=[[WKWebView alloc] initWithFrame:CGRectZero configuration:configuration]; _web.navigationDelegate=self;
    UIStackView *head=[[UIStackView alloc] initWithArrangedSubviews:@[_statusLabel,_spinner,_retry,_buttonVisibility,guidance,_sections]];
    head.axis=UILayoutConstraintAxisVertical; head.spacing=8;
    head.translatesAutoresizingMaskIntoConstraints=NO; _web.translatesAutoresizingMaskIntoConstraints=NO;
    [self.view addSubview:head]; [self.view addSubview:_web];
    UILayoutGuide *safe=self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [head.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12],
        [head.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [head.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [_web.topAnchor constraintEqualToAnchor:head.bottomAnchor constant:12],
        [_web.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [_web.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [_web.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor]]];
    [self refresh];
}
- (void)dealloc { [_web.configuration.userContentController removeScriptMessageHandlerForName:@"elichika"]; }
- (void)close { if (ELCore().started()) ELHidePanel(); }
- (void)toggleServerButton {
    ELButtonPolicy().toggle();
    [NSUserDefaults.standardUserDefaults setBool:ELButtonPolicy().visible() forKey:ELShowServerButtonKey];
    ELRefreshMenu(); [self refresh];
}
- (void)retrySetup {
    if (!ELProfileSupported || !ELRoutingPrepared) return;
    [self.retry setEnabled:NO];
    ElichikaPythonCall(@"status",^(NSDictionary *status) {
        if ([status[@"ready"] boolValue]) {
            const auto generation=ELCore().begin(); ELHookError=nil;
            ELReceiveStatus(status,generation);
        }
        else ELBeginBackend();
    });
}
- (void)refresh {
    if (!self.isViewLoaded) return;
    [_buttonVisibility setTitle:ELButtonPolicy().visible()
        ? ELButtonText(@"Hide server button",@"서버 버튼 숨기기",@"サーバーボタンを隠す")
        : ELButtonText(@"Show server button",@"서버 버튼 표시",@"サーバーボタンを表示") forState:UIControlStateNormal];
    NSString *error=ELHookError ?: [NSString stringWithUTF8String:ELCore().error().c_str()];
    if (error.length) _statusLabel.text=[NSString stringWithFormat:@"Setup could not finish.\n%@",error];
    else if (ELCore().ready()) _statusLabel.text=[ELConfiguration[@"core_only"] boolValue]
        ? @"Core server probe ready. Tools are excluded from this test."
        : @"Server and tools are ready. Closing this panel keeps them running.";
    else _statusLabel.text=ELProgress ?: @"Preparing your local server and tools…";
    BOOL busy=!ELCore().ready() && !error.length;
    if (busy) [_spinner startAnimating]; else [_spinner stopAnimating];
    _retry.hidden=!error.length; _retry.enabled=ELProfileSupported && ELRoutingPrepared;
    _sections.enabled=ELCore().ready() && ![ELConfiguration[@"core_only"] boolValue];
    self.navigationItem.rightBarButtonItem.enabled=ELCore().started();
}
- (void)openSection {
    NSString *url;
    if (_sections.selectedSegmentIndex==0) url=@"http://127.0.0.1:8080/webui/user";
    else if (_sections.selectedSegmentIndex==1) url=ELRuntimeStatus[@"admin_url"];
    else url=ELRuntimeStatus[@"tools_url"];
    NSURL *target=[NSURL URLWithString:url ?: @""];
    if (!ELIsPanelURL(target)) return;
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:target];
    [request setValue:ELConfiguration[@"token"] forHTTPHeaderField:@"X-Elichika-Local-Access"];
    [_web loadRequest:request];
}
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    (void)web;
    NSURL *url=action.request.URL;
    if (ELIsPanelURL(url) || [url.absoluteString isEqual:@"about:blank"] || [url.scheme isEqual:@"blob"]) { decision(WKNavigationActionPolicyAllow); return; }
    decision(WKNavigationActionPolicyCancel);
    if (action.navigationType==WKNavigationTypeLinkActivated && [url.scheme.lowercaseString isEqual:@"https"])
        [UIApplication.sharedApplication openURL:url options:@{} completionHandler:nil];
}
- (void)reply:(NSString *)identifier result:(id)result error:(NSString *)error {
    NSDictionary *value=@{@"id":identifier,@"result":result ?: NSNull.null,@"error":error ?: @""};
    NSString *javascript=[NSString stringWithFormat:@"window.dispatchEvent(new CustomEvent('elichika-native-result',{detail:%@}));",ELJSON(value)];
    [_web evaluateJavaScript:javascript completionHandler:nil];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)controller;
    if (!message.frameInfo.isMainFrame || !ELIsPanelURL(message.frameInfo.request.URL) || ![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *request=message.body;
    NSString *identifier=request[@"id"],*action=request[@"action"];
    if (![identifier isKindOfClass:NSString.class] || identifier.length>64 || ![action isKindOfClass:NSString.class]) return;
    if ([action isEqual:@"status"]) {
        [self reply:identifier result:[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] error:nil]; return;
    }
    if ([action isEqual:@"import"]) {
        NSArray *types=[request[@"types"] isKindOfClass:NSArray.class] ? request[@"types"] : @[@"public.data"];
        BOOL multiple=[request[@"multiple"] boolValue];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error; NSArray *paths=ElichikaHostImportDocuments(types,multiple,&error);
            id result=multiple ? paths : paths.firstObject;
            dispatch_async(dispatch_get_main_queue(),^{ [self reply:identifier result:result error:error.localizedDescription]; });
        }); return;
    }
    if ([action isEqual:@"export"] && [request[@"path"] isKindOfClass:NSString.class]) {
        NSString *path=request[@"path"];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error; BOOL done=ElichikaHostExportDocument(path,&error);
            dispatch_async(dispatch_get_main_queue(),^{ [self reply:identifier result:@(done) error:error.localizedDescription]; });
        }); return;
    }
    [self reply:identifier result:nil error:@"Unknown native action."];
}
@end

void ElichikaHostShowManagement(void) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(),^{ ElichikaHostShowManagement(); }); return; }
    ELGameWindow=ELFindGameWindow();
    if (!ELPanelWindow) {
        UIWindowScene *scene=ELGameWindow.windowScene;
        ELPanelWindow=scene ? [[UIWindow alloc] initWithWindowScene:scene] : [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
        ELPanelWindow.windowLevel=UIWindowLevelAlert+1;
        ELPanel=[ELPanelController new];
        ELPanelWindow.rootViewController=[[UINavigationController alloc] initWithRootViewController:ELPanel];
    }
    [ELPanel refresh]; [ELPanelWindow makeKeyAndVisible];
}
static void ELRefreshMenu(void) {
    UIWindow *window=ELFindGameWindow(); if (!window) return;
    static NSHashTable *gestureWindows;
    if (!gestureWindows) gestureWindows=NSHashTable.weakObjectsHashTable;
    if (![gestureWindows containsObject:window]) {
        UILongPressGestureRecognizer *restore=[[UILongPressGestureRecognizer alloc] initWithTarget:ELMenuTarget() action:@selector(restore:)];
        restore.minimumPressDuration=elichika::ServerButtonPolicy::restoreHoldSeconds;
        restore.numberOfTouchesRequired=1; restore.allowableMovement=12;
        restore.cancelsTouchesInView=NO; restore.delaysTouchesBegan=NO; restore.delaysTouchesEnded=NO;
        restore.delegate=ELMenuTarget(); [window addGestureRecognizer:restore]; [gestureWindows addObject:window];
    }
    if (!ELMenuButton) {
        ELMenuButton=[UIButton buttonWithType:UIButtonTypeSystem];
        [ELMenuButton setTitle:@"Elichika" forState:UIControlStateNormal];
        ELMenuButton.backgroundColor=[UIColor.systemBackgroundColor colorWithAlphaComponent:0.88];
        ELMenuButton.layer.cornerRadius=9;
        [ELMenuButton addTarget:ELMenuTarget() action:@selector(show) forControlEvents:UIControlEventTouchUpInside];
    }
    if (ELMenuButton.superview!=window) [window addSubview:ELMenuButton];
    ELMenuButton.hidden=!ELButtonPolicy().visible();
    ELMenuButton.frame=CGRectMake(window.safeAreaInsets.left+8,window.safeAreaInsets.top+8,82,34);
    [window bringSubviewToFront:ELMenuButton];
}

@interface ELMenuAction : NSObject <UIGestureRecognizerDelegate>
- (void)show;
- (void)restore:(UILongPressGestureRecognizer *)gesture;
@end
@implementation ELMenuAction
- (void)show { ElichikaHostShowManagement(); }
- (void)restore:(UILongPressGestureRecognizer *)gesture { if (gesture.state==UIGestureRecognizerStateBegan) ElichikaHostShowManagement(); }
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gesture shouldReceiveTouch:(UITouch *)touch {
    CGPoint point=[touch locationInView:gesture.view]; CGRect bounds=gesture.view.bounds; UIEdgeInsets safe=gesture.view.safeAreaInsets;
    return elichika::ServerButtonPolicy::restoreCorner(point.x,point.y,bounds.size.width,bounds.size.height,safe.left,safe.top);
}
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gesture shouldRecognizeSimultaneouslyWithGestureRecognizer:(UIGestureRecognizer *)other {
    (void)gesture; (void)other; return YES;
}
@end
static id ELMenuTarget(void) { static ELMenuAction *value; static dispatch_once_t once; dispatch_once(&once,^{ value=[ELMenuAction new]; }); return value; }

static BOOL ELPrepareConfiguration(NSString **error) {
    NSFileManager *manager=NSFileManager.defaultManager;
    NSURL *support=[manager URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *documents=[manager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSString *root=[[support.path stringByAppendingPathComponent:@"Elichika"] stringByAppendingPathComponent:@"data"];
    NSString *resources=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"ElichikaResources"];
    if (![manager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:@{NSFileProtectionKey:NSFileProtectionCompleteUntilFirstUserAuthentication} error:NULL]) {
        *error=@"Could not prepare app-private server storage."; return NO;
    }
    uint8_t random[32]; if (SecRandomCopyBytes(kSecRandomDefault,sizeof random,random)!=errSecSuccess) {
        *error=@"Could not create the local server session."; return NO;
    }
    NSMutableString *token=[NSMutableString new],*readyToken=[NSMutableString new];
    for (NSUInteger i=0;i<16;++i) [token appendFormat:@"%02x",random[i]];
    for (NSUInteger i=16;i<32;++i) [readyToken appendFormat:@"%02x",random[i]];
    NSString *language=NSLocale.preferredLanguages.firstObject ?: @"en";
    language=[language hasPrefix:@"ja"] ? @"ja" : ([language hasPrefix:@"ko"] ? @"ko" : @"en");
    NSMutableDictionary *configuration=[@{
        @"python_home":[resources stringByAppendingPathComponent:@"python"],
        @"python_app_root":[resources stringByAppendingPathComponent:@"python-app"],
        @"payload_root":[resources stringByAppendingPathComponent:@"python-app"],
        @"seed_root":[resources stringByAppendingPathComponent:@"payload"],
        @"tool_data_root":[resources stringByAppendingPathComponent:@"tool-data"],
        @"data_root":root,@"documents_root":documents.path,
        @"imports_root":[documents.path stringByAppendingPathComponent:@"Imports"],
        @"listen_address":@"127.0.0.1:8080",@"token":token,@"ready_token":readyToken,@"language":language,
        @"region":ELClientRegion ?: @"gl",
        @"core_only":@NO
    } mutableCopy];
#if ELICHIKA_SIMULATOR_PROBE
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--elichika-core-probe"]) configuration[@"core_only"]=@YES;
#endif
    ELConfiguration=[configuration copy]; return YES;
}
static void ELReceiveStatus(NSDictionary *status, uint64_t generation) {
    if (generation!=ELCore().generation()) return;
    ELRuntimeStatus=status;
    NSString *error=ELMessage(status[@"error"]);
    BOOL ready=[status[@"ready"] boolValue];
    NSDictionary *server=[status[@"server"] isKindOfClass:NSDictionary.class] ? status[@"server"] : nil;
    ready=ready && server && [server[@"ready"] boolValue];
    if (ready && ![ELConfiguration[@"core_only"] boolValue])
        ready=![status[@"core_only"] boolValue] && ELIsPanelURL([NSURL URLWithString:status[@"admin_url"] ?: @""])
            && ELIsPanelURL([NSURL URLWithString:status[@"tools_url"] ?: @""]);
    if (error.length) { ELCore().fail(error.UTF8String); ELProgress=error; ElichikaHostShowManagement(); }
    else ELCore().report(generation,ready,"");
    [ELPanel refresh]; ELMaybeStartGame();
}
static void ELPoll(void) {
    ELRefreshMenu();
    if (!ELBootstrapStarted || ELPollPending || !ELCore().foreground()) return;
    ELPollPending=YES; uint64_t generation=ELCore().generation();
    ElichikaPythonCall(@"status",^(NSDictionary *status) { ELPollPending=NO; ELReceiveStatus(status,generation); });
}
static void ELBeginBackend(void) {
    if (!ELProfileSupported || !ELRoutingPrepared || !ELGateInstalled) return;
    if (!ELConfiguration) {
        NSString *error=nil;
        if (!ELPrepareConfiguration(&error)) { ELCore().fail(error.UTF8String); ELHookError=error; [ELPanel refresh]; return; }
    }
    ELBootstrapStarted=YES; uint64_t generation=ELCore().begin(); ELHookError=nil;
    ELProgress=@"Preparing your local server and tools…";
    ElichikaPythonStart(ELConfiguration,^(NSDictionary *status) { ELReceiveStatus(status,generation); });
    if (!ELPollTimer) ELPollTimer=[NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) { (void)timer; ELPoll(); }];
    [ELPanel refresh];
}
static void ELMaybeStartGame(void) {
    if (!ELProfileSupported || !ELRoutingPrepared || !ELOriginalStart || !ELCore().takeStart()) return;
    ELHidePanel();
    ((void (*)(id,SEL,id))ELOriginalStart)(ELCapturedController,ELStartSelector,ELCapturedApplication);
    ELRefreshMenu();
}
void ElichikaHostReportEvent(NSString *json) {
    NSData *data=[json dataUsingEncoding:NSUTF8StringEncoding]; if (!data || data.length>65536) return;
    id event=[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if (![event isKindOfClass:NSDictionary.class]) return;
    dispatch_async(dispatch_get_main_queue(),^{
        NSString *phase=[event[@"phase"] isKindOfClass:NSString.class] ? event[@"phase"] : @"Preparing";
        if ([event[@"completed"] isKindOfClass:NSNumber.class] && [event[@"total"] isKindOfClass:NSNumber.class])
            ELProgress=[NSString stringWithFormat:@"Preparing local data: %@ of %@",event[@"completed"],event[@"total"]];
        else ELProgress=[phase stringByReplacingOccurrencesOfString:@"_" withString:@" "];
        [ELPanel refresh];
    });
}

static void ELHoldUnityStart(id controller, SEL selector, id application) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(),^{ ELHoldUnityStart(controller,selector,application); }); return; }
    if (!ELCore().capture((uintptr_t)(__bridge void *)controller)) { ElichikaHostShowManagement(); return; }
    if (ELCapturedController && (ELCapturedApplication!=application || ELStartSelector!=selector)) {
        ELCore().fail("The captured game startup arguments changed."); ElichikaHostShowManagement(); return;
    }
    if (!ELCapturedController) { ELCapturedController=controller; ELCapturedApplication=application; ELStartSelector=selector; }
    if (!ELProfileSupported || !ELRoutingPrepared) { ELCore().fail((ELHookError ?: @"This SIFAS executable is unsupported.").UTF8String); ElichikaHostShowManagement(); return; }
    if (!ELBootstrapStarted) ELBeginBackend();
    if (!ELCore().started()) ElichikaHostShowManagement();
    ELMaybeStartGame();
}
static BOOL ELMethodSignature(Method method) {
    if (!method || method_getNumberOfArguments(method)!=3) return NO;
    const char *expected[]={"v","@",":","@"};
    for (unsigned i=0;i<4;++i) {
        char *actual=i ? method_copyArgumentType(method,i-1) : method_copyReturnType(method);
        BOOL equal=actual && !strcmp(actual,expected[i]); free(actual); if (!equal) return NO;
    }
    return YES;
}
static BOOL ELAuditProfile(Method method) {
#if ELICHIKA_SIMULATOR_PROBE
    ELClientRegion=@"gl";
    Dl_info owner; return dladdr((const void *)method_getImplementation(method),&owner) && owner.dli_fbase==_dyld_get_image_header(0);
#else
    const struct mach_header_64 *header=(const struct mach_header_64 *)_dyld_get_image_header(0);
    if (!header || header->magic!=MH_MAGIC_64 || header->cputype!=CPU_TYPE_ARM64 || header->filetype!=MH_EXECUTE || header->ncmds>256 || header->sizeofcmds>65536) return NO;
    const uint8_t *cursor=(const uint8_t *)(header+1),*end=cursor+header->sizeofcmds;
    const ElichikaSIFASProfile *profile=NULL; uint64_t base=0, textSize=0;
    for (uint32_t i=0;i<header->ncmds;++i) {
        if ((size_t)(end-cursor)<sizeof(struct load_command)) return NO;
        const struct load_command *command=(const struct load_command *)cursor;
        if (command->cmdsize<sizeof *command || command->cmdsize>(size_t)(end-cursor)) return NO;
        if (command->cmd==LC_UUID && command->cmdsize==sizeof(struct uuid_command)) {
            for (const auto &candidate:ElichikaSIFASProfiles)
                if (!memcmp(((const struct uuid_command *)command)->uuid,candidate.uuid,16)) profile=&candidate;
        }
        if (command->cmd==LC_SEGMENT_64 && command->cmdsize>=sizeof(struct segment_command_64)) {
            const auto *segment=(const struct segment_command_64 *)command;
            if (!memcmp(segment->segname,"__TEXT\0",7) && segment->fileoff==0 && (segment->initprot&VM_PROT_EXECUTE)) { base=segment->vmaddr; textSize=segment->filesize; }
        }
        cursor+=command->cmdsize;
    }
    if (!profile || !base || cursor!=end || profile->startUnityRVA>textSize || sizeof profile->startUnityCode>textSize-profile->startUnityRVA) return NO;
    const void *expected=(const uint8_t *)header+profile->startUnityRVA;
    Dl_info owner;
    BOOL valid=method_getImplementation(method)==(IMP)expected && dladdr(expected,&owner) && owner.dli_fbase==header &&
        !memcmp(expected,profile->startUnityCode,sizeof profile->startUnityCode);
    if (valid) ELClientRegion=strcmp(profile->region,"jp")==0 ? @"jp" : @"gl";
    return valid;
#endif
}
static NSUInteger ELGameKeyCapacity(void) {
#if ELICHIKA_SIMULATOR_PROBE
    return 419; // no game metadata is substituted into the independent probe
#else
    NSString *path=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Data/Managed/Metadata/global-metadata.dat"];
    NSData *metadata=[NSData dataWithContentsOfFile:path options:NSDataReadingMappedIfSafe error:NULL];
    if (metadata.length<24) return 0;
    const uint8_t *bytes=(const uint8_t *)metadata.bytes; uint32_t header[6]; memcpy(header,bytes,sizeof header);
    uint64_t index=[ELClientRegion isEqual:@"jp"] ? 3615 : 3621;
    if (header[0]!=0xfab11baf || header[1]!=24 || index*8+8>header[3] ||
        (uint64_t)header[2]+index*8+8>metadata.length) return 0;
    uint32_t entry[2]; memcpy(entry,bytes+header[2]+index*8,sizeof entry);
    if (!entry[0] || entry[0]>4096 || (uint64_t)entry[1]+entry[0]>header[5] ||
        (uint64_t)header[4]+entry[1]+entry[0]>metadata.length) return 0;
    NSString *literal=[[NSString alloc] initWithBytes:bytes+header[4]+entry[1] length:entry[0] encoding:NSUTF8StringEncoding];
    NSString *trimmed=[literal stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    return [trimmed hasPrefix:@"<RSAKeyValue>"] && [trimmed hasSuffix:@"</RSAKeyValue>"] ? literal.length : 0;
#endif
}
static BOOL ELPrepareRouting(NSString **error) {
    NSString *path=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"ElichikaResources/payload/publickey.pem"];
    NSData *pem=[NSData dataWithContentsOfFile:path options:0 error:NULL];
    if (!pem.length || pem.length>8192) { *error=@"The bundled server public key is missing or too large."; return NO; }
    NSString *text=[[NSString alloc] initWithData:pem encoding:NSASCIIStringEncoding];
    text=[text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *begin=@"-----BEGIN PUBLIC KEY-----",*end=@"-----END PUBLIC KEY-----";
    if (![text hasPrefix:begin] || ![text hasSuffix:end]) { *error=@"The bundled server public key is not RSA public-key PEM."; return NO; }
    NSString *base64=[text substringWithRange:NSMakeRange(begin.length,text.length-begin.length-end.length)];
    base64=[[base64 componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] componentsJoinedByString:@""];
    NSData *der=[[NSData alloc] initWithBase64EncodedString:base64 options:0];
    std::vector<uint8_t> modulus,exponent;
    if (!der || !elichika::parseRSAPublicKey((const uint8_t *)der.bytes,der.length,modulus,exponent)) {
        *error=@"The bundled server public key is malformed or unsupported."; return NO;
    }
    NSString *n=[[NSData dataWithBytes:modulus.data() length:modulus.size()] base64EncodedStringWithOptions:0];
    NSString *e=[[NSData dataWithBytes:exponent.data() length:exponent.size()] base64EncodedStringWithOptions:0];
    NSString *xml=[NSString stringWithFormat:@"<RSAKeyValue><Modulus>%@</Modulus><Exponent>%@</Exponent></RSAKeyValue>",n,e];
    NSUInteger capacity=ELGameKeyCapacity();
    if (!capacity || xml.length>capacity) { *error=@"The server public key exceeds this game's verified RSA string capacity."; return NO; }
    NSUserDefaults *preferences=NSUserDefaults.standardUserDefaults;
    NSString *endpoint=[preferences stringForKey:@"ServerEndpoint"];
    if (endpoint.length && ![endpoint isEqual:@"http://127.0.0.1:8080"] && ![preferences objectForKey:@"ElichikaPreviousServerEndpoint"])
        [preferences setObject:endpoint forKey:@"ElichikaPreviousServerEndpoint"];
    NSString *previousKey=[preferences stringForKey:@"RSAKey"];
    if (previousKey.length && ![[previousKey stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] isEqual:xml] &&
        ![preferences objectForKey:@"ElichikaPreviousRSAKey"])
        [preferences setObject:previousKey forKey:@"ElichikaPreviousRSAKey"];
    [preferences setObject:@"http://127.0.0.1:8080" forKey:@"ServerEndpoint"];
    if (![previousKey isEqual:xml]) [preferences setObject:xml forKey:@"RSAKey"];
    ELRoutingPrepared=YES; return YES;
}
static BOOL ELInstall(Class controller) {
    if (ELGateInstalled) return ELProfileSupported;
    SEL selector=sel_registerName("startUnity:"); Method method=class_getInstanceMethod(controller,selector);
    if (!ELMethodSignature(method)) { ELHookError=@"The SIFAS startup method could not be verified. Reinstall the supported combined package."; return NO; }
    ELOriginalStart=method_getImplementation(method); ELProfileSupported=ELAuditProfile(method);
    if (!ELProfileSupported) ELHookError=@"This SIFAS executable does not match the supported startup profile. The game was held before startup.";
    else {
        NSString *error=nil;
        if (!ELPrepareRouting(&error)) ELHookError=error;
    }
    IMP previous=class_replaceMethod(controller,selector,(IMP)ELHoldUnityStart,method_getTypeEncoding(method));
    ELGateInstalled=previous==ELOriginalStart;
    if (!ELGateInstalled) { ELProfileSupported=NO; ELHookError=@"Another startup hook changed while the host was installing."; }
    return ELGateInstalled && ELProfileSupported && ELRoutingPrepared;
}
static void ELObserve(void) {
    NSNotificationCenter *center=NSNotificationCenter.defaultCenter;
    [center addObserverForName:UIApplicationDidBecomeActiveNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
        (void)note; ELCore().foreground(true); ElichikaPythonLifecycle(@"foreground"); ELPoll(); ELMaybeStartGame();
    }];
    [center addObserverForName:UIApplicationDidEnterBackgroundNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
        (void)note; ELCore().foreground(false); ElichikaPythonLifecycle(@"background");
    }];
    [center addObserverForName:UIApplicationDidReceiveMemoryWarningNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
        (void)note; ElichikaPythonLifecycle(@"memory_warning");
    }];
    [center addObserverForName:UIApplicationWillTerminateNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
        (void)note; ElichikaPythonLifecycle(@"terminate");
    }];
}
#if ELICHIKA_SIMULATOR_PROBE
BOOL ElichikaHostInstallForProbe(Class controller) { BOOL good=ELInstall(controller); ELObserve(); return good; }
#else
__attribute__((constructor)) static void ElichikaInstallHost(void) {
    @autoreleasepool {
        if (![NSBundle.mainBundle.infoDictionary[@"ElichikaUnifiedHostEnabled"] boolValue]) return;
        ELInstall(objc_getClass("UnityAppController")); ELObserve();
    }
}
#endif

@interface ELDocumentTransaction : NSObject <UIDocumentPickerDelegate,UIAdaptivePresentationControllerDelegate>
@property(nonatomic,strong) dispatch_semaphore_t finished;
@property(nonatomic,strong) NSError *error;
@property(nonatomic,copy) NSString *path;
@property(nonatomic,copy) NSArray<NSString *> *paths;
@property(nonatomic,assign) BOOL exporting;
@property(nonatomic,assign) BOOL multiple;
@property(nonatomic,assign) BOOL copying;
@property(nonatomic,assign) BOOL completed;
- (void)finish;
@end
static ELDocumentTransaction *ELPendingDocument;
@implementation ELDocumentTransaction
- (void)finish { if (_completed) return; _completed=YES; dispatch_semaphore_signal(_finished); if (ELPendingDocument==self) ELPendingDocument=nil; }
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller { (void)controller; if (_copying) return; _error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Document selection cancelled."}]; [self finish]; }
- (void)presentationControllerDidDismiss:(UIPresentationController *)controller { (void)controller; [self documentPickerWasCancelled:nil]; }
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    if (_exporting) { [self finish]; return; }
    if (!urls.count) { [self documentPickerWasCancelled:controller]; return; }
    if (urls.count>128 || (!_multiple && urls.count!=1)) {
        _error=[NSError errorWithDomain:@"ElichikaDocument" code:6 userInfo:@{NSLocalizedDescriptionKey:@"Choose at most 128 files per import."}]; [self finish]; return;
    }
    _copying=YES;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
        NSString *root=[ELConfiguration[@"imports_root"] stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
        __block NSError *error=nil; NSMutableArray *paths=[NSMutableArray new];
        for (NSUInteger i=0;i<urls.count && !error;++i) {
            NSURL *source=urls[i]; BOOL access=[source startAccessingSecurityScopedResource];
            NSString *folder=[root stringByAppendingPathComponent:[NSString stringWithFormat:@"%lu",(unsigned long)i]];
            NSFileCoordinator *coordinator=[[NSFileCoordinator alloc] initWithFilePresenter:nil];
            [coordinator coordinateReadingItemAtURL:source options:0 error:&error byAccessor:^(NSURL *readURL) {
                NSString *destination=[folder stringByAppendingPathComponent:readURL.lastPathComponent];
                if ([NSFileManager.defaultManager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:&error] &&
                    [NSFileManager.defaultManager copyItemAtURL:readURL toURL:[NSURL fileURLWithPath:destination] error:&error]) [paths addObject:destination];
            }];
            if (access) [source stopAccessingSecurityScopedResource];
        }
        if (error) [NSFileManager.defaultManager removeItemAtPath:root error:NULL];
        dispatch_async(dispatch_get_main_queue(),^{
            if (error) self.error=error; else { self.paths=paths; self.path=paths.firstObject; }
            [self finish];
        });
    });
}
@end
static ELDocumentTransaction *ELPick(NSArray *types, NSString *exportPath, BOOL multiple) {
    ELDocumentTransaction *transaction=[ELDocumentTransaction new]; transaction.finished=dispatch_semaphore_create(0); transaction.exporting=exportPath!=nil; transaction.multiple=multiple;
    dispatch_async(dispatch_get_main_queue(),^{
        UIViewController *presenter=ElichikaHostPresenter();
        if (ELPendingDocument || !presenter || presenter.presentedViewController) {
            transaction.error=[NSError errorWithDomain:@"ElichikaDocument" code:1 userInfo:@{NSLocalizedDescriptionKey:@"Another dialog is open. Close it and try again."}]; [transaction finish]; return;
        }
        ELPendingDocument=transaction;
        UIDocumentPickerViewController *picker;
        if (exportPath) picker=[[UIDocumentPickerViewController alloc] initWithURLs:@[[NSURL fileURLWithPath:exportPath]] inMode:UIDocumentPickerModeExportToService];
        else {
            BOOL folder=[types containsObject:@"public.folder"];
            picker=[[UIDocumentPickerViewController alloc] initWithDocumentTypes:types.count ? types : @[@"public.data"]
                inMode:folder ? UIDocumentPickerModeOpen : UIDocumentPickerModeImport];
        }
        picker.delegate=transaction; picker.allowsMultipleSelection=multiple && !exportPath; picker.presentationController.delegate=transaction;
        [presenter presentViewController:picker animated:YES completion:nil];
    });
    dispatch_semaphore_wait(transaction.finished,DISPATCH_TIME_FOREVER); return transaction;
}
NSString *ElichikaHostImportDocument(NSArray<NSString *> *types,NSError **error) {
    return ElichikaHostImportDocuments(types,NO,error).firstObject;
}
NSArray<NSString *> *ElichikaHostImportDocuments(NSArray<NSString *> *types,BOOL multiple,NSError **error) {
    if (NSThread.isMainThread) { if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:3 userInfo:@{NSLocalizedDescriptionKey:@"Document selection must run off the UI thread."}]; return nil; }
    if (types.count>32) { if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:4 userInfo:@{NSLocalizedDescriptionKey:@"Too many document types."}]; return nil; }
    for (id type in types) if (![type isKindOfClass:NSString.class] || [type length]>128 ||
        [type rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound) {
        if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:4 userInfo:@{NSLocalizedDescriptionKey:@"Invalid document type."}]; return nil;
    }
    ELDocumentTransaction *transaction=ELPick(types,nil,multiple); if (error) *error=transaction.error; return transaction.paths;
}
BOOL ElichikaHostExportDocument(NSString *path,NSError **error) {
    if ([path rangeOfCharacterFromSet:[NSCharacterSet characterSetWithRange:NSMakeRange(0,1)]].location!=NSNotFound) {
        if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:5 userInfo:@{NSLocalizedDescriptionKey:@"Invalid export path."}]; return NO;
    }
    NSString *resolved=path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    BOOL allowed=NO;
    for (NSString *root in @[ELConfiguration[@"data_root"] ?: @"",ELConfiguration[@"documents_root"] ?: @""]) {
        NSString *canonical=root.stringByStandardizingPath.stringByResolvingSymlinksInPath;
        if (canonical.length && [resolved hasPrefix:[canonical stringByAppendingString:@"/"]]) allowed=YES;
    }
    if (NSThread.isMainThread || !allowed || ![NSFileManager.defaultManager fileExistsAtPath:resolved]) {
        if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:5 userInfo:@{NSLocalizedDescriptionKey:@"Choose an existing file in app storage."}]; return NO;
    }
    ELDocumentTransaction *transaction=ELPick(nil,resolved,NO); if (error) *error=transaction.error; return !transaction.error;
}
