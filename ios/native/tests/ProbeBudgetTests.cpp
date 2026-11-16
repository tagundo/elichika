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
    // The new parity path budgets observed payload completion separately from
    // real backend initialization. Legacy/core paths retain their exact caps.
    assert(elichika::probeStageIndex("management_ui")==-1);
    assert(elichika::probeStageIndex("native_backend")==-1);
    assert(elichika::probeStageIndex("complete")==10);
    assert(elichika::probeStageIndex("native_backend",true)==1);
    assert(elichika::probeStageIndex("go_start",true)==1);
    assert(elichika::probeStageIndex("tool_dependencies",true)==1);
    assert(elichika::probeStageIndex("dependencies",true)==4);
    assert(elichika::probeStageIndex("management_ui",true)==11);
    assert(elichika::probeStageIndex("complete",true)==12);
    elichika::ProbeBudget boundary(0,false,true);
    assert(boundary.advance("payload_prepare",8.384));
    assert(!boundary.advance("native_health",224));
    assert(!boundary.advance("native_backend",224));
    assert(!boundary.advance("tool_dependencies",224));
    assert(boundary.advanceAt("go_start",224.618,225));
    assert(boundary.stage().seconds==90 && boundary.entered()==224.618);
    const auto backendSequence=boundary.sequence();
    assert(boundary.advance("tool_dependencies",250));
    assert(boundary.entered()==224.618 && boundary.sequence()==backendSequence);
    assert(!boundary.advance("native_health",314.618));
    elichika::ProbeBudget lateBoundary(0,false,true);
    assert(!lateBoundary.advance("go_start",240));
    assert(lateBoundary.index()==0 && lateBoundary.entered()==0);
    elichika::ProbeBudget queuedBackend(0,false,true);
    assert(!queuedBackend.advanceAt("go_start",224,314));
    assert(queuedBackend.index()==0 && queuedBackend.entered()==0);
    const char *parityStages[]={"go_start","native_health","tls","tools","go_stop","config_read","go_restart","python_complete","web_admin","web_tools"};
    elichika::ProbeBudget parity(0,false,true);
    for (unsigned i=0;i<10;++i) assert(parity.advance(parityStages[i],i+1));
    assert(!parity.advance("complete",11)); // Cannot skip the actual UI probe.
    assert(parity.advanceAt("management_ui",11,12));
    assert(parity.stage().seconds==120 && parity.entered()==11);
    const auto paritySequence=parity.sequence();
    assert(parity.advance("management_ui",40));
    assert(parity.entered()==11 && parity.sequence()==paritySequence);
    assert(!parity.advance("complete",131)); // Repeating UI heartbeat cannot renew120.
    const double parityTimes[]={239,328,347,376,435,464,553,554,563,599};
    elichika::ProbeBudget parityAbsolute(0,false,true);
    for (unsigned i=0;i<10;++i) assert(parityAbsolute.advance(parityStages[i],parityTimes[i]));
    assert(parityAbsolute.advance("management_ui",599.5));
    assert(!parityAbsolute.advance("complete",600));
    assert(parityAbsolute.expired(600));
    elichika::ProbeBudget queuedParity(0,false,true);
    for (unsigned i=0;i<10;++i) assert(queuedParity.advance(parityStages[i],i+1));
    assert(!queuedParity.advanceAt("management_ui",11,131));
    assert(queuedParity.index()==10 && queuedParity.entered()==10);
    elichika::ProbeBudget legacy;
    for (unsigned i=0;i<9;++i) assert(legacy.advance(stages[i],i+1));
    assert(!legacy.advance("management_ui",10));
    assert(legacy.advance("complete",10));
}
