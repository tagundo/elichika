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

/** Original neutral triangles exercise ZIP discovery, face assembly and actual device WebGL. */
@RunWith(AndroidJUnit4::class)
class ModelViewerAutoFaceTest {
    @Test
    fun costumeZipAddsOnlyMissingEyesAndHonorsFaceToggle() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val costumeBytes = instrumentation.context.assets.open("viewer_auto_face_costume.zip").use { it.readBytes() }
        val donorBytes = instrumentation.context.assets.open("viewer_auto_face_donor.unity").use { it.readBytes() }
        val directory = File(context.filesDir, "viewer-auto-face-qa-${System.nanoTime()}")
        val costume = File(directory, "costume.zip")
        val donor = File(directory, "originals/ch0207_original.unity")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        var activity: MainActivity? = null
        try {
            val permissions = mutableListOf<String>()
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) permissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissions.add(Manifest.permission.POST_NOTIFICATIONS)
            for (permission in permissions) {
                if (context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
                    instrumentation.uiAutomation.grantRuntimePermission(context.packageName, permission)
                }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                assertTrue("The device harness must grant All files access", Environment.isExternalStorageManager())
            }
            assertGameStopped()
            assertTrue("Create the test's private sibling donor directory", donor.parentFile!!.mkdirs())
            costume.writeBytes(costumeBytes)
            donor.writeBytes(donorBytes)
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ) as MainActivity
            activity = launched
            instrumentation.runOnMainSync {
                launched.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select()
            }
            // The real Asset editing tab prepares Python without starting the game server.
            val webView = waitForWebView(launched)
            waitForDom(webView, "the offline model viewer") {
                "return JSON.stringify({ok:typeof window.openModelViewer==='function'&&" +
                    "!!window.ModelViewer&&!!window.THREE&&" +
                    "!!document.querySelector('#tool-list button[data-id=\"mesh_baker\"]'),title:document.title});"
            }
            assertTrue("The editing tab must prepare its embedded tools", PyServers.isStarted())
            assertGameStopped()
            val initial = evaluate(webView, "return JSON.stringify({checked:document.getElementById('viewer-auto-face').checked});")
            assertTrue("Face completion must default to enabled", initial.getBoolean("checked"))
            openZip(webView, costume)
            val assembled = waitForDom(webView, "ZIP and same-owner missing Eyes assembly") {
                "var s=window.ModelViewer.getState(),f=s.faces;return JSON.stringify({" +
                    "ok:s.loaded&&!s.loading&&!s.contextLost&&s.autoFace&&s.loadedAutoFace&&" +
                    "!!s.stats&&s.stats.meshes===3&&s.stats.vertices===9&&s.stats.triangles===3&&s.stats.textures===3&&" +
                    "JSON.stringify(s.meshNames.slice().sort())==='[\"Body\",\"Eyes\",\"Face_shell\"]'&&" +
                    "!!f&&f.enabled&&f.status==='added'&&f.added===1&&JSON.stringify(f.characters)==='[207]'," +
                    "error:s.error,state:s});"
            }
            val assembledState = assembled.getJSONObject("state")
            assertEquals(setOf("Body", "Face_shell", "Eyes"), names(assembledState.getJSONArray("meshNames")))
            assertEquals("Keep the selected ZIP as the source", costume.absolutePath,
                assembledState.getJSONArray("loadedPaths").getString(0))
            frameModel(webView)
            val enabledPixels = waitForPixels(webView, "the completed costume", 3)
            val completion = evaluate(webView, "var e=document.getElementById('viewer-face-status');" +
                "return JSON.stringify({hidden:e.hidden,text:e.textContent});")
            assertFalse("Report success after actual missing Eyes geometry was added", completion.getBoolean("hidden"))
            assertTrue("The completion message must be present", completion.getString("text").isNotBlank())

            // Hide the original costume parts using their real checkboxes. The remaining
            // single drawn triangle and colored pixels must belong to the auto-added Eyes.
            val isolated = evaluate(webView, "var labels=document.querySelectorAll('#viewer-parts label');" +
                "var found=false;for(var i=0;i<labels.length;i++){" +
                "var input=labels[i].querySelector('input'),name=labels[i].querySelector('span').textContent;" +
                "var visible=name==='Eyes';found=found||visible;if(input.checked!==visible)input.click();}" +
                "return JSON.stringify({ok:found});")
            assertTrue("The real parts controls must include the auto-added Eyes", isolated.getBoolean("ok"))
            val eyesPixels = waitForPixels(webView, "only the auto-added Eyes", 1)
            evaluate(webView, "var inputs=document.querySelectorAll('#viewer-parts input');" +
                "for(var i=0;i<inputs.length;i++){if(!inputs[i].checked)inputs[i].click();}" +
                "return JSON.stringify({ok:true});")
            waitForPixels(webView, "the restored completed costume", 3)
            val enabledImage = saveScreenshot(launched, "model-viewer-auto-face.png")
            assertTrue("The costume ZIP must be byte-for-byte unchanged", costume.readBytes().contentEquals(costumeBytes))
            assertTrue("The original donor must be byte-for-byte unchanged", donor.readBytes().contentEquals(donorBytes))

            // Toggle the actual setting and reopen the same ZIP. Its different load identity
            // must replace the assembled model, rather than retaining the previous Eyes.
            evaluate(webView, "document.getElementById('viewer-auto-face').click();" +
                "return JSON.stringify({ok:!document.getElementById('viewer-auto-face').checked});")
            val staleStatus = evaluate(webView, "return JSON.stringify({hidden:document.getElementById('viewer-face-status').hidden});")
            assertTrue("Changing the setting must hide the previous completion claim", staleStatus.getBoolean("hidden"))
            openZip(webView, costume)
            val disabled = waitForDom(webView, "ZIP reopened with face completion disabled") {
                "var s=window.ModelViewer.getState(),f=s.faces;" +
                    "var status=document.getElementById('viewer-face-status');return JSON.stringify({" +
                    "ok:s.loaded&&!s.loading&&!s.contextLost&&!s.autoFace&&!s.loadedAutoFace&&" +
                    "!!s.stats&&s.stats.meshes===2&&s.stats.vertices===6&&s.stats.triangles===2&&s.stats.textures===2&&" +
                    "JSON.stringify(s.meshNames.slice().sort())==='[\"Body\",\"Face_shell\"]'&&" +
                    "!!f&&!f.enabled&&f.added===0&&f.status==='not_needed'&&status.hidden," +
                    "error:s.error,state:s,faceStatusHidden:status.hidden});"
            }
            val disabledState = disabled.getJSONObject("state")
            assertEquals(setOf("Body", "Face_shell"), names(disabledState.getJSONArray("meshNames")))
            assertFalse("Reopening with another face preference must replace its session",
                assembledState.getString("modelId") == disabledState.getString("modelId"))
            frameModel(webView)
            val disabledPixels = waitForPixels(webView, "the costume without added Eyes", 2)
            val disabledImage = saveScreenshot(launched, "model-viewer-auto-face-disabled.png")
            assertTrue("Reopening must preserve the ZIP", costume.readBytes().contentEquals(costumeBytes))
            assertTrue("Reopening must preserve the donor", donor.readBytes().contentEquals(donorBytes))
            assertGameStopped()
            val report = JSONObject().put("enabled", assembledState).put("disabled", disabledState)
                .put("enabledProbe", enabledPixels).put("addedEyesOnlyProbe", eyesPixels)
                .put("disabledProbe", disabledPixels).put("completion", completion)
                .put("sourceZipPreserved", true).put("donorPreserved", true)
                .put("gameServerRemainedStopped", true)
                .put("enabledScreenshot", enabledImage.absolutePath).put("disabledScreenshot", disabledImage.absolutePath)
            println("MODEL_VIEWER_AUTO_FACE_REPORT=$report")
        } finally {
            instrumentation.runOnMainSync { activity?.finish() }
            directory.deleteRecursively()
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun openZip(webView: WebView, source: File) {
        evaluate(webView, "window.openModelViewer([" + JSONObject.quote(source.absolutePath) +
            "]);return JSON.stringify({ok:true});")
    }

    private fun frameModel(webView: WebView) {
        evaluate(webView, "if(!document.getElementById('tab-viewer').classList.contains('viewer-expanded'))" +
            "document.getElementById('viewer-expand').click();" +
            "document.querySelector('button[data-viewer-view=\"front\"]').click();" +
            "document.getElementById('viewer-fit').click();" +
            "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'end'});" +
            "return JSON.stringify({ok:true});")
    }

    private fun waitForPixels(webView: WebView, description: String, expectedTriangles: Int): JSONObject {
        return waitForDom(webView, "$description in the actual WebGL framebuffer") {
            "var s=window.ModelViewer.getState(),p=window.ModelViewer.renderProbe();" +
                "return JSON.stringify({ok:s.loaded&&!s.loading&&!s.contextLost&&p.ready&&" +
                "p.triangles===$expectedTriangles&&p.nonBackgroundSamples>=3&&p.chromaticSamples>=3&&" +
                "p.width>=100&&p.height>=100&&p.glError===0,error:s.error,probe:p});"
        }.getJSONObject("probe")
    }

    private fun saveScreenshot(activity: MainActivity, filename: String): File {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(250)
        instrumentation.runOnMainSync {
            assertTrue("The model viewer must be in front of system dialogs", activity.hasWindowFocus())
        }
        val screenshot = instrumentation.uiAutomation.takeScreenshot()
        assertTrue("Capture the real device framebuffer", screenshot != null)
        val destination = File(instrumentation.targetContext.cacheDir, filename)
        destination.outputStream().use {
            assertTrue("Save the rendered model screenshot", screenshot!!.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
        screenshot?.recycle()
        return destination
    }

    private fun assertGameStopped() {
        assertFalse("The viewer must leave the game server stopped", Bus.serverRunning)
        assertFalse("The viewer must not queue a game server start", Bus.serverStarting)
        val process = ProcessBuilder("/system/bin/pidof", "libelichika.so").redirectErrorStream(true).start()
        assertTrue("Checking the game process must finish", process.waitFor(5, TimeUnit.SECONDS))
        val output = process.inputStream.bufferedReader().use { it.readText().trim() }
        assertTrue("pidof must report a match or no process", process.exitValue() in 0..1)
        assertEquals("Viewing a costume ZIP must not launch Go", "", if (process.exitValue() == 0) output else "")
    }

    private fun waitForWebView(activity: MainActivity): WebView {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(300)
        while (System.nanoTime() < deadline) {
            var view: WebView? = null
            instrumentation.runOnMainSync {
                view = descendants(activity.findViewById(R.id.content))
                    .filterIsInstance<WebView>().firstOrNull { it.visibility == View.VISIBLE }
            }
            view?.let { return it }
            if (PyServers.hasPreparationError() && !PyServers.isPreparing()) {
                throw AssertionError("Asset editing could not prepare tools: ${Bus.snapshot().takeLast(1500)}")
            }
            Thread.sleep(100)
        }
        throw AssertionError("The editing tab did not open its WebView after preparing tools")
    }

    private fun waitForDom(webView: WebView, description: String, script: () -> String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(240)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = evaluate(webView, script())
            val error = last.optString("error")
            if (error.isNotEmpty()) throw AssertionError("$description: $error; $last")
            if (last.optBoolean("ok")) return last
            Thread.sleep(100)
        }
        throw AssertionError("Timed out waiting for $description: $last")
    }

    private fun evaluate(webView: WebView, body: String): JSONObject {
        val result = AtomicReference<String>()
        val done = CountDownLatch(1)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            // ES5 wrapper also runs in Android 10's stock WebView 74.
            webView.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();") {
                result.set(it)
                done.countDown()
            }
        }
        assertTrue("WebView callback timed out", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        return JSONObject(decoded as? String ?: throw AssertionError("Unexpected JavaScript result: ${result.get()}"))
    }

    private fun names(values: JSONArray): Set<String> = (0 until values.length()).map { values.getString(it) }.toSet()

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
