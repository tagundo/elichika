// Standalone Apple SDK/runtime test of the production encoder. This synthetic
// pattern proves encoding/muxing; it does not prove SIFAS rendering or audio.
#import "ElichikaMVEncoder.h"
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#include "MVPixelBufferPool.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <chrono>
#include <vector>

static void Require(BOOL condition, NSString *message) {
    if (!condition) { fprintf(stderr,"MV encoder integration failed: %s\n",message.UTF8String); exit(1); }
}
static void Yield(void) { std::this_thread::sleep_for(std::chrono::milliseconds(2)); }
static ELMVEncoderConfiguration *Configuration(NSString *codec) {
    ELMVEncoderConfiguration *c=[ELMVEncoderConfiguration new];
    c.width=160; c.height=96; c.fpsNumerator=30000; c.fpsDenominator=1001;
    c.frameCount=90; c.videoBitRate=2000000; c.codec=codec;
    c.audioSampleRate=48000; c.audioChannels=2; c.audioBitRate=128000;
    c.audioSampleCount=(c.frameCount*c.fpsDenominator*c.audioSampleRate+c.fpsNumerator-1)/c.fpsNumerator;
    return c;
}
static NSData *Frame(ELMVEncoderConfiguration *c,int64_t index) {
    // Include row padding to exercise the real input stride contract.
    NSUInteger stride=c.width*4+16;
    NSMutableData *data=[NSMutableData dataWithLength:stride*c.height];
    uint8_t *pixels=(uint8_t *)data.mutableBytes;
    NSUInteger movingX=(NSUInteger)(index*3)%(c.width-20);
    for (NSUInteger y=0;y<c.height;y++) for (NSUInteger x=0;x<c.width;x++) {
        uint8_t *pixel=pixels+y*stride+x*4;
        pixel[0]=y<c.height/2 ? 10 : 220;
        pixel[1]=10; pixel[2]=y<c.height/2 ? 220 : 10; pixel[3]=255;
        if (x>=movingX && x<movingX+20) { pixel[0]=10; pixel[1]=220; pixel[2]=10; }
    }
    return data;
}
#if defined(ELMV_TEST_DIRECT_INPUT)
static ELMVPixelFrame *DirectFrame(ELMVEncoderConfiguration *c,int64_t index,elichika::MVPixelBufferPool &pool) {
    CVPixelBufferRef pixel=nullptr;CVReturn status=pool.acquire(&pixel);
    if(status==kCVReturnWouldExceedAllocationThreshold)return nil;
    Require(status==kCVReturnSuccess&&pixel,@"Direct input pool allocation failed.");
    ELMVPixelFrame *frame=[[ELMVPixelFrame alloc]initWithPixelBuffer:pixel];CVPixelBufferRelease(pixel);
    Require(frame!=nil,@"Direct input frame could not retain its buffer.");
    NSData *reference=Frame(c,index);elichika::MVPixelBufferLock locked(frame.pixelBuffer);
    Require(locked.locked(),@"Direct input could not map its buffer.");
    uint8_t *destination=(uint8_t *)CVPixelBufferGetBaseAddress(frame.pixelBuffer);
    for(NSUInteger y=0;y<c.height;y++)memcpy(destination+y*frame.rowBytes,(const uint8_t *)reference.bytes+y*(c.width*4+16),c.width*4);
    return frame;
}
#endif
static NSData *Audio(ELMVEncoderConfiguration *c,int64_t first,NSUInteger count) {
    NSMutableData *data=[NSMutableData dataWithLength:count*c.audioChannels*2];
    int16_t *pcm=(int16_t *)data.mutableBytes;
    for (NSUInteger n=0;n<count;n++) {
        double t=(double)(first+(int64_t)n)/c.audioSampleRate;
        int16_t sample=t<0.25 ? 0 : (int16_t)lrint(16000*sin(2*M_PI*440*t));
        for (NSUInteger channel=0;channel<c.audioChannels;channel++) pcm[n*c.audioChannels+channel]=sample;
    }
    return data;
}
static NSDictionary *Inspect(NSURL *url,ELMVEncoderConfiguration *c) {
    AVURLAsset *asset=[AVURLAsset URLAssetWithURL:url options:@{AVURLAssetPreferPreciseDurationAndTimingKey:@YES}];
    NSArray<AVAssetTrack *> *videos=[asset tracksWithMediaType:AVMediaTypeVideo];
    NSArray<AVAssetTrack *> *audios=[asset tracksWithMediaType:AVMediaTypeAudio];
    Require(videos.count==1 && audios.count==1,@"The MP4 must contain one video track and one AAC track.");
    FourCharCode wanted=[c.codec isEqual:@"h264"] ? kCMVideoCodecType_H264 : kCMVideoCodecType_HEVC;
    Require(CMFormatDescriptionGetMediaSubType((__bridge CMFormatDescriptionRef)videos[0].formatDescriptions[0])==wanted,@"The completed track changed the requested video codec.");
    Require(CMFormatDescriptionGetMediaSubType((__bridge CMFormatDescriptionRef)audios[0].formatDescriptions[0])==kAudioFormatMPEG4AAC,@"The completed audio track is not AAC.");
    CMTime duration=CMTimeMake(c.frameCount*c.fpsDenominator,c.fpsNumerator);
    Require(CMTimeCompare(videos[0].timeRange.duration,duration)==0,@"The video duration changed its exact rational endpoint.");
    NSError *error=nil;
    AVAssetReader *videoReader=[[AVAssetReader alloc] initWithAsset:asset error:&error];
    Require(videoReader!=nil,error.localizedDescription);
    AVAssetReaderTrackOutput *videoOutput=[AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:videos[0]
        outputSettings:@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA)}];
    videoOutput.alwaysCopiesSampleData=NO; [videoReader addOutput:videoOutput];
    Require([videoReader startReading],videoReader.error.localizedDescription);
    int64_t frames=0;
    while (CMSampleBufferRef sample=[videoOutput copyNextSampleBuffer]) {
        CMTime expected=CMTimeMake(frames*c.fpsDenominator,c.fpsNumerator);
        Require(CMTimeCompare(CMSampleBufferGetPresentationTimeStamp(sample),expected)==0,@"A video presentation timestamp was duplicated, skipped or rounded.");
        CVPixelBufferRef pixel=CMSampleBufferGetImageBuffer(sample);
        Require(pixel && CVPixelBufferGetWidth(pixel)==c.width && CVPixelBufferGetHeight(pixel)==c.height,@"The decoded image dimensions changed.");
        Require(CVPixelBufferLockBaseAddress(pixel,kCVPixelBufferLock_ReadOnly)==kCVReturnSuccess,@"Could not inspect the decoded video pixels.");
        const uint8_t *base=(const uint8_t *)CVPixelBufferGetBaseAddress(pixel);
        size_t stride=CVPixelBufferGetBytesPerRow(pixel);
        NSUInteger movingX=(NSUInteger)(frames*3)%(c.width-20);
        const uint8_t *bar=base+(c.height/4)*stride+(movingX+10)*4;
        Require(bar[1]>120 && bar[1]>bar[0]*2 && bar[1]>bar[2]*2,@"A moving bar was dropped, repeated or rendered at the wrong frame.");
        NSInteger greenStart=-1,greenEnd=-1;
        for (NSUInteger x=0;x<c.width;x++) {
            const uint8_t *p=base+(c.height/4)*stride+x*4;
            if (p[1]>100 && p[1]>p[0]*1.5 && p[1]>p[2]*1.5) {
                if (greenStart<0) greenStart=(NSInteger)x;
                greenEnd=(NSInteger)x;
            }
        }
        Require(labs(greenStart-(NSInteger)movingX)<=1 && labs(greenEnd-(NSInteger)(movingX+19))<=1,@"Decoded motion boundaries do not match this exact frame index.");
        NSUInteger backgroundX=movingX+20<c.width-10 ? c.width-10 : 10;
        const uint8_t *top=base+(c.height/4)*stride+backgroundX*4;
        const uint8_t *bottom=base+(c.height*3/4)*stride+backgroundX*4;
        Require(top[2]>120 && top[2]>top[0]*2 && bottom[0]>120 && bottom[0]>bottom[2]*2,@"The final image was flipped or its color channels were swapped.");
        CVPixelBufferUnlockBaseAddress(pixel,kCVPixelBufferLock_ReadOnly);
        CFRelease(sample); ++frames;
    }
    Require(videoReader.status==AVAssetReaderStatusCompleted,videoReader.error.localizedDescription ?: @"Video decode did not complete.");
    Require(frames==c.frameCount,@"The decoded video frame count does not match the plan.");
    AVAssetReader *audioReader=[[AVAssetReader alloc] initWithAsset:asset error:&error];
    Require(audioReader!=nil,error.localizedDescription);
    AVAssetReaderTrackOutput *audioOutput=[AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:audios[0]
        outputSettings:@{AVFormatIDKey:@(kAudioFormatLinearPCM),AVLinearPCMBitDepthKey:@16,
            AVLinearPCMIsFloatKey:@NO,AVLinearPCMIsBigEndianKey:@NO,AVLinearPCMIsNonInterleaved:@NO}];
    [audioReader addOutput:audioOutput]; Require([audioReader startReading],audioReader.error.localizedDescription);
    int64_t samples=0; double quietEnergy=0,toneEnergy=0; NSUInteger quietCount=0,toneCount=0;
    double onset=-1;
    CMTime lastEnd=kCMTimeZero;
    while (CMSampleBufferRef sample=[audioOutput copyNextSampleBuffer]) {
        CMTime time=CMSampleBufferGetPresentationTimeStamp(sample);
        Require(CMTimeCompare(time,lastEnd)>=0,@"AAC decode produced overlapping presentation times.");
        CMBlockBufferRef block=CMSampleBufferGetDataBuffer(sample);
        size_t bytes=CMBlockBufferGetDataLength(block);
        Require(bytes<=1024*1024 && bytes%(c.audioChannels*2)==0,@"Decoded audio sample size is invalid.");
        NSMutableData *data=[NSMutableData dataWithLength:bytes];
        Require(CMBlockBufferCopyDataBytes(block,0,bytes,data.mutableBytes)==noErr,@"Could not read decoded AAC samples.");
        const int16_t *pcm=(const int16_t *)data.bytes;
        NSUInteger count=bytes/(c.audioChannels*2);
        for (NSUInteger n=0;n<count;n++) {
            double t=CMTimeGetSeconds(time)+(double)n/c.audioSampleRate;
            double value=(double)pcm[n*c.audioChannels]/32768;
            if (onset<0 && t>=0.20 && fabs(value)>0.10) onset=t;
            if (t>=0 && t<0.20) { quietEnergy+=value*value; ++quietCount; }
            if (t>=0.5 && t<2.5) { toneEnergy+=value*value; ++toneCount; }
        }
        samples+=(int64_t)count; lastEnd=CMTimeAdd(time,CMTimeMake(count,c.audioSampleRate));
        CFRelease(sample);
    }
    Require(audioReader.status==AVAssetReaderStatusCompleted,audioReader.error.localizedDescription ?: @"AAC decode did not complete.");
    Require(quietCount>0 && toneCount>0 && sqrt(quietEnergy/quietCount)<0.03 && sqrt(toneEnergy/toneCount)>0.20,@"AAC audio was silent, misaligned or corrupted.");
    Require(onset>=0 && fabs(onset-0.25)<(double)c.fpsDenominator/c.fpsNumerator,@"AAC onset shifted by at least one video frame.");
    // AAC packet padding and priming are represented by the MP4 edit list.
    // Require the audible track endpoint, and allow at most one decoded packet
    // of padding when a reader exposes samples outside that edit boundary.
    Require(fabs(CMTimeGetSeconds(audios[0].timeRange.duration)-CMTimeGetSeconds(duration))<=1.0/c.audioSampleRate,@"The AAC track does not align to the planned video duration.");
    Require(llabs(samples-c.audioSampleCount)<=1024,@"AAC decode gained or lost more than one padding packet.");
    return @{ @"codec":c.codec,@"frames":@(frames),@"decoded_audio_samples":@(samples),
        @"planned_audio_samples":@(c.audioSampleCount),@"rational_pts_verified":@YES,
        @"moving_pixels_and_orientation_verified":@YES,@"aac_onset_and_tone_verified":@YES };
}
static NSDictionary *Encode(NSURL *directory,NSString *codec,BOOL required) {
    ELMVEncoderConfiguration *c=Configuration(codec);
    NSURL *url=[directory URLByAppendingPathComponent:[codec stringByAppendingPathExtension:@"mp4"]];
    NSError *error=nil;
    ELMVEncoder *encoder=[ELMVEncoder encoderWithConfiguration:c outputURL:url error:&error];
    BOOL codecUnavailable=[error.domain isEqual:@"ElichikaMVEncoder"] && (error.code==9 || error.code==27);
    if (!encoder && !required && codecUnavailable)
        return @{ @"codec":codec,@"status":@"UNAVAILABLE",@"error":error.localizedDescription,
            @"error_domain":error.domain,@"error_code":@(error.code) };
    Require(encoder!=nil,error.localizedDescription);
    auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(45);
    NSUInteger retries=0;
    int64_t maximumAudioLead=0;
#if defined(ELMV_TEST_DIRECT_INPUT)
    elichika::MVPixelBufferPool pool;Require(pool.create((uint32_t)c.width,(uint32_t)c.height)==kCVReturnSuccess,@"Direct input pool creation failed.");
    ELMVPixelFrame *pixels=nil;
#else
    NSData *pixels=nil;
#endif
    NSData *pcm=nil;
    NSString *videoRetry=nil; NSString *audioRetry=nil;
    while (encoder.acceptedVideoFrames<c.frameCount || encoder.acceptedAudioSamples<c.audioSampleCount) {
        @autoreleasepool {
            BOOL progressed=NO;
            int64_t frame=encoder.acceptedVideoFrames;
            // Each input advertises its own demand. A video-relative lead cap
            // starves AAC/mux interleaving despite audio.ready remaining true.
            // Keep only one PCM chunk and one final image in the producer;
            // append Retry is the backpressure signal for either track.
            int64_t audioEnd=c.audioSampleCount;
            if (frame<c.frameCount) {
#if defined(ELMV_TEST_DIRECT_INPUT)
                if (!pixels) pixels=DirectFrame(c,frame,pool);
                ELMVAppendResult result=pixels ? [encoder appendPixelBuffer:pixels.pixelBuffer frameIndex:frame] : ELMVAppendRetry;
#else
                if (!pixels) pixels=Frame(c,frame);
                ELMVAppendResult result=[encoder appendBGRA:pixels rowBytes:c.width*4+16 frameIndex:frame];
#endif
                Require(result!=ELMVAppendFailed,encoder.failure.localizedDescription);
                if (result==ELMVAppendAccepted) {
                    pixels=nil; progressed=YES; videoRetry=nil;
                    // A slow producer must not change the planned timestamps.
                    if (frame%7==0) std::this_thread::sleep_for(std::chrono::milliseconds(5));
                } else {
                    ++retries; videoRetry=encoder.backpressureReason;
                    Require(encoder.acceptedVideoFrames==frame,@"Retry consumed a frame index.");
                }
            }
            int64_t first=encoder.acceptedAudioSamples;
            if (first<audioEnd) {
                if (!pcm) pcm=Audio(c,first,(NSUInteger)MIN((int64_t)8192,audioEnd-first));
                ELMVAppendResult result=[encoder appendPCM16:pcm firstSample:first];
                Require(result!=ELMVAppendFailed,encoder.failure.localizedDescription);
                if (result==ELMVAppendAccepted) { pcm=nil; progressed=YES; audioRetry=nil; }
                else {
                    ++retries; audioRetry=encoder.backpressureReason;
                    Require(encoder.acceptedAudioSamples==first,@"Retry consumed PCM samples.");
                }
            }
            int64_t videoSamples=(encoder.acceptedVideoFrames*c.fpsDenominator*c.audioSampleRate+c.fpsNumerator-1)/c.fpsNumerator;
            maximumAudioLead=MAX(maximumAudioLead,encoder.acceptedAudioSamples-videoSamples);
            Require(std::chrono::steady_clock::now()<deadline,
                [NSString stringWithFormat:@"Writer stalled: codec=%@ status=%@ frames=%lld/%lld audio=%lld/%lld maxAudioLead=%lld videoRetry=%@ audioRetry=%@.",
                    codec,encoder.writerStatus,(long long)encoder.acceptedVideoFrames,(long long)c.frameCount,
                    (long long)encoder.acceptedAudioSamples,(long long)c.audioSampleCount,(long long)maximumAudioLead,videoRetry,audioRetry]);
            if (!progressed) Yield();
        }
    }
#if defined(ELMV_TEST_DIRECT_INPUT)
    pool.reset(); // Accepted writer buffers must survive producer-pool teardown.
#endif
    dispatch_semaphore_t finished=dispatch_semaphore_create(0);
    __block NSURL *completed=nil; __block NSError *finishError=nil;
    [encoder finishOnQueue:dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0) completion:^(NSURL *output,NSError *problem) {
        completed=output; finishError=problem; dispatch_semaphore_signal(finished);
    }];
    Require(dispatch_semaphore_wait(finished,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC))==0,@"MP4 finalization exceeded its test deadline.");
    Require(completed!=nil && !finishError,finishError.localizedDescription ?: @"MP4 finalization returned no file.");
    Require(![NSFileManager.defaultManager fileExistsAtPath:encoder.partialURL.path],@"Successful export left its partial file.");
    NSMutableDictionary *report=[Inspect(completed,c) mutableCopy];
#if defined(ELMV_TEST_DIRECT_INPUT)
    report[@"input_path"]=@"direct-pooled-CVPixelBuffer";
#endif
    report[@"status"]=@"PASS"; report[@"retry_count"]=@(retries);
    report[@"maximum_audio_lead_samples"]=@(maximumAudioLead);
    report[@"writer_status"]=encoder.writerStatus;
    // Existing completed output must survive cancellation/recreation attempts.
    Require(![ELMVEncoder encoderWithConfiguration:c outputURL:url error:&error],@"An existing MP4 was accepted for overwrite.");
    [encoder cancel]; Require([NSFileManager.defaultManager fileExistsAtPath:url.path],@"Cancel removed a completed MP4.");
    return report;
}
static void CancellationAndErrors(NSURL *directory) {
    ELMVEncoderConfiguration *c=Configuration(@"h264"); NSError *error=nil;
    NSURL *url=[directory URLByAppendingPathComponent:@"cancel.mp4"];
    ELMVEncoder *encoder=[ELMVEncoder encoderWithConfiguration:c outputURL:url error:&error];
    Require(encoder!=nil,error.localizedDescription);
    [encoder cancel]; [encoder cancel];
    Require(![NSFileManager.defaultManager fileExistsAtPath:encoder.partialURL.path] &&
            ![NSFileManager.defaultManager fileExistsAtPath:url.path],@"Cancellation left a partial or published MP4.");
    c.codec=@"unsupported";
    Require(![ELMVEncoder encoderWithConfiguration:c outputURL:url error:&error],@"An unsupported codec was accepted.");
    c.codec=@"h264";
    encoder=[ELMVEncoder encoderWithConfiguration:c outputURL:url error:&error]; Require(encoder!=nil,error.localizedDescription);
    Require([encoder appendBGRA:Frame(c,0) rowBytes:c.width*4+16 frameIndex:1]==ELMVAppendFailed,@"An out-of-order frame was accepted.");
    Require(![NSFileManager.defaultManager fileExistsAtPath:encoder.partialURL.path],@"A rejected sample left a partial MP4.");
}

static NSURL *EncodeCombinationClip(NSURL *directory, ELMVEncoderConfiguration *configuration,
                                    NSString *name, BOOL red, double tone) {
    NSURL *url=[directory URLByAppendingPathComponent:name];
    NSError *error=nil;
    ELMVEncoder *encoder=[ELMVEncoder encoderWithConfiguration:configuration outputURL:url error:&error];
    Require(encoder!=nil,error.localizedDescription);
    NSUInteger stride=configuration.width*4;
    NSMutableData *pixels=[NSMutableData dataWithLength:stride*configuration.height];
    uint8_t *pixel=(uint8_t *)pixels.mutableBytes;
    for (NSUInteger offset=0;offset<pixels.length;offset+=4) {
        pixel[offset]=red ? 10 : 220;
        pixel[offset+1]=10;
        pixel[offset+2]=red ? 220 : 10;
        pixel[offset+3]=255;
    }
    NSMutableData *audio=[NSMutableData dataWithLength:(NSUInteger)configuration.audioSampleCount*4];
    int16_t *pcm=(int16_t *)audio.mutableBytes;
    for (int64_t sample=0;sample<configuration.audioSampleCount;sample++) {
        int16_t value=(int16_t)lrint(14000*sin(2*M_PI*tone*sample/configuration.audioSampleRate));
        pcm[2*sample]=value; pcm[2*sample+1]=value;
    }
    auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(20);
    while (encoder.acceptedVideoFrames<configuration.frameCount || encoder.acceptedAudioSamples<configuration.audioSampleCount) {
        ELMVAppendResult video=ELMVAppendRetry, sound=ELMVAppendRetry;
        int64_t frame=encoder.acceptedVideoFrames, sample=encoder.acceptedAudioSamples;
        if (frame<configuration.frameCount) video=[encoder appendBGRA:pixels rowBytes:stride frameIndex:frame];
        if (sample<configuration.audioSampleCount) {
            NSUInteger count=(NSUInteger)MIN((int64_t)4096,configuration.audioSampleCount-sample);
            NSData *chunk=[audio subdataWithRange:NSMakeRange((NSUInteger)sample*4,count*4)];
            sound=[encoder appendPCM16:chunk firstSample:sample];
        }
        Require(video!=ELMVAppendFailed && sound!=ELMVAppendFailed,encoder.failure.localizedDescription);
        Require(std::chrono::steady_clock::now()<deadline,@"Combination source encoder stalled.");
        if (video==ELMVAppendRetry && sound==ELMVAppendRetry) Yield();
    }
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    __block NSURL *finished=nil;
    __block NSError *failure=nil;
    [encoder finishOnQueue:dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0) completion:^(NSURL *output,NSError *problem) {
        finished=output; failure=problem; dispatch_semaphore_signal(done);
    }];
    Require(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC))==0,@"Combination source did not finish.");
    Require([finished isEqual:url] && !failure,failure.localizedDescription ?: @"Combination source output did not match.");
    return finished;
}

static int64_t AudioIndex(CMTime time, int32_t rate) {
    Require(CMTIME_IS_NUMERIC(time),@"The combined AAC stream has invalid timing.");
    return CMTimeConvertScale(time,rate,kCMTimeRoundingMethod_RoundHalfAwayFromZero).value;
}

static int64_t AudioTrim(CMSampleBufferRef sample, CFStringRef key, int32_t rate) {
    CFTypeRef value=CMGetAttachment(sample,key,NULL);
    if (!value) return 0;
    Require(CFGetTypeID(value)==CFDictionaryGetTypeID(),@"Invalid AAC trim attachment.");
    return AudioIndex(CMTimeMakeFromDictionary((CFDictionaryRef)value),rate);
}

static double ToneEnergy(const std::vector<int16_t> &audio, int64_t start, int32_t rate, double frequency) {
    double real=0, imaginary=0;
    int32_t size=rate/100;
    for (int32_t sample=0;sample<size;sample++) {
        double phase=2*M_PI*frequency*sample/rate;
        double value=audio[(size_t)(start+sample)]/32768.0;
        real+=value*cos(phase); imaginary+=value*sin(phase);
    }
    return (real*real+imaginary*imaginary)/(size*size);
}

static NSDictionary *TestSequentialCombination(NSURL *directory) {
    ELMVEncoderConfiguration *red=Configuration(@"h264");
    red.fpsNumerator=30; red.fpsDenominator=1; red.frameCount=12;
    red.audioSampleCount=red.frameCount*red.audioSampleRate/red.fpsNumerator;
    ELMVEncoderConfiguration *blue=[red copy];
    blue.frameCount=15; blue.audioSampleCount=blue.frameCount*blue.audioSampleRate/blue.fpsNumerator;
    NSURL *first=EncodeCombinationClip(directory,red,@"combine-a-red.mp4",YES,440);
    NSURL *second=EncodeCombinationClip(directory,blue,@"combine-b-blue.mp4",NO,1320);
    NSURL *url=[directory URLByAppendingPathComponent:@"combined.mp4"];
    dispatch_queue_t worker=dispatch_queue_create("org.elichika.test.combine",DISPATCH_QUEUE_SERIAL);
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    __block NSURL *finished=nil;
    __block NSError *failure=nil;
    // Reverse the creation order to exercise ordered selection rather than filename order.
    ELMVMP4Combination *operation=[ELMVMP4Combination combineSources:@[second,first] outputURL:url
        workerQueue:worker callbackQueue:dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0)
        completion:^(NSURL *output,NSError *error) { finished=output; failure=error; dispatch_semaphore_signal(done); }];
    if (dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_SEC))!=0) {
        [operation cancel]; Require(NO,@"Sequential combination stalled.");
    }
    Require([finished isEqual:url] && !failure,failure.localizedDescription ?: @"Unexpected combined output destination.");
    NSFileManager *files=NSFileManager.defaultManager;
    Require([files fileExistsAtPath:first.path] && [files fileExistsAtPath:second.path],@"A source MP4 was removed.");

    AVURLAsset *asset=[AVURLAsset URLAssetWithURL:finished options:@{AVURLAssetPreferPreciseDurationAndTimingKey:@YES}];
    NSArray<AVAssetTrack *> *videos=[asset tracksWithMediaType:AVMediaTypeVideo];
    NSArray<AVAssetTrack *> *audios=[asset tracksWithMediaType:AVMediaTypeAudio];
    Require(videos.count==1 && audios.count==1,@"Combined MP4 must have one video and one audio track.");
    int64_t frames=red.frameCount+blue.frameCount;
    int64_t audioSamples=red.audioSampleCount+blue.audioSampleCount;
    CMTime duration=CMTimeMake(frames,red.fpsNumerator);
    Require(CMTimeCompare(videos[0].timeRange.duration,duration)==0 &&
            CMTimeCompare(audios[0].timeRange.duration,duration)==0,@"Combined track endpoints changed.");

    NSError *error=nil;
    AVAssetReader *videoReader=[[AVAssetReader alloc] initWithAsset:asset error:&error];
    Require(videoReader!=nil,error.localizedDescription);
    AVAssetReaderTrackOutput *videoOutput=[AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:videos[0]
        outputSettings:@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA)}];
    [videoReader addOutput:videoOutput]; Require([videoReader startReading],videoReader.error.localizedDescription);
    int64_t frame=0;
    while (CMSampleBufferRef sample=[videoOutput copyNextSampleBuffer]) {
        Require(frame<frames && CMTimeCompare(CMSampleBufferGetOutputPresentationTimeStamp(sample),
                CMTimeMake(frame,red.fpsNumerator))==0,@"The combined video dropped, duplicated or mistimed a frame.");
        CVPixelBufferRef pixel=CMSampleBufferGetImageBuffer(sample);
        Require(pixel && CVPixelBufferLockBaseAddress(pixel,kCVPixelBufferLock_ReadOnly)==kCVReturnSuccess,
                @"Could not inspect combined video pixels.");
        const uint8_t *center=(const uint8_t *)CVPixelBufferGetBaseAddress(pixel)
            +(red.height/2)*CVPixelBufferGetBytesPerRow(pixel)+(red.width/2)*4;
        BOOL isBlue=frame<blue.frameCount;
        Require(isBlue ? center[0]>150 && center[2]<60 : center[2]>150 && center[0]<60,
                @"Combined frame color disagrees with the selected sequence.");
        CVPixelBufferUnlockBaseAddress(pixel,kCVPixelBufferLock_ReadOnly);
        CFRelease(sample); ++frame;
    }
    Require(videoReader.status==AVAssetReaderStatusCompleted && frame==frames,@"Combined video did not decode all expected frames.");

    AVAssetReader *audioReader=[[AVAssetReader alloc] initWithAsset:asset error:&error];
    Require(audioReader!=nil,error.localizedDescription);
    AVAssetReaderTrackOutput *audioOutput=[AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:audios[0]
        outputSettings:@{AVFormatIDKey:@(kAudioFormatLinearPCM),AVLinearPCMBitDepthKey:@16,
            AVLinearPCMIsFloatKey:@NO,AVLinearPCMIsBigEndianKey:@NO,AVLinearPCMIsNonInterleaved:@NO}];
    [audioReader addOutput:audioOutput]; Require([audioReader startReading],audioReader.error.localizedDescription);
    std::vector<int16_t> audio((size_t)audioSamples);
    int64_t copied=0;
    while (CMSampleBufferRef sample=[audioOutput copyNextSampleBuffer]) {
        int32_t rate=red.audioSampleRate;
        int64_t time=AudioIndex(CMSampleBufferGetOutputPresentationTimeStamp(sample),rate);
        int64_t count=CMSampleBufferGetNumSamples(sample);
        int64_t start=AudioTrim(sample,kCMSampleBufferAttachmentKey_TrimDurationAtStart,rate);
        int64_t end=count-AudioTrim(sample,kCMSampleBufferAttachmentKey_TrimDurationAtEnd,rate);
        Require(start>=0 && start<=end && end<=count,@"AAC trim exceeds its decoded buffer.");
        CMBlockBufferRef block=CMSampleBufferGetDataBuffer(sample);
        size_t bytes=block ? CMBlockBufferGetDataLength(block) : 0;
        Require(bytes<1024*1024 && bytes==(size_t)count*4,@"Expected decoded stereo PCM16.");
        NSMutableData *data=[NSMutableData dataWithLength:bytes];
        Require(!bytes || CMBlockBufferCopyDataBytes(block,0,bytes,data.mutableBytes)==noErr,@"Could not read joined audio samples.");
        const int16_t *pcm=(const int16_t *)data.bytes;
        for (int64_t n=start;n<end;n++) {
            int64_t index=time+n-start;
            if (index<0 || index>=audioSamples) continue;
            Require(index==copied,@"Decoded audio timestamps contain a gap or overlap at an MP4 join.");
            audio[(size_t)copied++]=pcm[2*n];
        }
        CFRelease(sample);
    }
    Require(audioReader.status==AVAssetReaderStatusCompleted && copied==audioSamples,@"Combined audio did not cover the rendered timeline.");
    int32_t rate=red.audioSampleRate;
    int64_t join=blue.audioSampleCount;
    double before=ToneEnergy(audio,join-rate/50,rate,1320);
    double after=ToneEnergy(audio,join+rate/200,rate,440);
    Require(before>0.01 && before>8*ToneEnergy(audio,join-rate/50,rate,440),@"The first tone ended before its video cut.");
    Require(after>0.01 && after>8*ToneEnergy(audio,join+rate/200,rate,1320),@"The second tone began late or in the wrong order.");

    return @{@"status":@"PASS",@"frames":@(frame),@"decoded_audio_samples":@(copied),
        @"join_seconds":@(CMTimeGetSeconds(CMTimeMake(blue.frameCount,blue.fpsNumerator))),
        @"selected_order_and_video_pts_verified":@YES,@"aac_tones_and_timing_verified":@YES};
}

int main(int argc,char **argv) {
    @autoreleasepool {
        BOOL combine=argc==3 && !strcmp(argv[2],"--combine");
        Require(argc==2 || combine,@"Provide one fresh temporary output directory and optionally --combine.");
        NSURL *directory=[NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]] isDirectory:YES];
        NSError *error=nil;
        Require(![NSFileManager.defaultManager fileExistsAtPath:directory.path],@"The test output directory already exists.");
        Require([NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:&error],error.localizedDescription);
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{ @autoreleasepool {
            NSError *writeError=nil;
            NSDictionary *h264=Encode(directory,@"h264",YES);
            NSDictionary *hevc=Encode(directory,@"hevc",NO);
            CancellationAndErrors(directory);
            NSMutableDictionary *report=[@{ @"schema":@1,@"status":@"PASS_APPLE_AVASSETWRITER_RUNTIME",
                @"h264_aac":h264,@"hevc_aac":hevc,@"cancel_cleanup_and_invalid_indices_verified":@YES,
                @"actual_mv_capture_proven":@NO } mutableCopy];
            if (combine) report[@"sequential_combine"]=TestSequentialCombination(directory);
            NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:&writeError];
            Require(json!=nil,writeError.localizedDescription);
            Require([json writeToURL:[directory URLByAppendingPathComponent:@"report.json"] options:NSDataWritingAtomic error:&writeError],writeError.localizedDescription);
            printf("%s\n",[[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] UTF8String]);
            dispatch_semaphore_signal(done);
        }});
        Require(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,(combine ? 255 : 150)*NSEC_PER_SEC))==0,
                @"Apple encoder integration test exceeded its deadline.");
    }
    return 0;
}
