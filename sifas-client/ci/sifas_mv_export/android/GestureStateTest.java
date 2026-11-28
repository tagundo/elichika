package com.klab.lovelive.allstars.fovmod;

/** Host-only functional tests; no Android activity, engine or JNI is executed. */
public final class GestureStateTest {
    private static int checks;
    static final long DEFAULT = FovMod.CornerHold.DEFAULT_HOLD_MS;
    static void require(boolean condition, String message) {
        checks++; if (!condition) throw new AssertionError(message);
    }
    /** holdMs is what the caller would pass from the saved setting; only a DOWN reads it. */
    static boolean event(FovMod.CornerHold h, int action, int pointers, float x, float y, long holdMs, long time) {
        return h.onEvent(action, pointers, x, y, 1000, 100, 8, holdMs, time);
    }
    static boolean event(FovMod.CornerHold h, int action, int pointers, float x, float y, long time) {
        return event(h, action, pointers, x, y, DEFAULT, time);
    }
    static FovMod.CornerHold down(long time, long holdMs) {
        FovMod.CornerHold h = new FovMod.CornerHold();
        require(event(h, 0, 1, 950, 50, holdMs, time), "Corner down is reserved before it reaches the game");
        require(h.tracking(), "A reserved down starts the hold timer");
        require(h.duration() == holdMs, "The down captures the configured hold duration");
        return h;
    }
    static FovMod.CornerHold down(long time) { return down(time, DEFAULT); }

    /** The same state machine sequence for any configured duration. */
    static void durationSuite(long d) {
        FovMod.CornerHold h = down(100, d);
        require(h.remaining(100) == d, "Timer is first scheduled for the full configured duration " + d);
        require(h.remaining(100 + d / 2) == d - d / 2, "Re-scheduling waits only for the rest of " + d);
        require(h.remaining(100 + d + 50) == 1, "A late callback re-checks immediately");
        require(!h.onTimeout(100 + d - 1, 1000, 100), "No early menu before " + d + " ms");
        require(h.onTimeout(100 + d, 1000, 100), "Menu opens at exactly " + d + " ms");
        require(!h.onTimeout(100 + 2 * d, 1000, 100), "A hold cannot reopen the menu repeatedly at " + d);
        require(event(h, 2, 1, 951, 50, 101 + d), "Recognized hold consumes the remaining move");
        require(event(h, 1, 1, 951, 50, 102 + d), "Recognized hold consumes the ending up");
        require(!event(h, 2, 1, 500, 50, 103 + d), "No consumption leaks into later input");

        h = down(0, d);
        require(!event(h, 1, 1, 950, 50, d - 1), "A short tap releases the buffered stream at " + d);
        require(!h.onTimeout(d, 1000, 100), "Lift cancels the pending hold at " + d);

        h = down(0, d);
        require(!event(h, 5, 2, 950, 50, d / 2), "Multi-touch remains a game gesture at " + d);
        require(!h.onTimeout(d, 1000, 100), "Second finger cancels menu activation at " + d);

        h = down(0, d);
        require(!h.onTimeout(d, 1200, 100), "Window resize cancels activation at " + d);

        // A setting saved mid-gesture reaches only later DOWNs: MOVE/UP never change the captured duration.
        long other = d == 500 ? 5000 : 500;
        h = down(0, d);
        require(event(h, 2, 1, 952, 51, other, d / 2), "A small move with another configured time stays reserved");
        require(h.duration() == d, "A non-DOWN event cannot replace the captured duration " + d);
        if (other < d) require(!h.onTimeout(other, 1000, 100), "A shorter time saved mid-gesture cannot open the menu early");
        require(!h.onTimeout(d - 1, 1000, 100), "Still no early menu at " + d);
        require(h.onTimeout(d, 1000, 100), "The captured " + d + " ms still decides activation");
        h.cancel(); event(h, 0, 1, 950, 50, other, 10 * d);
        require(h.duration() == other, "The next DOWN uses the newly configured duration");
        require(!h.onTimeout(10 * d + other - 1, 1000, 100) && h.onTimeout(10 * d + other, 1000, 100),
            "The next hold follows its own captured duration");
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

        // Every offered hold time, including the non-default extremes, drives the same state machine.
        for (int choice : FovMod.HOLD_MS_CHOICES) durationSuite(choice);
        h = new FovMod.CornerHold();
        event(h, 0, 1, 950, 50, 0, 0);
        require(h.duration() == DEFAULT && !h.onTimeout(DEFAULT - 1, 1000, 100) && h.onTimeout(DEFAULT, 1000, 100),
            "A non-positive duration falls back to the two-second default");

        // A larger configured corner arms where the 64 dp default would not (density 1 here).
        h = new FovMod.CornerHold();
        require(!h.onEvent(0, 1, 850, 120, 1000, 64, 8, 500, 0), "Outside a 64 px corner");
        require(h.onEvent(0, 1, 850, 120, 1000, 160, 8, 500, 0), "Inside a 160 px corner");
        require(!h.onTimeout(499, 1000, 160) && h.onTimeout(500, 1000, 160), "Large corner with a half-second hold");

        // Saved setting validation: missing/invalid values use the defaults.
        require(FovMod.DEFAULT_CORNER_DP == 64 && FovMod.DEFAULT_HOLD_MS == 2000, "Defaults are 64 dp and 2 s");
        for (int dp : new int[]{32, 48, 64, 96, 128, 160}) require(FovMod.cornerDpOrDefault(dp) == dp, "Offered corner size kept: " + dp);
        for (int dp : new int[]{0, -64, 63, 65, 200, Integer.MAX_VALUE, Integer.MIN_VALUE}) require(FovMod.cornerDpOrDefault(dp) == 64, "Invalid corner size uses 64 dp: " + dp);
        for (int ms : new int[]{500, 1000, 1500, 2000, 3000, 4000, 5000}) require(FovMod.holdMsOrDefault(ms) == ms, "Offered hold time kept: " + ms);
        for (int ms : new int[]{0, -1, 499, 2500, 6000, Integer.MAX_VALUE}) require(FovMod.holdMsOrDefault(ms) == 2000, "Invalid hold time uses 2 s: " + ms);
        require(FovMod.cornerChoiceLabels().length == FovMod.CORNER_DP_CHOICES.length && FovMod.cornerChoiceLabels()[2].equals("64 dp"), "Corner labels");
        require(String.join(",", FovMod.holdChoiceLabels("en")).equals("0.5 s,1 s,1.5 s,2 s,3 s,4 s,5 s"), "English hold labels");
        require(FovMod.holdChoiceLabels("ko")[0].equals("0.5초") && FovMod.holdChoiceLabels("ja")[6].equals("5秒"), "Korean/Japanese hold labels");

        // The hint states the configured seconds in every supported language and never a fixed two seconds.
        String[] languages = {"en", "ko", "ja", "zh", "zh-Hant", "zh_TW", "fr"};
        for (int ms : FovMod.HOLD_MS_CHOICES) {
            String seconds = FovMod.holdSeconds(ms);
            for (String language : languages) {
                String hint = FovMod.menuHint(language, ms);
                require(hint.contains(seconds), "Hint shows " + seconds + " s for " + language);
                if (ms != 2000) require(!hint.contains("2 second") && !hint.contains("2초") && !hint.contains("2秒") && !hint.contains(" 2 秒"),
                    "Hint does not claim two seconds for " + language + " at " + ms);
            }
        }
        require(FovMod.menuHint("en", 1000).contains("for 1 second to"), "Singular English second");
        require(FovMod.menuHint("en", 500).contains("for 0.5 seconds to"), "Half-second English hint");
        require(FovMod.menuHint("ko", 1500).contains("1.5초간"), "Korean hint seconds");
        require(FovMod.menuHint("ja", 3000).contains("3秒間"), "Japanese hint seconds");
        require(FovMod.menuHint("zh-Hant", 4000).contains("右上角 4 秒即可開啟") && FovMod.menuHint("zh", 4000).contains("右上角 4 秒即可打开"), "Chinese hint seconds");
        require(FovMod.menuHint(null, 2000).startsWith("In game"), "Missing language falls back to English");

        // Panel strings: released map wins when it has the key; otherwise en/ja/ko text, English fallback.
        java.util.Map<String, String> released = new java.util.HashMap<String, String>();
        released.put("save", "Map save");
        require(FovMod.panelString(released, "ko", "save", "Save").equals("Map save"), "Released map value wins");
        require(FovMod.panelString(null, "en", "save", "Save").equals("Save"), "English Save fallback");
        require(FovMod.panelString(null, "ko", "save", "Save").equals("저장") && FovMod.panelString(null, "ja", "save", "Save").equals("保存"), "Localized Save");
        require(FovMod.panelString(null, "zh", "holdTime", "Hold time").equals("Hold time"), "Unsupported panel language uses English like the map");
        require(!FovMod.panelString(null, "ja", "cornerSize", "Corner size").equals("Corner size")
            && !FovMod.panelString(null, "ko", "holdTime", "Hold time").equals("Hold time"), "Corner/hold labels localized");

        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.2026.11.15.1").equals("2026.11.15.1"), "Installed date build label is displayed");
        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.2026.12.01.99").equals("2026.12.01.99"), "Two-digit revision is displayed");
        require(FovMod.buildLabelFromVersionName("3.12.0-fovmod.b25").equals("3.12.0-fovmod.b25"), "Legacy fallback displays its real installed version");
        require(FovMod.buildLabelFromVersionName(null).equals("Build unavailable"), "Missing metadata has an explicit fallback");
        System.out.println("PASS host gesture/settings/build-label assertions=" + checks + "; no Android or Unity runtime claim");
    }
}
