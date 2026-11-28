#import "ElichikaMVEncoder.h"
#import <AVFoundation/AVFoundation.h>
#import <AudioToolbox/AudioToolbox.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <VideoToolbox/VideoToolbox.h>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdio.h>

static NSString *const ELMVEncoderErrorDomain=@"ElichikaMVEncoder";
static NSError *ELMVError(NSInteger code, NSString *message, NSError *underlying=nil) {
    NSMutableDictionary *info=[@{NSLocalizedDescriptionKey:message} mutableCopy];
    if (underlying) info[NSUnderlyingErrorKey]=underlying;
    return [NSError errorWithDomain:ELMVEncoderErrorDomain code:code userInfo:info];
}

@implementation ELMVEncoderConfiguration
- (instancetype)init {
    if ((self=[super init])) {
        _width=1920; _height=1080; _fpsNumerator=30; _fpsDenominator=1;
        _codec=@"h264"; _videoBitRate=12000000;
        _audioSampleRate=48000; _audioChannels=2; _audioBitRate=192000;
    }
    return self;
}
- (id)copyWithZone:(NSZone *)zone {
    ELMVEncoderConfiguration *copy=[[[self class] allocWithZone:zone] init];
    copy.width=_width; copy.height=_height; copy.fpsNumerator=_fpsNumerator;
    copy.fpsDenominator=_fpsDenominator; copy.frameCount=_frameCount;
    copy.codec=_codec; copy.videoBitRate=_videoBitRate;
    copy.audioSampleRate=_audioSampleRate; copy.audioChannels=_audioChannels;
    copy.audioSampleCount=_audioSampleCount; copy.audioBitRate=_audioBitRate;
    return copy;
}
@end

@implementation ELMVPixelFrame {
    CVPixelBufferRef _pixelBuffer;
    NSUInteger _rowBytes;
}
- (instancetype)initWithPixelBuffer:(CVPixelBufferRef)pixelBuffer {
    if (!pixelBuffer) return nil;
    if ((self=[super init])) {
        _pixelBuffer=CVPixelBufferRetain(pixelBuffer);
        _rowBytes=CVPixelBufferGetBytesPerRow(pixelBuffer);
    }
    return self;
}
- (void)dealloc { if (_pixelBuffer) CVPixelBufferRelease(_pixelBuffer); }
- (CVPixelBufferRef)pixelBuffer { return _pixelBuffer; }
- (NSUInteger)rowBytes { return _rowBytes; }
@end

@interface ELMVEncoder () {
    AVAssetWriter *_writer;
    AVAssetWriterInput *_video;
    AVAssetWriterInput *_audio;
    AVAssetWriterInputPixelBufferAdaptor *_adaptor;
    CMAudioFormatDescriptionRef _pcmFormat;
    ELMVEncoderConfiguration *_configuration;
    int64_t _acceptedVideoFrames;
    int64_t _acceptedAudioSamples;
    NSError *_failure;
    NSString *_backpressureReason;
    NSURL *_outputURL;
    NSURL *_partialURL;
    BOOL _finishing;
    BOOL _completed;
    BOOL _videoFinished;
    BOOL _audioFinished;
    dispatch_queue_t _callbackQueue;
    void (^_completion)(NSURL *,NSError *);
}
- (void)failLocked:(NSError *)error;
- (void)deliverLocked:(NSURL *)output error:(NSError *)error;
- (ELMVAppendResult)appendPixelBufferLocked:(CVPixelBufferRef)pixel frameIndex:(int64_t)frameIndex;
@end

@implementation ELMVEncoder
- (void)dealloc {
    if (_pcmFormat) CFRelease(_pcmFormat);
    // Dropping an unfinished session cannot leave a partial export behind.
    if (!_completed) {
        [_writer cancelWriting];
        if (_partialURL) [NSFileManager.defaultManager removeItemAtURL:_partialURL error:NULL];
    }
}
- (int64_t)acceptedVideoFrames { @synchronized(self) { return _acceptedVideoFrames; } }
- (int64_t)acceptedAudioSamples { @synchronized(self) { return _acceptedAudioSamples; } }
- (NSError *)failure { @synchronized(self) { return _failure; } }
- (NSString *)backpressureReason { @synchronized(self) { return _backpressureReason; } }
- (NSString *)writerStatus {
    @synchronized(self) {
        switch (_writer.status) {
            case AVAssetWriterStatusUnknown: return @"unknown";
            case AVAssetWriterStatusWriting: return @"writing";
            case AVAssetWriterStatusCompleted: return @"completed";
            case AVAssetWriterStatusFailed: return @"failed";
            case AVAssetWriterStatusCancelled: return @"cancelled";
        }
    }
    return @"unrecognized";
}
- (NSURL *)outputURL { return _outputURL; }
- (NSURL *)partialURL { return _partialURL; }

+ (instancetype)encoderWithConfiguration:(ELMVEncoderConfiguration *)configuration
                               outputURL:(NSURL *)outputURL error:(NSError **)error {
    auto reject=[&](NSError *problem) -> ELMVEncoder * { if (error) *error=problem; return nil; };
    if (NSThread.isMainThread) return reject(ELMVError(1,@"Start MP4 encoding on the export worker, away from the UI thread."));
    ELMVEncoderConfiguration *c=[configuration copy];
    if (!c || ![@[@"h264",@"hevc"] containsObject:c.codec])
        return reject(ELMVError(2,@"Choose H.264 or HEVC for MP4 export."));
    if (c.width<16 || c.height<16 || c.width%2 || c.height%2 ||
#if defined(SIFAS_STANDALONE)
        c.width>INT32_MAX || c.height>INT32_MAX || c.width>NSUInteger(INT32_MAX)/4/c.height ||
#else
        c.width>7680 || c.height>4320 ||
#endif
        c.fpsNumerator<=0 || c.fpsDenominator<=0 ||
#if !defined(SIFAS_STANDALONE)
        (double)c.fpsNumerator/c.fpsDenominator>120 ||
#endif
        c.frameCount<=0 || c.frameCount>INT64_MAX/c.fpsDenominator ||
#if defined(SIFAS_STANDALONE)
        !c.videoBitRate || c.videoBitRate>NSUInteger(INT64_MAX) ||
#else
        c.videoBitRate<10000 || c.videoBitRate>200000000 ||
#endif
        (c.audioSampleRate!=44100 && c.audioSampleRate!=48000) ||
        (c.audioChannels!=1 && c.audioChannels!=2) || c.audioSampleCount<=0 ||
        c.audioBitRate<32000 || c.audioBitRate>512000)
        return reject(ELMVError(3,@"The MP4 dimensions, frame rate, duration or audio format are outside the supported limits."));
    CMTime duration=CMTimeMake(c.frameCount*c.fpsDenominator,c.fpsNumerator);
    CMTime audioEnd=CMTimeMake(c.audioSampleCount,c.audioSampleRate);
    // The final PCM sample may straddle the exact video boundary, by <1 sample.
    CMTime audioBeforeEnd=CMTimeMake(c.audioSampleCount-1,c.audioSampleRate);
    if (CMTimeCompare(audioEnd,duration)<0 || CMTimeCompare(audioBeforeEnd,duration)>=0)
        return reject(ELMVError(4,@"The PCM sample count must cover the exact video duration, rounded up to one audio sample."));
    if (!outputURL.isFileURL || !outputURL.path.isAbsolutePath ||
        ![outputURL.pathExtension.lowercaseString isEqual:@"mp4"])
        return reject(ELMVError(5,@"The export destination must be an absolute local MP4 file URL."));
    BOOL directory=NO;
    if (![NSFileManager.defaultManager fileExistsAtPath:outputURL.URLByDeletingLastPathComponent.path isDirectory:&directory] || !directory)
        return reject(ELMVError(6,@"The MP4 export folder does not exist."));
    if ([NSFileManager.defaultManager fileExistsAtPath:outputURL.path])
        return reject(ELMVError(7,@"An export already exists at this destination. Choose a new filename."));
    VTCompressionSessionRef codecProbe=NULL;
    OSStatus codecStatus=VTCompressionSessionCreate(kCFAllocatorDefault,(int32_t)c.width,(int32_t)c.height,
        [c.codec isEqual:@"hevc"] ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264,
        NULL,NULL,NULL,NULL,NULL,&codecProbe);
    if (codecProbe) { VTCompressionSessionInvalidate(codecProbe); CFRelease(codecProbe); }
    if (codecStatus!=noErr)
        return reject(ELMVError(27,[NSString stringWithFormat:@"The requested %@ encoder is unavailable on this device (%d).",c.codec,(int)codecStatus]));
    ELMVEncoder *encoder=[ELMVEncoder new]; encoder->_configuration=c; encoder->_outputURL=[outputURL copy];
    NSString *partialName=[NSString stringWithFormat:@".%@.%@.partial.mp4",outputURL.lastPathComponent,NSUUID.UUID.UUIDString];
    encoder->_partialURL=[outputURL.URLByDeletingLastPathComponent URLByAppendingPathComponent:partialName];
    NSError *problem=nil;
    encoder->_writer=[[AVAssetWriter alloc] initWithURL:encoder->_partialURL fileType:AVFileTypeMPEG4 error:&problem];
    if (!encoder->_writer) return reject(ELMVError(8,@"Could not create the MP4 file in the export folder.",problem));
    encoder->_writer.movieTimeScale=c.fpsNumerator;
    NSDictionary *videoSettings=@{
        AVVideoCodecKey:[c.codec isEqual:@"hevc"] ? AVVideoCodecTypeHEVC : AVVideoCodecTypeH264,
        AVVideoWidthKey:@(c.width), AVVideoHeightKey:@(c.height),
        AVVideoCompressionPropertiesKey:@{AVVideoAverageBitRateKey:@(c.videoBitRate),
            AVVideoExpectedSourceFrameRateKey:@((double)c.fpsNumerator/c.fpsDenominator),
            AVVideoAllowFrameReorderingKey:@NO},
        // Source is display-referred sRGB; make the transfer conversion explicit.
        AVVideoColorPropertiesKey:@{AVVideoColorPrimariesKey:AVVideoColorPrimaries_ITU_R_709_2,
            AVVideoTransferFunctionKey:AVVideoTransferFunction_ITU_R_709_2,
            AVVideoYCbCrMatrixKey:AVVideoYCbCrMatrix_ITU_R_709_2}};
    NSDictionary *audioSettings=@{AVFormatIDKey:@(kAudioFormatMPEG4AAC),
        AVSampleRateKey:@(c.audioSampleRate), AVNumberOfChannelsKey:@(c.audioChannels),
        AVEncoderBitRateKey:@(c.audioBitRate)};
    if (![encoder->_writer canApplyOutputSettings:videoSettings forMediaType:AVMediaTypeVideo])
        return reject(ELMVError(9,[NSString stringWithFormat:@"The requested %@ video format is unavailable for these dimensions and frame rate.",c.codec]));
    if (![encoder->_writer canApplyOutputSettings:audioSettings forMediaType:AVMediaTypeAudio])
        return reject(ELMVError(10,@"AAC encoding is unavailable for the requested PCM format."));
    encoder->_video=[AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo outputSettings:videoSettings];
    encoder->_audio=[AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeAudio outputSettings:audioSettings];
    encoder->_video.mediaTimeScale=c.fpsNumerator;
    // A framework-selected chunk may need a longer audio lead than the bounded
    // offline pump supplies. Request small chunks on both tracks so mux
    // interleaving cannot wait for a default multi-frame/second-sized chunk.
    encoder->_video.preferredMediaChunkDuration=CMTimeMake(1,10);
    encoder->_audio.preferredMediaChunkDuration=CMTimeMake(1,10);
    encoder->_video.expectsMediaDataInRealTime=NO; encoder->_audio.expectsMediaDataInRealTime=NO;
    if (![encoder->_writer canAddInput:encoder->_video] || ![encoder->_writer canAddInput:encoder->_audio])
        return reject(ELMVError(11,@"The MP4 writer could not attach its video and AAC tracks."));
    [encoder->_writer addInput:encoder->_video]; [encoder->_writer addInput:encoder->_audio];
    encoder->_adaptor=[AVAssetWriterInputPixelBufferAdaptor assetWriterInputPixelBufferAdaptorWithAssetWriterInput:encoder->_video
        sourcePixelBufferAttributes:@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
            (id)kCVPixelBufferWidthKey:@(c.width),(id)kCVPixelBufferHeightKey:@(c.height),
            (id)kCVPixelBufferIOSurfacePropertiesKey:@{}}];
    AudioStreamBasicDescription pcm={};
    pcm.mSampleRate=c.audioSampleRate; pcm.mFormatID=kAudioFormatLinearPCM;
    pcm.mFormatFlags=kLinearPCMFormatFlagIsSignedInteger|kLinearPCMFormatFlagIsPacked;
    pcm.mBytesPerPacket=(UInt32)c.audioChannels*2; pcm.mFramesPerPacket=1;
    pcm.mBytesPerFrame=pcm.mBytesPerPacket; pcm.mChannelsPerFrame=(UInt32)c.audioChannels; pcm.mBitsPerChannel=16;
    OSStatus formatStatus=CMAudioFormatDescriptionCreate(kCFAllocatorDefault,&pcm,0,NULL,0,NULL,NULL,&encoder->_pcmFormat);
    if (formatStatus!=noErr) return reject(ELMVError(12,[NSString stringWithFormat:@"Could not describe PCM audio (%d).",(int)formatStatus]));
    if (![encoder->_writer startWriting])
        return reject(ELMVError(13,@"The device could not start the requested video/AAC encoder.",encoder->_writer.error));
    [encoder->_writer startSessionAtSourceTime:kCMTimeZero];
    if (!encoder->_adaptor.pixelBufferPool) {
        [encoder failLocked:ELMVError(14,@"The video encoder did not create its bounded pixel-buffer pool.")];
        return reject(encoder.failure);
    }
    return encoder;
}

- (void)deliverLocked:(NSURL *)output error:(NSError *)error {
    void (^callback)(NSURL *,NSError *)=_completion;
    dispatch_queue_t queue=_callbackQueue;
    _completion=nil; _callbackQueue=nil;
    if (callback) dispatch_async(queue,^{ callback(output,error); });
}
- (void)failLocked:(NSError *)error {
    if (_completed) return;
    if (!_failure) _failure=error;
    [_writer cancelWriting];
    [NSFileManager.defaultManager removeItemAtURL:_partialURL error:NULL];
    [self deliverLocked:nil error:_failure];
}
- (BOOL)writableLocked {
    if (_failure || _completed || _finishing) return NO;
    if (_writer.status!=AVAssetWriterStatusWriting) {
        [self failLocked:ELMVError(15,@"MP4 encoding stopped before all samples were written.",_writer.error)]; return NO;
    }
    return YES;
}
- (ELMVAppendResult)appendPixelBufferLocked:(CVPixelBufferRef)pixel frameIndex:(int64_t)frameIndex {
    CVBufferSetAttachment(pixel,kCVImageBufferColorPrimariesKey,kCVImageBufferColorPrimaries_ITU_R_709_2,kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(pixel,kCVImageBufferTransferFunctionKey,kCVImageBufferTransferFunction_sRGB,kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(pixel,kCVImageBufferYCbCrMatrixKey,kCVImageBufferYCbCrMatrix_ITU_R_709_2,kCVAttachmentMode_ShouldPropagate);
    CMTime time=CMTimeMake(frameIndex*_configuration.fpsDenominator,_configuration.fpsNumerator);
    BOOL appended=[_adaptor appendPixelBuffer:pixel withPresentationTime:time];
    if (!appended) {
        [self failLocked:ELMVError(19,@"The video encoder rejected a complete rendered frame.",_writer.error)];
        return ELMVAppendFailed;
    }
    ++_acceptedVideoFrames; _backpressureReason=nil;
    if (_acceptedVideoFrames==_configuration.frameCount) { [_video markAsFinished]; _videoFinished=YES; }
    return ELMVAppendAccepted;
}
- (ELMVAppendResult)appendPixelBuffer:(CVPixelBufferRef)pixel frameIndex:(int64_t)frameIndex {
    @autoreleasepool {
    @synchronized(self) {
        if (![self writableLocked]) return ELMVAppendFailed;
        const size_t packed=_configuration.width*4;
        const size_t stride=pixel ? CVPixelBufferGetBytesPerRow(pixel) : 0;
        if (NSThread.isMainThread || frameIndex!=_acceptedVideoFrames || frameIndex>=_configuration.frameCount ||
            !pixel || CVPixelBufferIsPlanar(pixel) || CVPixelBufferGetPixelFormatType(pixel)!=kCVPixelFormatType_32BGRA ||
            CVPixelBufferGetWidth(pixel)!=_configuration.width || CVPixelBufferGetHeight(pixel)!=_configuration.height ||
            stride<packed || stride>SIZE_MAX/_configuration.height || CVPixelBufferGetDataSize(pixel)<stride*_configuration.height) {
            [self failLocked:ELMVError(16,@"A video pixel buffer had an invalid index, BGRA layout or dimensions, or arrived on the UI thread.")];
            return ELMVAppendFailed;
        }
        if (!_video.readyForMoreMediaData) { _backpressureReason=@"video-input-not-ready"; return ELMVAppendRetry; }
        return [self appendPixelBufferLocked:pixel frameIndex:frameIndex];
    }
    }
}
- (ELMVAppendResult)appendBGRA:(NSData *)data rowBytes:(NSUInteger)rowBytes frameIndex:(int64_t)frameIndex {
    @autoreleasepool {
    @synchronized(self) {
        if (![self writableLocked]) return ELMVAppendFailed;
        NSUInteger packed=_configuration.width*4;
        if (NSThread.isMainThread || frameIndex!=_acceptedVideoFrames || frameIndex>=_configuration.frameCount ||
            rowBytes<packed || rowBytes>NSUIntegerMax/_configuration.height || data.length<rowBytes*_configuration.height) {
            [self failLocked:ELMVError(16,@"A video frame had an invalid index, row stride or byte length, or arrived on the UI thread.")];
            return ELMVAppendFailed;
        }
        if (!_video.readyForMoreMediaData) { _backpressureReason=@"video-input-not-ready"; return ELMVAppendRetry; }
        CVPixelBufferRef pixel=NULL;
        CVReturn status=CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(kCFAllocatorDefault,_adaptor.pixelBufferPool,
            (__bridge CFDictionaryRef)@{(id)kCVPixelBufferPoolAllocationThresholdKey:@3},&pixel);
        if (status==kCVReturnWouldExceedAllocationThreshold) { _backpressureReason=@"three-video-buffers-retained"; return ELMVAppendRetry; }
        if (status!=kCVReturnSuccess || !pixel) {
            [self failLocked:ELMVError(17,[NSString stringWithFormat:@"Could not allocate a video buffer (%d).",(int)status])];
            return ELMVAppendFailed;
        }
        status=CVPixelBufferLockBaseAddress(pixel,0);
        if (status!=kCVReturnSuccess) {
            CVPixelBufferRelease(pixel);
            [self failLocked:ELMVError(18,@"Could not map the video buffer for its final rendered image.")]; return ELMVAppendFailed;
        }
        uint8_t *destination=(uint8_t *)CVPixelBufferGetBaseAddress(pixel);
        const uint8_t *source=(const uint8_t *)data.bytes;
        size_t destinationStride=CVPixelBufferGetBytesPerRow(pixel);
        // The BGRA contract already supplies the final opaque composite.
        for (NSUInteger y=0;y<_configuration.height;y++) {
            memcpy(destination+y*destinationStride,source+y*rowBytes,packed);
        }
        CVPixelBufferUnlockBaseAddress(pixel,0);
        ELMVAppendResult result=[self appendPixelBufferLocked:pixel frameIndex:frameIndex];
        CVPixelBufferRelease(pixel);
        return result;
    }
    }
}
- (ELMVAppendResult)appendPCM16:(NSData *)data firstSample:(int64_t)firstSample {
    @autoreleasepool {
    @synchronized(self) {
        if (![self writableLocked]) return ELMVAppendFailed;
        NSUInteger bytesPerFrame=_configuration.audioChannels*2;
        NSUInteger samples=data.length/bytesPerFrame;
        if (NSThread.isMainThread || firstSample!=_acceptedAudioSamples || !samples || samples>8192 ||
            data.length%bytesPerFrame || firstSample>_configuration.audioSampleCount ||
            samples>(uint64_t)(_configuration.audioSampleCount-firstSample)) {
            [self failLocked:ELMVError(20,@"A PCM chunk had an invalid sample index, byte length or size, or arrived on the UI thread.")];
            return ELMVAppendFailed;
        }
        if (!_audio.readyForMoreMediaData) { _backpressureReason=@"audio-input-not-ready"; return ELMVAppendRetry; }
        CMBlockBufferRef block=NULL; CMSampleBufferRef buffer=NULL;
        OSStatus status=CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault,NULL,data.length,kCFAllocatorDefault,NULL,0,data.length,0,&block);
        if (status==noErr) status=CMBlockBufferReplaceDataBytes(data.bytes,block,0,data.length);
        CMSampleTimingInfo timing={CMTimeMake(1,_configuration.audioSampleRate),CMTimeMake(firstSample,_configuration.audioSampleRate),kCMTimeInvalid};
        size_t sampleBytes=bytesPerFrame;
        if (status==noErr) status=CMSampleBufferCreateReady(kCFAllocatorDefault,block,_pcmFormat,samples,1,&timing,1,&sampleBytes,&buffer);
        if (block) CFRelease(block);
        if (status!=noErr || !buffer) {
            if (buffer) CFRelease(buffer);
            [self failLocked:ELMVError(21,[NSString stringWithFormat:@"Could not create a PCM audio sample buffer (%d).",(int)status])];
            return ELMVAppendFailed;
        }
        BOOL appended=[_audio appendSampleBuffer:buffer]; CFRelease(buffer);
        if (!appended) {
            [self failLocked:ELMVError(22,@"The AAC encoder rejected a PCM audio chunk.",_writer.error)]; return ELMVAppendFailed;
        }
        _acceptedAudioSamples+=(int64_t)samples; _backpressureReason=nil;
        if (_acceptedAudioSamples==_configuration.audioSampleCount) { [_audio markAsFinished]; _audioFinished=YES; }
        return ELMVAppendAccepted;
    }
    }
}
- (void)finishOnQueue:(dispatch_queue_t)callbackQueue completion:(void (^)(NSURL *,NSError *))completion {
    @synchronized(self) {
        if (_finishing || _completed) {
            NSError *problem=ELMVError(23,@"This MP4 export has already been finalized or is finishing.");
            dispatch_async(callbackQueue,^{ completion(nil,problem); }); return;
        }
        _callbackQueue=callbackQueue; _completion=[completion copy];
        if (_failure) { [self deliverLocked:nil error:_failure]; return; }
        if (NSThread.isMainThread || _acceptedVideoFrames!=_configuration.frameCount || _acceptedAudioSamples!=_configuration.audioSampleCount) {
            [self failLocked:ELMVError(24,@"MP4 finalization requires every planned video frame and PCM sample on the export worker.")]; return;
        }
        _finishing=YES;
        if (!_videoFinished) { [_video markAsFinished]; _videoFinished=YES; }
        if (!_audioFinished) { [_audio markAsFinished]; _audioFinished=YES; }
        [_writer endSessionAtSourceTime:CMTimeMake(_configuration.frameCount*_configuration.fpsDenominator,_configuration.fpsNumerator)];
        [_writer finishWritingWithCompletionHandler:^{
            @synchronized(self) {
                if (self->_failure) { [self deliverLocked:nil error:self->_failure]; return; }
                if (self->_writer.status!=AVAssetWriterStatusCompleted) {
                    [self failLocked:ELMVError(25,@"The MP4 writer could not finish the video and AAC tracks.",self->_writer.error)]; return;
                }
                if (renamex_np(self->_partialURL.fileSystemRepresentation,self->_outputURL.fileSystemRepresentation,RENAME_EXCL)!=0) {
                    NSError *underlying=[NSError errorWithDomain:NSPOSIXErrorDomain code:errno userInfo:nil];
                    [self failLocked:ELMVError(26,@"Could not publish the completed MP4 without replacing an existing file.",underlying)]; return;
                }
                self->_completed=YES; [self deliverLocked:self->_outputURL error:nil];
            }
        }];
    }
}
- (void)cancel { @synchronized(self) { [self failLocked:ELMVError(NSUserCancelledError,@"MV export was cancelled.")]; } }
@end

static BOOL ELMVLocalMP4(NSURL *url) {
    return url.isFileURL && url.path.isAbsolutePath && [url.pathExtension.lowercaseString isEqual:@"mp4"];
}

static AVURLAsset *ELMVCombinationAsset(NSURL *url) {
    return [AVURLAsset URLAssetWithURL:url options:@{AVURLAssetPreferPreciseDurationAndTimingKey:@YES}];
}

static id ELMVTrackFormat(AVAssetTrack *track) {
    NSArray *formats=track.formatDescriptions;
    return formats.count==1 ? formats.firstObject : nil;
}

static int32_t ELMVAACSampleRate(id description, UInt32 *channels) {
    CMFormatDescriptionRef format=(__bridge CMFormatDescriptionRef)description;
    if (!format || CMFormatDescriptionGetMediaSubType(format)!=kAudioFormatMPEG4AAC) return 0;
    const AudioStreamBasicDescription *audio=CMAudioFormatDescriptionGetStreamBasicDescription(format);
    if (!audio || (audio->mSampleRate!=44100 && audio->mSampleRate!=48000) ||
        (audio->mChannelsPerFrame!=1 && audio->mChannelsPerFrame!=2)) return 0;
    *channels=audio->mChannelsPerFrame;
    return (int32_t)audio->mSampleRate;
}

static BOOL ELMVTimeClose(CMTime a, CMTime b, CMTime tolerance) {
    return CMTIME_IS_NUMERIC(a) && CMTIME_IS_NUMERIC(b) &&
           CMTimeCompare(CMTimeAbsoluteValue(CMTimeSubtract(a,b)),tolerance)<=0;
}

static BOOL ELMVTrackSpans(AVAssetTrack *track, CMTime duration, CMTime tolerance) {
    CMTimeRange bounds=track.timeRange;
    if (!ELMVTimeClose(bounds.start,kCMTimeZero,tolerance) ||
        !ELMVTimeClose(CMTimeRangeGetEnd(bounds),duration,tolerance)) return NO;
    CMTime end=kCMTimeZero;
    BOOL hasMedia=NO;
    for (AVAssetTrackSegment *segment in track.segments) {
        CMTimeRange target=segment.timeMapping.target;
        if (!ELMVTimeClose(target.start,end,tolerance) || !CMTIME_IS_NUMERIC(target.duration) ||
            CMTimeCompare(target.duration,kCMTimeZero)<=0) return NO;
        if (segment.empty) {
            if (CMTimeCompare(target.duration,tolerance)>0) return NO;
        } else hasMedia=YES;
        end=CMTimeRangeGetEnd(target);
    }
    return hasMedia && ELMVTimeClose(end,duration,tolerance);
}

@interface ELMVMP4Combination () {
    NSArray<NSURL *> *_sources;
    NSURL *_outputURL;
    NSURL *_partialURL;
    dispatch_queue_t _workerQueue;
    dispatch_queue_t _callbackQueue;
    void (^_completion)(NSURL *,NSError *);
    AVAssetExportSession *_session;
    BOOL _cancelled;
    BOOL _finished;
}
- (instancetype)initWithSources:(NSArray<NSURL *> *)sources outputURL:(NSURL *)outputURL
                     workerQueue:(dispatch_queue_t)workerQueue callbackQueue:(dispatch_queue_t)callbackQueue
                      completion:(void (^)(NSURL *,NSError *))completion;
- (void)prepare;
- (void)complete:(NSError *)error;
@end

@implementation ELMVMP4Combination
+ (instancetype)combineSources:(NSArray<NSURL *> *)sources outputURL:(NSURL *)outputURL
                    workerQueue:(dispatch_queue_t)workerQueue callbackQueue:(dispatch_queue_t)callbackQueue
                     completion:(void (^)(NSURL *,NSError *))completion {
    ELMVMP4Combination *operation=[[self alloc] initWithSources:sources outputURL:outputURL
        workerQueue:workerQueue callbackQueue:callbackQueue completion:completion];
    dispatch_async(workerQueue,^{ [operation prepare]; });
    return operation;
}
- (instancetype)initWithSources:(NSArray<NSURL *> *)sources outputURL:(NSURL *)outputURL
                     workerQueue:(dispatch_queue_t)workerQueue callbackQueue:(dispatch_queue_t)callbackQueue
                      completion:(void (^)(NSURL *,NSError *))completion {
    if ((self=[super init])) {
        _sources=[sources copy]; _outputURL=[outputURL copy];
        _workerQueue=workerQueue; _callbackQueue=callbackQueue; _completion=[completion copy];
    }
    return self;
}
- (BOOL)isCancelled { @synchronized(self) { return _cancelled; } }
- (void)cancel {
    @synchronized(self) {
        if (_finished || _cancelled) return;
        _cancelled=YES;
    }
    dispatch_async(_workerQueue,^{ [self->_session cancelExport]; });
}
- (void)complete:(NSError *)error {
    void (^completion)(NSURL *,NSError *);
    @synchronized(self) {
        if (_finished) return;
        _finished=YES;
        if (_cancelled) error=ELMVError(NSUserCancelledError,@"Combining MP4s was cancelled.");
        if (!error && renamex_np(_partialURL.fileSystemRepresentation,_outputURL.fileSystemRepresentation,RENAME_EXCL)!=0) {
            NSError *underlying=[NSError errorWithDomain:NSPOSIXErrorDomain code:errno userInfo:nil];
            error=ELMVError(45,@"Could not publish the combined MP4 without replacing an existing file.",underlying);
        }
        completion=_completion; _completion=nil;
    }
    _session=nil;
    if (error && _partialURL) [NSFileManager.defaultManager removeItemAtURL:_partialURL error:NULL];
    dispatch_async(_callbackQueue,^{ completion(error ? nil : self->_outputURL,error); });
}
- (void)prepare {
    if (self.isCancelled) { [self complete:nil]; return; }
    if (NSThread.isMainThread) {
        [self complete:ELMVError(40,@"Start combining MP4s on the export worker, away from the UI thread.")]; return;
    }
    if (_sources.count<2 || _sources.count>100) {
        [self complete:ELMVError(40,@"Choose 2 to 100 completed MP4s to combine.")]; return;
    }
    NSFileManager *files=NSFileManager.defaultManager;
    NSURL *directory=_outputURL.URLByDeletingLastPathComponent;
    BOOL isDirectory=NO;
    if (!ELMVLocalMP4(_outputURL) ||
        ![files fileExistsAtPath:directory.path isDirectory:&isDirectory] || !isDirectory ||
        [files fileExistsAtPath:_outputURL.path]) {
        [self complete:ELMVError(40,@"Choose a new local MP4 destination in the export folder.")]; return;
    }
    AVMutableComposition *composition=[AVMutableComposition composition];
    AVMutableCompositionTrack *joinedVideo=[composition addMutableTrackWithMediaType:AVMediaTypeVideo
        preferredTrackID:kCMPersistentTrackID_Invalid];
    AVMutableCompositionTrack *joinedAudio=[composition addMutableTrackWithMediaType:AVMediaTypeAudio
        preferredTrackID:kCMPersistentTrackID_Invalid];
    if (!joinedVideo || !joinedAudio) {
        [self complete:ELMVError(41,@"Could not start the combined video and audio tracks.")]; return;
    }
    NSURL *destination=_outputURL.URLByResolvingSymlinksInPath;
    CMTime duration=kCMTimeZero;
    id expectedFormat=nil;
    float frameRate=0;
    CGAffineTransform transform=CGAffineTransformIdentity;
    UInt32 channels=0;
    int32_t sampleRate=0;
    for (NSURL *source in _sources) {
        if (self.isCancelled) { [self complete:nil]; return; }
        NSNumber *regular=nil;
        if (!ELMVLocalMP4(source) || [source.URLByResolvingSymlinksInPath isEqual:destination] ||
            ![source getResourceValue:&regular forKey:NSURLIsRegularFileKey error:NULL] || !regular.boolValue) {
            [self complete:ELMVError(41,@"A selected completed MP4 is missing or invalid.")]; return;
        }
        AVURLAsset *asset=ELMVCombinationAsset(source);
        NSArray<AVAssetTrack *> *videos=[asset tracksWithMediaType:AVMediaTypeVideo];
        NSArray<AVAssetTrack *> *audios=[asset tracksWithMediaType:AVMediaTypeAudio];
        if (!asset.composable || videos.count!=1 || audios.count!=1) {
            [self complete:ELMVError(41,@"Each completed MP4 must contain one video track and one AAC track.")]; return;
        }
        AVAssetTrack *video=videos[0], *audio=audios[0];
        id videoFormat=ELMVTrackFormat(video);
        FourCharCode codec=videoFormat ? CMFormatDescriptionGetMediaSubType((__bridge CMFormatDescriptionRef)videoFormat) : 0;
        UInt32 audioChannels=0;
        int32_t audioRate=ELMVAACSampleRate(ELMVTrackFormat(audio),&audioChannels);
        CMTimeRange videoRange=video.timeRange, audioRange=audio.timeRange;
        CMTime audioTolerance=CMTimeMake(1,audioRate ? audioRate : 1);
        if ((codec!=kCMVideoCodecType_H264 && codec!=kCMVideoCodecType_HEVC) ||
            !std::isfinite(video.nominalFrameRate) || video.nominalFrameRate<=0 || !audioRate ||
            !CMTIME_IS_NUMERIC(videoRange.duration) || CMTimeCompare(videoRange.duration,kCMTimeZero)<=0 ||
            !ELMVTrackSpans(video,videoRange.duration,kCMTimeZero) ||
            !ELMVTrackSpans(audio,videoRange.duration,audioTolerance)) {
            [self complete:ELMVError(41,@"A selected MP4 has unsupported encoding or incomplete video or audio timing.")]; return;
        }
        if (!expectedFormat) {
            expectedFormat=videoFormat; frameRate=video.nominalFrameRate; transform=video.preferredTransform;
            sampleRate=audioRate; channels=audioChannels;
            joinedVideo.preferredTransform=transform;
        } else if (!CMFormatDescriptionEqual((__bridge CMFormatDescriptionRef)expectedFormat,
                                             (__bridge CMFormatDescriptionRef)videoFormat) ||
                   frameRate!=video.nominalFrameRate || !CGAffineTransformEqualToTransform(transform,video.preferredTransform) ||
                   audioRate!=sampleRate || audioChannels!=channels) {
            [self complete:ELMVError(41,@"Combined MP4s need matching video codec, resolution, frame rate and audio format.")]; return;
        }
        CMTimeRange editedAudio=CMTimeRangeGetIntersection(videoRange,audioRange);
        // AVAssetTrack exposes the edited presentation range. Keep any AAC
        // priming and tail samples outside the requested clip timeline.
        NSError *error=nil;
        if (!CMTIMERANGE_IS_VALID(editedAudio) || CMTIMERANGE_IS_EMPTY(editedAudio) ||
            ![joinedVideo insertTimeRange:videoRange ofTrack:video atTime:duration error:&error] ||
            ![joinedAudio insertTimeRange:editedAudio ofTrack:audio atTime:CMTimeAdd(duration,editedAudio.start) error:&error]) {
            [self complete:ELMVError(42,@"Could not insert a selected clip's edited video and audio ranges.",error)]; return;
        }
        duration=CMTimeAdd(duration,videoRange.duration);
    }
    if (self.isCancelled) { [self complete:nil]; return; }
    _session=[[AVAssetExportSession alloc] initWithAsset:composition presetName:AVAssetExportPresetPassthrough];
    if (![_session.supportedFileTypes containsObject:AVFileTypeMPEG4]) {
        [self complete:ELMVError(43,@"The system could not combine these tracks into an MP4 without re-encoding.")]; return;
    }
    _partialURL=[directory URLByAppendingPathComponent:[NSString stringWithFormat:@".combine-%@.mp4",NSUUID.UUID.UUIDString]];
    _session.outputURL=_partialURL; _session.outputFileType=AVFileTypeMPEG4;
    _session.timeRange=CMTimeRangeMake(kCMTimeZero,duration);
    CMVideoDimensions dimensions=CMVideoFormatDescriptionGetDimensions((__bridge CMFormatDescriptionRef)expectedFormat);
    FourCharCode codec=CMFormatDescriptionGetMediaSubType((__bridge CMFormatDescriptionRef)expectedFormat);
    [_session exportAsynchronouslyWithCompletionHandler:^{
        dispatch_async(self->_workerQueue,^{
            if (self.isCancelled) { [self complete:nil]; return; }
            if (self->_session.status!=AVAssetExportSessionStatusCompleted) {
                [self complete:ELMVError(43,@"The system could not finish combining the MP4s.",self->_session.error)]; return;
            }
            AVURLAsset *result=ELMVCombinationAsset(self->_partialURL);
            NSArray<AVAssetTrack *> *videos=[result tracksWithMediaType:AVMediaTypeVideo];
            NSArray<AVAssetTrack *> *audios=[result tracksWithMediaType:AVMediaTypeAudio];
            id format=ELMVTrackFormat(videos.firstObject);
            UInt32 outputChannels=0;
            CMVideoDimensions outputSize=format ? CMVideoFormatDescriptionGetDimensions((__bridge CMFormatDescriptionRef)format) : CMVideoDimensions{};
            float outputFrameRate=videos.firstObject.nominalFrameRate;
            if (!result.playable || videos.count!=1 || audios.count!=1 || !format ||
                CMFormatDescriptionGetMediaSubType((__bridge CMFormatDescriptionRef)format)!=codec ||
                outputSize.width!=dimensions.width || outputSize.height!=dimensions.height ||
                !std::isfinite(outputFrameRate) || std::fabs(outputFrameRate-frameRate)>0.001f ||
                !CGAffineTransformEqualToTransform(transform,videos[0].preferredTransform) ||
                ELMVAACSampleRate(ELMVTrackFormat(audios[0]),&outputChannels)!=sampleRate || outputChannels!=channels ||
                !ELMVTrackSpans(videos[0],duration,kCMTimeZero) ||
                !ELMVTrackSpans(audios[0],duration,CMTimeMake(1,sampleRate))) {
                [self complete:ELMVError(44,@"The combined MP4 did not preserve the expected audio and video timeline.")]; return;
            }
            [self complete:nil];
        });
    }];
}
@end
