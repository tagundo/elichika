#pragma once
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN
/* Main-thread entry points. Dismissing the form does not cancel its export. */
/* Also exported by the SIFAS_STANDALONE dylib for the existing client menu. */
FOUNDATION_EXPORT void ElichikaPresentMVExportMenu(UIViewController *presenter) __attribute__((visibility("default")));
FOUNDATION_EXPORT NSDictionary *SIFASMVExportStatus(void);
FOUNDATION_EXPORT void SIFASMVCancelExport(void);
NS_ASSUME_NONNULL_END
