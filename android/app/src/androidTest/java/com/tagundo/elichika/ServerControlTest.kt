package com.tagundo.elichika

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeFalse
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Exercises the same worker-thread controller used by Python installer jobs. */
@RunWith(AndroidJUnit4::class)
class ServerControlTest {
    @Test
    fun installHoldSurvivesAnotherWorkerAndManualStopCancelsRestart() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assumeFalse("This test requires an initially stopped server", Bus.serverRunning)
        val activity = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        val controller = AndroidServerController(context)
        val otherWorker = Executors.newSingleThreadExecutor()
        try {
            assertTrue(controller.stop())
            assertFalse(controller.was_running_before_stop())

            // A second failed job's finally block must not release our DB hold.
            assertTrue(otherWorker.submit<Boolean> {
                try { controller.stop(); false }
                catch (_: Exception) { true }
                finally { controller.finish() }
            }.get(10, TimeUnit.SECONDS))
            instrumentation.runOnMainSync { ServerService.start(context) }
            instrumentation.waitForIdleSync()
            assertFalse("A second window must not start Go during writes", Bus.serverRunning)

            // Notification and UI Stop both dispatch this action. The user's
            // request takes precedence over the pending installer restart.
            val beforeStop = ServerService.cancellation
            instrumentation.runOnMainSync { ServerService.stop(context) }
            awaitOnMain { ServerService.cancellation != beforeStop }
            assertFalse(controller.start())
            assertFalse(Bus.serverRunning)
        } finally {
            controller.finish()
            otherWorker.shutdownNow()
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    private fun awaitOnMain(condition: () -> Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (System.nanoTime() < until) {
            var done = false
            instrumentation.runOnMainSync { done = condition() }
            if (done) return
            Thread.sleep(20)
        }
        fail("Service did not process the requested action")
    }
}
