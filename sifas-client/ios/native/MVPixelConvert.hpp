#pragma once
#include <cstddef>
#include <cstdint>
#include <limits>
#if defined(__aarch64__) || defined(__arm64__)
#include <arm_neon.h>
#endif

namespace elichika {
// Bit-exact replacement of the original export swizzle. Source is packed,
// bottom-up RGBA8; destination is top-down opaque BGRA8. No color transform,
// resampling, quantization, or change to the encoder's original color tags.
inline bool rgbaToOpaqueBGRA(const uint8_t *source,size_t sourceBytes,
                             uint32_t width,uint32_t height,
                             uint8_t *destination,size_t destinationBytes,
                             size_t destinationStride) {
    const size_t maximum=std::numeric_limits<size_t>::max();
    if(!source||!destination||!width||!height)return false;
    const size_t packed=size_t(width)*4;
    if(packed/4!=size_t(width))return false;
    if(packed>maximum/height||destinationStride<packed||destinationStride>maximum/height||
       sourceBytes<packed*height||destinationBytes<destinationStride*height)return false;
    const uintptr_t a=reinterpret_cast<uintptr_t>(source),b=reinterpret_cast<uintptr_t>(destination);
    if((a<=b&&b-a<packed*height)||(b<a&&a-b<destinationStride*height))return false;
    for(uint32_t y=0;y<height;y++){
        const uint8_t *input=source+size_t(height-1-y)*packed;
        uint8_t *output=destination+size_t(y)*destinationStride;
        uint32_t x=0;
#if defined(__aarch64__) || defined(__arm64__)
        for(;width-x>=16;x+=16){
            const uint8x16x4_t rgba=vld4q_u8(input+size_t(x)*4);
            uint8x16x4_t bgra;
            bgra.val[0]=rgba.val[2];bgra.val[1]=rgba.val[1];
            bgra.val[2]=rgba.val[0];bgra.val[3]=vdupq_n_u8(255);
            vst4q_u8(output+size_t(x)*4,bgra);
        }
#endif
        for(;x<width;x++){
            const size_t i=size_t(x)*4;
            output[i]=input[i+2];output[i+1]=input[i+1];output[i+2]=input[i];output[i+3]=255;
        }
    }
    return true;
}
} // namespace elichika
