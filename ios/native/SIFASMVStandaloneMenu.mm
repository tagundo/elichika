#import "SIFASMVExportSession.h"
#import "SIFASMVStandaloneAdapter.h"
#import <objc/runtime.h>

// Extend the original settings menu without replacing its FOV/connection
// actions or its long-press recognizer.
namespace {
using Factory = UIAlertController *(*)(id,SEL,NSString *,NSString *,UIAlertControllerStyle);
Factory originalFactory;
UIAlertController *exportMenu(id type, SEL selector, NSString *title, NSString *message, UIAlertControllerStyle style) {
    const BOOL settings=[title isEqualToString:@"Client settings"] && style==UIAlertControllerStyleAlert;
    // Resolve the game controller before UIKit starts dismissing its alert.
    // An action handler can run after alert.presentingViewController is nil.
    __weak UIViewController *gamePresenter=settings ? SIFASMVStandalonePresenter() : nil;
    if (settings) {
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
