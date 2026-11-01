package com.tagundo.elichika

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
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

/** Exercise the bundled JS in the device's real WebView, including older providers. */
@RunWith(AndroidJUnit4::class)
class MeshWebViewTest {
    @Test
    fun meshEditorLoadsAndWorksInTheInstalledWebView() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        // Instrumentation runs this test on a worker. Do not copy the payload or
        // initialize Chaquopy on the main thread just to open the editing page.
        AssetInstaller.install(context) {}
        PyServers.ensureStarted(context, context.filesDir)
        assertTrue("Embedded tool servers must start", PyServers.isStarted())
        val models = waitForTools().getJSONObject("roots").getString("models")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        preferences.edit().putBoolean("seen_guide", true).commit()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        val activity = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ) as MainActivity
        try {
            lateinit var webView: WebView
            instrumentation.runOnMainSync {
                activity.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select()
                webView = descendants(activity.findViewById(R.id.content))
                    .filterIsInstance<WebView>().first { it.visibility == View.VISIBLE }
            }
            waitForDom(webView, "Mesh Baker tool button") {
                "var b=document.querySelector('#tool-list button[data-id=\"mesh_baker\"]');" +
                    "return JSON.stringify({ok:!!b,ready:document.readyState,title:document.title});"
            }
            evaluate(webView, "document.querySelector('#tool-list button[data-id=\"mesh_baker\"]').click();return JSON.stringify({ok:true});")
            val editor = waitForDom(webView, "body-part controls and visible Save button") {
                """
                var buttons=document.querySelectorAll('#tool-form .body-part-choice');
                var expert=document.querySelector('#tool-form .expert-options');
                var save=document.querySelector('#tool-form .run-btn');
                var waist=document.getElementById('part-tab-torso');
                var rect=save?save.getBoundingClientRect():null;
                var hit=rect?document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2):null;
                var visible=!!rect&&rect.width>=44&&rect.height>=44&&rect.top>=0&&
                  rect.bottom<=window.innerHeight+1&&rect.left>=0&&rect.right<=window.innerWidth+1;
                return JSON.stringify({ok:buttons.length===8&&!!waist&&!!expert&&!!save&&visible&&
                  !save.disabled&&(hit===save||save.contains(hit)),parts:buttons.length,
                  expertOpen:expert?expert.open:true,targetSpec:!!document.querySelector('[data-name="target_spec"]'),
                  saveVisible:visible,saveEnabled:!!save&&!save.disabled});
                """.trimIndent()
            }
            assertEquals(8, editor.getInt("parts"))
            assertFalse("Expert controls should start closed", editor.getBoolean("expertOpen"))
            assertFalse("The beginner editor must not expose a target-spec text box", editor.getBoolean("targetSpec"))
            assertTrue(editor.getBoolean("saveVisible"))
            assertTrue(editor.getBoolean("saveEnabled"))
            evaluate(webView, "document.getElementById('part-tab-torso').click();return JSON.stringify({ok:true});")
            waitForDom(webView, "waist selection event handler") {
                "return JSON.stringify({ok:document.getElementById('part-tab-torso').getAttribute('aria-selected')==='true'" +
                    "&&!document.getElementById('part-card-torso').hidden});"
            }
            // A fresh official install need not have extracted any models yet.
            // Check an existing library without creating or modifying user folders.
            val modelDirectory = File(models)
            if (modelDirectory.isDirectory) {
                evaluate(webView, "document.querySelector('#tool-form [data-name=\"in_path\"]').parentNode.querySelector('button').click();return JSON.stringify({ok:true});")
                waitForDom(webView, "model-folder browser") {
                    "var picker=document.getElementById('picker');var path=document.getElementById('picker-crumb').textContent;" +
                        "return JSON.stringify({ok:!picker.classList.contains('hidden')&&path===" + JSONObject.quote(modelDirectory.canonicalPath) + ",path:path});"
                }
                evaluate(webView, "document.getElementById('picker-cancel').click();return JSON.stringify({ok:true});")
            }
            editor.put("existingModelFolderChecked", modelDirectory.isDirectory)
            println("MESH_WEBVIEW_REPORT=" + editor.toString())
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun waitForTools(): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var failure = ""
        while (System.nanoTime() < deadline) {
            val connection = URL("http://127.0.0.1:8770/api/tools").openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 3000
                connection.readTimeout = 3000
                return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            } catch (error: Exception) {
                failure = error.toString()
                Thread.sleep(100)
            } finally { connection.disconnect() }
        }
        throw AssertionError("Tool HTTP server did not become ready: $failure")
    }

    private fun waitForDom(webView: WebView, description: String, script: () -> String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = evaluate(webView, script())
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
            // Deliberately use ES5 syntax: Chromium 74 must parse the test too.
            webView.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();") {
                result.set(it)
                done.countDown()
            }
        }
        assertTrue("WebView JS callback timed out", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        return JSONObject(decoded as? String ?: throw AssertionError("Unexpected JS result: ${result.get()}"))
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
