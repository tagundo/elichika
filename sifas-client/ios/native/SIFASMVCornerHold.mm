// Adjustable upper-right corner hold for the unchanged SIFASFeatures.dylib.
//
// SIFASFeatures.dylib has no source in this repository. Its "Client settings"
// shortcut, read from the pinned binary (LC_UUID 4C4C4462-5555-3144-A110-
// CB94F1BA04B0, __TEXT,__text at 0x4000, 0xb360 bytes):
//  - -[SIFASFeatures poll:] (0x4024, an NSTimer every 0.5 s) creates one
//    UILongPressGestureRecognizer (target self, action showSettingsShortcut:,
//    delegate self) and calls setMinimumPressDuration: with the immediate 2.0
//    (fmov d0,#2.0 at 0x4140). Only that first poll sets the duration; later
//    polls just move the recognizer to the current root view.
//  - gestureRecognizer:shouldReceiveTouch: (0x51ec) and
//    gestureRecognizerShouldBegin: (0x5590) test the same conditions: that
//    recognizer, the settings button hidden (SIFASShowSettingsButton), the
//    recognizer on the active window's root view, nothing presented there, and
//    the location inside the static C function _settingsShortcutContains
//    (0x533c; the rectangle is described in SIFASMVCornerHold.hpp).
//    -showSettingsShortcut: re-checks gestureRecognizerShouldBegin: on Began.
//  - The menu hint passes the same 2.0 to "%.0f seconds".
// Nothing here writes SIFASFeatures memory. The two delegate methods are
// replaced through the Objective-C runtime, and only when the loaded image's
// __text is byte-identical to the pinned file and both methods still point at
// its code. -[SIFASFeatures poll:] stays untouched; the FOV adapter pins it.
#import "SIFASMVCornerHold.h"
#if defined(SIFAS_STANDALONE)
#import "SIFASMVStandaloneAdapter.h"
#import <CoreFoundation/CoreFoundation.h>
#import <objc/runtime.h>
#include "SIFASMVCornerHold.hpp"
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>

namespace {
namespace rules = elichika::corner;

constexpr uint8_t featureUUID[] = {0x4c, 0x4c, 0x44, 0x62, 0x55, 0x55, 0x31, 0x44,
                                   0xa1, 0x10, 0xcb, 0x94, 0xf1, 0xba, 0x04, 0xb0};
constexpr uintptr_t featureTextAddress = 0x4000, featureTextSize = 0xb360;
// FNV-1a 64 of that __text (its SHA-256 is 3ffff929…7ae04b).
constexpr uint64_t featureTextFNV1a = 0x4a17cfa051377179ULL;
constexpr uintptr_t shouldReceiveTouchCode = 0x51ec, shouldBeginCode = 0x5590;

// A missing, non-numeric or unlisted value keeps the original behaviour.
NSString *const pointsKey = @"SIFASCornerHoldPoints";
NSString *const millisecondsKey = @"SIFASCornerHoldMilliseconds";

using ShouldReceive = BOOL (*)(id, SEL, UIGestureRecognizer *, UITouch *);
using ShouldBegin = BOOL (*)(id, SEL, UIGestureRecognizer *);
ShouldReceive originalShouldReceive;
ShouldBegin originalShouldBegin;
const char *installFailure = "corner.not-installed";

template <size_t count>
long savedChoice(NSString *key, const long (&choices)[count]) {
    id value = [NSUserDefaults.standardUserDefaults objectForKey:key];
    if (![value isKindOfClass:NSNumber.class] ||
        CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID()) return 0;
    return rules::validChoice([value doubleValue], choices);
}
// 0 means the original 90 x 44 pt area.
long savedPoints() { return savedChoice(pointsKey, rules::pointChoices); }
long savedMilliseconds() {
    const long value = savedChoice(millisecondsKey, rules::millisecondChoices);
    return value ? value : rules::originalMilliseconds;
}
void storeChoice(NSString *key, long value, long defaultValue) {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    if (value == defaultValue) [defaults removeObjectForKey:key];
    else [defaults setInteger:value forKey:key];
}

rules::Rect bounds(UIView *view) {
    const CGRect value = view.bounds;
    return {value.origin.x, value.origin.y, value.size.width, value.size.height};
}
rules::Insets safeArea(UIView *view) {
    const UIEdgeInsets value = view.safeAreaInsets;
    return {value.top, value.right};
}
CGPoint originalAreaCentre(UIView *view) {
    if (!view) return CGPointMake(NAN, NAN);
    const rules::Point centre = rules::originalAreaCentre(bounds(view), safeArea(view));
    return CGPointMake(centre.x, centre.y);
}
bool insideCorner(UIView *view, CGPoint point, long edge) {
    return view && rules::insideCorner(bounds(view), safeArea(view), {point.x, point.y}, double(edge));
}
}

// Stands in for the touch when the pinned filter is asked about everything
// except geometry. -locationInView: is the only message that code sends to
// its touch (0x5318); anything else goes to the real touch.
@interface SIFASMVCornerProbeTouch : NSObject
- (instancetype)initWithTouch:(UITouch *)touch;
@end
@implementation SIFASMVCornerProbeTouch {
    UITouch *_touch;
}
- (instancetype)initWithTouch:(UITouch *)touch {
    if ((self = [super init])) _touch = touch;
    return self;
}
- (CGPoint)locationInView:(UIView *)view {
    return originalAreaCentre(view);
}
- (id)forwardingTargetForSelector:(SEL)selector {
    (void)selector;
    return _touch;
}
@end

namespace {
// The recognizer starts its timer after the delegate accepts the touch, so a
// duration set here applies to that touch.
void applyDuration(id features, UIGestureRecognizer *recognizer) {
    if (![recognizer isKindOfClass:UILongPressGestureRecognizer.class] || recognizer.delegate != features) return;
    UILongPressGestureRecognizer *press = (UILongPressGestureRecognizer *)recognizer;
    const NSTimeInterval wanted = savedMilliseconds() / 1000.0;
    if (press.minimumPressDuration != wanted) press.minimumPressDuration = wanted;
}

// The pinned filter's answer at a point inside its own area: every condition
// except the location stays SIFASFeatures' own.
BOOL originalConditions(id features, UIGestureRecognizer *recognizer, UITouch *touch) {
    SIFASMVCornerProbeTouch *probe = [[SIFASMVCornerProbeTouch alloc] initWithTouch:touch];
    return originalShouldReceive(features, @selector(gestureRecognizer:shouldReceiveTouch:), recognizer,
                                 (UITouch *)probe);
}

BOOL cornerShouldReceive(id features, SEL selector, UIGestureRecognizer *recognizer, UITouch *touch) {
    applyDuration(features, recognizer);
    const long edge = savedPoints();
    if (!edge || !touch) return originalShouldReceive(features, selector, recognizer, touch);
    if (!originalConditions(features, recognizer, touch)) return NO;
    UIView *view = recognizer.view;
    return insideCorner(view, [touch locationInView:view], edge);
}

BOOL cornerShouldBegin(id features, SEL selector, UIGestureRecognizer *recognizer) {
    const long edge = savedPoints();
    if (!edge) return originalShouldBegin(features, selector, recognizer);
    if (!originalConditions(features, recognizer, nil)) return NO;
    UIView *view = recognizer.view;
    return insideCorner(view, [recognizer locationInView:view], edge);
}

bool hasFeatureUUID(const mach_header_64 *header) {
    if (!header || header->magic != MH_MAGIC_64 || header->cputype != CPU_TYPE_ARM64 ||
        header->filetype != MH_DYLIB || header->ncmds > 128 ||
        header->sizeofcmds > 8192 - sizeof(*header)) return false;
    const uint8_t *cursor = reinterpret_cast<const uint8_t *>(header + 1);
    const uint8_t *end = cursor + header->sizeofcmds;
    bool matched = false;
    for (uint32_t index = 0; index < header->ncmds; ++index) {
        if (size_t(end - cursor) < sizeof(load_command)) return false;
        const auto *command = reinterpret_cast<const load_command *>(cursor);
        if (command->cmdsize < sizeof(*command) || command->cmdsize % 8 ||
            command->cmdsize > size_t(end - cursor)) return false;
        if (command->cmd == LC_UUID) {
            if (matched || command->cmdsize != sizeof(uuid_command) ||
                std::memcmp(reinterpret_cast<const uuid_command *>(command)->uuid, featureUUID, 16)) return false;
            matched = true;
        }
        cursor += command->cmdsize;
    }
    return cursor == end && matched;
}

uint64_t fnv1a(const uint8_t *bytes, size_t size) {
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (size_t index = 0; index < size; ++index) {
        hash ^= bytes[index];
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

const char *checkFeatures(Method receive, Method begin) {
    if (!receive || !begin) return "corner.feature-methods";
    const uint32_t images = _dyld_image_count();
    for (uint32_t index = 1; index < images; ++index) {
        const auto *header = reinterpret_cast<const mach_header_64 *>(_dyld_get_image_header(index));
        if (!hasFeatureUUID(header)) continue;
        const auto *text = getsectbynamefromheader_64(header, "__TEXT", "__text");
        const uintptr_t slide = _dyld_get_image_vmaddr_slide(index);
        if (!text || text->addr != featureTextAddress || text->size != featureTextSize ||
            fnv1a(reinterpret_cast<const uint8_t *>(slide + text->addr), text->size) != featureTextFNV1a)
            return "corner.feature-code";
        if (reinterpret_cast<uintptr_t>(method_getImplementation(receive)) != slide + shouldReceiveTouchCode ||
            reinterpret_cast<uintptr_t>(method_getImplementation(begin)) != slide + shouldBeginCode)
            return "corner.feature-hooked";
        return nullptr;
    }
    return "corner.feature-library";
}

void installCornerHold() {
    if (originalShouldReceive) return;
    Class features = objc_getClass("SIFASFeatures");
    if (!features) {
        installFailure = "corner.feature-class";
        return;
    }
    Method receive = class_getInstanceMethod(features, @selector(gestureRecognizer:shouldReceiveTouch:));
    Method begin = class_getInstanceMethod(features, @selector(gestureRecognizerShouldBegin:));
    if (const char *failure = checkFeatures(receive, begin)) {
        installFailure = failure;
        return;
    }
    // Both originals are known before either replacement can run.
    originalShouldBegin = reinterpret_cast<ShouldBegin>(method_getImplementation(begin));
    originalShouldReceive = reinterpret_cast<ShouldReceive>(method_getImplementation(receive));
    method_setImplementation(receive, reinterpret_cast<IMP>(&cornerShouldReceive));
    method_setImplementation(begin, reinterpret_cast<IMP>(&cornerShouldBegin));
    installFailure = nullptr;
}

// The recognizer already on screen, so a new duration applies without waiting
// for the next touch.
void applySavedDurationNow() {
    Class features = objc_getClass("SIFASFeatures");
    if (!features || !originalShouldReceive) return;
    const NSTimeInterval wanted = savedMilliseconds() / 1000.0;
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        for (UIGestureRecognizer *recognizer in window.rootViewController.viewIfLoaded.gestureRecognizers)
            if ([recognizer isKindOfClass:UILongPressGestureRecognizer.class] &&
                [recognizer.delegate isKindOfClass:features])
                ((UILongPressGestureRecognizer *)recognizer).minimumPressDuration = wanted;
}

NSString *text(NSString *english, NSString *korean, NSString *japanese) {
    NSString *language = SIFASMVStandaloneConfiguration()[@"language"];
    return [language hasPrefix:@"ko"] ? korean : ([language hasPrefix:@"ja"] ? japanese : english);
}
NSString *durationLabel(long milliseconds) {
    return [@(rules::seconds(milliseconds).c_str()) stringByAppendingString:text(@" s", @"초", @"秒")];
}
NSString *areaLabel(long points) {
    return points ? [NSString stringWithFormat:@"%ld × %ld pt", points, points]
                  : [NSString stringWithFormat:@"%ld × %ld pt", long(rules::originalWidth), long(rules::originalHeight)];
}
NSString *choiceTitle(NSString *label, bool selected, bool fallback) {
    NSString *title = selected ? [@"✓ " stringByAppendingString:label] : label;
    return fallback ? [title stringByAppendingString:text(@" (default)", @" (기본값)", @"（標準）")] : title;
}

using Presenter = UIViewController * _Nullable (^)(void);
void present(UIAlertController *alert, Presenter presenter, NSUInteger attempt) {
    dispatch_async(dispatch_get_main_queue(), ^{
        UIViewController *base = presenter ? presenter() : nil;
        if (!base) base = SIFASMVStandalonePresenter();
        UIViewController *top = base;
        while (top.presentedViewController && !top.presentedViewController.isBeingDismissed)
            top = top.presentedViewController;
        if (top.viewIfLoaded.window && !top.presentedViewController) {
            [top presentViewController:alert animated:YES completion:nil];
        } else if (attempt < 10) {
            // The menu that opened this one may still be dismissing.
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, int64_t(100 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
                present(alert, presenter, attempt + 1);
            });
        }
    });
}

UIAlertController *alert(NSString *title, NSString *message) {
    return [UIAlertController alertControllerWithTitle:title message:message preferredStyle:UIAlertControllerStyleAlert];
}
void addCancel(UIAlertController *menu, NSString *title, void (^handler)(void)) {
    [menu addAction:[UIAlertAction actionWithTitle:title style:UIAlertActionStyleCancel handler:^(__unused UIAlertAction *action) {
        if (handler) handler();
    }]];
}

void showCornerHold(Presenter presenter);

void showAreaChoices(Presenter presenter) {
    UIAlertController *menu = alert(text(@"Corner size", @"오른쪽 위 길게 누르기 영역 크기", @"右上の長押し範囲の大きさ"),
        text(@"The default is the original area where the settings button appears. Square sizes are measured from the upper-right corner.",
             @"기본값은 설정 버튼이 표시되는 원래 영역입니다. 정사각형 크기는 오른쪽 위 모서리부터 잽니다.",
             @"標準は設定ボタンが表示される元の範囲です。正方形の大きさは右上の角から測ります。"));
    const long current = savedPoints();
    NSMutableArray<NSNumber *> *values = [NSMutableArray arrayWithObject:@0];
    for (long choice : rules::pointChoices) [values addObject:@(choice)];
    for (NSNumber *value in values) {
        const long points = value.longValue;
        [menu addAction:[UIAlertAction actionWithTitle:choiceTitle(areaLabel(points), points == current, points == 0)
                                                 style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
            storeChoice(pointsKey, points, 0);
            showCornerHold(presenter);
        }]];
    }
    addCancel(menu, text(@"Cancel", @"취소", @"キャンセル"), ^{ showCornerHold(presenter); });
    present(menu, presenter, 0);
}

void showDurationChoices(Presenter presenter) {
    UIAlertController *menu = alert(text(@"Hold time", @"길게 누르는 시간", @"長押し時間"), nil);
    const long current = savedMilliseconds();
    for (long choice : rules::millisecondChoices) {
        const long milliseconds = choice;
        [menu addAction:[UIAlertAction actionWithTitle:choiceTitle(durationLabel(milliseconds), milliseconds == current,
                                                                   milliseconds == rules::originalMilliseconds)
                                                 style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
            storeChoice(millisecondsKey, milliseconds, rules::originalMilliseconds);
            applySavedDurationNow();
            showCornerHold(presenter);
        }]];
    }
    addCancel(menu, text(@"Cancel", @"취소", @"キャンセル"), ^{ showCornerHold(presenter); });
    present(menu, presenter, 0);
}

void showCornerHold(Presenter presenter) {
    NSString *title = text(@"Corner hold", @"오른쪽 위 길게 누르기", @"右上の長押し");
    if (!originalShouldReceive) {
        NSString *check = @(installFailure ?: "corner.not-installed");
        UIAlertController *menu = alert(title, [NSString stringWithFormat:text(
            @"This build cannot change the corner hold because the loaded SIFASFeatures.dylib is not the verified version (%@). The hold stays 2 seconds on the original area.",
            @"불러온 SIFASFeatures.dylib가 확인된 버전이 아니어서 이 빌드에서는 길게 누르기를 바꿀 수 없습니다(%@). 원래 영역에서 2초 그대로 동작합니다.",
            @"読み込まれたSIFASFeatures.dylibが確認済みの版ではないため、このビルドでは長押しを変更できません（%@）。元の範囲で2秒のまま動作します。"), check]);
        addCancel(menu, text(@"OK", @"확인", @"OK"), nil);
        present(menu, presenter, 0);
        return;
    }
    UIAlertController *menu = alert(title, [NSString stringWithFormat:text(
        @"While the settings button is hidden, hold the upper-right corner of the game screen to open Client settings.\n\nArea: %@\nHold time: %@",
        @"설정 버튼을 숨긴 동안 게임 화면 오른쪽 위를 길게 누르면 Client settings가 열립니다.\n\n영역: %@\n누르는 시간: %@",
        @"設定ボタンを非表示にしている間、ゲーム画面の右上を長押しするとClient settingsが開きます。\n\n範囲: %@\n長押し時間: %@"),
        areaLabel(savedPoints()), durationLabel(savedMilliseconds())]);
    [menu addAction:[UIAlertAction actionWithTitle:text(@"Area size…", @"영역 크기…", @"範囲の大きさ…")
                                             style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        showAreaChoices(presenter);
    }]];
    [menu addAction:[UIAlertAction actionWithTitle:text(@"Hold time…", @"누르는 시간…", @"長押し時間…")
                                             style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        showDurationChoices(presenter);
    }]];
    [menu addAction:[UIAlertAction actionWithTitle:text(@"Restore defaults", @"기본값으로 되돌리기", @"初期設定に戻す")
                                             style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        storeChoice(pointsKey, 0, 0);
        storeChoice(millisecondsKey, rules::originalMilliseconds, rules::originalMilliseconds);
        applySavedDurationNow();
        showCornerHold(presenter);
    }]];
    addCancel(menu, text(@"Done", @"완료", @"完了"), nil);
    present(menu, presenter, 0);
}
}

@interface SIFASMVCornerHold : NSObject
@end
@implementation SIFASMVCornerHold
+ (BOOL)isCornerHoldSettingsMenu:(NSString *)message {
    return rules::isSettingsMenu(message.UTF8String);
}
// SIFASFeatures' hint is English only, so the replacement stays English.
+ (NSString *)cornerHoldSettingsMessage:(NSString *)message {
    NSString *fixed = @(rules::hintPhrase(0, rules::originalMilliseconds).c_str());
    const NSRange range = message && originalShouldReceive ? [message rangeOfString:fixed] : NSMakeRange(NSNotFound, 0);
    if (range.location == NSNotFound) return message;
    NSString *phrase = @(rules::hintPhrase(savedPoints(), savedMilliseconds()).c_str());
    return [message stringByReplacingCharactersInRange:range withString:phrase];
}
+ (UIAlertAction *)cornerHoldActionWithPresenter:(UIViewController * _Nullable (^)(void))presenter {
    Presenter owner = [presenter copy];
    return [UIAlertAction actionWithTitle:text(@"Corner hold…", @"오른쪽 위 길게 누르기…", @"右上の長押し…")
                                    style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        showCornerHold(owner);
    }];
}
@end

__attribute__((constructor)) static void installStandaloneCornerHold() {
    @autoreleasepool {
        installCornerHold();
        // SIFASFeatures loads first; one later attempt covers an unexpected order.
        if (!originalShouldReceive) dispatch_async(dispatch_get_main_queue(), ^{
            installCornerHold();
            if (!originalShouldReceive) NSLog(@"SIFASMVCornerHold: corner hold settings unavailable (%s)", installFailure);
        });
    }
}
#endif
