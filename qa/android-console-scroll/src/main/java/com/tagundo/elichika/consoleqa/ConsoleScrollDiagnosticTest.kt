package com.tagundo.elichika.consoleqa

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.widget.Button
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch

/** QA-only producer/OS UI observer; the target signed C4 APK is never rebuilt. */
@RunWith(AndroidJUnit4::class)
class ConsoleScrollDiagnosticTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val report = JSONObject().put("status", "RUNNING")
    private var activity: Activity? = null
    private lateinit var log: (String) -> Unit
    private lateinit var snapshot: () -> String
    private fun view(name: String): View = requireNotNull(activity).findViewById(
        context.resources.getIdentifier(name, "id", "com.tagundo.elichika"))
    private fun text(): TextView = view("log_text") as TextView

    @Test
    fun observeOriginalSetupThenRequireVisibleSettledBottomFollow() {
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        try {
            val source = File(context.applicationInfo.sourceDir)
            val digest = MessageDigest.getInstance("SHA-256")
            source.inputStream().use { input ->
                val buffer = ByteArray(128 * 1024)
                while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
            }
            val sha = digest.digest().joinToString("") { "%02x".format(it) }
            report.put("apkSha256", sha).put("apkBytes", source.length())
                .put("sourceCommit", "28b80a8b43898ef9544d8452fef76181839eec6e")
                .put("qualification", "Separate diagnostic of exact C4; instrumented A variant is not an exact timing reproduction; original failed C4 test remains failed. No target APK, layout, selectability, callbacks or production code patched.")
            assertEquals("f97703fd863776882799f9efae7910518600d0ff7df0933cd4e54181a8369f66", sha)
            assertEquals(290920807L, source.length())
            // Reflection is solely a linkage adapter so this tiny instrumentation
            // compiles without rebuilding the target. These are its real public
            // log producer and snapshot APIs, as in the existing native case.
            val bus = Class.forName("com.tagundo.elichika.Bus", true, context.classLoader)
            val instance = bus.getField("INSTANCE").get(null)
            val write = bus.getMethod("log", String::class.java)
            val read = bus.getMethod("snapshot")
            log = { line -> write.invoke(instance, line); Unit }
            snapshot = { read.invoke(instance) as String }
            assertEquals(false, bus.getMethod("getServerRunning").invoke(instance))
            assertEquals(false, bus.getMethod("getServerStarting").invoke(instance))
            preferences.edit().putBoolean("seen_guide", true).commit()
            activity = instrumentation.startActivitySync(Intent().setClassName("com.tagundo.elichika", "com.tagundo.elichika.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.runOnMainSync {
                if (view("log_panel").visibility != View.VISIBLE) (view("btn_toggle_log") as Button).performClick()
                (view("btn_clear_log") as Button).performClick()
            }
            Thread.sleep(500)
            val prefix = "c4-scroll-${System.nanoTime()}-"
            repeat(10000) { log(prefix + it + " " + "x".repeat(60)) }
            await("Initial real retained text/layout") {
                text().text.toString() == snapshot() && text().length() == 200000 && !text().isLayoutRequested && text().layout != null
            }
            capture("A-before-original-fullScroll")
            instrumentation.runOnMainSync {
                val scroll = view("log_scroll")
                scroll.javaClass.getMethod("fullScroll", Integer.TYPE).invoke(scroll, View.FOCUS_DOWN)
            }
            Thread.sleep(200) // Instrumented A variant: same fullScroll/200ms setup, with extra observations.
            val aBefore = capture("A-original-before-append")
            log(prefix + "original-follow-sentinel")
            await("Original sentinel visible in actual text") { text().text.toString() == snapshot() && text().text.contains(prefix + "original-follow-sentinel") }
            Thread.sleep(200)
            val aAfter = capture("A-original-after-append")
            report.put("originalSetup", JSONObject().put("preBottom", !aBefore.getBoolean("canScrollDown"))
                .put("postBottom", !aAfter.getBoolean("canScrollDown")))
            // A's fullScroll focuses a selectable TextView. A fresh Activity
            // prevents that test-induced focus from contaminating the visible
            // reader control. The production Bus and retained tail stay intact.
            val originalActivity = requireNotNull(activity)
            instrumentation.runOnMainSync { originalActivity.finish() }
            instrumentation.waitForIdleSync()
            await("Original setup Activity destroyed") { originalActivity.isDestroyed }
            activity = instrumentation.startActivitySync(Intent().setClassName("com.tagundo.elichika", "com.tagundo.elichika.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.runOnMainSync {
                if (view("log_panel").visibility != View.VISIBLE) (view("btn_toggle_log") as Button).performClick()
            }
            await("Fresh Activity retained text/layout ready") {
                text().text.toString() == snapshot() && text().length() == 200000 &&
                    text().layout != null && !text().isLayoutRequested
            }
            report.put("controlledSetupUsesFreshActivity", true)
            capture("B-fresh-before-bring-onscreen")
            // B: make the actual viewport visible, require a settled nonempty
            // layout, and prove the starting scroll position before appending.
            instrumentation.runOnMainSync {
                val outer = view("console_scroll") as ViewGroup
                outer.scrollTo(0, outer.getChildAt(0).height)
            }
            await("Actual log viewport is onscreen with nonempty settled layout") {
                val visible = Rect()
                view("log_scroll").getGlobalVisibleRect(visible) && visible.width() > 0 && visible.height() > 40 &&
                    text().layout != null && text().layout.lineCount > 0 && !text().isLayoutRequested && !view("log_scroll").isLayoutRequested
            }
            capture("B-visible-before-scroll")
            instrumentation.runOnMainSync {
                val inner = view("log_scroll") as ViewGroup
                inner.scrollTo(0, inner.getChildAt(0).height)
            }
            await("Prove bottom BEFORE sentinel") { !view("log_scroll").canScrollVertically(1) && !text().isLayoutRequested }
            Thread.sleep(200)
            val bBefore = capture("B-proven-visible-bottom-before-append")
            assertFalse("Starting bottom must be witnessed, not assumed", bBefore.getBoolean("canScrollDown"))
            assertTrue("The actual log viewport needs a valid visible rect", bBefore.getJSONObject("visibleRect").getBoolean("valid"))
            assertTrue("The actual log viewport must be visible", bBefore.getJSONObject("visibleRect").getInt("height") > 40)
            assertFalse("Fresh control must not inherit fullScroll's focused TextView", bBefore.getBoolean("textFocused"))
            appendAndCompleteTraversal("B-follow-frame", prefix + "controlled-follow-sentinel")
            await("Controlled sentinel text and actual layout complete") {
                text().text.toString() == snapshot() && text().text.contains(prefix + "controlled-follow-sentinel") && !text().isLayoutRequested
            }
            val bAfter = capture("B-visible-after-append")
            report.put("controlledSetup", JSONObject().put("preBottom", !bBefore.getBoolean("canScrollDown"))
                .put("postBottom", !bAfter.getBoolean("canScrollDown"))
                .put("clearedTestFocusToEstablishBottom", false))
            save()
            assertFalse("A reader proven at the visible bottom must follow new output", bAfter.getBoolean("canScrollDown"))
            assertEquals("Bottom follow must preserve the outer action-list position", bBefore.getInt("outerScrollY"), bAfter.getInt("outerScrollY"))
            assertTrue("Bottom reader viewport needs a valid visible rect", bAfter.getJSONObject("visibleRect").getBoolean("valid"))
            assertTrue("Bottom reader viewport must remain visible", bAfter.getJSONObject("visibleRect").getInt("height") > 40)
            instrumentation.runOnMainSync { view("log_scroll").scrollTo(0, 0) }
            val oldBefore = capture("B-older-reading-before-append")
            assertTrue(oldBefore.getBoolean("canScrollDown"))
            assertTrue("Older-reader starting viewport needs a valid visible rect", oldBefore.getJSONObject("visibleRect").getBoolean("valid"))
            assertTrue("Older-reader starting viewport must be visible", oldBefore.getJSONObject("visibleRect").getInt("height") > 40)
            appendAndCompleteTraversal("B-older-reading-frame", prefix + "controlled-keep-reading-sentinel")
            await("Older-reader sentinel and actual layout complete") {
                text().text.toString() == snapshot() && text().text.contains(prefix + "controlled-keep-reading-sentinel") && !text().isLayoutRequested
            }
            val oldAfter = capture("B-older-reading-after-append")
            assertEquals("Older reader must not be pulled to the bottom", 0, oldAfter.getInt("scrollY"))
            assertEquals("New output must preserve the outer action-list position", oldBefore.getInt("outerScrollY"), oldAfter.getInt("outerScrollY"))
            assertTrue("Older-reader viewport needs a valid visible rect", oldAfter.getJSONObject("visibleRect").getBoolean("valid"))
            assertTrue("Older-reader viewport must remain visible", oldAfter.getJSONObject("visibleRect").getInt("height") > 40)
            report.put("controlledOlderReadingPositionPreserved", true).put("controlledOuterPositionPreserved", true)
                .put("status", "DIAGNOSTIC_VISIBLE_PRECONDITION_AND_FOLLOW_PASSED")
        } catch (failure: Throwable) {
            report.put("status", "DIAGNOSTIC_FAILED").put("error", failure.toString().take(1000))
            runCatching { capture("failure-before-activity-finish") }
            throw failure
        } finally {
            save()
            instrumentation.runOnMainSync { activity?.finish() }
            preferences.edit().apply { if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide") }.commit()
            println("EXACT_C4_SCROLL_DIAGNOSTIC=$report")
        }
    }

    /** Observe a real sentinel-containing pre-draw, then a main-queue turn after
     * the whole traversal (including production doOnPreDraw) has completed.
     * This waits on rendering, never on a desired scroll position. */
    private fun appendAndCompleteTraversal(label: String, sentinel: String) {
        val completed = CountDownLatch(1)
        val witness = JSONObject()
        lateinit var listener: ViewTreeObserver.OnPreDrawListener
        instrumentation.runOnMainSync {
            val target = text()
            listener = ViewTreeObserver.OnPreDrawListener {
                if (target.text.contains(sentinel) && !target.isLayoutRequested) {
                    target.viewTreeObserver.removeOnPreDrawListener(listener)
                    witness.put("preDrawUptimeMillis", android.os.SystemClock.uptimeMillis())
                        .put("textCharacters", target.length()).put("textLayoutRequested", target.isLayoutRequested)
                    target.post {
                        witness.put("completedTraversalQueueUptimeMillis", android.os.SystemClock.uptimeMillis())
                            .put("observedRealPreDrawAndSubsequentMainQueueTurn", true)
                        report.put(label, witness)
                        save()
                        completed.countDown()
                    }
                }
                true
            }
            target.viewTreeObserver.addOnPreDrawListener(listener)
        }
        try {
            log(sentinel)
            assertTrue("Actual sentinel-containing traversal must complete before sampling scroll geometry", completed.await(10, TimeUnit.SECONDS))
        } finally {
            instrumentation.runOnMainSync { text().viewTreeObserver.takeIf { it.isAlive }?.removeOnPreDrawListener(listener) }
        }
    }

    private fun capture(name: String): JSONObject {
        val value = JSONObject()
        instrumentation.runOnMainSync {
            val inner = view("log_scroll") as ViewGroup
            val outer = view("console_scroll")
            val t = text()
            val rect = Rect()
            val global = inner.getGlobalVisibleRect(rect)
            val location = IntArray(2); inner.getLocationOnScreen(location)
            value.put("uptimeMillis", android.os.SystemClock.uptimeMillis()).put("scrollY", inner.scrollY)
                .put("canScrollDown", inner.canScrollVertically(1)).put("canScrollUp", inner.canScrollVertically(-1))
                .put("height", inner.height).put("width", inner.width).put("childHeight", inner.getChildAt(0)?.height ?: 0)
                .put("outerScrollY", outer.scrollY).put("outerHeight", outer.height)
                .put("innerLayoutRequested", inner.isLayoutRequested).put("textLayoutRequested", t.isLayoutRequested)
                .put("textHeight", t.height).put("textCharacters", t.length()).put("textLineCount", t.layout?.lineCount ?: -1)
                .put("textFocused", t.isFocused).put("innerFocused", inner.isFocused)
                .put("selectionStart", t.selectionStart).put("selectionEnd", t.selectionEnd)
                .put("windowHasFocus", requireNotNull(activity).hasWindowFocus())
                .put("visibleRect", JSONObject().put("valid", global).put("left", rect.left).put("top", rect.top)
                    .put("width", rect.width()).put("height", rect.height()))
                .put("locationOnScreen", JSONObject().put("x", location[0]).put("y", location[1]))
            report.put(name, value)
        }
        // Geometry above is already fixed in the report. Wait a fixed compositor
        // interval solely for the PNG; never poll for a desired scroll outcome.
        Thread.sleep(250)
        value.put("screenshotRequestedUptimeMillis", android.os.SystemClock.uptimeMillis())
        val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        try { File(context.filesDir, "console-scroll-$name.png").outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) } }
        finally { bitmap.recycle() }
        save()
        return value
    }
    private fun save() { File(context.filesDir, "console-scroll-diagnostic.json").writeText(report.toString(2)) }
    private fun await(reason: String, ready: () -> Boolean) { assertTrue(reason, waitUntil(10000, ready)) }
    private fun waitUntil(timeoutMillis: Long, ready: () -> Boolean): Boolean {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        while (System.nanoTime() < deadline) {
            var complete = false
            instrumentation.runOnMainSync { complete = ready() }
            if (complete) return true
            Thread.sleep(50)
        }
        return false
    }
}
