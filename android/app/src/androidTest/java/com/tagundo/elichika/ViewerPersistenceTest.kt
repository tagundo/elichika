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
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Real embedded Python, serialized Unity output and native WebGL; original neutral geometry only. */
@RunWith(AndroidJUnit4::class)
class ViewerPersistenceTest {
    @Test
    fun mixedNodeAndMeshEditsSaveReloadAndRebuildWithoutAccumulating() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val bytes = instrumentation.context.assets.open("viewer_persistence.unity").use { it.readBytes() }
        val source = File(context.filesDir, "viewer-persistence-qa-${System.nanoTime()}.unity")
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
                "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1", sha256(bytes))
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
            run(webView, "document.getElementById('viewer-adjustments').open=true;document.getElementById('viewer-node-editor').open=true;")

            clickVisible(webView, "viewer-editor-mesh-tab")
            assertEditorGroup(webView, "mesh")
            boneInput(webView, "LeftUpLeg", "scale", "Y", 1.2)
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
            run(webView, "document.getElementById('viewer-preview-reset').click();")
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
            val rebuilt = vertices(webView)
            assertTrue("Rebuilding from the original must not accumulate another mesh transform",
                maxDifference(reloaded, rebuilt) < 2e-5)
            assertTrue("Repeated save and restore must preserve the original source", source.readBytes().contentEquals(bytes))
            assertTrue("The first completed output must remain available", outputFiles.all { it.isFile && it.length() > 0 })
            assertGameStopped()
            val report = JSONObject().put("sourceSha256", sha256(bytes)).put("sourcePreserved", true)
                .put("firstExport", first).put("secondExport", second).put("recipeRestored", true)
                .put("nodeAndMeshBackends", true).put("noAccumulation", true)
                .put("separateEditingAreas", true).put("switchingAreasPreservesEdits", true)
                .put("animationOrderComparison", true).put("animatedPoseExcludedFromExport", true)
                .put("baselineVertices", baseline).put("intendedVertices", intended)
                .put("reloadedVertices", reloaded).put("rebuiltVertices", rebuilt)
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
