package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Environment
import android.os.ParcelFileDescriptor
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.ViewTreeObserver
import android.widget.Button
import android.widget.TextView
import androidx.core.widget.NestedScrollView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch

/** Separate diagnostic run: this case is not part of the established 35-case suite. */
@RunWith(AndroidJUnit4::class)
class ConsolePerformanceTest {
    @Test
    fun burstUsesBatchedVisibleUpdatesAndSkipsCollapsedAndStoppedWindows() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        val report = JSONObject().put("status", "RUNNING")
        val evidence = File(context.filesDir, "console-performance-native.json")
        var activity: MainActivity? = null
        var changes = 0
        var changedCharacters = 0L
        val watcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                changes++
                changedCharacters += count
            }
            override fun afterTextChanged(s: Editable?) {}
        }
        try {
            val digest = MessageDigest.getInstance("SHA-256")
            File(context.applicationInfo.sourceDir).inputStream().use { input ->
                val bytes = ByteArray(128 * 1024)
                while (true) {
                    val count = input.read(bytes)
                    if (count < 0) break
                    digest.update(bytes, 0, count)
                }
            }
            report.put("applicationId", context.packageName)
                .put("apkSha256", digest.digest().joinToString("") { "%02x".format(it) })
            assertFalse("Standalone Console profiling must not start Go", Bus.serverRunning)
            assertFalse(Bus.serverStarting)
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            activity = launched
            instrumentation.runOnMainSync {
                NativeTabsQa.tab(launched, "console").select()
                launched.findViewById<Button>(R.id.btn_toggle_log).performClick()
                launched.findViewById<Button>(R.id.btn_clear_log).performClick()
            }
            // Let startup/clear settle before counting real TextView mutations.
            Thread.sleep(500)
            val text = launched.findViewById<TextView>(R.id.log_text)
            captureGraphics(context, "console-gfxinfo-before.txt", reset = true)
            instrumentation.runOnMainSync { text.addTextChangedListener(watcher) }
            val prefix = "console-qa-${System.nanoTime()}-"
            val expected = (0 until 10_000).map { prefix + it + " " + "x".repeat(60) }
            val began = System.nanoTime()
            // Instrumentation runs off main; this is the actual production Bus.
            expected.forEach(Bus::log)
            val producerNanos = System.nanoTime() - began
            await { text.text.toString() == Bus.snapshot() && text.text.endsWith(expected.last() + "\n") }
            var visibleChanges = 0
            var visibleCharacters = 0L
            instrumentation.runOnMainSync {
                visibleChanges = changes
                visibleCharacters = changedCharacters
                assertEquals(200_000, text.length())
                assertTrue("A burst must not redraw once per log line", visibleChanges in 1..40)
                assertTrue("Retained text remains complete", text.text.toString() == Bus.snapshot())
            }
            assertTrue("Final worker flush must finish", Bus.awaitLogFile(15_000))
            val disk = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                "sukusta/logs/elichika.log").readText()
            var position = -1
            expected.forEach { line ->
                val next = disk.indexOf(line + "\n", position + 1)
                assertTrue("Full persistent logs must preserve every line in order", next > position)
                position = next
            }
            report.put("burstLines", expected.size).put("producerNanos", producerNanos)
                .put("visibleTextChanges", visibleChanges).put("visibleChangedCharacters", visibleCharacters)
                .put("retainedCharacters", 200_000).put("persistentBurstLinesInOrder", expected.size)
            val scroll = launched.findViewById<NestedScrollView>(R.id.log_scroll)
            val outer = launched.findViewById<NestedScrollView>(R.id.console_scroll)
            // fullScroll focuses this selectable TextView, even while its
            // viewport is offscreen. Establish an actual visible reader using
            // public direct scrolling and prove the starting geometry first.
            instrumentation.runOnMainSync { outer.scrollTo(0, outer.getChildAt(0).height) }
            await("The actual Console viewport must be visible with settled text") { visibleAndSettled(launched, text) }
            instrumentation.runOnMainSync { scroll.scrollTo(0, text.height) }
            await("Prove actual visible bottom BEFORE appending") {
                !scroll.canScrollVertically(1) && visibleAndSettled(launched, text)
            }
            val bottomBefore = observe(launched, "bottomBefore", report)
            assertFalse("A fresh reader must not inherit fullScroll focus", bottomBefore.getBoolean("textFocused"))
            assertFalse("Starting bottom must be witnessed", bottomBefore.getBoolean("canScrollDown"))
            appendAndCompleteTraversal(text, "$prefix-follow-bottom", "bottomFrame", report)
            await { text.text.toString() == Bus.snapshot() && text.text.contains("$prefix-follow-bottom") && !text.isLayoutRequested }
            val bottomAfter = observe(launched, "bottomAfter", report)
            assertFalse("A reader at the visible bottom must follow new output", bottomAfter.getBoolean("canScrollDown"))
            assertEquals("Bottom follow must preserve the outer action-list position", bottomBefore.getInt("outerScrollY"), bottomAfter.getInt("outerScrollY"))
            assertVisible(bottomBefore); assertVisible(bottomAfter)
            instrumentation.runOnMainSync {
                scroll.scrollTo(0, 0)
                assertTrue("The retained tail must have older output to read", scroll.canScrollVertically(1))
            }
            val olderBefore = observe(launched, "olderBefore", report)
            assertVisible(olderBefore)
            appendAndCompleteTraversal(text, "$prefix-keep-reading-position", "olderFrame", report)
            await { text.text.toString() == Bus.snapshot() && text.text.contains("$prefix-keep-reading-position") && !text.isLayoutRequested }
            val olderAfter = observe(launched, "olderAfter", report)
            assertEquals("New output must not pull an older reader to the bottom", 0, olderAfter.getInt("scrollY"))
            assertEquals("New output must preserve the outer action-list position", olderBefore.getInt("outerScrollY"), olderAfter.getInt("outerScrollY"))
            assertVisible(olderAfter)
            // Geometry above is already sampled. This fixed interval lets the
            // compositor present the PNG; it never waits for a desired scroll.
            Thread.sleep(250)
            report.put("screenshotRequestedUptimeMillis", android.os.SystemClock.uptimeMillis())
            val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            try {
                File(context.filesDir, "console-performance-visible.png").outputStream().use {
                    assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
            } finally { screenshot.recycle() }
            captureGraphics(context, "console-gfxinfo-after.txt", reset = false)
            report.put("graphicsProcessId", android.os.Process.myPid())
                .put("liveGraphicsCapturedBeforeActivityFinish", true)
            instrumentation.runOnMainSync {
                launched.findViewById<Button>(R.id.btn_toggle_log).performClick()
                changes = 0
            }
            repeat(2_000) { Bus.log("$prefix-collapsed-$it") }
            Thread.sleep(600)
            instrumentation.runOnMainSync {
                assertEquals("Collapsed Console must not render log changes", 0, changes)
                assertEquals("", text.text.toString())
                launched.findViewById<Button>(R.id.btn_toggle_log).performClick()
                assertEquals(Bus.snapshot(), text.text.toString())
                launched.findViewById<Button>(R.id.btn_clear_log).performClick()
            }
            Bus.log("$prefix-after-clear")
            await { text.text.toString() == Bus.snapshot() && text.text.contains("$prefix-after-clear") }
            instrumentation.runOnMainSync {
                text.removeTextChangedListener(watcher)
                changes = 0
                text.addTextChangedListener(watcher)
                launched.finish()
            }
            instrumentation.waitForIdleSync()
            Thread.sleep(300)
            instrumentation.runOnMainSync { changes = 0 }
            repeat(2_000) { Bus.log("$prefix-stopped-$it") }
            Thread.sleep(600)
            instrumentation.runOnMainSync { assertEquals("Stopped windows must not render", 0, changes) }
            assertTrue(Bus.awaitLogFile(15_000))
            assertFalse(Bus.serverRunning)
            assertFalse(Bus.serverStarting)
            report.put("collapsedChanges", 0).put("stoppedChanges", 0)
                .put("bottomFollowPreserved", true).put("olderReadingPositionPreserved", true)
                .put("outerReadingPositionPreserved", true)
                .put("clearThenAppendDisplayed", true).put("gameServerStayedStopped", true)
                .put("comparison", "Actual device rendering counters; no before-build speedup claimed")
                .put("status", "PASS")
        } catch (failure: Throwable) {
            report.put("status", "FAIL").put("error", failure.message?.take(1000) ?: failure.javaClass.simpleName)
            throw failure
        } finally {
            val live = activity
            if (report.optString("status") != "PASS" && live != null && !live.isFinishing && !live.isDestroyed) {
                runCatching {
                    observe(live, "failureBeforeCleanup", report)
                    captureGraphics(context, "console-gfxinfo-failure.txt", reset = false)
                    Thread.sleep(250)
                    val image = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
                    try { File(context.filesDir, "console-performance-failure.png").outputStream().use {
                        assertTrue(image.compress(Bitmap.CompressFormat.PNG, 100, it))
                    } } finally { image.recycle() }
                }.onFailure { report.put("evidenceCaptureError", it.toString().take(1000)) }
            }
            evidence.writeText(report.toString(2))
            instrumentation.runOnMainSync { activity?.finish() }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
            println("CONSOLE_PERFORMANCE_NATIVE_REPORT=$report")
        }
    }

    private fun visibleAndSettled(activity: MainActivity, text: TextView): Boolean {
        val scroll = activity.findViewById<NestedScrollView>(R.id.log_scroll)
        val rect = Rect()
        return scroll.getGlobalVisibleRect(rect) && rect.width() > 0 && rect.height() > 40 &&
            text.layout != null && text.layout.lineCount > 0 && !text.isLayoutRequested && !scroll.isLayoutRequested
    }

    private fun observe(activity: MainActivity, name: String, report: JSONObject): JSONObject {
        val result = JSONObject()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val inner = activity.findViewById<NestedScrollView>(R.id.log_scroll)
            val text = activity.findViewById<TextView>(R.id.log_text)
            val rect = Rect(); val valid = inner.getGlobalVisibleRect(rect)
            result.put("uptimeMillis", android.os.SystemClock.uptimeMillis())
                .put("scrollY", inner.scrollY).put("canScrollDown", inner.canScrollVertically(1))
                .put("outerScrollY", activity.findViewById<NestedScrollView>(R.id.console_scroll).scrollY)
                .put("textFocused", text.isFocused).put("textLayoutRequested", text.isLayoutRequested)
                .put("innerLayoutRequested", inner.isLayoutRequested).put("textLineCount", text.layout?.lineCount ?: 0)
                .put("visibleRect", JSONObject().put("valid", valid).put("width", rect.width()).put("height", rect.height()))
            report.put(name, result)
        }
        return result
    }

    private fun assertVisible(sample: JSONObject) {
        assertTrue("The log viewport needs a valid visible rect", sample.getJSONObject("visibleRect").getBoolean("valid"))
        assertTrue("The log viewport must be visibly nonempty", sample.getJSONObject("visibleRect").getInt("height") > 40)
    }

    /** Wait for a real sentinel-containing traversal and the subsequent main
     * queue turn, never for the desired post-update scroll position. */
    private fun appendAndCompleteTraversal(text: TextView, sentinel: String, name: String, report: JSONObject) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val completed = CountDownLatch(1)
        val witness = JSONObject()
        lateinit var listener: ViewTreeObserver.OnPreDrawListener
        instrumentation.runOnMainSync {
            listener = ViewTreeObserver.OnPreDrawListener {
                if (text.text.contains(sentinel) && !text.isLayoutRequested) {
                    text.viewTreeObserver.removeOnPreDrawListener(listener)
                    witness.put("preDrawUptimeMillis", android.os.SystemClock.uptimeMillis())
                        .put("textLayoutRequested", text.isLayoutRequested)
                    text.post {
                        witness.put("completedTraversalQueueUptimeMillis", android.os.SystemClock.uptimeMillis())
                            .put("observedRealPreDrawAndSubsequentMainQueueTurn", true)
                        report.put(name, witness)
                        completed.countDown()
                    }
                }
                true
            }
            text.viewTreeObserver.addOnPreDrawListener(listener)
        }
        try {
            Bus.log(sentinel)
            assertTrue("The actual sentinel-containing traversal must complete before geometry sampling", completed.await(10, TimeUnit.SECONDS))
        } finally {
            instrumentation.runOnMainSync { text.viewTreeObserver.takeIf { it.isAlive }?.removeOnPreDrawListener(listener) }
        }
    }

    private fun captureGraphics(context: Context, name: String, reset: Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val command = "dumpsys gfxinfo ${context.packageName} " + if (reset) "reset" else "framestats"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(command)).use { input ->
            File(context.filesDir, name).outputStream().use { input.copyTo(it) }
        }
    }

    private fun await(reason: String = "Visible Console did not render its current retained tail", ready: () -> Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        while (System.nanoTime() < deadline) {
            var complete = false
            instrumentation.runOnMainSync { complete = ready() }
            if (complete) return
            Thread.sleep(25)
        }
        throw AssertionError(reason)
    }
}
