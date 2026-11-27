#include "mv_pixel_convert.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
int main(void) {
    uint8_t rgba[16],out[8];
    const uint8_t colors[5][3]={{0,0,0},{255,255,255},{255,0,0},{0,255,0},{0,0,255}};
    const uint8_t expected[5][3]={{16,128,128},{235,128,128},{63,102,240},{173,42,26},{32,240,118}};
    for(int c=0;c<5;c++) {
        for(int p=0;p<4;p++){memcpy(rgba+p*4,colors[c],3);rgba[p*4+3]=17;}
        memset(out,0xa5,sizeof(out));
        assert(amv_rgba_bottom_up_to_i420(rgba,sizeof(rgba),2,2,out,6));
        for(int p=0;p<4;p++)assert(out[p]==expected[c][0]);
        assert(out[4]==expected[c][1]&&out[5]==expected[c][2]);
        assert(out[6]==0xa5&&out[7]==0xa5);
    }
    // Bottom row red, top row green: first output row must be green.
    for(int p=0;p<4;p++){memcpy(rgba+p*4,colors[p<2?2:3],3);rgba[p*4+3]=255;}
    assert(amv_rgba_bottom_up_to_i420(rgba,16,2,2,out,6));
    assert(out[0]==173&&out[1]==173&&out[2]==63&&out[3]==63);
    memset(out,0xa5,sizeof(out));
    assert(!amv_rgba_bottom_up_to_i420(rgba,15,2,2,out,6));
    assert(!amv_rgba_bottom_up_to_i420(rgba,16,2,2,out,5));
    assert(!amv_rgba_bottom_up_to_i420(rgba,16,3,2,out,6));
    for(unsigned i=0;i<sizeof(out);i++)assert(out[i]==0xa5);
    puts("PASS: Rec709 black/white/primaries, alpha exclusion, row orientation, memory bounds");
    return 0;
}
