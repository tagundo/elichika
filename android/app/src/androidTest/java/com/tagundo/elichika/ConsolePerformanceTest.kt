package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Environment
import android.text.Editable
import android.text.TextWatcher
import android.view.View
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
            val scroll = launched.findViewById<NestedScrollView>(R.id.log_scroll)
            instrumentation.runOnMainSync { scroll.fullScroll(View.FOCUS_DOWN) }
            Thread.sleep(200)
            Bus.log("$prefix-follow-bottom")
            await { text.text.toString() == Bus.snapshot() && text.text.contains("$prefix-follow-bottom") }
            Thread.sleep(200)
            instrumentation.runOnMainSync {
                assertFalse("A reader at the bottom must follow new output", scroll.canScrollVertically(1))
                scroll.scrollTo(0, 0)
                assertTrue("The retained tail must have older output to read", scroll.canScrollVertically(1))
            }
            Bus.log("$prefix-keep-reading-position")
            await { text.text.toString() == Bus.snapshot() && text.text.contains("$prefix-keep-reading-position") }
            Thread.sleep(200)
            instrumentation.runOnMainSync {
                assertEquals("New output must not pull an older reader to the bottom", 0, scroll.scrollY)
                launched.findViewById<NestedScrollView>(R.id.console_scroll).fullScroll(View.FOCUS_DOWN)
            }
            instrumentation.waitForIdleSync()
            val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            try {
                File(context.filesDir, "console-performance-visible.png").outputStream().use {
                    assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
            } finally { screenshot.recycle() }
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
            report.put("burstLines", expected.size).put("producerNanos", producerNanos)
                .put("visibleTextChanges", visibleChanges).put("visibleChangedCharacters", visibleCharacters)
                .put("retainedCharacters", 200_000).put("persistentBurstLinesInOrder", expected.size)
                .put("collapsedChanges", 0).put("stoppedChanges", 0)
                .put("bottomFollowPreserved", true).put("olderReadingPositionPreserved", true)
                .put("clearThenAppendDisplayed", true).put("gameServerStayedStopped", true)
                .put("comparison", "Actual device rendering counters; no before-build speedup claimed")
                .put("status", "PASS")
        } catch (failure: Throwable) {
            report.put("status", "FAIL").put("error", failure.message?.take(1000) ?: failure.javaClass.simpleName)
            throw failure
        } finally {
            evidence.writeText(report.toString(2))
            instrumentation.runOnMainSync { activity?.finish() }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
            println("CONSOLE_PERFORMANCE_NATIVE_REPORT=$report")
        }
    }

    private fun await(ready: () -> Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        while (System.nanoTime() < deadline) {
            var complete = false
            instrumentation.runOnMainSync { complete = ready() }
            if (complete) return
            Thread.sleep(25)
        }
        throw AssertionError("Visible Console did not render its current retained tail")
    }
}
