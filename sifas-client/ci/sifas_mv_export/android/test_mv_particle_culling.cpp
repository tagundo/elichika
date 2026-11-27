#include "mv_particle_culling.h"
#include <cassert>
#include <cstring>
using namespace sifas_mv_particles;
struct Fixture {
    alignas(8) uint8_t object[128],parameters[128],state[128];
    Fixture(int mode) {
        std::memset(object,0xa5,sizeof(object));std::memset(parameters,0xa5,sizeof(parameters));std::memset(state,0xa5,sizeof(state));
        write<void *>(object,0x40,parameters);write<void *>(object,0x48,state);write<int32_t>(parameters,0x40,mode);
        write<uint8_t>(state,0x26,1);
    }
};
int main() {
    for(int mode=0;mode<=3;mode++){
        Fixture f(mode);Policy p{};assert(snapshot(p,f.object));int wakes=0;
        apply(p,[&](void *owner){assert(owner==f.object);assert(read<int32_t>(f.parameters,0x40)==3);++wakes;write<uint8_t>(f.state,0x26,0);});
        assert(valid(p,f.object));assert(wakes==(mode==3?0:1));
        assert(read<uint8_t>(f.parameters,0x3f)==0xa5&&read<uint8_t>(f.parameters,0x44)==0xa5);
        assert(read<uint8_t>(f.state,0x21)==0xa5&&read<uint8_t>(f.state,0x23)==0xa5);
        if(mode!=3)assert(read<uint8_t>(f.state,0x26)==0&&read<uint8_t>(f.state,0x22)==1);
        assert(restore(p,f.object));assert(read<int32_t>(f.parameters,0x40)==mode);assert(!p.changed);
    }
    Fixture f(1),other(2);Policy p{};assert(snapshot(p,f.object));apply(p,[](void*){});
    assert(!valid(p,other.object)&&!restore(p,other.object));assert(read<int32_t>(other.parameters,0x40)==2);
    write<void *>(f.object,0x40,other.parameters);assert(!valid(p,f.object)&&!restore(p,f.object));assert(read<int32_t>(other.parameters,0x40)==2);
    write<void *>(f.object,0x40,f.parameters);write<int32_t>(f.parameters,0x40,2);
    assert(!valid(p,f.object)&&!restore(p,f.object));assert(read<int32_t>(f.parameters,0x40)==2);
    Fixture bad(4);assert(!snapshot(p,bad.object));assert(!snapshot(p,nullptr));
    assert(android_wake_rva(1)==0x1cbd10&&android_wake_rva(2)==0x1cbd0c&&!android_wake_rva(0));
}
