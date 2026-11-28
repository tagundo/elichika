#import "SIFASMVExportSession.h"
#import "SIFASMVExportBindings.h"
#import "ElichikaMVEncoder.h"
#if defined(SIFAS_STANDALONE)
#import "SIFASMVStandaloneAdapter.h"
#import "SIFASMVExportFOV.hpp"
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
                 @"waiting":@[@"Waiting",@"대기",@"待機中"],
                 @"opening-mv":@[@"Opening MV",@"MV 여는 중",@"MVを開いています"],
                 @"combining":@[@"Combining MP4s",@"MP4 합치는 중",@"MP4を結合中"],
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
    NSURL *directory, *output, *combinedClipDirectory;
    NSString *audioSession, *phase, *message, *terminalPhase;
    NSString *queueEntryID;
    NSDictionary *queueFOVSnapshot;
    BOOL bindingsActive, ready, preparePending, closeStarted, audioClosed;
    BOOL cleaning, workerClean, completed, cleanupFailed;
#if defined(SIFAS_STANDALONE)
    NSTimeInterval macNoRenderProgressSince;
    double macLastProgress;
#endif
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
#if defined(SIFAS_STANDALONE)
    NSArray<NSDictionary *> *_queue;
    NSURL *_queueFile;
    NSString *_queueError, *_queueMessage, *_queueEntryID;
    SIFASMVExportFOVOverride *_queueFOV;
    uint64_t _queueEpoch;
    BOOL _queueActive, _queueCancelled;
    NSDictionary *_combinedEntry;
    NSArray<NSDictionary *> *_combinedSources;
    NSMutableArray<NSURL *> *_combinedClips;
    NSURL *_combinedDirectory;
    ELMVMP4Combination *_combination;
    NSString *_combinedCancelReason;
    id<NSObject> _macExportActivity;
    BOOL _macBackgroundRender;
    // "Add to export queue" checks the loaded MV for a short while; see
    // pollQueueRegistration:.
    NSDictionary *_queueRegistration;
    uint64_t _queueRegistrationEpoch;
    CFAbsoluteTime _queueRegistrationStarted;
    NSString *_queueRegistrationWaiting;
    // "Combine into MP4s": the remaining groups of one in-memory run. Groups
    // run in order; a group of >=2 clips is one ordinary combined entry and a
    // single clip is that MV's ordinary queued export (_groupSingleID).
    NSMutableArray<NSArray<NSString *> *> *_groupPlan;
    NSUInteger _groupTotal, _groupIndex, _groupExported, _groupSkipped, _groupFailed;
    NSMutableArray<NSNumber *> *_groupSkippedNumbers;
    NSMutableArray<NSString *> *_groupNotes;
    NSString *_groupSingleID, *_groupHaltReason, *_groupCancelReason;
    uint64_t _groupEpoch;
#endif
}
+ (instancetype)shared;
- (NSDictionary *)status;
- (NSURL *)completedURL;
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec;
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate;
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate queueEntry:(NSDictionary *)entry;
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
#if defined(SIFAS_STANDALONE)
- (NSArray<NSDictionary *> *)queueEntries;
- (NSArray<NSURL *> *)queuedOutputs;
- (NSString *)addToQueueWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate;
- (void)removeQueueEntry:(NSString *)identifier;
- (void)moveQueueEntryUp:(NSString *)identifier;
- (void)startQueue;
- (void)startCombinedQueue:(NSArray<NSString *> *)identifiers;
- (void)startCombinedGroups:(NSArray<NSArray<NSString *> *> *)groups;
- (void)retryCombinedQueueEntry:(NSString *)identifier;
- (NSString *)beginCombinedGroup:(NSArray<NSString *> *)identifiers;
- (BOOL)beginCombinedEntry:(NSDictionary *)entry sources:(NSArray<NSDictionary *> *)sources;
- (void)runNextGroup;
- (void)scheduleNextGroup;
- (void)recordGroupResult:(BOOL)exported message:(NSString *)message;
- (void)finishGroupPlan;
- (NSString *)pollQueueRegistration:(uint64_t)epoch;
- (NSString *)rejectQueueRegistration:(NSString *)message check:(NSString *)check detail:(NSString *)detail;
- (void)endQueueRegistration;
- (NSArray<NSDictionary *> *)combinedSources:(NSArray<NSString *> *)identifiers;
- (void)assembleCombinedQueue;
- (void)finishCombinedQueueWithOutput:(NSURL *)output message:(NSString *)message;
- (void)loadQueue;
- (BOOL)writeQueue:(NSArray<NSDictionary *> *)entries;
- (void)openNextQueueEntry;
- (void)finishQueueEntry:(NSString *)phase message:(NSString *)message output:(NSURL *)output safe:(BOOL)safe;
- (void)beginMacExport;
- (void)endMacBackgroundRender;
- (void)endMacExport;
- (void)showQueueNotice;
#endif
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
#if defined(SIFAS_STANDALONE)
static BOOL ELMVStandaloneVideoValid(NSUInteger width, NSUInteger height, int32_t fps, NSString *codec, NSUInteger bitrate) {
    return (fps==30 || fps==60 || fps==120) && width>=16 && height>=16 && !(width%2) && !(height%2) &&
        width<=INT32_MAX && height<=INT32_MAX && width<=NSUInteger(INT32_MAX)/4/height &&
        bitrate && bitrate<=NSUInteger(INT64_MAX) && [@[@"hevc",@"h264"] containsObject:codec];
}
// Clips per MP4 (the saved combined_sources limit) and MP4s per grouped run.
static constexpr NSUInteger ELMVCombinedSelectionLimit=100;
static constexpr NSUInteger ELMVCombinedGroupLimit=100;
// Android 21.4 gives queue registration 12 s for transient game states.
static constexpr CFAbsoluteTime ELMVQueueRegistrationWait=12.0;
static NSString *ELMVQueueIdentifier(id value) {
    if (![value isKindOfClass:NSString.class]) return nil;
    return [[NSUUID alloc] initWithUUIDString:value].UUIDString;
}
static BOOL ELMVValidCombinedSources(id value, NSString *identifier) {
    if (![value isKindOfClass:NSArray.class] || [value count]<2 || [value count]>ELMVCombinedSelectionLimit) return NO;
    NSMutableSet<NSString *> *seen=[NSMutableSet new];
    for (id raw in value) {
        NSString *canonical=ELMVQueueIdentifier(raw);
        if (!canonical || ![canonical isEqual:raw] || [canonical isEqual:identifier] || [seen containsObject:canonical]) return NO;
        [seen addObject:canonical];
    }
    return YES;
}
static NSURL *ELMVQueueOutput(NSURL *exports, NSDictionary *entry) {
    NSString *identifier=ELMVQueueIdentifier(entry[@"id"]);
    if (!exports || !identifier) return nil;
    NSString *name=[@"MV-" stringByAppendingString:identifier];
    NSURL *directory=[exports URLByAppendingPathComponent:name isDirectory:YES];
    int64_t live=0;
    if (entry[@"combined_sources"]) name=[@"MV-Combined-" stringByAppendingString:identifier];
    else if (ELMVInteger(entry[@"selection"][@"live_master_id"],1,INT32_MAX,&live))
        name=[NSString stringWithFormat:@"MV-%lld-%@",(long long)live,identifier];
    return [directory URLByAppendingPathComponent:[name stringByAppendingPathExtension:@"mp4"]];
}
static NSURL *ELMVQueueExports(void) {
    NSString *path=ElichikaHostConfiguration()[@"data_root"];
    if (![path isKindOfClass:NSString.class] || !path.isAbsolutePath) return nil;
    return [[[NSURL fileURLWithPath:path isDirectory:YES] URLByResolvingSymlinksInPath]
        URLByAppendingPathComponent:@"exports" isDirectory:YES];
}
static BOOL ELMVOutputExists(NSURL *output) {
    if (!output) return NO;
    NSDictionary *attributes=[NSFileManager.defaultManager attributesOfItemAtPath:output.path error:NULL];
    return [attributes[NSFileType] isEqual:NSFileTypeRegular] && [attributes[NSFileSize] unsignedLongLongValue]>0;
}
// One distinct message per failed "Add to export queue" check. The stable
// check identifier is appended so a screenshot names the exact check too.
static NSString *ELMVQueueCheckMessage(NSString *check, NSString *detail) {
    NSString *text=nil;
    detail=detail.length ? detail : @"";
    if ([check isEqual:@"bindings.installed"]) {
        text=ELMVText(@"This installation has no verified offline MV renderer. Install the matching GL 3.12.0 PlayCover export build.",
                      @"이 설치에는 검증된 오프라인 MV 렌더러가 없습니다. GL 3.12.0용 PlayCover 내보내기 빌드를 설치하세요.",
                      @"検証済みのオフラインMVレンダラーがありません。対応するGL 3.12.0のPlayCover書き出しビルドをインストールしてください。");
    } else if ([check isEqual:@"thread.unity-unknown"]) {
        text=ELMVText(@"The game's MV export interfaces are still loading. Play the MV until the stage is visible, then try again.",
                      @"게임의 MV 내보내기 기능이 아직 준비 중입니다. 무대가 보일 때까지 MV를 재생한 뒤 다시 시도하세요.",
                      @"ゲームのMV書き出し機能をまだ準備中です。ステージが表示されるまでMVを再生してから、もう一度お試しください。");
    } else if ([check hasPrefix:@"thread."] || [check isEqual:@"fov.main-thread"]) {
        text=ELMVText(@"The export queue was called outside the game's Unity thread. Restart the game and try again.",
                      @"내보내기 목록이 게임의 Unity 스레드 밖에서 호출되었습니다. 게임을 다시 시작한 뒤 시도하세요.",
                      @"書き出しリストがゲームのUnityスレッド外から呼び出されました。ゲームを再起動してからお試しください。");
    } else if ([check isEqual:@"runtime.rejected"]) {
        text=ELMVText(@"The game could not initialize its MV export interfaces. This client does not match the verified export build; reinstall the matching PlayCover build and restart the game.",
                      @"게임의 MV 내보내기 기능을 초기화하지 못했습니다. 이 클라이언트가 검증된 내보내기 빌드와 다릅니다. 맞는 PlayCover 빌드를 다시 설치하고 게임을 다시 시작하세요.",
                      @"ゲームのMV書き出し機能を初期化できませんでした。このクライアントは検証済みの書き出しビルドと一致しません。対応するPlayCoverビルドを再インストールし、ゲームを再起動してください。");
    } else if ([check isEqual:@"export.quarantined"]) {
        text=ELMVText(@"The previous MV export could not safely restore the game. Restart the game before using the export queue.",
                      @"이전 MV 내보내기가 게임 상태를 안전하게 복원하지 못했습니다. 내보내기 목록을 쓰기 전에 게임을 다시 시작하세요.",
                      @"前回のMV書き出しでゲームの状態を安全に復元できませんでした。書き出しリストを使う前にゲームを再起動してください。");
    } else if ([check isEqual:@"export.active"]) {
        text=ELMVText(@"Wait for the current MV export to restore its scene, then try again.",
                      @"현재 MV 내보내기가 장면을 복원할 때까지 기다린 뒤 다시 시도하세요.",
                      @"現在のMV書き出しがシーンを復元するまで待ってから、もう一度お試しください。");
    } else if ([check isEqual:@"navigation.busy"]) {
        text=ELMVText(@"The export queue is still opening an MV. Wait for it to finish, then try again.",
                      @"내보내기 목록이 아직 MV를 여는 중입니다. 끝날 때까지 기다린 뒤 다시 시도하세요.",
                      @"書き出しリストがまだMVを開いています。完了するまで待ってから、もう一度お試しください。");
    } else if ([check isEqual:@"navigation.override-unconfirmed"]) {
        text=ELMVText(@"This MV was opened by an export queue run that did not finish, so its settings and formation cannot be confirmed. Leave the MV, open it again from the MV menu, then add it.",
                      @"이 MV는 끝나지 않은 내보내기 목록 실행이 연 것이라 설정과 멤버 배치를 확인할 수 없습니다. MV에서 나간 뒤 MV 메뉴에서 다시 열고 등록하세요.",
                      @"このMVは完了しなかった書き出しリストの実行で開かれたため、設定とメンバー配置を確認できません。MVを終了し、MVメニューから開き直してから追加してください。");
    } else if ([check hasPrefix:@"director."]) {
        text=ELMVText(@"No playing 3D MV was found. Open a 3D MV from the MV menu and wait until the stage is visible.",
                      @"재생 중인 3D MV를 찾지 못했습니다. MV 메뉴에서 3D MV를 열고 무대가 보일 때까지 기다리세요.",
                      @"再生中の3D MVが見つかりません。MVメニューから3D MVを開き、ステージが表示されるまでお待ちください。");
    } else if ([check isEqual:@"cached.ready:final-camera"]) {
        text=ELMVText(@"The MV's final camera has not drawn the stage yet. Let the MV play until the stage is visible, then try again.",
                      @"MV의 최종 카메라가 아직 무대를 그리지 않았습니다. 무대가 보일 때까지 MV를 재생한 뒤 다시 시도하세요.",
                      @"MVの最終カメラがまだステージを描画していません。ステージが表示されるまでMVを再生してから、もう一度お試しください。");
    } else if ([check isEqual:@"cached.ready:music-loading"]) {
        text=ELMVText(@"The MV song is still loading. Wait for playback to start, then try again.",
                      @"MV 음원을 아직 불러오는 중입니다. 재생이 시작된 뒤 다시 시도하세요.",
                      @"MVの楽曲をまだ読み込んでいます。再生が始まってから、もう一度お試しください。");
    } else if ([check hasPrefix:@"cached.ready"]) {
        text=[NSString stringWithFormat:ELMVText(@"The game did not provide the MV song's cue sheet, cue, length or waveform (%@).",
                                                 @"게임에서 MV 음원의 큐 시트, 큐, 길이 또는 파형 정보를 받지 못했습니다(%@).",
                                                 @"ゲームからMV楽曲のキューシート、キュー、長さ、波形情報を取得できませんでした（%@）。"),detail];
    } else if ([check isEqual:@"scene.unique"]) {
        text=[NSString stringWithFormat:ELMVText(@"Exactly one loaded MV scene is required, but the game reported %@. Leave the MV and open it again.",
                                                 @"불러온 MV 장면이 하나여야 하지만 게임 상태는 %@입니다. MV에서 나간 뒤 다시 여세요.",
                                                 @"読み込まれたMVシーンは1つである必要がありますが、ゲームの状態は%@でした。MVを終了してから開き直してください。"),detail];
    } else if ([check isEqual:@"state.live-identity"]) {
        text=ELMVText(@"The game's current MV selection (song, stage, difficulty or deck) could not be read.",
                      @"게임의 현재 MV 선택(곡, 무대, 난이도 또는 덱)을 읽지 못했습니다.",
                      @"ゲームの現在のMV選択（楽曲、ステージ、難易度、デッキ）を読み取れませんでした。");
    } else if ([check isEqual:@"graphics.quality"]) {
        text=ELMVText(@"The MV's 3D graphics quality could not be read from the game.",
                      @"게임에서 MV의 3D 그래픽 품질을 읽지 못했습니다.",
                      @"ゲームからMVの3D画質設定を読み取れませんでした。");
    } else if ([check isEqual:@"graphics.setting"]) {
        text=ELMVText(@"The MV's display settings (quality mode, brightness or screen ratio) could not be read from the game.",
                      @"게임에서 MV 표시 설정(품질 모드, 밝기 또는 화면 비율)을 읽지 못했습니다.",
                      @"ゲームからMVの表示設定（画質モード、明るさ、画面比率）を読み取れませんでした。");
    } else if ([check isEqual:@"formation.members"]) {
        text=ELMVText(@"The MV's member formation or costumes could not be read from the game.",
                      @"게임에서 MV의 멤버 배치 또는 의상을 읽지 못했습니다.",
                      @"ゲームからMVのメンバー配置または衣装を読み取れませんでした。");
    } else if ([check isEqual:@"selection.encode"]) {
        text=ELMVText(@"The loaded MV could not be saved in a form the export queue can open again.",
                      @"불러온 MV를 내보내기 목록이 다시 열 수 있는 형태로 저장하지 못했습니다.",
                      @"読み込んだMVを書き出しリストで開き直せる形で保存できませんでした。");
    } else if ([check isEqual:@"game.exception"]) {
        text=ELMVText(@"The game rejected reading the loaded MV.",
                      @"게임이 불러온 MV 읽기를 거부했습니다.",
                      @"ゲームが読み込んだMVの読み取りを拒否しました。");
    } else if ([check isEqual:@"fov.main-image"] || [check isEqual:@"fov.config-section"]) {
        text=ELMVText(@"This game executable does not match the export build's FOV adapter, so the MV's camera FOV cannot be saved. Reinstall the matching PlayCover export build.",
                      @"게임 실행 파일이 내보내기 빌드의 FOV 어댑터와 맞지 않아 MV의 카메라 FOV를 저장할 수 없습니다. 맞는 PlayCover 내보내기 빌드를 다시 설치하세요.",
                      @"ゲームの実行ファイルが書き出しビルドのFOVアダプターと一致しないため、MVのカメラ画角を保存できません。対応するPlayCover書き出しビルドを再インストールしてください。");
    } else if ([check hasPrefix:@"fov.feature-"]) {
        text=ELMVText(@"The game's FOV feature (SIFASFeatures.dylib) is missing, modified or replaced, so the MV's camera FOV cannot be saved. Reinstall the matching PlayCover export build without other tweaks.",
                      @"게임의 FOV 기능(SIFASFeatures.dylib)이 없거나 변경 또는 교체되어 MV의 카메라 FOV를 저장할 수 없습니다. 다른 트윅 없이 맞는 PlayCover 내보내기 빌드를 다시 설치하세요.",
                      @"ゲームのFOV機能（SIFASFeatures.dylib）が見つからないか、変更・置換されているため、MVのカメラ画角を保存できません。他の改変を加えずに対応するPlayCover書き出しビルドを再インストールしてください。");
    } else if ([check isEqual:@"fov.bounds"]) {
        text=[NSString stringWithFormat:ELMVText(@"The current camera FOV limits (%@) must stay within 0.5–2.0 with the minimum not above the maximum. Change them in Client settings and try again.",
                                                 @"현재 카메라 FOV 범위(%@)는 0.5–2.0 안이어야 하며 최솟값이 최댓값보다 클 수 없습니다. 클라이언트 설정에서 바꾼 뒤 다시 시도하세요.",
                                                 @"現在のカメラ画角の範囲（%@）は0.5〜2.0の間で、最小値が最大値を超えてはいけません。クライアント設定で変更してから、もう一度お試しください。"),detail];
    } else {
        text=ELMVText(@"The loaded MV could not be registered in the export queue.",
                      @"불러온 MV를 내보낼 목록에 등록하지 못했습니다.",
                      @"読み込んだMVを書き出しリストに追加できませんでした。");
    }
    return [NSString stringWithFormat:@"%@ [%@]",text,check.length ? check : @"unknown"];
}
#endif
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
#if defined(SIFAS_STANDALONE)
        if (SIFASMVStandaloneRunOnMac())
            [center addObserver:self selector:@selector(becameActive:) name:UIWindowDidBecomeKeyNotification object:nil];
        [self loadQueue];
#endif
    }
    return self;
}
- (void)background:(NSNotification *)note {
#if defined(SIFAS_STANDALONE)
    if (!NSThread.isMainThread) { dispatch_async(dispatch_get_main_queue(), ^{ [self background:note]; }); return; }
    if (_macBackgroundRender || (_combination && SIFASMVStandaloneRunOnMac())) return;
#endif
    [self cancelWithReason:ELMVText(@"Export cancelled because the app entered the background.",@"앱이 백그라운드로 전환되어 내보내기가 취소되었습니다.",@"アプリがバックグラウンドに移ったため、書き出しをキャンセルしました。")];
}
- (void)memoryWarning:(NSNotification *)note { [self cancelWithReason:ELMVText(@"Export cancelled because iOS reported low memory. Try a lower resolution.",@"iOS의 메모리 부족 경고로 내보내기가 취소되었습니다. 해상도를 낮춰 보세요.",@"iOSのメモリ不足警告により、書き出しをキャンセルしました。解像度を下げてお試しください。")]; }
- (void)sceneClosed:(NSNotification *)note {
    if (!_gameWindow || note.object==_gameWindow.windowScene)
        [self cancelWithReason:ELMVText(@"Export cancelled because the app scene closed.",@"앱 화면이 닫혀 내보내기가 취소되었습니다.",@"アプリの画面が閉じられたため、書き出しをキャンセルしました。")];
}
- (void)becameActive:(NSNotification *)note { [self showPendingNotice]; }
- (BOOL)installInputBlocker {
    BOOL canReuse=NO;
#if defined(SIFAS_STANDALONE)
    // Reuse only the window acquired at the start of this export. A new export
    // must still start with an active game window.
    canReuse=_macBackgroundRender && _gameWindow && _inputBlocker.superview;
#endif
    if (!ElichikaHostShowGame()) return canReuse;
    UIWindow *window=ElichikaHostPresenter().view.window;
    UIView *gameView=window.rootViewController.view;
    if (!window || !gameView || window.hidden) return canReuse;
    if (_inputBlocker.superview==gameView && _gameWindow==window) return YES;
    [self removeInputBlocker];
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
    if (SIFASMVStandaloneRunOnMac() && (_queueActive || !SIFASMVStandaloneShowGame())) return;
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
#if defined(SIFAS_STANDALONE)
        if (_queueActive) {
            status[@"busy"]=@YES;
            status[@"phase"]=_combination ? @"combining" : @"opening-mv";
            [status removeObjectsForKeys:@[@"videoFrames",@"frameCount",@"audioSamples",@"sampleCount",@"message"]];
        }
        if (_queueRegistration) status[@"registering"]=@YES;
        NSString *queueMessage=_queueMessage ?: _queueError;
        if (_groupPlan) queueMessage=[NSString stringWithFormat:ELMVText(@"MP4 %lu of %lu",@"MP4 %lu / %lu",@"MP4 %lu / %lu"),
            (unsigned long)MAX(_groupIndex,(NSUInteger)1),(unsigned long)_groupTotal];
        if (queueMessage.length) status[@"message"]=queueMessage;
#endif
        return status;
    }
    ELMVEncoderConfiguration *c=run->configuration;
    NSMutableDictionary *status=[@{@"phase":run->cleaning ? @"draining" : run->phase,
             @"message":run->message ?: @"",@"busy":@YES,@"generation":@(run->generation),
             @"videoFrames":@(run->videoCount.load()),@"audioSamples":@(run->audioCount.load()),
             @"frameCount":@(c.frameCount),@"sampleCount":@(c.audioSampleCount),
             @"codec":c.codec ?: @"",@"width":@(c.width),@"height":@(c.height),@"fps":@(c.fpsNumerator)} mutableCopy];
#if defined(SIFAS_STANDALONE)
    if (_combinedEntry) status[@"message"]=[NSString stringWithFormat:ELMVText(@"Clip %lu of %lu",@"영상 %lu / %lu",@"クリップ %lu / %lu"),
        (unsigned long)_combinedClips.count+1,(unsigned long)_combinedSources.count];
    if (_groupPlan) {
        NSString *group=[NSString stringWithFormat:ELMVText(@"MP4 %lu of %lu",@"MP4 %lu / %lu",@"MP4 %lu / %lu"),
            (unsigned long)MAX(_groupIndex,(NSUInteger)1),(unsigned long)_groupTotal];
        NSString *detail=status[@"message"];
        status[@"message"]=[detail length] ? [NSString stringWithFormat:@"%@ · %@",group,detail] : group;
    }
#endif
    return status;
}
#if defined(SIFAS_STANDALONE)
- (void)beginMacExport {
    if (!SIFASMVStandaloneRunOnMac()) return;
    if (!_macExportActivity) {
        // Keep CPU work eligible and inhibit idle system sleep. The display is
        // free to sleep normally during the export.
        _macExportActivity=[NSProcessInfo.processInfo beginActivityWithOptions:NSActivityUserInitiated
            reason:@"Exporting SIFAS MV to MP4"];
    }
    if (!_macBackgroundRender) _macBackgroundRender=SIFASMVBindingsBeginMacBackgroundRender();
}
- (void)endMacBackgroundRender {
    if (!_macBackgroundRender) return;
    _macBackgroundRender=NO;
    SIFASMVBindingsEndMacBackgroundRender();
}
- (void)endMacExport {
    [self endMacBackgroundRender];
    if (_macExportActivity) {
        [NSProcessInfo.processInfo endActivity:_macExportActivity];
        _macExportActivity=nil;
    }
}
- (void)showQueueNotice {
    if (SIFASMVStandaloneRunOnMac()) {
        _pendingNotice=@{};
        [self showPendingNotice];
    } else if (UIApplication.sharedApplication.applicationState==UIApplicationStateActive) {
        ElichikaPresentMVExportMenu(SIFASMVStandalonePresenter());
    }
}
- (void)loadQueue {
    NSFileManager *files=NSFileManager.defaultManager;
    NSError *error=nil;
    NSURL *support=[files URLForDirectory:NSApplicationSupportDirectory inDomain:NSUserDomainMask
                            appropriateForURL:nil create:YES error:&error];
    if (!support) { _queueError=error.localizedDescription; return; }
    _queueFile=[support URLByAppendingPathComponent:@"Elichika-MV-Export-Queue.json"];
    NSURL *exports=ELMVQueueExports();
    if (exports) dispatch_async(_worker, ^{
        NSString *prefix=@".mv-combine-";
        for (NSURL *child in [NSFileManager.defaultManager contentsOfDirectoryAtURL:exports includingPropertiesForKeys:nil options:0 error:NULL]) {
            NSString *name=child.lastPathComponent;
            if ([name hasPrefix:prefix] && ELMVQueueIdentifier([name substringFromIndex:prefix.length]))
                [NSFileManager.defaultManager removeItemAtURL:child error:NULL];
        }
    });
    NSData *data=[NSData dataWithContentsOfURL:_queueFile options:0 error:&error];
    if (!data && [error.domain isEqual:NSCocoaErrorDomain] && error.code==NSFileReadNoSuchFileError) {
        _queue=@[]; return;
    }
    id document=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:&error] : nil;
    if (![document isKindOfClass:NSDictionary.class] || ![document[@"schema"] isEqual:@1] ||
        ![document[@"entries"] isKindOfClass:NSArray.class]) {
        _queueError=error.localizedDescription ?: @"The saved MP4 queue could not be read.";
        return;
    }
    NSMutableArray<NSDictionary *> *entries=[NSMutableArray new];
    NSMutableSet<NSString *> *identifiers=[NSMutableSet new];
    for (id entry in document[@"entries"]) {
        if (![entry isKindOfClass:NSDictionary.class]) { _queueError=@"The saved MP4 queue contains an invalid entry."; return; }
        NSString *identifier=ELMVQueueIdentifier(entry[@"id"]), *phase=entry[@"phase"];
        int64_t width=0,height=0,fps=0,bitrate=0;
        if (!identifier || ![identifier isEqual:entry[@"id"]] || [identifiers containsObject:identifier] ||
            ![entry[@"selection"] isKindOfClass:NSDictionary.class] || ![entry[@"title"] isKindOfClass:NSString.class] ||
            (entry[@"combined_sources"] && !ELMVValidCombinedSources(entry[@"combined_sources"],identifier)) ||
            !SIFASMVExportValidFOV(entry[@"fov"]) || ![@[@"waiting",@"completed",@"failed"] containsObject:phase ?: @""] ||
            !ELMVInteger(entry[@"width"],16,INT32_MAX,&width) || !ELMVInteger(entry[@"height"],16,INT32_MAX,&height) ||
            !ELMVInteger(entry[@"fps"],30,120,&fps) || !ELMVInteger(entry[@"bitrate"],1,INT64_MAX,&bitrate) ||
            !ELMVStandaloneVideoValid(NSUInteger(width),NSUInteger(height),int32_t(fps),entry[@"codec"],NSUInteger(bitrate))) {
            _queueError=@"The saved MP4 queue contains invalid settings.";
            return;
        }
        [identifiers addObject:identifier];
        NSMutableDictionary *restored=[entry mutableCopy];
        if (ELMVOutputExists(ELMVQueueOutput(exports,entry))) restored[@"phase"]=@"completed";
        else if ([phase isEqual:@"completed"]) restored[@"phase"]=@"waiting";
        [entries addObject:[restored copy]];
    }
    _queue=[entries copy];
}
- (BOOL)writeQueue:(NSArray<NSDictionary *> *)entries {
    if (!_queueFile || _queueError) return NO;
    NSError *error=nil;
    NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"schema":@1,@"entries":entries} options:0 error:&error];
    if (!data || ![data writeToURL:_queueFile options:NSDataWritingAtomic error:&error]) {
        _queueMessage=error.localizedDescription ?: @"The MP4 queue could not be saved.";
        return NO;
    }
    _queue=[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL][@"entries"];
    return YES;
}
- (NSArray<NSDictionary *> *)queueEntries {
    if (!_queueEntryID) return _queue ?: @[];
    NSMutableArray *visible=[_queue mutableCopy];
    NSUInteger index=[_queue indexOfObjectPassingTest:^BOOL(NSDictionary *entry, __unused NSUInteger index, __unused BOOL *stop) {
        return [entry[@"id"] isEqual:_queueEntryID];
    }];
    if (index!=NSNotFound) {
        NSMutableDictionary *current=[_queue[index] mutableCopy];
        current[@"phase"]=_run ? (_run->cleaning ? @"draining" : _run->phase) : (_combination ? @"combining" : @"opening-mv");
        visible[index]=[current copy];
    }
    return visible;
}
- (NSArray<NSURL *> *)queuedOutputs {
    NSURL *exports=ELMVQueueExports();
    NSMutableArray<NSURL *> *outputs=[NSMutableArray new];
    for (NSDictionary *entry in _queue) {
        if (![entry[@"phase"] isEqual:@"completed"]) continue;
        NSURL *output=ELMVQueueOutput(exports,entry);
        if (ELMVOutputExists(output)) [outputs addObject:output];
    }
    return outputs;
}
// Returns a message when the request ends at once with a failure. Otherwise
// the result (or "Checking the loaded MV…" while a transient game state such
// as a scene transition or the first rendered frame is awaited, at most
// ELMVQueueRegistrationWait seconds as on Android) is the queue message.
- (NSString *)addToQueueWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate {
    NSAssert(NSThread.isMainThread,@"The MP4 queue belongs to main");
    if (_queueError) return _queueError;
    if (_run || _queueActive) return ELMVText(@"Wait until the current export has finished.",@"현재 내보내기가 끝날 때까지 기다리세요.",@"現在の書き出しが終わるまでお待ちください。");
    if (_queueRegistration) return ELMVText(@"The loaded MV is still being checked.",@"불러온 MV를 아직 확인하는 중입니다.",@"読み込んだMVをまだ確認しています。");
    if (!ELMVStandaloneVideoValid(width,height,fps,codec,bitrate)) return ELMVText(@"The export settings are invalid.",@"내보내기 설정이 올바르지 않습니다.",@"書き出し設定が無効です。");
    _queueRegistration=@{@"width":@(width),@"height":@(height),@"fps":@(fps),@"codec":codec,@"bitrate":@(bitrate)};
    _queueRegistrationStarted=CFAbsoluteTimeGetCurrent(); _queueRegistrationWaiting=nil;
    _queueMessage=ELMVText(@"Checking the loaded MV…",@"불러온 MV를 확인하는 중…",@"読み込んだMVを確認中…");
    NSString *failure=[self pollQueueRegistration:++_queueRegistrationEpoch];
    if (failure) _queueMessage=nil;
    return failure;
}
- (NSString *)pollQueueRegistration:(uint64_t)epoch {
    if (epoch!=_queueRegistrationEpoch || !_queueRegistration) return nil;
    NSDictionary *settings=_queueRegistration;
    if (_run || _queueActive)
        return [self rejectQueueRegistration:ELMVText(@"Wait until the current export has finished.",@"현재 내보내기가 끝날 때까지 기다리세요.",@"現在の書き出しが終わるまでお待ちください。")
                                       check:@"export.started" detail:@"an export started while the MV was checked"];
    NSString *check=nil, *detail=nil; BOOL transient=NO;
    NSDictionary *selection=SIFASMVBindingsQueueSelectionChecked(&check,&detail,&transient);
    NSDictionary *fov=selection ? SIFASMVExportCaptureFOV() : nil;
    if (selection && !fov) {
        NSString *fovDetail=nil;
        check=SIFASMVExportFOVFailure(&fovDetail) ?: @"fov.capture";
        detail=fovDetail ?: @""; transient=NO;
    }
    if (selection && fov) {
        NSString *cue=SIFASMVBindingsSongSnapshot()[@"cue"];
        NSDictionary *entry=@{@"id":NSUUID.UUID.UUIDString,@"selection":selection,@"fov":fov,@"title":cue ?: @"",
                               @"width":settings[@"width"],@"height":settings[@"height"],@"fps":settings[@"fps"],
                               @"codec":settings[@"codec"],@"bitrate":settings[@"bitrate"],@"phase":@"waiting"};
        const CFAbsoluteTime waited=CFAbsoluteTimeGetCurrent()-_queueRegistrationStarted;
        [self endQueueRegistration];
        _queueMessage=nil; // writeQueue reports its own failure here.
        if (![self writeQueue:[_queue arrayByAddingObject:entry]]) {
            NSString *message=_queueMessage ?: @"The MP4 queue could not be saved.";
            NSLog(@"SIFAS-MV queue: Add to export queue rejected at check queue.save after %.1f s (%@)",waited,message);
            _queueMessage=message;
            return message;
        }
        NSLog(@"SIFAS-MV queue: Added live %@ stage %@ difficulty %@ deck %@ with FOV %@-%@ after %.1f s (%@)",
              selection[@"live_master_id"],selection[@"stage_id"],selection[@"difficulty_id"],selection[@"deck_type"],
              fov[@"min"],fov[@"max"],waited,detail ?: @"");
        _queueMessage=ELMVText(@"Added to the export queue.",@"내보낼 목록에 등록했습니다.",@"書き出しリストに追加しました。");
        return nil;
    }
    if (!check.length) check=@"unknown";
    if (transient && CFAbsoluteTimeGetCurrent()-_queueRegistrationStarted<ELMVQueueRegistrationWait) {
        if (![check isEqual:_queueRegistrationWaiting]) {
            _queueRegistrationWaiting=check;
            NSLog(@"SIFAS-MV queue: Add to export queue is waiting at check %@ (%@)",check,detail ?: @"");
        }
        __weak ELMVExportCoordinator *weakSelf=self;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(NSEC_PER_SEC/4)),dispatch_get_main_queue(), ^{
            [weakSelf pollQueueRegistration:epoch];
        });
        return nil;
    }
    NSString *message=ELMVQueueCheckMessage(check,detail);
    if (transient) message=[NSString stringWithFormat:@"%@ %@",ELMVText(@"A complete 3D MV was not ready to register in the export queue.",
        @"내보낼 목록에 등록할 완전한 3D MV가 준비되지 않았습니다.",@"書き出しリストに追加できる完全な3D MVの準備ができていません。"),message];
    return [self rejectQueueRegistration:message check:check detail:detail];
}
- (NSString *)rejectQueueRegistration:(NSString *)message check:(NSString *)check detail:(NSString *)detail {
    // Also record the FOV adapter and the renderer state, so one report shows
    // every independent precondition at once.
    NSString *fovDetail=nil, *fovCheck=SIFASMVExportFOVFailure(&fovDetail);
    NSDictionary *renderer=SIFASMVBindingsStatus();
    NSLog(@"SIFAS-MV queue: Add to export queue rejected at check %@ after %.1f s (%@); FOV %@; renderer installed=%@ director=%@ final-camera=%@ phase=%@ last failure=%@",
          check,CFAbsoluteTimeGetCurrent()-_queueRegistrationStarted,detail ?: @"",
          fovCheck ? [NSString stringWithFormat:@"%@ (%@)",fovCheck,fovDetail ?: @""] : @"ok",
          renderer[@"installed"],renderer[@"liveDirectorObserved"],renderer[@"finalOverlayObserved"],
          renderer[@"phase"] ?: @"",renderer[@"lastFailure"] ?: @"");
    [self endQueueRegistration];
    _queueMessage=message;
    return message;
}
- (void)endQueueRegistration {
    _queueRegistration=nil; _queueRegistrationWaiting=nil; ++_queueRegistrationEpoch;
}
- (void)removeQueueEntry:(NSString *)identifier {
    if (_run || _queueActive || _queueRegistration) return;
    NSMutableArray *entries=[_queue mutableCopy];
    for (NSUInteger i=0;i<entries.count;i++) {
        if (![entries[i][@"id"] isEqual:identifier]) continue;
        [entries removeObjectAtIndex:i];
        if ([self writeQueue:entries]) _queueMessage=nil;
        break;
    }
}
- (void)moveQueueEntryUp:(NSString *)identifier {
    if (_run || _queueActive || _queueRegistration) return;
    NSMutableArray *entries=[_queue mutableCopy];
    for (NSUInteger i=1;i<entries.count;i++) {
        if (![entries[i][@"id"] isEqual:identifier]) continue;
        [entries exchangeObjectAtIndex:i withObjectAtIndex:i-1];
        if ([self writeQueue:entries]) _queueMessage=nil;
        break;
    }
}
- (void)startQueue {
    if (_run || _queueActive || _queueRegistration) return;
    if (_queueError) { _queueMessage=_queueError; return; }
    _queueCancelled=NO; _queueActive=YES; _queueMessage=nil;
    [self openNextQueueEntry];
}
- (NSArray<NSDictionary *> *)combinedSources:(NSArray<NSString *> *)identifiers {
    if (!ELMVValidCombinedSources(identifiers,nil)) return nil;
    NSMutableDictionary<NSString *,NSDictionary *> *byID=[NSMutableDictionary new];
    for (NSDictionary *entry in _queue) if (!entry[@"combined_sources"]) byID[entry[@"id"]]=entry;
    NSMutableArray<NSDictionary *> *sources=[NSMutableArray new];
    for (NSString *identifier in identifiers) {
        NSDictionary *entry=byID[identifier];
        if (!entry) return nil;
        [sources addObject:entry];
    }
    return sources;
}
- (void)startCombinedQueue:(NSArray<NSString *> *)identifiers {
    NSAssert(NSThread.isMainThread,@"The combined queue belongs to main");
    if (_run || _queueActive || _queueRegistration) return;
    if (_queueError) { _queueMessage=_queueError; return; }
    NSString *failure=[self beginCombinedGroup:identifiers];
    if (failure) _queueMessage=failure;
}
// Saves one combined entry (video settings of the first clip, every clip with
// its own selection and FOV) and starts it. Returns a message when nothing
// was started.
- (NSString *)beginCombinedGroup:(NSArray<NSString *> *)identifiers {
    NSArray<NSDictionary *> *sources=[self combinedSources:identifiers];
    if (!sources)
        return ELMVText(@"Choose at least two different saved MVs.",@"서로 다른 저장 항목을 두 개 이상 고르세요.",@"異なる保存済みMVを2つ以上選んでください。");
    NSMutableDictionary *entry=[sources.firstObject mutableCopy];
    entry[@"id"]=NSUUID.UUID.UUIDString;
    entry[@"combined_sources"]=[identifiers copy];
    entry[@"phase"]=@"waiting";
    entry[@"title"]=[NSString stringWithFormat:ELMVText(@"Combined MV · %lu clips",@"합본 MV · %lu개",@"結合MV・%lu本"),(unsigned long)sources.count];
    if (!ELMVQueueExports()) return @"The export folder is unavailable.";
    if (![self writeQueue:[_queue arrayByAddingObject:entry]]) return _queueMessage ?: @"The MP4 queue could not be saved.";
    if (![self beginCombinedEntry:entry sources:sources]) return _queueMessage ?: @"The export folder is unavailable.";
    return nil;
}
// "Combine into MP4s": groups is the builder's ordered list of MP4s, each an
// ordered list of saved queue items. Empty groups are ignored; one group of
// two or more clips is exactly the former single combined export.
- (void)startCombinedGroups:(NSArray<NSArray<NSString *> *> *)groups {
    NSAssert(NSThread.isMainThread,@"The combined queue belongs to main");
    if (_run || _queueActive || _queueRegistration) return;
    if (_queueError) { _queueMessage=_queueError; return; }
    NSMutableSet<NSString *> *available=[NSMutableSet new], *used=[NSMutableSet new];
    for (NSDictionary *entry in _queue) if (!entry[@"combined_sources"]) [available addObject:entry[@"id"]];
    NSMutableArray<NSArray<NSString *> *> *plan=[NSMutableArray new];
    BOOL valid=[groups isKindOfClass:NSArray.class] && groups.count<=ELMVCombinedGroupLimit;
    for (id group in valid ? groups : @[]) {
        if (![group isKindOfClass:NSArray.class] || [group count]>ELMVCombinedSelectionLimit) { valid=NO; break; }
        if (![group count]) continue;
        for (id identifier in group) {
            if (![identifier isKindOfClass:NSString.class] || ![ELMVQueueIdentifier(identifier) isEqual:identifier] ||
                ![available containsObject:identifier] || [used containsObject:identifier]) { valid=NO; break; }
            [used addObject:identifier];
        }
        if (!valid) break;
        [plan addObject:[group copy]];
    }
    if (!valid || !plan.count) {
        _queueMessage=valid ? ELMVText(@"Add at least one saved MV to an MP4.",@"MP4에 저장한 MV를 하나 이상 추가하세요.",@"MP4に保存済みのMVを1つ以上追加してください。") :
            ELMVText(@"Each MP4 needs saved MVs from the queue, and each MV can be in only one MP4.",
                     @"각 MP4에는 목록에 저장한 MV만 넣을 수 있으며, MV 하나는 한 MP4에만 넣을 수 있습니다.",
                     @"各MP4にはリストに保存したMVだけを入れられ、1つのMVは1つのMP4にしか入れられません。");
        return;
    }
    if (plan.count==1 && plan.firstObject.count>=2) { [self startCombinedQueue:plan.firstObject]; return; }
    _groupPlan=plan; _groupTotal=plan.count; _groupIndex=0;
    _groupExported=_groupSkipped=_groupFailed=0;
    _groupSkippedNumbers=[NSMutableArray new]; _groupNotes=[NSMutableArray new];
    _groupSingleID=nil; _groupHaltReason=nil; _groupCancelReason=nil; ++_groupEpoch;
    _queueActive=YES; _queueCancelled=NO; _queueMessage=nil;
    NSLog(@"SIFAS-MV queue: Combine into MP4s started with %lu MP4s",(unsigned long)_groupTotal);
    [self runNextGroup];
}
- (void)scheduleNextGroup {
    const uint64_t epoch=_groupEpoch;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (_groupPlan && _groupEpoch==epoch) [self runNextGroup];
    });
}
- (void)recordGroupResult:(BOOL)exported message:(NSString *)message {
    if (exported) { _groupExported++; return; }
    if (_queueCancelled) return;
    _groupFailed++;
    NSString *reason=message.length ? message : ELMVText(@"Export failed.",@"내보내기에 실패했습니다.",@"書き出しに失敗しました。");
    [_groupNotes addObject:[NSString stringWithFormat:@"MP4 #%lu: %@",(unsigned long)_groupIndex,reason]];
    NSLog(@"SIFAS-MV queue: MP4 #%lu of %lu failed: %@",(unsigned long)_groupIndex,(unsigned long)_groupTotal,reason);
}
// Runs the next group in order. Only the conditions that already stop the
// ordinary queue end a run early: cancel, an unrestored FOV, an unsafe export
// cleanup, a queue file that cannot be saved, or a game that needs a restart.
- (void)runNextGroup {
    if (!_groupPlan || _run || _queueEntryID || _combinedEntry || _combination) return;
    while (_groupPlan.count && !_queueCancelled && !_groupHaltReason) {
        if ([SIFASMVBindingsStatus()[@"quarantined"] boolValue]) {
            _groupHaltReason=ELMVText(@"The previous MV export could not safely restore the game. Restart the game before using the export queue.",
                                      @"이전 MV 내보내기가 게임 상태를 안전하게 복원하지 못했습니다. 내보내기 목록을 쓰기 전에 게임을 다시 시작하세요.",
                                      @"前回のMV書き出しでゲームの状態を安全に復元できませんでした。書き出しリストを使う前にゲームを再起動してください。");
            break;
        }
        NSArray<NSString *> *group=_groupPlan.firstObject;
        [_groupPlan removeObjectAtIndex:0];
        _groupIndex++;
        if (group.count>=2) {
            NSLog(@"SIFAS-MV queue: MP4 #%lu of %lu combines %lu clips",(unsigned long)_groupIndex,(unsigned long)_groupTotal,(unsigned long)group.count);
            NSString *failure=[self beginCombinedGroup:group];
            if (!failure) return;
            [self recordGroupResult:NO message:failure];
            continue;
        }
        NSDictionary *entry=nil;
        for (NSDictionary *candidate in _queue)
            if (!candidate[@"combined_sources"] && [candidate[@"id"] isEqual:group.firstObject]) { entry=candidate; break; }
        if (!entry) {
            [self recordGroupResult:NO message:ELMVText(@"The saved MV is no longer in the queue.",@"저장한 MV가 더 이상 목록에 없습니다.",@"保存したMVがリストにありません。")];
            continue;
        }
        // A finished single MP4 is never rendered or overwritten again.
        if ([entry[@"phase"] isEqual:@"completed"] && ELMVOutputExists(ELMVQueueOutput(ELMVQueueExports(),entry))) {
            _groupSkipped++;
            [_groupSkippedNumbers addObject:@(_groupIndex)];
            NSLog(@"SIFAS-MV queue: MP4 #%lu of %lu skipped; its single MV is already exported",(unsigned long)_groupIndex,(unsigned long)_groupTotal);
            continue;
        }
        NSLog(@"SIFAS-MV queue: MP4 #%lu of %lu exports one MV",(unsigned long)_groupIndex,(unsigned long)_groupTotal);
        _groupSingleID=entry[@"id"];
        _queueActive=YES; _queueMessage=nil;
        [self openNextQueueEntry];
        return;
    }
    [self finishGroupPlan];
}
- (void)finishGroupPlan {
    if (!_groupPlan) return;
    const BOOL cancelled=_queueCancelled;
    NSMutableArray<NSString *> *lines=[NSMutableArray new];
    [lines addObject:[NSString stringWithFormat:ELMVText(@"Combine into MP4s: %lu exported, %lu skipped, %lu failed.",
                                                        @"MP4로 합치기: 내보냄 %lu개, 건너뜀 %lu개, 실패 %lu개.",
                                                        @"MP4にまとめる: 書き出し%lu個、スキップ%lu個、失敗%lu個。"),
        (unsigned long)_groupExported,(unsigned long)_groupSkipped,(unsigned long)_groupFailed]];
    if (_groupSkippedNumbers.count) {
        NSMutableArray<NSString *> *names=[NSMutableArray new];
        for (NSNumber *number in _groupSkippedNumbers) [names addObject:[NSString stringWithFormat:@"MP4 #%@",number]];
        [lines addObject:[NSString stringWithFormat:ELMVText(@"Already exported and kept as is: %@.",@"이미 내보낸 MP4라 그대로 두었습니다: %@.",@"書き出し済みのためそのままにしました: %@。"),
            [names componentsJoinedByString:@", "]]];
    }
    if (cancelled) {
        [lines addObject:[NSString stringWithFormat:@"%@ %@",_groupCancelReason ?: ELMVText(@"Export cancelled.",@"내보내기가 취소되었습니다.",@"書き出しをキャンセルしました。"),
            ELMVText(@"The remaining MP4s were not exported.",@"남은 MP4는 내보내지 않았습니다.",@"残りのMP4は書き出していません。")]];
    } else if (_groupHaltReason) {
        [lines addObject:[NSString stringWithFormat:@"%@ %@",_groupHaltReason,
            ELMVText(@"The remaining MP4s were not exported.",@"남은 MP4는 내보내지 않았습니다.",@"残りのMP4は書き出していません。")]];
    }
    const NSUInteger shown=MIN(_groupNotes.count,(NSUInteger)5);
    [lines addObjectsFromArray:[_groupNotes subarrayWithRange:NSMakeRange(0,shown)]];
    if (_groupNotes.count>shown) [lines addObject:@"…"];
    NSString *summary=[lines componentsJoinedByString:@"\n"];
    NSLog(@"SIFAS-MV queue: Combine into MP4s finished: %lu of %lu MP4s run, %lu exported, %lu skipped, %lu failed%@%@",
          (unsigned long)_groupIndex,(unsigned long)_groupTotal,(unsigned long)_groupExported,(unsigned long)_groupSkipped,
          (unsigned long)_groupFailed,cancelled?@", cancelled":@"",_groupHaltReason?[@", stopped: " stringByAppendingString:_groupHaltReason]:@"");
    NSString *phase=cancelled ? @"cancelled" : ((_groupFailed || _groupHaltReason) ? @"failed" : @"completed");
    _groupPlan=nil; _groupSkippedNumbers=nil; _groupNotes=nil; _groupSingleID=nil;
    _groupHaltReason=nil; _groupCancelReason=nil; ++_groupEpoch;
    _queueActive=NO; _queueCancelled=NO;
    _queueMessage=summary;
    _lastStatus=@{@"phase":phase,@"busy":@NO,@"message":summary};
    [self removeInputBlocker];
    [self endMacExport];
    [self showQueueNotice];
}
- (void)retryCombinedQueueEntry:(NSString *)identifier {
    NSAssert(NSThread.isMainThread,@"The combined queue belongs to main");
    if (_run || _queueActive || _queueRegistration) return;
    if (_queueError) { _queueMessage=_queueError; return; }
    for (NSDictionary *entry in _queue) {
        if (![entry[@"id"] isEqual:identifier] || !entry[@"combined_sources"] || [entry[@"phase"] isEqual:@"completed"]) continue;
        NSURL *output=ELMVQueueOutput(ELMVQueueExports(),entry);
        if (ELMVOutputExists(output)) {
            _combinedEntry=entry;
            [self finishCombinedQueueWithOutput:output message:nil];
            return;
        }
        NSArray<NSDictionary *> *sources=[self combinedSources:entry[@"combined_sources"]];
        if (!sources) {
            _queueMessage=ELMVText(@"A saved MV needed by this group is missing.",@"이 합본에 필요한 큐 항목이 없습니다.",@"この結合に必要なMVがリストにありません。");
            return;
        }
        [self beginCombinedEntry:entry sources:sources];
        return;
    }
}
- (BOOL)beginCombinedEntry:(NSDictionary *)entry sources:(NSArray<NSDictionary *> *)sources {
    NSURL *exports=ELMVQueueExports();
    if (!exports) { _queueMessage=@"The export folder is unavailable."; return NO; }
    _combinedEntry=entry;
    _combinedSources=[sources copy];
    _combinedClips=[NSMutableArray new];
    _combinedDirectory=[exports URLByAppendingPathComponent:[@".mv-combine-" stringByAppendingString:NSUUID.UUID.UUIDString] isDirectory:YES];
    _combinedCancelReason=nil;
    _queueActive=YES; _queueCancelled=NO; _queueMessage=nil;
    [self openNextQueueEntry];
    return YES;
}
- (void)openNextQueueEntry {
    if (!_queueActive || _queueCancelled || _run || _queueEntryID) return;
    NSDictionary *next=nil;
    if (_combinedEntry) {
        if (_combinedClips.count==_combinedSources.count) { [self assembleCombinedQueue]; return; }
        NSMutableDictionary *source=[_combinedSources[_combinedClips.count] mutableCopy];
        source[@"id"]=_combinedEntry[@"id"];
        for (NSString *key in @[@"width",@"height",@"fps",@"codec",@"bitrate"]) source[key]=_combinedEntry[key];
        next=source;
    } else if (_groupSingleID) {
        // A single-clip MP4 of a grouped run: exactly that saved MV, as an
        // ordinary queued export. A completed one with a missing file renders again.
        for (NSDictionary *entry in _queue)
            if (!entry[@"combined_sources"] && [entry[@"id"] isEqual:_groupSingleID]) { next=entry; break; }
        if (!next) {
            _groupSingleID=nil;
            [self recordGroupResult:NO message:ELMVText(@"The saved MV is no longer in the queue.",@"저장한 MV가 더 이상 목록에 없습니다.",@"保存したMVがリストにありません。")];
            [self scheduleNextGroup];
            return;
        }
    } else for (NSDictionary *entry in _queue) {
        if (!entry[@"combined_sources"] && ![entry[@"phase"] isEqual:@"completed"]) { next=entry; break; }
    }
    if (!next) {
        _queueActive=NO;
        _queueMessage=ELMVText(@"Queued MP4s are ready to save.",@"목록의 MP4를 저장할 수 있습니다.",@"リストのMP4を保存できます。");
        [self removeInputBlocker];
        [self endMacExport];
        [self showQueueNotice];
        return;
    }
    _queueEntryID=next[@"id"];
    const uint64_t epoch=++_queueEpoch;
    NSDictionary *selection=next[@"selection"];
    if (NSString *defect=SIFASMVBindingsQueueSelectionDefect(selection)) {
        NSLog(@"SIFAS-MV queue: queued live %@ stage %@ cannot be opened: %@",selection[@"live_master_id"],selection[@"stage_id"],defect);
        [self finishQueueEntry:@"failed" message:[defect isEqual:@"selection.legacy-suit"] ?
            ELMVText(@"This saved MV was registered by an earlier export build and its costumes cannot be restored. Remove it, load the MV and add it to the export queue again.",
                     @"이 저장 항목은 이전 내보내기 빌드로 등록되어 의상을 복원할 수 없습니다. 항목을 삭제하고 MV를 불러와 내보낼 목록에 다시 등록하세요.",
                     @"この保存済みMVは以前の書き出しビルドで追加されたため、衣装を復元できません。削除してからMVを読み込み、書き出しリストに追加し直してください。") :
            ELMVText(@"The saved MV selection is invalid. Remove it and add the MV to the export queue again.",
                     @"저장된 MV 선택 정보가 올바르지 않습니다. 항목을 삭제하고 MV를 내보낼 목록에 다시 등록하세요.",
                     @"保存されたMVの選択情報が無効です。削除してから、MVを書き出しリストに追加し直してください。")
            output:nil safe:NO];
        return;
    }
    if (![self installInputBlocker]) {
        [self finishQueueEntry:@"failed" message:@"The game window is unavailable." output:nil safe:NO];
        return;
    }
    [self beginMacExport];
    NSString *error=nil;
    _queueFOV=SIFASMVExportApplyFOV(next[@"fov"],&error);
    if (!_queueFOV) {
        [self finishQueueEntry:@"failed" message:error ?: @"The queued FOV could not be applied." output:nil safe:NO];
        return;
    }
    void (^ready)(NSString *)=^(NSString *reason) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!_queueActive || _queueCancelled || _queueEpoch!=epoch) return;
            // Only a selection the scene load confirmed (queue navigation or
            // full observation) may stand for the queued entry; live game
            // state is what the game would load now, not what is on screen.
            NSDictionary *loaded=reason.length ? nil : SIFASMVBindingsQueueSelection();
            if (reason.length || ![loaded isEqualToDictionary:selection]) {
                NSString *check=nil, *detail=nil;
                if (!reason.length && !loaded) {
                    NSDictionary *live=SIFASMVBindingsQueueSelectionChecked(&check,&detail,NULL);
                    if (live) check=@"selection.unconfirmed";
                }
                NSLog(@"SIFAS-MV queue: queued live %@ stage %@ did not open: %@",selection[@"live_master_id"],selection[@"stage_id"],
                      reason.length ? reason : (loaded ? @"the loaded MV differs from the queued selection" :
                      [NSString stringWithFormat:@"check %@ (%@)",check,detail ?: @""]));
                [self finishQueueEntry:@"failed" message:reason.length ? reason : @"The loaded MV differs from the queued selection." output:nil safe:NO];
                return;
            }
            [self startWidth:[next[@"width"] unsignedIntegerValue] height:[next[@"height"] unsignedIntegerValue]
                         fps:[next[@"fps"] intValue] codec:next[@"codec"] bitrate:[next[@"bitrate"] unsignedIntegerValue] queueEntry:next];
        });
    };
    // Skip reopening only when the scene load confirms the loaded MV is this
    // entry; a selection read from live game state always reopens it.
    if ([SIFASMVBindingsQueueSelection() isEqualToDictionary:selection]) ready(nil);
    else if (!SIFASMVBindingsQueueOpen(selection,ready)) {
        [self finishQueueEntry:@"failed" message:@"The game could not open the queued MV." output:nil safe:NO];
    }
}
- (void)finishQueueEntry:(NSString *)phase message:(NSString *)message output:(NSURL *)output safe:(BOOL)safe {
    if (!_queueActive || !_queueEntryID) return;
    const BOOL restoreOK=!_queueFOV || SIFASMVExportRestoreFOV(_queueFOV);
    _queueFOV=nil;
    NSString *identifier=_queueEntryID;
    _queueEntryID=nil; ++_queueEpoch;
    const BOOL completed=[phase isEqual:@"completed"] && ELMVOutputExists(output);
    if (_combinedEntry) {
        if (completed && safe && restoreOK && !_queueCancelled) {
            [_combinedClips addObject:output];
            dispatch_async(dispatch_get_main_queue(), ^{ [self openNextQueueEntry]; });
        } else {
            if (!restoreOK) message=@"The game FOV could not be restored. The rest of the queue is on hold.";
            if (_groupPlan && !restoreOK) _groupHaltReason=message;
            [self finishCombinedQueueWithOutput:nil message:message];
        }
        return;
    }
    NSString *storedPhase=completed ? @"completed" : (_queueCancelled ? @"waiting" : @"failed");
    NSMutableArray *entries=[_queue mutableCopy];
    NSUInteger index=[_queue indexOfObjectPassingTest:^BOOL(NSDictionary *entry, __unused NSUInteger index, __unused BOOL *stop) {
        return [entry[@"id"] isEqual:identifier];
    }];
    BOOL saved=NO;
    if (index!=NSNotFound) {
        NSMutableDictionary *entry=[_queue[index] mutableCopy];
        entry[@"phase"]=storedPhase;
        entries[index]=[entry copy];
        saved=[self writeQueue:entries];
    }
    if (_groupSingleID) {
        // One MP4 of a grouped run ended; the run continues with the next one
        // unless this ended the way that stops the ordinary queue.
        _groupSingleID=nil;
        if (!restoreOK) message=@"The game FOV could not be restored. The rest of the queue is on hold.";
        if (!restoreOK) _groupHaltReason=message;
        else if (!saved) _groupHaltReason=_queueMessage ?: @"The MP4 queue could not be saved.";
        [self recordGroupResult:completed message:message];
        [self scheduleNextGroup];
        return;
    }
    if (saved && safe && restoreOK && completed && !_queueCancelled) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self openNextQueueEntry]; });
        return;
    }
    _queueActive=NO;
    if (!restoreOK) _queueMessage=@"The game FOV could not be restored. The rest of the queue is on hold.";
    else if (saved) _queueMessage=message;
    [self removeInputBlocker];
    [self endMacExport];
    [self showQueueNotice];
}
- (void)assembleCombinedQueue {
    if (_combination || !_combinedEntry) return;
    NSURL *output=ELMVQueueOutput(ELMVQueueExports(),_combinedEntry);
    NSURL *folder=output.URLByDeletingLastPathComponent;
    NSFileManager *fm=NSFileManager.defaultManager;
    NSNumber *symlink=nil;
    [folder getResourceValue:&symlink forKey:NSURLIsSymbolicLinkKey error:NULL];
    NSError *error=nil;
    if (!output || symlink.boolValue || ![fm createDirectoryAtURL:folder withIntermediateDirectories:YES attributes:nil error:&error]) {
        [self finishCombinedQueueWithOutput:nil message:error.localizedDescription ?: @"The combined MP4 destination is unavailable."];
        return;
    }
    _queueEntryID=_combinedEntry[@"id"];
    const uint64_t epoch=++_queueEpoch;
    // When more MP4s of a grouped run follow, keep the input blocker, its game
    // window and the Mac background render through the assembly, exactly as
    // the queue keeps them between entries: on a Mac in the background the
    // next MP4 can neither acquire a game window nor begin a new render lease
    // (both need an active app), and would fail at once.
    const BOOL moreGroups=_groupPlan.count>0;
    if (!moreGroups) [self removeInputBlocker];
    _combination=[ELMVMP4Combination combineSources:[_combinedClips copy] outputURL:output workerQueue:_worker
        callbackQueue:dispatch_get_main_queue() completion:^(NSURL *result, NSError *failure) {
            if (!_combinedEntry || _queueEpoch!=epoch) return;
            NSString *reason=_combinedCancelReason ?: failure.localizedDescription;
            [self finishCombinedQueueWithOutput:result message:reason];
        }];
    if (!moreGroups) [self endMacBackgroundRender];
    if (!_combination) [self finishCombinedQueueWithOutput:nil message:@"The combined MP4 could not be started."];
}
- (void)finishCombinedQueueWithOutput:(NSURL *)output message:(NSString *)message {
    if (!_combinedEntry) return;
    NSURL *expected=ELMVQueueOutput(ELMVQueueExports(),_combinedEntry);
    const BOOL complete=[output isEqual:expected] && ELMVOutputExists(expected);
    NSString *phase=complete ? @"completed" : (_queueCancelled ? @"waiting" : @"failed");
    NSMutableArray<NSDictionary *> *entries=[_queue mutableCopy];
    NSString *identifier=_combinedEntry[@"id"];
    for (NSUInteger i=0;i<entries.count;i++) if ([entries[i][@"id"] isEqual:identifier]) {
        NSMutableDictionary *entry=[entries[i] mutableCopy];
        entry[@"phase"]=phase;
        entries[i]=[entry copy];
        break;
    }
    if (complete) _completedURL=output;
    NSString *notice=complete ? ELMVText(@"Combined MP4 is ready to save.",@"합본 MP4를 저장할 수 있습니다.",@"結合MP4を保存できます。") :
        (message ?: ELMVText(@"Combined MP4 export failed.",@"합본 MP4 내보내기에 실패했습니다.",@"MP4の結合に失敗しました。"));
    const BOOL saved=[self writeQueue:entries];
    if (saved) _queueMessage=notice;
    else if (complete) _queue=[entries copy]; // The finalized file also lets loadQueue recover this result.
    NSURL *scratch=_combinedDirectory;
    if (scratch) dispatch_async(_worker, ^{ [NSFileManager.defaultManager removeItemAtURL:scratch error:NULL]; });
    _combinedEntry=nil; _combinedSources=nil; _combinedClips=nil; _combinedDirectory=nil;
    _combination=nil; _combinedCancelReason=nil; _queueEntryID=nil; ++_queueEpoch;
    if (_groupPlan) {
        if (!saved && !_groupHaltReason) _groupHaltReason=_queueMessage ?: @"The MP4 queue could not be saved.";
        [self recordGroupResult:complete message:notice];
        [self scheduleNextGroup];
        return;
    }
    _queueActive=NO; _queueCancelled=NO;
    _lastStatus=@{@"phase":phase,@"busy":@NO,@"message":_queueMessage ?: notice};
    [self removeInputBlocker];
    [self endMacExport];
    [self showQueueNotice];
}
#endif
- (void)watch:(NSTimer *)timer {
#if defined(SIFAS_STANDALONE)
    (void)timer;
    ELMVExportRun *run=_run;
    if (!run || run->cleaning) return;
    if (run->queueFOVSnapshot &&
        ![SIFASMVExportCaptureFOV() isEqualToDictionary:run->queueFOVSnapshot]) {
        [self fail:@"The game FOV changed during the queued export." run:run];
        return;
    }
    if (!_macExportActivity || !_macBackgroundRender || ![run->phase isEqual:@"rendering"] ||
        (UIApplication.sharedApplication.applicationState==UIApplicationStateActive &&
         !SIFASMVBindingsMacBackgroundRenderFallbackActive())) {
        run->macNoRenderProgressSince=0;
        return;
    }
    const NSTimeInterval now=NSProcessInfo.processInfo.systemUptime;
    const double progress=run->lastProgress.load();
    if (!run->macNoRenderProgressSince || progress!=run->macLastProgress) {
        run->macNoRenderProgressSince=now;
        run->macLastProgress=progress;
    } else if (now-run->macNoRenderProgressSince>45.0) {
        [self fail:ELMVText(@"No frames rendered for 45 seconds in the background. Open the PlayCover window and retry the export.",
                          @"백그라운드에서 45초 동안 영상 프레임이 렌더링되지 않았습니다. PlayCover 창을 열고 다시 내보내세요.",
                          @"バックグラウンドで45秒間フレームを書き出せませんでした。PlayCoverのウインドウを開いて再試行してください。") run:run];
    }
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
    [self startWidth:width height:height fps:fps codec:codec bitrate:bitrate queueEntry:nil];
}
- (void)rejectStart:(NSString *)message queueEntry:(NSDictionary *)entry {
    _lastStatus=@{@"phase":@"failed",@"busy":@NO,@"message":message};
#if defined(SIFAS_STANDALONE)
    if (entry) [self finishQueueEntry:@"failed" message:message output:nil safe:NO];
#else
    (void)entry;
#endif
}
- (void)startWidth:(NSUInteger)width height:(NSUInteger)height fps:(int32_t)fps codec:(NSString *)codec bitrate:(NSUInteger)bitrate queueEntry:(NSDictionary *)entry {
    NSAssert(NSThread.isMainThread,@"MV start belongs to main");
    if (_run) return;
#if defined(SIFAS_STANDALONE)
    if (_queueActive!=(entry!=nil) || (entry && ![_queueEntryID isEqual:entry[@"id"]])) return;
    _queueMessage=nil;
#endif
    NSString *readiness=ELMVReadiness();
    if (readiness.length) { [self rejectStart:readiness queueEntry:entry]; return; }
    int64_t milliseconds=0;
    NSDictionary *initialSnapshot=SIFASMVBindingsSongSnapshot();
    NSDictionary *song=ELMVValidatedSong(initialSnapshot,&milliseconds);
    int64_t sceneIdentity=0;
    if (!song || !ELMVInteger(initialSnapshot[@"scene_identity"],INT32_MIN,INT32_MAX,&sceneIdentity) || !sceneIdentity) {
        [self rejectStart:ELMVText(@"The MV song snapshot is incomplete or invalid (scene, cue sheet, cue, gain or timing). Wait for loading to finish.",@"MV 음원 정보(장면, 큐 시트, 큐, 음량 또는 시간)가 누락되었거나 올바르지 않습니다. 로딩이 끝날 때까지 기다려 주세요.",@"MVの楽曲情報（シーン、キューシート、キュー、音量、再生時間）が不足しているか無効です。読み込みの完了をお待ちください。") queueEntry:entry];
        return;
    }
#if defined(SIFAS_STANDALONE)
    if (!ELMVStandaloneVideoValid(width,height,fps,codec,bitrate)) {
        [self rejectStart:@"Use positive even pixel dimensions (minimum 16), a representable RGBA frame, 30/60/120 FPS and a positive bitrate." queueEntry:entry];
        return;
    }
    const uint32_t simulationHz=uint32_t(MAX(60,fps));
#else
    if (![@[@30,@60] containsObject:@(fps)] || ![@[@720,@1080,@2160] containsObject:@(MIN(width,height))] ||
        width>4096 || height>4096 || ![@[@"hevc",@"h264"] containsObject:codec]) return;
    const uint32_t simulationHz=60;
#endif
    ELMVExportRun *run=[ELMVExportRun new]; run->generation=++_generation;
    run->queueEntryID=entry[@"id"];
    run->queueFOVSnapshot=entry[@"fov"];
#if defined(SIFAS_STANDALONE)
    if (_combinedEntry) {
        NSString *name=[NSString stringWithFormat:@"Clip-%lu",(unsigned long)_combinedClips.count+1];
        run->combinedClipDirectory=[_combinedDirectory URLByAppendingPathComponent:name isDirectory:YES];
    }
#endif
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
#if defined(SIFAS_STANDALONE)
    [self beginMacExport];
#endif
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
                NSURL *queuedOutput=nil;
#if defined(SIFAS_STANDALONE)
                if (run->combinedClipDirectory)
                    queuedOutput=[run->combinedClipDirectory URLByAppendingPathComponent:@"Clip.mp4"];
                else if (run->queueEntryID) queuedOutput=ELMVQueueOutput(exports,entry);
#endif
                NSURL *directory=queuedOutput ? queuedOutput.URLByDeletingLastPathComponent :
                    [exports URLByAppendingPathComponent:[@"MV-" stringByAppendingString:NSUUID.UUID.UUIDString] isDirectory:YES];
                NSError *error=nil;
                BOOL isExistingDirectory=NO;
                if (queuedOutput && [fm fileExistsAtPath:directory.path isDirectory:&isExistingDirectory]) {
                    NSNumber *symlink=nil;
                    [directory getResourceValue:&symlink forKey:NSURLIsSymbolicLinkKey error:NULL];
                    if (!isExistingDirectory || symlink.boolValue || [fm fileExistsAtPath:queuedOutput.path])
                        failure=@"The queued MP4 destination is already occupied.";
                } else if (![fm createDirectoryAtURL:directory withIntermediateDirectories:run->combinedClipDirectory!=nil attributes:nil error:&error])
                    failure=error.localizedDescription;
                if (!failure) {
                    run->directory=directory;
                    run->output=queuedOutput ?: [directory URLByAppendingPathComponent:@"MV.mp4"];
                }
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                if (_run!=run || run->stopped.load()) return;
                if (failure) { [self fail:failure run:run]; return; }
                NSDictionary *fresh=SIFASMVBindingsSongSnapshot(); int64_t freshIdentity=0;
                if (!ELMVInteger(fresh[@"scene_identity"],INT32_MIN,INT32_MAX,&freshIdentity) || !freshIdentity || freshIdentity!=sceneIdentity ||
                    ![fresh[@"sheet"] isEqual:song[@"sheet"]] || ![fresh[@"cue"] isEqual:song[@"cue"]]) {
                    [self fail:ELMVText(@"The loaded MV changed during export preparation. Open the intended MV and start again.",@"내보내기를 준비하는 동안 MV가 변경되었습니다. 원하는 MV를 열고 다시 시작하세요.",@"書き出しの準備中にMVが変更されました。目的のMVを開いて再度開始してください。") run:run]; return;
                }
#if defined(SIFAS_STANDALONE)
                if (entry && (![SIFASMVBindingsQueueSelection() isEqualToDictionary:entry[@"selection"]] ||
                              ![SIFASMVExportCaptureFOV() isEqualToDictionary:entry[@"fov"]])) {
                    [self fail:@"The selected MV or FOV changed during export preparation." run:run];
                    return;
                }
#endif
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
                    run->completed=YES;
                    if (!run->combinedClipDirectory) _completedURL=output;
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
#if defined(SIFAS_STANDALONE)
    if (_queueRegistration) {
        NSLog(@"SIFAS-MV queue: Add to export queue cancelled (%@)",reason ?: @"");
        [self endQueueRegistration];
        _queueMessage=reason;
    }
    if (_queueActive) {
        _queueCancelled=YES;
        // Cancel stops the current MP4 and every remaining group of a run.
        if (_groupPlan && !_groupCancelReason) _groupCancelReason=reason;
        if (!_run) {
            SIFASMVBindingsQueueCancelNavigation();
            if (_combination) {
                _combinedCancelReason=reason;
                [_combination cancel];
            }
            else if (_queueEntryID) [self finishQueueEntry:@"cancelled" message:reason output:nil safe:NO];
            else if (_combinedEntry) [self finishCombinedQueueWithOutput:nil message:reason];
            else if (_groupPlan) [self finishGroupPlan];
            else { _queueActive=NO; _queueMessage=reason; [self removeInputBlocker]; [self endMacExport]; }
            return;
        }
    }
#endif
    if (_run && !_run->cleaning) [self cleanup:_run terminal:@"cancelled" message:reason];
}
- (void)cleanup:(ELMVExportRun *)run terminal:(NSString *)terminal message:(NSString *)message {
    if (_run!=run || run->cleaning) return;
    run->cleaning=YES; run->stopped=true; run->ready=NO;
    run->clock->cancel(run->generation); run->terminalPhase=terminal; run->message=message;
    if (run->bindingsActive) { run->bindingsActive=NO; SIFASMVBindingsEnd(); }
    NSString *restorePhase=SIFASMVBindingsStatus()[@"phase"];
    if ([restorePhase isEqual:@"restore-incomplete"]) {
        run->cleanupFailed=YES;
        run->message=[run->message stringByAppendingFormat:ELMVText(@" State restoration: %@",@" 상태 복원: %@",@" 状態の復元: %@"),SIFASMVBindingsStatus()[@"lastFailure"] ?: @"incomplete"];
    }
    // Even a cancelled prepare must acknowledge close before another run may
    // start. This prevents stale reads/closes from reaching the next song.
    if (!run->closeStarted) {
        run->closeStarted=YES;
        NSMutableDictionary *request=[@{@"schema":@1} mutableCopy];
        if (run->audioSession) request[@"session_id"]=run->audioSession;
        ElichikaPythonCallWithArguments(@"mv_export_audio_close",request,^(NSDictionary *reply) {
            run->audioClosed=YES;
            if (![reply[@"ok"] boolValue]) {
                run->cleanupFailed=YES;
                run->message=[run->message stringByAppendingFormat:ELMVText(@" Audio cleanup: %@",@" 오디오 정리: %@",@" 音声の後処理: %@"),ELMVReplyError(reply)];
            }
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
                run->completed=YES;
                if (!run->combinedClipDirectory) _completedURL=run->output;
                run->terminalPhase=@"completed";
                if (!run->cleanupFailed) run->message=ELMVText(@"MP4 export completed. Save or share the file below.",@"MP4 내보내기가 완료되었습니다. 아래에서 파일을 저장하거나 공유하세요.",@"MP4の書き出しが完了しました。下からファイルを保存または共有できます。");
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
    _run=nil; [_watchdog invalidate]; _watchdog=nil;
#if defined(SIFAS_STANDALONE)
    if (run->queueEntryID) {
        // An export that could not clean up stops a grouped run like the queue.
        if (run->cleanupFailed && _groupPlan && !_groupHaltReason) _groupHaltReason=run->message;
        [self finishQueueEntry:run->terminalPhase message:run->message output:run->output safe:!run->cleanupFailed];
        return;
    }
    [self endMacExport];
#endif
    [self removeInputBlocker];
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
@property(nonatomic,strong) UIButton *queueAddButton,*queueStartButton,*queueSaveButton,*combineButton;
@property(nonatomic,strong) UIScrollView *scroll;
@property(nonatomic,strong) UIStackView *queueRows,*exportContent,*combineContent;
@property(nonatomic,copy) NSArray<NSDictionary *> *displayedQueue;
// "Combine into MP4s" builder: ordered MP4s, each an ordered list of saved
// queue item IDs. An item is in at most one MP4. combinedSelection is the
// active MP4, where "Add to MP4 #k" puts items.
@property(nonatomic,strong) NSMutableArray<NSMutableArray<NSString *> *> *combinedGroups;
@property(nonatomic) NSUInteger activeCombinedGroup;
@property(nonatomic,readonly) NSMutableArray<NSString *> *combinedSelection;
@property(nonatomic) BOOL queueWasBusy, queueWasRegistering;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,weak) UIViewController *presenter;
@property(nonatomic,copy) NSString *inputError;
- (void)refresh;
- (void)refreshCombinedSelection;
@end
static __weak SIFASMVStandalonePanel *SIFASMVCurrentPanel;
static NSString *ELMVCombineExportTitle(NSUInteger count) {
    if (ELMVLanguageIndex()==0) return count==1 ? @"Export 1 MP4" : [NSString stringWithFormat:@"Export %lu MP4s",(unsigned long)count];
    return [NSString stringWithFormat:ELMVText(@"Export %lu MP4s",@"MP4 %lu개 내보내기",@"%lu個のMP4を書き出す"),(unsigned long)count];
}
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
    scroll.keyboardDismissMode=UIScrollViewKeyboardDismissModeOnDrag; self.scroll=scroll; [self addSubview:scroll];
    UIStackView *content=[UIStackView new]; content.axis=UILayoutConstraintAxisVertical; content.translatesAutoresizingMaskIntoConstraints=NO;
    [scroll addSubview:content];
    NSLayoutConstraint *preferredWidth=[scroll.widthAnchor constraintEqualToAnchor:self.widthAnchor constant:-32]; preferredWidth.priority=UILayoutPriorityDefaultHigh;
    [NSLayoutConstraint activateConstraints:@[
        [scroll.topAnchor constraintEqualToAnchor:self.safeAreaLayoutGuide.topAnchor constant:16],
        [scroll.bottomAnchor constraintEqualToAnchor:self.safeAreaLayoutGuide.bottomAnchor constant:-16],
        [scroll.centerXAnchor constraintEqualToAnchor:self.centerXAnchor],
        [scroll.widthAnchor constraintLessThanOrEqualToConstant:600],
        preferredWidth,
        [content.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor],
        [content.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor],
        [content.leadingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.leadingAnchor],
        [content.trailingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.trailingAnchor],
        [content.widthAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.widthAnchor]]];
    UIStackView *stack=[UIStackView new]; stack.axis=UILayoutConstraintAxisVertical; stack.spacing=10;
    self.exportContent=stack; [content addArrangedSubview:stack];
    self.combineContent=[UIStackView new]; self.combineContent.axis=UILayoutConstraintAxisVertical;
    self.combineContent.spacing=10; self.combineContent.hidden=YES; [content addArrangedSubview:self.combineContent];
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
    self.queueAddButton=[self button:ELMVText(@"Add to export queue",@"내보낼 목록에 등록",@"書き出しリストに追加") action:@selector(addToQueue) stack:stack];
    self.queueStartButton=[self button:ELMVText(@"Export queue",@"목록 내보내기",@"リストを書き出す") action:@selector(startQueue) stack:stack];
    self.combineButton=[self button:ELMVText(@"Combine into MP4s…",@"MP4로 합치기…",@"MP4にまとめる…") action:@selector(chooseCombined) stack:stack];
    self.combineButton.accessibilityIdentifier=@"Elichika.MVExport.Combine";
    self.cancelButton=[self button:@"Cancel export" action:@selector(cancel) stack:stack];
    self.queueRows=[UIStackView new]; self.queueRows.axis=UILayoutConstraintAxisVertical; self.queueRows.spacing=10;
    [stack addArrangedSubview:self.queueRows];
    self.queueSaveButton=[self button:ELMVText(@"Save completed queue files",@"목록의 완료된 MP4 저장",@"リストの完成済みMP4を保存") action:@selector(saveQueue) stack:stack];
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
- (NSDictionary *)videoSettings {
    NSUInteger width=0,height=0; if (![self dimensionsWidth:&width height:&height]) return nil;
    NSString *input=[(self.bitrateField.text ?: @"") stringByReplacingOccurrencesOfString:@"," withString:@"."];
    NSScanner *scanner=[NSScanner scannerWithString:input]; double mbps=0;
    if (![scanner scanDouble:&mbps] || !scanner.isAtEnd || !std::isfinite(mbps) || mbps<=0 || mbps*1000000.0>=double(INT64_MAX) || std::round(mbps*1000000.0)<1) {
        self.inputError=@"Enter a positive Mbps bitrate representable as a signed 64-bit bits/sec value."; [self refresh]; return nil;
    }
    int fps=self.rate.selectedSegmentIndex==2?120:self.rate.selectedSegmentIndex==1?60:30;
    NSString *codec=self.codec.selectedSegmentIndex==0?@"hevc":@"h264";
    NSUserDefaults *defaults=NSUserDefaults.standardUserDefaults;
    [defaults setObject:self.widthField.text forKey:@"SIFASMVExportWidth"]; [defaults setObject:self.heightField.text forKey:@"SIFASMVExportHeight"];
    [defaults setInteger:fps forKey:@"SIFASMVExportFPS"]; [defaults setObject:codec forKey:@"SIFASMVExportCodec"]; [defaults setObject:input forKey:@"SIFASMVExportBitrate"];
    self.inputError=nil; [self endEditing:YES];
    return @{@"width":@(width),@"height":@(height),@"fps":@(fps),@"codec":codec,@"bitrate":@(NSUInteger(std::round(mbps*1000000.0)))};
}
- (void)start {
    NSDictionary *settings=[self videoSettings];
    if (!settings) return;
    [[ELMVExportCoordinator shared] startWidth:[settings[@"width"] unsignedIntegerValue] height:[settings[@"height"] unsignedIntegerValue]
        fps:[settings[@"fps"] intValue] codec:settings[@"codec"] bitrate:[settings[@"bitrate"] unsignedIntegerValue]];
    [self refresh];
}
- (void)addToQueue {
    NSDictionary *settings=[self videoSettings];
    if (!settings) return;
    self.inputError=[[ELMVExportCoordinator shared] addToQueueWidth:[settings[@"width"] unsignedIntegerValue] height:[settings[@"height"] unsignedIntegerValue]
        fps:[settings[@"fps"] intValue] codec:settings[@"codec"] bitrate:[settings[@"bitrate"] unsignedIntegerValue]];
    [self refresh];
}
- (void)startQueue {
    self.inputError=nil; [self endEditing:YES];
    [[ELMVExportCoordinator shared] startQueue]; [self refresh];
}
- (void)removeEntry:(UIButton *)sender {
    [[ELMVExportCoordinator shared] removeQueueEntry:sender.accessibilityIdentifier]; [self refresh];
}
- (void)moveEntryUp:(UIButton *)sender {
    [[ELMVExportCoordinator shared] moveQueueEntryUp:sender.accessibilityIdentifier]; [self refresh];
}
- (NSString *)combinedVideoSettings:(NSDictionary *)entry {
    NSString *codec=[entry[@"codec"] isEqual:@"h264"] ? @"H.264" : @"HEVC";
    return [NSString stringWithFormat:@"%@×%@ · %@ FPS · %@ · %.2f Mbps",entry[@"width"],entry[@"height"],
            entry[@"fps"],codec,[entry[@"bitrate"] doubleValue]/1000000.0];
}
- (NSString *)combinedSourceLabel:(NSDictionary *)entry {
    NSString *title=entry[@"title"];
    NSDictionary *fov=entry[@"fov"];
    return [NSString stringWithFormat:@"%@ · %@ %@ · FOV %.5g / %.5g",title.length ? title : @"MV",
            ELMVText(@"Stage",@"무대",@"ステージ"),entry[@"selection"][@"stage_id"] ?: @"",
            [fov[@"min"] doubleValue],[fov[@"max"] doubleValue]];
}
- (NSMutableArray<NSString *> *)combinedSelection {
    return self.activeCombinedGroup<self.combinedGroups.count ? self.combinedGroups[self.activeCombinedGroup] : nil;
}
- (NSMutableArray<NSString *> *)combinedGroupContaining:(NSString *)identifier {
    if (!identifier) return nil;
    for (NSMutableArray<NSString *> *group in self.combinedGroups) if ([group containsObject:identifier]) return group;
    return nil;
}
- (void)showExportQueue {
    self.combinedGroups=nil; self.activeCombinedGroup=0;
    self.combineContent.hidden=YES; self.exportContent.hidden=NO;
    for (UIView *view in self.combineContent.arrangedSubviews) [view removeFromSuperview];
    [self.scroll setContentOffset:CGPointMake(0,-self.scroll.adjustedContentInset.top) animated:NO];
    [self refresh];
}
- (void)chooseCombined {
    if (!self.combineButton.enabled || [SIFASMVExportStatus()[@"busy"] boolValue]) return;
    [self endEditing:YES]; self.inputError=nil;
    self.combinedGroups=[NSMutableArray arrayWithObject:[NSMutableArray new]]; self.activeCombinedGroup=0;
    self.exportContent.hidden=YES; self.combineContent.hidden=NO;
    [self refreshCombinedSelection];
    [self.scroll setContentOffset:CGPointMake(0,-self.scroll.adjustedContentInset.top) animated:NO];
}
- (NSString *)combinedGroupNote:(NSArray<NSString *> *)group sources:(NSDictionary<NSString *,NSDictionary *> *)sourcesByID {
    if (!group.count) return ELMVText(@"No MVs yet. An empty MP4 is skipped.",
                                      @"아직 MV가 없습니다. 빈 MP4는 내보내지 않습니다.",
                                      @"まだMVがありません。空のMP4は書き出しません。");
    return [NSString stringWithFormat:ELMVText(
        @"All clips use the first MV’s video settings (%@). Each MV keeps its saved FOV.",
        @"모든 클립에 첫 번째 MV의 영상 설정(%@)을 적용합니다. FOV는 각 MV에 저장된 값을 사용합니다.",
        @"すべてのクリップで最初のMVの映像設定（%@）を使用します。画角はMVごとの保存値を使用します。"),
        [self combinedVideoSettings:sourcesByID[group.firstObject]]];
}
- (void)refreshCombinedSelection {
    NSMutableArray<NSMutableArray<NSString *> *> *groups=self.combinedGroups;
    if (!groups) return;
    NSMutableArray<NSDictionary *> *sources=[NSMutableArray new];
    NSMutableDictionary<NSString *,NSDictionary *> *sourcesByID=[NSMutableDictionary new];
    for (NSDictionary *entry in [ELMVExportCoordinator shared].queueEntries) {
        if (entry[@"combined_sources"]) continue;
        [sources addObject:entry]; sourcesByID[entry[@"id"]]=entry;
    }
    // Drop items no longer in the queue; an item stays in its first MP4 only.
    NSMutableSet<NSString *> *grouped=[NSMutableSet new];
    for (NSMutableArray<NSString *> *group in groups) {
        for (NSString *identifier in [group copy])
            if (!sourcesByID[identifier] || [grouped containsObject:identifier]) [group removeObject:identifier];
        [grouped addObjectsFromArray:group];
    }
    if (!groups.count) [groups addObject:[NSMutableArray new]];
    if (self.activeCombinedGroup>=groups.count) self.activeCombinedGroup=groups.count-1;
    NSUInteger exports=0;
    for (NSArray<NSString *> *group in groups) if (group.count) exports++;
    UIStackView *stack=self.combineContent;
    for (UIView *view in stack.arrangedSubviews) [view removeFromSuperview];
    [self label:ELMVText(@"Combine into MP4s",@"MP4로 합치기",@"MP4にまとめる") stack:stack];
    [self label:ELMVText(@"Each MP4 plays its saved MVs in order. Select an MP4, then add MVs to it. An MP4 with one MV exports that MV alone. Each MV can be in one MP4.",
                         @"MP4마다 저장한 MV를 순서대로 재생합니다. MP4를 고른 뒤 MV를 추가하세요. MV가 하나인 MP4는 그 MV만 내보냅니다. MV 하나는 한 MP4에만 넣을 수 있습니다.",
                         @"MP4ごとに保存済みのMVを順番に再生します。MP4を選んでからMVを追加してください。MVが1つのMP4はそのMVだけを書き出します。1つのMVは1つのMP4にのみ入れられます。") stack:stack];
    UIButton *start=[self button:ELMVCombineExportTitle(exports) action:@selector(startCombinedSelection) stack:stack];
    start.enabled=exports>0; start.accessibilityIdentifier=@"Elichika.MVExport.Combine.Start";
    UIButton *add=[self button:ELMVText(@"New MP4",@"새 MP4",@"新しいMP4") action:@selector(addCombinedGroup) stack:stack];
    add.enabled=groups.count<ELMVCombinedGroupLimit; add.accessibilityIdentifier=@"Elichika.MVExport.Combine.NewGroup";
    [self button:ELMVText(@"Back to export queue",@"내보내기 목록으로",@"書き出しリストに戻る") action:@selector(showExportQueue) stack:stack];
    for (NSUInteger number=0;number<groups.count;number++) {
        NSArray<NSString *> *group=groups[number];
        const BOOL active=number==self.activeCombinedGroup;
        NSString *heading=[NSString stringWithFormat:@"%@MP4 #%lu · %@",active?@"▶ ":@"",(unsigned long)number+1,
            [NSString stringWithFormat:ELMVText(@"%lu clips",@"클립 %lu개",@"%luクリップ"),(unsigned long)group.count]];
        if (active) heading=[heading stringByAppendingFormat:@" · %@",ELMVText(@"adding here",@"여기에 추가",@"ここに追加")];
        UIButton *choose=[self button:heading action:@selector(selectCombinedGroup:) stack:stack];
        choose.tag=(NSInteger)number;
        choose.accessibilityIdentifier=[NSString stringWithFormat:@"Elichika.MVExport.Combine.Group.%lu",(unsigned long)number+1];
        choose.titleLabel.adjustsFontSizeToFitWidth=YES;
        if (active) choose.backgroundColor=[UIColor colorWithRed:.85 green:.92 blue:1 alpha:1];
        [self label:[self combinedGroupNote:group sources:sourcesByID] stack:stack];
        for (NSUInteger index=0;index<group.count;index++) {
            NSString *identifier=group[index];
            [self label:[NSString stringWithFormat:@"%lu. %@",(unsigned long)index+1,[self combinedSourceLabel:sourcesByID[identifier]]] stack:stack];
            UIStackView *actions=[UIStackView new]; actions.axis=UILayoutConstraintAxisHorizontal;
            actions.spacing=10; actions.distribution=UIStackViewDistributionFillEqually;
            [stack addArrangedSubview:actions];
            UIButton *up=[self button:ELMVText(@"Move up",@"위로 이동",@"上へ") action:@selector(moveCombinedUp:) stack:actions];
            up.accessibilityIdentifier=identifier; up.enabled=index>0;
            UIButton *down=[self button:ELMVText(@"Move down",@"아래로 이동",@"下へ") action:@selector(moveCombinedDown:) stack:actions];
            down.accessibilityIdentifier=identifier; down.enabled=index+1<group.count;
            UIButton *remove=[self button:ELMVText(@"Remove",@"제외",@"除外") action:@selector(removeCombinedSource:) stack:actions];
            remove.accessibilityIdentifier=identifier;
            for (UIButton *button in @[up,down,remove]) button.titleLabel.adjustsFontSizeToFitWidth=YES;
        }
    }
    NSArray<NSString *> *selected=self.combinedSelection;
    if (selected.count>=ELMVCombinedSelectionLimit) {
        [self label:[NSString stringWithFormat:ELMVText(@"Up to %lu clips per MP4.",@"MP4 하나에 클립을 최대 %lu개까지 넣을 수 있습니다.",@"MP4のクリップは最大%lu本です。"),
                     (unsigned long)ELMVCombinedSelectionLimit] stack:stack];
        return;
    }
    BOOL listed=NO;
    for (NSDictionary *entry in sources) if (![grouped containsObject:entry[@"id"]]) {
        if (!listed) {
            [self label:ELMVText(@"Saved MVs not in an MP4",@"아직 MP4에 넣지 않은 저장 MV",@"まだMP4に入れていない保存済みMV") stack:stack];
            listed=YES;
        }
        [self label:[self combinedSourceLabel:entry] stack:stack];
        UIButton *button=[self button:[NSString stringWithFormat:ELMVText(@"Add to MP4 #%lu",@"MP4 #%lu에 추가",@"MP4 #%luに追加"),
            (unsigned long)self.activeCombinedGroup+1] action:@selector(addCombinedSource:) stack:stack];
        button.accessibilityIdentifier=entry[@"id"];
    }
}
- (void)addCombinedGroup {
    if (!self.combinedGroups || self.combinedGroups.count>=ELMVCombinedGroupLimit) return;
    [self.combinedGroups addObject:[NSMutableArray new]];
    self.activeCombinedGroup=self.combinedGroups.count-1;
    [self refreshCombinedSelection];
}
- (void)selectCombinedGroup:(UIButton *)sender {
    if (sender.tag<0 || (NSUInteger)sender.tag>=self.combinedGroups.count) return;
    self.activeCombinedGroup=(NSUInteger)sender.tag;
    [self refreshCombinedSelection];
}
- (void)addCombinedSource:(UIButton *)sender {
    NSString *identifier=sender.accessibilityIdentifier;
    NSMutableArray<NSString *> *selected=self.combinedSelection;
    if (!identifier || !selected || selected.count>=ELMVCombinedSelectionLimit || [self combinedGroupContaining:identifier]) return;
    [selected addObject:identifier]; [self refreshCombinedSelection];
}
- (void)removeCombinedSource:(UIButton *)sender {
    // The MP4 stays in the builder even when its last clip is removed.
    [[self combinedGroupContaining:sender.accessibilityIdentifier] removeObject:sender.accessibilityIdentifier];
    [self refreshCombinedSelection];
}
- (void)moveCombinedSource:(UIButton *)sender by:(NSInteger)delta {
    NSMutableArray<NSString *> *group=[self combinedGroupContaining:sender.accessibilityIdentifier];
    if (!group) return;
    NSUInteger found=[group indexOfObject:sender.accessibilityIdentifier];
    NSInteger destination=(NSInteger)found+delta;
    if (found==NSNotFound || destination<0 || destination>=(NSInteger)group.count) return;
    [group exchangeObjectAtIndex:found withObjectAtIndex:(NSUInteger)destination];
    [self refreshCombinedSelection];
}
- (void)moveCombinedUp:(UIButton *)sender { [self moveCombinedSource:sender by:-1]; }
- (void)moveCombinedDown:(UIButton *)sender { [self moveCombinedSource:sender by:1]; }
- (void)startCombinedSelection {
    if ([SIFASMVExportStatus()[@"busy"] boolValue] || [SIFASMVExportStatus()[@"registering"] boolValue]) return;
    NSMutableArray<NSArray<NSString *> *> *groups=[NSMutableArray new];
    for (NSArray<NSString *> *group in self.combinedGroups) if (group.count) [groups addObject:[group copy]];
    if (!groups.count) return;
    [self showExportQueue];
    [[ELMVExportCoordinator shared] startCombinedGroups:groups]; [self refresh];
}
- (void)retryCombinedEntry:(UIButton *)sender {
    self.inputError=nil; [self endEditing:YES];
    [[ELMVExportCoordinator shared] retryCombinedQueueEntry:sender.accessibilityIdentifier]; [self refresh];
}
- (void)refreshQueue:(BOOL)busy registering:(BOOL)registering {
    ELMVExportCoordinator *coordinator=[ELMVExportCoordinator shared];
    NSArray<NSDictionary *> *entries=coordinator.queueEntries;
    if ([self.displayedQueue isEqualToArray:entries] && self.queueWasBusy==busy && self.queueWasRegistering==registering) return;
    self.displayedQueue=entries; self.queueWasBusy=busy; self.queueWasRegistering=registering;
    for (UIView *view in self.queueRows.arrangedSubviews) [view removeFromSuperview];
    NSUInteger pending=0,sourceCount=0;
    for (NSUInteger index=0;index<entries.count;index++) {
        NSDictionary *entry=entries[index], *selection=entry[@"selection"], *fov=entry[@"fov"];
        NSString *phase=entry[@"phase"], *cue=entry[@"title"];
        NSArray *sources=entry[@"combined_sources"];
        if (!sources) {
            sourceCount++;
            if (![phase isEqual:@"completed"]) pending++;
        }
        NSString *text=sources ? [NSString stringWithFormat:@"%@ · %@\n%@",
            [NSString stringWithFormat:ELMVText(@"Combined MV · %lu clips",@"MV 합본 · 클립 %lu개",@"MV合成 · %luクリップ"),(unsigned long)sources.count],
            ELMVPhase(phase),[self combinedVideoSettings:entry]] : [NSString stringWithFormat:@"%@ · %@ %@ · %@\n%@×%@ · %@ FPS · %@ · %.2f Mbps · FOV %.5g / %.5g",
            cue.length ? cue : ELMVText(@"MV",@"MV",@"MV"),ELMVText(@"Stage",@"무대",@"ステージ"),selection[@"stage_id"] ?: @"",
            ELMVPhase(phase),entry[@"width"],entry[@"height"],entry[@"fps"],[entry[@"codec"] uppercaseString],
            [entry[@"bitrate"] doubleValue]/1000000.0,[fov[@"min"] doubleValue],[fov[@"max"] doubleValue]];
        [self label:text stack:self.queueRows];
        if (busy) continue;
        UIStackView *actions=[UIStackView new]; actions.axis=UILayoutConstraintAxisHorizontal;
        actions.spacing=10; actions.distribution=UIStackViewDistributionFillEqually;
        [self.queueRows addArrangedSubview:actions];
        if (sources && ![phase isEqual:@"completed"]) {
            UIButton *retry=[self button:ELMVText(@"Retry combined export",@"합본 내보내기 다시 시도",@"合成書き出しを再試行") action:@selector(retryCombinedEntry:) stack:actions];
            retry.accessibilityIdentifier=entry[@"id"];
        } else if (!sources && index) {
            UIButton *move=[self button:ELMVText(@"Move up",@"위로 이동",@"上へ") action:@selector(moveEntryUp:) stack:actions];
            move.accessibilityIdentifier=entry[@"id"];
        }
        UIButton *remove=[self button:ELMVText(@"Remove from queue",@"목록에서 삭제",@"リストから削除") action:@selector(removeEntry:) stack:actions];
        remove.accessibilityIdentifier=entry[@"id"];
    }
    self.queueStartButton.enabled=!busy && !registering && pending!=0;
    // A single saved MV can form an MP4 of its own in the group builder.
    self.combineButton.enabled=!busy && !registering && sourceCount>=1;
    self.combineContent.userInteractionEnabled=!busy;
    NSString *startTitle=ELMVText(@"Export queue",@"목록 내보내기",@"リストを書き出す");
    if (pending) startTitle=[NSString stringWithFormat:@"%@ (%lu)",startTitle,(unsigned long)pending];
    [self.queueStartButton setTitle:startTitle forState:UIControlStateNormal];
    self.queueSaveButton.enabled=!busy && coordinator.queuedOutputs.count!=0;
}
- (void)refresh {
    NSDictionary *state=SIFASMVExportStatus(); BOOL busy=[state[@"busy"] boolValue];
    const BOOL registering=[state[@"registering"] boolValue];
    self.status.text=self.inputError.length && !busy ? self.inputError : [NSString stringWithFormat:@"%@\n%@\n%@ / %@ frames",ELMVPhase(state[@"phase"] ?: @"idle"),state[@"message"] ?: state[@"readiness"] ?: @"",state[@"videoFrames"] ?: @0,state[@"frameCount"] ?: @0];
    self.widthField.enabled=!busy; self.heightField.enabled=!busy; self.bitrateField.enabled=!busy; self.rate.enabled=!busy; self.codec.enabled=!busy;
    self.recommendButton.enabled=!busy; self.exportButton.enabled=!busy && !registering;
    self.queueAddButton.enabled=!busy && !registering; self.cancelButton.enabled=busy;
    NSURL *output=[ELMVExportCoordinator shared].completedURL;
    BOOL completed=output && [NSFileManager.defaultManager fileExistsAtPath:output.path]; self.saveButton.enabled=completed && !busy; self.shareButton.enabled=completed && !busy;
    [self refreshQueue:busy registering:registering];
}
- (void)cancel { SIFASMVCancelExport(); [self refresh]; }
- (void)close { [self endEditing:YES]; [self.timer invalidate]; self.timer=nil; [self removeFromSuperview]; }
- (void)save {
    NSURL *output=[ELMVExportCoordinator shared].completedURL; if (!output) return;
    UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc] initWithURLs:@[output] inMode:UIDocumentPickerModeExportToService];
    [self.presenter presentViewController:picker animated:YES completion:nil];
}
- (void)saveQueue {
    NSArray<NSURL *> *outputs=[ELMVExportCoordinator shared].queuedOutputs;
    if (!outputs.count) return;
    UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc] initWithURLs:outputs inMode:UIDocumentPickerModeExportToService];
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
