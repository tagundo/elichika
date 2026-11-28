#include "mv_pixel_convert.h"
#include <limits.h>
static uint8_t byte(double value) {
    int v=(int)(value+0.5); return (uint8_t)(v<0?0:v>255?255:v);
}
int amv_rgba_bottom_up_to_i420(const uint8_t *rgba,size_t rgba_bytes,uint32_t width,uint32_t height,
                              uint8_t *out,size_t out_bytes) {
    if(!rgba||!out||width<2||height<2||(width&1)||(height&1)||width>SIZE_MAX/height)return 0;
    size_t plane=(size_t)width*height;
    if(plane>SIZE_MAX/4||rgba_bytes<plane*4||out_bytes<plane+plane/2)return 0;
    uint8_t *u=out+plane,*v=u+plane/4;
    for(uint32_t y=0;y<height;y++)for(uint32_t x=0;x<width;x++) {
        const uint8_t *p=rgba+((size_t)(height-1-y)*width+x)*4;
        out[(size_t)y*width+x]=byte(16+219*(0.2126*p[0]+0.7152*p[1]+0.0722*p[2])/255);
    }
    for(uint32_t y=0;y<height;y+=2)for(uint32_t x=0;x<width;x+=2) {
        double r=0,g=0,b=0;
        for(uint32_t dy=0;dy<2;dy++)for(uint32_t dx=0;dx<2;dx++) {
            const uint8_t *p=rgba+((size_t)(height-1-y-dy)*width+x+dx)*4;
            r+=p[0];g+=p[1];b+=p[2];
        }
        r/=4;g/=4;b/=4;size_t at=(size_t)(y/2)*(width/2)+x/2;
        u[at]=byte(128+224*(-0.114572*r-0.385428*g+0.5*b)/255);
        v[at]=byte(128+224*(0.5*r-0.454153*g-0.045847*b)/255);
    }
    return 1;
}
