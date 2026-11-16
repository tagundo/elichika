#include "../MVExportClock.hpp"
#include <cassert>
#include <initializer_list>
int main() {
    for (unsigned fps : {30u,60u,120u}) {
        const unsigned hz=fps==120 ? 120 : 60;
        elichika::MVExportClock clock(7,fps,hz,42);
        uint64_t tick=999; int64_t image=-2, frame=0;
        for (uint64_t expected=0; expected<=clock.finalTick(); ++expected) {
            assert(!clock.grant(41,tick,image));
            assert(clock.grant(42,tick,image) && tick==expected);
            if (image<0) continue;
            assert(image==frame);
            assert(!clock.accepted(42,image)); // An overlay must arrive first.
            assert(clock.received(42,image));
            for (int retry=0; retry<100; ++retry) {
                uint64_t blockedTick=0; int64_t blockedFrame=-1;
                assert(!clock.grant(42,blockedTick,blockedFrame));
            }
            assert(!clock.received(42,image));
            assert(!clock.accepted(41,image));
            assert(clock.accepted(42,image)); ++frame;
        }
        assert(frame==7 && clock.complete());
        assert(!clock.grant(42,tick,image));
    }
    elichika::MVExportClock cancelled(2,30,60,9);
    uint64_t tick=0; int64_t index=-1;
    assert(cancelled.grant(9,tick,index));
    assert(cancelled.received(9,index));
    cancelled.cancel(9);
    assert(!cancelled.accepted(9,index));
    assert(!cancelled.grant(9,tick,index));
    elichika::MVExportClock single(1,30,60,10);
    assert(single.finalTick()==0 && single.grant(10,tick,index));
    assert(tick==0 && index==0 && !single.complete());
    assert(!single.received(9,index));
    assert(!single.received(10,1));
    assert(single.received(10,0) && single.accepted(10,0));
    assert(single.complete() && !single.grant(10,tick,index));
    elichika::MVExportClock invalid(0,30,60,11);
    assert(!invalid.grant(11,tick,index));
}
