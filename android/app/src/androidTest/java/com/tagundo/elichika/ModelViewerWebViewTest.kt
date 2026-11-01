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
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Load a real Unity scene through Python, GLB and the device's actual WebGL renderer. */
@RunWith(AndroidJUnit4::class)
class ModelViewerWebViewTest {
    @Test
    fun unityModelRendersRealPixelsAndSurvivesTabChanges() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val fixtureBytes = instrumentation.context.assets.open("viewer_textured_triangle.unity").use { it.readBytes() }
        val source = File(context.filesDir, "viewer-qa-${System.nanoTime()}.unity")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        var activity: MainActivity? = null
        try {
            val storagePermissions = mutableListOf<String>()
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) {
                storagePermissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) {
                storagePermissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            }
            for (permission in storagePermissions) {
                if (context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
                    instrumentation.uiAutomation.grantRuntimePermission(context.packageName, permission)
                }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                assertTrue("The emulator harness must grant All files access before UI QA",
                    Environment.isExternalStorageManager())
            }
            assertFalse("The viewer must open with the game server stopped", Bus.serverRunning)
            assertFalse("The viewer must not queue a game-server start", Bus.serverStarting)
            assertEquals("The fixture flow requires no existing Go process", "", gameServerPids())
            source.writeBytes(fixtureBytes)
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ) as MainActivity
            activity = launched
            instrumentation.runOnMainSync {
                launched.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select()
            }
            // Selecting Asset editing must prepare its local server asynchronously.
            // Do not bypass that product flow with a direct PyServers.start call.
            val webView = waitForWebView(launched)
            waitForTools()
            assertTrue("The tab must prepare its embedded tools", PyServers.isStarted())
            assertFalse("Preparing tools must leave the game server stopped", Bus.serverRunning)
            assertFalse("Preparing tools must not queue a Go start", Bus.serverStarting)
            assertEquals("Opening editing tools must not launch Go", "", gameServerPids())
            waitForDom(webView, "offline viewer scripts") {
                "return JSON.stringify({ok:typeof window.openModelViewer==='function'&&" +
                    "!!window.ModelViewer&&!!window.THREE&&" +
                    "!!document.querySelector('#tool-list button[data-id=\"mesh_baker\"]'),title:document.title});"
            }
            evaluate(webView, "window.openModelViewer([" + JSONObject.quote(source.absolutePath) +
                "]);return JSON.stringify({ok:true});")
            val rendered = waitForDom(webView, "actual Unity triangle pixels") {
                """
                var s=window.ModelViewer.getState();
                var p=s.loaded?window.ModelViewer.renderProbe():{ready:false};
                return JSON.stringify({ok:s.loaded&&!s.loading&&!s.contextLost&&!!s.stats&&
                  s.stats.meshes===1&&s.stats.vertices===3&&s.stats.triangles===1&&s.stats.textures===1&&p.ready&&
                  p.triangles>=1&&p.nonBackgroundSamples>=5&&p.chromaticSamples>=3&&p.width>=100&&p.height>=100&&
                  p.glError===0,error:s.error,state:s,probe:p,
                  noHorizontalOverflow:document.documentElement.scrollWidth<=window.innerWidth+1});
                """.trimIndent()
            }
            assertTrue("The rendered model must not overflow horizontally", rendered.getBoolean("noHorizontalOverflow"))
            assertEquals(1, rendered.getJSONObject("state").getJSONObject("stats").getInt("meshes"))
            assertTrue("The WebGL framebuffer must contain model pixels",
                rendered.getJSONObject("probe").getInt("nonBackgroundSamples") >= 5)
            assertTrue("The model texture must produce actual colored pixels",
                rendered.getJSONObject("probe").getInt("chromaticSamples") >= 3)
            val modelId = rendered.getJSONObject("state").getString("modelId")

            // These are the real UI click handlers, not a separate test renderer.
            evaluate(webView, "document.querySelector('.tab[data-tab=\"tools\"]').click();" +
                "return JSON.stringify(window.ModelViewer.getState());")
            val hidden = evaluate(webView, "return JSON.stringify(window.ModelViewer.getState());")
            assertFalse("Hidden tabs must stop drawing the model", hidden.getBoolean("visible"))
            val hiddenFrames = hidden.getInt("renderedFrames")
            Thread.sleep(500)
            val idle = evaluate(webView, "return JSON.stringify(window.ModelViewer.getState());")
            assertEquals("A hidden viewer must not keep consuming GPU frames", hiddenFrames, idle.getInt("renderedFrames"))
            evaluate(webView, "document.querySelector('.tab[data-tab=\"viewer\"]').click();" +
                "return JSON.stringify({ok:true});")
            val resumed = waitForDom(webView, "retained model after tab change") {
                "var s=window.ModelViewer.getState();var p=window.ModelViewer.renderProbe();" +
                    "return JSON.stringify({ok:s.visible&&s.loaded&&p.ready&&p.nonBackgroundSamples>=5," +
                    "error:s.error,state:s,probe:p});"
            }
            assertEquals("Returning to the tab must preserve the loaded model", modelId,
                resumed.getJSONObject("state").getString("modelId"))

            evaluate(webView, "document.getElementById('viewer-expand').click();" +
                "document.getElementById('viewer-fit').click();" +
                "document.querySelector('.viewer-camera-actions').scrollIntoView({block:'center'});" +
                "return JSON.stringify({ok:true});")
            val controls = waitForDom(webView, "visible camera controls") {
                """
                var buttons=document.querySelectorAll('.viewer-camera-actions button');
                var fits=buttons.length===5;
                for(var i=0;i<buttons.length;i++){
                  var b=buttons[i],r=b.getBoundingClientRect();
                  var hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                  fits=fits&&r.width>=44&&r.height>=44&&r.top>=0&&r.bottom<=window.innerHeight+1&&
                    r.left>=0&&r.right<=window.innerWidth+1&&(hit===b||b.contains(hit));
                }
                return JSON.stringify({ok:fits,count:buttons.length,
                  width:window.innerWidth,height:window.innerHeight});
                """.trimIndent()
            }
            assertEquals(5, controls.getInt("count"))
            assertTrue("Viewing a model must leave its Unity source unchanged", source.readBytes().contentEquals(fixtureBytes))
            instrumentation.waitForIdleSync()
            Thread.sleep(250)
            instrumentation.runOnMainSync {
                assertTrue("The rendered app must be in front of permission or system dialogs", launched.hasWindowFocus())
            }
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            assertTrue("Capture actual rendered device evidence", screenshot != null)
            val image = File(context.cacheDir, "model-viewer-qa.png")
            image.outputStream().use { screenshot!!.compress(Bitmap.CompressFormat.PNG, 100, it) }
            screenshot?.recycle()
            rendered.put("tabStateRetained", true)
            rendered.put("hiddenFramesPaused", true)
            rendered.put("sourcePreserved", true)
            rendered.put("gameServerRemainedStopped", true)
            rendered.put("cameraControls", controls)
            println("MODEL_VIEWER_WEBVIEW_REPORT=$rendered")
        } finally {
            instrumentation.runOnMainSync { activity?.finish() }
            source.delete()
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun gameServerPids(): String {
        val process = ProcessBuilder("/system/bin/pidof", "libelichika.so")
            .redirectErrorStream(true).start()
        assertTrue("Checking the Go process must finish", process.waitFor(5, TimeUnit.SECONDS))
        val output = process.inputStream.bufferedReader().use { it.readText().trim() }
        assertTrue("pidof must report a match or no process", process.exitValue() in 0..1)
        return if (process.exitValue() == 0) output else ""
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
                throw AssertionError("The editing tab could not prepare its local tools: ${Bus.snapshot().takeLast(1500)}")
            }
            Thread.sleep(100)
        }
        throw AssertionError("The editing tab did not open its WebView after preparing tools")
    }

    private fun waitForTools() {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var failure = ""
        while (System.nanoTime() < deadline) {
            val connection = URL("http://127.0.0.1:8770/api/tools").openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 3000
                connection.readTimeout = 3000
                connection.inputStream.bufferedReader().use { JSONObject(it.readText()) }
                return
            } catch (error: Exception) {
                failure = error.toString()
                Thread.sleep(100)
            } finally { connection.disconnect() }
        }
        throw AssertionError("Viewer HTTP server did not become ready: $failure")
    }

    private fun waitForDom(webView: WebView, description: String, script: () -> String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = evaluate(webView, script())
            val error = last.optString("error")
            if (error.isNotEmpty()) throw AssertionError("$description: $error; $last")
            if (last.optBoolean("ok")) return last
            Thread.sleep(100)
        }
        fail("Timed out waiting for $description: $last")
        return last
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
        return JSONObject(decoded as? String ?: throw AssertionError("Unexpected JS result: ${result.get()}"))
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
