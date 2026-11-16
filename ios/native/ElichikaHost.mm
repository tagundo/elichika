#import "ElichikaHost.h"
#import "ElichikaPythonRuntime.h"
#include "HostCore.hpp"
#include "SIFASProfile.h"
#include "RSAPublicKey.hpp"
#include "CandidatePolicy.hpp"
#import <WebKit/WebKit.h>
#import <Security/Security.h>
#import <CommonCrypto/CommonDigest.h>
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
static BOOL ELExperimentalArchivePending;
static BOOL ELStorageError;
#if ELICHIKA_SIMULATOR_PROBE
static void (^ELProbeStageHandler)(NSString *stage,NSTimeInterval entered);
static NSString *ELProbeJavaScriptFailure(NSString *context,NSError *error) {
    if (!error) return context;
    id exception=error.userInfo[@"WKJavaScriptExceptionMessage"];
    NSString *detail=[exception isKindOfClass:NSString.class] ? exception : error.localizedDescription;
    if (detail.length>512) detail=[detail substringToIndex:512];
    return [NSString stringWithFormat:@"%@ (%@ %ld): %@",context,error.domain,(long)error.code,detail ?: @""];
}
#endif
static NSTimer *ELPollTimer;
static UIWindow *ELPanelWindow;
static UIButton *ELMenuButton;
static __weak UIWindow *ELGameWindow;
static id ELMenuTarget(void);
static void ELRefreshMenu(void);
static NSDictionary *ELChooseAssetDirectory(NSError **error);
static NSDictionary *ELRestoreAssetDirectory(void);
static NSInteger ELDocumentChoice(NSString *title,NSString *message,NSArray<NSString *> *choices);
static NSURL *ELActiveLibraryURL;
static NSMutableArray<NSURL *> *ELHeldScopes;
static NSString *const ELAssetBookmarkKey=@"ElichikaAssetDirectoryBookmark";
static NSString *const ELAssetPathKey=@"ElichikaAssetDirectoryPath";
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
    NSString *active=ELConfiguration[@"library_root"] ?: @"";
    NSString *saved=[NSUserDefaults.standardUserDefaults stringForKey:ELAssetPathKey];
    if (!saved.length) saved=[[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject
        stringByAppendingPathComponent:@"Elichika"] stringByResolvingSymlinksInPath];
    return ELJSON(@{@"schema":@1,@"phase":[NSString stringWithUTF8String:core.phase()],
                    @"captured":@(core.captured()),@"game_started":@(core.started()),
                    @"real_backend_ready":@(core.ready()),@"foreground":@(core.foreground()),
                    @"gate_installed":@(ELGateInstalled),@"profile_supported":@(ELProfileSupported),
                    @"routing_prepared":@(ELRoutingPrepared),
                    @"server_button_visible":@(ELButtonPolicy().visible()),
                    @"archive_publication_pending":@(ELExperimentalArchivePending),
                    @"candidate_channel":ELExperimentalArchivePending ? @"EXPERIMENTAL_ARCHIVE_PENDING" : @"STANDARD",
                    @"core_only":ELConfiguration[@"core_only"] ?: @NO,
                    @"asset_directory":active,@"next_asset_directory":saved ?: @"",
                    @"external_asset_directory":ELConfiguration[@"external_asset_directory"] ?: @NO,
                    @"restart_required":@(active.length && ![active isEqual:saved]),
                    @"generation":@(core.generation()),@"error":ELHookError ?: [NSString stringWithUTF8String:core.error().c_str()]});
}

// A content controller retains its message handler. Keep that edge weak so
// retaining several documents does not create a controller/WebView cycle.
@interface ELPanelMessageHandler : NSObject <WKScriptMessageHandler>
@property(nonatomic,weak) id<WKScriptMessageHandler> target;
@end
@implementation ELPanelMessageHandler
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    [self.target userContentController:controller didReceiveScriptMessage:message];
}
@end

@interface ELPanelController : UIViewController <WKNavigationDelegate,WKScriptMessageHandler,WKUIDelegate,WKDownloadDelegate>
@property(nonatomic,strong) UILabel *statusLabel;
@property(nonatomic,strong) UIActivityIndicatorView *spinner;
@property(nonatomic,strong) UISegmentedControl *sections;
@property(nonatomic,strong) WKWebView *web;
@property(nonatomic,strong) UIView *webContainer;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,WKWebView *> *sectionWebViews;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,NSString *> *sectionTargets;
@property(nonatomic,strong) NSHashTable<WKWebView *> *failedPanels;
@property(nonatomic,strong) NSMapTable<WKWebView *,NSString *> *panelErrors;
@property(nonatomic,strong) UIButton *retry;
@property(nonatomic,strong) UIButton *storageRecovery;
@property(nonatomic,strong) UIBarButtonItem *buttonVisibility;
@property(nonatomic,strong) UILabel *candidateLabel;
@property(nonatomic,assign) BOOL initialPanelLoaded;
@property(nonatomic,strong) NSMapTable<WKDownload *,NSURL *> *downloads;
#if ELICHIKA_SIMULATOR_PROBE
@property(nonatomic,copy) void (^storageProbeReply)(NSDictionary *reply);
@property(nonatomic,strong) WKNavigation *storageProbeNavigation;
@property(nonatomic,copy) NSString *storageProbeService;
@property(nonatomic,copy) NSString *storageProbeOrigin;
@property(nonatomic,assign) NSUInteger storageProbeLaunch;
@property(nonatomic,assign) NSUInteger storageProbeGeneration;
@property(nonatomic,assign) NSInteger storageProbeHTTPStatus;
@property(nonatomic,copy) void (^managementProbeReply)(NSDictionary *reply);
@property(nonatomic,strong) WKNavigation *managementProbeNavigation;
@property(nonatomic,strong) NSMutableDictionary *managementProof;
@property(nonatomic,assign) NSUInteger managementProbeGeneration;
@property(nonatomic,assign) NSInteger managementProbeStep;
@property(nonatomic,assign) NSInteger managementProbeHTTPStatus;
@property(nonatomic,assign) BOOL retentionProbeRunning;
@property(nonatomic,assign) BOOL retainedDocumentsChecked;
- (void)probeStorageService:(NSString *)service port:(NSInteger)port launch:(NSUInteger)launch completion:(void (^)(NSDictionary *reply))completion;
- (void)probeManagement:(void (^)(NSDictionary *reply))completion;
#endif
- (WKWebView *)activateSection:(NSInteger)section;
- (WKNavigation *)loadPanelURL:(NSURL *)target;
- (void)refresh;
@end
static ELPanelController *ELPanel;
static void ELBeginBackend(void);
static void ELMaybeStartGame(void);
static void ELReceiveStatus(NSDictionary *status, uint64_t generation);
static BOOL ELIsPanelURL(NSURL *url);
static BOOL ELPanelReady(void) {
    return [ELRuntimeStatus[@"ready"] boolValue]
        && ELIsPanelURL([NSURL URLWithString:ELRuntimeStatus[@"admin_url"] ?: @""])
        && ELIsPanelURL([NSURL URLWithString:ELRuntimeStatus[@"tools_url"] ?: @""]);
}

static BOOL ELIsPanelURL(NSURL *url) {
    if (![url.scheme.lowercaseString isEqual:@"http"] || ![url.host isEqual:@"127.0.0.1"] || url.user || url.password) return NO;
    NSMutableSet *ports=[NSMutableSet setWithObject:@8080];
    for (NSString *key in @[@"admin_url",@"tools_url"]) {
        NSURL *panel=[NSURL URLWithString:ELRuntimeStatus[key] ?: @""];
        if ([panel.host isEqual:@"127.0.0.1"] && panel.port) [ports addObject:panel.port];
    }
    return url.port && [ports containsObject:url.port];
}
static NSURL *ELAccountsURL(void) {
    NSDictionary *server=[ELRuntimeStatus[@"server"] isKindOfClass:NSDictionary.class] ? ELRuntimeStatus[@"server"] : nil;
    if ([server[@"ready"] boolValue]) return [NSURL URLWithString:@"http://127.0.0.1:8080/webui/user"];
    NSURLComponents *parts=[NSURLComponents componentsWithString:ELRuntimeStatus[@"admin_url"] ?: @""];
    parts.path=@"/ios/server/webui/user/"; parts.fragment=nil;
    return parts.URL;
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
    _sections=[[UISegmentedControl alloc] initWithItems:@[@"Manage",@"Accounts",@"Content",@"Tools"]];
    _sections.selectedSegmentIndex=0;
    [_sections addTarget:self action:@selector(openSection) forControlEvents:UIControlEventValueChanged];
    _buttonVisibility=[[UIBarButtonItem alloc] initWithTitle:@"" style:UIBarButtonItemStylePlain target:self action:@selector(toggleServerButton)];
    self.navigationItem.leftBarButtonItem=_buttonVisibility;
    _buttonVisibility.accessibilityHint=ELButtonText(@"The choice is saved. Hold the upper-left corner for 2 seconds to reopen this panel.",
        @"선택은 저장됩니다. 왼쪽 위 모서리를 2초간 길게 누르면 이 패널을 다시 열 수 있습니다.",
        @"設定は保存されます。左上隅を2秒間長押しすると、このパネルを再び開けます。");
    UILabel *guidance=[UILabel new]; guidance.numberOfLines=0;
    guidance.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2]; guidance.textColor=UIColor.secondaryLabelColor;
    guidance.text=ELButtonText(@"Hide for MV. Hold upper-left 2s to reopen.",
        @"MV 중 숨기기 · 왼쪽 위 2초 길게 눌러 다시 열기",
        @"MV中は非表示に。左上を2秒長押しで再表示。");
    _candidateLabel=[UILabel new]; _candidateLabel.numberOfLines=0;
    _candidateLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2]; _candidateLabel.textColor=UIColor.systemOrangeColor;
    _candidateLabel.text=ELButtonText(@"Experimental · Archive pending · Device untested\nFiles: Elichika/packs",
        @"실험 빌드 · Archive 게시 대기 · 실기기 미검증\n파일: Elichika/packs",
        @"実験版 · Archive公開待ち · 実機未検証\nファイル: Elichika/packs");
    _sectionWebViews=[NSMutableDictionary new]; _sectionTargets=[NSMutableDictionary new];
    _failedPanels=NSHashTable.weakObjectsHashTable; _panelErrors=[NSMapTable weakToStrongObjectsMapTable];
    _webContainer=[UIView new];
    _downloads=[NSMapTable strongToStrongObjectsMapTable];
    _storageRecovery=[UIButton buttonWithType:UIButtonTypeSystem];
    [_storageRecovery setTitle:ELButtonText(@"Use default asset folder",@"기본 에셋 폴더 사용",@"既定の保存先を使用") forState:UIControlStateNormal];
    [_storageRecovery addTarget:self action:@selector(restoreStorage) forControlEvents:UIControlEventTouchUpInside];
    UIStackView *statusRow=[[UIStackView alloc] initWithArrangedSubviews:@[_spinner,_statusLabel]];
    statusRow.axis=UILayoutConstraintAxisHorizontal; statusRow.alignment=UIStackViewAlignmentCenter; statusRow.spacing=8;
    [_spinner setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
    UIStackView *head=[[UIStackView alloc] initWithArrangedSubviews:@[statusRow,_candidateLabel,_retry,_storageRecovery,guidance,_sections]];
    head.axis=UILayoutConstraintAxisVertical; head.spacing=6;
    head.translatesAutoresizingMaskIntoConstraints=NO; _webContainer.translatesAutoresizingMaskIntoConstraints=NO;
    [self.view addSubview:head]; [self.view addSubview:_webContainer];
    UILayoutGuide *safe=self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [head.topAnchor constraintEqualToAnchor:safe.topAnchor constant:8],
        [head.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [head.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [_webContainer.topAnchor constraintEqualToAnchor:head.bottomAnchor constant:8],
        [_webContainer.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [_webContainer.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [_webContainer.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor]]];
    [self activateSection:0]; [self refresh];
}
- (void)dealloc {
    for (WKWebView *web in _sectionWebViews.allValues)
        [web.configuration.userContentController removeScriptMessageHandlerForName:@"elichika"];
}
- (void)close { if (ELCore().started()) ELHidePanel(); }
- (void)toggleServerButton {
    ELButtonPolicy().toggle();
    [NSUserDefaults.standardUserDefaults setBool:ELButtonPolicy().visible() forKey:ELShowServerButtonKey];
    ELRefreshMenu(); [self refresh];
}
- (void)retrySetup {
    if ([_failedPanels containsObject:_web]) {
        NSNumber *section=@(_sections.selectedSegmentIndex); NSString *entry=_sectionTargets[section];
        NSURL *target=_web.URL ?: [NSURL URLWithString:entry ?: @""];
        if (ELIsPanelURL(target)) {
            [_failedPanels removeObject:_web]; [self loadPanelURL:target];
            if (entry) _sectionTargets[section]=entry; [self refresh];
        }
        return;
    }
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
- (void)restoreStorage {
    if (!ELStorageError || ELCore().started()) return;
    ELRestoreAssetDirectory(); ELStorageError=NO; ELConfiguration=nil; ELHookError=nil; ELBeginBackend();
}
- (void)refresh {
    if (!self.isViewLoaded) return;
    _candidateLabel.hidden=!ELExperimentalArchivePending;
    _buttonVisibility.title=ELButtonPolicy().visible()
        ? ELButtonText(@"Hide button",@"버튼 숨기기",@"ボタンを隠す")
        : ELButtonText(@"Show button",@"버튼 표시",@"ボタンを表示");
    _buttonVisibility.accessibilityLabel=ELButtonPolicy().visible()
        ? ELButtonText(@"Hide server button",@"서버 버튼 숨기기",@"サーバーボタンを隠す")
        : ELButtonText(@"Show server button",@"서버 버튼 표시",@"サーバーボタンを表示");
    NSString *error=ELHookError ?: [NSString stringWithUTF8String:ELCore().error().c_str()];
    _statusLabel.numberOfLines=ELCore().ready() && !error.length ? 1 : 0;
    if (error.length) _statusLabel.text=[NSString stringWithFormat:@"Setup could not finish.\n%@",error];
    else if (ELCore().started() && !ELCore().ready() && ELPanelReady()) {
        NSDictionary *server=ELRuntimeStatus[@"server"];
        NSString *state=[server[@"state"] isKindOfClass:NSString.class] ? server[@"state"] : server[@"phase"];
        NSString *serverError=ELMessage(server[@"error"]);
        _statusLabel.text=serverError.length ? [@"Server: " stringByAppendingString:serverError]
            : [NSString stringWithFormat:@"Server %@ · management available",state ?: @"stopped"];
    }
    else if (ELCore().ready()) _statusLabel.text=[ELConfiguration[@"core_only"] boolValue]
        ? @"Core server probe ready"
        : (ELExperimentalArchivePending ? ELButtonText(@"Local ready",@"로컬 서버 준비됨",@"ローカル準備完了")
           : ELButtonText(@"Ready",@"준비됨",@"準備完了"));
    else _statusLabel.text=ELProgress ?: @"Preparing your local server and tools…";
    BOOL busy=!ELCore().ready() && !error.length && !(ELCore().started() && ELPanelReady());
    if (busy) [_spinner startAnimating]; else [_spinner stopAnimating];
    BOOL pageFailed=[_failedPanels containsObject:_web];
    if (pageFailed) {
        _statusLabel.numberOfLines=0;
        NSString *notice=ELButtonText(@"This page stopped. Unsaved edits may be lost; retry reloads this page only.",
            @"이 페이지가 중지되었습니다. 저장 전 편집은 사라졌을 수 있습니다. 다시 시도하면 이 페이지만 새로 엽니다.",
            @"ページが停止しました。未保存の編集は失われた可能性があります。再試行でこのページだけを開き直します。");
        _statusLabel.text=[NSString stringWithFormat:@"%@\n%@",notice,[_panelErrors objectForKey:_web] ?: @""];
    }
    [_retry setTitle:pageFailed ? ELButtonText(@"Reload page",@"페이지 다시 열기",@"ページを再読み込み") : @"Retry setup" forState:UIControlStateNormal];
    _retry.hidden=!error.length && !pageFailed; _retry.enabled=ELProfileSupported && ELRoutingPrepared;
    _storageRecovery.hidden=!ELStorageError;
    _sections.enabled=elichika::managementAvailable(ELCore().started(),ELCore().ready(),ELPanelReady())
        && ![ELConfiguration[@"core_only"] boolValue];
    self.navigationItem.rightBarButtonItem.enabled=ELCore().started();
    if (_sections.enabled && !_initialPanelLoaded) { _initialPanelLoaded=YES; [self openSection]; }
}
- (void)openSection {
    NSString *url;
    if (_sections.selectedSegmentIndex==0) {
        NSURLComponents *parts=[NSURLComponents componentsWithString:ELRuntimeStatus[@"admin_url"] ?: @""];
        parts.path=@"/ios/"; parts.fragment=nil; url=parts.URL.absoluteString;
    }
    else if (_sections.selectedSegmentIndex==1) url=[ELAccountsURL() absoluteString];
    else if (_sections.selectedSegmentIndex==2) url=ELRuntimeStatus[@"admin_url"];
    else url=ELRuntimeStatus[@"tools_url"];
    NSURL *target=[NSURL URLWithString:url ?: @""];
    if (!ELIsPanelURL(target)) return;
    NSInteger section=_sections.selectedSegmentIndex;
    WKWebView *web=[self activateSection:section]; if (!web) return;
    // Internal navigation belongs to this retained document. Comparing its
    // original entry URL (including auth/origin) avoids reloading editors when
    // a tab is revisited, while a server-origin change still gets a fresh page.
    if (![_sectionTargets[@(section)] isEqual:target.absoluteString]) [self loadPanelURL:target];
    [self refresh];
}
- (WKWebView *)activateSection:(NSInteger)section {
    if (section<0 || section>3) return nil;
    NSNumber *key=@(section); WKWebView *web=_sectionWebViews[key];
    if (!web) {
        WKWebViewConfiguration *configuration=[WKWebViewConfiguration new];
        configuration.websiteDataStore=WKWebsiteDataStore.defaultDataStore;
        ELPanelMessageHandler *handler=[ELPanelMessageHandler new]; handler.target=self;
        [configuration.userContentController addScriptMessageHandler:handler name:@"elichika"];
        // A reply also carries this document's nonce: navigating the same WK
        // while a picker is open cannot resolve a newer document's request ID.
        NSString *script=@"(()=>{const p=new Map();let n=0;const d=(globalThis.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+'-'+Math.random();window.__elichikaNativeDocument=d;window.ElichikaIOS=Object.freeze({request:(action,options={})=>new Promise((resolve,reject)=>{const id=String(++n);p.set(id,{resolve,reject});window.webkit.messageHandlers.elichika.postMessage({...options,id,action,document:d});})});window.addEventListener('elichika-native-result',e=>{const x=e.detail;if(!x||x.document!==d)return;const j=p.get(x.id);if(j){p.delete(x.id);x.error?j.reject(Error(x.error)):j.resolve(x.result)}})})();";
        [configuration.userContentController addUserScript:[[WKUserScript alloc] initWithSource:script injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
        web=[[WKWebView alloc] initWithFrame:CGRectZero configuration:configuration];
        web.navigationDelegate=self; web.UIDelegate=self; web.translatesAutoresizingMaskIntoConstraints=NO;
        _sectionWebViews[key]=web; [_webContainer addSubview:web];
        [NSLayoutConstraint activateConstraints:@[[web.topAnchor constraintEqualToAnchor:_webContainer.topAnchor],
            [web.leadingAnchor constraintEqualToAnchor:_webContainer.leadingAnchor],
            [web.trailingAnchor constraintEqualToAnchor:_webContainer.trailingAnchor],
            [web.bottomAnchor constraintEqualToAnchor:_webContainer.bottomAnchor]]];
    }
    // Lazy, bounded to four documents. Hidden views stay attached and retain
    // JS/undo/form state; WebKit need not paint their layers while hidden.
    for (WKWebView *other in _sectionWebViews.allValues) other.hidden=(other!=web);
    _web=web; [_webContainer bringSubviewToFront:web];
    return web;
}
- (WKNavigation *)loadPanelURL:(NSURL *)target {
    if (!ELIsPanelURL(target)) return nil;
    NSInteger section=_sections.selectedSegmentIndex;
    WKWebView *web=[self activateSection:section]; if (!web) return nil;
    _sectionTargets[@(section)]=target.absoluteString; [_failedPanels removeObject:web]; [_panelErrors removeObjectForKey:web];
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:target];
    [request setValue:ELConfiguration[@"token"] forHTTPHeaderField:@"X-Elichika-Local-Access"];
    return [web loadRequest:request];
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)web {
    if (![_sectionWebViews.allValues containsObject:web]) return;
    [_failedPanels addObject:web];
    [_panelErrors setObject:ELButtonText(@"WebKit ended the page's content process.",@"WebKit이 페이지의 웹 프로세스를 종료했습니다.",@"WebKitがページのコンテンツプロセスを終了しました。") forKey:web];
    if (web==_web) [self refresh];
}
- (void)webView:(WKWebView *)web didStartProvisionalNavigation:(WKNavigation *)navigation {
    [_failedPanels removeObject:web]; [_panelErrors removeObjectForKey:web];
#if ELICHIKA_SIMULATOR_PROBE
    if (web==_web && _managementProbeReply && _managementProbeStep==2) _managementProbeNavigation=navigation;
#endif
}
- (void)webView:(WKWebView *)web didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (!([error.domain isEqual:NSURLErrorDomain] && error.code==NSURLErrorCancelled)) {
        [_failedPanels addObject:web];
        [_panelErrors setObject:[NSString stringWithFormat:@"%@ (%ld): %@",error.domain,(long)error.code,error.localizedDescription] forKey:web];
        if (web==_web) [self refresh];
    }
#if ELICHIKA_SIMULATOR_PROBE
    if (web==_web && _managementProbeReply && _managementProbeStep==2 &&
        [error.domain isEqual:NSURLErrorDomain] && error.code==NSURLErrorCancelled) return;
    if (web==_web && _managementProbeReply && navigation==_managementProbeNavigation) { [self finishManagementProbe:@"Management navigation failed."]; return; }
    if (web==_web && _storageProbeReply && navigation==_storageProbeNavigation)
        [self finishStorageProbe:[self failedStorageProbe:@"Management navigation failed."]];
#endif
}
- (void)webView:(WKWebView *)web didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    [self webView:web didFailNavigation:navigation withError:error];
}
#if ELICHIKA_SIMULATOR_PROBE
- (void)finishStorageProbe:(NSDictionary *)reply {
    void (^completion)(NSDictionary *)=_storageProbeReply;
    if (!completion) return;
    _storageProbeReply=nil; _storageProbeNavigation=nil; ++_storageProbeGeneration;
    completion(reply);
}
- (NSDictionary *)failedStorageProbe:(NSString *)message {
    return @{@"ready":@NO,@"persisted":@NO,@"seeded":@NO,
        @"origin_port":@([NSURL URLWithString:_storageProbeOrigin].port.integerValue),@"error":message};
}
- (void)probeStorageService:(NSString *)service port:(NSInteger)port launch:(NSUInteger)launch completion:(void (^)(NSDictionary *))completion {
    if (_storageProbeReply) { completion(@{@"ready":@NO,@"error":@"A management WebView probe is already active."}); return; }
    _storageProbeReply=[completion copy]; _storageProbeService=service; _storageProbeLaunch=launch;
    _storageProbeOrigin=[NSString stringWithFormat:@"http://127.0.0.1:%ld",(long)port];
    _storageProbeHTTPStatus=0; NSUInteger generation=++_storageProbeGeneration;
    NSString *url=ELRuntimeStatus[[service stringByAppendingString:@"_url"]];
    NSURL *target=[NSURL URLWithString:url ?: @""];
    if (![target.scheme isEqual:@"http"] || ![target.host isEqual:@"127.0.0.1"] || target.port.integerValue!=port ||
        !_web.configuration.websiteDataStore.persistent) {
        [self finishStorageProbe:[self failedStorageProbe:@"Management origin or persistent data store does not match."]]; return;
    }
    _sections.selectedSegmentIndex=[service isEqual:@"admin"] ? 2 : 3;
    _storageProbeNavigation=[self loadPanelURL:target];
    if (!_storageProbeNavigation) { [self finishStorageProbe:[self failedStorageProbe:@"Could not navigate the actual management WebView."]]; return; }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if (self.storageProbeReply && self.storageProbeGeneration==generation)
            [self finishStorageProbe:[self failedStorageProbe:@"Management WebView storage probe timed out."]];
    });
}
- (void)webView:(WKWebView *)web didFinishNavigation:(WKNavigation *)navigation {
    if (web==_web && _managementProbeReply && navigation==_managementProbeNavigation) {
        // The existing Accounts hub redirects to its login picker in JavaScript
        // when this WebView has no selected account. Follow that real navigation.
        if (_managementProbeStep==2 && ![web.URL.path isEqual:@"/ios/server/webui/user/login"]) return;
        if (_managementProbeHTTPStatus!=200) { [self finishManagementProbe:@"The management page did not return HTTP 200."]; return; }
        _managementProof[@"page_loaded"]=@YES; [self pollManagementProbe]; return;
    }
    if (web!=_web || !_storageProbeReply || navigation!=_storageProbeNavigation) return;
    if (_storageProbeHTTPStatus!=200) { [self finishStorageProbe:[self failedStorageProbe:@"The real management page did not return HTTP 200."]]; return; }
    NSDictionary *arguments=@{@"origin":_storageProbeOrigin,@"service":_storageProbeService,@"launch":@(_storageProbeLaunch)};
    NSString *script=[NSString stringWithFormat:@"(()=>{const a=%@,k='elichika.simulator.preferences-persistence.v1',v=a.service+'-v1',p=localStorage.getItem(k);let seeded=false;if(a.launch===1){localStorage.setItem(k,v);seeded=localStorage.getItem(k)===v;}return{origin_matches:location.origin===a.origin,prior_present:p!==null,persisted:a.launch===2&&p===v,seeded};})()",ELJSON(arguments)];
    NSUInteger generation=_storageProbeGeneration;
    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error) {
        if (!self.storageProbeReply || self.storageProbeGeneration!=generation) return;
        if (error || ![value isKindOfClass:NSDictionary.class]) {
            [self finishStorageProbe:[self failedStorageProbe:ELProbeJavaScriptFailure(@"Management localStorage evaluation failed.",error)]]; return;
        }
        BOOL persisted=[value[@"persisted"] boolValue],seeded=[value[@"seeded"] boolValue];
        BOOL ready=[value[@"origin_matches"] boolValue] && web.configuration.websiteDataStore.persistent &&
            (self.storageProbeLaunch==1 ? seeded && ![value[@"prior_present"] boolValue] : persisted);
        NSDictionary *reply=@{@"ready":@(ready),@"persisted":@(persisted),@"seeded":@(seeded),
            @"origin_port":@([NSURL URLWithString:self.storageProbeOrigin].port.integerValue)};
        // The next process verifies persistence; this bounded asynchronous
        // interval merely lets WebKit finish its ordinary disk scheduling.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,self.storageProbeLaunch==1 ? NSEC_PER_SEC : 0),dispatch_get_main_queue(),^{
            if (self.storageProbeReply && self.storageProbeGeneration==generation) [self finishStorageProbe:reply];
        });
    }];
}
- (void)finishManagementProbe:(NSString *)error {
    void (^completion)(NSDictionary *)=_managementProbeReply; if (!completion) return;
    _managementProbeReply=nil; _managementProbeNavigation=nil; _retentionProbeRunning=NO; ++_managementProbeGeneration;
    _managementProof[@"error"]=error.length ? (id)error : (id)@NO;
    BOOL ready=!error.length;
    for (NSString *key in @[@"actual_management_webview",@"page_loaded",@"javascript_ready",@"state_fetch",@"controls_present",@"native_binding",@"retained_panels",@"go_stopped",@"offline_accounts",@"server_restarted"])
        ready=ready && [_managementProof[key] boolValue];
    _managementProof[@"ready"]=@(ready); completion([_managementProof copy]);
}
- (void)probeRetainedPanels {
    // This is a real WK document-lifetime and reply-routing check, not a 3D
    // render test. Storage probing already visited the Content and Tools pages.
    NSUInteger generation=_managementProbeGeneration;
    WKWebView *manage=_sectionWebViews[@0],*content=_sectionWebViews[@2],*tools=_sectionWebViews[@3];
    if (_web!=manage || !manage || !content || !tools || manage==content || manage==tools || content==tools ||
        manage.loading || content.loading || tools.loading || !ELIsPanelURL(manage.URL) ||
        !ELIsPanelURL(content.URL) || !ELIsPanelURL(tools.URL)) {
        [self finishManagementProbe:@"The lazy retained management documents were unavailable."]; return;
    }
    _retentionProbeRunning=YES;
    NSString *token=NSUUID.UUID.UUIDString;
    NSDictionary *arguments=@{@"token":token};
    NSString *seed=[NSString stringWithFormat:@"(()=>{const a=%@,field=document.createElement('textarea');field.id='elichika-retention-draft';field.hidden=true;field.value='unsaved draft';document.body.appendChild(field);const p={token:a.token,undo:[{vertex:7,before:1,after:2}],selection:[7,11],pagehide:0,reply:false};window.__elichikaRetentionProbe=p;window.addEventListener('pagehide',()=>++p.pagehide);return true;})()",ELJSON(arguments)];
    NSString *check=[NSString stringWithFormat:@"(()=>{const a=%@,p=window.__elichikaRetentionProbe,f=document.getElementById('elichika-retention-draft');return{same:!!p&&p.token===a.token&&p.pagehide===0&&p.undo.length===1&&p.undo[0].after===2&&p.selection.join(',')==='7,11'&&!!f&&f.value==='unsaved draft',reply:!!p&&p.reply===true};})()",ELJSON(arguments)];
    [manage evaluateJavaScript:seed completionHandler:^(id value,NSError *error) {
        if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
        if (error || ![value isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Could not seed the actual management document's unsaved state.",error)]; return; }
        [content evaluateJavaScript:seed completionHandler:^(id contentSeed,NSError *contentError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (contentError || ![contentSeed isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Could not seed the actual Content document's unsaved state.",contentError)]; return; }
        self.sections.selectedSegmentIndex=3; [self openSection];
        if (self.web!=tools) { [self finishManagementProbe:@"Revisiting Tools replaced its retained WebView."]; return; }
        NSString *toolSeed=[seed stringByAppendingString:@";window.ElichikaIOS.request('__probe_deferred_status').then(v=>{window.__elichikaRetentionProbe.reply=v.returned_to_origin===true&&v.other_tab_active===true});true;"];
        [tools evaluateJavaScript:toolSeed completionHandler:^(id seeded,NSError *seedError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (seedError || ![seeded isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Could not seed the actual Tools document and deferred native request.",seedError)]; return; }
            self.sections.selectedSegmentIndex=0; [self openSection];
            if (self.web!=manage) { [self finishManagementProbe:@"Revisiting Manage replaced its retained WebView."]; return; }
            self.sections.selectedSegmentIndex=2; [self openSection];
            if (self.web!=content) { [self finishManagementProbe:@"Revisiting Content replaced its retained WebView."]; return; }
            ELHidePanel(); ElichikaHostShowManagement();
            if (self.web!=content || ![content isDescendantOfView:self.view] || content.hidden || ELPanelWindow.hidden) {
                [self finishManagementProbe:@"Hiding and reopening management replaced the active document."]; return;
            }
            // The deferred native reply must reach hidden Tools, while Content
            // is active, rather than the current alias or a different document.
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC/5),dispatch_get_main_queue(),^{
                if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
                [self pollRetainedTools:tools manage:manage script:check generation:generation];
            });
        }];
        }];
    }];
}
- (void)pollRetainedTools:(WKWebView *)tools manage:(WKWebView *)manage script:(NSString *)check generation:(NSUInteger)generation {
    if (!_managementProbeReply || _managementProbeGeneration!=generation) return;
    // Keep Content active until the delayed reply reaches hidden Tools. Poll
    // under the original management deadline; a busy WebKit queue cannot turn
    // a fixed sleep into either a false PASS or an unnecessary failure.
    [tools evaluateJavaScript:check completionHandler:^(id retained,NSError *error) {
        if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
        if (error || ![retained isKindOfClass:NSDictionary.class] || ![retained[@"same"] isEqual:@YES]) {
            [self finishManagementProbe:ELProbeJavaScriptFailure(@"Tools lost its unsaved document state while another tab was active.",error)]; return;
        }
        if (![retained[@"reply"] isEqual:@YES]) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/4),dispatch_get_main_queue(),^{
                [self pollRetainedTools:tools manage:manage script:check generation:generation];
            }); return;
        }
        self.sections.selectedSegmentIndex=3; [self openSection];
        if (self.web!=tools) { [self finishManagementProbe:@"Tools was recreated after hiding and reopening management."]; return; }
        [tools evaluateJavaScript:check completionHandler:^(id visible,NSError *visibleError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (visibleError || ![visible isKindOfClass:NSDictionary.class] || ![visible[@"same"] isEqual:@YES] || ![visible[@"reply"] isEqual:@YES]) {
                [self finishManagementProbe:ELProbeJavaScriptFailure(@"Revisiting Tools discarded its document state or deferred native reply.",visibleError)]; return;
            }
            self.sections.selectedSegmentIndex=0; [self openSection];
            if (self.web!=manage) { [self finishManagementProbe:@"The management document was recreated after revisiting other tabs."]; return; }
            [manage evaluateJavaScript:check completionHandler:^(id preserved,NSError *preservedError) {
                if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
                if (preservedError || ![preserved isKindOfClass:NSDictionary.class] || ![preserved[@"same"] isEqual:@YES]) {
                    [self finishManagementProbe:ELProbeJavaScriptFailure(@"Manage lost its unsaved document state after tab switching.",preservedError)]; return;
                }
                WKWebView *content=self.sectionWebViews[@2];
                [content evaluateJavaScript:check completionHandler:^(id contentState,NSError *contentError) {
                    if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
                    if (contentError || ![contentState isKindOfClass:NSDictionary.class] || ![contentState[@"same"] isEqual:@YES]) {
                        [self finishManagementProbe:ELProbeJavaScriptFailure(@"Content lost its unsaved document state after tab switching.",contentError)]; return;
                    }
                    self.retentionProbeRunning=NO; self.retainedDocumentsChecked=YES;
                    [self pollManagementProbe];
                }];
            }];
        }];
    }];
}
- (void)probeRetainedAccounts {
    NSUInteger generation=_managementProbeGeneration;
    WKWebView *accounts=_sectionWebViews[@1];
    if (!accounts || accounts!=_web || accounts.loading || ![accounts.URL.path isEqual:@"/ios/server/webui/user/login"]) {
        [self finishManagementProbe:@"The stopped-server Accounts document was unavailable for retention verification."]; return;
    }
    NSString *token=NSUUID.UUID.UUIDString;
    NSDictionary *arguments=@{@"token":token};
    NSString *seed=[NSString stringWithFormat:@"(()=>{const a=%@,f=document.createElement('input');f.hidden=true;f.id='elichika-retention-account-draft';f.value='unsaved account draft';document.body.appendChild(f);window.__elichikaAccountRetention={token:a.token,pagehide:0};window.addEventListener('pagehide',()=>++window.__elichikaAccountRetention.pagehide);return true;})()",ELJSON(arguments)];
    [accounts evaluateJavaScript:seed completionHandler:^(id value,NSError *error) {
        if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
        if (error || ![value isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Could not seed the actual Accounts document's unsaved form state.",error)]; return; }
        for (NSNumber *section in @[@0,@2,@3,@1]) {
            WKWebView *retained=self.sectionWebViews[section];
            self.sections.selectedSegmentIndex=section.integerValue; [self openSection];
            if (self.web!=retained) { [self finishManagementProbe:@"A management tab was recreated during the Accounts retention check."]; return; }
        }
        NSString *check=[NSString stringWithFormat:@"(()=>{const a=%@,p=window.__elichikaAccountRetention,f=document.getElementById('elichika-retention-account-draft');return !!p&&p.token===a.token&&p.pagehide===0&&!!f&&f.value==='unsaved account draft';})()",ELJSON(arguments)];
        [accounts evaluateJavaScript:check completionHandler:^(id retained,NSError *retainedError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (retainedError || ![retained isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Accounts lost its unsaved form state after visiting the other three tabs.",retainedError)]; return; }
            self.sections.selectedSegmentIndex=0; [self openSection];
            if (!self.web || self.web!=self.sectionWebViews[@0] || !self.retainedDocumentsChecked) {
                [self finishManagementProbe:@"Could not return to retained management after the offline Accounts check."]; return;
            }
            self.managementProof[@"retained_panels"]=@YES; self.managementProbeNavigation=nil;
            [self pollManagementProbe];
        }];
    }];
}
- (void)pollManagementProbe {
    if (!_managementProbeReply) return;
    if (_managementProbeStep==0 && !_retainedDocumentsChecked) {
        if (!_retentionProbeRunning) [self probeRetainedPanels];
        return;
    }
    NSUInteger generation=_managementProbeGeneration;
    BOOL nativeStopped=ELCore().started() && !ELCore().ready() && ELPanelReady() && _sections.enabled;
    NSDictionary *arguments=@{@"step":@(_managementProbeStep),@"allowStart":@(nativeStopped)};
    NSString *script=_managementProbeStep==2
        ? @"if(location.pathname!=='/ios/server/webui/user/login')return{waiting:true};"
          "const picker=document.getElementById('native-account-picker'),list=document.getElementById('native-account-list');"
          "if(!picker||!list||picker.hidden||document.body.dataset.elichikaLocalAccess!=='true')return{waiting:true};"
          "const u=new URL('/ios/server/webui/user/native_accounts',location.href);u.search=location.search;"
          "const response=await fetch(u,{cache:'no-store'});if(!response.ok)return{error:true};"
          "const data=await response.json();if(!Array.isArray(data.accounts)||data.accounts.some(a=>!Number.isInteger(a.user_id)||!Number.isInteger(a.rank)))return{error:true};"
          "if(list.querySelectorAll('button[data-user-id]').length!==data.accounts.length)return{waiting:true};"
          "const native=await window.ElichikaIOS.request('status');return{offline_accounts:native.real_backend_ready===false};"
        : @"if(!window.ElichikaManagementReady||typeof window.ElichikaManagementProbe!=='function')return{waiting:true};"
        "const p=await window.ElichikaManagementProbe();if(p.error)return{error:true};"
        "const s=window.ElichikaManagementProof||{};const r={javascript_ready:!!p.javascript_ready,state_fetch:!!p.state_fetch,controls_present:!!p.controls_present,native_binding:!!p.native_binding,server_ready:!!p.server_ready};"
        "if(step===0){const b=document.getElementById('server-stop');if(!b||b.disabled||!r.server_ready)return{waiting:true};b.click();r.requested='stop';}"
        "else if(step===1){if(r.server_ready||s.server_state!=='stopped'||!allowStart)return{waiting:true};r.requested='offline_accounts';}"
        "else if(step===3){if(r.server_ready||s.server_state!=='stopped'||!allowStart)return{waiting:true};const b=document.getElementById('server-start');if(!b||b.disabled)return{waiting:true};b.click();r.requested='start';}"
        "return r;";
    if (@available(iOS 14.0,*)) {
        WKWebView *origin=_web;
        [origin callAsyncJavaScript:script arguments:arguments inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value,NSError *error){
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (self.web!=origin) { [self finishManagementProbe:@"The active management document changed during its API probe."]; return; }
            if (error || ![value isKindOfClass:NSDictionary.class] || [value[@"error"] boolValue]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"The actual management JavaScript/API probe failed.",error)]; return; }
            if (![value[@"waiting"] boolValue]) {
                if (self.managementProbeStep==2) {
                    if (![value[@"offline_accounts"] isEqual:@YES] || ELCore().ready() || !ELPanelReady() || !self.sections.enabled) {
                        [self finishManagementProbe:@"The stopped-server Accounts page or native account directory was unavailable."]; return;
                    }
                    self.managementProof[@"offline_accounts"]=@YES; self.managementProbeStep=3;
                    [self probeRetainedAccounts]; return;
                }
                for (NSString *key in @[@"javascript_ready",@"state_fetch",@"controls_present",@"native_binding"]) {
                    if (![value[key] boolValue]) { [self finishManagementProbe:@"Management controls or native binding were unavailable."]; return; }
                    self.managementProof[key]=@YES;
                }
                if (self.managementProbeStep==0 && [value[@"requested"] isEqual:@"stop"]) self.managementProbeStep=1;
                else if (self.managementProbeStep==1 && [value[@"requested"] isEqual:@"offline_accounts"]) {
                    self.managementProof[@"go_stopped"]=@YES; self.managementProbeStep=2; self.sections.selectedSegmentIndex=1;
                    self.managementProbeHTTPStatus=0; self.managementProbeNavigation=[self loadPanelURL:ELAccountsURL()];
                    if (!self.managementProbeNavigation) [self finishManagementProbe:@"Could not open Accounts while the game server was stopped."];
                    return;
                }
                else if (self.managementProbeStep==3 && [value[@"requested"] isEqual:@"start"]) self.managementProbeStep=4;
                else if (self.managementProbeStep==4 && [value[@"server_ready"] boolValue] && ELCore().ready() && self.sections.enabled) {
                    self.managementProof[@"server_restarted"]=@YES; [self finishManagementProbe:nil]; return;
                }
            }
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/4),dispatch_get_main_queue(),^{
                if (self.managementProbeReply && self.managementProbeGeneration==generation) [self pollManagementProbe];
            });
        }];
    } else [self finishManagementProbe:@"The test runtime lacks asynchronous WebKit evaluation."];
}
- (void)probeManagement:(void (^)(NSDictionary *))completion {
    if (_managementProbeReply || _storageProbeReply) { completion(@{@"ready":@NO,@"error":@"A management WebView probe is already running."}); return; }
    _managementProbeReply=[completion copy]; NSUInteger generation=++_managementProbeGeneration;
    _managementProbeStep=0; _managementProbeHTTPStatus=0; _retainedDocumentsChecked=NO; _retentionProbeRunning=NO;
    _managementProof=[@{@"schema":@1,@"ready":@NO,@"actual_management_webview":@(_web && [_web isDescendantOfView:self.view] && _web.navigationDelegate==self),
        @"page_loaded":@NO,@"javascript_ready":@NO,@"state_fetch":@NO,@"controls_present":@NO,@"native_binding":@NO,@"retained_panels":@NO,@"go_stopped":@NO,@"offline_accounts":@NO,@"server_restarted":@NO,@"error":@NO} mutableCopy];
    NSURLComponents *parts=[NSURLComponents componentsWithString:ELRuntimeStatus[@"admin_url"] ?: @""];
    parts.path=@"/ios/"; parts.fragment=nil; _sections.selectedSegmentIndex=0;
    _managementProbeNavigation=[self loadPanelURL:parts.URL];
    if (!_managementProbeNavigation) { [self finishManagementProbe:@"The actual management page URL was unavailable."]; return; }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,115*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if (self.managementProbeReply && self.managementProbeGeneration==generation) [self finishManagementProbe:@"Management stop/start proof exceeded its fixed deadline."];
    });
}
#endif
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    (void)web;
    NSURL *url=action.request.URL;
    if (ELIsPanelURL(url) || [url.absoluteString isEqual:@"about:blank"] || [url.scheme isEqual:@"blob"]) {
        if (@available(iOS 14.5,*)) { if (action.shouldPerformDownload) { decision(WKNavigationActionPolicyDownload); return; } }
        decision(WKNavigationActionPolicyAllow); return;
    }
    decision(WKNavigationActionPolicyCancel);
    if (action.navigationType==WKNavigationTypeLinkActivated && [url.scheme.lowercaseString isEqual:@"https"])
        [UIApplication.sharedApplication openURL:url options:@{} completionHandler:nil];
}
- (void)webView:(WKWebView *)web decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decision {
#if ELICHIKA_SIMULATOR_PROBE
    if (web==_web && _storageProbeReply && response.forMainFrame && [response.response isKindOfClass:NSHTTPURLResponse.class])
        _storageProbeHTTPStatus=((NSHTTPURLResponse *)response.response).statusCode;
    if (web==_web && _managementProbeReply && response.forMainFrame && [response.response isKindOfClass:NSHTTPURLResponse.class])
        _managementProbeHTTPStatus=((NSHTTPURLResponse *)response.response).statusCode;
#endif
    NSURL *url=response.response.URL;
    if (!ELIsPanelURL(url) && ![url.scheme isEqual:@"blob"]) { decision(WKNavigationResponsePolicyCancel); return; }
    BOOL attachment=NO;
    if ([response.response isKindOfClass:NSHTTPURLResponse.class]) {
        NSString *value=[(NSHTTPURLResponse *)response.response valueForHTTPHeaderField:@"Content-Disposition"];
        attachment=[[value lowercaseString] hasPrefix:@"attachment"];
    }
    if (@available(iOS 14.5,*)) {
        if (!response.canShowMIMEType || attachment) { decision(WKNavigationResponsePolicyDownload); return; }
    }
    decision(WKNavigationResponsePolicyAllow);
}
- (void)webView:(WKWebView *)web navigationAction:(WKNavigationAction *)action didBecomeDownload:(WKDownload *)download API_AVAILABLE(ios(14.5)) {
    (void)web; (void)action; download.delegate=self;
}
- (void)webView:(WKWebView *)web navigationResponse:(WKNavigationResponse *)response didBecomeDownload:(WKDownload *)download API_AVAILABLE(ios(14.5)) {
    (void)web; (void)response; download.delegate=self;
}
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response suggestedFilename:(NSString *)suggested completionHandler:(void (^)(NSURL *))completion API_AVAILABLE(ios(14.5)) {
    if (_downloads.count>=8 || response.expectedContentLength>2LL*1024*1024*1024) { completion(nil); return; }
    NSString *name=suggested.lastPathComponent;
    if (!name.length || [name isEqual:@"."] || [name isEqual:@".."] || name.length>240 ||
        [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound) name=@"download.bin";
    NSString *root=[[ELConfiguration[@"documents_root"] stringByAppendingPathComponent:@"Elichika/exports"] stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    NSError *error=nil;
    if (![NSFileManager.defaultManager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:&error]) { completion(nil); return; }
    NSURL *target=[NSURL fileURLWithPath:[root stringByAppendingPathComponent:name]];
    [_downloads setObject:target forKey:download]; completion(target);
}
- (void)downloadDidFinish:(WKDownload *)download API_AVAILABLE(ios(14.5)) {
    NSURL *file=[_downloads objectForKey:download]; [_downloads removeObjectForKey:download];
    if (!file) return;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
        NSError *error=nil; ElichikaHostExportDocument(file.path,&error);
        if (error && error.code!=2) dispatch_async(dispatch_get_main_queue(),^{
            UIAlertController *alert=[UIAlertController alertControllerWithTitle:@"Save download" message:error.localizedDescription preferredStyle:UIAlertControllerStyleAlert];
            [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
            [ElichikaHostPresenter() presentViewController:alert animated:YES completion:nil];
        });
    });
}
- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)data API_AVAILABLE(ios(14.5)) {
    (void)error; (void)data; NSURL *file=[_downloads objectForKey:download]; [_downloads removeObjectForKey:download];
    if (file) [NSFileManager.defaultManager removeItemAtURL:file error:NULL];
}
- (WKWebView *)webView:(WKWebView *)web createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)features {
    (void)configuration; (void)features; NSURL *url=action.request.URL;
    if (ELIsPanelURL(url) || [url.scheme isEqual:@"blob"]) [web loadRequest:action.request];
    else if ([url.scheme.lowercaseString isEqual:@"https"]) [UIApplication.sharedApplication openURL:url options:@{} completionHandler:nil];
    return nil;
}
- (void)webView:(WKWebView *)web runJavaScriptAlertPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(void))completion {
    (void)web; if (!ELIsPanelURL(frame.request.URL)) { completion(); return; }
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:@"Elichika" message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){ (void)action; completion(); }]];
    [ElichikaHostPresenter() presentViewController:alert animated:YES completion:nil];
}
- (void)webView:(WKWebView *)web runJavaScriptConfirmPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(BOOL))completion {
    (void)web; if (!ELIsPanelURL(frame.request.URL)) { completion(NO); return; }
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:@"Elichika" message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:^(UIAlertAction *action){ (void)action; completion(NO); }]];
    [alert addAction:[UIAlertAction actionWithTitle:@"Continue" style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){ (void)action; completion(YES); }]];
    [ElichikaHostPresenter() presentViewController:alert animated:YES completion:nil];
}
- (void)webView:(WKWebView *)web runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))completion {
    (void)web;
    if (!frame.isMainFrame || !ELIsPanelURL(frame.request.URL)) { completion(nil); return; }
    if (@available(iOS 18.4,*)) {
        BOOL multiple=parameters.allowsMultipleSelection,folders=parameters.allowsDirectories;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error=nil; NSArray<NSString *> *paths=ElichikaHostImportDocuments(folders ? @[@"public.folder"] : @[@"public.item"],multiple,&error);
            NSMutableArray<NSURL *> *urls=[NSMutableArray new]; for (NSString *path in paths) [urls addObject:[NSURL fileURLWithPath:path]];
            dispatch_async(dispatch_get_main_queue(),^{ completion(error ? nil : urls); });
        });
    } else completion(nil);
}
- (void)reply:(NSString *)identifier inWebView:(WKWebView *)web document:(NSString *)document result:(id)result error:(NSString *)error {
    if (!web || ![_sectionWebViews.allValues containsObject:web]) return;
    NSDictionary *value=@{@"id":identifier,@"document":document,@"result":result ?: NSNull.null,@"error":error ?: @""};
    NSString *javascript=[NSString stringWithFormat:@"(()=>{const v=%@;if(window.__elichikaNativeDocument===v.document)window.dispatchEvent(new CustomEvent('elichika-native-result',{detail:v}));})();",ELJSON(value)];
    [web evaluateJavaScript:javascript completionHandler:nil];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)controller;
    if (!message.frameInfo.isMainFrame || !ELIsPanelURL(message.frameInfo.request.URL) || ![message.body isKindOfClass:NSDictionary.class]) return;
    WKWebView *source=message.webView;
    if (!source || ![_sectionWebViews.allValues containsObject:source]) return;
    NSDictionary *request=message.body;
    NSString *identifier=request[@"id"],*action=request[@"action"],*document=request[@"document"];
    if (![identifier isKindOfClass:NSString.class] || identifier.length>64 || ![action isKindOfClass:NSString.class] ||
        ![document isKindOfClass:NSString.class] || !document.length || document.length>128) return;
#if ELICHIKA_SIMULATOR_PROBE
    if ([action isEqual:@"__probe_deferred_status"]) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/5),dispatch_get_main_queue(),^{
            [self reply:identifier inWebView:source document:document result:@{@"returned_to_origin":@YES,@"other_tab_active":@(self.web!=source)} error:nil];
        }); return;
    }
#endif
    if ([action isEqual:@"status"]) {
        [self reply:identifier inWebView:source document:document result:[NSJSONSerialization JSONObjectWithData:[ElichikaHostDiagnosticsJSON() dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL] error:nil]; return;
    }
    if ([action isEqual:@"chooseAssetDirectory"]) {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error=nil; NSDictionary *result=ELChooseAssetDirectory(&error);
            dispatch_async(dispatch_get_main_queue(),^{
                if (error.code==2 && [error.domain isEqual:@"ElichikaDocument"]) [self reply:identifier inWebView:source document:document result:@{@"cancelled":@YES} error:nil];
                else [self reply:identifier inWebView:source document:document result:result error:error.localizedDescription];
            });
        }); return;
    }
    if ([action isEqual:@"restoreDefaultAssetDirectory"]) {
        [self reply:identifier inWebView:source document:document result:ELRestoreAssetDirectory() error:nil]; return;
    }
    if ([action isEqual:@"import"]) {
        NSArray *types=[request[@"types"] isKindOfClass:NSArray.class] ? request[@"types"] : @[@"public.data"];
        BOOL multiple=[request[@"multiple"] boolValue];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error=nil; NSArray *paths=ElichikaHostImportDocuments(types,multiple,&error);
            id result=multiple ? paths : paths.firstObject;
            dispatch_async(dispatch_get_main_queue(),^{
                if (error.code==2 && [error.domain isEqual:@"ElichikaDocument"]) [self reply:identifier inWebView:source document:document result:@{@"cancelled":@YES} error:nil];
                else [self reply:identifier inWebView:source document:document result:result error:error.localizedDescription];
            });
        }); return;
    }
    if ([action isEqual:@"export"] && [request[@"path"] isKindOfClass:NSString.class]) {
        NSString *path=request[@"path"];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
            NSError *error=nil; BOOL done=ElichikaHostExportDocument(path,&error);
            dispatch_async(dispatch_get_main_queue(),^{
                if (error.code==2 && [error.domain isEqual:@"ElichikaDocument"]) [self reply:identifier inWebView:source document:document result:@{@"cancelled":@YES} error:nil];
                else [self reply:identifier inWebView:source document:document result:@(done) error:error.localizedDescription];
            });
        }); return;
    }
    [self reply:identifier inWebView:source document:document result:nil error:@"Unknown native action."];
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

static BOOL ELReadCandidateMode(NSString *resources,NSString **error) {
    NSDictionary *info=NSBundle.mainBundle.infoDictionary;
    NSString *channel=@"EXPERIMENTAL_ARCHIVE_PENDING";
    NSString *pin=@"594a87c306f0d6ccb12b9cbcd2c505045cb17f6bb8cdcc063f956580aae289a9";
    NSString *path=[resources stringByAppendingPathComponent:@"experimental-capability.json"];
    id declaredChannel=info[@"ElichikaUnifiedCandidateChannel"];
    BOOL present=[NSFileManager.defaultManager fileExistsAtPath:path] ||
        ([declaredChannel isKindOfClass:NSString.class] && [declaredChannel hasPrefix:@"EXPERIMENTAL"]) ||
        [info[@"ElichikaArchivePublicationStatus"] isEqual:@"INCOMPLETE"] ||
        [info[@"ElichikaArchiveConfigSHA256"] isEqual:pin];
    if (!present) { ELExperimentalArchivePending=NO; return YES; }
    BOOL infoMatches=[info[@"ElichikaUnifiedCandidateChannel"] isEqual:channel] &&
        [info[@"ElichikaArchivePublicationStatus"] isEqual:@"INCOMPLETE"] &&
        [info[@"ElichikaArchiveConfigSHA256"] isEqual:pin] &&
        [info[@"ElichikaUnifiedCandidateStatus"] isEqual:@"ARCHIVE_PENDING_UNTESTED_DEVICE_REQUIRES_USER_SIGNING"];
    NSData *raw=[NSData dataWithContentsOfFile:path options:0 error:NULL];
    id capability=raw.length && raw.length<=32768 ? [NSJSONSerialization JSONObjectWithData:raw options:0 error:NULL] : nil;
    NSDictionary *pending=@{@"schema":@1,@"status":@"INCOMPLETE",@"requested_total":@42830,
        @"catalog_url":NSNull.null,@"catalog_sha256":NSNull.null,
        @"target_manifest_sha256":@"e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c"};
    NSDictionary *runtime=@{@"target":@"device",@"python_abi":@"3.13",@"experimental_device":@YES,
        @"simulator_probe_only":@NO,@"core_only":@NO,@"toolset_complete":@YES,@"archive_publication_guard_passed":@NO};
    BOOL capabilityMatches=[capability isKindOfClass:NSDictionary.class] && [capability[@"schema"] isEqual:@1] &&
        [capability[@"channel"] isEqual:channel] && [capability[@"archive_state"] isEqual:pending] &&
        [capability[@"archive_config"] isEqual:@{@"bytes":@217,@"sha256":pin}] &&
        [capability[@"new_archive_publication_ready"] isEqual:@NO] &&
        [capability[@"existing_user_packs_supported"] isEqual:@YES] && [capability[@"runtime"] isEqual:runtime];
    NSData *archive=[NSData dataWithContentsOfFile:[resources stringByAppendingPathComponent:@"python-app/archive-hosted-catalog.json"] options:0 error:NULL];
    BOOL sourceMatches=NO;
    if (archive.length==217) {
        unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(archive.bytes,(CC_LONG)archive.length,digest);
        NSMutableString *actual=[NSMutableString new]; for (unsigned char byte:digest) [actual appendFormat:@"%02x",byte];
        id state=[NSJSONSerialization JSONObjectWithData:archive options:0 error:NULL];
        sourceMatches=[actual isEqual:pin] && [state isEqual:pending];
    }
    const auto mode=elichika::candidateMode(present,infoMatches,capabilityMatches,sourceMatches);
    if (mode!=elichika::CandidateMode::ExperimentalArchivePending) {
        *error=@"The experimental Archive marker does not match this signed app's runtime and source configuration."; return NO;
    }
#if ELICHIKA_SIMULATOR_PROBE
    *error=@"An experimental device marker cannot enable the Simulator probe."; return NO;
#else
    ELExperimentalArchivePending=YES; return YES;
#endif
}

static BOOL ELPrepareConfiguration(NSString **error) {
    NSFileManager *manager=NSFileManager.defaultManager;
    NSURL *support=[manager URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *documents=[manager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSString *root=[[support.path stringByAppendingPathComponent:@"Elichika"] stringByAppendingPathComponent:@"data"];
    NSString *documentsRoot=documents.path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    NSString *library=[documentsRoot stringByAppendingPathComponent:@"Elichika"];
    ELStorageError=NO;
    NSData *bookmark=[NSUserDefaults.standardUserDefaults dataForKey:ELAssetBookmarkKey];
    if (bookmark) {
        BOOL stale=NO; NSError *bookmarkError=nil;
        NSURL *url=bookmark.length<=262144 ? [NSURL URLByResolvingBookmarkData:bookmark options:NSURLBookmarkResolutionWithoutUI
            relativeToURL:nil bookmarkDataIsStale:&stale error:&bookmarkError] : nil;
        if (!url.isFileURL) { ELStorageError=YES; *error=@"The saved asset folder is unavailable. Reconnect it or use the default asset folder."; return NO; }
        BOOL scoped=[url startAccessingSecurityScopedResource];
        if (!scoped && !([manager isReadableFileAtPath:url.path] && [manager isWritableFileAtPath:url.path])) {
            ELStorageError=YES; *error=@"Access to the saved asset folder expired. Select it again or use the default asset folder."; return NO;
        }
        if (!ELHeldScopes) ELHeldScopes=[NSMutableArray new]; [ELHeldScopes addObject:url]; ELActiveLibraryURL=url;
        library=url.path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
        if (stale) {
            NSData *renewed=[url bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:&bookmarkError];
            if (!renewed) { ELStorageError=YES; *error=@"The saved asset folder bookmark could not be renewed."; return NO; }
            [NSUserDefaults.standardUserDefaults setObject:renewed forKey:ELAssetBookmarkKey];
        }
        [NSUserDefaults.standardUserDefaults setObject:library forKey:ELAssetPathKey];
    }
    NSString *packs=[library stringByAppendingPathComponent:@"packs"];
    NSString *imports=[library stringByAppendingPathComponent:@"imports"];
    NSString *resources=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"ElichikaResources"];
    if (!ELReadCandidateMode(resources,error)) return NO;
    if (![manager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:@{NSFileProtectionKey:NSFileProtectionCompleteUntilFirstUserAuthentication} error:NULL]) {
        *error=@"Could not prepare app-private server storage."; return NO;
    }
    for (NSString *folder in @[packs,imports]) {
        NSString *canonical=folder.stringByStandardizingPath.stringByResolvingSymlinksInPath;
        if (![canonical hasPrefix:[library stringByAppendingString:@"/"]] ||
            ![manager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:NULL] ||
            ![folder.stringByResolvingSymlinksInPath hasPrefix:[library stringByAppendingString:@"/"]]) {
            ELStorageError=YES; *error=@"Could not prepare packs/imports in the selected asset folder."; return NO;
        }
    }
    uint8_t random[32]; if (SecRandomCopyBytes(kSecRandomDefault,sizeof random,random)!=errSecSuccess) {
        *error=@"Could not create the local server session."; return NO;
    }
    NSMutableString *token=[NSMutableString new],*readyToken=[NSMutableString new];
    for (NSUInteger i=0;i<16;++i) [token appendFormat:@"%02x",random[i]];
    for (NSUInteger i=16;i<32;++i) [readyToken appendFormat:@"%02x",random[i]];
    NSString *language=NSLocale.preferredLanguages.firstObject ?: @"en";
    language=[language hasPrefix:@"ja"] ? @"ja" : ([language hasPrefix:@"ko"] ? @"ko" : @"en");
    NSString *listen=@"127.0.0.1:8080",*languagePreference=@"auto";
    NSString *settingsPath=[root stringByAppendingPathComponent:@"ios-app-settings.json"];
    if ([manager fileExistsAtPath:settingsPath]) {
        NSData *data=[NSData dataWithContentsOfFile:settingsPath options:0 error:NULL];
        NSDictionary *settings=data.length && data.length<=65536 ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        if (![settings isKindOfClass:NSDictionary.class] || settings.count!=3 || ![settings[@"schema"] isEqual:@1] ||
            ![settings[@"language"] isKindOfClass:NSString.class] || ![settings[@"listen_address"] isKindOfClass:NSString.class] ||
            !elichika::nativeLanguageAllowed(std::string_view([settings[@"language"] UTF8String],[settings[@"language"] lengthOfBytesUsingEncoding:NSUTF8StringEncoding])) ||
            !elichika::nativeListenAllowed(std::string_view([settings[@"listen_address"] UTF8String],[settings[@"listen_address"] lengthOfBytesUsingEncoding:NSUTF8StringEncoding]))) {
            *error=@"The saved app language/listen settings are invalid."; return NO;
        }
        languagePreference=settings[@"language"]; listen=settings[@"listen_address"];
        if (![languagePreference isEqual:@"auto"]) language=languagePreference;
    }
    NSMutableDictionary *configuration=[@{
        @"python_home":[resources stringByAppendingPathComponent:@"python"],
        @"python_app_root":[resources stringByAppendingPathComponent:@"python-app"],
        @"payload_root":[resources stringByAppendingPathComponent:@"python-app"],
        @"seed_root":[resources stringByAppendingPathComponent:@"payload"],
        @"tool_data_root":[resources stringByAppendingPathComponent:@"tool-data"],
        @"data_root":root,@"documents_root":documentsRoot,
        @"library_root":library,@"external_asset_directory":@(bookmark!=nil),
        @"packs_root":packs,@"imports_root":imports,
        @"listen_address":listen,@"token":token,@"ready_token":readyToken,@"language":language,@"language_preference":languagePreference,
        @"region":ELClientRegion ?: @"gl",
        @"app_version":NSBundle.mainBundle.infoDictionary[@"ElichikaUnifiedBuildVersion"]
            ?: NSBundle.mainBundle.infoDictionary[@"CFBundleShortVersionString"] ?: @"",
        @"core_only":@NO
    } mutableCopy];
    if (ELExperimentalArchivePending) configuration[@"experimental_device"]=@YES;
#if ELICHIKA_SIMULATOR_PROBE
    configuration[@"simulator_probe_only"]=@YES;
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
    if (error.length && !ELCore().started()) { ELCore().fail(error.UTF8String); ELProgress=error; ElichikaHostShowManagement(); }
    else if (error.length) { ELProgress=error; ELCore().report(generation,ready,""); }
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
        NSString *resources=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"ElichikaResources"];
        if (!ELReadCandidateMode(resources,&error) || !ELPrepareRouting(&error)) ELHookError=error;
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
void ElichikaHostSetProbeStageHandler(void (^handler)(NSString *stage,NSTimeInterval entered)) { ELProbeStageHandler=[handler copy]; }
void ElichikaHostProbeStage(NSString *stage) {
    const NSTimeInterval entered=NSProcessInfo.processInfo.systemUptime;
    if (!NSThread.isMainThread) {
        dispatch_async(dispatch_get_main_queue(),^{ if (ELProbeStageHandler) ELProbeStageHandler(stage,entered); }); return;
    }
    if (ELProbeStageHandler) ELProbeStageHandler(stage,entered);
}
void ElichikaHostProbeWebStorage(NSUInteger launchNumber,void (^completion)(NSDictionary *)) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(),^{ ElichikaHostProbeWebStorage(launchNumber,completion); }); return; }
    if (launchNumber!=1 && launchNumber!=2) {
        completion(@{@"ready":@NO,@"actual_management_webview":@NO,@"launch_number":@(launchNumber),@"error":@"The cold-launch index must be 1 or 2."}); return;
    }
    ElichikaHostShowManagement(); [ELPanel loadViewIfNeeded];
    BOOL actual=ELPanel.web && [ELPanel.web isDescendantOfView:ELPanel.view] && ELPanel.web.navigationDelegate==ELPanel;
    BOOL persistent=ELPanel.web.configuration.websiteDataStore.persistent;
    if (!actual || !persistent) {
        completion(@{@"ready":@NO,@"actual_management_webview":@(actual),@"launch_number":@(launchNumber),@"error":@"The actual management WebView is not persistent."}); return;
    }
    ElichikaHostProbeStage(@"web_admin");
    [ELPanel probeStorageService:@"admin" port:8772 launch:launchNumber completion:^(NSDictionary *admin) {
        ElichikaHostProbeStage(@"web_tools");
        [ELPanel probeStorageService:@"tools" port:8770 launch:launchNumber completion:^(NSDictionary *tools) {
            completion(@{@"ready":@([admin[@"ready"] boolValue] && [tools[@"ready"] boolValue]),
                @"actual_management_webview":@(actual),@"persistent_store":@(persistent),@"launch_number":@(launchNumber),
                @"admin":admin,@"tools":tools});
        }];
    }];
}
void ElichikaHostProbeManagement(void (^completion)(NSDictionary *)) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(),^{ ElichikaHostProbeManagement(completion); }); return; }
    ElichikaHostProbeStage(@"management_ui");
    ElichikaHostShowManagement(); [ELPanel loadViewIfNeeded];
    if (!ELPanel.web || !ELPanelReady() || !ELCore().started()) {
        completion(@{@"ready":@NO,@"actual_management_webview":@NO,@"error":@"Management was unavailable after backend startup."}); return;
    }
    [ELPanel probeManagement:completion];
}
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
@property(nonatomic,assign) NSInteger selectionKind;
@property(nonatomic,strong) NSURL *selectedURL;
@property(nonatomic,strong) NSData *bookmark;
@property(nonatomic,assign) BOOL securityScope;
@property(nonatomic,weak) UIDocumentPickerViewController *picker;
- (void)finish;
@end
static ELDocumentTransaction *ELPendingDocument;
@implementation ELDocumentTransaction
- (void)dealloc { if (_securityScope) [_selectedURL stopAccessingSecurityScopedResource]; }
- (void)finish {
    if (_completed) return; _completed=YES;
    void (^settled)(void)=^{ if (ELPendingDocument==self) ELPendingDocument=nil; dispatch_semaphore_signal(self.finished); };
    if (_picker.presentingViewController) [_picker dismissViewControllerAnimated:YES completion:settled];
    else settled();
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller { (void)controller; if (_copying) return; _error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Document selection cancelled."}]; [self finish]; }
- (void)presentationControllerDidDismiss:(UIPresentationController *)controller { (void)controller; [self documentPickerWasCancelled:nil]; }
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    if (_exporting) { [self finish]; return; }
    if (!urls.count) { [self documentPickerWasCancelled:controller]; return; }
    if (urls.count>128 || (!_multiple && urls.count!=1)) {
        _error=[NSError errorWithDomain:@"ElichikaDocument" code:6 userInfo:@{NSLocalizedDescriptionKey:@"Choose at most 128 files per import."}]; [self finish]; return;
    }
    if (_selectionKind) {
        NSURL *source=urls.firstObject; NSNumber *directory=nil; NSError *error=nil;
        [source getResourceValue:&directory forKey:NSURLIsDirectoryKey error:&error];
        if (!source.isFileURL || error || (_selectionKind==1 && !directory.boolValue) || (_selectionKind==2 && directory.boolValue)) {
            _error=error ?: [NSError errorWithDomain:@"ElichikaDocument" code:7 userInfo:@{NSLocalizedDescriptionKey:@"Choose the requested file or folder."}]; [self finish]; return;
        }
        BOOL scoped=[source startAccessingSecurityScopedResource];
        if (!scoped && !([NSFileManager.defaultManager isReadableFileAtPath:source.path] && [NSFileManager.defaultManager isWritableFileAtPath:source.path])) {
            _error=[NSError errorWithDomain:@"ElichikaDocument" code:8 userInfo:@{NSLocalizedDescriptionKey:@"The selected location is not writable."}]; [self finish]; return;
        }
        NSData *bookmark=_selectionKind==1 ? [source bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:&error] : nil;
        if (_selectionKind==1 && (!bookmark || bookmark.length>262144)) {
            if (scoped) [source stopAccessingSecurityScopedResource];
            _error=error ?: [NSError errorWithDomain:@"ElichikaDocument" code:8 userInfo:@{NSLocalizedDescriptionKey:@"Could not retain access to this location."}]; [self finish]; return;
        }
        _securityScope=scoped; _bookmark=bookmark; _selectedURL=source; _path=source.path; [self finish]; return;
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
static ELDocumentTransaction *ELPickOptions(NSArray *types, NSString *exportPath, BOOL multiple, NSInteger selectionKind) {
    ELDocumentTransaction *transaction=[ELDocumentTransaction new]; transaction.finished=dispatch_semaphore_create(0); transaction.exporting=exportPath!=nil; transaction.multiple=multiple;
    transaction.selectionKind=selectionKind;
    dispatch_async(dispatch_get_main_queue(),^{
        UIViewController *presenter=ElichikaHostPresenter();
        if (ELPendingDocument || !presenter || presenter.presentedViewController ||
            [presenter isKindOfClass:UIAlertController.class] || [presenter isKindOfClass:UIDocumentPickerViewController.class]) {
            transaction.error=[NSError errorWithDomain:@"ElichikaDocument" code:1 userInfo:@{NSLocalizedDescriptionKey:@"Another dialog is open. Close it and try again."}]; [transaction finish]; return;
        }
        ELPendingDocument=transaction;
        UIDocumentPickerViewController *picker;
        if (exportPath) picker=[[UIDocumentPickerViewController alloc] initWithURLs:@[[NSURL fileURLWithPath:exportPath]] inMode:UIDocumentPickerModeExportToService];
        else {
            BOOL folder=[types containsObject:@"public.folder"];
            picker=[[UIDocumentPickerViewController alloc] initWithDocumentTypes:types.count ? types : @[@"public.data"]
                inMode:folder || selectionKind ? UIDocumentPickerModeOpen : UIDocumentPickerModeImport];
        }
        transaction.picker=picker; picker.delegate=transaction; picker.allowsMultipleSelection=multiple && !exportPath; picker.presentationController.delegate=transaction;
        [presenter presentViewController:picker animated:YES completion:nil];
    });
    dispatch_semaphore_wait(transaction.finished,DISPATCH_TIME_FOREVER); return transaction;
}
static ELDocumentTransaction *ELPick(NSArray *types, NSString *exportPath, BOOL multiple) { return ELPickOptions(types,exportPath,multiple,0); }
static NSDictionary *ELChooseAssetDirectory(NSError **error) {
    if (NSThread.isMainThread) { if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:3 userInfo:@{NSLocalizedDescriptionKey:@"Folder selection must run off the UI thread."}]; return nil; }
    ELDocumentTransaction *transaction=ELPickOptions(@[@"public.folder"],nil,NO,1);
    if (error) *error=transaction.error;
    if (transaction.error || !transaction.path) return nil;
    NSString *message=ELButtonText(@"Use this folder directly as the asset library after reopening? Tools can read and save files here. Existing files are not moved. Ordinary file imports still make copies.",
        @"앱을 다시 연 뒤 이 폴더를 에셋 보관함으로 직접 사용할까요? 도구가 이곳의 파일을 읽고 저장할 수 있습니다. 기존 파일은 옮기지 않으며 일반 파일 가져오기는 계속 복사본을 만듭니다.",
        @"再起動後、このフォルダーを保存先として直接使用しますか？ツールがここで読み書きします。既存ファイルは移動せず、通常の読み込みはコピーを作ります。");
    if (ELDocumentChoice(ELButtonText(@"Use external asset folder?",@"외부 에셋 폴더를 사용할까요?",@"外部フォルダーを使用しますか？"),message,
        @[ELButtonText(@"Use folder directly",@"폴더 직접 사용",@"直接使用"),ELButtonText(@"Cancel",@"취소",@"キャンセル")])!=0) {
        if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Folder selection cancelled."}]; return nil;
    }
    [NSUserDefaults.standardUserDefaults setObject:transaction.bookmark forKey:ELAssetBookmarkKey];
    [NSUserDefaults.standardUserDefaults setObject:transaction.path.stringByResolvingSymlinksInPath forKey:ELAssetPathKey];
    if (transaction.securityScope) {
        @synchronized(NSUserDefaults.standardUserDefaults) {
            if (!ELHeldScopes) ELHeldScopes=[NSMutableArray new]; [ELHeldScopes addObject:transaction.selectedURL];
        }
        transaction.securityScope=NO;
    }
    return @{@"path":transaction.path.stringByResolvingSymlinksInPath,@"external":@YES,@"requires_restart":@YES};
}
static NSDictionary *ELRestoreAssetDirectory(void) {
    [NSUserDefaults.standardUserDefaults removeObjectForKey:ELAssetBookmarkKey];
    [NSUserDefaults.standardUserDefaults removeObjectForKey:ELAssetPathKey];
    NSString *path=[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"Elichika"];
    // Existing security scopes stay alive until process exit. Active jobs and
    // current ELConfiguration continue using the old library until reopening.
    return @{@"path":path.stringByResolvingSymlinksInPath,@"external":@NO,@"requires_restart":@YES};
}
BOOL ElichikaHostWritablePath(NSString *path) {
    if (![path isKindOfClass:NSString.class] || !path.isAbsolutePath ||
        [path rangeOfCharacterFromSet:[NSCharacterSet characterSetWithRange:NSMakeRange(0,1)]].location!=NSNotFound) return NO;
    NSString *resolved=path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    for (NSString *root in @[ELConfiguration[@"data_root"] ?: @"",ELConfiguration[@"documents_root"] ?: @"",ELConfiguration[@"library_root"] ?: @""]) {
        NSString *canonical=root.stringByStandardizingPath.stringByResolvingSymlinksInPath;
        if (canonical.length && ([resolved isEqual:canonical] || [resolved hasPrefix:[canonical stringByAppendingString:@"/"]])) return YES;
    }
    return NO;
}
static NSInteger ELDocumentChoice(NSString *title,NSString *message,NSArray<NSString *> *choices) {
    dispatch_semaphore_t finished=dispatch_semaphore_create(0); __block NSInteger result=-1;
    dispatch_async(dispatch_get_main_queue(),^{
        UIViewController *presenter=ElichikaHostPresenter();
        if (!presenter || ELPendingDocument || [presenter isKindOfClass:UIAlertController.class] ||
            [presenter isKindOfClass:UIDocumentPickerViewController.class]) { dispatch_semaphore_signal(finished); return; }
        UIAlertController *alert=[UIAlertController alertControllerWithTitle:title message:message preferredStyle:UIAlertControllerStyleAlert];
        for (NSUInteger index=0;index<choices.count;++index) {
            [alert addAction:[UIAlertAction actionWithTitle:choices[index] style:index==choices.count-1 ? UIAlertActionStyleCancel : UIAlertActionStyleDefault
                handler:^(UIAlertAction *action){
                    (void)action; result=(NSInteger)index;
                    [alert dismissViewControllerAnimated:YES completion:^{ dispatch_semaphore_signal(finished); }];
                }]];
        }
        [presenter presentViewController:alert animated:YES completion:nil];
    });
    dispatch_semaphore_wait(finished,DISPATCH_TIME_FOREVER); return result;
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
    if (NSThread.isMainThread || !ElichikaHostWritablePath(resolved) || ![NSFileManager.defaultManager fileExistsAtPath:resolved]) {
        if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:5 userInfo:@{NSLocalizedDescriptionKey:@"Choose an existing file in app storage."}]; return NO;
    }
    BOOL directory=NO; [NSFileManager.defaultManager fileExistsAtPath:resolved isDirectory:&directory];
    if (!directory) {
        NSInteger choice=ELDocumentChoice(ELButtonText(@"Save file",@"파일 저장",@"ファイルを保存"),resolved.lastPathComponent,
            @[ELButtonText(@"Export a copy",@"복사본 내보내기",@"コピーを書き出す"),
              ELButtonText(@"Replace an existing file…",@"기존 파일에 저장…",@"既存ファイルに保存…"),
              ELButtonText(@"Cancel",@"취소",@"キャンセル")]);
        if (choice<0 || choice==2) { if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Saving cancelled."}]; return NO; }
        if (choice==1) {
            __attribute__((objc_precise_lifetime)) ELDocumentTransaction *selection=ELPickOptions(@[@"public.item"],nil,NO,2);
            if (selection.error || !selection.selectedURL) { if (error) *error=selection.error; return NO; }
            NSString *message=[NSString stringWithFormat:ELButtonText(@"Replace %@ with %@? The existing file's contents will change.",@"%@ 파일을 %@ 내용으로 바꿀까요? 기존 파일의 내용이 변경됩니다.",@"%@を%@の内容で置き換えますか？既存の内容が変更されます。"),selection.selectedURL.lastPathComponent,resolved.lastPathComponent];
            if (ELDocumentChoice(ELButtonText(@"Replace file?",@"파일을 바꿀까요?",@"ファイルを置き換えますか？"),message,
                @[ELButtonText(@"Replace",@"바꾸기",@"置き換える"),ELButtonText(@"Cancel",@"취소",@"キャンセル")])!=0) {
                if (error) *error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:@{NSLocalizedDescriptionKey:@"Saving cancelled."}]; return NO;
            }
            NSURL *source=[NSURL fileURLWithPath:resolved];
            if ([source.path.stringByResolvingSymlinksInPath isEqual:selection.selectedURL.path.stringByResolvingSymlinksInPath]) return YES;
            NSFileCoordinator *coordinator=[[NSFileCoordinator alloc] initWithFilePresenter:nil]; __block NSError *writeError=nil;
            [coordinator coordinateReadingItemAtURL:source options:0 writingItemAtURL:selection.selectedURL options:NSFileCoordinatorWritingForReplacing error:&writeError
                byAccessor:^(NSURL *readURL,NSURL *writeURL){
                    NSURL *replacement=[NSFileManager.defaultManager URLForDirectory:NSItemReplacementDirectory inDomain:NSUserDomainMask
                        appropriateForURL:writeURL create:YES error:&writeError];
                    NSURL *temporary=[replacement URLByAppendingPathComponent:writeURL.lastPathComponent];
                    if (temporary && [NSFileManager.defaultManager copyItemAtURL:readURL toURL:temporary error:&writeError])
                        [NSFileManager.defaultManager replaceItemAtURL:writeURL withItemAtURL:temporary backupItemName:nil options:0 resultingItemURL:nil error:&writeError];
                    if (replacement) [NSFileManager.defaultManager removeItemAtURL:replacement error:NULL];
                }];
            if (error) *error=writeError; return !writeError;
        }
    }
    ELDocumentTransaction *transaction=ELPick(nil,resolved,NO); if (error) *error=transaction.error; return !transaction.error;
}
