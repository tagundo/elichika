#import "AppleABI.h"
#include "InputValidation.h"
#include "SettingsOverlay.h"

/* Nothing here writes executable memory, intercepts network traffic, or requests
 * extra entitlements. Offline, reviewed patches read this dedicated RW section. */
typedef struct {
    float minimum, maximum, fadeSeconds, holdSeconds;
    unsigned int fastIntro, orientation, magic, version;
} FeatureConfig;
_Static_assert(sizeof(FeatureConfig) == 32, "Configuration ABI must match offline patcher");
_Static_assert(__builtin_offsetof(FeatureConfig, fastIntro) == 16, "Intro flag offset must match stubs");
typedef struct { unsigned int magic, cpu, subtype, type, ncmds, cmdbytes, flags, reserved; } MachHeader;
typedef struct { unsigned int command, size; } LoadCommand;
typedef struct {
    unsigned int command, size; char name[16];
    unsigned long address, memorySize, offset, fileSize;
    int maximumProtection, initialProtection; unsigned int sections, flags;
} Segment;
typedef struct {
    char name[16], segment[16]; unsigned long address, size;
    unsigned int offset, alignment, relocationOffset, relocations, flags, r1, r2, r3;
} Section;
static FeatureConfig *configuration;
static unsigned int orientationMode;
static const unsigned int CONFIG_MAGIC = 0x53494641;
static NSString *const MIN_KEY = @"SIFASFOVMinimum";
static NSString *const MAX_KEY = @"SIFASFOVMaximum";
static NSString *const INTRO_KEY = @"SIFASFastIntro";
static NSString *const ORIENTATION_KEY = @"SIFASOrientation";
static NSString *const SETTINGS_BUTTON_KEY = @"SIFASShowSettingsButton";
static const double SETTINGS_HOLD_SECONDS = 2.0;
static NSString *const SERVER_KEY = @"ServerEndpoint";
static NSString *const PUBLIC_KEY = @"RSAKey";
static NSString *clientBuildLabel(void) {
    NSBundle *bundle = [NSBundle mainBundle];
    id value = [bundle objectForInfoDictionaryKey:@"SIFASBuildVersion"];
    if (![value isKindOfClass:[NSString class]] || ![(NSString *)value length] || [(NSString *)value length] > 64) {
        value = [bundle objectForInfoDictionaryKey:@"CFBundleVersion"];
    }
    return [value isKindOfClass:[NSString class]] && [(NSString *)value length] && [(NSString *)value length] <= 64 ? value : @"Unknown";
}
static NSString *packagedServerURL;
static NSString *launchServerURL;
static NSUInteger serverCapacity;
static NSUInteger publicKeyCapacity;
static BOOL rotationInFlight;
static BOOL orientationPending;

static NSString *trimServer(NSString *value) {
    return [value stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"/ "]];
}
static NSString *metadataLiteral(NSFileHandle *file, const unsigned int *header, unsigned int index) {
    if ((unsigned long)index*8+8 > header[3]) return 0;
    [file seekToFileOffset:header[2]+(unsigned long)index*8];
    NSData *entry = [file readDataOfLength:8];
    if ([entry length] != 8) return 0;
    const unsigned int *pair = [entry bytes];
    unsigned int length = pair[0], offset = pair[1];
    if (length > 4096 || (unsigned long)offset+length > header[5]) return 0;
    [file seekToFileOffset:(unsigned long)header[4]+offset];
    NSData *data = [file readDataOfLength:length];
    return [data length] == length ? [[NSString alloc] initWithData:data encoding:4] : 0;
}
static void loadConnectionMetadata(void) {
    NSBundle *bundle = [NSBundle mainBundle];
    BOOL global = [[bundle bundleIdentifier] hasSuffix:@".global"];
    NSString *path = [[bundle bundlePath] stringByAppendingPathComponent:@"Data/Managed/Metadata/global-metadata.dat"];
    NSFileHandle *file = [NSFileHandle fileHandleForReadingAtPath:path];
    if (!file) return;
    @try {
        NSData *data = [file readDataOfLength:24];
        if ([data length] == 24) {
            const unsigned int *rawHeader = [data bytes];
            unsigned int header[6];
            for (unsigned int i = 0; i < 6; i++) header[i] = rawHeader[i];
            if (header[0] == 0xfab11baf && header[1] == 24 && header[2] < 1048576 && header[3] < 1048576) {
                NSString *url = metadataLiteral(file, header, global ? 11910 : 11469);
                NSString *key = metadataLiteral(file, header, global ? 3621 : 3615);
                if ([url hasPrefix:@"http://"] || [url hasPrefix:@"https://"]) {
                    packagedServerURL = url; serverCapacity = [url length];
                }
                NSString *xml = [key stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@" \t\r\n"]];
                // GL's initialized key reserves trailing spaces for a longer
                // replacement. Validate the XML without losing that capacity.
                if ([xml hasPrefix:@"<RSAKeyValue>"] && [xml hasSuffix:@"</RSAKeyValue>"]) publicKeyCapacity = [key length];
            }
        }
    } @catch (id error) { (void)error; }
    [file closeFile];
    NSString *saved = [[NSUserDefaults standardUserDefaults] stringForKey:SERVER_KEY];
    launchServerURL = saved ? trimServer(saved) : packagedServerURL;
    // The existing routing library truncates to the initialized string capacity.
    if (serverCapacity && [launchServerURL length] > serverCapacity) launchServerURL = [launchServerURL substringToIndex:serverCapacity];
}

static UIWindow *activeWindow(void) {
    UIApplication *app = [UIApplication sharedApplication];
    NSArray *scenes = [[app connectedScenes] allObjects];
    UIWindow *fallback = [app keyWindow];
    for (NSUInteger i = 0; i < [scenes count]; i++) {
        id scene = [scenes objectAtIndex:i];
        if (![scene respondsToSelector:sel_registerName("windows")]) continue;
        NSArray *windows = [(UIWindowScene *)scene windows];
        for (NSUInteger j = 0; j < [windows count]; j++) {
            UIWindow *window = [windows objectAtIndex:j];
            if ([window isKeyWindow] && [window rootViewController]) return window;
            if (!fallback && [(UIWindowScene *)scene activationState] == 0 && [window rootViewController]) fallback = window;
        }
    }
    return fallback;
}
static BOOL runningOnMac(void) {
    NSProcessInfo *process = [NSProcessInfo processInfo];
    return ([process respondsToSelector:sel_registerName("isiOSAppOnMac")] && [process isiOSAppOnMac]) ||
           ([process respondsToSelector:sel_registerName("isMacCatalystApp")] && [process isMacCatalystApp]);
}

@interface SIFASRotationController : UIViewController
@end
@implementation SIFASRotationController
- (NSUInteger)supportedInterfaceOrientations { return 26; }
- (NSInteger)preferredInterfaceOrientationForPresentation { return orientationMode == 1 ? 1 : 4; }
- (BOOL)shouldAutorotate { return 1; }
@end

static BOOL equalName(const char a[16], const char *b) {
    for (unsigned int i = 0; i < 16; i++) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 1;
}

static FeatureConfig *findConfiguration(void) {
    const MachHeader *header = _dyld_get_image_header(0);
    if (!header || header->magic != 0xfeedfacf || header->ncmds > 128 || header->cmdbytes > 65536) return 0;
    const char *cursor = (const char *)(header + 1);
    const char *end = cursor + header->cmdbytes;
    for (unsigned int i = 0; i < header->ncmds; i++) {
        const LoadCommand *command = (const LoadCommand *)cursor;
        if (cursor + sizeof(*command) > end || command->size < 8 || cursor + command->size > end) return 0;
        if (command->command == 0x19 && command->size >= sizeof(Segment)) {
            const Segment *segment = (const Segment *)cursor;
            if (segment->initialProtection == 3 && segment->sections <= 128 &&
                sizeof(Segment) + segment->sections * sizeof(Section) <= command->size) {
                const Section *sections = (const Section *)(segment + 1);
                for (unsigned int j = 0; j < segment->sections; j++) {
                    if (equalName(sections[j].name, "__sifas_cfg") && sections[j].size == sizeof(FeatureConfig)) {
                        FeatureConfig *candidate = (FeatureConfig *)(sections[j].address + _dyld_get_image_vmaddr_slide(0));
                        if (candidate->magic == CONFIG_MAGIC && candidate->version == 1) return candidate;
                    }
                }
            }
        }
        cursor += command->size;
    }
    return 0;
}

static NSUInteger currentMask(void) {
    if (orientationMode == 1) return 2;   /* portrait */
    if (orientationMode == 2) return 24;  /* both landscape directions */
    return 26;                          /* device auto: portrait + landscape */
}
static NSUInteger supportedOrientations(id object, SEL selector) {
    (void)object; (void)selector; return currentMask();
}
static NSUInteger appSupportedOrientations(id object, SEL selector, id app, id window) {
    (void)object; (void)selector; (void)app; (void)window; return currentMask();
}
static BOOL shouldAutorotate(id object, SEL selector) {
    (void)object; (void)selector; return 1;
}

static void installOrientationMethods(void) {
    const char *names[] = {"UnityViewControllerBase", "UnityDefaultViewController", "UnityPortraitOnlyViewController",
                          "UnityPortraitUpsideDownOnlyViewController", "UnityLandscapeLeftOnlyViewController", "UnityLandscapeRightOnlyViewController"};
    for (unsigned int i = 0; i < sizeof(names)/sizeof(names[0]); i++) {
        Class klass = objc_getClass(names[i]);
        if (!klass) continue;
        class_replaceMethod(klass, sel_registerName("supportedInterfaceOrientations"), (IMP)supportedOrientations, "Q@:");
        class_replaceMethod(klass, sel_registerName("shouldAutorotate"), (IMP)shouldAutorotate, "B@:");
    }
    Class app = objc_getClass("UnityAppController");
    if (app) class_replaceMethod(app, sel_registerName("application:supportedInterfaceOrientationsForWindow:"),
                                (IMP)appSupportedOrientations, "Q@:@@");
}

static UIViewController *presenter(void) {
    UIViewController *controller = [activeWindow() rootViewController];
    while ([controller presentedViewController]) controller = [controller presentedViewController];
    return [controller isBeingDismissed] ? 0 : controller;
}
static BOOL applyOrientation(void) {
    UIWindow *window = activeWindow();
    UIViewController *root = [window rootViewController];
    if (!root || ![[root view] window] || [root isBeingDismissed] || [root isBeingPresented] || [root transitionCoordinator]) return 0;
    BOOL mac = runningOnMac();
    if (mac && orientationMode != 0 && ([root presentedViewController] || rotationInFlight)) return 0;
    if ([root respondsToSelector:sel_registerName("setNeedsUpdateOfSupportedInterfaceOrientations")])
        [root setNeedsUpdateOfSupportedInterfaceOrientations];
    Class geometry = objc_getClass("UIWindowSceneGeometryPreferencesIOS");
    UIWindowScene *scene = [window windowScene];
    if (!mac && geometry && [scene respondsToSelector:sel_registerName("requestGeometryUpdateWithPreferences:errorHandler:")]) {
        id preferences = [[(id)geometry alloc] initWithInterfaceOrientations:currentMask()];
        [scene requestGeometryUpdateWithPreferences:preferences errorHandler:^(id error) { (void)error; }];
    }
    [UIViewController attemptRotationToDeviceOrientation];
    // Catalyst can ignore iOS geometry requests. Public fullscreen presentation
    // also gives iOS-on-Mac a preferred orientation, as PlayTools itself does.
    if (mac && orientationMode != 0) {
        rotationInFlight = 1;
        SIFASRotationController *rotation = [[SIFASRotationController alloc] initWithNibName:0 bundle:0];
        [rotation setModalPresentationStyle:0];
        [root presentViewController:rotation animated:0 completion:^{
            [rotation dismissViewControllerAnimated:0 completion:^{ rotationInFlight = 0; }];
        }];
    }
    return 1;
}

static void readPreferences(void) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    double minimum = [defaults objectForKey:MIN_KEY] ? [defaults doubleForKey:MIN_KEY] : 0.75;
    double maximum = [defaults objectForKey:MAX_KEY] ? [defaults doubleForKey:MAX_KEY] : 1.0;
    if (!__builtin_isfinite(minimum) || minimum < 0.5 || minimum > 2.0) minimum = 0.75;
    if (!__builtin_isfinite(maximum) || maximum < 0.5 || maximum > 2.0) maximum = 1.0;
    if (minimum > maximum) { minimum = 0.75; maximum = 1.0; }
    NSInteger requested = [defaults integerForKey:ORIENTATION_KEY];
    unsigned int nextOrientation = requested >= 0 && requested <= 2 ? (unsigned int)requested : 0;
    BOOL changedOrientation = nextOrientation != orientationMode;
    orientationMode = nextOrientation;
    if (configuration) {
        configuration->minimum = (float)minimum;
        configuration->maximum = (float)maximum;
        configuration->fadeSeconds = 0.125f;
        configuration->holdSeconds = 0.0f;
        configuration->fastIntro = [defaults boolForKey:INTRO_KEY] ? 1 : 0;
        configuration->orientation = orientationMode;
    }
    if (changedOrientation) orientationPending = 1;
    if (orientationPending && applyOrientation()) orientationPending = 0;
}

@interface SIFASFeatures : NSObject <UIGestureRecognizerDelegate>
- (void)poll:(id)timer;
- (void)showSettings;
- (void)showSettingsShortcut:(UILongPressGestureRecognizer *)recognizer;
- (void)showCamera;
- (void)showOrientation;
- (void)showConnection;
- (void)editServerURL;
- (void)editPublicKey;
@end

static SIFASFeatures *controller;
static UIButton *settingsButton;
static UILongPressGestureRecognizer *settingsShortcut;
static NSTimer *settingsTimer;
static BOOL settingsButtonVisible(void) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    return SIFASSettingsButtonVisible([defaults objectForKey:SETTINGS_BUTTON_KEY] != 0,
                                     [defaults boolForKey:SETTINGS_BUTTON_KEY]);
}
static BOOL settingsShortcutContains(UIView *view, CGPoint point) {
    if (!view) return 0;
    CGRect bounds = [view bounds];
    UIEdgeInsets insets = [view safeAreaInsets];
    SIFASSettingsShortcutRegion region = SIFASSettingsShortcutBounds(
        bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height,
        insets.top, insets.right);
    return SIFASSettingsShortcutContains(region, point.x, point.y);
}
static void writeDiagnostics(void) {
    if (![[NSUserDefaults standardUserDefaults] boolForKey:@"SIFASDiagnosticsEnabled"]) return;
    UIWindow *window = activeWindow();
    UIView *rootView = [[window rootViewController] view];
    CGRect bounds = [window bounds];
    NSDictionary *value = @{
        @"schema": [NSNumber numberWithUnsignedInteger:1],
        @"fov_minimum": [NSNumber numberWithDouble:configuration->minimum],
        @"fov_maximum": [NSNumber numberWithDouble:configuration->maximum],
        @"fast_intro": [NSNumber numberWithBool:configuration->fastIntro != 0],
        @"requested_orientation": [NSNumber numberWithUnsignedInteger:orientationMode],
        @"observed_interface_orientation": [NSNumber numberWithUnsignedInteger:(NSUInteger)[[window windowScene] interfaceOrientation]],
        @"window_width": [NSNumber numberWithDouble:bounds.size.width],
        @"window_height": [NSNumber numberWithDouble:bounds.size.height],
        @"settings_overlay_attached": [NSNumber numberWithBool:[settingsButton superview] != 0],
        @"settings_button_visible": [NSNumber numberWithBool:[settingsButton superview] != 0 && ![settingsButton isHidden]],
        @"settings_shortcut_attached": [NSNumber numberWithBool:settingsShortcut && rootView && [settingsShortcut view] == rootView],
        @"running_on_mac": [NSNumber numberWithBool:runningOnMac()],
        @"server_url_capacity_utf16": [NSNumber numberWithUnsignedInteger:serverCapacity],
        @"public_key_capacity_utf16": [NSNumber numberWithUnsignedInteger:publicKeyCapacity],
        @"server_override_present": [NSNumber numberWithBool:[[NSUserDefaults standardUserDefaults] stringForKey:SERVER_KEY] != 0],
        @"public_key_override_present": [NSNumber numberWithBool:[[NSUserDefaults standardUserDefaults] stringForKey:PUBLIC_KEY] != 0]
    };
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:1 error:0];
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/SIFASFeatures-diagnostics.json"];
    [data writeToFile:path atomically:1];
}

static void addAction(UIAlertController *alert, NSString *title, NSInteger style, void (^action)(void)) {
    __weak UIAlertController *weakAlert = alert;
    [alert addAction:[UIAlertAction actionWithTitle:title style:style handler:^(UIAlertAction *sender) {
        (void)sender;
        if (action) [weakAlert dismissViewControllerAnimated:1 completion:action];
    }]];
}
static void message(NSString *text) {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Client settings" message:text preferredStyle:1];
    addAction(alert, @"OK", 1, 0);
    [presenter() presentViewController:alert animated:1 completion:0];
}

@implementation SIFASFeatures
- (void)poll:(id)timer {
    (void)timer;
    readPreferences();
    UIView *view = [[activeWindow() rootViewController] view];
    if (!view) return;
    CGRect bounds = [view bounds];
    UIEdgeInsets insets = [view safeAreaInsets];
    CGRect frame = {{bounds.size.width-insets.right-98, insets.top+8}, {90, 36}};
    if (!settingsShortcut) {
        settingsShortcut = [[UILongPressGestureRecognizer alloc] initWithTarget:self
            action:sel_registerName("showSettingsShortcut:")];
        [settingsShortcut setMinimumPressDuration:SETTINGS_HOLD_SECONDS];
        [settingsShortcut setDelegate:self];
        [settingsShortcut setCancelsTouchesInView:0];
        [settingsShortcut setDelaysTouchesBegan:0];
        [settingsShortcut setDelaysTouchesEnded:0];
    }
    if ([settingsShortcut view] != view) {
        [[settingsShortcut view] removeGestureRecognizer:settingsShortcut];
        [view addGestureRecognizer:settingsShortcut];
    }
    if (!settingsButton) {
        settingsButton = [UIButton buttonWithType:1];
        [settingsButton setTitle:@"Settings" forState:0];
        [settingsButton setAccessibilityLabel:@"Client camera and connection settings"];
        [settingsButton setAccessibilityIdentifier:@"SIFASFeatures.Settings"];
        [settingsButton setAutoresizingMask:1|32]; /* flexible left/bottom margin */
        [settingsButton setBackgroundColor:[UIColor colorWithRed:0.05 green:0.05 blue:0.1 alpha:0.85]];
        [settingsButton setAlpha:0.85];
        [settingsButton addTarget:self action:sel_registerName("showSettings") forControlEvents:1<<6];
    }
    if ([settingsButton superview] != view) {
        [settingsButton removeFromSuperview];
        [view addSubview:settingsButton];
    }
    [settingsButton setFrame:frame];
    [settingsButton setHidden:!settingsButtonVisible()];
    writeDiagnostics();
}
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer shouldReceiveTouch:(UITouch *)touch {
    UIView *view = [[activeWindow() rootViewController] view];
    return recognizer == settingsShortcut && !settingsButtonVisible() &&
        [recognizer view] == view && ![[activeWindow() rootViewController] presentedViewController] &&
        settingsShortcutContains(view, [touch locationInView:view]);
}
- (BOOL)gestureRecognizerShouldBegin:(UIGestureRecognizer *)recognizer {
    UIView *view = [[activeWindow() rootViewController] view];
    return recognizer == settingsShortcut && !settingsButtonVisible() &&
        [recognizer view] == view && ![[activeWindow() rootViewController] presentedViewController] &&
        settingsShortcutContains(view, [recognizer locationInView:view]);
}
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer
    shouldRecognizeSimultaneouslyWithGestureRecognizer:(UIGestureRecognizer *)other {
    (void)other;
    return recognizer == settingsShortcut;
}
- (void)showSettingsShortcut:(UILongPressGestureRecognizer *)recognizer {
    if ([recognizer state] == 1 && [self gestureRecognizerShouldBegin:recognizer]) [self showSettings];
}
- (void)showSettings {
    if (!configuration) { message(@"This build has no verified feature configuration section."); return; }
    readPreferences();
    NSString *orientation = orientationMode == 1 ? @"Portrait" : (orientationMode == 2 ? @"Landscape" : @"Auto");
    NSString *detail = [NSString stringWithFormat:@"Build %@\nFOV scale %.4f to %.4f\nOrientation: %@\nFast intro: %@\n\nHide/Show settings button controls the overlay and is saved after restart. While hidden, hold the upper-right corner in game for %.0f seconds to open this menu. Server URL: Connection. Restore defaults shows the button.",
                       clientBuildLabel(), (double)configuration->minimum, (double)configuration->maximum, orientation,
                       configuration->fastIntro ? @"On" : @"Off", SETTINGS_HOLD_SECONDS];
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Client settings" message:detail preferredStyle:1];
    addAction(alert, @"Connection", 0, ^{ [self showConnection]; });
    addAction(alert, @"Adjust FOV bounds", 0, ^{ [self showCamera]; });
    addAction(alert, @"Orientation lock", 0, ^{ [self showOrientation]; });
    addAction(alert, settingsButtonVisible() ? @"Hide settings button" : @"Show settings button", 0, ^{
        [[NSUserDefaults standardUserDefaults] setBool:!settingsButtonVisible() forKey:SETTINGS_BUTTON_KEY];
        [self poll:0];
    });
    addAction(alert, configuration->fastIntro ? @"Disable fast intro" : @"Enable fast intro", 0, ^{
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setBool:![defaults boolForKey:INTRO_KEY] forKey:INTRO_KEY];
        readPreferences();
    });
    addAction(alert, @"Restore defaults", 2, ^{
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setDouble:0.75 forKey:MIN_KEY]; [defaults setDouble:1.0 forKey:MAX_KEY];
        [defaults setBool:0 forKey:INTRO_KEY]; [defaults setInteger:0 forKey:ORIENTATION_KEY];
        [defaults setBool:1 forKey:SETTINGS_BUTTON_KEY];
        orientationPending = 1; [self poll:0];
    });
    addAction(alert, @"Done", 1, 0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
- (void)showCamera {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"FOV bounds"
        message:@"Enter scales from 0.5 to 2.0. Minimum must be at most maximum. Original bounds: 0.75 to 1.0." preferredStyle:1];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) {
        [field setPlaceholder:@"Minimum scale"]; [field setKeyboardType:8];
        [field setText:[NSString stringWithFormat:@"%.4f", (double)configuration->minimum]];
    }];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) {
        [field setPlaceholder:@"Maximum scale"]; [field setKeyboardType:8];
        [field setText:[NSString stringWithFormat:@"%.4f", (double)configuration->maximum]];
    }];
    __weak UIAlertController *weakAlert = alert;
    [alert addAction:[UIAlertAction actionWithTitle:@"Apply" style:0 handler:^(UIAlertAction *sender) {
        (void)sender;
        NSArray *fields = [weakAlert textFields];
        if ([fields count] != 2) return;
        double minimum = 0, maximum = 0;
        NSScanner *a = [NSScanner scannerWithString:[(UITextField *)[fields objectAtIndex:0] text]];
        NSScanner *b = [NSScanner scannerWithString:[(UITextField *)[fields objectAtIndex:1] text]];
        if (![a scanDouble:&minimum] || ![a isAtEnd] || ![b scanDouble:&maximum] || ![b isAtEnd] ||
            !__builtin_isfinite(minimum) || !__builtin_isfinite(maximum) || minimum < 0.5 || maximum > 2.0 || minimum > maximum) {
            [weakAlert dismissViewControllerAnimated:1 completion:^{
                message(@"Use two numbers from 0.5 to 2.0, with minimum at most maximum.");
            }];
            return;
        }
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setDouble:minimum forKey:MIN_KEY]; [defaults setDouble:maximum forKey:MAX_KEY]; readPreferences();
    }]];
    addAction(alert, @"Cancel", 1, 0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
- (void)showOrientation {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Orientation lock"
        message:@"Choose portrait, landscape, or device rotation. On iPhone/iPad, rotate the device after applying if needed. On Mac, the game window may also need resizing." preferredStyle:1];
    NSString *names[] = {@"Auto", @"Portrait", @"Landscape"};
    for (NSUInteger mode = 0; mode < 3; mode++) {
        addAction(alert, names[mode], 0, ^{
            [[NSUserDefaults standardUserDefaults] setInteger:(NSInteger)mode forKey:ORIENTATION_KEY];
            orientationPending = 1; readPreferences();
        });
    }
    addAction(alert, @"Cancel", 1, 0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
- (void)showConnection {
    NSString *saved = [[NSUserDefaults standardUserDefaults] stringForKey:SERVER_KEY];
    NSString *details = [NSString stringWithFormat:@"Current launch URL:\n%@\n\nSaved for next launch:\n%@\n\nPackaged URL:\n%@\n\nRestart the game after changes. 127.0.0.1 means this Mac/device. URL capacity: %lu UTF-16 characters. Local GL supports loopback; use the primary GL/JP build for longer LAN URLs.",
        launchServerURL ?: @"Unavailable", saved ? trimServer(saved) : (packagedServerURL ?: @"Unavailable"),
        packagedServerURL ?: @"Unavailable", (unsigned long)serverCapacity];
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Connection" message:details preferredStyle:1];
    addAction(alert, @"Change server URL", 0, ^{ [self editServerURL]; });
    addAction(alert, @"Use 127.0.0.1:8080", 0, ^{
        if (serverCapacity < 21) { message(@"This build's server URL capacity could not be verified."); return; }
        [[NSUserDefaults standardUserDefaults] setObject:@"http://127.0.0.1:8080" forKey:SERVER_KEY];
        message(@"Saved. Restart the game to use the server on this Mac/device.");
    });
    addAction(alert, @"Public key", 0, ^{ [self editPublicKey]; });
    addAction(alert, @"Use packaged URL", 0, ^{
        [[NSUserDefaults standardUserDefaults] removeObjectForKey:SERVER_KEY];
        message(@"The packaged server URL will apply after restarting the game.");
    });
    addAction(alert, @"Done", 1, 0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
- (void)editServerURL {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Server URL"
        message:[NSString stringWithFormat:@"Enter an http:// or https:// server URL, up to %lu UTF-16 characters. No username, password, query, or fragment. Restart to apply.",(unsigned long)serverCapacity] preferredStyle:1];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) {
        [field setKeyboardType:3]; [field setPlaceholder:@"http://127.0.0.1:8080"];
        [field setAutocapitalizationType:0]; [field setAutocorrectionType:1];
        [field setText:[[NSUserDefaults standardUserDefaults] stringForKey:SERVER_KEY] ?: packagedServerURL];
    }];
    __weak UIAlertController *weak = alert;
    [alert addAction:[UIAlertAction actionWithTitle:@"Save" style:0 handler:^(UIAlertAction *sender) {
        (void)sender;
        NSString *value = trimServer([(UITextField *)[[weak textFields] objectAtIndex:0] text]);
        NSURL *url = [NSURL URLWithString:value];
        BOOL charactersOK = SIFASValidURLCharacters([value UTF8String]) != 0;
        NSInteger port = [url port] ? [[url port] integerValue] : 80;
        BOOL valid = charactersOK && [value length] && [value length] <= serverCapacity && serverCapacity &&
            ([[url scheme] isEqualToString:@"http"] || [[url scheme] isEqualToString:@"https"]) && [[url host] length] &&
            ![url user] && ![url password] && ![url query] && ![url fragment] && port >= 1 && port <= 65535;
        if (!valid) {
            NSString *error = [NSString stringWithFormat:@"URL was not saved. This build accepts a valid http(s) URL of at most %lu UTF-16 characters, without spaces, credentials, query, or fragment. Local GL has a 21-character limit; use the primary GL/JP build for longer LAN URLs.",(unsigned long)serverCapacity];
            [weak dismissViewControllerAnimated:1 completion:^{ message(error); }]; return;
        }
        [[NSUserDefaults standardUserDefaults] setObject:value forKey:SERVER_KEY];
        [weak dismissViewControllerAnimated:1 completion:^{ message(@"Saved. Restart the game to apply the server URL."); }];
    }]];
    addAction(alert,@"Cancel",1,0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
- (void)editPublicKey {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Server public key"
        message:[NSString stringWithFormat:@"Only change this when your server provides an RSAKeyValue XML public key. Maximum: %lu UTF-16 characters. Clear the field to restore the packaged key. Restart to apply.",(unsigned long)publicKeyCapacity] preferredStyle:1];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) {
        [field setKeyboardType:1]; [field setPlaceholder:@"<RSAKeyValue>…</RSAKeyValue>"];
        [field setAutocapitalizationType:0]; [field setAutocorrectionType:1];
        [field setText:[[NSUserDefaults standardUserDefaults] stringForKey:PUBLIC_KEY]];
    }];
    __weak UIAlertController *weak = alert;
    [alert addAction:[UIAlertAction actionWithTitle:@"Save" style:0 handler:^(UIAlertAction *sender) {
        (void)sender;
        NSString *value = [[(UITextField *)[[weak textFields] objectAtIndex:0] text]
            stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@" \t\r\n"]];
        BOOL empty = [value length] == 0;
        BOOL valid = empty || (publicKeyCapacity && [value length] <= publicKeyCapacity && SIFASValidPublicKey([value UTF8String]));
        if (!valid) {
            [weak dismissViewControllerAnimated:1 completion:^{ message(@"Key was not saved. Paste compact RSAKeyValue XML with valid base64 Modulus and Exponent, within this build's length limit."); }]; return;
        }
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        if (empty) [defaults removeObjectForKey:PUBLIC_KEY]; else [defaults setObject:value forKey:PUBLIC_KEY];
        [weak dismissViewControllerAnimated:1 completion:^{ message(@"Saved. Restart the game to apply the public key."); }];
    }]];
    addAction(alert,@"Cancel",1,0);
    [presenter() presentViewController:alert animated:1 completion:0];
}
@end

__attribute__((constructor)) static void initializeFeatures(void) {
    configuration = findConfiguration();
    if (!configuration) return; /* unsupported binaries fail closed */
    loadConnectionMetadata();
    /* Read before the first splash duration is used. UIKit changes run on main. */
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    configuration->fastIntro = [defaults boolForKey:INTRO_KEY] ? 1 : 0;
    dispatch_async(&_dispatch_main_q, ^{
        installOrientationMethods();
        readPreferences();
        controller = [SIFASFeatures new];
        [controller poll:0];
        settingsTimer = [NSTimer scheduledTimerWithTimeInterval:0.5 target:controller selector:sel_registerName("poll:") userInfo:0 repeats:1];
    });
}
