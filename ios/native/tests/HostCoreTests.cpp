#include "../HostCore.hpp"
#include <cassert>
int main() {
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
