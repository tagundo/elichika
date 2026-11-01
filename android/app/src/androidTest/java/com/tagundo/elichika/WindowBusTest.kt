package com.tagundo.elichika

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** One window leaving the screen must not unsubscribe another visible window. */
@RunWith(AndroidJUnit4::class)
class WindowBusTest {
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
            instrumentation.runOnMainSync {
                Bus.addListener(firstWindow, { firstLogs.add(it) }, { firstStates.add(it) }, { firstToolsUpdates++ })
                Bus.addListener(secondWindow, { secondLogs.add(it) }, { secondStates.add(it) }, { secondToolsUpdates++ })
                Bus.log("both windows visible")
                Bus.setRunning(!initialState)
                Bus.toolsStateChanged()
            }
            instrumentation.waitForIdleSync()
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
}
