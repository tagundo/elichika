package com.tagundo.elichika

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.tabs.TabLayout
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Real Unity conversion and actual native WebGL; all source geometry is an original neutral ribbon. */
@RunWith(AndroidJUnit4::class)
class ModelViewerRigTest {
    @Test
    fun unitySkinMotionAndLiveSettingsChangePixelsAndSurviveContextRecovery() = withRig { session ->
        val webView = session.webView
        input(webView, "viewer-shader", "basic", "change")
        val defaultSavedNodes = state(webView).getJSONObject("rig").getJSONObject("savedNodes")
        assertTrue("Supported saved file settings must be applied on load", defaultSavedNodes.getBoolean("enabled"))
        assertEquals("Scale, position and rotation records must all apply", 3, defaultSavedNodes.getInt("applied"))
        assertSavedTransforms(state(webView))
        val defaultSavedFrame = capture(webView, "savedDefault")
        click(webView, "viewer-saved-nodes")
        fun resetAuthoredBaseline() {
            click(webView, "viewer-preview-reset")
            assertTrue("Reset must restore the saved-file default", state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
            assertSavedTransforms(state(webView))
            click(webView, "viewer-saved-nodes")
        }
        val poseControls = evaluate(webView,
            "var basic=ViewerRigQa.control('viewer-pose-basic',true),preview=ViewerRigQa.control('viewer-pose-preview',true);" +
                "return JSON.stringify({basic:basic,preview:preview,rig:ModelViewer.getState().rig});")
        val authoredButton = poseControls.getJSONObject("basic")
        val unavailablePreview = poseControls.getJSONObject("preview")
        assertFalse("Authored pose must remain usable without a verified preview", authoredButton.getBoolean("disabled"))
        assertEquals("true", authoredButton.getString("pressed"))
        assertTrue("An ordinary motion clip must not enable the verified SIFAS pose button", unavailablePreview.getBoolean("disabled"))
        assertEquals("false", unavailablePreview.getString("pressed"))
        for (button in listOf(authoredButton, unavailablePreview)) {
            assertTrue("Pose controls must have visible, unobstructed 44 px targets: $button",
                button.getBoolean("visible") && button.getBoolean("withinViewport") && button.getBoolean("hittable") &&
                    button.getDouble("width") >= 44 && button.getDouble("height") >= 44)
        }
        assertEquals("", poseControls.getJSONObject("rig").getString("defaultClip"))
        assertEquals("", poseControls.getJSONObject("rig").getString("selectedClip"))
        run(webView, "document.getElementById('viewer-pose-preview').click();")
        assertEquals("A disabled preview action must leave the authored pose selected", "", state(webView).getJSONObject("rig").getString("selectedClip"))
        run(webView, "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'end'});")
        val rest = capture(webView, "rest")
        assertEquals(4, rest.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals(4, rest.getJSONObject("probe").getInt("triangles"))
        val restVertices = evaluate(webView, "return JSON.stringify(ViewerRigQa.deformedVertices());")
        assertEquals("The genuine Unity skin must contain three usable joints", 3, restVertices.getInt("jointCount"))
        val authored = arrayOf(doubleArrayOf(.4, 0.0, 0.0), doubleArrayOf(-.4, 0.0, 0.0),
            doubleArrayOf(.4, .65, 0.0), doubleArrayOf(-.4, .65, 0.0),
            doubleArrayOf(.25, 1.25, 0.0), doubleArrayOf(-.25, 1.25, 0.0))
        val vertices = restVertices.getJSONArray("vertices")
        assertEquals(authored.size, vertices.length())
        for (vertex in authored.indices) for (axis in 0..2) {
            assertEquals("The native rest skin must preserve authored Unity coordinates ($vertex/$axis)",
                authored[vertex][axis], vertices.getJSONArray(vertex).getDouble(axis), 1e-6)
        }

        boneInput(webView, "BreastSize", "rotation", "Z", 45)
        val manualPose = capture(webView, compare = "rest")
        assertChanged("Changing an actual weighted joint must change the framebuffer", manualPose)
        click(webView, "viewer-node-reset")
        assertRestored("Reset this bone must restore the authored rest pixels", capture(webView, compare = "rest"))

        input(webView, "viewer-height", "120")
        assertBoneScale(state(webView), "Move", doubleArrayOf(1.2, 1.2, 1.2))
        val height = capture(webView, compare = "rest")
        assertChanged("Height must change actual skinned pixels", height)
        input(webView, "viewer-breast", "150")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.5, 1.5, 1.5))
        val breast = capture(webView, compare = "rest")
        assertChanged("BreastSize must change the weighted neutral ribbon", breast)
        input(webView, "viewer-breast", "150")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.5, 1.5, 1.5))
        resetAuthoredBaseline()
        assertRestored("Reset must remove live scaling without compounding", capture(webView, compare = "rest"))

        val savedAvailable = state(webView).getJSONObject("rig").getJSONObject("savedNodes")
        assertTrue("The real serialized component must supply a supported saved entry", savedAvailable.getBoolean("available"))
        assertFalse("The explicit authored baseline must remain opted out", savedAvailable.getBoolean("enabled"))
        click(webView, "viewer-saved-nodes")
        val savedState = state(webView)
        assertEquals(3, savedState.getJSONObject("rig").getJSONObject("savedNodes").getInt("applied"))
        assertSavedTransforms(savedState)
        val saved = capture(webView, compare = "rest")
        assertChanged("Applying the original serialized saved entry must change pixels", saved)
        assertRestored("Reapplying saved settings must reproduce the initial file-default pixels", capture(webView, compare = "savedDefault"))
        click(webView, "viewer-saved-nodes")
        assertRestored("Disabling saved entries must restore authored geometry", capture(webView, compare = "rest"))
        click(webView, "viewer-saved-nodes")
        input(webView, "viewer-breast", "150")
        input(webView, "viewer-breast", "150")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.95, 1.35, 1.5))
        resetAuthoredBaseline()
        assertFalse(state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
        assertRestored("Reset must also remove explicitly applied saved settings", capture(webView, compare = "rest"))

        input(webView, "viewer-expression-value", "100")
        assertEquals(1.0, state(webView).getJSONObject("rig").getJSONArray("expressions").getJSONObject(0).getDouble("weight"), 1e-9)
        val expression = capture(webView, compare = "rest")
        assertChanged("A real Unity blend-shape channel must change visible geometry", expression)
        resetAuthoredBaseline()
        assertRestored("Expression reset must restore the actual rest framebuffer", capture(webView, compare = "rest"))

        input(webView, "viewer-motion", "Neutral swing", "change")
        assertEquals(2.0, state(webView).getJSONObject("rig").getDouble("duration"), 1e-6)
        input(webView, "viewer-time", "1")
        val scrub = capture(webView, compare = "rest")
        assertChanged("Scrubbing the actual Unity clip must visibly change its weighted pose", scrub)
        assertTrue(kotlin.math.abs(bone(state(webView), "BreastSize").getJSONArray("quaternion").getDouble(2)) > .4)
        val otherClipControls = evaluate(webView,
            "return JSON.stringify({basic:ViewerRigQa.control('viewer-pose-basic',false),preview:ViewerRigQa.control('viewer-pose-preview',false)});")
        assertEquals("false", otherClipControls.getJSONObject("basic").getString("pressed"))
        assertEquals("false", otherClipControls.getJSONObject("preview").getString("pressed"))
        click(webView, "viewer-pose-basic")
        assertEquals("", state(webView).getJSONObject("rig").getString("selectedClip"))
        assertEquals(0.0, state(webView).getJSONObject("rig").getDouble("time"), 1e-9)
        assertFalse(state(webView).getJSONObject("rig").getBoolean("playing"))
        assertFalse("Basic pose must retain the authored baseline opt-out", state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
        assertRestored("The basic-pose button must restore actual authored pixels after an ordinary clip", capture(webView, compare = "rest"))
        input(webView, "viewer-motion", "Neutral swing", "change")
        input(webView, "viewer-time", ".5")
        capture(webView, "playStart")
        click(webView, "viewer-play")
        waitForDom(webView, "actual animation time to advance", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.rig.playing&&s.rig.time>=.7,error:s.error,state:s});"
        }
        val playing = capture(webView, compare = "playStart")
        assertChanged("Playback must advance actual framebuffer pixels", playing)
        click(webView, "viewer-play")
        val pausedState = state(webView)
        assertFalse(pausedState.getJSONObject("rig").getBoolean("playing"))
        capture(webView, "paused")
        Thread.sleep(400)
        val paused = capture(webView, compare = "paused")
        assertRestored("Paused playback must hold its actual rendered frame", paused)
        assertEquals(pausedState.getJSONObject("rig").getDouble("time"), state(webView).getJSONObject("rig").getDouble("time"), 1e-9)
        run(webView, "ViewerRigQa.drop('playStart');ViewerRigQa.drop('paused');")

        // Preserve a nontrivial paused pose, rather than only checking defaults.
        resetAuthoredBaseline()
        input(webView, "viewer-motion", "Neutral swing", "change")
        input(webView, "viewer-time", ".6")
        click(webView, "viewer-saved-nodes")
        input(webView, "viewer-height", "115")
        input(webView, "viewer-breast", "130")
        input(webView, "viewer-expression-value", "40")
        boneInput(webView, "Tip", "rotation", "X", 20)
        val retainedState = state(webView)
        capture(webView, "retained")
        run(webView, "document.querySelector('.tab[data-tab=\"tools\"]').click();")
        assertFalse(state(webView).getBoolean("visible"))
        Thread.sleep(250)
        run(webView, "document.querySelector('.tab[data-tab=\"viewer\"]').click();" +
            "if(!document.getElementById('tab-viewer').classList.contains('viewer-expanded'))document.getElementById('viewer-expand').click();")
        waitForDom(webView, "the retained native rig tab") {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.visible&&s.loaded&&!s.loading,error:s.error,state:s});"
        }
        assertRetained(retainedState, state(webView))
        val afterTab = capture(webView, compare = "retained")
        assertRestored("Returning to the viewer must retain its actual adjusted image", afterTab)
        recoverContext(webView)
        assertRetained(retainedState, state(webView))
        val afterContext = capture(webView, compare = "retained")
        assertRestored("A restored native WebGL context must retain the adjusted model", afterContext)
        saveScreenshot(session.activity, "model-viewer-rig.png")
        click(webView, "viewer-preview-reset")
        assertTrue(state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
        assertSavedTransforms(state(webView))
        val restoredFileDefault = capture(webView, compare = "savedDefault")
        assertRestored("Final reset must recover saved-file defaults after context restoration", restoredFileDefault)
        click(webView, "viewer-saved-nodes")
        assertRestored("Opting out must still recover exact authored pixels after context restoration", capture(webView, compare = "rest"))
        val report = JSONObject().put("scope", "Original serialized Unity rig through real API/GLB/native WebGL")
            .put("poseControlsWithoutVerifiedPreview", poseControls)
            .put("defaultSavedNodes", defaultSavedNodes).put("defaultSavedFrame", defaultSavedFrame)
            .put("restoredFileDefault", restoredFileDefault)
            .put("restVertices", restVertices).put("rest", rest).put("manualPose", manualPose)
            .put("height", height).put("breast", breast).put("savedEntry", saved).put("expression", expression)
            .put("scrub", scrub).put("playing", playing).put("paused", paused)
            .put("afterTab", afterTab).put("afterContext", afterContext)
            .put("sourcePreserved", true).put("gameServerRemainedStopped", true)
        persistReport("model-viewer-rig-report.json", report)
        println("MODEL_VIEWER_RIG_REPORT=$report")
    }

    @Test
    fun memberShaderUsesSourceGammaMaskAndActualOutlineDrawPasses() = withRig { session ->
        val webView = session.webView
        val initial = state(webView)
        assertTrue("The genuine linked AS/Member shader must be recognized", initial.getJSONObject("materials").getInt("recognizedMaterials") == 1)
        assertEquals(1, initial.getJSONObject("materials").getInt("outlines"))
        val member = capture(webView, "member")
        assertEquals("Source geometry excludes helper outlines", 4, member.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals("GPU metrics must include the real outline draw", 8, member.getJSONObject("probe").getInt("triangles"))
        assertRgb("AS/Member must apply the authored blue-mask in source Gamma space", member.getJSONArray("centerRGB"), intArrayOf(14, 63, 84))
        input(webView, "viewer-shader", "basic", "change")
        val basic = capture(webView, compare = "member")
        assertEquals(4, basic.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals("Disabling member preview must remove its helper draw", 4, basic.getJSONObject("probe").getInt("triangles"))
        assertRgb("Basic textures must show the unchanged neutral source texel", basic.getJSONArray("centerRGB"), intArrayOf(40, 180, 240))
        assertChanged("The actual member shader must change rendered pixels", basic)
        input(webView, "viewer-shader", "sifas", "change")
        val memberAgain = capture(webView, compare = "member")
        assertRestored("Switching back must restore the same shader result", memberAgain)
        assertEquals(8, memberAgain.getJSONObject("probe").getInt("triangles"))
        boneInput(webView, "BreastSize", "rotation", "Z", 35)
        val posed = capture(webView, compare = "member")
        assertChanged("Member rendering must follow the actual skinned pose", posed)
        assertEquals(4, posed.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals(8, posed.getJSONObject("probe").getInt("triangles"))
        click(webView, "viewer-node-reset")
        run(webView, "var input=document.querySelector('#viewer-parts input');if(!input||!input.checked)throw new Error('Missing source part');input.click();")
        val hidden = capture(webView)
        assertEquals("Hiding the source must hide its helper draw too", 0, hidden.getJSONObject("probe").getInt("triangles"))
        assertEquals(0, hidden.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals(0, hidden.getInt("foregroundPixels"))
        run(webView, "document.querySelector('#viewer-parts input').click();")
        recoverContext(webView)
        val recovered = capture(webView, compare = "member")
        assertRestored("Native context restoration must rebuild the same member shader", recovered)
        assertEquals(8, recovered.getJSONObject("probe").getInt("triangles"))
        assertRgb("Context restoration must retain the source Gamma shader output", recovered.getJSONArray("centerRGB"), intArrayOf(14, 63, 84))
        saveScreenshot(session.activity, "model-viewer-shader.png")
        val report = JSONObject().put("member", member).put("basic", basic)
            .put("posed", posed).put("hidden", hidden).put("recovered", recovered)
            .put("sourcePreserved", true).put("gameServerRemainedStopped", true)
        persistReport("model-viewer-shader-report.json", report)
        println("MODEL_VIEWER_SHADER_REPORT=$report")
    }

    private data class Session(val activity: MainActivity, val webView: WebView)

    private fun withRig(check: (Session) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val fixture = instrumentation.context.assets.open("viewer_rig.unity").use { it.readBytes() }
        val source = File(context.filesDir, "viewer-rig-qa-${System.nanoTime()}.unity")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        var activity: MainActivity? = null
        var webView: WebView? = null
        try {
            val permissions = mutableListOf<String>()
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) permissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissions.add(Manifest.permission.POST_NOTIFICATIONS)
            for (permission in permissions) if (context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
                instrumentation.uiAutomation.grantRuntimePermission(context.packageName, permission)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) assertTrue(Environment.isExternalStorageManager())
            assertGameStopped()
            source.writeBytes(fixture)
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            activity = launched
            instrumentation.runOnMainSync { launched.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select() }
            val browser = waitForWebView(launched)
            webView = browser
            waitForDom(browser, "the real offline rig viewer") {
                "return JSON.stringify({ok:typeof openModelViewer==='function'&&!!window.ViewerRig&&" +
                    "!!window.THREE&&!!document.querySelector('#tool-list button[data-id=\"mesh_baker\"]')});"
            }
            val helper = instrumentation.context.assets.open("viewer_rig_qa.js").bufferedReader().use { it.readText() }
            run(browser, helper)
            run(browser, "if(document.getElementById('viewer-auto-face').checked)document.getElementById('viewer-auto-face').click();" +
                "openModelViewer([" + JSONObject.quote(source.absolutePath) + "]);" )
            waitForDom(browser, "the genuine Unity skin, morph and animation") {
                "var s=ModelViewer.getState();return JSON.stringify({ok:s.loaded&&!s.loading&&!s.contextLost&&" +
                    "!!s.rig&&s.rig.available&&s.stats.meshes===1&&s.stats.vertices===6&&s.stats.triangles===4&&" +
                    "s.stats.textures===1&&s.rig.clipNames.indexOf('Neutral swing')>=0&&s.rig.expressions.length===1," +
                    "error:s.error,state:s});"
            }
            run(browser, "document.getElementById('viewer-expand').click();" +
                "document.querySelector('[data-viewer-view=\"front\"]').click();document.getElementById('viewer-fit').click();" +
                "document.getElementById('viewer-adjustments').open=true;document.querySelector('.viewer-node-editor').open=true;" +
                "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'end'});")
            waitForDom(browser, "actual neutral rig framebuffer pixels") {
                "var p=ModelViewer.renderProbe(33);return JSON.stringify({ok:p.ready&&p.sourceTriangles===4&&p.triangles>=4&&" +
                    "p.nonBackgroundSamples>=3&&p.chromaticSamples>=3&&p.glError===0,probe:p});"
            }
            assertGameStopped()
            check(Session(launched, browser))
            assertTrue("All rig, shader and scaling operations must preserve the source bytes", source.readBytes().contentEquals(fixture))
            assertGameStopped()
        } finally {
            webView?.let { runCatching { run(it, "if(window.ViewerRigQa)ViewerRigQa.dispose();") } }
            instrumentation.runOnMainSync { activity?.finish() }
            source.delete()
            preferences.edit().apply { if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide") }.commit()
        }
    }

    private fun recoverContext(webView: WebView) {
        run(webView, "ViewerRigQa.loseContext();")
        waitForDom(webView, "actual native context loss", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.contextLost&&document.getElementById('viewer-height').disabled&&" +
                "document.getElementById('viewer-pose-basic').disabled&&document.getElementById('viewer-pose-preview').disabled,state:s});"
        }
        run(webView, "ViewerRigQa.restoreContext();")
        waitForDom(webView, "actual native context restoration", 60) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:!s.contextLost&&s.loaded&&!s.loading&&!document.getElementById('viewer-height').disabled&&" +
                "!document.getElementById('viewer-pose-basic').disabled&&document.getElementById('viewer-pose-preview').disabled,state:s});"
        }
    }

    private fun capture(webView: WebView, save: String? = null, compare: String? = null): JSONObject = evaluate(webView,
        "return JSON.stringify(ViewerRigQa.capture(" + (save?.let { JSONObject.quote(it) } ?: "null") + "," +
            (compare?.let { JSONObject.quote(it) } ?: "null") + "));")

    private fun assertChanged(message: String, frame: JSONObject) {
        val difference = frame.getJSONObject("difference")
        assertTrue("$message: $frame", difference.getInt("changedPixels") >= 64)
        assertTrue("A camera move must not substitute for a model change", difference.getDouble("cameraMaximumDifference") <= 1e-7)
        assertEquals(0, frame.getInt("glError"))
    }

    private fun assertRestored(message: String, frame: JSONObject) {
        val difference = frame.getJSONObject("difference")
        assertTrue("$message: $frame", difference.getInt("changedPixels") <= 8)
        assertTrue("The same camera must be retained", difference.getDouble("cameraMaximumDifference") <= 1e-7)
        assertEquals(0, frame.getInt("glError"))
    }

    private fun assertRgb(message: String, rgb: JSONArray, expected: IntArray) {
        for (index in expected.indices) assertTrue("$message: $rgb", kotlin.math.abs(rgb.getInt(index) - expected[index]) <= 3)
    }

    private fun bone(state: JSONObject, name: String): JSONObject {
        val bones = state.getJSONObject("rig").getJSONArray("bones")
        return (0 until bones.length()).map { bones.getJSONObject(it) }.single {
            it.getString("name") == name || it.getString("name").endsWith("/$name")
        }
    }

    private fun assertBoneScale(state: JSONObject, name: String, expected: DoubleArray) {
        val scale = bone(state, name).getJSONArray("scale")
        for (axis in expected.indices) assertEquals("$name axis $axis must use the authored baseline", expected[axis], scale.getDouble(axis), 1e-6)
    }

    private fun assertSavedTransforms(state: JSONObject) {
        assertBoneScale(state, "BreastSize", doubleArrayOf(1.3, .9, 1.0))
        val tip = bone(state, "Tip")
        val position = tip.getJSONArray("position")
        for ((axis, expected) in doubleArrayOf(-.1, .6, 0.0).withIndex()) {
            assertEquals("The saved position must apply to its non-BreastSize target", expected, position.getDouble(axis), 1e-6)
        }
        val quaternion = tip.getJSONArray("quaternion")
        val expected = doubleArrayOf(kotlin.math.sin(Math.PI / 12), 0.0, 0.0, kotlin.math.cos(Math.PI / 12))
        for (axis in expected.indices) assertEquals("The saved Unity X30 rotation must apply as its converted quaternion",
            expected[axis], quaternion.getDouble(axis), 1e-6)
    }

    private fun assertRetained(before: JSONObject, after: JSONObject) {
        val first = before.getJSONObject("rig"); val second = after.getJSONObject("rig")
        assertEquals(first.getString("selectedClip"), second.getString("selectedClip"))
        assertEquals(first.getBoolean("playing"), second.getBoolean("playing"))
        assertEquals(first.getDouble("time"), second.getDouble("time"), 1e-9)
        assertEquals(first.getJSONObject("body").toString(), second.getJSONObject("body").toString())
        assertEquals(first.getJSONObject("nodeAdjustments").toString(), second.getJSONObject("nodeAdjustments").toString())
        assertEquals(first.getJSONArray("expressions").toString(), second.getJSONArray("expressions").toString())
        assertEquals(first.getJSONObject("savedNodes").getBoolean("enabled"), second.getJSONObject("savedNodes").getBoolean("enabled"))
        assertEquals(first.getJSONObject("savedNodes").getInt("applied"), second.getJSONObject("savedNodes").getInt("applied"))
        assertEquals(before.getString("modelId"), after.getString("modelId"))
        for (name in listOf("Move", "BreastSize", "Tip")) {
            for (property in listOf("position", "quaternion", "scale")) {
                val left = bone(before, name).getJSONArray(property); val right = bone(after, name).getJSONArray(property)
                for (axis in 0 until left.length()) assertEquals(left.getDouble(axis), right.getDouble(axis), 1e-8)
            }
        }
    }

    private fun state(webView: WebView): JSONObject = evaluate(webView, "return JSON.stringify(ModelViewer.getState());")
    private fun input(webView: WebView, id: String, value: String, event: String = "input") = run(webView,
        "ViewerRigQa.input(" + JSONObject.quote(id) + "," + JSONObject.quote(value) + "," + JSONObject.quote(event) + ");")
    private fun click(webView: WebView, id: String) = run(webView, "ViewerRigQa.click(" + JSONObject.quote(id) + ");")
    private fun boneInput(webView: WebView, name: String, kind: String, axis: String, value: Int) = run(webView,
        "ViewerRigQa.boneInput(" + JSONObject.quote(name) + "," + JSONObject.quote(kind) + "," + JSONObject.quote(axis) + ",$value);")
    private fun run(webView: WebView, script: String) = evaluate(webView, script + "\nreturn JSON.stringify({ok:true});")

    private fun saveScreenshot(activity: MainActivity, filename: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(200)
        instrumentation.runOnMainSync { assertTrue(activity.hasWindowFocus()) }
        val screenshot = instrumentation.uiAutomation.takeScreenshot()
        assertTrue(screenshot != null)
        File(instrumentation.targetContext.cacheDir, filename).outputStream().use {
            assertTrue(screenshot!!.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
        screenshot?.recycle()
    }

    private fun persistReport(filename: String, report: JSONObject) {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        File(context.cacheDir, filename).writeText(report.toString(2))
    }

    private fun assertGameStopped() {
        assertFalse(Bus.serverRunning); assertFalse(Bus.serverStarting)
        val process = ProcessBuilder("/system/bin/pidof", "libelichika.so").redirectErrorStream(true).start()
        assertTrue(process.waitFor(5, TimeUnit.SECONDS))
        val output = process.inputStream.bufferedReader().use { it.readText().trim() }
        assertTrue(process.exitValue() in 0..1)
        assertEquals("Previewing must not launch the game process", "", if (process.exitValue() == 0) output else "")
    }

    private fun waitForWebView(activity: MainActivity): WebView {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(300)
        while (System.nanoTime() < deadline) {
            var result: WebView? = null
            instrumentation.runOnMainSync {
                result = descendants(activity.findViewById(R.id.content)).filterIsInstance<WebView>().firstOrNull { it.visibility == View.VISIBLE }
            }
            result?.let { return it }
            if (PyServers.hasPreparationError() && !PyServers.isPreparing()) throw AssertionError(Bus.snapshot().takeLast(1500))
            Thread.sleep(100)
        }
        throw AssertionError("The actual editing tab did not prepare its WebView")
    }

    private fun waitForDom(webView: WebView, description: String, seconds: Long = 240, script: () -> String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(seconds)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = evaluate(webView, script())
            if (last.optString("error").isNotEmpty()) throw AssertionError("$description: $last")
            if (last.optBoolean("ok")) return last
            Thread.sleep(100)
        }
        throw AssertionError("Timed out waiting for $description: $last")
    }

    private fun evaluate(webView: WebView, body: String): JSONObject {
        val result = AtomicReference<String>()
        val done = CountDownLatch(1)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            webView.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();") {
                result.set(it); done.countDown()
            }
        }
        assertTrue("The real viewer JavaScript callback timed out", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        val value = JSONObject(decoded as? String ?: throw AssertionError("Unexpected JavaScript result: ${result.get()}"))
        if (value.optString("error").isNotEmpty() && value.optBoolean("ok", true).not()) throw AssertionError("Viewer JavaScript failed: $value")
        return value
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
