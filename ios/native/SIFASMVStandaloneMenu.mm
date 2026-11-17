#import "SIFASMVExportSession.h"
#import <objc/runtime.h>

// Extend the existing standalone settings menu. Its FOV, connection and
// orientation actions and long-press recognizer remain the original ones.
namespace {
using Factory = UIAlertController *(*)(id,SEL,NSString *,NSString *,UIAlertControllerStyle);
Factory originalFactory;
UIAlertController *exportMenu(id type, SEL selector, NSString *title, NSString *message, UIAlertControllerStyle style) {
    if ([title isEqualToString:@"Client settings"]) {
        NSString *version=[NSBundle.mainBundle objectForInfoDictionaryKey:@"SIFASBuildVersion"] ?: @"";
        message=[message stringByAppendingFormat:@"\n\nBuild %@ · MP4 export supports paused MVs.",version];
    }
    UIAlertController *menu=originalFactory(type,selector,title,message,style);
    if ([title isEqualToString:@"Client settings"] && style==UIAlertControllerStyleAlert) {
        __weak UIAlertController *weakMenu=menu;
        [menu addAction:[UIAlertAction actionWithTitle:@"MP4 export" style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
            UIViewController *presenter=weakMenu.presentingViewController;
            if (!presenter) return;
            [presenter dismissViewControllerAnimated:YES completion:^{ ElichikaPresentMVExportMenu(presenter); }];
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
