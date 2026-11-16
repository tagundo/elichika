#pragma once
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN
/* Main-thread entry points. Dismissing the form does not cancel its export. */
FOUNDATION_EXPORT void ElichikaPresentMVExportMenu(UIViewController *presenter);
FOUNDATION_EXPORT NSDictionary *SIFASMVExportStatus(void);
FOUNDATION_EXPORT void SIFASMVCancelExport(void);
NS_ASSUME_NONNULL_END
