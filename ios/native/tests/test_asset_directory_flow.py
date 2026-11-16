"""Run the production storage flow against scoped URLs on Apple Foundation.

No game files, live picker or installed app defaults are used. The picker URL
deliberately denies metadata until access starts, reproducing the reported
PlayCover failure instead of assuming ordinary temporary paths prove access.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "ElichikaHost.mm"


def harness_source():
    source = SOURCE.read_text()
    helpers = source[source.index("static NSURLBookmarkCreationOptions ELAssetBookmarkCreationOptions(void)"):
                     source.index("static NSString *ELJSON(id value)")]
    delegate = source[source.index("@implementation ELDocumentTransaction") :]
    picker = delegate[delegate.index("- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:"):
                      delegate.index("    _copying=YES;")]
    # The production branch returns after every folder/direct-file outcome.
    # Entering the ordinary import branch is a test-fixture error.
    picker += "    abort();\n}\n"
    dealloc = delegate[delegate.index("- (void)dealloc {"):delegate.index("- (void)finish {")]
    choosing = source[source.index("static NSDictionary *ELChooseAssetDirectory(NSError **error) {", source.index("@implementation ELDocumentTransaction")):]
    commit = choosing[choosing.index("    NSString *selected=transaction.path."):choosing.index("static NSDictionary *ELRestoreAssetDirectory(NSError **error) {")]
    restore = choosing[choosing.index("static NSDictionary *ELRestoreAssetDirectory(NSError **error) {"):
                       choosing.index("BOOL ElichikaHostWritablePath")]
    prelude = r'''
#import <Foundation/Foundation.h>
#include <cstdlib>
#include <cstdio>
#include <cstring>
typedef NSObject UIDocumentPickerViewController;
static BOOL ELTestCatalyst;
static NSString *ELTestDocuments;
static NSDictionary *ELConfiguration;
static NSMutableArray<NSURL *> *ELHeldScopes;
static NSString *const ELAssetBookmarkKey=@"TestAssetBookmark";
static NSString *const ELAssetPathKey=@"TestAssetPath";
static NSString *ELButtonText(NSString *en,NSString *ko,NSString *ja) { (void)ko; (void)ja; return en; }
static void check(BOOL good,const char *message) { if (!good) { fprintf(stderr,"%s\n",message); abort(); } }
@interface ELTestProcessInfo : NSObject
+ (instancetype)processInfo;
- (BOOL)isMacCatalystApp;
@end
@implementation ELTestProcessInfo
+ (instancetype)processInfo { static ELTestProcessInfo *p; if (!p) p=[self new]; return p; }
- (BOOL)isMacCatalystApp { return ELTestCatalyst; }
@end
@interface ELTestDefaults : NSObject
@property(nonatomic,strong) NSMutableDictionary *values;
+ (instancetype)standardUserDefaults;
- (void)setObject:(id)value forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
- (NSData *)dataForKey:(NSString *)key;
- (NSString *)stringForKey:(NSString *)key;
@end
@implementation ELTestDefaults
+ (instancetype)standardUserDefaults { static ELTestDefaults *p; if (!p) { p=[self new]; p.values=[NSMutableDictionary new]; } return p; }
- (void)setObject:(id)value forKey:(NSString *)key { self.values[key]=value; }
- (void)removeObjectForKey:(NSString *)key { [self.values removeObjectForKey:key]; }
- (NSData *)dataForKey:(NSString *)key { id v=self.values[key]; return [v isKindOfClass:NSData.class] ? v : nil; }
- (NSString *)stringForKey:(NSString *)key { id v=self.values[key]; return [v isKindOfClass:NSString.class] ? v : nil; }
@end
// Foundation's actual filesystem is retained. Only process identity/defaults
// and the picker-issued URL are test seams.
#define NSProcessInfo ELTestProcessInfo
#define NSUserDefaults ELTestDefaults
#define NSSearchPathForDirectoriesInDomains(domain,mask,expand) (@[ELTestDocuments])
'''
    transaction = r'''
@interface ELFakeScopedURL : NSObject
@property(nonatomic,strong) NSURL *underlying;
@property(nonatomic,assign) BOOL access;
@property(nonatomic,assign) BOOL grant;
@property(nonatomic,assign) BOOL inspectionFailure;
@property(nonatomic,assign) BOOL explicitBookmarkFailure;
@property(nonatomic,assign) NSUInteger starts;
@property(nonatomic,assign) NSUInteger stops;
@property(nonatomic,assign) NSUInteger inspections;
@property(nonatomic,assign) NSUInteger readsBeforeAccess;
@property(nonatomic,assign) NSURLBookmarkCreationOptions bookmarkOptions;
@end
@implementation ELFakeScopedURL
- (BOOL)isFileURL { return YES; }
- (NSString *)path { return self.underlying.path; }
- (NSString *)absoluteString { return self.underlying.absoluteString; }
- (NSString *)lastPathComponent { return self.underlying.lastPathComponent; }
- (NSURL *)URLByDeletingLastPathComponent { return self.underlying.URLByDeletingLastPathComponent; }
- (BOOL)startAccessingSecurityScopedResource { self.starts++; self.access=self.grant; return self.grant; }
- (void)stopAccessingSecurityScopedResource { self.stops++; self.access=NO; }
- (BOOL)getResourceValue:(out id *)value forKey:(NSURLResourceKey)key error:(NSError **)error {
    self.inspections++;
    if (!self.access || self.inspectionFailure) {
        if (!self.access) self.readsBeforeAccess++;
        if (error) *error=[NSError errorWithDomain:NSCocoaErrorDomain code:NSFileReadNoPermissionError
            userInfo:@{NSLocalizedDescriptionKey:@"Scoped picker URL denied metadata."}];
        return NO;
    }
    return [self.underlying getResourceValue:value forKey:key error:error];
}
- (NSData *)bookmarkDataWithOptions:(NSURLBookmarkCreationOptions)options includingResourceValuesForKeys:(NSArray *)keys relativeToURL:(NSURL *)relative error:(NSError **)error {
    (void)keys; (void)relative; self.bookmarkOptions=options;
    if (self.explicitBookmarkFailure && (options&(1UL<<11))) {
        if (error) *error=[NSError errorWithDomain:NSCocoaErrorDomain code:256 userInfo:@{NSLocalizedDescriptionKey:@"No app-scoped bookmark entitlement."}];
        return nil;
    }
    return [[@"scoped-bookmark:" stringByAppendingString:self.path] dataUsingEncoding:NSUTF8StringEncoding];
}
@end
@interface ELDocumentTransaction : NSObject
@property(nonatomic,strong) NSError *error;
@property(nonatomic,copy) NSString *path;
@property(nonatomic,assign) BOOL exporting;
@property(nonatomic,assign) BOOL multiple;
@property(nonatomic,assign) NSInteger selectionKind;
@property(nonatomic,strong) NSURL *selectedURL;
@property(nonatomic,strong) NSData *bookmark;
@property(nonatomic,copy) NSString *bookmarkMode;
@property(nonatomic,assign) BOOL securityScope;
@property(nonatomic,assign) BOOL finished;
- (void)finish;
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller;
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls;
@end
@implementation ELDocumentTransaction
- (void)finish { self.finished=YES; }
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller { (void)controller; self.error=[NSError errorWithDomain:@"ElichikaDocument" code:2 userInfo:nil]; [self finish]; }
'''
    main = r'''
static ELFakeScopedURL *scoped(NSString *path) { ELFakeScopedURL *u=[ELFakeScopedURL new]; u.underlying=[NSURL fileURLWithPath:path]; u.grant=YES; return u; }
static ELDocumentTransaction *pick(ELFakeScopedURL *url) { ELDocumentTransaction *t=[ELDocumentTransaction new]; t.selectionKind=1; [t documentPicker:nil didPickDocumentsAtURLs:@[(NSURL *)url]]; return t; }
static void seed(void) { ELTestDefaults.standardUserDefaults.values=[@{ELAssetPathKey:@"/previous/library",ELAssetBookmarkKey:[@"previous-bookmark" dataUsingEncoding:NSUTF8StringEncoding]} mutableCopy]; }
int main(void) {
    @autoreleasepool {
        NSString *root=[[NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString] stringByResolvingSymlinksInPath];
        NSFileManager *fm=NSFileManager.defaultManager; NSError *error=nil;
        check([fm createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:&error],"temporary root");
        @try {
            ELConfiguration=@{@"library_root":@"/previous/library"};
            ELTestDocuments=[root stringByAppendingPathComponent:@"Documents"];
            check([fm createDirectoryAtPath:ELTestDocuments withIntermediateDirectories:YES attributes:nil error:&error],"documents");
            NSString *library=[root stringByAppendingPathComponent:@"library"];
            check([fm createDirectoryAtPath:library withIntermediateDirectories:YES attributes:nil error:&error],"library");
            NSString *sentinel=[library stringByAppendingPathComponent:@"existing.txt"];
            check([@"unchanged" writeToFile:sentinel atomically:YES encoding:NSUTF8StringEncoding error:&error],"sentinel");
            // The shipped iOS slice takes the runtime Catalyst branch after
            // PlayCover conversion, regardless of its compile-time target.
            ELTestCatalyst=YES;
            check(ELAssetBookmarkCreationOptions()==(1UL<<11),"Catalyst persistent security-scope creation");
            check((ELAssetBookmarkResolutionOptions(@"mac_security_scoped")&(1UL<<10))!=0,"Catalyst explicit security-scope restore");
            ELTestCatalyst=NO;
            check(ELAssetBookmarkCreationOptions()==NSURLBookmarkCreationMinimalBookmark,"iOS picker bookmark");
            check((ELAssetBookmarkResolutionOptions(@"mac_security_scoped")&(1UL<<10))==0,"iOS restore excludes Catalyst-only flag");
            ELTestCatalyst=YES; seed();
            check([ELSavedAssetBookmarkMode() isEqual:@"mac_implicit"] && !(ELAssetBookmarkResolutionOptions(ELSavedAssetBookmarkMode())&(1UL<<10)),"legacy .3 minimal bookmark resolves without explicit-only flag");
            ELFakeScopedURL *url=scoped(library);
            __attribute__((objc_precise_lifetime)) ELDocumentTransaction *selection=pick(url);
            check(selection.finished && !selection.error && [selection.path isEqual:library],"picker completes after scoped inspection");
            check(url.starts==1 && url.inspections==1 && url.readsBeforeAccess==0,"scope precedes first filesystem metadata read");
            check(url.bookmarkOptions==(1UL<<11),"picker uses runtime Catalyst bookmark options");
            check([ELTestDefaults.standardUserDefaults.values[ELAssetPathKey] isEqual:@"/previous/library"],"picker alone cannot change saved root");
            NSDictionary *result=ELTestCommit(selection,&error);
            check(result && !error && [result[@"path"] isEqual:library] && [result[@"active_path"] isEqual:@"/previous/library"],"validated pending root returned");
            check([result[@"requires_restart"] boolValue] && ![result[@"applied"] boolValue],"pending root never reported active");
            check([ELTestDefaults.standardUserDefaults.values[ELAssetPathKey] isEqual:library] && !selection.securityScope && ELHeldScopes.count==1,"commit transfers scope and preference together");
            check([[@"unchanged" stringByAppendingString:@""] isEqual:[NSString stringWithContentsOfFile:sentinel encoding:NSUTF8StringEncoding error:&error]],"existing assets preserved");
            NSString *decodedMode=nil;
            NSData *decoded=ELReadAssetBookmark(ELTestDefaults.standardUserDefaults.values[ELAssetBookmarkKey],&decodedMode,&error);
            check([decoded isEqual:selection.bookmark] && [decodedMode isEqual:@"mac_security_scoped"],"saved mode and bookmark bytes share one value");
            // Default PlayCover signing omits app-scoped-bookmark entitlement.
            // A fallback is explicitly temporary, never silently permanent.
            seed(); ELFakeScopedURL *temporary=scoped(library); temporary.explicitBookmarkFailure=YES;
            @autoreleasepool {
                ELDocumentTransaction *t=pick(temporary); error=nil;
                check(!t.error && [t.bookmarkMode isEqual:@"mac_implicit"] && temporary.bookmarkOptions==NSURLBookmarkCreationMinimalBookmark,"documented implicit fallback after explicit grant failure");
                result=ELTestCommit(t,&error);
                check(result && !error && [result[@"access_lifetime"] isEqual:@"until_reboot"] && [result[@"persistence_warning"] length]>0,"implicit access lifetime is reported honestly");
                decodedMode=nil; decoded=ELReadAssetBookmark(ELTestDefaults.standardUserDefaults.values[ELAssetBookmarkKey],&decodedMode,&error);
                check([decoded isEqual:t.bookmark] && [decodedMode isEqual:@"mac_implicit"] && !(ELAssetBookmarkResolutionOptions(decodedMode)&(1UL<<10)),"implicit bytes/mode restore without explicit-only flag");
            }
            // A selected packs child must not silently become packs/packs or
            // obtain access to a parent that the user never selected.
            seed(); NSString *packs=[library stringByAppendingPathComponent:@"packs"];
            ELFakeScopedURL *child=scoped(packs);
            @autoreleasepool { ELDocumentTransaction *t=pick(child); check(t.error && !t.path && [t.error.localizedDescription containsString:library],"packs child names containing root"); }
            check(child.starts==1 && child.stops==1 && ![fm fileExistsAtPath:[packs stringByAppendingPathComponent:@"packs"]],"failed child scope released, no nested packs");
            check([ELTestDefaults.standardUserDefaults.values[ELAssetPathKey] isEqual:@"/previous/library"],"failed child keeps previous preference");
            // Read failure after a successful scope must also release it and
            // surface the original failure domain/code and selected path.
            ELFakeScopedURL *denied=scoped(library); denied.inspectionFailure=YES;
            @autoreleasepool { ELDocumentTransaction *t=pick(denied); check(t.error && [t.error.localizedDescription containsString:NSCocoaErrorDomain] && [t.error.localizedDescription containsString:library],"specific inspection failure"); }
            check(denied.stops==1,"failed inspection releases acquired scope");
            // Even a valid picker/bookmark may point at a library whose packs
            // entry is a file. Validation failure must not commit any settings.
            NSString *bad=[root stringByAppendingPathComponent:@"bad-library"];
            check([fm createDirectoryAtPath:bad withIntermediateDirectories:YES attributes:nil error:&error],"bad library");
            check([@"file" writeToFile:[bad stringByAppendingPathComponent:@"packs"] atomically:YES encoding:NSUTF8StringEncoding error:&error],"bad packs fixture");
            ELFakeScopedURL *badURL=scoped(bad);
            @autoreleasepool { ELDocumentTransaction *t=pick(badURL); error=nil; check(!ELTestCommit(t,&error) && error && [error.localizedDescription containsString:@"packs"],"real layout validation rejects file"); }
            check([ELTestDefaults.standardUserDefaults.values[ELAssetPathKey] isEqual:@"/previous/library"] && badURL.stops==1,"failed layout preserves previous root and releases scope");
            NSString *escape=[root stringByAppendingPathComponent:@"escape-library"];
            check([fm createDirectoryAtPath:escape withIntermediateDirectories:YES attributes:nil error:&error],"escape library");
            check([fm createSymbolicLinkAtPath:[escape stringByAppendingPathComponent:@"packs"] withDestinationPath:library error:&error],"escape symlink");
            error=nil; check(!ELPrepareAssetFolders(escape,&error) && error,"packs symlink cannot escape granted root");
            NSString *defaultPath=[ELTestDocuments stringByAppendingPathComponent:@"Elichika"];
            check([fm createDirectoryAtPath:defaultPath withIntermediateDirectories:YES attributes:nil error:&error],"default library");
            check([@"file" writeToFile:[defaultPath stringByAppendingPathComponent:@"packs"] atomically:YES encoding:NSUTF8StringEncoding error:&error],"bad default fixture");
            error=nil; check(!ELRestoreAssetDirectory(&error) && error,"default validation fails before clearing external preference");
            check([ELTestDefaults.standardUserDefaults.values[ELAssetBookmarkKey] isEqual:[@"previous-bookmark" dataUsingEncoding:NSUTF8StringEncoding]],"failed default restore keeps saved bookmark");
            check([fm removeItemAtPath:[defaultPath stringByAppendingPathComponent:@"packs"] error:&error],"clear bad fixture");
            error=nil; result=ELRestoreAssetDirectory(&error);
            check(result && !error && [result[@"requires_restart"] boolValue] && ![result[@"applied"] boolValue],"default restore is pending, old active root retained");
            check(!ELTestDefaults.standardUserDefaults.values[ELAssetBookmarkKey] && [ELConfiguration[@"library_root"] isEqual:@"/previous/library"],"default restore changes only next-launch preference");
            // Successful pending choices retain their grants; process-exit
            // cleanup is represented explicitly in this isolated test.
            check(url.stops==0,"old active/pending grants not revoked by default choice");
            ELFakeScopedURL *failedRestore=scoped(library);
            @autoreleasepool {
                __attribute__((objc_precise_lifetime)) ELAssetScopeLease *lease=[[ELAssetScopeLease alloc] initWithURL:(NSURL *)failedRestore];
                check(lease.acquired,"restore lease acquires scoped access");
            }
            check(failedRestore.stops==1,"failed configuration releases its acquired restore scope");
            ELFakeScopedURL *successfulRestore=scoped(library);
            @autoreleasepool {
                __attribute__((objc_precise_lifetime)) ELAssetScopeLease *lease=[[ELAssetScopeLease alloc] initWithURL:(NSURL *)successfulRestore];
                [lease keepUntilExit];
            }
            check(successfulRestore.stops==0 && ELHeldScopes.count==3,"successful configuration retains scope for running jobs");
            for (NSURL *held in ELHeldScopes) [held stopAccessingSecurityScopedResource];
            [ELHeldScopes removeAllObjects];
            printf("{\"status\":\"PASS\",\"scoped_picker_before_metadata\":true,\"runtime_catalyst_flags\":true,\"rollback_on_failures\":true,\"pending_not_active\":true,\"real_layout_checks\":true}\n");
        } @finally { [fm removeItemAtPath:root error:NULL]; }
    }
    return 0;
}
'''
    return (prelude + helpers + transaction + dealloc + picker + "@end\n" +
            "static NSDictionary *ELTestCommit(ELDocumentTransaction *transaction,NSError **error) {\n" +
            commit + restore + main)


@unittest.skipUnless(sys.platform == "darwin", "Apple Foundation regression executes on macOS CI")
class AssetDirectoryFlowTests(unittest.TestCase):
    def test_real_production_folder_flow_with_scoped_url_and_rollback(self):
        with tempfile.TemporaryDirectory(prefix="elichika-storage-regression-") as directory:
            root = Path(directory)
            source = root / "probe.mm"
            executable = root / "probe"
            source.write_text(harness_source())
            compiler = shutil.which("clang++")
            self.assertIsNotNone(compiler, "Apple clang++ is required")
            compiled = subprocess.run([compiler, "-std=c++17", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                                       "-framework", "Foundation", str(source), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, "Storage Foundation harness compile failed:\n" +
                             (compiled.stdout + compiled.stderr)[-16384:])
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, "Storage Foundation harness execution failed:\n" +
                             (result.stdout + result.stderr)[-16384:])
            self.assertEqual(json.loads(result.stdout), {
                "status": "PASS", "scoped_picker_before_metadata": True, "runtime_catalyst_flags": True,
                "rollback_on_failures": True, "pending_not_active": True, "real_layout_checks": True,
            })


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--emit":
        Path(sys.argv[2]).write_text(harness_source())
    else:
        unittest.main()
