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
        val independentPanels = exerciseIndependentPoseAndBodyPanels(session, retainedState)
        val expressionPanel = exerciseExpressionPanel(session, retainedState)
        val sections = exerciseSectionCollapse(session, retainedState)
        val fullscreen = exerciseFullscreen(session, retainedState)
        capture(webView, "retained")
        persistReport("model-viewer-viewport-milestones.json", JSONObject()
            .put("scope", "Strict new-feature milestones captured before the unchanged quality exercise")
            .put("verticalViewport", verticalViewport)
            .put("absoluteSourceValueEdits", absoluteAxes).put("childBoneCompensation", childCompensation)
            .put("independentPoseAndBodyPanels", independentPanels).put("separateExpressionPanel", expressionPanel)
            .put("collapsibleSections", sections).put("fullscreenViewport", fullscreen))
        val quality = ViewerQualityNativeQa.exercise(webView, "neutral-rig-quality", 4, 4)
        val highQualityReference = quality.getString("hqReferenceFrame")
        val qualityNativeViewport = nativeViewport(session)
        val qualityPresentation = presentation(webView)
        for (key in listOf("expanded", "fullscreen")) assertEquals("The recorded presentation must match the quality reference's $key",
            quality.getJSONObject("finalState").getJSONObject("layout").get(key), qualityPresentation.getJSONObject("layout").get(key))
        persistReport("model-viewer-rig-resume-geometry.json", JSONObject().put("status", "REFERENCE_CAPTURED")
            .put("referencePresentation", qualityPresentation).put("referenceNativeViewport", qualityNativeViewport))
        selectNativeAssetSection(session, MainActivity.TAB_ASSET_TOOLS, "tools")
        selectNativeAssetSection(session, MainActivity.TAB_MODEL_VIEWER, "viewer")
        val restoredPresentation = restorePresentation(webView, qualityPresentation)
        assertRetained(retainedState, state(webView))
        val resumeGeometry = waitForRetainedFramebuffer(session, quality.getJSONObject("high"),
            quality.getJSONObject("highDriver").getJSONObject("quality"), qualityNativeViewport, restoredPresentation)
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
        // All original fixed-viewport pixel thresholds have finished before the
        // intentional minimize/restore layout transition.
        val minimizedModel = exerciseModelMinimize(session)
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
            .put("independentPoseAndBodyPanels", independentPanels).put("separateExpressionPanel", expressionPanel)
            .put("collapsibleSections", sections).put("fullscreenViewport", fullscreen).put("highQuality3D", quality)
            .put("restoredReferencePresentation", restoredPresentation)
            .put("retainedFramebufferGeometry", resumeGeometry).put("afterTab", afterTab).put("afterContext", afterContext)
            .put("modelMinimize", minimizedModel)
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

    @Test
    fun outlineControlsKeepExactEditsValidateSaveAndResetOnlyOutlines() = withRig { session ->
        val webView = session.webView
        waitForDom(webView, "the genuine source outline catalogue and controls") {
            "var m=ModelViewer.getEditingMetadata(),s=ModelViewer.getState();return JSON.stringify({ok:" +
                "!!window.ViewerOutlines&&!!m&&m.available&&!!m.outlines&&m.outlines.meshes.length>0&&" +
                "!!s.outlines&&s.outlines.available&&!document.getElementById('viewer-outline-number').disabled});"
        }
        val initial = evaluate(webView,
            "var panel=document.getElementById('viewer-outline-card'),expression=document.getElementById('viewer-expression-adjustments')," +
                "body=document.getElementById('viewer-body-adjustments');return JSON.stringify({collapsed:!panel.open," +
                "afterExpression:panel.previousElementSibling===expression,beforeBody:panel.nextElementSibling===body," +
                "meshes:ModelViewer.getEditingMetadata().outlines.meshes.map(function(m){return m.id;})," +
                "authoring:ModelViewer.getAuthoringState()});")
        assertTrue("Outline controls must start collapsed", initial.getBoolean("collapsed"))
        assertTrue("The actual outline card follows Expression", initial.getBoolean("afterExpression"))
        assertTrue("The actual outline card precedes Body", initial.getBoolean("beforeBody"))
        val catalogue = initial.getJSONArray("meshes")
        assertTrue("The fixture supplies original editable outline data", catalogue.length() > 0)
        run(webView, "document.querySelector('#viewer-outline-card > summary').click();")

        boneInput(webView, "BreastSize", "scale", "Y", 1.125)
        input(webView, "viewer-save-method", "node", "change")
        val unrelated = evaluate(webView,
            "var a=ModelViewer.getAuthoringState();delete a.outlines;return JSON.stringify(a);")
        assertTrue("A separate valid body edit makes Save meaningful", unrelated.getJSONArray("edits").length() > 0)
        waitForDom(webView, "Save for the unrelated valid body edit") {
            "return JSON.stringify({ok:!document.getElementById('viewer-save').disabled});"
        }

        fun outlineState(): JSONObject = evaluate(webView,
            "return JSON.stringify({authoring:ModelViewer.getAuthoringState(),outline:ModelViewer.getState().outlines," +
                "saveDisabled:document.getElementById('viewer-save').disabled," +
                "invalid:!document.getElementById('viewer-outline-number').checkValidity()," +
                "status:document.getElementById('viewer-outline-status').textContent});")
        fun assertFactors(observed: JSONObject, expected: Double) {
            val values = observed.getJSONObject("authoring").getJSONArray("outlines")
            assertEquals("All original catalogue meshes receive the selected factor", catalogue.length(), values.length())
            val ids = (0 until catalogue.length()).map { catalogue.getString(it) }.toSet()
            for (index in 0 until values.length()) {
                val entry = values.getJSONObject(index)
                assertTrue("Only original source mesh IDs may be authored", entry.getString("id") in ids)
                assertEquals("Outline state preserves numeric precision", expected, entry.getDouble("factor"), 1e-12)
            }
        }
        run(webView, "document.getElementById('viewer-outline-number').focus();")
        input(webView, "viewer-outline-number", "137.123456789")
        val numbered = outlineState()
        assertFactors(numbered, 137.123456789 / 100.0)
        assertFalse("A valid precise outline edit keeps Save enabled", numbered.getBoolean("saveDisabled"))

        input(webView, "viewer-shader", "basic", "change")
        val basic = outlineState()
        assertFalse("Basic rendering reports that outline preview is unavailable", basic.getJSONObject("outline").getBoolean("shaderEnabled"))
        assertTrue("The actual warning identifies SIFAS rendering", basic.getString("status").contains("SIFAS"))
        assertFactors(basic, 137.123456789 / 100.0)
        input(webView, "viewer-shader", "sifas", "change")
        val member = outlineState()
        assertTrue("Restoring SIFAS rendering restores outline preview eligibility", member.getJSONObject("outline").getBoolean("shaderEnabled"))
        assertTrue("The basic-renderer warning clears", member.getString("status") != basic.getString("status"))
        assertFactors(member, 137.123456789 / 100.0)

        run(webView, "document.getElementById('viewer-outline-number').focus();")
        input(webView, "viewer-outline-number", "201")
        val invalid = outlineState()
        assertTrue("Out-of-range outline input is rejected", invalid.getBoolean("invalid"))
        assertTrue("Invalid outline input blocks real Save", invalid.getBoolean("saveDisabled"))
        assertFactors(invalid, 137.123456789 / 100.0)
        run(webView, "document.getElementById('viewer-outline-range').focus();")
        input(webView, "viewer-outline-range", "80")
        val ranged = outlineState()
        assertFactors(ranged, .8)
        assertFalse("A valid range edit clears the invalid draft", ranged.getBoolean("invalid"))
        assertFalse("A valid range edit restores Save", ranged.getBoolean("saveDisabled"))
        click(webView, "viewer-outline-reset")
        val reset = outlineState()
        assertEquals("Reset removes outline edits", 0, reset.getJSONObject("authoring").optJSONArray("outlines")?.length() ?: 0)
        val bodyAfterReset = JSONObject(reset.getJSONObject("authoring").toString()).apply { remove("outlines") }
        assertEquals("Outline reset preserves every unrelated authoring field", unrelated.toString(), bodyAfterReset.toString())
        assertFalse("Reset keeps unrelated valid body edits saveable", reset.getBoolean("saveDisabled"))
        saveScreenshot(session.activity, "model-viewer-outline-controls.png")
        val report = JSONObject().put("status", "PASS").put("initial", initial).put("number", numbered)
            .put("basic", basic).put("sifas", member).put("invalid", invalid).put("range", ranged).put("reset", reset)
            .put("unrelatedAuthoringPreserved", true).put("sourcePreserved", true)
            .put("scope", "Actual Android WebView controls and original fixture catalogue; no visible outline-width pixel assertion")
        persistReport("model-viewer-outline-controls-report.json", report)
        println("MODEL_VIEWER_OUTLINE_CONTROLS_REPORT=$report")
    }

    private data class Session(val activity: MainActivity, val webView: WebView, val defaultPanels: JSONObject)

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
            instrumentation.runOnMainSync { NativeTabsQa.tab(launched, MainActivity.TAB_MODEL_VIEWER).select() }
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
            val defaultPanels = evaluate(browser,
                "var pose=document.getElementById('viewer-adjustments'),body=document.getElementById('viewer-body-adjustments'),expression=document.getElementById('viewer-expression-adjustments');" +
                    "if(!pose||!body||!expression||pose.open||!body.open||expression.open||pose.parentNode!==body.parentNode||body.parentNode!==expression.parentNode||" +
                    "!pose.contains(document.getElementById('viewer-motion'))||!pose.contains(document.getElementById('viewer-add-motion'))||body.contains(document.getElementById('viewer-motion'))||" +
                    "!body.contains(document.getElementById('viewer-node-fields'))||pose.contains(document.getElementById('viewer-node-fields')))" +
                    "throw new Error('Pose and expressions must default collapsed, with body open as independent sibling panels and their actual controls');" +
                    "return JSON.stringify({poseOpen:pose.open,bodyOpen:body.open,expressionOpen:expression.open,distinctControlOwners:true});")
            run(browser, "document.getElementById('viewer-expand').click();" +
                "document.querySelector('[data-viewer-view=\"front\"]').click();document.getElementById('viewer-fit').click();" +
                "document.getElementById('viewer-adjustments').open=true;document.getElementById('viewer-body-adjustments').open=true;document.querySelector('.viewer-node-editor').open=true;" +
                "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'end'});")
            waitForDom(browser, "actual neutral rig framebuffer pixels") {
                "var p=ModelViewer.renderProbe(33);return JSON.stringify({ok:p.ready&&p.sourceTriangles===4&&p.triangles>=4&&" +
                    "p.nonBackgroundSamples>=3&&p.chromaticSamples>=3&&p.glError===0,probe:p});"
            }
            assertGameStopped()
            check(Session(launched, browser, defaultPanels))
            assertTrue("All rig, shader and scaling operations must preserve the source bytes", source.readBytes().contentEquals(fixture))
            assertGameStopped()
        } finally {
            webView?.let { runCatching { run(it, "if(window.ViewerQualityQa)ViewerQualityQa.dispose();if(window.ViewerRigQa)ViewerRigQa.dispose();") } }
            instrumentation.runOnMainSync { activity?.finish() }
            source.delete()
            preferences.edit().apply { if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide") }.commit()
        }
    }

    private fun exerciseIndependentPoseAndBodyPanels(session: Session, retained: JSONObject): JSONObject {
        val webView = session.webView
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val initial = evaluate(webView, "return JSON.stringify({poseOpen:document.getElementById('viewer-adjustments').open," +
            "bodyOpen:document.getElementById('viewer-body-adjustments').open,expressionOpen:document.getElementById('viewer-expression-adjustments').open,x:scrollX,y:scrollY,authoring:ModelViewer.getAuthoringState()});")
        val expanded = retained.getJSONObject("layout").getBoolean("expanded")
        val worlds = JSONObject()
        for (name in listOf("Move", "BreastSize", "Tip", "Head", "Neck_Hair")) worlds.put(name, nodeWorld(webView, name))
        fun assertPreserved(): JSONObject {
            val current = state(webView)
            assertRetained(retained, current)
            for (field in listOf("selectedNode", "editorGroup")) assertEquals(retained.getJSONObject("rig").getString(field), current.getJSONObject("rig").getString(field))
            val authoring = evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            assertEquals("Panel toggles must preserve every pending export edit", initial.getJSONObject("authoring").toString(), authoring.toString())
            var cameraDifference = kotlin.math.abs(retained.getJSONObject("camera").getDouble("fov") - current.getJSONObject("camera").getDouble("fov"))
            for (kind in listOf("position", "target")) for (axis in 0..2) cameraDifference = maxOf(cameraDifference,
                kotlin.math.abs(retained.getJSONObject("camera").getJSONArray(kind).getDouble(axis) - current.getJSONObject("camera").getJSONArray(kind).getDouble(axis)))
            assertTrue("Panel toggles must not move the actual camera", cameraDifference <= 1e-7)
            var worldDifference = 0.0
            for (name in listOf("Move", "BreastSize", "Tip", "Head", "Neck_Hair")) {
                val before = worlds.getJSONObject(name).getJSONArray("matrix")
                val after = nodeWorld(webView, name).getJSONArray("matrix")
                assertArrayNear("Panel toggles must preserve the full $name world matrix", before, after)
                for (axis in 0 until before.length()) worldDifference = maxOf(worldDifference, kotlin.math.abs(before.getDouble(axis) - after.getDouble(axis)))
            }
            return JSONObject().put("cameraMaximumDifference", cameraDifference).put("worldMaximumDifference", worldDifference)
                .put("selectedNode", current.getJSONObject("rig").getString("selectedNode")).put("editorGroup", current.getJSONObject("rig").getString("editorGroup"))
                .put("selectedClip", current.getJSONObject("rig").getString("selectedClip")).put("time", current.getJSONObject("rig").getDouble("time"))
                .put("playing", current.getJSONObject("rig").getBoolean("playing")).put("authoringPreserved", true);
        }
        val toggles = JSONArray()
        try {
            if (expanded) click(webView, "viewer-expand")
            run(webView, "['viewer-adjustments','viewer-body-adjustments','viewer-expression-adjustments'].forEach(function(id){document.getElementById(id).open=true;});")
            for (id in listOf("viewer-adjustments", "viewer-body-adjustments")) {
                val closed = evaluate(webView, "var section=document.getElementById(" + JSONObject.quote(id) + "),summary=section.querySelector('summary'),target=ViewerRigQa.control(summary,true);" +
                    "if(!section.open||!target.visible||!target.withinViewport||!target.hittable||target.width<44||target.height<44)throw new Error('The real independent panel summary must be an open visible 44px target');" +
                    "summary.click();var peer=ViewerRigQa.control(section.id==='viewer-adjustments'?'viewer-node':'viewer-motion',true);" +
                    "if(peer.disabled||!peer.visible||!peer.withinViewport||!peer.hittable||peer.width<44||peer.height<44)throw new Error('The other independent panel must retain a real visible 44px control');" +
                    "var style=getComputedStyle(section);return JSON.stringify({id:section.id,open:section.open,target:target,peerControl:peer,height:section.getBoundingClientRect().height,summaryHeight:summary.getBoundingClientRect().height," +
                    "chrome:parseFloat(style.paddingTop)+parseFloat(style.paddingBottom)+parseFloat(style.borderTopWidth)+parseFloat(style.borderBottomWidth)," +
                    "othersOpen:['viewer-adjustments','viewer-body-adjustments','viewer-expression-adjustments'].every(function(other){return other===section.id||document.getElementById(other).open;})});")
                assertFalse("Each top-level panel must collapse independently", closed.getBoolean("open"))
                assertTrue("Closing one panel keeps the other two open", closed.getBoolean("othersOpen"))
                assertEquals("A collapsed panel keeps only its summary and chrome", closed.getDouble("summaryHeight") + closed.getDouble("chrome"), closed.getDouble("height"), 1.0)
                val closedState = assertPreserved()
                instrumentation.runOnMainSync { webView.requestFocus() }
                run(webView, "var summary=document.querySelector('#" + id + " > summary');summary.focus();if(document.activeElement!==summary)throw new Error('The real panel summary must own native keyboard focus');")
                instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_ENTER)
                val reopened = waitForDom(webView, "native Enter reopens $id", 15) {
                    "var section=document.getElementById(" + JSONObject.quote(id) + ");return JSON.stringify({ok:section.open&&section.getBoundingClientRect().height>section.querySelector('summary').getBoundingClientRect().height+40," +
                        "open:section.open,othersOpen:['viewer-adjustments','viewer-body-adjustments','viewer-expression-adjustments'].every(function(other){return other===section.id||document.getElementById(other).open;})});"
                }
                assertTrue("Keyboard reopening keeps the other panels open", reopened.getBoolean("othersOpen"))
                toggles.put(JSONObject().put("id", id).put("closed", closed).put("closedState", closedState).put("nativeEnterReopened", reopened).put("reopenedState", assertPreserved()))
            }
            return JSONObject().put("defaultsBeforeSetup", session.defaultPanels).put("toggles", toggles).put("preservedPausedPoseAndBodyEdits", true)
                .put("scope", "Normal-layout real panel summaries and native Enter input; state/world matrices retained; no cross-layout pixel comparison")
        } finally {
            run(webView, "document.getElementById('viewer-adjustments').open=" + initial.getBoolean("poseOpen") + ";document.getElementById('viewer-body-adjustments').open=" + initial.getBoolean("bodyOpen") +
                ";document.getElementById('viewer-expression-adjustments').open=" + initial.getBoolean("expressionOpen") + ";window.scrollTo(" + initial.getDouble("x") + "," + initial.getDouble("y") + ");")
            if (state(webView).getJSONObject("layout").getBoolean("expanded") != expanded) click(webView, "viewer-expand")
            waitForDom(webView, "the original fixed viewport after independent panels", 30) {
                "var s=ModelViewer.getState();return JSON.stringify({ok:s.layout.expanded===" + expanded + "&&Math.abs(s.layout.stage.width-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("width") +
                    ")<1&&Math.abs(s.layout.stage.height-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("height") + ")<1});"
            }
            assertPreserved()
        }
    }

    private fun exerciseExpressionPanel(session: Session, retained: JSONObject): JSONObject {
        val webView = session.webView
        val initial = evaluate(webView, "var body=document.getElementById('viewer-body-adjustments'),pose=document.getElementById('viewer-adjustments'),expression=document.getElementById('viewer-expression-adjustments')," +
            "panel=document.getElementById('viewer-expression-panel'),advanced=document.getElementById('viewer-expression-advanced');" +
            "if(body.contains(panel)||pose.contains(panel)||!expression.contains(panel)||body.parentNode!==expression.parentNode||pose.parentNode!==body.parentNode)" +
            "throw new Error('Expressions must be a separate sibling panel outside body editing');" +
            "return JSON.stringify({bodyOpen:body.open,poseOpen:pose.open,expressionOpen:expression.open,advancedOpen:advanced.open,x:scrollX,y:scrollY});")
        val originallyExpanded = retained.getJSONObject("layout").getBoolean("expanded")
        assertTrue("The rig fixture uses its existing fixed expanded viewport for pixel comparisons", originallyExpanded)
        try {
            run(webView, "document.getElementById('viewer-body-adjustments').open=false;document.getElementById('viewer-adjustments').open=false;" +
                "document.getElementById('viewer-expression-adjustments').open=true;document.getElementById('viewer-expression-advanced').open=true;")
            val referenceFrame = capture(webView, "separateExpressionBefore")
            input(webView, "viewer-expression-number", "100", "input")
            assertEquals("The expression control must edit the real Unity morph channel", 1.0,
                state(webView).getJSONObject("rig").getJSONArray("expressions").getJSONObject(0).getDouble("weight"), 1e-9)
            val changed = capture(webView, compare = "separateExpressionBefore")
            assertChanged("Expression controls must change real pixels with body editing collapsed", changed)
            input(webView, "viewer-expression-number",
                (retained.getJSONObject("rig").getJSONArray("expressions").getJSONObject(0).getDouble("weight") * 100).toString(), "input")
            val restored = capture(webView, compare = "separateExpressionBefore")
            assertRestored("Restoring the expression must restore the same fixed-viewport framebuffer", restored)
            assertRetained(retained, state(webView))

            click(webView, "viewer-expand")
            waitForDom(webView, "the visible normal-layout expression controls", 30) {
                "return JSON.stringify({ok:!ModelViewer.getState().layout.expanded});"
            }
            val controls = evaluate(webView, "document.getElementById('viewer-body-adjustments').open=false;document.getElementById('viewer-adjustments').open=false;" +
                "document.getElementById('viewer-expression-adjustments').open=true;document.getElementById('viewer-expression-advanced').open=true;" +
                "var controls=['viewer-expression','viewer-expression-number','viewer-expression-reset'].map(function(id){" +
                "var result=ViewerRigQa.control(id,true);if(result.disabled||!result.visible||!result.withinViewport||!result.hittable||result.width<44||result.height<44)" +
                "throw new Error('The separate expression panel must keep its actual 44px touch controls: '+JSON.stringify(result));return result;});" +
                "return JSON.stringify({controls:controls,bodyClosed:!document.getElementById('viewer-body-adjustments').open,poseClosed:!document.getElementById('viewer-adjustments').open,coarse:matchMedia('(pointer:coarse)').matches});")
            assertTrue(controls.getBoolean("bodyClosed")); assertTrue(controls.getBoolean("poseClosed"))
            assertRetained(retained, state(webView))
            input(webView, "viewer-expression-number", "100", "input")
            assertEquals("The visible independent panel must edit the same real Unity morph channel", 1.0,
                state(webView).getJSONObject("rig").getJSONArray("expressions").getJSONObject(0).getDouble("weight"), 1e-9)
            input(webView, "viewer-expression-number",
                (retained.getJSONObject("rig").getJSONArray("expressions").getJSONObject(0).getDouble("weight") * 100).toString(), "input")
            assertRetained(retained, state(webView))
            val closed = evaluate(webView, "var expression=document.getElementById('viewer-expression-adjustments'),summary=expression.querySelector('summary');" +
                "var target=ViewerRigQa.control(summary,true);if(!target.visible||!target.hittable||target.height<44)throw new Error('Expression summary must remain a real 44px touch target');" +
                "summary.click();var style=getComputedStyle(expression);return JSON.stringify({open:expression.open,bodyOpen:document.getElementById('viewer-body-adjustments').open,poseOpen:document.getElementById('viewer-adjustments').open," +
                "sectionHeight:expression.getBoundingClientRect().height,summaryHeight:summary.getBoundingClientRect().height," +
                "chromeHeight:parseFloat(style.paddingTop)+parseFloat(style.paddingBottom)+parseFloat(style.borderTopWidth)+parseFloat(style.borderBottomWidth),summary:target});")
            assertFalse("The expression panel collapses independently", closed.getBoolean("open"))
            assertFalse("Expression toggling must leave body editing collapsed", closed.getBoolean("bodyOpen"))
            assertFalse("Expression toggling must leave pose editing collapsed", closed.getBoolean("poseOpen"))
            // Native details can retain the closed child's last bounding box.
            // Its actual section must shrink exactly to summary plus border/padding.
            assertEquals("Collapsed expressions must occupy only their summary and chrome",
                closed.getDouble("summaryHeight") + closed.getDouble("chromeHeight"), closed.getDouble("sectionHeight"), 1.0)
            assertRetained(retained, state(webView))
            InstrumentationRegistry.getInstrumentation().runOnMainSync { webView.requestFocus() }
            run(webView, "document.querySelector('#viewer-expression-adjustments > summary').focus();")
            InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_ENTER)
            val reopened = waitForDom(webView, "the independently reopened expression panel", 15) {
                "var section=document.getElementById('viewer-expression-adjustments');return JSON.stringify({ok:section.open&&" +
                    "section.getBoundingClientRect().height>section.querySelector('summary').getBoundingClientRect().height+40," +
                    "bodyOpen:document.getElementById('viewer-body-adjustments').open,poseOpen:document.getElementById('viewer-adjustments').open});"
            }
            assertFalse(reopened.getBoolean("bodyOpen")); assertFalse(reopened.getBoolean("poseOpen"))
            val after = state(webView)
            assertRetained(retained, after)
            assertEquals(retained.getJSONObject("rig").getString("selectedNode"), after.getJSONObject("rig").getString("selectedNode"))
            for (kind in listOf("position", "target")) assertArrayNear("Independent expression controls preserve camera $kind",
                retained.getJSONObject("camera").getJSONArray(kind), after.getJSONObject("camera").getJSONArray(kind))
            assertEquals(retained.getJSONObject("camera").getDouble("fov"), after.getJSONObject("camera").getDouble("fov"), 1e-9)
            val normalRendering = waitForDom(webView, "the real renderer after independent panel reopening", 30) {
                "var probe=ModelViewer.renderProbe(33);return JSON.stringify({ok:probe.ready&&probe.glError===0&&probe.nonBackgroundSamples>=3,probe:probe});"
            }
            return JSONObject().put("controls", controls).put("closed", closed).put("keyboardReopened", reopened)
                .put("pixelViewport", "fixed expanded viewport before layout changes").put("referenceFrame", referenceFrame)
                .put("normalRendering", normalRendering)
                .put("actualMorphPixelsChanged", changed).put("restoredPixels", restored).put("bodyAndCameraPreserved", true)
        } finally {
            run(webView, "document.getElementById('viewer-body-adjustments').open=" + initial.getBoolean("bodyOpen") + ";" +
                "document.getElementById('viewer-adjustments').open=" + initial.getBoolean("poseOpen") + ";" +
                "document.getElementById('viewer-expression-adjustments').open=" + initial.getBoolean("expressionOpen") + ";" +
                "document.getElementById('viewer-expression-advanced').open=" + initial.getBoolean("advancedOpen") + ";" +
                "window.scrollTo(" + initial.getDouble("x") + "," + initial.getDouble("y") + ");ViewerRigQa.drop('separateExpressionBefore');")
            if (state(webView).getJSONObject("layout").getBoolean("expanded") != originallyExpanded) click(webView, "viewer-expand")
            waitForDom(webView, "the original viewport after expression-panel checks", 30) {
                "var layout=ModelViewer.getState().layout;return JSON.stringify({ok:layout.expanded===" + originallyExpanded +
                    "&&Math.abs(layout.stage.width-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("width") +
                    ")<1&&Math.abs(layout.stage.height-" + retained.getJSONObject("layout").getJSONObject("stage").getDouble("height") + ")<1});"
            }
        }
    }

    private fun exerciseSectionCollapse(session: Session, retained: JSONObject): JSONArray {
        val originallyExpanded = retained.getJSONObject("layout").getBoolean("expanded")
        val originalGroup = retained.getJSONObject("rig").getString("editorGroup")
        val selectedBone = retained.getJSONObject("rig").getString("selectedNode")
        val results = JSONArray()
        val keyboardDiagnostics = JSONArray()
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
            // Common choices follow the active editing area and effective save methods.
            // Metadata recommendations may differ from explicitly authored methods.
            val shortcutGroup = originalGroup
            selectArea(shortcutGroup)
            val commonSelection = evaluate(session.webView, "var id=" + JSONObject.quote(selectedBone) + ";" +
                "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('Tip'),'change');" +
                "ViewerRigQa.input('viewer-node-search','','input');ViewerRigQa.input('viewer-node-filter','tool','change');" +
                "var select=document.getElementById('viewer-node'),container=document.getElementById('viewer-node-shortcuts');" +
                "if(document.querySelectorAll('#viewer-node').length!==1||select.tagName!=='SELECT'||!container.contains(select)||" +
                "container.querySelector('[data-viewer-bone]'))throw new Error('Common body parts must use one real select without shortcut buttons');" +
                "var options=Array.prototype.filter.call(select.options,function(option){return !!option.value;});" +
                "if(!options.length)throw new Error('The actual compact editing area must offer a common body part');" +
                "var previous=ModelViewer.getState().rig.selectedNode,choice=options.filter(function(option){return option.value!==previous;})[0];" +
                "if(previous!==String(ViewerRigQa.nodeId('Tip'))||!choice)throw new Error('The compact selector must change the retained advanced selection');" +
                "var control=ViewerRigQa.control(select,true);if(!control.visible||!control.withinViewport||!control.hittable||control.width<44||control.height<44)" +
                "throw new Error('The common-part select must be an unobstructed 44px touch target');" +
                "var authoring=JSON.stringify(ModelViewer.getAuthoringState());document.getElementById('viewer-node-editor').open=false;" +
                "select.value=choice.value;select.dispatchEvent(new Event('change',{bubbles:true}));" +
                "if(ModelViewer.getState().rig.selectedNode!==choice.value||!document.getElementById('viewer-node-editor').open)throw new Error('Selecting a common part must open its actual editor');" +
                "ViewerRigQa.input('viewer-node',id,'change');" +
                "if(JSON.stringify(ModelViewer.getAuthoringState())!==authoring)throw new Error('Choosing body parts must preserve existing authored edits');" +
                "return JSON.stringify({singleSelect:true,control:control,optionCount:options.length,previous:previous,chosen:choice.value,distinctChoice:choice.value!==previous,restored:id,coarse:matchMedia('(pointer:coarse)').matches});")
            assertRetained(retained, state(session.webView))
            assertEquals(selectedBone, state(session.webView).getJSONObject("rig").getString("selectedNode"))
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
                        "summary.scrollIntoView({block:'center'});summary.click();summary.scrollIntoView({block:'center'});" +
                        "var box=summary.getBoundingClientRect(),hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2)," +
                        "coarse=matchMedia('(pointer:coarse)').matches,fine=matchMedia('(pointer:fine)').matches;" +
                        "return JSON.stringify({id:card.id,open:card.open,summaryHeight:box.height,summaryWidth:box.width," +
                        "coarse:coarse,pointer:coarse?'coarse':fine?'fine':'none',minimumTarget:coarse?44:34," +
                        "hittable:hit===summary||summary.contains(hit),withinViewport:box.left>=0&&box.top>=0&&box.right<=innerWidth+1&&box.bottom<=innerHeight+1," +
                        "contentHeight:content.getBoundingClientRect().height,states:['viewer-common-adjustments','viewer-breast-card','viewer-skirt-card'].map(function(id){return {id:id,open:document.getElementById(id).open};})});")
                assertFalse("Native details must hide its controls when collapsed", closed.getBoolean("open"))
                assertEquals("Collapsed content must occupy no space on the native WebView", 0.0, closed.getDouble("contentHeight"), 1e-6)
                val minimumTarget = if (closed.getBoolean("coarse")) 44.0 else 34.0
                assertTrue("A collapsed section must meet its actual pointer target policy: $closed",
                    closed.getDouble("summaryHeight") + 1e-6 >= minimumTarget && closed.getDouble("summaryWidth") + 1e-6 >= minimumTarget)
                assertTrue("A collapsed section must remain visible and hittable: $closed",
                    closed.getBoolean("hittable") && closed.getBoolean("withinViewport"))
                val sectionStates = closed.getJSONArray("states")
                for (index in 0 until sectionStates.length()) {
                    val section = sectionStates.getJSONObject(index)
                    assertEquals("Each section must collapse independently", section.getString("id") != id, section.getBoolean("open"))
                }
                assertRetained(retained, state(session.webView))
                assertEquals("Collapsing preserves the shortcut-selected bone", retained.getJSONObject("rig").getString("selectedNode"), state(session.webView).getJSONObject("rig").getString("selectedNode"))
                val opened = reopenDetailsWithNativeEnter(session, id, content, keyboardDiagnostics)
                val current = state(session.webView)
                assertRetained(retained, current)
                assertEquals("Keyboard reopening preserves the shortcut-selected bone", retained.getJSONObject("rig").getString("selectedNode"), current.getJSONObject("rig").getString("selectedNode"))
                for (kind in listOf("position", "target")) assertArrayNear("Section toggling preserves camera $kind",
                    retained.getJSONObject("camera").getJSONArray(kind), current.getJSONObject("camera").getJSONArray(kind))
                assertEquals(retained.getJSONObject("camera").getDouble("fov"), current.getJSONObject("camera").getDouble("fov"), 1e-9)
                val result = JSONObject().put("id", id).put("editingArea", sectionGroup).put("closed", closed).put("keyboardReopened", opened)
                if (id == "viewer-common-adjustments") result.put("commonSelection", commonSelection)
                results.put(result)
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

    private fun keyboardNativeState(session: Session): JSONObject {
        val observed = AtomicReference<JSONObject>()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val activity = session.activity
            val webView = session.webView
            var focused: View? = activity.currentFocus
            var focusInside = false
            while (focused != null) {
                if (focused === webView) { focusInside = true; break }
                focused = focused.parent as? View
            }
            observed.set(JSONObject().put("resumed", activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
                .put("windowHasFocus", activity.hasWindowFocus()).put("webWindowHasFocus", webView.hasWindowFocus())
                .put("attached", webView.isAttachedToWindow).put("shown", webView.isShown)
                .put("webHasFocus", webView.hasFocus()).put("webIsFocused", webView.isFocused)
                .put("currentFocusInsideWebView", focusInside)
                .put("focusClass", activity.currentFocus?.javaClass?.name ?: "none")
                .put("imeVisible", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
                    webView.rootWindowInsets?.isVisible(android.view.WindowInsets.Type.ime()) ?: JSONObject.NULL else JSONObject.NULL))
        }
        return observed.get()
    }

    /** Observe the genuine input channel before one hardware Enter. Passive
     * observers record delivery/default handling without activating a control. */
    private fun reopenDetailsWithNativeEnter(session: Session, id: String, content: String,
                                              attempts: JSONArray): JSONObject {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val webView = session.webView
        val target = JSONObject.quote(id)
        val selector = JSONObject.quote(content)
        val key = JSONObject.quote(System.nanoTime().toString())
        val report = JSONObject().put("id", id).put("status", "WAITING_FOR_FOCUS").put("hardwareEnterCalls", 0)
            .put("nativeBefore", keyboardNativeState(session))
        attempts.put(report)
        fun persist() = persistReport("model-viewer-section-keyboard.json", JSONObject().put("attempts", attempts))
        try {
            instrumentation.runOnMainSync { webView.requestFocus() }
            run(webView, """
                if(window.__nativeDetailsKeyboard)window.__nativeDetailsKeyboard.dispose();
                var card=document.getElementById($target),summary=card.querySelector('summary'),events=[];
                function identity(node){return node?{tag:node.tagName||'',id:node.id||'',parent:node.parentElement&&node.parentElement.id||''}:null;}
                function observe(event){
                  var enter=(event.key==='Enter'||event.keyCode===13),isKey=event.type==='keydown'||event.type==='keyup';
                  if(isKey&&!enter||event.type==='click'&&event.target!==summary&&!summary.contains(event.target)||event.type==='toggle'&&event.target!==card)return;
                  var record={type:event.type,key:event.key||'',code:event.code||'',keyCode:event.keyCode||0,repeat:!!event.repeat,
                    isTrusted:event.isTrusted,target:identity(event.target),summaryTarget:event.target===summary||summary.contains(event.target),
                    documentFocused:document.hasFocus(),active:identity(document.activeElement),defaultPreventedAtCapture:event.defaultPrevented,
                    cardOpenAtCapture:card.open,timeStamp:event.timeStamp};
                  if(events.length<64)events.push(record);
                  setTimeout(function(){record.defaultPreventedAfterDispatch=event.defaultPrevented;record.afterDispatch=true;
                    record.cardOpenAfterDispatch=card.open;record.activeAfterDispatch=identity(document.activeElement);},0);
                }
                var types=['keydown','keyup','click','toggle','focusin','focusout'];
                types.forEach(function(type){document.addEventListener(type,observe,{capture:true,passive:true});});
                window.__nativeDetailsKeyboard={key:$key,proof:null,dispose:function(){types.forEach(function(type){document.removeEventListener(type,observe,true);});},
                  snapshot:function(){var box=summary.getBoundingClientRect(),hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2),
                    coarse=matchMedia('(pointer:coarse)').matches,fine=matchMedia('(pointer:fine)').matches;
                    return {id:card.id,open:card.open,contentHeight:card.querySelector($selector).getBoundingClientRect().height,
                      documentFocused:document.hasFocus(),summaryActive:document.activeElement===summary,connected:card.isConnected&&summary.isConnected,
                      hitSummary:hit===summary||summary.contains(hit),withinViewport:box.left>=0&&box.top>=0&&box.right<=innerWidth+1&&box.bottom<=innerHeight+1,
                      coarse:coarse,pointer:coarse?'coarse':fine?'fine':'none',minimumTarget:coarse?44:34,
                      width:box.width,height:box.height,active:identity(document.activeElement),events:events.slice()};}};
                summary.scrollIntoView({block:'center'});summary.focus();
                """.trimIndent())
            val ready = waitForDom(webView, "native and DOM keyboard focus for $id in two observations", 15) {
                val native = keyboardNativeState(session)
                """
                var observer=window.__nativeDetailsKeyboard,dom=observer.snapshot(),native=$native;
                var coherent=!!(native.resumed&&native.windowHasFocus&&native.webWindowHasFocus&&native.attached&&native.shown&&
                  native.webHasFocus&&(native.webIsFocused||native.currentFocusInsideWebView)&&
                  dom.documentFocused&&dom.summaryActive&&dom.connected&&dom.hitSummary&&dom.withinViewport&&dom.width+1e-6>=dom.minimumTarget&&dom.height+1e-6>=dom.minimumTarget&&!dom.open);
                var geometry=JSON.stringify({native:native,active:dom.active,pointer:dom.pointer,minimumTarget:dom.minimumTarget,width:dom.width,height:dom.height}),prior=observer.proof;
                observer.proof=coherent?geometry:null;
                return JSON.stringify({ok:!!(coherent&&prior===geometry),coherent:coherent,native:native,dom:dom});
                """.trimIndent()
            }
            report.put("focusReady", ready).put("status", "ONE_HARDWARE_ENTER").put("hardwareEnterCalls", 1)
            persist()
            instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_ENTER)
            val opened = waitForDom(webView, "one trusted hardware Enter reopening $id", 15) {
                val native = keyboardNativeState(session)
                """
                var dom=window.__nativeDetailsKeyboard.snapshot(),keys=dom.events.filter(function(e){return e.type==='keydown'||e.type==='keyup';});
                var down=keys.filter(function(e){return e.type==='keydown';}),up=keys.filter(function(e){return e.type==='keyup';});
                var delivered=down.length===1&&up.length===1&&keys[0].type==='keydown'&&keys[1].type==='keyup'&&keys.every(function(e){
                  return e.summaryTarget&&e.isTrusted&&!e.repeat&&e.documentFocused&&e.afterDispatch&&e.defaultPreventedAfterDispatch===false;});
                return JSON.stringify({ok:dom.open&&dom.contentHeight>0&&delivered,open:dom.open,delivered:delivered,dom:dom,native:$native});
                """.trimIndent()
            }
            report.put("status", "PASS").put("opened", opened)
            persist()
            return opened
        } catch (failure: AssertionError) {
            val dom = runCatching { evaluate(webView, "return JSON.stringify(window.__nativeDetailsKeyboard?window.__nativeDetailsKeyboard.snapshot():{observerMissing:true});") }
                .getOrElse { JSONObject().put("observerUnavailable", true) }
            report.put("status", "FAIL").put("domAtFailure", dom).put("nativeAtFailure", keyboardNativeState(session))
            persist()
            throw failure
        } finally {
            runCatching { run(webView, "if(window.__nativeDetailsKeyboard)window.__nativeDetailsKeyboard.dispose();") }
        }
    }

    private fun exerciseModelMinimize(session: Session): JSONObject {
        val webView = session.webView
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val original = state(webView)
        val expanded = original.getJSONObject("layout").getBoolean("expanded")
        val stage = original.getJSONObject("layout").getJSONObject("stage")
        if (!original.getJSONObject("rig").getJSONObject("savedNodes").getBoolean("enabled")) click(webView, "viewer-saved-nodes")
        input(webView, "viewer-motion", "Neutral swing", "change")
        input(webView, "viewer-time", ".6")
        input(webView, "viewer-breast-preset", "rin", "change")
        input(webView, "viewer-expression-value", "40")
        boneInput(webView, "Head", "rotation", "Z", 35)
        input(webView, "viewer-save-method", "node", "change")
        // Prepare non-default actual details state without changing the hidden
        // expanded viewport. Earlier phases verify real summary interaction.
        run(webView, "document.getElementById('viewer-adjustments').open=false;document.getElementById('viewer-breast-card').open=false;" + minimizeQaScript)
        val beforeState = state(webView)
        val before = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.snapshot());")
        assertFalse(before.getJSONObject("manualFolds").getBoolean("viewer-adjustments"))
        assertFalse(before.getJSONObject("manualFolds").getBoolean("viewer-breast-card"))
        assertTrue("Minimize must retain genuine pending edits", before.getJSONObject("authoring").getJSONArray("edits").length() > 0)
        fun assertPreserved(observed: JSONObject) {
            assertRetained(beforeState, state(webView))
            for (key in listOf("authoring", "manualFolds", "panePreferences")) {
                assertEquals("Minimize/restore preserves $key", before.getJSONObject(key).toString(), observed.getJSONObject(key).toString())
            }
            for (key in listOf("modelId", "selectedNode", "editorGroup")) assertEquals(before.getString(key), observed.getString(key))
            for (key in listOf("position", "target")) {
                val left = before.getJSONObject("camera").getJSONArray(key)
                val right = observed.getJSONObject("camera").getJSONArray(key)
                for (axis in 0..2) assertEquals("Minimize must not refit the camera", left.getDouble(axis), right.getDouble(axis), 1e-7)
            }
            assertEquals(before.getJSONObject("camera").getDouble("fov"), observed.getJSONObject("camera").getDouble("fov"), 1e-7)
        }
        val button = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.minimize());")
        waitForDom(webView, "the loaded model minimized coherently from the expanded phone viewport", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.loaded&&!s.loading&&s.layout.minimized&&" +
                "s.layout.minimizeDirection==='height'&&!s.layout.expanded&&s.layout.fullscreen==='none'&&!s.layout.fullscreenPending,state:s});"
        }
        val hidden = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.snapshot());")
        assertTrue("Minimize must hide the real model stage", hidden.getBoolean("stageHidden"))
        assertPreserved(hidden)
        instrumentation.runOnMainSync { webView.requestFocus() }
        val restore = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.focusRestore());")
        assertTrue("The real external restore bar must receive native keyboard focus", restore.getBoolean("focused"))
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_ENTER)
        waitForDom(webView, "native Enter restoring the same loaded model", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.loaded&&!s.loading&&!s.layout.minimized&&" +
                "s.layout.fullscreen==='none'&&!s.layout.fullscreenPending,state:s});"
        }
        val restored = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.snapshot());")
        assertFalse(restored.getBoolean("stageHidden"))
        assertPreserved(restored)
        val rendered = waitForDom(webView, "actual restored model rendering without a reload or refit", 30) {
            "var p=ModelViewer.renderProbe(33);return JSON.stringify({ok:p.ready&&p.glError===0&&p.nonBackgroundSamples>=3,probe:p});"
        }
        if (state(webView).getJSONObject("layout").getBoolean("expanded") != expanded) click(webView, "viewer-expand")
        waitForDom(webView, "the original expanded geometry after minimize", 30) {
            "var s=ModelViewer.getState(),r=s.layout.stage;return JSON.stringify({ok:s.layout.expanded===" + expanded +
                "&&!s.layout.minimized&&Math.abs(r.width-" + stage.getDouble("width") + ")<1&&Math.abs(r.height-" + stage.getDouble("height") + ")<1,state:s});"
        }
        val final = evaluate(webView, "return JSON.stringify(ViewerMinimizeNativeQa.snapshot());")
        assertPreserved(final)
        assertGameStopped()
        return JSONObject().put("button", button).put("before", before).put("minimized", hidden)
            .put("restoreBar", restore).put("nativeEnterRestored", true).put("restored", restored)
            .put("rendered", rendered.getJSONObject("probe")).put("originalExpandedGeometryRestored", true)
            .put("final", final).put("scope", "After all original pixel thresholds; real minimize target/native Enter restore; no cross-layout pixel comparison")
    }

    private val minimizeQaScript = """
        window.ViewerMinimizeNativeQa = (function () {
          function target(id, minimum) {
            var element = document.getElementById(id), control = ViewerRigQa.control(element, true);
            if (control.disabled || !control.visible || !control.withinViewport || !control.hittable || control.width < minimum || control.height < minimum)
              throw new Error('The real minimize/restore target must remain reachable: ' + JSON.stringify(control));
            return control;
          }
          return {
            snapshot: function () {
              var s = ModelViewer.getState(), stage = document.getElementById('viewer-stage'), rect = stage.getBoundingClientRect(), folds = {};
              ['viewer-adjustments','viewer-body-adjustments','viewer-expression-adjustments','viewer-breast-card','viewer-hips-card','viewer-skirt-card','viewer-common-adjustments','viewer-node-editor'].forEach(function (id) {
                folds[id] = document.getElementById(id).open;
              });
              return { modelId: s.modelId, camera: s.camera, authoring: ModelViewer.getAuthoringState(), selectedNode: s.rig.selectedNode,
                editorGroup: s.rig.editorGroup, manualFolds: folds, layout: s.layout,
                stageHidden: stage.getAttribute('aria-hidden') === 'true' && (!rect.width || !rect.height || getComputedStyle(stage).display === 'none'),
                panePreferences: { files: localStorage.getItem('elichika.viewer.files-width.v1'), panel: localStorage.getItem('elichika.viewer.panel-width.v1') } };
            },
            minimize: function () { var control = target('viewer-minimize', 32); document.getElementById('viewer-minimize').click(); return control; },
            focusRestore: function () {
              var control = target('viewer-model-restore', 44), element = document.getElementById('viewer-model-restore');
              element.focus(); control.focused = document.activeElement === element; return control;
            }
          };
        })();
    """.trimIndent()

    private fun assertVerticalHud(webView: WebView, includeGeometry: Boolean = false): JSONObject {
        val observed = evaluate(webView, "return JSON.stringify(ViewerRigQa.verticalViewport($includeGeometry));")
        assertTrue("The APK must use the reviewed visible vertical controls", observed.getBoolean("vertical"))
        val controls = observed.getJSONArray("controls")
        assertEquals("Retain every viewport HUD action including minimize", 12, controls.length())
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
            assertEquals("Fullscreen Back must stay on the model viewer tab", normalNative.getInt("selectedTab"), current.getInt("selectedTab"))
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
            instrumentation.runOnMainSync { NativeTabsQa.tab(activity, MainActivity.TAB_MODEL_VIEWER).select() }
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

    private fun presentation(webView: WebView): JSONObject = evaluate(webView,
        "var s=ModelViewer.getState(),tab=document.getElementById('tab-viewer');return JSON.stringify({layout:s.layout," +
            "classes:tab.className,expandedClass:tab.classList.contains('viewer-expanded'),fullscreenClass:tab.classList.contains('viewer-fullscreen')," +
            "section:ElichikaNavigation.currentSection()});")

    private fun selectNativeAssetSection(session: Session, id: String, section: String) {
        val expectedIndex = AtomicReference<Int>()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val tab = NativeTabsQa.tab(session.activity, id)
            expectedIndex.set(tab.position)
            tab.select()
        }
        waitForDom(session.webView, "the native $section tab and its shared document acknowledgement", 30) {
            val native = nativeViewport(session)
            "var s=ModelViewer.getState(),native=$native;return JSON.stringify({ok:native.selectedTab===${expectedIndex.get()}&&" +
                "native.webViewAttached&&ElichikaNavigation.currentSection()===${JSONObject.quote(section)}&&" +
                "s.visible===${section == "viewer"}" + (if (section == "viewer") "&&s.loaded&&!s.loading" else "") +
                ",native:native,presentation:{layout:s.layout,classes:document.getElementById('tab-viewer').className}});"
        }
    }

    /** Native navigation intentionally exits presentation modes. Re-enter only
     * the recorded mode through its real controls after both tabs acknowledge. */
    private fun restorePresentation(webView: WebView, reference: JSONObject): JSONObject {
        val before = presentation(webView)
        val expected = reference.getJSONObject("layout")
        val mode = expected.getString("fullscreen")
        assertTrue("The native reference must use an observed supported fullscreen mode", mode in setOf("none", "native"))
        assertFalse("A reference must not contain an unsettled fullscreen command", expected.getBoolean("fullscreenPending"))
        val actions = JSONArray()
        persistReport("model-viewer-rig-resume-geometry.json", JSONObject().put("status", "RESTORING_PRESENTATION")
            .put("referencePresentation", reference).put("afterNativeAcknowledgement", before))
        fun waitMode(value: String) = waitForDom(webView, "the recorded fullscreen presentation $value", 30) {
            "var s=ModelViewer.getState();return JSON.stringify({ok:s.layout.fullscreen===${JSONObject.quote(value)}&&" +
                "!s.layout.fullscreenPending&&s.visible&&s.loaded&&!s.loading,layout:s.layout});"
        }
        val currentMode = before.getJSONObject("layout").getString("fullscreen")
        waitMode(currentMode)
        if (currentMode != mode) {
            if (currentMode != "none") { click(webView, "viewer-fullscreen"); actions.put("exit-fullscreen"); waitMode("none") }
            if (mode != "none") { click(webView, "viewer-fullscreen"); actions.put("enter-" + mode); waitMode(mode) }
        }
        if (state(webView).getJSONObject("layout").getBoolean("expanded") != expected.getBoolean("expanded")) {
            click(webView, "viewer-expand")
            actions.put("expanded=" + expected.getBoolean("expanded"))
        }
        waitForDom(webView, "the original observed presentation after native navigation", 30) {
            "var p=" + presentationScript + ",expected=$expected;return JSON.stringify({ok:" +
                "p.section==='viewer'&&p.layout.fullscreen===expected.fullscreen&&!p.layout.fullscreenPending&&" +
                "p.layout.expanded===expected.expanded&&p.expandedClass===expected.expanded,presentation:p});"
        }
        return JSONObject().put("reference", reference).put("afterNativeAcknowledgement", before)
            .put("actions", actions).put("restored", presentation(webView))
    }

    private val presentationScript = "(function(){var s=ModelViewer.getState(),tab=document.getElementById('tab-viewer');" +
        "return {layout:s.layout,classes:tab.className,expandedClass:tab.classList.contains('viewer-expanded')," +
        "fullscreenClass:tab.classList.contains('viewer-fullscreen'),section:ElichikaNavigation.currentSection()};})()"

    /** A visible/loaded scene may still have a queued resize from section
     * activation. Require the original exact pixel and CSS geometry before
     * comparing the original frame; never replace its pixels or camera. */
    private fun waitForRetainedFramebuffer(session: Session, reference: JSONObject,
                                           quality: JSONObject, native: JSONObject, presentation: JSONObject): JSONObject {
        val expected = JSONObject().put("width", reference.getInt("width")).put("height", reference.getInt("height"))
            .put("cssWidth", quality.getDouble("cssWidth")).put("cssHeight", quality.getDouble("cssHeight"))
            .put("nativePixelRatio", quality.getDouble("nativePixelRatio"))
            .put("webViewWidth", native.getInt("webViewWidth")).put("webViewHeight", native.getInt("webViewHeight"))
            .put("orientation", native.getInt("orientation")).put("selectedTab", native.getInt("selectedTab"))
            .put("presentation", presentation)
        val key = JSONObject.quote(System.nanoTime().toString())
        try {
            val observation = waitForDom(session.webView, "the original HQ framebuffer and native viewport in two coherent observations", 30) {
                val currentNative = nativeViewport(session)
                """
                var s=ModelViewer.getState(),q=s.quality,stage=document.getElementById('viewer-stage'),canvas=document.getElementById('viewer-canvas');
                var gl=canvas.getContext('webgl2')||canvas.getContext('webgl')||canvas.getContext('experimental-webgl');
                var expected=$expected,native=$currentNative,box=stage.getBoundingClientRect();
                var actual={cssWidth:stage.clientWidth,cssHeight:stage.clientHeight,stageLeft:box.left,stageTop:box.top,
                  canvasWidth:canvas.width,canvasHeight:canvas.height,drawingWidth:gl&&gl.drawingBufferWidth,drawingHeight:gl&&gl.drawingBufferHeight,
                  qualityWidth:q&&q.width,qualityHeight:q&&q.height,qualityCssWidth:q&&q.cssWidth,qualityCssHeight:q&&q.cssHeight,
                  nativePixelRatio:devicePixelRatio,qualityNativePixelRatio:q&&q.nativePixelRatio,viewportWidth:innerWidth,viewportHeight:innerHeight,
                  webViewWidth:native.webViewWidth,webViewHeight:native.webViewHeight,orientation:native.orientation,selectedTab:native.selectedTab,
                  expanded:s.layout.expanded,fullscreen:s.layout.fullscreen,fullscreenPending:s.layout.fullscreenPending,
                  classes:document.getElementById('tab-viewer').className,section:ElichikaNavigation.currentSection()};
                var coherent=!!(s.visible&&s.loaded&&!s.loading&&!s.contextLost&&q&&q.ready&&q.enabled&&gl&&native.webViewAttached&&
                  actual.cssWidth===expected.cssWidth&&actual.cssHeight===expected.cssHeight&&
                  actual.qualityCssWidth===actual.cssWidth&&actual.qualityCssHeight===actual.cssHeight&&
                  actual.canvasWidth===expected.width&&actual.canvasHeight===expected.height&&
                  actual.drawingWidth===expected.width&&actual.drawingHeight===expected.height&&
                  actual.qualityWidth===expected.width&&actual.qualityHeight===expected.height&&
                  actual.nativePixelRatio===expected.nativePixelRatio&&actual.qualityNativePixelRatio===expected.nativePixelRatio&&
                  actual.webViewWidth===expected.webViewWidth&&actual.webViewHeight===expected.webViewHeight&&
                  actual.orientation===expected.orientation&&actual.selectedTab===expected.selectedTab&&
                  actual.expanded===expected.presentation.reference.layout.expanded&&
                  actual.fullscreen===expected.presentation.reference.layout.fullscreen&&!actual.fullscreenPending&&actual.section==='viewer');
                var geometry=JSON.stringify(actual),prior=window.__nativeRigResumeGeometry;
                var report={ok:!!(coherent&&prior&&prior.key===$key&&prior.geometry===geometry),coherent:coherent,
                  expected:expected,actual:actual,scope:'Readiness only; the original strict framebuffer and camera oracle follows'};
                window.__nativeRigResumeGeometry={key:$key,geometry:coherent?geometry:null,report:report};
                return JSON.stringify(report);
                """.trimIndent()
            }
            persistReport("model-viewer-rig-resume-geometry.json", observation)
            return observation
        } catch (failure: AssertionError) {
            val last = evaluate(session.webView, "return JSON.stringify(window.__nativeRigResumeGeometry&&window.__nativeRigResumeGeometry.report||{ok:false,expected:$expected});")
            persistReport("model-viewer-rig-resume-geometry.json", last)
            throw failure
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
            run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('BreastSize'),'change');")
            input(webView, "viewer-save-method", "node", "change")
            val nodeCompensationBlocked = evaluate(webView,
                "return JSON.stringify({disabled:document.getElementById('bone-compensate-children').disabled," +
                    "method:ModelViewer.getState().rig.editingMethods[ViewerRigQa.nodeId('BreastSize')]});")
            assertEquals("Node restriction requires an explicit Node save method", "node", nodeCompensationBlocked.getString("method"))
            assertTrue("Node export does not currently support child compensation", nodeCompensationBlocked.getBoolean("disabled"))
            input(webView, "viewer-save-method", "mesh", "change")
            assertFalse("Explicit Mesh Baker export enables supported child compensation", evaluate(webView,
                "return JSON.stringify({disabled:document.getElementById('bone-compensate-children').disabled});").getBoolean("disabled"))
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
