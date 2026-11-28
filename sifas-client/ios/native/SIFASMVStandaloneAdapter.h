#pragma once
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

#if defined(SIFAS_STANDALONE)
NS_ASSUME_NONNULL_BEGIN
/* Main-thread copy from the actual loaded CRI cue. Implemented by the native
 * game adapter; absence fails audio preparation instead of exporting silence. */
FOUNDATION_EXPORT NSDictionary * _Nullable SIFASMVBindingsAudioSelection(void) __attribute__((weak_import));
FOUNDATION_EXPORT NSDictionary *SIFASMVStandaloneConfiguration(void);
FOUNDATION_EXPORT void SIFASMVStandaloneSetPresenter(UIViewController * _Nullable presenter);
FOUNDATION_EXPORT UIViewController * _Nullable SIFASMVStandalonePresenter(void);
FOUNDATION_EXPORT BOOL SIFASMVStandaloneShowGame(void);
FOUNDATION_EXPORT BOOL SIFASMVStandaloneRunOnMac(void);
FOUNDATION_EXPORT void SIFASMVStandaloneAudioCall(NSString *method,NSDictionary *arguments,
                                                void (^completion)(NSDictionary *reply));
/* Main thread. Nil when SIFASMVExportCaptureFOV can read the game's live FOV
 * limits. Otherwise the exact failed check as a stable identifier (for example
 * "fov.feature-library" or "fov.bounds") and, in detail, what it found. */
FOUNDATION_EXPORT NSString * _Nullable SIFASMVExportFOVFailure(NSString * _Nullable * _Nullable detail);
NS_ASSUME_NONNULL_END
#endif
