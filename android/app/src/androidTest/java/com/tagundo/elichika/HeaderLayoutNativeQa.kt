package com.tagundo.elichika

import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.graphics.drawable.ColorDrawable
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import androidx.core.graphics.ColorUtils
import com.google.android.material.color.MaterialColors
import com.google.android.material.tabs.TabLayout
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.ceil

/** Extra phases of existing tests; never starts the game server or replaces chrome. */
internal object HeaderLayoutNativeQa {
    fun exercise(activity: MainActivity, wide: Boolean, retainedWebView: WebView? = null): JSONObject {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        lateinit var header: LinearLayout
        lateinit var controls: LinearLayout
        lateinit var tabs: TabLayout
        lateinit var status: TextView
        lateinit var toggle: Button
        lateinit var progress: ProgressBar
        lateinit var tabViews: List<View>
        lateinit var tabObjects: List<TabLayout.Tab>
        lateinit var labels: List<CharSequence?>
        var selected = 0
        var originalWidth = 0
        var originalStatus: CharSequence = ""
        var originalToggle: CharSequence = ""
        var originalProgress = View.GONE
        var originalHeaderVisibility = View.VISIBLE
        var originalTabsVisibility = View.VISIBLE
        var originalWebViewUrl: String? = null
        instrumentation.runOnMainSync {
            header = activity.findViewById(R.id.app_header)
            tabs = activity.findViewById(R.id.tabs)
            assertEquals("The adaptive header owns exactly the original server row and tabs", 2, header.childCount)
            controls = header.getChildAt(0) as LinearLayout
            assertSame(tabs, header.getChildAt(1))
            status = activity.findViewById(R.id.txt_status)
            toggle = activity.findViewById(R.id.btn_toggle)
            progress = activity.findViewById(R.id.progress_preparing)
            assertSame(controls, status.parent)
            assertSame(controls, toggle.parent)
            assertSame(controls, progress.parent)
            assertEquals(5, tabs.tabCount)
            val strip = tabs.getChildAt(0) as ViewGroup
            tabViews = (0 until 5).map(strip::getChildAt)
            tabObjects = (0 until 5).map { tabs.getTabAt(it)!! }
            labels = tabObjects.map { it.text }
            selected = tabs.selectedTabPosition
            originalWidth = header.layoutParams.width
            originalStatus = status.text
            originalToggle = toggle.text
            originalProgress = progress.visibility
            originalHeaderVisibility = header.visibility
            originalTabsVisibility = tabs.visibility
            originalWebViewUrl = retainedWebView?.url
            assertEquals(View.VISIBLE, originalHeaderVisibility)
            assertEquals(View.VISIBLE, originalTabsVisibility)
            if (wide) assertTrue("The wide phase needs a real 1600dp native window",
                (header.rootView.width / activity.resources.displayMetrics.density) >= 1599)
        }
        val density = activity.resources.displayMetrics.density
        val systemFontScale = activity.resources.configuration.fontScale
        val diagnosticOnly = InstrumentationRegistry.getArguments().getString("headerDiagnosticOnly") == "true"
        val expectedFontScale = InstrumentationRegistry.getArguments().getString("expectedFontScale")?.let {
            requireNotNull(it.toFloatOrNull()) { "expectedFontScale must be a number" }
        }
        expectedFontScale?.let {
            assertTrue("This launch must use the requested real system fontScale: $it, actual $systemFontScale",
                kotlin.math.abs(systemFontScale - it) < .02f)
        }
        val samples = JSONArray()
        val measurements = JSONArray()
        val inlinePositionComparisons = JSONArray()
        val inlineTabPositions = mutableMapOf<String, Pair<String, List<Rect>>>()
        val report = JSONObject().put("wide", wide).put("samples", samples)
            .put("measurements", measurements).put("diagnosticOnly", diagnosticOnly)
            .put("inlinePositionComparisons", inlinePositionComparisons)
            .put("systemFontScale", systemFontScale)
            .put("expectedFontScale", expectedFontScale ?: JSONObject.NULL)
            .put("fontScaling", "Actual system fontScale and native TextView paints; no test font or private-field overrides")
            .put("statusStateScope", "Translated stopped/running/preparing/updating/failed text, Start/Stop labels and progress on actual views; no server state changes")
        val night = (activity.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        InstrumentationRegistry.getArguments().getString("expectedNightMode")?.let { expected ->
            assertTrue("expectedNightMode must be yes or no", expected in listOf("yes", "no"))
            assertEquals("Use the requested actual Android night mode", expected == "yes", night)
        }
        val surface = MaterialColors.getColor(header, com.google.android.material.R.attr.colorSurface)
        val onSurface = MaterialColors.getColor(header, com.google.android.material.R.attr.colorOnSurface)
        val primary = MaterialColors.getColor(header, com.google.android.material.R.attr.colorPrimary)
        val theme = JSONObject().put("night", night).put("surface", surface).put("onSurface", onSurface).put("primary", primary)
        report.put("theme", theme)
        var expectedStatus = originalStatus.toString()
        var expectedProgress = originalProgress
        var expectedToggle = originalToggle.toString()
        fun rightMargin(view: View) = (view.layoutParams as? ViewGroup.MarginLayoutParams)?.rightMargin ?: 0
        fun rectJson(rect: Rect) = JSONObject().put("left", rect.left).put("top", rect.top)
            .put("right", rect.right).put("bottom", rect.bottom)
        fun mutate(action: () -> Unit) {
            val latch = CountDownLatch(1)
            instrumentation.runOnMainSync {
                action()
                header.requestLayout()
                header.postOnAnimation { header.postOnAnimation { header.postOnAnimation { latch.countDown() } } }
            }
            assertTrue("The actual native header must settle after layout", latch.await(10, TimeUnit.SECONDS))
            instrumentation.waitForIdleSync()
        }
        fun width(dp: Int) = mutate {
            header.layoutParams = header.layoutParams.apply { width = ceil(dp * density.toDouble()).toInt() }
        }
        fun configure(language: String, statusId: Int, busy: Boolean, stopAction: Boolean = false) = mutate {
            val configuration = Configuration(activity.resources.configuration).apply { setLocale(Locale(language)) }
            val strings = activity.createConfigurationContext(configuration).resources
            expectedToggle = strings.getString(if (stopAction) R.string.stop_server else R.string.start_server)
            toggle.text = expectedToggle
            expectedStatus = strings.getString(statusId)
            status.text = expectedStatus
            expectedProgress = if (busy) View.VISIBLE else View.GONE
            progress.visibility = expectedProgress
            val ids = listOf(R.string.tab_console, R.string.tab_webui, R.string.tab_user, R.string.tab_dev, R.string.tab_mod)
            ids.forEachIndexed { index, id -> tabObjects[index].text = strings.getString(id) }
        }
        fun check(language: String, scale: Float, state: String, dp: Int): JSONObject {
            lateinit var result: JSONObject
            instrumentation.runOnMainSync {
                val strip = tabs.getChildAt(0) as ViewGroup
                val tabRects = tabViews.map { bounds(header, it) }
                val expectedGroupRight = header.width - header.paddingRight - rightMargin(tabs) -
                    tabs.paddingRight - rightMargin(strip) - strip.paddingRight - rightMargin(tabViews.last())
                val groupGeometry = JSONObject().put("left", tabRects.first().left)
                    .put("right", tabRects.last().right).put("expectedRight", expectedGroupRight)
                    .put("edgeInset", header.width - tabRects.last().right)
                    .put("tabRects", JSONArray(tabRects.map(::rectJson)))
                val measured = fitInputs(activity, header, controls, tabs)
                    .put("requested", JSONObject().put("language", language).put("fontScale", scale)
                        .put("state", state).put("widthDp", dp).put("widthPx", ceil(dp * density.toDouble()).toInt()))
                    .put("tabGroup", groupGeometry)
                measurements.put(measured)
                report.put("lastFitInputs", measured)
                logFitInputs(measured)
                assertEquals(ceil(dp * density.toDouble()).toInt(), header.width)
                assertEquals(2, header.childCount)
                assertEquals("The requested full status must remain under test", expectedStatus, status.text.toString())
                assertEquals("The requested Start/Stop action must remain under test", expectedToggle, toggle.text.toString())
                assertEquals("The requested busy spinner state must remain under test", expectedProgress, progress.visibility)
                assertSame(controls, header.getChildAt(0))
                assertSame(tabs, header.getChildAt(1))
                assertEquals("Reflow must retain the selected tab", selected, tabs.selectedTabPosition)
                tabObjects.forEachIndexed { index, tab ->
                    assertSame("Keep each existing tab and its click handler", tab, tabs.getTabAt(index))
                    assertSame("Keep each existing native tab view", tabViews[index], strip.getChildAt(index))
                }
                retainedWebView?.let { assertTrue("Resizing must retain the active WebView instance",
                    descendants(activity.findViewById(R.id.content)).any { view -> view === it }) }
                assertTrue("The server action must retain its 44dp touch height", toggle.height + 1 >= 44 * density)
                assertTrue("The server action must retain its 44dp touch width", toggle.width + 1 >= 44 * density)
                assertReadable(toggle)
                assertReadable(status)
                val controlRect = bounds(header, controls)
                val tabRect = bounds(header, tabs)
                assertTrue("Server controls stay inside the measured header", controlRect.left >= 0 && controlRect.right <= header.width)
                assertTrue("Navigation stays inside the measured header", tabRect.left >= 0 && tabRect.right <= header.width)
                assertFalse("Server controls and navigation must not overlap", Rect.intersects(controlRect, tabRect))
                val visibleControls = (0 until controls.childCount).map(controls::getChildAt)
                    .filter { it.visibility == View.VISIBLE }
                for (first in visibleControls.indices) for (second in first + 1 until visibleControls.size) {
                    assertFalse("Server action, progress and full status must not overlap", Rect.intersects(
                        bounds(controls, visibleControls[first]), bounds(controls, visibleControls[second])))
                }
                val inline = header.orientation == LinearLayout.HORIZONTAL
                for (view in listOf(header, controls, tabs)) {
                    assertEquals("Both header groups and their gap must use the actual theme surface",
                        surface, (view.background as? ColorDrawable)?.color)
                }
                assertEquals("Status text must use the theme's readable foreground", onSurface, status.currentTextColor)
                assertEquals("The server action must use the theme's readable foreground", onSurface, toggle.currentTextColor)
                assertEquals("The server action keeps its shape on the shared surface", surface,
                    toggle.backgroundTintList?.getColorForState(toggle.drawableState, surface))
                val spinnerColor = requireNotNull(progress.indeterminateTintList).getColorForState(progress.drawableState, onSurface)
                assertEquals("The spinner must contrast with the shared surface", onSurface, spinnerColor)
                assertTrue("Full status text must retain 4.5:1 contrast", ColorUtils.calculateContrast(status.currentTextColor, surface) >= 4.5)
                assertTrue("The server action must retain 4.5:1 contrast", ColorUtils.calculateContrast(toggle.currentTextColor, surface) >= 4.5)
                assertTrue("The preparation indicator must retain 3:1 contrast", ColorUtils.calculateContrast(spinnerColor, surface) >= 3.0)
                assertEquals("Unselected tabs remain readable on the shared surface", onSurface, tabs.tabTextColors?.defaultColor)
                assertEquals("Keep the selected-tab primary accent", primary,
                    tabs.tabTextColors?.getColorForState(intArrayOf(android.R.attr.state_selected), onSurface))
                theme.put("statusContrast", ColorUtils.calculateContrast(status.currentTextColor, surface))
                    .put("actionContrast", ColorUtils.calculateContrast(toggle.currentTextColor, surface))
                    .put("spinnerContrast", ColorUtils.calculateContrast(spinnerColor, surface))
                if (dp == 320 && state == "stopped") assertFalse("A narrow stopped header must retain two readable rows", inline)
                if (language == "ko" && kotlin.math.abs(scale - 1f) < .01f && state == "stopped" && dp in listOf(768, 853)) {
                    assertTrue("Korean stopped controls and all five tabs must fit inline at $dp dp", inline)
                }
                if (inline) {
                    assertEquals("The actual five-tab group must end at the padded header edge: $groupGeometry",
                        expectedGroupRight, tabRects.last().right)
                    val key = JSONArray().put(language).put(scale.toDouble()).put(header.width)
                        .put(JSONArray(tabObjects.map { it.text.toString() })).toString()
                    val reference = inlineTabPositions.getOrPut(key) { state to tabRects.map { Rect(it) } }
                    inlinePositionComparisons.put(JSONObject().put("language", language).put("fontScale", scale)
                        .put("widthDp", dp).put("referenceState", reference.first).put("state", state)
                        .put("referenceTabRects", JSONArray(reference.second.map(::rectJson)))
                        .put("actualTabRects", JSONArray(tabRects.map(::rectJson))))
                    tabRects.forEachIndexed { index, rect ->
                        val message = "Status changes must retain each inline tab X position: $language/$scale/$dp " +
                            "${reference.first}->$state tab=$index reference=${reference.second[index]} actual=$rect"
                        assertEquals(message, reference.second[index].left, rect.left)
                        assertEquals(message, reference.second[index].right, rect.right)
                    }
                }
                tabViews.forEachIndexed { index, tab ->
                    assertTrue("Every native tab needs a 44dp touch target", tab.width + 1 >= 44 * density && tab.height + 1 >= 44 * density)
                    descendants(tab).filterIsInstance<TextView>().filter { it.text.isNotEmpty() }.forEach(::assertReadable)
                    if (inline) {
                        val rect = bounds(header, tab)
                        val target = "tab=$index rect=$rect header=${header.width}x${header.height} navigationScrollX=${tabs.scrollX}"
                        assertTrue("All five inline tabs must be fully inside the header: $target", rect.left >= 0 && rect.right <= header.width && rect.top >= 0 && rect.bottom <= header.height)
                        val visible = Rect()
                        assertTrue("Every inline tab must actually be visible in the native window: $target", tab.getGlobalVisibleRect(visible))
                        assertEquals("The whole inline tab width must be visible: $target visible=$visible", tab.width, visible.width())
                        assertEquals("The whole inline tab height must be visible: $target visible=$visible", tab.height, visible.height())
                    }
                }
                assertTrue("The full status layout must fit its row", status.height <= controls.height)
                result = JSONObject().put("language", language).put("fontScale", scale).put("state", state)
                    .put("widthDp", dp).put("measuredWidth", header.width).put("height", header.height)
                    .put("inline", inline).put("status", status.text).put("statusLines", status.layout.lineCount)
                    .put("statusTextSizePx", status.textSize).put("progressVisible", progress.visibility == View.VISIBLE)
                    .put("toggle", toggle.text).put("tabGroup", groupGeometry)
                    .put("tabCount", tabs.tabCount).put("selectedTab", tabs.selectedTabPosition)
                    .put("tabTextSizesPx", JSONArray(tabViews.map { tab -> descendants(tab).filterIsInstance<TextView>().first { it.text.isNotEmpty() }.textSize }))
            }
            if (wide && language == "ko" && dp == 853 && state in listOf("stopped", "running", "preparing")) {
                val name = "header-layout-state-$state.png"
                val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot()) {
                    "Capture the actual $state header before changing its status"
                }
                try {
                    File(activity.cacheDir, name).outputStream().use {
                        assertTrue("Write the actual $state header screenshot", bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
                    }
                } finally { bitmap.recycle() }
                result.put("screenshot", name)
            }
            samples.put(result)
            return result
        }
        try {
            val widths = if (wide) listOf(320, 768, 853, 1000, 1600) else listOf(320)
            for (language in listOf("en", "ko", "ja")) {
                val scale = systemFontScale
                configure(language, R.string.status_stopped, false)
                for (dp in widths) { width(dp); check(language, scale, "stopped", dp) }
                if (wide || language == "ko") {
                    configure(language, R.string.status_updating_game_data, true)
                    width(320); check(language, scale, "updating", 320)
                    if (wide) {
                        for (dp in listOf(853, 1600)) { width(dp); check(language, scale, "updating", dp) }
                    }
                    configure(language, R.string.status_preparation_failed, false)
                    width(320); check(language, scale, "failed", 320)
                }
                if (wide) {
                    configure(language, R.string.status_running, false, stopAction = true)
                    for (dp in listOf(853, 1600)) { width(dp); check(language, scale, "running", dp) }
                    configure(language, R.string.status_preparing, true)
                    for (dp in listOf(853, 1600)) { width(dp); check(language, scale, "preparing", dp) }
                }
            }
            if (diagnosticOnly) {
                report.put("status", "PASS").put("nativeGeometryOnly", true)
                    .put("notExecuted", JSONArray(listOf("narrowTabNavigation", "chromeGoneResize", "webViewRetention")))
                    .put("scope", "All ${samples.length()} strict native measurement cases; tool-tab navigation is outside the focused comparison")
                return report
            }
            configure("ko", R.string.status_stopped, false)
            width(320)
            // Exercise each actual tab's scroll/reveal and existing selection
            // callback; no Start server action is clicked.
            for (index in 0 until 5) {
                mutate {
                    val tab = tabViews[index]
                    tabObjects[index].select()
                    tab.requestRectangleOnScreen(Rect(0, 0, tab.width, tab.height), true)
                }
                awaitFullyVisible(tabViews[index])
                instrumentation.runOnMainSync {
                    val visible = Rect()
                    assertEquals(index, tabs.selectedTabPosition)
                    assertTrue("Every narrow tab must be reachable by scrolling", tabViews[index].getGlobalVisibleRect(visible))
                    assertEquals(tabViews[index].width, visible.width())
                    assertEquals(tabViews[index].height, visible.height())
                    if (index == 0) assertEquals("The original Console listener must still reveal the console",
                        View.VISIBLE, activity.findViewById<View>(R.id.console_scroll).visibility)
                }
            }
            mutate { tabObjects[selected].select() }
            instrumentation.runOnMainSync {
                retainedWebView?.let { existing ->
                    assertTrue("Returning through the original tab listener must reveal the same WebView",
                        descendants(activity.findViewById(R.id.content)).any { it === existing })
                    assertEquals(View.VISIBLE, existing.visibility)
                    assertEquals("Native header reflow must retain the existing page", originalWebViewUrl, existing.url)
                }
            }
            val beforeHidden = header.orientation
            mutate { header.visibility = View.GONE; tabs.visibility = View.GONE }
            width(if (wide) 1600 else 600)
            instrumentation.runOnMainSync {
                assertEquals("Reflow must not restore fullscreen chrome", View.GONE, header.visibility)
                assertEquals(View.GONE, tabs.visibility)
                assertEquals("Hidden chrome must not be rearranged", beforeHidden, header.orientation)
            }
            report.put("narrowTabsReachable", true).put("chromeGonePreserved", true)
                .put("tabAndViewInstancesRetained", true).put("webViewInstanceRetained", retainedWebView != null)
                .put("status", "PASS")
        } catch (error: Throwable) {
            report.put("status", "FAIL").put("error", error.toString())
            val prefix = if (wide) "header-layout-wide" else "header-layout-narrow"
            runCatching {
                instrumentation.uiAutomation.takeScreenshot()?.let { bitmap ->
                    File(activity.cacheDir, "$prefix-failure.png").outputStream().use {
                        bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
                    }
                    bitmap.recycle()
                }
            }.onFailure { report.put("failureCaptureError", it.toString()) }
            File(activity.cacheDir, "$prefix-report.json").writeText(report.toString(2))
            report.optJSONObject("lastFitInputs")?.let { logFitInputs(it, detailed = true) }
            throw error
        } finally {
            mutate {
                header.visibility = originalHeaderVisibility
                tabs.visibility = originalTabsVisibility
                header.layoutParams = header.layoutParams.apply { width = originalWidth }
                toggle.text = originalToggle
                status.text = originalStatus
                progress.visibility = originalProgress
                labels.forEachIndexed { index, text -> tabObjects[index].text = text }
                tabObjects[selected].select()
            }
            val prefix = if (wide) "header-layout-wide" else "header-layout-narrow"
            File(activity.cacheDir, "$prefix-report.json").writeText(report.toString(2))
            instrumentation.uiAutomation.takeScreenshot()?.let { bitmap ->
                File(activity.cacheDir, "$prefix.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                bitmap.recycle()
            }
            println("HEADER_LAYOUT_NATIVE_REPORT=" + JSONObject().put("wide", wide).put("status", report.optString("status"))
                .put("systemFontScale", systemFontScale).put("sampleCount", samples.length())
                .put("measurementCount", measurements.length()).put("error", report.optString("error")))
        }
        return report
    }

    private fun assertReadable(view: TextView) {
        val layout = requireNotNull(view.layout) { "A visible native label needs a real text layout" }
        val metrics = textLayoutMetrics(view)
        assertTrue("Keep full native text height: ${view.text}; metrics=$metrics", layout.height <= view.height - view.compoundPaddingTop - view.compoundPaddingBottom + 1)
        for (line in 0 until layout.lineCount) {
            assertEquals("Native labels must not be ellipsized: ${view.text}; line=$line metrics=$metrics", 0, layout.getEllipsisCount(line))
            // Android Layout.getLineWidth includes whitespace after a wrapped
            // line. getLineMax measures its visible extent with the same margin.
            assertTrue("Native visible label lines must fit their measured width: ${view.text}; line=$line metrics=$metrics",
                layout.getLineMax(line) <= view.width - view.compoundPaddingLeft - view.compoundPaddingRight + 1)
        }
    }

    private fun textLayoutMetrics(view: TextView): JSONObject {
        val data = JSONObject().put("viewWidth", view.width).put("viewHeight", view.height)
            .put("contentWidth", view.width - view.compoundPaddingLeft - view.compoundPaddingRight)
            .put("contentHeight", view.height - view.compoundPaddingTop - view.compoundPaddingBottom)
        val layout = view.layout ?: return data.put("available", false)
        val lines = JSONArray()
        for (line in 0 until layout.lineCount) {
            val start = layout.getLineStart(line)
            val end = layout.getLineEnd(line)
            val visibleEnd = layout.getLineVisibleEnd(line)
            lines.put(JSONObject().put("line", line).put("start", start).put("end", end).put("visibleEnd", visibleEnd)
                .put("rawLineText", layout.text.subSequence(start, end).toString())
                .put("visibleLineText", layout.text.subSequence(start, visibleEnd).toString())
                .put("lineWidth", layout.getLineWidth(line)).put("lineMax", layout.getLineMax(line))
                .put("lineLeft", layout.getLineLeft(line)).put("lineRight", layout.getLineRight(line))
                .put("ellipsisStart", layout.getEllipsisStart(line)).put("ellipsisCount", layout.getEllipsisCount(line))
                .put("top", layout.getLineTop(line)).put("bottom", layout.getLineBottom(line)))
        }
        return data.put("available", true).put("layoutWidth", layout.width).put("layoutHeight", layout.height)
            .put("lineCount", layout.lineCount).put("lines", lines)
    }

    /** Read the original APK's calculations without altering any view or paint. */
    private fun fitInputs(activity: MainActivity, header: LinearLayout, controls: LinearLayout, tabs: TabLayout): JSONObject {
        val textWidth = MainActivity::class.java.getDeclaredMethod("naturalHeaderTextWidth", TextView::class.java)
            .apply { isAccessible = true }
        val tabWidth = MainActivity::class.java.getDeclaredMethod("naturalTabWidth", View::class.java)
            .apply { isAccessible = true }
        fun margins(view: View): Int = (view.layoutParams as? ViewGroup.MarginLayoutParams)
            ?.let { it.leftMargin + it.rightMargin } ?: 0
        fun describe(view: View): JSONObject {
            val lp = view.layoutParams
            fun rect(value: Rect) = JSONObject().put("left", value.left).put("top", value.top)
                .put("right", value.right).put("bottom", value.bottom)
            val visible = Rect()
            val globallyVisible = view.getGlobalVisibleRect(visible)
            val ancestors = JSONArray()
            var node = view.parent
            while (node is View) {
                val current = node as View
                ancestors.put(JSONObject().put("class", current.javaClass.name)
                    .put("paddingLeft", current.paddingLeft).put("paddingRight", current.paddingRight)
                    .put("margins", margins(current)).put("width", current.width))
                if (current === header) break
                node = current.parent
            }
            val data = JSONObject().put("class", view.javaClass.name).put("id", view.id)
                .put("visibility", view.visibility).put("width", view.width).put("height", view.height)
                .put("left", view.left).put("top", view.top).put("right", view.right).put("bottom", view.bottom)
                .put("scrollX", view.scrollX).put("scrollY", view.scrollY)
                .put("boundsInHeader", rect(if (view === header) Rect(0, 0, view.width, view.height) else bounds(header, view)))
                .put("globallyVisible", globallyVisible)
                .put("globalVisibleBounds", rect(visible)).put("globalVisibleWidth", visible.width()).put("globalVisibleHeight", visible.height())
                .put("layoutWidth", lp.width).put("layoutHeight", lp.height)
                .put("minimumWidth", view.minimumWidth).put("paddingLeft", view.paddingLeft)
                .put("paddingRight", view.paddingRight).put("backgroundMinimumWidth", view.background?.minimumWidth ?: 0)
                .put("margins", margins(view)).put("ancestors", ancestors)
            if (lp is LinearLayout.LayoutParams) data.put("layoutWeight", lp.weight)
            if (view is LinearLayout) data.put("gravity", view.gravity)
            if (view is TextView) {
                val rendered = view.transformationMethod?.getTransformation(view.text, view) ?: view.text
                data.put("text", view.text.toString()).put("renderedText", rendered.toString())
                    .put("textLayout", textLayoutMetrics(view))
                    .put("textSizePx", view.textSize).put("minWidth", view.minWidth).put("minEms", view.minEms)
                    .put("lineHeight", view.lineHeight).put("compoundPaddingLeft", view.compoundPaddingLeft)
                    .put("compoundPaddingRight", view.compoundPaddingRight)
                    .put("paintDesiredWidth", android.text.Layout.getDesiredWidth(rendered, view.paint))
                    .put("calculatedTextWidth", (textWidth.invoke(activity, view) as Number).toInt())
            }
            return data
        }
        val children = (0 until controls.childCount).map(controls::getChildAt)
        val controlDetails = JSONArray(children.map(::describe))
        val controlsWidth = controls.paddingLeft + controls.paddingRight + children.sumOf { child ->
            if (child.visibility == View.GONE) 0 else {
                val width = if (child is TextView) (textWidth.invoke(activity, child) as Number).toInt()
                    else maxOf(child.layoutParams.width.coerceAtLeast(0), child.minimumWidth, child.background?.minimumWidth ?: 0)
                width + margins(child)
            }
        }
        val strip = tabs.getChildAt(0) as ViewGroup
        val tabDetails = JSONArray()
        var tabsWidth = tabs.paddingLeft + tabs.paddingRight + strip.paddingLeft + strip.paddingRight
        for (index in 0 until strip.childCount) {
            val tab = strip.getChildAt(index)
            val calculated = (tabWidth.invoke(activity, tab) as Number).toInt()
            tabsWidth += calculated
            tabDetails.put(describe(tab).put("index", index).put("calculatedTabWidth", calculated)
                .put("labels", JSONArray(descendants(tab).filterIsInstance<TextView>().map(::describe).toList())))
        }
        val gap = ceil(8 * activity.resources.displayMetrics.density.toDouble()).toInt()
        val available = header.width - header.paddingLeft - header.paddingRight
        return JSONObject().put("header", describe(header)).put("orientation", header.orientation)
            .put("tabGravity", tabs.tabGravity).put("tabMode", tabs.tabMode)
            .put("density", activity.resources.displayMetrics.density).put("systemFontScale", activity.resources.configuration.fontScale)
            .put("controls", controlDetails).put("serverRow", describe(controls)).put("tabs", tabDetails)
            .put("navigation", describe(tabs)).put("strip", describe(strip)).put("controlsWidth", controlsWidth)
            .put("tabsWidth", tabsWidth).put("gap", gap).put("availableWidth", available)
            .put("calculatedFits", controlsWidth + gap + tabsWidth <= available)
    }

    private fun logFitInputs(inputs: JSONObject, detailed: Boolean = false) {
        // Individual valid JSON lines stay below Android's log-entry limit.
        // The complete object is also retained in the on-device report file.
        val summary = JSONObject()
        for (key in listOf("orientation", "density", "systemFontScale", "tabGravity", "tabMode", "controlsWidth", "tabsWidth", "gap", "availableWidth", "calculatedFits", "requested"))
            summary.put(key, inputs.get(key))
        summary.put("navigationScrollX", inputs.getJSONObject("navigation").getInt("scrollX"))
        val tabBounds = JSONArray()
        val tabs = inputs.getJSONArray("tabs")
        for (index in 0 until tabs.length()) {
            val tab = tabs.getJSONObject(index)
            tabBounds.put(JSONObject().put("index", index).put("width", tab.getInt("width"))
                .put("layoutWidth", tab.getInt("layoutWidth")).put("calculatedTabWidth", tab.getInt("calculatedTabWidth"))
                .put("bounds", tab.getJSONObject("boundsInHeader")).put("visibleWidth", tab.getInt("globalVisibleWidth")))
        }
        summary.put("actualTabs", tabBounds)
        println("HEADER_FIT_NATIVE_INPUTS=" + summary)
        if (!detailed) return
        for (key in listOf("header", "serverRow", "navigation", "strip"))
            println("HEADER_FIT_NATIVE_" + key + "=" + inputs.getJSONObject(key))
        for (key in listOf("controls", "tabs")) {
            val rows = inputs.getJSONArray(key)
            for (index in 0 until rows.length()) println("HEADER_FIT_NATIVE_" + key + "_" + index + "=" + rows.getJSONObject(index))
        }
    }

    private fun awaitFullyVisible(view: View) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = android.os.SystemClock.uptimeMillis() + 5000
        while (true) {
            var visible = false
            val frame = CountDownLatch(1)
            instrumentation.runOnMainSync {
                val rect = Rect()
                visible = view.getGlobalVisibleRect(rect) && rect.width() == view.width && rect.height() == view.height
                if (!visible) view.postOnAnimation { frame.countDown() }
            }
            if (visible) return
            assertTrue("The selected native tab must finish scrolling fully into view",
                android.os.SystemClock.uptimeMillis() < deadline)
            assertTrue(frame.await(1, TimeUnit.SECONDS))
        }
    }

    private fun bounds(parent: ViewGroup, child: View): Rect = Rect(0, 0, child.width, child.height).also {
        parent.offsetDescendantRectToMyCoords(child, it)
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
