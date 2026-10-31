package com.tagundo.elichika

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.TextView
import androidx.core.widget.NestedScrollView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Console actions remain reachable without giving the log most of the window. */
@RunWith(AndroidJUnit4::class)
class ConsoleLayoutTest {
    @Test
    fun logStartsCollapsedAndUserCanExpandClearAndCollapseIt() = withActivity { activity ->
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val panel = activity.findViewById<View>(R.id.log_panel)
            val toggle = activity.findViewById<Button>(R.id.btn_toggle_log)
            assertEquals(View.GONE, panel.visibility)
            assertNotNull(activity.findViewById<Button>(R.id.btn_share_log))
            assertNotNull(activity.findViewById<Button>(R.id.btn_clear_log))
            Bus.log("console-layout-test: diagnostic message")
            toggle.performClick()
            assertEquals(View.VISIBLE, panel.visibility)
        }
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            val text = activity.findViewById<TextView>(R.id.log_text)
            assertTrue(text.text.contains("console-layout-test: diagnostic message"))
            activity.findViewById<Button>(R.id.btn_clear_log).performClick()
            assertEquals("", text.text.toString())
            assertEquals("", Bus.snapshot())
            activity.findViewById<Button>(R.id.btn_toggle_log).performClick()
            assertEquals(View.GONE, activity.findViewById<View>(R.id.log_panel).visibility)
        }
    }

    @Test
    fun actionsAndAdvancedControlsFitAndScrollInANarrowShortWindow() = withActivity { activity ->
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val console = activity.findViewById<NestedScrollView>(R.id.console_scroll)
            val density = activity.resources.displayMetrics.density
            // Constrain the actual panel, exercising the same measurement as a
            // short split-screen window without changing emulator-wide settings.
            console.layoutParams = FrameLayout.LayoutParams(
                (280 * density).toInt(), (220 * density).toInt()
            )
        }
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            val console = activity.findViewById<NestedScrollView>(R.id.console_scroll)
            assertFalse("Console actions must not require horizontal scrolling", hasHorizontalScroll(console))
            val actions = activity.findViewById<ViewGroup>(R.id.actions_row)
            assertTrue("Actions must be able to scroll vertically", console.canScrollVertically(1))
            for (button in descendants(actions).filterIsInstance<Button>()) {
                assertTrue("Action is wider than its window: ${button.text}", button.width <= console.width)
            }
            val settings = requireNotNull(actions.findViewWithTag<Button>("settings")) {
                "The settings action must remain in the console"
            }
            reveal(settings)
            assertFullyVisible(settings, console)

            val advanced = activity.findViewById<View>(R.id.advanced_scroll)
            assertEquals(View.GONE, advanced.visibility)
            val toggle = activity.findViewById<Button>(R.id.btn_advanced)
            reveal(toggle)
            toggle.performClick()
            assertEquals(View.VISIBLE, advanced.visibility)
        }
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            val console = activity.findViewById<NestedScrollView>(R.id.console_scroll)
            val reset = requireNotNull(activity.findViewById<ViewGroup>(R.id.advanced_row)
                .findViewWithTag<Button>("reset_server")) {
                "Advanced reset action must remain available"
            }
            reveal(reset)
            assertFullyVisible(reset, console)
        }
    }

    private fun reveal(view: View) {
        view.requestRectangleOnScreen(Rect(0, 0, view.width, view.height), true)
    }

    private fun assertFullyVisible(view: View, container: View) {
        val visible = Rect()
        val bounds = Rect()
        assertTrue(view.getGlobalVisibleRect(visible))
        assertTrue(container.getGlobalVisibleRect(bounds))
        assertEquals("The full control must fit vertically", view.height, visible.height())
        assertTrue("Control must remain inside the window", bounds.contains(visible))
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) {
            for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
        }
    }

    private fun hasHorizontalScroll(view: View): Boolean =
        descendants(view).any { it is HorizontalScrollView }

    private fun withActivity(check: (MainActivity) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuidePreference = preferences.contains("seen_guide")
        val sawGuide = preferences.getBoolean("seen_guide", false)
        preferences.edit().putBoolean("seen_guide", true).commit()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        val activity = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ) as MainActivity
        try {
            instrumentation.waitForIdleSync()
            check(activity)
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
            preferences.edit().apply {
                if (hadGuidePreference) putBoolean("seen_guide", sawGuide) else remove("seen_guide")
            }.commit()
            instrumentation.waitForIdleSync()
        }
    }
}
