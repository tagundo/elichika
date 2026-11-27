#ifndef SIFAS_MV_PIXEL_CONVERT_H
#define SIFAS_MV_PIXEL_CONVERT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Unity RGBA32 ReadPixels uses bottom-up rows. Produce top-down, limited-range
 * SDR Rec.709 I420. Alpha is intentionally discarded by the MP4 video path.
 * Both input and output bounds are checked before any pixel is touched. */
int amv_rgba_bottom_up_to_i420(const uint8_t *,size_t,uint32_t,uint32_t,uint8_t *,size_t);
#ifdef __cplusplus
}
#endif
#endif
