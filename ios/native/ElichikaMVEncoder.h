#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, ELMVAppendResult) {
    ELMVAppendAccepted,
    ELMVAppendRetry,
    ELMVAppendFailed,
};

// Only H.264 and HEVC are accepted. There is deliberately no fallback to a
// different codec when the requested format is unavailable.
@interface ELMVEncoderConfiguration : NSObject <NSCopying>
@property(nonatomic) NSUInteger width;
@property(nonatomic) NSUInteger height;
@property(nonatomic) int32_t fpsNumerator;
@property(nonatomic) int32_t fpsDenominator;
@property(nonatomic) int64_t frameCount;
@property(nonatomic,copy) NSString *codec; // @"h264" or @"hevc"
@property(nonatomic) NSUInteger videoBitRate;
@property(nonatomic) int32_t audioSampleRate; // 44100 or 48000
@property(nonatomic) NSUInteger audioChannels; // 1 or 2
@property(nonatomic) int64_t audioSampleCount; // sample frames, including all channels
@property(nonatomic) NSUInteger audioBitRate;
@end

// Retains one final rendered buffer across the renderer/worker handoff. The
// producer must unlock it before handoff and keep its pixels immutable until
// the frame is released. The adaptor retains accepted buffers independently.
@interface ELMVPixelFrame : NSObject
@property(nonatomic,readonly) CVPixelBufferRef pixelBuffer;
@property(nonatomic,readonly) NSUInteger rowBytes;
- (nullable instancetype)initWithPixelBuffer:(CVPixelBufferRef)pixelBuffer NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

// Confine create/append/finish/cancel to one serial non-main worker. No method
// waits for encoder readiness. A Retry consumes neither bytes nor an index:
// retain that frame/chunk and yield before trying again. Independently attempt
// both tracks: the writer's readiness determines demand. A video-relative audio
// lead limit can starve the muxer even while its audio input requests more data.
@interface ELMVEncoder : NSObject
@property(nonatomic,readonly) int64_t acceptedVideoFrames;
@property(nonatomic,readonly) int64_t acceptedAudioSamples;
@property(nonatomic,readonly,nullable) NSError *failure;
@property(nonatomic,readonly,nullable) NSString *backpressureReason;
@property(nonatomic,readonly) NSString *writerStatus;
@property(nonatomic,readonly) NSURL *outputURL;
@property(nonatomic,readonly) NSURL *partialURL;

// The parent directory must already exist. Existing output is never replaced.
// Validate app-storage containment in the host before passing an output URL.
+ (nullable instancetype)encoderWithConfiguration:(ELMVEncoderConfiguration *)configuration
                                        outputURL:(NSURL *)outputURL
                                            error:(NSError **)error;

// BGRA8, top-to-bottom rows, opaque SDR sRGB/Rec.709 primaries. The renderer
// resolves its complete final image and converts linear output to sRGB first.
- (ELMVAppendResult)appendBGRA:(NSData *)data
                    rowBytes:(NSUInteger)rowBytes
                  frameIndex:(int64_t)frameIndex;

// Same final-image contract as appendBGRA, without copying the image. Supply an
// unlocked, nonplanar BGRA8 buffer matching the configured dimensions. Retain
// and keep it immutable on Retry; the adaptor retains it after acceptance.
- (ELMVAppendResult)appendPixelBuffer:(CVPixelBufferRef)pixelBuffer
                         frameIndex:(int64_t)frameIndex;

// Interleaved signed 16-bit little-endian PCM. Maximum 8192 sample frames per
// call. firstSample and frameIndex must each be contiguous from zero.
- (ELMVAppendResult)appendPCM16:(NSData *)data firstSample:(int64_t)firstSample;

// Counts must exactly match configuration. Callback runs on callbackQueue.
// Success publishes the completed MP4 with an exclusive, atomic rename.
- (void)finishOnQueue:(dispatch_queue_t)callbackQueue
          completion:(void (^)(NSURL * _Nullable output, NSError * _Nullable error))completion;
- (void)cancel;
@end

NS_ASSUME_NONNULL_END
