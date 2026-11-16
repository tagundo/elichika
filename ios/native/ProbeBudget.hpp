#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
namespace elichika {
struct ProbeStage { const char *name; double seconds; };
inline constexpr ProbeStage probeStages[]={{"native_start",240},{"native_health",20},{"tls",30},{"tools",60},
    {"go_stop",30},{"config_read",90},{"go_restart",90},{"python_complete",10},{"web_admin",45},{"web_tools",45},{"complete",5}};
inline constexpr ProbeStage parityProbeStages[]={{"native_start",240},{"native_health",20},{"tls",30},{"tools",60},
    {"go_stop",30},{"config_read",90},{"go_restart",90},{"python_complete",10},{"web_admin",45},{"web_tools",45},
    {"management_ui",120},{"complete",5}};
inline int probeStageIndex(const char *name,bool parity=false) {
    if (!name) return -1;
    if (!std::strcmp(name,"payload_prepare") || !std::strcmp(name,"go_start") || !std::strcmp(name,"tool_dependencies")) return 0;
    if (!std::strcmp(name,"dependencies") || !std::strcmp(name,"registries") ||
        !std::strcmp(name,"texture_codecs") || !std::strcmp(name,"model_glb")) return 3;
    const auto *stages=parity ? parityProbeStages : probeStages;
    for (int i=0;i<(parity ? 12 : 11);++i) if (!std::strcmp(name,stages[i].name)) return i;
    return -1;
}
/* Test-only monotonic deadline policy. Alias/detail transitions and repeated
 * heartbeats cannot renew a parent stage's budget. Forward stages cannot escape
 * an already-expired stage or the fixed 600-second absolute ceiling. */
class ProbeBudget {
public:
    explicit ProbeBudget(double start=0,bool coreOnly=false,bool parity=false)
        :start_(start),entered_(start),event_(start),coreOnly_(coreOnly),parity_(parity && !coreOnly) {}
    bool expired(double now) const {
        return !std::isfinite(now) || now<entered_ || now-start_>=600 || now-entered_>=stage().seconds;
    }
    bool advance(const char *name,double now) {
        const int next=probeStageIndex(name,parity_);
        if (sealed_ || next<index_ || next<0 || now<event_ || expired(now)) return false;
        if (next!=index_) {
            const bool allowed=coreOnly_ ? ((index_==0 && next==1) || (index_==1 && next==2) ||
                (index_==2 && next==7) || (index_==7 && next==10)) : next==index_+1;
            if (!allowed) return false;
        }
        if (next!=index_) { index_=next; entered_=now; ++sequence_; }
        event_=now;
        return true;
    }
    // A worker captures operation entry before enqueueing its main-thread
    // callback. Queue delay must not renew the new operation's budget.
    bool advanceAt(const char *name,double entered,double received) {
        if (!std::isfinite(received) || received<entered) return false;
        ProbeBudget next=*this;
        if (!next.advance(name,entered) || next.expired(received)) return false;
        *this=next; return true;
    }
    void seal() { sealed_=true; }
    const ProbeStage &stage() const { return parity_ ? parityProbeStages[index_] : probeStages[index_]; }
    int index() const { return index_; }
    double start() const { return start_; }
    double entered() const { return entered_; }
    std::uint64_t sequence() const { return sequence_; }
private:
    double start_,entered_,event_;
    int index_=0;
    std::uint64_t sequence_=1;
    bool sealed_=false;
    bool coreOnly_=false;
    bool parity_=false;
};
}
