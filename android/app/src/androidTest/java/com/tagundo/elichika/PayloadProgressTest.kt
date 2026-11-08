package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.view.View
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Display contracts are tested separately from the real journal fixture in PayloadRevisionTest. */
@RunWith(AndroidJUnit4::class)
class PayloadProgressTest {
    private fun record(stage: String, percent: Int, current: String = "masterdata.db", done: Long = 1, total: Long = 2) =
        JSONObject().put("stage", stage).put("completed", done).put("total", total)
            .put("current", current).put("percent", percent).toString()

    @Test fun invalidBackwardsAndEarlyCompletionCannotMisleadDisplay() {
        val values = mutableListOf<PayloadProgress.State>()
        val session = PayloadProgress.Session { values.add(it) }
        session.accept(record("validating", 5))
        session.accept(record("snapshot", 20))
        session.accept(record("validating", 10))
        session.accept(record("snapshot", 19))
        session.accept(record("unknown", 40))
        session.accept(record("merging", 40, "/private/userdata.db"))
        session.accept(record("merging", 40, ".."))
        session.accept(record("merging", 40, done = -1))
        session.accept(record("merging", 40, done = 3))
        session.accept(record("merging", 99))
        assertEquals(listOf(5, 20), values.map { it.percent })
        session.accept(record("complete", 100, "", 1, 1))
        assertEquals(99, values.last().percent)
        assertEquals("publishing", values.last().stage)
        session.committed()
        assertEquals(100, values.last().percent)
        session.accept(record("merging", 50))
        assertEquals(listOf(5, 20, 99, 100), values.map { it.percent })
        val failure = PayloadProgress.Session { throw IllegalStateException("observer error") }
        failure.accept(record("merging", 50))
        failure.committed()
        failure.close()
        println("ANDROID_PAYLOAD_PROGRESS_DEFENSE_PASS backward_ignored=true basename_only=true raw_complete_capped99=true observer_error_contained=true")
    }

    @Test fun recreatedWindowReplaysNewestPercentageAndFailureClearsIt() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assertFalse("Synthetic UI test requires a stopped server", Bus.serverRunning)
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val previous = preferences.all["seen_guide"]
        val oldPhase = Bus.preparationPhase
        val oldStarting = Bus.serverStarting
        val oldProgress = Bus.payloadProgress
        var first: android.app.Activity? = null
        var second: android.app.Activity? = null
        try {
            preferences.edit().putBoolean("seen_guide", true).commit()
            instrumentation.runOnMainSync {
                Bus.setPreparationPhase(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA)
                Bus.setPayloadProgress(PayloadProgress.State("merging", 12, 30, "masterdata.db", 55))
            }
            first = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertEquals(first!!.getString(R.string.status_data_update_percent, 55), first!!.findViewById<TextView>(R.id.txt_status).text.toString())
                first!!.finish()
                // Latest state can advance while no Activity is subscribed.
                Bus.setPayloadProgress(PayloadProgress.State("verifying", 7, 8, "asset_a_ko.db", 94))
            }
            second = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.waitForIdleSync()
            val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            try {
                java.io.File(context.cacheDir, "payload-progress-94.png").outputStream().use {
                    assertTrue(screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it))
                }
            } finally { screenshot.recycle() }
            instrumentation.runOnMainSync {
                assertEquals(second!!.getString(R.string.status_data_update_percent, 94), second!!.findViewById<TextView>(R.id.txt_status).text.toString())
                assertEquals(View.VISIBLE, second!!.findViewById<View>(R.id.progress_preparing).visibility)
                Bus.setPreparationPhase(AssetInstaller.PreparationPhase.FAILED)
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertNull(Bus.payloadProgress)
                assertEquals(second!!.getString(R.string.status_preparation_failed), second!!.findViewById<TextView>(R.id.txt_status).text.toString())
                assertEquals(View.GONE, second!!.findViewById<View>(R.id.progress_preparing).visibility)
            }
            println("ANDROID_PAYLOAD_PROGRESS_REPLAY_PASS actual_activity_recreated=true latest94=true failure_cleared=true spinner=true")
        } finally {
            instrumentation.runOnMainSync {
                first?.finish(); second?.finish()
                Bus.setPreparationPhase(oldPhase)
                Bus.setPayloadProgress(oldProgress)
                Bus.setStarting(oldStarting)
            }
            preferences.edit().apply {
                if (previous is Boolean) putBoolean("seen_guide", previous) else remove("seen_guide")
            }.commit()
        }
    }
}
