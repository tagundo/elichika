#pragma once
#include <cstdint>
#include <limits>

namespace elichika {
// Main-thread fixed-step grant/acknowledgment clock. A capture owns its grant
// until the encoder accepts those exact bytes; Retry never calls accepted().
class MVExportClock {
    uint64_t generation_, nextTick_=0, finalTick_=0, step_=0;
    int64_t frameCount_=0, awaiting_=-1, accepted_=0;
    bool received_=false, cancelled_=false, valid_=false;
public:
    MVExportClock(int64_t frames, uint32_t fps, uint32_t simulationHz, uint64_t generation)
        : generation_(generation), frameCount_(frames) {
        valid_=frames>0 && (fps==30 || fps==60 || fps==120) &&
            (simulationHz==60 || simulationHz==120) && simulationHz%fps==0;
        if (!valid_) return;
        step_=simulationHz/fps;
        valid_=uint64_t(frames-1)<=std::numeric_limits<uint64_t>::max()/step_;
        if (valid_) finalTick_=uint64_t(frames-1)*step_;
    }
    bool grant(uint64_t generation, uint64_t &tick, int64_t &capture) {
        if (!valid_ || cancelled_ || generation!=generation_ || awaiting_>=0 || nextTick_>finalTick_) return false;
        tick=nextTick_++; capture=tick%step_==0 ? int64_t(tick/step_) : -1;
        if (capture>=0) { awaiting_=capture; received_=false; }
        return true;
    }
    bool received(uint64_t generation, int64_t index) {
        if (cancelled_ || generation!=generation_ || index<0 || index!=awaiting_ || received_) return false;
        received_=true; return true;
    }
    bool accepted(uint64_t generation, int64_t index) {
        if (cancelled_ || generation!=generation_ || !received_ || index!=awaiting_ || index!=accepted_) return false;
        ++accepted_; awaiting_=-1; received_=false; return true;
    }
    void cancel(uint64_t generation) { if (generation==generation_) cancelled_=true; }
    bool complete() const { return valid_ && accepted_==frameCount_; }
    int64_t acceptedFrames() const { return accepted_; }
    uint64_t finalTick() const { return finalTick_; }
};
}
