package com.klab.lovelive.allstars.fovmod;

/** Host-only functional tests; no Android activity, engine or JNI is executed. */
public final class GestureStateTest {
    private static int checks;
    static void require(boolean condition, String message) {
        checks++; if (!condition) throw new AssertionError(message);
    }
    static boolean event(FovMod.CornerHold h, int action, int pointers, float x, float y, long time) {
        return h.onEvent(action, pointers, x, y, 1000, 100, 8, time);
    }
    static FovMod.CornerHold down(long time) {
        FovMod.CornerHold h = new FovMod.CornerHold();
        require(event(h, 0, 1, 950, 50, time), "Corner down is reserved before it reaches the game");
        require(h.tracking(), "A reserved down starts the hold timer");
        return h;
    }
    public static void main(String[] args) {
        FovMod.CornerHold h = new FovMod.CornerHold();
        require(!event(h, 0, 1, 500, 50, 0), "Ordinary down passthrough");
        require(!h.onTimeout(3000, 1000, 100), "Outside the corner never opens settings");
        require(!event(h, 1, 1, 500, 50, 3001), "Ordinary up passthrough");

        h = down(100);
        require(!h.onTimeout(2099, 1000, 100), "No early menu");
        require(!event(h, 1, 1, 950, 50, 2099), "A short tap releases the buffered stream for replay");
        require(!h.onTimeout(2100, 1000, 100), "Lift cancels the pending hold");

        h = down(100);
        require(h.onTimeout(2100, 1000, 100), "Menu opens at exactly two seconds");
        require(!h.onTimeout(4100, 1000, 100), "A hold cannot reopen the menu repeatedly");
        require(event(h, 2, 1, 951, 50, 2200), "Recognized hold consumes the remaining move");
        require(event(h, 1, 1, 951, 50, 2201), "Recognized hold consumes the ending up");
        require(!event(h, 2, 1, 500, 50, 2202), "No consumption leaks into later input");

        h = down(0);
        require(!event(h, 2, 1, 959, 50, 1000), "Moving more than touch slop still reaches game");
        event(h, 2, 1, 950, 50, 1500);
        require(!h.onTimeout(2000, 1000, 100), "Returning after a drag cannot revive the hold");

        h = down(0);
        require(event(h, 2, 1, 956, 54, 1000), "Small moves remain reserved without reaching the game");
        require(h.onTimeout(2000, 1000, 100), "Small finger jitter is tolerated");

        h = down(0);
        require(!event(h, 5, 2, 950, 50, 1000), "Multi-touch remains a game gesture");
        require(!h.onTimeout(2000, 1000, 100), "Second finger cancels menu activation");

        h = down(0);
        event(h, 3, 1, 950, 50, 1000);
        require(!h.onTimeout(2000, 1000, 100), "OS cancellation prevents activation");
        h = down(0); h.cancel();
        require(!h.onTimeout(2000, 1000, 100), "Pause/destroy cancellation prevents stale timer activation");

        h = down(0);
        require(!h.onTimeout(2000, 1200, 100), "Window resize moving the corner cancels activation");
        require(!h.tracking(), "Resize cancellation is final");

        h = down(0); h.cancel(); event(h, 0, 1, 950, 50, 1999);
        require(!h.onTimeout(2000, 1000, 100), "An old callback cannot trigger a newly started hold");
        require(h.onTimeout(3999, 1000, 100), "The new hold uses its own two-second duration");
        require(event(h, 5, 2, 950, 50, 4000), "Second finger after recognition stays consumed");
        require(event(h, 3, 1, 950, 50, 4001), "Ending CANCEL is consumed only after recognition");

        h = new FovMod.CornerHold();
        event(h, 0, 1, 950, 50, 0);
        event(h, 0, 1, 400, 50, 1999);
        require(!h.onTimeout(3999, 1000, 100), "A new outside-corner down clears stale tracking");
        require(!FovMod.CornerHold.inCorner(Float.NaN, 0, 1000, 100), "Invalid pointer coordinates are not a corner");
        require(!FovMod.CornerHold.inCorner(0, 0, 0, 100), "Unmeasured windows do not arm the gesture");

        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.2026.11.15.1").equals("2026.11.15.1"), "Installed date build label is displayed");
        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.2026.12.01.99").equals("2026.12.01.99"), "Two-digit revision is displayed");
        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.b25").equals("3.12.0-fovmod.b25"), "Legacy fallback displays its real installed version");
        require(FovMod.buildLabelFromVersionName(null).equals("Build unavailable"), "Missing metadata has an explicit fallback");
        System.out.println("PASS host gesture/build-label assertions=" + checks + "; no Android or Unity runtime claim");
    }
}
