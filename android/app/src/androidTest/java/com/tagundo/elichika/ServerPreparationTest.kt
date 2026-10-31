package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeFalse
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Heavy payload work must not prevent another window from cancelling Start. */
@RunWith(AndroidJUnit4::class)
class ServerPreparationTest {
    @Test
    fun pendingStartRemainsResponsiveAcrossWindowsAndStopWins() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assumeFalse("This test requires a stopped server", Bus.serverRunning)
        instrumentation.runOnMainSync {
            if (ServerService.current != null) ServerService.stop(context)
        }
        awaitOnMain(300) { ServerService.current == null }
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        preferences.edit().putBoolean("seen_guide", true).commit()
        val first = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        var second: android.app.Activity? = null
        val locked = CountDownLatch(1)
        val release = CountDownLatch(1)
        val worker = Executors.newSingleThreadExecutor()
        try {
            // Use the real install/reset serialization lock to simulate a slow
            // copy. This adds no test hook to the production startup path.
            worker.submit {
                synchronized(AssetInstaller) {
                    locked.countDown()
                    release.await(30, TimeUnit.SECONDS)
                }
            }
            assertTrue(locked.await(5, TimeUnit.SECONDS))
            instrumentation.runOnMainSync { ServerService.start(context) }
            awaitOnMain(10) { ServerService.current != null && Bus.serverStarting }
            val heartbeat = CountDownLatch(1)
            Handler(Looper.getMainLooper()).post { heartbeat.countDown() }
            assertTrue("Payload preparation must leave the main thread responsive",
                heartbeat.await(2, TimeUnit.SECONDS))

            second = instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
            )
            val cancellation = ServerService.cancellation
            instrumentation.runOnMainSync {
                assertFalse(ServerService.current!!.isReady)
                val toggle = second!!.findViewById<Button>(R.id.btn_toggle)
                assertEquals(context.getString(R.string.stop_server), toggle.text.toString())
                toggle.performClick()
            }
            awaitOnMain(10) { ServerService.cancellation != cancellation && !Bus.serverStarting }
            instrumentation.runOnMainSync {
                assertFalse(Bus.serverRunning)
                assertTrue("Keep the foreground service until its copy ends", ServerService.current != null)
            }
            release.countDown()
            awaitOnMain(300) { ServerService.current == null }
            assertFalse("Cancelled Start must never launch Go after setup", Bus.serverRunning)
            assertFalse(Bus.serverStarting)
        } finally {
            release.countDown()
            worker.shutdownNow()
            instrumentation.runOnMainSync {
                if (ServerService.current != null) ServerService.stop(context)
                second?.finish()
                first.finish()
            }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun awaitOnMain(timeoutSeconds: Long, condition: () -> Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(timeoutSeconds)
        while (System.nanoTime() < until) {
            var done = false
            instrumentation.runOnMainSync { done = condition() }
            if (done) return
            Thread.sleep(50)
        }
        fail("Server did not reach the requested preparation state")
    }
}
