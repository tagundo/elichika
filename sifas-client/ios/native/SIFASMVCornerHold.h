#pragma once
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN
/* Corner-hold settings for the unchanged SIFASFeatures.dylib "Client settings"
 * menu. SIFASMVCornerHold.mm implements these as class methods of the class
 * SIFASMVCornerHold. Callers look the class up at run time, so a target that
 * does not compile that file (for example the UIKit menu probe) links and
 * simply gets nil. */
@protocol SIFASMVCornerHoldMenu
/* YES only for the real settings menu. SIFASFeatures' one-off status and error
 * alerts use the same "Client settings" title and alert style, but their text
 * never describes the corner hold. */
- (BOOL)isCornerHoldSettingsMenu:(nullable NSString *)message;
/* The menu message with SIFASFeatures' fixed "2 seconds" hint replaced by the
 * saved area and hold time; the message unchanged when nothing applies. */
- (NSString *)cornerHoldSettingsMessage:(NSString *)message;
/* "Corner hold…" action that opens the area/time chooser. presenter is asked
 * for the game view controller when the action runs. */
- (UIAlertAction *)cornerHoldActionWithPresenter:(UIViewController * _Nullable (^)(void))presenter;
@end

static inline id<SIFASMVCornerHoldMenu> _Nullable SIFASMVCornerHoldMenuProvider(void) {
    return (id<SIFASMVCornerHoldMenu>)(id)NSClassFromString(@"SIFASMVCornerHold");
}
NS_ASSUME_NONNULL_END
