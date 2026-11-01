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
import com.google.android.material.tabs.TabLayout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
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

    @Test
    fun measuredWidthChangesColumnsWithoutReplacingActionsOrResettingPanels() = withActivity { activity ->
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        lateinit var originalButtons: Map<String, Button>
        lateinit var longLabelButton: Button
        instrumentation.runOnMainSync {
            activity.findViewById<Button>(R.id.btn_advanced).performClick()
            activity.findViewById<Button>(R.id.btn_toggle_log).performClick()
            Bus.log("console-grid-test: keep this log while resizing")
            originalButtons = actionButtons(activity)
            longLabelButton = requireNotNull(originalButtons["download_archive"])
            longLabelButton.text = "게임 데이터 전체 다운로드 — 진행 상태와 저장 공간을 확인한 뒤 " +
                "원하는 지역의 파일을 내려받습니다. 네트워크가 느리면 완료될 때까지 기다려 주세요."
        }
        instrumentation.waitForIdleSync()
        val fontScale = activity.resources.configuration.fontScale.coerceAtLeast(1f)
        val widths = listOf(320f to 1, 600f * fontScale to 2, 1000f * fontScale to 3)
        for ((width, columns) in widths) {
            resizeContent(activity, width)
            instrumentation.runOnMainSync {
                val grids = descendants(activity.findViewById(R.id.actions_row))
                    .filterIsInstance<ConsoleActionGrid>().toList()
                assertTrue("Each action section needs a responsive grid", grids.isNotEmpty())
                for (grid in grids) {
                    if (grid.childCount >= 3) {
                        assertEquals("Columns must follow the measured $width dp width", columns, grid.columnCount)
                    }
                    assertGridFitsItsMeasuredBounds(grid)
                }
                assertTrue("Long translated labels must wrap", longLabelButton.layout.lineCount > 1)
                assertTrue("Wrapped labels must retain their full height",
                    longLabelButton.layout.height <= longLabelButton.height -
                        longLabelButton.compoundPaddingTop - longLabelButton.compoundPaddingBottom)
                for (line in 0 until longLabelButton.layout.lineCount) {
                    assertEquals("Translated labels must not be truncated", 0,
                        longLabelButton.layout.getEllipsisCount(line))
                }
            }
        }

        // Resize while another tab is selected, then return to the existing
        // console. This must reflow the same controls instead of rebuilding UI.
        instrumentation.runOnMainSync {
            activity.findViewById<TabLayout>(R.id.tabs).getTabAt(1)!!.select()
        }
        resizeContent(activity, 320f)
        instrumentation.runOnMainSync {
            val tabs = activity.findViewById<TabLayout>(R.id.tabs)
            assertEquals("Resizing must preserve the selected tab", 1, tabs.selectedTabPosition)
            tabs.getTabAt(0)!!.select()
        }
        instrumentation.waitForIdleSync()
        assertConsoleStateRetained(activity, originalButtons, 1)
        resizeContent(activity, 1000f * fontScale)
        assertConsoleStateRetained(activity, originalButtons, 3)
    }

    private fun resizeContent(activity: MainActivity, widthDp: Float) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val content = activity.findViewById<FrameLayout>(R.id.content)
            content.layoutParams = content.layoutParams.apply {
                width = (widthDp * activity.resources.displayMetrics.density).toInt()
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun assertConsoleStateRetained(
        activity: MainActivity, originalButtons: Map<String, Button>, columns: Int
    ) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.advanced_scroll).visibility)
            assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.log_panel).visibility)
            assertTrue(activity.findViewById<TextView>(R.id.log_text).text
                .contains("console-grid-test: keep this log while resizing"))
            val currentButtons = actionButtons(activity)
            assertEquals(originalButtons.keys, currentButtons.keys)
            originalButtons.forEach { (id, button) ->
                assertSame("Resizing must retain action instances: $id", button, currentButtons[id])
            }
            for (container in listOf(R.id.actions_row, R.id.advanced_row)) {
                for (grid in descendants(activity.findViewById(container)).filterIsInstance<ConsoleActionGrid>()) {
                    if (grid.childCount >= 3) assertEquals(columns, grid.columnCount)
                    assertGridFitsItsMeasuredBounds(grid)
                }
            }
        }
    }

    private fun actionButtons(activity: MainActivity): Map<String, Button> =
        listOf(R.id.actions_row, R.id.advanced_row).flatMap { container ->
            descendants(activity.findViewById(container)).filterIsInstance<Button>().toList()
        }.associateBy { it.tag.toString() }

    private fun assertGridFitsItsMeasuredBounds(grid: ConsoleActionGrid) {
        val children = (0 until grid.childCount).map(grid::getChildAt)
            .filter { it.visibility != View.GONE }
        for (child in children) {
            assertTrue("Button must stay within the measured grid", child.left >= grid.paddingLeft &&
                child.right <= grid.width - grid.paddingRight && child.top >= grid.paddingTop &&
                child.bottom <= grid.height - grid.paddingBottom)
        }
        for (row in children.groupBy { it.top }.values) {
            assertTrue("A row must not exceed the column count", row.size <= grid.columnCount)
            assertTrue("Buttons in each row need equal widths", row.maxOf { it.width } - row.minOf { it.width } <= 1)
            assertEquals("Wrapped labels must share a row height", 1, row.map { it.height }.distinct().size)
        }
        for (first in children.indices) for (second in first + 1 until children.size) {
            val a = children[first]
            val b = children[second]
            assertFalse("Action buttons must not overlap", Rect.intersects(
                Rect(a.left, a.top, a.right, a.bottom), Rect(b.left, b.top, b.right, b.bottom)))
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
