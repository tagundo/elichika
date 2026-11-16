#import "ElichikaHost.h"
#import "ElichikaPythonRuntime.h"
#import "SIFASMVExportSession.h"
#include "HostCore.hpp"
#include "NavigationPolicy.hpp"
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
#include <cstdlib>

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
static NSDictionary *ELRestoreAssetDirectory(NSError **error);
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

// PlayCover converts this iOS binary to Catalyst after compilation. Select
// bookmark options at runtime: the public Foundation flag values are stable,
// while their SDK names are unavailable when compiling the iOS slice.
static NSURLBookmarkCreationOptions ELAssetBookmarkCreationOptions(void) {
    return [NSProcessInfo.processInfo isMacCatalystApp] ? (NSURLBookmarkCreationOptions)(1UL << 11)
        : NSURLBookmarkCreationMinimalBookmark;
}
static NSURLBookmarkResolutionOptions ELAssetBookmarkResolutionOptions(NSString *mode) {
    return NSURLBookmarkResolutionWithoutUI | ([NSProcessInfo.processInfo isMacCatalystApp] && [mode isEqual:@"mac_security_scoped"]
        ? (NSURLBookmarkResolutionOptions)(1UL << 10) : 0);
}
static NSError *ELAssetFolderError(NSString *action,NSString *path,NSError *underlying) {
    NSString *detail=underlying ? [NSString stringWithFormat:@" (%@ %ld): %@",underlying.domain,
        (long)underlying.code,underlying.localizedDescription] : @"";
    NSMutableDictionary *info=[@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"%@\n%@%@",
        action,path ?: @"",detail]} mutableCopy];
    if (underlying) info[NSUnderlyingErrorKey]=underlying;
    return [NSError errorWithDomain:@"ElichikaAssetDirectory" code:1 userInfo:info];
}
// Standard PlayCover signatures omit the app-scoped-bookmark entitlement.
// Foundation's implicit bookmark scope can still carry the picker grant until
// a system reboot, but it must never be advertised as permanent access.
static NSString *ELAssetBookmarkLifetime(NSString *mode) {
    return [mode isEqual:@"mac_security_scoped"] ? @"persistent" :
        ([mode isEqual:@"mac_implicit"] ? @"until_reboot" :
         ([mode isEqual:@"ios_document_picker"] ? @"document_provider" : mode));
}
static NSString *ELAssetBookmarkWarning(NSString *mode) {
    return [mode isEqual:@"mac_implicit"] ? ELButtonText(
        @"This PlayCover installation may require choosing the folder again after the Mac restarts. If access expires, choose the same folder again. Existing files stay in place.",
        @"이 PlayCover 설치에서는 Mac을 재시동하면 폴더를 다시 선택해야 할 수 있습니다. 접근 권한이 만료되면 같은 폴더를 다시 선택하세요. 기존 파일은 그대로 유지됩니다.",
        @"このPlayCover環境ではMacの再起動後にフォルダーの再選択が必要になる場合があります。アクセス期限が切れたら同じフォルダーを再選択してください。既存ファイルは移動しません。") : @"";
}
static NSData *ELCreateAssetBookmark(NSURL *url,NSString **mode,NSError **error) {
    NSError *failure=nil;
    NSData *data=[url bookmarkDataWithOptions:ELAssetBookmarkCreationOptions() includingResourceValuesForKeys:nil relativeToURL:nil error:&failure];
    NSString *chosen=[NSProcessInfo.processInfo isMacCatalystApp] ? @"mac_security_scoped" : @"ios_document_picker";
    if (!data && [NSProcessInfo.processInfo isMacCatalystApp]) {
        // This is a documented ephemeral grant, not an entitlement bypass.
        failure=nil;
        data=[url bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:&failure];
        chosen=@"mac_implicit";
    }
    if (!data.length || data.length>262144) { if (error) *error=failure ?: ELAssetFolderError(@"The selected folder's bookmark could not be retained.",url.path,nil); return nil; }
    if (mode) *mode=chosen;
    return data;
}
static NSData *ELStoreAssetBookmark(NSData *bookmark,NSString *mode,NSError **error) {
    // Mode and bytes share a single atomic UserDefaults value. The old raw
    // bookmark format remains readable; no extra mode key can get out of sync.
    NSData *plist=[NSPropertyListSerialization dataWithPropertyList:@{@"schema":@1,@"mode":mode,@"bookmark":bookmark}
        format:NSPropertyListBinaryFormat_v1_0 options:0 error:error];
    if (!plist) return nil;
    NSMutableData *stored=[NSMutableData dataWithBytes:"ELBK1" length:5]; [stored appendData:plist]; return stored;
}
static NSData *ELReadAssetBookmark(NSData *stored,NSString **mode,NSError **error) {
    if (!stored.length || stored.length>300000) { if (error) *error=ELAssetFolderError(@"The saved folder bookmark is invalid.",@"",nil); return nil; }
    BOOL envelope=stored.length>=5 && memcmp(stored.bytes,"ELBK1",5)==0;
    NSData *payload=envelope ? [stored subdataWithRange:NSMakeRange(5,stored.length-5)] : nil;
    id value=envelope ? [NSPropertyListSerialization propertyListWithData:payload options:NSPropertyListImmutable format:NULL error:NULL] : nil;
    if (envelope) {
        BOOL valid=[value isKindOfClass:NSDictionary.class] && [value count]==3 && [value[@"schema"] isEqual:@1] &&
            [value[@"mode"] isKindOfClass:NSString.class] &&
            [@[@"mac_security_scoped",@"mac_implicit",@"ios_document_picker"] containsObject:value[@"mode"]] &&
            [value[@"bookmark"] isKindOfClass:NSData.class] && [value[@"bookmark"] length]>0 && [value[@"bookmark"] length]<=262144;
        if (!valid) { if (error) *error=ELAssetFolderError(@"The saved folder bookmark metadata is invalid. Choose the folder again.",@"",nil); return nil; }
        if (mode) *mode=value[@"mode"];
        return value[@"bookmark"];
    }
    // .3 used raw minimal bookmarks on every platform, including PlayCover.
    if (mode) *mode=[NSProcessInfo.processInfo isMacCatalystApp] ? @"mac_implicit" : @"ios_document_picker";
    return stored;
}
static NSString *ELSavedAssetBookmarkMode(void) {
    NSData *saved=[NSUserDefaults.standardUserDefaults dataForKey:ELAssetBookmarkKey];
    if (!saved) return @"app_storage";
    NSString *mode=nil; ELReadAssetBookmark(saved,&mode,NULL); return mode ?: @"unavailable";
}
static BOOL ELPrepareAssetFolders(NSString *library,NSError **error) {
    NSFileManager *manager=NSFileManager.defaultManager;
    for (NSString *component in @[@"packs",@"imports"]) {
        NSString *folder=[library stringByAppendingPathComponent:component];
        NSString *prefix=[library stringByAppendingString:@"/"];
        NSError *failure=nil;
        if (![folder.stringByStandardizingPath.stringByResolvingSymlinksInPath hasPrefix:prefix]) {
            if (error) *error=ELAssetFolderError(ELButtonText(@"An asset subfolder points outside the selected library.",
                @"에셋 하위 폴더가 선택한 보관 폴더 밖을 가리킵니다.",@"アセットのサブフォルダーが選択した保存先の外を参照しています。"),folder,nil);
            return NO;
        }
        if (![manager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:&failure] ||
            ![folder.stringByResolvingSymlinksInPath hasPrefix:prefix] ||
            ![manager isReadableFileAtPath:folder] || ![manager isWritableFileAtPath:folder]) {
            if (error) *error=ELAssetFolderError(ELButtonText(@"Could not prepare this asset subfolder.",
                @"이 에셋 하위 폴더를 준비하지 못했습니다.",@"このアセットのサブフォルダーを準備できませんでした。"),folder,failure);
            return NO;
        }
    }
    return YES;
}
// A failed restore/selection releases its acquired access. Successful roots
// transfer that reference to the process-lived list, keeping active jobs valid.
@interface ELAssetScopeLease : NSObject
@property(nonatomic,strong) NSURL *url;
@property(nonatomic,assign) BOOL acquired;
- (instancetype)initWithURL:(NSURL *)url;
- (void)keepUntilExit;
@end
@implementation ELAssetScopeLease
- (instancetype)initWithURL:(NSURL *)url {
    if ((self=[super init])) { _url=url; _acquired=[url startAccessingSecurityScopedResource]; }
    return self;
}
- (void)dealloc { if (_acquired) [_url stopAccessingSecurityScopedResource]; }
- (void)keepUntilExit {
    if (!_acquired) return;
    @synchronized(NSUserDefaults.standardUserDefaults) {
        if (!ELHeldScopes) ELHeldScopes=[NSMutableArray new]; [ELHeldScopes addObject:_url];
    }
    _acquired=NO;
}
@end

static NSString *ELJSON(id value) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingFragmentsAllowed error:NULL];
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

// The dated client library remains byte-for-byte unchanged. Bind only after
// Objective-C has registered its exact API, then capture its already-initialized
// controller from the real preference poll. A fresh instance would bypass the
// client's verified configuration initialization.
static IMP ELClientOriginalPoll;
static __weak id ELClientControls;
static __weak UIView *ELClientControlRoot;
static __weak UIButton *ELClientOldButton;
static __weak UILongPressGestureRecognizer *ELClientOldShortcut;
static BOOL ELClientMenuHooked,ELClientMenuInspected;
static BOOL ELClientMethod(Class type,SEL selector,unsigned int arguments,const char *argument=nullptr) {
    Method method=class_getInstanceMethod(type,selector);
    if (!method || method_getNumberOfArguments(method)!=arguments) return NO;
    char *result=method_copyReturnType(method); BOOL valid=result && !std::strcmp(result,"v"); free(result);
    if (valid && argument) { char *value=method_copyArgumentType(method,2); valid=value && !std::strcmp(value,argument); free(value); }
    return valid;
}
static void ELHideOriginalClientMenu(id owner) {
    UIWindow *window=ELPanelWindow.isKeyWindow ? ELPanelWindow : ELGameWindow;
    UIView *root=window.rootViewController.view; if (!root) return;
    if (root!=ELClientControlRoot) {
        ELClientControlRoot=root; ELClientOldButton=nil; ELClientOldShortcut=nil;
        // The client inserts these as direct children. Reinspect only when it
        // reparents them to a different root; normal polls allocate/scan nothing.
        for (UIView *child in root.subviews)
            if ([child isKindOfClass:UIButton.class] && [child.accessibilityIdentifier isEqual:@"SIFASFeatures.Settings"] &&
                [((UIButton *)child).allTargets containsObject:owner]) { ELClientOldButton=(UIButton *)child; break; }
        for (UIGestureRecognizer *gesture in root.gestureRecognizers)
            if ([gesture isKindOfClass:UILongPressGestureRecognizer.class] && gesture.delegate==owner) {
                ELClientOldShortcut=(UILongPressGestureRecognizer *)gesture; break;
            }
    }
    // Original poll refreshes the button's visibility. Override only that
    // presentation, without changing either standalone client's saved setting.
    ELClientOldButton.hidden=YES; ELClientOldShortcut.enabled=NO;
}
static void ELUnifiedClientPoll(id owner,SEL selector,id timer) {
    ((void (*)(id,SEL,id))ELClientOriginalPoll)(owner,selector,timer);
    ELClientControls=owner; ELHideOriginalClientMenu(owner);
}
static void ELUnifiedClientShow(id owner,SEL selector) {
    (void)owner; (void)selector; ElichikaHostShowManagement();
}
static void ELInstallClientMenuBridge(void) {
    if (ELClientMenuInspected || !NSThread.isMainThread) return;
    Class type=NSClassFromString(@"SIFASFeatures"); if (!type) return;
    ELClientMenuInspected=YES;
    SEL poll=@selector(poll:),show=@selector(showSettings);
    if (!ELClientMethod(type,poll,3,"@") || !ELClientMethod(type,show,2) ||
        !ELClientMethod(type,@selector(showCamera),2) || !ELClientMethod(type,@selector(showOrientation),2)) return;
    Method method=class_getInstanceMethod(type,poll); ELClientOriginalPoll=method_getImplementation(method);
    method_setImplementation(method,(IMP)ELUnifiedClientPoll);
    method_setImplementation(class_getInstanceMethod(type,show),(IMP)ELUnifiedClientShow);
    ELClientMenuHooked=YES;
}
static BOOL ELClientControlsAvailable(void) { return ELClientMenuHooked && ELClientControls!=nil; }
static void ELClientApplyPreferences(void) {
    id controller=ELClientControls;
    if (controller && ELClientOriginalPoll) ELUnifiedClientPoll(controller,@selector(poll:),nil);
}
static BOOL ELClientOpenControl(NSString *name) {
    id controller=ELClientControls;
    if (!ELClientControlsAvailable() || !([name isEqual:@"showCamera"] || [name isEqual:@"showOrientation"])) return NO;
    SEL selector=NSSelectorFromString(name);
    IMP action=[controller methodForSelector:selector];
    if (!action) return NO;
    ((void (*)(id,SEL))action)(controller,selector); return YES;
}
static void ELAfterMenuDismissal(UIAlertController *menu,void (^action)(void)) {
    UIViewController *presenting=menu.presentingViewController;
    if (!presenting) { dispatch_async(dispatch_get_main_queue(),action); return; }
    id<UIViewControllerTransitionCoordinator> transition=menu.transitionCoordinator;
    if (menu.isBeingDismissed && transition) {
        [transition animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context) {
            if (!context.isCancelled) action();
        }];
    } else [presenting dismissViewControllerAnimated:YES completion:action];
}
static void ELClientControlRoute(UIAlertController *menu,NSString *name,void (^completion)(BOOL)) {
    ELAfterMenuDismissal(menu,^{
        BOOL delivered=ELClientOpenControl(name);
        if (completion) completion(delivered);
    });
}
NSDictionary *ElichikaHostConfiguration(void) { return ELConfiguration ?: @{}; }
NSString *ElichikaHostDiagnosticsJSON(void) {
    const auto &core=ELCore();
    NSString *active=ELConfiguration[@"library_root"] ?: @"";
    NSString *saved=[NSUserDefaults.standardUserDefaults stringForKey:ELAssetPathKey];
    NSString *nextMode=ELSavedAssetBookmarkMode();
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
                    @"next_external_asset_directory":@([NSUserDefaults.standardUserDefaults dataForKey:ELAssetBookmarkKey]!=nil),
                    @"bookmark_mode":ELConfiguration[@"bookmark_mode"] ?: @"app_storage",@"next_bookmark_mode":nextMode,
                    @"access_lifetime":ELConfiguration[@"access_lifetime"] ?: @"app_storage",
                    @"persistence_warning":ELConfiguration[@"persistence_warning"] ?: @"",
                    @"next_access_lifetime":[nextMode isEqual:@"app_storage"] ? @"app_storage" : ELAssetBookmarkLifetime(nextMode),
                    @"next_persistence_warning":ELAssetBookmarkWarning(nextMode),
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
@property(nonatomic,assign) NSInteger selectedWebSection;
@property(nonatomic,assign) NSInteger selectedDestination;
@property(nonatomic,assign) BOOL managementAvailable;
@property(nonatomic,copy) NSString *managementPage;
@property(nonatomic,copy) NSString *editorPage;
@property(nonatomic,strong) UIScrollView *sidebar;
@property(nonatomic,strong) NSLayoutConstraint *sidebarContentWidth;
@property(nonatomic,strong) UIButton *destinationPicker;
@property(nonatomic,strong) NSArray<UIButton *> *destinationButtons;
@property(nonatomic,assign) NSInteger renderedDestination;
@property(nonatomic,assign) BOOL renderedAvailable;
@property(nonatomic,copy) NSString *renderedLanguage;
@property(nonatomic,strong) WKWebView *web;
@property(nonatomic,strong) UIView *webContainer;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,WKWebView *> *sectionWebViews;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,NSString *> *sectionTargets;
@property(nonatomic,strong) NSHashTable<WKWebView *> *failedPanels;
@property(nonatomic,strong) NSMapTable<WKWebView *,NSString *> *panelErrors;
@property(nonatomic,strong) UIButton *retry;
@property(nonatomic,strong) UIButton *storageRecovery;
@property(nonatomic,strong) UIButton *storageReselect;
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
- (void)applyDestinationToWebView:(WKWebView *)web;
- (void)selectDestination:(NSInteger)destination;
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
    self.navigationItem.rightBarButtonItem=[[UIBarButtonItem alloc] initWithTitle:ELButtonText(@"Game",@"게임으로",@"ゲームへ") style:UIBarButtonItemStyleDone target:self action:@selector(close)];
    _statusLabel=[UILabel new]; _statusLabel.numberOfLines=0; _statusLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline];
    _spinner=[[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    _retry=[UIButton buttonWithType:UIButtonTypeSystem]; [_retry setTitle:@"Retry setup" forState:UIControlStateNormal];
    [_retry addTarget:self action:@selector(retrySetup) forControlEvents:UIControlEventTouchUpInside];
    _selectedWebSection=0; _selectedDestination=0; _renderedDestination=-1; _managementPage=@"server"; _editorPage=@"tools";
    _buttonVisibility=[[UIBarButtonItem alloc] initWithTitle:@"" style:UIBarButtonItemStylePlain target:self action:@selector(toggleServerButton)];
    self.navigationItem.leftBarButtonItem=_buttonVisibility;
    _buttonVisibility.accessibilityHint=ELButtonText(@"The choice is saved. Hold the upper-right corner for 2 seconds to reopen server and game settings.",
        @"선택은 저장됩니다. 오른쪽 위를 2초 길게 누르면 서버·게임 설정을 다시 열 수 있습니다.",
        @"設定は保存されます。右上を2秒間長押しするとサーバー・ゲーム設定を再び開けます。");
    _candidateLabel=[UILabel new]; _candidateLabel.numberOfLines=1;
    _candidateLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2]; _candidateLabel.textColor=UIColor.systemOrangeColor;
    _candidateLabel.text=ELButtonText(@"Preview",@"미리보기",@"プレビュー");
    _candidateLabel.accessibilityLabel=ELButtonText(@"Experimental build. Archive publication and physical device testing are pending.",
        @"실험 빌드입니다. Archive 게시와 실기기 검증은 대기 중입니다.",
        @"実験ビルドです。Archive公開と実機検証は未完了です。");
    _sectionWebViews=[NSMutableDictionary new]; _sectionTargets=[NSMutableDictionary new];
    _failedPanels=NSHashTable.weakObjectsHashTable; _panelErrors=[NSMapTable weakToStrongObjectsMapTable];
    _webContainer=[UIView new];
    _downloads=[NSMapTable strongToStrongObjectsMapTable];
    _storageRecovery=[UIButton buttonWithType:UIButtonTypeSystem];
    [_storageRecovery setTitle:ELButtonText(@"Use default asset folder",@"기본 에셋 폴더 사용",@"既定の保存先を使用") forState:UIControlStateNormal];
    [_storageRecovery addTarget:self action:@selector(restoreStorage) forControlEvents:UIControlEventTouchUpInside];
    _storageReselect=[UIButton buttonWithType:UIButtonTypeSystem];
    [_storageReselect setTitle:ELButtonText(@"Choose asset folder again",@"에셋 폴더 다시 선택",@"保存先を再選択") forState:UIControlStateNormal];
    [_storageReselect addTarget:self action:@selector(reselectStorage) forControlEvents:UIControlEventTouchUpInside];
    UIStackView *statusRow=[[UIStackView alloc] initWithArrangedSubviews:@[_spinner,_statusLabel,_candidateLabel]];
    statusRow.axis=UILayoutConstraintAxisHorizontal; statusRow.alignment=UIStackViewAlignmentCenter; statusRow.spacing=8;
    [_spinner setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
    [_candidateLabel setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];
    _destinationPicker=[UIButton buttonWithType:UIButtonTypeSystem];
    _destinationPicker.contentHorizontalAlignment=UIControlContentHorizontalAlignmentLeading;
    _destinationPicker.titleLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleHeadline];
    [_destinationPicker addTarget:self action:@selector(chooseDestination) forControlEvents:UIControlEventTouchUpInside];
    UIStackView *recovery=[[UIStackView alloc] initWithArrangedSubviews:@[_storageReselect,_storageRecovery]];
    recovery.axis=UILayoutConstraintAxisHorizontal; recovery.spacing=12; recovery.distribution=UIStackViewDistributionFillEqually;
    UIStackView *head=[[UIStackView alloc] initWithArrangedSubviews:@[statusRow,_retry,recovery,_destinationPicker]];
    head.axis=UILayoutConstraintAxisVertical; head.spacing=6;
    _sidebar=[UIScrollView new]; _sidebar.backgroundColor=UIColor.secondarySystemBackgroundColor;
    NSLayoutConstraint *sidebarWidth=[_sidebar.widthAnchor constraintEqualToConstant:196];
    sidebarWidth.priority=999; sidebarWidth.active=YES;
    UIStackView *navigation=[UIStackView new]; navigation.axis=UILayoutConstraintAxisVertical; navigation.spacing=3;
    navigation.translatesAutoresizingMaskIntoConstraints=NO; [_sidebar addSubview:navigation];
    NSMutableArray *buttons=[NSMutableArray new];
    NSArray *icons=@[@"server.rack",@"person.crop.circle",@"slider.horizontal.3",@"externaldrive",@"paintbrush.pointed",@"cube",@"gearshape",@"camera",@"arrow.down.circle",@"questionmark.circle"];
    for (NSInteger index=0;index<(NSInteger)elichika::Destination::count;++index) {
        UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem]; button.tag=index;
        button.contentHorizontalAlignment=UIControlContentHorizontalAlignmentLeading;
        button.contentEdgeInsets=UIEdgeInsetsMake(8,10,8,8); button.layer.cornerRadius=6;
        button.titleLabel.font=[UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline];
        [button setImage:[UIImage systemImageNamed:icons[index]] forState:UIControlStateNormal];
        button.imageEdgeInsets=UIEdgeInsetsMake(0,0,0,8);
        [button.heightAnchor constraintGreaterThanOrEqualToConstant:36].active=YES;
        [button addTarget:self action:@selector(destinationPressed:) forControlEvents:UIControlEventTouchUpInside];
        [navigation addArrangedSubview:button]; [buttons addObject:button];
    }
    UILabel *guidance=[UILabel new]; guidance.numberOfLines=0; guidance.textColor=UIColor.secondaryLabelColor;
    guidance.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2];
    guidance.text=ELButtonText(@"Hide the button for MV. Hold upper-right 2s to reopen.",
        @"MV 중 버튼 숨기기\n오른쪽 위 2초 길게 눌러 다시 열기",@"MV中はボタンを非表示に。右上を2秒長押しで再表示。");
    [navigation addArrangedSubview:guidance]; _destinationButtons=buttons;
    _sidebarContentWidth=[navigation.widthAnchor constraintEqualToAnchor:_sidebar.frameLayoutGuide.widthAnchor constant:-16];
    [NSLayoutConstraint activateConstraints:@[
        [navigation.topAnchor constraintEqualToAnchor:_sidebar.contentLayoutGuide.topAnchor constant:8],
        [navigation.bottomAnchor constraintEqualToAnchor:_sidebar.contentLayoutGuide.bottomAnchor constant:-8],
        [navigation.leadingAnchor constraintEqualToAnchor:_sidebar.contentLayoutGuide.leadingAnchor constant:8],
        [navigation.trailingAnchor constraintEqualToAnchor:_sidebar.contentLayoutGuide.trailingAnchor constant:-8]]];
    UIStackView *body=[[UIStackView alloc] initWithArrangedSubviews:@[_sidebar,_webContainer]];
    body.axis=UILayoutConstraintAxisHorizontal; body.spacing=0;
    head.translatesAutoresizingMaskIntoConstraints=NO; body.translatesAutoresizingMaskIntoConstraints=NO;
    [_webContainer setContentHuggingPriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    [self.view addSubview:head]; [self.view addSubview:body];
    UILayoutGuide *safe=self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [head.topAnchor constraintEqualToAnchor:safe.topAnchor constant:8],
        [head.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [head.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [body.topAnchor constraintEqualToAnchor:head.bottomAnchor constant:6],
        [body.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [body.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [body.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor]]];
    [self activateSection:0]; [self refresh];
}
- (NSString *)destinationTitle:(NSInteger)destination {
    NSArray *titles=@[ELButtonText(@"Server",@"서버",@"サーバー"),ELButtonText(@"Accounts",@"계정",@"アカウント"),
        ELButtonText(@"Server settings",@"서버 설정",@"サーバー設定"),ELButtonText(@"Content",@"서버 콘텐츠",@"コンテンツ"),
        ELButtonText(@"Asset tools",@"에셋 편집 도구",@"アセット編集"),ELButtonText(@"3D model",@"3D 모델",@"3Dモデル"),
        ELButtonText(@"App settings",@"앱 설정",@"アプリ設定"),ELButtonText(@"Game settings",@"게임 설정",@"ゲーム設定"),
        ELButtonText(@"Downloads",@"다운로드",@"ダウンロード"),ELButtonText(@"Help",@"도움말",@"ヘルプ")];
    return destination>=0 && destination<(NSInteger)titles.count ? titles[destination] : @"Elichika";
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    BOOL wide=elichika::wideNavigation(self.view.bounds.size.width);
    // A hidden arranged sidebar collapses to width zero. Do not leave its
    // content constrained to zero-minus-insets during compact layout.
    if (_sidebarContentWidth.active!=wide) _sidebarContentWidth.active=wide;
    _sidebar.hidden=!wide; _destinationPicker.hidden=wide;
}
- (void)destinationPressed:(UIButton *)sender { [self selectDestination:sender.tag]; }
- (void)chooseDestination {
    UIAlertController *menu=[UIAlertController alertControllerWithTitle:@"Elichika" message:nil preferredStyle:UIAlertControllerStyleActionSheet];
    for (NSInteger index=0;index<(NSInteger)elichika::Destination::count;++index) {
        UIAlertAction *action=[UIAlertAction actionWithTitle:[self destinationTitle:index] style:UIAlertActionStyleDefault
            handler:^(__unused UIAlertAction *selected) { [self selectDestination:index]; }];
        action.enabled=_managementAvailable || index==(NSInteger)elichika::Destination::gameSettings;
        [menu addAction:action];
    }
    [menu addAction:[UIAlertAction actionWithTitle:ELButtonText(@"Cancel",@"취소",@"キャンセル") style:UIAlertActionStyleCancel handler:nil]];
    menu.popoverPresentationController.sourceView=_destinationPicker;
    menu.popoverPresentationController.sourceRect=_destinationPicker.bounds;
    [self presentViewController:menu animated:YES completion:nil];
}
- (void)selectDestination:(NSInteger)destination {
    if (destination<0 || destination>=(NSInteger)elichika::Destination::count) return;
    const auto choice=static_cast<elichika::Destination>(destination);
    if (choice==elichika::Destination::gameSettings) { [self showGameSettings]; return; }
    if (!_managementAvailable) return;
    _selectedDestination=destination; _selectedWebSection=elichika::webSection(choice);
    if (const char *page=elichika::managementPage(choice)) _managementPage=[NSString stringWithUTF8String:page];
    if (const char *page=elichika::editorPage(choice)) _editorPage=[NSString stringWithUTF8String:page];
    [self openSection];
}
- (void)applyDestinationToWebView:(WKWebView *)web {
    if (!web || web.loading || !ELIsPanelURL(web.URL)) return;
    NSString *script=nil;
    if (web==_sectionWebViews[@0]) script=[NSString stringWithFormat:
        @"window.ElichikaManagementNavigate&&window.ElichikaManagementNavigate(%@)",ELJSON(_managementPage ?: @"server")];
    else if (web==_sectionWebViews[@3]) script=[NSString stringWithFormat:
        @"window.ElichikaNavigation&&window.ElichikaNavigation.showSection(%@,{notify:false})",ELJSON(_editorPage ?: @"tools")];
    if (script) [web evaluateJavaScript:script completionHandler:nil];
}
- (void)showGameSettings {
    UIViewController *presenter=ElichikaHostPresenter();
    if (!presenter || presenter.isBeingPresented || presenter.isBeingDismissed || presenter.presentedViewController) return;
    if (!ELClientControlsAvailable()) {
        UIAlertController *notice=[UIAlertController alertControllerWithTitle:[self destinationTitle:7]
            message:ELButtonText(@"Game controls are not ready yet. Open the game first; the original client must finish initializing its controls.",
                @"게임 설정이 아직 준비되지 않았습니다. 게임을 먼저 열어 클라이언트의 설정 초기화를 마쳐 주세요.",
                @"ゲーム設定はまだ準備中です。ゲームを開いてクライアントの初期化を完了してください。") preferredStyle:UIAlertControllerStyleAlert];
        [notice addAction:[UIAlertAction actionWithTitle:ELButtonText(@"OK",@"확인",@"OK") style:UIAlertActionStyleCancel handler:nil]];
        [presenter presentViewController:notice animated:YES completion:nil]; return;
    }
    NSUserDefaults *defaults=NSUserDefaults.standardUserDefaults;
    BOOL fast=[defaults boolForKey:@"SIFASFastIntro"];
    NSString *detail=ELButtonText(@"FOV, screen orientation and intro speed use the original client controls. Hold upper-right for two seconds to reopen this menu.",
        @"시야각·화면 방향·인트로 속도를 설정합니다. 오른쪽 위를 2초 길게 누르면 서버·게임 메뉴를 다시 열 수 있습니다.",
        @"視野角・画面の向き・イントロ速度を設定します。右上を2秒長押しでサーバー・ゲームメニューを再び開けます。");
    UIAlertController *menu=[UIAlertController alertControllerWithTitle:[self destinationTitle:7] message:detail preferredStyle:UIAlertControllerStyleAlert];
    __weak UIAlertController *weakMenu=menu;
    void (^add)(NSString *,void (^)(void))=^(NSString *title,void (^action)(void)) {
        [menu addAction:[UIAlertAction actionWithTitle:title style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *selected) {
            ELAfterMenuDismissal(weakMenu,action);
        }]];
    };
    [menu addAction:[UIAlertAction actionWithTitle:ELButtonText(@"Adjust FOV",@"시야각(FOV) 조절",@"視野角(FOV)調整")
        style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *selected) { ELClientControlRoute(weakMenu,@"showCamera",nil); }]];
    [menu addAction:[UIAlertAction actionWithTitle:ELButtonText(@"Orientation lock",@"화면 방향 고정",@"画面の向きを固定")
        style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *selected) { ELClientControlRoute(weakMenu,@"showOrientation",nil); }]];
    add(ELButtonText(@"Export MV as MP4",@"MV를 MP4로 내보내기",@"MVをMP4に書き出す"),^{
        ElichikaPresentMVExportMenu(ElichikaHostPresenter());
    });
    add(fast ? ELButtonText(@"Fast intro: On",@"인트로 빠르게: 켜짐",@"イントロ高速:オン")
             : ELButtonText(@"Fast intro: Off",@"인트로 빠르게: 꺼짐",@"イントロ高速:オフ"),^{
        [defaults setBool:!fast forKey:@"SIFASFastIntro"]; ELClientApplyPreferences();
    });
    add(ELButtonText(@"Restore game view defaults",@"게임 보기 설정 초기화",@"ゲーム表示設定を初期化"),^{
        [defaults setDouble:0.75 forKey:@"SIFASFOVMinimum"]; [defaults setDouble:1.0 forKey:@"SIFASFOVMaximum"];
        [defaults setBool:NO forKey:@"SIFASFastIntro"]; [defaults setInteger:0 forKey:@"SIFASOrientation"];
        ELClientApplyPreferences();
    });
    [menu addAction:[UIAlertAction actionWithTitle:ELButtonText(@"Done",@"닫기",@"閉じる") style:UIAlertActionStyleCancel handler:nil]];
    [presenter presentViewController:menu animated:YES completion:nil];
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
        NSNumber *section=@(_selectedWebSection); NSString *entry=_sectionTargets[section];
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
- (void)reselectStorage {
    if (!ELStorageError || ELCore().started()) return;
    _storageReselect.enabled=NO;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
        NSError *error=nil; NSDictionary *result=ELChooseAssetDirectory(&error);
        dispatch_async(dispatch_get_main_queue(),^{
            self.storageReselect.enabled=YES;
            if (error || !result) {
                if (!(error.code==2 && [error.domain isEqual:@"ElichikaDocument"])) ELHookError=error.localizedDescription;
                [self refresh]; return;
            }
            // Recovery precedes successful setup, so no Python scope/jobs use
            // an old library. A running session still needs a process restart.
            if (!ELCore().started()) {
                ELStorageError=NO; ELConfiguration=nil; ELHookError=nil; ELBeginBackend();
            }
        });
    });
}
- (void)restoreStorage {
    if (!ELStorageError || ELCore().started()) return;
    NSError *error=nil;
    if (!ELRestoreAssetDirectory(&error)) { ELHookError=error.localizedDescription; [self refresh]; return; }
    ELStorageError=NO; ELConfiguration=nil; ELHookError=nil; ELBeginBackend();
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
    _statusLabel.numberOfLines=error.length ? 0 : 1;
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
    _storageReselect.hidden=!ELStorageError;
    _managementAvailable=elichika::managementAvailable(ELCore().started(),ELCore().ready(),ELPanelReady())
        && ![ELConfiguration[@"core_only"] boolValue];
    NSString *language=ELConfiguration[@"language"] ?: @"";
    if (_renderedDestination!=_selectedDestination || _renderedAvailable!=_managementAvailable || ![_renderedLanguage isEqual:language]) {
        _renderedDestination=_selectedDestination; _renderedAvailable=_managementAvailable; _renderedLanguage=language;
        for (UIButton *button in _destinationButtons) {
            [button setTitle:[self destinationTitle:button.tag] forState:UIControlStateNormal];
            button.enabled=_managementAvailable || button.tag==(NSInteger)elichika::Destination::gameSettings;
            button.backgroundColor=button.tag==_selectedDestination ? [self.view.tintColor colorWithAlphaComponent:0.14] : UIColor.clearColor;
        }
        [_destinationPicker setTitle:[[self destinationTitle:_selectedDestination] stringByAppendingString:@"  ▾"] forState:UIControlStateNormal];
    }
    self.navigationItem.rightBarButtonItem.enabled=ELCore().started();
    if (_managementAvailable && !_initialPanelLoaded) { _initialPanelLoaded=YES; [self openSection]; }
}
- (void)openSection {
    NSString *url;
    if (_selectedWebSection==0) {
        NSURLComponents *parts=[NSURLComponents componentsWithString:ELRuntimeStatus[@"admin_url"] ?: @""];
        parts.path=@"/ios/"; parts.fragment=nil; url=parts.URL.absoluteString;
    }
    else if (_selectedWebSection==1) url=[ELAccountsURL() absoluteString];
    else if (_selectedWebSection==2) url=ELRuntimeStatus[@"admin_url"];
    else url=ELRuntimeStatus[@"tools_url"];
    NSURL *target=[NSURL URLWithString:url ?: @""];
    if (!ELIsPanelURL(target)) return;
    NSInteger section=_selectedWebSection;
    WKWebView *web=[self activateSection:section]; if (!web) return;
    // Internal navigation belongs to this retained document. Comparing its
    // original entry URL (including auth/origin) avoids reloading editors when
    // a tab is revisited, while a server-origin change still gets a fresh page.
    if (![_sectionTargets[@(section)] isEqual:target.absoluteString]) [self loadPanelURL:target];
    else [self applyDestinationToWebView:web];
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
        NSString *script=@"(()=>{window.ElichikaUnifiedNavigation=true;const p=new Map();let n=0;const d=(globalThis.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+'-'+Math.random();window.__elichikaNativeDocument=d;window.ElichikaIOS=Object.freeze({request:(action,options={})=>new Promise((resolve,reject)=>{const id=String(++n);p.set(id,{resolve,reject});window.webkit.messageHandlers.elichika.postMessage({...options,id,action,document:d});})});window.addEventListener('elichika-native-result',e=>{const x=e.detail;if(!x||x.document!==d)return;const j=p.get(x.id);if(j){p.delete(x.id);x.error?j.reject(Error(x.error)):j.resolve(x.result)}})})();";
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
    NSInteger section=_selectedWebSection;
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
- (void)webView:(WKWebView *)web didFinishNavigation:(WKNavigation *)navigation {
    [self applyDestinationToWebView:web];
#if ELICHIKA_SIMULATOR_PROBE
    [self probeWebView:web didFinishNavigation:navigation];
#else
    (void)navigation;
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
    _selectedWebSection=[service isEqual:@"admin"] ? 2 : 3;
    _storageProbeNavigation=[self loadPanelURL:target];
    if (!_storageProbeNavigation) { [self finishStorageProbe:[self failedStorageProbe:@"Could not navigate the actual management WebView."]]; return; }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        if (self.storageProbeReply && self.storageProbeGeneration==generation)
            [self finishStorageProbe:[self failedStorageProbe:@"Management WebView storage probe timed out."]];
    });
}
- (void)probeWebView:(WKWebView *)web didFinishNavigation:(WKNavigation *)navigation {
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
        self.selectedWebSection=3; [self openSection];
        if (self.web!=tools) { [self finishManagementProbe:@"Revisiting Tools replaced its retained WebView."]; return; }
        NSString *toolSeed=[seed stringByAppendingString:@";window.ElichikaIOS.request('__probe_deferred_status').then(v=>{window.__elichikaRetentionProbe.reply=v.returned_to_origin===true&&v.other_tab_active===true});true;"];
        [tools evaluateJavaScript:toolSeed completionHandler:^(id seeded,NSError *seedError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (seedError || ![seeded isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Could not seed the actual Tools document and deferred native request.",seedError)]; return; }
            self.selectedWebSection=0; [self openSection];
            if (self.web!=manage) { [self finishManagementProbe:@"Revisiting Manage replaced its retained WebView."]; return; }
            self.selectedWebSection=2; [self openSection];
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
        self.selectedWebSection=3; [self openSection];
        if (self.web!=tools) { [self finishManagementProbe:@"Tools was recreated after hiding and reopening management."]; return; }
        [tools evaluateJavaScript:check completionHandler:^(id visible,NSError *visibleError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (visibleError || ![visible isKindOfClass:NSDictionary.class] || ![visible[@"same"] isEqual:@YES] || ![visible[@"reply"] isEqual:@YES]) {
                [self finishManagementProbe:ELProbeJavaScriptFailure(@"Revisiting Tools discarded its document state or deferred native reply.",visibleError)]; return;
            }
            self.selectedWebSection=0; [self openSection];
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
            self.selectedWebSection=section.integerValue; [self openSection];
            if (self.web!=retained) { [self finishManagementProbe:@"A management tab was recreated during the Accounts retention check."]; return; }
        }
        NSString *check=[NSString stringWithFormat:@"(()=>{const a=%@,p=window.__elichikaAccountRetention,f=document.getElementById('elichika-retention-account-draft');return !!p&&p.token===a.token&&p.pagehide===0&&!!f&&f.value==='unsaved account draft';})()",ELJSON(arguments)];
        [accounts evaluateJavaScript:check completionHandler:^(id retained,NSError *retainedError) {
            if (!self.managementProbeReply || self.managementProbeGeneration!=generation) return;
            if (retainedError || ![retained isEqual:@YES]) { [self finishManagementProbe:ELProbeJavaScriptFailure(@"Accounts lost its unsaved form state after visiting the other three tabs.",retainedError)]; return; }
            self.selectedWebSection=0; [self openSection];
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
    BOOL nativeStopped=ELCore().started() && !ELCore().ready() && ELPanelReady() && _managementAvailable;
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
                    if (![value[@"offline_accounts"] isEqual:@YES] || ELCore().ready() || !ELPanelReady() || !self.managementAvailable) {
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
                    self.managementProof[@"go_stopped"]=@YES; self.managementProbeStep=2; self.selectedWebSection=1;
                    self.managementProbeHTTPStatus=0; self.managementProbeNavigation=[self loadPanelURL:ELAccountsURL()];
                    if (!self.managementProbeNavigation) [self finishManagementProbe:@"Could not open Accounts while the game server was stopped."];
                    return;
                }
                else if (self.managementProbeStep==3 && [value[@"requested"] isEqual:@"start"]) self.managementProbeStep=4;
                else if (self.managementProbeStep==4 && [value[@"server_ready"] boolValue] && ELCore().ready() && self.managementAvailable) {
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
    parts.path=@"/ios/"; parts.fragment=nil; _selectedWebSection=0;
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
        NSError *error=nil; NSDictionary *result=ELRestoreAssetDirectory(&error);
        [self reply:identifier inWebView:source document:document result:result error:error.localizedDescription]; return;
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
    ELInstallClientMenuBridge();
    UIWindow *window=ELFindGameWindow(); if (!window) return;
    ELGameWindow=window;
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
        ELMenuButton.accessibilityLabel=ELButtonText(@"Server and game settings",@"서버·게임 설정",@"サーバー・ゲーム設定");
        ELMenuButton.backgroundColor=[UIColor.systemBackgroundColor colorWithAlphaComponent:0.88];
        ELMenuButton.layer.cornerRadius=9;
        [ELMenuButton addTarget:ELMenuTarget() action:@selector(show) forControlEvents:UIControlEventTouchUpInside];
    }
    if (ELMenuButton.superview!=window) [window addSubview:ELMenuButton];
    ELMenuButton.hidden=!ELButtonPolicy().visible();
    ELMenuButton.frame=CGRectMake(MAX(8,window.bounds.size.width-window.safeAreaInsets.right-90),window.safeAreaInsets.top+8,82,34);
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
    return !gesture.view.window.rootViewController.presentedViewController &&
        elichika::ServerButtonPolicy::restoreCorner(point.x,point.y,bounds.size.width,bounds.size.height,safe.right,safe.top);
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
    NSData *savedBookmark=[NSUserDefaults.standardUserDefaults dataForKey:ELAssetBookmarkKey];
    NSData *bookmark=nil; NSString *bookmarkMode=@"app_storage";
    __attribute__((objc_precise_lifetime)) ELAssetScopeLease *lease=nil;
    NSData *renewedBookmark=nil;
    if (savedBookmark) {
        BOOL stale=NO; NSError *bookmarkError=nil;
        bookmark=ELReadAssetBookmark(savedBookmark,&bookmarkMode,&bookmarkError);
        NSURL *url=bookmark ? [NSURL URLByResolvingBookmarkData:bookmark options:ELAssetBookmarkResolutionOptions(bookmarkMode)
            relativeToURL:nil bookmarkDataIsStale:&stale error:&bookmarkError] : nil;
        if (!url.isFileURL) {
            ELStorageError=YES; *error=ELAssetFolderError(ELButtonText(@"The saved asset folder could not be reopened. Select it again or use the default folder.",
                @"저장된 에셋 폴더를 다시 열지 못했습니다. 같은 폴더를 다시 선택하거나 기본 폴더를 사용하세요.",
                @"保存したアセットフォルダーを再び開けませんでした。同じフォルダーを再選択するか、既定の保存先を使用してください。"),
                [NSUserDefaults.standardUserDefaults stringForKey:ELAssetPathKey],bookmarkError).localizedDescription; return NO;
        }
        // Access must precede even metadata reads on a picker/bookmark URL.
        lease=[[ELAssetScopeLease alloc] initWithURL:url];
        NSNumber *directory=nil;
        if (![url getResourceValue:&directory forKey:NSURLIsDirectoryKey error:&bookmarkError] || !directory.boolValue ||
            !([manager isReadableFileAtPath:url.path] && [manager isWritableFileAtPath:url.path])) {
            ELStorageError=YES; *error=ELAssetFolderError(ELButtonText(@"Access to the saved asset folder is unavailable. Select it again.",
                @"저장된 에셋 폴더에 접근할 수 없습니다. 같은 폴더를 다시 선택하세요.",
                @"保存したアセットフォルダーにアクセスできません。同じフォルダーを再選択してください。"),url.path,bookmarkError).localizedDescription; return NO;
        }
        library=url.path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
        if (stale) {
            NSData *raw=ELCreateAssetBookmark(url,&bookmarkMode,&bookmarkError);
            renewedBookmark=raw ? ELStoreAssetBookmark(raw,bookmarkMode,&bookmarkError) : nil;
            if (!renewedBookmark) {
                ELStorageError=YES; *error=ELAssetFolderError(ELButtonText(@"Could not renew saved access to the asset folder.",
                    @"에셋 폴더의 저장된 접근 권한을 갱신하지 못했습니다.",@"アセットフォルダーへの保存済みアクセスを更新できませんでした。"),url.path,bookmarkError).localizedDescription; return NO;
            }
        }
    }
    NSString *packs=[library stringByAppendingPathComponent:@"packs"];
    NSString *imports=[library stringByAppendingPathComponent:@"imports"];
    NSString *resources=[NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"ElichikaResources"];
    if (!ELReadCandidateMode(resources,error)) return NO;
    NSError *storageFailure=nil;
    if (![manager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:@{NSFileProtectionKey:NSFileProtectionCompleteUntilFirstUserAuthentication} error:&storageFailure]) {
        *error=ELAssetFolderError(@"Could not prepare app-private server storage.",root,storageFailure).localizedDescription; return NO;
    }
    if (!ELPrepareAssetFolders(library,&storageFailure)) {
        ELStorageError=YES; *error=storageFailure.localizedDescription; return NO;
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
        @"bookmark_mode":bookmarkMode,@"access_lifetime":bookmark ? ELAssetBookmarkLifetime(bookmarkMode) : @"app_storage",
        @"persistence_warning":ELAssetBookmarkWarning(bookmarkMode),
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
    if (bookmark) {
        if (renewedBookmark) [NSUserDefaults.standardUserDefaults setObject:renewedBookmark forKey:ELAssetBookmarkKey];
        [NSUserDefaults.standardUserDefaults setObject:library forKey:ELAssetPathKey];
        [lease keepUntilExit]; ELActiveLibraryURL=lease.url;
    }
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
static NSDictionary *ELProbeClientCounters(id fixture) {
    SEL selector=NSSelectorFromString(@"probeCounters");
    if (![fixture respondsToSelector:selector]) return @{};
    id result=((id (*)(id,SEL))[fixture methodForSelector:selector])(fixture,selector);
    return [result isKindOfClass:NSDictionary.class] ? result : @{};
}
void ElichikaHostProbeUnifiedMenu(id fixture,void (^completion)(NSDictionary *)) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(),^{ ElichikaHostProbeUnifiedMenu(fixture,completion); }); return; }
    NSMutableDictionary *proof=[@{@"ready":@NO,@"fake_client_controls":@YES,@"real_game_fov":@NO,
        @"source_tag":@"SIMULATOR_FAKE_CLIENT_UI_ONLY",@"original_poll_preserved":@NO,@"old_button_hidden":@NO,
        @"old_gesture_disabled":@NO,@"decoys_unchanged":@NO,@"show_settings_redirected":@NO,@"fov_route":@NO,
        @"orientation_route":@NO,@"right_corner_gesture":@NO,@"wide_sidebar":@NO,@"compact_navigation":@NO,
        @"retained_navigation":@NO} mutableCopy];
    if (![fixture isKindOfClass:NSClassFromString(@"SIFASFeatures")] || !ELCore().started() || !ELPanel.managementAvailable) {
        proof[@"error"]=@"The initialized Simulator-only client fixture or retained panel is unavailable."; completion(proof); return;
    }
    ELInstallClientMenuBridge(); ELHidePanel(); ELRefreshMenu();
    NSUInteger before=[ELProbeClientCounters(fixture)[@"poll"] unsignedIntegerValue];
    SEL poll=@selector(poll:),settings=@selector(showSettings);
    ((void (*)(id,SEL,id))[fixture methodForSelector:poll])(fixture,poll,nil);
    ((void (*)(id,SEL))[fixture methodForSelector:settings])(fixture,settings);
    proof[@"show_settings_redirected"]=@(!ELPanelWindow.hidden && ELPanelWindow.isKeyWindow &&
        [ELProbeClientCounters(fixture)[@"settings"] unsignedIntegerValue]==0);
    ((void (*)(id,SEL,id))[fixture methodForSelector:poll])(fixture,poll,nil);
    NSDictionary *counters=ELProbeClientCounters(fixture);
    proof[@"original_poll_preserved"]=@([counters[@"poll"] unsignedIntegerValue]>=before+2 && ELClientControls==fixture);
    proof[@"old_button_hidden"]=counters[@"button_hidden"] ?: @NO;
    proof[@"old_gesture_disabled"]=@(![counters[@"shortcut_enabled"] boolValue]);
    proof[@"decoys_unchanged"]=@(![counters[@"decoy_button_hidden"] boolValue] && [counters[@"decoy_shortcut_enabled"] boolValue]);
    BOOL shortcut=NO;
    for (UIGestureRecognizer *recognizer in ELGameWindow.gestureRecognizers)
        if ([recognizer isKindOfClass:UILongPressGestureRecognizer.class] && recognizer.delegate==ELMenuTarget()) {
            UILongPressGestureRecognizer *hold=(UILongPressGestureRecognizer *)recognizer;
            shortcut=hold.enabled && hold.minimumPressDuration==2.0 && !hold.cancelsTouchesInView &&
                !hold.delaysTouchesBegan && !hold.delaysTouchesEnded;
        }
    CGRect game=ELGameWindow.bounds; UIEdgeInsets inset=ELGameWindow.safeAreaInsets;
    proof[@"right_corner_gesture"]=@(shortcut &&
        elichika::ServerButtonPolicy::restoreCorner(game.size.width-1,1,game.size.width,game.size.height,inset.right,inset.top) &&
        !elichika::ServerButtonPolicy::restoreCorner(1,1,game.size.width,game.size.height,inset.right,inset.top));
    CGRect prior=ELPanel.view.bounds;
    ELPanel.view.bounds=CGRectMake(0,0,1024,768); [ELPanel.view setNeedsLayout]; [ELPanel.view layoutIfNeeded];
    proof[@"wide_sidebar"]=@(!ELPanel.sidebar.hidden && ELPanel.destinationPicker.hidden &&
        ELPanel.sidebar.bounds.size.width>=180 && ELPanel.webContainer.bounds.size.width>500 &&
        !ELPanel.webContainer.hasAmbiguousLayout);
    ELPanel.view.bounds=CGRectMake(0,0,390,844); [ELPanel.view setNeedsLayout]; [ELPanel.view layoutIfNeeded];
    proof[@"compact_navigation"]=@(ELPanel.sidebar.hidden && !ELPanel.destinationPicker.hidden &&
        ELPanel.sidebar.bounds.size.width<1 && ELPanel.webContainer.bounds.size.width>300 &&
        !ELPanel.webContainer.hasAmbiguousLayout);
    ELPanel.view.bounds=prior; [ELPanel.view setNeedsLayout]; [ELPanel.view layoutIfNeeded];
    NSDictionary *documents=[ELPanel.sectionWebViews copy];
    if (documents.count!=4 || !documents[@0] || !documents[@3]) {
        proof[@"error"]=@"The four retained WebKit documents were not available."; completion(proof); return;
    }
    NSString *token=NSUUID.UUID.UUIDString;
    NSString *seed=[NSString stringWithFormat:@"window.__elichikaUnifiedMenuToken=%@;window.__elichikaNativeDocument",ELJSON(token)];
    WKWebView *management=documents[@0],*editor=documents[@3];
    [management evaluateJavaScript:seed completionHandler:^(id managementNonce,NSError *managementError) {
        [editor evaluateJavaScript:seed completionHandler:^(id editorNonce,NSError *editorError) {
            if (managementError || editorError || ![managementNonce isKindOfClass:NSString.class] || ![editorNonce isKindOfClass:NSString.class]) {
                proof[@"error"]=@"The real retained documents could not be seeded."; completion(proof); return;
            }
            NSArray *routes=@[@[@0,@0,@"home"],@[@2,@0,@"server"],@[@6,@0,@"app"],@[@8,@0,@"downloads"],
                @[@9,@0,@"help"],@[@4,@3,@"tools"],@[@5,@3,@"viewer"]];
            __block void (^next)(NSUInteger);
            void (^finish)(NSString *)=^(NSString *error) {
                next=nil; [ELPanel selectDestination:0];
                BOOL ready=!error.length;
                for (NSString *key in @[@"original_poll_preserved",@"old_button_hidden",@"old_gesture_disabled",@"decoys_unchanged",
                    @"show_settings_redirected",@"fov_route",@"orientation_route",@"right_corner_gesture",@"wide_sidebar",
                    @"compact_navigation",@"retained_navigation"]) ready=ready && [proof[key] boolValue];
                proof[@"ready"]=@(ready);
                if (error.length) proof[@"error"]=error;
                else if (!ready) proof[@"error"]=@"A native menu or fake-client dispatch assertion failed.";
                completion([proof copy]);
            };
            next=^(NSUInteger index) {
                if (index<routes.count) {
                    NSArray *route=routes[index]; [ELPanel selectDestination:[route[0] integerValue]];
                    WKWebView *web=documents[route[1]];
                    NSString *page=[route[1] isEqual:@0] ? @"window.ElichikaManagementProof.page" : @"window.ElichikaNavigation.currentSection()";
                    NSString *script=[NSString stringWithFormat:@"({page:%@,nonce:window.__elichikaNativeDocument,token:window.__elichikaUnifiedMenuToken,unified:window.ElichikaUnifiedNavigation===true})",page];
                    [web evaluateJavaScript:script completionHandler:^(id value,NSError *error) {
                        NSString *nonce=[route[1] isEqual:@0] ? managementNonce : editorNonce;
                        BOOL same=ELPanel.web==web && !web.loading && [value isKindOfClass:NSDictionary.class] &&
                            [value[@"page"] isEqual:route[2]] && [value[@"nonce"] isEqual:nonce] &&
                            [value[@"token"] isEqual:token] && [value[@"unified"] isEqual:@YES];
                        for (NSNumber *key in documents) same=same && ELPanel.sectionWebViews[key]==documents[key];
                        if (error || !same) { finish(@"Native navigation changed a document or failed to select its requested page."); return; }
                        next(index+1);
                    }]; return;
                }
                proof[@"retained_navigation"]=@YES;
                UIViewController *presenter=ElichikaHostPresenter();
                UIAlertController *camera=[UIAlertController alertControllerWithTitle:@"Fake client route probe" message:nil preferredStyle:UIAlertControllerStyleAlert];
                [camera addAction:[UIAlertAction actionWithTitle:@"Close" style:UIAlertActionStyleCancel handler:nil]];
                NSUInteger cameraBefore=[ELProbeClientCounters(fixture)[@"camera"] unsignedIntegerValue];
                [presenter presentViewController:camera animated:NO completion:^{
                    ELClientControlRoute(camera,@"showCamera",^(BOOL delivered) {
                        proof[@"fov_route"]=@(delivered && [ELProbeClientCounters(fixture)[@"camera"] unsignedIntegerValue]==cameraBefore+1 && !presenter.presentedViewController);
                        UIAlertController *orientation=[UIAlertController alertControllerWithTitle:@"Fake client route probe" message:nil preferredStyle:UIAlertControllerStyleAlert];
                        [orientation addAction:[UIAlertAction actionWithTitle:@"Close" style:UIAlertActionStyleCancel handler:nil]];
                        NSUInteger orientationBefore=[ELProbeClientCounters(fixture)[@"orientation"] unsignedIntegerValue];
                        [presenter presentViewController:orientation animated:NO completion:^{
                            ELClientControlRoute(orientation,@"showOrientation",^(BOOL changed) {
                                proof[@"orientation_route"]=@(changed && [ELProbeClientCounters(fixture)[@"orientation"] unsignedIntegerValue]==orientationBefore+1 && !presenter.presentedViewController);
                                finish(nil);
                            });
                        }];
                    });
                }];
            };
            next(0);
        }];
    }];
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
@property(nonatomic,copy) NSString *bookmarkMode;
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
        if (!source.isFileURL) {
            _error=ELAssetFolderError(ELButtonText(@"Choose a local file or folder.",@"로컬 파일 또는 폴더를 선택하세요.",@"ローカルファイルまたはフォルダーを選択してください。"),source.absoluteString,nil); [self finish]; return;
        }
        // UIDocumentPicker grants access on this URL, not on a reconstructed
        // file URL. Opening the scope after getResourceValue already fails.
        BOOL scoped=[source startAccessingSecurityScopedResource];
        _securityScope=scoped; _selectedURL=source;
        if (![source getResourceValue:&directory forKey:NSURLIsDirectoryKey error:&error] ||
            (_selectionKind==1 && !directory.boolValue) || (_selectionKind==2 && directory.boolValue)) {
            _error=ELAssetFolderError(ELButtonText(@"Could not inspect the selected file or folder after requesting access.",
                @"접근 권한을 요청한 뒤에도 선택한 파일 또는 폴더를 확인하지 못했습니다.",
                @"アクセスを要求した後も、選択したファイルまたはフォルダーを確認できませんでした。"),source.path,error); [self finish]; return;
        }
        if (!([NSFileManager.defaultManager isReadableFileAtPath:source.path] && [NSFileManager.defaultManager isWritableFileAtPath:source.path])) {
            _error=ELAssetFolderError(ELButtonText(@"The selected location does not allow reading and saving.",
                @"선택한 위치에서 파일을 읽고 저장할 수 없습니다.",@"選択した場所では読み取りと保存が許可されていません。"),source.path,nil); [self finish]; return;
        }
        if (_selectionKind==1 && [source.lastPathComponent.lowercaseString isEqual:@"packs"]) {
            NSString *message=[NSString stringWithFormat:ELButtonText(@"Select the asset library that contains packs, extracted and modded, rather than packs itself. Choose: %@",
                @"packs 폴더 자체가 아닌, packs·extracted·modded가 들어 있는 에셋 보관 폴더를 선택하세요. 선택할 폴더: %@",
                @"packs 自体ではなく、packs・extracted・modded を含むアセット保存フォルダーを選択してください。選択するフォルダー: %@"),source.URLByDeletingLastPathComponent.path];
            _error=ELAssetFolderError(message,source.path,nil); [self finish]; return;
        }
        NSString *bookmarkMode=nil;
        NSData *bookmark=_selectionKind==1 ? ELCreateAssetBookmark(source,&bookmarkMode,&error) : nil;
        if (_selectionKind==1 && (!bookmark || bookmark.length>262144)) {
            _error=ELAssetFolderError(ELButtonText(@"Could not save access to the selected asset folder.",
                @"선택한 에셋 폴더의 접근 권한을 저장하지 못했습니다.",@"選択したアセットフォルダーへのアクセスを保存できませんでした。"),source.path,error); [self finish]; return;
        }
        _bookmark=bookmark; _bookmarkMode=bookmarkMode; _path=source.path; [self finish]; return;
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
    NSString *selected=transaction.path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    NSError *validationError=nil;
    if (!ELPrepareAssetFolders(selected,&validationError)) { if (error) *error=validationError; return nil; }
    // No saved preference changes until selection, durable access and the
    // actual packs/imports layout have all succeeded.
    NSData *stored=ELStoreAssetBookmark(transaction.bookmark,transaction.bookmarkMode,&validationError);
    if (!stored) { if (error) *error=validationError; return nil; }
    [NSUserDefaults.standardUserDefaults setObject:stored forKey:ELAssetBookmarkKey];
    [NSUserDefaults.standardUserDefaults setObject:selected forKey:ELAssetPathKey];
    if (transaction.securityScope) {
        @synchronized(NSUserDefaults.standardUserDefaults) {
            if (!ELHeldScopes) ELHeldScopes=[NSMutableArray new]; [ELHeldScopes addObject:transaction.selectedURL];
        }
        transaction.securityScope=NO;
    }
    NSString *active=ELConfiguration[@"library_root"] ?: @"";
    BOOL same=[selected isEqual:active];
    return @{@"path":selected,@"active_path":active,@"external":@YES,@"requires_restart":@(!same),@"applied":@(same),
        @"bookmark_mode":transaction.bookmarkMode,@"access_lifetime":ELAssetBookmarkLifetime(transaction.bookmarkMode),
        @"persistence_warning":ELAssetBookmarkWarning(transaction.bookmarkMode)};
}
static NSDictionary *ELRestoreAssetDirectory(NSError **error) {
    NSString *path=[NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"Elichika"];
    path=path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    if (!ELPrepareAssetFolders(path,error)) return nil;
    [NSUserDefaults.standardUserDefaults removeObjectForKey:ELAssetBookmarkKey];
    [NSUserDefaults.standardUserDefaults removeObjectForKey:ELAssetPathKey];
    // Existing security scopes stay alive until process exit. Active jobs and
    // current ELConfiguration continue using the old library until reopening.
    NSString *active=ELConfiguration[@"library_root"] ?: @"";
    BOOL same=[path isEqual:active];
    return @{@"path":path,@"active_path":active,@"external":@NO,@"requires_restart":@(!same),@"applied":@(same),
        @"bookmark_mode":@"app_storage",@"access_lifetime":@"app_storage",@"persistence_warning":@""};
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
