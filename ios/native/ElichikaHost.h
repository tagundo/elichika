#pragma once
#ifdef __OBJC__
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT __attribute__((visibility("default"))) void ElichikaHostShowManagement(void);
FOUNDATION_EXPORT __attribute__((visibility("default"))) void ElichikaHostReportEvent(NSString *json);
FOUNDATION_EXPORT __attribute__((visibility("default"))) NSString *ElichikaHostDiagnosticsJSON(void);
FOUNDATION_EXPORT NSDictionary *ElichikaHostConfiguration(void);
FOUNDATION_EXPORT UIViewController * _Nullable ElichikaHostPresenter(void);
FOUNDATION_EXPORT NSString * _Nullable ElichikaHostImportDocument(NSArray<NSString *> *types, NSError **error);
FOUNDATION_EXPORT NSArray<NSString *> * _Nullable ElichikaHostImportDocuments(NSArray<NSString *> *types, BOOL multiple, NSError **error);
FOUNDATION_EXPORT BOOL ElichikaHostExportDocument(NSString *path, NSError **error);
FOUNDATION_EXPORT BOOL ElichikaHostWritablePath(NSString *path);
#if ELICHIKA_SIMULATOR_PROBE
FOUNDATION_EXPORT BOOL ElichikaHostInstallForProbe(Class gameClass);
FOUNDATION_EXPORT void ElichikaHostProbeWebStorage(NSUInteger launchNumber, void (^completion)(NSDictionary *result));
FOUNDATION_EXPORT void ElichikaHostProbeManagement(void (^completion)(NSDictionary *result));
FOUNDATION_EXPORT void ElichikaHostSetProbeStageHandler(void (^handler)(NSString *stage, NSTimeInterval entered));
FOUNDATION_EXPORT void ElichikaHostProbeStage(NSString *stage);
#endif
NS_ASSUME_NONNULL_END
#endif
#ifdef __cplusplus
#include <string_view>
namespace elichika {
inline bool nativeLanguageAllowed(std::string_view value) {
    return value=="auto" || value=="en" || value=="ko" || value=="ja";
}
inline bool nativeListenAllowed(std::string_view value) {
    return value=="127.0.0.1:8080" || value=="0.0.0.0:8080";
}
inline bool managementAvailable(bool gameStarted,bool bootstrapReady,bool panelsReady) {
    return panelsReady && (gameStarted || bootstrapReady);
}
}
#endif
