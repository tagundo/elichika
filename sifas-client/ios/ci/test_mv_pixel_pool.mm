#import <Foundation/Foundation.h>
#import "ElichikaMVEncoder.h"
#include "MVPixelBufferPool.hpp"
#include "MVPixelConvert.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
static void Require(bool value,const char *message){if(!value){std::fprintf(stderr,"MV pixel pool: %s\n",message);std::exit(1);}}
int main(){@autoreleasepool{
 elichika::MVPixelBufferPool pool;Require(pool.create(18,4)==kCVReturnSuccess,"create");
 CVPixelBufferRef first=nullptr,second=nullptr,third=nullptr,extra=nullptr;
 Require(pool.acquire(&first)==kCVReturnSuccess&&pool.acquire(&second)==kCVReturnSuccess&&pool.acquire(&third)==kCVReturnSuccess,"three exclusive slots");
 Require(pool.acquire(&extra)==kCVReturnWouldExceedAllocationThreshold&&!extra,"fourth slot must backpressure");
 __attribute__((objc_precise_lifetime)) ELMVPixelFrame *frame=[[ELMVPixelFrame alloc]initWithPixelBuffer:first];CVPixelBufferRelease(first);first=nullptr;
 Require(frame&&frame.rowBytes>=18*4,"wrapper retains stride");
 std::vector<uint8_t> rgba(18*4*4);for(size_t i=0;i<rgba.size();i++)rgba[i]=uint8_t(i*37+3);
 {elichika::MVPixelBufferLock mapped(frame.pixelBuffer);Require(mapped.locked(),"lock");auto *out=(uint8_t *)CVPixelBufferGetBaseAddress(frame.pixelBuffer);size_t size=CVPixelBufferGetDataSize(frame.pixelBuffer);std::memset(out,125,size);
  Require(elichika::rgbaToOpaqueBGRA(rgba.data(),rgba.size(),18,4,out,size,frame.rowBytes),"direct conversion");
  for(size_t y=0;y<4;y++){for(size_t x=0;x<18;x++){const auto *src=rgba.data()+((3-y)*18+x)*4;const auto *dst=out+y*frame.rowBytes+x*4;Require(dst[0]==src[2]&&dst[1]==src[1]&&dst[2]==src[0]&&dst[3]==255,"visible byte equality");}for(size_t i=18*4;i<frame.rowBytes;i++)Require(out[y*frame.rowBytes+i]==125,"padding preserved");}}
 CVPixelBufferRef codecRetain=CVPixelBufferRetain(frame.pixelBuffer);frame=nil;
 Require(pool.acquire(&extra)==kCVReturnWouldExceedAllocationThreshold&&!extra,"codec retain protects accepted storage");
 CVPixelBufferRelease(codecRetain);Require(pool.acquire(&extra)==kCVReturnSuccess&&extra,"released slot reusable");
 pool.reset();
 {elichika::MVPixelBufferLock mapped(extra);Require(mapped.locked()&&CVPixelBufferGetBaseAddress(extra),"owned buffer survives pool cancellation/reset");}
 CVPixelBufferRelease(extra);CVPixelBufferRelease(second);CVPixelBufferRelease(third);extra=nullptr;
 Require(pool.acquire(&extra)==kCVReturnInvalidArgument&&!extra,"reset pool cannot produce a frame");
 std::puts("PASS_MV_PIXEL_POOL: exact visible bytes/padding, three-slot backpressure, wrapper/codec ownership, reuse and cancellation lifetime");
}return 0;}
