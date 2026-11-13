package com.tagundo.elichika

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** One window leaving the screen must not unsubscribe another visible window. */
@RunWith(AndroidJUnit4::class)
class WindowBusTest {
    @Test
    fun updatePhaseSurvivesReopeningAndCancelledPendingStart() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        val previousLanguage = Lang.pref(context)
        val previousPhase = Bus.preparationPhase
        val previousRunning = Bus.serverRunning
        val previousStarting = Bus.serverStarting
        val windows = mutableListOf<Activity>()
        fun openWindow(): Activity = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
        ).also { windows.add(it) }
        fun assertHeader(activity: Activity, text: Int, busy: Boolean) {
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertEquals(activity.getString(text), activity.findViewById<TextView>(R.id.txt_status).text.toString())
                assertEquals(if (busy) View.VISIBLE else View.GONE,
                    activity.findViewById<View>(R.id.progress_preparing).visibility)
                assertFalse("Preparation must not claim Go is running", Bus.serverRunning)
            }
        }
        try {
            preferences.edit().putBoolean("seen_guide", true).commit()
            instrumentation.runOnMainSync {
                Lang.setPref(context, "ko")
                Lang.applyToApp(context)
                Bus.setRunning(false)
                Bus.setStarting(true)
                Bus.setPreparationPhase(AssetInstaller.PreparationPhase.UPDATING_GAME_DATA)
            }
            val first = openWindow()
            assertHeader(first, R.string.status_updating_game_data, true)
            instrumentation.runOnMainSync {
                val header = first.findViewById<View>(R.id.app_header)
                header.layoutParams = header.layoutParams.apply {
                    width = (320 * first.resources.displayMetrics.density).toInt()
                }
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                val text = first.findViewById<TextView>(R.id.txt_status)
                assertTrue(text.width > 0 && text.layout != null)
                for (line in 0 until text.layout.lineCount) assertEquals(0, text.layout.getEllipsisCount(line))
                assertTrue("Update status must fit its measured height",
                    text.layout.height <= text.height - text.compoundPaddingTop - text.compoundPaddingBottom)
            }
            // Actual rendered evidence, with only synthetic state and public fixtures.
            val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            try {
                File(context.cacheDir, "payload-upgrade-status.png").outputStream().use {
                    assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
            } finally { screenshot.recycle() }
            instrumentation.runOnMainSync {
                // The service's real Stop responsiveness is tested separately.
                // Cancelling its queued start must leave active DB work visible.
                Bus.setStarting(false)
                Bus.setRunning(false)
                first.finish()
            }
            val reopened = openWindow()
            assertHeader(reopened, R.string.status_updating_game_data, true)
            instrumentation.runOnMainSync {
                assertEquals(reopened.getString(R.string.start_server), reopened.findViewById<Button>(R.id.btn_toggle).text.toString())
                Bus.setPreparationPhase(AssetInstaller.PreparationPhase.IDLE)
            }
            assertHeader(reopened, R.string.status_stopped, false)
            instrumentation.runOnMainSync { Bus.setPreparationPhase(AssetInstaller.PreparationPhase.FAILED) }
            assertHeader(reopened, R.string.status_preparation_failed, false)
            instrumentation.runOnMainSync { Bus.setStarting(true) }
            assertHeader(reopened, R.string.status_starting, true)
        } finally {
            instrumentation.runOnMainSync {
                windows.forEach { it.finish() }
                Bus.setRunning(previousRunning)
                Bus.setStarting(previousStarting)
                Bus.setPreparationPhase(previousPhase)
                Lang.setPref(context, previousLanguage)
                Lang.applyToApp(context)
            }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
            instrumentation.waitForIdleSync()
        }
    }

    @Test
    fun visibleWindowsReceiveUpdatesIndependently() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val firstWindow = Any()
        val secondWindow = Any()
        val firstLogs = mutableListOf<String>()
        val secondLogs = mutableListOf<String>()
        val firstStates = mutableListOf<Boolean>()
        val secondStates = mutableListOf<Boolean>()
        var firstToolsUpdates = 0
        var secondToolsUpdates = 0
        val initialState = Bus.serverRunning
        try {
            // A prior Activity may still have a coalesced startup notification.
            // Settle it before these listeners begin their independent lifetime.
            val settleOwner = Any()
            var settled = false
            instrumentation.runOnMainSync {
                Bus.addListener(settleOwner, { settled = true }, {})
                Bus.log("window bus listener barrier")
            }
            try { awaitLogs { settled } }
            finally { instrumentation.runOnMainSync { Bus.removeListener(settleOwner) } }
            instrumentation.runOnMainSync {
                Bus.addListener(firstWindow, { firstLogs.add(it) }, { firstStates.add(it) }, { firstToolsUpdates++ })
                Bus.addListener(secondWindow, { secondLogs.add(it) }, { secondStates.add(it) }, { secondToolsUpdates++ })
                Bus.log("both windows visible")
                Bus.setRunning(!initialState)
                Bus.toolsStateChanged()
            }
            instrumentation.waitForIdleSync()
            awaitLogs { firstLogs.size == 1 && secondLogs.size == 1 }
            assertEquals(listOf("both windows visible"), firstLogs)
            assertEquals(firstLogs, secondLogs)
            assertEquals(listOf(!initialState), firstStates)
            assertEquals(firstStates, secondStates)
            assertEquals(1, firstToolsUpdates)
            assertEquals(1, secondToolsUpdates)

            instrumentation.runOnMainSync {
                Bus.removeListener(firstWindow)
                Bus.log("second window visible")
                Bus.setRunning(initialState)
                Bus.toolsStateChanged()
            }
            instrumentation.waitForIdleSync()
            awaitLogs { secondLogs.size == 2 }
            assertEquals(listOf("both windows visible"), firstLogs)
            assertEquals(listOf("both windows visible", "second window visible"), secondLogs)
            assertEquals(listOf(!initialState), firstStates)
            assertEquals(listOf(!initialState, initialState), secondStates)
            assertEquals(1, firstToolsUpdates)
            assertEquals(2, secondToolsUpdates)
        } finally {
            instrumentation.runOnMainSync {
                Bus.removeListener(firstWindow)
                Bus.removeListener(secondWindow)
                Bus.setRunning(initialState)
            }
            instrumentation.waitForIdleSync()
        }
    }

    private fun awaitLogs(ready: () -> Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(3)
        while (System.nanoTime() < deadline) {
            var complete = false
            instrumentation.runOnMainSync { complete = ready() }
            if (complete) return
            Thread.sleep(10)
        }
        throw AssertionError("Coalesced log updates were not delivered to every visible window")
    }
}
