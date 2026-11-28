#import "SIFASMVExportSession.h"
#import "SIFASMVStandaloneAdapter.h"
#import "SIFASMVCornerHold.h"
#import <objc/runtime.h>

// Extend the original settings menu without replacing its FOV/connection
// actions or its long-press recognizer. SIFASMVCornerHold.mm adjusts that
// recognizer's area and duration; it is looked up at run time, so builds
// without it (the UIKit menu probe) keep the menu unchanged.
namespace {
using Factory = UIAlertController *(*)(id,SEL,NSString *,NSString *,UIAlertControllerStyle);
Factory originalFactory;
UIAlertController *exportMenu(id type, SEL selector, NSString *title, NSString *message, UIAlertControllerStyle style) {
    // SIFASFeatures' _message() status and error alerts share the menu's title
    // and style. Only the real menu says how to reopen it with the corner hold,
    // so only that one gets the MP4 export and corner-hold actions.
    const BOOL settings=[title isEqualToString:@"Client settings"] && style==UIAlertControllerStyleAlert &&
        [message containsString:@"hold the upper-right corner"];
    // Resolve the game controller before UIKit starts dismissing its alert.
    // An action handler can run after alert.presentingViewController is nil.
    __weak UIViewController *gamePresenter=settings ? SIFASMVStandalonePresenter() : nil;
    id<SIFASMVCornerHoldMenu> cornerHold=settings ? SIFASMVCornerHoldMenuProvider() : nil;
    if (![cornerHold isCornerHoldSettingsMenu:message]) cornerHold=nil;
    if (settings) {
        if (cornerHold && message) message=[cornerHold cornerHoldSettingsMessage:message];
        NSString *version=[NSBundle.mainBundle objectForInfoDictionaryKey:@"SIFASBuildVersion"] ?: @"";
        message=[message stringByAppendingFormat:@"\n\nBuild %@ · MP4 export supports paused MVs.",version];
    }
    UIAlertController *menu=originalFactory(type,selector,title,message,style);
    if (settings) {
        [menu addAction:[UIAlertAction actionWithTitle:@"MP4 export" style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
            UIViewController *presenter=gamePresenter ?: SIFASMVStandalonePresenter();
            // The export form is a UIView in the game window. UIAlertController
            // dismisses itself; a second dismiss call can omit its completion.
            ElichikaPresentMVExportMenu(presenter);
        }]];
        if (cornerHold) [menu addAction:[cornerHold cornerHoldActionWithPresenter:^UIViewController *{
            return gamePresenter ?: SIFASMVStandalonePresenter();
        }]];
    }
    return menu;
}
}
__attribute__((constructor)) static void installStandaloneExportMenu() {
    @autoreleasepool {
        Method factory=class_getClassMethod(UIAlertController.class,@selector(alertControllerWithTitle:message:preferredStyle:));
        if (factory) originalFactory=reinterpret_cast<Factory>(method_setImplementation(factory,reinterpret_cast<IMP>(&exportMenu)));
    }
}
