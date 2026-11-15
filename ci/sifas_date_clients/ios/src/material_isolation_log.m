#import "AppleABI.h"
extern void NSLog(NSString *format, ...);

/* Plain C linkage: the C++ binder never includes Objective-C ABI declarations. */
void sifas_material_log(const char *text) {
    NSLog(@"[SIFAS Material] %s", text ? text : "(empty diagnostic)");
}
