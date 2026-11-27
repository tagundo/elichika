#include "../HostCore.hpp"
#include <cassert>
int main() {
    elichika::ServerButtonPolicy menu;
    assert(menu.visible());
    menu.load(false,false); assert(menu.visible()); // absent preference stays visible on first launch
    menu.toggle(); assert(!menu.visible());
    elichika::ServerButtonPolicy relaunched;
    relaunched.load(true,menu.visible()); assert(!relaunched.visible());
    relaunched.toggle(); assert(relaunched.visible());
    assert(elichika::ServerButtonPolicy::restoreHoldSeconds==2.0);
    assert(elichika::ServerButtonPolicy::restoreCorner(380,40,390,844,0,44));
    assert(!elichika::ServerButtonPolicy::restoreCorner(20,40,390,844,0,44));
    assert(elichika::ServerButtonPolicy::restoreCorner(800,10,844,390,44,0)); // landscape safe area
    assert(!elichika::ServerButtonPolicy::restoreCorner(700,10,844,390,44,0));
    assert(!elichika::ServerButtonPolicy::restoreCorner(391,0,390,844,0,44));
    assert(!elichika::ServerButtonPolicy::restoreCorner(380,0,390,844,390,44));
    assert(!elichika::ServerButtonPolicy::restoreCorner(20,400,390,844,0,44));
    assert(!elichika::ServerButtonPolicy::restoreCorner(-1,0,390,844,0,44));
    assert(!elichika::ServerButtonPolicy::restoreCorner(NAN,0,390,844,0,44));
    elichika::HostCore h;
    const auto first = h.begin();
    assert(!h.canStart());
    assert(h.capture(42));
    assert(!h.canStart());
    assert(h.report(first, true, ""));
    h.foreground(false);
    assert(!h.takeStart());
    h.foreground(true);
    assert(h.takeStart());
    assert(!h.takeStart()); // duplicate activation/capture cannot start twice
    h.foreground(false); h.foreground(true);
    assert(!h.takeStart());
    h.fail("backend stopped");
    assert(h.started() && !h.ready());
    const auto retry = h.begin();
    assert(!h.report(first, true, "")); // a stale async reply cannot resume
    assert(h.report(retry, true, ""));
    assert(h.ready() && !h.takeStart()); // backend recovery never relaunches Unity
    elichika::HostCore unsupported;
    const auto generation = unsupported.begin();
    unsupported.fail("unsupported executable");
    assert(unsupported.capture(1));
    assert(!unsupported.report(generation, true, ""));
    assert(!unsupported.takeStart());
    elichika::HostCore changed;
    changed.begin(); changed.capture(1);
    assert(!changed.capture(2) && changed.failed());
    elichika::HostCore early;
    const auto earlyGeneration=early.begin();
    early.report(earlyGeneration,true,"");
    assert(!early.takeStart()); // readiness before the real method capture is safe
    assert(early.capture(5) && early.capture(5));
    assert(early.takeStart() && !early.takeStart());
    elichika::HostCore failedBeforeGame;
    const auto failedGeneration=failedBeforeGame.begin();
    failedBeforeGame.capture(9);
    failedBeforeGame.report(failedGeneration,false,"Database seed is missing.");
    assert(!failedBeforeGame.takeStart());
    const auto recoveredGeneration=failedBeforeGame.begin();
    assert(!failedBeforeGame.report(failedGeneration,true,""));
    failedBeforeGame.report(recoveredGeneration,true,"");
    assert(failedBeforeGame.takeStart());
}
