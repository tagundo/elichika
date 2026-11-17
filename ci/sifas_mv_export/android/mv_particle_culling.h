#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>

// Exact Unity 2018.4 particle layout, verified in the original Apple/GL/JP
// visibility tests, mode-1 catch-up branches and parameter setters. No manual
// particle stepping: Unity retains authored emission, transforms and lifetime.
namespace sifas_mv_particles {
struct Policy {
    void *native=nullptr, *parameters=nullptr, *state=nullptr;
    int32_t original=0;
    bool changed=false;
};
template<class T> inline T read(const void *p, size_t offset) {
    T value; std::memcpy(&value,static_cast<const uint8_t *>(p)+offset,sizeof(value)); return value;
}
template<class T> inline void write(void *p, size_t offset, T value) {
    std::memcpy(static_cast<uint8_t *>(p)+offset,&value,sizeof(value));
}
inline bool snapshot(Policy &p,void *native) {
    if(!native)return false;
    p.native=native;p.parameters=read<void *>(native,0x40);p.state=read<void *>(native,0x48);
    if(!p.parameters||!p.state)return false;
    p.original=read<int32_t>(p.parameters,0x40);
    return p.original>=0&&p.original<=3;
}
inline bool owners_match(const Policy &p,void *native) {
    return native&&native==p.native&&read<void *>(native,0x40)==p.parameters&&
        read<void *>(native,0x48)==p.state;
}
inline bool valid(const Policy &p,void *native) {
    return owners_match(p,native)&&read<int32_t>(p.parameters,0x40)==(p.changed?3:p.original);
}
template<class Wake> inline void apply(Policy &p,Wake wake) {
    if(p.original==3)return;
    p.changed=true;write<int32_t>(p.parameters,0x40,3);
    // Same transition as the original property-transfer code: uncull with
    // mode 3 already installed, so it never catches up encoder wall time.
    wake(p.native);write<uint8_t>(p.state,0x22,1);
}
inline bool restore(Policy &p,void *native) {
    if(!p.changed)return true;
    if(!owners_match(p,native))return false;
    int32_t current=read<int32_t>(p.parameters,0x40);
    if(current!=3&&current!=p.original)return false;
    write<int32_t>(p.parameters,0x40,p.original);write<uint8_t>(p.state,0x22,1);
    p.changed=false;return true;
}
inline uintptr_t android_wake_rva(uint32_t region) {
    return region==1?0x1cbd10:region==2?0x1cbd0c:0;
}
static const uint8_t android_wake_head[]={0xea,0x0f,0x1c,0xfc,0xe9,0x23,0x01,0x6d,0xf5,0x53,0x02,0xa9,0xf3,0x7b,0x03,0xa9,0xf3,0x03,0x00,0xaa,0x68,0x26,0x40,0xf9,0x09,0x99,0x40,0x39,0xe9,0x0b,0x00,0x34};
} // namespace sifas_mv_particles
