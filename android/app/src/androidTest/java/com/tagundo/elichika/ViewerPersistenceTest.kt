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
import java.io.ByteArrayInputStream
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.zip.ZipInputStream

/** Real embedded Python, serialized Unity output and native WebGL; original neutral geometry only. */
@RunWith(AndroidJUnit4::class)
class ViewerPersistenceTest {
    @Test
    fun mixedNodeAndMeshEditsSaveReloadAndRebuildWithoutAccumulating() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val neutralBytes = instrumentation.context.assets.open("viewer_persistence.unity").use { it.readBytes() }
        val bytes = instrumentation.context.assets.open("viewer_persistence_fractional.zip").use { it.readBytes() }
        val source = File(context.filesDir, "viewer-persistence-qa-${System.nanoTime()}.zip")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        var activity: MainActivity? = null
        var browser: WebView? = null
        try {
            grantPermissions(context)
            assertGameStopped()
            File(context.cacheDir, "viewer-persistence-report.json").delete()
            File(context.cacheDir, "viewer-persistence.png").delete()
            assertEquals("The APK must package the audited original neutral persistence fixture",
                "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1", sha256(neutralBytes))
            assertEquals("Use the fixed separate synthetic fractional ZIP without altering the original Unity fixture",
                "ed4eab70d111789b90abe2cab1fadf7640afb9610b96c613f5b87ff256275611", sha256(bytes))
            val member = ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
                assertEquals("분수 의상.unity", zip.nextEntry.name)
                val content = zip.readBytes()
                assertTrue("The ZIP must contain only its audited neutral Unity model", zip.nextEntry == null)
                content
            }
            assertEquals("The fractional position/rotation must come from the serialized Unity member",
                "d468e330e747001096092e33d8bc8e9191096d5c66b9f5723b9f76792e4c23b3", sha256(member))
            source.writeBytes(bytes)
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ) as MainActivity
            activity = launched
            instrumentation.runOnMainSync { launched.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select() }
            val webView = waitForWebView(launched)
            browser = webView
            waitForDom(webView, "the packaged persistent editing UI") {
                "return JSON.stringify({ok:typeof openModelViewer==='function'&&!!window.THREE&&" +
                    "!!window.ModelViewer&&typeof ModelViewer.getAuthoringState==='function'&&" +
                    "typeof ModelViewer.restoreAuthoringState==='function'&&" +
                    "!!document.getElementById('viewer-save')});"
            }
            val helper = instrumentation.context.assets.open("viewer_rig_qa.js").bufferedReader().use { it.readText() }
            run(webView, helper)
            run(webView, "if(document.getElementById('viewer-auto-face').checked)document.getElementById('viewer-auto-face').click();")
            open(webView, source.absolutePath)
            val sourceThigh = thighTransform(webView)
            val baseline = vertices(webView)
            assertBoneScale(webView, "LeftUpLeg", doubleArrayOf(1.3, .9, 1.0))

            // The real neutral clip writes the thigh scale. Authoring and
            // animation-order checks must visibly expose that difference.
            input(webView, "viewer-motion", "Neutral MV scale override")
            input(webView, "viewer-edit-evaluation", "animation")
            waitForBoneScale(webView, "LeftUpLeg", doubleArrayOf(1.0, 1.0, 1.0))
            input(webView, "viewer-edit-evaluation", "authoring")
            waitForBoneScale(webView, "LeftUpLeg", doubleArrayOf(1.3, .9, 1.0))
            input(webView, "viewer-motion", "")
            run(webView, "document.getElementById('viewer-body-adjustments').open=true;document.getElementById('viewer-node-editor').open=true;")

            clickVisible(webView, "viewer-editor-mesh-tab")
            assertEditorGroup(webView, "mesh")
            boneInput(webView, "LeftUpLeg", "scale", "Y", 1.234567)
            input(webView, "viewer-save-method", "mesh")
            val meshEdit = evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());").getJSONArray("edits")
            assertEquals(1, meshEdit.length())
            clickVisible(webView, "viewer-editor-node-tab")
            assertEditorGroup(webView, "node")
            assertEquals("Switching editing areas must not change the existing mesh edit", meshEdit.toString(),
                evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());").getJSONArray("edits").toString())
            boneInput(webView, "BreastSize", "scale", "Z", 1.15)
            input(webView, "viewer-save-method", "node")
            val authoring = evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            assertEquals("Exactly the edited body nodes must be exported", 2, authoring.getJSONArray("edits").length())
            val methods = (0 until authoring.getJSONArray("edits").length()).map {
                authoring.getJSONArray("edits").getJSONObject(it).getString("method")
            }.toSet()
            assertEquals("The native flow must exercise both persistent backends", setOf("mesh", "node"), methods)
            clickVisible(webView, "viewer-editor-mesh-tab")
            run(webView, "ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('LeftUpLeg'),'change');")
            val fractionalValidation = fractionalSaveState(webView)
            val intended = vertices(webView)
            assertTrue("Body editing must change the application's actual deformed skin", maxDifference(baseline, intended) > .01)

            // An animated pose is a viewing choice, not an extra saved body edit.
            input(webView, "viewer-motion", "Neutral MV scale override")
            input(webView, "viewer-time", ".75", "input")
            val whileAnimated = evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            assertEquals("Animation and playhead must not contaminate persistent edits",
                authoring.getJSONArray("edits").toString(), whileAnimated.getJSONArray("edits").toString())
            input(webView, "viewer-motion", "")

            val first = save(webView)
            val outputFiles = checkOutputs(first, source)
            val recipeFile = File(first.getString("recipePath"))
            val recipe = JSONObject(recipeFile.readText())
            assertTrue("The server must write a nonempty portable recipe", recipe.length() > 0)
            assertTrue("Saving must preserve the source bundle byte for byte", source.readBytes().contentEquals(bytes))
            openSaved(webView, first)
            val savedThigh = thighTransform(webView)
            assertThighTransformPreserved(sourceThigh, savedThigh)
            val reloaded = vertices(webView)
            assertTrue("The serialized output must reproduce the intended deformed skin",
                maxDifference(intended, reloaded) < 2e-5)
            assertBoneScale(webView, "BreastSize", doubleArrayOf(1.0, 1.0, 1.15))
            assertEquals("A freshly opened output must not retain unsaved edits", 0,
                evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());").getJSONArray("edits").length())

            // First use the product's re-edit action to open its preserved
            // original and restore the edits, rather than rebaking the output.
            val previous = evaluate(webView, "return JSON.stringify({id:ModelViewer.getState().modelId});").getString("id")
            clickVisible(webView, "viewer-reedit-original")
            waitForNewModel(webView, previous, first.getJSONArray("originalPaths"))
            waitForDom(webView, "the preserved original and its restored editor values") {
                "var s=ModelViewer.getState(),a=ModelViewer.getAuthoringState(),p=s.persistence;" +
                    "return JSON.stringify({ok:!p.busy&&p.status==='restored'&&a.edits.length===2,error:p.error||'',state:s});"
            }
            // Also read the portable recipe from disk and restore it through
            // the real API, after clearing the editor. This checks the saved
            // file rather than only the previous response kept by the UI.
            clickVisible(webView, "viewer-preview-reset")
            assertEquals(0, evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());").getJSONArray("edits").length())
            restore(webView, recipe)
            val restored = evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            assertEquals("Portable recipe restore must recover the original absolute edits",
                authoring.getJSONArray("edits").toString(), restored.getJSONArray("edits").toString())
            val second = save(webView)
            checkOutputs(second, source)
            assertFalse("Every export must publish a new output rather than overwrite a prior result",
                first.getJSONArray("previewPaths").toString() == second.getJSONArray("previewPaths").toString())
            openSaved(webView, second)
            assertThighTransformPreserved(sourceThigh, thighTransform(webView))
            val rebuilt = vertices(webView)
            assertTrue("Rebuilding from the original must not accumulate another mesh transform",
                maxDifference(reloaded, rebuilt) < 2e-5)
            assertTrue("Repeated save and restore must preserve the original source", source.readBytes().contentEquals(bytes))
            assertTrue("The first completed output must remain available", outputFiles.all { it.isFile && it.length() > 0 })
            assertGameStopped()
            val modPackage = saveNamedModPackage(context, webView, second, authoring, source, bytes, intended, sourceThigh)
            val report = JSONObject().put("sourceSha256", sha256(bytes)).put("sourcePreserved", true)
                .put("originalNeutralFixtureSha256", sha256(neutralBytes)).put("unityMemberSha256", sha256(member))
                .put("fractionalZipValidation", fractionalValidation).put("sourceThighTransform", sourceThigh)
                .put("savedThighTransform", savedThigh).put("originalPositionAndRotationPreserved", true)
                .put("firstExport", first).put("secondExport", second).put("recipeRestored", true)
                .put("nodeAndMeshBackends", true).put("noAccumulation", true)
                .put("separateEditingAreas", true).put("switchingAreasPreservesEdits", true)
                .put("animationOrderComparison", true).put("animatedPoseExcludedFromExport", true)
                .put("baselineVertices", baseline).put("intendedVertices", intended)
                .put("reloadedVertices", reloaded).put("rebuiltVertices", rebuilt)
                .put("namedInstallerModPackage", modPackage)
                .put("gameServerRemainedStopped", true)
            File(context.cacheDir, "viewer-persistence-report.json").writeText(report.toString(2))
            instrumentation.waitForIdleSync()
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            screenshot?.let { bitmap ->
                File(context.cacheDir, "viewer-persistence.png").outputStream().use {
                    assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
                }
                bitmap.recycle()
            }
            println("VIEWER_PERSISTENCE_REPORT=$report")
        } finally {
            browser?.let { runCatching { run(it, "if(window.ViewerRigQa)ViewerRigQa.dispose();") } }
            instrumentation.runOnMainSync { activity?.finish() }
            source.delete()
            preferences.edit().apply { if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide") }.commit()
        }
    }

    private fun fractionalSaveState(webView: WebView): JSONObject {
        val observed = evaluate(webView, "var inputs=Array.prototype.slice.call(document.querySelectorAll('#viewer-node-fields input[type=number]'));" +
            "var offGrid=inputs.filter(function(input){return input.validity.stepMismatch;}).map(function(input){return {" +
            "kind:input.dataset.viewerNodeKind,axis:input.dataset.axis,value:input.value,step:input.step};});" +
            "if(inputs.some(function(input){var v=input.validity;return v.badInput||v.rangeOverflow||v.rangeUnderflow||v.customError||v.valueMissing;}))" +
            "throw new Error('The fractional regression must contain only spinner step mismatches');" +
            "var position=document.querySelector('[data-viewer-node-kind=\"position\"][data-axis=\"Y\"]')," +
            "rotation=document.querySelector('[data-viewer-node-kind=\"rotation\"][data-axis=\"X\"]')," +
            "scale=document.querySelector('[data-viewer-node-kind=\"scale\"][data-axis=\"Y\"]'),authoring=ModelViewer.getAuthoringState();" +
            "return JSON.stringify({offGridInputs:offGrid,saveEnabled:!document.getElementById('viewer-save').disabled," +
            "unsupported:authoring.unsupported,positionY:Number(position.value),rotationX:Number(rotation.value),scaleY:Number(scale.value)," +
            "positionStep:position.step,rotationStep:rotation.step,scaleStep:scale.step});")
        val offGrid = observed.getJSONArray("offGridInputs")
        val kinds = (0 until offGrid.length()).map { offGrid.getJSONObject(it).getString("kind") }.toSet()
        assertTrue("Real serialized position, rotation and explicit scale must all exceed their spinner increments", kinds.containsAll(listOf("position", "rotation", "scale")))
        assertEquals("0.001", observed.getString("positionStep"))
        assertEquals("1", observed.getString("rotationStep"))
        assertEquals("0.001", observed.getString("scaleStep"))
        assertEquals("Untouched source positions must not be rounded to the spinner step", .1234567, observed.getDouble("positionY"), 1e-7)
        assertEquals("Untouched source rotations must retain their fractional precision", 12.34567, kotlin.math.abs(observed.getDouble("rotationX")), 1e-4)
        assertEquals(1.234567, observed.getDouble("scaleY"), 1e-7)
        assertEquals("Step mismatches alone are valid authoring values", 0, observed.getJSONArray("unsupported").length())
        assertTrue("The real APK must enable Save with only fractional step mismatches", observed.getBoolean("saveEnabled"))
        return observed.put("invalidBodyValueValidation", invalidBodySaveState(webView))
    }

    private fun invalidBodySaveState(webView: WebView): JSONObject = evaluate(webView, """
        var pose=document.getElementById('viewer-adjustments'),body=document.getElementById('viewer-body-adjustments'),
            fields=document.getElementById('viewer-node-fields'),save=document.getElementById('viewer-save'),
            input=document.querySelector('[data-viewer-node-kind="scale"][data-axis="Y"]');
        if(!body.contains(fields)||pose.contains(fields)||body.parentNode!==pose.parentNode||!input||!fields.contains(input))
            throw new Error('The actual bone fields must belong only to the independent Body panel');
        var poseWasOpen=pose.open,bodyWasOpen=body.open,original=input.value;
        try {
            body.open=true;pose.open=false;
            var control=ViewerRigQa.control(input,true);
            if(control.disabled||!control.visible||!control.withinViewport||!control.hittable||control.width<44||control.height<44)
                throw new Error('The actual Body input must be a visible unobstructed 44px target: '+JSON.stringify(control));
            var before=ModelViewer.getAuthoringState();
            if(save.disabled||before.unsupported.length||Number(original)!==1.234567)
                throw new Error('Begin with the exact valid fractional edit and enabled Save');
            input.focus();input.value='0';input.dispatchEvent(new Event('input',{bubbles:true}));
            var invalidAuthoring=ModelViewer.getAuthoringState(),invalid={value:input.value,
                customError:input.validity.customError,stepMismatch:input.validity.stepMismatch,
                ariaInvalid:input.getAttribute('aria-invalid'),saveEnabled:!save.disabled,
                unsupported:invalidAuthoring.unsupported,poseOpen:pose.open,bodyOpen:body.open};
            if(!invalid.customError||invalid.stepMismatch||invalid.ariaInvalid!=='true'||invalid.saveEnabled||
                !invalid.unsupported.length||invalid.poseOpen||!invalid.bodyOpen)
                throw new Error('A truly invalid zero scale must disable Save while Pose remains collapsed: '+JSON.stringify(invalid));
            if(JSON.stringify(invalidAuthoring.edits)!==JSON.stringify(before.edits))
                throw new Error('An invalid number must preserve the last valid persistent edits');
            input.value=original;input.dispatchEvent(new Event('input',{bubbles:true}));
            var restoredAuthoring=ModelViewer.getAuthoringState(),restored={value:input.value,
                customError:input.validity.customError,saveEnabled:!save.disabled,
                unsupported:restoredAuthoring.unsupported,poseOpen:pose.open,bodyOpen:body.open};
            if(restored.value!==original||restored.customError||!restored.saveEnabled||restored.unsupported.length||
                restored.poseOpen||!restored.bodyOpen||JSON.stringify(restoredAuthoring)!==JSON.stringify(before))
                throw new Error('Restoring the exact fractional input must reenable Save without changing edits: '+JSON.stringify(restored));
            return JSON.stringify({control:control,originalValue:original,invalid:invalid,restored:restored,
                independentBodyPanel:true,lastValidEditsPreserved:true});
        } finally {
            if(input.value!==original||input.validity.customError){input.value=original;input.dispatchEvent(new Event('input',{bubbles:true}));}
            pose.open=poseWasOpen;body.open=bodyWasOpen;
        }
    """.trimIndent())

    private fun thighTransform(webView: WebView): JSONObject = evaluate(webView,
        "var bone=ModelViewer.getState().rig.bones.filter(function(bone){return bone.name==='LeftUpLeg'||bone.name.slice(-10)==='/LeftUpLeg';})[0];" +
            "return JSON.stringify({position:bone.position,quaternion:bone.quaternion});")

    private fun assertThighTransformPreserved(before: JSONObject, after: JSONObject) {
        for (kind in listOf("position", "quaternion")) {
            val left = before.getJSONArray(kind); val right = after.getJSONArray(kind)
            assertEquals(left.length(), right.length())
            for (axis in 0 until left.length()) assertEquals("ZIP save/rebuild must preserve untouched source $kind axis $axis",
                left.getDouble(axis), right.getDouble(axis), 1e-8)
        }
    }

    private fun open(webView: WebView, path: String) {
        val previous = evaluate(webView, "return JSON.stringify({id:ModelViewer.getState().modelId||''});").getString("id")
        run(webView, "openModelViewer([" + JSONObject.quote(path) + "]);")
        waitForNewModel(webView, previous, JSONArray().put(path))
        waitForLoaded(webView)
        waitForDom(webView, "the real source-bound editing session") {
            "var p=ModelViewer.getState().persistence,m=ModelViewer.getEditingMetadata();" +
                "return JSON.stringify({ok:!!p&&p.available&&!p.busy&&!!m&&m.available,state:ModelViewer.getState()});"
        }
    }

    private fun openSaved(webView: WebView, result: JSONObject) {
        val previous = evaluate(webView, "return JSON.stringify({id:ModelViewer.getState().modelId||''});").getString("id")
        clickVisible(webView, "viewer-open-saved")
        waitForNewModel(webView, previous, result.getJSONArray("previewPaths"))
        waitForLoaded(webView)
    }

    private fun waitForNewModel(webView: WebView, previous: String, expectedPaths: JSONArray) = waitForDom(webView, "a newly converted output rather than the retained original") {
        "var s=ModelViewer.getState(),expected=" + expectedPaths.toString() + ";" +
            "return JSON.stringify({ok:s.loaded&&!s.loading&&s.modelId!==" + JSONObject.quote(previous) +
            "&&Array.isArray(s.loadedPaths)&&s.loadedPaths.length===expected.length&&" +
            "s.loadedPaths.every(function(path,i){return path===expected[i];}),error:s.error,state:s});"
    }

    private fun waitForLoaded(webView: WebView) = waitForDom(webView, "the genuine saved Unity skin and native framebuffer") {
        "var s=ModelViewer.getState(),p=s.loaded?ModelViewer.renderProbe(33):{ready:false};" +
            "return JSON.stringify({ok:s.loaded&&!s.loading&&!s.contextLost&&!!s.rig&&s.rig.available&&" +
            "s.stats.meshes===1&&s.stats.vertices===6&&s.stats.triangles===4&&p.ready&&p.glError===0&&" +
            "p.nonBackgroundSamples>=3,error:s.error,state:s,probe:p});"
    }

    private fun save(webView: WebView): JSONObject {
        val clicked = clickVisible(webView, "viewer-save")
        assertTrue("Saving must immediately show busy state and disable duplicate requests",
            clicked.getJSONObject("state").getJSONObject("persistence").getBoolean("busy"))
        assertTrue(clicked.getBoolean("disabled"))
        val done = waitForDom(webView, "embedded Python serialization and real SSE completion", 240) {
            "var p=ModelViewer.getState().persistence;return JSON.stringify({ok:!!p&&!p.busy&&" +
                "Array.isArray(p.outputs)&&p.outputs.length>=2&&Array.isArray(p.previewPaths)&&p.previewPaths.length===1&&!!p.recipePath," +
                "error:p&&(p.error||p.status==='error'&&document.getElementById('viewer-save-status').textContent)||'',persistence:p});"
        }
        return done.getJSONObject("persistence")
    }

    private fun saveNamedModPackage(context: Context, webView: WebView, previousResult: JSONObject,
        expectedAuthoring: JSONObject, source: File, sourceBytes: ByteArray, intended: JSONArray,
        sourceThigh: JSONObject): JSONObject {
        val previous = evaluate(webView, "return JSON.stringify({id:ModelViewer.getState().modelId});").getString("id")
        clickVisible(webView, "viewer-reedit-original")
        waitForNewModel(webView, previous, previousResult.getJSONArray("originalPaths"))
        waitForDom(webView, "the original body edits before packaging") {
            "var p=ModelViewer.getState().persistence;return JSON.stringify({ok:!p.busy&&p.status==='restored',error:p.error||''});"
        }
        assertEquals(expectedAuthoring.getJSONArray("edits").toString(),
            evaluate(webView, "return JSON.stringify(ModelViewer.getAuthoringState());").getJSONArray("edits").toString())
        // The neutral fixture has no character identity. Use the real explicit
        // owner selector, and a long Unicode name which exceeds 255 UTF-8 bytes.
        val name = "안드로이드 \"분수\" 모드 · " + "가나다라마바사아자차카타파하".repeat(6) + " 🧪"
        assertTrue(name.length <= 120 && name.toByteArray(Charsets.UTF_8).size > 255)
        val ownerControl = showModField(webView, "viewer-mod-character")
        input(webView, "viewer-mod-character", "6")
        val nameControl = showModField(webView, "viewer-mod-name")
        input(webView, "viewer-mod-name", name, "input")
        val form = evaluate(webView, "var p=ModelViewer.getState().persistence;return JSON.stringify({" +
            "owner:document.getElementById('viewer-mod-character').value,name:p.modName,manual:p.modNameManual});")
        assertEquals("6", form.getString("owner"))
        assertEquals(name, form.getString("name"))
        assertTrue(form.getBoolean("manual"))
        val clicked = clickVisible(webView, "viewer-save-mod")
        assertTrue("The real package action must immediately disable duplicate requests",
            clicked.getBoolean("disabled") && clicked.getJSONObject("state").getJSONObject("persistence").getBoolean("busy"))
        val done = waitForDom(webView, "a completed installer ZIP from the embedded Python package action", 240) {
            "var p=ModelViewer.getState().persistence;return JSON.stringify({ok:!p.busy&&p.status==='done'&&!!p.modPackage&&" +
                "!!p.modPackage.packagePath,error:p.error||'',persistence:p});"
        }.getJSONObject("persistence")
        checkOutputs(done, source)
        val publicPackage = done.getJSONObject("modPackage")
        assertEquals(6, publicPackage.getInt("characterId"))
        assertFalse("The UI inspection state must not expose the installation token", publicPackage.has("token"))
        val packageFile = File(publicPackage.getString("packagePath"))
        assertTrue(packageFile.isFile && packageFile.length() > 0)
        assertTrue("The full Unicode display name must fit a portable output filename", packageFile.name.toByteArray(Charsets.UTF_8).size <= 255)
        run(webView, "window.__viewerNativeModReceipt={done:false};fetch('/api/viewer/edit/result/'+" +
            "encodeURIComponent(ModelViewer.getState().persistence.jobId)).then(function(response){" +
            "return response.json().then(function(value){if(!response.ok||value.error)throw new Error(value.error||'Package result failed');return value;});" +
            "}).then(function(value){window.__viewerNativeModReceipt={done:true,value:value};}," +
            "function(error){window.__viewerNativeModReceipt={done:true,error:String(error)};});")
        val full = waitForDom(webView, "the authoritative completed package receipt") {
            "var r=window.__viewerNativeModReceipt;return JSON.stringify({ok:r.done&&!r.error,error:r.error||'',value:r.value});"
        }.getJSONObject("value")
        assertEquals(done.getString("recipePath"), full.getString("recipe_path"))
        assertEquals(done.getJSONArray("previewPaths").toString(), full.getJSONArray("preview_paths").toString())
        val receipt = full.getJSONObject("mod_package")
        assertEquals(packageFile.canonicalPath, File(receipt.getString("package_path")).canonicalPath)
        assertEquals(name, receipt.getString("display_name"))
        assertEquals(6, receipt.getInt("character_id"))
        assertEquals("android", receipt.getString("platform"))
        assertTrue(receipt.getBoolean("installable"))
        assertTrue(receipt.getString("token").matches(Regex("[a-f0-9]{32}")))
        assertEquals(packageFile.length(), receipt.getLong("bytes"))
        assertEquals(sha256(packageFile.readBytes()), receipt.getString("sha256"))
        val spec = JSONObject().put("receipt", receipt).put("previewPaths", done.getJSONArray("previewPaths"))
            .put("recipePath", done.getString("recipePath")).put("state", expectedAuthoring)
            .put("sourceSha256", sha256(sourceBytes)).put("memberSha256", "d468e330e747001096092e33d8bc8e9191096d5c66b9f5723b9f76792e4c23b3")
        val python = EmbeddedPython.instance(context)
        val module = python.getModule("types").callAttr("ModuleType", "_viewer_mod_package_native_qa")
        python.getModule("builtins").callAttr("exec", packageInspectionScript, module.get("__dict__"))
        val inspected = JSONObject(module.callAttr("inspect_json", spec.toString()).toString())
        assertTrue(inspected.getBoolean("safeInstallerArchive"))
        // Open the installer ZIP itself, then compare its actual serialized skin
        // with the original intended hybrid result using the existing threshold.
        open(webView, packageFile.absolutePath)
        val packagedVertices = vertices(webView)
        assertTrue("The installer ZIP must reproduce the intended hybrid skin", maxDifference(intended, packagedVertices) < 2e-5)
        assertThighTransformPreserved(sourceThigh, thighTransform(webView))
        assertBoneScale(webView, "BreastSize", doubleArrayOf(1.0, 1.0, 1.15))
        assertTrue("Mod packaging must preserve the original fractional ZIP", source.readBytes().contentEquals(sourceBytes))
        assertGameStopped()
        return JSONObject().put("displayName", name).put("explicitOwner", 6).put("ownerControl", ownerControl)
            .put("nameControl", nameControl).put("inspection", inspected).put("sourcePreserved", true)
            .put("installerZipReopened", true).put("hybridSkinMaximumDifference", maxDifference(intended, packagedVertices))
            .put("scope", "Package-only actual WebView/SSE/bundled Python; no game installation or user database writes")
    }

    private fun showModField(webView: WebView, id: String): JSONObject {
        run(webView, "var t=document.getElementById(" + JSONObject.quote(id) + ");" +
            "for(var p=t.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;t.scrollIntoView({block:'center'});")
        return waitForDom(webView, "the visible explicit mod option $id", 30) {
            "var t=document.getElementById(" + JSONObject.quote(id) + "),r=t.getBoundingClientRect()," +
                "top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);" +
                "return JSON.stringify({ok:!t.disabled&&r.width>=44&&r.height>=44&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&" +
                "(top===t||t.contains(top)),id:t.id,width:r.width,height:r.height,visible:!!t.getClientRects().length,hittable:top===t||t.contains(top)});"
        }
    }

    private val packageInspectionScript = """
        import ast, hashlib, io, json, re, stat, zipfile
        from pathlib import Path, PurePosixPath
        from PIL import Image

        def inspect_json(encoded):
            spec = json.loads(encoded)
            receipt = spec['receipt']
            path = Path(receipt['package_path'])
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == receipt['sha256']
            assert len(data) == receipt['bytes'] and receipt['character_id'] == 6
            assert receipt['platform'] == 'android' and receipt['installable'] is True
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                names = [entry.filename for entry in infos]
                assert len(names) == len(set(name.casefold() for name in names)) == 3
                for entry in infos:
                    name = PurePosixPath(entry.filename)
                    assert not name.is_absolute() and '..' not in name.parts
                    assert '\\' not in entry.filename and ':' not in entry.filename
                    assert not stat.S_ISLNK(entry.external_attr >> 16)
                config = {}
                for node in ast.parse(archive.read('modinstall.txt').decode('utf-8-sig')).body:
                    assert isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    key = node.targets[0].id
                    assert key not in config
                    config[key] = ast.literal_eval(node.value)
                assert config['chara_id'] == 6
                for key in ['costume_name_en', 'costume_name_ko', 'costume_name_zh', 'costume_name_ja', 'costume_description']:
                    assert config[key] == receipt['display_name']
                model = config['costume_file']
                assert re.fullmatch(r'[a-z0-9]+\.unity', model) and re.search('[a-z]', Path(model).stem)
                assert set(names) == {model, config['thumbnail_file'], 'modinstall.txt'}
                model_bytes = archive.read(model)
                with Image.open(io.BytesIO(archive.read(config['thumbnail_file']))) as image:
                    assert image.format == 'PNG' and 0 < max(image.size) <= 256
                    image.verify()
            assert len(spec['previewPaths']) == 1
            preview = Path(spec['previewPaths'][0])
            with zipfile.ZipFile(preview) as saved:
                members = [entry.filename for entry in saved.infolist() if entry.filename.endswith('.unity')]
                assert len(members) == 1
                assert model_bytes == saved.read(members[0])
            model_sha = hashlib.sha256(model_bytes).hexdigest()
            assert model_sha != spec['memberSha256']
            recipe = json.loads(Path(spec['recipePath']).read_text())
            assert recipe['format'] == 'elichika-viewer-body-edit'
            assert len(recipe['originals']) == 1 and recipe['originals'][0]['sha256'] == spec['sourceSha256']
            assert len(recipe['sources']) == 1 and recipe['sources'][0]['sha256'] == spec['memberSha256']
            expected = {edit['node']: edit for edit in spec['state']['edits']}
            actual = {edit['node']: edit for edit in recipe['state']['edits']}
            assert set(actual) == set(expected) and {edit['method'] for edit in actual.values()} == {'node', 'mesh'}
            for node, edit in expected.items():
                assert actual[node]['method'] == edit['method']
                for key in ['scale', 'position', 'rotation']:
                    if key in edit:
                        assert len(actual[node][key]) == len(edit[key])
                        assert max(abs(a-b) for a,b in zip(actual[node][key], edit[key])) <= 1e-8
            return json.dumps({'safeInstallerArchive': True, 'characterId': 6, 'displayName': receipt['display_name'],
                'packageSha256': receipt['sha256'], 'packageBytes': len(data), 'members': names,
                'modelMember': model, 'modelSha256': model_sha, 'modelMatchesFreshPreview': True,
                'recipeBoundToOriginal': True, 'hybridRecipePreserved': True})
    """.trimIndent()

    private fun checkOutputs(result: JSONObject, source: File): List<File> {
        val outputs = result.getJSONArray("outputs")
        val files = (0 until outputs.length()).map { File(outputs.getString(it)) }
        assertTrue("Both the recipe and modified model must be finished files", files.all { it.isFile && it.length() > 0 })
        val previews = result.getJSONArray("previewPaths")
        val edited = File(previews.getString(0))
        assertTrue("The re-open path must be a completed serialized Unity model", edited.isFile && edited.length() > 0)
        assertFalse("The exporter must never target the original input", edited.canonicalPath == source.canonicalPath)
        assertTrue("The recipe must be one of the completed download outputs", files.any { it.canonicalPath == File(result.getString("recipePath")).canonicalPath })
        assertTrue("The modified model must be one of the completed download outputs", files.any { it.canonicalPath == edited.canonicalPath })
        val originals = result.getJSONArray("originalPaths")
        assertEquals("A restorable original must be kept separately", 1, originals.length())
        val originalCopy = File(originals.getString(0))
        assertTrue("The preserved original must keep the source bytes", originalCopy.isFile && originalCopy.readBytes().contentEquals(source.readBytes()))
        assertFalse("The preserved original must be a separate file", originalCopy.canonicalPath == source.canonicalPath)
        return files
    }

    private fun restore(webView: WebView, recipe: JSONObject) {
        run(webView, "window.__persistenceRestore={done:false};" +
            "fetch('/api/viewer/edit/restore',{method:'POST',headers:{'Content-Type':'application/json'}," +
            "body:JSON.stringify({token:ModelViewer.getEditingMetadata().token,recipe:JSON.parse(" + JSONObject.quote(recipe.toString()) + ")})})" +
            ".then(function(response){return response.json().then(function(value){if(!response.ok)throw new Error(value.error||'Restore failed');return value;});})" +
            ".then(function(value){return Promise.resolve(ModelViewer.restoreAuthoringState(value.state));})" +
            ".then(function(){window.__persistenceRestore={done:true};},function(error){window.__persistenceRestore={done:true,error:String(error)};});")
        waitForDom(webView, "the source-bound portable recipe restore") {
            "return JSON.stringify({ok:window.__persistenceRestore.done&&!window.__persistenceRestore.error,error:window.__persistenceRestore.error||''});"
        }
    }

    private fun vertices(webView: WebView): JSONArray = evaluate(webView,
        "return JSON.stringify(ViewerRigQa.deformedVertices());").getJSONArray("vertices")

    private fun maxDifference(left: JSONArray, right: JSONArray): Double {
        assertEquals("Both real skins must retain the same vertices", left.length(), right.length())
        var maximum = 0.0
        for (vertex in 0 until left.length()) for (axis in 0..2) {
            maximum = maxOf(maximum, kotlin.math.abs(left.getJSONArray(vertex).getDouble(axis) - right.getJSONArray(vertex).getDouble(axis)))
        }
        return maximum
    }

    private fun assertBoneScale(webView: WebView, name: String, expected: DoubleArray) {
        val actual = evaluate(webView, "return JSON.stringify(ViewerRigQa.nodeWorld(" + JSONObject.quote(name) + "));")
            .getJSONArray("localScale")
        for (axis in expected.indices) assertEquals("$name scale axis $axis", expected[axis], actual.getDouble(axis), 2e-5)
    }

    private fun waitForBoneScale(webView: WebView, name: String, expected: DoubleArray) = waitForDom(webView, "the expected $name scale") {
        val values = JSONArray(expected.toList()).toString()
        "var a=ViewerRigQa.nodeWorld(" + JSONObject.quote(name) + ").localScale,e=$values;" +
            "return JSON.stringify({ok:a.every(function(v,i){return Math.abs(v-e[i])<2e-5;}),actual:a});"
    }

    private fun input(webView: WebView, id: String, value: String, event: String = "change") = run(webView,
        "ViewerRigQa.input(" + JSONObject.quote(id) + "," + JSONObject.quote(value) + "," + JSONObject.quote(event) + ");")

    private fun boneInput(webView: WebView, name: String, kind: String, axis: String, value: Number) = run(webView,
        "ViewerRigQa.boneInput(" + JSONObject.quote(name) + "," + JSONObject.quote(kind) + "," + JSONObject.quote(axis) + ",$value);")

    private fun assertEditorGroup(webView: WebView, group: String) {
        val value = evaluate(webView, "var active=document.getElementById('viewer-editor-" + group + "-tab')," +
            "panel=document.getElementById('viewer-editor-" + group + "-panel');" +
            "return JSON.stringify({selected:active.getAttribute('aria-selected'),visible:!panel.hidden," +
            "ownsEditor:panel.contains(document.getElementById('viewer-node-editor'))});")
        assertEquals("The chosen editing area must be the active accessible tab", "true", value.getString("selected"))
        assertTrue("The active editing area must contain the usable shared editor", value.getBoolean("visible") && value.getBoolean("ownsEditor"))
    }

    private fun clickVisible(webView: WebView, id: String): JSONObject {
        run(webView, "var t=document.getElementById(" + JSONObject.quote(id) + ");" +
            "for(var p=t.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;t.scrollIntoView({block:'center'});")
        waitForDom(webView, "the visible $id control", 30) {
            "var t=document.getElementById(" + JSONObject.quote(id) + "),r=t.getBoundingClientRect()," +
                "top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);" +
                "return JSON.stringify({ok:!t.disabled&&r.width>=44&&r.height>=44&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&" +
                "(top===t||t.contains(top)),id:t.id,width:r.width,height:r.height,disabled:t.disabled});"
        }
        return evaluate(webView, "var t=document.getElementById(" + JSONObject.quote(id) + ");t.click();" +
            "return JSON.stringify({state:ModelViewer.getState(),disabled:t.disabled});")
    }

    private fun grantPermissions(context: Context) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) permissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        for (permission in permissions) if (context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, permission)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) assertTrue(Environment.isExternalStorageManager())
    }

    private fun assertGameStopped() {
        assertFalse(Bus.serverRunning)
        assertFalse(Bus.serverStarting)
        val process = ProcessBuilder("/system/bin/pidof", "libelichika.so").redirectErrorStream(true).start()
        assertTrue(process.waitFor(5, TimeUnit.SECONDS))
        val output = process.inputStream.bufferedReader().use { it.readText().trim() }
        assertTrue(process.exitValue() in 0..1)
        assertEquals("Editing a model must not launch the game server", "", if (process.exitValue() == 0) output else "")
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

    private fun run(webView: WebView, script: String) = evaluate(webView, script + "\nreturn JSON.stringify({ok:true});")

    private fun evaluate(webView: WebView, body: String): JSONObject {
        val result = AtomicReference<String>()
        val done = CountDownLatch(1)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            webView.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();") {
                result.set(it)
                done.countDown()
            }
        }
        assertTrue("The actual WebView JavaScript callback timed out", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        val value = JSONObject(decoded as? String ?: throw AssertionError("Unexpected JavaScript result: ${result.get()}"))
        if (value.optString("error").isNotEmpty() && value.optBoolean("ok", true).not()) throw AssertionError("Viewer JavaScript failed: $value")
        return value
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
