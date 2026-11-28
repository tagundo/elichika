package com.klab.lovelive.allstars.fovmod;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/** Host-only checks of the "Combine into MP4s" plan bookkeeping (counts, stop
 * rule, summary). It loads only AndroidMVExport.GroupPlan; no Activity, Unity,
 * encoder or queue storage runs, so group chaining itself is not exercised here. */
public final class GroupPlanTest {
    private static int checks;
    static void require(boolean condition, String message) {
        checks++; if (!condition) throw new AssertionError(message);
    }
    static AndroidMVExport.GroupPlan plan(int groups) {
        List<List<UUID>> order = new ArrayList<List<UUID>>();
        for (int i = 0; i < groups; i++) order.add(Arrays.asList(UUID.randomUUID()));
        return new AndroidMVExport.GroupPlan(null, order);
    }
    public static void main(String[] args) {
        // queue (1..6) -> MP4 #1 = 1 (already exported), #2 = 2+3+4, #3 = 5+6 with one failure.
        AndroidMVExport.GroupPlan run = plan(3);
        run.next = 1; run.skipped++;
        run.next = 2; run.ended(true, false, null);
        run.next = 3; run.ended(false, false, "The selected MVs use different audio sample rates or channel counts.");
        require(run.exported == 1 && run.skipped == 1 && run.failed == 1 && run.cancelled == 0, "Counts per finished group");
        require(run.stopReason == null, "An ordinary failure does not stop later groups");
        require(run.summary().equals("MP4s: 1 exported · 1 skipped · 1 failed. The skipped MV was already exported.\n"
            + "The selected MVs use different audio sample rates or channel counts."), "Summary with the first failure: " + run.summary());

        // Cancel during group 2 of 4: the cancelled group and the two unstarted groups are not exported.
        run = plan(4);
        run.next = 1; run.ended(true, false, null);
        run.next = 2; run.ended(false, true, "Export cancelled"); run.stop("Export cancelled.");
        require(run.summary().equals("MP4s: 1 exported · 0 skipped · 0 failed · 3 not exported.\nExport cancelled."),
            "Cancel summary: " + run.summary());

        // The first stop reason wins; empty reasons read as a cancel.
        run = plan(2);
        run.stop("The game window closed during MP4 export."); run.stop("Export cancelled.");
        require(run.stopReason.equals("The game window closed during MP4 export."), "First stop reason is kept");
        run = plan(2); run.stop(null);
        require(run.stopReason.equals("Export cancelled."), "Null stop reason");
        run = plan(2); run.stop("");
        require(run.stopReason.equals("Export cancelled."), "Empty stop reason");

        // Failures without a message still count, and later failures do not replace the first message.
        run = plan(3); run.next = 3;
        run.ended(false, false, ""); run.ended(false, false, "first"); run.ended(false, false, "second");
        require(run.failed == 3 && run.firstFailure.equals("first"), "First non-empty failure message is reported");
        require(run.summary().equals("MP4s: 0 exported · 0 skipped · 3 failed.\nfirst"), "All-failed summary: " + run.summary());

        // Everything skipped: no failure line, plural note.
        run = plan(2); run.next = 2; run.skipped = 2;
        require(run.summary().equals("MP4s: 0 exported · 2 skipped · 0 failed. The skipped MVs were already exported."), "All-skipped summary: " + run.summary());

        // Restart-class failures stop the plan; ordinary per-MV failures do not.
        String[] restart = {
            "The game window closed during MP4 export. Restart the game before exporting again.",
            "The Unity display could not be restored. Restart the game before exporting again.",
            "The previous FOV could not be restored. Restart the game before exporting again.",
            "MP4 cleanup timed out. Restart the game before retrying.",
            "MV spring jobs did not complete safely; retained scene roots require restarting the game before another export",
            "MP4 finished, but spring jobs did not complete safely; restart the game before another export",
            "The previous MV export could not safely restore the game. Restart the game before using the export queue.",
            "The game could not initialize its MV export interfaces. Restart the game and try again.",
        };
        for (String reason : restart) require(AndroidMVExport.GroupPlan.requiresRestart(reason), "Restart-class: " + reason);
        String[] ordinary = {
            null, "", "Export cancelled",
            "The loaded MV does not match the saved selection.",
            "The saved FOV changed while loading the MV.",
            "The selected MVs use different audio sample rates or channel counts.",
            "A selected MV changed or was removed from the queue.",
            "The queued MP4 destination is already in use.",
        };
        for (String reason : ordinary) require(!AndroidMVExport.GroupPlan.requiresRestart(reason), "Ordinary failure: " + reason);
        System.out.println("PASS host group-plan bookkeeping assertions=" + checks + "; group chaining needs a device run");
    }
}
