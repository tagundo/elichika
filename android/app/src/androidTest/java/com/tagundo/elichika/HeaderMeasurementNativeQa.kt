package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.ceil

/** Frozen-APK diagnostic: changes only public runtime measurement properties. */
internal object HeaderMeasurementNativeQa {
    fun compare() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val previousGuide = preferences.all["seen_guide"]
        preferences.edit().putBoolean("seen_guide", true).commit()
        var activity: MainActivity? = null
        val report = JSONObject().put("status", "RUNNING").put("scope",
            "Frozen product APK; same actual native views; public setters only; synthetic header width853→320 inside the actual wide Android window")
        val evidence = File(context.cacheDir, "header-policy-comparison.json")
        try {
            val launched = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            activity = launched
            val header = launched.findViewById<LinearLayout>(R.id.app_header)
            val status = launched.findViewById<TextView>(R.id.txt_status)
            val toggle = launched.findViewById<TextView>(R.id.btn_toggle)
            val progress = launched.findViewById<ProgressBar>(R.id.progress_preparing)
            lateinit var controls: LinearLayout
            instrumentation.runOnMainSync {
                assertFalse(Bus.serverRunning || Bus.serverStarting)
                assertFalse(PyServers.isPreparing())
                controls = header.getChildAt(0) as LinearLayout
                report.put("originalBaselineAligned", controls.isBaselineAligned)
                    .put("actualWindowWidthPx", header.rootView.width)
                    .put("density", launched.resources.displayMetrics.density)
                    .put("fontScale", launched.resources.configuration.fontScale)
            }
            val strings = launched.createConfigurationContext(Configuration(launched.resources.configuration).apply {
                setLocale(Locale.JAPANESE)
            }).resources
            val density = launched.resources.displayMetrics.density
            fun mutate(action: () -> Unit) {
                val settled = CountDownLatch(1)
                instrumentation.runOnMainSync {
                    action()
                    header.requestLayout()
                    header.postOnAnimation { header.postOnAnimation { header.postOnAnimation { settled.countDown() } } }
                }
                assertTrue("Native measurement must settle", settled.await(10, TimeUnit.SECONDS))
                instrumentation.waitForIdleSync()
            }
            fun width(dp: Int) = mutate { header.layoutParams = header.layoutParams.apply { width = ceil(dp * density.toDouble()).toInt() } }
            fun capture(label: String): JSONObject {
                lateinit var sample: JSONObject
                instrumentation.runOnMainSync {
                    val layout = requireNotNull(status.layout)
                    val contentHeight = status.height - status.compoundPaddingTop - status.compoundPaddingBottom
                    val lines = JSONArray()
                    var widthsFit = true
                    var ellipsesAbsent = true
                    for (line in 0 until layout.lineCount) {
                        lines.put(JSONObject().put("width", layout.getLineMax(line))
                            .put("ellipsis", layout.getEllipsisCount(line)).put("bottom", layout.getLineBottom(line)))
                        widthsFit = widthsFit && layout.getLineMax(line) <= status.width - status.compoundPaddingLeft - status.compoundPaddingRight + 1
                        ellipsesAbsent = ellipsesAbsent && layout.getEllipsisCount(line) == 0
                    }
                    val readable = layout.height <= contentHeight + 1 && widthsFit && ellipsesAbsent
                    sample = JSONObject().put("candidate", label).put("baselineAligned", controls.isBaselineAligned)
                        .put("headerWidth", header.width).put("headerHeight", header.height)
                        .put("controlsWidth", controls.width).put("controlsHeight", controls.height)
                        .put("statusText", status.text).put("statusWidth", status.width).put("statusHeight", status.height)
                        .put("measuredWidth", status.measuredWidth).put("measuredHeight", status.measuredHeight)
                        .put("textLayoutWidth", layout.width).put("textLayoutHeight", layout.height)
                        .put("lineCount", layout.lineCount).put("contentHeight", contentHeight)
                        .put("fullyReadable", readable).put("strictOutcome", if (readable) "PASS" else "FAIL")
                        .put("widthsFit", widthsFit).put("ellipsesAbsent", ellipsesAbsent).put("lines", lines)
                        .put("headerOrientation", header.orientation)
                }
                return sample
            }
            fun reproduce(baselineAligned: Boolean): JSONObject {
                mutate {
                    controls.isBaselineAligned = baselineAligned
                    toggle.text = strings.getString(R.string.start_server)
                    status.text = strings.getString(R.string.status_data_update_percent, 99)
                    progress.visibility = View.VISIBLE
                }
                width(320); width(853)
                mutate {
                    toggle.text = strings.getString(R.string.stop_server)
                    status.text = strings.getString(R.string.status_server_loading)
                }
                val wide = capture("loading-wide-baseline-$baselineAligned")
                width(320)
                return wide
            }
            fun screenshot(name: String) {
                instrumentation.uiAutomation.takeScreenshot()?.let { image ->
                    File(context.cacheDir, name).outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    image.recycle()
                }
            }
            val baselineWide = reproduce(true)
            report.put("baselineWide", baselineWide)
            val baseline = capture("default-baseline-aligned")
            report.put("baseline", baseline)
            screenshot("header-policy-center-failure.png")
            mutate { status.forceLayout(); status.requestLayout() }
            val forced = capture("explicit-force-layout-at-same-width")
            report.put("forceLayout", forced)
            width(853)
            report.put("forceLayoutWide", capture("force-layout-wide"))
            val baselineOffWide = reproduce(false)
            report.put("baselineOffWide", baselineOffWide)
            val noBaseline = capture("baseline-aligned-false")
            report.put("baselineOff", noBaseline)
            screenshot("header-policy-start.png")
            // Repeat the actual text and width boundary so a one-off settled
            // view cannot masquerade as a persistent measurement fix.
            val repeats = JSONArray()
            repeat(3) {
                reproduce(false)
                repeats.put(capture("baseline-off-repeat-$it"))
            }
            report.put("baselineOffRepeats", repeats)
            val repeatedReadable = (0 until repeats.length()).all { repeats.getJSONObject(it).getBoolean("fullyReadable") }
            report.put("baselineOffRepeatedStrictOutcome", if (repeatedReadable) "PASS" else "FAIL")
            report.put("status", "DIAGNOSTIC_COMPLETED")
            report.put("baselineReproduced", !baseline.getBoolean("fullyReadable"))
                .put("forceLayoutReadable", forced.getBoolean("fullyReadable"))
                .put("baselineOffReadable", noBaseline.getBoolean("fullyReadable"))
            println("HEADER_MEASUREMENT_DIAGNOSTIC=" + JSONObject().put("baselineReproduced", !baseline.getBoolean("fullyReadable"))
                .put("forceLayoutReadable", forced.getBoolean("fullyReadable"))
                .put("baselineOffReadable", noBaseline.getBoolean("fullyReadable")))
        } catch (failure: Throwable) {
            report.put("status", "FAIL_DIAGNOSTIC").put("error", failure.toString())
            throw failure
        } finally {
            evidence.writeText(report.toString(2))
            File(context.cacheDir, "header-layout-wide-report.json").writeText(report.toString(2))
            instrumentation.runOnMainSync { activity?.finish() }
            preferences.edit().apply {
                if (previousGuide is Boolean) putBoolean("seen_guide", previousGuide) else remove("seen_guide")
            }.commit()
        }
    }
}
