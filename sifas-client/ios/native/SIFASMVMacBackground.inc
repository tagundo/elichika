// Included in the exact-image bootstrap for standalone PlayCover builds.
#import "SIFASMVStandaloneAdapter.h"
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <initializer_list>
#include <mach-o/getsect.h>

namespace {
using ControllerAction = void (*)(id, SEL);
using ApplicationAction = void (*)(id, SEL, UIApplication *);
using PresentAction = void (*)(id, SEL, const void *);
using ObjectGetter = id (*)(id, SEL);
using DrawableGetter = id (*)(id, SEL);

// The Metal path creates two fallback textures, makes one the current back
// buffer at the start of each frame, and replaces it only if nextDrawable
// succeeds. The exported camera captures a separate RenderTexture.
struct UnityMetalSurface {
    uint8_t prefix[0x64];
    int32_t graphicsAPI;
    const void *layer;
    uint8_t intermediate[0x28];
    const void *fallbackTextures[2];
};
static_assert(offsetof(UnityMetalSurface, fallbackTextures)==0x98);

struct MacRenderHooks {
    ApplicationAction resign = nullptr;
    ApplicationAction activate = nullptr;
    ApplicationAction terminate = nullptr;
    ControllerAction displayLink = nullptr;
    ControllerAction repaint = nullptr;
    PresentAction present = nullptr;
    ObjectGetter displayManager = nullptr;
    ObjectGetter mainDisplay = nullptr;
    const UnityMetalSurface *(*metalSurface)(id, SEL) = nullptr;
};

MacRenderHooks macHooks;
std::atomic<DrawableGetter> originalNextDrawable{nullptr};
std::atomic<const void *> leasedMetalLayer{nullptr};
std::atomic<const void *> offscreenLayer{nullptr};
std::atomic<bool> missingDrawable{false};
std::atomic<bool> macFallbackRequested{false};
intptr_t macImageSlide = 0;
bool macRenderPinsVerified = false;
__weak id macRenderController;
id macRenderLayer;
NSTimer *macRenderTimer;
bool macDeferredResign = false;
bool macStepping = false;
bool macEndPending = false;
bool macDisplayAsleep = false;
NSTimeInterval macLastDisplayTick = 0;
NSTimeInterval macNextDisplayCheck = 0;
NSTimeInterval macNextDrawableAttempt = 0;

constexpr uintptr_t kUnityResign = 0x1000191ec;
constexpr uintptr_t kUnityActivate = 0x100018ef8;
constexpr uintptr_t kUnityTerminate = 0x100019290;
constexpr uintptr_t kUnityDisplayLink = 0x10000de80;
constexpr uintptr_t kUnityRepaint = 0x10000dedc;
constexpr uintptr_t kUnityPresent = 0x10000e0a0;
constexpr uintptr_t kDisplayManager = 0x100013580;
constexpr uintptr_t kMainDisplay = 0x1000135c8;
constexpr uintptr_t kMetalSurface = 0x100011e6c;
constexpr NSTimeInterval kDisplayLinkTimeout = 0.15;
constexpr NSTimeInterval kDrawableRetryInterval = 4.0;

void verifyMacRenderPins(intptr_t slide) {
    const auto *header = reinterpret_cast<const mach_header_64 *>(_dyld_get_image_header(0));
    unsigned long textSize = 0;
    const uint8_t *code = getsectiondata(header, "__TEXT", "__text", &textSize);
    if (!code) return;

    const uintptr_t base = reinterpret_cast<uintptr_t>(code);
    const auto matches = [&](uintptr_t preferred, std::initializer_list<uint32_t> bytes) {
        const uintptr_t address = preferred + slide;
        const size_t count = bytes.size()*sizeof(uint32_t);
        return address >= base && address-base <= textSize && count <= textSize-(address-base) &&
            std::memcmp(reinterpret_cast<const void *>(address), bytes.begin(), count)==0;
    };
    // Lifecycle dispatch, nil drawable handling, and the alternative texture
    // are separate parts of the exact Unity contract.
    macRenderPinsVerified =
        matches(0x10000deb0, {0x39400108, 0x350000a8, 0xaa1303e0, 0x95043f31}) &&
        matches(0x100019240, {0xaa1303e0, 0x9504124f, 0x52800020, 0x94307830}) &&
        matches(0x100018f9c, {0x95040be1, 0x9002c228, 0x3902e11f}) &&
        matches(0x1000192a4, {0xf002c208, 0x3942d508, 0x34000048, 0x9430775d}) &&
        matches(0x10000dedc, {0xa9be4ff4, 0xa9017bfd, 0x910043fd, 0xaa0003f3}) &&
        matches(0x10000e0b0, {0xd002c268, 0x9102dd08, 0x39400108, 0xd002c269}) &&
        matches(0x100014de8, {0xf9404800, 0xf9004a7f, 0x9503db2c, 0xf9404e61, 0x9102c260, 0x9503db4a}) &&
        matches(0x100014d74, {0xf9404800, 0xb5000160, 0xf9403660, 0x95041760}) &&
        matches(0x100014d9c, {0xf9404a60, 0xb4000140, 0x95043dbf}) &&
        matches(0x1000144e8, {0xf9403a60, 0xaa1403e2, 0x95041974, 0x8b170e78, 0xf9404f08, 0xf9004f00}) &&
        matches(0x1000123bc, {0xf9401a60, 0x95041d10, 0xaa1d03fd, 0x9503e5c2, 0xf90036a0});
    if (macRenderPinsVerified) macImageSlide = slide;
}

Method pinnedMethod(Class owner, const char *name, uintptr_t address, const char *signature) {
    Method method = class_getInstanceMethod(owner, sel_registerName(name));
    if (!method || reinterpret_cast<uintptr_t>(method_getImplementation(method))!=address+macImageSlide)
        return nullptr;
    const char *encoding = method_getTypeEncoding(method);
    return encoding && !std::strcmp(encoding, signature) ? method : nullptr;
}

id mainMetalLayer() {
    Class displayManager = objc_getClass("DisplayManager");
    id manager = macHooks.displayManager(displayManager, sel_registerName("Instance"));
    if (![manager isMemberOfClass:displayManager]) return nil;
    id display = macHooks.mainDisplay(manager, sel_registerName("mainDisplay"));
    if (![display isMemberOfClass:objc_getClass("DisplayConnection")]) return nil;
    const auto *surface = macHooks.metalSurface(display, sel_registerName("surfaceMTL"));
    if (!surface || surface->graphicsAPI!=4 || !surface->layer ||
        !surface->fallbackTextures[0] || !surface->fallbackTextures[1]) return nil;
    id layer = (__bridge id)surface->layer;
    return [layer isKindOfClass:objc_getClass("CAMetalLayer")] ? layer : nil;
}

void setMacOffscreen(bool offscreen) {
    macFallbackRequested.store(offscreen, std::memory_order_release);
    offscreenLayer.store(offscreen ? (__bridge const void *)macRenderLayer : nullptr, std::memory_order_release);
}

void clearMacRenderLease() {
    [macRenderTimer invalidate];
    macRenderTimer = nil;
    leasedMetalLayer.store(nullptr, std::memory_order_release);
    setMacOffscreen(false);
    macRenderController = nil;
    macRenderLayer = nil;
    macDeferredResign = false;
}

id macNextDrawable(id object, SEL selector) {
    const void *layer = (__bridge const void *)object;
    if (offscreenLayer.load(std::memory_order_acquire)==layer) return nil;
    id drawable = originalNextDrawable.load(std::memory_order_acquire)(object, selector);
    if (!drawable && leasedMetalLayer.load(std::memory_order_acquire)==layer)
        missingDrawable.store(true, std::memory_order_release);
    return drawable;
}

void macPresent(id object, SEL selector, const void *stats) {
    // The normal inactive Unity delegate also skips this screen-only callback.
    if (offscreenLayer.load(std::memory_order_acquire)) return;
    macHooks.present(object, selector, stats);
}

void macResign(id object, SEL selector, UIApplication *app) {
    if (!NSThread.isMainThread || !macRenderTimer || object!=macRenderController) {
        macHooks.resign(object, selector, app);
        return;
    }
    macDeferredResign = true;
    setMacOffscreen(true);
}

void macActivate(id object, SEL selector, UIApplication *app) {
    if (NSThread.isMainThread && macRenderTimer && object==macRenderController) {
        macDeferredResign = false;
        macLastDisplayTick = NSProcessInfo.processInfo.systemUptime;
        macNextDrawableAttempt = 0;
        missingDrawable.store(false, std::memory_order_release);
        setMacOffscreen(false);
    }
    macHooks.activate(object, selector, app);
}

void macTerminate(id object, SEL selector, UIApplication *app) {
    if (NSThread.isMainThread && macRenderTimer && object==macRenderController)
        clearMacRenderLease();
    macHooks.terminate(object, selector, app);
}

struct MacFrameScope {
    MacFrameScope() { macStepping = true; }
    ~MacFrameScope() { macStepping = false; }
};

void macDisplayLink(id object, SEL selector) {
    if (!NSThread.isMainThread || !macRenderTimer || object!=macRenderController) {
        macHooks.displayLink(object, selector);
        return;
    }
    if (macStepping || macEndPending) return;
    const NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    macLastDisplayTick = now;
    if (macDeferredResign || macDisplayAsleep || UIApplication.sharedApplication.applicationState!=UIApplicationStateActive)
        return;
    if (missingDrawable.load(std::memory_order_acquire)) {
        // CAMetalLayer can time out for a minimized or sleeping display
        // even if UIKit continues issuing display-link callbacks.
        if (macNextDrawableAttempt==0) macNextDrawableAttempt = now+kDrawableRetryInterval;
        if (now < macNextDrawableAttempt) return;
        missingDrawable.store(false, std::memory_order_release);
        macNextDrawableAttempt = 0;
    }
    setMacOffscreen(false);
    MacFrameScope stepping;
    macHooks.displayLink(object, selector);
}

bool mainDisplayAsleep() {
    // These public CoreGraphics APIs are provided by macOS and absent from
    // the iOS SDK. The callback/drawable watchdogs also work without them.
    using MainDisplay = uint32_t (*)();
    using DisplayIsAsleep = int32_t (*)(uint32_t);
    static const auto main = reinterpret_cast<MainDisplay>(dlsym(RTLD_DEFAULT, "CGMainDisplayID"));
    static const auto asleep = reinterpret_cast<DisplayIsAsleep>(dlsym(RTLD_DEFAULT, "CGDisplayIsAsleep"));
    return main && asleep && asleep(main()) != 0;
}

void tickMacRender() {
    UIApplication *app = UIApplication.sharedApplication;
    id controller = macRenderController;
    if (macStepping || macEndPending || !controller || controller!=app.delegate) return;
    const NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    if (now >= macNextDisplayCheck) {
        macDisplayAsleep = mainDisplayAsleep();
        macNextDisplayCheck = now+0.2;
    }
    if (!macDeferredResign && !macDisplayAsleep && app.applicationState==UIApplicationStateActive &&
        !missingDrawable.load(std::memory_order_acquire) && now-macLastDisplayTick < kDisplayLinkTimeout) return;

    // The run-loop timer also handles a sleeping display with no UIKit focus
    // notification. Unity's repaint remains on its owning main thread.
    id layer = mainMetalLayer();
    if (!layer || class_getMethodImplementation(object_getClass(layer), sel_registerName("nextDrawable"))!=
            reinterpret_cast<IMP>(&macNextDrawable)) {
        leasedMetalLayer.store(nullptr, std::memory_order_release);
        offscreenLayer.store(nullptr, std::memory_order_release);
        macFallbackRequested.store(true, std::memory_order_release);
        return;
    }
    macRenderLayer = layer;
    leasedMetalLayer.store((__bridge const void *)layer, std::memory_order_release);
    setMacOffscreen(true);
    MacFrameScope stepping;
    macHooks.repaint(controller, sel_registerName("repaint"));
}

id installMacRenderHooks(Class controller) {
    const char *lifecycle = "v24@0:8@16";
    Method resign = pinnedMethod(controller, "applicationWillResignActive:", kUnityResign, lifecycle);
    Method active = pinnedMethod(controller, "applicationDidBecomeActive:", kUnityActivate, lifecycle);
    Method terminate = pinnedMethod(controller, "applicationWillTerminate:", kUnityTerminate, lifecycle);
    Method link = pinnedMethod(controller, "repaintDisplayLink", kUnityDisplayLink, "v16@0:8");
    Method repaint = pinnedMethod(controller, "repaint", kUnityRepaint, "v16@0:8");
    Method present = class_getInstanceMethod(controller, sel_registerName("callbackPresent:"));
    if (!resign || !active || !terminate || !link || !repaint || !present || method_getNumberOfArguments(present)!=3 ||
        reinterpret_cast<uintptr_t>(method_getImplementation(present))!=kUnityPresent+macImageSlide) return nil;

    Class manager = objc_getClass("DisplayManager");
    Class display = objc_getClass("DisplayConnection");
    Method instance = pinnedMethod(object_getClass(manager), "Instance", kDisplayManager, "@16@0:8");
    Method main = pinnedMethod(manager, "mainDisplay", kMainDisplay, "@16@0:8");
    Method surface = class_getInstanceMethod(display, sel_registerName("surfaceMTL"));
    if (!instance || !main || !surface || method_getNumberOfArguments(surface)!=2 ||
        reinterpret_cast<uintptr_t>(method_getImplementation(surface))!=kMetalSurface+macImageSlide) return nil;
    macHooks = {
        reinterpret_cast<ApplicationAction>(method_getImplementation(resign)),
        reinterpret_cast<ApplicationAction>(method_getImplementation(active)),
        reinterpret_cast<ApplicationAction>(method_getImplementation(terminate)),
        reinterpret_cast<ControllerAction>(method_getImplementation(link)),
        reinterpret_cast<ControllerAction>(method_getImplementation(repaint)),
        reinterpret_cast<PresentAction>(method_getImplementation(present)),
        reinterpret_cast<ObjectGetter>(method_getImplementation(instance)),
        reinterpret_cast<ObjectGetter>(method_getImplementation(main)),
        reinterpret_cast<decltype(macHooks.metalSurface)>(method_getImplementation(surface)),
    };
    id layer = mainMetalLayer();
    SEL selector = sel_registerName("nextDrawable");
    Method nextDrawable = class_getInstanceMethod(objc_getClass("CAMetalLayer"), selector);
    const char *signature = nextDrawable ? method_getTypeEncoding(nextDrawable) : nullptr;
    if (!layer || !signature || std::strcmp(signature, "@16@0:8") ||
        class_getMethodImplementation(object_getClass(layer), selector)!=method_getImplementation(nextDrawable)) {
        macHooks = {};
        return nil;
    }

    originalNextDrawable.store(reinterpret_cast<DrawableGetter>(method_getImplementation(nextDrawable)), std::memory_order_release);
    method_setImplementation(nextDrawable, reinterpret_cast<IMP>(&macNextDrawable));
    method_setImplementation(present, reinterpret_cast<IMP>(&macPresent));
    method_setImplementation(resign, reinterpret_cast<IMP>(&macResign));
    method_setImplementation(active, reinterpret_cast<IMP>(&macActivate));
    method_setImplementation(terminate, reinterpret_cast<IMP>(&macTerminate));
    method_setImplementation(link, reinterpret_cast<IMP>(&macDisplayLink));
    return layer;
}
}

BOOL SIFASMVBindingsBeginMacBackgroundRender(void) {
    if (!NSThread.isMainThread || !macRenderPinsVerified || !SIFASMVStandaloneRunOnMac()) return NO;
    UIApplication *app = UIApplication.sharedApplication;
    id controller = app.delegate;
    // The app's initial UnityAppController class name is replaced by the
    // stock LLASAppController +load before UIApplicationMain reads it.
    Class game = objc_getClass("LLASAppController");
    Class gameBase = objc_getClass("KJPAppController");
    if (!game || !gameBase || object_getClass(controller)!=game ||
        class_getSuperclass(game)!=gameBase || class_getSuperclass(gameBase)!=objc_getClass("UnityAppController")) return NO;
    if (macRenderTimer) return !macEndPending && controller==macRenderController;
    if (app.applicationState!=UIApplicationStateActive) return NO;

    id layer = macHooks.repaint ? mainMetalLayer() : installMacRenderHooks(game);
    if (!layer || class_getMethodImplementation(object_getClass(layer), sel_registerName("nextDrawable"))!=
            reinterpret_cast<IMP>(&macNextDrawable)) return NO;
    if (class_getMethodImplementation(game, sel_registerName("applicationWillResignActive:"))!=reinterpret_cast<IMP>(&macResign) ||
        class_getMethodImplementation(game, sel_registerName("applicationDidBecomeActive:"))!=reinterpret_cast<IMP>(&macActivate) ||
        class_getMethodImplementation(game, sel_registerName("applicationWillTerminate:"))!=reinterpret_cast<IMP>(&macTerminate) ||
        class_getMethodImplementation(game, sel_registerName("repaintDisplayLink"))!=reinterpret_cast<IMP>(&macDisplayLink) ||
        class_getMethodImplementation(game, sel_registerName("callbackPresent:"))!=reinterpret_cast<IMP>(&macPresent) ||
        class_getMethodImplementation(game, sel_registerName("repaint"))!=reinterpret_cast<IMP>(macHooks.repaint)) return NO;

    macRenderController = controller;
    macRenderLayer = layer;
    macLastDisplayTick = NSProcessInfo.processInfo.systemUptime;
    macNextDisplayCheck = macNextDrawableAttempt = 0;
    macDisplayAsleep = false;
    missingDrawable.store(false, std::memory_order_release);
    leasedMetalLayer.store((__bridge const void *)layer, std::memory_order_release);
    macRenderTimer = [NSTimer timerWithTimeInterval:1.0/60.0 repeats:YES block:^(__unused NSTimer *timer) {
        tickMacRender();
    }];
    [NSRunLoop.mainRunLoop addTimer:macRenderTimer forMode:NSRunLoopCommonModes];
    return YES;
}

void SIFASMVBindingsEndMacBackgroundRender(void) {
    if (!NSThread.isMainThread || !macRenderTimer) return;
    if (macStepping) {
        if (!macEndPending) {
            macEndPending = true;
            dispatch_async(dispatch_get_main_queue(), ^{
                macEndPending = false;
                SIFASMVBindingsEndMacBackgroundRender();
            });
        }
        return;
    }
    id controller = macRenderController;
    UIApplication *app = UIApplication.sharedApplication;
    // Deliver only the outstanding transition. A return to the foreground
    // already handled it through Unity's normal activation callback.
    @try {
        if (macDeferredResign && controller==app.delegate) {
            MacFrameScope stepping;
            macHooks.resign(controller, sel_registerName("applicationWillResignActive:"), app);
        }
    } @finally {
        clearMacRenderLease();
    }
}

BOOL SIFASMVBindingsMacBackgroundRenderFallbackActive(void) {
    return macFallbackRequested.load(std::memory_order_acquire);
}
