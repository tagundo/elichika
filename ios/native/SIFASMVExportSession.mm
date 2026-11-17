#import "SIFASMVExportSession.h"
#import "SIFASMVExportBindings.h"
#import "ElichikaMVEncoder.h"
#if defined(SIFAS_STANDALONE)
#import "SIFASMVStandaloneAdapter.h"
#define ElichikaHostConfiguration SIFASMVStandaloneConfiguration
#define ElichikaHostShowGame SIFASMVStandaloneShowGame
#define ElichikaHostPresenter SIFASMVStandalonePresenter
#define ElichikaPythonCallWithArguments SIFASMVStandaloneAudioCall
#else
#import "ElichikaPythonRuntime.h"
#import "ElichikaHost.h"
#endif
#include "MVExportClock.hpp"
#include "MVWorkerHandoff.hpp"
#include <atomic>
#include <cmath>
#include <memory>

static NSUInteger ELMVLanguageIndex(void) {
    NSString *language=ElichikaHostConfiguration()[@"language"] ?: NSLocale.preferredLanguages.firstObject;
    return [language hasPrefix:@"ko"] ? 1 : ([language hasPrefix:@"ja"] ? 2 : 0);
}
static NSString *ELMVText(NSString *english, NSString *korean, NSString *japanese) {
    return @[english,korean,japanese][ELMVLanguageIndex()];
}
static NSString *ELMVPhase(NSString *phase) {
    static NSDictionary *labels; static dispatch_once_t once;
    dispatch_once(&once, ^{
        labels=@{@"idle":@[@"Ready",@"준비",@"準備完了"],
                 @"preflight":@[@"Checking storage",@"저장 공간 확인 중",@"空き容量を確認中"],
                 @"snapshot-and-freeze":@[@"Preparing MV",@"MV 준비 중",@"MVを準備中"],
                 @"preparing-song":@[@"Preparing song",@"음원 준비 중",@"楽曲を準備中"],
                 @"starting-encoder":@[@"Starting encoder",@"인코더 시작 중",@"エンコーダーを起動中"],
                 @"rendering":@[@"Rendering",@"렌더링 중",@"レンダリング中"],
                 @"finishing-audio":@[@"Finishing audio",@"오디오 마무리 중",@"音声を処理中"],
                 @"finalizing":@[@"Finalizing MP4",@"MP4 마무리 중",@"MP4を仕上げ中"],
                 @"draining":@[@"Cleaning up",@"정리 중",@"後処理中"],
                 @"completed":@[@"Completed",@"완료",@"完了"],
                 @"cancelled":@[@"Cancelled",@"취소됨",@"キャンセル済み"],
                 @"failed":@[@"Export failed",@"내보내기 실패",@"書き出しに失敗"]};
    });
    NSArray *values=labels[phase];
    return values ? values[ELMVLanguageIndex()] : phase;
}

// The coordinator and all Unity calls belong to main. Each run's encoder,
// pending BGRA frame and pending PCM chunk belong exclusively to worker.
// Only the cancellation bit and progress counters cross those owners.
@interface ELMVExportRun : NSObject {
@public
    std::atomic_bool stopped;
    std::atomic<int64_t> videoCount, audioCount;
    std::atomic<double> lastProgress;
    std::unique_ptr<elichika::MVExportClock> clock;
    uint64_t generation;
    ELMVEncoderConfiguration *configuration;
    NSURL *directory, *output;
    NSString *audioSession, *phase, *message, *terminalPhase;
    BOOL bindingsActive, ready, preparePending, closeStarted, audioClosed;
    BOOL cleaning, workerClean, completed;
    // Worker only.
    ELMVEncoder *encoder;
    ELMVPixelFrame *pendingFrame;
    NSData *pendingPCM;
    NSUInteger pendingRowBytes;
    int64_t pendingFrameIndex, pendingFirstSample;
    BOOL audioRequestPending, pumpScheduled, finishing;
}
@end
@implementation ELMVExportRun
- (instancetype)init {
    if ((self=[super init])) {
        stopped=false; videoCount=0; audioCount=0;
        lastProgress=CFAbsoluteTimeGetCurrent(); pendingFrameIndex=-1;
        phase=@"preflight"; message=@""; terminalPhase=@"";
    }
    return self;
}
@end

@interface ELMVExportCoordinator : NSObject {
    dispatch_queue_t _worker;
    ELMVExportRun *_run;
    uint64_t _generation;
    NSTimer *_watchdog;
    NSDictionary *_lastStatus;
    NSURL *_completedURL;
    __weak UIWindow *_gameWindow;
    UIView *_inputBlocker;
    NSDictionary *_pendingNotice;
    NSTimer *_noticeTimer;
}
+ (instancetype)shared;
- (NSDictionary *)status;
- (NSURL *)completedURL;
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec;
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate;
- (void)cancelWithReason:(NSString *)reason;
- (BOOL)grant:(ELMVExportRun *)run tick:(uint64_t *)tick capture:(int64_t *)capture;
- (void)frame:(ELMVPixelFrame *)pixels rowBytes:(NSUInteger)rowBytes index:(int64_t)index run:(ELMVExportRun *)run;
- (void)acceptedFrameIndex:(int64_t)index run:(ELMVExportRun *)run;
- (void)fail:(NSString *)message run:(ELMVExportRun *)run;
- (void)pump:(ELMVExportRun *)run;
- (void)schedulePump:(ELMVExportRun *)run;
- (void)cleanup:(ELMVExportRun *)run terminal:(NSString *)terminal message:(NSString *)message;
- (void)finishCleanup:(ELMVExportRun *)run;
- (BOOL)installInputBlocker;
- (void)removeInputBlocker;
- (void)showPendingNotice;
@end

static bool ELMVNext(void *context, uint64_t *tick, int64_t *capture) {
    return [[ELMVExportCoordinator shared] grant:(__bridge ELMVExportRun *)context tick:tick capture:capture];
}
static void ELMVFrame(void *context, ELMVPixelFrame *pixels, NSUInteger rowBytes, int64_t capture) {
    [[ELMVExportCoordinator shared] frame:pixels rowBytes:rowBytes index:capture run:(__bridge ELMVExportRun *)context];
}
static void ELMVFailed(void *context, NSString *message) {
    [[ELMVExportCoordinator shared] fail:message run:(__bridge ELMVExportRun *)context];
}
static NSString *ELMVReplyError(NSDictionary *reply) {
    id error=reply[@"error"];
    if ([error isKindOfClass:NSDictionary.class]) {
        NSString *text=[error[@"message"] isKindOfClass:NSString.class] ? error[@"message"] : ELMVText(@"Embedded audio operation failed.",@"내장 오디오 작업에 실패했습니다.",@"内蔵音声処理に失敗しました。");
        NSString *code=[error[@"code"] isKindOfClass:NSString.class] ? error[@"code"] : @"MV_AUDIO";
        return [NSString stringWithFormat:@"%@: %@",code,text];
    }
    return [error isKindOfClass:NSString.class] ? error : ELMVText(@"Embedded audio operation returned an invalid response.",@"내장 오디오 작업이 올바르지 않은 응답을 반환했습니다.",@"内蔵音声処理から無効な応答が返されました。");
}
static BOOL ELMVInteger(id value, int64_t minimum, int64_t maximum, int64_t *result) {
    if (![value isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)value)==CFBooleanGetTypeID()) return NO;
    double real=[value doubleValue]; int64_t integer=[value longLongValue];
    if (!std::isfinite(real) || real!=double(integer) || integer<minimum || integer>maximum) return NO;
    if (result) *result=integer;
    return YES;
}
static NSDictionary *ELMVValidatedSong(NSDictionary *snapshot, int64_t *milliseconds) {
    if (![snapshot isKindOfClass:NSDictionary.class]) return nil;
    NSString *sheet=snapshot[@"sheet"], *cue=snapshot[@"cue"];
    const unichar nul=0;
    NSString *zero=[NSString stringWithCharacters:&nul length:1];
    for (id text in @[sheet ?: NSNull.null,cue ?: NSNull.null]) {
        if (![text isKindOfClass:NSString.class] || ![text length] || [text length]>240 ||
            [text rangeOfString:zero].location!=NSNotFound) return nil;
    }
    id gain=snapshot[@"gain"];
    if (![gain isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)gain)==CFBooleanGetTypeID() ||
        !std::isfinite([gain doubleValue]) || [gain doubleValue]<0 || [gain doubleValue]>4) return nil;
    int64_t length=0,start=0,offset=0;
    if (!ELMVInteger(snapshot[@"music_length_ms"],1,1200000,&length) ||
        !ELMVInteger(snapshot[@"start_time_ms"],-1200000,1200000,&start) ||
        !ELMVInteger(snapshot[@"source_offset_ms"],0,1200000,&offset)) return nil;
    *milliseconds=length;
    return @{@"sheet":sheet,@"cue":cue,@"gain":gain,@"music_length_ms":@(length),
             @"start_time_ms":@(start),@"source_offset_ms":@(offset)};
}
static NSString *ELMVReadiness(void) {
    NSDictionary *native=SIFASMVBindingsStatus();
    if (![native[@"installed"] boolValue]) return ELMVText(@"This installation has no verified offline MV renderer. Install the matching GL 3.12.0 export build.",@"이 설치에는 검증된 오프라인 MV 렌더러가 없습니다. GL 3.12.0용 내보내기 빌드를 설치하세요.",@"検証済みのオフラインMVレンダラーがありません。対応するGL 3.12.0の書き出しビルドをインストールしてください。");
    if (![native[@"liveDirectorObserved"] boolValue])
        return ELMVText(@"Load and play a 3D MV until the complete stage is visible, then open MP4 export.",@"3D MV를 재생하여 무대 전체가 표시된 후 MP4 내보내기를 여세요.",@"3D MVを再生し、ステージ全体が表示されてからMP4書き出しを開いてください。");
    return @"";
}

@implementation ELMVExportCoordinator
+ (instancetype)shared {
    static ELMVExportCoordinator *value; static dispatch_once_t once;
    dispatch_once(&once, ^{ value=[ELMVExportCoordinator new]; }); return value;
}
- (instancetype)init {
    if ((self=[super init])) {
        _worker=dispatch_queue_create("app.elichika.mv-export",DISPATCH_QUEUE_SERIAL);
        _lastStatus=@{@"phase":@"idle",@"busy":@NO,@"videoFrames":@0,@"audioSamples":@0};
        NSNotificationCenter *center=NSNotificationCenter.defaultCenter;
        [center addObserver:self selector:@selector(background:) name:UIApplicationDidEnterBackgroundNotification object:nil];
        [center addObserver:self selector:@selector(memoryWarning:) name:UIApplicationDidReceiveMemoryWarningNotification object:nil];
        [center addObserver:self selector:@selector(sceneClosed:) name:UISceneDidDisconnectNotification object:nil];
        [center addObserver:self selector:@selector(becameActive:) name:UIApplicationDidBecomeActiveNotification object:nil];
    }
    return self;
}
- (void)background:(NSNotification *)note { [self cancelWithReason:ELMVText(@"Export cancelled because the app entered the background.",@"앱이 백그라운드로 전환되어 내보내기가 취소되었습니다.",@"アプリがバックグラウンドに移ったため、書き出しをキャンセルしました。")]; }
- (void)memoryWarning:(NSNotification *)note { [self cancelWithReason:ELMVText(@"Export cancelled because iOS reported low memory. Try a lower resolution.",@"iOS의 메모리 부족 경고로 내보내기가 취소되었습니다. 해상도를 낮춰 보세요.",@"iOSのメモリ不足警告により、書き出しをキャンセルしました。解像度を下げてお試しください。")]; }
- (void)sceneClosed:(NSNotification *)note {
    if (!_gameWindow || note.object==_gameWindow.windowScene)
        [self cancelWithReason:ELMVText(@"Export cancelled because the app scene closed.",@"앱 화면이 닫혀 내보내기가 취소되었습니다.",@"アプリの画面が閉じられたため、書き出しをキャンセルしました。")];
}
- (void)becameActive:(NSNotification *)note { [self showPendingNotice]; }
- (BOOL)installInputBlocker {
    if (!ElichikaHostShowGame()) return NO;
    UIWindow *window=ElichikaHostPresenter().view.window;
    UIView *gameView=window.rootViewController.view;
    if (!window || !gameView || window.hidden) return NO;
    _gameWindow=window;
    _inputBlocker=[[UIView alloc] initWithFrame:gameView.bounds];
    _inputBlocker.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
    _inputBlocker.backgroundColor=UIColor.clearColor; _inputBlocker.userInteractionEnabled=YES;
    _inputBlocker.accessibilityIdentifier=@"Elichika.MVExport.InputBlocker";
    UILabel *hint=[UILabel new]; hint.translatesAutoresizingMaskIntoConstraints=NO;
    hint.text=ELMVText(@"Exporting MP4 · Hold the upper-right corner for 2 seconds for progress or cancel.",@"MP4 내보내는 중 · 오른쪽 위를 2초간 길게 누르면 진행 상황 확인 또는 취소가 가능합니다.",@"MP4を書き出し中 · 右上を2秒間長押しすると進行状況の確認やキャンセルができます。");
    hint.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
    hint.textColor=UIColor.whiteColor; hint.backgroundColor=[UIColor.blackColor colorWithAlphaComponent:.65];
    hint.textAlignment=NSTextAlignmentCenter; hint.numberOfLines=0;
    hint.layer.cornerRadius=6; hint.clipsToBounds=YES;
    [_inputBlocker addSubview:hint]; [gameView addSubview:_inputBlocker];
    [NSLayoutConstraint activateConstraints:@[
        [hint.centerXAnchor constraintEqualToAnchor:_inputBlocker.centerXAnchor],
        [hint.bottomAnchor constraintEqualToAnchor:_inputBlocker.safeAreaLayoutGuide.bottomAnchor constant:-12],
        [hint.widthAnchor constraintLessThanOrEqualToAnchor:_inputBlocker.widthAnchor constant:-32],
        [hint.widthAnchor constraintLessThanOrEqualToConstant:560]]];
    // Host's menu button belongs to the UIWindow; refresh it above the game
    // view. Its window long-press still sees touches on this descendant view.
    ElichikaHostShowGame(); return YES;
}
- (void)removeInputBlocker { [_inputBlocker removeFromSuperview]; _inputBlocker=nil; _gameWindow=nil; }
- (void)showPendingNotice {
    if (!_pendingNotice || _run) return;
    if (UIApplication.sharedApplication.applicationState!=UIApplicationStateActive) {
        [_noticeTimer invalidate]; _noticeTimer=nil; return;
    }
#if defined(SIFAS_STANDALONE)
    _pendingNotice=nil; [_noticeTimer invalidate]; _noticeTimer=nil;
    ElichikaPresentMVExportMenu(SIFASMVStandalonePresenter()); return;
#else
    UIViewController *presenter=ElichikaHostPresenter();
    UIViewController *visible=[presenter isKindOfClass:UINavigationController.class] ? ((UINavigationController *)presenter).visibleViewController : presenter;
    const BOOL dismissing=presenter.isBeingDismissed || visible.isBeingDismissed;
    if (!dismissing && [visible isKindOfClass:NSClassFromString(@"ELMVExportController")]) {
        _pendingNotice=nil; [_noticeTimer invalidate]; _noticeTimer=nil; return;
    }
    UIWindowScene *scene=presenter.view.window.windowScene;
    if (!presenter || !presenter.view.window || (scene && scene.activationState!=UISceneActivationStateForegroundActive) ||
        presenter.presentingViewController || presenter.presentedViewController || dismissing) {
        if (!_noticeTimer) {
            __weak ELMVExportCoordinator *weakSelf=self;
            _noticeTimer=[NSTimer scheduledTimerWithTimeInterval:1 repeats:YES block:^(__unused NSTimer *timer) { [weakSelf showPendingNotice]; }];
        }
        return;
    }
    NSDictionary *notice=_pendingNotice; _pendingNotice=nil; [_noticeTimer invalidate]; _noticeTimer=nil;
    NSString *message=[NSString stringWithFormat:@"%@\n\n%@",notice[@"message"] ?: @"",
        ELMVText(@"Hold the upper-right corner for 2 seconds to reopen MP4 export.",@"MP4 내보내기를 다시 열려면 오른쪽 위를 2초간 길게 누르세요.",@"MP4書き出しを再度開くには、右上を2秒間長押ししてください。")];
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:ELMVPhase(notice[@"phase"]) message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:ELMVText(@"OK",@"확인",@"OK") style:UIAlertActionStyleDefault handler:nil]];
    [presenter presentViewController:alert animated:YES completion:nil];
#endif
}
- (NSURL *)completedURL { return _completedURL; }
- (NSDictionary *)status {
    NSAssert(NSThread.isMainThread,@"MV status belongs to main");
    ELMVExportRun *run=_run;
    if (!run) {
        NSMutableDictionary *status=[_lastStatus mutableCopy];
        status[@"readiness"]=ELMVReadiness();
        if (_completedURL) status[@"completedPath"]=_completedURL.path;
        return status;
    }
    ELMVEncoderConfiguration *c=run->configuration;
    return @{@"phase":run->cleaning ? @"draining" : run->phase,
             @"message":run->message ?: @"",@"busy":@YES,@"generation":@(run->generation),
             @"videoFrames":@(run->videoCount.load()),@"audioSamples":@(run->audioCount.load()),
             @"frameCount":@(c.frameCount),@"sampleCount":@(c.audioSampleCount),
             @"codec":c.codec ?: @"",@"width":@(c.width),@"height":@(c.height),@"fps":@(c.fpsNumerator)};
}
- (void)watch:(NSTimer *)timer {
#if defined(SIFAS_STANDALONE)
    (void)timer; // Offline rendering waits for GPU/encoder readiness without a speed limit.
    return;
#else
    ELMVExportRun *run=_run;
    if (!run || run->cleaning) return;
    const double idle=CFAbsoluteTimeGetCurrent()-run->lastProgress.load();
    const double limit=run->preparePending ? 180.0 : ([run->phase isEqual:@"finalizing"] ? 120.0 : 45.0);
    if (idle>limit) [self fail:[NSString stringWithFormat:ELMVText(@"No export progress for %.0f seconds. The last native stage was %@.",@"%.0f초 동안 내보내기가 진행되지 않았습니다. 마지막 네이티브 단계: %@.",@"%.0f秒間、書き出しが進行していません。最後のネイティブ処理段階: %@。"),limit,SIFASMVBindingsStatus()[@"phase"] ?: @"unknown"] run:run];
#endif
}
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec {
    const NSUInteger base=MIN(width,height)>=2160 ? 48000000 : (MIN(width,height)>=1080 ? 16000000 : 8000000);
    [self startWidth:width height:height fps:fps codec:codec bitrate:base*(fps/30)];
}
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate {
    NSAssert(NSThread.isMainThread,@"MV start belongs to main");
    if (_run) return;
    NSString *readiness=ELMVReadiness();
    if (readiness.length) { _lastStatus=@{@"phase":@"failed",@"busy":@NO,@"message":readiness}; return; }
    int64_t milliseconds=0;
    NSDictionary *initialSnapshot=SIFASMVBindingsSongSnapshot();
    NSDictionary *song=ELMVValidatedSong(initialSnapshot,&milliseconds);
    int64_t sceneIdentity=0;
    if (!song || !ELMVInteger(initialSnapshot[@"scene_identity"],INT32_MIN,INT32_MAX,&sceneIdentity) || !sceneIdentity) {
        _lastStatus=@{@"phase":@"failed",@"busy":@NO,@"message":ELMVText(@"The MV song snapshot is incomplete or invalid (scene, cue sheet, cue, gain or timing). Wait for loading to finish.",@"MV 음원 정보(장면, 큐 시트, 큐, 음량 또는 시간)가 누락되었거나 올바르지 않습니다. 로딩이 끝날 때까지 기다려 주세요.",@"MVの楽曲情報（シーン、キューシート、キュー、音量、再生時間）が不足しているか無効です。読み込みの完了をお待ちください。")}; return;
    }
#if defined(SIFAS_STANDALONE)
    if (![@[@30,@60,@120] containsObject:@(fps)] || width<16 || height<16 || width%2 || height%2 ||
        width>INT32_MAX || height>INT32_MAX || width>NSUInteger(INT32_MAX)/4/height ||
        !bitrate || bitrate>NSUInteger(INT64_MAX) || ![@[@"hevc",@"h264"] containsObject:codec]) {
        _lastStatus=@{@"phase":@"failed",@"busy":@NO,@"message":@"Use positive even pixel dimensions (minimum16), a representable RGBA frame, 30/60/120 FPS and a positive bitrate."}; return;
    }
    const uint32_t simulationHz=uint32_t(MAX(60,fps));
#else
    if (![@[@30,@60] containsObject:@(fps)] || ![@[@720,@1080,@2160] containsObject:@(MIN(width,height))] ||
        width>4096 || height>4096 || ![@[@"hevc",@"h264"] containsObject:codec]) return;
    const uint32_t simulationHz=60;
#endif
    ELMVExportRun *run=[ELMVExportRun new]; run->generation=++_generation;
    ELMVEncoderConfiguration *c=[ELMVEncoderConfiguration new];
    c.width=width; c.height=height; c.fpsNumerator=fps; c.fpsDenominator=1;
    c.frameCount=(milliseconds*fps+999)/1000; c.codec=codec;
    c.videoBitRate=bitrate; c.audioBitRate=192000;
    run->configuration=c; run->clock=std::make_unique<elichika::MVExportClock>(c.frameCount,fps,simulationHz,run->generation);
    _run=run;
    _pendingNotice=nil; [_noticeTimer invalidate]; _noticeTimer=nil;
    _watchdog=[NSTimer scheduledTimerWithTimeInterval:.25 target:self selector:@selector(watch:) userInfo:nil repeats:YES];
    if (![self installInputBlocker]) {
        [self fail:ELMVText(@"The game window is unavailable. Reopen the MV and try again.",@"게임 화면을 사용할 수 없습니다. MV를 다시 열고 시도하세요.",@"ゲーム画面を使用できません。MVを開き直してお試しください。") run:run]; return;
    }
    NSString *trustedRoot=ElichikaHostConfiguration()[@"data_root"];
    // Filesystem validation and disk preflight run before freezing Unity.
    dispatch_async(_worker, ^{
        @autoreleasepool {
            NSString *failure=nil;
            NSFileManager *fm=NSFileManager.defaultManager;
            if (![trustedRoot isKindOfClass:NSString.class] || !trustedRoot.isAbsolutePath) failure=ELMVText(@"The app data root is unavailable.",@"앱 데이터 폴더를 사용할 수 없습니다.",@"アプリのデータフォルダーを使用できません。");
            NSURL *root=failure ? nil : [[NSURL fileURLWithPath:trustedRoot isDirectory:YES] URLByResolvingSymlinksInPath];
            BOOL isDirectory=NO;
            if (!failure && (![fm fileExistsAtPath:root.path isDirectory:&isDirectory] || !isDirectory)) failure=ELMVText(@"The app data root is not a directory.",@"앱 데이터 경로가 폴더가 아닙니다.",@"アプリのデータパスがフォルダーではありません。");
            NSURL *exports=[root URLByAppendingPathComponent:@"exports" isDirectory:YES];
            if (!failure && [fm fileExistsAtPath:exports.path]) {
                NSNumber *symlink=nil; [exports getResourceValue:&symlink forKey:NSURLIsSymbolicLinkKey error:NULL];
                if (symlink.boolValue || ![exports.URLByResolvingSymlinksInPath.path hasPrefix:[root.path stringByAppendingString:@"/"]]) failure=ELMVText(@"The app export directory is not safely contained in the data root.",@"내보내기 폴더가 앱 데이터 폴더 안의 안전한 위치에 있지 않습니다.",@"書き出しフォルダーがアプリのデータフォルダー内の安全な場所にありません。");
                if (![fm fileExistsAtPath:exports.path isDirectory:&isDirectory] || !isDirectory) failure=ELMVText(@"The app export destination is not a directory.",@"내보내기 대상이 폴더가 아닙니다.",@"書き出し先がフォルダーではありません。");
            } else if (!failure) {
                NSError *error=nil;
                if (![fm createDirectoryAtURL:exports withIntermediateDirectories:NO attributes:nil error:&error]) failure=error.localizedDescription;
            }
            if (!failure) {
                NSDictionary *attributes=[fm attributesOfFileSystemForPath:root.path error:NULL];
                const uint64_t durationSeconds=(milliseconds+999)/1000;
#if defined(SIFAS_STANDALONE)
                const __uint128_t estimate=__uint128_t(durationSeconds)*(c.videoBitRate/8+192000/8+48000*4)*5/4+128*1024*1024;
                const uint64_t needed=estimate>UINT64_MAX ? UINT64_MAX : uint64_t(estimate);
#else
                const uint64_t needed=durationSeconds*(c.videoBitRate/8+192000/8+48000*4)*5/4+128*1024*1024;
#endif
                if (!attributes[NSFileSystemFreeSize] || [attributes[NSFileSystemFreeSize] unsignedLongLongValue]<needed)
                    failure=[NSString stringWithFormat:ELMVText(@"Not enough free app storage. This export needs approximately %.1f GB including its temporary audio.",@"앱 저장 공간이 부족합니다. 임시 오디오를 포함하여 약 %.1f GB가 필요합니다.",@"アプリの空き容量が不足しています。一時音声を含め約%.1f GBが必要です。"),double(needed)/1000000000.0];
            }
            if (!failure) {
                NSURL *directory=[exports URLByAppendingPathComponent:[@"MV-" stringByAppendingString:NSUUID.UUID.UUIDString] isDirectory:YES];
                NSError *error=nil;
                if (![fm createDirectoryAtURL:directory withIntermediateDirectories:NO attributes:nil error:&error]) failure=error.localizedDescription;
                else { run->directory=directory; run->output=[directory URLByAppendingPathComponent:@"MV.mp4"]; }
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                if (_run!=run || run->stopped.load()) return;
                if (failure) { [self fail:failure run:run]; return; }
                NSDictionary *fresh=SIFASMVBindingsSongSnapshot(); int64_t freshIdentity=0;
                if (!ELMVInteger(fresh[@"scene_identity"],INT32_MIN,INT32_MAX,&freshIdentity) || !freshIdentity || freshIdentity!=sceneIdentity ||
                    ![fresh[@"sheet"] isEqual:song[@"sheet"]] || ![fresh[@"cue"] isEqual:song[@"cue"]]) {
                    [self fail:ELMVText(@"The loaded MV changed during export preparation. Open the intended MV and start again.",@"내보내기를 준비하는 동안 MV가 변경되었습니다. 원하는 MV를 열고 다시 시작하세요.",@"書き出しの準備中にMVが変更されました。目的のMVを開いて再度開始してください。") run:run]; return;
                }
                run->phase=@"snapshot-and-freeze"; run->bindingsActive=YES;
                SIFASMVBindingConfiguration binding={(uint32_t)width,(uint32_t)height,simulationHz,(uint32_t)fps};
                SIFASMVBindingCallbacks callbacks={(__bridge void *)run,ELMVNext,ELMVFrame,ELMVFailed}; NSError *error=nil;
                if (!SIFASMVBindingsBegin(binding,callbacks,&error)) {
                    [self fail:error.localizedDescription ?: ELMVText(@"The native MV scene rejected offline rendering.",@"MV 장면에서 오프라인 렌더링을 시작할 수 없습니다.",@"MVシーンでオフラインレンダリングを開始できません。") run:run]; return;
                }
                if (run->cleaning) return;
                run->phase=@"preparing-song"; run->preparePending=YES; run->lastProgress=CFAbsoluteTimeGetCurrent();
                NSDictionary *request=@{@"schema":@1,@"song":song,@"video":@{@"frame_count":@(c.frameCount),@"fps_numerator":@(fps),@"fps_denominator":@1}};
                ElichikaPythonCallWithArguments(@"mv_export_audio_prepare",request,^(NSDictionary *reply) {
                    run->preparePending=NO;
                    if (_run!=run) return;
                    if (run->cleaning) { [self finishCleanup:run]; return; }
                    NSDictionary *manifest=[reply[@"manifest"] isKindOfClass:NSDictionary.class] ? reply[@"manifest"] : nil;
                    NSString *identifier=[reply[@"session_id"] isKindOfClass:NSString.class] ? reply[@"session_id"] : nil;
                    int64_t rate=0, channels=0, count=0;
                    if (![reply[@"ok"] boolValue] || !identifier.length || ![[NSUUID alloc] initWithUUIDString:identifier] ||
                        !ELMVInteger(manifest[@"sampleRate"],44100,48000,&rate) || (rate!=44100 && rate!=48000) ||
                        !ELMVInteger(manifest[@"channels"],1,2,&channels) || !ELMVInteger(manifest[@"sampleCount"],1,100000000,&count)) {
                        // Closing without an ID also disposes a malformed owned prepare result.
                        [self fail:[reply[@"ok"] boolValue] ? ELMVText(@"The native song preparation returned an invalid PCM manifest.",@"음원 준비 결과의 PCM 정보가 올바르지 않습니다.",@"楽曲の準備で無効なPCM情報が返されました。") : ELMVReplyError(reply) run:run]; return;
                    }
                    run->audioSession=identifier; c.audioSampleRate=(int32_t)rate; c.audioChannels=(NSUInteger)channels; c.audioSampleCount=count;
                    run->phase=@"starting-encoder"; run->lastProgress=CFAbsoluteTimeGetCurrent();
                    dispatch_async(_worker, ^{
                        if (run->stopped.load()) return;
                        NSError *writerError=nil;
                        run->encoder=[ELMVEncoder encoderWithConfiguration:c outputURL:run->output error:&writerError];
                        const BOOL created=run->encoder!=nil;
                        dispatch_async(dispatch_get_main_queue(), ^{
                            if (_run!=run || run->stopped.load()) return;
                            if (!created) { [self fail:writerError.localizedDescription ?: ELMVText(@"The requested MP4 encoder is unavailable.",@"요청한 MP4 인코더를 사용할 수 없습니다.",@"指定したMP4エンコーダーを使用できません。") run:run]; return; }
                            run->ready=YES; run->phase=@"rendering"; run->lastProgress=CFAbsoluteTimeGetCurrent();
                            dispatch_async(_worker, ^{ [self pump:run]; });
                        });
                    });
                });
            });
        }
    });
}
- (BOOL)grant:(ELMVExportRun *)run tick:(uint64_t *)tick capture:(int64_t *)capture {
    if (_run!=run || !run->ready || run->stopped.load() || run->cleaning) return NO;
    uint64_t next=0; int64_t index=-1;
    if (!run->clock->grant(run->generation,next,index)) return NO;
    *tick=next; *capture=index; run->lastProgress=CFAbsoluteTimeGetCurrent(); return YES;
}
- (void)frame:(ELMVPixelFrame *)pixels rowBytes:(NSUInteger)rowBytes index:(int64_t)index run:(ELMVExportRun *)run {
    NSAssert(NSThread.isMainThread,@"MV frames belong to main");
    if (_run!=run || run->stopped.load() || run->cleaning) return;
    if (!run->clock->received(run->generation,index) || rowBytes<run->configuration.width*4 ||
        !pixels || !pixels.pixelBuffer || rowBytes!=pixels.rowBytes ||
        CVPixelBufferGetWidth(pixels.pixelBuffer)!=run->configuration.width ||
        CVPixelBufferGetHeight(pixels.pixelBuffer)!=run->configuration.height ||
        run->configuration.height>NSUIntegerMax/rowBytes || CVPixelBufferGetDataSize(pixels.pixelBuffer)<rowBytes*run->configuration.height) {
        [self fail:ELMVText(@"The final Unity overlay delivered an invalid or repeated BGRA frame.",@"Unity 최종 합성 화면의 BGRA 프레임이 올바르지 않거나 중복되었습니다.",@"Unityの最終合成映像で無効または重複したBGRAフレームを受信しました。") run:run]; return;
    }
    // Try one append on the encoder's serial owner, without waiting for writer
    // readiness. dispatch_sync can execute on its caller, so an async handoff
    // guarantees a non-main append. Wait only for that attempt, then acknowledge
    // a ready writer before this Unity boundary grants its next tick. Worker
    // never synchronously calls main; audio/finalization stay in the async pump.
    __block ELMVAppendResult result=ELMVAppendRetry;
    __block NSString *failure=nil;
    elichika::MVWorkerHandoff(_worker, ^{
        @autoreleasepool {
            if (!run->stopped.load()) {
                if (run->pendingFrame) {
                    failure=ELMVText(@"The renderer exceeded its one-frame export queue.",@"렌더러가 내보내기 대기열의 한 프레임 제한을 초과했습니다.",@"レンダラーが書き出し待ちの1フレーム制限を超えました。");
                    result=ELMVAppendFailed;
                } else {
                    ELMVEncoder *writer=run->encoder;
                    if (!writer || run->finishing) {
                        failure=ELMVText(@"Video input failed.",@"영상 입력에 실패했습니다.",@"映像入力に失敗しました。");
                        result=ELMVAppendFailed;
                    } else {
                        result=[writer appendPixelBuffer:pixels.pixelBuffer frameIndex:index];
                        if (result==ELMVAppendAccepted) {
                            run->videoCount=writer.acceptedVideoFrames; run->lastProgress=CFAbsoluteTimeGetCurrent();
                        } else if (result==ELMVAppendRetry) {
                            run->pendingFrame=pixels; run->pendingRowBytes=rowBytes; run->pendingFrameIndex=index;
                        } else {
                            failure=writer.failure.localizedDescription ?: ELMVText(@"Video input failed.",@"영상 입력에 실패했습니다.",@"映像入力に失敗しました。");
                        }
                        if (result!=ELMVAppendFailed) [self schedulePump:run];
                    }
                }
            }
        }
    });
    if (_run!=run || run->stopped.load()) return;
    if (result==ELMVAppendFailed) { [self fail:failure run:run]; return; }
    if (result==ELMVAppendAccepted) [self acceptedFrameIndex:index run:run];
}
- (void)acceptedFrameIndex:(int64_t)index run:(ELMVExportRun *)run {
    if (_run!=run || run->stopped.load()) return;
    if (!run->clock->accepted(run->generation,index)) { [self fail:ELMVText(@"The video encoder acknowledged a discontinuous frame index.",@"영상 인코더의 프레임 순서가 연속되지 않습니다.",@"映像エンコーダーのフレーム番号が連続していません。") run:run]; return; }
    if (run->clock->complete()) run->phase=@"finishing-audio";
}
- (void)schedulePump:(ELMVExportRun *)run {
    if (run->stopped.load() || run->finishing || run->pumpScheduled) return;
    run->pumpScheduled=YES;
    const int64_t retryMilliseconds=(run->pendingFrame || run->pendingPCM) ? 1 : 10;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,retryMilliseconds*NSEC_PER_MSEC),_worker, ^{
        run->pumpScheduled=NO; [self pump:run];
    });
}
- (void)pump:(ELMVExportRun *)run {
    @autoreleasepool {
        if (run->stopped.load() || run->finishing || !run->encoder) return;
        ELMVEncoder *writer=run->encoder;
        // AVFoundation's input readiness controls audio demand independently
        // of video progress. Artificial time gating can starve its muxer.
        // Retain one <=8192-frame PCM chunk on Retry; do not read ahead.
        const int64_t limit=run->configuration.audioSampleCount;
        if (run->pendingPCM) {
            ELMVAppendResult result=[writer appendPCM16:run->pendingPCM firstSample:run->pendingFirstSample];
            if (result==ELMVAppendFailed) { dispatch_async(dispatch_get_main_queue(), ^{ [self fail:writer.failure.localizedDescription ?: ELMVText(@"AAC input failed.",@"AAC 입력에 실패했습니다.",@"AAC入力に失敗しました。") run:run]; }); return; }
            if (result==ELMVAppendAccepted) {
                run->pendingPCM=nil; run->audioCount=writer.acceptedAudioSamples; run->lastProgress=CFAbsoluteTimeGetCurrent();
            }
        }
        if (!run->pendingPCM && !run->audioRequestPending && writer.acceptedAudioSamples<limit) {
            const int64_t first=writer.acceptedAudioSamples;
            const int64_t maximum=MIN(int64_t(8192),limit-first);
            run->audioRequestPending=YES;
            dispatch_async(dispatch_get_main_queue(), ^{
                if (_run!=run || run->stopped.load()) { dispatch_async(_worker, ^{ run->audioRequestPending=NO; }); return; }
                ElichikaPythonCallWithArguments(@"mv_export_audio_read",@{@"schema":@1,@"session_id":run->audioSession,@"first_sample":@(first),@"max_frames":@(maximum)},^(NSDictionary *reply) {
                    dispatch_async(_worker, ^{
                        run->audioRequestPending=NO;
                        if (run->stopped.load()) return;
                        int64_t responseFirst=0, responseCount=0;
#if defined(SIFAS_STANDALONE)
                        NSData *pcm=[reply[@"pcm_data"] isKindOfClass:NSData.class] ? reply[@"pcm_data"] : nil;
#else
                        NSString *base64=[reply[@"pcm_base64"] isKindOfClass:NSString.class] ? reply[@"pcm_base64"] : nil;
                        NSData *pcm=base64 ? [[NSData alloc] initWithBase64EncodedString:base64 options:0] : nil;
#endif
                        if (![reply[@"ok"] boolValue] || ![reply[@"session_id"] isEqual:run->audioSession] ||
                            !ELMVInteger(reply[@"first_sample"],0,run->configuration.audioSampleCount,&responseFirst) || responseFirst!=first ||
                            !ELMVInteger(reply[@"frame_count"],1,maximum,&responseCount) ||
                            pcm.length!=NSUInteger(responseCount)*run->configuration.audioChannels*2) {
                            dispatch_async(dispatch_get_main_queue(), ^{ [self fail:[reply[@"ok"] boolValue] ? ELMVText(@"The prepared song returned an invalid PCM chunk.",@"준비된 음원의 PCM 데이터가 올바르지 않습니다.",@"準備した楽曲から無効なPCMデータが返されました。") : ELMVReplyError(reply) run:run]; }); return;
                        }
                        run->pendingPCM=pcm; run->pendingFirstSample=first; [self pump:run];
                    });
                });
            });
        }
        if (run->pendingFrame) {
            const int64_t index=run->pendingFrameIndex;
            ELMVAppendResult result=[writer appendPixelBuffer:run->pendingFrame.pixelBuffer frameIndex:index];
            if (result==ELMVAppendFailed) { dispatch_async(dispatch_get_main_queue(), ^{ [self fail:writer.failure.localizedDescription ?: ELMVText(@"Video input failed.",@"영상 입력에 실패했습니다.",@"映像入力に失敗しました。") run:run]; }); return; }
            if (result==ELMVAppendAccepted) {
                run->pendingFrame=nil; run->pendingFrameIndex=-1; run->videoCount=writer.acceptedVideoFrames; run->lastProgress=CFAbsoluteTimeGetCurrent();
                dispatch_async(dispatch_get_main_queue(), ^{
                    [self acceptedFrameIndex:index run:run];
                });
            }
        }
        if (writer.acceptedVideoFrames==run->configuration.frameCount && writer.acceptedAudioSamples==run->configuration.audioSampleCount && !run->pendingFrame && !run->pendingPCM && !run->audioRequestPending) {
            run->finishing=YES;
            dispatch_async(dispatch_get_main_queue(), ^{ if (_run==run && !run->cleaning) run->phase=@"finalizing"; });
            [writer finishOnQueue:_worker completion:^(NSURL *output, NSError *error) {
                if (run->stopped.load()) return;
                if (!output) { dispatch_async(dispatch_get_main_queue(), ^{ [self fail:error.localizedDescription ?: ELMVText(@"MP4 finalization failed.",@"MP4 마무리 작업에 실패했습니다.",@"MP4の最終処理に失敗しました。") run:run]; }); return; }
                dispatch_async(dispatch_get_main_queue(), ^{
                    if (_run!=run || run->stopped.load()) return;
                    run->completed=YES; _completedURL=output;
                    [self cleanup:run terminal:@"completed" message:ELMVText(@"MP4 export completed. Save or share the file below.",@"MP4 내보내기가 완료되었습니다. 아래에서 파일을 저장하거나 공유하세요.",@"MP4の書き出しが完了しました。下からファイルを保存または共有できます。")];
                });
            }]; return;
        }
        [self schedulePump:run];
    }
}
- (void)fail:(NSString *)message run:(ELMVExportRun *)run {
    if (_run!=run || run->cleaning) return;
    ELMVEncoderConfiguration *c=run->configuration;
    NSString *detail=[NSString stringWithFormat:@"%@ · %@ %lu×%lu %d fps: %@",ELMVPhase(run->phase),[c.codec uppercaseString],(unsigned long)c.width,(unsigned long)c.height,c.fpsNumerator,message ?: ELMVText(@"Unknown export failure.",@"알 수 없는 내보내기 오류입니다.",@"不明な書き出しエラーです。")];
    [self cleanup:run terminal:@"failed" message:detail];
}
- (void)cancelWithReason:(NSString *)reason {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ [self cancelWithReason:reason]; }); return; }
    if (_run && !_run->cleaning) [self cleanup:_run terminal:@"cancelled" message:reason];
}
- (void)cleanup:(ELMVExportRun *)run terminal:(NSString *)terminal message:(NSString *)message {
    if (_run!=run || run->cleaning) return;
    run->cleaning=YES; run->stopped=true; run->ready=NO;
    run->clock->cancel(run->generation); run->terminalPhase=terminal; run->message=message;
    if (run->bindingsActive) { run->bindingsActive=NO; SIFASMVBindingsEnd(); }
    NSString *restorePhase=SIFASMVBindingsStatus()[@"phase"];
    if ([restorePhase isEqual:@"restore-incomplete"]) run->message=[run->message stringByAppendingFormat:ELMVText(@" State restoration: %@",@" 상태 복원: %@",@" 状態の復元: %@"),SIFASMVBindingsStatus()[@"lastFailure"] ?: @"incomplete"];
    // Even a cancelled prepare must acknowledge close before another run may
    // start. This prevents stale reads/closes from reaching the next song.
    if (!run->closeStarted) {
        run->closeStarted=YES;
        NSMutableDictionary *request=[@{@"schema":@1} mutableCopy];
        if (run->audioSession) request[@"session_id"]=run->audioSession;
        ElichikaPythonCallWithArguments(@"mv_export_audio_close",request,^(NSDictionary *reply) {
            run->audioClosed=YES;
            if (![reply[@"ok"] boolValue]) run->message=[run->message stringByAppendingFormat:ELMVText(@" Audio cleanup: %@",@" 오디오 정리: %@",@" 音声の後処理: %@"),ELMVReplyError(reply)];
            [self finishCleanup:run];
        });
    }
    dispatch_async(_worker, ^{
        if (!run->completed) [run->encoder cancel];
        run->encoder=nil; run->pendingFrame=nil; run->pendingPCM=nil;
        // A cancellation can race the writer's atomic successful publish.
        // cancel() synchronizes with that publish; retain every completed MP4.
        const BOOL published=run->output && [NSFileManager.defaultManager fileExistsAtPath:run->output.path];
        if (!published && run->directory) [NSFileManager.defaultManager removeItemAtURL:run->directory error:NULL];
        dispatch_async(dispatch_get_main_queue(), ^{
            if (published) {
                run->completed=YES; _completedURL=run->output;
                run->terminalPhase=@"completed";
                run->message=ELMVText(@"MP4 export completed. Save or share the file below.",@"MP4 내보내기가 완료되었습니다. 아래에서 파일을 저장하거나 공유하세요.",@"MP4の書き出しが完了しました。下からファイルを保存または共有できます。");
            }
            run->workerClean=YES; [self finishCleanup:run];
        });
    });
}
- (void)finishCleanup:(ELMVExportRun *)run {
    if (_run!=run || !run->cleaning || !run->workerClean || !run->audioClosed || run->preparePending) return;
    ELMVEncoderConfiguration *c=run->configuration;
    _lastStatus=@{@"phase":run->terminalPhase,@"message":run->message ?: @"",@"busy":@NO,
                  @"videoFrames":@(run->videoCount.load()),@"audioSamples":@(run->audioCount.load()),
                  @"frameCount":@(c.frameCount),@"sampleCount":@(c.audioSampleCount),@"codec":c.codec ?: @"",
                  @"width":@(c.width),@"height":@(c.height),@"fps":@(c.fpsNumerator)};
    _run=nil; [_watchdog invalidate]; _watchdog=nil; [self removeInputBlocker];
    if ([run->terminalPhase isEqual:@"completed"] || [run->terminalPhase isEqual:@"failed"]) {
        _pendingNotice=_lastStatus; [self showPendingNotice];
    }
}
@end

#if !defined(SIFAS_STANDALONE)
@interface ELMVExportController : UITableViewController
@property(nonatomic,strong) UISegmentedControl *resolution;
@property(nonatomic,strong) UISegmentedControl *rate;
@property(nonatomic,strong) UISegmentedControl *codec;
@property(nonatomic,strong) NSTimer *refreshTimer;
@property(nonatomic,copy) NSDictionary *displayedStatus;
@property(nonatomic) BOOL landscape;
- (void)refresh;
@end
@implementation ELMVExportController
- (void)viewDidLoad {
    [super viewDidLoad]; self.title=@"MV → MP4";
    self.navigationItem.rightBarButtonItem=[[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemDone target:self action:@selector(done)];
    self.resolution=[[UISegmentedControl alloc] initWithItems:@[@"720p",@"1080p",@"4K"]]; self.resolution.selectedSegmentIndex=0;
    self.rate=[[UISegmentedControl alloc] initWithItems:@[@"30",@"60"]]; self.rate.selectedSegmentIndex=0;
    self.codec=[[UISegmentedControl alloc] initWithItems:@[@"HEVC",@"H.264"]]; self.codec.selectedSegmentIndex=0;
    self.tableView.rowHeight=UITableViewAutomaticDimension; self.tableView.estimatedRowHeight=64;
    self.displayedStatus=SIFASMVExportStatus();
}
- (void)viewWillAppear:(BOOL)animated {
    [super viewWillAppear:animated]; [self refresh];
    __weak ELMVExportController *weakSelf=self;
    self.refreshTimer=[NSTimer scheduledTimerWithTimeInterval:.25 repeats:YES block:^(__unused NSTimer *timer) { [weakSelf refresh]; }];
}
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; [self.refreshTimer invalidate]; self.refreshTimer=nil; }
- (void)done { [self dismissViewControllerAnimated:YES completion:nil]; }
- (void)refresh {
    NSDictionary *status=SIFASMVExportStatus(), *previous=self.displayedStatus;
    if ([status isEqualToDictionary:previous]) return;
    self.displayedStatus=status;
    const BOOL busy=[status[@"busy"] boolValue], wasBusy=[previous[@"busy"] boolValue];
    const BOOL busyChanged=busy!=wasBusy;
    if (busyChanged) { self.resolution.enabled=!busy; self.rate.enabled=!busy; self.codec.enabled=!busy; }
    NSMutableIndexSet *sections=[NSMutableIndexSet new];
    if (busyChanged || ![(status[@"readiness"] ?: @"") isEqual:(previous[@"readiness"] ?: @"")] ||
        [status[@"phase"] isEqual:@"draining"]!=[previous[@"phase"] isEqual:@"draining"]) [sections addIndex:1];
    if (![(status[@"completedPath"] ?: @"") isEqual:(previous[@"completedPath"] ?: @"")]) [sections addIndex:3];
    // The settings keep their controls/cells. Only changed action/footer
    // state and the single progress row need an update at this 4 Hz poll.
    [UIView performWithoutAnimation:^{
        [self.tableView beginUpdates];
        if (sections.count) [self.tableView reloadSections:sections withRowAnimation:UITableViewRowAnimationNone];
        [self.tableView reloadRowsAtIndexPaths:@[[NSIndexPath indexPathForRow:0 inSection:2]] withRowAnimation:UITableViewRowAnimationNone];
        [self.tableView endUpdates];
    }];
}
- (NSInteger)numberOfSectionsInTableView:(UITableView *)tableView { return 4; }
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return section==0 ? 3 : (section==1 ? 2 : (section==2 ? 1 : 2)); }
- (NSString *)tableView:(UITableView *)tableView titleForHeaderInSection:(NSInteger)section {
    return @[ELMVText(@"Video",@"영상",@"映像"),ELMVText(@"Export",@"내보내기",@"書き出し"),
             ELMVText(@"Progress",@"진행 상황",@"進行状況"),ELMVText(@"Completed MP4",@"완성된 MP4",@"完成したMP4")][section];
}
- (NSString *)tableView:(UITableView *)tableView titleForFooterInSection:(NSInteger)section {
    NSDictionary *status=self.displayedStatus;
    if (section==0) return ELMVText(@"Offline fixed-frame rendering uses the game's original camera field of view and complete final MV image, including stage, lights and props. The game pauses during export. MP4 contains H.264 or HEVC video and AAC song audio.",@"오프라인 고정 프레임 렌더링은 게임의 원래 카메라 화각을 사용하며 무대, 조명, 소품을 포함한 최종 MV 화면 전체를 내보냅니다. 내보내는 동안 게임이 일시 정지됩니다. MP4에는 H.264 또는 HEVC 영상과 AAC 음원이 포함됩니다.",@"固定フレームのオフラインレンダリングは、ゲーム本来のカメラ画角を使い、ステージ・照明・小道具を含む最終MV映像全体を書き出します。書き出し中はゲームが一時停止します。MP4にはH.264またはHEVC映像とAAC音声が含まれます。");
    if (section==1) return [status[@"busy"] boolValue] ? ELMVText(@"You can close and reopen this form while export continues. Keep the app in the foreground. Cancel restores the MV state and removes the unfinished file.",@"이 창을 닫아도 내보내기가 계속되며 다시 열 수 있습니다. 앱을 전면에 유지하세요. 취소하면 MV 상태를 복원하고 미완성 파일을 삭제합니다.",@"この画面を閉じても書き出しは続き、再度開けます。アプリを前面に保ってください。キャンセルするとMVの状態を復元し、未完成のファイルを削除します。") : (status[@"readiness"] ?: @"");
    if (section==3) return ELMVText(@"Completed files stay in this app's exports folder. Save to Files copies a completed MP4 to your chosen destination.",@"완성된 파일은 앱의 exports 폴더에 보관됩니다. ‘파일에 저장’으로 원하는 위치에 MP4를 복사할 수 있습니다.",@"完成したファイルはアプリのexportsフォルダーに保存されます。「ファイルに保存」で指定した場所にMP4をコピーできます。");
    return nil;
}
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)path {
    NSString *identifier=path.section==0 ? [NSString stringWithFormat:@"MVSetting-%ld",(long)path.row] : (path.section==2 ? @"MVProgress" : @"MVAction");
    UITableViewCell *cell=[tableView dequeueReusableCellWithIdentifier:identifier];
    if (!cell) cell=[[UITableViewCell alloc] initWithStyle:UITableViewCellStyleSubtitle reuseIdentifier:identifier];
    NSDictionary *status=self.displayedStatus; BOOL busy=[status[@"busy"] boolValue];
    cell.textLabel.numberOfLines=0; cell.detailTextLabel.numberOfLines=0;
    cell.selectionStyle=UITableViewCellSelectionStyleNone; cell.userInteractionEnabled=YES;
    cell.accessoryView=nil; cell.detailTextLabel.text=nil; cell.textLabel.textColor=UIColor.labelColor;
    if (path.section==0) {
        cell.textLabel.text=@[ELMVText(@"Resolution",@"해상도",@"解像度"),ELMVText(@"Frames / second",@"초당 프레임",@"フレーム/秒"),ELMVText(@"Video codec",@"영상 코덱",@"映像コーデック")][path.row];
        UISegmentedControl *control=@[self.resolution,self.rate,self.codec][path.row];
        control.enabled=!busy; cell.accessoryView=control;
    } else if (path.section==1) {
        BOOL enabled=path.row==0 ? (!busy && ![status[@"readiness"] length]) : (busy && ![status[@"phase"] isEqual:@"draining"]);
        cell.textLabel.text=path.row==0 ? ELMVText(@"Start export",@"내보내기 시작",@"書き出しを開始") : ELMVText(@"Cancel export",@"내보내기 취소",@"書き出しをキャンセル");
        cell.textLabel.textColor=enabled ? (path.row==0 ? self.view.tintColor : UIColor.systemRedColor) : UIColor.secondaryLabelColor;
        cell.userInteractionEnabled=enabled; cell.selectionStyle=enabled ? UITableViewCellSelectionStyleDefault : UITableViewCellSelectionStyleNone;
    } else if (path.section==2) {
        NSString *phase=ELMVPhase(status[@"phase"] ?: @"idle");
        int64_t video=[status[@"videoFrames"] longLongValue], total=[status[@"frameCount"] longLongValue];
        int64_t audio=[status[@"audioSamples"] longLongValue], samples=[status[@"sampleCount"] longLongValue];
        double progress=total>0 ? double(video)/total : 0;
        cell.textLabel.text=[NSString stringWithFormat:@"%@ — %.1f%%",phase,100*progress];
        NSString *format=ELMVText(@"Video: %lld / %lld frames\nAudio: %lld / %lld sample frames\n%@",@"영상: %lld / %lld 프레임\n오디오: %lld / %lld 샘플 프레임\n%@",@"映像: %lld / %lld フレーム\n音声: %lld / %lld サンプルフレーム\n%@");
        cell.detailTextLabel.text=[NSString stringWithFormat:format,(long long)video,(long long)total,(long long)audio,(long long)samples,status[@"message"] ?: @""];
    } else {
        BOOL enabled=[ELMVExportCoordinator shared].completedURL!=nil;
        cell.textLabel.text=path.row==0 ? ELMVText(@"Save to Files…",@"파일에 저장…",@"ファイルに保存…") : ELMVText(@"Share MP4…",@"MP4 공유…",@"MP4を共有…");
        cell.textLabel.textColor=enabled ? self.view.tintColor : UIColor.secondaryLabelColor;
        cell.userInteractionEnabled=enabled; cell.selectionStyle=enabled ? UITableViewCellSelectionStyleDefault : UITableViewCellSelectionStyleNone;
    }
    return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)path {
    [tableView deselectRowAtIndexPath:path animated:YES];
    if (path.section==1) {
        if (path.row==1) SIFASMVCancelExport();
        else {
            NSUInteger shortSide=[@[@720,@1080,@2160][self.resolution.selectedSegmentIndex] unsignedIntegerValue];
            NSUInteger longSide=shortSide*16/9;
            [[ELMVExportCoordinator shared] startWidth:self.landscape ? longSide : shortSide height:self.landscape ? shortSide : longSide fps:self.rate.selectedSegmentIndex==0 ? 30 : 60 codec:self.codec.selectedSegmentIndex==0 ? @"hevc" : @"h264"];
            if ([SIFASMVExportStatus()[@"busy"] boolValue]) {
                [self dismissViewControllerAnimated:YES completion:^{ ElichikaHostShowGame(); }];
            }
        }
        [self refresh];
    } else if (path.section==3) {
        NSURL *output=[ELMVExportCoordinator shared].completedURL;
        if (!output || ![NSFileManager.defaultManager fileExistsAtPath:output.path]) return;
        if (path.row==0) {
            UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc] initWithURLs:@[output] inMode:UIDocumentPickerModeExportToService];
            [self presentViewController:picker animated:YES completion:nil];
        } else {
            UIActivityViewController *activity=[[UIActivityViewController alloc] initWithActivityItems:@[output] applicationActivities:nil];
            activity.popoverPresentationController.sourceView=self.tableView;
            activity.popoverPresentationController.sourceRect=[self.tableView rectForRowAtIndexPath:path];
            [self presentViewController:activity animated:YES completion:nil];
        }
    }
}
@end

void ElichikaPresentMVExportMenu(UIViewController *presenter) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ ElichikaPresentMVExportMenu(presenter); }); return; }
    if (!ElichikaHostShowGame()) return;
    presenter=ElichikaHostPresenter();
    if (!presenter || presenter.isBeingDismissed) return;
    UIViewController *visible=[presenter isKindOfClass:UINavigationController.class] ? ((UINavigationController *)presenter).visibleViewController : presenter;
    if ([visible isKindOfClass:ELMVExportController.class] || presenter.presentedViewController || presenter.presentingViewController) return;
    ELMVExportController *controller=[[ELMVExportController alloc] initWithStyle:UITableViewStyleInsetGrouped];
    CGSize size=presenter.view.window.bounds.size;
    if (size.width<=0 || size.height<=0) size=UIScreen.mainScreen.bounds.size;
    controller.landscape=size.width>=size.height;
    UINavigationController *navigation=[[UINavigationController alloc] initWithRootViewController:controller];
    navigation.modalPresentationStyle=UIModalPresentationFormSheet;
    [presenter presentViewController:navigation animated:YES completion:nil];
}
#else
@interface SIFASMVStandalonePanel : UIView
@property(nonatomic,strong) UITextField *widthField,*heightField,*bitrateField;
@property(nonatomic,strong) UISegmentedControl *rate,*codec;
@property(nonatomic,strong) UILabel *status;
@property(nonatomic,strong) UIButton *exportButton,*cancelButton,*recommendButton,*saveButton,*shareButton;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,weak) UIViewController *presenter;
@property(nonatomic,copy) NSString *inputError;
- (void)refresh;
@end
static __weak SIFASMVStandalonePanel *SIFASMVCurrentPanel;
@implementation SIFASMVStandalonePanel
- (UILabel *)label:(NSString *)text stack:(UIStackView *)stack {
    UILabel *label=[UILabel new]; label.text=text; label.textColor=UIColor.whiteColor; label.numberOfLines=0;
    [stack addArrangedSubview:label]; return label;
}
- (UITextField *)field:(NSString *)text stack:(UIStackView *)stack {
    UITextField *field=[UITextField new]; field.borderStyle=UITextBorderStyleRoundedRect;
    field.keyboardType=UIKeyboardTypeDecimalPad; field.text=text; field.backgroundColor=UIColor.whiteColor; field.textColor=UIColor.blackColor;
    [stack addArrangedSubview:field]; return field;
}
- (UIButton *)button:(NSString *)text action:(SEL)action stack:(UIStackView *)stack {
    UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem]; [button setTitle:text forState:UIControlStateNormal];
    button.backgroundColor=UIColor.whiteColor; button.layer.cornerRadius=5;
    [button addTarget:self action:action forControlEvents:UIControlEventTouchUpInside]; [stack addArrangedSubview:button]; return button;
}
- (instancetype)initWithPresenter:(UIViewController *)presenter {
    UIWindow *window=presenter.view.window;
    if (!(self=[super initWithFrame:window.bounds])) return nil;
    self.presenter=presenter; self.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
    self.backgroundColor=[UIColor.blackColor colorWithAlphaComponent:.88]; self.userInteractionEnabled=YES;
    UIScrollView *scroll=[UIScrollView new]; scroll.translatesAutoresizingMaskIntoConstraints=NO;
    scroll.keyboardDismissMode=UIScrollViewKeyboardDismissModeOnDrag; [self addSubview:scroll];
    UIStackView *stack=[UIStackView new]; stack.axis=UILayoutConstraintAxisVertical; stack.spacing=10; stack.translatesAutoresizingMaskIntoConstraints=NO; [scroll addSubview:stack];
    NSLayoutConstraint *preferredWidth=[scroll.widthAnchor constraintEqualToAnchor:self.widthAnchor constant:-32]; preferredWidth.priority=UILayoutPriorityDefaultHigh;
    [NSLayoutConstraint activateConstraints:@[
        [scroll.topAnchor constraintEqualToAnchor:self.safeAreaLayoutGuide.topAnchor constant:16],
        [scroll.bottomAnchor constraintEqualToAnchor:self.safeAreaLayoutGuide.bottomAnchor constant:-16],
        [scroll.centerXAnchor constraintEqualToAnchor:self.centerXAnchor],
        [scroll.widthAnchor constraintLessThanOrEqualToConstant:600],
        preferredWidth,
        [stack.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor],
        [stack.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor],
        [stack.leadingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.leadingAnchor],
        [stack.trailingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.trailingAnchor],
        [stack.widthAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.widthAnchor]]];
    [self label:@"MV → MP4" stack:stack];
    [self label:ELMVText(@"Export the complete loaded MV with its selected song. Offline encoding may run slower than output FPS. The current game graphics settings are inherited.",@"현재 MV 전체와 선택된 음원을 내보냅니다. 오프라인 인코딩 속도는 출력 FPS보다 느릴 수 있습니다. 게임 그래픽 설정을 유지합니다.",@"読み込んだMV全体と選択された楽曲を書き出します。オフライン処理速度は出力FPSより遅い場合があります。ゲームの画質設定を使用します。") stack:stack];
    NSUserDefaults *defaults=NSUserDefaults.standardUserDefaults;
    [self label:@"Width (pixels; even, minimum 16)" stack:stack];
    self.widthField=[self field:[defaults stringForKey:@"SIFASMVExportWidth"] ?: @"1280" stack:stack];
    [self label:@"Height (pixels; even, minimum 16)" stack:stack];
    self.heightField=[self field:[defaults stringForKey:@"SIFASMVExportHeight"] ?: @"720" stack:stack];
    [self label:@"Frame rate" stack:stack]; self.rate=[[UISegmentedControl alloc] initWithItems:@[@"30 FPS",@"60 FPS",@"120 FPS"]];
    NSInteger savedRate=[defaults integerForKey:@"SIFASMVExportFPS"]; self.rate.selectedSegmentIndex=savedRate==120?2:savedRate==60?1:0; [stack addArrangedSubview:self.rate];
    [self label:@"Video codec" stack:stack]; self.codec=[[UISegmentedControl alloc] initWithItems:@[@"HEVC",@"H.264"]];
    self.codec.selectedSegmentIndex=[[defaults stringForKey:@"SIFASMVExportCodec"] isEqual:@"h264"]?1:0; [stack addArrangedSubview:self.codec];
    [self label:@"Video bitrate (Mbps)" stack:stack]; self.bitrateField=[self field:[defaults stringForKey:@"SIFASMVExportBitrate"] ?: @"8" stack:stack];
    self.recommendButton=[self button:@"Use recommended bitrate" action:@selector(recommend) stack:stack];
    for (UITextField *field in @[self.widthField,self.heightField,self.bitrateField])
        [field addTarget:self action:@selector(inputChanged) forControlEvents:UIControlEventEditingChanged];
    self.status=[self label:@"" stack:stack];
    self.exportButton=[self button:@"Export MP4" action:@selector(start) stack:stack];
    self.cancelButton=[self button:@"Cancel export" action:@selector(cancel) stack:stack];
    self.saveButton=[self button:@"Save completed MP4" action:@selector(save) stack:stack];
    self.shareButton=[self button:@"Share completed MP4" action:@selector(share) stack:stack];
    [self button:@"Close" action:@selector(close) stack:stack];
    __weak SIFASMVStandalonePanel *weakSelf=self;
    self.timer=[NSTimer scheduledTimerWithTimeInterval:.25 repeats:YES block:^(__unused NSTimer *timer) { [weakSelf refresh]; }];
    [self refresh]; return self;
}
- (void)dealloc { [_timer invalidate]; }
- (void)inputChanged { self.inputError=nil; [self refresh]; }
- (BOOL)dimensionsWidth:(NSUInteger *)width height:(NSUInteger *)height {
    long long w=0,h=0; NSScanner *ws=[NSScanner scannerWithString:self.widthField.text ?: @""],*hs=[NSScanner scannerWithString:self.heightField.text ?: @""];
    if (![ws scanLongLong:&w] || !ws.isAtEnd || ![hs scanLongLong:&h] || !hs.isAtEnd ||
        w<16 || h<16 || w>INT32_MAX || h>INT32_MAX || (w&1) || (h&1) || uint64_t(w)>uint64_t(INT32_MAX)/4/uint64_t(h)) {
        self.inputError=@"Enter positive even width and height (minimum16) with a representable RGBA frame. Any aspect ratio is allowed."; [self refresh]; return NO;
    }
    *width=NSUInteger(w); *height=NSUInteger(h); return YES;
}
- (void)recommend {
    NSUInteger width=0,height=0; if (![self dimensionsWidth:&width height:&height]) return;
    int fps=self.rate.selectedSegmentIndex==2?120:self.rate.selectedSegmentIndex==1?60:30;
    double mbps=double(width)*height*fps*(self.codec.selectedSegmentIndex==0?.09:.14)/1000000.0;
    self.bitrateField.text=[NSString stringWithFormat:@"%.3f",MAX(.25,mbps)];
    self.inputError=nil; [self refresh];
}
- (void)start {
    NSUInteger width=0,height=0; if (![self dimensionsWidth:&width height:&height]) return;
    NSString *input=[(self.bitrateField.text ?: @"") stringByReplacingOccurrencesOfString:@"," withString:@"."];
    NSScanner *scanner=[NSScanner scannerWithString:input]; double mbps=0;
    if (![scanner scanDouble:&mbps] || !scanner.isAtEnd || !std::isfinite(mbps) || mbps<=0 || mbps*1000000.0>=double(INT64_MAX) || std::round(mbps*1000000.0)<1) {
        self.inputError=@"Enter a positive Mbps bitrate representable as a signed64-bit bits/sec value."; [self refresh]; return;
    }
    int fps=self.rate.selectedSegmentIndex==2?120:self.rate.selectedSegmentIndex==1?60:30;
    NSString *codec=self.codec.selectedSegmentIndex==0?@"hevc":@"h264";
    NSUserDefaults *defaults=NSUserDefaults.standardUserDefaults;
    [defaults setObject:self.widthField.text forKey:@"SIFASMVExportWidth"]; [defaults setObject:self.heightField.text forKey:@"SIFASMVExportHeight"];
    [defaults setInteger:fps forKey:@"SIFASMVExportFPS"]; [defaults setObject:codec forKey:@"SIFASMVExportCodec"]; [defaults setObject:input forKey:@"SIFASMVExportBitrate"];
    self.inputError=nil; [self endEditing:YES]; [[ELMVExportCoordinator shared] startWidth:width height:height fps:fps codec:codec bitrate:NSUInteger(std::round(mbps*1000000.0))]; [self refresh];
}
- (void)refresh {
    NSDictionary *state=SIFASMVExportStatus(); BOOL busy=[state[@"busy"] boolValue];
    self.status.text=self.inputError.length && !busy ? self.inputError : [NSString stringWithFormat:@"%@\n%@\n%@ / %@ frames",ELMVPhase(state[@"phase"] ?: @"idle"),state[@"message"] ?: state[@"readiness"] ?: @"",state[@"videoFrames"] ?: @0,state[@"frameCount"] ?: @0];
    self.widthField.enabled=!busy; self.heightField.enabled=!busy; self.bitrateField.enabled=!busy; self.rate.enabled=!busy; self.codec.enabled=!busy;
    self.recommendButton.enabled=!busy; self.exportButton.enabled=!busy; self.cancelButton.enabled=busy;
    NSURL *output=[ELMVExportCoordinator shared].completedURL;
    BOOL completed=output && [NSFileManager.defaultManager fileExistsAtPath:output.path]; self.saveButton.enabled=completed && !busy; self.shareButton.enabled=completed && !busy;
}
- (void)cancel { SIFASMVCancelExport(); [self refresh]; }
- (void)close { [self endEditing:YES]; [self.timer invalidate]; self.timer=nil; [self removeFromSuperview]; }
- (void)save {
    NSURL *output=[ELMVExportCoordinator shared].completedURL; if (!output) return;
    UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc] initWithURLs:@[output] inMode:UIDocumentPickerModeExportToService];
    [self.presenter presentViewController:picker animated:YES completion:nil];
}
- (void)share {
    NSURL *output=[ELMVExportCoordinator shared].completedURL; if (!output) return;
    UIActivityViewController *share=[[UIActivityViewController alloc] initWithActivityItems:@[output] applicationActivities:nil];
    share.popoverPresentationController.sourceView=self.shareButton; share.popoverPresentationController.sourceRect=self.shareButton.bounds;
    [self.presenter presentViewController:share animated:YES completion:nil];
}
@end
void ElichikaPresentMVExportMenu(UIViewController *presenter) {
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ ElichikaPresentMVExportMenu(presenter); }); return; }
    if (presenter) SIFASMVStandaloneSetPresenter(presenter);
    presenter=SIFASMVStandalonePresenter(); if (!presenter || !SIFASMVStandaloneShowGame()) return;
    if (SIFASMVCurrentPanel.window) {
        [SIFASMVCurrentPanel.window bringSubviewToFront:SIFASMVCurrentPanel];
        [SIFASMVCurrentPanel refresh]; return;
    }
    SIFASMVStandalonePanel *panel=[[SIFASMVStandalonePanel alloc] initWithPresenter:presenter];
    [presenter.view.window addSubview:panel]; SIFASMVCurrentPanel=panel;
}
#endif
NSDictionary *SIFASMVExportStatus(void) {
    if (!NSThread.isMainThread) return @{@"phase":@"main-thread-required",@"busy":@NO};
    return [[ELMVExportCoordinator shared] status];
}
void SIFASMVCancelExport(void) { [[ELMVExportCoordinator shared] cancelWithReason:ELMVText(@"Export cancelled. The unfinished MP4 has been removed.",@"내보내기가 취소되었습니다. 미완성 MP4가 삭제되었습니다.",@"書き出しをキャンセルし、未完成のMP4を削除しました。")]; }
