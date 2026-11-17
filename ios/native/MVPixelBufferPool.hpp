#pragma once
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>

namespace elichika {
// One bounded capture pool. Buffers remain alive through their frame wrapper
// and AVAssetWriter retains, even after the pool is reset during cancellation.
class MVPixelBufferPool {
    CVPixelBufferPoolRef pool_=nullptr;
public:
    MVPixelBufferPool()=default;
    MVPixelBufferPool(const MVPixelBufferPool &)=delete;
    MVPixelBufferPool &operator=(const MVPixelBufferPool &)=delete;
    ~MVPixelBufferPool(){reset();}
    void reset(){if(pool_)CVPixelBufferPoolRelease(pool_);pool_=nullptr;}
    CVReturn create(uint32_t width,uint32_t height) {
        reset();
        if(!width||!height)return kCVReturnInvalidArgument;
        NSDictionary *attributes=@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
            (id)kCVPixelBufferWidthKey:@(width),(id)kCVPixelBufferHeightKey:@(height),
            (id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        return CVPixelBufferPoolCreate(kCFAllocatorDefault,nullptr,(__bridge CFDictionaryRef)attributes,&pool_);
    }
    CVReturn acquire(CVPixelBufferRef *pixel) {
        if(!pixel)return kCVReturnInvalidArgument;
        *pixel=nullptr;
        if(!pool_)return kCVReturnInvalidArgument;
        return CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(kCFAllocatorDefault,pool_,
            (__bridge CFDictionaryRef)@{(id)kCVPixelBufferPoolAllocationThresholdKey:@3},pixel);
    }
};

class MVPixelBufferLock {
    CVPixelBufferRef pixel_;
    CVReturn status_;
    bool locked_;
public:
    explicit MVPixelBufferLock(CVPixelBufferRef pixel):pixel_(pixel),
        status_(pixel?CVPixelBufferLockBaseAddress(pixel,0):kCVReturnInvalidArgument),locked_(status_==kCVReturnSuccess){}
    MVPixelBufferLock(const MVPixelBufferLock &)=delete;
    MVPixelBufferLock &operator=(const MVPixelBufferLock &)=delete;
    ~MVPixelBufferLock(){unlock();}
    bool locked()const{return locked_;}
    CVReturn status()const{return status_;}
    void unlock(){if(locked_){CVPixelBufferUnlockBaseAddress(pixel_,0);locked_=false;}}
};
} // namespace elichika
