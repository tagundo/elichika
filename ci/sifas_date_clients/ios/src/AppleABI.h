/* Minimal declarations of public Apple APIs used by this small library.
 * The build can be cross-compiled on Linux; Xcode/device validation is separate. */
#ifndef SIFAS_APPLE_ABI_H
#define SIFAS_APPLE_ABI_H
typedef _Bool BOOL;
typedef unsigned long NSUInteger;
typedef long NSInteger;
typedef double CGFloat;
typedef struct { CGFloat x, y; } CGPoint;
typedef struct { CGFloat width, height; } CGSize;
typedef struct { CGPoint origin; CGSize size; } CGRect;
typedef struct { CGFloat top, left, bottom, right; } UIEdgeInsets;
typedef struct objc_class *Class;
typedef struct objc_selector *SEL;
typedef void (*IMP)(void);
typedef struct objc_method *Method;
extern Class objc_getClass(const char *);
extern SEL sel_registerName(const char *);
extern Method class_getInstanceMethod(Class, SEL);
extern IMP class_replaceMethod(Class, SEL, IMP, const char *);
extern const void *_dyld_get_image_header(unsigned int);
extern long _dyld_get_image_vmaddr_slide(unsigned int);
struct dispatch_queue_s;
extern struct dispatch_queue_s _dispatch_main_q;
extern void dispatch_async(struct dispatch_queue_s *, void (^)(void));

@class NSString, NSArray, NSDictionary, NSNotification, NSNotificationCenter, NSData, NSCharacterSet, NSNumber;
__attribute__((objc_root_class)) @interface NSObject
+ (instancetype)alloc;
+ (instancetype)new;
+ (Class)class;
- (BOOL)isKindOfClass:(Class)kind;
- (instancetype)init;
- (BOOL)respondsToSelector:(SEL)selector;
- (Class)class;
@end
@interface NSString : NSObject
+ (instancetype)stringWithUTF8String:(const char *)value;
+ (instancetype)stringWithFormat:(NSString *)format, ...;
- (NSUInteger)length;
- (const char *)UTF8String;
- (BOOL)isEqualToString:(NSString *)string;
- (BOOL)hasPrefix:(NSString *)prefix;
- (BOOL)hasSuffix:(NSString *)suffix;
- (BOOL)containsString:(NSString *)string;
- (NSString *)stringByAppendingPathComponent:(NSString *)component;
- (NSString *)stringByTrimmingCharactersInSet:(NSCharacterSet *)characters;
- (NSString *)substringToIndex:(NSUInteger)index;
- (instancetype)initWithData:(NSData *)data encoding:(NSUInteger)encoding;
@end
@interface NSArray : NSObject
- (NSUInteger)count;
- (id)objectAtIndex:(NSUInteger)index;
@end
@interface NSSet : NSObject
- (NSArray *)allObjects;
@end
@interface NSData : NSObject
- (NSUInteger)length;
- (const void *)bytes;
- (BOOL)writeToFile:(NSString *)path atomically:(BOOL)atomically;
@end
@interface NSFileHandle : NSObject
+ (instancetype)fileHandleForReadingAtPath:(NSString *)path;
- (void)seekToFileOffset:(unsigned long)offset;
- (NSData *)readDataOfLength:(NSUInteger)length;
- (void)closeFile;
@end
@interface NSBundle : NSObject
+ (instancetype)mainBundle;
- (NSString *)bundleIdentifier;
- (NSString *)bundlePath;
- (id)objectForInfoDictionaryKey:(NSString *)key;
@end
@interface NSCharacterSet : NSObject
+ (instancetype)characterSetWithCharactersInString:(NSString *)string;
@end
@interface NSNumber : NSObject
+ (instancetype)numberWithDouble:(double)value;
+ (instancetype)numberWithUnsignedInteger:(NSUInteger)value;
+ (instancetype)numberWithBool:(BOOL)value;
- (NSInteger)integerValue;
@end
@interface NSDictionary : NSObject
+ (instancetype)dictionaryWithObjects:(const id [])objects forKeys:(const id [])keys count:(NSUInteger)count;
@end
@interface NSJSONSerialization : NSObject
+ (NSData *)dataWithJSONObject:(id)object options:(NSUInteger)options error:(id *)error;
@end
@interface NSProcessInfo : NSObject
+ (instancetype)processInfo;
- (BOOL)isiOSAppOnMac;
- (BOOL)isMacCatalystApp;
@end
@interface NSURL : NSObject
+ (instancetype)URLWithString:(NSString *)string;
- (NSString *)scheme;
- (NSString *)host;
- (NSString *)user;
- (NSString *)password;
- (NSString *)query;
- (NSString *)fragment;
- (NSNumber *)port;
@end
extern NSString *NSHomeDirectory(void);
@interface NSUserDefaults : NSObject
+ (instancetype)standardUserDefaults;
- (id)objectForKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
- (double)doubleForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (void)setDouble:(double)value forKey:(NSString *)key;
- (void)setInteger:(NSInteger)value forKey:(NSString *)key;
- (void)setBool:(BOOL)value forKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
@end
@interface NSScanner : NSObject
+ (instancetype)scannerWithString:(NSString *)string;
- (BOOL)scanDouble:(double *)result;
- (BOOL)isAtEnd;
@end
@interface NSTimer : NSObject
+ (instancetype)scheduledTimerWithTimeInterval:(double)interval target:(id)target selector:(SEL)selector userInfo:(id)info repeats:(BOOL)repeats;
@end
@interface NSNotificationCenter : NSObject
+ (instancetype)defaultCenter;
- (void)addObserver:(id)observer selector:(SEL)selector name:(NSString *)name object:(id)object;
@end
@interface UIColor : NSObject
+ (instancetype)colorWithRed:(CGFloat)red green:(CGFloat)green blue:(CGFloat)blue alpha:(CGFloat)alpha;
@end
@class UIViewController, UIWindowScene, UIWindow, UIGestureRecognizer, UITouch;
@interface UIView : NSObject
- (CGRect)bounds;
- (UIWindow *)window;
- (UIEdgeInsets)safeAreaInsets;
- (UIView *)superview;
- (void)setFrame:(CGRect)frame;
- (void)setAutoresizingMask:(NSUInteger)mask;
- (void)setBackgroundColor:(UIColor *)color;
- (void)setAlpha:(CGFloat)value;
- (void)setHidden:(BOOL)hidden;
- (BOOL)isHidden;
- (void)addSubview:(UIView *)view;
- (void)removeFromSuperview;
- (void)addGestureRecognizer:(UIGestureRecognizer *)recognizer;
- (void)removeGestureRecognizer:(UIGestureRecognizer *)recognizer;
@end
@protocol UIGestureRecognizerDelegate
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer shouldReceiveTouch:(UITouch *)touch;
- (BOOL)gestureRecognizerShouldBegin:(UIGestureRecognizer *)recognizer;
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer
    shouldRecognizeSimultaneouslyWithGestureRecognizer:(UIGestureRecognizer *)other;
@end
@interface UIGestureRecognizer : NSObject
- (instancetype)initWithTarget:(id)target action:(SEL)action;
- (void)setDelegate:(id<UIGestureRecognizerDelegate>)delegate;
- (void)setCancelsTouchesInView:(BOOL)value;
- (void)setDelaysTouchesBegan:(BOOL)value;
- (void)setDelaysTouchesEnded:(BOOL)value;
- (NSInteger)state;
- (UIView *)view;
- (CGPoint)locationInView:(UIView *)view;
@end
@interface UILongPressGestureRecognizer : UIGestureRecognizer
- (void)setMinimumPressDuration:(double)duration;
@end
@interface UITouch : NSObject
- (CGPoint)locationInView:(UIView *)view;
@end
@interface UIButton : UIView
+ (instancetype)buttonWithType:(NSInteger)type;
- (void)setTitle:(NSString *)title forState:(NSUInteger)state;
- (void)addTarget:(id)target action:(SEL)action forControlEvents:(NSUInteger)events;
- (void)setAccessibilityLabel:(NSString *)label;
- (void)setAccessibilityIdentifier:(NSString *)identifier;
@end
@interface UIWindow : UIView
- (UIViewController *)rootViewController;
- (UIWindowScene *)windowScene;
- (BOOL)isKeyWindow;
@end
@interface UIApplication : NSObject
+ (instancetype)sharedApplication;
- (UIWindow *)keyWindow;
- (NSSet *)connectedScenes;
@end
@interface UIViewController : NSObject
+ (void)attemptRotationToDeviceOrientation;
- (UIView *)view;
- (instancetype)initWithNibName:(NSString *)name bundle:(NSBundle *)bundle;
- (void)setModalPresentationStyle:(NSInteger)style;
- (UIViewController *)presentedViewController;
- (BOOL)isBeingDismissed;
- (BOOL)isBeingPresented;
- (id)transitionCoordinator;
- (void)setNeedsUpdateOfSupportedInterfaceOrientations;
- (void)presentViewController:(UIViewController *)controller animated:(BOOL)animated completion:(void (^)(void))completion;
- (void)dismissViewControllerAnimated:(BOOL)animated completion:(void (^)(void))completion;
@end
@interface UIWindowScene : NSObject
- (NSArray *)windows;
- (NSInteger)activationState;
- (NSInteger)interfaceOrientation;
- (void)requestGeometryUpdateWithPreferences:(id)preferences errorHandler:(void (^)(id))handler;
@end
@interface SIFASGeometryPreferences : NSObject
- (instancetype)initWithInterfaceOrientations:(NSUInteger)mask;
@end
@interface UITextField : UIView
- (void)setText:(NSString *)text;
- (NSString *)text;
- (void)setPlaceholder:(NSString *)placeholder;
- (void)setKeyboardType:(NSInteger)keyboardType;
- (void)setAutocapitalizationType:(NSInteger)type;
- (void)setAutocorrectionType:(NSInteger)type;
@end
@interface UIAlertAction : NSObject
+ (instancetype)actionWithTitle:(NSString *)title style:(NSInteger)style handler:(void (^)(UIAlertAction *))handler;
@end
@interface UIAlertController : UIViewController
+ (instancetype)alertControllerWithTitle:(NSString *)title message:(NSString *)message preferredStyle:(NSInteger)style;
- (void)addAction:(UIAlertAction *)action;
- (void)addTextFieldWithConfigurationHandler:(void (^)(UITextField *))handler;
- (NSArray *)textFields;
@end
#endif
