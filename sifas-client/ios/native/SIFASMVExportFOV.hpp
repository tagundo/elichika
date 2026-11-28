#pragma once

#import <Foundation/Foundation.h>

@class SIFASMVExportFOVOverride;

// Standalone PlayCover camera limits. Apply and restore on the main thread.
BOOL SIFASMVExportValidFOV(id value);
NSDictionary *SIFASMVExportCaptureFOV(void);
SIFASMVExportFOVOverride *SIFASMVExportApplyFOV(NSDictionary *bounds, NSString **error);
BOOL SIFASMVExportRestoreFOV(SIFASMVExportFOVOverride *token);
