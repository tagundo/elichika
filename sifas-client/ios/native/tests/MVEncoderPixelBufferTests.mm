// Real Foundation/CoreVideo buffers with a recording adaptor. This exercises
// the production handoff and append contract without running a codec or game.
#import "ElichikaMVEncoder.h"
#import <AVFoundation/AVFoundation.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void Require(BOOL condition, NSString *message) {
    if (!condition) {
        fprintf(stderr,"MV pixel-buffer test failed: %s\n",message.UTF8String);
        exit(1);
    }
}

@interface RecordingAdaptor : NSObject {
    CVPixelBufferRef _acceptedPixel;
}
@property(nonatomic) NSUInteger appendCalls;
@property(nonatomic) NSUInteger poolCalls;
@property(nonatomic) BOOL rejectAppend;
@property(nonatomic) CMTime presentationTime;
@property(nonatomic,readonly) CVPixelBufferRef acceptedPixel;
- (CVPixelBufferPoolRef)pixelBufferPool;
- (BOOL)appendPixelBuffer:(CVPixelBufferRef)pixel withPresentationTime:(CMTime)time;
- (void)releaseAcceptedPixel;
@end
@implementation RecordingAdaptor
- (CVPixelBufferPoolRef)pixelBufferPool {
    ++_poolCalls;
    [NSException raise:NSInternalInconsistencyException format:@"Direct append entered the legacy allocation/copy route"];
    return NULL;
}
- (BOOL)appendPixelBuffer:(CVPixelBufferRef)pixel withPresentationTime:(CMTime)time {
    ++_appendCalls;
    if (_rejectAppend) return NO;
    CVPixelBufferRetain(pixel);
    [self releaseAcceptedPixel];
    _acceptedPixel=pixel; _presentationTime=time;
    return YES;
}
- (CVPixelBufferRef)acceptedPixel { return _acceptedPixel; }
- (void)releaseAcceptedPixel {
    if (_acceptedPixel) CVPixelBufferRelease(_acceptedPixel);
    _acceptedPixel=NULL;
}
- (void)dealloc { [self releaseAcceptedPixel]; }
@end

@interface RecordingWriter : NSObject
@property(nonatomic) AVAssetWriterStatus status;
@property(nonatomic,strong) NSError *error;
@property(nonatomic) NSUInteger cancellations;
@property(nonatomic,weak) RecordingAdaptor *adaptor;
- (void)cancelWriting;
@end
@implementation RecordingWriter
- (void)cancelWriting {
    ++_cancellations; _status=AVAssetWriterStatusCancelled;
    [_adaptor releaseAcceptedPixel];
}
@end

@interface RecordingInput : NSObject
// Match AVAssetWriterInput's Objective-C getter, not just its property name.
@property(nonatomic,getter=isReadyForMoreMediaData) BOOL readyForMoreMediaData;
@property(nonatomic) NSUInteger finishedCalls;
- (void)markAsFinished;
@end
@implementation RecordingInput
- (void)markAsFinished { ++_finishedCalls; }
@end

struct Fixture {
    ELMVEncoder *encoder;
    RecordingWriter *writer;
    RecordingInput *input;
    RecordingAdaptor *adaptor;
    Fixture() {
        ELMVEncoderConfiguration *c=[ELMVEncoderConfiguration new];
        c.width=16; c.height=16; c.frameCount=2;
        c.fpsNumerator=30000; c.fpsDenominator=1001;
        encoder=[ELMVEncoder new]; writer=[RecordingWriter new];
        input=[RecordingInput new]; adaptor=[RecordingAdaptor new];
        Require([input respondsToSelector:@selector(isReadyForMoreMediaData)] &&
            [input respondsToSelector:@selector(markAsFinished)] &&
            [writer respondsToSelector:@selector(status)] &&
            [writer respondsToSelector:@selector(error)] &&
            [writer respondsToSelector:@selector(cancelWriting)] &&
            [adaptor respondsToSelector:@selector(appendPixelBuffer:withPresentationTime:)],
            @"Recording objects must implement the production framework selectors.");
        writer.status=AVAssetWriterStatusWriting; writer.adaptor=adaptor;
        input.readyForMoreMediaData=YES;
        // Confined to this fixture; no production API exposes writer injection.
        [encoder setValue:c forKey:@"configuration"];
        [encoder setValue:writer forKey:@"writer"];
        [encoder setValue:input forKey:@"video"];
        [encoder setValue:adaptor forKey:@"adaptor"];
        NSString *path=[NSTemporaryDirectory() stringByAppendingPathComponent:
            [NSString stringWithFormat:@"mv-pixel-test-%@.partial.mp4",NSUUID.UUID.UUIDString]];
        [encoder setValue:[NSURL fileURLWithPath:path] forKey:@"partialURL"];
    }
};

static void Released(void *context,const void *base) {
    ++*static_cast<NSUInteger *>(context);
    free(const_cast<void *>(base));
}
static CVPixelBufferRef Pixel(NSUInteger *releases,size_t width=16,OSType format=kCVPixelFormatType_32BGRA) {
    const size_t stride=width*4+16,height=16;
    uint8_t *bytes=static_cast<uint8_t *>(malloc(stride*height));
    Require(bytes!=nullptr,@"Could not allocate the bounded padded fixture.");
    memset(bytes,0xa5,stride*height);
    for (size_t y=0;y<height;y++) for (size_t x=0;x<width;x++) {
        uint8_t *p=bytes+y*stride+x*4;
        p[0]=(uint8_t)(x*7); p[1]=(uint8_t)(y*11); p[2]=123; p[3]=255;
    }
    CVPixelBufferRef pixel=NULL;
    CVReturn status=CVPixelBufferCreateWithBytes(kCFAllocatorDefault,width,height,format,
        bytes,stride,Released,releases,NULL,&pixel);
    Require(status==kCVReturnSuccess && pixel,@"Could not create the real padded CVPixelBuffer.");
    return pixel;
}
static void CheckTag(CVPixelBufferRef pixel,CFStringRef key,CFStringRef expected) {
    CVAttachmentMode mode=kCVAttachmentMode_ShouldNotPropagate;
    CFTypeRef actual=CVBufferGetAttachment(pixel,key,&mode);
    Require(actual && CFEqual(actual,expected) && mode==kCVAttachmentMode_ShouldPropagate,
        @"Direct append changed a propagated color attachment.");
}
static void DirectIdentityRetryAndOwnership(void) {
    NSUInteger releases=0;
    Fixture f;
    CVPixelBufferRef pixel=Pixel(&releases);
    ELMVPixelFrame *frame=[[ELMVPixelFrame alloc] initWithPixelBuffer:pixel];
    Require(frame && frame.pixelBuffer==pixel && frame.rowBytes==80,@"The handoff wrapper changed buffer identity or padded stride.");
    CVPixelBufferRelease(pixel);
    Require(releases==0,@"The wrapper did not retain the producer's buffer.");
    Require(CVPixelBufferLockBaseAddress(frame.pixelBuffer,kCVPixelBufferLock_ReadOnly)==kCVReturnSuccess,@"Could not inspect fixture pixels.");
    NSData *before=[NSData dataWithBytes:CVPixelBufferGetBaseAddress(frame.pixelBuffer) length:80*16];
    CVPixelBufferUnlockBaseAddress(frame.pixelBuffer,kCVPixelBufferLock_ReadOnly);
    f.input.readyForMoreMediaData=NO;
    for (NSUInteger n=0;n<3;n++) {
        Require([f.encoder appendPixelBuffer:frame.pixelBuffer frameIndex:0]==ELMVAppendRetry,@"A non-ready input did not return Retry.");
        Require(f.encoder.acceptedVideoFrames==0 && f.adaptor.appendCalls==0 && !f.encoder.failure,
            @"Retry consumed a frame or called the adaptor.");
        Require(CVBufferGetAttachment(frame.pixelBuffer,kCVImageBufferColorPrimariesKey,NULL)==NULL,
            @"Retry changed the pending buffer's attachments.");
    }
    f.input.readyForMoreMediaData=YES;
    for (int64_t index=0;index<2;index++) {
        Require([f.encoder appendPixelBuffer:frame.pixelBuffer frameIndex:index]==ELMVAppendAccepted,@"A ready direct frame was rejected.");
        Require(f.adaptor.acceptedPixel==frame.pixelBuffer && f.adaptor.poolCalls==0,
            @"Direct append copied or replaced the producer's pixel buffer.");
        Require(CMTimeCompare(f.adaptor.presentationTime,CMTimeMake(index*1001,30000))==0,
            @"Direct append changed exact rational presentation time.");
    }
    Require(f.encoder.acceptedVideoFrames==2 && f.input.finishedCalls==1,@"Direct append changed frame accounting or final input completion.");
    CheckTag(frame.pixelBuffer,kCVImageBufferColorPrimariesKey,kCVImageBufferColorPrimaries_ITU_R_709_2);
    CheckTag(frame.pixelBuffer,kCVImageBufferTransferFunctionKey,kCVImageBufferTransferFunction_sRGB);
    CheckTag(frame.pixelBuffer,kCVImageBufferYCbCrMatrixKey,kCVImageBufferYCbCrMatrix_ITU_R_709_2);
    Require(CVPixelBufferLockBaseAddress(frame.pixelBuffer,kCVPixelBufferLock_ReadOnly)==kCVReturnSuccess,@"Could not recheck direct pixels.");
    Require(memcmp(before.bytes,CVPixelBufferGetBaseAddress(frame.pixelBuffer),before.length)==0,
        @"Direct append changed image bytes or row padding.");
    CVPixelBufferUnlockBaseAddress(frame.pixelBuffer,kCVPixelBufferLock_ReadOnly);
    frame=nil;
    Require(releases==0,@"Dropping the handoff wrapper released an adaptor-owned accepted buffer.");
    [f.encoder cancel];
    Require(releases==1,@"Cancellation did not release the adaptor's accepted-buffer ownership.");
}
static void Reject(CVPixelBufferRef pixel,int64_t index,NSString *reason) {
    Fixture f;
    Require([f.encoder appendPixelBuffer:pixel frameIndex:index]==ELMVAppendFailed,reason);
    Require(f.encoder.acceptedVideoFrames==0 && f.adaptor.appendCalls==0 && f.adaptor.poolCalls==0 &&
        f.encoder.failure && f.writer.cancellations==1,@"Invalid direct input reached the adaptor or advanced accounting.");
}
static void ValidationAndFailure(void) {
    NSUInteger releases=0;
    CVPixelBufferRef pixel=Pixel(&releases);
    Reject(pixel,1,@"An out-of-order direct frame was accepted.");
    CVPixelBufferRef missing=NULL;
    Reject(missing,0,@"A missing direct pixel buffer was accepted.");
    Require(![[ELMVPixelFrame alloc] initWithPixelBuffer:missing],@"The frame wrapper accepted a missing buffer.");
    CVPixelBufferRelease(pixel);
    pixel=Pixel(&releases,18);
    Reject(pixel,0,@"Mismatched direct dimensions were accepted.");
    CVPixelBufferRelease(pixel);
    pixel=Pixel(&releases,16,kCVPixelFormatType_32ARGB);
    Reject(pixel,0,@"A non-BGRA direct pixel format was accepted.");
    CVPixelBufferRelease(pixel);
    CVReturn status=CVPixelBufferCreate(kCFAllocatorDefault,16,16,kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,NULL,&pixel);
    Require(status==kCVReturnSuccess && pixel,@"Could not create the planar validation fixture.");
    Reject(pixel,0,@"A planar direct pixel buffer was accepted.");
    CVPixelBufferRelease(pixel);
    pixel=Pixel(&releases);
    {
        Fixture f; f.adaptor.rejectAppend=YES;
        Require([f.encoder appendPixelBuffer:pixel frameIndex:0]==ELMVAppendFailed &&
            f.encoder.acceptedVideoFrames==0 && f.encoder.failure.code==19,
            @"An adaptor rejection changed failure or frame accounting.");
    }
    CVPixelBufferRelease(pixel);
    Require(releases==4,@"Validation or failure leaked a producer-owned buffer.");
    NSUInteger pendingReleases=0;
    {
        Fixture f; f.input.readyForMoreMediaData=NO;
        pixel=Pixel(&pendingReleases);
        ELMVPixelFrame *pending=[[ELMVPixelFrame alloc] initWithPixelBuffer:pixel];
        CVPixelBufferRelease(pixel);
        Require([f.encoder appendPixelBuffer:pending.pixelBuffer frameIndex:0]==ELMVAppendRetry,@"Pending cancellation fixture did not retry.");
        [f.encoder cancel];
        Require(pendingReleases==0,@"Cancelling the encoder consumed the producer's pending-buffer ownership.");
        pending=nil;
        Require(pendingReleases==1,@"Clearing a cancelled pending frame leaked its buffer.");
    }
}
int main(void) {
    @autoreleasepool {
        fprintf(stderr,"MV pixel-buffer tests: main-thread validation\n");
        NSUInteger releases=0;
        CVPixelBufferRef pixel=Pixel(&releases);
        Reject(pixel,0,@"Main-thread direct append was accepted.");
        CVPixelBufferRelease(pixel);
        Require(releases==1,@"Main-thread rejection consumed or leaked producer ownership.");
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        dispatch_queue_t worker=dispatch_queue_create("mv-pixel-buffer-tests",DISPATCH_QUEUE_SERIAL);
        dispatch_async(worker,^{ @autoreleasepool {
            @try {
                fprintf(stderr,"MV pixel-buffer tests: direct identity, Retry and ownership\n");
                DirectIdentityRetryAndOwnership();
                fprintf(stderr,"MV pixel-buffer tests: invalid inputs and cancellation\n");
                ValidationAndFailure();
            } @catch (NSException *exception) {
                fprintf(stderr,"MV pixel-buffer test exception: %s\n%s\n",
                    exception.description.UTF8String,
                    [exception.callStackSymbols componentsJoinedByString:@"\n"].UTF8String);
                exit(1);
            }
            dispatch_semaphore_signal(done);
        }});
        Require(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))==0,@"Direct pixel-buffer tests exceeded their bounded deadline.");
        puts("PASS: direct pixel-buffer identity, unchanged payload/tags/PTS, Retry, validation, ownership and cancellation (recording adaptor; no codec or MV runtime proof)");
    }
    return 0;
}
