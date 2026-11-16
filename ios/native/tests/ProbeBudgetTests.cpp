#include "../ProbeBudget.hpp"
#include <cassert>
int main() {
    elichika::ProbeBudget first(100);
    assert(first.advance("payload_prepare",150));
    assert(first.advance("go_start",250));
    assert(first.entered()==100 && first.sequence()==1);
    assert(!first.advance("native_health",340)); // aliases did not extend startup240
    elichika::ProbeBudget tools;
    assert(tools.advance("native_health",200));
    assert(tools.advance("tls",201));
    assert(tools.advance("tools",202));
    const auto entered=tools.entered(); const auto sequence=tools.sequence();
    assert(tools.advance("registries",220) && tools.advance("model_glb",250));
    assert(tools.entered()==entered && tools.sequence()==sequence);
    assert(!tools.advance("go_stop",262)); // tools group has one60s cap
    elichika::ProbeBudget ordered;
    assert(!ordered.advance("complete",0.5));
    assert(!ordered.advance("tls",0.5));
    assert(ordered.advance("native_health",1));
    assert(!ordered.advance("payload_prepare",2));
    assert(!ordered.advance("unknown",2));
    ordered.seal(); assert(!ordered.advance("tls",2));
    elichika::ProbeBudget absolute;
    const double times[]={239,258,287,346,375,464,553,562,599};
    const char *stages[]={"native_health","tls","tools","go_stop","config_read","go_restart","python_complete","web_admin","web_tools"};
    for (unsigned i=0;i<9;++i) assert(absolute.advance(stages[i],times[i]));
    assert(!absolute.advance("complete",600));
    assert(absolute.expired(NAN));
    elichika::ProbeBudget core(0,true);
    assert(core.advance("native_health",1) && core.advance("tls",2));
    assert(!core.advance("tools",3));
    assert(core.advance("python_complete",3) && core.advance("complete",4));
    elichika::ProbeBudget queued;
    assert(queued.advance("native_health",1) && queued.advance("tls",2) && queued.advance("tools",3));
    assert(!queued.advanceAt("go_stop",4,44)); // queue delay cannot move entry to44
    assert(queued.index()==3 && queued.entered()==3); // rejected callback is atomic
    assert(queued.advanceAt("go_stop",4,24) && queued.entered()==4);
    assert(queued.expired(34)); // actual30s cap starts at the worker's entry4
    assert(!queued.advanceAt("go_stop",3.5,25)); // captured clock cannot regress
    assert(!queued.advanceAt("config_read",25,24)); // receipt cannot predate entry
    assert(!queued.advanceAt("config_read",NAN,25));
    // Parity adds one real UI stage, without changing any legacy stage index,
    // deadline, cold-launch order, or the shared absolute 600-second ceiling.
    assert(elichika::probeStageIndex("management_ui")==-1);
    assert(elichika::probeStageIndex("complete")==10);
    assert(elichika::probeStageIndex("management_ui",true)==10);
    assert(elichika::probeStageIndex("complete",true)==11);
    const char *parityStages[]={"native_health","tls","tools","go_stop","config_read","go_restart","python_complete","web_admin","web_tools"};
    elichika::ProbeBudget parity(0,false,true);
    for (unsigned i=0;i<9;++i) assert(parity.advance(parityStages[i],i+1));
    assert(!parity.advance("complete",10)); // Cannot skip the actual UI probe.
    assert(parity.advanceAt("management_ui",10,11));
    assert(parity.stage().seconds==120 && parity.entered()==10);
    const auto paritySequence=parity.sequence();
    assert(parity.advance("management_ui",40));
    assert(parity.entered()==10 && parity.sequence()==paritySequence);
    assert(!parity.advance("complete",130)); // Repeating UI heartbeat cannot renew120.
    elichika::ProbeBudget parityAbsolute(0,false,true);
    for (unsigned i=0;i<9;++i) assert(parityAbsolute.advance(stages[i],times[i]));
    assert(parityAbsolute.advance("management_ui",599.5));
    assert(!parityAbsolute.advance("complete",600));
    assert(parityAbsolute.expired(600));
    elichika::ProbeBudget queuedParity(0,false,true);
    for (unsigned i=0;i<9;++i) assert(queuedParity.advance(parityStages[i],i+1));
    assert(!queuedParity.advanceAt("management_ui",10,130));
    assert(queuedParity.index()==9 && queuedParity.entered()==9);
    elichika::ProbeBudget legacy;
    for (unsigned i=0;i<9;++i) assert(legacy.advance(parityStages[i],i+1));
    assert(!legacy.advance("management_ui",10));
    assert(legacy.advance("complete",10));
}
