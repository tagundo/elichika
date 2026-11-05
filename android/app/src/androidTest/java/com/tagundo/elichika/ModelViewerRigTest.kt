package com.tagundo.elichika

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.view.View
import android.view.KeyEvent
import android.view.WindowManager
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.webkit.WebView
import androidx.lifecycle.Lifecycle
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
        val verticalViewport = exerciseVerticalViewport(webView)
        val defaultSavedNodes = state(webView).getJSONObject("rig").getJSONObject("savedNodes")
        assertTrue("Supported saved file settings must be applied on load", defaultSavedNodes.getBoolean("enabled"))
        assertEquals("Scale, position and rotation records must all apply", 3, defaultSavedNodes.getInt("applied"))
        assertSavedTransforms(state(webView))
        val referenceControls = assertReferenceOnlyControls(webView)
        run(webView, "document.getElementById('viewer-node-editor').open=true;ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('BreastSize'),'change');")
        assertAdvancedVector(webView, "scale", doubleArrayOf(1.3, .9, 1.0))
        run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('Tip'),'change');")
        assertAdvancedVector(webView, "position", doubleArrayOf(.1, .6, 0.0))
        assertAdvancedVector(webView, "rotation", doubleArrayOf(30.0, 0.0, 0.0))
        assertEquals("Reading imported values must not create user changes", 0,
            state(webView).getJSONObject("rig").getJSONObject("nodeAdjustments").length())
        val defaultSavedFrame = capture(webView, "savedDefault")
        val absoluteAxes = exerciseAbsoluteAxes(webView)
        val childCompensation = exerciseChildCompensation(webView)
        assertRestored("Compensation undo must restore the exact original saved-file pixels", capture(webView, compare = "savedDefault"))
        click(webView, "viewer-saved-nodes")
        fun resetAuthoredBaseline() {
            click(webView, "viewer-preview-reset")
            assertTrue("Reset must restore the saved-file default", state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
            assertSavedTransforms(state(webView))
            click(webView, "viewer-saved-nodes")
        }
        val poseControls = evaluate(webView,
            "return JSON.stringify(ViewerRigQa.withViewControls(function(){" +
                "var basic=ViewerRigQa.viewControl('viewer-pose-basic'),preview=ViewerRigQa.viewControl('viewer-pose-preview',true);" +
                "return {basic:basic,preview:preview,rig:ModelViewer.getState().rig};}));")
        val authoredButton = poseControls.getJSONObject("basic")
        val unavailablePreview = poseControls.getJSONObject("preview")
        assertFalse("Authored pose must remain usable without a verified preview", authoredButton.getBoolean("disabled"))
        assertEquals("true", authoredButton.getString("pressed"))
        assertTrue("An ordinary motion clip must not enable the verified SIFAS pose button", unavailablePreview.getBoolean("disabled"))
        assertEquals("false", unavailablePreview.getString("pressed"))
        for (button in listOf(authoredButton, unavailablePreview)) {
            assertTrue("Pose controls must meet the actual compact HUD target policy: $button",
                button.getBoolean("visible") && button.getBoolean("withinViewport") && button.getBoolean("hittable") &&
                    button.getDouble("width") >= button.getInt("minimumTarget") &&
                    button.getDouble("height") >= button.getInt("minimumTarget"))
        }
        assertEquals("", poseControls.getJSONObject("rig").getString("defaultClip"))
        assertEquals("", poseControls.getJSONObject("rig").getString("selectedClip"))
        run(webView, "ViewerRigQa.withViewControls(function(){ViewerRigQa.viewControl('viewer-pose-preview',true);" +
            "document.getElementById('viewer-pose-preview').click();});")
        assertEquals("A disabled preview action must leave the authored pose selected", "", state(webView).getJSONObject("rig").getString("selectedClip"))
        run(webView, "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'end'});")
        val rest = capture(webView, "rest")
        assertEquals(4, rest.getJSONObject("probe").getInt("sourceTriangles"))
        assertEquals(4, rest.getJSONObject("probe").getInt("triangles"))
        val restVertices = evaluate(webView, "return JSON.stringify(ViewerRigQa.deformedVertices());")
        assertEquals("The genuine Unity skin retains three weighted and two unweighted source joints", 5, restVertices.getInt("jointCount"))
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

        boneInput(webView, "Head", "rotation", "X", 35)
        boneInput(webView, "Head", "rotation", "Y", 45)
        boneInput(webView, "Head", "rotation", "Z", 60)
        assertAdvancedVector(webView, "rotation", doubleArrayOf(35.0, 45.0, 60.0))
        val multiAxisHead = bone(state(webView), "Head").getJSONArray("quaternion")
        assertUnityRotation("The source Unity order is RyRxRz, not Three's intrinsic ZXY",
            multiAxisHead, doubleArrayOf(35.0, 45.0, 60.0))
        click(webView, "viewer-node-reset")
        boneInput(webView, "Head", "rotation", "Z", 45)
        boneInput(webView, "Neck_Hair", "rotation", "X", 30)
        val profileInvariant = mapOf("Move" to nodeWorld(webView, "Move"), "Head" to nodeWorld(webView, "Head"),
            "Neck_Hair" to nodeWorld(webView, "Neck_Hair"))
        assertTrue("Use a genuinely rotated head when checking profile isolation",
            kotlin.math.abs(profileInvariant.getValue("Head").getJSONArray("linear").getDouble(1)) > .5)
        val sourceProfiles = listOf(
            "stock" to doubleArrayOf(1.0, 1.0, 1.0),
            "yoshiko_shioriko" to doubleArrayOf(.95, .99, .98), "honoka_maki" to doubleArrayOf(.90, .98, .96),
            "umi_ruby_kasumi" to doubleArrayOf(.80, .96, .92), "rin" to doubleArrayOf(.72, .95, .90),
            "nico" to doubleArrayOf(.64, .94, .88), "rina" to doubleArrayOf(.61, .91, .85),
            "chika_you_ayumu" to doubleArrayOf(1.04, 1.02, 1.04), "hanayo_setsuna" to doubleArrayOf(1.08, 1.04, 1.08),
            "hanamaru_ai" to doubleArrayOf(1.12, 1.06, 1.12), "lanzhu" to doubleArrayOf(1.14, 1.07, 1.14),
            "eli_kanan_kanata" to doubleArrayOf(1.16, 1.08, 1.16), "mari" to doubleArrayOf(1.20, 1.10, 1.20),
            "karin" to doubleArrayOf(1.22, 1.11, 1.22), "nozomi" to doubleArrayOf(1.30, 1.15, 1.30),
            "emma" to doubleArrayOf(1.30, 1.18, 1.30))
        val profileResults = JSONArray()
        for ((profile, expected) in sourceProfiles) {
            input(webView, "viewer-breast-preset", profile, "change")
            input(webView, "viewer-breast-preset", profile, "change")
            val current = state(webView)
            assertBoneScale(current, "BreastSize", expected)
            assertFalse("An exact selected reference must not be labelled custom",
                current.getJSONObject("rig").getJSONObject("breastProfile").getBoolean("custom"))
            for ((name, before) in profileInvariant) assertArrayNear("$profile must leave the full authored $name world matrix unchanged",
                before.getJSONArray("matrix"), nodeWorld(webView, name).getJSONArray("matrix"))
            profileResults.put(JSONObject().put("id", profile).put("scale", bone(current, "BreastSize").getJSONArray("scale")))
        }
        val breast = capture(webView, compare = "rest")
        assertChanged("An exact reference must change actual weighted ribbon pixels", breast)
        boneInput(webView, "BreastSize", "position", "X", .02)
        boneInput(webView, "BreastSize", "rotation", "Z", 15)
        boneInput(webView, "BreastSize", "scale", "X", 1.4)
        val manualProfile = state(webView)
        assertTrue("A manual scale must be shown as a custom shape",
            manualProfile.getJSONObject("rig").getJSONObject("breastProfile").getBoolean("custom"))
        input(webView, "viewer-breast-preset", "rina", "change")
        val selectedProfile = state(webView)
        assertBoneScale(selectedProfile, "BreastSize", doubleArrayOf(.61, .91, .85))
        for (kind in listOf("position", "quaternion")) assertArrayNear("A reference clears only manual scale, preserving breast $kind",
            bone(manualProfile, "BreastSize").getJSONArray(kind), bone(selectedProfile, "BreastSize").getJSONArray(kind))
        click(webView, "viewer-breast-reset")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.0, 1.0, 1.0))
        for (kind in listOf("position", "quaternion")) assertArrayNear("Loaded-shape reset preserves manual breast $kind",
            bone(manualProfile, "BreastSize").getJSONArray(kind), bone(state(webView), "BreastSize").getJSONArray(kind))
        click(webView, "viewer-node-reset")
        run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('Head'),'change');")
        click(webView, "viewer-node-reset")
        run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('Neck_Hair'),'change');")
        click(webView, "viewer-node-reset")
        resetAuthoredBaseline()
        assertRestored("Reset must restore the source rather than compound reference settings", capture(webView, compare = "rest"))

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
        input(webView, "viewer-breast-preset", "emma", "change")
        input(webView, "viewer-breast-preset", "emma", "change")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.3, 1.18, 1.3))
        click(webView, "viewer-saved-nodes")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.3, 1.18, 1.3))
        click(webView, "viewer-saved-nodes")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.3, 1.18, 1.3))
        click(webView, "viewer-breast-reset")
        assertSavedTransforms(state(webView))
        input(webView, "viewer-breast-preset", "stock", "change")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.0, 1.0, 1.0))
        click(webView, "viewer-breast-reset")
        assertSavedTransforms(state(webView))
        assertRestored("Loaded is distinct from Stock and must restore the exact custom file pixels", capture(webView, compare = "savedDefault"))
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
            "return JSON.stringify(ViewerRigQa.withViewControls(function(){return {" +
                "basic:ViewerRigQa.viewControl('viewer-pose-basic'),preview:ViewerRigQa.viewControl('viewer-pose-preview',true)};}));")
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
        input(webView, "viewer-breast-preset", "rin", "change")
        input(webView, "viewer-expression-value", "40")
        boneInput(webView, "Tip", "rotation", "X", 20)
        boneInput(webView, "Head", "rotation", "Z", 35)
        val retainedState = state(webView)
        val retainedHeadWorld = nodeWorld(webView, "Head")
        val sections = exerciseSectionCollapse(session, retainedState)
        val fullscreen = exerciseFullscreen(session, retainedState)
        capture(webView, "retained")
        persistReport("model-viewer-viewport-milestones.json", JSONObject()
            .put("scope", "Strict new-feature milestones captured before the unchanged quality exercise")
            .put("verticalViewport", verticalViewport)
            .put("absoluteSourceValueEdits", absoluteAxes).put("childBoneCompensation", childCompensation)
            .put("collapsibleSections", sections).put("fullscreenViewport", fullscreen))
        val quality = ViewerQualityNativeQa.exercise(webView, "neutral-rig-quality", 4, 4)
        val highQualityReference = quality.getString("hqReferenceFrame")
        run(webView, "document.querySelector('.tab[data-tab=\"tools\"]').click();")
        assertFalse(state(webView).getBoolean("visible"))
        Thread.sleep(250)
        run(webView, "document.querySelector('.tab[data-tab=\"viewer\"]').click();" +
            "if(!document.getElementById('tab-viewer').classList.contains('viewer-expanded'))document.getElementById('viewer-expand').click();")
        waitForDom(webView, "the retained native rig tab") {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.visible&&s.loaded&&!s.loading,error:s.error,state:s});"
        }
        assertRetained(retainedState, state(webView))
        val afterTab = capture(webView, compare = highQualityReference)
        assertRestored("Returning to the viewer must retain its actual adjusted image", afterTab)
        recoverContext(webView)
        assertRetained(retainedState, state(webView))
        assertArrayNear("Context recovery must retain the authored rotated head world matrix",
            retainedHeadWorld.getJSONArray("matrix"), nodeWorld(webView, "Head").getJSONArray("matrix"))
        val afterContext = capture(webView, compare = highQualityReference)
        assertRestored("A restored native WebGL context must retain the adjusted model", afterContext)
        run(webView, "ViewerRigQa.withViewControls(function(){ViewerRigQa.viewControl('viewer-high-quality');ViewerQualityQa.set(false);});")
        waitForDom(webView, "the original standard quality after context recovery") {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.quality.ready&&!s.quality.enabled,state:s});"
        }
        assertRestored("Standard mode must retain its original adjusted image after HQ lifecycle checks", capture(webView, compare = "retained"))
        saveScreenshot(session.activity, "model-viewer-rig.png")
        click(webView, "viewer-preview-reset")
        assertTrue(state(webView).getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
        assertSavedTransforms(state(webView))
        val restoredFileDefault = capture(webView, compare = "savedDefault")
        assertRestored("Final reset must recover saved-file defaults after context restoration", restoredFileDefault)
        click(webView, "viewer-saved-nodes")
        assertRestored("Opting out must still recover exact authored pixels after context restoration", capture(webView, compare = "rest"))
        val report = JSONObject().put("scope", "Original serialized Unity rig through real API/GLB/native WebGL")
            .put("verticalViewport", verticalViewport)
            .put("poseControlsWithoutVerifiedPreview", poseControls)
            .put("defaultSavedNodes", defaultSavedNodes).put("defaultSavedFrame", defaultSavedFrame)
            .put("absoluteSourceValueEdits", absoluteAxes).put("childBoneCompensation", childCompensation)
            .put("restoredFileDefault", restoredFileDefault)
            .put("restVertices", restVertices).put("rest", rest).put("manualPose", manualPose)
            .put("referenceOnlyControls", referenceControls).put("absoluteProfiles", profileResults)
            .put("profileInvariantHead", profileInvariant.getValue("Head")).put("profileInvariantHair", profileInvariant.getValue("Neck_Hair"))
            .put("multiAxisHeadQuaternion", multiAxisHead)
            .put("breast", breast).put("savedEntry", saved).put("expression", expression)
            .put("scrub", scrub).put("playing", playing).put("paused", paused)
            .put("collapsibleSections", sections).put("fullscreenViewport", fullscreen).put("highQuality3D", quality)
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
        val quality = ViewerQualityNativeQa.exercise(webView, "member-shader-quality", 4, 8,
            leaveEnabled = false, centerRgb = intArrayOf(14, 63, 84))
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
        val report = JSONObject().put("member", member).put("basic", basic).put("highQuality3D", quality)
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
            webView?.let { runCatching { run(it, "if(window.ViewerQualityQa)ViewerQualityQa.dispose();if(window.ViewerRigQa)ViewerRigQa.dispose();") } }
            instrumentation.runOnMainSync { activity?.finish() }
            source.delete()
            preferences.edit().apply { if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide") }.commit()
        }
    }

    private fun exerciseSectionCollapse(session: Session, retained: JSONObject): JSONArray {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val originallyExpanded = retained.getJSONObject("layout").getBoolean("expanded")
        val originalGroup = retained.getJSONObject("rig").getString("editorGroup")
        val selectedBone = retained.getJSONObject("rig").getString("selectedNode")
        val results = JSONArray()
        fun selectArea(group: String) {
            run(session.webView, "var group=" + JSONObject.quote(group) + ",id=" + JSONObject.quote(selectedBone) + ";" +
                "var tab=document.getElementById('viewer-editor-'+group+'-tab'),panel=document.getElementById('viewer-editor-'+group+'-panel');" +
                "if(tab.getAttribute('aria-selected')!=='true')tab.click();" +
                "ViewerRigQa.input('viewer-node',id,'change');" +
                "if(panel.hidden||!panel.contains(document.getElementById('viewer-shared-bone-editor')))" +
                "throw new Error('The chosen editing area must contain the shared bone controls');")
            assertRetained(retained, state(session.webView))
            assertEquals("Changing editing areas preserves the explicitly selected bone", selectedBone,
                state(session.webView).getJSONObject("rig").getString("selectedNode"))
        }
        if (originallyExpanded) {
            click(session.webView, "viewer-expand")
            waitForDom(session.webView, "the normal editing layout", 30) {
                "var s=ModelViewer.getState();return JSON.stringify({ok:!s.layout.expanded,state:s});"
            }
        }
        try {
            // Shortcuts belong to the active Node/Mesh area. The advanced All
            // filter can select Head while Node is active, so first open its
            // recommended area instead of expecting every area to repeat it.
            val shortcutGroup = evaluate(session.webView,
                "var id=" + JSONObject.quote(selectedBone) + ",metadata=ModelViewer.getEditingMetadata()||{}," +
                    "target=(metadata.nodes||[]).filter(function(node){return String(node.node)===id;})[0];" +
                    "return JSON.stringify({group:target&&target.recommendedMethod||ModelViewer.getState().rig.editorGroup});")
                .getString("group")
            selectArea(shortcutGroup)
            run(session.webView, "var id=" + JSONObject.quote(selectedBone) + ";" +
                "var shortcut=Array.prototype.filter.call(document.querySelectorAll('#viewer-node-shortcuts [data-viewer-bone]'),function(button){return button.dataset.viewerBone===id;})[0];" +
                "if(!shortcut)throw new Error('The selected frequent bone must have a shortcut in its editing area');" +
                "var control=ViewerRigQa.control(shortcut,true);" +
                "if(!control.visible||!control.withinViewport||!control.hittable)throw new Error('The selected shortcut must be visible and unobstructed');shortcut.click();")
            val sections = listOf("viewer-common-adjustments", "viewer-breast-card", "viewer-skirt-card")
            for (id in sections) {
                // The shared common controls move with their area; breast and
                // skirt cards intentionally stay in the Node Scaling area.
                val sectionGroup = if (id == "viewer-common-adjustments") shortcutGroup else "node"
                selectArea(sectionGroup)
                val content = if (id == "viewer-common-adjustments") "#viewer-node-shortcuts" else ".viewer-card-content"
                val closed = evaluate(session.webView,
                    "var card=document.getElementById(" + JSONObject.quote(id) + "),summary=card.querySelector('summary'),content=card.querySelector(" + JSONObject.quote(content) + ");" +
                        "if(!card.open||content.getBoundingClientRect().height<=0)" +
                        "throw new Error('The normal editing section must initially show its source controls');" +
                        "summary.scrollIntoView({block:'center'});summary.click();" +
                        "return JSON.stringify({id:card.id,open:card.open,summaryHeight:summary.getBoundingClientRect().height," +
                        "contentHeight:content.getBoundingClientRect().height,states:['viewer-common-adjustments','viewer-breast-card','viewer-skirt-card'].map(function(id){return {id:id,open:document.getElementById(id).open};})});")
                assertFalse("Native details must hide its controls when collapsed", closed.getBoolean("open"))
                assertEquals("Collapsed content must occupy no space on the native WebView", 0.0, closed.getDouble("contentHeight"), 1e-6)
                assertTrue("A collapsed section keeps a 44 px summary target", closed.getDouble("summaryHeight") >= 44)
                val sectionStates = closed.getJSONArray("states")
                for (index in 0 until sectionStates.length()) {
                    val section = sectionStates.getJSONObject(index)
                    assertEquals("Each section must collapse independently", section.getString("id") != id, section.getBoolean("open"))
                }
                assertRetained(retained, state(session.webView))
                assertEquals("Collapsing preserves the shortcut-selected bone", retained.getJSONObject("rig").getString("selectedNode"), state(session.webView).getJSONObject("rig").getString("selectedNode"))
                instrumentation.runOnMainSync { session.webView.requestFocus() }
                run(session.webView, "var summary=document.getElementById(" + JSONObject.quote(id) + ").querySelector('summary');summary.focus();" +
                    "if(document.activeElement!==summary)throw new Error('The native section summary cannot receive keyboard focus');")
                instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_ENTER)
                val opened = waitForDom(session.webView, "keyboard reopening $id", 15) {
                    "var card=document.getElementById(" + JSONObject.quote(id) + ");return JSON.stringify({ok:card.open&&" +
                        "card.querySelector(" + JSONObject.quote(content) + ").getBoundingClientRect().height>0,open:card.open});"
                }
                val current = state(session.webView)
                assertRetained(retained, current)
                assertEquals("Keyboard reopening preserves the shortcut-selected bone", retained.getJSONObject("rig").getString("selectedNode"), current.getJSONObject("rig").getString("selectedNode"))
                for (kind in listOf("position", "target")) assertArrayNear("Section toggling preserves camera $kind",
                    retained.getJSONObject("camera").getJSONArray(kind), current.getJSONObject("camera").getJSONArray(kind))
                assertEquals(retained.getJSONObject("camera").getDouble("fov"), current.getJSONObject("camera").getDouble("fov"), 1e-9)
                results.put(JSONObject().put("id", id).put("editingArea", sectionGroup).put("closed", closed).put("keyboardReopened", opened))
            }
            return results
        } finally {
            selectArea(originalGroup)
            assertEquals("Section checks restore the original editing area", originalGroup,
                state(session.webView).getJSONObject("rig").getString("editorGroup"))
            if (state(session.webView).getJSONObject("layout").getBoolean("expanded") != originallyExpanded) click(session.webView, "viewer-expand")
            waitForDom(session.webView, "the original expanded preview geometry", 30) {
                "var s=ModelViewer.getState(),stage=s.layout.stage;return JSON.stringify({ok:s.layout.expanded===" + originallyExpanded +
                    "&&Math.abs(stage.width-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("width") +
                    ")<1&&Math.abs(stage.height-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("height") + ")<1,state:s});"
            }
        }
    }

    private fun assertVerticalHud(webView: WebView, includeGeometry: Boolean = false): JSONObject {
        val observed = evaluate(webView, "return JSON.stringify(ViewerRigQa.verticalViewport($includeGeometry));")
        assertTrue("The APK must use the reviewed visible vertical controls", observed.getBoolean("vertical"))
        val controls = observed.getJSONArray("controls")
        assertEquals("Retain every original HUD action", 11, controls.length())
        assertEquals("Separate controls must not overlap", 0, observed.getJSONArray("overlapPairs").length())
        for (index in 0 until controls.length()) {
            val target = controls.getJSONObject(index)
            assertEquals("Only intentional compact HUD controls use the smaller target", 32, target.getInt("minimumTarget"))
            assertTrue("Every HUD action remains visible and directly reachable: $target",
                target.getBoolean("visible") && target.getBoolean("withinViewport") && target.getBoolean("hittable") &&
                    target.getDouble("width") >= 32 && target.getDouble("height") >= 32)
        }
        if (includeGeometry) {
            val vertices = observed.getJSONObject("projectedVertices")
            assertTrue("Observe actual converted skin vertices", vertices.getInt("count") >= 6)
            assertEquals("Explicit Fit must retain all observed deformed vertices inside the viewport", 0, vertices.getInt("outside"))
            assertEquals("Visible model pixels must not be covered by closed HUD controls", 0, observed.getInt("coveredModelPixels"))
            assertEquals(0, observed.getJSONObject("framebuffer").getInt("glError"))
        }
        return observed
    }

    private fun exerciseVerticalViewport(webView: WebView): JSONArray {
        val results = JSONArray()
        val before = state(webView)
        assertVerticalHud(webView)
        try {
            for (direction in listOf("front", "back", "left", "right")) {
                run(webView, "document.querySelector('[data-viewer-view=\"$direction\"]').click();" +
                    "document.getElementById('viewer-fit').click();")
                results.put(assertVerticalHud(webView, true).put("direction", direction))
            }
        } finally {
            run(webView, "document.querySelector('[data-viewer-view=\"front\"]').click();document.getElementById('viewer-fit').click();")
        }
        val after = state(webView)
        assertEquals("Changing direction/Fit must not reload the model", before.getString("modelId"), after.getString("modelId"))
        assertEquals("Changing direction/Fit must preserve every rig edit and selected pose",
            before.getJSONObject("rig").toString(), after.getJSONObject("rig").toString())
        return results
    }

    /** Exercise the real Android window and the existing renderer without creating a second viewer. */
    private fun exerciseFullscreen(session: Session, retained: JSONObject): JSONObject {
        val activity = session.activity
        val webView = session.webView
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val originalRequested = activity.requestedOrientation
        val originalOrientation = activity.resources.configuration.orientation
        val normalNative = nativeViewport(session)
        val normalLayout = retained.getJSONObject("layout")
        val normalFrame = capture(webView)
        assertEquals("none", normalLayout.getString("fullscreen"))
        assertTrue("The existing expanded-preview choice must survive fullscreen", normalLayout.getBoolean("expanded"))
        fun assertPreserved(): JSONObject {
            val current = state(webView)
            assertRetained(retained, current)
            for (kind in listOf("position", "target")) assertArrayNear("Resizing must preserve camera $kind",
                retained.getJSONObject("camera").getJSONArray(kind), current.getJSONObject("camera").getJSONArray(kind))
            assertEquals(retained.getJSONObject("camera").getDouble("fov"), current.getJSONObject("camera").getDouble("fov"), 1e-9)
            return current
        }
        fun waitMode(mode: String) = waitForDom(webView, "native fullscreen mode $mode", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.layout.fullscreen==='" + mode +
                "'&&!s.layout.fullscreenPending&&s.loaded&&!s.loading,error:s.error,state:s});"
        }
        fun enter() {
            instrumentation.runOnMainSync { webView.requestFocus() }
            click(webView, "viewer-fullscreen"); waitMode("native")
        }
        fun assertNormal(checkFocus: Boolean = true): JSONObject {
            val current = waitNativeViewport(session, "restored app chrome") {
                it.getInt("headerVisibility") == normalNative.getInt("headerVisibility") &&
                    it.getInt("tabsVisibility") == normalNative.getInt("tabsVisibility") &&
                    it.getInt("systemUiVisibility") == normalNative.getInt("systemUiVisibility") &&
                    it.getInt("windowFlags") == normalNative.getInt("windowFlags")
            }
            assertEquals("Fullscreen Back must stay on the modeling-tools tab", 4, current.getInt("selectedTab"))
            assertTrue(current.getBoolean("webViewAttached"))
            if (checkFocus) assertEquals("Leaving fullscreen restores the original native focus target", normalNative.getInt("focusIdentity"), current.getInt("focusIdentity"))
            val state = assertPreserved()
            assertEquals(normalLayout.getBoolean("expanded"), state.getJSONObject("layout").getBoolean("expanded"))
            return current
        }
        try {
            enter()
            val entered = waitNativeViewport(session, "fullscreen app chrome and viewport") {
                it.getInt("headerVisibility") == View.GONE && it.getInt("tabsVisibility") == View.GONE &&
                    it.getInt("webViewHeight") > normalNative.getInt("webViewHeight")
            }
            assertTrue("Fullscreen must set the native window flag", (entered.getInt("windowFlags") and WindowManager.LayoutParams.FLAG_FULLSCREEN) != 0)
            val immersiveFlags = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            assertEquals("Fullscreen must hide Android status/navigation bars", immersiveFlags, entered.getInt("systemUiVisibility") and immersiveFlags)
            val enteredState = assertPreserved()
            val enteredControls = assertVerticalHud(webView)
            assertTrue("Fullscreen must give actual model pixels more height",
                enteredState.getJSONObject("layout").getJSONObject("stage").getDouble("height") > normalLayout.getJSONObject("stage").getDouble("height"))
            val fullscreenFrame = capture(webView)
            assertEquals(4, fullscreenFrame.getJSONObject("probe").getInt("sourceTriangles"))
            assertTrue("Native fullscreen must visibly enlarge actual model pixels",
                fullscreenFrame.getInt("foregroundPixelHeight") > normalFrame.getInt("foregroundPixelHeight") * 1.08)
            run(webView, "ElichikaViewerFullscreen.postMessage('enter');ElichikaViewerFullscreen.postMessage('enter');")
            waitMode("native"); assertPreserved()
            val opposite = if (originalOrientation == Configuration.ORIENTATION_LANDSCAPE)
                ActivityInfo.SCREEN_ORIENTATION_PORTRAIT else ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            instrumentation.runOnMainSync { activity.requestedOrientation = opposite }
            val rotated = waitNativeViewport(session, "fullscreen orientation change") {
                it.getInt("orientation") != originalOrientation && it.getInt("headerVisibility") == View.GONE &&
                    it.getInt("tabsVisibility") == View.GONE && it.getBoolean("hasFocus")
            }
            waitMode("native"); assertPreserved()
            waitForDom(webView, "the rotated WebView viewport", 30) {
                "var s=ModelViewer.getState(),v=s.layout.viewport;return JSON.stringify({ok:" +
                    (if (originalOrientation == Configuration.ORIENTATION_LANDSCAPE) "v.height>v.width" else "v.width>v.height") + ",state:s});"
            }
            val rendered = capture(webView)
            val rotatedControls = assertVerticalHud(webView)
            assertEquals(4, rendered.getJSONObject("probe").getInt("sourceTriangles"))
            assertTrue("The rotated fullscreen must render the actual weighted model", rendered.getInt("foregroundPixels") >= 64)
            saveScreenshot(activity, "model-viewer-fullscreen.png")
            instrumentation.runOnMainSync { activity.requestedOrientation = if (originalOrientation == Configuration.ORIENTATION_LANDSCAPE)
                ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE else ActivityInfo.SCREEN_ORIENTATION_PORTRAIT }
            waitNativeViewport(session, "original fullscreen orientation") { it.getInt("orientation") == originalOrientation && it.getBoolean("hasFocus") }
            waitMode("native"); assertPreserved()
            instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
            waitMode("none")
            val afterBack = assertNormal()
            run(webView, "ElichikaViewerFullscreen.postMessage('exit');ElichikaViewerFullscreen.postMessage('exit');")
            waitMode("none"); assertNormal()
            enter()
            instrumentation.runOnMainSync { activity.findViewById<TabLayout>(R.id.tabs).getTabAt(0)!!.select() }
            waitNativeViewport(session, "fullscreen cleanup on a native tab change") {
                it.getInt("selectedTab") == 0 && it.getInt("headerVisibility") == normalNative.getInt("headerVisibility") &&
                    it.getInt("tabsVisibility") == normalNative.getInt("tabsVisibility")
            }
            instrumentation.runOnMainSync { activity.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select() }
            waitMode("none")
            val afterNativeTab = assertNormal(checkFocus = false)
            enter()
            assertTrue("The framework must accept Home for the actual onStop lifecycle", instrumentation.uiAutomation.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME))
            waitNativeViewport(session, "background fullscreen cleanup") {
                !it.getBoolean("hasFocus") && it.getInt("headerVisibility") == normalNative.getInt("headerVisibility") &&
                    it.getInt("tabsVisibility") == normalNative.getInt("tabsVisibility")
            }
            instrumentation.runOnMainSync { activity.startActivity(Intent(activity, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
            waitNativeViewport(session, "the same activity returning from Home") { it.getBoolean("hasFocus") && it.getBoolean("webViewAttached") }
            waitMode("none")
            val afterLifecycle = assertNormal()
            enter()
            val exit = evaluate(webView, "return JSON.stringify(ViewerRigQa.control('viewer-fullscreen',false));")
            assertTrue("The fullscreen exit must retain its compact visible target", exit.getBoolean("visible") && exit.getBoolean("withinViewport") && exit.getBoolean("hittable") &&
                exit.getDouble("width") >= exit.getInt("minimumTarget") && exit.getDouble("height") >= exit.getInt("minimumTarget"))
            click(webView, "viewer-fullscreen"); waitMode("none")
            val restored = assertNormal()
            waitNativeViewport(session, "the unchanged original preview dimensions") {
                it.getInt("webViewWidth") == normalNative.getInt("webViewWidth") && it.getInt("webViewHeight") == normalNative.getInt("webViewHeight")
            }
            waitForDom(webView, "the restored renderer stage dimensions", 30) {
                "var s=ModelViewer.getState(),stage=s.layout.stage;return JSON.stringify({ok:Math.abs(stage.width-" +
                    normalLayout.getJSONObject("stage").getDouble("width") + ")<1&&Math.abs(stage.height-" +
                    normalLayout.getJSONObject("stage").getDouble("height") + ")<1,state:s});"
            }
            return JSONObject().put("normal", normalNative).put("normalFrame", normalFrame).put("entered", entered)
                .put("enteredVerticalControls", enteredControls).put("rotatedVerticalControls", rotatedControls)
                .put("fullscreenFrame", fullscreenFrame).put("rotated", rotated)
                .put("renderedFullscreen", rendered).put("afterBack", afterBack).put("afterNativeTab", afterNativeTab)
                .put("afterLifecycle", afterLifecycle).put("restored", restored)
        } finally {
            instrumentation.runOnMainSync { activity.requestedOrientation = originalRequested }
        }
    }

    private fun nativeViewport(session: Session): JSONObject {
        val result = AtomicReference<JSONObject>()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val activity = session.activity
            val tabs = activity.findViewById<TabLayout>(R.id.tabs)
            result.set(JSONObject().put("headerVisibility", activity.findViewById<View>(R.id.app_header).visibility)
                .put("tabsVisibility", tabs.visibility).put("selectedTab", tabs.selectedTabPosition)
                .put("webViewWidth", session.webView.width).put("webViewHeight", session.webView.height)
                .put("webViewAttached", session.webView.isAttachedToWindow && session.webView.visibility == View.VISIBLE)
                .put("hasFocus", activity.hasWindowFocus()).put("focusIdentity", System.identityHashCode(activity.currentFocus))
                .put("orientation", activity.resources.configuration.orientation)
                .put("requestedOrientation", activity.requestedOrientation)
                .put("systemUiVisibility", activity.window.decorView.systemUiVisibility).put("windowFlags", activity.window.attributes.flags))
        }
        return result.get()
    }

    private fun waitNativeViewport(session: Session, description: String, accept: (JSONObject) -> Boolean): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        var observed = JSONObject()
        while (System.nanoTime() < deadline) {
            observed = nativeViewport(session)
            if (accept(observed)) return observed
            Thread.sleep(100)
        }
        throw AssertionError("Timed out waiting for $description: $observed")
    }

    private fun recoverContext(webView: WebView) {
        run(webView, "ViewerRigQa.loseContext();")
        waitForDom(webView, "actual native context loss", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.contextLost&&document.getElementById('viewer-breast-preset').disabled&&" +
                "document.getElementById('viewer-pose-basic').disabled&&document.getElementById('viewer-pose-preview').disabled,state:s});"
        }
        run(webView, "ViewerRigQa.restoreContext();")
        waitForDom(webView, "actual native context restoration", 60) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:!s.contextLost&&s.loaded&&!s.loading&&!document.getElementById('viewer-breast-preset').disabled&&" +
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

    private fun assertReferenceOnlyControls(webView: WebView): JSONObject {
        val result = evaluate(webView,
            "var ids=['viewer-height','viewer-height-number','viewer-breast','viewer-breast-number','viewer-skirt'];" +
                "return JSON.stringify({removed:ids.every(function(id){return !document.getElementById(id);}),rig:ModelViewer.getState().rig});")
        assertTrue("Arbitrary height and continuous breast sliders must not exist", result.getBoolean("removed"))
        val rig = result.getJSONObject("rig")
        assertEquals("saved_settings_only", rig.getString("heightMode"))
        assertFalse(rig.has("heightCompensation"))
        assertEquals(2, rig.getJSONObject("body").length())
        assertEquals("loaded", rig.getJSONObject("body").getString("breastPreset"))
        assertEquals("file", rig.getJSONObject("body").getString("skirtMode"))
        assertEquals(4, rig.getJSONObject("scaling").getInt("version"))
        val controls = rig.getJSONObject("scaling").getJSONArray("controls")
        val height = (0 until controls.length()).map { controls.getJSONObject(it) }.single { it.getString("id") == "height" }
        assertFalse(height.getBoolean("available")); assertEquals("saved_height_metadata_only", height.getString("mode"))
        return result
    }

    private fun exerciseChildCompensation(webView: WebView): JSONObject {
        val start = state(webView)
        val initiallyExpanded = start.getJSONObject("layout").getBoolean("expanded")
        if (initiallyExpanded) click(webView, "viewer-expand")
        try {
            boneInput(webView, "BreastSize", "position", "X", .05)
            boneInput(webView, "BreastSize", "rotation", "Z", 35)
            boneInput(webView, "Tip", "position", "X", .15)
            boneInput(webView, "Tip", "scale", "X", 1.1)
            boneInput(webView, "Tip", "rotation", "Y", 20)
            val referenceState = state(webView)
            val referenceWorld = nodeWorld(webView, "Tip")
            run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('BreastSize'),'change');")
            val defaultOff = evaluate(webView,
                "return JSON.stringify({checked:document.getElementById('bone-compensate-children').checked," +
                    "mode:document.getElementById('bone-compensate-target').value});")
            assertFalse("Child compensation must begin as an explicit opt-in", defaultOff.getBoolean("checked"))
            assertEquals("auto", defaultOff.getString("mode"))
            click(webView, "bone-compensate-children")
            boneInput(webView, "BreastSize", "scale", "X", 1.56)
            boneInput(webView, "BreastSize", "scale", "Y", 1.17)
            boneInput(webView, "BreastSize", "scale", "Z", .8)
            val correctedState = state(webView)
            val correctedWorld = nodeWorld(webView, "Tip")
            assertBoneScale(correctedState, "BreastSize", doubleArrayOf(1.56, 1.17, .8))
            assertArrayNear("The rotated, nonuniform parent must preserve the child's complete actual world transform",
                referenceWorld.getJSONArray("matrix"), correctedWorld.getJSONArray("matrix"))
            for (kind in listOf("position", "quaternion", "scale")) assertArrayNear("Compensation must retain the child's own manual $kind",
                bone(referenceState, "Tip").getJSONArray(kind), bone(correctedState, "Tip").getJSONArray(kind))
            for (kind in listOf("position", "quaternion")) assertArrayNear("Compensation must retain the parent's requested $kind",
                bone(referenceState, "BreastSize").getJSONArray(kind), bone(correctedState, "BreastSize").getJSONArray(kind))
            val parentId = bone(correctedState, "BreastSize").getString("node")
            val parents = correctedState.getJSONObject("rig").getJSONObject("compensation").getJSONArray("parents")
            val status = (0 until parents.length()).map { parents.getJSONObject(it) }.single { it.getString("node") == parentId }
            assertEquals("active", status.getString("state"))
            assertArrayNear("Compensation uses each explicit factor relative to the active imported baseline",
                JSONArray(listOf(1.2, 1.3, .8)), status.getJSONArray("scaleDelta"))
            click(webView, "bone-compensate-children")
            val propagated = nodeWorld(webView, "Tip")
            assertTrue("Opting out must visibly restore normal parent propagation",
                (0 until 16).maxOf { kotlin.math.abs(propagated.getJSONArray("matrix").getDouble(it) - referenceWorld.getJSONArray("matrix").getDouble(it)) } > .05)
            click(webView, "bone-compensate-children")
            assertArrayNear("Repeated compensation must not compound corrections", referenceWorld.getJSONArray("matrix"), nodeWorld(webView, "Tip").getJSONArray("matrix"))
            click(webView, "viewer-node-reset")
            val parentReset = state(webView)
            assertFalse("Reset this bone clears its compensation opt-in", parentReset.getJSONObject("rig").getJSONObject("nodeCompensations").has(parentId))
            assertEquals("Clearing compensation restores the child's normal matrix updates", referenceWorld.getBoolean("matrixAutoUpdate"), nodeWorld(webView, "Tip").getBoolean("matrixAutoUpdate"))
            for (kind in listOf("position", "quaternion", "scale")) assertArrayNear("Resetting the parent preserves the child's own $kind edits",
                bone(referenceState, "Tip").getJSONArray(kind), bone(parentReset, "Tip").getJSONArray(kind))
            click(webView, "viewer-preview-reset")
            val restored = state(webView)
            assertSavedTransforms(restored)
            assertEquals(0, restored.getJSONObject("rig").getJSONObject("nodeAdjustments").length())
            assertEquals(0, restored.getJSONObject("rig").getJSONObject("nodeCompensations").length())
            return JSONObject().put("defaultOff", defaultOff).put("referenceWorld", referenceWorld).put("correctedWorld", correctedWorld)
                .put("normalPropagationWorld", propagated).put("status", status).put("childEditsPreserved", true).put("resetToSource", true)
        } finally {
            if (state(webView).getJSONObject("layout").getBoolean("expanded") != initiallyExpanded) click(webView, "viewer-expand")
            waitForDom(webView, "the source preview after compensation cleanup", 30) {
                "var s=ModelViewer.getState(),stage=s.layout.stage;return JSON.stringify({ok:s.layout.expanded===" + initiallyExpanded +
                    "&&Math.abs(stage.width-" + start.getJSONObject("layout").getJSONObject("stage").getDouble("width") +
                    ")<1&&Math.abs(stage.height-" + start.getJSONObject("layout").getJSONObject("stage").getDouble("height") + ")<1,state:s});"
            }
        }
    }

    /** Pin only edited axes while untouched axes keep following the active source baseline. */
    private fun exerciseAbsoluteAxes(webView: WebView): JSONObject {
        fun assertMask(current: JSONObject, name: String, kind: String, expected: List<Double?>) {
            val id = bone(current, name).getString("node")
            val adjustment = current.getJSONObject("rig").getJSONObject("nodeAdjustments").getJSONObject(id)
            assertEquals("absolute_axes", adjustment.getString("mode"))
            val axes = adjustment.getJSONArray(kind)
            assertEquals(3, axes.length())
            for (axis in expected.indices) {
                val value = expected[axis]
                if (value == null) assertTrue("$name $kind axis $axis must inherit its baseline", axes.isNull(axis))
                else assertEquals("$name $kind axis $axis must keep the entered endpoint", value, axes.getDouble(axis), 1e-9)
            }
        }
        fun assertValues(saved: Boolean): JSONObject {
            val current = state(webView)
            assertBoneScale(current, "BreastSize", doubleArrayOf(1.4, if (saved) .9 else 1.0, 1.0))
            assertArrayNear("Only the explicit Tip X is pinned; the saved Y remains inherited",
                JSONArray(listOf(-.2, if (saved) .6 else .5, 0.0)), bone(current, "Tip").getJSONArray("position"))
            assertUnityRotation("Only the explicit Unity Y rotation is pinned",
                bone(current, "Tip").getJSONArray("quaternion"), doubleArrayOf(if (saved) 30.0 else 0.0, 45.0, 0.0))
            val target = current.getJSONObject("rig").getJSONObject("breastProfile").getJSONArray("targets").getJSONObject(0)
            assertEquals("saved", target.getString("fileStatus"))
            assertArrayNear("File XYZ must remain immutable regardless of preview toggles", JSONArray(listOf(1.3, .9, 1.0)), target.getJSONArray("fileScale"))
            assertArrayNear("Active XYZ is separate from immutable file XYZ", JSONArray(if (saved) listOf(1.3, .9, 1.0) else listOf(1.0, 1.0, 1.0)), target.getJSONArray("activeScale"))
            assertArrayNear("Current XYZ includes the absolute manual factor", bone(current, "BreastSize").getJSONArray("scale"), target.getJSONArray("currentScale"))
            assertMask(current, "BreastSize", "scale", listOf(1.4, null, null))
            assertMask(current, "BreastSize", "position", listOf(null, null, null))
            assertMask(current, "Tip", "position", listOf(-.2, null, null))
            assertMask(current, "Tip", "rotation", listOf(null, 45.0, null))
            return current
        }
        fun togglePart(name: String) = run(webView,
            "var id=String(ViewerRigQa.nodeId(" + JSONObject.quote(name) + "));" +
                "var groups=ModelViewer.getState().rig.savedNodes.groups.filter(function(group){return group.nodes.indexOf(id)>=0;});" +
                "if(groups.length!==1)throw new Error('Expected one saved group for '+id);" +
                "var input=Array.prototype.filter.call(document.querySelectorAll('[data-viewer-saved-part]'),function(input){return input.dataset.viewerSavedPart===groups[0].id;})[0];" +
                "if(!input||input.disabled)throw new Error('Saved part control is unavailable');input.click();")

        boneInput(webView, "BreastSize", "scale", "X", 1.4)
        boneInput(webView, "Tip", "position", "X", .2)
        boneInput(webView, "Tip", "rotation", "Y", 45)
        val edited = assertValues(true)
        click(webView, "viewer-saved-nodes")
        val globalOff = assertValues(false)
        click(webView, "viewer-saved-nodes")
        assertValues(true)
        togglePart("BreastSize"); togglePart("Tip")
        val partsOff = assertValues(false)
        assertTrue("Per-part opt-outs must preserve the global saved-settings selection",
            partsOff.getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled"))
        togglePart("BreastSize"); togglePart("Tip")
        assertValues(true)

        input(webView, "viewer-breast-preset", "rin", "change")
        boneInput(webView, "BreastSize", "scale", "X", 1.3)
        val equalFile = state(webView)
        assertBoneScale(equalFile, "BreastSize", doubleArrayOf(1.3, .95, .9))
        assertMask(equalFile, "BreastSize", "scale", listOf(1.3, null, null))
        click(webView, "viewer-saved-nodes")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.3, .95, .9))
        click(webView, "viewer-breast-reset")
        assertBoneScale(state(webView), "BreastSize", doubleArrayOf(1.0, 1.0, 1.0))
        click(webView, "viewer-saved-nodes")
        run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('Tip'),'change');")
        click(webView, "viewer-node-reset")
        val restored = state(webView)
        assertSavedTransforms(restored)
        assertEquals("Undo actions must clear only manual masks, restoring the unchanged source", 0,
            restored.getJSONObject("rig").getJSONObject("nodeAdjustments").length())
        return JSONObject().put("edited", edited.getJSONObject("rig")).put("globalSavedOff", globalOff.getJSONObject("rig"))
            .put("partsSavedOff", partsOff.getJSONObject("rig")).put("sourceEqualPin", equalFile.getJSONObject("rig"))
            .put("restored", restored.getJSONObject("rig"))
    }

    private fun nodeWorld(webView: WebView, name: String): JSONObject = evaluate(webView,
        "return JSON.stringify(ViewerRigQa.nodeWorld(" + JSONObject.quote(name) + "));")

    private fun assertArrayNear(message: String, expected: JSONArray, actual: JSONArray) {
        assertEquals(message, expected.length(), actual.length())
        for (axis in 0 until expected.length()) assertEquals("$message axis $axis",
            expected.getDouble(axis), actual.getDouble(axis), 1e-6)
    }

    private fun assertUnityRotation(message: String, quaternion: JSONArray, degrees: DoubleArray) {
        val x = Math.toRadians(degrees[0]); val y = Math.toRadians(degrees[1]); val z = Math.toRadians(degrees[2])
        val sx = kotlin.math.sin(x); val sy = kotlin.math.sin(y); val sz = kotlin.math.sin(z)
        val cx = kotlin.math.cos(x); val cy = kotlin.math.cos(y); val cz = kotlin.math.cos(z)
        // Independent column-vector Ry*Rx*Rz, reflected by diag(-1,1,1).
        val expected = doubleArrayOf(cy * cz + sy * sx * sz, cy * sz - sy * sx * cz, -sy * cx,
            -cx * sz, cx * cz, -sx, sy * cz - cy * sx * sz, sy * sz + cy * sx * cz, cy * cx)
        val qx = quaternion.getDouble(0); val qy = quaternion.getDouble(1)
        val qz = quaternion.getDouble(2); val qw = quaternion.getDouble(3)
        val actual = doubleArrayOf(1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw),
            2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw),
            2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy))
        for (axis in expected.indices) assertEquals("$message matrix element $axis", expected[axis], actual[axis], 1e-6)
    }

    private fun assertAdvancedVector(webView: WebView, kind: String, expected: DoubleArray) {
        val values = evaluate(webView,
            "var inputs=document.querySelectorAll('[data-viewer-node-kind=\"" + kind + "\"]');" +
                "return JSON.stringify({values:Array.prototype.map.call(inputs,function(input){return Number(input.value);})});")
            .getJSONArray("values")
        assertEquals("The visible $kind editor must have all source axes", 3, values.length())
        for (axis in expected.indices) assertEquals("The visible $kind axis $axis must show its imported value",
            expected[axis], values.getDouble(axis), 1e-6)
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
        assertEquals(first.getJSONObject("breastProfile").toString(), second.getJSONObject("breastProfile").toString())
        assertEquals("saved_settings_only", second.getString("heightMode"))
        assertEquals(first.getJSONObject("nodeAdjustments").toString(), second.getJSONObject("nodeAdjustments").toString())
        assertEquals(first.getJSONObject("nodeCompensations").toString(), second.getJSONObject("nodeCompensations").toString())
        assertEquals(first.getJSONArray("expressions").toString(), second.getJSONArray("expressions").toString())
        assertEquals(first.getJSONObject("savedNodes").getBoolean("enabled"), second.getJSONObject("savedNodes").getBoolean("enabled"))
        assertEquals(first.getJSONObject("savedNodes").getInt("applied"), second.getJSONObject("savedNodes").getInt("applied"))
        assertEquals(before.getString("modelId"), after.getString("modelId"))
        for (name in listOf("Move", "BreastSize", "Tip", "Head", "Neck_Hair")) {
            for (property in listOf("position", "quaternion", "scale")) {
                val left = bone(before, name).getJSONArray(property); val right = bone(after, name).getJSONArray(property)
                for (axis in 0 until left.length()) assertEquals(left.getDouble(axis), right.getDouble(axis), 1e-8)
            }
        }
    }

    private fun state(webView: WebView): JSONObject = evaluate(webView, "return JSON.stringify(ModelViewer.getState());")
    private fun input(webView: WebView, id: String, value: String, event: String = "input") = run(webView,
        "ViewerRigQa.input(" + JSONObject.quote(id) + "," + JSONObject.quote(value) + "," + JSONObject.quote(event) + ");")
    private fun click(webView: WebView, id: String) = run(webView,
        if (id == "viewer-pose-basic" || id == "viewer-pose-preview")
            "ViewerRigQa.withViewControls(function(){ViewerRigQa.viewControl(" + JSONObject.quote(id) + ");ViewerRigQa.click(" + JSONObject.quote(id) + ");});"
        else "ViewerRigQa.click(" + JSONObject.quote(id) + ");")
    private fun boneInput(webView: WebView, name: String, kind: String, axis: String, value: Number) = run(webView,
        "ViewerRigQa.boneInput(" + JSONObject.quote(name) + "," + JSONObject.quote(kind) + "," + JSONObject.quote(axis) + ",$value);")
    private fun run(webView: WebView, script: String) = evaluate(webView, script + "\nreturn JSON.stringify({ok:true});")

    private fun saveScreenshot(activity: MainActivity, filename: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        val frameReady = CountDownLatch(1)
        val observed = AtomicReference<JSONObject>()
        var captureOrientation = Configuration.ORIENTATION_UNDEFINED
        lateinit var observer: ViewTreeObserver
        lateinit var preDraw: ViewTreeObserver.OnPreDrawListener
        lateinit var focusChange: ViewTreeObserver.OnWindowFocusChangeListener
        fun observe(): JSONObject {
            val decor = activity.window.decorView
            return JSONObject().put("filename", filename).put("activityIdentity", System.identityHashCode(activity))
                .put("lifecycle", activity.lifecycle.currentState.toString())
                .put("resumed", activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
                .put("finishing", activity.isFinishing).put("destroyed", activity.isDestroyed)
                .put("hasFocus", activity.hasWindowFocus()).put("decorAttached", decor.isAttachedToWindow)
                .put("decorShown", decor.isShown).put("decorVisibility", decor.visibility)
                .put("decorWidth", decor.width).put("decorHeight", decor.height)
                .put("orientation", activity.resources.configuration.orientation)
                .put("requestedOrientation", activity.requestedOrientation)
                .put("captureOrientation", captureOrientation)
                .put("focusIdentity", System.identityHashCode(activity.currentFocus))
                .put("focusClass", activity.currentFocus?.javaClass?.name ?: "none")
                .put("systemUiVisibility", decor.systemUiVisibility).put("windowFlags", activity.window.attributes.flags)
        }
        fun canCapture(state: JSONObject) = state.getBoolean("resumed") && !state.getBoolean("finishing") &&
            !state.getBoolean("destroyed") && state.getBoolean("hasFocus") && state.getBoolean("decorAttached") &&
            state.getBoolean("decorShown") && state.getInt("decorWidth") > 0 && state.getInt("decorHeight") > 0 &&
            state.getInt("orientation") == captureOrientation
        instrumentation.runOnMainSync {
            captureOrientation = when (activity.requestedOrientation) {
                ActivityInfo.SCREEN_ORIENTATION_PORTRAIT, ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT,
                ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT, ActivityInfo.SCREEN_ORIENTATION_USER_PORTRAIT -> Configuration.ORIENTATION_PORTRAIT
                ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE, ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE,
                ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE, ActivityInfo.SCREEN_ORIENTATION_USER_LANDSCAPE -> Configuration.ORIENTATION_LANDSCAPE
                else -> activity.resources.configuration.orientation
            }
            val decor = activity.window.decorView
            observer = decor.viewTreeObserver
            preDraw = ViewTreeObserver.OnPreDrawListener {
                val current = observe(); observed.set(current)
                if (canCapture(current)) frameReady.countDown()
                true
            }
            focusChange = ViewTreeObserver.OnWindowFocusChangeListener {
                observed.set(observe())
                if (it) decor.postInvalidateOnAnimation()
            }
            observer.addOnPreDrawListener(preDraw)
            observer.addOnWindowFocusChangeListener(focusChange)
            observed.set(observe())
            decor.postInvalidateOnAnimation()
        }
        try {
            val ready = frameReady.await(30, TimeUnit.SECONDS)
            val windowOwner = if (ready) "" else runCatching {
                android.os.ParcelFileDescriptor.AutoCloseInputStream(
                    instrumentation.uiAutomation.executeShellCommand("dumpsys window windows")
                ).bufferedReader().use { reader -> reader.readText().lineSequence()
                    .filter { it.contains("mCurrentFocus") || it.contains("mFocusedApp") ||
                        it.contains("mTopFocusedDisplayId") || it.contains("Immersive") || it.contains("immersive") }
                    .take(30).joinToString("\n") }
            }.getOrElse { "Window focus diagnostic unavailable: $it" }
            assertTrue("Timed out awaiting a focused Activity frame for $filename: ${observed.get()}; focused windows: $windowOwner", ready)
            instrumentation.runOnMainSync {
                val current = observe(); observed.set(current)
                assertTrue("Screenshot requires the same resumed, attached Activity: $current", canCapture(current))
                assertTrue("Screenshot requires focused Activity for $filename: $current", activity.hasWindowFocus())
            }
        } finally {
            instrumentation.runOnMainSync {
                if (observer.isAlive) {
                    observer.removeOnPreDrawListener(preDraw)
                    observer.removeOnWindowFocusChangeListener(focusChange)
                }
            }
        }
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
