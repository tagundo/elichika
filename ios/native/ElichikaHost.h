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
#if ELICHIKA_SIMULATOR_PROBE
FOUNDATION_EXPORT BOOL ElichikaHostInstallForProbe(Class gameClass);
FOUNDATION_EXPORT void ElichikaHostProbeWebStorage(NSUInteger launchNumber, void (^completion)(NSDictionary *result));
#endif
NS_ASSUME_NONNULL_END
