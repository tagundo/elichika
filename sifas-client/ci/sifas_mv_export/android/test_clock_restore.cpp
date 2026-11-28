#include "android_mv_game_bindings.h"
#include <assert.h>
#include <stdio.h>
template<class T>void write_value(uint8_t *p,size_t offset,T value){memcpy(p+offset,&value,sizeof(value));}
template<class T>T read_value(const uint8_t *p,size_t offset){T value;memcpy(&value,p+offset,sizeof(value));return value;}
int main(){
    uint8_t original[0x110],live[0x110];memset(original,0x5a,sizeof(original));memset(live,0xa5,sizeof(live));
    write_value<double>(original,0x60,20.0);write_value<double>(original,0x70,21.0);
    write_value<double>(original,0xe0,100.0);write_value<double>(original,0xe8,200.0);
    write_value<int32_t>(original,0xd8,60);write_value<float>(original,0xfc,0.f);
    write_value<uint64_t>(live,0xc8,9000000001ULL);write_value<uint32_t>(live,0xd0,1337);
    live[0xc0]=1;live[0xc1]=3;write_value<uint32_t>(live,0xf8,0xdeadbeef);
    amv_restore_offline_clock(live,original+0x30,12.5,1);
    assert(read_value<double>(live,0x60)==20.0&&read_value<double>(live,0x70)==21.0);
    assert(read_value<double>(live,0xe0)==112.5&&read_value<double>(live,0xe8)==212.5);
    assert(read_value<uint64_t>(live,0xc8)==9000000001ULL&&read_value<uint32_t>(live,0xd0)==1337);
    assert(live[0xc0]==1&&live[0xc1]==3&&read_value<uint32_t>(live,0xf8)==0xdeadbeef);
    assert(read_value<int32_t>(live,0xd8)==60&&read_value<float>(live,0xfc)==0.f);
    assert(live[0x40]==0xa5&&live[0xb0]==0xa5&&live[0x100]==0xa5);
    // A replacement scene owns its own time scale and target frame rate.
    write_value<int32_t>(live,0xd8,30);write_value<float>(live,0xfc,.75f);
    amv_restore_offline_clock(live,original+0x30,25.0,0);
    assert(read_value<int32_t>(live,0xd8)==30&&read_value<float>(live,0xfc)==.75f);
    assert(read_value<uint64_t>(live,0xc8)==9000000001ULL&&read_value<uint32_t>(live,0xd0)==1337);
    assert(read_value<double>(live,0xe0)==125.0&&read_value<double>(live,0xe8)==225.0);
    puts("PASS original clock fields restored; live frame counters, flags, caches and replacement-scene settings preserved");
}
